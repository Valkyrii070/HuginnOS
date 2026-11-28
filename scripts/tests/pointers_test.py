#!/usr/bin/env python3
"""Huginn's own pointers (pointers/make_pointers.py): drawn, packed as Xcursor files that X's own cursor library reads
(libXcursor), named every way apps ask for them, and put in place by the image, by updates and for people still on
Breeze's.

    pointers_test.py <kit root>        (not as root; needs PySide6, and libXcursor for the reading part)
"""
import ctypes
import ctypes.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if os.geteuid() == 0:
    sys.exit("not as root")
KIT = Path(sys.argv[1]).resolve()
home = Path(tempfile.mkdtemp(prefix="pointers-"))
os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(home / ".local/share"),
                  QT_QPA_PLATFORM="offscreen")
sys.path.insert(0, str(KIT / "pointers"))
sys.path.insert(0, str(KIT / "apps"))
import make_pointers as mp  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"ok   {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


tool = [sys.executable, str(KIT / "pointers/make_pointers.py")]
got = subprocess.run(tool + [str(home / "links"), "--links"], capture_output=True, text=True, timeout=300)
check("drawn, with the other names as links", got.returncode == 0 and "pointers written" in got.stdout, got.stderr[-400:])
got = subprocess.run(tool + [str(home / "copies")], capture_output=True, text=True, timeout=300)
check("drawn, with the other names as files of their own", got.returncode == 0, got.stderr[-400:])
cur = home / "links/cursors"
names = set(mp.SHAPES) | {a for v in mp.ALIASES.values() for a in v}
check("every name apps ask for is there", all((cur / n).exists() for n in names) and len(names) >= 110, sorted(n for n in names if not (cur / n).exists()))
must = ["default", "left_ptr", "pointer", "hand2", "text", "xterm", "wait", "watch", "progress", "left_ptr_watch", "help", "crosshair",
        "move", "grab", "grabbing", "not-allowed", "no-drop", "copy", "alias", "context-menu", "cell", "vertical-text", "all-scroll",
        "col-resize", "row-resize", "n-resize", "e-resize", "s-resize", "w-resize", "ne-resize", "nw-resize", "se-resize", "sw-resize",
        "ns-resize", "ew-resize", "nesw-resize", "nwse-resize", "zoom-in", "zoom-out", "dnd-move", "dnd-copy", "dnd-link", "dnd-none",
        "openhand", "closedhand", "split_h", "split_v", "size_ver", "size_hor", "size_bdiag", "size_fdiag", "fleur", "color-picker", "pencil"]
check("…CSS's names, X's, GTK's and Qt's", all((cur / n).exists() for n in must), [n for n in must if not (cur / n).exists()])
check("with links: the other names point at the one drawn", (cur / "left_ptr").is_symlink() and os.readlink(cur / "left_ptr") == "default"
      and not (cur / "default").is_symlink())
check("without: files of their own, the same bytes", not (home / "copies/cursors/left_ptr").is_symlink()
      and (home / "copies/cursors/left_ptr").read_bytes() == (home / "copies/cursors/default").read_bytes())
check("X11's default theme file", (home / "links/cursor.theme").read_text().strip().endswith("Inherits=Huginn")
      and "Name=Huginn" in (home / "links/index.theme").read_text())
(home / "inside").mkdir()
(home / "inside/index.theme").write_text("[Icon Theme]\nName=Huginn\nComment=icons\nInherits=hicolor\n")
subprocess.run(tool + [str(home / "inside")], capture_output=True, timeout=300)
check("drawn into Huginn's icon theme, its index is left as it is", "Comment=icons" in (home / "inside/index.theme").read_text()
      and (home / "inside/cursors/default").is_file())

# ------------------------------------------------------------------------------------------------ X's own reading
lib = ctypes.util.find_library("Xcursor")
if lib:
    X = ctypes.CDLL(lib)

    class Image(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint), ("size", ctypes.c_uint), ("width", ctypes.c_uint), ("height", ctypes.c_uint),
                    ("xhot", ctypes.c_uint), ("yhot", ctypes.c_uint), ("delay", ctypes.c_uint), ("pixels", ctypes.POINTER(ctypes.c_uint32))]

    class Images(ctypes.Structure):
        _fields_ = [("nimage", ctypes.c_int), ("images", ctypes.POINTER(ctypes.POINTER(Image))), ("name", ctypes.c_char_p)]
    X.XcursorFilenameLoadImages.restype = ctypes.POINTER(Images)
    X.XcursorFilenameLoadImages.argtypes = [ctypes.c_char_p, ctypes.c_int]
    X.XcursorImagesDestroy.argtypes = [ctypes.POINTER(Images)]

    def load(name, size):
        p = X.XcursorFilenameLoadImages(str(cur / name).encode(), size)
        if not p:
            return []
        out = []
        for i in range(p.contents.nimage):
            im = p.contents.images[i].contents
            px = [im.pixels[k] for k in range(im.width * im.height)]
            out.append((im.size, im.width, im.height, im.xhot, im.yhot, im.delay, px))
        X.XcursorImagesDestroy(p)
        return out
    bad = []
    for name in mp.SHAPES:
        for size in mp.SIZES:
            imgs = load(name, size)
            if not imgs or any(i[0] != size or i[1] != size or i[2] != size or i[3] >= size or i[4] >= size for i in imgs):
                bad.append((name, size))
    check("libXcursor reads every one at 24, 32, 48 and 64 pixels", not bad, bad[:6])
    arrow = load("default", 32)[0]
    check("the dart's hotspot is its tip", (arrow[3], arrow[4]) == (5, 4), arrow[3:5])
    px = arrow[6]
    a = lambda v: v >> 24  # noqa: E731
    check("…something drawn there, and clear in the far corner", a(px[5 * 32 + 6]) > 128 and a(px[31 * 32 + 31]) == 0)
    premul = all(((v >> 16) & 255) <= a(v) and ((v >> 8) & 255) <= a(v) and (v & 255) <= a(v) for v in px)
    check("premultiplied, as X wants", premul)
    check("a soft shadow under it (part-clear pixels beyond the shape)", any(0 < a(v) < 90 for v in px))
    waits = load("wait", 32)
    check("busy: the orb turns, in frames with a delay", len(waits) == mp.FRAMES and all(w[5] == mp.FRAME_MS for w in waits)
          and waits[0][6] != waits[4][6], (len(waits), waits[0][5] if waits else None))
    check("…and the arrow with the orb", len(load("left_ptr_watch", 24)) == mp.FRAMES)
    hand = load("pointer", 48)[0]
    check("a link's pointer (the dart with the orb lit) points with the same tip", abs(hand[3] - 8) <= 1 and abs(hand[4] - 5) <= 1, hand[3:5])
    check("a resize pointer's hotspot is its middle", load("ns-resize", 32)[0][3:5] == (16, 16))
else:
    check("libXcursor to read them (not found here)", False)

# ------------------------------------------------------------------------------------------------ the two looks, the sheet
got = subprocess.run(tool + ["--sheet", str(home / "sheet.png")], capture_output=True, text=True, timeout=300)
check("a picture of the two looks (glass and frost)", got.returncode == 0 and (home / "sheet.png").stat().st_size > 20000, got.stderr[-300:])
check("a look that isn't one is refused", subprocess.run(tool + [str(home / "x"), "--style", "neon"], capture_output=True).returncode != 0)

# ------------------------------------------------------------------------------------------------ updates
import huginn_osupdate as up  # noqa: E402
theme = home / "theme"
(theme / "pointers").mkdir(parents=True)
check("updates draw them from the tree", up.make_pointers(KIT, theme / "pointers"))
want = up.wanted_files(KIT, theme)
check("…and put every one in place as a file", all(f"usr/share/icons/Huginn/cursors/{n}" in want for n in names)
      and "usr/share/icons/Huginn/cursor.theme" in want and want["usr/share/icons/Huginn/cursors/default"][1] == 0o644)
check("…GTK told the pointer theme too", "gtk-cursor-theme-name=Huginn" in want["etc/gtk-3.0/settings.ini"][0].read_text())
root = home / "root"
(root / "usr/share/icons/Huginn/cursors").mkdir(parents=True)
(root / "usr/share/icons/Huginn/cursors/left_ptr").symlink_to("default")
every = up.wanted_files
up.wanted_files = lambda kit, t=None: {k: v for k, v in every(kit, t).items() if k.startswith(up.POINTERS)}   # (only the pointers' part)
p = up.plan(KIT, root, theme)
up.wanted_files = every
check("…a name that's a link on the system is left a link", "usr/share/icons/Huginn/cursors/left_ptr" not in p["write"]
      and "usr/share/icons/Huginn/cursors/default" in p["write"])
shutil.rmtree(theme / "pointers")
check("…and none put in place when they couldn't be drawn", not any(k.startswith("usr/share/icons/Huginn/cursors/") for k in up.wanted_files(KIT, theme)))

# ------------------------------------------------------------------------------------------------ people on Breeze's
share = home / "share"
(share / "icons/Huginn/cursors").mkdir(parents=True)
(share / "icons/Huginn/cursors/default").write_bytes(b"x")
(share / "icons/breeze_cursors/cursors").mkdir(parents=True)
(share / "icons/Oxygen_Blue/cursors").mkdir(parents=True)
os.environ["HUGINN_LOOK_SHARE"] = str(share)
import huginn_look as hl  # noqa: E402
kin = home / ".config/kcminputrc"
for before, after in (("breeze_cursors", "Huginn"), ("", "Huginn"), ("Adwaita", "Adwaita"), ("Oxygen_Blue", "Oxygen_Blue"), ("Oxygen_Zion", "Huginn")):
    kin.parent.mkdir(parents=True, exist_ok=True)
    kin.write_text(f"[Mouse]\ncursorSize=32\ncursorTheme={before}\n" if before else "[Keyboard]\nRepeatDelay=600\n")
    hl._huginn_pointers()
    text = kin.read_text()
    check(f"on {before or 'nothing chosen'}: {after} afterwards", f"cursorTheme={after}" in text
          and ("cursorSize=32" in text if before else "RepeatDelay=600" in text), text)
icons = home / ".icons/default/index.theme"
icons.parent.mkdir(parents=True)
icons.write_text("[Icon Theme]\nInherits=breeze_cursors\n")
kin.write_text("[Mouse]\ncursorTheme=breeze_cursors\n")
hl._huginn_pointers()
check("X11 apps' default moves too", icons.read_text().strip().endswith("Inherits=Huginn"))

shutil.rmtree(home, ignore_errors=True)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
