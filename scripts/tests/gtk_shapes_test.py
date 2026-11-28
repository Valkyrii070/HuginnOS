#!/usr/bin/env python3
"""Huginn's shapes for GTK 3 apps (config/overlay/usr/share/themes/Huginn/gtk-3.0/shapes.css) in a real GTK 3 window:
GTK reads them without a word of complaint, its widgets take the tokens' radii, and a picture of the same controls
before and after.

    gtk_shapes_test.py <kit root> [picture.png]       (not as root; needs PyGObject with GTK 3 and an X display: DISPLAY)
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if os.geteuid() == 0:
    sys.exit("not as root")
if not os.environ.get("DISPLAY"):
    sys.exit("needs an X display (DISPLAY)")
KIT = Path(sys.argv[1]).resolve()
PICTURE = Path(sys.argv[2]) if len(sys.argv) > 2 else None
THEME = KIT / "config/overlay/usr/share/themes/Huginn"
work = Path(tempfile.mkdtemp(prefix="gtkshapes-"))
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"ok   {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


# the theme as it is, and the same without the shapes (for the picture of before and after)
share = work / "share/themes"
shutil.copytree(THEME, share / "Huginn")
shutil.copytree(THEME, share / "HuginnBefore")
for name in ("gtk.css", "gtk-dark.css"):
    f = share / "HuginnBefore/gtk-3.0" / name
    f.write_text(f.read_text().replace('@import url("shapes.css");', ""))
check("both of the theme's entries bring the shapes in", all('@import url("shapes.css");' in (THEME / "gtk-3.0" / n).read_text()
                                                              for n in ("gtk.css", "gtk-dark.css")))

APP = r'''
import json, sys
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
out = sys.argv[1]
win = Gtk.Window(title="Shapes")
win.set_default_size(560, 330)
hb = Gtk.HeaderBar(title="Huginn shapes", show_close_button=True)
win.set_titlebar(hb)
grid = Gtk.Grid(column_spacing=12, row_spacing=12, margin=16)
win.add(grid)
b = Gtk.Button(label="Button"); grid.attach(b, 0, 0, 1, 1)
s = Gtk.Button(label="Suggested"); s.get_style_context().add_class("suggested-action"); grid.attach(s, 1, 0, 1, 1)
d = Gtk.Button(label="Delete"); d.get_style_context().add_class("destructive-action"); grid.attach(d, 2, 0, 1, 1)
e = Gtk.Entry(text="Text field"); grid.attach(e, 0, 1, 2, 1)
sw = Gtk.Switch(active=True, halign=Gtk.Align.START, valign=Gtk.Align.CENTER); grid.attach(sw, 2, 1, 1, 1)
c1 = Gtk.CheckButton(label="Check", active=True); grid.attach(c1, 0, 2, 1, 1)
r1 = Gtk.RadioButton(label="Radio"); r1.set_active(True); grid.attach(r1, 1, 2, 1, 1)
combo = Gtk.ComboBoxText(); combo.append_text("Choice"); combo.set_active(0); grid.attach(combo, 2, 2, 1, 1)
sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1); sc.set_value(60); sc.set_draw_value(False); grid.attach(sc, 0, 3, 2, 1)
pb = Gtk.ProgressBar(fraction=0.45); pb.set_valign(Gtk.Align.CENTER); grid.attach(pb, 2, 3, 1, 1)
nb = Gtk.Notebook()
for t in ("First", "Second"):
    nb.append_page(Gtk.Label(label=t + " page"), Gtk.Label(label=t))
grid.attach(nb, 0, 4, 3, 1)
menu = Gtk.Menu(); menu.append(Gtk.MenuItem(label="Item"))
def radius(w, prop="border-radius"):
    return w.get_style_context().get_property(prop, Gtk.StateFlags.NORMAL)
def done():
    e.grab_focus()
    while Gtk.events_pending():
        Gtk.main_iteration()
    gw = win.get_window()
    w, h = gw.get_width(), gw.get_height()
    pix = Gdk.pixbuf_get_from_window(gw, 0, 0, w, h)
    pix.savev(out, "png", [], [])
    print("styles:" + json.dumps({"button": radius(b), "entry": radius(e), "switch": radius(sw), "menu": radius(menu),
                                  "headerbar_h": hb.get_allocated_height(), "suggested": radius(s)}), flush=True)
    Gtk.main_quit()
win.connect("destroy", Gtk.main_quit)
win.show_all()
GLib.timeout_add(900, lambda: done() and False)
Gtk.main()
'''
(work / "app.py").write_text(APP)
results = {}
for theme in ("HuginnBefore", "Huginn"):
    env = dict(os.environ, GTK_THEME=f"{theme}:dark", XDG_DATA_DIRS=f"{work / 'share'}:/usr/share", GDK_BACKEND="x11", NO_AT_BRIDGE="1",
               HOME=str(work / "home"), XDG_CONFIG_HOME=str(work / "home/.config"))
    got = subprocess.run([sys.executable, str(work / "app.py"), str(work / f"{theme}.png")], env=env, capture_output=True, text=True, timeout=60)
    line = next((x for x in got.stdout.splitlines() if x.startswith("styles:")), "styles:{}")
    import json
    results[theme] = (json.loads(line[7:]), got.stderr)
after, errors = results["Huginn"]
problems = [x for x in errors.splitlines() if "Theme parsing error" in x or "Gtk-WARNING" in x]
check("GTK reads the shapes without complaint", not problems, problems[:4])
check("buttons and entries: 7 px corners (the tokens' control radius)", after.get("button") == 7 and after.get("entry") == 7, after)
check("the suggested button keeps them", after.get("suggested") == 7, after)
check("switches: pills", (after.get("switch") or 0) >= 11, after)
check("menus: 10 px corners (the tokens' card radius)", after.get("menu") == 10, after)
check("a roomier header bar", (after.get("headerbar_h") or 0) >= 44, after)
before = results["HuginnBefore"][0]
check("…where Adwaita's own were different", before.get("button") != after.get("button") or before.get("menu") != after.get("menu"), before)

if PICTURE:
    try:
        from PIL import Image, ImageDraw
        a, b = Image.open(work / "HuginnBefore.png"), Image.open(work / "Huginn.png")
        sheet = Image.new("RGB", (a.width + b.width + 30, max(a.height, b.height) + 40), "#0E1013")
        sheet.paste(a, (10, 30))
        sheet.paste(b, (a.width + 20, 30))
        d = ImageDraw.Draw(sheet)
        d.text((14, 8), "Before: Adwaita's shapes", fill="#B9C2CB")
        d.text((a.width + 24, 8), "After: Huginn's shapes", fill="#B9C2CB")
        sheet.save(PICTURE)
    except ImportError:
        shutil.copy(work / "Huginn.png", PICTURE)
shutil.rmtree(work, ignore_errors=True)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
