#!/usr/bin/env python3
"""GTK apps' menus for the top bar (shell/huginn_gtkmenus.py): a real GTK 3 app built on GtkApplication, on a bus of
its own, read the way the shell reads it once Huginn's compositor has said where its menus are (gtk_shell1), and
told to do what is chosen.

    gtk_menus_test.py <kit root>        (not as root; needs dbus-daemon and a display for GTK: DISPLAY or WAYLAND_DISPLAY)
"""
import os
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if os.geteuid() == 0:
    sys.exit("not as root")
if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    sys.exit("needs a display for GTK (DISPLAY or WAYLAND_DISPLAY)")
KIT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(KIT / "shell"))
home = Path(tempfile.mkdtemp(prefix="gtkmenus-"))
os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"))
from gi.repository import Gio, GLib  # noqa: E402
import huginn_gtkmenus as gm  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"ok   {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


# ------------------------------------------------------------------------------------------------ labels and keys
check("mnemonics go", gm.plain("_File") == "File" and gm.plain("Save __As") == "Save _As")
check("GTK's keys as Huginn writes them", gm.keys("<Primary>n") == "Ctrl+N" and gm.keys("<Control><Shift>z") == "Ctrl+Shift+Z"
      and gm.keys("<Alt>F4") == "Alt+F4" and gm.keys("<Primary>plus") == "Ctrl++" and gm.keys("F11") == "F11" and gm.keys("") == ""
      and gm.keys("<Shift><Primary>Page_Up") == "Ctrl+Shift+PgUp", gm.keys("<Shift><Primary>Page_Up"))

# ------------------------------------------------------------------------------------------------ a GTK app
APP = r'''
import sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk
say = lambda *a: print(*a, flush=True)
app = Gtk.Application(application_id="org.example.GtkMenus", flags=Gio.ApplicationFlags.NON_UNIQUE)
def startup(a):
    for name in ("new", "about", "quit", "preferences", "open"):
        act = Gio.SimpleAction.new(name, GLib.VariantType("s") if name == "open" else None)
        act.connect("activate", lambda _a, p, n=name: say("activated:" + n + (":" + p.unpack() if p is not None else "")))
        a.add_action(act)
    off = Gio.SimpleAction.new("off", None); off.set_enabled(False); a.add_action(off)
    a.set_accels_for_action("app.new", ["<Primary>n"])
    a.set_accels_for_action("app.quit", ["<Primary>q"])
    bar = Gio.Menu()
    f = Gio.Menu(); top = Gio.Menu(); top.append("_New", "app.new"); top.append("Not now", "app.off"); f.append_section(None, top)
    rec = Gio.Menu(); rec.append("a.txt", "app.open::a.txt"); rec.append("b.txt", "app.open::b.txt"); f.append_submenu("Open _Recent", rec)
    gone = Gio.MenuItem.new("Gone", "app.nothing"); gone.set_attribute_value("hidden-when", GLib.Variant("s", "action-missing")); f.append_item(gone)
    q = Gio.Menu(); quit_ = Gio.MenuItem.new("_Quit", "app.quit"); quit_.set_attribute_value("accel", GLib.Variant("s", "<Primary>q")); q.append_item(quit_)
    f.append_section(None, q)
    bar.append_submenu("_File", f)
    e = Gio.Menu(); e.append("Bold", "win.bold"); e.append("Small", "win.size::small"); e.append("Large", "win.size::large")
    e.append("Preferences", "app.preferences")
    bar.append_submenu("F_ormat", e)
    h = Gio.Menu(); h.append("About Menus", "app.about"); bar.append_submenu("_Help", h)
    a.set_menubar(bar)
def activate(a):
    w = Gtk.ApplicationWindow(application=a, title="GTK menus")
    bold = Gio.SimpleAction.new_stateful("bold", None, GLib.Variant("b", False))
    bold.connect("change-state", lambda act, v: (act.set_state(v), say("bold:%s" % v.unpack())))
    w.add_action(bold)
    size = Gio.SimpleAction.new_stateful("size", GLib.VariantType("s"), GLib.Variant("s", "small"))
    size.connect("change-state", lambda act, v: (act.set_state(v), say("size:" + v.unpack())))
    w.add_action(size)
    w.show_all()
    say("ready|%s|%d|%s" % (a.get_dbus_object_path(), w.get_id(), a.get_dbus_connection().get_unique_name()))
app.connect("startup", startup)
app.connect("activate", activate)
app.run([])
'''
(home / "app.py").write_text(APP)
bus = subprocess.run(["dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"], capture_output=True, text=True)
address, bus_pid = bus.stdout.split()[:2]
env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address, GTK_MODULES="")
proc = subprocess.Popen([sys.executable, str(home / "app.py")], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
lines = []


def wait(prefix, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        for i, line in enumerate(lines):
            if line.startswith(prefix):
                return lines.pop(i)
        r, _, _ = select.select([proc.stdout], [], [], 0.1)
        if r:
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line.strip())
    return None


ready = wait("ready|", 20)
check("the app is up", ready is not None)
if ready is None:
    proc.kill()
    sys.exit(1)
_, app_path, wid, owner = ready.split("|")
conn = Gio.DBusConnection.new_for_address_sync(address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
# what GTK tells Huginn's compositor (gtk_surface1.set_dbus_properties), and the compositor the shell
where = {"bus": owner, "menubar": f"{app_path}/menus/menubar", "app": app_path, "window": f"{app_path}/window/{wid}", "appId": "org.example.GtkMenus"}
menus, refs = gm.read(conn, where, "Menus")
names = [g["name"] for g in menus["groups"]]
check("the app's menus by name (and Help, left with nothing once About moved, gone)", names == ["File", "Format"], names)
file_items = menus["groups"][0]["items"]
labels = [i.get("label") if not i.get("sep") else "—" for i in file_items]
check("File: its sections with lines between (as GTK draws them), a submenu, nothing hidden that should be",
      labels == ["New", "Not now", "—", "Open Recent"], labels)
check("…keys only where the menu says them (GtkApplication's own shortcuts aren't in its menus)", file_items[0]["keys"] == "")
check("…what's off is off", file_items[1]["enabled"] is False and file_items[0]["enabled"] is True)
rec = file_items[3]
check("…the submenu's items", [c["label"] for c in rec.get("children", [])] == ["a.txt", "b.txt"], rec)
fmt = menus["groups"][1]["items"]
check("Format: a tick, not set", fmt[0]["label"] == "Bold" and fmt[0].get("checked") is False and not fmt[0].get("radio"), fmt[0])
check("…one of a group, chosen", fmt[1].get("radio") and fmt[1]["checked"] is True and fmt[2]["checked"] is False, fmt[1:3])
check("About first, its own", menus["top"][0]["label"] == "About Menus" and menus["top"][0]["id"].startswith("gtk:"))
check("Preferences as <App> Settings…", menus["top"][1]["label"] == "Menus Settings…" and menus["top"][1]["enabled"] and menus["settings"])
check("Quit last, its own, with its keys", menus["bottom"][-1]["label"] == "Quit Menus" and menus["bottom"][-1]["keys"] == "Ctrl+Q"
      and menus["bottom"][-1]["id"].startswith("gtk:"))
check("…Huginn's window items around it", [i["id"] for i in menus["bottom"][:3]] == ["shell:ontop", "shell:minimise", "shell:close"])
gm.activate(conn, where, refs[file_items[0]["id"]])
check("choosing one does it in the app", wait("activated:new") is not None)
gm.activate(conn, where, refs[rec["children"][1]["id"]])
check("…with its value", wait("activated:open:b.txt") is not None)
gm.activate(conn, where, refs[fmt[0]["id"]])
check("…a tick toggles", wait("bold:True") is not None and gm.read(conn, where, "Menus")[0]["groups"][1]["items"][0]["checked"] is True)
gm.activate(conn, where, refs[fmt[2]["id"]])
check("…one of a group changes", wait("size:large") is not None)
again = gm.read(conn, where, "Menus")[0]["groups"][1]["items"]
check("…and reads back so", again[2]["checked"] is True and again[1]["checked"] is False)
gm.activate(conn, where, refs[menus["bottom"][-1]["id"]])
check("its Quit is the app's", wait("activated:quit") is not None)
try:
    gm.read(conn, dict(where, bus=":1.9999"), "Menus")
    check("an app that's gone is said to be", False)
except GLib.Error:
    check("an app that's gone is said to be", True)
proc.kill()
subprocess.run(["kill", bus_pid])
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
