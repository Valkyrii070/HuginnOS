"""What the top bar and the control centre show and change, for real: the battery (UPower), the network
(NetworkManager), Bluetooth (BlueZ), the screen's brightness and the sound (Huginn's session daemon), Do Not Disturb,
night light (KWin), the notifications that came, and which app is in front.

Which app is in front: Huginn's own compositor tells the shell over D-Bus (org.huginn.Shell.Active); under KWin a small
KWin script (/usr/share/kwin/scripts/huginnactive) does. Things done to windows (bring an app forward, minimise, close)
are asked of Huginn's compositor (org.huginn.Compositor.ActivateApp, WindowAction), or of KWin through its scripting
interface, one tiny script at a time.

All of it is D-Bus through Gio; nothing here blocks the screen for long (every call has a short timeout).
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from gi.repository import Gio, GLib
from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QTimer, QUrl, Signal, Slot

# KWin script: the window list for the shell (the same as huginnactive's main.js, for a shell started after KWin)
WINDOWS_JS = """var lastWindows = "";
function spaceOf(w) {
    if (w.onAllDesktops || !w.desktops || w.desktops.length === 0) return -1;
    return workspace.desktops.indexOf(w.desktops[0]);
}
function reportWindows() {
    var rows = [];
    var all = workspace.windowList();
    for (var i = 0; i < all.length; i++) {
        var w = all[i];
        if (!w.normalWindow || w.skipTaskbar) continue;
        var g = w.frameGeometry;
        rows.push({ id: String(w.internalId), app: w.desktopFileName || w.resourceClass || "", cls: w.resourceClass || "",
                    title: w.caption, minimised: w.minimized, active: w === workspace.activeWindow, space: spaceOf(w), pid: w.pid, full: w.fullScreen,
                    x: g.x, y: g.y, w: g.width, h: g.height });
    }
    var spaces = [];
    for (var j = 0; j < workspace.desktops.length; j++) spaces.push(workspace.desktops[j].name);
    callDBus("org.huginn.Shell", "/org/huginn/Shell", "org.huginn.Shell", "Windows",
             JSON.stringify({ current: workspace.desktops.indexOf(workspace.currentDesktop), spaces: spaces, windows: rows }));
}"""

SHELL_XML = """<node><interface name="org.huginn.Shell">
  <method name="Active"><arg type="s" name="caption" direction="in"/><arg type="s" name="app" direction="in"/>
    <arg type="s" name="desktop" direction="in"/><arg type="b" name="maximized" direction="in"/></method>
  <method name="Activated"><arg type="s" name="app" direction="in"/><arg type="b" name="found" direction="in"/></method>
  <method name="ToggleLauncher"/>
  <method name="Launcher"><arg type="s" name="what" direction="in"/></method>
  <method name="Search"><arg type="s" name="text" direction="in"/></method>
  <method name="Screenshot"><arg type="s" name="what" direction="in"/></method>
  <method name="Windows"><arg type="s" name="json" direction="in"/></method>
  <method name="Key"><arg type="s" name="what" direction="in"/></method>
  <method name="Tour"/>
  <method name="Overview"><arg type="s" name="json" direction="in"/></method>
  <method name="SnapPreview"><arg type="s" name="json" direction="in"/></method>
  <method name="SnapAssist"><arg type="s" name="json" direction="in"/></method>
  <method name="Switcher"><arg type="s" name="json" direction="in"/></method>
  <method name="Snap"><arg type="s" name="layout" direction="in"/></method>
  <method name="Lift"><arg type="s" name="app" direction="in"/></method>
  <method name="AppMenu"/>
</interface></node>"""
HISTORY = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "notifications.jsonl"
SEEN_NOTES = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "huginn" / "notifications-seen"
CLEARED_NOTES = HISTORY.with_name("notifications-cleared")     # sessiond: Clear all, from when on the list shows them
BUSY_FLAG = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "huginn-busy-screen"



def QProcess_start(app: str) -> None:
    """One of Huginn's own apps."""
    from PySide6.QtCore import QProcess
    here = Path(__file__).resolve().parent
    for d in (Path("/usr/share/huginn-apps"), here.parent / "apps"):
        if (d / "huginn_app.py").exists():
            QProcess.startDetached("python3", [str(d / "huginn_app.py"), app])
            return


def qt_runs_glib() -> bool:
    """Ubuntu's Qt runs GLib's loop itself, and GLib's sources (D-Bus) are served with Qt's events. Turning GLib's
    loop by hand from a Qt timer as well would run Qt's events inside Qt's events: a window drawn in the middle of
    drawing another, which can leave a surface waiting forever for its compositor."""
    from PySide6.QtCore import QAbstractEventDispatcher
    d = QAbstractEventDispatcher.instance()
    return d is not None and "Glib" in d.metaObject().className()

def _js(text: str) -> str:
    return json.dumps(text)


def apps_module(name: str):
    """One of the apps' Python modules (huginn_settings, ...), from the installed apps or the kit's."""
    here = Path(__file__).resolve().parent
    for d in (Path("/usr/share/huginn-apps"), here.parent / "apps"):
        if (d / (name + ".py")).exists():
            if str(d) not in sys.path:
                sys.path.append(str(d))
            return __import__(name)
    return None


# How a key is shown on a keycap in the shortcut sheet (hold Super)
KEYCAPS = {"period": ".", "comma": ",", "equal": "=", "plus": "+", "minus": "\u2212", "slash": "/", "semicolon": ";", "apostrophe": "'",
           "grave": "`", "bracketleft": "[", "bracketright": "]", "backslash": "\\", "KP_Add": "Num +", "KP_Subtract": "Num \u2212",
           "KP_0": "Num 0", "Left": "\u2190", "Right": "\u2192", "Up": "\u2191", "Down": "\u2193", "Print": "PrtSc", "Return": "Enter",
           "Escape": "Esc", "Delete": "Del", "Prior": "PgUp", "Next": "PgDn"}
SHEET_GROUPS = ("Finding and opening", "Windows", "Spaces", "Screen", "Typing and reading")
SHEET_FIXED = {"Start menu": ("Finding and opening", "Start menu (tap)", 0), "The app's menu": ("Windows", "The app's menu (tap)", None),
               "Switch between windows": ("Windows", "Switch between windows", None), "Go to space 1 to 9": ("Spaces", "Go to space 1 to 9", 0)}


def keycaps(combo: str) -> list:
    """'Super+Shift+S' -> ['Super', 'Shift', 'S']; 'Super+equal' -> ['Super', '=']."""
    parts = combo.split("+")
    if len(parts) >= 2 and parts[-1] == "" and parts[-2] == "":
        parts = parts[:-2] + ["+"]
    caps = {k.lower(): v for k, v in KEYCAPS.items()}
    return [caps.get(p.lower(), p) for p in parts if p]


SHEET_SHORT = {"Take the window to the space on the left": "Window to the space on the left",
               "Take the window to the space on the right": "Window to the space on the right",
               "Keep the window on top of the others": "Keep the window on top", "Overview of windows and spaces": "Overview",
               "Screenshot of a part, or a window": "Screenshot of a part or a window"}


def sheet_label(label: str) -> str:
    """A shortcut's line in Settings cut to what it is: 'Dictation: talk, and it types (again: done)' -> 'Dictation'."""
    label = label.split(" (")[0].split(": ")[0].strip()
    return SHEET_SHORT.get(label, label)


def shortcut_sheet(keys: dict) -> list:
    """The shortcut sheet's groups, from Settings › Keyboard shortcuts as it stands (huginn_settings.load_keys):
    [{"title", "rows": [{"label", "keys": [keycaps]}]}], in Settings' order, the person's own last."""
    groups = {g: [] for g in SHEET_GROUPS}
    for it in keys.get("items", []):
        if it.get("keys"):
            groups.setdefault(it.get("group") or "Windows", []).append({"label": sheet_label(it.get("label", "")), "keys": keycaps(it["keys"][0])})
    for f in keys.get("fixed", []):
        group, label, at = SHEET_FIXED.get(f.get("label"), ("Windows", f.get("label", ""), None))
        row = {"label": label, "keys": keycaps(f.get("keys", ""))}
        groups.setdefault(group, [])
        if at is None:
            groups[group].append(row)
        else:
            groups[group].insert(at, row)
    own = [{"label": o.get("name") or o.get("run", ""), "keys": keycaps(o["keys"])} for o in keys.get("own", []) if o.get("keys")]
    if own:
        groups["Your own"] = own
    return [{"title": g, "rows": rows} for g, rows in groups.items() if rows]




def app_streams(text: str) -> list:
    """pactl's sink inputs (JSON) as the control centre lists them: one per stream that has a volume, not the
    desktop's own clicks; its app (name and program), what it says it's playing, volume (%) and mute."""
    try:
        items = json.loads(text or "[]")
    except ValueError:
        return []
    out = []
    for s in items if isinstance(items, list) else []:
        props = s.get("properties") or {}
        if props.get("media.role") == "event" or not s.get("has_volume", True) or props.get("application.id") == "org.huginn.sounds":
            continue
        vols = [v.get("value_percent", "0%") for v in (s.get("volume") or {}).values() if isinstance(v, dict)]
        try:
            vol = round(sum(int(str(v).rstrip("%")) for v in vols) / len(vols)) if vols else 100
        except ValueError:
            vol = 100
        out.append({"index": int(s.get("index", -1)),
                    "app": props.get("application.name") or props.get("application.process.binary") or "Something",
                    "binary": props.get("application.process.binary", ""), "icon": props.get("application.icon_name", ""),
                    "what": props.get("media.name", ""), "volume": vol, "mute": bool(s.get("mute"))})
    return out

def _ptr(obj) -> int:
    """The C++ object behind a Qt wrapper (two wrappers of one window compare equal by it); 0 for none."""
    if obj is None:
        return 0
    try:
        import shiboken6
        return int(shiboken6.getCppPointer(obj)[0])
    except (ImportError, RuntimeError, TypeError):
        return id(obj)

class System(QObject):
    changed = Signal()
    activeChanged = Signal()
    windowsChanged = Signal()
    menusChanged = Signal()
    sceneChanged = Signal()                                # the Overview, snapping, Alt+Tab (Huginn's compositor)
    launcherWanted = Signal()                              # Super on its own (KWin asks)
    searchWanted = Signal(str)                             # Meta+Space: Search everything
    keyWanted = Signal(str)                                # a key for the shell: "today" (Meta+T)…
    tourWanted = Signal()                                  # Huginn's menu: Take the tour again
    shellMenuAction = Signal(str)                          # a menu item the shell itself does (about, aboutApp, appWindows, pin)

    def __init__(self, demo: bool, apps=None):
        super().__init__()
        self._demo = demo
        self._apps = apps
        self._battery = {"present": False, "percent": 0, "charging": False}
        self._network = {"wifiDevice": False, "wifiOn": False, "kind": "none", "name": "", "signal": 0}
        self._bt = {"present": False, "on": False}
        self._levels = {"brightness": -1.0, "volume": 0.0, "muted": False}
        self._app_volumes_read.connect(self._app_volumes_got)          # (read off the window's thread, kept on it)
        self._dnd = False
        self._night = {"available": False, "on": False}
        self._notes = []
        self._active = {"name": "", "appId": "", "caption": "", "maximized": False}
        self._lift_apps = []                                  # Huginn's apps that share the bar's row when filled
        self._windows = []                                 # every window (the dock, the Overview): see _read_windows
        self._spaces = {"current": 0, "names": ["Main"]}
        self._menus = {}                                   # the app in front's menus (the top bar's one menu)
        self._overview, self._snap_preview, self._snap_assist, self._switcher = {}, {}, {}, {}
        self._menu_bus = ""
        self._bt_path = ""
        self._pending = {}                                 # dock clicks waiting for KWin to say if a window was there
        self.sb = self.yb = None
        # Game Mode (Steam in gamescope, huginn-game-session): only where gamescope is, under Huginn's own session
        self._power = {"sleep": True, "restart": True, "shutdown": True, "gamemode": bool(shutil.which("gamescope", path=os.environ.get("PATH", "") + ":/usr/games")) and os.environ.get("XDG_SESSION_DESKTOP") == "huginn"}
        self.lastPower = ""                                 # (tests) the last power action asked for
        self._shooting = False
        # A game has the screen (the compositor's mark, gamemode.rs): the shell lets go of what it can (trimMemory)
        self._game_playing = False
        if not demo:
            self._game_timer = QTimer(self, interval=2000, timeout=self._game_check)
            self._game_timer.start()
        if demo:
            self._battery = {"present": True, "percent": 82, "charging": False}
            self._network = {"wifiDevice": True, "wifiOn": True, "kind": "wifi", "name": "Home", "signal": 78, "wifiName": "Home", "wired": False, "wiredName": ""}
            self._bt = {"present": True, "on": True}
            self._levels = {"brightness": 0.68, "volume": 0.42, "muted": False}
            self._night = {"available": True, "on": False}
            self._notes = [{"app": "Software Update", "summary": "Updates are ready", "body": "3 updates, including Huginn 1.4.", "ago": "2 min"}]
            demo_windows = [("1", "huginn-files", "Documents › Travel", False, False), ("2", "huginn-files", "Pictures › Iceland", False, True),
                            ("3", "huginn-files", "Downloads", True, False), ("4", "huginn-writer", "Iceland trip plan", False, False)]
            self._windows = [{"id": i, "appId": a, "name": "", "title": t, "minimised": m, "active": act, "space": 0}
                             for i, a, t, m, act in demo_windows]
            QTimer.singleShot(0, self._name_windows)
            return
        try:
            self.sb = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(SHELL_XML)
            self.sb.register_object("/org/huginn/Shell", node.interfaces[0], self._shell_call, None, None)
            Gio.bus_own_name_on_connection(self.sb, "org.huginn.Shell", Gio.BusNameOwnerFlags.REPLACE | Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT, None, None)
        except GLib.Error:
            self.sb = None
        try:
            self.yb = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error:
            self.yb = None
        if self.yb:
            self.yb.signal_subscribe("org.freedesktop.UPower", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                     "/org/freedesktop/UPower/devices/DisplayDevice", None, Gio.DBusSignalFlags.NONE, lambda *a: self._later(self._read_battery))
            self.yb.signal_subscribe("org.freedesktop.NetworkManager", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                     "/org/freedesktop/NetworkManager", None, Gio.DBusSignalFlags.NONE, lambda *a: self._later(self._read_network))
            self.yb.signal_subscribe("org.bluez", "org.freedesktop.DBus.Properties", "PropertiesChanged", None, None,
                                     Gio.DBusSignalFlags.NONE, lambda *a: self._later(self._read_bluetooth))
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.instance():
            app = QGuiApplication.instance()
            app.primaryScreenChanged.connect(lambda *_: self.primaryScreenChanged.emit())
            app.screenAdded.connect(lambda *_: self.primaryScreenChanged.emit())
            app.screenRemoved.connect(lambda *_: QTimer.singleShot(0, self.primaryScreenChanged.emit))
            # the main screen chosen in Settings › Displays (Huginn's own compositor keeps it in displays.json)
            folder = Path.home() / ".config" / "huginn"
            folder.mkdir(parents=True, exist_ok=True)
            self._displays_watch = QFileSystemWatcher([str(folder)], self)

            def displays_changed(*_):
                if (folder / "displays.json").exists() and str(folder / "displays.json") not in self._displays_watch.files():
                    self._displays_watch.addPath(str(folder / "displays.json"))
                QTimer.singleShot(200, self.primaryScreenChanged.emit)
            self._displays_watch.directoryChanged.connect(displays_changed)
            self._displays_watch.fileChanged.connect(displays_changed)
            displays_changed()
            QTimer.singleShot(15000, self._offer_arranging)
        self._pump = QTimer(self, interval=40, timeout=lambda: GLib.MainContext.default().iteration(False))
        if not qt_runs_glib():
            self._pump.start()
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        self._notes_watch = QFileSystemWatcher([str(HISTORY.parent)], self)        # a notification came: the dot, the Control Centre
        self._notes_watch.directoryChanged.connect(lambda *_: self._later(self._reread_notes))
        self._notes_watch.fileChanged.connect(lambda *_: self._later(self._reread_notes))
        if HISTORY.exists():
            self._notes_watch.addPath(str(HISTORY))
        self._slow = QTimer(self, interval=20000, timeout=self.refresh)        # the Wi‑Fi signal, and anything missed
        self._slow.start()
        QTimer.singleShot(800, self.refresh)
        QTimer.singleShot(1500, self._read_power)
        QTimer.singleShot(1200, self._ask_kwin)            # KWin's own script reports changes; this asks for the start
        QTimer.singleShot(1300, self._ask_windows)
        QTimer.singleShot(1600, self.readLayouts)

    def _ask_kwin(self):
        """When the shell (re)starts after KWin, ask once which window is in front."""
        if not self.sb or not self._kwin_running():
            return
        self.kwin("""var w = workspace.activeWindow; var full = false;
if (w && w.fullScreen) full = true;
else if (w) { var a = workspace.clientArea(KWin.MaximizeArea, w); full = w.frameGeometry.width >= a.width - 2 && w.frameGeometry.height >= a.height - 2; }
if (!w || w.normalWindow || w.dialog)
    callDBus("org.huginn.Shell", "/org/huginn/Shell", "org.huginn.Shell", "Active", w ? w.caption : "", w ? w.resourceClass : "", w ? w.desktopFileName : "", full);""")

    def _ask_windows(self):
        """The window list, once at the start (afterwards the compositor or KWin's script tells us of changes)."""
        if not self.sb:
            return
        if self._own_compositor():
            got = self._compositor("Windows", None, "(s)")
            if got:
                self._read_windows(got[0])
        elif self._kwin_running():
            self.kwin(WINDOWS_JS + "\nreportWindows();")

    def _read_windows(self, text: str) -> None:
        try:
            data = json.loads(text or "{}")
        except ValueError:
            return
        if isinstance(data, list):                         # an older compositor: just the windows
            data = {"windows": data}
        rows = []
        for w in data.get("windows", []):
            app_id = w.get("app", "")
            pid = int(w.get("pid", 0) or 0)
            rows.append({"id": str(w.get("id", "")), "appId": app_id, "pid": pid, "cls": w.get("cls", ""),
                         "name": self.app_for_window(app_id, w.get("cls", ""), pid),
                         "title": w.get("title", ""), "minimised": bool(w.get("minimised")), "active": bool(w.get("active") or w.get("focused")),
                         "space": int(w.get("space", 0)), "full": bool(w.get("full")), "x": w.get("x", 0), "y": w.get("y", 0), "w": w.get("w", 0), "h": w.get("h", 0),
                         "above": bool(w.get("above")), "screen": w.get("screen", ""), "snap": w.get("snap", ""), "max": bool(w.get("max"))})
        self._windows = rows
        self._others = self._other_apps(rows)
        self._spaces = {"current": int(data.get("current", 0)), "names": list(data.get("spaces") or ["Main"])}
        self.windowsChanged.emit()
        self._place_waiting()

    def _name_windows(self):
        for w in self._windows:
            w["name"] = self.app_for_window(w["appId"], w.get("cls", ""), w.get("pid", 0))   # "" again: _other_apps names the rest
        self._others = self._other_apps(self._windows)
        self.windowsChanged.emit()

    # ------------------------------------------------------------------ which app a window belongs to
    def app_for_window(self, app_id: str, cls: str = "", pid: int = 0) -> str:
        """The name of the installed app a window is from: by its app id or X11 class against each .desktop file's id
        and StartupWMClass, then by the process that made it, then by looser likenesses (org.foo.Bar ~ bar, a
        class that starts with the app's program: steamwebhelper ~ steam). '' when none fits."""
        return (self._app_name(app_id) or self._app_name(cls) or self._app_by_pid(pid)
                or self._app_loose(app_id) or self._app_loose(cls))

    def _app_by_pid(self, pid: int) -> str:
        if not pid or self._apps is None:
            return ""
        try:
            with open(f"/proc/{pid}/environ", "rb") as fh:                 # a Flatpak app says which it is
                env = dict(kv.split(b"=", 1) for kv in fh.read(65536).split(b"\0") if b"=" in kv)
            flatpak = env.get(b"FLATPAK_ID", b"").decode("utf-8", "replace")
            if flatpak:
                found = self._app_name(flatpak)
                if found:
                    return found
        except OSError:
            pass
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                argv = [os.path.basename(a.decode("utf-8", "replace")) for a in fh.read(4096).split(b"\0") if a]
        except OSError:
            return ""
        return self._apps.app_for_argv(argv) if hasattr(self._apps, "app_for_argv") else ""

    GENERIC_PROGRAMS = {"flatpak", "env", "sh", "bash", "python", "python3", "java", "wine", "mono", "electron", "gjs", "exo-open", "xdg-open"}

    def _app_loose(self, wid: str) -> str:
        low = (wid or "").lower().removesuffix(".desktop")
        if len(low) < 3 or self._apps is None:
            return ""
        last = low.rsplit(".", 1)[-1]
        for a in self._apps.all:
            if a.get("web"):
                continue
            ident = a.get("id", "").lower()
            names = {ident, ident.rsplit(".", 1)[-1], a.get("wm", "").lower(), a.get("name", "").lower(), a.get("name", "").lower().replace(" ", "")}
            if low in names or last in names:
                return a["name"]
            try:
                prog = os.path.basename(shlex.split(a.get("exec") or "")[0]).lower()
            except (ValueError, IndexError):
                prog = ""
            if len(prog) >= 4 and prog not in self.GENERIC_PROGRAMS and (low == prog or low.startswith(prog) or last == prog):
                return a["name"]
        return ""

    @staticmethod
    def _pretty(wid: str) -> str:
        """A name for an app nobody installed a .desktop file for: org.example.FooBar -> FooBar, my_game -> My game."""
        last = (wid or "").removesuffix(".desktop").rsplit(".", 1)[-1].replace("_", " ").replace("-", " ").strip()
        return (last[:1].upper() + last[1:]) if last else ""

    def _other_apps(self, rows: list) -> list:
        """Tiles for windows of apps that aren't installed as apps (no .desktop file): named from the window, with
        the icon its app id or class names in the icon theme, if any. Their windows take that name, so the dock
        groups them like any app's."""
        out, seen = [], set()
        for w in rows:
            if w.get("name"):
                continue
            ident = w.get("appId") or w.get("cls") or ""
            name = self._pretty(ident) or (w.get("title") or "").split(" — ")[-1].split(" - ")[-1].strip() or "App"
            w["name"] = name
            if name in seen:
                continue
            seen.add(name)
            image = ""
            if self._apps is not None and hasattr(self._apps, "_image"):
                for cand in (w.get("appId", ""), w.get("cls", ""), (w.get("cls") or "").lower(), (w.get("appId") or "").lower()):
                    image = self._apps._image(cand) if cand else ""
                    if image:
                        break
            out.append({"name": name, "exec": "", "icon": ident, "image": image, "glyph": "", "own": "", "web": False, "id": ident,
                        "wm": ident, "colours": [], "actions": [], "mimes": [], "group": "utilities", "keywords": "", "about": "", "other": True})
        return out



    @Slot(str, str)
    def windowDo(self, wid: str, action: str) -> None:
        """Something done to one window, by its id in the list: activate, minimise, close, toggle (hide it if it's
        in front, else bring it forward), maximise."""
        own = action.startswith(("snap:", "space:", "place:"))  # Huginn's compositor only (KWin: snapFront / spaceDo)
        if action not in ("activate", "minimise", "close", "toggle", "maximise") and not own or not wid:
            return
        if own and (self._demo or not self.sb or not self._own_compositor()):
            return
        if self._demo or not self.sb:
            for w in self._windows:
                if w["id"] == wid:
                    if action == "close":
                        self._windows.remove(w)
                        break
                    hide = action == "minimise" or (action == "toggle" and w["active"] and not w["minimised"])
                    for o in self._windows:
                        o["active"] = False
                    w["minimised"] = hide
                    w["active"] = not hide
                    break
            self.windowsChanged.emit()
            return
        if self._own_compositor():
            self._compositor("WindowDo", GLib.Variant("(ss)", (wid, action)), None)
            return
        do = {"activate": "w.minimized = false; workspace.activeWindow = w;",
              "minimise": "w.minimized = true;",
              "close": "w.closeWindow();",
              "toggle": "if (w === workspace.activeWindow && !w.minimized) w.minimized = true; else { w.minimized = false; workspace.activeWindow = w; }",
              "maximise": "w.minimized = false; workspace.activeWindow = w; w.setMaximize(true, true);"}[action]
        self.kwin(f"""var all = workspace.windowList();
for (var i = 0; i < all.length; i++) {{ var w = all[i]; if (String(w.internalId) === {json.dumps(wid)}) {{ {do} break; }} }}""")

    # ------------------------------------------------------------------ the app in front's menus
    def _huginn_menus(self) -> dict:
        """With nothing in front, the name in the bar is Huginn: the desktop's own menu."""
        def it(label, act, keys=""):
            return {"label": label, "id": act, "keys": keys, "enabled": True}
        return {"app": "Huginn", "key": "huginn", "groups": [],
                "top": [it("About Huginn OS", "shell:about"), it("Settings…", "shell:settings", "Ctrl+,")],
                "middle": [it("Change wallpaper…", "shell:wallpaper"), it("Desktop & Dock settings…", "shell:desktop"), it("Show the desktop", "shell:showDesktop", "Super+D"),
                           {"sep": True}, it("Help", "shell:help", "F1"), it("Take the tour again", "shell:tour")],
                "bottom": []}

    def _basic_menus(self, name: str) -> dict:
        """An app that doesn't share its menus: the same basics as every other app's, so the menu is never empty."""
        def it(label, act, keys="", on=True):
            return {"label": label, "id": act, "keys": keys, "enabled": on}
        return {"app": name, "key": "", "groups": [],
                "top": [it(f"About {name}", "shell:aboutApp"), it(f"{name} Settings…", "", "Ctrl+,", False)],
                "middle": [it("Show all its windows", "shell:appWindows"), it("Keep in the dock", "shell:pin")],
                "bottom": [it("Keep on Top", "shell:ontop", "Super+Ctrl+T"), it("Minimise", "shell:minimise"), it("Close window", "shell:close", "Ctrl+W"),
                           it(f"Quit {name}", "shell:quit", "Ctrl+Q")]}

    def _front_window(self):
        """The window whose app is in the bar (the shell's own panels can have the keyboard meanwhile). The bar's app
        (Active) and the window list come separately from the compositor; when the list is a moment behind, the
        window it calls active can be the previous app's, and its menus would sit under this app's name. So the
        app in the bar decides: its active window, else its newest one."""
        want = (self._active.get("appId") or "").lower()
        if want:
            mine = [w for w in self._windows if not w.get("minimised") and (w.get("appId", "").lower() == want or w.get("cls", "").lower() == want)]
            if mine:
                return next((w for w in mine if w.get("active")), mine[-1])
        return next((w for w in self._windows if w.get("active") and not w.get("minimised")), None)

    @Slot()
    def loadMenus(self) -> None:
        name = self._active.get("name") or ""
        front = self._front_window()
        if not name or front is None and not self._demo:
            self._menu_bus = ""
            self._menus = self._huginn_menus()
            self.menusChanged.emit()
            return
        self._menus = self._on_top_label(self._basic_menus(name), front)
        self._menu_bus = ""
        self.menusChanged.emit()
        pid = (front or {}).get("pid", 0)
        if self._demo or not self.sb or not pid:
            return
        bus = f"org.huginn.App.p{pid}"

        def got(conn, res):
            try:
                text = conn.call_finish(res).unpack()[0]
                data = json.loads(text)
            except (GLib.Error, ValueError):
                return
            if data.get("groups") is not None:
                data.setdefault("middle", [])
                self._menus = self._on_top_label(data, front)
                self._menu_bus = bus
                self.menusChanged.emit()
        self.sb.call(bus, "/org/huginn/App", "org.huginn.App", "Menus", None, GLib.VariantType("(s)"),
                     Gio.DBusCallFlags.NO_AUTO_START, 1500, None, got)

    @staticmethod
    def _on_top_label(menus: dict, front) -> dict:
        """"Keep on Top" says "Stop Keeping on Top" while the window in front is kept on top."""
        above = bool((front or {}).get("above"))
        for key in ("top", "middle", "bottom"):
            for it in menus.get(key) or []:
                if it.get("id") == "shell:ontop":
                    it["label"] = "Stop Keeping on Top" if above else "Keep on Top"
        for g in menus.get("groups") or []:
            for it in g.get("items") or []:
                if isinstance(it, dict) and it.get("id") == "shell:ontop":
                    it["label"] = "Stop Keeping on Top" if above else "Keep on Top"
        return menus

    @Slot(result=str)
    def gameStats(self) -> str:
        """The game stats overlay (Super+Alt+G), as JSON: the frames of the window a game plays in on each screen
        (Huginn's compositor counts them), and the graphics card's and processor's readings (huginn_hwstats)."""
        if getattr(self, "_hw", None) is None:
            import huginn_hwstats
            self._hw = huginn_hwstats.Readings()
        windows = []
        if self.sb and self._own_compositor():
            got = self._compositor("GameStats", None, "(s)")
            try:
                windows = json.loads(got[0]) if got else []
            except ValueError:
                windows = []
        return json.dumps({"windows": windows, "gpu": self._hw.gpu(), "cpu": self._hw.cpu()})

    @Slot(result=str)
    def frameStats(self) -> str:
        """Frame times on each screen over the last second (Huginn's compositor), as JSON."""
        if not self.sb or not self._own_compositor():
            return "[]"
        got = self._compositor("FrameStats", None, "(s)")
        return got[0] if got else "[]"

    @Slot(str)
    def menuTrigger(self, act: str) -> None:
        if not act:
            return
        if act.startswith("shell:"):
            what = act[6:]
            front = self._front_window()
            if what == "minimise":
                self.windowAction("minimise")
            elif what == "close":
                self.windowAction("close")
            elif what == "ontop":
                self.windowAction("ontop")
            elif what == "quit" and front:
                for w in [w for w in self._windows if w.get("name") == front.get("name")]:
                    self.windowDo(w["id"], "close")
            elif what in ("settings", "wallpaper", "desktop"):
                self.openSettings({"settings": "", "wallpaper": "appearance", "desktop": "desktop"}[what])
            elif what == "help":
                QProcess_start("help")
            elif what == "tour":
                self.tourWanted.emit()
            elif what == "showDesktop":
                for w in self._windows:
                    if not w.get("minimised"):
                        self.windowDo(w["id"], "minimise")
            else:
                self.shellMenuAction.emit(what)
            return
        if self._menu_bus and self.sb:
            self.sb.call(self._menu_bus, "/org/huginn/App", "org.huginn.App", "Trigger", GLib.Variant("(s)", (act,)), None,
                         Gio.DBusCallFlags.NO_AUTO_START, 1500, None, None)

    # ------------------------------------------------------------------ the Overview, spaces, snapping
    @Slot(str)
    def overviewDo(self, action: str) -> None:
        """The Overview: toggle, close, activate:ID, dim:ID,ID… (KWin: its own Overview, for toggle)."""
        if self._demo or not self.sb:
            return
        if self._own_compositor():
            self._compositor("OverviewDo", GLib.Variant("(s)", (action,)), None)
        elif self._kwin_running() and action in ("toggle", "open"):
            try:
                self.sb.call_sync("org.kde.kglobalaccel", "/component/kwin", "org.kde.kglobalaccel.Component", "invokeShortcut",
                                  GLib.Variant("(s)", ("Overview",)), None, 0, 1500, None)
            except GLib.Error:
                pass

    @Slot(str)
    def spaceDo(self, action: str) -> None:
        """Spaces: switch:N, add, remove:N, rename:N:name, move:ID:N, reorder:A:B."""
        if self._demo or not self.sb:
            return
        if self._own_compositor():
            self._compositor("SpaceDo", GLib.Variant("(s)", (action,)), None)
            return
        parts = action.split(":", 2)
        what, a, b = (parts + ["", "", ""])[:3]
        js = {"switch": f"var d = workspace.desktops[{int(a or 0)}]; if (d) workspace.currentDesktop = d;",
              "add": "workspace.createDesktop(workspace.desktops.length, 'Space ' + (workspace.desktops.length + 1));",
              "remove": f"var d = workspace.desktops[{int(a or 0)}]; if (d && workspace.desktops.length > 1) workspace.removeDesktop(d);",
              "rename": f"var d = workspace.desktops[{int(a or 0) if a.isdigit() else 0}]; if (d) d.name = {json.dumps(b)};",
              "move": f"var d = workspace.desktops[{int(b or 0) if b.isdigit() else 0}]; var all = workspace.windowList();"
                      f" for (var i = 0; i < all.length; i++) if (String(all[i].internalId) === {json.dumps(a)} && d) all[i].desktops = [d];"}.get(what)
        if js:
            self.kwin(js + "\n" + WINDOWS_JS + "\nreportWindows();")

    # ---- a filled app under the island top bar: it reaches up behind the bar, its top islands beside the shell's.
    # The apps that can (GlassWindow.qml) say so (Lift); the compositor is told which (DockLayout: liftApps); and
    # the apps read where the bar's own islands end from a file the shell keeps (apps/huginn_menu.py: barInsets).
    liftAppsChanged = Signal()
    BAR_FILE = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "huginn" / "bar.json"
    liftApps = Property("QVariantList", lambda self: list(self._lift_apps), notify=liftAppsChanged)

    @Slot(str)
    def setBarInsets(self, text: str) -> None:
        """{"h": the bar's height (0: no islands), "left": where the shell's left islands end, "right": how far in
        the right one starts, "screens": [names of the screens with a bar]}"""
        if self._demo or text == getattr(self, "_bar_text", None):
            return
        self._bar_text = text
        try:
            self.BAR_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.BAR_FILE.with_suffix(".tmp")
            tmp.write_text(text)
            tmp.replace(self.BAR_FILE)
        except OSError:
            pass

    @Slot(QObject, "QVariantList")
    def setInputRects(self, window, rects) -> None:
        """Only these parts of a shell window take the pointer (the top bar's islands: between them, what's under it)."""
        from PySide6.QtGui import QRegion
        from PySide6.QtCore import QRect
        if window is None or not hasattr(window, "setMask"):
            return
        if hasattr(rects, "toVariant"):
            rects = rects.toVariant()
        region = QRegion()
        for r in rects or []:
            try:
                x, y, w, h = (int(round(float(v))) for v in list(r)[:4])
            except (TypeError, ValueError):
                continue
            if w > 0 and h > 0:
                region = region.united(QRegion(QRect(x, y, w, h)))
        window.setMask(region if not region.isEmpty() else QRegion(QRect(0, 0, 1, 1)))

    @Slot(str)
    def dockLayout(self, text: str) -> None:
        """Where the dock's tiles are (windows hide into them) and how: for Huginn's compositor."""
        if self._demo or not self.sb or not self._own_compositor():
            return
        self._compositor("DockLayout", GLib.Variant("(s)", (text,)), None)

    @Slot(str)
    def snapFront(self, layout: str) -> None:
        """The window in front, snapped: left, right, max, top-left…, left-third, right-two-thirds… (its fill button)."""
        front = self._front_window()
        if not front or self._demo or not self.sb:
            return
        if self._own_compositor():
            self.windowDo(front["id"], "snap:" + layout)
            return
        part = {"left": (0, 0, .5, 1), "right": (.5, 0, .5, 1), "max": (0, 0, 1, 1), "top-left": (0, 0, .5, .5), "top-right": (.5, 0, .5, .5),
                "bottom-left": (0, .5, .5, .5), "bottom-right": (.5, .5, .5, .5), "left-third": (0, 0, 1 / 3, 1), "right-third": (2 / 3, 0, 1 / 3, 1),
                "left-two-thirds": (0, 0, 2 / 3, 1), "right-two-thirds": (1 / 3, 0, 2 / 3, 1), "middle-third": (1 / 3, 0, 1 / 3, 1),
                "top-half": (0, 0, 1, .5), "bottom-half": (0, .5, 1, .5)}.get(layout)
        if part:
            x, y, w, h = part
            self.kwin(f"""var all = workspace.windowList();
for (var i = 0; i < all.length; i++) {{ var win = all[i]; if (String(win.internalId) !== {json.dumps(front['id'])}) continue;
  var a = workspace.clientArea(KWin.MaximizeArea, win), g = 8;
  win.frameGeometry = {{ x: a.x + g + (a.width - 2 * g) * {x} + ({x} > 0 ? g / 2 : 0), y: a.y + g + (a.height - 2 * g) * {y} + ({y} > 0 ? g / 2 : 0),
                        width: (a.width - 2 * g) * {w} - ({w} < 1 ? g / 2 : 0), height: (a.height - 2 * g) * {h} - ({h} < 1 ? g / 2 : 0) }}; }}""")

    # ---------------------------------------------------------------- window sets (Layouts, Super+Z)
    # The windows on screen now, kept under a name: each one's app, screen and place on it (snapped part, filled, or
    # its share of the screen). Putting a set back moves the app's windows that are open there and starts the apps
    # that aren't (the shell starts them; their windows are placed as they appear, for up to a minute).
    def _sets_file(self) -> Path:
        return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn" / "window-sets.json"

    def _read_sets(self) -> list:
        if self._demo:
            return getattr(self, "_demo_sets", None) or [
                {"name": "Writing", "saved": 0, "windows": [{"app": "Writer", "appId": "huginn-writer", "screen": "DP-1", "snap": "left-two-thirds"},
                                                           {"app": "Notes", "appId": "huginn-notes", "screen": "DP-1", "snap": "right-third"}]},
                {"name": "Gaming", "saved": 0, "windows": [{"app": "Discord", "appId": "discord", "screen": "HDMI-A-1", "snap": "max"},
                                                          {"app": "Steam", "appId": "steam", "screen": "DP-2", "snap": "left"}, {"app": "Huginn", "appId": "huginn", "screen": "DP-2", "snap": "right"}]}]
        try:
            data = json.loads(self._sets_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [d for d in data if isinstance(d, dict) and d.get("name") and isinstance(d.get("windows"), list)] if isinstance(data, list) else []

    windowSetsChanged = Signal()

    def _get_sets(self) -> list:
        out = []
        for d in self._read_sets():
            apps = []
            for w in d["windows"]:
                if w.get("app") and w["app"] not in apps:
                    apps.append(w["app"])
            out.append({"name": d["name"], "count": len(d["windows"]), "apps": ", ".join(apps[:4]) + (f" and {len(apps) - 4} more" if len(apps) > 4 else ""),
                        "screens": len({w.get("screen") for w in d["windows"]})})
        return out
    windowSets = Property("QVariantList", _get_sets, notify=windowSetsChanged)

    @Slot(str, result=str)
    def saveWindowSet(self, name: str) -> str:
        """Keep the windows on screen now as a set. Returns "" or why it couldn't."""
        from PySide6.QtGui import QGuiApplication
        name = " ".join(name.split())[:40] or "Windows"
        current = self._spaces.get("current", 0) if isinstance(getattr(self, "_spaces", None), dict) else 0
        shown = [w for w in self._windows if not w.get("minimised") and int(w.get("space", 0)) == current and (w.get("name") or w.get("appId"))]
        if not shown:
            return "There are no windows on screen to keep."
        screens = [(sc.name(), sc.geometry()) for sc in (QGuiApplication.screens() if QGuiApplication.instance() else [])]

        def screen_of(w):
            for n, g in screens:
                if n == w.get("screen"):
                    return n, g
            cx, cy = w.get("x", 0) + w.get("w", 0) / 2, w.get("y", 0) + w.get("h", 0) / 2
            for n, g in screens:
                if g.x() <= cx < g.x() + g.width() and g.y() <= cy < g.y() + g.height():
                    return n, g
            return (screens[0] if screens else (w.get("screen", ""), None))
        rows = []
        for w in shown:
            n, g = screen_of(w)
            row = {"app": w.get("name", ""), "appId": w.get("appId", ""), "screen": w.get("screen") or n}
            if w.get("snap"):
                row["snap"] = w["snap"]
            elif w.get("max") or w.get("full"):
                row["snap"] = "max"
            elif g is not None and g.width() and g.height():
                row.update({"fx": round(max(0.0, (w.get("x", 0) - g.x()) / g.width()), 4), "fy": round(max(0.0, (w.get("y", 0) - g.y()) / g.height()), 4),
                            "fw": round(min(1.0, w.get("w", 0) / g.width()), 4), "fh": round(min(1.0, w.get("h", 0) / g.height()), 4)})
            rows.append(row)
        sets = [d for d in self._read_sets() if d["name"].lower() != name.lower()]
        sets.insert(0, {"name": name, "saved": int(time.time()), "windows": rows})
        if self._demo:
            self._demo_sets = sets
        else:
            try:
                path = self._sets_file()
                path.parent.mkdir(parents=True, exist_ok=True)
                part = path.with_name(".window-sets.json.saving")
                part.write_text(json.dumps(sets[:20], indent=1), encoding="utf-8")
                os.replace(part, path)
            except OSError as err:
                return f"Couldn't keep it: {err.strerror or err}"
        self.windowSetsChanged.emit()
        return ""

    @Slot(str)
    def removeWindowSet(self, name: str) -> None:
        sets = [d for d in self._read_sets() if d["name"] != name]
        if self._demo:
            self._demo_sets = sets
        else:
            try:
                self._sets_file().write_text(json.dumps(sets, indent=1), encoding="utf-8")
            except OSError:
                return
        self.windowSetsChanged.emit()

    @Slot(str, result="QVariantList")
    def putBackWindowSet(self, name: str) -> list:
        """Move the set's apps' open windows into place. Returns the apps to start (by name): their windows are
        placed as they appear."""
        entry = next((d for d in self._read_sets() if d["name"] == name), None)
        if not entry:
            return []
        used, missing = set(), []
        for item in entry["windows"]:
            w = self._window_for(item, used)
            if w:
                used.add(w["id"])
                self._place(w["id"], item)
            else:
                missing.append(item)
        self._set_waiting = {"items": missing, "until": time.time() + 60, "known": {w["id"] for w in self._windows}}
        return [i.get("app", "") for i in missing if i.get("app")]

    def _window_for(self, item: dict, used: set, among: list = None):
        for w in among if among is not None else self._windows:
            if w["id"] in used:
                continue
            if (item.get("app") and w.get("name") == item["app"]) or (item.get("appId") and w.get("appId") == item["appId"]):
                return w
        return None

    def _place(self, wid: str, item: dict) -> None:
        screen = item.get("screen", "")
        if item.get("snap"):
            self.windowDo(wid, f"snap:{item['snap']}" + (f"@{screen}" if screen else ""))
        elif all(k in item for k in ("fx", "fy", "fw", "fh")):
            self.windowDo(wid, f"place:{screen}:{item['fx']},{item['fy']},{item['fw']},{item['fh']}")

    def _place_waiting(self) -> None:
        wait = getattr(self, "_set_waiting", None)
        if not wait or not wait["items"]:
            return
        if time.time() > wait["until"]:
            self._set_waiting = None
            return
        new = [w for w in self._windows if w["id"] not in wait["known"] and not w.get("minimised")]
        used = set()
        for item in list(wait["items"]):
            w = self._window_for(item, used, new)
            if w:
                used.add(w["id"])
                wait["items"].remove(item)
                wid = w["id"]
                QTimer.singleShot(350, lambda wid=wid, item=item: self._place(wid, item))   # (once it has its first size)
        wait["known"] |= used

    @Slot()
    def assistDone(self) -> None:
        self._snap_assist = {}
        self.sceneChanged.emit()

    def _later(self, fn):
        QTimer.singleShot(150, fn)

    # ------------------------------------------------------------------ reading
    def _get(self, bus, name, path, iface, prop, default=None):
        try:
            v = bus.call_sync(name, path, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (iface, prop)),
                              GLib.VariantType("(v)"), 0, 1500, None)
            return v.unpack()[0]
        except (GLib.Error, AttributeError):
            return default

    @Slot()
    def refresh(self) -> None:
        if self._demo:
            return
        self._read_battery()
        self._read_network()
        self._read_bluetooth()
        self._read_night()
        self.changed.emit()

    def _read_battery(self) -> None:
        if not self.yb:
            return
        dev = "/org/freedesktop/UPower/devices/DisplayDevice"
        kind = self._get(self.yb, "org.freedesktop.UPower", dev, "org.freedesktop.UPower.Device", "Type", 0)
        present = bool(self._get(self.yb, "org.freedesktop.UPower", dev, "org.freedesktop.UPower.Device", "IsPresent", False)) and kind == 2
        pct = self._get(self.yb, "org.freedesktop.UPower", dev, "org.freedesktop.UPower.Device", "Percentage", 0.0) or 0.0
        state = self._get(self.yb, "org.freedesktop.UPower", dev, "org.freedesktop.UPower.Device", "State", 0)
        self._battery = {"present": present, "percent": int(round(pct)), "charging": state in (1, 4)}
        self.changed.emit()

    def _read_network(self) -> None:
        if not self.yb:
            return
        nm, base = "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager"
        out = {"wifiDevice": False, "wifiOn": bool(self._get(self.yb, nm, base, nm, "WirelessEnabled", False)), "kind": "none", "name": "", "signal": 0,
               "wifiName": "", "wired": False, "wiredName": ""}
        devices = self._get(self.yb, nm, base, nm, "Devices", []) or []

        def active_id(d):
            """The connection a device is using (each device's own, not only the one the internet goes through)."""
            ac = self._get(self.yb, nm, d, nm + ".Device", "ActiveConnection", "/")
            if not ac or ac == "/" or self._get(self.yb, nm, ac, nm + ".Connection.Active", "State", 0) != 2:   # 2: activated
                return ""
            return self._get(self.yb, nm, ac, nm + ".Connection.Active", "Id", "") or ""
        for d in devices:
            kind = self._get(self.yb, nm, d, nm + ".Device", "DeviceType", 0)
            if kind == 2:
                out["wifiDevice"] = True
                out["wifiName"] = out["wifiName"] or active_id(d)
                ap = self._get(self.yb, nm, d, nm + ".Device.Wireless", "ActiveAccessPoint", "/")
                if ap and ap != "/":
                    out["signal"] = int(self._get(self.yb, nm, ap, nm + ".AccessPoint", "Strength", 0) or 0)
            elif kind == 1:
                name = active_id(d)
                if name:
                    out["wired"], out["wiredName"] = True, out["wiredName"] or name
        primary = self._get(self.yb, nm, base, nm, "PrimaryConnection", "/")
        if primary and primary != "/":
            kind = self._get(self.yb, nm, primary, nm + ".Connection.Active", "Type", "") or ""
            out["name"] = self._get(self.yb, nm, primary, nm + ".Connection.Active", "Id", "") or ""
            out["kind"] = "wifi" if "wireless" in kind else "wired" if "ethernet" in kind else "vpn" if kind in ("vpn", "wireguard") else "other"
        self._network = out
        self.changed.emit()

    def _read_bluetooth(self) -> None:
        if not self.yb:
            return
        try:
            got = self.yb.call_sync("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", None,
                                    GLib.VariantType("(a{oa{sa{sv}}})"), 0, 1500, None).unpack()[0]
        except GLib.Error:
            got = {}
        self._bt_path = next((p for p, ifs in got.items() if "org.bluez.Adapter1" in ifs), "")
        on = bool(got[self._bt_path]["org.bluez.Adapter1"].get("Powered", False)) if self._bt_path else False
        self._bt = {"present": bool(self._bt_path), "on": on}
        self.changed.emit()

    NIGHT = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kwinrc"

    def _read_night(self) -> None:
        """Night light is Huginn's session daemon's (huginn_sessiond.night_light): Settings › Displays keeps it in
        [NightColor] of kwinrc (the name it has had since KWin), and the daemon follows that file."""
        on = False
        try:
            group = ""
            for line in self.NIGHT.read_text(encoding="utf-8").splitlines():
                t = line.strip()
                if t.startswith("["):
                    group = t
                elif group == "[NightColor]" and t.startswith("Active="):
                    on = t.split("=", 1)[1].strip() == "true"
        except OSError:
            pass
        self._night = {"available": not self._demo, "on": on}

    @Slot()
    def refreshPanel(self) -> None:
        """When the control centre opens: the sliders, Do Not Disturb and the notifications as they are now."""
        if self._demo:
            return
        if self.sb:
            try:
                b, v, m = self.sb.call_sync("org.huginn.Session", "/org/huginn/Session", "org.huginn.Session", "Levels", None,
                                            GLib.VariantType("(ddb)"), 0, 2000, None).unpack()
                self._levels = {"brightness": b, "volume": v, "muted": m}
            except GLib.Error:
                pass
            self._dnd = bool(self._get(self.sb, "org.huginn.Session", "/org/huginn/Session", "org.huginn.Session", "DoNotDisturb", False))
        self._notes = self._read_notes()
        self.refresh()

    @staticmethod
    def _history_lines() -> list:
        try:
            return HISTORY.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

    @staticmethod
    def _read_notes() -> list:
        """What came since Clear all, grouped by app (the newest of each, and how many more), newest app first."""
        lines = System._history_lines()[-60:]
        try:
            cleared = int(CLEARED_NOTES.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            cleared = 0
        out, at = [], {}
        for line in reversed(lines):
            try:
                n = json.loads(line)
            except ValueError:
                continue
            if int(n.get("at", 0)) <= cleared:
                continue
            app = n.get("app", "")
            if app in at:
                out[at[app]]["more"] += 1
                continue
            if len(out) >= 6:
                continue
            ago = max(0, int(time.time()) - int(n.get("at", 0)))
            text = "now" if ago < 60 else f"{ago // 60} min" if ago < 3600 else f"{ago // 3600} h" if ago < 86400 else f"{ago // 86400} d"
            at[app] = len(out)
            out.append({"app": app, "summary": n.get("summary", ""), "body": n.get("body", ""), "ago": text, "at": int(n.get("at", 0)), "more": 0,
                        "icon": n.get("icon", "")})
        return out

    def _reread_notes(self) -> None:
        if HISTORY.exists() and str(HISTORY) not in self._notes_watch.files():
            self._notes_watch.addPath(str(HISTORY))
        notes = self._read_notes()
        if notes != self._notes:
            self._notes = notes
            self.changed.emit()

    def _waiting(self) -> bool:
        """Notifications came since the Control Centre was last opened: a dot by the status icons."""
        try:
            seen = float(SEEN_NOTES.read_text(encoding="utf-8") or 0)
        except (OSError, ValueError):
            seen = 0
        return any(n.get("at", 0) > seen for n in self._notes)

    @Slot()
    def notesSeen(self) -> None:
        try:
            SEEN_NOTES.parent.mkdir(parents=True, exist_ok=True)
            SEEN_NOTES.write_text(str(time.time()), encoding="utf-8")
        except OSError:
            pass
        self.changed.emit()

    @Slot(bool)
    def setBusyScreen(self, busy: bool) -> None:
        """Something has the whole screen, or it's being shared: notifications wait quietly (calls and alarms don't)."""
        try:
            if busy:
                BUSY_FLAG.write_text("1", encoding="utf-8")
            elif BUSY_FLAG.exists():
                BUSY_FLAG.unlink()
        except OSError:
            pass

    # ------------------------------------------------------------------ changing
    def _set(self, bus, name, path, iface, prop, value) -> None:
        if bus:
            bus.call(name, path, "org.freedesktop.DBus.Properties", "Set", GLib.Variant("(ssv)", (iface, prop, value)),
                     None, 0, 3000, None, lambda *a: self._later(self.refresh))

    @Slot(bool)
    def setWifi(self, on: bool) -> None:
        self._network = dict(self._network, wifiOn=on)
        self.changed.emit()
        if not self._demo:
            self._set(self.yb, "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager",
                      "WirelessEnabled", GLib.Variant("b", on))

    @Slot(bool)
    def setBluetooth(self, on: bool) -> None:
        self._bt = dict(self._bt, on=on)
        self.changed.emit()
        if not self._demo and self._bt_path:
            self._set(self.yb, "org.bluez", self._bt_path, "org.bluez.Adapter1", "Powered", GLib.Variant("b", on))

    def _session(self, method, args=None):
        if self.sb:
            self.sb.call("org.huginn.Session", "/org/huginn/Session", "org.huginn.Session", method, args, None, 0, 3000, None, None)

    @Slot(float)
    def setBrightness(self, level: float) -> None:
        self._levels = dict(self._levels, brightness=level)
        self.changed.emit()
        if not self._demo:
            self._session("SetBrightness", GLib.Variant("(d)", (level,)))

    @Slot(float)
    def setVolume(self, level: float) -> None:
        self._levels = dict(self._levels, volume=level, muted=False)
        self.changed.emit()
        if not self._demo:
            self._session("SetVolume", GLib.Variant("(d)", (level,)))

    @Slot(bool)
    def setMuted(self, muted: bool) -> None:
        self._levels = dict(self._levels, muted=muted)
        self.changed.emit()
        if not self._demo:
            self._session("SetMuted", GLib.Variant("(b)", (muted,)))

    # ---------------------------------------------------------------- each app's own volume (the control centre)
    appVolumesChanged = Signal()
    appVolumes = Property("QVariantList", lambda self: getattr(self, "_app_volumes", []), notify=appVolumesChanged)

    @Slot()
    def loadAppVolumes(self) -> None:
        """What's playing sound now, each with its volume (PipeWire's streams, through pactl): read off the window's
        thread; the control centre asks every second or two while it's open."""
        if self._demo:
            self._app_volumes = [{"index": 41, "app": "Music", "binary": "huginn-music", "icon": "", "what": "Northbound", "volume": 82, "mute": False},
                                 {"index": 57, "app": "Discord", "binary": "Discord", "icon": "discord", "what": "Voice", "volume": 64, "mute": False},
                                 {"index": 63, "app": "Steam", "binary": "steamwebhelper", "icon": "steam", "what": "Game audio", "volume": 100, "mute": True}]
            self.appVolumesChanged.emit()
            return
        if not shutil.which("pactl") or getattr(self, "_app_volumes_busy", False):
            return
        self._app_volumes_busy = True

        def read():
            try:
                out = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True, text=True, timeout=3).stdout
            except (OSError, subprocess.TimeoutExpired):
                out = ""
            self._app_volumes_busy = False
            self._app_volumes_read.emit(app_streams(out))
        threading.Thread(target=read, daemon=True).start()

    _app_volumes_read = Signal(list)

    def _app_volumes_got(self, items: list) -> None:
        if items != getattr(self, "_app_volumes", []):
            self._app_volumes = items
            self.appVolumesChanged.emit()

    @Slot(int, int)
    def setAppVolume(self, index: int, percent: int) -> None:
        percent = max(0, min(150, percent))
        self._app_volumes = [dict(a, volume=percent, mute=False) if a["index"] == index else a for a in getattr(self, "_app_volumes", [])]
        self.appVolumesChanged.emit()
        if not self._demo and shutil.which("pactl"):
            threading.Thread(target=lambda: subprocess.run(["pactl", "set-sink-input-volume", str(index), f"{percent}%"], capture_output=True, timeout=3)
                             and subprocess.run(["pactl", "set-sink-input-mute", str(index), "0"], capture_output=True, timeout=3), daemon=True).start()

    @Slot(int, bool)
    def setAppMuted(self, index: int, mute: bool) -> None:
        self._app_volumes = [dict(a, mute=mute) if a["index"] == index else a for a in getattr(self, "_app_volumes", [])]
        self.appVolumesChanged.emit()
        if not self._demo and shutil.which("pactl"):
            threading.Thread(target=lambda: subprocess.run(["pactl", "set-sink-input-mute", str(index), "1" if mute else "0"], capture_output=True, timeout=3),
                             daemon=True).start()

    @Slot(result=bool)
    def micMuted(self) -> bool:
        """Whether the microphone (PipeWire's default source) is muted (the game bar)."""
        if self._demo or not shutil.which("wpctl"):
            return False
        try:
            out = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"], capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.TimeoutExpired):
            return False
        return "[MUTED]" in out

    @Slot(bool)
    def setMicMuted(self, muted: bool) -> None:
        if self._demo or not shutil.which("wpctl"):
            return
        try:
            subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "1" if muted else "0"], timeout=3,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            pass

    @Slot(bool)
    def setDnd(self, on: bool) -> None:
        self._dnd = on
        self.changed.emit()
        if not self._demo:
            self._session("SetDoNotDisturb", GLib.Variant("(b)", (on,)))

    @Slot(bool)
    def setNightLight(self, on: bool) -> None:
        self._night = dict(self._night, on=on)
        self.changed.emit()
        if self._demo:
            return
        try:
            lines = self.NIGHT.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        start = next((i for i, line in enumerate(lines) if line.strip() == "[NightColor]"), -1)
        value = "Active=" + ("true" if on else "false")
        if start < 0:
            lines += (["" ] if lines and lines[-1].strip() else []) + ["[NightColor]", value]
        else:
            end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
            hit = next((i for i in range(start + 1, end) if lines[i].strip().startswith("Active=")), -1)
            if hit >= 0:
                lines[hit] = value
            else:
                lines.insert(start + 1, value)
        try:
            self.NIGHT.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.NIGHT.with_name(".kwinrc.saving")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(tmp, self.NIGHT)                  # (the session daemon sees ~/.config change, and follows)
        except OSError:
            pass

    # ------------------------------------------------------------------ keyboard layouts, the screen reader, the bell
    layoutsChanged = Signal()

    @Slot()
    def readLayouts(self) -> None:
        """The keyboard layouts and the one in use (Huginn's compositor), for the top bar's indicator."""
        if self._demo or not self.sb or not self._own_compositor():
            return
        got = self._compositor("KeyboardLayout", None, "(s)")
        try:
            data = json.loads(got[0]) if got and got[0] else {}
        except ValueError:
            data = {}
        if data != getattr(self, "_layouts", {}):
            self._layouts = data
            self.layoutsChanged.emit()

    @Slot()
    def nextLayout(self) -> None:
        if not self._demo and self.sb:
            self._compositor("SetKeyboardLayout", GLib.Variant("(i)", (-1,)), None)

    keyboardLayouts = Property("QVariantMap", lambda self: getattr(self, "_layouts", {}), notify=layoutsChanged)

    @Slot()
    def toggleReader(self) -> None:
        """Super+Alt+S: the screen reader (Orca) on or off, from anywhere, the same switch as Settings › Accessibility."""
        if self._demo:
            return
        import huginn_settings as hs
        acc = hs.CONFIG / "kaccessrc"
        on = hs.kconfig_read(acc, ["ScreenReader"], "Enabled", "false") != "true"
        if on and not shutil.which("orca"):
            return
        hs.kconfig_write(acc, ["ScreenReader"], "Enabled", on)

        def work():                                        # (waited for here, so nothing is left behind as a zombie)
            quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if shutil.which("gsettings"):
                subprocess.run(["gsettings", "set", "org.gnome.desktop.a11y.applications", "screen-reader-enabled", "true" if on else "false"],
                               timeout=10, check=False, **quiet)
            if on:
                subprocess.run(["setsid", "-f", "orca", "--replace"], timeout=10, check=False, **quiet)   # Orca outlives the call
            else:
                subprocess.run(["pkill", "-x", "orca"], timeout=10, check=False, **quiet)
        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def playEffect(self, kind: str) -> None:
        """One of Huginn's little sounds (huginn_sounds.py): "bell" is the alert sound Settings › Sound chose."""
        if self._demo:
            return
        try:
            import huginn_sounds
            huginn_sounds.play(kind)
        except Exception:                                  # noqa: BLE001  (no sound is better than a stuck shell)
            pass

    @Slot()
    def clearNotifications(self) -> None:
        self._notes = []
        self.changed.emit()
        if not self._demo:
            self._session("ClearNotifications")

    @Slot(result="QVariantList")
    def notificationHistory(self) -> list:
        """Every notification of the last week (Settings › Notifications › Keep a history), newest first, each with its
        day ("Today", "Yesterday", "Thu 19 Nov") for the Control Centre's History."""
        if self._demo:
            now = time.time()
            rows = [("Mail", "Astrid Berg", "Lunch on Friday? I found a place by the harbour.", now - 600),
                    ("Calendar", "Dentist in 30 minutes", "Tomorrow 09:00", now - 3600 * 3),
                    ("Steam", "Download complete", "Hollow Knight is ready to play.", now - 3600 * 7),
                    ("Software Update", "Updates installed", "Restart to finish.", now - 86400 * 1.2),
                    ("Messages", "Sam", "See you at 6!", now - 86400 * 2.5)]
            lines = [json.dumps({"app": a, "summary": t, "body": b, "time": time.strftime("%H:%M", time.localtime(at)), "at": int(at), "icon": ""})
                     for a, t, b, at in reversed(rows)]
        else:
            lines = self._history_lines()
        out, today = [], time.localtime()
        for line in reversed(lines):
            try:
                n = json.loads(line)
                t = time.localtime(int(n.get("at", 0)))
            except (ValueError, OverflowError):
                continue
            days = (time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))
                    - time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))) // 86400
            day = "Today" if days <= 0 else "Yesterday" if days == 1 else time.strftime("%a %d %b", t)
            out.append({"app": n.get("app", ""), "summary": n.get("summary", ""), "body": n.get("body", ""), "icon": n.get("icon", ""),
                        "time": time.strftime("%H:%M", t), "day": day})
        return out

    @Slot(result="QVariantList")
    def saverPhotos(self) -> list:
        """The screen saver's photos: pictures in Pictures (not screenshots), newest first, up to 300."""
        try:
            from gi.repository import GLib
            pictures = Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or Path.home() / "Pictures")
        except (ImportError, ValueError, TypeError):
            pictures = Path.home() / "Pictures"
        found, deadline = [], time.monotonic() + 1.5
        for root, dirs, files in os.walk(pictures):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() != "screenshots"]
            for f in files:
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".heic", ".avif")) and not f.startswith("."):
                    p = os.path.join(root, f)
                    try:
                        if os.path.getsize(p) > 60 * 1024:          # (icons and tiny pictures aren't photos)
                            found.append((os.path.getmtime(p), p))
                    except OSError:
                        continue
            if time.monotonic() > deadline or len(found) > 2000:
                break
        found.sort(reverse=True)
        return [QUrl.fromLocalFile(p).toString() for _t, p in found[:300]]

    @Slot(result="QVariantList")
    def shortcutSheet(self) -> list:
        """Hold Super: every shortcut as Settings › Keyboard shortcuts has it now, grouped (shortcut_sheet)."""
        try:
            hs = apps_module("huginn_settings")
            return shortcut_sheet(hs.load_keys({})) if hs else []
        except Exception:      # (a sheet with nothing on it is better than a shell that stops here)
            return []

    @Slot()
    def clearHistory(self) -> None:
        self._notes = []
        self.changed.emit()
        if not self._demo:
            self._session("ClearHistory")

    # ------------------------------------------------------------------ power (the start menu's bottom row)
    def _read_power(self) -> None:
        """Which of Sleep / Restart / Shut Down logind will do here ("na" means the machine can't, e.g. sleep in a VM)."""
        if not self.yb:
            return
        caps = {}
        for key, method in (("sleep", "CanSuspend"), ("restart", "CanReboot"), ("shutdown", "CanPowerOff")):
            try:
                v = self.yb.call_sync("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", method,
                                      None, GLib.VariantType("(s)"), 0, 1500, None).unpack()[0]
                caps[key] = v != "na"
            except GLib.Error:
                caps[key] = True
        caps["gamemode"] = self._power.get("gamemode", False)
        if caps != self._power:
            self._power = caps
            self.changed.emit()

    @Slot(str)
    def screenshot(self, what: str) -> None:
        """screen: the whole screen into Pictures › Screenshots at once (with a banner); choose: the Screenshot app."""
        if self._demo:
            return
        apps = "/usr/share/huginn-apps"
        if what == "choose":
            subprocess.Popen(["python3", f"{apps}/huginn_app.py", "screenshot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return
        if self._shooting:
            return
        self._shooting = True

        def run():
            try:
                subprocess.run(["python3", f"{apps}/huginn_capture.py", "--save"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self._shooting = False
        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------ input regions
    @Slot(QObject, int, int, int, int)
    def setInputRegion(self, window, x: int, y: int, w: int, h: int) -> None:
        """Only this part of a shell window takes the pointer (w or h <= 0: all of it). The popups over the dock reach
        down over it when it makes room (no exclusive zone): the dock keeps the pointer there."""
        from PySide6.QtGui import QRegion
        from PySide6.QtCore import QRect
        if window is None or not hasattr(window, "setMask"):
            return
        window.setMask(QRegion() if w <= 0 or h <= 0 else QRegion(QRect(x, y, w, h)))

    # ------------------------------------------------------------------ making room for a game
    gamePlayingChanged = Signal()
    GAME_MARK = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "huginn" / "game-playing"

    def _game_check(self) -> None:
        now = self.GAME_MARK.exists()
        if now != self._game_playing:
            self._game_playing = now
            self.gamePlayingChanged.emit()
            if now:
                QTimer.singleShot(1500, self.trimMemory)            # once the shell's own QML has collected (Shell.qml)

    gamePlaying = Property(bool, lambda self: self._game_playing, notify=gamePlayingChanged)

    @Slot()
    def trimMemory(self) -> None:
        """Give back memory the shell isn't using: each window's cached graphics (its scene graph's textures, glyphs,
        shaders: made again when next drawn), Python's garbage, and the C library's freed heap."""
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQuick import QQuickWindow

        def rss() -> int:
            try:
                return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE") // 1048576
            except (OSError, ValueError, IndexError):
                return 0
        before = rss()
        for w in QGuiApplication.topLevelWindows():
            if isinstance(w, QQuickWindow):
                w.releaseResources()
        import gc
        gc.collect()
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass
        print(f"huginn-shell: a game has the screen; memory {before} MB → {rss()} MB", file=sys.stderr, flush=True)

    @Slot(str)
    def power(self, what: str) -> None:
        """lock, sleep, restart, shutdown, signout or gamemode (the desktop ends and Game Mode starts in its place). The
        session daemon does it (it locks before sleeping); without it, logind directly."""
        if what not in ("lock", "sleep", "restart", "shutdown", "signout", "gamemode"):
            return
        self.lastPower = what
        if self._demo:
            print(f"huginn-shell: power: {what} (preview: nothing happens)", file=__import__("sys").stderr)
            return

        def fallback(conn, res):
            try:
                conn.call_finish(res)
            except GLib.Error:
                self._power_direct(what)
        if self.sb:
            self.sb.call("org.huginn.Session", "/org/huginn/Session", "org.huginn.Session", "Do", GLib.Variant("(s)", (what,)),
                         None, 0, 3000, None, fallback)
        else:
            self._power_direct(what)

    def _power_direct(self, what: str) -> None:
        if what == "gamemode":
            nxt = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "huginn" / "next-session"
            try:
                nxt.parent.mkdir(parents=True, exist_ok=True)
                nxt.write_text("game\n")
            except OSError:
                return
            what = "signout"
        if what == "lock":
            cmd = ["loginctl", "lock-session"]
        elif what == "signout":
            if self.sb and self._own_compositor() and self._compositor("SignOut", None, None) is not None:
                return
            cmd = ["loginctl", "terminate-session", os.environ.get("XDG_SESSION_ID", "")]
        else:
            cmd = ["systemctl", {"sleep": "suspend", "restart": "reboot", "shutdown": "poweroff"}[what]]
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def _offer_arranging(self, tries: int = 4) -> None:
        """Two or more screens that have never been arranged (displays.json has no place for any of them): they stand
        side by side in the order their sockets come, which may not be how they stand on the desk, so the pointer
        leaves one screen by the wrong edge. Once, a notification offers to arrange them (Settings › Displays, with
        each screen's name shown over it)."""
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.instance()
        if self._demo or self.sb is None or app is None or len(app.screens()) < 2:
            return
        asked = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "huginn" / "asked-to-arrange"
        if asked.exists():
            return
        try:
            saved = json.loads((Path.home() / ".config/huginn/displays.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        if any(not k.startswith("_") and isinstance(v, dict) and "x" in v for k, v in (saved or {}).items()):
            return                                      # arranged before (Settings › Displays saves each screen's place)
        n = len(app.screens())
        words = {2: "two", 3: "three", 4: "four"}.get(n, str(n))

        def sent(conn, res):
            try:
                self._arrange_note = conn.call_finish(res).unpack()[0]
            except GLib.Error:                          # the notification server isn't up yet: again in a while
                self._arrange_note = 0
                if tries > 1:
                    QTimer.singleShot(10000, lambda: self._offer_arranging(tries - 1))
                return
            try:                                        # asked once, ever
                asked.parent.mkdir(parents=True, exist_ok=True)
                asked.touch()
            except OSError:
                pass
        self._arrange_note = -1
        if not getattr(self, "_arrange_listen", 0):
            self._arrange_listen = self.sb.signal_subscribe(
                "org.freedesktop.Notifications", "org.freedesktop.Notifications", "ActionInvoked", "/org/freedesktop/Notifications", None,
                Gio.DBusSignalFlags.NONE, self._arrange_action)
        self.sb.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                     GLib.Variant("(susssasa{sv}i)", ("Displays", 0, "preferences-desktop-display", f"Huginn OS found {words} screens",
                                                       "They're side by side in the order they're plugged in. If the pointer leaves a screen "
                                                       "by the wrong edge, put them in the order they stand on your desk, and choose the main "
                                                       "one (it has the dock).",
                                                       ["arrange", "Arrange Them", "default", "Arrange Them"], {}, 0)),
                     None, Gio.DBusCallFlags.NONE, 3000, None, sent)

    def _arrange_action(self, conn, sender, path, iface, signal, params) -> None:
        nid, key = params.unpack()
        if nid != getattr(self, "_arrange_note", -2) or key not in ("arrange", "default"):
            return
        self.openSettings("displays")

    @Slot(str)
    def openSettings(self, page: str) -> None:
        if not self._demo:
            subprocess.Popen(["python3", "/usr/share/huginn-apps/huginn_app.py", "settings"] + (["--page", page] if page else []),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    # ------------------------------------------------------------------ the app in front (KWin)
    def _shell_call(self, conn, sender, path, iface, method, params, inv):
        if method in ("ToggleLauncher", "Launcher"):            # Super (KWin)
            self.launcherWanted.emit()
            inv.return_value(None)
            return
        if method == "Search":                                   # Meta+Space (KWin's script)
            self.searchWanted.emit(params.unpack()[0])
            inv.return_value(None)
            return
        if method == "Screenshot":                               # Print and Meta+Shift+S (KWin's script)
            inv.return_value(None)
            self.screenshot(params.unpack()[0])
            return
        if method == "Active":
            caption, resource, desktop, maximized = params.unpack()
            app = self.app_for_window(desktop or resource, resource) or self._pretty(desktop or resource)
            self._active = {"name": app or caption, "appId": desktop or resource, "caption": caption, "maximized": bool(maximized)}
            self.activeChanged.emit()
        elif method == "Key":
            self.keyWanted.emit(params.unpack()[0])
        elif method == "Tour":                                   # Welcome in the apps, Help, Huginn's menu
            self.tourWanted.emit()
        elif method == "Lift":                                   # one of Huginn's apps: filled, it shares the bar's row
            app = str(params.unpack()[0])[:80]
            if app and app not in self._lift_apps:
                self._lift_apps.append(app)
                self.liftAppsChanged.emit()
        elif method == "Snap":                                   # an app's fill button: the window in front, snapped
            layout = params.unpack()[0]
            QTimer.singleShot(0, lambda: self.snapFront(layout))
        elif method in ("Overview", "SnapPreview", "SnapAssist", "Switcher"):
            text = params.unpack()[0]
            try:
                data = json.loads(text) if text else {}
            except ValueError:
                data = {}
            if method == "Overview":
                self._overview = data
            elif method == "SnapPreview":
                self._snap_preview = data
            elif method == "SnapAssist":
                self._snap_assist = data
            else:
                self._switcher = data
            self.sceneChanged.emit()
        elif method == "AppMenu":                                # Alt on its own (KWin)
            self.keyWanted.emit("menu")
        elif method == "Windows":
            self._read_windows(params.unpack()[0])
        elif method == "Activated":
            key, found = params.unpack()
            command = self._pending.pop(key, "")
            if not found and command and self._apps is not None:
                self._apps.launch(command)                   # no window of it after all: start it (it hands over if running)
        inv.return_value(None)

    def _kwin_running(self) -> bool:
        return self._has_name("org.kde.KWin")

    def _app_name(self, app_id: str) -> str:
        low = (app_id or "").lower()
        if not low or self._apps is None:
            return ""
        found = next((a for a in self._apps.all if low in (a.get("wm", "").lower(), a.get("id", "").lower())), None)
        return found["name"] if found else ""

    def kwin(self, script: str) -> bool:
        """Runs a few lines of KWin script (window actions). False where KWin isn't the compositor."""
        if self._demo or not self.sb:
            return False
        folder = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
        fd, path = tempfile.mkstemp(prefix="huginn-kwin-", suffix=".js", dir=folder)
        with os.fdopen(fd, "w") as f:
            f.write(script)
        name = "huginn" + Path(path).stem.replace("-", "")
        try:
            sid = self.sb.call_sync("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript", GLib.Variant("(ss)", (path, name)),
                                    GLib.VariantType("(i)"), 0, 2000, None).unpack()[0]
            self.sb.call_sync("org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run", None, None, 0, 2000, None)
        except GLib.Error:
            os.unlink(path)
            return False

        def tidy():
            try:
                self.sb.call_sync("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "unloadScript", GLib.Variant("(s)", (name,)), None, 0, 2000, None)
            except GLib.Error:
                pass
            try:
                os.unlink(path)
            except OSError:
                pass
        QTimer.singleShot(3000, tidy)
        return True

    def _own_compositor(self) -> bool:
        """Huginn's own compositor (org.huginn.Compositor with ActivateApp) is running this session."""
        return self._has_name("org.huginn.Compositor")

    def _has_name(self, name: str) -> bool:
        try:
            return bool(self.sb.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                                          GLib.Variant("(s)", (name,)), GLib.VariantType("(b)"), 0, 1000, None).unpack()[0])
        except GLib.Error:
            return False

    def _compositor(self, method: str, args: GLib.Variant | None, reply: str | None):
        """A call to Huginn's own compositor; None when it can't be made."""
        try:
            out = self.sb.call_sync("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor", method, args,
                                    GLib.VariantType(reply) if reply else None, 0, 2000, None)
            return out.unpack() if reply else ()
        except GLib.Error:
            return None

    # ---------------------------------------------------------------- where the pop-ups' glass is
    # The control centre, Today, the menus, the start menu and Search are surfaces over the whole screen (a click beside
    # their panels closes them); Huginn's compositor would blur all of that again whenever anything under them changed.
    # Each frame one of them draws, its Glass pieces' places (as drawn: moved, grown, faded) go to the compositor, which
    # then blurs just those (look.rs: Backdrop).
    @Slot(QObject, str)
    def glassWindow(self, window, scope: str) -> None:
        if self._demo or window is None or not hasattr(window, "afterAnimating"):
            return
        if not hasattr(self, "_glass_windows"):
            self._glass_windows, self._glass_items, self._glass_sent = {}, [], {}
        key = _ptr(window)
        if key in self._glass_windows:
            return
        self._glass_windows[key] = scope
        window.afterAnimating.connect(lambda w=window: self._glass_frame(w))   # (the GUI thread, each frame)
        window.visibleChanged.connect(lambda shown: None if shown else self._glass_send(scope, []))

    @Slot(QObject, bool)
    def glassItem(self, item, on: bool) -> None:
        if not hasattr(self, "_glass_items"):
            self._glass_windows, self._glass_items, self._glass_sent = {}, [], {}
        if on and item not in self._glass_items:
            self._glass_items.append(item)
        elif not on and item in self._glass_items:
            self._glass_items.remove(item)

    def _glass_frame(self, window) -> None:
        from PySide6.QtCore import QRectF
        pieces, key = [], _ptr(window)
        for item in list(self._glass_items):
            try:
                if _ptr(item.window()) != key or not item.isVisible() or item.width() < 2 or item.height() < 2:
                    continue
                op, it = 1.0, item
                while it is not None:
                    op *= it.opacity()
                    it = it.parentItem()
                if op < 0.05:
                    continue
                r = item.mapRectToScene(QRectF(0, 0, item.width(), item.height()))
                k = r.width() / max(1.0, item.width())
                rad = float(item.property("radius") or 0) * k
                pieces.append([round(r.x(), 1), round(r.y(), 1), round(r.width(), 1), round(r.height(), 1), round(rad, 1),
                               round(min(1.0, max(0.0, (op - 0.15) / 0.55)), 2)])
            except RuntimeError:                                  # (an item already gone)
                self._glass_items.remove(item)
        self._glass_send(self._glass_windows.get(key, ""), pieces)

    def _glass_send(self, scope: str, pieces: list) -> None:
        if not scope or not self.sb:
            return
        text = json.dumps(pieces)
        if self._glass_sent.get(scope) == text:
            return
        self._glass_sent[scope] = text
        if not hasattr(self, "_own_comp"):
            self._own_comp = self._own_compositor()
        if self._own_comp:
            self.sb.call("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor", "SetGlass",
                         GLib.Variant("(ss)", (scope, text)), None, 0, 1000, None, None, None)

    # ---------------------------------------------------------------- pictures of windows, for the dock's cards
    picturesChanged = Signal()
    windowPictures = Property("QVariantMap", lambda self: getattr(self, "_pictures", {}), notify=picturesChanged)

    @Slot("QVariantList")
    def refreshPictures(self, ids: list) -> None:
        """Ask Huginn's own compositor for a small picture of each window (KWin: none; the cards stay plain). They
        come back one by one, as PNGs in $XDG_RUNTIME_DIR, into windowPictures (id -> file URL)."""
        if not self.sb or not self._own_compositor():
            return
        if not hasattr(self, "_pictures"):
            self._pictures, self._picture_n = {}, 0
        run = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
        for wid in ids:
            wid = str(wid)

            def done(bus, res, wid=wid):
                try:
                    text = bus.call_finish(res).unpack()[0]
                    info = json.loads(text) if text else None
                except (GLib.Error, ValueError):
                    info = None
                if not info:
                    return
                from PySide6.QtGui import QImage
                try:
                    data = Path(info["path"]).read_bytes()
                    Path(info["path"]).unlink(missing_ok=True)
                except OSError:
                    return
                head, _, pixels = data.partition(b"\n")
                w, h, stride = (int(x) for x in head.split()[1:4])
                image = QImage(pixels, w, h, stride, QImage.Format_ARGB32_Premultiplied).copy()
                self._picture_n += 1
                out = run / f"huginn-card-{os.getpid()}-{wid}-{self._picture_n % 2}.png"
                if image.save(str(out), "PNG"):
                    self._pictures = dict(self._pictures, **{wid: f"file://{out}?{self._picture_n}"})
                    self.picturesChanged.emit()
            self.sb.call("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor", "WindowPicture",
                         GLib.Variant("(s)", (wid,)), GLib.VariantType("(s)"), 0, 6000, None, done)

    @Slot("QVariantMap", result=bool)
    def activateApp(self, app: dict) -> bool:
        """A running app's window comes forward (un-minimised) instead of the app starting again. Huginn's own
        compositor answers at once; KWin answers through Activated. With no window of it there, the app is started
        after all."""
        ids = [i.lower() for i in (app.get("wm", ""), app.get("id", "")) if i]
        if not ids or self._demo or not self.sb:
            return False
        if self._apps is None or app.get("name") not in self._apps.running:
            return False
        if self._own_compositor():
            found = self._compositor("ActivateApp", GLib.Variant("(s)", (" ".join(ids),)), "(b)")
            return bool(found and found[0])
        if not self._kwin_running():
            return False
        self._pending[ids[0]] = app.get("exec", "")
        return self.kwin(f"""var ids = {json.dumps(ids)};
var best = null;
workspace.stackingOrder.forEach(function (w) {{
    var id = (w.desktopFileName || w.resourceClass || "").toLowerCase();
    if (w.normalWindow && ids.indexOf(id) >= 0) best = w;
}});
if (best) {{ best.minimized = false; workspace.activeWindow = best; }}
callDBus("org.huginn.Shell", "/org/huginn/Shell", "org.huginn.Shell", "Activated", ids[0], best !== null);""")

    @Slot(str)
    def windowAction(self, action: str) -> None:
        """The app menu in the top bar: minimise or close the window in front; Layouts: snap it (snap:<part>)."""
        if (action not in ("minimise", "close", "ontop") and not action.startswith("snap:")) or self._demo or not self.sb:
            return
        if self._own_compositor():
            self._compositor("WindowAction", GLib.Variant("(s)", (action,)), None)
            return
        if action.startswith("snap:"):
            return
        if action == "ontop":
            self.kwin("if (workspace.activeWindow) workspace.activeWindow.keepAbove = !workspace.activeWindow.keepAbove;")
            return
        js = {"minimise": "if (workspace.activeWindow) workspace.activeWindow.minimized = true;",
              "close": "if (workspace.activeWindow) workspace.activeWindow.closeWindow();"}.get(action)
        self.kwin(js)

    battery = Property("QVariantMap", lambda self: self._battery, notify=changed)
    network = Property("QVariantMap", lambda self: self._network, notify=changed)
    bluetooth = Property("QVariantMap", lambda self: self._bt, notify=changed)
    levels = Property("QVariantMap", lambda self: self._levels, notify=changed)
    dnd = Property(bool, lambda self: self._dnd, notify=changed)
    nightLight = Property("QVariantMap", lambda self: self._night, notify=changed)
    notifications = Property("QVariantList", lambda self: self._notes, notify=changed)
    waiting = Property(bool, lambda self: self._waiting(), notify=changed)
    active = Property("QVariantMap", lambda self: self._active, notify=activeChanged)
    windows = Property("QVariantList", lambda self: self._windows, notify=windowsChanged)
    otherApps = Property("QVariantList", lambda self: getattr(self, "_others", []), notify=windowsChanged)
    menus = Property("QVariantMap", lambda self: self._menus, notify=menusChanged)
    overview = Property("QVariantMap", lambda self: self._overview, notify=sceneChanged)
    snapPreview = Property("QVariantMap", lambda self: self._snap_preview, notify=sceneChanged)
    snapAssist = Property("QVariantMap", lambda self: self._snap_assist, notify=sceneChanged)
    switcher = Property("QVariantMap", lambda self: self._switcher, notify=sceneChanged)
    ownCompositor = Property(bool, lambda self: bool(self.sb) and self._own_compositor(), constant=True)
    spaces = Property("QVariantMap", lambda self: self._spaces, notify=windowsChanged)
    powerCaps = Property("QVariantMap", lambda self: self._power, notify=changed)

    def _primary(self) -> str:
        """The main screen (the top bar and dock's): the one chosen in Settings › Displays on Huginn's own compositor
        (~/.config/huginn/displays.json, "_main"), else the one Qt calls primary."""
        from PySide6.QtGui import QGuiApplication
        if not QGuiApplication.instance():
            return ""
        names = [s.name() for s in QGuiApplication.screens()]
        try:
            main = json.loads((Path.home() / ".config" / "huginn" / "displays.json").read_text(encoding="utf-8")).get("_main", "")
        except (OSError, ValueError, AttributeError):
            main = ""
        if main in names and self.sb and self._own_compositor():
            return main
        screen = QGuiApplication.primaryScreen()
        return screen.name() if screen else ""
    primaryScreenChanged = Signal()
    primaryScreen = Property(str, _primary, notify=primaryScreenChanged)

    def _screens(self) -> list:
        """The screens as QScreen objects (QML's own Qt.application.screens are a different type, which layer-shell
        surfaces can't be given), for one wallpaper per screen."""
        from PySide6.QtGui import QGuiApplication
        return list(QGuiApplication.screens()) if QGuiApplication.instance() else []
    screenList = Property("QVariantList", _screens, notify=primaryScreenChanged)
