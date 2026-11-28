#!/usr/bin/env python3
"""Huginn's own pointers: every pointer an app can ask for, drawn here and packed as an X cursor theme.

    make_pointers.py <out folder> [--style glass|frost] [--realm aurora|bifrost|muspelheim|niflheim] [--links]
    make_pointers.py --realms <icons folder> [--links]   all four realms' themes: Huginn (Aurora), Huginn-Bifrost, …,
        and the same again with a plain outline: Huginn-Plain, Huginn-Bifrost-Plain, …
    (--plain: one realm's plain-outline pointers)
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
from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QConicalGradient, QGuiApplication, QImage, QLinearGradient, QPainter, QRadialGradient  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

SIZES = (24, 32, 48, 64)
STYLE = "glass"                                 # the one the image and updates make
FRAMES, FRAME_MS = 16, 55                       # the busy orb: one turn in 0.88 s
STYLES = {
    # the shell's glass: a dark (or frosted light) body lit from above, a rim in the realm's two colours, a faint glow
    "glass": {"top": "#3B4550", "mid": "#1D232A", "low": "#0D1014", "edge": "#07090C", "sheen": 0.42, "glow": 34, "ink": "#E9FFF9", "rims": "light"},
    "frost": {"top": "#FFFFFF", "mid": "#E9EEF3", "low": "#C9D3DD", "edge": "#FFFFFF", "sheen": 0.55, "glow": 26, "ink": "#0D1014", "rims": "deep"},
}
REALM = "aurora"
# each realm's pointers: its theme's folder and name, the rim's two colours (light ones on dark glass, deep ones on
# frost), the faint glow's colour, and the colours that turn in the busy pointer (tokens.json's realms, widened)
REALMS = {
    "aurora": {"theme": "Huginn", "name": "Huginn", "light": ("#8AF5DE", "#A99BFF"), "deep": ("#0E9C80", "#5B45E0"), "glow": (61, 214, 181),
               "spin": ["#3DD6B5", "#86F2CF", "#4FB6F0", "#7B61FF", "#C36BFF", "#5FE0C0"]},
    "bifrost": {"theme": "Huginn-Bifrost", "name": "Huginn Bifröst", "light": ("#B3A6FF", "#FF9CCB"), "deep": ("#563AD1", "#C2367A"), "glow": (142, 123, 255),
                "spin": ["#8E7BFF", "#5BC8F5", "#6EF0A6", "#FFD36B", "#FF8A6B", "#FF7AB8"]},
    "muspelheim": {"theme": "Huginn-Muspelheim", "name": "Huginn Muspelheim", "light": ("#FFAD7A", "#FFD98A"), "deep": ("#AE4518", "#B8741A"),
                   "glow": (255, 138, 76), "spin": ["#FF5F3A", "#FF8A4C", "#FFC857", "#FFE7A3", "#FF9A5C", "#E8452C"]},
    "niflheim": {"theme": "Huginn-Niflheim", "name": "Huginn Niflheim", "light": ("#A6D6FF", "#E6F4FF"), "deep": ("#2361AE", "#4A86CF"), "glow": (124, 196, 255),
                 "spin": ["#4F8DF7", "#7CC4FF", "#D6EEFF", "#9FD2FF", "#6FA8FF", "#B9E2FF"]},
}
# the plain ones: the same pointers with an ordinary outline (white round the dark glass, near-black round frost) and
# no glow round them, for those who'd rather not have the realm's rim; the marks and the spinner keep the realm's colours
PLAIN_RIMS = {"light": ("#FFFFFF", "#FFFFFF"), "deep": ("#14181D", "#14181D")}
TEAL, VIOLET, RED = "#3DD6B5", "#7B61FF", "#FF5F57"


def theme_name(realm: str, plain: bool = False) -> str:
    """The theme's folder: Huginn (Aurora's), Huginn-Bifrost…, and Huginn-Plain, Huginn-Bifrost-Plain… for the plain ones."""
    return REALMS[realm]["theme"] + ("-Plain" if plain else "")

# ------------------------------------------------------------------------------------------------ the shapes
# Huginn's own: the arrow is a notched dart (a raven's quill, not the old arrow with a stem), things that move are
# grips, a link lights the orb in the dart, busy is the orb turning. Each shape: (body, extras, hotspot). body: SVG
# elements drawn as one glass silhouette (the rim goes round the whole of it); extras: drawn on top in their own
# colours. Units: a 32 square.
DART = ("M5 3 L6.7 24.3 Q6.9 25.9 8.1 24.9 L12.4 19.4 L21.2 18.9 Q22.7 18.8 21.7 17.7 "
        "Q14.6 9.9 5.9 3.2 Q5.3 2.7 5 3 Z")
SMALL_DART = ("M4.5 2.5 L5.8 19.5 Q6 20.8 7 20 L10.4 15.6 L17.4 15.2 Q18.6 15.1 17.8 14.2 "
              "Q12.1 8 5.3 2.7 Q4.8 2.3 4.5 2.5 Z")


def orb_dot(cx, cy, r):
    """Huginn's orb, small and lit: teal to violet, a highlight up and to the left."""
    return (f'<defs><radialGradient id="od" cx="0.36" cy="0.3" r="0.8"><stop offset="0" stop-color="#FFFFFF" stop-opacity="0.9"/>'
            f'<stop offset="0.45" stop-color="@L1@"/><stop offset="1" stop-color="@L2@"/></radialGradient></defs>'
            f'<circle cx="{cx}" cy="{cy}" r="{r + 1.1}" fill="#0B0E12" stroke="#FFFFFF" stroke-opacity="0.85" stroke-width="0.9"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#od)"/>')


def badge(cx, cy, inner, colour=None):
    """A round badge at the dart's foot (copy, link, menu, ask, no): the orb's colours, or red."""
    fill = colour or "url(#bd)"
    grad = ("" if colour else '<defs><linearGradient id="bd" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="@L1@"/>'
            '<stop offset="1" stop-color="@L2@"/></linearGradient></defs>')
    return (grad + f'<circle cx="{cx}" cy="{cy}" r="6.4" fill="{fill}" stroke="#0B0E12" stroke-width="1.3"/>'
            f'<g fill="none" stroke="#06231D" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{inner}</g>')


def head(x, y, angle, scale=1.0):
    """A notched dart head pointing along angle (degrees, 0 = up), its point at x, y: the ends of the two-way pointers."""
    return (f'<path transform="translate({x} {y}) rotate({angle}) scale({scale})" '
            'd="M0 0 L6.4 6.6 Q7 7.4 6 7.4 L2.2 6.2 L0 7.9 L-2.2 6.2 L-6 7.4 Q-7 7.4 -6.4 6.6 Z"/>')


def two_way(angle):
    """A two-headed pointer through the middle, turned by angle degrees: a slim shaft, a dart head at each end."""
    return (f'<g transform="rotate({angle} 16 16)">{head(16, 2.6, 0)}{head(16, 29.4, 180)}'
            '<rect x="14.7" y="8" width="2.6" height="16" rx="1.3"/></g>')


def bar_two_way(vertical):
    """A bar with a dart head out to each side: a column (or row) border being dragged."""
    return (f'<g transform="rotate({90 if vertical else 0} 16 16)"><rect x="14.4" y="6" width="3.2" height="20" rx="1.6"/>'
            f'{head(2.8, 16, -90)}{head(29.2, 16, 90)}<rect x="7.5" y="14.8" width="17" height="2.4" rx="1.2"/></g>')


def grip(w, h, gap):
    """Something to take hold of: a rounded glass grip (its dots are drawn on top)."""
    return f'<rect x="{16 - w / 2}" y="{16 - h / 2}" width="{w}" height="{h}" rx="{min(w, h) / 2 - 0.5}"/>'


def grip_dots(rows, cols, step, r, colour="url(#gd)"):
    out = ['<defs><linearGradient id="gd" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="@L1@"/>'
           '<stop offset="1" stop-color="@L2@"/></linearGradient></defs>']
    for i in range(rows):
        for j in range(cols):
            out.append(f'<circle cx="{16 + (j - (cols - 1) / 2) * step:.2f}" cy="{16 + (i - (rows - 1) / 2) * step:.2f}" r="{r}" fill="{colour}"/>')
    return "".join(out)


IBEAM = ('<rect x="14.9" y="6.5" width="2.2" height="19" rx="1.1"/>'
         '<path d="M10.6 5.2 Q16 5.2 16 8 Q16 5.2 21.4 5.2 L21.4 7.2 Q17.6 7.2 17.1 9 L14.9 9 Q14.4 7.2 10.6 7.2 Z"/>'
         '<path d="M10.6 26.8 Q16 26.8 16 24 Q16 26.8 21.4 26.8 L21.4 24.8 Q17.6 24.8 17.1 23 L14.9 23 Q14.4 24.8 10.6 24.8 Z"/>')
CROSS = ('<rect x="15" y="2.5" width="2" height="9" rx="1"/><rect x="15" y="20.5" width="2" height="9" rx="1"/>'
         '<rect x="2.5" y="15" width="9" height="2" rx="1"/><rect x="20.5" y="15" width="9" height="2" rx="1"/>')
MOVE = (head(16, 2.6, 0, 0.72) + head(16, 29.4, 180, 0.72) + head(2.6, 16, -90, 0.72) + head(29.4, 16, 90, 0.72)
        + '<rect x="14.9" y="6" width="2.2" height="20" rx="1.1"/><rect x="6" y="14.9" width="20" height="2.2" rx="1.1"/>')
CELL = '<path d="M13.2 4.5 Q13.2 3.5 14.2 3.5 L17.8 3.5 Q18.8 3.5 18.8 4.5 L18.8 13.2 L27.5 13.2 Q28.5 13.2 28.5 14.2 L28.5 17.8 Q28.5 18.8 27.5 18.8 L18.8 18.8 L18.8 27.5 Q18.8 28.5 17.8 28.5 L14.2 28.5 Q13.2 28.5 13.2 27.5 L13.2 18.8 L4.5 18.8 Q3.5 18.8 3.5 17.8 L3.5 14.2 Q3.5 13.2 4.5 13.2 L13.2 13.2 Z"/>'
QUILL = '<path d="M4 28 L5.2 22.2 Q12 10 25.6 4.2 Q27.6 3.4 27 5.4 Q22 19.6 9.8 26.8 Z"/>'
PICKER = ('<path d="M4 28 L4.6 24.4 L15.6 13.4 L18.6 16.4 L7.6 27.4 Z"/>'
          '<path d="M14.4 9.6 L17.4 6.6 Q20.6 3.4 23.8 4.2 Q27.8 5.4 27.8 8.2 Q28.6 11.4 25.4 14.6 L22.4 17.6 Z"/>')
LENS = '<circle cx="13" cy="13" r="9.2"/><path d="M19 17.2 L28.6 26.8 Q29.6 28.2 28.2 29.4 Q26.9 30.4 25.6 29.2 L16.6 19.6 Z"/>'


class Spinner:
    """The busy pointer: the realm's light turning in a disc, no outline round it (not macOS's pinwheel of separate
    colours: bands that run into each other like the aurora, two layers turning at different speeds, so it seems to
    swirl), lit from the top left like a drop of glass. Drawn with QPainter (QtSvg has no conical gradients)."""

    def __init__(self, cx, cy, r):
        self.cx, self.cy, self.r = cx, cy, r

    def draw(self, p: QPainter, size: int, turn: float, colours: list) -> None:
        k = size / 32
        cx, cy, r = self.cx * k, self.cy * k, self.r * k
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)

        def conic(angle, cols):
            g = QConicalGradient(QPointF(cx, cy), angle)
            for i, c in enumerate(cols + cols[:1]):
                g.setColorAt(i / len(cols), QColor(c))
            return g
        p.setBrush(conic(-turn * 360, colours))
        p.drawEllipse(QPointF(cx, cy), r, r)
        # the inner layer turns the other way, slower, and fades out toward the edge (no line where it ends): a swirl
        layer = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        layer.fill(Qt.GlobalColor.transparent)
        q = QPainter(layer)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(conic(turn * 180 + 90, colours[::-1]))
        q.drawEllipse(QPointF(cx, cy), r * 0.78, r * 0.78)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        fade = QRadialGradient(QPointF(cx, cy), r * 0.78)
        fade.setColorAt(0.0, QColor(0, 0, 0, 200))
        fade.setColorAt(0.45, QColor(0, 0, 0, 150))
        fade.setColorAt(1.0, QColor(0, 0, 0, 0))
        q.fillRect(layer.rect(), fade)
        q.end()
        p.drawImage(0, 0, layer)
        shade = QRadialGradient(QPointF(cx - r * 0.32, cy - r * 0.38), r * 1.32)
        shade.setColorAt(0.0, QColor(255, 255, 255, 150))
        shade.setColorAt(0.28, QColor(255, 255, 255, 40))
        shade.setColorAt(0.62, QColor(255, 255, 255, 0))
        shade.setColorAt(0.9, QColor(0, 0, 0, 40))
        shade.setColorAt(1.0, QColor(0, 0, 0, 70))
        p.setBrush(shade)
        p.drawEllipse(QPointF(cx, cy), r, r)


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
            f'<circle cx="{cx}" cy="{cy}" r="{r + ring / 2 + 1.2}" fill="#14171B" stroke="#FFFFFF" stroke-opacity="0.85" stroke-width="1.1"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r - ring / 2 - 0.6}" fill="url(#o)"/>'
            f'<path d="M{x0:.2f} {y0:.2f} A{r} {r} 0 1 1 {x1:.2f} {y1:.2f}" fill="none" stroke="url(#l)" '
            f'stroke-width="{ring}" stroke-linecap="round"/>')


NOT_ALLOWED = (f'<circle cx="16" cy="16" r="9.6" fill="#0B0E12" fill-opacity="0.35" stroke="#0B0E12" stroke-width="5.2"/>'
               f'<circle cx="16" cy="16" r="9.6" fill="none" stroke="{RED}" stroke-width="2.8"/>'
               f'<path d="M9.4 9.4 L22.6 22.6" stroke="#0B0E12" stroke-width="5.2" stroke-linecap="round"/>'
               f'<path d="M9.6 9.6 L22.4 22.4" stroke="{RED}" stroke-width="2.8" stroke-linecap="round"/>')

# name -> (body, extras or a function of the frame's turn, hotspot)
SHAPES = {
    "default": (f'<path d="{DART}"/>', "", (5.4, 3.6)),
    "pointer": (f'<path d="{DART}"/>', orb_dot(11.6, 14.6, 3.3), (5.4, 3.6)),
    "text": (IBEAM, "", (16, 16)),
    "vertical-text": (f'<g transform="rotate(90 16 16)">{IBEAM}</g>', "", (16, 16)),
    "crosshair": (CROSS, '<circle cx="16" cy="16" r="3.2" fill="none" stroke="@L1@" stroke-width="1.4"/>', (16, 16)),
    "move": (MOVE, orb_dot(16, 16, 2.2), (16, 16)),
    "grab": (grip(15, 20, 0), grip_dots(3, 2, 5, 1.55), (16, 16)),
    "grabbing": (grip(14, 14, 0), grip_dots(2, 2, 4.2, 1.7), (16, 16)),
    "cell": (CELL, "", (16, 16)),
    "not-allowed": ("", NOT_ALLOWED, (16, 16)),
    "copy": (f'<path d="{SMALL_DART}"/>', badge(23, 23, '<path d="M23 19.8 L23 26.2 M19.8 23 L26.2 23"/>'), (4.8, 3.1)),
    "alias": (f'<path d="{SMALL_DART}"/>', badge(23, 23, '<path d="M20.2 25.6 Q20.4 20.6 25.4 20.6 M23.4 18.8 L25.6 20.6 L23.6 22.6"/>'), (4.8, 3.1)),
    "context-menu": (f'<path d="{SMALL_DART}"/>', badge(23, 23, '<path d="M20.2 20.8 L25.8 20.8 M20.2 23 L25.8 23 M20.2 25.2 L25.8 25.2"/>'), (4.8, 3.1)),
    "help": (f'<path d="{SMALL_DART}"/>', badge(23, 23, '<path d="M21 21.4 Q21 19.4 23 19.4 Q25 19.4 25 21.2 Q25 22.6 23 23.2 L23 24.2"/>'
                                                    '<circle cx="23" cy="26.3" r="0.4"/>'), (4.8, 3.1)),
    "no-drop": (f'<path d="{SMALL_DART}"/>', badge(23, 23, '<path d="M20.6 20.6 L25.4 25.4"/><circle cx="23" cy="23" r="3.4"/>', RED), (4.8, 3.1)),
    "dnd-move": (f'<path d="{SMALL_DART}"/>', badge(23, 23, '<path d="M23 19.6 L23 26.4 M19.6 23 L26.4 23 M21.6 21 L23 19.6 L24.4 21 '
                                                        'M21.6 25 L23 26.4 L24.4 25"/>'), (4.8, 3.1)),
    "ns-resize": (two_way(0), "", (16, 16)),
    "ew-resize": (two_way(90), "", (16, 16)),
    "nesw-resize": (two_way(45), "", (16, 16)),
    "nwse-resize": (two_way(-45), "", (16, 16)),
    "col-resize": (bar_two_way(False), "", (16, 16)),
    "row-resize": (bar_two_way(True), "", (16, 16)),
    "zoom-in": (LENS, '<path d="M13 9 L13 17 M9 13 L17 13" stroke="INK" stroke-width="2" stroke-linecap="round"/>', (13, 13)),
    "zoom-out": (LENS, '<path d="M9 13 L17 13" stroke="INK" stroke-width="2" stroke-linecap="round"/>', (13, 13)),
    "pencil": (QUILL, '<path d="M5.2 22.2 L9.8 26.8" stroke="@L1@" stroke-width="1.5"/><path d="M8.6 21 Q15.6 12.6 24.2 6.8" fill="none" stroke="@L1@" stroke-opacity="0.6" stroke-width="0.9"/>', (4, 28)),
    "color-picker": (PICKER, "", (4, 28)),
    "wait": ("", Spinner(16, 16, 10.2), (16, 16)),
    "progress": (f'<path d="{SMALL_DART}"/>', Spinner(23.2, 23.2, 6.3), (4.8, 3.1)),
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


def layers(name, style, turn=0.0, realm=REALM, plain=False) -> tuple:
    """A pointer's drawing as layers: (the rim and its dark edge, the glass body, the body alone in white for the
    sheen, what goes on top), each an SVG. Plain: the rim an ordinary outline, not the realm's colours."""
    body, extras, _hot = SHAPES[name]
    s = STYLES[style]
    rim1, rim2 = (PLAIN_RIMS if plain else REALMS[realm])[s["rims"]]
    if isinstance(extras, Spinner):
        extras = ""                                            # (drawn by render())
    elif callable(extras):
        extras = extras(turn)
    head_ = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    rim = glass = mask = ""
    if body:
        rim = (head_ + f'<defs><linearGradient id="rim" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{rim1}"/>'
               f'<stop offset="1" stop-color="{rim2}"/></linearGradient></defs>'
               f'<g fill="{s["edge"]}" stroke="{s["edge"]}" stroke-opacity="0.75" stroke-width="3.9" stroke-linejoin="round">{body}</g>'
               f'<g fill="url(#rim)" stroke="url(#rim)" stroke-width="2.3" stroke-linejoin="round">{body}</g></svg>')
        glass = (head_ + f'<defs><linearGradient id="gl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{s["top"]}"/>'
                 f'<stop offset="0.5" stop-color="{s["mid"]}"/><stop offset="1" stop-color="{s["low"]}"/></linearGradient></defs>'
                 f'<g fill="url(#gl)">{body}</g></svg>')
        mask = head_ + f'<g fill="#FFFFFF">{body}</g></svg>'
    light = REALMS[realm]["light"]
    top = head_ + extras.replace("INK", s["ink"]).replace("@L1@", light[0]).replace("@L2@", light[1]) + "</svg>"   # (marks in the realm's colours)
    return rim, glass, mask, top


def svg(name, style, turn=0.0, realm=REALM, plain=False) -> str:
    """The pointer as one SVG, without the sheen, glow and spinner that render() adds (for looking at it elsewhere)."""
    rim, glass, _mask, top = layers(name, style, turn, realm, plain)
    inner = lambda t: t[t.index(">") + 1:-len("</svg>")] if t else ""  # noqa: E731
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">' + inner(rim) + inner(glass) + inner(top) + "</svg>"


def _draw(text: str, size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    if text:
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        QSvgRenderer(QByteArray(text.encode())).render(p, QRectF(0, 0, size, size))
        p.end()
    return img


def _soft(img: QImage, size: int, colour: QColor, shrink: int) -> QImage:
    """The silhouette in one colour, made soft by shrinking and growing it."""
    out = QImage(img)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(out.rect(), colour)
    p.end()
    small = max(3, size // shrink)
    out = out.scaled(small, small, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return out.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def render(name: str, style: str, turn: float, size: int, realm: str = REALM, plain: bool = False) -> QImage:
    """The pointer at size×size pixels, premultiplied ARGB: a faint glow in the realm's colour round it (not the plain
    ones) and a shadow below, the rim, the glass, light across its top half (the sheen), what goes on top, and the spinner."""
    s = STYLES[style]
    rim, glass, mask, top = layers(name, style, turn, realm, plain)
    art = _draw(rim, size)
    p = QPainter(art)
    p.drawImage(0, 0, _draw(glass, size))
    if mask:
        sheen = _draw(mask, size)
        q = QPainter(sheen)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        g = QLinearGradient(0, 0, 0, size)
        g.setColorAt(0.0, QColor(255, 255, 255, int(255 * s["sheen"])))
        g.setColorAt(0.48, QColor(255, 255, 255, 0))
        q.fillRect(sheen.rect(), g)
        q.end()
        p.drawImage(0, 0, sheen)
    p.drawImage(0, 0, _draw(top, size))
    spin = SHAPES[name][1]
    if isinstance(spin, Spinner):
        spin.draw(p, size, turn, REALMS[realm]["spin"])
    p.end()
    out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    if not plain:
        p.drawImage(0, 0, _soft(art, size, QColor(*REALMS[realm]["glow"], s["glow"]), 6))
    p.drawImage(round(size / 32), round(size * 1.4 / 32), _soft(art, size, QColor(0, 0, 0, 110), 5))
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


def make(name, style, realm=REALM, plain=False) -> bytes:
    _body, extras, (hx, hy) = SHAPES[name]
    frames = FRAMES if callable(extras) or isinstance(extras, Spinner) else 1
    images = []
    for size in SIZES:
        for f in range(frames):
            img = render(name, style, f / frames, size, realm, plain)
            images.append((size, min(size - 1, round(hx * size / 32)), min(size - 1, round(hy * size / 32)), FRAME_MS if frames > 1 else 0, img))
    return xcursor(images)


def write_theme(out: Path, style: str, links: bool, realm: str = REALM, plain: bool = False) -> int:
    """One realm's pointers into a theme folder. Aurora's are "Huginn" (inside Huginn's icon theme); the others are
    themes of pointers alone, "Huginn-Bifrost" and so on, which the look swaps to when the realm changes; the plain
    ones are "Huginn-Plain", "Huginn-Bifrost-Plain"…"""
    cursors = out / "cursors"
    cursors.mkdir(parents=True, exist_ok=True)
    r = REALMS[realm]
    name_ = r["name"] + (" Plain" if plain else "")
    if not (out / "index.theme").exists():
        comment = "Huginn OS's own pointers" + (f", in {realm.title()}'s colours" if realm != "aurora" else "") + (", with a plain outline" if plain else "")
        (out / "index.theme").write_text(f"[Icon Theme]\nName={name_}\nComment={comment}\n"
                                         + ("Inherits=Huginn\n" if realm != "aurora" or plain else ""), encoding="utf-8")
    (out / "cursor.theme").write_text(f"[Icon Theme]\nName={name_}\nInherits={theme_name(realm, plain)}\n", encoding="utf-8")
    count = 0
    for name in SHAPES:
        data = make(name, style, realm, plain)
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


def sheet(path: Path, styles, realms=("aurora",), plain=False) -> None:
    """A picture of the main pointers at 48 px, each look (and realm) on dark and on light."""
    names = ["default", "pointer", "text", "wait", "progress", "help", "grab", "grabbing", "move", "crosshair",
             "not-allowed", "copy", "alias", "ns-resize", "nwse-resize", "col-resize", "zoom-in", "color-picker"]
    cell, pad = 64, 24
    width = pad * 2 + cell * len(names)
    height = pad + len(styles) * len(realms) * 2 * (cell + 8) + pad
    img = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#0E1013"))
    p = QPainter(img)
    y = pad
    for realm in realms:
        for style in styles:
            for bg in ("#1E2227", "#E9ECEF"):
                p.fillRect(pad, y, cell * len(names), cell, QColor(bg))
                for i, name in enumerate(names):
                    p.drawImage(pad + i * cell + 8, y + 8, render(name, style, 0.15, 48, realm, plain))
                y += cell + 8
    p.end()
    img.save(str(path))


if __name__ == "__main__":
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    args = sys.argv[1:]
    style = args[args.index("--style") + 1] if "--style" in args else STYLE
    realm = args[args.index("--realm") + 1] if "--realm" in args else REALM
    if style not in STYLES:
        sys.exit(f"no style {style}: {', '.join(STYLES)}")
    if realm not in REALMS and realm != "all":
        sys.exit(f"no realm {realm}: {', '.join(REALMS)}")
    if "--sheet" in args:
        chosen = [style] if "--style" in args else list(STYLES)
        sheet(Path(args[args.index("--sheet") + 1]), chosen, list(REALMS) if realm == "all" else [realm], "--plain" in args)
        sys.exit(0)
    if "--realms" in args:                                     # every realm's theme, side by side in an icons folder
        base = Path(args[args.index("--realms") + 1])
        n = sum(write_theme(base / theme_name(key, plain), style, "--links" in args, key, plain) for plain in (False, True) for key in REALMS)
        print(n, "pointers written for", len(REALMS), "realms, with the realm's rim and plain")
        sys.exit(0)
    if not args or args[0].startswith("-"):
        sys.exit(__doc__)
    print(write_theme(Path(args[0]), style, "--links" in args, realm, "--plain" in args), "pointers written")
