"""Slides' model: a deck of slides, each a free canvas of items (text, shapes, pictures) on a 1080-unit-high slide.

The deck is plain JSON ("huginn-slides-2"):
    {"format", "theme", "look" (a design read from a PowerPoint file, until another theme is picked), "size": "16:9"|"4:3",
     "slides": [{"id", "layout", "items": [...], "notes", "bg", "transition": {"kind", "ms"}, "hidden"}]}
An item: {"id", "kind": "text"|"shape"|"picture"|"table"|"chart", "role": ""|"title"|"subtitle"|"body"|"body2", "x", "y", "w", "h", "rot",
          "shape", "fill", "line", "lineW", "flipH", "flipV", "arrow", "paras", "valign", "fit", "src", "anim", "locked"}
A table also has "cells" (rows of strings), "header" and "banded" (bool), "accent" and "size" (points); a chart "chart"
("column"|"bar"|"line"|"pie"), "cats" (its labels), "series" ([{"name", "values"}]), "title" and "legend".
A paragraph: {"runs": [{"t", "b", "i", "u", "s", "color", "size" (points), "font"}], "lvl", "list": ""|"bullet"|"number", "align"}
A run keeps only what differs from its place's defaults (the role, the level and the theme), so a new theme re-colours
and re-fonts everything that wasn't set by hand. One slide unit is 6350 EMU: 1920 x 1080 is PowerPoint's 13.33 x 7.5 in.
"""
import copy
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QTextBlockFormat,
                           QTextCharFormat, QTextCursor, QTextDocument, QTextListFormat, QTransform)

SLIDE_H = 1080
EMU = 6350                     # EMU in one slide unit
PT = 2.0                       # slide units in one point (a slide is 540 pt high)
INSET_X, INSET_Y = 14.4, 7.2   # PowerPoint's text insets: 0.1 in and 0.05 in
INDENT = 40                    # Qt's indent per list level, in slide units (the same in every text view)


def slide_w(size: str) -> int:
    return 1440 if size == "4:3" else 1920


# ---------------------------------------------------------------------------------------------- themes
THEMES = {
    "realm": {"name": "Realm", "bg": {"from": "#0F2624", "to": "#17192C", "angle": 0}, "title": "#ECEFF3", "text": "#D5DAE0",
              "accents": ["#43D9B8", "#7B61FF", "#FF8A4C", "#7CC4FF", "#FFC857", "#FF7AB8"], "head": "Inter", "body": "Inter", "deco": "orb"},
    "paper": {"name": "Paper", "bg": {"color": "#FFFFFF"}, "title": "#101317", "text": "#2B3138",
              "accents": ["#0A8071", "#5F3DC4", "#E8590C", "#1C7ED6", "#F59F00", "#C2255C"], "head": "Inter", "body": "Inter", "deco": "bar"},
    "night": {"name": "Night", "bg": {"color": "#101317"}, "title": "#ECEFF3", "text": "#C9CED6",
              "accents": ["#7CC4FF", "#B197FC", "#FFA94D", "#63E6BE", "#FFD43B", "#F783AC"], "head": "Inter", "body": "Inter", "deco": "bar"},
    "dawn": {"name": "Dawn", "bg": {"from": "#FFF4E6", "to": "#FFE3E3", "angle": 90}, "title": "#3B1F2B", "text": "#5C3D46",
             "accents": ["#E8590C", "#C2255C", "#5F3DC4", "#0B7285", "#F08C00", "#2B8A3E"], "head": "Caladea", "body": "Inter", "deco": "bar"},
    "ocean": {"name": "Ocean", "bg": {"from": "#0B3D91", "to": "#062A5C", "angle": 90}, "title": "#FFFFFF", "text": "#DCE7F7",
              "accents": ["#4DD0E1", "#FFD54F", "#FF8A65", "#AED581", "#BA68C8", "#F06292"], "head": "Inter", "body": "Inter", "deco": "orb"},
    "chalk": {"name": "Chalk", "bg": {"color": "#2F3A32"}, "title": "#F8F9FA", "text": "#E9ECEF",
              "accents": ["#FFD43B", "#74C0FC", "#FF8787", "#8CE99A", "#E599F7", "#FFA94D"], "head": "Carlito", "body": "Carlito", "deco": ""},
}


def look_of(deck: dict) -> dict:
    """The design in use: the deck's own (from a PowerPoint file) or one of the themes."""
    if deck.get("look"):
        base = dict(THEMES["paper"])
        base.update(deck["look"])
        return base
    return THEMES.get(deck.get("theme"), THEMES["realm"])


def colour(value: str, look: dict, fallback: str = "") -> str:
    """'accent1'…'accent6', 'title', 'text' or '#RRGGBB' → '#RRGGBB'; '' stays '' (nothing)."""
    if not value:
        return fallback
    if value.startswith("accent") and value[6:].isdigit():
        acc = look["accents"]
        return acc[(int(value[6:]) - 1) % len(acc)]
    if value in ("title", "text"):
        return look[value]
    return value


# ---------------------------------------------------------------------------------------------- layouts
LAYOUTS = ("title", "content", "section", "two", "titleonly", "blank")
LAYOUT_NAMES = {"title": "Title", "content": "Title & Text", "section": "Section", "two": "Two Columns", "titleonly": "Title Only", "blank": "Blank"}


def placeholders(layout: str, size: str = "16:9") -> list:
    """The placeholders a layout puts on a new slide, as (role, x, y, w, h)."""
    w = slide_w(size)
    m = 120 * w / 1920                   # side margin
    if layout == "title":
        return [("title", 160 * w / 1920, 300, w - 320 * w / 1920, 260), ("subtitle", 160 * w / 1920, 590, w - 320 * w / 1920, 160)]
    if layout == "content":
        return [("title", m, 60, w - 2 * m, 170), ("body", m, 280, w - 2 * m, 720)]
    if layout == "section":
        return [("title", 160 * w / 1920, 380, w - 320 * w / 1920, 220), ("body", 160 * w / 1920, 620, w - 320 * w / 1920, 140)]
    if layout == "two":
        half = (w - 2 * m - 40) / 2
        return [("title", m, 60, w - 2 * m, 170), ("body", m, 280, half, 720), ("body2", m + half + 40, 280, half, 720)]
    if layout == "titleonly":
        return [("title", m, 60, w - 2 * m, 170)]
    return []


def role_style(role: str, layout: str) -> dict:
    """A role's defaults: size in points, bold, which font (head/body), colour (title/text), alignment, anchoring, list."""
    centred = layout == "title"
    if role == "title":
        if centred:
            return {"size": 54, "b": False, "font": "head", "color": "title", "align": "center", "valign": "bottom", "list": ""}
        if layout == "section":
            return {"size": 48, "b": True, "font": "head", "color": "title", "align": "left", "valign": "bottom", "list": ""}
        return {"size": 40, "b": True, "font": "head", "color": "title", "align": "left", "valign": "middle", "list": ""}
    if role == "subtitle":
        return {"size": 24, "b": False, "font": "body", "color": "text", "align": "center", "valign": "top", "list": ""}
    if role in ("body", "body2"):
        if layout == "section":
            return {"size": 22, "b": False, "font": "body", "color": "text", "align": "left", "valign": "top", "list": ""}
        return {"size": 26, "b": False, "font": "body", "color": "text", "align": "left", "valign": "top", "list": "bullet"}
    return {"size": 24, "b": False, "font": "body", "color": "text", "align": "left", "valign": "top", "list": ""}


LEVEL_SIZES = (1.0, 0.85, 0.77, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7)


def para_size(base: float, lvl: int, role: str) -> float:
    """Body text gets smaller with each level, as in PowerPoint (26, 22, 20, 18…)."""
    if role in ("body", "body2"):
        return round(base * LEVEL_SIZES[min(lvl, 8)])
    return base


def new_item(kind: str, iid: str, x: float, y: float, w: float, h: float, **extra) -> dict:
    item = {"id": iid, "kind": kind, "role": "", "x": round(x, 2), "y": round(y, 2), "w": round(w, 2), "h": round(h, 2), "rot": 0}
    if kind in ("text", "shape"):
        item.update({"paras": [{"runs": [], "lvl": 0, "list": "", "align": ""}], "valign": "", "fit": 1.0})
    if kind == "shape":
        item.update({"shape": "rect", "fill": "accent1", "line": "", "lineW": 0, "valign": "middle"})
    item.update(extra)
    return item


def new_table(iid: str, x: float, y: float, w: float, rows: int, cols: int) -> dict:
    rows, cols = max(1, min(30, rows)), max(1, min(12, cols))
    item = new_item("table", iid, x, y, w, 70 * rows)
    item.update({"cells": [["" for _ in range(cols)] for _ in range(rows)], "header": True, "banded": True, "accent": "accent1", "size": 18})
    return item


def new_chart(iid: str, x: float, y: float, w: float, h: float, kind: str) -> dict:
    item = new_item("chart", iid, x, y, w, h)
    item.update({"chart": kind if kind in CHARTS else "column", "title": "", "legend": True, "cats": ["North", "South", "East", "West"],
                 "series": [{"name": "This year", "values": [42, 35, 28, 50]}, {"name": "Last year", "values": [36, 30, 31, 41]}]})
    if item["chart"] == "pie":
        item["series"] = item["series"][:1]
    return item


CHARTS = ("column", "bar", "line", "pie")


def grid_of(item: dict) -> list:
    """A table's cells, or a chart's data as a grid: the series' names along the top, the labels down the side."""
    if item.get("kind") == "table":
        return [list(r) for r in item.get("cells") or [[""]]]
    series = item.get("series") or []
    head = [""] + [s.get("name", "") for s in series]
    rows = [head]
    for k, cat in enumerate(item.get("cats") or []):
        rows.append([str(cat)] + [_num_text(s.get("values", [])[k] if k < len(s.get("values", [])) else "") for s in series])
    return rows


def _num_text(v) -> str:
    if v in ("", None):
        return ""
    v = float(v)
    return str(int(v)) if v == int(v) else f"{v:g}"


def with_grid(item: dict, grid: list) -> dict:
    """The item with its cells, or its chart's data, from a grid (as grid_of gives it)."""
    rows = [[str(c)[:500] for c in r] for r in grid if isinstance(r, list)][:60] or [[""]]
    width = max(1, min(20, max(len(r) for r in rows)))
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = dict(item)
    if item.get("kind") == "table":
        out["cells"] = [r[:12] for r in rows[:30]]
        return out
    out["series"] = []
    for j in range(1, width):
        vals = []
        for r in rows[1:]:
            try:
                vals.append(float(r[j].replace(",", "").replace("%", "")) if r[j].strip() else 0.0)
            except ValueError:
                vals.append(0.0)
        out["series"].append({"name": rows[0][j] or f"Series {j}", "values": vals})
    out["cats"] = [r[0] for r in rows[1:]]
    if not out["series"]:
        out["series"] = [{"name": "Series 1", "values": [0.0] * len(out["cats"])}]
    return out


def paint_table(p: QPainter, item: dict, look: dict) -> None:
    cells = item.get("cells") or [[""]]
    rows, cols = len(cells), max(len(r) for r in cells)
    w, h = item["w"], item["h"]
    cw, rh = w / cols, h / rows
    accent = QColor(colour(item.get("accent") or "accent1", look) or "#1C7ED6")
    ground = QColor((look.get("bg") or {}).get("color") or (look.get("bg") or {}).get("from") or "#FFFFFF")
    dark_bg = ground.lightnessF() < 0.5
    text = QColor(look.get("text", "#2B3138"))
    band = QColor(accent)
    band.setAlphaF(0.14 if dark_bg else 0.10)
    plain = QColor("#FFFFFF") if not dark_bg else ground.lighter(115)     # cells are solid: nothing shows through them
    font = QFont(look.get("body") or "Inter")
    font.setPixelSize(max(6, int(float(item.get("size") or 18) * PT)))
    p.setFont(font)
    for r in range(rows):
        for c in range(cols):
            rect = QRectF(c * cw, r * rh, cw, rh)
            head = item.get("header", True) and r == 0
            if head:
                p.fillRect(rect, accent)
            else:
                p.fillRect(rect, plain)
                if item.get("banded", True) and r % 2 == (1 if item.get("header", True) else 0):
                    p.fillRect(rect, band)
            p.setPen(QPen(QColor(255, 255, 255, 90) if dark_bg else QColor(0, 0, 0, 40), 1.5))
            p.drawRect(rect)
            f = QFont(font)
            f.setBold(head)
            p.setFont(f)
            p.setPen(QColor("#FFFFFF") if head else text)
            t = cells[r][c] if c < len(cells[r]) else ""
            p.drawText(rect.adjusted(14, 4, -14, -4), int(Qt.AlignVCenter | Qt.TextWordWrap | (Qt.AlignRight if _is_number(t) and not head else Qt.AlignLeft)), t)


def _is_number(t: str) -> bool:
    try:
        float(str(t).replace(",", "").replace("%", "").replace("$", "").replace("€", "").replace("£", "").strip())
        return True
    except ValueError:
        return False


def paint_chart(p: QPainter, item: dict, look: dict) -> None:
    w, h = item["w"], item["h"]
    series = item.get("series") or []
    cats = item.get("cats") or []
    kind = item.get("chart", "column")
    accents = look.get("accents") or ["#1C7ED6"]
    ink = QColor(look.get("text", "#2B3138"))
    faint = QColor(ink)
    faint.setAlphaF(0.25)
    font = QFont(look.get("body") or "Inter")
    font.setPixelSize(26)
    p.setFont(font)
    top = 0.0
    if item.get("title"):
        tf = QFont(font)
        tf.setPixelSize(36)
        tf.setBold(True)
        p.setFont(tf)
        p.setPen(QColor(look.get("title", "#101317")))
        p.drawText(QRectF(0, 0, w, 54), int(Qt.AlignCenter), item["title"])
        p.setFont(font)
        top = 64.0
    legend_h = 44.0 if item.get("legend", True) and (len(series) > 1 or kind == "pie") else 0.0
    if legend_h:
        names = [c for c in cats] if kind == "pie" else [s.get("name", "") for s in series]
        x = 0.0
        p.setPen(ink)
        for k, name in enumerate(names[:12]):
            p.fillRect(QRectF(x, h - 30, 22, 22), QColor(accents[k % len(accents)]))
            tw = p.fontMetrics().horizontalAdvance(name) + 54
            p.drawText(QRectF(x + 30, h - 38, tw, 38), int(Qt.AlignVCenter | Qt.AlignLeft), name)
            x += tw
    area = QRectF(0, top, w, h - top - legend_h - 6)
    if kind == "pie":
        vals = [max(0.0, float(v)) for v in ((series[0].get("values") if series else []) or [])]
        total = sum(vals) or 1.0
        d = min(area.width(), area.height())
        box = QRectF(area.center().x() - d / 2, area.center().y() - d / 2, d, d)
        start = 90 * 16
        p.setPen(QPen(QColor("#FFFFFF"), 3))
        for k, v in enumerate(vals):
            span = -int(round(v / total * 360 * 16))
            p.setBrush(QColor(accents[k % len(accents)]))
            p.drawPie(box, start, span)
            start += span
        return
    allv = [float(v) for s_ in series for v in s_.get("values", [])] or [0.0]
    lo, hi = min(0.0, min(allv)), max(0.0, max(allv))
    if hi == lo:
        hi = lo + 1
    step = _nice((hi - lo) / 5)
    hi = math.ceil(hi / step) * step
    lo = math.floor(lo / step) * step
    label_w = max(p.fontMetrics().horizontalAdvance(_num_text(v)) for v in (lo, hi)) + 16
    cat_h = 40.0
    plot = QRectF(area.left() + label_w, area.top() + 10, area.width() - label_w - 10, area.height() - cat_h - 10) if kind != "bar" else \
        QRectF(area.left() + 140, area.top() + 10, area.width() - 150, area.height() - cat_h - 10)
    n = max(1, len(cats))
    ticks = int(round((hi - lo) / step))
    p.setPen(QPen(faint, 1.5))
    for t in range(ticks + 1):
        v = lo + t * step
        if kind == "bar":
            x = plot.left() + (v - lo) / (hi - lo) * plot.width()
            p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))
            p.setPen(ink)
            p.drawText(QRectF(x - 60, plot.bottom() + 4, 120, cat_h), int(Qt.AlignHCenter | Qt.AlignTop), _num_text(v))
        else:
            y = plot.bottom() - (v - lo) / (hi - lo) * plot.height()
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
            p.setPen(ink)
            p.drawText(QRectF(area.left(), y - 20, label_w - 10, 40), int(Qt.AlignRight | Qt.AlignVCenter), _num_text(v))
        p.setPen(QPen(faint, 1.5))
    p.setPen(ink)
    for k, cat in enumerate(cats):
        if kind == "bar":
            y = plot.top() + (k + 0.5) / n * plot.height()
            p.drawText(QRectF(area.left(), y - 20, 130, 40), int(Qt.AlignRight | Qt.AlignVCenter), str(cat))
        else:
            x = plot.left() + (k + 0.5) / n * plot.width()
            p.drawText(QRectF(x - plot.width() / n / 2, plot.bottom() + 6, plot.width() / n, cat_h), int(Qt.AlignHCenter | Qt.AlignTop), str(cat))
    zero = (0 - lo) / (hi - lo)
    m = max(1, len(series))
    for j, s_ in enumerate(series):
        colr = QColor(accents[j % len(accents)])
        vals = [float(v) for v in s_.get("values", [])][:len(cats)]
        if kind == "line":
            pen = QPen(colr, 6)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            pts = [(plot.left() + (k + 0.5) / n * plot.width(), plot.bottom() - (v - lo) / (hi - lo) * plot.height()) for k, v in enumerate(vals)]
            for a, b in zip(pts, pts[1:]):
                p.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))
            p.setBrush(colr)
            for x, y in pts:
                p.drawEllipse(QRectF(x - 8, y - 8, 16, 16))
            continue
        p.setPen(Qt.NoPen)
        p.setBrush(colr)
        for k, v in enumerate(vals):
            frac = (v - lo) / (hi - lo)
            if kind == "bar":
                slot = plot.height() / n
                bh = slot * 0.7 / m
                y = plot.top() + k * slot + slot * 0.15 + j * bh
                x0, x1 = plot.left() + zero * plot.width(), plot.left() + frac * plot.width()
                p.drawRect(QRectF(min(x0, x1), y, abs(x1 - x0), bh))
            else:
                slot = plot.width() / n
                bw = slot * 0.7 / m
                x = plot.left() + k * slot + slot * 0.15 + j * bw
                y0, y1 = plot.bottom() - zero * plot.height(), plot.bottom() - frac * plot.height()
                p.drawRect(QRectF(x, min(y0, y1), bw, abs(y1 - y0)))


def _nice(raw: float) -> float:
    if raw <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(raw))
    for f in (1, 2, 2.5, 5, 10):
        if raw <= f * mag:
            return f * mag
    return 10 * mag


def render_item(item: dict, look: dict, scale: float = 0.5) -> QImage:
    """A table or a chart as a picture (for the window, which shows them as pictures until they're edited)."""
    img = QImage(max(1, int(item["w"] * scale)), max(1, int(item["h"] * scale)), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.scale(scale, scale)
    (paint_table if item["kind"] == "table" else paint_chart)(p, item, look)
    p.end()
    return img


def placeholder_item(role: str, iid: str, rect: tuple, layout: str) -> dict:
    st = role_style(role, layout)
    it = new_item("text", iid, *rect, role=role)
    it["paras"] = [{"runs": [], "lvl": 0, "list": st["list"], "align": ""}]
    return it


def text_of(item: dict) -> str:
    return "\n".join("".join(r.get("t", "") for r in p.get("runs", [])) for p in item.get("paras", []))


def has_text(item: dict) -> bool:
    return any(r.get("t") for p in item.get("paras", []) for r in p.get("runs", []))


def upgrade(data: dict, size: str = "16:9") -> dict:
    """A deck in the first format (title, body and notes per slide) as free items."""
    slides, n = [], 0
    for s in data.get("slides", []):
        if not isinstance(s, dict):
            continue
        layout = s.get("layout") if s.get("layout") in ("title", "content", "section", "blank") else "content"
        items = []
        for role, *rect in placeholders(layout, size):
            n += 1
            it = placeholder_item(role, f"i{n}", tuple(rect), layout)
            text = s.get("title", "") if role == "title" else s.get("body", "")
            st = role_style(role, layout)
            if text:
                it["paras"] = [{"runs": [{"t": line}] if line else [], "lvl": 0, "list": st["list"], "align": ""} for line in text.split("\n")]
            items.append(it)
        slides.append({"id": f"s{len(slides) + 1}", "layout": layout, "items": items, "notes": str(s.get("notes", "")), "bg": None,
                       "transition": {"kind": "none", "ms": 500}, "hidden": False})
    return {"format": "huginn-slides-2", "theme": data.get("theme") if data.get("theme") in THEMES else "realm", "look": None,
            "size": size, "slides": slides}


# ---------------------------------------------------------------------------------------------- shapes
SHAPES = ("rect", "rounded", "ellipse", "triangle", "rtriangle", "diamond", "pentagon", "hexagon", "star", "arrow", "larrow",
          "chevron", "callout", "heart", "plus", "line", "arrowline")
SHAPE_NAMES = {"rect": "Rectangle", "rounded": "Rounded rectangle", "ellipse": "Oval", "triangle": "Triangle", "rtriangle": "Right triangle",
               "diamond": "Diamond", "pentagon": "Pentagon", "hexagon": "Hexagon", "star": "Star", "arrow": "Arrow right", "larrow": "Arrow left",
               "chevron": "Chevron", "callout": "Speech bubble", "heart": "Heart", "plus": "Plus", "line": "Line", "arrowline": "Arrow"}
K = 0.5522847498            # a quarter circle as a cubic


def _ellipse(cx, cy, rx, ry) -> list:
    return [("M", cx + rx, cy), ("C", cx + rx, cy + ry * K, cx + rx * K, cy + ry, cx, cy + ry),
            ("C", cx - rx * K, cy + ry, cx - rx, cy + ry * K, cx - rx, cy), ("C", cx - rx, cy - ry * K, cx - rx * K, cy - ry, cx, cy - ry),
            ("C", cx + rx * K, cy - ry, cx + rx, cy - ry * K, cx + rx, cy), ("Z",)]


def _poly(points) -> list:
    return [("M", *points[0])] + [("L", *p) for p in points[1:]] + [("Z",)]


def shape_ops(kind: str, w: float, h: float, flip_h: bool = False, flip_v: bool = False) -> list:
    """A shape's outline in its own box, as M/L/C/Z steps (shared by the screen, the PDF and nothing else)."""
    w, h = max(w, 0.1), max(h, 0.1)
    ss = min(w, h)
    if kind == "rounded":
        r = ss * 0.1667
        ops = [("M", r, 0), ("L", w - r, 0), ("C", w - r + r * K, 0, w, r - r * K, w, r), ("L", w, h - r),
               ("C", w, h - r + r * K, w - r + r * K, h, w - r, h), ("L", r, h), ("C", r - r * K, h, 0, h - r + r * K, 0, h - r),
               ("L", 0, r), ("C", 0, r - r * K, r - r * K, 0, r, 0), ("Z",)]
    elif kind == "ellipse":
        ops = _ellipse(w / 2, h / 2, w / 2, h / 2)
    elif kind == "triangle":
        ops = _poly([(w / 2, 0), (w, h), (0, h)])
    elif kind == "rtriangle":
        ops = _poly([(0, 0), (w, h), (0, h)])
    elif kind == "diamond":
        ops = _poly([(w / 2, 0), (w, h / 2), (w / 2, h), (0, h / 2)])
    elif kind == "pentagon":
        ops = _poly([(w / 2 + w / 2 * math.sin(a), h * 0.5 - h * 0.5 * math.cos(a) * 1.05 + h * 0.025)
                     for a in (i * 2 * math.pi / 5 for i in range(5))])
    elif kind == "hexagon":
        q = ss * 0.25
        ops = _poly([(0, h / 2), (q, 0), (w - q, 0), (w, h / 2), (w - q, h), (q, h)])
    elif kind == "star":
        pts = []
        for i in range(10):
            a = i * math.pi / 5
            r = 1.0 if i % 2 == 0 else 0.382
            pts.append((w / 2 + w / 2 * r * math.sin(a), h * 0.53 - h * 0.53 * r * math.cos(a)))
        ops = _poly(pts)
    elif kind in ("arrow", "larrow"):
        head = min(w, ss * 0.5)
        pts = [(0, h * 0.25), (w - head, h * 0.25), (w - head, 0), (w, h / 2), (w - head, h), (w - head, h * 0.75), (0, h * 0.75)]
        if kind == "larrow":
            pts = [(w - x, y) for x, y in pts]
        ops = _poly(pts)
    elif kind == "chevron":
        d = min(w, ss * 0.5)
        ops = _poly([(0, 0), (w - d, 0), (w, h / 2), (w - d, h), (0, h), (d, h / 2)])
    elif kind == "callout":
        ops = _poly([(0, 0), (w, 0), (w, h), (w * 0.42, h), (w * 0.29, h * 1.125), (w * 0.25, h), (0, h)])
    elif kind == "heart":
        ops = [("M", w / 2, h * 0.25), ("C", w / 2, h * 0.08, w * 0.3, 0, w * 0.18, 0), ("C", w * 0.02, 0, 0, h * 0.18, 0, h * 0.3),
               ("C", 0, h * 0.55, w * 0.3, h * 0.75, w / 2, h), ("C", w * 0.7, h * 0.75, w, h * 0.55, w, h * 0.3),
               ("C", w, h * 0.18, w * 0.98, 0, w * 0.82, 0), ("C", w * 0.7, 0, w / 2, h * 0.08, w / 2, h * 0.25), ("Z",)]
    elif kind == "plus":
        a = ss * 0.25
        ops = _poly([(w / 2 - a, 0), (w / 2 + a, 0), (w / 2 + a, h / 2 - a), (w, h / 2 - a), (w, h / 2 + a), (w / 2 + a, h / 2 + a),
                     (w / 2 + a, h), (w / 2 - a, h), (w / 2 - a, h / 2 + a), (0, h / 2 + a), (0, h / 2 - a), (w / 2 - a, h / 2 - a)])
    elif kind in ("line", "arrowline"):
        ops = [("M", 0, 0), ("L", w, h)]
    else:
        ops = _poly([(0, 0), (w, 0), (w, h), (0, h)])
    if flip_h or flip_v:
        fx = (lambda x: w - x) if flip_h else (lambda x: x)
        fy = (lambda y: h - y) if flip_v else (lambda y: y)
        flipped = []
        for op in ops:
            if op[0] == "Z":
                flipped.append(op)
            else:
                vals = list(op[1:])
                flipped.append((op[0], *[fx(v) if i % 2 == 0 else fy(v) for i, v in enumerate(vals)]))
        ops = flipped
    return ops


def ops_svg(ops: list) -> str:
    return " ".join(op[0] + (" " + " ".join(f"{v:.2f}" for v in op[1:]) if len(op) > 1 else "") for op in ops)


def ops_path(ops: list) -> QPainterPath:
    path = QPainterPath()
    for op in ops:
        if op[0] == "M":
            path.moveTo(op[1], op[2])
        elif op[0] == "L":
            path.lineTo(op[1], op[2])
        elif op[0] == "C":
            path.cubicTo(*op[1:])
        else:
            path.closeSubpath()
    return path


def arrow_head(item: dict) -> list:
    """The triangle at a line's end (for the arrow): three points in the item's box."""
    w, h = item["w"], item["h"]
    x0, y0, x1, y1 = (w if item.get("flipH") else 0), (h if item.get("flipV") else 0), (0 if item.get("flipH") else w), (0 if item.get("flipV") else h)
    ang = math.atan2(y1 - y0, x1 - x0)
    size = max(14.0, float(item.get("lineW") or 3) * 4)
    left = (x1 - size * math.cos(ang - 0.45), y1 - size * math.sin(ang - 0.45))
    right = (x1 - size * math.cos(ang + 0.45), y1 - size * math.sin(ang + 0.45))
    return [(x1, y1), left, right]


# ---------------------------------------------------------------------------------------------- text
LIST_STYLES = {"bullet": (QTextListFormat.ListDisc, QTextListFormat.ListCircle, QTextListFormat.ListSquare),
               "number": (QTextListFormat.ListDecimal, QTextListFormat.ListLowerAlpha, QTextListFormat.ListLowerRoman)}
ALIGN = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight, "justify": Qt.AlignJustify}


def para_defaults(item: dict, para: dict, layout: str, look: dict) -> dict:
    st = role_style(item.get("role", ""), layout)
    if item.get("kind") == "shape":
        st = dict(st, align="center", color="#FFFFFF" if item.get("fill") else "text", size=20)
    size = para_size(st["size"], int(para.get("lvl", 0)), item.get("role", ""))
    font = look["head"] if st["font"] == "head" else look["body"]
    return {"size": size, "b": st["b"], "i": False, "u": False, "s": False, "color": colour(st["color"], look), "font": font,
            "align": st["align"]}


def char_format(run: dict, dflt: dict, hide: bool = False) -> QTextCharFormat:
    cf = QTextCharFormat()
    font = QFont(run.get("font") or dflt["font"])
    font.setPixelSize(max(1, round(float(run.get("size") or dflt["size"]) * PT)))
    font.setBold(bool(run.get("b", dflt["b"])))
    font.setItalic(bool(run.get("i", False)))
    font.setUnderline(bool(run.get("u", False)))
    font.setStrikeOut(bool(run.get("s", False)))
    cf.setFont(font)
    cf.setFontFamilies([run.get("font") or dflt["font"]])
    cf.setForeground(QColor(0, 0, 0, 0) if hide else QColor(run.get("color") or dflt["color"]))
    return cf


def build_doc(item: dict, layout: str, look: dict, doc: QTextDocument = None) -> QTextDocument:
    """The item's paragraphs as a Qt text document (its HTML is what the window shows and edits)."""
    doc = doc or QTextDocument()
    doc.clear()
    doc.setDocumentMargin(0)
    doc.setIndentWidth(INDENT)
    cursor = QTextCursor(doc)
    lists = {}
    paras = item.get("paras") or [{"runs": []}]
    role = item.get("role", "")
    for n, para in enumerate(paras):
        dflt = para_defaults(item, para, layout, look)
        lvl = max(0, min(8, int(para.get("lvl", 0))))
        bf = QTextBlockFormat()
        bf.setAlignment(ALIGN.get(para.get("align") or dflt["align"], Qt.AlignLeft))
        spacing = float(para.get("spacing", 0) or 0)
        bf.setLineHeight(100 * (spacing or (0.95 if role == "title" else 1.0)), 1)      # 1 = proportional
        if n and role in ("body", "body2") and para.get("list"):
            bf.setTopMargin(round(dflt["size"] * PT * 0.35))
        kind = para.get("list") or ""
        if not kind:
            bf.setIndent(lvl)
        hide = bool(para.get("_hide"))           # a paragraph not built yet while presenting: there, but unseen
        if n:
            cursor.insertBlock(bf, char_format({}, dflt, hide))
        else:
            cursor.setBlockFormat(bf)
            cursor.setBlockCharFormat(char_format({}, dflt, hide))
        for k in [k for k in lists if k > lvl or (k == lvl and not kind)]:
            del lists[k]
        if kind in LIST_STYLES:
            if lvl in lists and lists[lvl][0] == kind:
                lists[lvl][1].add(cursor.block())
            else:
                lf = QTextListFormat()
                lf.setStyle(LIST_STYLES[kind][lvl % 3])
                lf.setIndent(lvl + 1)
                lists[lvl] = (kind, cursor.createList(lf))
        for run in para.get("runs", []):
            if run.get("t"):
                cursor.insertText(run["t"].replace("\n", "\u2028"), char_format(run, dflt, hide))
    return doc


def item_html(item: dict, layout: str, look: dict) -> str:
    return build_doc(item, layout, look).toHtml()


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a or 0) - float(b or 0)) < 0.26
    return a == b


def read_doc(doc: QTextDocument, item: dict, layout: str, look: dict) -> list:
    """The paragraphs back out of an edited document, keeping only what differs from the defaults."""
    paras = []
    block = doc.begin()
    role = item.get("role", "")
    while block.isValid():
        lst = block.textList()
        bf = block.blockFormat()
        if lst is not None:
            style = lst.format().style()
            kind = "number" if style in LIST_STYLES["number"] else "bullet"
            lvl = max(0, lst.format().indent() - 1)
        else:
            kind, lvl = "", max(0, bf.indent())
        para = {"runs": [], "lvl": lvl, "list": kind, "align": ""}
        dflt = para_defaults(item, para, layout, look)
        al = bf.alignment() & Qt.AlignHorizontal_Mask
        name = {Qt.AlignHCenter: "center", Qt.AlignRight: "right", Qt.AlignJustify: "justify"}.get(al, "left")
        if name != dflt["align"]:
            para["align"] = name
        lh = bf.lineHeight() / 100 if bf.lineHeightType() == 1 else 0
        if lh and abs(lh - (0.95 if role == "title" else 1.0)) > 0.01:
            para["spacing"] = round(lh, 2)
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.text():
                cf = frag.charFormat()
                font = cf.font()
                px = font.pixelSize() if font.pixelSize() > 0 else (font.pointSizeF() * 96 / 72 if font.pointSizeF() > 0 else dflt["size"] * PT)
                fams = cf.fontFamilies() if isinstance(cf.fontFamilies(), list) else []
                run = {"t": frag.text().replace("\u2028", "\n"), "b": font.bold(), "i": font.italic(), "u": font.underline(),
                       "s": font.strikeOut(), "size": round(px / PT * 2) / 2, "font": (fams[0] if fams else font.family()),
                       "color": cf.foreground().color().name().upper() if cf.foreground().style() != Qt.NoBrush else ""}
                for key in ("b", "i", "u", "s", "size", "font", "color"):
                    if key == "color" and (not run["color"] or run["color"].upper() == dflt["color"].upper()):
                        run.pop("color")
                    elif key != "color" and _same(run[key], dflt[key]):
                        run.pop(key)
                last = para["runs"][-1] if para["runs"] else None
                if last is not None and {k: v for k, v in last.items() if k != "t"} == {k: v for k, v in run.items() if k != "t"}:
                    last["t"] += run["t"]
                else:
                    para["runs"].append(run)
            it += 1
        paras.append(para)
        block = block.next()
    return paras or [{"runs": [], "lvl": 0, "list": "", "align": ""}]


def text_height(item: dict, layout: str, look: dict, width: float) -> float:
    doc = build_doc(item, layout, look)
    doc.setTextWidth(max(10.0, width))
    return doc.size().height()


def fit_scale(item: dict, layout: str, look: dict) -> float:
    """Placeholders shrink their text to fit, as PowerPoint's 'shrink text on overflow' does."""
    inner_w, inner_h = item["w"] - 2 * INSET_X, item["h"] - 2 * INSET_Y
    if not has_text(item) or text_height(item, layout, look, inner_w) <= inner_h + 1:
        return 1.0
    s = 1.0
    while s > 0.4:
        s = round(s - 0.05, 2)
        if text_height(item, layout, look, inner_w / s) * s <= inner_h + 1:
            return s
    return 0.4


# ---------------------------------------------------------------------------------------------- drawing (PDF)
def image_of(src: str) -> QImage:
    img = QImage()
    if src.startswith("data:") and "," in src:
        import base64
        img.loadFromData(base64.b64decode(src.split(",", 1)[1]))
    return img


def paint_background(p: QPainter, bg: dict, w: float, h: float) -> None:
    if bg.get("picture"):
        img = image_of(bg["picture"])
        if not img.isNull():
            scale = max(w / img.width(), h / img.height())
            sw, sh = img.width() * scale, img.height() * scale
            p.drawImage(QRectF((w - sw) / 2, (h - sh) / 2, sw, sh), img)
            return
    if bg.get("from"):
        horizontal = int(bg.get("angle", 0)) % 180 == 0
        grad = QLinearGradient(0, 0, w if horizontal else 0, 0 if horizontal else h)
        grad.setColorAt(0, QColor(bg["from"]))
        grad.setColorAt(1, QColor(bg.get("to") or bg["from"]))
        p.fillRect(QRectF(0, 0, w, h), QBrush(grad))
    else:
        p.fillRect(QRectF(0, 0, w, h), QColor(bg.get("color") or "#FFFFFF"))


def paint_slide(p: QPainter, deck: dict, slide: dict) -> None:
    """One slide in slide units (the painter already scaled): the same drawing as the window's."""
    look = look_of(deck)
    w, h = slide_w(deck.get("size", "16:9")), SLIDE_H
    paint_background(p, slide.get("bg") or look["bg"], w, h)
    deco = look.get("deco", "")
    if deco == "orb":
        c = QColor(look["accents"][0])
        c.setAlphaF(0.10)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        d = w * 0.5
        p.drawEllipse(QRectF(w * 0.68, -h * 0.45, d, d))
    layout = slide.get("layout", "content")
    frame = (look.get("frames") or {}).get(slide.get("frame") or "") if deck.get("look") else None
    for item in (frame or {}).get("items", []):
        paint_item(p, item, layout, look)
    for item in slide.get("items", []):
        paint_item(p, item, layout, look)
        if deco and item.get("role") == "title" and layout in ("content", "two", "titleonly"):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(look["accents"][0]))
            p.drawRoundedRect(QRectF(item["x"] + INSET_X, item["y"] + item["h"] + 4, 112, 8), 4, 4)


def paint_item(p: QPainter, item: dict, layout: str, look: dict) -> None:
    p.save()
    p.translate(item["x"] + item["w"] / 2, item["y"] + item["h"] / 2)
    p.rotate(float(item.get("rot", 0) or 0))
    p.translate(-item["w"] / 2, -item["h"] / 2)
    w, h = item["w"], item["h"]
    if item["kind"] == "picture":
        img = image_of(item.get("src", ""))
        if not img.isNull():
            p.drawImage(QRectF(0, 0, w, h), img)
    elif item["kind"] == "table":
        paint_table(p, item, look)
    elif item["kind"] == "chart":
        paint_chart(p, item, look)
    elif item["kind"] == "shape":
        kind = item.get("shape", "rect")
        path = ops_path(shape_ops(kind, w, h, item.get("flipH"), item.get("flipV")))
        line = colour(item.get("line", ""), look)
        if kind in ("line", "arrowline"):
            pen = QPen(QColor(line or colour(item.get("fill") or "accent1", look)), float(item.get("lineW") or 3))
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            if kind == "arrowline":
                head = QPainterPath()
                pts = arrow_head(item)
                head.moveTo(*pts[0])
                head.lineTo(*pts[1])
                head.lineTo(*pts[2])
                head.closeSubpath()
                p.fillPath(head, pen.color())
        else:
            fill = colour(item.get("fill", ""), look)
            p.setBrush(QColor(fill) if fill else Qt.NoBrush)
            p.setPen(QPen(QColor(line), float(item.get("lineW") or 2)) if line and item.get("lineW") else Qt.NoPen)
            p.drawPath(path)
    if item["kind"] in ("text", "shape") and has_text(item) and item.get("shape") not in ("line", "arrowline"):
        fit = float(item.get("fit", 1.0) or 1.0)
        doc = build_doc(item, layout, look)
        inner_w = w - 2 * INSET_X
        doc.setTextWidth(inner_w / fit)
        th = doc.size().height() * fit
        valign = item.get("valign") or role_style(item.get("role", ""), layout)["valign"]
        y = INSET_Y if valign == "top" else (h - th) / 2 if valign == "middle" else h - INSET_Y - th
        p.translate(INSET_X, y)
        p.scale(fit, fit)
        doc.drawContents(p)
    p.restore()


def write_pdf(deck: dict, path: str, title: str = "") -> None:
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageSize, QPdfWriter
    w = slide_w(deck.get("size", "16:9"))
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QSizeF(w / PT, SLIDE_H / PT), QPageSize.Point))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    writer.setResolution(144)
    writer.setTitle(title)
    painter = QPainter(writer)
    painter.setRenderHint(QPainter.Antialiasing)
    scale = painter.viewport().width() / w
    first = True
    for slide in deck["slides"]:
        if slide.get("hidden"):
            continue
        if not first:
            writer.newPage()
        first = False
        painter.save()
        painter.setTransform(QTransform.fromScale(scale, scale))
        paint_slide(painter, deck, slide)
        painter.restore()
    painter.end()


def render_png(deck: dict, slide: dict, path: str, width: int = 1280) -> None:
    w = slide_w(deck.get("size", "16:9"))
    img = QImage(width, round(width * SLIDE_H / w), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.white)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(width / w, width / w)
    paint_slide(painter, deck, slide)
    painter.end()
    img.save(path)


def clone(obj):
    return copy.deepcopy(obj)


def bounds(items: list) -> QRectF:
    r = QRectF()
    for it in items:
        r = r.united(QRectF(it["x"], it["y"], it["w"], it["h"]))
    return r
