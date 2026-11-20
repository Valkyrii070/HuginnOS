//! GameMode by itself (Settings › Desktop & Dock › "Game mode for games", on unless turned off): while a game
//! fills a screen, Feral's GameMode (gamemoded) is told it's playing, as `gamemoderun` in its launch options would:
//! the processor at full speed (the polkit rule 50-huginn-gamemode.rules lets it), the screen kept awake. No launch
//! options needed, and it works for Steam from Flathub too, whose sandbox can't see the system's gamemoderun.
//!
//! A game is a window filling a screen that is Proton's (an X11 class "steam_app_…"), was started by Steam
//! (SteamGameId or SteamAppId in its environment), is a Windows program (a class or name ending in ".exe"), or asked
//! to tear (tearing.rs). GameMode is told over the session bus, by process id, from a thread of its own (starting
//! gamemoded can take a moment, and the drawing mustn't wait); X11 windows' ids come from the X server (XRes), so a
//! game in Flatpak's own process numbering still counts. A game that ends is let go (gamemoded also notices).
//!
//! While any game plays, the computer's power mode is also held at Performance (power-profiles-daemon's
//! HoldProfile, on the system bus; let go when the last game stops, or by the daemon if Huginn goes), where the
//! computer has one (a desktop with amd-pstate does). The mode the person chose comes back after.

use std::{
    collections::BTreeSet,
    sync::{
        Mutex, OnceLock,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
};

/// Settings: on unless turned off (dock_layout's "gamemode").
pub static ALLOWED: AtomicBool = AtomicBool::new(true);

static WORKER: OnceLock<Mutex<mpsc::Sender<BTreeSet<u32>>>> = OnceLock::new();
static LAST: Mutex<BTreeSet<u32>> = Mutex::new(BTreeSet::new());

/// Whether a window looks like a game: its X11 class (or app id), its title, and its process's environment.
pub fn looks_like_game(class: &str, title: &str, pid: u32, tearing: bool) -> bool {
    if tearing {
        return true;
    }
    let class = class.to_ascii_lowercase();
    if class.starts_with("steam_app_") || class.ends_with(".exe") || title.to_ascii_lowercase().ends_with(".exe") {
        return true;
    }
    if pid > 1 {
        if let Ok(env) = std::fs::read(format!("/proc/{pid}/environ")) {
            return env
                .split(|b| *b == 0)
                .any(|v| (v.starts_with(b"SteamGameId=") || v.starts_with(b"SteamAppId=")) && !v.ends_with(b"=0") && !v.ends_with(b"="));
        }
    }
    false
}

/// The games filling screens now (their process ids). Called every couple of seconds; tells GameMode only when
/// the set changes.
/// $XDG_RUNTIME_DIR/huginn/game-playing, there while a game fills a screen (whether or not GameMode is on), so the
/// rest of the session can make room for it: the local AI model is unloaded (huginn_ai.py), update downloads wait
/// (huginn_updates.py) and the shell lets go of its caches (huginn_system.py). Written only when it changes.
pub fn mark(playing: bool) {
    static LAST_MARK: Mutex<Option<bool>> = Mutex::new(None);
    let Ok(mut last) = LAST_MARK.lock() else { return };
    if *last == Some(playing) {
        return;
    }
    *last = Some(playing);
    let Some(dir) = std::env::var_os("XDG_RUNTIME_DIR").map(|d| std::path::PathBuf::from(d).join("huginn")) else { return };
    let file = dir.join("game-playing");
    if playing {
        let _ = std::fs::create_dir_all(&dir);
        let _ = std::fs::write(&file, b"desktop\n");
    } else {
        let _ = std::fs::remove_file(&file);
    }
}

pub fn playing(pids: BTreeSet<u32>) {
    let pids = if ALLOWED.load(Ordering::Relaxed) { pids } else { BTreeSet::new() };
    {
        let Ok(mut last) = LAST.lock() else { return };
        if *last == pids {
            return;
        }
        *last = pids.clone();
    }
    let tx = WORKER.get_or_init(|| {
        let (tx, rx) = mpsc::channel();
        let _ = std::thread::Builder::new().name("gamemode".into()).spawn(move || worker(rx));
        Mutex::new(tx)
    });
    if let Ok(tx) = tx.lock() {
        let _ = tx.send(pids);
    }
}

fn worker(rx: mpsc::Receiver<BTreeSet<u32>>) {
    let me = std::process::id() as i32;
    let mut told: BTreeSet<u32> = BTreeSet::new();
    let mut bus: Option<zbus::blocking::Connection> = None;
    let mut power = Power::default();
    while let Ok(mut want) = rx.recv() {
        while let Ok(newer) = rx.try_recv() {
            want = newer;
        }
        power.playing(!want.is_empty());
        if bus.is_none() {
            bus = zbus::blocking::Connection::session().ok();
        }
        let Some(conn) = bus.as_ref() else { continue };
        for pid in told.difference(&want).copied().collect::<Vec<_>>() {
            let _ = call(conn, "UnregisterGameByPID", me, pid as i32);
            told.remove(&pid);
            tracing::info!(pid, "GameMode: the game stopped filling the screen");
        }
        for pid in want.difference(&told).copied().collect::<Vec<_>>() {
            match call(conn, "RegisterGameByPID", me, pid as i32) {
                Ok(0) => tracing::info!(pid, "GameMode on for a game filling the screen"),
                Ok(code) => tracing::warn!(pid, code, "GameMode didn't take the game"),
                Err(err) => {
                    tracing::warn!(?err, "GameMode isn't there to ask");
                    bus = None;
                    break;
                }
            }
            told.insert(pid);
        }
    }
}

/// The Performance power mode held while games play (power-profiles-daemon).
#[derive(Default)]
struct Power {
    bus: Option<zbus::blocking::Connection>,
    cookie: Option<(&'static str, &'static str, u32)>,
}

impl Power {
    const NAMES: [(&'static str, &'static str); 2] = [
        ("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles"),
        ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles"),
    ];

    fn playing(&mut self, on: bool) {
        if on == self.cookie.is_some() {
            return;
        }
        if self.bus.is_none() {
            self.bus = zbus::blocking::Connection::system().ok();
        }
        let Some(bus) = self.bus.as_ref() else { return };
        if on {
            for (name, path) in Self::NAMES {
                let held = bus
                    .call_method(Some(name), path, Some(name), "HoldProfile", &("performance", "A game is playing", "org.huginn.Games"))
                    .and_then(|reply| reply.body().deserialize::<u32>());
                match held {
                    Ok(cookie) => {
                        tracing::info!("Performance power mode while a game plays");
                        self.cookie = Some((name, path, cookie));
                        return;
                    }
                    // no Performance mode on this computer, or the daemon under its other name
                    Err(err) => tracing::debug!(?err, name, "power mode not held"),
                }
            }
        } else if let Some((name, path, cookie)) = self.cookie.take() {
            let _ = bus.call_method(Some(name), path, Some(name), "ReleaseProfile", &(cookie,));
            tracing::info!("power mode back as it was");
        }
    }
}

fn call(conn: &zbus::blocking::Connection, method: &str, me: i32, pid: i32) -> zbus::Result<i32> {
    let reply = conn.call_method(
        Some("com.feralinteractive.GameMode"),
        "/com/feralinteractive/GameMode",
        Some("com.feralinteractive.GameMode"),
        method,
        &(me, pid),
    )?;
    reply.body().deserialize::<i32>()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn games_are_told_apart() {
        assert!(looks_like_game("steam_app_1091500", "Cyberpunk 2077", 0, false));
        assert!(looks_like_game("eldenring.exe", "ELDEN RING", 0, false));
        assert!(looks_like_game("", "Game.exe", 0, false));
        assert!(looks_like_game("org.mpv.mpv", "film", 0, true));
        assert!(!looks_like_game("org.mpv.mpv", "film", 0, false));
        assert!(!looks_like_game("huginn-video", "Holiday", std::process::id(), false));
    }
}
