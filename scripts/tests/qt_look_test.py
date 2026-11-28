#!/usr/bin/env python3
"""Huginn's own Qt look (qt/: the platform theme and the widget style) in a real Qt app: the settings huginn_look.py
writes for it, the colours, fonts and style an app gets from them, an open app following a change, and the app's
menu bar handed to the top bar (org.huginn.App.p<pid>: Menus and Trigger, as Huginn's own apps answer) on a bus of
its own with a stand-in shell, its shortcuts still working with the bar hidden.

    qt_look_test.py <kit root> [<Qt plugins folder>] [<folder for pictures>]
        (not as root; the plugins folder has platformthemes/libhuginntheme.so and styles/libhuginnstyle.so: the
         system's by default, as on Huginn OS)
"""
import json
import os
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if os.geteuid() == 0:
    sys.exit("not as root")
KIT = Path(sys.argv[1]).resolve()
PLUGINS = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else Path("/usr/lib/x86_64-linux-gnu/qt6/plugins")
PICTURES = Path(sys.argv[3]) if len(sys.argv) > 3 else None
home = Path(tempfile.mkdtemp(prefix="qtlook-"))
share = home / "share"
os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_CONFIG_DIRS=str(home / "xdg"),
                  HUGINN_LOOK_SHARE=str(share), XDG_STATE_HOME=str(home / ".state"))
sys.path.insert(0, str(KIT / "apps"))
import huginn_look as hl  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"ok   {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


for p in ("platformthemes/libhuginntheme.so", "styles/libhuginnstyle.so"):
    if not (PLUGINS / p).is_file():
        sys.exit(f"no {PLUGINS / p}: build qt/ first")

# ------------------------------------------------------------------------------------------------ what the look writes
out = subprocess.run([sys.executable, str(KIT / "tokens/gen_theme.py"), str(KIT / "tokens/tokens.json"), str(home / "theme")], capture_output=True, text=True)
check("the tokens make Huginn's Qt colours for every realm, dark and light", out.returncode == 0 and len(list((home / "theme/qt").glob("*.conf"))) == 8, out.stdout[-300:])
(share / "huginn-os").mkdir(parents=True)
os.symlink(home / "theme/qt", share / "huginn-os/qt")
qt_conf = home / ".config/huginn/qt.conf"


def colours_of(name):
    text = (home / f"theme/qt/{name}.conf").read_text()
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith(";"))


check("written once", hl.write_qt("bifrost", False, icons="Papirus") and not hl.write_qt("bifrost", False, icons="Papirus"))
text = qt_conf.read_text()
check("…light, the icons chosen, Huginn's fonts, menus in the top bar", "scheme=light" in text and "icons=Papirus" in text
      and "font=Inter Variable,10" in text and "fixed=JetBrains Mono,10" in text and "top_bar=true" in text, text[:400])
check("…the realm's colours", f"accent={colours_of('HuginnBifrostLight')['accent']}" in text and "[Colours]" in text)
qt_conf.write_text(text.replace("top_bar=true", "top_bar = false"))
hl.write_qt("bifrost", True, icons="Papirus")
check("…menus kept in the window when the person said so, through a change of look", "top_bar=false" in qt_conf.read_text()
      and "scheme=dark" in qt_conf.read_text())
qt_conf.unlink()
check("apply() writes it with the rest of the look", hl.apply("aurora", True, force=True) is True and qt_conf.is_file()
      and f"accent={colours_of('HuginnAuroraDark')['accent']}" in qt_conf.read_text())
(home / ".config/huginn-shell").mkdir(parents=True, exist_ok=True)
(home / ".config/huginn-shell/settings.json").write_text(json.dumps({"realm": "niflheim", "dark": "false"}))
hl.write_qt(icons="Huginn")
check("a new icon theme alone (Settings) keeps the person's realm", "icons=Huginn" in qt_conf.read_text()
      and f"window={colours_of('HuginnNiflheimLight')['window']}" in qt_conf.read_text())
hl.write_qt("aurora", True)

# ------------------------------------------------------------------------------------------------ an app
APP = r'''
import json, os, sys
from PySide6.QtCore import Qt, QSocketNotifier, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QPushButton, QWidget, QVBoxLayout, QLineEdit, QMenu
app = QApplication(sys.argv)
app.setApplicationDisplayName("Gallery")
say = lambda *a: (print(*a, flush=True))
win = QMainWindow(); win.resize(500, 300)
mb = win.menuBar()
f = mb.addMenu("&File")
f.addAction("&New", QKeySequence("Ctrl+N"), lambda: say("triggered:New"))
recent = f.addMenu("Open &Recent")
def fill():
    recent.clear()
    for n in ("a.txt", "b.txt"):
        recent.addAction(n, lambda n=n: say("triggered:" + n))
recent.aboutToShow.connect(fill)
f.addSeparator()
f.addAction("Save && Close", lambda: say("triggered:SaveClose"))
f.addSeparator()
f.addAction("&Quit", QKeySequence("Ctrl+Q"), lambda: say("triggered:Quit"))
e = mb.addMenu("&Edit")
e.addAction("&Undo", QKeySequence("Ctrl+Z"), lambda: say("triggered:Undo"))
cut = e.addAction("Cu&t", QKeySequence("Ctrl+X"), lambda: say("triggered:Cut")); cut.setEnabled(False)
grid = e.addAction("Show grid"); grid.setCheckable(True); grid.toggled.connect(lambda on: say("grid:%s" % on))
hidden = e.addAction("Secret"); hidden.setVisible(False)
e.addSeparator()
e.addAction("Preferences…", QKeySequence("Ctrl+,"), lambda: say("triggered:Preferences"))
v = mb.addMenu("&View")
g = QActionGroup(win)
for n in ("Small", "Large"):
    a = v.addAction(n); a.setCheckable(True); g.addAction(a); a.setChecked(n == "Small")
h = mb.addMenu("&Help")
h.addAction("About Gallery", lambda: say("triggered:About"))
w = QWidget(); lay = QVBoxLayout(w); lay.addWidget(QLabel("Hello")); field = QLineEdit(); lay.addWidget(field); win.setCentralWidget(w)
win.show(); win.activateWindow()
second = None
def polished(w):
    w.ensurePolished()
    return w
def state():
    p = app.palette()
    return {"style": app.style().name(), "window": p.window().color().name(), "accent": p.accent().color().name(),
            "highlighted": p.highlightedText().color().name(), "font": app.font().family(), "size": app.font().pointSizeF(),
            "fixed": __import__("PySide6.QtGui", fromlist=["QFontDatabase"]).QFontDatabase.systemFont(
                __import__("PySide6.QtGui", fromlist=["QFontDatabase"]).QFontDatabase.FixedFont).family(),
            "native": mb.isNativeMenuBar(), "barShown": mb.isVisible(), "barHeight": mb.height() if mb.isVisible() else 0,
            "scheme": str(app.styleHints().colorScheme()), "menuWindow": polished(QMenu()).palette().window().color().name(),
            "pid": os.getpid()}
def command():
    global second
    line = sys.stdin.readline().strip()
    if line == "state":
        say("state:" + json.dumps(state()))
    elif line == "ctrl-n":
        QTest.keyClick(win, Qt.Key_N, Qt.ControlModifier)
    elif line == "second":
        second = QMainWindow(); second.menuBar().addMenu("&Tools").addAction("Measure", lambda: say("triggered:Measure"))
        second.show(); second.activateWindow(); second.windowHandle().requestActivate()
        QTimer.singleShot(300, lambda: say("second:%s" % (app.focusWindow() is second.windowHandle())))
    elif line == "first":
        win.activateWindow(); win.windowHandle().requestActivate()
        QTimer.singleShot(300, lambda: say("first:%s" % (app.focusWindow() is win.windowHandle())))
    elif line == "dialog":
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog(win)
        d.show()
        QTimer.singleShot(300, lambda: say("dialog:%s" % d.isVisible()))
    elif line == "quit" or not line:
        app.quit()
n = QSocketNotifier(sys.stdin.fileno(), QSocketNotifier.Read); n.activated.connect(command)
QTimer.singleShot(200, lambda: say("ready"))
app.exec()
'''
app_py = home / "app.py"
app_py.write_text(APP)


class App:
    def __init__(self, env_more=None):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QPA_PLATFORMTHEME="huginn", QT_PLUGIN_PATH=str(PLUGINS), **(env_more or {}))
        self.p = subprocess.Popen([sys.executable, str(app_py)], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.lines = []
        self.wait("ready", 20)

    def wait(self, prefix, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            for i, line in enumerate(self.lines):
                if line.startswith(prefix):
                    return self.lines.pop(i)
            r, _, _ = select.select([self.p.stdout], [], [], 0.1)
            if r:
                line = self.p.stdout.readline()
                if not line:
                    break
                self.lines.append(line.strip())
        return None

    def send(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def state(self):
        self.send("state")
        got = self.wait("state:")
        return json.loads(got[6:]) if got else {}

    def close(self):
        try:
            self.send("quit")
            self.p.wait(5)
        except (OSError, subprocess.TimeoutExpired):
            self.p.kill()


# without the top bar there to take them (no bus at all here), an app keeps its menu bar in the window
os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + str(home / "no-bus")
a = App()
s = a.state()
dark = colours_of("HuginnAuroraDark")
check("an app takes Huginn's style", s.get("style") == "huginn", s)
check("…the realm's colours", s.get("window", "").upper() == dark["window"] and s.get("accent", "").upper() == dark["accent"]
      and s.get("highlighted", "").upper() == dark["on_accent"], s)
check("…menus in the menu colour", s.get("menuWindow", "").upper() == dark["menu"], s)
check("…dark", "Dark" in s.get("scheme", ""), s)
check("…Huginn's fonts", s.get("font") == "Inter Variable" and s.get("size") == 10 and s.get("fixed") == "JetBrains Mono", s)
check("…and its own menu bar, while there's no top bar to take it", s.get("native") is False and s.get("barShown") is True, s)
hl.write_qt("muspelheim", False)
light = colours_of("HuginnMuspelheimLight")
for _ in range(30):
    s = a.state()
    if s.get("window", "").upper() == light["window"]:
        break
    time.sleep(0.1)
check("an open app follows a change of look at once", s.get("window", "").upper() == light["window"] and s.get("accent", "").upper() == light["accent"]
      and "Light" in s.get("scheme", ""), s)
a.close()
hl.write_qt("aurora", True)

# ------------------------------------------------------------------------------------------------ the menu bar, in the top bar
bus = subprocess.run(["dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"], capture_output=True, text=True)
address, bus_pid = bus.stdout.split()[:2]
os.environ["DBUS_SESSION_BUS_ADDRESS"] = address
from gi.repository import Gio, GLib  # noqa: E402
conn = Gio.DBusConnection.new_for_address_sync(address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)


def menus(pid):
    r = conn.call_sync(f"org.huginn.App.p{pid}", "/org/huginn/App", "org.huginn.App", "Menus", None, GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 3000, None)
    return json.loads(r.unpack()[0])


def trigger(pid, ident):
    conn.call_sync(f"org.huginn.App.p{pid}", "/org/huginn/App", "org.huginn.App", "Trigger", GLib.Variant("(s)", (ident,)), None, Gio.DBusCallFlags.NONE, 3000, None)


def find(rows, label):
    for r in rows:
        if r.get("label") == label:
            return r
        inside = find(r.get("children") or [], label)
        if inside:
            return inside
    return None


a = App()
check("with no shell on the bus, the menu bar stays in the window", a.state().get("barShown") is True)
a.close()
shell = subprocess.Popen([sys.executable, "-c", "from gi.repository import Gio, GLib\nc = Gio.bus_get_sync(Gio.BusType.SESSION)\n"
                          "Gio.bus_own_name_on_connection(c, 'org.huginn.Shell', 0, None, None)\nprint('owned', flush=True)\nGLib.MainLoop().run()"],
                         stdout=subprocess.PIPE, text=True)
shell.stdout.readline()
time.sleep(0.3)
a = App()
s = a.state()
pid = s.get("pid")
check("with Huginn's shell there, the menu bar leaves the window", s.get("native") is True and s.get("barShown") is False, s)
m = menus(pid)
names = [g["name"] for g in m["groups"]]
check("the app's menus, by name, without their mnemonics", names == ["File", "Edit", "View"], names)
check("…About first, from the app's own (and Help, left empty, gone)", m["top"][0]["label"] == "About Gallery" and m["top"][0]["id"].startswith("qt:"), m["top"])
check("…its Preferences as <App> Settings…, with its keys", m["top"][1]["label"] == "Gallery Settings…" and m["top"][1]["keys"] == "Ctrl+," and m["top"][1]["enabled"], m["top"])
check("…its Quit last, as Quit <App>, with its keys", m["bottom"][-1]["label"] == "Quit Gallery" and m["bottom"][-1]["keys"] == "Ctrl+Q"
      and m["bottom"][-1]["id"].startswith("qt:"), m["bottom"])
check("…and the shell's own window items around them", [i["id"] for i in m["bottom"][:3]] == ["shell:ontop", "shell:minimise", "shell:close"]
      and [i["id"] for i in m["middle"]] == ["shell:appWindows", "shell:pin"])
file_items = m["groups"][0]["items"]
check("File: New with its keys", file_items[0]["label"] == "New" and file_items[0]["keys"] == "Ctrl+N", file_items[:1])
rec = find(file_items, "Open Recent")
check("…a submenu the app fills as it opens, filled", rec and [c["label"] for c in rec.get("children", [])] == ["a.txt", "b.txt"], rec)
check("…“&&” is a plain &", find(file_items, "Save & Close") is not None)
check("…no line left at the end where Quit was", not file_items[-1].get("sep"), file_items[-2:])
edit = m["groups"][1]["items"]
check("Edit: what's off is off", find(edit, "Cut")["enabled"] is False and find(edit, "Undo")["enabled"] is True)
check("…a tick that can be set, not set", find(edit, "Show grid").get("checked") is False)
check("…what's hidden isn't there (nor Preferences, moved)", find(edit, "Secret") is None and find(edit, "Preferences…") is None and not edit[-1].get("sep"), edit)
view = m["groups"][2]["items"]
check("View: one of a group, chosen", view[0].get("radio") and view[0]["checked"] is True and view[1]["checked"] is False, view)
trigger(pid, file_items[0]["id"])
check("Trigger does the app's own action", a.wait("triggered:New") is not None)
trigger(pid, find(menus(pid)["groups"][0]["items"], "b.txt")["id"])
check("…one in a submenu too", a.wait("triggered:b.txt") is not None)
trigger(pid, find(edit, "Show grid")["id"])
check("…a tick toggles", a.wait("grid:True") is not None and find(menus(pid)["groups"][1]["items"], "Show grid")["checked"] is True)
trigger(pid, find(edit, "Cut")["id"])
trigger(pid, "qt:99999999")
trigger(pid, "shell:quit")
trigger(pid, "qt:abc")
check("…nothing for what's off, unknown or not the app's", a.wait("triggered:", 1.0) is None and a.p.poll() is None)
trigger(pid, m["bottom"][-1]["id"])
check("…its Quit is the app's own Quit", a.wait("triggered:Quit") is not None)
a.send("ctrl-n")
check("its shortcuts work with the bar out of the window", a.wait("triggered:New") is not None)
a.send("second")
focus = a.wait("second:")
if focus == "second:True":
    check("a second window with its own menu bar: its menus while it's in front", [g["name"] for g in menus(pid)["groups"]] == ["Tools"])
    a.send("first")
    a.wait("first:")
    check("…and the first's again when that is", [g["name"] for g in menus(pid)["groups"]] == ["File", "Edit", "View"])
else:
    print("skip second window: this Qt platform doesn't move the keyboard between windows", focus)
a.close()
began = time.time()
a = App({"DESKTOP_SESSION": "huginn", "XDG_SESSION_DESKTOP": "huginn"})
check("in a session called huginn, an app starts at once (Qt's portal theme, looking for a base theme by that name, "
      "doesn't make this theme again)", a.p.poll() is None and time.time() - began < 8 and a.state().get("style") == "huginn", time.time() - began)
a.send("dialog")
check("…and Open and Save still come up (Qt's portal theme, asked only now)", a.wait("dialog:", 30) == "dialog:True")
a.close()
a = App({"HUGINN_QT_MENUS": "0"})
check("HUGINN_QT_MENUS=0 keeps an app's menu bar in its window", a.state().get("barShown") is True)
a.close()
qt_conf.write_text(qt_conf.read_text().replace("top_bar=true", "top_bar=false"))
a = App()
check("…and so does [Menus] top_bar=false", a.state().get("barShown") is True)
a.close()
shell.kill()
subprocess.run(["kill", bus_pid])

# ------------------------------------------------------------------------------------------------ pictures
if PICTURES:
    GALLERY = KIT / "scripts/tests/qt_gallery.py"
    for realm, dark in (("aurora", True), ("aurora", False), ("bifrost", True), ("muspelheim", False)):
        hl.write_qt(realm, dark)
        name = f"{realm}-{'dark' if dark else 'light'}"
        r = subprocess.run([sys.executable, str(GALLERY), str(PICTURES / name)], env=dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QPA_PLATFORMTHEME="huginn",
                           QT_PLUGIN_PATH=str(PLUGINS), DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent"), capture_output=True, text=True, timeout=60)
        check(f"a gallery of controls in {name}", (PICTURES / f"{name}-window.png").is_file() and (PICTURES / f"{name}-menu.png").is_file(), r.stderr[-300:])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
