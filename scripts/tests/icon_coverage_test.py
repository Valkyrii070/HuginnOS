#!/usr/bin/env python3
"""Huginn's icon theme standing on its own (nothing of Breeze's underneath): every standard icon name and the ones GTK
and Qt ask for themselves (scripts/icon_names.py) answered, found by Qt's and GTK's own lookups, every file a valid
picture, the line icons recolourable, and the tree's icons exactly what the sources make.

    icon_coverage_test.py <kit root>        (not as root; needs PySide6, and PyGObject with GTK 3 for GTK's part)
"""
import filecmp
import os
import sys
import tempfile
from pathlib import Path

if os.geteuid() == 0:
    sys.exit("not as root")
KIT = Path(sys.argv[1]).resolve()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(KIT / "scripts"))
import icon_names  # noqa: E402
import icon_symbols  # noqa: E402

THEME = KIT / "config/overlay/usr/share/icons/Huginn"
ICONS = THEME.parent
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"ok   {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


names = icon_names.names()
check("every standard name, and GTK's and Qt's own, answered", not icon_names.missing(THEME) and len(names) > 400, icon_names.missing(THEME)[:20])
index = (THEME / "index.theme").read_text()
check("nothing of KDE's underneath: it inherits only the apps' own icons", "Inherits=hicolor\n" in index and "breeze" not in index.lower())
dirs = next(line for line in index.splitlines() if line.startswith("Directories=")).split("=", 1)[1].split(",")
present = sorted({str(f.parent.relative_to(THEME)) for f in THEME.rglob("*.svg")})
check("every folder of icons is listed in the index, and has a section", all(d in dirs and f"[{d}]" in index for d in present),
      [d for d in present if d not in dirs])

from PySide6.QtCore import QByteArray  # noqa: E402
from PySide6.QtGui import QGuiApplication, QIcon  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402
app = QGuiApplication(sys.argv[:1])
bad = [f.name for f in THEME.rglob("*.svg") if not QSvgRenderer(QByteArray(f.read_bytes())).isValid()]
check(f"every picture is valid SVG ({sum(1 for _ in THEME.rglob('*.svg'))} of them)", not bad, bad[:6])
sym = list((THEME / "symbolic").rglob("*.svg"))
check("the line icons take the text colour (Qt's colour scheme class, GTK's currentColor)",
      all("ColorScheme-Text" in f.read_text() and "currentColor" in f.read_text() for f in sym))

QIcon.setThemeSearchPaths([str(ICONS)])
QIcon.setFallbackThemeName("hicolor")
QIcon.setThemeName("Huginn")
qt_miss = [n for n in names if not (QIcon.hasThemeIcon(n) or QIcon.hasThemeIcon(n + "-symbolic"))]
check("Qt finds every one in the theme", not qt_miss, qt_miss[:20])
pic = QIcon.fromTheme("contact-new").pixmap(32, 32).toImage()
check("…and draws it", not pic.isNull() and any(pic.pixelColor(x, y).alpha() > 0 for x in range(32) for y in range(32)))

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    theme = Gtk.IconTheme.new()
    theme.set_search_path([str(ICONS)])
    theme.set_custom_theme("Huginn")
    gtk_miss = [n for n in names if not (theme.has_icon(n) or theme.has_icon(n + "-symbolic"))]
    check("GTK finds every one in the theme", not gtk_miss, gtk_miss[:20])
    info = theme.lookup_icon("network-wireless-signal-weak-symbolic", 16, 0)
    check("…a -symbolic one as a symbolic icon GTK recolours", info is not None and info.is_symbolic())
except (ImportError, ValueError) as err:
    check(f"GTK to look them up ({err})", False)

# made from the sources: the glyphs (shell/qml/Glyph.qml, apps/qml/Glyph.qml, scripts/icon_glyphs_more.js) and recipes
with tempfile.TemporaryDirectory() as tmp:
    _dirs, count = icon_symbols.write(Path(tmp))
    for ctx in ("actions", "status"):
        made, kept = Path(tmp) / "symbolic" / ctx, THEME / "symbolic" / ctx
        cmp = filecmp.dircmp(made, kept)
        check(f"the tree's {ctx} icons are what the sources make", not cmp.left_only and not cmp.right_only and not cmp.diff_files,
              (cmp.left_only[:4], cmp.right_only[:4], cmp.diff_files[:4]))

    def ink(name):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage, QPainter
        img = QImage(48, 48, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        f = next(f for f in (Path(tmp) / "symbolic" / c / f"{n}.svg" for c in ("actions", "status") for n in (name, name + "-symbolic")) if f.is_file())
        QSvgRenderer(QByteArray(f.read_bytes())).render(p, QRectF(0, 0, 48, 48))
        p.end()
        return [img.pixelColor(x, y).alpha() > 60 for y in range(48) for x in range(48)]
    corner, bare = ink("contact-new"), ink("avatar-default")
    check("a badge: the glyph with something drawn in its foot's corner", corner != bare
          and sum(corner[y * 48 + x] for y in range(30, 46) for x in range(30, 46)) > sum(bare[y * 48 + x] for y in range(30, 46) for x in range(30, 46)))
    slash = ink("notifications-disabled")
    check("crossed out: a line from corner to corner", (slash[9 * 48 + 9] or slash[10 * 48 + 10]) and (slash[38 * 48 + 38] or slash[37 * 48 + 37]))
    mirror_a, mirror_b = ink("view-sidebar-start"), ink("view-sidebar-end")
    check("mirrored: the end sidebar is the start one turned round", mirror_a == [mirror_b[y * 48 + (47 - x)] for y in range(48) for x in range(48)])
    ring = ink("emblem-readonly")
    check("an emblem: the glyph in a ring", ring[24 * 48 + 2] or ring[24 * 48 + 3] or ring[24 * 48 + 4])

tiles = {f.stem for f in (THEME / "scalable/apps").glob("*.svg")}
check("Huginn's app tiles stand for the standard app names", {"accessories-calculator", "utilities-system-monitor", "applications-games",
                                                              "preferences-desktop", "system-file-manager"} <= tiles)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
