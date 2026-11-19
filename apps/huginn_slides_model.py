"""Slides' model: a deck of slides, each a free canvas of items (text, shapes, pictures) on a 1080-unit-high slide.

The deck is plain JSON ("huginn-slides-2"):
    {"format", "theme", "look" (a design read from a PowerPoint file, until another theme is picked), "size": "16:9"|"4:3",
     "slides": [{"id", "layout", "items": [...], "notes", "bg", "transition": {"kind", "ms"}, "hidden"}]}
An item: {"id", "kind": "text"|"shape"|"picture", "role": ""|"title"|"subtitle"|"body"|"body2", "x", "y", "w", "h", "rot",
          "shape", "fill", "line", "lineW", "flipH", "flipV", "arrow", "paras", "valign", "fit", "src", "anim", "locked"}
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
