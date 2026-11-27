#!/usr/bin/env python3
"""Huginn's sign-in screen.

Drawn as the `huginn-greeter` account under Huginn's compositor, with nobody's session behind it (huginn-signind starts
/usr/libexec/huginn-greeter-session, which starts this). It can do nothing by itself: it shows who can sign in, sends a
name and a password to the sign-in service down the service's socket, and is told yes or no. On yes it plays the wake
(the dock fills, the clock blooms away) and leaves with 0; the service then starts that person's session on the screen
it has left.

    huginn_greeter.py            under the compositor, as the service starts it
    HUGINN_SIGNIN_SOCK=…         the service's socket (the service sets it)
"""
import json
import os
import socket
import sys
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
os.environ.pop("QT_WAYLAND_SHELL_INTEGRATION", None)

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

HERE = Path(__file__).resolve().parent
for apps in (Path("/usr/share/huginn-apps"), HERE.parent / "apps"):
    if (apps / "huginn_signind.py").exists():
        sys.path.insert(0, str(apps))
        break
LIVE_PATHS = (Path("/usr/share/huginn-os/live"), HERE.parent / "config/overlay/usr/share/huginn-os/live")
SOCK = os.environ.get("HUGINN_SIGNIN_SOCK") or "/run/huginn-signin/greeter.sock"


def live_dir() -> str:
    for d in LIVE_PATHS:
        if (d / "LiveWallpaper.qml").exists():
            return QUrl.fromLocalFile(str(d) + "/").toString()
    return ""


def realm() -> str:
    try:
        import huginn_signind
        return huginn_signind.look_realm()
    except Exception:                                            # noqa: BLE001  (whatever's wrong with the files: the default)
        return "aurora"


def battery() -> int:
    """This computer's battery, 0…100, or -1 when it has none."""
    try:
        for b in sorted(Path("/sys/class/power_supply").glob("BAT*")):
            return max(0, min(100, int((b / "capacity").read_text().strip())))
    except (OSError, ValueError):
        pass
    return -1


class Greeter(QObject):
    changed = Signal()
    screensChanged = Signal()
    answered = Signal(bool, str, int)        # a sign-in try: right?, what to say, seconds to wait
    _heard = Signal(object)

    def __init__(self, app: QGuiApplication):
        super().__init__()
        self._app = app
        self._people, self._sessions, self._last, self._last_session, self._host = [], [], "", "huginn", ""
        self._sock, self._lock, self._up = None, threading.Lock(), False
        self._battery = battery()
        app.screenAdded.connect(lambda _s: self.screensChanged.emit())
        app.screenRemoved.connect(lambda _s: self.screensChanged.emit())
        app.primaryScreenChanged.connect(lambda _s: self.screensChanged.emit())
        self._heard.connect(self._on_heard)
        self._again = QTimer(self, interval=1500)
        self._again.timeout.connect(self._connect)
        self._tick = QTimer(self, interval=60000)
        self._tick.timeout.connect(self._minute)
        self._tick.start()
        self._connect()

    # .................................................................................................. the service
    def _connect(self) -> None:
        if self._sock is not None:
            return
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(SOCK)
        except OSError:
            if self._up:
                self._up = False
                self.changed.emit()
            self._again.start()
            return
        self._again.stop()
        self._sock, self._up = s, True
        threading.Thread(target=self._listen, args=(s,), daemon=True).start()
        self._send({"op": "people"})
        self.changed.emit()

    def _listen(self, s: socket.socket) -> None:
        buf = b""
        while True:
            try:
                chunk = s.recv(65536)
            except OSError:
                chunk = b""
            if not chunk:
                self._heard.emit(None)
                return
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    self._heard.emit(msg)

    def _send(self, msg: dict) -> bool:
        with self._lock:
            if self._sock is None:
                return False
            try:
                self._sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
                return True
            except OSError:
                return False

    def _on_heard(self, msg) -> None:
        if msg is None:                                          # the service went away: keep trying, say so meanwhile
            with self._lock:
                try:
                    if self._sock:
                        self._sock.close()
                finally:
                    self._sock = None
            self._up = False
            self.changed.emit()
            self.answered.emit(False, "", 0)
            self._again.start()
            return
        if msg.get("op") == "people":
            who = []
            for p in msg.get("people") or []:
                if isinstance(p, dict) and isinstance(p.get("name"), str):
                    face = p.get("face") or ""
                    who.append({"name": p["name"], "full": str(p.get("full") or p["name"]),
                                "face": QUrl.fromLocalFile(face).toString() if face and os.access(face, os.R_OK) else ""})
            self._people = who
            self._sessions = [s for s in (msg.get("sessions") or []) if isinstance(s, dict) and "id" in s and "name" in s]
            self._last, self._last_session, self._host = str(msg.get("last") or ""), str(msg.get("lastSession") or "huginn"), str(msg.get("host") or "")
            self.changed.emit()
        elif msg.get("op") == "signin":
            self.answered.emit(bool(msg.get("ok")), str(msg.get("why") or ""), int(msg.get("wait") or 0))

    # ................................................................................................. what the screen asks
    @Slot(str, str, str)
    def signIn(self, user: str, password: str, session: str) -> None:
        if not self._send({"op": "signin", "user": user, "password": password, "session": session}):
            self.answered.emit(False, "The sign-in service isn't answering.", 0)

    @Slot(str)
    def power(self, what: str) -> None:
        self._send({"op": "power", "what": what})

    @Slot()
    def done(self) -> None:
        """The wake has played: leaving is what lets the session have the screen. At once: nothing here needs putting
        away, and every moment spent leaving is a moment of black screen."""
        if os.environ.get("HUGINN_GREETER_LEAVE_SLOWLY"):            # (tests watch the leaving)
            self._app.exit(0)
            return
        os._exit(0)

    def _minute(self) -> None:
        b = battery()
        if b != self._battery:
            self._battery = b
            self.changed.emit()

    def _screens(self) -> list:
        primary = self._app.primaryScreen()
        rest = [s for s in self._app.screens() if s is not primary]
        return ([primary] if primary else []) + rest

    screens = Property("QVariantList", _screens, notify=screensChanged)
    people = Property("QVariantList", lambda self: self._people, notify=changed)
    sessions = Property("QVariantList", lambda self: self._sessions, notify=changed)
    last = Property(str, lambda self: self._last, notify=changed)
    lastSession = Property(str, lambda self: self._last_session, notify=changed)
    host = Property(str, lambda self: self._host, notify=changed)
    up = Property(bool, lambda self: self._up, notify=changed)
    battery = Property(int, lambda self: self._battery, notify=changed)
    realm = Property(str, lambda self: realm(), constant=True)
    liveDir = Property(str, lambda self: live_dir(), constant=True)


def main() -> int:
    app = QGuiApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)             # a screen unplugged mustn't end the sign-in screen
    host = Greeter(app)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("Host", host)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Greeter.qml")))
    if not engine.rootObjects():
        return 2
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
