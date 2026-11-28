"""Screen Sharing: let someone see and use this computer for a while, or see and use another one.

Sharing is Huginn's compositor's own RDP server (compositor/src/rdp.rs, asked over org.huginn.Compositor), with a
fresh one-time password, only while this window is open: the password is proved before anything is shown (Network
Level Authentication), over TLS with a certificate of this computer's own (~/.local/share/huginn/sharing). Any
Remote Desktop app can connect: Huginn's own viewer, Windows' Remote Desktop Connection, Microsoft's Windows App on
a Mac or phone. One screen or all of them; what's playing comes along, and the clipboard's text goes both ways. While
someone is looking, the island says so, with Stop. Looking at another computer runs FreeRDP's
viewer (sdl-freerdp, package freerdp-sdl), handing it the password on stdin so it never shows up in the process
list."""
import json
import os
import secrets
import shutil
import socket
import subprocess
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface

STATE = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "sharing.json"
TLS = STATE.parent / "sharing"                                 # cert.pem and key.pem: this computer's, for sharing
COMPOSITOR = ("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor")
PORT = 3389
LOGIN = "huginn"
LETTERS = "abcdefghjkmnpqrstuvwxyz23456789"                     # no 0/o, 1/l/i to misread over the phone
VIEWERS = ["sdl-freerdp", "sdl-freerdp3", "wlfreerdp3", "xfreerdp3", "xfreerdp"]


def one_time_password() -> str:
    return "-".join("".join(secrets.choice(LETTERS) for _ in range(4)) for _ in range(3))


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def addresses() -> list:
    """This computer's addresses other computers on the network can reach, Wi-Fi/Ethernet first."""
    out = []
    for iface in QNetworkInterface.allInterfaces():
        flags = iface.flags()
        if not (flags & QNetworkInterface.IsUp) or flags & QNetworkInterface.IsLoopBack:
            continue
        name = iface.name()
        if name.startswith(("docker", "veth", "br-", "virbr", "lxc")):
            continue
        for entry in iface.addressEntries():
            ip = entry.ip()
            if ip.protocol() == QAbstractSocket.IPv4Protocol and not ip.isLoopback():
                kind = "Wi-Fi" if name.startswith("wl") else "Cable" if name.startswith(("en", "eth")) else "VPN" if name.startswith(("tun", "wg", "tailscale")) else name
                out.append({"ip": ip.toString(), "kind": kind})
    order = {"Wi-Fi": 0, "Cable": 0, "VPN": 2}
    return sorted(out, key=lambda a: order.get(a["kind"], 1))


def watchers(port: int, text: str = None) -> list:
    """Who is connected to the sharing port right now (from `ss -tnH state established`)."""
    if text is None:
        try:
            text = subprocess.run(["ss", "-tnH", "state", "established", f"( sport = :{port} )"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return []
    seen = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local, peer = parts[-2], parts[-1]
        if not local.endswith(f":{port}"):
            continue
        host = peer.rsplit(":", 1)[0].strip("[]")
        if host.startswith("::ffff:"):
            host = host[7:]
        if host not in seen:
            seen.append(host)
    return seen


def split_address(text: str) -> tuple:
    """'192.168.1.20', 'pc.local:3390', '[fe80::1]:3389' -> (host, port)."""
    text = text.strip().replace("rdp://", "").rstrip("/")
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        return host, int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() else PORT
    if text.count(":") == 1:
        host, port = text.split(":")
        return host, int(port) if port.isdigit() else PORT
    return text, PORT


def viewer_args(host: str, port: int, user: str, password: str, full: bool) -> list:
    args = [f"/v:{host}:{port}", f"/u:{user}", f"/p:{password}", "/cert:tofu", "/dynamic-resolution", "+clipboard", "/sound", "/t:" + f"{host} · Huginn"]
    if full:
        args.append("/f")
    return args


def find_viewer() -> str:
    for name in VIEWERS:
        path = shutil.which(name)
        if path:
            return path
    return ""


def certificate(folder: Path = TLS) -> tuple:
    """This computer's certificate for sharing (made the first time: RSA, which every Remote Desktop app takes),
    and its key, private to you."""
    cert, key = folder / "cert.pem", folder / "key.pem"
    if cert.is_file() and key.is_file():
        return cert, key
    import datetime as dt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    k = rsa.generate_private_key(65537, 2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, socket.gethostname() or "huginn"), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Huginn OS")])
    now = dt.datetime.now(dt.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650))
         .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False).sign(k, hashes.SHA256()))
    fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return cert, key


class Sharing(QObject):
    changed = Signal()
    said = Signal(str, bool)

    def __init__(self, demo: bool = False):
        super().__init__()
        self._demo = demo
        self._viewer = find_viewer()
        self._on = False
        self._password, self._port, self._monitor = "", PORT, -1
        self._watching, self._why = [], ""
        self._recent = []
        self._kids = []
        self._bus, self._live = None, None
        if demo:
            self._viewer = "/usr/bin/sdl-freerdp"
            self._on, self._password, self._watching = True, "k7mp-2xq9-w4rt", ["192.168.1.37"]
            self._recent = [{"host": "studio-pc.local", "port": PORT, "user": "astrid", "name": "Studio PC"},
                            {"host": "192.168.1.52", "port": PORT, "user": "huginn", "name": "Mum's laptop"}]
        else:
            try:
                self._recent = json.loads(STATE.read_text(encoding="utf-8")).get("recent", [])[:8]
            except (OSError, ValueError, AttributeError):
                pass
            try:
                from gi.repository import Gio
                self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            except Exception:
                self._bus = None
        self._server = self._demo or self._status() is not None
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._look)

    def _call(self, method: str, sig: str = "", args: tuple = (), timeout: int = 10000):
        from gi.repository import Gio, GLib
        if self._bus is None:
            return None
        try:
            out = self._bus.call_sync(*COMPOSITOR, method, GLib.Variant(f"({sig})", args) if sig else None, None, Gio.DBusCallFlags.NO_AUTO_START, timeout, None)
        except Exception:
            return None
        return out.unpack() if out is not None else ()

    def _status(self):
        """The compositor's word on sharing ({"on", "viewers"…}); None if it has no sharing to offer. Asking keeps
        sharing going: if this window stops asking (it closed or crashed), the compositor stops sharing."""
        got = self._call("ShareStatus", timeout=3000)
        try:
            return json.loads(got[0]) if got else None
        except (ValueError, TypeError):
            return None

    def _keep(self) -> None:
        if self._demo:
            return
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps({"recent": self._recent}), encoding="utf-8")   # never a password
        except OSError:
            pass

    def _look(self) -> None:
        status = self._status() or {}
        if self._on and not status.get("on"):
            self._on, self._password = False, ""
            self._why = "Sharing stopped."
            self._timer.stop()
        now = [str(v) for v in status.get("viewers", [])] if self._on else []
        if now != self._watching:
            new = [w for w in now if w not in self._watching]
            self._watching = now
            for w in new:
                self.said.emit(f"{w} is looking at your screen", False)
        self._tell_island()
        self.changed.emit()

    def _tell_island(self) -> None:
        """While someone is looking, the island says so, with Stop (it isn't PipeWire, so the Privacy Report's watcher
        can't see it)."""
        if self._demo:
            return
        if self._live is None:
            try:
                from huginn_live import LiveReport
                self._live = LiveReport("Screen Sharing")
                self._live.action.connect(lambda _key, what: self.stop() if what == "stop" else None)
            except Exception:
                return
        if self._on and self._watching:
            self._live.report("watching", {"kind": "screen", "title": "Your screen is shared", "sub": ", ".join(self._watching) + " can see and use it",
                                           "glyph": "display", "actions": [{"id": "stop", "label": "Stop", "glyph": "stop", "tone": "danger"}]})
        else:
            self._live.end("watching")

    # ---------------- what QML sees
    sharing = Property(bool, lambda self: self._on, notify=changed)
    password = Property(str, lambda self: self._password, notify=changed)
    login = Property(str, lambda self: LOGIN, constant=True)
    port = Property(int, lambda self: self._port, notify=changed)
    watching = Property("QStringList", lambda self: self._watching, notify=changed)
    why = Property(str, lambda self: self._why, notify=changed)
    canShare = Property(bool, lambda self: bool(self._server), constant=True)
    canView = Property(bool, lambda self: bool(self._viewer), constant=True)
    recent = Property("QVariantList", lambda self: self._recent, notify=changed)
    monitor = Property(int, lambda self: self._monitor, notify=changed)
    hostname = Property(str, lambda self: socket.gethostname(), constant=True)

    def _get_addresses(self) -> list:
        if self._demo:
            return [{"ip": "192.168.1.24", "kind": "Wi-Fi"}, {"ip": "100.92.14.3", "kind": "VPN"}]
        return addresses()

    def _screens(self) -> list:
        app = QGuiApplication.instance()
        return app.screens() if app else []

    def _get_screens(self) -> list:
        """The first screen is shared unless another is picked, or all of them, side by side as they're arranged
        (none listed with one screen)."""
        if self._demo:
            return [{"name": "Built-in screen"}, {"name": "DELL U2720Q"}, {"name": "All screens"}]
        screens = self._screens()
        return [{"name": s.model() or s.name()} for s in screens] + [{"name": "All screens"}] if len(screens) > 1 else []

    addresses = Property("QVariantList", _get_addresses, notify=changed)
    screens = Property("QVariantList", _get_screens, constant=True)

    @Slot(int)
    def setMonitor(self, n: int) -> None:
        self._monitor = n
        self.changed.emit()
        if self._on:
            self.start()

    @Slot()
    def start(self) -> None:
        """(Re)start sharing with a new one-time password."""
        if self._demo:
            self._password = one_time_password()
            self.changed.emit()
            return
        if not self._server:
            self._why = "Sharing needs Huginn's own desktop session, which shares the screen itself."
            self.changed.emit()
            return
        self._stop_server()
        if not port_free(self._port):
            self._why = f"Something else is already using port {self._port}, so sharing can't start."
            self.changed.emit()
            return
        try:
            cert, key = certificate()
        except (OSError, ImportError) as err:
            self._why = f"Sharing's certificate couldn't be made ({err})."
            self.changed.emit()
            return
        screens = self._screens()
        output = screens[self._monitor].name() if 0 <= self._monitor < len(screens) else "*" if self._monitor == len(screens) > 1 else ""
        password = one_time_password()
        got = self._call("ShareStart", "sqssss", (output, self._port, LOGIN, password, str(cert), str(key)))
        why = got[0] if got else "The compositor didn't answer."
        if why:
            self._why, self._password = "Sharing didn't start: " + why, ""
        else:
            self._why, self._password, self._on = "", password, True
            self._timer.start()
        self.changed.emit()

    def _stop_server(self) -> None:
        if self._on or not self._demo:
            self._call("ShareStop", timeout=3000)
        self._on = False
        self._timer.stop()
        self._watching = []
        self._tell_island()

    @Slot()
    def stop(self) -> None:
        if self._demo:
            self.said.emit("Stopped sharing (demo)", False)
            return
        self._stop_server()
        self._password = ""
        self.changed.emit()
        self.said.emit("Stopped sharing. Nobody can see your screen.", False)

    @Slot(str)
    def copy(self, text: str) -> None:
        if QGuiApplication.instance():
            QGuiApplication.clipboard().setText(text)
            self.said.emit("Copied", False)

    @Slot(str, str, str, bool, result=str)
    def view(self, address: str, user: str, password: str, full: bool) -> str:
        """Open another computer's screen in FreeRDP's viewer."""
        host, port = split_address(address)
        if not host or " " in host:
            return "Type the other computer's address, like 192.168.1.20."
        if not user.strip():
            return "Type the name to sign in with."
        if not self._viewer:
            return "Looking at other screens needs FreeRDP's viewer (freerdp-sdl). Get it from the App Store."
        entry = {"host": host, "port": port, "user": user.strip(), "name": next((r.get("name", "") for r in self._recent if r["host"] == host), "")}
        self._recent = [entry] + [r for r in self._recent if r["host"] != host]
        del self._recent[8:]
        self._keep()
        self.changed.emit()
        if self._demo:
            return ""
        try:
            kid = subprocess.Popen([self._viewer, "/args-from:stdin"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
            kid.stdin.write(("\n".join(viewer_args(host, port, user.strip(), password, full)) + "\n").encode())
            kid.stdin.close()
            self._kids.append(kid)
        except OSError as e:
            return f"The viewer didn't start: {e.strerror}"
        self.said.emit(f"Connecting to {host}…", False)
        return ""

    @Slot(str, str)
    def rename(self, host: str, name: str) -> None:
        for r in self._recent:
            if r["host"] == host:
                r["name"] = name.strip()
        self._keep()
        self.changed.emit()

    @Slot(str)
    def forget(self, host: str) -> None:
        self._recent = [r for r in self._recent if r["host"] != host]
        self._keep()
        self.changed.emit()

    def leaving(self) -> None:
        """The window closed: sharing never outlives it."""
        if self._on:
            self._stop_server()
