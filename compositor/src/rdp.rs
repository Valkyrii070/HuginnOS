//! Screen Sharing: this computer's screens over RDP, from the compositor itself, so any Remote Desktop app (Windows'
//! own, Microsoft's Windows App on a Mac or phone, FreeRDP) can see and use it while Screen Sharing is open.
//!
//! The Screen Sharing app asks over the bus (`ShareStart`: which screen, or "*" for all of them, the port, the name
//! and the one-time password, and its own TLS certificate); the server (IronRDP's) runs on a thread of its own with a
//! small tokio runtime. It only takes Network Level Authentication (CredSSP): the password is proved before anything
//! is shown. One person at a time.
//!
//! Pictures: while sharing, each time a shared screen is drawn and something on it changed since its last picture (a
//! damage tracker of its own, the pointer included), it is drawn again into a buffer of its own and read back, at
//! most every 33 ms; each screen's newest picture waits in a `watch` slot of its own, so a slow connection skips
//! pictures instead of falling behind, and goes to its place in the picture the viewer sees (all screens side by
//! side as they're arranged, at the largest screen scale). IronRDP sends only the parts that differ. Screens
//! changing (one plugged in, a new resolution) restart the share, same password: the viewer reconnects.
//!
//! Input: keys, the mouse and characters typed on a phone's on-screen keyboard (afar.rs).
//! The clipboard: text both ways (`wl-paste --watch` says when this side's changes; `wl-copy` takes the other's).
//! Sound: what's playing here, recorded from the default output by `pw-record`, 44.1 kHz stereo, while the viewer
//! wants it.
//!
//! Sharing stops when the app says so, and when the app hasn't asked how it's going for 20 seconds (it closed or
//! crashed): sharing never outlives its window.

use std::{
    cell::RefCell,
    io::{BufRead, BufReader, Read, Write},
    net::SocketAddr,
    num::{NonZeroU16, NonZeroUsize},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use ironrdp_cliprdr::{
    backend::{ClipboardMessage, CliprdrBackend, CliprdrBackendFactory},
    pdu::{
        ClipboardFormat, ClipboardFormatId, ClipboardGeneralCapabilityFlags, FileContentsRequest, FileContentsResponse,
        FormatDataRequest, FormatDataResponse, LockDataId,
    },
};
use ironrdp_rdpsnd::{
    pdu::{AudioFormat, WaveFormat},
    server::NegotiatedFormat,
};
use ironrdp_server::{
    BitmapUpdate, ConnectionHandler, Credentials, CliprdrServerFactory, DesktopSize, DisplayUpdate, KeyboardEvent, MouseEvent,
    PixelFormat, PostConnectionAction, RdpServer, RdpServerDisplay, RdpServerDisplayUpdates, RdpServerInputHandler,
    RdpsndServerHandler, RdpsndServerMessage, ServerEvent, ServerEventSender, SoundServerFactory, TlsIdentityCtx, tokio,
};
use smithay::{
    backend::renderer::{
        Bind, Color32F, ExportMem, Offscreen, Renderer, TextureMapping, damage::OutputDamageTracker, element::RenderElement,
        gles::GlesRenderbuffer,
    },
    backend::allocator::Fourcc,
    output::Output,
    reexports::calloop::{
        RegistrationToken,
        channel::{Event as ChannelEvent, Sender as LoopSender, channel},
    },
    utils::{Logical, Point, Rectangle, Size, Transform},
};
use tracing::{info, warn};

use crate::{
    afar::Afar,
    state::{Backend, HuginnState},
};

/// One picture of one shared screen: B, G, R, A per pixel, rows `w * 4` bytes apart, first row first.
#[derive(Clone)]
pub struct Picture {
    pub w: u16,
    pub h: u16,
    pub bytes: bytes::Bytes,
}

type Slot = tokio::sync::watch::Sender<Option<Picture>>;

/// Where one shared screen sits in the picture the viewer sees.
#[derive(Clone, Debug, PartialEq)]
pub struct Place {
    pub name: String,
    pub x: u16,
    pub y: u16,
    pub w: u16,
    pub h: u16,
    pub geo: Rectangle<i32, Logical>,
}

/// The picture the viewer sees: its size, and where each shared screen is in it.
#[derive(Clone, Debug, PartialEq)]
pub struct Layout {
    pub w: u16,
    pub h: u16,
    pub places: Vec<Place>,
}

/// What the Screen Sharing app hands over.
#[derive(Clone)]
pub struct Ask {
    /// a screen's name, "" for the first, "*" for all of them
    pub output: String,
    pub port: u16,
    pub user: String,
    pub password: String,
    pub cert: PathBuf,
    pub key: PathBuf,
}

/// What the compositor keeps while sharing.
pub struct Share {
    pub output: String,
    pub port: u16,
    pub viewers: Arc<Mutex<Vec<String>>>,
    pub asked: Instant,
    pub layout: Layout,
    ask: Ask,
    stop: Option<tokio::sync::oneshot::Sender<()>>,
    input: Option<RegistrationToken>,
}

impl std::fmt::Debug for Share {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Share").field("output", &self.output).field("port", &self.port).finish()
    }
}

/// From the viewer to the event loop.
#[derive(Debug)]
enum FromViewer {
    /// x, y in the viewer's picture
    Move(u16, u16),
    Afar(Afar),
}

// ------------------------------------------------------------------------------------------ the pictures
/// What the renderer keeps for one shared screen, in the output's user data.
struct Stream {
    slot: Slot,
    ping: Arc<tokio::sync::Notify>,
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
        s.last = None;
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
    s.ping.notify_one();
}

/// The screens `output` names ("" the first, "*" all), side by side as they're arranged, at the largest scale among
/// them (a screen at a smaller one leaves a dark margin); None if there's nothing to show or it's too big for RDP.
pub fn layout_of(screens: &[(String, Rectangle<i32, Logical>, Size<i32, smithay::utils::Buffer>, f64)]) -> Option<Layout> {
    let scale = screens.iter().map(|s| s.3).fold(0.0_f64, f64::max).max(1.0);
    let left = screens.iter().map(|s| s.1.loc.x).min()?;
    let top = screens.iter().map(|s| s.1.loc.y).min()?;
    let mut places = Vec::new();
    let (mut w, mut h) = (0_i64, 0_i64);
    for (name, geo, px, _) in screens {
        let x = (f64::from(geo.loc.x - left) * scale).round() as i64;
        let y = (f64::from(geo.loc.y - top) * scale).round() as i64;
        let (pw, ph) = (i64::from(px.w), i64::from(px.h));
        if pw <= 0 || ph <= 0 {
            continue;
        }
        w = w.max(x + pw);
        h = h.max(y + ph);
        places.push(Place { name: name.clone(), x: x as u16, y: y as u16, w: pw as u16, h: ph as u16, geo: *geo });
    }
    // (RDP's limit for a desktop is 8192 pixels each way)
    if places.is_empty() || w > 8192 || h > 8192 {
        return None;
    }
    Some(Layout { w: w as u16, h: h as u16, places })
}

/// Where a point of the viewer's picture is on the desktop (None between screens).
pub fn desktop_point(layout: &Layout, x: u16, y: u16) -> Option<Point<f64, Logical>> {
    let p = layout.places.iter().find(|p| x >= p.x && y >= p.y && x < p.x + p.w && y < p.y + p.h)?;
    Some(Point::from((
        f64::from(p.geo.loc.x) + f64::from(x - p.x) * f64::from(p.geo.size.w) / f64::from(p.w),
        f64::from(p.geo.loc.y) + f64::from(y - p.y) * f64::from(p.geo.size.h) / f64::from(p.h),
    )))
}

// -------------------------------------------------------------------------------------------- the server
struct Display {
    size: DesktopSize,
    screens: Vec<(tokio::sync::watch::Receiver<Option<Picture>>, u16, u16, u16, u16)>,
    ping: Arc<tokio::sync::Notify>,
}

struct Updates {
    screens: Vec<(tokio::sync::watch::Receiver<Option<Picture>>, u16, u16, u16, u16)>,
    ping: Arc<tokio::sync::Notify>,
    first: bool,
}

#[async_trait::async_trait]
impl RdpServerDisplay for Display {
    async fn size(&mut self) -> DesktopSize {
        self.size
    }

    async fn updates(&mut self) -> anyhow::Result<Box<dyn RdpServerDisplayUpdates>> {
        let mut screens = self.screens.clone();
        for s in &mut screens {
            s.0.mark_changed(); // the pictures there are now, at once, for whoever just came
        }
        Ok(Box::new(Updates { screens, ping: self.ping.clone(), first: true }))
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
            for (rx, x, y, w, h) in &mut self.screens {
                if !rx.has_changed().unwrap_or(false) {
                    continue;
                }
                let picture = rx.borrow_and_update().clone();
                let Some(p) = picture else { continue };
                if (p.w, p.h) != (*w, *h) {
                    continue; // (the screen changed size: the share restarts with a new layout)
                }
                let (Some(width), Some(height), Some(stride)) =
                    (NonZeroU16::new(p.w), NonZeroU16::new(p.h), NonZeroUsize::new(usize::from(p.w) * 4))
                else {
                    continue;
                };
                return Ok(Some(DisplayUpdate::Bitmap(BitmapUpdate {
                    x: *x,
                    y: *y,
                    width,
                    height,
                    format: PixelFormat::BgrA32,
                    data: p.bytes.clone(),
                    stride,
                })));
            }
            self.ping.notified().await;
        }
    }
}

struct Input {
    to_loop: LoopSender<FromViewer>,
    surrogate: Option<u16>,
}

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
            // a phone's on-screen keyboard: characters (UTF-16, so two halves for some)
            KeyboardEvent::UnicodePressed(unit) => {
                if (0xD800..0xDC00).contains(&unit) {
                    self.surrogate = Some(unit);
                    None
                } else {
                    let units: Vec<u16> = self.surrogate.take().into_iter().chain([unit]).collect();
                    let text: String = char::decode_utf16(units).filter_map(Result::ok).collect();
                    (!text.is_empty()).then_some(Afar::Text(text))
                }
            }
            _ => None, // (letting go of a character; lock-key sync)
        };
        if let Some(ev) = ev {
            let _ = self.to_loop.send(FromViewer::Afar(ev));
        }
    }

    fn mouse(&mut self, event: MouseEvent) {
        const LEFT: u32 = 0x110;
        const RIGHT: u32 = 0x111;
        const MIDDLE: u32 = 0x112;
        const SIDE: u32 = 0x113;
        const EXTRA: u32 = 0x114;
        let ev = match event {
            MouseEvent::Move { x, y } => FromViewer::Move(x, y),
            MouseEvent::LeftPressed => FromViewer::Afar(Afar::Button(LEFT, true)),
            MouseEvent::LeftReleased => FromViewer::Afar(Afar::Button(LEFT, false)),
            MouseEvent::RightPressed => FromViewer::Afar(Afar::Button(RIGHT, true)),
            MouseEvent::RightReleased => FromViewer::Afar(Afar::Button(RIGHT, false)),
            MouseEvent::MiddlePressed => FromViewer::Afar(Afar::Button(MIDDLE, true)),
            MouseEvent::MiddleReleased => FromViewer::Afar(Afar::Button(MIDDLE, false)),
            MouseEvent::Button4Pressed => FromViewer::Afar(Afar::Button(SIDE, true)),
            MouseEvent::Button4Released => FromViewer::Afar(Afar::Button(SIDE, false)),
            MouseEvent::Button5Pressed => FromViewer::Afar(Afar::Button(EXTRA, true)),
            MouseEvent::Button5Released => FromViewer::Afar(Afar::Button(EXTRA, false)),
            // RDP: up is positive; here down is
            MouseEvent::VerticalScroll { value } => FromViewer::Afar(Afar::Wheel(0.0, -f64::from(value))),
            MouseEvent::Scroll { x, y } => FromViewer::Afar(Afar::Wheel(f64::from(x), -f64::from(y))),
            MouseEvent::RelMove { .. } => return,
        };
        let _ = self.to_loop.send(ev);
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

// --------------------------------------------------------------------------------- the server's own events
/// The way back into the server (sound and the clipboard), once it has handed it over.
#[derive(Clone, Default)]
struct Events(Arc<Mutex<Option<tokio::sync::mpsc::UnboundedSender<ServerEvent>>>>);

impl std::fmt::Debug for Events {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("Events")
    }
}

impl Events {
    fn send(&self, ev: ServerEvent) {
        if let Ok(guard) = self.0.lock()
            && let Some(tx) = guard.as_ref()
        {
            let _ = tx.send(ev);
        }
    }

    fn clip(&self, msg: ClipboardMessage) {
        self.send(ServerEvent::Clipboard(msg));
    }
}

/// A child process that ends when this does.
struct Kid(Child);

impl Drop for Kid {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

// ------------------------------------------------------------------------------------------- the clipboard
const MOST_TEXT: usize = 4 << 20;

/// `wl-paste`/`wl-copy` as clients of this compositor (on its own socket): the clipboard's text, in and out.
#[derive(Clone, Debug)]
struct Wayland(String);

impl Wayland {
    fn command(&self, program: &str) -> Command {
        let mut cmd = Command::new(program);
        cmd.env("WAYLAND_DISPLAY", &self.0).stdin(Stdio::null()).stderr(Stdio::null());
        cmd
    }

    fn has_text(&self) -> bool {
        let Ok(out) = self.command("wl-paste").arg("--list-types").stdout(Stdio::piped()).output() else { return false };
        String::from_utf8_lossy(&out.stdout).lines().any(|t| t.starts_with("text/plain") || t == "UTF8_STRING" || t == "STRING" || t == "TEXT")
    }

    fn text(&self) -> Option<String> {
        let mut kid = Kid(self.command("wl-paste").args(["--no-newline", "--type", "text"]).stdout(Stdio::piped()).spawn().ok()?);
        let mut out = Vec::new();
        let stdout = kid.0.stdout.take()?;
        let reader = std::thread::spawn(move || {
            let _ = stdout.take(MOST_TEXT as u64).read_to_end(&mut out);
            out
        });
        let end = Instant::now() + Duration::from_secs(3);
        while Instant::now() < end && !reader.is_finished() {
            std::thread::sleep(Duration::from_millis(10));
        }
        if !reader.is_finished() {
            return None; // (the app that has the clipboard didn't answer: Kid's drop ends wl-paste, and the reader with it)
        }
        String::from_utf8(reader.join().ok()?).ok()
    }

    fn set_text(&self, text: &str) {
        if let Ok(mut kid) = self.command("wl-copy").arg("--type").arg("text/plain;charset=utf-8").stdin(Stdio::piped()).stdout(Stdio::null()).spawn() {
            if let Some(mut input) = kid.stdin.take() {
                let _ = input.write_all(text.as_bytes());
            }
            let _ = kid.wait(); // (wl-copy goes on in the background, offering the text, until something else is copied)
        }
    }
}

#[derive(Debug)]
struct Clip {
    events: Events,
    wayland: Wayland,
    asked: Option<ClipboardFormatId>,
}

ironrdp_core::impl_as_any!(Clip);

impl Clip {
    /// Tell the viewer what this side's clipboard has (text, or nothing).
    fn announce(events: &Events, wayland: &Wayland) {
        let formats = if wayland.has_text() { vec![ClipboardFormat::new(ClipboardFormatId::CF_UNICODETEXT)] } else { vec![] };
        events.clip(ClipboardMessage::SendInitiateCopy(formats));
    }
}

impl CliprdrBackend for Clip {
    fn temporary_directory(&self) -> &str {
        "/tmp"
    }

    fn client_capabilities(&self) -> ClipboardGeneralCapabilityFlags {
        ClipboardGeneralCapabilityFlags::empty()
    }

    fn on_ready(&mut self) {
        let (events, wayland) = (self.events.clone(), self.wayland.clone());
        std::thread::spawn(move || Clip::announce(&events, &wayland));
    }

    fn on_request_format_list(&mut self) {
        self.on_ready();
    }

    fn on_process_negotiated_capabilities(&mut self, _capabilities: ClipboardGeneralCapabilityFlags) {}

    fn on_remote_copy(&mut self, available: &[ClipboardFormat]) {
        // something copied over there: fetch its text now, so it's ready to paste here
        let want = [ClipboardFormatId::CF_UNICODETEXT, ClipboardFormatId::CF_TEXT].into_iter().find(|id| available.iter().any(|f| f.id() == *id));
        if let Some(id) = want {
            self.asked = Some(id);
            self.events.clip(ClipboardMessage::SendInitiatePaste(id));
        }
    }

    fn on_format_data_request(&mut self, request: FormatDataRequest) {
        let (events, wayland, format) = (self.events.clone(), self.wayland.clone(), request.format);
        std::thread::spawn(move || {
            let text = (format == ClipboardFormatId::CF_UNICODETEXT || format == ClipboardFormatId::CF_TEXT).then(|| wayland.text()).flatten();
            let response = match text {
                Some(text) if format == ClipboardFormatId::CF_UNICODETEXT => FormatDataResponse::new_unicode_string(&text),
                Some(text) => FormatDataResponse::new_string(&text),
                None => FormatDataResponse::new_error(),
            };
            events.clip(ClipboardMessage::SendFormatData(response));
        });
    }

    fn on_format_data_response(&mut self, response: FormatDataResponse<'_>) {
        let Some(asked) = self.asked.take() else { return };
        if response.is_error() || response.data().len() > MOST_TEXT {
            return;
        }
        let text = if asked == ClipboardFormatId::CF_UNICODETEXT {
            response.to_unicode_string().ok()
        } else {
            Some(String::from_utf8_lossy(response.data()).trim_end_matches('\0').to_owned())
        };
        if let Some(text) = text.map(|t| t.trim_end_matches('\0').to_owned()) {
            let wayland = self.wayland.clone();
            std::thread::spawn(move || wayland.set_text(&text));
        }
    }

    fn on_file_contents_request(&mut self, request: FileContentsRequest) {
        self.events.clip(ClipboardMessage::SendFileContentsResponse(FileContentsResponse::new_error(request.stream_id)));
    }

    fn on_file_contents_response(&mut self, _response: FileContentsResponse<'_>) {}

    fn on_lock(&mut self, _data_id: LockDataId) {}

    fn on_unlock(&mut self, _data_id: LockDataId) {}
}

struct ClipFactory {
    events: Events,
    wayland: Wayland,
}

impl ServerEventSender for ClipFactory {
    fn set_sender(&mut self, sender: tokio::sync::mpsc::UnboundedSender<ServerEvent>) {
        if let Ok(mut s) = self.events.0.lock() {
            *s = Some(sender);
        }
    }
}

impl CliprdrBackendFactory for ClipFactory {
    fn build_cliprdr_backend(&self) -> Box<dyn CliprdrBackend> {
        Box::new(Clip { events: self.events.clone(), wayland: self.wayland.clone(), asked: None })
    }
}

impl CliprdrServerFactory for ClipFactory {}

/// While sharing: each time something is copied here, the viewer is told (`wl-paste --watch`).
fn watch_clipboard(events: Events, wayland: Wayland) -> Option<Kid> {
    let mut kid = Kid(wayland.command("wl-paste").args(["--watch", "echo"]).stdout(Stdio::piped()).spawn().ok()?);
    let out = kid.0.stdout.take()?;
    std::thread::spawn(move || {
        for _ in BufReader::new(out).lines().map_while(Result::ok) {
            Clip::announce(&events, &wayland);
        }
    });
    Some(kid)
}

// ---------------------------------------------------------------------------------------------- sound
static FORMATS: [AudioFormat; 1] = [AudioFormat {
    format: WaveFormat::PCM,
    n_channels: 2,
    n_samples_per_sec: 44100,
    n_avg_bytes_per_sec: 44100 * 4,
    n_block_align: 4,
    bits_per_sample: 16,
    data: None,
}];

#[derive(Debug)]
struct Sound {
    events: Events,
    recorder: Option<Recorder>,
}

/// `pw-record` on the default output's monitor: what's playing here, as raw 16-bit samples.
struct Recorder {
    _alive: Kid,
}

impl std::fmt::Debug for Recorder {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("Recorder")
    }
}

impl RdpsndServerHandler for Sound {
    fn get_formats(&self) -> &[AudioFormat] {
        &FORMATS
    }

    fn choose_format<'a>(&mut self, common: &'a [NegotiatedFormat]) -> Option<&'a NegotiatedFormat> {
        common.iter().find(|f| *f.format() == FORMATS[0])
    }

    fn start(&mut self, format: &NegotiatedFormat) -> Result<(), Box<dyn ironrdp_rdpsnd::server::RdpsndError>> {
        self.stop();
        let f = format.format();
        let mut kid = Command::new("pw-record")
            .args(["--raw", "--format", "s16", "--latency", "40ms"])
            .args(["--rate", &f.n_samples_per_sec.to_string(), "--channels", &f.n_channels.to_string()])
            .args(["-P", "{ stream.capture.sink = true node.name = huginn-screen-sharing media.name = \"Screen Sharing\" }", "-"])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| Box::new(e) as Box<dyn ironrdp_rdpsnd::server::RdpsndError>)?;
        let Some(mut out) = kid.stdout.take() else { return Ok(()) };
        // 20 ms a piece
        let piece = (f.n_samples_per_sec as usize * usize::from(f.n_block_align) / 50).max(64);
        let events = self.events.clone();
        std::thread::spawn(move || {
            let began = Instant::now();
            let mut buf = vec![0u8; piece];
            while out.read_exact(&mut buf).is_ok() {
                let ts = (began.elapsed().as_millis() & 0xffff_ffff) as u32;
                events.send(ServerEvent::Rdpsnd(RdpsndServerMessage::Wave(buf.clone(), ts)));
            }
        });
        info!("Screen Sharing: sound on");
        self.recorder = Some(Recorder { _alive: Kid(kid) });
        Ok(())
    }

    fn stop(&mut self) {
        self.recorder = None;
    }
}

struct SoundFactory {
    events: Events,
}

impl ServerEventSender for SoundFactory {
    fn set_sender(&mut self, sender: tokio::sync::mpsc::UnboundedSender<ServerEvent>) {
        if let Ok(mut s) = self.events.0.lock() {
            *s = Some(sender);
        }
    }
}

impl SoundServerFactory for SoundFactory {
    fn build_backend(&self) -> Box<dyn RdpsndServerHandler> {
        Box::new(Sound { events: self.events.clone(), recorder: None })
    }
}

// ------------------------------------------------------------------------------------------- starting
impl<B: Backend + 'static> HuginnState<B> {
    /// The screens `ask.output` names, laid out as the viewer will see them.
    fn share_layout(&self, which: &str) -> Option<(Layout, Vec<Output>)> {
        let outputs: Vec<Output> = self
            .space
            .outputs()
            .filter(|o| which == "*" || o.name() == which)
            .take(if which.is_empty() { 1 } else { usize::MAX })
            .cloned()
            .collect();
        let outputs = if outputs.is_empty() && which.is_empty() { self.space.outputs().take(1).cloned().collect() } else { outputs };
        let screens: Vec<_> = outputs
            .iter()
            .filter_map(|o| Some((o.name(), self.space.output_geometry(o)?, crate::capture::size_of(o)?, o.current_scale().fractional_scale())))
            .collect();
        Some((layout_of(&screens)?, outputs))
    }

    /// Start sharing (stopping any sharing first): "" when listening, else why not, in words for the person.
    pub fn share_start(&mut self, ask: Ask) -> String {
        self.share_stop();
        if ask.password.len() < 8 || ask.user.is_empty() {
            return "A name and a password of at least 8 characters, please.".into();
        }
        let Some((layout, outputs)) = self.share_layout(&ask.output) else {
            return if ask.output == "*" {
                "All the screens together are too big to share at once (8192 pixels each way at most). Pick one.".into()
            } else {
                "That screen isn't connected, or it's off.".into()
            };
        };
        let tls = match TlsIdentityCtx::init_from_paths(&ask.cert, &ask.key) {
            Ok(t) => t,
            Err(err) => return format!("Sharing's certificate couldn't be read ({err:#})."),
        };
        let _ = ironrdp_server::tokio_rustls::rustls::crypto::aws_lc_rs::default_provider().install_default();
        let acceptor = match tls.make_acceptor() {
            Ok(a) => a,
            Err(err) => return format!("Sharing's certificate couldn't be used ({err:#})."),
        };

        let ping = Arc::new(tokio::sync::Notify::new());
        let mut screens = Vec::new();
        for (o, place) in outputs.iter().zip(&layout.places) {
            let (slot, pictures) = tokio::sync::watch::channel(None);
            *stream(o).borrow_mut() = Some(Stream { slot, ping: ping.clone(), tracker: None, target: None, size: Size::from((0, 0)), last: None });
            screens.push((pictures, place.x, place.y, place.w, place.h));
        }
        let (to_loop, from_server) = channel::<FromViewer>();
        let input = self
            .handle
            .insert_source(from_server, move |event, _, state| {
                if let ChannelEvent::Msg(ev) = event {
                    state.from_viewer(ev);
                }
            })
            .ok();

        let viewers = Arc::new(Mutex::new(Vec::new()));
        let (stop, stopped) = tokio::sync::oneshot::channel::<()>();
        let (ready_tx, ready_rx) = std::sync::mpsc::channel::<String>();
        let display = Display { size: DesktopSize { width: layout.w, height: layout.h }, screens, ping };
        let creds = Credentials { username: ask.user.clone(), password: ask.password.clone(), domain: None };
        let port = ask.port;
        let watching = viewers.clone();
        let wayland = self.socket_name.clone().map(Wayland);
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
                let sound = Events::default();
                let clip = Events::default();
                let mut server = RdpServer::builder()
                    .with_addr(addr)
                    .with_hybrid(acceptor, tls.pub_key.clone())
                    .with_input_handler(Input { to_loop, surrogate: None })
                    .with_display_handler(display)
                    .with_connection_handler(Some(Box::new(Viewers(watching))))
                    .with_sound_factory(Some(Box::new(SoundFactory { events: sound })))
                    .with_cliprdr_factory(wayland.clone().map(|w| Box::new(ClipFactory { events: clip.clone(), wayland: w }) as Box<dyn CliprdrServerFactory>))
                    .build();
                server.set_credentials(Some(creds));
                let _watcher = wayland.and_then(|w| watch_clipboard(clip, w)); // (ends with the share)
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
            self.share_cleanup(&outputs, input);
            return format!("Sharing couldn't start ({err}).");
        }
        match ready_rx.recv_timeout(Duration::from_secs(5)) {
            Ok(why) if why.is_empty() => {}
            Ok(why) => {
                self.share_cleanup(&outputs, input);
                return why;
            }
            Err(_) => {
                self.share_cleanup(&outputs, input);
                return "Sharing didn't start in time.".into();
            }
        }
        let names: Vec<String> = outputs.iter().map(|o| o.name()).collect();
        info!("Screen Sharing: {} on port {} ({}x{})", names.join(", "), ask.port, layout.w, layout.h);
        for o in &outputs {
            self.backend_data.reset_buffers(o); // (a first picture, whatever else is going on)
        }
        self.huginn.share = Some(Share {
            output: if ask.output == "*" { "*".into() } else { names.join(",") },
            port: ask.port,
            viewers,
            asked: Instant::now(),
            layout,
            ask,
            stop: Some(stop),
            input,
        });
        String::new()
    }

    fn share_cleanup(&mut self, outputs: &[Output], input: Option<RegistrationToken>) {
        for o in outputs {
            *stream(o).borrow_mut() = None;
        }
        if let Some(token) = input {
            self.handle.remove(token);
        }
    }

    pub fn share_stop(&mut self) {
        let Some(mut share) = self.huginn.share.take() else { return };
        if let Some(stop) = share.stop.take() {
            let _ = stop.send(());
        }
        let outputs: Vec<Output> = self.space.outputs().cloned().collect();
        for o in &outputs {
            *stream(o).borrow_mut() = None;
        }
        if let Some(token) = share.input.take() {
            self.handle.remove(token);
        }
    }

    /// How it's going, as JSON {"on", "output", "port", "size", "viewers"}; asking keeps it going.
    pub fn share_status(&mut self) -> String {
        match &mut self.huginn.share {
            Some(share) => {
                share.asked = Instant::now();
                let viewers = share.viewers.lock().map(|v| v.clone()).unwrap_or_default();
                let viewers: Vec<String> = viewers.iter().map(|v| format!("{v:?}")).collect();
                format!(
                    "{{\"on\":true,\"output\":{:?},\"port\":{},\"size\":[{},{}],\"viewers\":[{}]}}",
                    share.output,
                    share.port,
                    share.layout.w,
                    share.layout.h,
                    viewers.join(",")
                )
            }
            None => "{\"on\":false}".into(),
        }
    }

    /// Now and then: nobody has asked for 20 seconds (the app closed or crashed), so sharing stops; the screens
    /// changed (one plugged in or out, a new resolution or arrangement), so it starts again to match.
    pub fn share_tick(&mut self) {
        let Some(share) = self.huginn.share.as_ref() else { return };
        if share.asked.elapsed() > Duration::from_secs(20) {
            info!("Screen Sharing: the app stopped asking, so sharing stops");
            self.share_stop();
            return;
        }
        let now = self.share_layout(&share.ask.output).map(|(l, _)| l);
        if now.as_ref() != Some(&share.layout) {
            let ask = share.ask.clone();
            let asked = share.asked;
            info!("Screen Sharing: the screens changed, so sharing starts again to match");
            let why = self.share_start(ask);
            if !why.is_empty() {
                warn!("Screen Sharing couldn't start again: {why}");
            } else if let Some(s) = self.huginn.share.as_mut() {
                s.asked = asked;
            }
        }
    }

    fn from_viewer(&mut self, ev: FromViewer) {
        match ev {
            FromViewer::Move(x, y) => {
                let Some(at) = self.huginn.share.as_ref().and_then(|s| desktop_point(&s.layout, x, y)) else { return };
                self.afar(Afar::To(at));
            }
            FromViewer::Afar(ev) => self.afar(ev),
        }
    }
}
