//! Screen Sharing: this screen over RDP, from the compositor itself, so any Remote Desktop app (Windows' own,
//! Microsoft's Windows App on a Mac or phone, FreeRDP) can see and use it while Screen Sharing is open.
//!
//! The Screen Sharing app asks over the bus (`ShareStart`: the screen, the port, the name and the one-time password,
//! and its own TLS certificate); the server (IronRDP's) runs on a thread of its own with a small tokio runtime. It
//! only takes Network Level Authentication (CredSSP): the password is proved before anything is shown. Only one
//! person at a time.
//!
//! Pictures: while sharing, each time the screen is drawn and something on it changed since the last picture (a
//! damage tracker of its own, the pointer included), it is drawn again into a buffer of its own and read back, at
//! most every 33 ms; the newest picture waits in a `watch` slot, so a slow connection skips pictures instead of
//! falling behind. IronRDP sends only the parts that differ from the last one it sent.
//!
//! Input: the server's keys and mouse come back to the event loop over a calloop channel and go through the same
//! paths as a real keyboard and mouse (`Remote` is an input backend of its own), so shortcuts, sticky keys and the
//! rest behave the same. A text console switch from afar is ignored.
//!
//! Sharing stops when the app says so, and when the app hasn't asked how it's going for 20 seconds (it closed or
//! crashed): sharing never outlives its window.

use std::{
    cell::RefCell,
    net::SocketAddr,
    num::{NonZeroU16, NonZeroUsize},
    path::PathBuf,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use ironrdp_server::{
    BitmapUpdate, ConnectionHandler, Credentials, DesktopSize, DisplayUpdate, KeyboardEvent, MouseEvent, PixelFormat,
    PostConnectionAction, RdpServer, RdpServerDisplay, RdpServerDisplayUpdates, RdpServerInputHandler, TlsIdentityCtx,
    tokio,
};
use smithay::{
    backend::{
        allocator::Fourcc,
        input::{
            self, Axis, AxisRelativeDirection, AxisSource, ButtonState, DeviceCapability, InputBackend, InputTime,
            KeyState, Keycode, UnusedEvent,
        },
        renderer::{
            Bind, Color32F, ExportMem, Offscreen, Renderer, TextureMapping, damage::OutputDamageTracker,
            element::RenderElement, gles::GlesRenderbuffer,
        },
    },
    output::Output,
    reexports::calloop::{
        RegistrationToken,
        channel::{Event as ChannelEvent, Sender as LoopSender, channel},
    },
    utils::{Logical, Point, Rectangle, Size, Transform},
};
use tracing::{info, warn};

use crate::state::{Backend, HuginnState};

/// One picture of the shared screen: B, G, R, A per pixel, rows `w * 4` bytes apart, first row first.
#[derive(Clone)]
pub struct Picture {
    pub w: u16,
    pub h: u16,
    pub bytes: bytes::Bytes,
}

type Slot = tokio::sync::watch::Sender<Option<Picture>>;

/// What the compositor keeps while sharing.
pub struct Share {
    pub output: String,
    pub port: u16,
    pub viewers: Arc<Mutex<Vec<String>>>,
    pub asked: Instant,
    stop: Option<tokio::sync::oneshot::Sender<()>>,
    input: Option<RegistrationToken>,
}

impl std::fmt::Debug for Share {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Share").field("output", &self.output).field("port", &self.port).finish()
    }
}

/// Keys and the mouse, from afar.
#[derive(Debug)]
pub enum Afar {
    /// x, y in the picture's pixels
    Move(u16, u16),
    Button(u32, bool),
    /// rotation in 1/120ths of a notch: horizontal (right +), vertical (down +)
    Scroll(f64, f64),
    /// an evdev key code
    Key(u32, bool),
}

// ------------------------------------------------------------------------------------------ the pictures
/// What the renderer keeps for one shared screen, in the output's user data.
struct Stream {
    slot: Slot,
    tracker: Option<OutputDamageTracker>,
    target: Option<GlesRenderbuffer>,
    size: Size<i32, smithay::utils::Buffer>,
    last: Option<Instant>,
}

fn stream(output: &Output) -> &RefCell<Option<Stream>> {
    output.user_data().insert_if_missing(|| RefCell::new(None::<Stream>));
    output.user_data().get::<RefCell<Option<Stream>>>().unwrap()
}

/// Whether `output` is being shared.
pub fn sharing(output: &Output) -> bool {
    stream(output).borrow().is_some()
}

/// Called after `output` is drawn: if it's being shared, a new picture when something changed (`elements` front
/// first, the pointer included).
pub fn serve<R, E>(renderer: &mut R, output: &Output, elements: &[E], clear: Color32F)
where
    R: Renderer + Offscreen<GlesRenderbuffer> + Bind<GlesRenderbuffer> + ExportMem,
    E: RenderElement<R>,
{
    let mut cell = stream(output).borrow_mut();
    let Some(s) = cell.as_mut() else { return };
    if s.last.is_some_and(|t| t.elapsed() < Duration::from_millis(33)) {
        return; // (what changed meanwhile is still damage for the next time)
    }
    let Some(size) = crate::capture::size_of(output) else { return };
    if size != s.size || s.target.is_none() {
        s.size = size;
        s.tracker = Some(OutputDamageTracker::new((size.w, size.h), output.current_scale().fractional_scale(), Transform::Flipped180));
        s.target = renderer.create_buffer(Fourcc::Argb8888, size).ok();
    }
    let (Some(tracker), Some(target)) = (s.tracker.as_mut(), s.target.as_mut()) else { return };
    let age = if s.last.is_some() { 1 } else { 0 };
    let Ok(mut fb) = renderer.bind(target) else { return };
    let damaged = match tracker.render_output(renderer, &mut fb, age, elements, clear) {
        Ok(result) => result.damage.is_some_and(|d| !d.is_empty()),
        Err(err) => {
            warn!("Screen Sharing couldn't draw the screen: {err:?}");
            false
        }
    };
    if !damaged && s.last.is_some() {
        return;
    }
    let Ok(mapping) = renderer.copy_framebuffer(&fb, Rectangle::from_size(size), Fourcc::Argb8888) else { return };
    let flipped = mapping.flipped();
    let Ok(bytes) = renderer.map_texture(&mapping) else { return };
    let stride = size.w as usize * 4;
    let mut out = Vec::with_capacity(stride * size.h as usize);
    for row in 0..size.h as usize {
        let row = if flipped { size.h as usize - 1 - row } else { row };
        match bytes.get(row * stride..(row + 1) * stride) {
            Some(line) => out.extend_from_slice(line),
            None => return,
        }
    }
    for px in out.chunks_exact_mut(4) {
        px[3] = 255; // (no see-through desktop over the wire)
    }
    s.last = Some(Instant::now());
    let _ = s.slot.send(Some(Picture { w: size.w as u16, h: size.h as u16, bytes: out.into() }));
}

// -------------------------------------------------------------------------------------------- the server
struct Display {
    size: DesktopSize,
    pictures: tokio::sync::watch::Receiver<Option<Picture>>,
}

struct Updates {
    pictures: tokio::sync::watch::Receiver<Option<Picture>>,
    size: (u16, u16),
    first: bool,
}

fn bitmap(p: &Picture) -> Option<DisplayUpdate> {
    Some(DisplayUpdate::Bitmap(BitmapUpdate {
        x: 0,
        y: 0,
        width: NonZeroU16::new(p.w)?,
        height: NonZeroU16::new(p.h)?,
        format: PixelFormat::BgrA32,
        data: p.bytes.clone(),
        stride: NonZeroUsize::new(p.w as usize * 4)?,
    }))
}

#[async_trait::async_trait]
impl RdpServerDisplay for Display {
    async fn size(&mut self) -> DesktopSize {
        self.size
    }

    async fn updates(&mut self) -> anyhow::Result<Box<dyn RdpServerDisplayUpdates>> {
        let mut pictures = self.pictures.clone();
        pictures.mark_changed(); // the picture there is now, at once, for whoever just came
        Ok(Box::new(Updates { pictures, size: (self.size.width, self.size.height), first: true }))
    }
}

#[async_trait::async_trait]
impl RdpServerDisplayUpdates for Updates {
    async fn next_update(&mut self) -> anyhow::Result<Option<DisplayUpdate>> {
        if self.first {
            self.first = false;
            return Ok(Some(DisplayUpdate::DefaultPointer));
        }
        loop {
            self.pictures.changed().await?;
            let picture = self.pictures.borrow_and_update().clone();
            let Some(p) = picture else { continue };
            if (p.w, p.h) != self.size {
                // the screen changed size: say so first, then the picture
                self.size = (p.w, p.h);
                self.pictures.mark_changed();
                return Ok(Some(DisplayUpdate::Resize(DesktopSize { width: p.w, height: p.h })));
            }
            if let Some(update) = bitmap(&p) {
                return Ok(Some(update));
            }
        }
    }
}

struct Input(LoopSender<Afar>);

/// A scan code (set 1, as RDP sends them) as an evdev key code.
fn evdev(code: u8, extended: bool) -> Option<u32> {
    let code = u32::from(code);
    if !extended {
        return (1..=0x58).contains(&code).then_some(code);
    }
    Some(match code {
        0x1c => 96,  // keypad Enter
        0x1d => 97,  // right Ctrl
        0x35 => 98,  // keypad /
        0x37 => 99,  // Print
        0x38 => 100, // right Alt (AltGr)
        0x47 => 102, // Home
        0x48 => 103, // Up
        0x49 => 104, // Page Up
        0x4b => 105, // Left
        0x4d => 106, // Right
        0x4f => 107, // End
        0x50 => 108, // Down
        0x51 => 109, // Page Down
        0x52 => 110, // Insert
        0x53 => 111, // Delete
        0x5b => 125, // left Super
        0x5c => 126, // right Super
        0x5d => 127, // Menu
        0x20 => 113, // Mute
        0x2e => 114, // Volume Down
        0x30 => 115, // Volume Up
        0x22 => 164, // Play/Pause
        0x24 => 166, // Stop
        0x10 => 165, // Previous
        0x19 => 163, // Next
        _ => return None,
    })
}

impl RdpServerInputHandler for Input {
    fn keyboard(&mut self, event: KeyboardEvent) {
        let ev = match event {
            KeyboardEvent::Pressed { code, extended } => evdev(code, extended).map(|k| Afar::Key(k, true)),
            KeyboardEvent::Released { code, extended } => evdev(code, extended).map(|k| Afar::Key(k, false)),
            _ => None, // (Unicode keys from phones' on-screen keyboards, lock-key sync: not yet)
        };
        if let Some(ev) = ev {
            let _ = self.0.send(ev);
        }
    }

    fn mouse(&mut self, event: MouseEvent) {
        const LEFT: u32 = 0x110;
        const RIGHT: u32 = 0x111;
        const MIDDLE: u32 = 0x112;
        const SIDE: u32 = 0x113;
        const EXTRA: u32 = 0x114;
        let ev = match event {
            MouseEvent::Move { x, y } => Afar::Move(x, y),
            MouseEvent::LeftPressed => Afar::Button(LEFT, true),
            MouseEvent::LeftReleased => Afar::Button(LEFT, false),
            MouseEvent::RightPressed => Afar::Button(RIGHT, true),
            MouseEvent::RightReleased => Afar::Button(RIGHT, false),
            MouseEvent::MiddlePressed => Afar::Button(MIDDLE, true),
            MouseEvent::MiddleReleased => Afar::Button(MIDDLE, false),
            MouseEvent::Button4Pressed => Afar::Button(SIDE, true),
            MouseEvent::Button4Released => Afar::Button(SIDE, false),
            MouseEvent::Button5Pressed => Afar::Button(EXTRA, true),
            MouseEvent::Button5Released => Afar::Button(EXTRA, false),
            // RDP: up is positive; here down is
            MouseEvent::VerticalScroll { value } => Afar::Scroll(0.0, -f64::from(value)),
            MouseEvent::Scroll { x, y } => Afar::Scroll(f64::from(x), -f64::from(y)),
            MouseEvent::RelMove { .. } => return,
        };
        let _ = self.0.send(ev);
    }
}

struct Viewers(Arc<Mutex<Vec<String>>>);

impl ConnectionHandler for Viewers {
    fn on_accept(&mut self, peer: SocketAddr) -> bool {
        let ip = match peer.ip() {
            std::net::IpAddr::V6(v6) => v6.to_ipv4_mapped().map(std::net::IpAddr::V4).unwrap_or(std::net::IpAddr::V6(v6)),
            ip => ip,
        };
        info!("Screen Sharing: {ip} connecting");
        if let Ok(mut v) = self.0.lock() {
            v.clear();
            v.push(ip.to_string());
        }
        true
    }

    fn on_disconnected(&mut self, peer: SocketAddr, _lasted: Duration, error: Option<&anyhow::Error>) -> PostConnectionAction {
        info!("Screen Sharing: {peer} left{}", error.map(|e| format!(" ({e:#})")).unwrap_or_default());
        if let Ok(mut v) = self.0.lock() {
            v.clear();
        }
        PostConnectionAction::Continue
    }
}

/// What the Screen Sharing app hands over.
pub struct Ask {
    pub output: String,
    pub port: u16,
    pub user: String,
    pub password: String,
    pub cert: PathBuf,
    pub key: PathBuf,
}

impl<B: Backend + 'static> HuginnState<B> {
    /// Start sharing (stopping any sharing first): "" when listening, else why not, in words for the person.
    pub fn share_start(&mut self, ask: Ask) -> String {
        self.share_stop();
        let Some(output) = self
            .space
            .outputs()
            .find(|o| ask.output.is_empty() || o.name() == ask.output)
            .cloned()
        else {
            return "That screen isn't connected.".into();
        };
        let Some(size) = crate::capture::size_of(&output) else { return "That screen is off.".into() };
        if ask.password.len() < 8 || ask.user.is_empty() {
            return "A name and a password of at least 8 characters, please.".into();
        }
        let tls = match TlsIdentityCtx::init_from_paths(&ask.cert, &ask.key) {
            Ok(t) => t,
            Err(err) => return format!("Sharing's certificate couldn't be read ({err:#})."),
        };
        let _ = ironrdp_server::tokio_rustls::rustls::crypto::aws_lc_rs::default_provider().install_default();
        let acceptor = match tls.make_acceptor() {
            Ok(a) => a,
            Err(err) => return format!("Sharing's certificate couldn't be used ({err:#})."),
        };

        let (slot, pictures) = tokio::sync::watch::channel(None);
        *stream(&output).borrow_mut() = Some(Stream { slot, tracker: None, target: None, size: Size::from((0, 0)), last: None });
        let (to_loop, from_server) = channel::<Afar>();
        let name = output.name();
        let input = self
            .handle
            .insert_source(from_server, move |event, _, state| {
                if let ChannelEvent::Msg(ev) = event {
                    state.remote(&name, ev);
                }
            })
            .ok();

        let viewers = Arc::new(Mutex::new(Vec::new()));
        let (stop, stopped) = tokio::sync::oneshot::channel::<()>();
        let (ready_tx, ready_rx) = std::sync::mpsc::channel::<String>();
        let display = Display { size: DesktopSize { width: size.w as u16, height: size.h as u16 }, pictures };
        let creds = Credentials { username: ask.user.clone(), password: ask.password.clone(), domain: None };
        let port = ask.port;
        let watching = viewers.clone();
        let spawned = std::thread::Builder::new().name("screen-sharing".into()).spawn(move || {
            let runtime = match tokio::runtime::Builder::new_current_thread().enable_all().build() {
                Ok(r) => r,
                Err(err) => {
                    let _ = ready_tx.send(format!("Sharing couldn't start ({err})."));
                    return;
                }
            };
            runtime.block_on(async move {
                // IPv4 and IPv6 both (one dual-stack socket), or IPv4 alone where IPv6 is switched off
                let mut addr = SocketAddr::from((std::net::Ipv6Addr::UNSPECIFIED, port));
                let mut tried = std::net::TcpListener::bind(addr).map(drop);
                if tried.as_ref().is_err_and(|e| e.raw_os_error() == Some(libc::EAFNOSUPPORT)) {
                    addr = SocketAddr::from((std::net::Ipv4Addr::UNSPECIFIED, port));
                    tried = std::net::TcpListener::bind(addr).map(drop);
                }
                if let Err(err) = tried {
                    let _ = ready_tx.send(if err.kind() == std::io::ErrorKind::AddrInUse {
                        format!("Something else is using port {port} (another Remote Desktop server?).")
                    } else {
                        format!("Sharing couldn't listen on port {port} ({err}).")
                    });
                    return;
                }
                let mut server = RdpServer::builder()
                    .with_addr(addr)
                    .with_hybrid(acceptor, tls.pub_key.clone())
                    .with_input_handler(Input(to_loop))
                    .with_display_handler(display)
                    .with_connection_handler(Some(Box::new(Viewers(watching))))
                    .build();
                server.set_credentials(Some(creds));
                let _ = ready_tx.send(String::new());
                tokio::select! {
                    result = server.run() => {
                        if let Err(err) = result {
                            warn!("Screen Sharing's server stopped: {err:#}");
                        }
                    }
                    _ = stopped => {}
                }
            });
            info!("Screen Sharing stopped");
        });
        if let Err(err) = spawned {
            self.share_cleanup(&output, input);
            return format!("Sharing couldn't start ({err}).");
        }
        match ready_rx.recv_timeout(Duration::from_secs(5)) {
            Ok(why) if why.is_empty() => {}
            Ok(why) => {
                self.share_cleanup(&output, input);
                return why;
            }
            Err(_) => {
                self.share_cleanup(&output, input);
                return "Sharing didn't start in time.".into();
            }
        }
        info!("Screen Sharing: {} on port {}", output.name(), ask.port);
        self.huginn.share = Some(Share { output: output.name(), port: ask.port, viewers, asked: Instant::now(), stop: Some(stop), input });
        self.backend_data.reset_buffers(&output); // (a first picture, whatever else is going on)
        String::new()
    }

    fn share_cleanup(&mut self, output: &Output, input: Option<RegistrationToken>) {
        *stream(output).borrow_mut() = None;
        if let Some(token) = input {
            self.handle.remove(token);
        }
    }

    pub fn share_stop(&mut self) {
        let Some(mut share) = self.huginn.share.take() else { return };
        if let Some(stop) = share.stop.take() {
            let _ = stop.send(());
        }
        if let Some(output) = self.space.outputs().find(|o| o.name() == share.output).cloned() {
            *stream(&output).borrow_mut() = None;
        }
        if let Some(token) = share.input.take() {
            self.handle.remove(token);
        }
    }

    /// How it's going, as JSON {"on", "output", "port", "viewers"}; asking keeps it going.
    pub fn share_status(&mut self) -> String {
        match &mut self.huginn.share {
            Some(share) => {
                share.asked = Instant::now();
                let viewers = share.viewers.lock().map(|v| v.clone()).unwrap_or_default();
                let viewers: Vec<String> = viewers.iter().map(|v| format!("{v:?}")).collect();
                format!("{{\"on\":true,\"output\":{:?},\"port\":{},\"viewers\":[{}]}}", share.output, share.port, viewers.join(","))
            }
            None => "{\"on\":false}".into(),
        }
    }

    /// Now and then: nobody has asked for 20 seconds (the app closed or crashed), so sharing stops.
    pub fn share_tick(&mut self) {
        if self.huginn.share.as_ref().is_some_and(|s| s.asked.elapsed() > Duration::from_secs(20)) {
            info!("Screen Sharing: the app stopped asking, so sharing stops");
            self.share_stop();
        }
    }

    fn remote(&mut self, output_name: &str, ev: Afar) {
        let Some(output) = self.space.outputs().find(|o| o.name() == output_name).cloned() else { return };
        match ev {
            Afar::Move(x, y) => {
                let (Some(geo), Some(size)) = (self.space.output_geometry(&output), crate::capture::size_of(&output)) else { return };
                if size.w <= 0 || size.h <= 0 {
                    return;
                }
                let at: Point<f64, Logical> = Point::from((
                    f64::from(geo.loc.x) + f64::from(x).min(f64::from(size.w - 1)) * f64::from(geo.size.w) / f64::from(size.w),
                    f64::from(geo.loc.y) + f64::from(y).min(f64::from(size.h - 1)) * f64::from(geo.size.h) / f64::from(size.h),
                ));
                self.touched();
                self.pointer_to(at, InputTime::now());
            }
            Afar::Button(code, down) => {
                self.touched();
                self.on_pointer_button::<Remote>(RemoteButton { code, down });
            }
            Afar::Scroll(h, v) => {
                self.touched();
                self.on_pointer_axis::<Remote>(RemoteAxis { h, v });
            }
            Afar::Key(code, down) => {
                self.touched();
                let action = self.keyboard_key_to_action::<Remote>(RemoteKey { code, down });
                self.process_common_key_action(action);
            }
        }
    }
}

// ------------------------------------------------------------------------- keys and the mouse, from afar
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct RemoteDevice;

impl input::Device for RemoteDevice {
    fn id(&self) -> String {
        "screen-sharing".into()
    }
    fn name(&self) -> String {
        "Screen Sharing".into()
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
        let v120 = if axis == Axis::Horizontal { self.h } else { self.v };
        (v120 != 0.0).then_some(v120 * 15.0 / 120.0)
    }
    fn amount_v120(&self, axis: Axis) -> Option<f64> {
        let v120 = if axis == Axis::Horizontal { self.h } else { self.v };
        (v120 != 0.0).then_some(v120)
    }
    fn source(&self) -> AxisSource {
        AxisSource::Wheel
    }
    fn relative_direction(&self, _axis: Axis) -> AxisRelativeDirection {
        AxisRelativeDirection::Identical
    }
}

/// Screen Sharing's keys and mouse, as an input backend of their own.
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
