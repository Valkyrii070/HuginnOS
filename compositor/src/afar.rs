//! Keys and the mouse from afar: Screen Sharing's viewer (rdp.rs) and Phone's remote control (huginn_phoned.py,
//! over the bus: `PointerBy`, `PointerButton`, `Scroll`, `Key`, `TypeText`). Everything goes through the same paths
//! as a real keyboard and mouse (`Remote` is an input backend of its own), so shortcuts, sticky keys and the rest
//! behave as at the computer. A text-console switch from afar is ignored (`process_common_key_action` leaves it to
//! the console's own keyboard).
//!
//! Typing characters (a phone's on-screen keyboard sends characters, not keys): into a text field they go whole,
//! the compositor acting as the field's input method (text-input: Qt and GTK apps take it), which keeps them in
//! order and takes any character; elsewhere each is typed with the keys the layout in use has for it (Shift and/or
//! AltGr as it needs), and one it has none for waits a moment for a text field. Enter, Tab, Backspace and Escape are
//! always keys. The compositor is the input method while anything comes from afar, and a minute after.

use std::{
    path::PathBuf,
    time::{Duration, Instant},
};

use smithay::{
    backend::input::{
        self, Axis, AxisRelativeDirection, AxisSource, ButtonState, DeviceCapability, InputBackend, InputTime, KeyState,
        Keycode, UnusedEvent,
    },
    input::keyboard::xkb,
    utils::{Logical, Point},
    wayland::text_input::TextInputSeat,
};

use crate::state::{Backend, HuginnState};

const SHIFT: u32 = 42;
const ALTGR: u32 = 100;

/// One thing done from afar.
#[derive(Debug)]
pub enum Afar {
    /// the pointer to a place on the desktop
    To(Point<f64, Logical>),
    /// the pointer moved by so much (a phone's touchpad)
    By(f64, f64),
    /// an evdev button code, pressed or let go
    Button(u32, bool),
    /// a wheel, in 120ths of a notch: right +, down +
    Wheel(f64, f64),
    /// smooth scrolling, in pixels: right +, down +
    Scroll(f64, f64),
    /// an evdev key code, pressed or let go
    Key(u32, bool),
    /// characters to type
    Text(String),
}

impl<B: Backend + 'static> HuginnState<B> {
    pub fn afar(&mut self, ev: Afar) {
        self.touched();
        // (as the input method from the start, the text field the person goes to already takes text when they type)
        let ti = self.seat.text_input().clone();
        if !ti.compositor_input_method() {
            ti.set_compositor_input_method(true);
        }
        self.huginn.afar_im = Some(Instant::now());
        match ev {
            Afar::To(pos) => self.pointer_to(pos, InputTime::now()),
            Afar::By(dx, dy) => {
                if !(dx.is_finite() && dy.is_finite()) {
                    return;
                }
                let at = self.pointer.current_location();
                let Some(bounds) = self.space.outputs().filter_map(|o| self.space.output_geometry(o)).reduce(|a, b| a.merge(b)) else { return };
                let x = (at.x + dx.clamp(-4000.0, 4000.0)).clamp(f64::from(bounds.loc.x), f64::from(bounds.loc.x + bounds.size.w - 1));
                let y = (at.y + dy.clamp(-4000.0, 4000.0)).clamp(f64::from(bounds.loc.y), f64::from(bounds.loc.y + bounds.size.h - 1));
                self.pointer_to(Point::from((x, y)), InputTime::now());
            }
            Afar::Button(code, down) => {
                if (0x110..0x120).contains(&code) {
                    self.on_pointer_button::<Remote>(RemoteButton { code, down });
                }
            }
            Afar::Wheel(h, v) => self.on_pointer_axis::<Remote>(RemoteAxis { h, v, wheel: true }),
            Afar::Scroll(h, v) => {
                if h.is_finite() && v.is_finite() {
                    self.on_pointer_axis::<Remote>(RemoteAxis { h: h.clamp(-2000.0, 2000.0), v: v.clamp(-2000.0, 2000.0), wheel: false });
                }
            }
            Afar::Key(code, down) => {
                if (1..0x300).contains(&code) {
                    self.key_afar(code, down);
                }
            }
            Afar::Text(text) => {
                let mut run = String::new();
                for ch in text.chars().take(2000) {
                    if matches!(ch, '\n' | '\r' | '\t' | '\u{8}' | '\u{1b}' | '\u{7f}') {
                        self.put_text(&std::mem::take(&mut run));
                        self.type_char(ch);
                    } else if !ch.is_control() {
                        run.push(ch); // (other control characters, a NUL from a viewer that couldn't tell: nothing)
                    }
                }
                self.put_text(&run);
            }
        }
    }

    fn key_afar(&mut self, code: u32, down: bool) {
        let action = self.keyboard_key_to_action::<Remote>(RemoteKey { code, down });
        self.process_common_key_action(action);
    }

    /// Characters: into the focused text field whole if there is one; else with keys, and those no key makes
    /// waiting a moment for a field.
    fn put_text(&mut self, text: &str) {
        if text.is_empty() || self.commit_now(text) {
            return;
        }
        let mut no_key = String::new();
        for ch in text.chars() {
            if self.type_char(ch) {
                self.commit_text(&std::mem::take(&mut no_key));
            } else {
                no_key.push(ch);
            }
        }
        self.commit_text(&no_key);
    }

    /// Into the text field that's taking text now, if one is.
    fn commit_now(&mut self, text: &str) -> bool {
        let ti = self.seat.text_input().clone();
        let mut sent = false;
        ti.with_active_text_input(|t, _| {
            if !sent {
                t.commit_string(Some(text.to_owned()));
                sent = true;
            }
        });
        if sent {
            ti.done(false);
        }
        sent
    }

    /// Characters no key makes, into the focused app's text field (text-input), the compositor as its input method.
    /// If the field isn't taking text yet (it hears that it can as this starts), they wait a moment.
    fn commit_text(&mut self, text: &str) {
        if text.is_empty() {
            return;
        }
        let ti = self.seat.text_input().clone();
        if !ti.compositor_input_method() {
            ti.set_compositor_input_method(true);
        }
        self.huginn.afar_im = Some(Instant::now());
        let waiting = self.huginn.afar_text.take().map(|(t, _)| t).unwrap_or_default() + text;
        let mut sent = false;
        ti.with_active_text_input(|t, _| {
            if !sent {
                t.commit_string(Some(waiting.clone()));
                sent = true;
            }
        });
        if sent {
            ti.done(false);
        } else {
            self.huginn.afar_text = Some((waiting, Instant::now()));
        }
    }

    /// Now and then: characters waiting for a text field go in once it takes them (or are dropped after 2 s); the
    /// compositor stops being the input method a minute after the last characters from afar.
    pub fn afar_tick(&mut self) {
        if let Some((text, since)) = self.huginn.afar_text.take() {
            if since.elapsed() < Duration::from_secs(2) {
                let ti = self.seat.text_input().clone();
                let mut sent = false;
                ti.with_active_text_input(|t, _| {
                    if !sent {
                        t.commit_string(Some(text.clone()));
                        sent = true;
                    }
                });
                if sent {
                    ti.done(false);
                    self.huginn.afar_text = None;
                } else {
                    self.huginn.afar_text = Some((text, since));
                }
            }
        }
        if self.huginn.afar_im.is_some_and(|t| t.elapsed() > Duration::from_secs(60)) && self.huginn.afar_text.is_none() {
            self.huginn.afar_im = None;
            self.seat.text_input().set_compositor_input_method(false);
        }
    }

    /// One character, typed with the keys the layout in use has for it; false when it has none.
    fn type_char(&mut self, ch: char) -> bool {
        let simple = match ch {
            '\n' | '\r' => Some(28), // Enter
            '\t' => Some(15),
            '\u{8}' => Some(14), // Backspace
            '\u{1b}' => Some(1), // Escape
            '\u{7f}' => Some(111), // Delete
            _ => None,
        };
        let (code, level) = match simple {
            Some(code) => (code, 0),
            None => {
                let Some(found) = self.key_for(ch) else { return false };
                found
            }
        };
        let mods: &[u32] = match level {
            0 => &[],
            1 => &[SHIFT],
            2 => &[ALTGR],
            _ => &[SHIFT, ALTGR],
        };
        for &m in mods {
            self.key_afar(m, true);
        }
        self.key_afar(code, true);
        self.key_afar(code, false);
        for &m in mods.iter().rev() {
            self.key_afar(m, false);
        }
        true
    }

    /// The evdev key and shift level that make `ch` in the layout in use (the lowest level that does).
    fn key_for(&mut self, ch: char) -> Option<(u32, u32)> {
        let want = xkb::utf32_to_keysym(ch as u32);
        if want.raw() == 0 {
            return None;
        }
        let keyboard = self.seat.get_keyboard()?;
        keyboard.with_xkb_state(self, |ctx| {
            let xkb = ctx.xkb().lock().ok()?;
            // SAFETY: the keymap is only looked at, inside this call, while the lock is held
            let keymap = unsafe { xkb.keymap() };
            let layout = xkb.active_layout().0;
            let mut best: Option<(u32, u32)> = None;
            for raw in keymap.min_keycode().raw()..=keymap.max_keycode().raw() {
                let kc = xkb::Keycode::new(raw);
                for level in 0..keymap.num_levels_for_key(kc, layout).min(4) {
                    if keymap.key_get_syms_by_level(kc, layout, level) == [want] && raw >= 8 && best.is_none_or(|(_, l)| level < l) {
                        best = Some((raw - 8, level));
                    }
                }
            }
            best
        })
    }
}

// --------------------------------------------------------------------------------- the input backend
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct RemoteDevice;

impl input::Device for RemoteDevice {
    fn id(&self) -> String {
        "afar".into()
    }
    fn name(&self) -> String {
        "Keys and mouse from afar".into()
    }
    fn has_capability(&self, capability: DeviceCapability) -> bool {
        matches!(capability, DeviceCapability::Keyboard | DeviceCapability::Pointer)
    }
    fn usb_id(&self) -> Option<(u32, u32)> {
        None
    }
    fn syspath(&self) -> Option<PathBuf> {
        None
    }
}

#[derive(Debug)]
pub struct RemoteKey {
    code: u32,
    down: bool,
}

#[derive(Debug)]
pub struct RemoteButton {
    code: u32,
    down: bool,
}

#[derive(Debug)]
pub struct RemoteAxis {
    h: f64,
    v: f64,
    /// a wheel's notches (in 120ths), or smooth scrolling (in pixels)
    wheel: bool,
}

macro_rules! remote_event {
    ($t:ty) => {
        impl input::Event<Remote> for $t {
            fn time(&self) -> InputTime {
                InputTime::now()
            }
            fn device(&self) -> RemoteDevice {
                RemoteDevice
            }
        }
    };
}
remote_event!(RemoteKey);
remote_event!(RemoteButton);
remote_event!(RemoteAxis);

impl input::KeyboardKeyEvent<Remote> for RemoteKey {
    fn key_code(&self) -> Keycode {
        Keycode::from(self.code + 8)
    }
    fn state(&self) -> KeyState {
        if self.down { KeyState::Pressed } else { KeyState::Released }
    }
    fn count(&self) -> u32 {
        u32::from(self.down)
    }
}

impl input::PointerButtonEvent<Remote> for RemoteButton {
    fn button_code(&self) -> u32 {
        self.code
    }
    fn state(&self) -> ButtonState {
        if self.down { ButtonState::Pressed } else { ButtonState::Released }
    }
}

impl input::PointerAxisEvent<Remote> for RemoteAxis {
    fn amount(&self, axis: Axis) -> Option<f64> {
        let n = if axis == Axis::Horizontal { self.h } else { self.v };
        (n != 0.0).then_some(if self.wheel { n * 15.0 / 120.0 } else { n })
    }
    fn amount_v120(&self, axis: Axis) -> Option<f64> {
        let n = if axis == Axis::Horizontal { self.h } else { self.v };
        (self.wheel && n != 0.0).then_some(n)
    }
    fn source(&self) -> AxisSource {
        if self.wheel { AxisSource::Wheel } else { AxisSource::Finger }
    }
    fn relative_direction(&self, _axis: Axis) -> AxisRelativeDirection {
        AxisRelativeDirection::Identical
    }
}

/// Keys and the mouse from afar, as an input backend of their own.
#[derive(Debug)]
pub struct Remote;

impl InputBackend for Remote {
    type Device = RemoteDevice;
    type KeyboardKeyEvent = RemoteKey;
    type PointerAxisEvent = RemoteAxis;
    type PointerButtonEvent = RemoteButton;
    type PointerMotionEvent = UnusedEvent;
    type PointerMotionAbsoluteEvent = UnusedEvent;
    type GestureSwipeBeginEvent = UnusedEvent;
    type GestureSwipeUpdateEvent = UnusedEvent;
    type GestureSwipeEndEvent = UnusedEvent;
    type GesturePinchBeginEvent = UnusedEvent;
    type GesturePinchUpdateEvent = UnusedEvent;
    type GesturePinchEndEvent = UnusedEvent;
    type GestureHoldBeginEvent = UnusedEvent;
    type GestureHoldEndEvent = UnusedEvent;
    type TouchDownEvent = UnusedEvent;
    type TouchUpEvent = UnusedEvent;
    type TouchMotionEvent = UnusedEvent;
    type TouchCancelEvent = UnusedEvent;
    type TouchFrameEvent = UnusedEvent;
    type TabletToolAxisEvent = UnusedEvent;
    type TabletToolProximityEvent = UnusedEvent;
    type TabletToolTipEvent = UnusedEvent;
    type TabletToolButtonEvent = UnusedEvent;
    type SwitchToggleEvent = UnusedEvent;
    type SpecialEvent = UnusedEvent;
}
