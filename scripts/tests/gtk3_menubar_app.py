#!/usr/bin/env python3
"""A GTK 3 app with old-style menu bars, for gtk3_menus_test.py and for trying gtk/menus.c in a session by hand.

Sketchbook's window has a GtkMenuBar built item by item: shortcuts from an accel group and from an accel path, a menu
the app fills as it opens, check and radio items, a hidden and a greyed item, About, Preferences and Quit. Its second
window, Notes ("notes"), has one made from a GMenuModel (gtk_menu_bar_new_from_model), and a menu bar in its header
bar that is to be left alone.

It says what it does on stdout ("ready", "activated:<what>", "filled:recent", "state:<json>") and takes commands
on stdin: state, dialog, notes, focus <title>, key <GTK accelerator>, hide-bar, show-bar, quit.

    gtk3_menubar_app.py        (with GTK_MODULES=<path to libhuginn-menus.so> to try the module)
"""
import json
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402


def say(*a):
    print(*a, flush=True)


GLib.set_application_name("Sketchbook")
accel = Gtk.AccelGroup()
Gtk.AccelMap.add_entry("<Sketchbook>/File/Open", Gdk.KEY_o, Gdk.ModifierType.CONTROL_MASK)
windows = {}


def item(menu, label, what=None, key=None, path=None, check=None, group=None):
    if group is not None or check == "radio":
        it = Gtk.RadioMenuItem.new_with_mnemonic_from_widget(group, label)
    elif check is not None:
        it = Gtk.CheckMenuItem.new_with_mnemonic(label)
    else:
        it = Gtk.MenuItem.new_with_mnemonic(label)
    if what:
        def act(w):
            if isinstance(w, Gtk.CheckMenuItem):
                say(f"activated:{what}:{str(w.get_active()).lower()}")
            else:
                say("activated:" + what)
        it.connect("activate", act)
    if key:
        k, m = Gtk.accelerator_parse(key)
        it.add_accelerator("activate", accel, k, m, Gtk.AccelFlags.VISIBLE)
    if path:
        it.set_accel_path(path)
    menu.append(it)
    return it


def top(bar, label):
    t = Gtk.MenuItem.new_with_mnemonic(label)
    m = Gtk.Menu()
    m.set_accel_group(accel)
    t.set_submenu(m)
    bar.append(t)
    return m


# ------------------------------------------------------------------------------------------------ Sketchbook
win = Gtk.Window(title="Sketchbook")
win.set_default_size(480, 320)
win.add_accel_group(accel)
win.connect("destroy", Gtk.main_quit)
windows["Sketchbook"] = win
bar = Gtk.MenuBar()
fm = top(bar, "_File")
item(fm, "_New", "new", "<Primary>n")
item(fm, "_Open…", "open", path="<Sketchbook>/File/Open")
recent = item(fm, "Open _Recent")
rm = Gtk.Menu()
recent.set_submenu(rm)


def fill(_w):
    for c in rm.get_children():
        rm.remove(c)
    for name in ("drawing-1.sketch", "drawing-2.sketch"):
        item(rm, name, "recent:" + name)
    rm.show_all()
    say("filled:recent")


recent.connect("activate", fill)
fm.append(Gtk.SeparatorMenuItem())
item(fm, "_Quit", "quit", "<Primary>q")
em = top(bar, "_Edit")
item(em, "_Undo", "undo", "<Primary>z").set_sensitive(False)
item(em, "_Redo", "redo").set_no_show_all(True)
em.append(Gtk.SeparatorMenuItem())
item(em, "_Preferences", "preferences")
vm = top(bar, "_View")
grid = Gtk.CheckMenuItem.new_with_mnemonic("Show _Grid")
grid.set_active(True)
grid.connect("activate", lambda w: say(f"activated:grid:{str(w.get_active()).lower()}"))
k, m = Gtk.accelerator_parse("<Primary>g")
grid.add_accelerator("activate", accel, k, m, Gtk.AccelFlags.VISIBLE)
vm.append(grid)
vm.append(Gtk.SeparatorMenuItem())
small = Gtk.RadioMenuItem.new_with_mnemonic(None, "_Small")
vm.append(small)
large = Gtk.RadioMenuItem.new_with_mnemonic_from_widget(small, "_Large")
vm.append(large)
small.set_active(True)
large.connect("activate", lambda w: w.get_active() and say("activated:large:true"))
small.connect("activate", lambda w: w.get_active() and say("activated:small:true"))
zoom = item(vm, "_Zoom")
zm = Gtk.Menu()
zm.set_accel_group(accel)
zoom.set_submenu(zm)
item(zm, "Zoom _In", "zoomin", "<Primary>plus")
item(zm, "Zoom _Out", "zoomout", "<Primary>minus")
hm = top(bar, "_Help")
item(hm, "_Contents", "help", "F1")
item(hm, "_About Sketchbook", "about")
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
box.pack_start(bar, False, False, 0)
canvas = Gtk.Label(label="canvas")
box.pack_start(canvas, True, True, 0)
win.add(box)

# ------------------------------------------------------------------------------------------------ Notes
notes_parts = {}


def notes():
    n = Gtk.Window(title="Notes")
    n.set_default_size(360, 240)
    windows["Notes"] = n
    group = Gio.SimpleActionGroup()
    save = Gio.SimpleAction.new("save", None)
    save.connect("activate", lambda *a: say("activated:save"))
    group.add_action(save)
    wrap = Gio.SimpleAction.new_stateful("wrap", None, GLib.Variant("b", False))
    wrap.connect("change-state", lambda a, v: (a.set_state(v), say("activated:wrap:" + str(v.unpack()).lower())))
    group.add_action(wrap)
    theme = Gio.SimpleAction.new_stateful("theme", GLib.VariantType("s"), GLib.Variant("s", "light"))
    theme.connect("change-state", lambda a, v: (a.set_state(v), say("activated:theme:" + v.unpack())))
    group.add_action(theme)
    n.insert_action_group("doc", group)
    model, doc = Gio.Menu(), Gio.Menu()
    it = Gio.MenuItem.new("_Save", "doc.save")
    it.set_attribute_value("accel", GLib.Variant("s", "<Primary>s"))
    doc.append_item(it)
    doc.append("Word _Wrap", "doc.wrap")
    themes = Gio.Menu()
    themes.append("_Light", "doc.theme::light")
    themes.append("_Dark", "doc.theme::dark")
    doc.append_section(None, themes)
    model.append_submenu("_Document", doc)
    mbar = Gtk.MenuBar.new_from_model(model)
    header = Gtk.HeaderBar(title="Notes", show_close_button=True)
    hbar = Gtk.MenuBar()
    hmenu = top(hbar, "☰")
    item(hmenu, "Notes Help", "notes-help")
    header.pack_end(hbar)
    n.set_titlebar(header)
    nb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    nb.pack_start(mbar, False, False, 0)
    nb.pack_start(Gtk.TextView(), True, True, 0)
    n.add(nb)
    n.show_all()
    notes_parts.update(bar=mbar, header=hbar)


def dialog():
    d = Gtk.Window(title="Sketchbook Info", transient_for=win, type_hint=Gdk.WindowTypeHint.DIALOG)
    d.add(Gtk.Label(label="A dialog"))
    windows["Sketchbook Info"] = d
    d.show_all()


def shown(w):
    return [w.get_visible(), w.get_mapped(), w.get_allocated_height()] if w else None


def state():
    active = next((t for t, w in windows.items() if w.is_active()), "")
    return {"bar": shown(bar), "canvasY": canvas.get_allocation().y, "notesBar": shown(notes_parts.get("bar")),
            "headerBar": shown(notes_parts.get("header")), "active": active}


def command(line):
    words = line.strip().split(" ", 1)
    if words[0] == "state":
        say("state:" + json.dumps(state()))
    elif words[0] == "dialog":
        dialog()
    elif words[0] == "notes":
        notes()
    elif words[0] == "focus" and len(words) > 1 and words[1] in windows:
        windows[words[1]].present()
    elif words[0] == "key" and len(words) > 1:          # a shortcut pressed in the window, as GTK hands it on
        k, m = Gtk.accelerator_parse(words[1])
        say("key:" + str(Gtk.accel_groups_activate(win, k, m)).lower())
    elif words[0] == "hide-bar":
        bar.hide()
    elif words[0] == "show-bar":
        bar.show()
    elif words[0] == "quit":
        Gtk.main_quit()


pending = b""


def commands(fd, _cond):
    """Every whole line that has come (read straight from stdin: GLib's watch and Python's buffer don't mix)"""
    global pending
    chunk = os.read(fd, 65536)
    if not chunk:
        Gtk.main_quit()
        return False
    pending += chunk
    while b"\n" in pending:
        line, pending = pending.split(b"\n", 1)
        command(line.decode(errors="replace"))
    return True


try:
    from gi.repository import GLibUnix                  # (PyGObject 3.52 on)
    GLibUnix.fd_add_full(GLib.PRIORITY_DEFAULT, sys.stdin.fileno(), GLib.IOCondition.IN | GLib.IOCondition.HUP, commands)
except (ImportError, AttributeError):
    GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, sys.stdin.fileno(), GLib.IO_IN | GLib.IO_HUP, commands)
win.show_all()
GLib.timeout_add(300, lambda: say("ready") and False)
Gtk.main()
