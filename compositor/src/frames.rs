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
