#!/usr/bin/env python3
"""Huginn's lock screen, under Huginn's own compositor.

The compositor starts this when the session locks (Super+L, the lid, going to sleep, the screen-off timer), connected
through a socket made just for it (WAYLAND_SOCKET), and while the session is locked it draws nothing else and sends the
keyboard and mouse nowhere else. It is the sign-in screen's own design (GreeterView.qml, through Locker.qml), with
this as its "Host": you alone in the dock, Sleep and nothing that would close your work, and your sign-in widgets
under the same rule as at the sign-in screen (one you keep private shows its name and a lock). The password is checked
through PAM (huginn_pam.py, as you, never root), with a wait after five wrong ones. Once it's right the wake plays,
and leaving with 0 is what unlocks the session. Anything else (a crash, being killed) and the compositor starts it
again: a broken lock screen never unlocks.

    huginn_locker.py                      under the compositor (it passes the connection)
    HUGINN_LOCKER=/path/to/this ...       the compositor runs this copy instead of the installed one (for development)
"""
import json
import os
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
    if (apps / "huginn_pam.py").exists():
        sys.path.insert(0, str(apps))
        break
LIVE_PATHS = (Path("/usr/share/huginn-os/live"), HERE.parent / "config/overlay/usr/share/huginn-os/live")


def person() -> dict:
    """The signed-in person's name, login and picture, as the lock screen shows them."""
    import pwd
    try:
        pw = pwd.getpwuid(os.getuid())
        name, login, home = (pw.pw_gecos or "").split(",")[0].strip(), pw.pw_name, Path(pw.pw_dir)
    except KeyError:
        name, login, home = "", os.environ.get("USER", ""), Path.home()
    face = next((f for f in (Path("/var/lib/AccountsService/icons") / login, home / ".face.icon", home / ".face") if f.is_file() and os.access(f, os.R_OK)), None)
    return {"name": name or login, "login": login, "face": QUrl.fromLocalFile(str(face)).toString() if face else ""}


def realm() -> str:
    """The realm (colours) the shell's settings have; the lock wears it too."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    try:
        value = json.loads((config / "huginn-shell" / "settings.json").read_text(encoding="utf-8")).get("realm", "")
    except (OSError, ValueError, AttributeError):
        value = ""
    return value if isinstance(value, str) and value.isalpha() else "aurora"


def live_dir() -> str:
    for d in LIVE_PATHS:
        if (d / "LiveWallpaper.qml").exists():
            return QUrl.fromLocalFile(str(d) + "/").toString()
    return ""


class Locker(QObject):
    """What the lock screen asks, answering as the sign-in screen's service does (huginn_greeter.py's Greeter)."""
    changed = Signal()
    screensChanged = Signal()
    answered = Signal(bool, str, int)                  # a try: right?, what to say, seconds to wait
    _checked = Signal(bool, str)

    def __init__(self, app: QGuiApplication):
        super().__init__()
        self._app = app
        self._checking = False
        self._me = person()
        self._widgets = []
        self._battery = battery()
        try:
            import huginn_signind
            self._misses, self._words = huginn_signind.Misses(), huginn_signind.wait_words
        except Exception:                                  # noqa: BLE001  (without the sign-in service's rules: no waits)
            self._misses, self._words = None, None
        self._checked.connect(self._answer)
        app.screenAdded.connect(lambda *_: self.screensChanged.emit())
        app.screenRemoved.connect(lambda *_: self.screensChanged.emit())
        app.primaryScreenChanged.connect(lambda *_: self.screensChanged.emit())
        self._read_widgets()
        self._tick = QTimer(self, interval=60000, timeout=self._minute)
        self._tick.start()

    def _read_widgets(self) -> None:
        """Your sign-in widgets, as the sign-in screen would show them (huginn_signin_widgets.merge)."""
        try:
            import huginn_signin_widgets as sw
            home = Path.home()

            def text(path):
                try:
                    return path.read_text(encoding="utf-8")[:256 * 1024] if path.is_file() else ""
                except OSError:
                    return ""
            layout = text(sw.layout_path(home))
            self._widgets = sw.merge(layout, text(sw.snapshot_path(home)), sw.system_status()) if layout else []
        except Exception:                                  # noqa: BLE001  (no widgets rather than no lock screen)
            self._widgets = []

    def _minute(self) -> None:
        self._read_widgets()
        self._battery = battery()
        self.changed.emit()

    @Slot(str, str, str)
    def signIn(self, user: str, password: str, session: str) -> None:
        """Checks the password away from the screen's thread (a wrong one takes PAM a couple of seconds)."""
        if self._checking:
            return
        login = self._me["login"]
        wait = self._misses.wait(login) if self._misses else 0
        if wait:
            self.answered.emit(False, self._words(wait), wait)
            return
        self._checking = True

        def check():
            try:
                import huginn_pam
                ok, message = huginn_pam.check(login, password)
            except Exception as err:                       # noqa: BLE001 - say what's wrong rather than hang
                ok, message = False, f"Can't check the password: {err}"
            self._checked.emit(ok, message)
        threading.Thread(target=check, daemon=True).start()

    def _answer(self, ok: bool, message: str) -> None:
        self._checking = False
        login = self._me["login"]
        wait = 0
        if self._misses:
            if ok:
                self._misses.right(login)
            else:
                self._misses.missed(login)
                wait = self._misses.wait(login)
        self.answered.emit(ok, "" if ok else (self._words(wait) if wait else message or "Wrong password."), wait)
        if ok:                                             # the wake ends it; a timer makes sure it does
            QTimer.singleShot(4000, self.done)

    @Slot(str)
    def power(self, what: str) -> None:
        """Only Sleep from a lock screen: restarting or shutting down would close what's open."""
        if what == "sleep":
            self.suspend()

    @Slot()
    def done(self) -> None:
        """Right password and the wake has played: leaving with 0 unlocks the session."""
        self._app.exit(0)

    @Slot()
    def suspend(self) -> None:
        from gi.repository import Gio, GLib
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            bus.call("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "Suspend",
                     GLib.Variant("(b)", (True,)), None, 0, 5000, None, None)
        except GLib.Error:
            pass

    def _screens(self) -> list:
        primary = self._app.primaryScreen()
        rest = [s for s in self._app.screens() if s is not primary]
        return ([primary] if primary else []) + rest

    def _people(self) -> list:
        return [{"name": self._me["login"], "full": self._me["name"], "face": self._me["face"], "widgets": self._widgets}]

    screens = Property("QVariantList", _screens, notify=screensChanged)
    people = Property("QVariantList", _people, notify=changed)
    sessions = Property("QVariantList", lambda self: [], constant=True)
    last = Property(str, lambda self: self._me["login"], constant=True)
    lastSession = Property(str, lambda self: "huginn", constant=True)
    host = Property(str, lambda self: "", constant=True)
    up = Property(bool, lambda self: True, constant=True)
    locking = Property(bool, lambda self: True, constant=True)
    battery = Property(int, lambda self: self._battery, notify=changed)
    realm = Property(str, lambda self: realm(), constant=True)
    liveDir = Property(str, lambda self: live_dir(), constant=True)


def battery() -> int:
    """This computer's battery, 0…100, or -1 when it has none."""
    try:
        for b in sorted(Path("/sys/class/power_supply").glob("BAT*")):
            return max(0, min(100, int((b / "capacity").read_text().strip())))
    except (OSError, ValueError):
        pass
    return -1


def main() -> int:
    app = QGuiApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)             # a screen unplugged mustn't end the lock
    locker = Locker(app)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("Host", locker)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Locker.qml")))
    if not engine.rootObjects():
        return 2                                         # not 0: the compositor tries again, the session stays locked
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
