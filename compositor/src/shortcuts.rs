//! Keyboard shortcuts: Huginn's own (changed or turned off in Settings › Keyboard shortcuts) and the person's own,
//! each opening an app or running a command. Kept in `~/.config/huginn/shortcuts.json`:
//!
//! ```json
//! {"keys": {"files": "Super+E", "lock": ""}, "own": [{"keys": "Super+G", "run": "steam", "name": "Steam"}]}
//! ```
//!
//! An action missing from "keys" has its default; "" turns it off. Keys read like "Super+Shift+S": Ctrl, Alt, Shift
//! and Super, then a key by its xkb name ("E", "Left", "period", "F4", "Print"). A key is matched as it is without
//! Shift (and in the Latin layout, for other alphabets), so Super+. is the same key with Shift held or not.
//! What stays fixed: Super and Alt on their own, Super+1…9, Alt+Tab, the text consoles and the hardware keys.

use std::sync::RwLock;
use std::sync::atomic::{AtomicBool, Ordering};

use xkbcommon::xkb::{self, Keysym};

/// Huginn's own shortcuts and their keys out of the box ("|" between more than one).
pub const DEFAULTS: &[(&str, &str)] = &[
    ("search", "Super+Space"),
    ("lock", "Super+L"),
    ("today", "Super+T"),
    ("clipboard", "Super+V"),
    ("emoji", "Super+period"),
    ("overview", "Super+Tab"),
    ("desktop", "Super+D"),
    ("files", "Super+E"),
    ("settings", "Super+I"),
    ("terminal", "Ctrl+Alt+T"),
    ("space-left", "Super+Ctrl+Left"),
    ("space-right", "Super+Ctrl+Right"),
    ("take-left", "Super+Shift+Left"),
    ("take-right", "Super+Shift+Right"),
    ("screen-left", "Super+Alt+Left"),
    ("screen-right", "Super+Alt+Right"),
    ("snap-left", "Super+Left"),
    ("snap-right", "Super+Right"),
    ("snap-up", "Super+Up"),
    ("snap-down", "Super+Down"),
    ("close", "Alt+F4"),
    ("screenshot", "Print"),
    ("screenshot-choose", "Super+Shift+S|Shift+Print"),
    ("zoom-in", "Super+equal|Super+plus|Super+KP_Add"),
    ("zoom-out", "Super+minus|Super+KP_Subtract"),
    ("zoom-reset", "Super+0|Super+KP_0"),
];

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Combo {
    pub ctrl: bool,
    pub alt: bool,
    pub shift: bool,
    pub logo: bool,
    pub key: u32,
}

#[derive(Clone, Debug)]
pub enum Act {
    /// One of Huginn's (DEFAULTS' names)
    Own(&'static str),
    /// The person's: a command to run (through the shell, so the dock shows it starting)
    Run(String),
}

static TABLE: RwLock<Vec<(Combo, Act)>> = RwLock::new(Vec::new());

/// Settings is listening for new keys for a shortcut: the shortcuts don't fire until it's done (or 30 s pass).
static PAUSED: AtomicBool = AtomicBool::new(false);
static PAUSED_AT: RwLock<Option<std::time::Instant>> = RwLock::new(None);

pub fn pause(on: bool) {
    PAUSED.store(on, Ordering::Relaxed);
    if let Ok(mut t) = PAUSED_AT.write() {
        *t = on.then(std::time::Instant::now);
    }
}

fn paused() -> bool {
    if !PAUSED.load(Ordering::Relaxed) {
        return false;
    }
    let fresh = PAUSED_AT.read().ok().and_then(|t| *t).is_some_and(|t| t.elapsed() < std::time::Duration::from_secs(30));
    if !fresh {
        PAUSED.store(false, Ordering::Relaxed);
    }
    fresh
}

fn lower(key: u32) -> u32 {
    if (0x41..=0x5a).contains(&key) { key + 0x20 } else { key }
}

/// "Super+Shift+S" as a key and its modifiers (None if it isn't one).
pub fn parse(text: &str) -> Option<Combo> {
    let mut c = Combo { ctrl: false, alt: false, shift: false, logo: false, key: 0 };
    let parts: Vec<&str> = text.split('+').map(str::trim).collect();
    let (key, mods) = match parts.as_slice() {
        // "Super++": the plus key itself
        [rest @ .., "", ""] => ("plus", rest),
        [rest @ .., last] => (*last, rest),
        [] => return None,
    };
    for m in mods {
        match m.to_ascii_lowercase().as_str() {
            "ctrl" | "control" => c.ctrl = true,
            "alt" => c.alt = true,
            "shift" => c.shift = true,
            "super" | "logo" | "meta" | "win" => c.logo = true,
            "" => {}
            _ => return None,
        }
    }
    let name = match key {
        "." => "period",
        "," => "comma",
        "-" => "minus",
        "=" => "equal",
        "/" => "slash",
        ";" => "semicolon",
        "'" => "apostrophe",
        "`" => "grave",
        "[" => "bracketleft",
        "]" => "bracketright",
        "\\" => "backslash",
        k => k,
    };
    let sym = xkb::keysym_from_name(name, xkb::KEYSYM_CASE_INSENSITIVE);
    if sym.raw() == 0 {
        return None;
    }
    c.key = lower(sym.raw());
    Some(c)
}

fn config_path() -> std::path::PathBuf {
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".config"));
    base.join("huginn").join("shortcuts.json")
}

/// Read the file (again): Settings asks for this after a change (org.huginn.Compositor.ReloadShortcuts).
pub fn load() {
    let saved: serde_json::Value = std::fs::read_to_string(config_path())
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or(serde_json::Value::Null);
    let mut table: Vec<(Combo, Act)> = Vec::new();
    for (name, default) in DEFAULTS {
        let keys = saved.get("keys").and_then(|k| k.get(*name)).and_then(|v| v.as_str()).unwrap_or(default);
        for one in keys.split('|').filter(|s| !s.trim().is_empty()) {
            if let Some(c) = parse(one) {
                table.push((c, Act::Own(name)));
            }
        }
    }
    if let Some(own) = saved.get("own").and_then(|o| o.as_array()) {
        for entry in own.iter().take(100) {
            let (Some(keys), Some(run)) = (entry.get("keys").and_then(|v| v.as_str()), entry.get("run").and_then(|v| v.as_str())) else {
                continue;
            };
            if run.trim().is_empty() {
                continue;
            }
            if let Some(c) = parse(keys) {
                // the person's own come first: a key they chose wins over one of Huginn's
                table.insert(0, (c, Act::Run(run.to_string())));
            }
        }
    }
    tracing::info!(shortcuts = table.len(), "Keyboard shortcuts read");
    if let Ok(mut t) = TABLE.write() {
        *t = table;
    }
}

/// What a key does with these modifiers held, if anything. `raw` is the key without Shift (smithay's
/// raw_latin_sym_or_raw_current_sym), `modified` the key as typed (for keys whose Shift level is what's named).
pub fn lookup(ctrl: bool, alt: bool, shift: bool, logo: bool, raw: Option<Keysym>, modified: Keysym) -> Option<Act> {
    if paused() {
        return None;
    }
    let table = TABLE.read().ok()?;
    let keys: Vec<u32> = raw.map(|k| lower(k.raw())).into_iter().chain(std::iter::once(lower(modified.raw()))).collect();
    table
        .iter()
        .find(|(c, _)| c.ctrl == ctrl && c.alt == alt && c.shift == shift && c.logo == logo && keys.contains(&c.key))
        .map(|(_, a)| a.clone())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses() {
        let c = parse("Super+Shift+S").unwrap();
        assert!(c.logo && c.shift && !c.ctrl && c.key == xkb::keysym_from_name("s", 0).raw());
        assert_eq!(parse("Super+.").unwrap().key, xkb::keysym_from_name("period", 0).raw());
        assert_eq!(parse("Ctrl+Alt+T").unwrap().key, xkb::keysym_from_name("t", 0).raw());
        assert!(parse("Super+Nothing").is_none());
        assert!(parse("Hyper+E").is_none());
        assert_eq!(parse("Print").unwrap().key, xkb::keysym_from_name("Print", 0).raw());
    }
}
