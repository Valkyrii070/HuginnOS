//! Where windows open: each app's window comes back where it was and at its size (Settings › Desktop & Dock,
//! "Windows open where they were"; ~/.config/huginn/places.json), and rules for particular apps
//! (~/.config/huginn/window-rules.json, written by hand):
//!
//! ```json
//! [{"app": "org.gimp.GIMP", "maximise": true},
//!  {"app": "huginn-terminal", "size": [900, 560], "position": [40, 60]},
//!  {"app": "discord", "title": "Discord", "space": 2}]
//! ```
//! "app" is the app's id (as the window list gives it), "title" a part of the title; "space" counts from 1. Settings ›
//! Desktop & Dock › Where apps open writes them too, with "screen" (a screen's make, model and serial, its name, or
//! "main") and "ontop" (kept on top of other windows).

use std::{
    path::PathBuf,
    sync::atomic::{AtomicBool, Ordering},
};

use serde_json::{Value, json};
use smithay::{
    desktop::space::SpaceElement,
    utils::{Logical, Point, Rectangle, Size},
};

use crate::{
    shell::WindowElement,
    state::{Backend, HuginnState},
};

/// "Windows open where they were" (the shell says, with the dock's layout).
pub static REMEMBER: AtomicBool = AtomicBool::new(true);

fn dir() -> Option<PathBuf> {
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))?;
    Some(base.join("huginn"))
}

fn read(name: &str) -> Value {
    dir()
        .and_then(|d| std::fs::read_to_string(d.join(name)).ok())
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or(Value::Null)
}

#[derive(Default)]
pub struct Places {
    /// app -> where its window last was (logical, desktop)
    pub seen: std::collections::HashMap<String, Rectangle<i32, Logical>>,
    pub dirty: bool,
    pub loaded: bool,
}

/// The first rule for this app and title, if any.
fn rule(app: &str, title: &str) -> Option<Value> {
    let rules = read("window-rules.json");
    rules.as_array()?.iter().find(|r| {
        r.get("app").and_then(|a| a.as_str()).is_some_and(|a| a.eq_ignore_ascii_case(app))
            && r.get("title").and_then(|t| t.as_str()).is_none_or(|t| title.contains(t))
    }).cloned()
}

impl<B: Backend + 'static> HuginnState<B> {
    /// A window being put on the screen for the first time: its rule, else where the app's window last was.
    /// Returns where it goes (its top-left), or None to leave it to the usual placing.
    pub fn place_from_memory(&mut self, window: &WindowElement) -> Option<Point<i32, Logical>> {
        let (title, app) = crate::shell::window_names(window);
        let id = crate::huginn::window_id(window);
        if let Some(r) = rule(&app, &title) {
            let n = |k: &str, i: usize| r.get(k).and_then(|v| v.get(i)).and_then(|v| v.as_i64()).map(|v| v as i32);
            if let Some(space) = r.get("space").and_then(|v| v.as_u64()).filter(|s| *s >= 1) {
                let to = space - 1;
                self.handle.insert_idle(move |state| state.space_do(&format!("move:{id}:{to}")));
            }
            if r.get("ontop").and_then(|v| v.as_bool()) == Some(true) {
                let w = window.clone();
                self.handle.insert_idle(move |state| state.set_above(&w, true));
            }
            // the screen it opens on (when that screen is here)
            let area = r.get("screen").and_then(|v| v.as_str()).and_then(|want| self.rule_screen(want));
            if r.get("maximise").and_then(|v| v.as_bool()) == Some(true) {
                if let Some(t) = window.0.toplevel().cloned() {
                    if let Some(a) = area {
                        self.space.map_element(window.clone(), a.loc, false);
                    }
                    let state: &mut Self = self;
                    smithay::wayland::shell::xdg::XdgShellHandler::maximize_request(state, t);
                    // where the filled window is (place_window takes the window's own offset back off)
                    return self.space.element_location(window).map(|l| l + window.geometry().loc);
                }
            }
            if let (Some(w), Some(h)) = (n("size", 0), n("size", 1)) {
                self.configure_size(window, Size::from((w.max(200), h.max(120))), false);
            }
            if let (Some(x), Some(y)) = (n("position", 0), n("position", 1)) {
                let at = Point::from((x, y));
                return Some(match area {
                    Some(a) => a.loc + at,                       // a place on that screen
                    None => self.on_a_screen(at),
                });
            }
            if let Some(a) = area {                              // the middle of that screen
                let size = window.geometry().size;
                return Some(Point::from((a.loc.x + (a.size.w - size.w).max(0) / 2, a.loc.y + (a.size.h - size.h).max(0) / 2)));
            }
            return None;
        }
        if !REMEMBER.load(Ordering::Relaxed) {
            return None;
        }
        self.load_places();
        let was = *self.huginn.places.seen.get(&app)?;
        // a second window of the app goes beside the first, not on it
        let taken = self.space.elements().filter(|w| *w != window).any(|w| crate::shell::window_names(w).1 == app);
        // no bigger than the room its screen has now (a smaller screen, or a taller bar, since)
        let room = self
            .space
            .outputs()
            .find(|o| self.space.output_geometry(o).is_some_and(|g| g.contains(was.loc)))
            .or_else(|| self.space.outputs().next())
            .map(|o| smithay::desktop::layer_map_for_output(o).non_exclusive_zone().size);
        let size = match room {
            Some(r) if r.w > 0 && r.h > 0 => Size::from((was.size.w.min(r.w), was.size.h.min(r.h))),
            _ => was.size,
        };
        self.configure_size(window, size, false);
        let at = if taken { was.loc + Point::from((32, 32)) } else { was.loc };
        Some(self.on_a_screen(at))
    }

    /// A rule's screen, if it's here: its make, model and serial (displays::key), its name, or "main". Its work area.
    fn rule_screen(&self, want: &str) -> Option<Rectangle<i32, Logical>> {
        let main = crate::displays::main_name();
        let o = self.space.outputs().find(|o| {
            crate::displays::mirror_of(o).is_none()
                && (crate::displays::key(o) == want || o.name() == want || (want == "main" && main.as_deref().is_none_or(|m| m == o.name())))
        })?;
        let geo = self.space.output_geometry(o)?;
        let zone = smithay::desktop::layer_map_for_output(o).non_exclusive_zone();
        Some(Rectangle::new(geo.loc + zone.loc, zone.size))
    }

    /// A point kept on one of the screens (a screen that's gone since).
    fn on_a_screen(&self, at: Point<i32, Logical>) -> Point<i32, Logical> {
        let inside = self.space.outputs().any(|o| self.space.output_geometry(o).is_some_and(|g| g.contains(at)));
        if inside {
            return at;
        }
        self.space.outputs().next().and_then(|o| self.space.output_geometry(o)).map_or(at, |g| g.loc + Point::from((60, 60)))
    }

    fn load_places(&mut self) {
        if self.huginn.places.loaded {
            return;
        }
        self.huginn.places.loaded = true;
        if let Some(all) = read("places.json").as_object() {
            for (app, r) in all {
                let n = |i: usize| r.get(i).and_then(|v| v.as_i64()).unwrap_or(0) as i32;
                if n(2) > 0 && n(3) > 0 {
                    self.huginn.places.seen.insert(app.clone(), Rectangle::new((n(0), n(1)).into(), (n(2), n(3)).into()));
                }
            }
        }
    }

    /// Now and then: where each app's free-standing window is (not snapped, filled or full screen), saved when it
    /// changed.
    pub fn note_places(&mut self) {
        if !REMEMBER.load(Ordering::Relaxed) {
            return;
        }
        self.load_places();
        let mut changed = false;
        let windows: Vec<WindowElement> = self.space.elements().cloned().collect();
        for w in windows {
            let id = crate::huginn::window_id(&w);
            if self.huginn.wm.snapped.contains_key(&id) {
                continue;
            }
            let maxed = w.0.toplevel().is_some_and(|t| {
                t.with_pending_state(|s| {
                    s.states.contains(smithay::reexports::wayland_protocols::xdg::shell::server::xdg_toplevel::State::Maximized)
                        || s.states.contains(smithay::reexports::wayland_protocols::xdg::shell::server::xdg_toplevel::State::Fullscreen)
                })
            });
            if maxed {
                continue;
            }
            let Some(loc) = self.space.element_location(&w) else { continue };
            let g = w.geometry();
            if g.size.w < 120 || g.size.h < 80 {
                continue;
            }
            let app = crate::shell::window_names(&w).1;
            if app.is_empty() {
                continue;
            }
            let rect = Rectangle::new(loc + g.loc, g.size);
            if self.huginn.places.seen.get(&app) != Some(&rect) {
                self.huginn.places.seen.insert(app, rect);
                changed = true;
            }
        }
        if changed {
            self.huginn.places.dirty = true;
        }
        if self.huginn.places.dirty {
            self.huginn.places.dirty = false;
            let all: serde_json::Map<String, Value> = self
                .huginn
                .places
                .seen
                .iter()
                .map(|(a, r)| (a.clone(), json!([r.loc.x, r.loc.y, r.size.w, r.size.h])))
                .collect();
            if let Some(d) = dir() {
                let _ = std::fs::create_dir_all(&d);
                let _ = std::fs::write(d.join("places.json"), serde_json::to_string(&Value::Object(all)).unwrap_or_default());
            }
        }
    }
}
