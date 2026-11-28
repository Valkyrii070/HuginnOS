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
check("…every realm's, the other realms' with their own index (Huginn's index is the icon theme's)",
      all(f"usr/share/icons/Huginn-{r}/cursors/wait" in want and f"usr/share/icons/Huginn-{r}/index.theme" in want for r in ("Bifrost", "Muspelheim", "Niflheim"))
      and "pointers" not in str(want.get("usr/share/icons/Huginn/index.theme", ("",))[0]))
check("…and the plain ones, each realm's", all(f"usr/share/icons/{t}/cursors/default" in want and f"usr/share/icons/{t}/index.theme" in want
      for t in ("Huginn-Plain", "Huginn-Bifrost-Plain", "Huginn-Muspelheim-Plain", "Huginn-Niflheim-Plain")))
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

# ------------------------------------------------------------------------------------------------ each realm's colours
sys.path.insert(0, str(KIT / "pointers"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import make_pointers as mp  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
_app = QGuiApplication.instance() or QGuiApplication(["x"])
realms = home / "realms"
got = subprocess.run(tool + ["--realms", str(realms), "--links"], capture_output=True, text=True, timeout=600)
check("every realm's pointers, side by side", got.returncode == 0 and all((realms / t / "cursors/default").is_file() for t in
      ("Huginn", "Huginn-Bifrost", "Huginn-Muspelheim", "Huginn-Niflheim")), got.stderr[-300:])
check("…and each again with a plain outline", all((realms / t / "cursors/default").is_file() for t in
      ("Huginn-Plain", "Huginn-Bifrost-Plain", "Huginn-Muspelheim-Plain", "Huginn-Niflheim-Plain")))
plain_index = (realms / "Huginn-Plain/index.theme").read_text()
check("…named Huginn Plain, falling back to Huginn", "Name=Huginn Plain" in plain_index and "Inherits=Huginn" in plain_index
      and "Inherits=Huginn-Bifrost-Plain" in (realms / "Huginn-Bifrost-Plain/cursor.theme").read_text())
bif = (realms / "Huginn-Bifrost/index.theme").read_text()
check("…the others named for their realm, falling back to Huginn", "Name=Huginn Bifröst" in bif and "Inherits=Huginn" in bif
      and "Inherits=Huginn-Muspelheim" in (realms / "Huginn-Muspelheim/cursor.theme").read_text())
def mean(img):
    w, h = img.width(), img.height()
    px = [img.pixelColor(x, y) for x in range(w) for y in range(h)]
    px = [c for c in px if c.alpha() > 200]
    return [sum(getattr(c, k)() for c in px) / max(1, len(px)) for k in ("red", "green", "blue")]
fire, ice = mean(mp.render("wait", "glass", 0.0, 64, "muspelheim")), mean(mp.render("wait", "glass", 0.0, 64, "niflheim"))
check("the busy pointer in the realm's colours: Muspelheim's fire, Niflheim's ice", fire[0] > fire[2] + 80 and ice[2] > ice[0] + 40, (fire, ice))
w0, w8 = mp.render("wait", "glass", 0.0, 64), mp.render("wait", "glass", 0.5, 64)
check("…it turns", w0 != w8)
edge = [w0.pixelColor(32 + int(19 * c), 32 + int(19 * s_)) for c, s_ in ((1, 0), (0, 1), (-1, 0), (0, -1), (0.7, 0.7), (-0.7, -0.7))]
check("…a solid disc, with no white or dark ring round it", all(c.alpha() > 200 and not (c.red() > 230 and c.green() > 230 and c.blue() > 230)
      and max(c.red(), c.green(), c.blue()) > 90 for c in edge), [(c.red(), c.green(), c.blue(), c.alpha()) for c in edge])
check("the rims follow the realm too", mp.svg("default", "glass", 0, "muspelheim") != mp.svg("default", "glass", 0, "aurora") and "#FFAD7A" in mp.svg("default", "glass", 0, "muspelheim"))
check("…and the marks (the link's orb)", "#FFAD7A" in mp.svg("pointer", "glass", 0, "muspelheim") and "@L1@" not in mp.svg("pointer", "glass", 0, "muspelheim"))
check("a realm that isn't one is refused", subprocess.run(tool + [str(home / "y"), "--realm", "asgard"], capture_output=True).returncode != 0)
# the plain ones: the same pointer, an ordinary outline (white round dark glass, near-black round frost), no glow
plain_svg, glow_svg = mp.svg("default", "glass", 0, "aurora", True), mp.svg("default", "glass", 0, "aurora")
check("plain: the same shape and glass, only the outline differs", plain_svg != glow_svg
      and plain_svg.replace("#FFFFFF", "").count("<path") == glow_svg.count("<path") and "#8AF5DE" not in plain_svg and "#8AF5DE" in glow_svg)
check("…white round the dark glass, near-black round frost", plain_svg.count('stop-color="#FFFFFF"') == 2
      and mp.svg("default", "frost", 0, "aurora", True).count('stop-color="#14181D"') == 2)
check("…the marks keep the realm's colours", "#8AF5DE" in mp.svg("pointer", "glass", 0, "aurora", True))
def tinted(img):
    """Pixels round the shape (not solid) that carry a colour, not just the grey of a shadow."""
    out = 0
    for x in range(img.width()):
        for y in range(img.height()):
            c = img.pixelColor(x, y)
            if 8 < c.alpha() < 160 and max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue()) > 40:
                out += 1
    return out
check("…no glow round it (only the shadow's grey)", tinted(mp.render("default", "glass", 0, 64, "aurora", True)) == 0
      and tinted(mp.render("default", "glass", 0, 64, "aurora")) > 20,
      (tinted(mp.render("default", "glass", 0, 64, "aurora", True)), tinted(mp.render("default", "glass", 0, 64, "aurora"))))
fire_plain = mean(mp.render("wait", "glass", 0.0, 64, "muspelheim", True))
check("…the busy pointer still in the realm's colours", fire_plain[0] > fire_plain[2] + 80, fire_plain)
# the look swaps Huginn's pointers to the realm's (plain ones staying plain); anyone else's stay
for t in ("Huginn-Bifrost", "Huginn-Plain", "Huginn-Bifrost-Plain"):
    (share / f"icons/{t}/cursors").mkdir(parents=True)
    (share / f"icons/{t}/cursors/default").write_bytes(b"x")
    (share / f"icons/{t}/index.theme").write_text(f"[Icon Theme]\nName={t.replace('-', ' ')}\n")
for before, realm, after in (("Huginn", "bifrost", "Huginn-Bifrost"), ("Huginn-Bifrost", "aurora", "Huginn"), ("Adwaita", "bifrost", "Adwaita"),
                             ("Huginn", "niflheim", "Huginn"), ("Huginn-Plain", "bifrost", "Huginn-Bifrost-Plain"),
                             ("Huginn-Bifrost-Plain", "aurora", "Huginn-Plain"), ("Huginn-Plain", "niflheim", "Huginn-Plain")):
    kin.write_text(f"[Mouse]\ncursorTheme={before}\n")
    hl._realm_pointers(realm)
    check(f"{before} in {realm}: {after}", f"cursorTheme={after}" in kin.read_text(), kin.read_text())
import huginn_looks as hls  # noqa: E402
hls.ICON_DIRS = [share / "icons"]
ids = [t["id"] for t in hls.list_pointer_themes()]
check("Settings lists Huginn once (the realm's colours come with it)", "Huginn" in ids and "Huginn-Bifrost" not in ids, ids)
check("…and Huginn Plain once, just after it", ids[:2] == ["Huginn", "Huginn-Plain"] and "Huginn-Bifrost-Plain" not in ids, ids)
icons.write_text("[Icon Theme]\nInherits=Huginn-Plain\n")
kin.write_text("[Mouse]\ncursorTheme=Huginn-Plain\n")
hl._realm_pointers("bifrost")
check("…X11 apps' default follows the plain ones too", icons.read_text().strip().endswith("Inherits=Huginn-Bifrost-Plain"), icons.read_text())
src = (KIT / "apps/huginn_settings.py").read_text()
ns = {}
exec(src[src.index("def pointer_choice"):src.index("def load_look")], ns)
check("Settings shows any realm's plain ones as Huginn Plain chosen", [ns["pointer_choice"](t) for t in ("Huginn-Bifrost-Plain", "Huginn-Muspelheim", "Huginn", "Adwaita")]
      == ["Huginn-Plain", "Huginn", "Huginn", "Adwaita"])

shutil.rmtree(home, ignore_errors=True)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
