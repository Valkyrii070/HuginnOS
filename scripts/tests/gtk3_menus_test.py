#!/usr/bin/env python3
"""Old GTK 3 apps' menu bars in the top bar (gtk/menus.c, libhuginn-menus.so): a real GTK 3 app with GtkMenuBars
(gtk3_menubar_app.py), on a bus of its own with a stand-in for Huginn's shell, read and told what to do the way the
shell does it (org.huginn.App.p<pid>: Menus, Trigger).

    gtk3_menus_test.py <kit root> <folder with libhuginn-menus.so>
        (not as root; needs dbus-daemon and an X display for GTK: DISPLAY)

Checked: the menu bar leaves the window only while the shell is there (and not with HUGINN_GTK_MENUS=0), comes back
when the shell goes and leaves again when it returns, and keeps what the app asked for meanwhile; the menus as the
shell reads them (names, shortcuts from an accel group, an accel path and a GMenuModel, a menu filled as it opens,
check and radio items, greyed and hidden items, separators, About/Settings/Quit moved to where Huginn has them); the
window in front decides, a dialog counts as its window; a menu bar in a header bar stays; doing items (and not doing
greyed ones, menus, or made-up ids); shortcuts still working with the menu bar gone.
"""
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if os.geteuid() == 0:
    sys.exit("not as root")
if not os.environ.get("DISPLAY"):
    sys.exit("needs an X display for GTK (DISPLAY)")
KIT = Path(sys.argv[1]).resolve()
MODULE = Path(sys.argv[2]).resolve() / "libhuginn-menus.so"
if not MODULE.is_file():
    sys.exit(f"no {MODULE}")
home = Path(tempfile.mkdtemp(prefix="gtk3menus-"))
os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_CACHE_HOME=str(home / ".cache"))
from gi.repository import Gio, GLib  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"ok   {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


got = subprocess.run(["dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"], capture_output=True, text=True)
address, bus_pid = got.stdout.split("\n")[:2]
os.environ["DBUS_SESSION_BUS_ADDRESS"] = address
conn = Gio.DBusConnection.new_for_address_sync(address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)

SHELL = "from gi.repository import Gio, GLib\nGio.bus_own_name(Gio.BusType.SESSION, 'org.huginn.Shell', 0, None, lambda *a: print('here', flush=True), None)\nGLib.MainLoop().run()\n"


class Shell:
    """A stand-in for Huginn's shell: owns org.huginn.Shell while it runs."""
    def __init__(self):
        self.proc = subprocess.Popen([sys.executable, "-c", SHELL], stdout=subprocess.PIPE, text=True)
        self.proc.stdout.readline()

    def stop(self):
        self.proc.terminate()
        self.proc.wait()
        wait_for(lambda: not owner("org.huginn.Shell"))


def owner(name):
    try:
        return conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                              GLib.Variant("(s)", (name,)), GLib.VariantType("(b)"), 0, 2000, None).unpack()[0]
    except GLib.Error:
        return False


def wait_for(test, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return True
        time.sleep(0.05)
    return test()


class App:
    def __init__(self, env=None):
        e = dict(os.environ, GDK_BACKEND="x11", NO_AT_BRIDGE="1", GTK_MODULES=str(MODULE))
        e.update(env or {})
        self.err = open(home / "app-err.txt", "w+")
        self.proc = subprocess.Popen([sys.executable, str(KIT / "scripts/tests/gtk3_menubar_app.py")], env=e, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.err, text=True, bufsize=1)
        self.out, self.buf, self.lines = self.proc.stdout.fileno(), b"", []
        self.wait_line("ready", 15)
        self.bus = f"org.huginn.App.p{self.proc.pid}"

    def read(self, seconds):
        """Its next line, if one comes within that time (read straight from the pipe: select and Python's own buffer
        don't mix)"""
        end = time.time() + seconds
        while b"\n" not in self.buf:
            left = end - time.time()
            if left <= 0:
                return None
            r, _, _ = select.select([self.out], [], [], left)
            if not r:
                return None
            chunk = os.read(self.out, 65536)
            if not chunk:
                return None
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        line = line.decode(errors="replace").strip()
        self.lines.append(line)
        return line

    def wait_line(self, want, seconds=5.0):
        end = time.time() + seconds
        while time.time() < end:
            line = self.read(end - time.time())
            if line is None:
                return False
            if line == want or (want.endswith("*") and line.startswith(want[:-1])):
                return line
        return False

    def say(self, text):
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def state(self):
        self.say("state")
        line = self.wait_line("state:*")
        return json.loads(line[6:]) if line else {}

    def menus(self):
        text = conn.call_sync(self.bus, "/org/huginn/App", "org.huginn.App", "Menus", None, GLib.VariantType("(s)"),
                              Gio.DBusCallFlags.NO_AUTO_START, 3000, None).unpack()[0]
        return json.loads(text)

    def trigger(self, ident):
        conn.call_sync(self.bus, "/org/huginn/App", "org.huginn.App", "Trigger", GLib.Variant("(s)", (ident,)), None,
                       Gio.DBusCallFlags.NO_AUTO_START, 3000, None)

    def quiet(self, seconds=0.6):
        """What it said in the next moments"""
        out = []
        end = time.time() + seconds
        while time.time() < end:
            line = self.read(end - time.time())
            if line is None:
                break
            out.append(line)
        return out

    def stop(self):
        if self.proc.poll() is None:
            self.say("quit")
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.err.seek(0)
        err = self.err.read()
        self.err.close()
        return err


def find(items, label):
    for it in items or []:
        if it.get("label") == label:
            return it
    return None


def group(menus, name):
    return next((g["items"] for g in menus.get("groups", []) if g["name"] == name), None)


# ------------------------------------------------------------------------------------------------ without the shell
app = App()
st = app.state()
check("no shell: the menu bar stays in the window", st.get("bar", [0])[0] is True and st["bar"][2] > 0 and st["canvasY"] > 0, st)
check("no shell: no menus offered on the bus", not owner(app.bus))
err = app.stop()
check("the module loads quietly", "huginn-menus" not in err and "CRITICAL" not in err and "WARNING" not in err.replace("Glycin running without sandbox", ""), err[-400:])

shell = Shell()
app = App({"HUGINN_GTK_MENUS": "0"})
st = app.state()
check("HUGINN_GTK_MENUS=0: the menu bar stays", st.get("bar", [0])[0] is True and not owner(app.bus), st)
app.stop()

# ------------------------------------------------------------------------------------------------ with the shell
app = App()
st = app.state()
check("the menus are offered on the bus", owner(app.bus), app.bus)
check("the menu bar has left the window (no room kept for it)", st.get("bar", [1])[0] is False and st["canvasY"] == 0, st)

m = app.menus()
check("app and toolkit", m.get("app") == "Sketchbook" and m.get("toolkit") == "gtk3", {k: m.get(k) for k in ("app", "toolkit")})
check("the menus, by name", [g["name"] for g in m.get("groups", [])] == ["File", "Edit", "View", "Help"], [g["name"] for g in m.get("groups", [])])
f = group(m, "File") or []
new, opn, rec = find(f, "New"), find(f, "Open…"), find(f, "Open Recent")
check("a shortcut from an accel group", new and new["keys"] == "Ctrl+N" and new["enabled"] and new["id"].startswith("gtk3:"), new)
check("a shortcut from an accel path", opn and opn["keys"] == "Ctrl+O", opn)
app.quiet(0.3)
check("a menu filled as it opens has its items", rec and [c["label"] for c in rec.get("children", [])] == ["drawing-1.sketch", "drawing-2.sketch"]
      and "filled:recent" in app.lines, (rec, app.lines))
check("Quit left File (and the line before it)", [i.get("label") for i in f] == ["New", "Open…", "Open Recent"], f)
e = group(m, "Edit") or []
check("a greyed item stays greyed, a hidden one isn't there, Preferences moved", [(i.get("label"), i.get("enabled"), i.get("keys")) for i in e]
      == [("Undo", False, "Ctrl+Z")], e)
v = group(m, "View") or []
labels = [i.get("label") if not i.get("sep") else "-" for i in v]
check("check, line, radio items, submenu", labels == ["Show Grid", "-", "Small", "Large", "Zoom"], labels)
g_, sm, lg = find(v, "Show Grid"), find(v, "Small"), find(v, "Large")
check("a check item", g_ and g_.get("checked") is True and "radio" not in g_ and g_["keys"] == "Ctrl+G", g_)
check("radio items", sm and sm.get("checked") is True and sm.get("radio") and lg and lg.get("checked") is False and lg.get("radio"), (sm, lg))
zm = find(v, "Zoom") or {}
check("keys with signs", [(c["label"], c["keys"]) for c in zm.get("children", [])] == [("Zoom In", "Ctrl++"), ("Zoom Out", "Ctrl+-")], zm)
h = group(m, "Help") or []
check("About left Help", [(i["label"], i["keys"]) for i in h] == [("Contents", "F1")], h)
top, bottom = m.get("top", []), m.get("bottom", [])
check("About is first", top and top[0]["label"] == "About Sketchbook" and top[0]["id"].startswith("gtk3:"), top)
check("Settings is the app's Preferences", len(top) > 1 and top[1]["label"] == "Sketchbook Settings…" and top[1]["id"].startswith("gtk3:")
      and m.get("settings") is True, top)
check("Quit is last, with its shortcut", bottom and bottom[-1]["label"] == "Quit Sketchbook" and bottom[-1]["id"].startswith("gtk3:")
      and bottom[-1]["keys"] == "Ctrl+Q", bottom)
check("the shell's own entries", [i["id"] for i in m.get("middle", [])] == ["shell:appWindows", "shell:pin"]
      and [i["id"] for i in bottom[:3]] == ["shell:ontop", "shell:minimise", "shell:close"], m.get("middle"))

app.quiet(0.3)
app.trigger(new["id"])
check("an item is done", "activated:new" in app.quiet())
app.trigger(g_["id"])
check("a check item turns", "activated:grid:false" in app.quiet())
app.trigger(lg["id"])
check("a radio item is chosen", "activated:large:true" in app.quiet())
m2 = app.menus()
v2 = group(m2, "View") or []
check("the menus read again say so", find(v2, "Show Grid").get("checked") is False and find(v2, "Large").get("checked") is True
      and find(v2, "Small").get("checked") is False, v2)
app.quiet(0.3)
app.trigger(top[0]["id"])
out = app.quiet()
check("About is the app's", "activated:about" in out, (top[0], out))
rec2 = find(group(m2, "File"), "Open Recent") or {}
app.trigger(rec2["children"][1]["id"])
out = app.quiet()
check("an item of a filled menu", "activated:recent:drawing-2.sketch" in out, out)
said = []
for bad in (find(e, "Undo")["id"], rec["id"], "gtk3:999999", "gtk3:abc", "gtk3:", "qt:1", "gtk3:-1"):
    app.trigger(bad)
said = [x for x in app.quiet() if x.startswith("activated")]
check("greyed items, menus and made-up ids do nothing", said == [], said)

# the keyboard, with the menu bar gone
app.say("key <Primary>n")
out = app.quiet(1.0)
check("a shortcut still works without the menu bar", "key:true" in out and "activated:new" in out, out)
app.say("key <Primary>o")
out = app.quiet(1.0)
check("an accel path's shortcut too", "key:true" in out and "activated:open" in out, out)
app.say("key <Primary>z")
out = app.quiet(1.0)
check("a greyed item's shortcut does nothing", "key:false" in out and "activated:undo" not in out, out)

# the app shows and hides its bar; the shell goes and comes back
app.say("show-bar")
st = app.state()
check("the app showing its menu bar: it stays gone", st.get("bar", [1])[0] is False, st)
app.say("hide-bar")
shell.stop()
time.sleep(0.4)
check("the shell gone, a bar the app had hidden stays hidden", app.state().get("bar", [1])[0] is False)
app.say("show-bar")
st = app.state()
check("the app shows it meanwhile: it's there", st.get("bar", [0])[0] is True, st)
shell = Shell()
check("the shell back: it leaves again", wait_for(lambda: app.state().get("bar", [1])[0] is False))
shell.stop()
check("the shell gone: it comes back", wait_for(lambda: app.state().get("bar", [0])[0] is True))
shell = Shell()
check("and leaves again", wait_for(lambda: app.state().get("bar", [1])[0] is False))

# a dialog belongs to its window
app.say("dialog")
time.sleep(0.5)
app.say("focus Sketchbook Info")
active = wait_for(lambda: app.state().get("active") == "Sketchbook Info")
m3 = app.menus()
check("a dialog in front: its window's menus", active and [g["name"] for g in m3.get("groups", [])] == ["File", "Edit", "View", "Help"], m3.get("groups"))

# a menu bar made from a GMenuModel, in a window with a menu bar in its header bar
app.say("notes")
time.sleep(0.6)
app.say("focus Notes")
check("Notes in front", wait_for(lambda: app.state().get("active") == "Notes"), app.state())
st = app.state()
check("its menu bar has left; the one in its header bar stays", st.get("notesBar", [1])[0] is False and st.get("headerBar", [0])[0] is True, st)
m4 = app.menus()
d = group(m4, "Document") or []
check("Notes' menus", [g["name"] for g in m4.get("groups", [])] == ["Document"], m4.get("groups"))
labels = [i.get("label") if not i.get("sep") else "-" for i in d]
check("a GMenuModel's items, sections as lines", labels == ["Save", "Word Wrap", "-", "Light", "Dark"], labels)
sv, wr, li, dk = (find(d, x) or {} for x in ("Save", "Word Wrap", "Light", "Dark"))
check("its shortcut, and a plain item isn't a check item", sv.get("keys") == "Ctrl+S" and "checked" not in sv, sv)
check("a toggle", wr.get("checked") is False and not wr.get("radio"), wr)
check("radio by state", li.get("checked") is True and li.get("radio") and dk.get("checked") is False and dk.get("radio"), (li, dk))
app.quiet(0.2)
app.trigger(wr["id"])
app.trigger(dk["id"])
app.trigger(sv["id"])
out = app.quiet(1.0)
check("a GMenuModel's items are done", "activated:wrap:true" in out and "activated:theme:dark" in out and "activated:save" in out, out)
d2 = group(app.menus(), "Document") or []
check("and say so", (find(d2, "Word Wrap") or {}).get("checked") is True and (find(d2, "Dark") or {}).get("checked") is True, d2)
err = app.stop()
check("nothing complained", "CRITICAL" not in err and "Gtk-WARNING" not in err, err[-600:])

shell.stop()
subprocess.run(["kill", bus_pid])
shutil.rmtree(home, ignore_errors=True)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
