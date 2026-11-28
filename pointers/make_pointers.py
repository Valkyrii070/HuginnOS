#!/usr/bin/env python3
"""Huginn's own pointers: every pointer an app can ask for, drawn here and packed as an X cursor theme.

    make_pointers.py <out folder> [--style slate|aurora|frost] [--links]
        -> <out>/cursors/<name> (Xcursor files, sizes 24, 32, 48 and 64), <out>/cursor.theme (for X11's default:
           /usr/share/icons/default), and <out>/index.theme when there is none (the image puts them in Huginn's icon
           theme, /usr/share/icons/Huginn, as Adwaita keeps its pointers in its icons)
    make_pointers.py --sheet <picture.png> [--style …]     a picture of the main ones, light and dark behind them

Each pointer is drawn on a 32-unit square (SVG, rendered by Qt, so it needs only PySide6), with a soft shadow, and
named the way X, CSS, GTK and Qt name it (the old names and Qt's hashed ones as well). With --links the other names
are symbolic links to the first (the image); without, copies (updates, which put files, not links, in place).
"""
from __future__ import annotations

import math
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QByteArray, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

SIZES = (24, 32, 48, 64)
STYLE = "slate"                                 # the one the image and updates make
FRAMES, FRAME_MS = 16, 55                       # the busy orb: one turn in 0.88 s
STYLES = {
    # fill, rim, the rim's second colour (a gradient when it differs), a hairline outside the rim (for light backgrounds)
    "slate": {"fill": "#1B1F24", "rim": "#FFFFFF", "rim2": "#FFFFFF", "edge": None},
    "aurora": {"fill": "#171B20", "rim": "#7BF0D6", "rim2": "#A99BFF", "edge": "#0B0D10"},
    "frost": {"fill": "#F4F6F8", "rim": "#14171B", "rim2": "#14171B", "edge": None},
}
TEAL, VIOLET, RED = "#3DD6B5", "#7B61FF", "#FF5F57"

# ------------------------------------------------------------------------------------------------ the shapes
# Each shape: (body, extras, hotspot). body: SVG elements drawn as one silhouette (the rim goes round the whole of
# it); extras: drawn on top in their own colours (badges, the orb). Units: a 32 square.
ARROW = "M6 3.5 L6 24.5 L11 19.8 L14.3 27.4 Q14.7 28.3 15.6 27.9 L18 26.9 Q18.9 26.5 18.5 25.6 L15.3 18.2 L22 18.2 Z"
SMALL_ARROW = "M5 3 L5 20.5 L9.2 16.6 L11.9 22.9 Q12.2 23.6 13 23.3 L14.9 22.5 Q15.6 22.2 15.3 21.5 L12.7 15.4 L18.3 15.4 Z"


def badge(cx, cy, inner, colour=TEAL):
    """A round badge at the arrow's foot (copy, link, menu, ask, no)."""
    return (f'<circle cx="{cx}" cy="{cy}" r="6.4" fill="{colour}" stroke="#FFFFFF" stroke-width="1.4"/>'
            f'<g fill="none" stroke="#06231D" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{inner}</g>')


def double_arrow(angle):
    """A two-headed arrow through the middle, turned by angle degrees."""
    shape = ("M16 2.5 L22 9 L18.2 9 L18.2 23 L22 23 L16 29.5 L10 23 L13.8 23 L13.8 9 L10 9 Z")
    return f'<path transform="rotate({angle} 16 16)" d="{shape}"/>'


def bar_arrows(vertical):
    """Two bars with arrows out to the sides: a column (or row) border being dragged."""
    shape = ("M14.2 7 L14.2 13.6 L9.5 13.6 L9.5 10 L3.5 16 L9.5 22 L9.5 18.4 L14.2 18.4 L14.2 25 L17.8 25 L17.8 18.4 "
             "L22.5 18.4 L22.5 22 L28.5 16 L22.5 10 L22.5 13.6 L17.8 13.6 L17.8 7 Z")
    return f'<path transform="rotate({90 if vertical else 0} 16 16)" d="{shape}"/>'


HAND = ('<rect x="11" y="2.5" width="5.4" height="16" rx="2.7"/>'
        '<rect x="15.6" y="10.5" width="4.8" height="10" rx="2.4"/><rect x="19.6" y="12" width="4.6" height="9" rx="2.3"/>'
        '<rect x="23.2" y="13.6" width="4.2" height="8.6" rx="2.1"/>'
        '<path d="M11 15 L8.2 12.9 Q6.2 11.6 5 13.2 Q4 14.6 5.4 16.4 L11 24 Q13.2 28.8 18.5 28.8 L21 28.8 Q27.4 28.8 27.4 22 L27.4 18 L11 18 Z"/>')
OPEN_HAND = ('<rect x="9.5" y="5" width="4.4" height="14" rx="2.2"/><rect x="13.8" y="3" width="4.4" height="15" rx="2.2"/>'
             '<rect x="18.1" y="4" width="4.4" height="14" rx="2.2"/><rect x="22.3" y="7" width="4.2" height="12" rx="2.1"/>'
             '<path d="M9.5 15 L7 12.6 Q5.2 11.2 3.9 12.7 Q2.8 14 4.2 15.8 L9.6 23.8 Q12 28.6 17 28.6 L19.5 28.6 Q26.5 28.6 26.5 21.5 L26.5 15 L9.5 15 Z"/>')
CLOSED_HAND = ('<rect x="9" y="10" width="4.6" height="9" rx="2.3"/><rect x="13.4" y="8.8" width="4.6" height="10" rx="2.3"/>'
               '<rect x="17.8" y="9.2" width="4.6" height="10" rx="2.3"/><rect x="22" y="10.6" width="4.4" height="9" rx="2.2"/>'
               '<path d="M9 14 L9 22 Q10.6 28.2 16.6 28.2 L19.6 28.2 Q26.4 28.2 26.4 21.6 L26.4 14 Z"/>')
IBEAM = ('<rect x="15" y="7" width="2" height="18" rx="1"/><rect x="11.5" y="5.6" width="9" height="2.4" rx="1.2"/>'
         '<rect x="11.5" y="24" width="9" height="2.4" rx="1.2"/>')
CROSS = ('<rect x="15" y="3" width="2" height="9.5" rx="1"/><rect x="15" y="19.5" width="2" height="9.5" rx="1"/>'
         '<rect x="3" y="15" width="9.5" height="2" rx="1"/><rect x="19.5" y="15" width="9.5" height="2" rx="1"/>'
         '<circle cx="16" cy="16" r="1.3"/>')
MOVE = ('<path d="M16 2.5 L21 8 L17.8 8 L17.8 14.2 L24 14.2 L24 11 L29.5 16 L24 21 L24 17.8 L17.8 17.8 L17.8 24 L21 24 '
        'L16 29.5 L11 24 L14.2 24 L14.2 17.8 L8 17.8 L8 21 L2.5 16 L8 11 L8 14.2 L14.2 14.2 L14.2 8 L11 8 Z"/>')
CELL = '<path d="M13 4 L19 4 L19 13 L28 13 L28 19 L19 19 L19 28 L13 28 L13 19 L4 19 L4 13 L13 13 Z"/>'
PENCIL = '<path d="M4 28 L5.5 21.5 L20.5 6.5 Q22.5 4.5 24.5 6.5 L25.5 7.5 Q27.5 9.5 25.5 11.5 L10.5 26.5 Z"/>'
PICKER = ('<path d="M4 28 L4.6 24.4 L15.6 13.4 L18.6 16.4 L7.6 27.4 Z"/>'
          '<path d="M14.4 9.6 L17.4 6.6 Q20.6 3.4 23.8 4.2 Q27.8 5.4 27.8 8.2 Q28.6 11.4 25.4 14.6 L22.4 17.6 Z"/>')
LENS = '<circle cx="13" cy="13" r="9"/><path d="M19 17.2 L28.6 26.8 Q29.6 28.2 28.2 29.4 Q26.9 30.4 25.6 29.2 L16.6 19.6 Z"/>'


def orb(cx, cy, r, turn, ring=2.6):
    """Huginn's orb with a light running round it: one frame of the busy pointer."""
    a0 = turn * 2 * math.pi
    sweep = math.radians(250)
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a0 + sweep), cy + r * math.sin(a0 + sweep)
    return (f'<defs><radialGradient id="o" cx="0.38" cy="0.32" r="0.75"><stop offset="0" stop-color="#9CF5E2"/>'
            f'<stop offset="0.5" stop-color="{TEAL}"/><stop offset="1" stop-color="{VIOLET}"/></radialGradient>'
            f'<linearGradient id="l" x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" gradientUnits="userSpaceOnUse">'
            f'<stop offset="0" stop-color="{VIOLET}" stop-opacity="0"/><stop offset="1" stop-color="#E8FFF9"/></linearGradient></defs>'
            f'<circle cx="{cx}" cy="{cy}" r="{r + ring / 2 + 1.2}" fill="#14171B" stroke="#FFFFFF" stroke-width="1.3"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r - ring / 2 - 0.6}" fill="url(#o)"/>'
            f'<path d="M{x0:.2f} {y0:.2f} A{r} {r} 0 1 1 {x1:.2f} {y1:.2f}" fill="none" stroke="url(#l)" '
            f'stroke-width="{ring}" stroke-linecap="round"/>')


# name -> (body, extras or a function of the frame's turn, hotspot)
SHAPES = {
    "default": (f'<path d="{ARROW}"/>', "", (6, 3.5)),
    "pointer": (HAND, "", (13.7, 2.8)),
    "text": (IBEAM, "", (16, 16)),
    "vertical-text": (f'<g transform="rotate(90 16 16)">{IBEAM}</g>', "", (16, 16)),
    "crosshair": (CROSS, "", (16, 16)),
    "move": (MOVE, "", (16, 16)),
    "grab": (OPEN_HAND, "", (16, 14)),
    "grabbing": (CLOSED_HAND, "", (16, 16)),
    "cell": (CELL, "", (16, 16)),
    "not-allowed": ("", f'<circle cx="16" cy="16" r="11" fill="none" stroke="#FFFFFF" stroke-width="6.4"/>'
                        f'<circle cx="16" cy="16" r="11" fill="none" stroke="{RED}" stroke-width="3.6"/>'
                        f'<path d="M8.3 8.3 L23.7 23.7" stroke="#FFFFFF" stroke-width="6.4" stroke-linecap="round"/>'
                        f'<path d="M8.6 8.6 L23.4 23.4" stroke="{RED}" stroke-width="3.6" stroke-linecap="round"/>', (16, 16)),
    "copy": (f'<path d="{SMALL_ARROW}"/>', badge(23, 23, '<path d="M23 19.8 L23 26.2 M19.8 23 L26.2 23"/>'), (5, 3)),
    "alias": (f'<path d="{SMALL_ARROW}"/>', badge(23, 23, '<path d="M20.2 25.6 Q20.4 20.6 25.4 20.6 M23.4 18.8 L25.6 20.6 L23.6 22.6"/>'), (5, 3)),
    "context-menu": (f'<path d="{SMALL_ARROW}"/>', badge(23, 23, '<path d="M20.2 20.8 L25.8 20.8 M20.2 23 L25.8 23 M20.2 25.2 L25.8 25.2"/>'), (5, 3)),
    "help": (f'<path d="{SMALL_ARROW}"/>', badge(23, 23, '<path d="M21 21.4 Q21 19.4 23 19.4 Q25 19.4 25 21.2 Q25 22.6 23 23.2 L23 24.2"/>'
                                                     '<circle cx="23" cy="26.3" r="0.4"/>'), (5, 3)),
    "no-drop": (f'<path d="{SMALL_ARROW}"/>', badge(23, 23, '<path d="M20.6 20.6 L25.4 25.4"/><circle cx="23" cy="23" r="3.4"/>', RED), (5, 3)),
    "dnd-move": (f'<path d="{SMALL_ARROW}"/>', badge(23, 23, '<path d="M23 19.6 L23 26.4 M19.6 23 L26.4 23 M21.6 21 L23 19.6 L24.4 21 '
                                                         'M21.6 25 L23 26.4 L24.4 25"/>'), (5, 3)),
    "ns-resize": (double_arrow(0), "", (16, 16)),
    "ew-resize": (double_arrow(90), "", (16, 16)),
    "nesw-resize": (double_arrow(45), "", (16, 16)),
    "nwse-resize": (double_arrow(-45), "", (16, 16)),
    "col-resize": (bar_arrows(False), "", (16, 16)),
    "row-resize": (bar_arrows(True), "", (16, 16)),
    "zoom-in": (LENS, '<path d="M13 9 L13 17 M9 13 L17 13" stroke="INK" stroke-width="2" stroke-linecap="round"/>', (13, 13)),
    "zoom-out": (LENS, '<path d="M9 13 L17 13" stroke="INK" stroke-width="2" stroke-linecap="round"/>', (13, 13)),
    "pencil": (PENCIL, f'<path d="M5.5 21.5 L10.5 26.5" stroke="{TEAL}" stroke-width="1.6"/>', (4, 28)),
    "color-picker": (PICKER, "", (4, 28)),
    "wait": ("", lambda turn: orb(16, 16, 8.6, turn), (16, 16)),
    "progress": (f'<path d="{SMALL_ARROW}"/>', lambda turn: orb(23, 23, 5.2, turn, 2.0), (5, 3)),
}
# every other name apps use for them (CSS, X, GTK, Qt's hashed names), each to the pointer drawn for it
ALIASES = {
    "default": ["left_ptr", "arrow", "top_left_arrow", "right_ptr"],
    "pointer": ["hand2", "hand1", "hand", "pointing_hand", "9d800788f1b08800ae810202380a0822", "e29285e634086352946a0e7090d73106"],
    "text": ["xterm", "ibeam"],
    "crosshair": ["cross", "tcross", "cross_reverse", "diamond_cross"],
    "move": ["fleur", "size_all", "all-scroll", "4498f0e0c1937ffe01fd06f973665830", "9081237383d90e509aa00f00170e968f"],
    "grab": ["openhand", "5aca4d189052212118709018842178c0", "fleur_grab"],
    "grabbing": ["closedhand", "208530c400c041818281048008011002", "dnd-none"],
    "cell": ["plus"],
    "not-allowed": ["forbidden", "crossed_circle", "circle", "03b6e0fcb3499374a867c041f52298f0", "X_cursor", "pirate"],
    "copy": ["dnd-copy", "1081e37283d90000800003c07f3ef6bf", "6407b0e94181790501fd1e167b474872", "b66166c04f8c3109214a4fbd64a50fc8"],
    "alias": ["link", "dnd-link", "3085a0e285430894940527032f8b26df", "640fb0e74195791501fd1ed57b41487f", "a2a266d0498c3104214a47bd64ab0fc8"],
    "help": ["question_arrow", "whats_this", "left_ptr_help", "dnd-ask", "5c6cd98b3f3ebcb1f9c7f1c204630408", "d9ce0ab605698f320427677b458ad60b"],
    "no-drop": ["dnd-no-drop"],
    "ns-resize": ["sb_v_double_arrow", "v_double_arrow", "size_ver", "n-resize", "s-resize", "top_side", "bottom_side",
                  "00008160000006810000408080010102", "double_arrow"],
    "ew-resize": ["sb_h_double_arrow", "h_double_arrow", "size_hor", "e-resize", "w-resize", "left_side", "right_side",
                  "028006030e0e7ebffc7f7070c0600140"],
    "nesw-resize": ["size_bdiag", "fd_double_arrow", "ne-resize", "sw-resize", "top_right_corner", "bottom_left_corner",
                    "fcf1c3c7cd4491d801f1e1c78f100000"],
    "nwse-resize": ["size_fdiag", "bd_double_arrow", "nw-resize", "se-resize", "top_left_corner", "bottom_right_corner",
                    "c7088f0f3e6c8088236ef8e1e3e70000"],
    "col-resize": ["split_h", "sb_h_double_arrow_split", "14fef782d02440884392942c11205230"],
    "row-resize": ["split_v", "2870a09082c103050810ffdffffe0204"],
    "pencil": ["draft"],
    "wait": ["watch"],
    "progress": ["left_ptr_watch", "half-busy", "08e8e1c95fe2fc01f976f1e063a24ccd", "3ecb610c1bf2410f44200f48c40d3599"],
    "zoom-in": [], "zoom-out": [], "vertical-text": [], "context-menu": [], "dnd-move": [], "color-picker": [],
}


def svg(name, style, turn=0.0) -> str:
    body, extras, _hot = SHAPES[name]
    s = STYLES[style]
    if callable(extras):
        extras = extras(turn)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">']
    if body:
        rim = s["rim"] if s["rim"] == s["rim2"] else "url(#rim)"
        if rim != s["rim"]:
            parts.append(f'<defs><linearGradient id="rim" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{s["rim"]}"/>'
                         f'<stop offset="1" stop-color="{s["rim2"]}"/></linearGradient></defs>')
        if s["edge"]:
            parts.append(f'<g fill="{s["edge"]}" stroke="{s["edge"]}" stroke-width="4.6" stroke-linejoin="round">{body}</g>')
        parts.append(f'<g fill="{rim}" stroke="{rim}" stroke-width="3.2" stroke-linejoin="round">{body}</g>')
        parts.append(f'<g fill="{s["fill"]}">{body}</g>')
    parts.append(extras.replace("INK", s["rim"] if s["fill"] > "#8" else "#FFFFFF"))   # (marks inside: the rim's colour on a light fill)
    parts.append("</svg>")
    return "".join(parts)


def render(text: str, size: int) -> QImage:
    """The drawing at size×size pixels, with a soft shadow below and to the right, premultiplied ARGB."""
    renderer = QSvgRenderer(QByteArray(text.encode()))
    art = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    art.fill(Qt.GlobalColor.transparent)
    p = QPainter(art)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    shadow = QImage(art)                                         # the silhouette, made soft by shrinking and growing it
    p = QPainter(shadow)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(shadow.rect(), QColor(0, 0, 0, 120))
    p.end()
    small = max(4, size // 5)
    shadow = shadow.scaled(small, small, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    shadow = shadow.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawImage(round(size / 32), round(size * 1.4 / 32), shadow)
    p.drawImage(0, 0, art)
    p.end()
    return out


def xcursor(images) -> bytes:
    """An Xcursor file: images are (nominal size, hot x, hot y, delay ms, QImage)."""
    header = struct.pack("<4sIII", b"Xcur", 16, 0x10000, len(images))
    toc, chunks, at = b"", b"", 16 + 12 * len(images)
    for nominal, hx, hy, delay, img in images:
        w, h = img.width(), img.height()
        pixels = bytes(img.constBits())[: w * h * 4]           # premultiplied 0xAARRGGBB, little-endian: as Xcursor wants
        chunk = struct.pack("<IIIIIIIII", 36, 0xFFFD0002, nominal, 1, w, h, hx, hy, delay) + pixels
        toc += struct.pack("<III", 0xFFFD0002, nominal, at)
        chunks += chunk
        at += len(chunk)
    return header + toc + chunks


def make(name, style) -> bytes:
    _body, extras, (hx, hy) = SHAPES[name]
    frames = FRAMES if callable(extras) else 1
    images = []
    for size in SIZES:
        for f in range(frames):
            img = render(svg(name, style, f / frames), size)
            images.append((size, min(size - 1, round(hx * size / 32)), min(size - 1, round(hy * size / 32)), FRAME_MS if frames > 1 else 0, img))
    return xcursor(images)


def write_theme(out: Path, style: str, links: bool) -> int:
    cursors = out / "cursors"
    cursors.mkdir(parents=True, exist_ok=True)
    if not (out / "index.theme").exists():
        (out / "index.theme").write_text("[Icon Theme]\nName=Huginn\nComment=Huginn OS's own pointers\n", encoding="utf-8")
    (out / "cursor.theme").write_text("[Icon Theme]\nName=Huginn\nInherits=Huginn\n", encoding="utf-8")
    count = 0
    for name in SHAPES:
        data = make(name, style)
        (cursors / name).write_bytes(data)
        count += 1
        for other in ALIASES.get(name, []):
            target = cursors / other
            if target.is_symlink() or target.exists():
                target.unlink()
            if links:
                target.symlink_to(name)
            else:
                target.write_bytes(data)
            count += 1
    return count


def sheet(path: Path, styles) -> None:
    """A picture of the main pointers at 48 px, each look on dark and on light."""
    names = ["default", "pointer", "text", "wait", "progress", "help", "grab", "grabbing", "move", "crosshair",
             "not-allowed", "copy", "alias", "ns-resize", "nwse-resize", "col-resize", "zoom-in", "color-picker"]
    cell, pad = 64, 24
    width = pad * 2 + cell * len(names)
    height = pad + len(styles) * 2 * (cell + 8) + pad
    img = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#0E1013"))
    p = QPainter(img)
    y = pad
    for style in styles:
        for bg in ("#1E2227", "#E9ECEF"):
            p.fillRect(pad, y, cell * len(names), cell, QColor(bg))
            for i, name in enumerate(names):
                p.drawImage(pad + i * cell + 8, y + 8, render(svg(name, style, 0.15), 48))
            y += cell + 8
    p.end()
    img.save(str(path))


if __name__ == "__main__":
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    args = sys.argv[1:]
    style = args[args.index("--style") + 1] if "--style" in args else STYLE
    if style not in STYLES:
        sys.exit(f"no style {style}: {', '.join(STYLES)}")
    if "--sheet" in args:
        chosen = [style] if "--style" in args else list(STYLES)
        sheet(Path(args[args.index("--sheet") + 1]), chosen)
        sys.exit(0)
    if not args or args[0].startswith("-"):
        sys.exit(__doc__)
    print(write_theme(Path(args[0]), style, "--links" in args), "pointers written")
