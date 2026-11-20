//! Frame times, for the frame-time display (Super+Alt+F, Settings › Displays): for each screen, when each frame was
//! shown and how long drawing it took. Kept for the last few hundred frames; the shell asks for the numbers over the
//! bus (`org.huginn.Compositor.FrameStats`) about twice a second while the display is on.

use std::{
    collections::{HashMap, VecDeque},
    sync::Mutex,
    time::{Duration, Instant},
};

const KEEP: usize = 600;

#[derive(Default)]
struct Screen {
    hz: f64,
    shown: VecDeque<Instant>,
    drawn: VecDeque<(Instant, f64)>,
}

static SCREENS: Mutex<Option<HashMap<String, Screen>>> = Mutex::new(None);

fn with<F: FnOnce(&mut Screen)>(name: &str, f: F) {
    if let Ok(mut all) = SCREENS.lock() {
        f(all.get_or_insert_with(HashMap::new).entry(name.to_string()).or_default());
    }
}

/// A frame reached the screen (its vblank).
pub fn shown(name: &str, hz: f64) {
    with(name, |s| {
        s.hz = hz;
        s.shown.push_back(Instant::now());
        while s.shown.len() > KEEP {
            s.shown.pop_front();
        }
    });
}

/// A frame was drawn, taking this long.
pub fn drawn(name: &str, took: Duration) {
    with(name, |s| {
        s.drawn.push_back((Instant::now(), took.as_secs_f64() * 1000.0));
        while s.drawn.len() > KEEP {
            s.drawn.pop_front();
        }
    });
}

/// The last second, per screen, as JSON: [{"screen", "hz", "fps", "frameMs" (the average time between frames),
/// "worstMs", "late" (frames that took over one and a half refreshes), "drawMs", "drawWorstMs"}].
pub fn report() -> String {
    let now = Instant::now();
    let second = Duration::from_secs(1);
    let mut rows = Vec::new();
    if let Ok(all) = SCREENS.lock() {
        let mut names: Vec<&String> = all.as_ref().map(|a| a.keys().collect()).unwrap_or_default();
        names.sort();
        for name in names {
            let s = &all.as_ref().unwrap()[name];
            let recent: Vec<&Instant> = s.shown.iter().filter(|t| now.duration_since(**t) <= second).collect();
            let gaps: Vec<f64> = recent.windows(2).map(|w| w[1].duration_since(*w[0]).as_secs_f64() * 1000.0).collect();
            let period = if s.hz > 0.0 { 1000.0 / s.hz } else { 16.7 };
            let draws: Vec<f64> = s.drawn.iter().filter(|(t, _)| now.duration_since(*t) <= second).map(|(_, ms)| *ms).collect();
            let avg = |v: &[f64]| if v.is_empty() { 0.0 } else { v.iter().sum::<f64>() / v.len() as f64 };
            let worst = |v: &[f64]| v.iter().cloned().fold(0.0, f64::max);
            rows.push(serde_json::json!({
                "screen": name, "hz": (s.hz * 10.0).round() / 10.0, "fps": recent.len(),
                "frameMs": (avg(&gaps) * 100.0).round() / 100.0, "worstMs": (worst(&gaps) * 100.0).round() / 100.0,
                "late": gaps.iter().filter(|g| **g > period * 1.5).count(),
                "drawMs": (avg(&draws) * 100.0).round() / 100.0, "drawWorstMs": (worst(&draws) * 100.0).round() / 100.0,
            }));
        }
    }
    serde_json::Value::Array(rows).to_string()
}

// ---------------------------------------------------------------------------------------------------------------
// The game stats overlay (Super+Alt+G): the frames of the window a game is playing in, counted as it hands them over
// (each commit of its surface), so the rate is the game's own: above the screen's Hz when it tears, its own
// stutter when it has one. The window is the one filling a screen (fullscreen), else the focused one.

#[derive(Default)]
struct Game {
    surface: Option<smithay::reexports::wayland_server::backend::ObjectId>,
    app: String,
    full: bool,
    frames: VecDeque<Instant>,
}

static GAMES: Mutex<Option<HashMap<String, Game>>> = Mutex::new(None);

/// Which window's frames to count on each screen (the compositor's tick says, every two seconds).
pub fn watch(screen: &str, surface: Option<smithay::reexports::wayland_server::backend::ObjectId>, app: &str, full: bool) {
    if let Ok(mut all) = GAMES.lock() {
        let g = all.get_or_insert_with(HashMap::new).entry(screen.to_string()).or_default();
        if g.surface != surface {
            g.frames.clear();
        }
        g.surface = surface;
        g.app = app.to_string();
        g.full = full;
    }
}

/// A surface handed over a frame (shell/mod.rs: commit).
pub fn committed(surface: &smithay::reexports::wayland_server::backend::ObjectId) {
    if let Ok(mut all) = GAMES.lock() {
        if let Some(all) = all.as_mut() {
            for g in all.values_mut() {
                if g.surface.as_ref() == Some(surface) {
                    let now = Instant::now();
                    g.frames.push_back(now);
                    while g.frames.len() > 2000 || g.frames.front().is_some_and(|t| now.duration_since(*t) > Duration::from_secs(2)) {
                        g.frames.pop_front();
                    }
                }
            }
        }
    }
}

/// Each screen's watched window: its name, whether it fills the screen, its frames over the last second, the
/// average and longest gap between them (ms), as JSON.
pub fn game_report() -> String {
    let now = Instant::now();
    let mut rows = Vec::new();
    if let Ok(all) = GAMES.lock() {
        if let Some(all) = all.as_ref() {
            let mut names: Vec<&String> = all.keys().collect();
            names.sort();
            for name in names {
                let g = &all[name];
                if g.surface.is_none() {
                    continue;
                }
                let recent: Vec<&Instant> = g.frames.iter().filter(|t| now.duration_since(**t) <= Duration::from_secs(1)).collect();
                let gaps: Vec<f64> = recent.windows(2).map(|w| w[1].duration_since(*w[0]).as_secs_f64() * 1000.0).collect();
                let avg = if gaps.is_empty() { 0.0 } else { gaps.iter().sum::<f64>() / gaps.len() as f64 };
                let worst = gaps.iter().cloned().fold(0.0, f64::max);
                rows.push(serde_json::json!({
                    "screen": name, "app": g.app, "full": g.full, "fps": recent.len(),
                    "frameMs": (avg * 10.0).round() / 10.0, "worstMs": (worst * 10.0).round() / 10.0,
                }));
            }
        }
    }
    serde_json::Value::Array(rows).to_string()
}
