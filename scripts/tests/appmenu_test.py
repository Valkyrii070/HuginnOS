#!/usr/bin/env python3
"""Menu bars exported as dbusmenu (shell/huginn_appmenu.py): the shell's com.canonical.AppMenu.Registrar, and the
reader, against a real Qt app that hands its menu bar over the standard way (Qt's own QDBusMenuBar, as an X11 app
does once the registrar is there; App Store Qt apps do the same on Wayland through KDE's platform theme), on a bus of
its own.

    appmenu_test.py <kit root>        (not as root; needs dbus-daemon, PySide6 and an X display: DISPLAY)

Checked: the app finds the registrar and hides its menu bar; its window is registered under the app's own name and
process (and a number registered by another process isn't taken for that window); the menus as the shell reads them
(names without mnemonics, shortcuts, a menu filled as it opens, lines, greyed, check and radio items, submenus, About,
Settings and Quit moved, About Qt left); doing items (and not greyed ones); someone else can't unregister the window;
it's forgotten when the app goes; addresses that aren't sound are never asked.
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
if not os.environ.get("DISPLAY"):
    sys.exit("needs an X display (DISPLAY)")
KIT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(KIT / "shell"))
home = Path(tempfile.mkdtemp(prefix="appmenu-"))
os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_RUNTIME_DIR=str(home / "run"))
(home / "run").mkdir(mode=0o700)
from gi.repository import Gio, GLib  # noqa: E402
import huginn_appmenu as am  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"ok   {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


# ------------------------------------------------------------------------------------------------ small parts
check("dbusmenu's shortcuts as Huginn writes keys", am.keys([["Control", "N"]]) == "Ctrl+N" and am.keys([["Shift", "Control", "s"]]) == "Ctrl+Shift+S"
      and am.keys([["Control", "plus"]]) == "Ctrl++" and am.keys([["F5"]]) == "F5" and am.keys([]) == "" and am.keys(None) == ""
      and am.keys([["Alt", "Delete"], ["Control", "X"]]) == "Alt+Del", am.keys([["Shift", "Control", "s"]]))
check("sound addresses only", am.sound({"service": ":1.42", "path": "/MenuBar/1"}) and am.sound({"service": "org.kde.kate", "path": "/"})
      and not am.sound({"service": "nodot", "path": "/x"}) and not am.sound({"service": ":1.2", "path": "x/y"})
      and not am.sound({"service": ":1.2", "path": "/a//b"}) and not am.sound({"service": ":1.2"}) and not am.sound(None)
      and not am.sound({"service": "a b.c", "path": "/x"}))

# ------------------------------------------------------------------------------------------------ a Qt app
APP = r'''
import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtCore import QTimer
say = lambda *a: print(*a, flush=True)
app = QApplication(sys.argv)
app.setApplicationDisplayName("Sketchbook")
w = QMainWindow()
w.setCentralWidget(QLabel("canvas"))
def act(menu, label, what, keys=None, check=None):
    a = menu.addAction(label)
    if keys:
        a.setShortcut(QKeySequence(keys))
    if check is not None:
        a.setCheckable(True); a.setChecked(check)
    a.triggered.connect(lambda checked=False, what=what, a=a: say("activated:" + what + (":" + str(a.isChecked()).lower() if a.isCheckable() else "")))
    return a
bar = w.menuBar()
f = bar.addMenu("&File")
act(f, "&New", "new", "Ctrl+N")
act(f, "&Open…", "open", "Ctrl+O")
recent = f.addMenu("Open &Recent")
def fill():
    recent.clear()
    for name in ("drawing-1.sketch", "drawing-2.sketch"):
        act(recent, name, "recent:" + name)
    say("filled:recent")
recent.aboutToShow.connect(fill)
f.addSeparator()
act(f, "&Quit", "quit", "Ctrl+Q")
e = bar.addMenu("&Edit")
act(e, "&Undo", "undo", "Ctrl+Z").setEnabled(False)
e.addSeparator()
act(e, "&Preferences", "preferences")
v = bar.addMenu("&View")
act(v, "Show &Grid", "grid", "Ctrl+G", True)
v.addSeparator()
g = QActionGroup(w)
for label, on in (("&Small", True), ("&Large", False)):
    g.addAction(act(v, label, label.strip("&").lower(), None, on))
z = v.addMenu("&Zoom")
act(z, "Zoom &In", "zoomin", "Ctrl++")
act(z, "Zoom &Out", "zoomout", "Ctrl+-")
h = bar.addMenu("&Help")
act(h, "&About Sketchbook", "about")
act(h, "About &Qt", "aboutqt")
w.show()
QTimer.singleShot(800, lambda: say("ready wid:%d native:%s" % (int(w.winId()), str(bar.isNativeMenuBar()).lower())))
app.exec()
'''
(home / "app.py").write_text(APP)
got = subprocess.run(["dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"], capture_output=True, text=True)
address, bus_pid = got.stdout.split("\n")[:2]
os.environ["DBUS_SESSION_BUS_ADDRESS"] = address
conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
told = []
reg = am.Registrar(conn, changed=lambda: told.append(1))
ctx = GLib.MainContext.default()


def spin(seconds, until=None):
    end = time.time() + seconds
    while time.time() < end:
        ctx.iteration(False)
        if until and until():
            return True
        time.sleep(0.02)
    return bool(until and until())


spin(0.5, lambda: conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                                 GLib.Variant("(s)", ("com.canonical.AppMenu.Registrar",)), GLib.VariantType("(b)"), 0, 1000, None).unpack()[0])
env = dict(os.environ, QT_QPA_PLATFORM="xcb", QT_QPA_PLATFORMTHEME="nonesuch", XDG_CURRENT_DESKTOP="X-Test")
proc = subprocess.Popen([sys.executable, str(home / "app.py")], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
out, buf, lines = proc.stdout.fileno(), [b""], []


def read_line(seconds):
    end = time.time() + seconds
    while b"\n" not in buf[0]:
        ctx.iteration(False)
        r, _, _ = select.select([out], [], [], 0.02)
        if r:
            chunk = os.read(out, 65536)
            if not chunk:
                return None
            buf[0] += chunk
        if time.time() > end:
            return None
    line, buf[0] = buf[0].split(b"\n", 1)
    lines.append(line.decode().strip())
    return lines[-1]


def said(seconds=0.8):
    got, end = [], time.time() + seconds
    while time.time() < end:
        line = read_line(end - time.time())
        if line is None:
            break
        got.append(line)
    return got


ready = None
for _ in range(20):
    line = read_line(1.0)
    if line and line.startswith("ready"):
        ready = line
        break
wid = int(ready.split("wid:")[1].split()[0]) if ready else 0
check("the app hands its menu bar over once the registrar is there", ready and "native:true" in ready, ready)
check("its window is registered", spin(3, lambda: wid in reg.windows) and told, (wid, reg.windows))
entry = reg.windows.get(wid, ("", "", 0))
check("…under the app's own bus name and process", entry[0].startswith(":") and entry[2] == proc.pid, entry)
where = reg.lookup(wid, proc.pid)
check("found for its window", where == {"service": entry[0], "path": entry[1]}, where)
check("not for a window of another process, nor for another window", reg.lookup(wid, proc.pid + 1) is None and reg.lookup(wid + 1) is None
      and reg.lookup(None) is None and reg.lookup(0) is None)
other = Gio.DBusConnection.new_for_address_sync(address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
asking = []
other.call("com.canonical.AppMenu.Registrar", am.REGISTRAR_PATH, "com.canonical.AppMenu.Registrar", "GetMenuForWindow",
           GLib.Variant("(u)", (wid,)), GLib.VariantType("(so)"), 0, 1000, None, lambda c, r: asking.append(c.call_finish(r).unpack()))
spin(2, lambda: asking)
check("GetMenuForWindow answers", asking and list(asking[0]) == [entry[0], entry[1]], asking)

menus, refs = am.read(conn, where, "Sketchbook")
said(0.3)
names = [g["name"] for g in menus["groups"]]
check("the menus, by name", names == ["File", "Edit", "View", "Help"], names)


def find(items, label):
    return next((i for i in items or [] if i.get("label") == label), None)


def group(name):
    return next((g["items"] for g in menus["groups"] if g["name"] == name), [])


f = group("File")
check("File: shortcuts, a menu filled as it opens, Quit taken out", [(i.get("label"), i.get("keys")) for i in f]
      == [("New", "Ctrl+N"), ("Open…", "Ctrl+O"), ("Open Recent", "")], f)
rec = find(f, "Open Recent") or {}
check("…the filled menu's items", [c["label"] for c in rec.get("children", [])] == ["drawing-1.sketch", "drawing-2.sketch"] and "filled:recent" in lines, rec)
e = group("Edit")
check("Edit: Undo greyed, Preferences taken out (and the line before it)", [(i.get("label"), i.get("enabled")) for i in e] == [("Undo", False)], e)
v = group("View")
check("View: a check item, a line, radio items, a submenu", [i.get("label") if not i.get("sep") else "-" for i in v] == ["Show Grid", "-", "Small", "Large", "Zoom"], v)
gr, sm, lg = find(v, "Show Grid") or {}, find(v, "Small") or {}, find(v, "Large") or {}
check("…checked as they are", gr.get("checked") is True and "radio" not in gr and sm.get("checked") is True and sm.get("radio")
      and lg.get("checked") is False and lg.get("radio"), (gr, sm, lg))
zm = find(v, "Zoom") or {}
check("…keys with signs", [(c["label"], c["keys"]) for c in zm.get("children", [])] == [("Zoom In", "Ctrl++"), ("Zoom Out", "Ctrl+-")], zm)
h = group("Help")
check("Help keeps About Qt; About Sketchbook goes first", [i["label"] for i in h] == ["About Qt"] and menus["top"][0]["label"] == "About Sketchbook"
      and menus["top"][0]["id"].startswith("dbm:"), (h, menus["top"]))
check("Settings is the app's Preferences, Quit its own", menus["top"][1]["label"] == "Sketchbook Settings…" and menus["top"][1]["id"].startswith("dbm:")
      and menus["settings"] is True and menus["bottom"][-1]["label"] == "Quit Sketchbook" and menus["bottom"][-1]["id"].startswith("dbm:")
      and menus["toolkit"] == "dbusmenu", (menus["top"], menus["bottom"]))
check("the shell's own entries", [i["id"] for i in menus["middle"]] == ["shell:appWindows", "shell:pin"]
      and [i["id"] for i in menus["bottom"][:3]] == ["shell:ontop", "shell:minimise", "shell:close"])
json.dumps(menus)

said(0.2)
am.activate(conn, where, refs[find(f, "New")["id"]])
check("an item is done", "activated:new" in said())
am.activate(conn, where, refs[gr["id"]])
check("a check item turns", "activated:grid:false" in said())
am.activate(conn, where, refs[lg["id"]])
check("a radio item is chosen", "activated:large:true" in said())
am.activate(conn, where, refs[menus["top"][0]["id"]])
check("About is the app's", "activated:about" in said())
menus2, refs2 = am.read(conn, where, "Sketchbook")
v2 = next(g["items"] for g in menus2["groups"] if g["name"] == "View")
check("read again, they say so", find(v2, "Show Grid").get("checked") is False and find(v2, "Large").get("checked") is True
      and find(v2, "Small").get("checked") is False, v2)
rec2 = find(next(g["items"] for g in menus2["groups"] if g["name"] == "File"), "Open Recent")
am.activate(conn, where, refs2[rec2["children"][1]["id"]])
check("an item of the filled menu", "activated:recent:drawing-2.sketch" in said())
e2 = next(g["items"] for g in menus2["groups"] if g["name"] == "Edit")
am.activate(conn, where, refs2.get(find(e2, "Undo")["id"]))
check("a greyed item does nothing", not [x for x in said() if x.startswith("activated")])
check("nothing is asked of an address that isn't sound", not am.activate(conn, {"service": "x", "path": "/"}, 1)
      and not am.activate(conn, where, "1"))
try:
    am.read(conn, {"service": ":1.1", "path": "not a path"}, "X")
    check("reading an unsound address refuses", False)
except GLib.Error:
    check("reading an unsound address refuses", True)

other.call("com.canonical.AppMenu.Registrar", am.REGISTRAR_PATH, "com.canonical.AppMenu.Registrar", "UnregisterWindow", GLib.Variant("(u)", (wid,)), None, 0, 1000, None, None)
spin(0.5)
check("another app can't unregister the window", wid in reg.windows)
other.call("com.canonical.AppMenu.Registrar", am.REGISTRAR_PATH, "com.canonical.AppMenu.Registrar", "RegisterWindow",
           GLib.Variant("(uo)", (12345, "/Fake")), None, 0, 1000, None, None)
spin(2, lambda: 12345 in reg.windows)
check("another app registering its own window is kept apart", reg.windows.get(12345, ("",))[0] == other.get_unique_name() and reg.lookup(12345, proc.pid) is None)
other.close_sync(None)
check("…and forgotten when it leaves the bus", spin(3, lambda: 12345 not in reg.windows))

proc.terminate()
proc.wait(10)
check("the app's window is forgotten when it goes", spin(5, lambda: wid not in reg.windows), reg.windows)
reg.close()
subprocess.run(["kill", bus_pid])
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
