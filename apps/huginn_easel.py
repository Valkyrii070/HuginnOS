"""Huginn Easel: paint, retouch and draw. Pixel layers and vector layers live in one document.

The document
    A stack of layers, bottom first. Pixel layers hold a picture as big as the canvas; vector layers hold shapes
    (rectangles, ellipses, lines, stars, paths drawn with the pen, and text) that stay sharp at any size; adjustment
    layers change the look of everything below them without touching it. Any pixel or vector layer can have a mask
    (white shows, black hides), a blend mode and an opacity.

Files
    .easel        Easel's own: a zip with manifest.json, one PNG per pixel layer and mask, and a preview.
    .ora          OpenRaster, which Krita, GIMP and MyPaint read and write: layers, blend modes and opacity cross over.
    PNG, JPEG, WebP, TIFF, BMP open as one pixel layer; SVG opens as a picture (drawn sharp at the canvas size).
    Export        PNG, JPEG, WebP; SVG and PDF keep vector layers as vectors (pixel layers go in as pictures).

Qt's QPainter does the compositing (blend modes, masks, antialiased shapes); numpy and Pillow do the filters.
"""
import json
import math
import os
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRect, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QLinearGradient, QPageSize, QPainter, QPainterPath, QPainterPathStroker,
                           QPdfWriter, QPen, QPolygonF, QRadialGradient, QRegion, QBitmap, QTransform)

try:
    import cv2
except Exception:                                                # noqa: BLE001  (Easel works without it, more slowly)
    cv2 = None

FMT = QImage.Format.Format_ARGB32_Premultiplied
CM = QPainter.CompositionMode
BLENDS = {"normal": CM.CompositionMode_SourceOver, "multiply": CM.CompositionMode_Multiply, "screen": CM.CompositionMode_Screen,
          "overlay": CM.CompositionMode_Overlay, "darken": CM.CompositionMode_Darken, "lighten": CM.CompositionMode_Lighten,
          "dodge": CM.CompositionMode_ColorDodge, "burn": CM.CompositionMode_ColorBurn, "hard": CM.CompositionMode_HardLight,
          "soft": CM.CompositionMode_SoftLight, "difference": CM.CompositionMode_Difference, "exclusion": CM.CompositionMode_Exclusion,
          "add": CM.CompositionMode_Plus,
          # the four that take hue, saturation or lightness from one layer and the rest from the other: Qt has none of
          # them, so they're worked out here (HSL_BLENDS); anything that only knows Qt's modes draws them as Normal
          "hue": CM.CompositionMode_SourceOver, "saturation": CM.CompositionMode_SourceOver, "color": CM.CompositionMode_SourceOver,
          "luminosity": CM.CompositionMode_SourceOver}
HSL_BLENDS = ("hue", "saturation", "color", "luminosity")
BLEND_NAMES = [("normal", "Normal"), ("multiply", "Multiply"), ("screen", "Screen"), ("overlay", "Overlay"), ("darken", "Darken"),
               ("lighten", "Lighten"), ("dodge", "Colour Dodge"), ("burn", "Colour Burn"), ("hard", "Hard Light"), ("soft", "Soft Light"),
               ("difference", "Difference"), ("exclusion", "Exclusion"), ("add", "Add"),
               ("hue", "Hue"), ("saturation", "Saturation"), ("color", "Colour"), ("luminosity", "Luminosity")]
ORA_OPS = {"normal": "svg:src-over", "multiply": "svg:multiply", "screen": "svg:screen", "overlay": "svg:overlay", "darken": "svg:darken",
           "lighten": "svg:lighten", "dodge": "svg:color-dodge", "burn": "svg:color-burn", "hard": "svg:hard-light", "soft": "svg:soft-light",
           "difference": "svg:difference", "exclusion": "svg:exclusion", "add": "svg:plus",
           "hue": "svg:hue", "saturation": "svg:saturation", "color": "svg:color", "luminosity": "svg:luminosity"}
ADJUSTMENTS = {"light": "Brightness & Contrast", "curves": "Curves", "colour": "Hue & Saturation", "levels": "Levels", "bw": "Black & White",
               "invert": "Invert", "warmth": "Warmth", "posterize": "Posterize", "vibrance": "Vibrance", "gradmap": "Gradient Map",
               "exposure": "Exposure", "balance": "Colour Balance", "threshold": "Threshold", "mixer": "Channel Mixer"}
PICTURES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif")


SIDE_LIMIT = 16384            # the longest side a picture may have (as New Picture allows)
LOAD_LIMIT = 3 << 30          # bytes of pixels a file may ask for when it opens (every layer at the picture's size)
KINDS = ("pixel", "vector", "adjust", "group", "smart")


_VERSIONS = iter(range(1, 1 << 62))
CHECK_MIPS = bool(os.environ.get("EASEL_CHECK_MIPS"))        # (for the tests: every kept smaller copy is checked against a fresh one)


def next_v() -> int:
    """A layer's version: a number no layer has had before. Two layers with the same id and version hold the same
    picture, which is what lets a kept copy (a thumbnail, a style's shadow, a smaller copy for the canvas) be trusted,
    through any amount of Undo and Redo. (It used to be the old number plus one, so undoing and then painting
    something else arrived at a number already used for a different picture.)"""
    return next(_VERSIONS)


def checked_size(w, h, layers: int = 1) -> tuple:
    """A picture's size as a file gives it, made sure of before anything is set aside for it: whole numbers, at least
    one pixel, within Easel's limit, and not more layers of that size than a computer has room for."""
    try:
        w, h = int(w), int(h)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("This file doesn't say how big its picture is.") from None
    if w < 1 or h < 1:
        raise ValueError("This file's picture has no size.")
    if w > SIDE_LIMIT or h > SIDE_LIMIT:
        raise ValueError(f"This picture is {w:,} × {h:,} pixels. Easel works with up to {SIDE_LIMIT:,} a side.")
    if w * h * 4 * max(1, int(layers)) > LOAD_LIMIT:
        raise ValueError(f"This picture is {w:,} × {h:,} pixels with {layers} layers: more than Easel can open at once.")
    return w, h


def _number(v, lo: float, hi: float, default: float) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v)) if math.isfinite(v) and not isinstance(v, bool) or isinstance(v, bool) else default


def new_image(w: int, h: int, fill=None) -> QImage:
    img = QImage(max(1, int(w)), max(1, int(h)), FMT)
    img.fill(QColor(fill) if fill else Qt.GlobalColor.transparent)
    return img


def colour(text: str, fallback: str = "#000000") -> QColor:
    c = QColor(text or fallback)
    return c if c.isValid() else QColor(fallback)


def image_to_array(img: QImage) -> np.ndarray:
    """A QImage as an h×w×4 uint8 array in RGBA order (straight alpha)."""
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = img.constBits()
    arr = np.frombuffer(ptr, np.uint8, img.sizeInBytes()).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4]
    return arr.reshape(img.height(), img.width(), 4).copy()


def array_to_image(arr: np.ndarray) -> QImage:
    arr = np.ascontiguousarray(arr.astype(np.uint8))
    h, w = arr.shape[:2]
    img = QImage(arr.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
    return img.convertToFormat(FMT)


def alpha_of(img: QImage) -> np.ndarray:
    return image_to_array(img)[..., 3]


def alpha_image(a: np.ndarray) -> QImage:
    """An image that is white, with this alpha (masks and selections are kept like this)."""
    h, w = a.shape
    rgba = np.empty((h, w, 4), np.uint8)
    rgba[..., :3] = 255
    rgba[..., 3] = a
    return array_to_image(rgba)


def png_bytes(img: QImage, quick: bool = False) -> bytes:
    """`quick`: packed a little less tightly and many times faster (a 12-megapixel photo: under a second instead of
    eight, for a file a sixth bigger). For the layers inside Easel's own files, which are saved again and again."""
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG", 70 if quick else -1)
    buf.close()
    return bytes(data)


def image_from_bytes(raw: bytes) -> QImage:
    img = QImage()
    img.loadFromData(raw)
    return img.convertToFormat(FMT) if not img.isNull() else img


# ------------------------------------------------------------------------------------------- vector shapes
def _node_path(subs: list) -> QPainterPath:
    path = QPainterPath()
    for sub in subs:
        nodes = sub.get("nodes") or []
        if not nodes:
            continue
        path.moveTo(nodes[0]["x"], nodes[0]["y"])
        pairs = list(zip(nodes, nodes[1:])) + ([(nodes[-1], nodes[0])] if sub.get("closed") and len(nodes) > 1 else [])
        for a, b in pairs:
            ax, ay = a.get("ox", a["x"]), a.get("oy", a["y"])
            bx, by = b.get("ix", b["x"]), b.get("iy", b["y"])
            if (ax, ay) == (a["x"], a["y"]) and (bx, by) == (b["x"], b["y"]):
                path.lineTo(b["x"], b["y"])
            else:
                path.cubicTo(ax, ay, bx, by, b["x"], b["y"])
        if sub.get("closed"):
            path.closeSubpath()
    return path


def text_font(s: dict) -> QFont:
    f = QFont(s.get("font") or "Inter")
    f.setPixelSize(max(1, int(s.get("size", 48))))
    f.setWeight(QFont.Weight(int(s.get("weight", 400))))
    f.setItalic(bool(s.get("italic")))
    track = _number(s.get("tracking"), -50.0, 300.0, 0.0)             # letters set tighter (below 0) or wider, in percent of their width
    if track:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100.0 + track)
    return f


def raw_path(s: dict) -> QPainterPath:
    """A shape's outline before its turn."""
    t = s.get("type")
    path = QPainterPath()
    if t == "rect":
        r = max(0.0, min(float(s.get("radius", 0)), abs(s["w"]) / 2, abs(s["h"]) / 2))
        path.addRoundedRect(QRectF(s["x"], s["y"], s["w"], s["h"]).normalized(), r, r)
    elif t == "ellipse":
        path.addEllipse(QRectF(s["x"], s["y"], s["w"], s["h"]).normalized())
    elif t == "line":
        path.moveTo(s["x1"], s["y1"])
        path.lineTo(s["x2"], s["y2"])
    elif t == "star":
        rect = QRectF(s["x"], s["y"], s["w"], s["h"]).normalized()
        n, inner = max(3, int(s.get("points", 5))), float(s.get("inner", 0.5))
        cx, cy, rx, ry = rect.center().x(), rect.center().y(), rect.width() / 2, rect.height() / 2
        poly = QPolygonF()
        steps = n * 2 if inner < 0.999 else n
        for i in range(steps):
            k = 1.0 if (i % 2 == 0 or inner >= 0.999) else inner
            a = -math.pi / 2 + i * (2 * math.pi / steps)
            poly.append(QPointF(cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
        path.addPolygon(poly)
        path.closeSubpath()
    elif t == "path":
        path = _node_path(s.get("subs") or [])
    elif t == "text" and s.get("along"):
        return text_along(s, text_font(s), s["along"])
    elif t == "text":
        f = text_font(s)
        from PySide6.QtGui import QFontMetricsF
        fm = QFontMetricsF(f)
        lines = (s.get("text") or "").split("\n")
        widths = [fm.horizontalAdvance(line) for line in lines]
        box = max(widths or [0])
        for i, line in enumerate(lines):
            dx = {"center": (box - widths[i]) / 2, "right": box - widths[i]}.get(s.get("align", "left"), 0)
            path.addText(s["x"] + dx, s["y"] + fm.ascent() + i * fm.lineSpacing() * _number(s.get("leading"), 0.4, 5.0, 1.0), f, line)
    return path


def shape_path(s: dict) -> QPainterPath:
    path = raw_path(s)
    rot = float(s.get("rot", 0))
    if rot:
        c = path.boundingRect().center()
        path = QTransform().translate(c.x(), c.y()).rotate(rot).translate(-c.x(), -c.y()).map(path)
    return path


def paint_shape(p: QPainter, s: dict) -> None:
    path = shape_path(s)
    p.save()
    p.setOpacity(p.opacity() * float(s.get("opacity", 1)))
    fill = s.get("fill", "")
    if fill and s.get("type") != "line":
        if s.get("fill2"):                                           # a gradient across the shape
            box = path.boundingRect()
            c = box.center()
            if s.get("gkind") == "radial":
                g = QRadialGradient(c, max(box.width(), box.height()) / 2)
            else:
                a = math.radians(float(s.get("gangle", 90)))
                r = (abs(box.width() * math.cos(a)) + abs(box.height() * math.sin(a))) / 2
                g = QLinearGradient(QPointF(c.x() - math.cos(a) * r, c.y() - math.sin(a) * r), QPointF(c.x() + math.cos(a) * r, c.y() + math.sin(a) * r))
            g.setColorAt(0, colour(fill))
            g.setColorAt(1, colour(s["fill2"]))
            p.fillPath(path, QBrush(g))
        else:
            p.fillPath(path, colour(fill))
    width = float(s.get("width", 0))
    if s.get("stroke") and width > 0:
        pen = QPen(colour(s["stroke"]), width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if s.get("dash"):
            pen.setDashPattern([3.0, 2.0])
        p.strokePath(path, pen)
    p.restore()


def shape_bounds(s: dict) -> QRectF:
    path = shape_path(s)
    box = path.boundingRect()
    w = float(s.get("width", 0)) if s.get("stroke") else 0
    return box.adjusted(-w / 2, -w / 2, w / 2, w / 2)


def hits(s: dict, pt: QPointF, slack: float = 4.0) -> bool:
    path = shape_path(s)
    if s.get("type") != "line" and s.get("fill") and path.contains(pt):
        return True
    stroker = QPainterPathStroker()
    stroker.setWidth(max(float(s.get("width", 0)), 1.0) + slack * 2)
    return stroker.createStroke(path).contains(pt) or (s.get("type") == "text" and path.boundingRect().contains(pt))


def path_to_subs(path: QPainterPath) -> list:
    """A QPainterPath (from combining shapes) as Easel's nodes: one list per subpath, with curve handles."""
    subs, nodes, i, n = [], [], 0, path.elementCount()
    while i < n:
        e = path.elementAt(i)
        if e.type == QPainterPath.ElementType.MoveToElement:
            if nodes:
                subs.append({"nodes": nodes, "closed": True})
            nodes = [{"x": e.x, "y": e.y}]
            i += 1
        elif e.type == QPainterPath.ElementType.LineToElement:
            nodes.append({"x": e.x, "y": e.y})
            i += 1
        elif e.type == QPainterPath.ElementType.CurveToElement and i + 2 < n:
            c1, c2, end = e, path.elementAt(i + 1), path.elementAt(i + 2)
            nodes[-1]["ox"], nodes[-1]["oy"] = c1.x, c1.y
            nodes.append({"x": end.x, "y": end.y, "ix": c2.x, "iy": c2.y})
            i += 3
        else:
            i += 1
    if nodes:
        subs.append({"nodes": nodes, "closed": True})
    for sub in subs:                                                 # a closed subpath repeats its first point last
        ns = sub["nodes"]
        if len(ns) > 2 and abs(ns[-1]["x"] - ns[0]["x"]) < 1e-6 and abs(ns[-1]["y"] - ns[0]["y"]) < 1e-6:
            last = ns.pop()
            if "ix" in last:
                ns[0]["ix"], ns[0]["iy"] = last["ix"], last["iy"]
    return subs


def move_shape(s: dict, dx: float, dy: float) -> None:
    t = s["type"]
    if t == "line":
        s["x1"] += dx
        s["y1"] += dy
        s["x2"] += dx
        s["y2"] += dy
    elif t == "path":
        for sub in s.get("subs", []):
            for nd in sub["nodes"]:
                for kx, ky in (("x", "y"), ("ix", "iy"), ("ox", "oy")):
                    if kx in nd:
                        nd[kx] += dx
                        nd[ky] += dy
    else:
        s["x"] += dx
        s["y"] += dy


def scale_shape(s: dict, box: QRectF, new: QRectF) -> None:
    """Fit a shape from one box into another (resizing with the handles)."""
    sx = new.width() / box.width() if box.width() else 1
    sy = new.height() / box.height() if box.height() else 1

    def mx(x):
        return new.x() + (x - box.x()) * sx

    def my(y):
        return new.y() + (y - box.y()) * sy
    t = s["type"]
    if t == "line":
        s["x1"], s["y1"], s["x2"], s["y2"] = mx(s["x1"]), my(s["y1"]), mx(s["x2"]), my(s["y2"])
    elif t == "path":
        for sub in s.get("subs", []):
            for nd in sub["nodes"]:
                for kx, ky in (("x", "y"), ("ix", "iy"), ("ox", "oy")):
                    if kx in nd:
                        nd[kx], nd[ky] = mx(nd[kx]), my(nd[ky])
    elif t == "text":
        s["x"], s["y"] = mx(s["x"]), my(s["y"])
        if s.get("along"):
            s["along"] = [[mx(x), my(y)] for x, y in s["along"]]
        s["size"] = max(4, float(s.get("size", 48)) * (sy if abs(sy - 1) > abs(sx - 1) else sx))
    else:
        x2, y2 = mx(s["x"] + s["w"]), my(s["y"] + s["h"])
        s["x"], s["y"] = mx(s["x"]), my(s["y"])
        s["w"], s["h"] = x2 - s["x"], y2 - s["y"]



# ------------------------------------------------------------------------------------------- filling a hole from its surroundings
def _box_sum(a: np.ndarray, r: int) -> np.ndarray:
    pad = np.pad(a.astype(np.float32), r + 1)
    c = pad.cumsum(0).cumsum(1)
    k = 2 * r + 1
    h, w = a.shape
    return (c[k:k + h, k:k + w] - c[:h, k:k + w] - c[k:k + h, :w] + c[:h, :w])


def _patch_offsets(r: int):
    dy, dx = np.mgrid[-r:r + 1, -r:r + 1]
    return dy.ravel(), dx.ravel()


def _ssd(img: np.ndarray, ty, tx, sy, sx, r: int) -> np.ndarray:
    h, w = img.shape[:2]
    dy, dx = _patch_offsets(r)
    a = img[np.clip(ty[:, None] + dy, 0, h - 1), np.clip(tx[:, None] + dx, 0, w - 1)]
    b = img[np.clip(sy[:, None] + dy, 0, h - 1), np.clip(sx[:, None] + dx, 0, w - 1)]
    d = a - b
    return (d * d).sum(axis=(1, 2))


def _diffuse(img: np.ndarray, hole: np.ndarray, rounds: int = 60) -> np.ndarray:
    """A first guess for the hole: its edges spread inwards."""
    out = img.copy()
    known = (~hole).astype(np.float32)
    for _ in range(rounds):
        s = np.stack([_box_sum(out[..., c] * known, 1) for c in range(3)], -1)
        n = _box_sum(known, 1)[..., None]
        fill = s / np.maximum(n, 1e-6)
        out[hole] = np.where(n[hole] > 0, fill[hole], out[hole])
        known = np.maximum(known, (n[..., 0] > 0).astype(np.float32))
    return out


def content_fill(rgb: np.ndarray, hole: np.ndarray, patch: int = 7, seed: int = 1) -> np.ndarray:
    """Fill the hole (True where to fill) with what's around it, texture and all: PatchMatch (Barnes et al.) inside
    an expectation-maximisation loop, coarse to fine over an image pyramid. Works on the hole's surroundings only."""
    hole = hole.astype(bool)
    if not hole.any():
        return rgb
    H, W = hole.shape
    ys, xs = np.nonzero(hole)
    m = max(int(np.ptp(ys)) + 1, int(np.ptp(xs)) + 1)
    margin = int(max(32, m * 1.6))
    Y0, Y1, X0, X1 = max(0, ys.min() - margin), min(H, ys.max() + margin + 1), max(0, xs.min() - margin), min(W, xs.max() + margin + 1)
    img0 = rgb[Y0:Y1, X0:X1, :3].astype(np.float32)
    hole0 = hole[Y0:Y1, X0:X1]
    r = patch // 2
    rng = np.random.default_rng(seed)
    # the pyramid
    levels = [(img0, hole0)]
    while min(levels[-1][0].shape[:2]) > 64 and levels[-1][1].sum() > 64:
        im, ho = levels[-1]
        h2, w2 = im.shape[0] // 2, im.shape[1] // 2
        im2 = im[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2, 3).mean(axis=(1, 3))
        ho2 = ho[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2).any(axis=(1, 3))
        levels.append((im2, ho2))
    levels.reverse()
    est, nnf = None, None
    for li, (im, ho) in enumerate(levels):
        h, w = ho.shape
        img = im.copy()
        if est is None:
            img = _diffuse(img, ho)
        else:                                                 # the coarser answer, made larger, as the start here
            up = np.repeat(np.repeat(est, 2, axis=0), 2, axis=1)
            up = np.pad(up, ((0, max(0, h - up.shape[0])), (0, max(0, w - up.shape[1])), (0, 0)), mode="edge")[:h, :w]
            img[ho] = up[ho]
        # sources: where a whole patch lies in known picture
        valid = (_box_sum(ho.astype(np.float32), r) == 0)
        valid[:r, :] = valid[-r:, :] = False
        valid[:, :r] = valid[:, -r:] = False
        vy, vx = np.nonzero(valid)
        if len(vy) == 0:
            return rgb
        ty, tx = np.nonzero(ho)
        n = len(ty)
        if nnf is None:
            k = rng.integers(0, len(vy), n)
            sy, sx = vy[k], vx[k]
        else:
            py, px = nnf
            sy = np.clip(py[np.minimum(ty // 2, py.shape[0] - 1), np.minimum(tx // 2, py.shape[1] - 1)] * 2 + ty % 2, 0, h - 1)
            sx = np.clip(px[np.minimum(ty // 2, px.shape[0] - 1), np.minimum(tx // 2, px.shape[1] - 1)] * 2 + tx % 2, 0, w - 1)
            bad = ~valid[sy, sx]
            k = rng.integers(0, len(vy), int(bad.sum()))
            sy[bad], sx[bad] = vy[k], vx[k]
        rounds = 3 if li < len(levels) - 1 else 2
        for _em in range(rounds):
            best = _ssd(img, ty, tx, sy, sx, r)
            mapy = np.full((h, w), -1, np.int64)
            mapx = np.full((h, w), -1, np.int64)
            for it in range(4):
                mapy[ty, tx], mapx[ty, tx] = sy, sx
                step = 1 if it % 2 == 0 else -1
                for oy, ox in ((0, step), (step, 0)):          # propagation: a neighbour's match, moved along
                    ny, nx = np.clip(ty - oy, 0, h - 1), np.clip(tx - ox, 0, w - 1)
                    cy, cx = mapy[ny, nx], mapx[ny, nx]
                    ok = cy >= 0
                    cy, cx = np.clip(cy + oy, 0, h - 1), np.clip(cx + ox, 0, w - 1)
                    ok &= valid[cy, cx]
                    if ok.any():
                        d = np.full(n, np.inf, np.float32)
                        d[ok] = _ssd(img, ty[ok], tx[ok], cy[ok], cx[ok], r)
                        better = d < best
                        sy[better], sx[better], best[better] = cy[better], cx[better], d[better]
                radius = max(h, w)
                while radius >= 1:                             # random search, nearer and nearer
                    cy = np.clip(sy + rng.integers(-radius, radius + 1, n), 0, h - 1)
                    cx = np.clip(sx + rng.integers(-radius, radius + 1, n), 0, w - 1)
                    ok = valid[cy, cx]
                    if ok.any():
                        d = np.full(n, np.inf, np.float32)
                        d[ok] = _ssd(img, ty[ok], tx[ok], cy[ok], cx[ok], r)
                        better = d < best
                        sy[better], sx[better], best[better] = cy[better], cx[better], d[better]
                    radius //= 2
            # voting: each hole pixel takes the average of what the patches over it say
            acc = np.zeros((h, w, 3), np.float32)
            cnt = np.zeros((h, w), np.float32)
            plain = np.zeros((h, w, 3), np.float32)
            many = np.zeros((h, w), np.float32)
            # good matches count for more; the scale has a floor, or a smooth picture (where most matches are
            # perfect) would give every imperfect one no say at all and leave pixels with nothing
            sigma = max(float(np.median(best)), 2.0 * (2 * r + 1) ** 2 * 3)
            wgt = np.exp(-np.minimum(best, 1e12) / (2 * sigma)).astype(np.float32)
            dy, dx = _patch_offsets(r)
            for oy, ox in zip(dy, dx):
                py, px = ty + oy, tx + ox
                ok = (py >= 0) & (py < h) & (px >= 0) & (px < w)
                py, px = py[ok], px[ok]
                qy, qx = np.clip(sy[ok] + oy, 0, h - 1), np.clip(sx[ok] + ox, 0, w - 1)
                vals = img[qy, qx]
                np.add.at(acc, (py, px), vals * wgt[ok][:, None])
                np.add.at(cnt, (py, px), wgt[ok])
                np.add.at(plain, (py, px), vals)
                np.add.at(many, (py, px), 1.0)
            filled = np.where((cnt > 1e-4)[..., None], acc / np.maximum(cnt, 1e-6)[..., None], plain / np.maximum(many, 1.0)[..., None])
            img[ho] = np.nan_to_num(filled[ho], nan=0.0)
        est = img
        py = np.zeros((h, w), np.int64)
        px = np.zeros((h, w), np.int64)
        py[ty, tx], px[ty, tx] = sy, sx
        nnf = (py, px)
    out = rgb.copy()
    region = out[Y0:Y1, X0:X1]
    region[..., :3][hole0] = np.clip(est[hole0], 0, 255).astype(rgb.dtype)
    out[Y0:Y1, X0:X1] = region
    return out


# ------------------------------------------------------------------------------------------- type along a path
def text_along(s: dict, f, points: list) -> QPainterPath:
    """Type that follows a line: each letter sits on the line at its place, turned to the line's direction."""
    from PySide6.QtGui import QFontMetricsF
    out = QPainterPath()
    if len(points) < 2:
        return out
    pts = np.array(points, np.float64)
    seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
    cum = np.concatenate([[0], np.cumsum(seg)])
    total = cum[-1]
    fm = QFontMetricsF(f)
    text = (s.get("text") or "").replace("\\n", " ")
    adv = [fm.horizontalAdvance(ch) for ch in text]
    width = sum(adv)
    start = float(s.get("pathOffset", 0)) * max(0.0, total - width)
    if s.get("align") == "center":
        start = (total - width) / 2
    elif s.get("align") == "right":
        start = total - width
    lift = float(s.get("pathLift", 0))

    def point(d):
        d = max(0.0, min(total, d))
        k = int(np.searchsorted(cum, d, side="right") - 1)
        k = max(0, min(k, len(seg) - 1))
        t = (d - cum[k]) / max(1e-9, seg[k])
        return pts[k] + (pts[k + 1] - pts[k]) * t

    at = start
    for ch, a in zip(text, adv):
        mid = at + a / 2
        at += a
        if mid < 0 or mid > total or not ch.strip():
            continue
        x, y = point(mid)
        a0, a1 = point(mid - a / 2), point(mid + a / 2)      # the letter turns with the line across its own width,
        ang = math.degrees(math.atan2(a1[1] - a0[1], a1[0] - a0[0]))   # so bends don't jolt it
        glyph = QPainterPath()
        glyph.addText(-a / 2, -lift, f, ch)
        out.addPath(QTransform().translate(x, y).rotate(ang).map(glyph))
    return out


# ------------------------------------------------------------------------------------------- adjustment layers and filters
def hue_rotate(rgb: np.ndarray, degrees: float) -> np.ndarray:
    """Turn every colour round the colour wheel (in YIQ, which keeps brightness)."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    to_yiq = np.array([[0.299, 0.587, 0.114], [0.596, -0.274, -0.322], [0.211, -0.523, 0.312]], np.float32)
    rot = np.array([[1, 0, 0], [0, c, -s], [0, s, c]], np.float32)
    m = np.linalg.inv(to_yiq) @ rot @ to_yiq
    return rgb @ m.T.astype(np.float32)


def curve_lut(points: list) -> np.ndarray:
    """A 256-step table through the curve's points (x, y in 0..1), smooth and never overshooting (monotone cubic)."""
    pts = sorted((max(0.0, min(1.0, float(x))), max(0.0, min(1.0, float(y)))) for x, y in (points or []))
    if not pts:
        pts = [(0.0, 0.0), (1.0, 1.0)]
    if pts[0][0] > 0:                                               # past the end points the curve stays level
        pts.insert(0, (0.0, pts[0][1]))
    if pts[-1][0] < 1:
        pts.append((1.0, pts[-1][1]))
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    keep = np.concatenate(([True], np.diff(xs) > 1e-6))
    xs, ys = xs[keep], ys[keep]
    t = np.linspace(0, 1, 256)
    if len(xs) < 2:
        return np.clip(t, 0, 1)
    h = np.diff(xs)
    d = np.diff(ys) / h
    m = np.zeros_like(xs)
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, len(xs) - 1):                                 # Fritsch–Carlson slopes
        m[i] = 0 if d[i - 1] * d[i] <= 0 else 3 * (h[i - 1] + h[i]) / ((2 * h[i] + h[i - 1]) / d[i - 1] + (h[i] + 2 * h[i - 1]) / d[i])
    k = np.clip(np.searchsorted(xs, t) - 1, 0, len(xs) - 2)
    u = (t - xs[k]) / h[k]
    h00, h10, h01, h11 = 2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u, -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
    out = h00 * ys[k] + h10 * h[k] * m[k] + h01 * ys[k + 1] + h11 * h[k] * m[k + 1]
    return np.clip(out, 0, 1)


def apply_curves(x: np.ndarray, curves: dict) -> np.ndarray:
    idx = np.clip((x * 255 + 0.5).astype(np.int32), 0, 255)
    if curves.get("rgb"):
        lut = curve_lut(curves["rgb"])
        x = lut[idx]
        idx = np.clip((x * 255 + 0.5).astype(np.int32), 0, 255)
    out = x.copy()
    for c, key in enumerate(("r", "g", "b")):
        if curves.get(key):
            out[..., c] = curve_lut(curves[key])[idx[..., c]]
    return out


def hex_rgb(colour: str) -> tuple:
    c = QColor(colour)
    return (c.red(), c.green(), c.blue()) if c.isValid() else (0, 0, 0)


def adjust_array(rgb: np.ndarray, kind: str, p: dict) -> np.ndarray:
    """One adjustment on float RGB (0..1). Parameters run from -1 to 1 unless said otherwise."""
    x = rgb
    if kind == "light":
        x = x + p.get("brightness", 0) * 0.35
        k = 1 + p.get("contrast", 0) * (0.9 if p.get("contrast", 0) > 0 else 0.7)
        x = (x - 0.5) * k + 0.5
    elif kind == "colour":
        if p.get("hue"):
            x = hue_rotate(x, p["hue"] * 180)
        lum = (x @ np.array([0.2126, 0.7152, 0.0722], np.float32))[..., None]
        x = lum + (x - lum) * (1 + p.get("saturation", 0))
        light = p.get("lightness", 0)
        if light:
            x = x + (1 - x) * light * 0.8 if light > 0 else x * (1 + light * 0.8)
    elif kind == "levels":
        lo, hi = p.get("black", 0.0), p.get("white", 1.0)                  # 0..1
        gamma = 2.0 ** (-p.get("gamma", 0.0) * 1.5)
        x = np.clip((x - lo) / max(1e-3, hi - lo), 0, 1) ** gamma
    elif kind == "bw":
        grey = (x @ np.array([0.3 + p.get("reds", 0) * 0.3, 0.59 + p.get("greens", 0) * 0.3, 0.11 + p.get("blues", 0) * 0.3], np.float32))[..., None]
        x = np.repeat(grey, 3, axis=2)
    elif kind == "invert":
        x = 1 - x
    elif kind == "curves":
        x = apply_curves(x, p.get("curves") or {})
    elif kind == "warmth":
        w = p.get("warmth", 0) * 0.15
        x = x * np.array([1 + w, 1, 1 - w], np.float32)
    elif kind == "posterize":
        n = max(2, int(2 + (p.get("levels", 0.3) + 1) * 7))
        x = np.round(x * (n - 1)) / (n - 1)
    elif kind == "vibrance":
        # vibrance lifts the dull colours most and leaves the strong ones (and skin) nearly alone; saturation is even
        lum = (x @ np.array([0.2126, 0.7152, 0.0722], np.float32))[..., None]
        sat = (x.max(axis=2, keepdims=True) - x.min(axis=2, keepdims=True))
        v = p.get("vibrance", 0)
        k = 1 + v * (1 - sat) * 1.5 if v > 0 else 1 + v * (1 - sat * 0.5)
        x = lum + (x - lum) * k * (1 + p.get("saturation", 0))
    elif kind == "exposure":
        # exposure in stops (-1..1 is three stops either way), then offset lifts or sinks the shadows, then gamma
        x = x * (2.0 ** (p.get("exposure", 0) * 3.0)) + p.get("offset", 0) * 0.25
        x = np.clip(x, 0, 1) ** (2.0 ** (-p.get("gamma", 0) * 1.5))
    elif kind == "balance":
        # each slider moves one channel, most in the midtones and not at all at black or white, so the picture
        # keeps its darkest and lightest points: toward red (away from cyan), green (magenta), blue (yellow)
        mid = 4 * x * (1 - x)
        x = x + mid * np.array([p.get("red", 0), p.get("green", 0), p.get("blue", 0)], np.float32) * 0.3
    elif kind == "threshold":
        lum = x @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        x = np.repeat((lum >= (p.get("level", 0) + 1) / 2).astype(np.float32)[..., None], 3, axis=2)
    elif kind == "mixer":
        # how much of each channel goes into the others: red from green, green from blue, blue from red (the three
        # swaps that between them reach any mix), keeping each channel's total at one so greys stay grey
        a, b, c = p.get("red_green", 0), p.get("green_blue", 0), p.get("blue_red", 0)
        m = np.array([[1 - abs(a), a, 0], [0, 1 - abs(b), b], [c, 0, 1 - abs(c)]], np.float32)
        x = x @ m.T
    elif kind == "gradmap":
        # each pixel's lightness picks its colour on a gradient: shadows → highlights (balance moves the middle)
        lum = np.clip(x @ np.array([0.2126, 0.7152, 0.0722], np.float32), 0, 1)
        bal = p.get("balance", 0)
        if bal:
            lum = lum ** (2.0 ** (-bal * 1.5))
        a = np.array(hex_rgb(p.get("from", "#1A1A2E")), np.float32) / 255
        b = np.array(hex_rgb(p.get("to", "#F5E6C8")), np.float32) / 255
        mapped = a + (b - a) * lum[..., None]
        k = (p.get("strength", 1.0) + 1) / 2
        x = x + (mapped - x) * k
    return np.clip(x, 0, 1)


ADJUST_PARAMS = {"light": [("brightness", "Brightness"), ("contrast", "Contrast")], "colour": [("hue", "Hue"), ("saturation", "Saturation"), ("lightness", "Lightness")],
                 "levels": [("black", "Black point"), ("gamma", "Midtones"), ("white", "White point")], "bw": [("reds", "Reds"), ("greens", "Greens"), ("blues", "Blues")],
                 "invert": [], "warmth": [("warmth", "Warmth")], "posterize": [("levels", "Levels")], "curves": [],
                 "vibrance": [("vibrance", "Vibrance"), ("saturation", "Saturation")], "gradmap": [("balance", "Balance"), ("strength", "Strength")],
                 "exposure": [("exposure", "Exposure"), ("offset", "Offset"), ("gamma", "Gamma")],
                 "balance": [("red", "Cyan · Red"), ("green", "Magenta · Green"), ("blue", "Yellow · Blue")],
                 "threshold": [("level", "Level")], "mixer": [("red_green", "Red ← Green"), ("green_blue", "Green ← Blue"), ("blue_red", "Blue ← Red")]}
ADJUST_DEFAULTS = {"levels": {"black": 0.0, "white": 1.0, "gamma": 0.0}, "posterize": {"levels": -0.4}, "vibrance": {"vibrance": 0.4},
                   "gradmap": {"balance": 0.0, "strength": 1.0},
                   "curves": {"curves": {"rgb": [[0, 0], [0.25, 0.2], [0.75, 0.82], [1, 1]]}}}


def _lum(c: np.ndarray) -> np.ndarray:
    return c[..., 0:1] * 0.3 + c[..., 1:2] * 0.59 + c[..., 2:3] * 0.11


def _set_lum(c: np.ndarray, l: np.ndarray) -> np.ndarray:
    """A colour moved to lightness l, kept inside 0..1 by pulling it toward grey (the W3C compositing rules)."""
    c = c + (l - _lum(c))
    l2, lo, hi = _lum(c), c.min(axis=2, keepdims=True), c.max(axis=2, keepdims=True)
    c = np.where(lo < 0, l2 + (c - l2) * l2 / np.maximum(l2 - lo, 1e-6), c)
    return np.where(hi > 1, l2 + (c - l2) * (1 - l2) / np.maximum(hi - l2, 1e-6), c)


def _set_sat(c: np.ndarray, s: np.ndarray) -> np.ndarray:
    lo, hi = c.min(axis=2, keepdims=True), c.max(axis=2, keepdims=True)
    return np.where(hi > lo, (c - lo) * s / np.maximum(hi - lo, 1e-6), 0.0)


def hsl_blend(under: np.ndarray, top: np.ndarray, mode: str, opacity: float) -> np.ndarray:
    """One of the four blend modes Qt lacks, on straight RGBA bytes: `top` over `under`.
    hue: the top layer's hue with what's under it for saturation and lightness; saturation: its saturation only;
    color: its hue and saturation (tinting a photograph); luminosity: its lightness only."""
    b, s = under.astype(np.float32) / 255.0, top.astype(np.float32) / 255.0
    cb, ab, cs, as_ = b[..., :3], b[..., 3:4], s[..., :3], s[..., 3:4] * opacity
    sat = lambda c: c.max(axis=2, keepdims=True) - c.min(axis=2, keepdims=True)
    if mode == "hue":
        mix = _set_lum(_set_sat(cs, sat(cb)), _lum(cb))
    elif mode == "saturation":
        mix = _set_lum(_set_sat(cb, sat(cs)), _lum(cb))
    elif mode == "color":
        mix = _set_lum(cs, _lum(cb))
    else:
        mix = _set_lum(cb, _lum(cs))
    ao = as_ + ab * (1 - as_)
    co = as_ * (1 - ab) * cs + as_ * ab * mix + (1 - as_) * ab * cb          # (premultiplied by the new alpha)
    out = np.empty_like(under)
    out[..., :3] = (np.clip(np.where(ao > 0, co / np.maximum(ao, 1e-6), 0), 0, 1) * 255 + 0.5).astype(np.uint8)
    out[..., 3:4] = (np.clip(ao, 0, 1) * 255 + 0.5).astype(np.uint8)
    return out


def blend_onto(out: QImage, img: QImage, mode: str, opacity: float) -> None:
    """Put a layer's picture onto what's under it, with its blend mode and opacity. Every place that stacks layers
    goes through here, so the modes Qt doesn't have work everywhere the others do."""
    if mode in HSL_BLENDS and opacity > 0:
        under, top = image_to_array(out), image_to_array(img)
        h, w = under.shape[:2]
        if h * w < 400_000:
            mixed = hsl_blend(under, top, mode, opacity)
        else:                                                      # in bands, on every core (as the adjustments are)
            step = max(16, min(96, 400_000 // max(1, w)))
            mixed = np.concatenate(list(pool().map(lambda y: hsl_blend(under[y:y + step], top[y:y + step], mode, opacity), range(0, h, step))))
        p = QPainter(out)
        p.setCompositionMode(CM.CompositionMode_Source)
        p.drawImage(0, 0, array_to_image(mixed))
        p.end()
        return
    p = QPainter(out)
    p.setOpacity(opacity)
    p.setCompositionMode(BLENDS.get(mode, CM.CompositionMode_SourceOver))
    p.drawImage(0, 0, img)
    p.end()


_POOL = None
PER_CHANNEL = ("light", "levels", "invert", "curves", "warmth", "posterize", "exposure", "balance")


def pool():
    """A few threads for work that splits into rows or into layers (numpy and Qt's picture code let other threads run)."""
    global _POOL
    if _POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _POOL = ThreadPoolExecutor(max(1, min(8, os.cpu_count() or 2)), thread_name_prefix="easel")
    return _POOL


def apply_adjust_run(below: QImage, run: list) -> QImage:
    """One or more adjustments of the kind where each channel's new value depends only on its old one, one over
    another: [(kind, params)], bottom first. The 256 possible answers are worked out once and every pixel looked up: a
    12-megapixel picture in a few hundredths of a second, however many adjustments there are. And the answers are
    carried from one adjustment to the next as fine numbers, rounded to whole levels only at the end, so three
    adjustments in a row don't leave the gaps and steps in smooth tones that rounding three times does."""
    src = image_to_array(below)
    x = np.repeat((np.arange(256, dtype=np.float32) / 255.0)[:, None, None], 3, axis=2)
    for kind, params in run:
        x = adjust_array(x, kind, params)
    table = (x * 255 + 0.5).astype(np.uint8)[:, 0, :]
    ramp0 = np.zeros((1, 1, 3), np.float32)                        # see-through pixels count as black for each adjustment in turn
    clear0 = (adjust_array(ramp0, run[-1][0], run[-1][1]) * 255 + 0.5).astype(np.uint8)[0, 0]
    out = np.empty_like(src)
    clear = src[..., 3] == 0
    for c in range(3):
        out[..., c] = table[:, c][src[..., c]]
        out[..., c][clear] = clear0[c]
    out[..., 3] = src[..., 3]
    return array_to_image(out)


def apply_adjust_image(below: QImage, kind: str, params: dict) -> QImage:
    """An adjustment layer's doing: every pixel under it changed, each on its own. Worked a band of rows at a time
    (the numbers for a band fit in the processor's cache, where the whole picture's don't) and the bands side by side
    on every core: about four times quicker on a big picture, and the same answer to the last bit."""
    if kind in PER_CHANNEL:
        return apply_adjust_run(below, [(kind, params)])
    src = image_to_array(below)
    h = src.shape[0]

    def band(rows: slice) -> np.ndarray:
        arr = src[rows].astype(np.float32) / 255.0
        rgb, a = arr[..., :3], arr[..., 3:4]
        out = adjust_array(np.where(a > 0, rgb, 0), kind, params)
        return (np.concatenate([out, a], axis=2) * 255 + 0.5).astype(np.uint8)
    if h * src.shape[1] < 400_000:
        return array_to_image(band(slice(0, h)))
    step = max(16, min(96, 400_000 // max(1, src.shape[1])))
    return array_to_image(np.concatenate(list(pool().map(band, [slice(y, min(h, y + step)) for y in range(0, h, step)]))))


FILTERS = {"blur": "Blur", "sharpen": "Sharpen", "noise": "Add Noise", "pixelate": "Pixelate", "emboss": "Emboss", "edges": "Find Edges",
           "invert": "Invert", "desaturate": "Desaturate", "posterize": "Posterize", "autolevels": "Auto Levels", "motion": "Motion Blur",
           "clarity": "Clarity", "highpass": "High Pass", "denoise": "Reduce Noise", "glow": "Soft Glow", "vignette": "Vignette"}


def filter_array(rgba: np.ndarray, name: str, amount: float) -> np.ndarray:
    """A filter on the whole of an RGBA picture (Pillow does the convolutions). amount is 0..1."""
    from PIL import Image, ImageFilter, ImageOps
    img = Image.fromarray(rgba, "RGBA")
    if name == "blur":
        img = img.filter(ImageFilter.GaussianBlur(radius=0.5 + amount * 30))
    elif name == "sharpen":
        img = img.filter(ImageFilter.UnsharpMask(radius=2 + amount * 3, percent=int(60 + amount * 240), threshold=2))
    elif name == "motion":
        n = max(3, int(3 + amount * 40)) | 1
        k = [0.0] * (n * n)
        for i in range(n):
            k[(n // 2) * n + i] = 1.0
        if n > 5:                                                    # Pillow's kernels stop at 5×5: blur sideways by shifting
            arr = np.asarray(img).astype(np.float32)
            acc = np.zeros_like(arr)
            for i in range(-(n // 2), n // 2 + 1):
                acc += np.roll(arr, i, axis=1)
            return np.clip(acc / n, 0, 255).astype(np.uint8)
        img = img.filter(ImageFilter.Kernel((n, n), k, scale=n))
    elif name == "noise":
        arr = np.asarray(img).astype(np.float32)
        noise = np.random.default_rng(int(time.time())).normal(0, 1, arr.shape[:2] + (1,)) * (4 + amount * 60)
        arr[..., :3] += noise
        return np.clip(arr, 0, 255).astype(np.uint8)
    elif name == "pixelate":
        side = max(2, int(2 + amount * 60))
        w, h = img.size
        img = img.resize((max(1, w // side), max(1, h // side)), Image.Resampling.BOX).resize((w, h), Image.Resampling.NEAREST)
    elif name == "emboss":
        a = img.getchannel("A")
        img = img.convert("RGB").filter(ImageFilter.EMBOSS).convert("RGBA")
        img.putalpha(a)
    elif name == "edges":
        a = img.getchannel("A")
        img = ImageOps.invert(img.convert("RGB").filter(ImageFilter.FIND_EDGES)).convert("RGBA")
        img.putalpha(a)
    elif name in ("clarity", "highpass", "glow"):
        # all three compare the picture with a blurred copy of itself. Clarity adds the difference back at a wide
        # radius (contrast in the midtones, without the halos of sharpening); High Pass keeps only the difference
        # on grey (for a layer set to Overlay); Soft Glow screens the blur over the picture.
        arr = np.asarray(img).astype(np.float32)
        radius = {"clarity": 20 + amount * 60, "highpass": 1 + amount * 30, "glow": 4 + amount * 40}[name]
        soft = np.asarray(img.convert("RGB").filter(ImageFilter.GaussianBlur(radius=radius))).astype(np.float32)
        rgb = arr[..., :3]
        if name == "clarity":
            mid = 1 - np.abs(rgb / 255 - 0.5) * 2                      # least at black and white, so nothing clips
            rgb = rgb + (rgb - soft) * (0.3 + amount * 0.9) * mid
        elif name == "highpass":
            rgb = (rgb - soft) + 127.5
        else:
            k = 0.25 + amount * 0.6
            rgb = rgb + (255 - (255 - rgb) * (255 - soft) / 255 - rgb) * k
        arr[..., :3] = rgb
        return np.clip(arr + 0.5, 0, 255).astype(np.uint8)
    elif name == "denoise":
        a = img.getchannel("A")
        if cv2 is not None:                                          # smooths the grain, keeps the edges
            rgb = np.ascontiguousarray(np.asarray(img.convert("RGB")))
            d = 5 if amount < 0.5 else 7
            out = cv2.bilateralFilter(rgb, d, 12 + amount * 70, 3 + amount * 6)
            img = Image.fromarray(out, "RGB").convert("RGBA")
        else:
            img = img.convert("RGB").filter(ImageFilter.MedianFilter(3 if amount < 0.5 else 5)).convert("RGBA")
        img.putalpha(a)
    elif name == "vignette":
        arr = np.asarray(img).astype(np.float32)
        h, w = arr.shape[:2]
        yy, xx = np.ogrid[0:h, 0:w]
        d = np.sqrt(((xx - (w - 1) / 2) / max(1.0, w / 2)) ** 2 + ((yy - (h - 1) / 2) / max(1.0, h / 2)) ** 2) / math.sqrt(2)
        fall = np.clip((d - 0.35) / 0.65, 0, 1) ** 2                 # nothing in the middle, deepening to the corners
        arr[..., :3] *= (1 - fall * (0.2 + amount * 0.75))[..., None]
        return np.clip(arr + 0.5, 0, 255).astype(np.uint8)
    elif name in ("invert", "desaturate", "posterize", "autolevels"):
        arr = np.asarray(img).astype(np.float32) / 255
        rgb = arr[..., :3]
        if name == "invert":
            rgb = 1 - rgb
        elif name == "desaturate":
            rgb = np.repeat((rgb @ np.array([0.3, 0.59, 0.11], np.float32))[..., None], 3, axis=2)
        elif name == "posterize":
            n = max(2, int(2 + (1 - amount) * 10))
            rgb = np.round(rgb * (n - 1)) / (n - 1)
        else:
            seen = rgb[arr[..., 3] > 0.05] if (arr[..., 3] > 0.05).any() else rgb.reshape(-1, 3)
            lo, hi = np.percentile(seen, 0.5, axis=0), np.percentile(seen, 99.5, axis=0)
            rgb = np.clip((rgb - lo) / np.maximum(1e-3, hi - lo), 0, 1)
        arr[..., :3] = rgb
        return (np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)
    return np.asarray(img).copy()


def refine_edge(alpha: np.ndarray, rgba: np.ndarray, radius: float) -> np.ndarray:
    """A selection's edge fitted to the picture under it. Within `radius` pixels of the edge, how selected each pixel
    is gets worked out again from the picture itself (a guided filter: where the picture has an edge the selection
    gets one, where it has wisps of hair or fur the selection goes partly through them), and further in or out it's
    left as it was. alpha: 0..255 bytes; rgba: the picture, straight RGBA bytes. Returns bytes."""
    r = max(1, int(round(radius)))
    p = alpha.astype(np.float32) / 255.0
    guide = (rgba[..., 0] * 0.2126 + rgba[..., 1] * 0.7152 + rgba[..., 2] * 0.0722).astype(np.float32) / 255.0
    if cv2 is not None:
        box = lambda x: cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1), borderType=cv2.BORDER_REFLECT)
    else:
        from PIL import Image, ImageFilter
        box = lambda x: np.asarray(Image.fromarray(x, "F").filter(ImageFilter.BoxBlur(r)), np.float32)
    mean_i, mean_p = box(guide), box(p)
    var_i = box(guide * guide) - mean_i * mean_i
    cov = box(guide * p) - mean_i * mean_p
    a = cov / (var_i + 1e-4)
    b = mean_p - a * mean_i
    q = np.clip(box(a) * guide + box(b), 0.0, 1.0)
    q = np.clip((q - 0.06) / 0.88, 0.0, 1.0)                        # (a little contrast: nearly-in is in, nearly-out is out)
    near = (box((p > 0.5).astype(np.float32)) > 0.002) & (box((p > 0.5).astype(np.float32)) < 0.998)     # the band along the edge
    return (np.where(near, q, p) * 255 + 0.5).astype(np.uint8)


# ------------------------------------------------------------------------------------------- filling and choosing by colour
def flood(ok: np.ndarray, x: int, y: int) -> np.ndarray:
    """The connected part of `ok` (a h×w bool array) that holds (x, y): a scanline fill, row runs at a time."""
    h, w = ok.shape
    out = np.zeros_like(ok)
    if not (0 <= x < w and 0 <= y < h) or not ok[y, x]:
        return out
    stack = [(x, y)]
    while stack:
        x, y = stack.pop()
        if out[y, x] or not ok[y, x]:
            continue
        row = ok[y]
        left = row[:x + 1][::-1]
        l = x - (int(np.argmin(left)) if not left.all() else len(left)) + 1
        right = row[x:]
        r = x + (int(np.argmin(right)) if not right.all() else len(right)) - 1
        out[y, l:r + 1] = True
        for ny in (y - 1, y + 1):
            if 0 <= ny < h:
                seg = ok[ny, l:r + 1] & ~out[ny, l:r + 1]
                if seg.any():
                    d = np.diff(np.concatenate(([False], seg)).astype(np.int8))
                    for s0 in np.nonzero(d == 1)[0]:
                        stack.append((l + int(s0), ny))
    return out


def similar(rgba: np.ndarray, x: int, y: int, tolerance: float) -> np.ndarray:
    """Pixels close in colour (and transparency) to the one at (x, y). tolerance 0..1."""
    ref = rgba[y, x].astype(np.int16)
    t = int(tolerance * 255)
    if cv2 is not None:                                              # the same test, in one pass over the picture
        lo, hi = np.clip(ref - t, 0, 255).astype(np.uint8), np.clip(ref + t, 0, 255).astype(np.uint8)
        return cv2.inRange(np.ascontiguousarray(rgba), lo, hi) > 0
    diff = np.abs(rgba.astype(np.int16) - ref).max(axis=2)
    return diff <= t


# ------------------------------------------------------------------------------------------- the document
def new_layer(kind: str, name: str, w: int = 0, h: int = 0, fill=None) -> dict:
    layer = {"id": uuid.uuid4().hex[:10], "name": name, "kind": kind, "visible": True, "locked": False, "opacity": 1.0, "blend": "normal",
             "mask": None, "maskOn": True, "v": 0}
    if kind == "pixel":
        layer["image"] = new_image(w, h, fill)
    elif kind == "vector":
        layer["shapes"] = []
    elif kind == "adjust":
        layer["adjust"] = "light"
        layer["params"] = {}
    elif kind == "group":
        layer["open"] = True
    return layer


def copy_layer(layer: dict) -> dict:
    """A copy that shares pictures until one side paints (QImage copies only when written to)."""
    out = dict(layer)
    if "image" in layer:
        out["image"] = QImage(layer["image"])
    if layer.get("source") is not None:
        out["source"] = QImage(layer["source"])
    for key in ("fx", "place", "sfilters"):                     # nested settings: a copy, so undo keeps the old ones
        if layer.get(key) is not None:
            out[key] = json.loads(json.dumps(layer[key]))
    if layer.get("mask") is not None:
        out["mask"] = QImage(layer["mask"])
    if "shapes" in layer:
        out["shapes"] = json.loads(json.dumps(layer["shapes"]))
    if "params" in layer:
        out["params"] = dict(layer["params"])
    return out


class Document:
    def __init__(self, w: int, h: int, background="#FFFFFF"):
        self.w, self.h = checked_size(w, h)
        self.layers = []
        if background is not None:
            self.layers.append(new_layer("pixel", "Background", w, h, background))
        else:
            self.layers.append(new_layer("pixel", "Layer 1", w, h))
        self.active = self.layers[-1]["id"]
        self.selection = None                                   # an image whose alpha is how chosen each pixel is
        self.path = ""
        self.dpi = 72
        self.version = 0
        self.guides = []                                        # [{"axis": "x" or "y", "at": pixels}]
        self._vector_cache = {}
        self._mask_cache = {}
        self._fx_cache = {}
        self._win = None                                        # while one patch of the picture is being put together: its rectangle
        self._mip = 0                                           # while a smaller copy is being put together: how many times smaller
        self._mip_cache = {}                                    # each layer's smaller copies, kept until the layer changes
        self.export_note = ""                                   # after an export: what had to be merged to keep the look, in words

    def tidy(self) -> "Document":
        """After a file is read: every layer made sound, whatever the file said. A setting of the wrong kind goes back
        to its usual value, a picture of the wrong size is fitted, a shape or style that can't be drawn is dropped,
        and a picture that still can't be put together is refused (ValueError), so nothing half-read gets on screen."""
        import huginn_easel_more as more
        good, seen = [], set()
        for l in self.layers if isinstance(self.layers, list) else []:
            if not isinstance(l, dict) or l.get("kind") not in KINDS:
                continue
            if not isinstance(l.get("id"), str) or not l["id"] or len(l["id"]) > 64 or l["id"] in seen:
                l["id"] = uuid.uuid4().hex[:10]
            seen.add(l["id"])
            l["name"] = (l["name"].replace("\0", "")[:80] or "Layer") if isinstance(l.get("name"), str) else "Layer"
            for key, usual in (("visible", True), ("locked", False), ("maskOn", True)):
                l[key] = l[key] if isinstance(l.get(key), bool) else usual
            for key in ("clip", "lockAlpha", "open"):
                if key in l and not isinstance(l[key], bool):
                    del l[key]
            l["opacity"] = _number(l.get("opacity"), 0.0, 1.0, 1.0)
            l["blend"] = l["blend"] if isinstance(l.get("blend"), str) and l["blend"] in BLENDS else "normal"
            l["v"] = 0
            if not isinstance(l.get("group"), str):
                l.pop("group", None)
            if l["kind"] == "pixel":
                img = l.get("image")
                if not isinstance(img, QImage) or img.isNull():
                    l["image"] = new_image(self.w, self.h)
                elif img.width() != self.w or img.height() != self.h or img.format() != FMT:
                    l["image"] = _fit(img.convertToFormat(FMT), self.w, self.h)
            elif l["kind"] == "vector":
                shapes = []
                for sh in l["shapes"] if isinstance(l.get("shapes"), list) else []:
                    try:                                       # a shape stays only if it can be measured and drawn
                        if not isinstance(sh, dict) or sh.get("type") not in ("rect", "ellipse", "line", "star", "path", "text"):
                            continue
                        if sh["type"] == "path" and not isinstance(sh.get("subs"), list):
                            continue
                        if any(isinstance(v, float) and not math.isfinite(v) or isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) > 1e7 for v in sh.values()):
                            continue
                        if "points" in sh:                     # (a star with a billion points would never finish drawing)
                            sh["points"] = int(_number(sh["points"], 3, 200, 5))
                        if sh["type"] == "text":
                            sh["size"] = _number(sh.get("size"), 1, 4000, 72)
                            sh["text"] = sh["text"][:20000] if isinstance(sh.get("text"), str) else ""
                        if not isinstance(sh.get("id"), str):
                            sh["id"] = uuid.uuid4().hex[:8]
                        box = shape_bounds(sh)
                        if not all(math.isfinite(v) for v in (box.x(), box.y(), box.width(), box.height())) or max(abs(box.x()), abs(box.y()), box.width(), box.height()) > 1e7:
                            continue
                        probe = new_image(8, 8)
                        pp = QPainter(probe)
                        try:
                            paint_shape(pp, sh)
                        finally:
                            pp.end()
                        shapes.append(sh)
                    except Exception:                          # noqa: BLE001  (whatever is wrong with it, it can't be kept)
                        continue
                l["shapes"] = shapes[:20000]
            elif l["kind"] == "adjust":
                l["adjust"] = l["adjust"] if isinstance(l.get("adjust"), str) and l["adjust"] in ADJUSTMENTS else "light"
                params = {}
                for key, v in (l["params"] if isinstance(l.get("params"), dict) else {}).items():
                    if not isinstance(key, str) or len(key) > 40:
                        continue
                    if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                        params[key] = max(-100.0, min(100.0, float(v)))
                    elif isinstance(v, str) and len(v) < 40 and QColor(v).isValid():
                        params[key] = v
                    elif key == "curves" and isinstance(v, dict):
                        curves = {}
                        for ch, pts in v.items():
                            if ch in ("rgb", "r", "g", "b") and isinstance(pts, list):
                                ok = [[_number(pt[0], 0, 1, 0), _number(pt[1], 0, 1, 0)] for pt in pts[:32]
                                      if isinstance(pt, (list, tuple)) and len(pt) == 2 and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in pt)]
                                if len(ok) >= 2:
                                    curves[ch] = ok
                        params[key] = curves
                l["params"] = params
            elif l["kind"] == "smart":
                src = l.get("source")
                if not isinstance(src, QImage) or src.isNull():
                    continue
                pl = l["place"] if isinstance(l.get("place"), dict) else {}
                place = {"cx": _number(pl.get("cx"), -1e6, 1e6, self.w / 2), "cy": _number(pl.get("cy"), -1e6, 1e6, self.h / 2),
                         "sx": _number(pl.get("sx"), 0.001, 1000, 1.0), "sy": _number(pl.get("sy"), 0.001, 1000, 1.0), "rot": _number(pl.get("rot"), -36000, 36000, 0.0)}
                for key in ("flipx", "flipy"):
                    if isinstance(pl.get(key), bool):
                        place[key] = pl[key]
                quad = pl.get("quad")
                if isinstance(quad, list) and len(quad) == 4 and all(isinstance(c, (list, tuple)) and len(c) == 2 and all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) and abs(n) < 1e6 for n in c) for c in quad):
                    place["quad"] = [[float(c[0]), float(c[1])] for c in quad]
                l["place"] = place
                l["sfilters"] = [{"name": f["name"], "amount": _number(f.get("amount"), 0.0, 1.0, 0.4), "on": f.get("on") is not False}
                                 for f in (l["sfilters"] if isinstance(l.get("sfilters"), list) else [])[:32]
                                 if isinstance(f, dict) and isinstance(f.get("name"), str) and f["name"] in FILTERS]
            mask = l.get("mask")
            if mask is not None:
                if not isinstance(mask, QImage) or mask.isNull():
                    l["mask"] = None
                elif mask.width() != self.w or mask.height() != self.h or mask.format() != FMT:
                    l["mask"] = _fit(mask.convertToFormat(FMT), self.w, self.h)
            if "fx" in l:
                fx = l["fx"]
                sound = isinstance(fx, dict) and all(isinstance(k, str) and k in more.STYLES and isinstance(st, dict) for k, st in fx.items())
                if sound:
                    clean = {}
                    for k, st in fx.items():
                        usual, one = more.STYLES[k], {}
                        for prop, v in st.items():
                            if prop not in usual:
                                continue
                            want = usual[prop]
                            if isinstance(want, bool):
                                one[prop] = v if isinstance(v, bool) else want
                            elif isinstance(want, (int, float)):
                                one[prop] = _number(v, -3600.0, 3600.0, float(want))
                            elif isinstance(want, str):
                                one[prop] = v if isinstance(v, str) and len(v) < 40 and (prop != "colour" or QColor(v).isValid()) else want
                        clean[k] = one
                    l["fx"] = clean
                else:
                    del l["fx"]
            good.append(l)
        ids = {l["id"] for l in good}
        for l in good:
            if l.get("group") not in ids or l.get("group") == l["id"]:
                l.pop("group", None)
        if not any(l["kind"] != "group" for l in good):
            good.append(new_layer("pixel", "Layer 1", self.w, self.h))
        self.layers = more.normalize(good)
        self.active = self.active if isinstance(self.active, str) and any(l["id"] == self.active for l in self.layers) else self.layers[-1]["id"]
        self.guides = [{"axis": g["axis"], "at": round(_number(g.get("at"), -1e5, 1e5, 0.0), 1)} for g in (self.guides if isinstance(self.guides, list) else [])[:200]
                       if isinstance(g, dict) and g.get("axis") in ("x", "y")]
        self.dpi = int(_number(self.dpi, 1, 10000, 72))
        self.selection = None
        self._vector_cache, self._mask_cache, self._fx_cache = {}, {}, {}
        try:
            flat = self.flattened()
            if flat.isNull():
                raise ValueError
        except Exception:                                      # noqa: BLE001
            raise ValueError("This file is damaged in a way Easel can't mend.") from None
        return self

    # -------------------------------------------------------------- finding layers
    def layer(self, ident: str = None) -> dict:
        ident = ident or self.active
        return next((l for l in self.layers if l["id"] == ident), self.layers[-1] if self.layers else None)

    def index(self, ident: str) -> int:
        return next((i for i, l in enumerate(self.layers) if l["id"] == ident), -1)

    def touch(self, layer: dict = None) -> None:
        self.version += 1
        if layer is not None:
            layer["v"] = next_v()

    # -------------------------------------------------------------- drawing it all
    def layer_image(self, layer: dict, extra=None) -> QImage:
        """What one layer looks like on its own (vector layers are drawn here; their picture is kept until they change)."""
        if layer["kind"] == "pixel":
            img = layer["image"]
            if extra is not None:
                img = extra(img)
        elif layer["kind"] == "vector":
            key = (layer["id"], layer.get("v", 0), self.w, self.h)
            img = self._vector_cache.get(layer["id"])
            if img is None or img[0] != key or extra is not None:
                canvas = new_image(self.w, self.h)
                p = QPainter(canvas)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
                for s in layer["shapes"]:
                    if not s.get("hidden"):
                        paint_shape(p, s)
                p.end()
                if extra is not None:
                    return self._masked(layer, extra(canvas))
                self._vector_cache[layer["id"]] = (key, canvas)
                img = (key, canvas)
            img = img[1]
        elif layer["kind"] == "smart":
            key = (layer["id"], layer.get("v", 0), self.w, self.h)
            img = self._vector_cache.get(layer["id"])
            if img is None or img[0] != key:
                import huginn_easel_more as more
                img = (key, more.smart_render(layer, self.w, self.h, filter_array))
                self._vector_cache[layer["id"]] = img
            img = img[1]
            if extra is not None:
                img = extra(img)
        elif layer["kind"] == "group":
            return self.group_image(layer)
        else:
            return None
        return self._masked(layer, img)

    def styled_image(self, layer: dict, extra=None) -> QImage:
        """A layer as it shows: its picture with its styles (shadows, glows, outlines…), kept until it changes."""
        import huginn_easel_more as more
        img = self.layer_image(layer, extra)
        if img is None or not more.has_fx(layer):
            return img
        if extra is not None:
            return more.render_fx(img, layer)
        key = (layer.get("v", 0), self.w, self.h, more.dumps(layer.get("fx")), self._inside_key(layer))
        got = self._fx_cache.get(layer["id"])
        if got is None or got[0] != key:
            got = (key, more.render_fx(img, layer))
            self._fx_cache[layer["id"]] = got
        return got[1]

    def _inside_key(self, layer: dict) -> tuple:
        if layer["kind"] != "group":
            return ()
        import huginn_easel_more as more
        a, b = more.span(self.layers, layer["id"])
        return tuple((l["id"], l.get("v", 0), l["visible"], l["opacity"], l["blend"], more.dumps(l.get("fx"))) for l in self.layers[a:b])

    def group_image(self, header: dict, live=None) -> QImage:
        """A group's insides drawn on their own, then masked (its own blend and opacity are for where it goes)."""
        import huginn_easel_more as more
        sub = self._find(more.tree(self.layers), header["id"])
        return self._masked(header, self._stack(sub or [], live))

    def _find(self, items: list, gid: str):
        for it in items:
            if isinstance(it, tuple):
                if it[1]["id"] == gid:
                    return it[2]
                got = self._find(it[2], gid)
                if got is not None:
                    return got
        return None

    def visible_in_place(self, layer: dict) -> bool:
        """Shown: it and every group it's in."""
        import huginn_easel_more as more
        return layer["visible"] and all(self.layer(g)["visible"] for g in more.ancestors(self.layers, layer))

    def opacity_in_place(self, layer: dict) -> float:
        import huginn_easel_more as more
        o = layer["opacity"]
        for g in more.ancestors(self.layers, layer):
            o *= self.layer(g)["opacity"]
        return o

    def _masked(self, layer: dict, img: QImage) -> QImage:
        if layer.get("mask") is None or not layer.get("maskOn", True):
            return img
        mask = layer["mask"]
        if self._mip and img.size() != mask.size():
            mask = self._shrunk(mask, ("mask", layer["id"]), (layer.get("v", 0), self._mip, self.w, self.h))
        elif self._win is not None and img.size() != mask.size():
            mask = mask.copy(self._win)
        out = img.copy()
        p = QPainter(out)
        p.setCompositionMode(CM.CompositionMode_DestinationIn)
        p.drawImage(0, 0, mask)
        p.end()
        return out

    def small_size(self, k: int) -> tuple:
        return max(1, -(-self.w // k)), max(1, -(-self.h // k))

    def _shrunk(self, img: QImage, name=None, key=None) -> QImage:
        """A picture at 1/k of its size (k = self._mip), kept under `name` for as long as `key` stays the same."""
        if name is not None:
            got = self._mip_cache.get((name, self._mip))
            if got is not None and got[0] == key:
                return got[1]
        w, h = self.small_size(self._mip)
        out = img.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if out.format() != FMT:
            out = out.convertToFormat(FMT)
        if name is not None:
            if len(self._mip_cache) > 6 * len(self.layers) + 24:   # (layers long gone: let their copies go)
                self._mip_cache.clear()
            self._mip_cache[(name, self._mip)] = (key, out)
        return out

    def histogram(self, upto: int = None) -> dict:
        """How the picture's tones are spread: 64 bars each for lightness, red, green and blue, each 0..1 (square-rooted,
        so a few very full bars don't flatten the rest). Counted on a small copy: the shape is the same and it's instant.
        `upto`: only the layers below that place in the stack (what an adjustment layer there is given to work on)."""
        import huginn_easel_more as more
        k = 1
        while (self.w // k) * (self.h // k) > 600_000 and k < 8:
            k *= 2
        layers = self.layers if upto is None else self.layers[:max(0, upto)]
        if k > 1:
            self._mip = k
        try:
            img = self._stack(more.tree(layers))
        finally:
            self._mip = 0
        a = image_to_array(img)
        seen = a[a[..., 3] > 12]
        out = {}
        if not len(seen):
            return {key: [0.0] * 64 for key in ("l", "r", "g", "b")}
        lum = (seen[:, 0] * 0.2126 + seen[:, 1] * 0.7152 + seen[:, 2] * 0.0722).astype(np.uint8)
        for key, vals in (("l", lum), ("r", seen[:, 0]), ("g", seen[:, 1]), ("b", seen[:, 2])):
            bars = np.sqrt(np.bincount(vals >> 2, minlength=64)[:64].astype(np.float64))
            out[key] = [float(v) for v in bars / max(1.0, bars.max())]
        return out

    def composite_small(self, k: int, live=None) -> QImage:
        """The whole picture at 1/k of its size, put together from 1/k-size copies of the layers (each kept until its
        layer changes). When the picture is shown smaller than life this is all the screen can show anyway, and it
        costs 1/k² as much: on a 12-megapixel picture at "fit to window", moving a layer or dragging an adjustment's
        slider redraws in a few hundredths of a second instead of most of one. Not for saving or exporting: the
        layers are shrunk before they're blended, so it can differ from the true picture by a shade at hard edges."""
        import huginn_easel_more as more
        if k <= 1:
            return self.composite(live)
        self._mip = int(k)
        try:
            return self._stack(more.tree(self.layers), live)
        finally:
            self._mip = 0

    def composite_patch(self, r: QRect, live=None) -> QImage:
        """One rectangle of the finished picture, put together from that rectangle of every layer: blends, adjustment
        layers, masks, groups and clipping all as in the whole picture, at a cost that goes with the patch's size and
        not the picture's. `live` = (layer id, None, function(rect) -> that layer's patch with the stroke in progress).
        Styles spread past a patch, so a layer or group with styles is taken from its kept picture: the caller must
        not ask for this while the layer being painted has styles, or is in a group that has."""
        import huginn_easel_more as more
        self._win = QRect(r)
        try:
            return self._stack(more.tree(self.layers), live)
        finally:
            self._win = None

    def composite(self, live=None, upto: int = None) -> QImage:
        """Every visible layer, bottom up. `live` = (layer id, function(image) → image) shows a stroke in progress.
        A group's insides are drawn on their own and then go onto what's under the group, with its blend,
        opacity, mask and styles."""
        import huginn_easel_more as more
        layers = self.layers if upto is None else self.layers[:upto]
        return self._stack(more.tree(layers), live)

    def _item_image(self, it, live=None):
        """One thing in a stack (a layer, or a group as a tuple) as a picture, before its own opacity and blend:
        (image, header). None for what isn't a picture of its own (an adjustment layer)."""
        import huginn_easel_more as more
        if self._mip:                                              # a smaller copy is wanted
            k = self._mip
            if isinstance(it, tuple):
                header, inside = it[1], it[2]
                if more.has_fx(header):                            # (styles are worked out at full size, then shrunk and kept)
                    self._mip = 0
                    try:
                        full, _ = self._item_image(it, live)
                    finally:
                        self._mip = k
                    busy = live is not None and any(l["id"] == live[0] for l in more.flatten_tree(inside))
                    key = (header.get("v", 0), k, self.w, self.h, more.dumps(header.get("fx")), self._inside_key(header))
                    return (self._shrunk(full) if busy else self._shrunk(full, ("group", header["id"]), key)), header
                return self._masked(header, self._stack(inside, live)), header
            if it["kind"] == "adjust":
                return None
            if live and live[0] == it["id"]:
                if len(live) > 3 and live[3] is not None:          # (the caller can make the small picture itself)
                    return live[3](k), it
                return self._shrunk(self.styled_image(it, live[1])), it
            key = (it.get("v", 0), k, self.w, self.h, more.dumps(it.get("fx")), it.get("maskOn", True))
            got = self._mip_cache.get((it["id"], k))
            if got is not None and got[0] == key:
                if CHECK_MIPS and image_to_array(self._shrunk(self.styled_image(it))).tobytes() != image_to_array(got[1]).tobytes():
                    raise AssertionError(f"a kept smaller copy of layer {it['name']!r} is out of date (version {it.get('v')})")
                return got[1], it
            return self._shrunk(self.styled_image(it), it["id"], key), it
        win = self._win
        if win is not None:                                        # only a patch is wanted
            if isinstance(it, tuple) and more.has_fx(it[1]):       # (styles reach past a patch: from the group's kept picture)
                self._win = None
                try:
                    full, header = self._item_image(it, None)
                finally:
                    self._win = win
                return full.copy(win), header
            if not isinstance(it, tuple):
                if it["kind"] == "adjust":
                    return None
                if live and live[0] == it["id"] and len(live) > 2 and live[2] is not None:
                    return self._masked(it, live[2](win)), it
                if it["kind"] == "pixel" and not more.has_fx(it):
                    return self._masked(it, it["image"].copy(win)), it
                return self.styled_image(it).copy(win), it         # shapes, smart objects, styled layers: kept pictures
        if isinstance(it, tuple):
            header, inside = it[1], it[2]
            img = self._masked(header, self._stack(inside, live))
            if more.has_fx(header):
                key = (header.get("v", 0), self.w, self.h, more.dumps(header.get("fx")), self._inside_key(header))
                got = self._fx_cache.get(header["id"])
                if live is not None and any(l["id"] == live[0] for l in more.flatten_tree(inside)):
                    img = more.render_fx(img, header)
                else:
                    if got is None or got[0] != key:
                        got = (key, more.render_fx(img, header))
                        self._fx_cache[header["id"]] = got
                    img = got[1]
            return img, header
        if it["kind"] == "adjust":
            return None
        return self.styled_image(it, live[1] if live and live[0] == it["id"] else None), it

    def _lay(self, out: QImage, it, live=None) -> None:
        """Put one layer, group or adjustment onto what's been put together so far."""
        head = it[1] if isinstance(it, tuple) else it
        if not head["visible"]:
            return
        if head["kind"] == "adjust":
            adjusted = apply_adjust_image(out, head["adjust"], head.get("params") or {})
            if head.get("mask") is not None and head.get("maskOn", True):
                adjusted = self._masked(head, adjusted)
            p = QPainter(out)
            p.setOpacity(head["opacity"])
            p.drawImage(0, 0, adjusted)
            p.end()
            return
        img, _ = self._item_image(it, live)
        blend_onto(out, img, head["blend"], head["opacity"])

    @staticmethod
    def _plain_adjust(it) -> bool:
        """An adjustment layer that changes every pixel under it in full, each channel on its own: no mask, full
        strength, showing. Several of these in a row come to one table of answers (apply_adjust_run)."""
        return (not isinstance(it, tuple) and it["kind"] == "adjust" and it["visible"] and it.get("adjust") in PER_CHANNEL
                and it["opacity"] >= 0.999 and not (it.get("mask") is not None and it.get("maskOn", True)))

    def _clipped_image(self, base, clipped: list, live=None) -> QImage:
        """A layer (or group) with the layers clipped to it, as one picture in the lower one's shape."""
        shape, _ = self._item_image(base, live)
        both = shape.copy()
        for c in clipped:
            self._lay(both, c, live)
        p = QPainter(both)
        p.setCompositionMode(CM.CompositionMode_DestinationIn)
        p.drawImage(0, 0, shape)                                   # only where the lower layer is
        p.end()
        return both

    def export_layers(self, groups: bool, clipping: bool) -> list:
        """The picture as plain layers another program can stack up to get the same picture: bottom first, each
        {"name", "image", "opacity", "blend", "visible", "clip", "lockAlpha"}, or (with `groups`) {"stack": [...]} for
        a group. What the other format can't say is baked in, and only that: an adjustment layer and everything it
        changes become one picture; a group with a mask, styles, or (without `groups`) a blend mode or anything else
        that depends on its being drawn on its own becomes one picture; a clipped layer keeps its flag when the
        format has one (`clipping`), and otherwise is cut to shape with the layer under it."""
        import huginn_easel_more as more
        self.export_note = ""
        baked = set()

        def entry(head: dict, image: QImage, clip: bool = False, **over) -> dict:
            e = {"name": head["name"], "image": image, "opacity": head["opacity"], "blend": head["blend"], "visible": head["visible"],
                 "clip": clip, "lockAlpha": bool(head.get("lockAlpha")) and head["kind"] == "pixel"}
            e.update(over)
            return e

        def deep(items: list, test) -> bool:
            return any(deep(it[2], test) or test(it[1]) if isinstance(it, tuple) else test(it) for it in items)

        def walk(items: list) -> list:
            out, k = [], 0
            while k < len(items):
                it = items[k]
                head = it[1] if isinstance(it, tuple) else it
                if head["kind"] == "adjust":
                    if head["visible"]:                            # all it changes, and it, as one picture
                        baked.add("adjustment layers (with what's under them)")
                        out = [e for e in out if not e.get("visible", True)] + \
                              [{"name": head["name"], "image": self._stack(items[:k + 1]), "opacity": 1.0, "blend": "normal", "visible": True, "clip": False, "lockAlpha": False}]
                    k += 1
                    continue
                n = k + 1
                while n < len(items) and not isinstance(items[n], tuple) and items[n].get("clip"):
                    n += 1
                clipped = items[k + 1:n]
                if clipped and (not clipping or any(c["kind"] == "adjust" for c in clipped)):
                    if any(c["visible"] for c in clipped):
                        baked.add("clipped layers")
                    out.append(entry(head, self._clipped_image(it, clipped)))
                    k = n
                    continue
                if isinstance(it, tuple):
                    inside = it[2]
                    shown = [x for x in more.flatten_tree(inside) if x["kind"] != "group" and x["visible"]]
                    one = more.has_fx(head) or (head.get("mask") is not None and head.get("maskOn", True))
                    if not groups:
                        one = one or head["blend"] != "normal" or bool(clipped) or (head["opacity"] < 1 and len(shown) > 1) \
                              or deep(inside, lambda x: x["visible"] and (x["kind"] == "adjust" or x["blend"] != "normal" and x["kind"] != "group"))
                    if one:
                        if head["visible"] and len(shown) > 1:
                            baked.add("some groups")
                        out.append(entry(head, self._item_image(it)[0]))
                    elif groups:
                        out.append({"name": head["name"], "opacity": head["opacity"], "blend": head["blend"], "visible": head["visible"], "stack": walk(inside)})
                    else:                                          # its layers, each carrying the group's opacity and whether it shows
                        for e in walk(inside):
                            e["opacity"], e["visible"] = e["opacity"] * head["opacity"], e["visible"] and head["visible"]
                            out.append(e)
                else:
                    out.append(entry(head, self.styled_image(it)))
                for c in clipped:
                    out.append(entry(c, self.styled_image(c), clip=True))
                k = n
            return out
        got = walk(more.tree(self.layers))
        if baked:
            self.export_note = "To look the same there, " + ", ".join(sorted(baked)) + (" were" if len(baked) > 1 or not sorted(baked)[0].startswith("some") or True else " was") + " merged in the file."
        return got

    def _stack(self, items: list, live=None) -> QImage:
        """A list of layers and groups put together, bottom up. A layer marked "clip" shows only where the layer (or
        group) under it has something: the two (and any more clipped layers above) are put together first, keeping
        the lower one's shape, and then go onto the picture with the lower one's opacity and blend."""
        out = new_image(*self.small_size(self._mip)) if self._mip else new_image(self.w, self.h) if self._win is None else new_image(self._win.width(), self._win.height())
        k = 0
        while k < len(items):
            base = items[k]
            head = base[1] if isinstance(base, tuple) else base
            n = k + 1
            while n < len(items) and not isinstance(items[n], tuple) and items[n].get("clip"):
                n += 1
            clipped = items[k + 1:n]
            if not clipped or head["kind"] == "adjust" or (head.get("clip") and not isinstance(base, tuple) and k == 0):
                run = []                                           # plain adjustments straight over one another are worked as one
                while k + len(run) < len(items) and self._plain_adjust(items[k + len(run)]):
                    run.append(items[k + len(run)])
                if len(run) > 1:
                    done = apply_adjust_run(out, [(l["adjust"], l.get("params") or {}) for l in run])
                    p = QPainter(out)
                    p.setCompositionMode(CM.CompositionMode_Source)
                    p.drawImage(0, 0, done)
                    p.end()
                    k += len(run)
                    continue
                self._lay(out, base, live)                         # nothing clipped to it (or nothing it could be clipped to)
                k += 1
                continue
            if head["visible"]:                                    # (hidden: what's clipped to it has nothing to show in)
                blend_onto(out, self._clipped_image(base, clipped, live), head["blend"], head["opacity"])
            k = n
        return out

    def flattened(self, background=None) -> QImage:
        out = self.composite()
        if background:
            under = new_image(self.w, self.h, background)
            p = QPainter(under)
            p.drawImage(0, 0, out)
            p.end()
            return under
        return out

    # -------------------------------------------------------------- the whole document as data (for undo)
    def snapshot(self) -> dict:
        return {"w": self.w, "h": self.h, "layers": [copy_layer(l) for l in self.layers], "active": self.active,
                "selection": QImage(self.selection) if self.selection is not None else None, "guides": [dict(g) for g in self.guides]}

    def restore(self, snap: dict) -> None:
        self.w, self.h = snap["w"], snap["h"]
        self.layers = [copy_layer(l) for l in snap["layers"]]
        for l in self.layers:
            if l["kind"] != "pixel":                                 # shapes and smart objects are drawn afresh (cheap, and their
                l["v"] = next_v()                                    # insides are changed in place); a pixel layer comes back with the
                                                                     # version it had, so what was kept for that picture is still good
        self.active = snap["active"] if any(l["id"] == snap["active"] for l in self.layers) else self.layers[-1]["id"]
        self.selection = QImage(snap["selection"]) if snap["selection"] is not None else None
        self.guides = [dict(g) for g in snap.get("guides", self.guides)]
        self.touch()

    # -------------------------------------------------------------- the selection
    def selection_alpha(self) -> np.ndarray:
        if self.selection is None:
            return np.full((self.h, self.w), 255, np.uint8)
        return alpha_of(self.selection)

    def selection_box(self) -> QRect:
        if self.selection is None:
            return QRect(0, 0, self.w, self.h)
        a = alpha_of(self.selection)
        ys, xs = np.nonzero(a > 8)
        if not len(xs):
            return QRect()
        return QRect(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))

    def selection_path(self) -> QPainterPath:
        """The outline of the selection, for the marching ants."""
        if self.selection is None:
            return QPainterPath()
        a = alpha_of(self.selection) > 127
        if not a.any():
            return QPainterPath()
        packed = np.packbits(a, axis=1, bitorder="little")
        bpl = packed.shape[1]
        stride = (bpl + 3) // 4 * 4
        buf = np.zeros((self.h, stride), np.uint8)
        buf[:, :bpl] = packed
        mono = QImage(buf.tobytes(), self.w, self.h, stride, QImage.Format.Format_MonoLSB)
        mono.setColorTable([0xFFFFFFFF, 0xFF000000])                 # a bitmap's "set" bits are its dark ones: the selected pixels
        region = QRegion(QBitmap.fromImage(mono.copy()))              # (the other way round this was the part NOT selected: the outline
                                                                      #  also ran round the canvas, and Select All had none at all)
        if cv2 is None or region.rectCount() <= 2500:                # a plain shape: its exact outline, along the pixels' edges
            path = QPainterPath()
            path.addRegion(region)
            return path.simplified()
        # A ragged selection (the magic wand on a photograph is thousands of specks): joining its rows up exactly took
        # 13 seconds for a 12-megapixel picture, and minutes for worse. Its edges are traced instead, on a grid twice
        # as fine so one-pixel specks and gaps keep their shape; the line runs a quarter of a pixel inside the edge.
        k = 2 if self.w * self.h <= 30_000_000 else 1
        grid = np.zeros((self.h * k + 2, self.w * k + 2), np.uint8)
        grid[1:-1, 1:-1] = np.repeat(np.repeat(a, k, axis=0), k, axis=1) if k > 1 else a
        found, _ = cv2.findContours(grid, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        if len(found) > 30_000:
            # specks by the hundred thousand (a colour range over film grain): an outline round every one took many
            # seconds to make and as long to draw, and showed nothing but a shimmer. The specks are joined into the
            # patches they make up and those are outlined; what's selected is untouched, only the line round it is rougher.
            rough = cv2.morphologyEx(cv2.morphologyEx(a.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
            k = 1
            grid = np.zeros((self.h + 2, self.w + 2), np.uint8)
            grid[1:-1, 1:-1] = rough
            found, _ = cv2.findContours(grid, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            if len(found) > 30_000:
                found = sorted(found, key=len, reverse=True)[:30_000]
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        for c in found:
            pts = (c[:, 0, :].astype(np.float64) - 0.5) / k
            if len(pts) < 2:
                continue
            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in pts.tolist()]))
            path.closeSubpath()
        return path

    # -------------------------------------------------------------- reading and writing
    def manifest(self) -> dict:
        out = {"format": "huginn-easel", "version": 1, "w": self.w, "h": self.h, "dpi": self.dpi, "active": self.active, "layers": [],
               "guides": self.guides}
        for l in self.layers:
            entry = {k: l[k] for k in ("id", "name", "kind", "visible", "locked", "opacity", "blend", "maskOn")}
            for k in ("group", "open", "fx", "place", "sfilters"):
                if l.get(k) is not None:
                    entry[k] = l[k]
            for k in ("clip", "lockAlpha"):                         # (only written when on: older Easels read the file as before)
                if l.get(k):
                    entry[k] = True
            if l["kind"] == "vector":
                entry["shapes"] = l["shapes"]
            if l["kind"] == "adjust":
                entry["adjust"], entry["params"] = l["adjust"], l.get("params") or {}
            entry["hasMask"] = l.get("mask") is not None
            out["layers"].append(entry)
        return out

    def save_easel(self, path: str) -> None:
        part = path + ".saving"
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("mimetype", "application/x-huginn-easel", compress_type=zipfile.ZIP_STORED)
            z.writestr("manifest.json", json.dumps(self.manifest(), indent=1))
            todo = []
            for l in self.layers:
                if l["kind"] == "pixel":
                    todo.append((f"layers/{l['id']}.png", l["image"]))
                if l["kind"] == "smart":
                    todo.append((f"smart/{l['id']}.png", l["source"]))
                if l.get("mask") is not None:
                    todo.append((f"masks/{l['id']}.png", l["mask"]))
            for (name, _), data in zip(todo, pool().map(lambda t: png_bytes(t[1], True), todo)):     # each layer packed on its own core
                z.writestr(name, data, compress_type=zipfile.ZIP_STORED)
            thumb = self.flattened().scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            z.writestr("Thumbnails/thumbnail.png", png_bytes(thumb), compress_type=zipfile.ZIP_STORED)
        os.replace(part, path)
        self.path = path

    @classmethod
    def load_easel(cls, path: str) -> "Document":
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read("manifest.json"))
            if m.get("format") != "huginn-easel":
                raise ValueError("That isn't an Easel picture.")
            if not isinstance(m, dict) or not isinstance(m.get("layers"), list):
                raise ValueError("That isn't an Easel picture.")
            w, h = checked_size(m.get("w"), m.get("h"), sum(1 for e in m["layers"] if isinstance(e, dict) and e.get("kind") == "pixel") + 1)
            if sum(i.file_size for i in z.infolist()) > 4 << 30:
                raise ValueError("That file unpacks to more than Easel can open.")
            m["layers"] = [e for e in m["layers"] if isinstance(e, dict) and e.get("kind") in KINDS and isinstance(e.get("id"), str)][:2000]
            doc = cls(w, h, None)
            doc.layers, doc.dpi = [], m.get("dpi", 72)
            names = set(z.namelist())
            for e in m["layers"]:
                layer = new_layer(e["kind"], e.get("name", "Layer"), doc.w, doc.h)
                layer.update({k: e[k] for k in ("id", "visible", "locked", "opacity", "blend", "maskOn", "group", "open", "fx", "place", "sfilters") if k in e})
                for k in ("clip", "lockAlpha"):
                    if e.get(k) is True:
                        layer[k] = True
                if e["kind"] == "smart":
                    layer["source"] = image_from_bytes(z.read(f"smart/{e['id']}.png")) if f"smart/{e['id']}.png" in names else new_image(1, 1)
                    layer.setdefault("place", {"cx": 0.5, "cy": 0.5, "sx": 1, "sy": 1, "rot": 0})
                if e["kind"] == "pixel" and f"layers/{e['id']}.png" in names:
                    img = image_from_bytes(z.read(f"layers/{e['id']}.png"))
                    layer["image"] = img if img.size() == QSize(doc.w, doc.h) else _fit(img, doc.w, doc.h)
                if e["kind"] == "vector":
                    layer["shapes"] = e.get("shapes", [])
                if e["kind"] == "adjust":
                    layer["adjust"], layer["params"] = e.get("adjust", "light"), e.get("params", {})
                if e.get("hasMask") and f"masks/{e['id']}.png" in names:
                    layer["mask"] = image_from_bytes(z.read(f"masks/{e['id']}.png"))
                doc.layers.append(layer)
            if not doc.layers:
                doc.layers.append(new_layer("pixel", "Layer 1", doc.w, doc.h))
            doc.active = m.get("active") if any(l["id"] == m.get("active") for l in doc.layers) else doc.layers[-1]["id"]
            doc.guides = [g for g in (m.get("guides") if isinstance(m.get("guides"), list) else []) if isinstance(g, dict) and g.get("axis") in ("x", "y")]
            import huginn_easel_more as more
            doc.layers = more.normalize(doc.layers)
        doc.path = path
        return doc

    def save_ora(self, path: str) -> None:
        """OpenRaster: vector layers go in as pictures (other programs can't edit Easel's shapes)."""
        part = path + ".saving"
        stack = ET.Element("image", {"w": str(self.w), "h": str(self.h), "version": "0.0.5"})
        top = ET.SubElement(stack, "stack")
        import huginn_easel_more as more
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("mimetype", "image/openraster", compress_type=zipfile.ZIP_STORED)
            count = [0]

            def put(entries, parent):                               # OpenRaster lists the top layer first; a group is a stack
                for e in reversed(entries):
                    if "stack" in e:
                        sub = ET.SubElement(parent, "stack", {"name": e["name"], "opacity": f"{e['opacity']:.3f}",
                                                              "visibility": "visible" if e["visible"] else "hidden",
                                                              "composite-op": ORA_OPS.get(e["blend"], "svg:src-over"), "isolation": "isolate"})
                        put(e["stack"], sub)
                        continue
                    name = f"data/layer{count[0]}.png"
                    count[0] += 1
                    z.writestr(name, png_bytes(e["image"], True), compress_type=zipfile.ZIP_STORED)
                    ET.SubElement(parent, "layer", {"name": e["name"], "src": name, "x": "0", "y": "0", "opacity": f"{e['opacity']:.3f}",
                                                    "visibility": "visible" if e["visible"] else "hidden", "composite-op": ORA_OPS.get(e["blend"], "svg:src-over")})
            put(self.export_layers(groups=True, clipping=False), top)
            z.writestr("stack.xml", ET.tostring(stack, encoding="unicode"))
            flat = self.flattened()
            z.writestr("mergedimage.png", png_bytes(flat), compress_type=zipfile.ZIP_STORED)
            z.writestr("Thumbnails/thumbnail.png", png_bytes(flat.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)),
                       compress_type=zipfile.ZIP_STORED)
        os.replace(part, path)

    @classmethod
    def load_ora(cls, path: str) -> "Document":
        ops = {v: k for k, v in ORA_OPS.items()}
        with zipfile.ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist()) > 4 << 30:
                raise ValueError("That file unpacks to more than Easel can open.")
            root = ET.fromstring(z.read("stack.xml"))
            w, h = checked_size(root.get("w"), root.get("h"), sum(1 for _ in root.iter("layer")) + 1)
            doc = cls(w, h, None)
            doc.layers = []

            def walk(stack, hidden=False, group=None):
                for el in stack:
                    if el.tag == "stack":
                        g = new_layer("group", el.get("name", "Group"))
                        g.update(opacity=_number(el.get("opacity", 1), 0.0, 1.0, 1.0), visible=el.get("visibility", "visible") != "hidden",
                                 blend=ops.get(el.get("composite-op", "svg:src-over"), "normal"), group=group)
                        doc.layers.insert(0, g)
                        walk(el, False, g["id"])
                    elif el.tag == "layer" and el.get("src", "").lower().endswith(".png"):
                        img = image_from_bytes(z.read(el.get("src")))
                        layer = new_layer("pixel", el.get("name", "Layer"), w, h)
                        p = QPainter(layer["image"])
                        p.drawImage(int(_number(el.get("x", 0), -1e6, 1e6, 0)), int(_number(el.get("y", 0), -1e6, 1e6, 0)), img)
                        p.end()
                        layer["opacity"] = _number(el.get("opacity", 1), 0.0, 1.0, 1.0)
                        layer["visible"] = el.get("visibility", "visible") != "hidden" and not hidden
                        layer["blend"] = ops.get(el.get("composite-op", "svg:src-over"), "normal")
                        layer["group"] = group
                        doc.layers.insert(0, layer)
            walk(root.find("stack") if root.find("stack") is not None else root)
            import huginn_easel_more as more
            doc.layers = more.normalize(doc.layers)
        if not doc.layers:
            doc.layers.append(new_layer("pixel", "Layer 1", w, h))
        doc.active = doc.layers[-1]["id"]
        return doc

    @classmethod
    def from_picture(cls, path: str) -> "Document":
        if path.lower().endswith(".svg"):
            from PySide6.QtSvg import QSvgRenderer
            r = QSvgRenderer(path)
            if not r.isValid():
                raise ValueError("That SVG couldn't be read.")
            size = r.defaultSize()
            w, h = max(1, size.width()), max(1, size.height())
            if max(w, h) < 1024:                                     # draw small drawings bigger, so they stay sharp
                k = 2048 / max(w, h)
                w, h = max(1, int(w * k)), max(1, int(h * k))
            if max(w, h) > SIDE_LIMIT:                               # and enormous ones smaller: a drawing has no pixels to lose
                k = SIDE_LIMIT / max(w, h)
                w, h = max(1, int(w * k)), max(1, int(h * k))
            doc = cls(w, h, None)
            p = QPainter(doc.layers[0]["image"])
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r.render(p, QRectF(0, 0, w, h))
            p.end()
            doc.layers[0]["name"] = Path(path).stem
            return doc
        from PySide6.QtGui import QImageReader
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        if reader.size().isValid():                                  # (said before it's read, when the file says its size)
            checked_size(reader.size().width(), reader.size().height())
        img = reader.read()
        if img.isNull():
            raise ValueError(reader.errorString() or "That picture couldn't be read.")
        img = img.convertToFormat(FMT)
        doc = cls(img.width(), img.height(), None)
        doc.layers[0]["image"] = img
        doc.layers[0]["name"] = "Background"
        try:
            doc.dpi = round(img.dotsPerMeterX() * 0.0254) or 72
        except Exception:                                            # noqa: BLE001
            pass
        return doc

    def export(self, path: str, quality: int = 92, background: str = "") -> None:
        ext = Path(path).suffix.lower()
        if ext == ".svg":
            self.export_svg(path)
            return
        if ext == ".psd":
            write_psd(self, path)
            return
        if ext == ".pdf":
            self.export_pdf(path)
            return
        img = self.flattened(background or ("#FFFFFF" if ext in (".jpg", ".jpeg", ".bmp") else None))
        if ext in (".jpg", ".jpeg"):
            img = img.convertToFormat(QImage.Format.Format_RGB32)
        part = str(Path(path).with_name(f".{Path(path).name}.saving{ext}"))
        if not img.save(part, None, quality):
            raise OSError(f"Couldn't write {Path(path).name}.")
        os.replace(part, path)

    def _paint_vectors(self, p: QPainter) -> None:
        """For SVG and PDF: shapes as shapes and pictures as pictures, wherever that gives the same picture. Those
        formats only know "this, over that", so everything up to the last layer that needs more than that (a blend
        mode, an adjustment, clipping, a group drawn on its own) goes in as one picture, and what's above it as before."""
        import huginn_easel_more as more
        items = more.tree(self.layers)

        def plain(it) -> bool:
            if isinstance(it, tuple):
                h, kids = it[1], [x for x in it[2] if (x[1] if isinstance(x, tuple) else x)["visible"]]
                return h["blend"] == "normal" and not more.has_fx(h) and not (h.get("mask") is not None and h.get("maskOn", True)) \
                    and (h["opacity"] >= 1 or len(kids) <= 1) and all(plain(x) for x in it[2])
            return it["kind"] != "adjust" and it["blend"] == "normal" and not it.get("clip")
        last = -1
        for k, it in enumerate(items):
            head = it[1] if isinstance(it, tuple) else it
            if head["visible"] and not plain(it):
                last = k
            if not isinstance(it, tuple) and it.get("clip") and it["visible"] and k > 0:
                last = max(last, k)                                # (and the layer it's clipped to is under it, so inside the picture)
        self.export_note = ""
        if last >= 0:
            p.drawImage(0, 0, self._stack(items[:last + 1]))
            under = more.flatten_tree(items[:last + 1])
            if any(l["kind"] == "vector" and l["visible"] and l.get("shapes") for l in under):
                self.export_note = "Shapes under a blend mode, an adjustment or a clipped layer went in as a picture, so the file looks the same."

        def draw(seq, opacity: float) -> None:
            for it in seq:
                if isinstance(it, tuple):
                    if it[1]["visible"]:
                        draw(it[2], opacity * it[1]["opacity"])
                    continue
                layer = it
                if not layer["visible"] or layer["kind"] == "adjust":
                    continue
                p.save()
                p.setOpacity(opacity * layer["opacity"])
                if layer["kind"] == "vector" and not more.has_fx(layer) and (layer.get("mask") is None or not layer.get("maskOn", True)):
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    for s in layer["shapes"]:
                        if not s.get("hidden"):
                            paint_shape(p, s)
                else:
                    p.drawImage(0, 0, self.styled_image(layer))
                p.restore()
        draw(items[last + 1:], 1.0)

    def export_svg(self, path: str) -> None:
        from PySide6.QtSvg import QSvgGenerator
        gen = QSvgGenerator()
        part = str(Path(path).with_name(f".{Path(path).name}.saving.svg"))
        gen.setFileName(part)
        gen.setSize(QSize(self.w, self.h))
        gen.setViewBox(QRect(0, 0, self.w, self.h))
        gen.setTitle(Path(path).stem)
        gen.setDescription("Made in Huginn Easel")
        p = QPainter(gen)
        self._paint_vectors(p)
        p.end()
        os.replace(part, path)

    def export_pdf(self, path: str) -> None:
        part = str(Path(path).with_name(f".{Path(path).name}.saving.pdf"))
        writer = QPdfWriter(part)
        writer.setResolution(72)
        writer.setPageSize(QPageSize(QSizeF(self.w, self.h), QPageSize.Unit.Point))
        from PySide6.QtGui import QPageLayout
        from PySide6.QtCore import QMarginsF
        writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
        writer.setCreator("Huginn Easel")
        p = QPainter(writer)
        self._paint_vectors(p)
        p.end()
        os.replace(part, path)


def _fit(img: QImage, w: int, h: int) -> QImage:
    out = new_image(w, h)
    p = QPainter(out)
    p.drawImage(0, 0, img)
    p.end()
    return out


def open_any(path: str) -> Document:
    """Open any file Easel reads. Whatever is wrong with the file, the answer is a sound picture or a ValueError (or
    OSError) that says why not: a damaged or hostile file must never get further than this."""
    import stat as _stat
    st = os.stat(path)
    if not _stat.S_ISREG(st.st_mode):
        raise ValueError("That isn't a file Easel can open.")
    if st.st_size > 2 << 30:
        raise ValueError("That file is over 2 GB: too big for Easel to open.")
    low = path.lower()
    try:
        if low.endswith(".psd"):
            doc = read_psd(path)
            doc.path = ""
        elif low.endswith(".easel"):
            doc = Document.load_easel(path)
        elif low.endswith(".ora"):
            doc = Document.load_ora(path)
            doc.path = ""
        else:
            doc = Document.from_picture(path)
            doc.path = ""
        return doc.tidy()
    except (ValueError, OSError):
        raise
    except MemoryError:
        raise ValueError("There isn't enough memory to open that picture.") from None
    except Exception as err:                                   # noqa: BLE001  (a damaged file can fail in any way at all)
        raise ValueError("The file is damaged or isn't what its name says.") from err


# ------------------------------------------------------------------------------------------- brushes
BRUSHES = {"round": {"name": "Round", "size": 24, "hardness": 0.8, "flow": 1.0, "spacing": 0.12, "scatter": 0.0},
           "soft": {"name": "Soft", "size": 60, "hardness": 0.0, "flow": 0.6, "spacing": 0.1, "scatter": 0.0},
           "pencil": {"name": "Pencil", "size": 3, "hardness": 1.0, "flow": 1.0, "spacing": 0.05, "scatter": 0.0},
           "ink": {"name": "Ink", "size": 8, "hardness": 0.95, "flow": 1.0, "spacing": 0.06, "scatter": 0.0},
           "airbrush": {"name": "Airbrush", "size": 120, "hardness": 0.0, "flow": 0.08, "spacing": 0.06, "scatter": 0.0},
           "chalk": {"name": "Chalk", "size": 30, "hardness": 0.6, "flow": 0.5, "spacing": 0.2, "scatter": 0.35},
           "marker": {"name": "Marker", "size": 40, "hardness": 0.9, "flow": 0.35, "spacing": 0.05, "scatter": 0.0},
           # brushes whose mark is a picture, not a disc (TIPS), and that change as they go: "follow" turns the tip
           # along the stroke, "angle" fixes it (a pen held one way), and the jitters vary each dab's size, turn and strength
           "bristle": {"name": "Dry Bristle", "size": 46, "hardness": 0.9, "flow": 0.7, "spacing": 0.07, "scatter": 0.0, "tip": "bristle", "follow": True},
           "charcoal": {"name": "Charcoal", "size": 34, "hardness": 0.5, "flow": 0.45, "spacing": 0.12, "scatter": 0.06, "tip": "grain", "turn": 1.0, "vary": 0.15},
           "calligraphy": {"name": "Calligraphy Pen", "size": 30, "hardness": 1.0, "flow": 1.0, "spacing": 0.03, "scatter": 0.0, "tip": "flat", "angle": 40.0},
           "ribbon": {"name": "Ribbon", "size": 36, "hardness": 1.0, "flow": 1.0, "spacing": 0.03, "scatter": 0.0, "tip": "flat", "follow": True},
           "spray": {"name": "Spray Can", "size": 110, "hardness": 0.0, "flow": 0.5, "spacing": 0.1, "scatter": 0.05, "tip": "spray", "turn": 1.0},
           "splatter": {"name": "Splatter", "size": 90, "hardness": 1.0, "flow": 0.9, "spacing": 0.55, "scatter": 0.5, "tip": "splatter", "turn": 1.0, "vary": 0.5, "fade": 0.4},
           "leaves": {"name": "Leaves", "size": 44, "hardness": 1.0, "flow": 1.0, "spacing": 0.8, "scatter": 0.7, "tip": "leaf", "turn": 1.0, "vary": 0.45, "fade": 0.3}}
TIPS = ("round", "bristle", "grain", "flat", "spray", "splatter", "leaf")


CUSTOM_TIPS = {}               # brushes made from your own pictures: name -> how solid each pixel is (0..1), up to 256 across


def tip_from_picture(rgba: np.ndarray) -> np.ndarray:
    """A brush tip from a piece of a picture: where it's solid and dark the brush paints, where it's light or
    see-through it doesn't (a black mark on white paper, or a cut-out on nothing, both work). Trimmed to the mark and
    fitted into a square of at most 256 pixels."""
    a = rgba.astype(np.float32) / 255.0
    lum = a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722
    solid = a[..., 3]
    ink = solid * (1.0 - lum) if (solid > 0.98).mean() > 0.9 else solid * np.maximum(1.0 - lum, 0.35)   # (a cut-out keeps its light parts, fainter)
    if ink.max() <= 0.02:
        raise ValueError("There's nothing dark or solid there to make a brush from.")
    ink = ink / ink.max()
    ys, xs = np.nonzero(ink > 0.04)
    ink = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    side = max(ink.shape)
    square = np.zeros((side, side), np.float32)
    y0, x0 = (side - ink.shape[0]) // 2, (side - ink.shape[1]) // 2
    square[y0:y0 + ink.shape[0], x0:x0 + ink.shape[1]] = ink
    if side > 256:
        from PIL import Image
        square = np.asarray(Image.fromarray((square * 255).astype(np.uint8)).resize((256, 256), Image.Resampling.LANCZOS)).astype(np.float32) / 255.0
    return square


def tip_alpha(tip: str, size: float, hardness: float) -> np.ndarray:
    """A brush tip's mark as how solid each pixel is (0..1), `size` pixels across. Made from numbers, the same every
    time for the same size, so a stroke looks the same when it's redrawn."""
    side = max(3, int(math.ceil(size)) + 2)
    if tip in CUSTOM_TIPS:                                         # your own mark, fitted to the brush's size
        from PIL import Image
        inner = max(1, side - 2)
        small = np.asarray(Image.fromarray((CUSTOM_TIPS[tip] * 255).astype(np.uint8)).resize((inner, inner), Image.Resampling.LANCZOS if inner < CUSTOM_TIPS[tip].shape[0] else Image.Resampling.BILINEAR))
        out = np.zeros((side, side), np.float32)
        out[1:1 + inner, 1:1 + inner] = small.astype(np.float32) / 255.0
        return out
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    c = (side - 1) / 2
    x, y = (xx - c) / max(1.0, size / 2), (yy - c) / max(1.0, size / 2)      # -1..1 across the tip
    r = np.sqrt(x * x + y * y)
    rng = np.random.default_rng(7 + {t: k for k, t in enumerate(TIPS)}.get(tip, 0))
    edge = lambda d, soft: np.clip((1 - d) / max(soft, 1.5 / max(2.0, size / 2)), 0, 1)
    if tip == "flat":                                              # a chisel: long one way, thin the other
        a = edge(np.maximum(np.abs(x), np.abs(y) / 0.16), 0.08)
    elif tip == "bristle":                                         # a row of hairs across the stroke, some missing
        hairs = rng.random(64) > 0.28
        strength = 0.55 + 0.45 * rng.random(64)
        k = np.clip(((y + 1) / 2 * 63).astype(np.int32), 0, 63)
        a = edge(np.maximum(np.abs(x) / 0.22, np.abs(y)), 0.1) * hairs[k] * strength[k]
    elif tip == "grain":                                           # a soft disc eaten into by paper grain
        grain = rng.random((side, side)).astype(np.float32)
        a = np.clip(edge(r, max(0.05, 1 - hardness)) * 1.6 - grain * 0.9, 0, 1)
    elif tip == "spray":                                           # fine dots, thick in the middle and thin at the edge
        a = (rng.random((side, side)) < np.exp(-(r * 2.2) ** 2) * 0.22).astype(np.float32) * (r < 1)
    elif tip == "splatter":                                        # a few blots of different sizes
        a = np.zeros((side, side), np.float32)
        for _ in range(9):
            bx, by, br = rng.uniform(-0.7, 0.7), rng.uniform(-0.7, 0.7), rng.uniform(0.05, 0.3) ** 1.0
            a = np.maximum(a, np.clip((br - np.sqrt((x - bx) ** 2 + (y - by) ** 2)) * max(2.0, size / 2), 0, 1))
    elif tip == "leaf":                                            # two arcs meeting in points, with a vein
        a = edge(np.abs(y) / np.maximum(0.02, 0.42 * (1 - x * x)), 0.12) * (np.abs(x) < 1)
        a = a * (1 - 0.55 * np.clip(1 - np.abs(y) * max(3.0, size / 3), 0, 1))
    else:
        a = edge(r, max(0.0, 1 - hardness)) if hardness < 0.98 else np.clip((1 - r) * max(1.0, size / 2), 0, 1)
    return np.clip(a, 0, 1).astype(np.float32)


def tip_image(tip: str, size: float, hardness: float, colour_: QColor) -> QImage:
    a = tip_alpha(tip, size, hardness)
    out = np.empty(a.shape + (4,), np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = colour_.red(), colour_.green(), colour_.blue()
    out[..., 3] = (a * colour_.alpha() + 0.5).astype(np.uint8)
    return array_to_image(out)


# gradients with more than two colours: (place along the line, colour). "fgbg" and "fgclear" use the colours in hand.
GRADIENTS = {"fgbg": ("Front to Back Colour", None), "fgclear": ("Front Colour to Clear", None),
             "sunset": ("Sunset", [(0, "#1B1464"), (0.35, "#8E2A8B"), (0.62, "#E8505B"), (0.82, "#F9A03F"), (1, "#FFE9A8")]),
             "sky": ("Sky", [(0, "#0B3C7D"), (0.5, "#3F8FE0"), (0.85, "#BFE1FF"), (1, "#FFFFFF")]),
             "fire": ("Fire", [(0, "#000000"), (0.3, "#7A0A00"), (0.55, "#E8450A"), (0.8, "#FFC21A"), (1, "#FFFFE0")]),
             "chrome": ("Chrome", [(0, "#F4F7FA"), (0.42, "#8D99A6"), (0.5, "#2B3138"), (0.58, "#B9C3CC"), (1, "#FFFFFF")]),
             "gold": ("Gold", [(0, "#5B3A00"), (0.3, "#D9A521"), (0.5, "#FFF3B0"), (0.7, "#D9A521"), (1, "#6B4500")]),
             "spectrum": ("Spectrum", [(0, "#FF0000"), (0.17, "#FFFF00"), (0.33, "#00FF00"), (0.5, "#00FFFF"), (0.67, "#0000FF"), (0.83, "#FF00FF"), (1, "#FF0000")]),
             "aurora": ("Aurora", [(0, "#05101F"), (0.4, "#0E6B5C"), (0.65, "#3DDC97"), (0.85, "#9B5DE5"), (1, "#0B1026")])}


_NOISE = None


def _noise(h: int, w: int, y0: int = 0) -> np.ndarray:
    """The same fine grain every time (0..1, a 256-pixel tile repeated): what's added before rounding so that a slow
    change of tone comes out as a mix of two neighbouring levels instead of a visible step."""
    global _NOISE
    if _NOISE is None:
        r = np.random.default_rng(20261122)
        _NOISE = r.random((256, 256), dtype=np.float32)            # (evenly spread: only then is the average of the mix the true tone)
    ys = (np.arange(y0, y0 + h) % 256)[:, None]
    xs = (np.arange(w) % 256)[None, :]
    return _NOISE[ys, xs]


def gradient_stops(stops: list) -> list:
    """Stops as [(place 0..1, QColor)], in order, with one at each end. Raises ValueError when they make no sense."""
    out = []
    for st in stops or []:
        try:
            at, c = float(st[0]), QColor(st[1])
        except (TypeError, ValueError, IndexError):
            raise ValueError("a gradient stop is a place and a colour")
        if not (at == at) or not c.isValid():
            raise ValueError("a gradient stop is a place and a colour")
        out.append((max(0.0, min(1.0, at)), c))
    if len(out) < 2:
        raise ValueError("a gradient needs two colours at least")
    out.sort(key=lambda st: st[0])
    out = out[:32]
    if out[0][0] > 0:
        out.insert(0, (0.0, out[0][1]))
    if out[-1][0] < 1:
        out.append((1.0, out[-1][1]))
    return out


def gradient_image(w: int, h: int, kind: str, a: QPointF, b: QPointF, stops: list, smooth: bool = True) -> QImage:
    """A gradient over the whole picture from a to b (straight, or round about a), through `stops` [(place, QColor)].
    Worked in fine numbers and rounded with a little grain, so a long gentle gradient has no visible steps in it (the
    plain way gives bands a few pixels to a few dozen pixels wide wherever the colours are close). Where the colour
    isn't changing it comes out exactly that colour."""
    stops = gradient_stops(stops)
    n = 8192
    at = np.array([s_[0] for s_ in stops], np.float64)
    at = at + np.arange(len(at)) * 1e-9                            # (two stops at one place: a hard edge, in the order given)
    cols = np.array([[c.red(), c.green(), c.blue(), c.alpha()] for _, c in stops], np.float64)
    ramp = np.linspace(0.0, 1.0, n)
    lut = np.stack([np.interp(ramp, at, cols[:, c]) for c in range(4)], axis=1).astype(np.float32)
    ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
    dx, dy = bx - ax, by - ay
    length2 = max(1e-6, dx * dx + dy * dy)
    xs = (np.arange(w, dtype=np.float32) + 0.5 - ax)[None, :]

    def band(rows: slice) -> np.ndarray:
        ys = (np.arange(rows.start, rows.stop, dtype=np.float32) + 0.5 - ay)[:, None]
        if kind == "radial":
            t = np.sqrt(xs * xs + ys * ys) / math.sqrt(length2)
        else:
            t = (xs * dx + ys * dy) / length2
        v = lut[(np.clip(t, 0.0, 1.0) * (n - 1) + 0.5).astype(np.int32)]     # (8192 places along the line: far finer than a level)
        if smooth:
            # (the grain runs from just over 0 to just under 1, and the number is then cut to a whole level: a
            # colour that isn't changing stays exactly itself, and one between two levels becomes a mix of the two)
            return np.clip(v + _noise(rows.stop - rows.start, w, rows.start)[..., None] * 0.996 + 0.002, 0, 255).astype(np.uint8)
        return np.clip(v + 0.5, 0, 255).astype(np.uint8)
    step = max(16, min(128, 300_000 // max(1, w)))
    rows = [slice(y, min(h, y + step)) for y in range(0, h, step)]
    out = np.concatenate([band(r) for r in rows] if w * h < 400_000 else list(pool().map(band, rows)))
    return array_to_image(out)


RANGES = {"colour": "The front colour", "highlights": "Highlights", "midtones": "Midtones", "shadows": "Shadows",
          "reds": "Reds", "yellows": "Yellows", "greens": "Greens", "cyans": "Cyans", "blues": "Blues", "magentas": "Magentas"}
_HUES = {"reds": 0, "yellows": 60, "greens": 120, "cyans": 180, "blues": 240, "magentas": 300}


def colour_range(rgba: np.ndarray, kind: str, colour_: str, fuzz: float) -> np.ndarray:
    """Select › Colour Range: how much each pixel belongs (0..255) to a colour, a band of tones or a family of hues.
    `fuzz` 0..1 is how far from the middle of the range still counts; belonging falls away smoothly, so the selection
    has a soft edge where the picture has a soft change."""
    fuzz = max(0.01, min(1.0, float(fuzz)))
    rgb = rgba[..., :3].astype(np.float32)
    if kind == "colour":
        c = QColor(colour_)
        ref = np.array([c.red(), c.green(), c.blue()], np.float32)
        # (the eye's rough weighting: a step in green shows more than the same step in blue)
        d = np.sqrt((((rgb - ref) * np.array([0.55, 0.75, 0.38], np.float32)) ** 2).sum(axis=2)) / 255.0
        reach = 0.04 + fuzz * 0.6
        m = 1.0 - np.clip((d - reach * 0.5) / (reach * 0.5), 0, 1)
    elif kind in ("highlights", "midtones", "shadows"):
        lum = (rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)) / 255.0
        mid = {"highlights": 1.0, "midtones": 0.5, "shadows": 0.0}[kind]
        reach = 0.1 + fuzz * 0.45
        m = 1.0 - np.clip((np.abs(lum - mid) - reach * 0.6) / (reach * 0.4), 0, 1)
    elif kind in _HUES:
        mx, mn = rgb.max(axis=2), rgb.min(axis=2)
        span = mx - mn
        safe = np.where(span > 0, span, 1)
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        hue = np.where(mx == r, ((g - b) / safe) % 6, np.where(mx == g, (b - r) / safe + 2, (r - g) / safe + 4)) * 60.0
        away = np.abs((hue - _HUES[kind] + 180) % 360 - 180)
        reach = 12 + fuzz * 48
        m = 1.0 - np.clip((away - reach * 0.6) / (reach * 0.4), 0, 1)
        m = m * np.clip((span / 255.0 - 0.06) / 0.14, 0, 1)        # (greys have no hue to speak of)
    else:
        raise ValueError("no such range")
    m = m * (rgba[..., 3].astype(np.float32) / 255.0)
    return (m * 255 + 0.5).astype(np.uint8)


def dab(size: float, hardness: float, colour_: QColor) -> QImage:
    """One stamp of the brush: a disc, soft at the edge by (1 - hardness)."""
    side = max(1, int(math.ceil(size)) + 2)
    img = new_image(side, side)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(colour_)
    r = size / 2
    if hardness >= 0.98 or size <= 2:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(side / 2, side / 2), r, r)
    else:
        g = QRadialGradient(QPointF(side / 2, side / 2), r)
        g.setColorAt(0, c)
        g.setColorAt(max(0.0, min(0.99, hardness)), c)
        edge = QColor(c)
        edge.setAlpha(0)
        g.setColorAt(1, edge)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(side / 2, side / 2), r, r)
    p.end()
    return img


# ------------------------------------------------------------------------------------------- healing
def heal_patch(dst: np.ndarray, src: np.ndarray, radius: float) -> np.ndarray:
    """Healing: the source's texture with the destination's colour and light. Both are float RGB(A) arrays of the
    same size; the detail is what's left after blurring, so it carries over and the tone underneath does not."""
    r = max(1, int(round(radius)))

    def box(a, axis):
        """A running mean along one axis (edges repeat), done with cumulative sums so it costs the same at any size."""
        pad = [(0, 0)] * a.ndim
        pad[axis] = (r + 1, r)
        c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
        hi = np.take(c, np.arange(2 * r + 1, c.shape[axis]), axis=axis)
        lo = np.take(c, np.arange(0, c.shape[axis] - 2 * r - 1), axis=axis)
        return ((hi - lo) / (2 * r + 1)).astype(np.float32)

    def blur(a):                                                    # three box blurs are very nearly a Gaussian
        for _ in range(3):
            a = box(box(a, 0), 1)
        return a
    return np.clip(blur(dst) + (src - blur(src)), 0, 255)


def best_spot_source(rgba: np.ndarray, cx: float, cy: float, size: float) -> tuple:
    """For spot healing: the nearby patch, one or two brush widths away, that looks most like the area round the spot."""
    h, w = rgba.shape[:2]
    r = max(4, int(size * 0.75))
    ring = []
    for k in (1.6, 2.4):
        for i in range(8):
            a = i * math.pi / 4
            ring.append((cx + math.cos(a) * size * k, cy + math.sin(a) * size * k))
    x0, y0 = int(cx) - r, int(cy) - r

    def patch(x, y):
        xa, ya = int(x) - r, int(y) - r
        if xa < 0 or ya < 0 or xa + 2 * r >= w or ya + 2 * r >= h:
            return None
        return rgba[ya:ya + 2 * r, xa:xa + 2 * r, :3].astype(np.float32)
    here = patch(cx, cy)
    if here is None:
        return ring[0]
    yy, xx = np.mgrid[0:2 * r, 0:2 * r]
    edge = (np.hypot(xx - r, yy - r) > r * 0.7)[..., None]           # compare the edges: the middle is the blemish
    best, choice = None, ring[0]
    for x, y in ring:
        other = patch(x, y)
        if other is None:
            continue
        score = float((np.abs(other - here) * edge).mean() + other.std(axis=(0, 1)).mean() * 0.15)
        if best is None or score < best:
            best, choice = score, (x, y)
    del x0, y0
    return choice


# ------------------------------------------------------------------------------------------- Photoshop files
PSD_BLENDS = {"norm": "normal", "mul ": "multiply", "scrn": "screen", "over": "overlay", "dark": "darken", "lite": "lighten", "div ": "dodge",
              "idiv": "burn", "hLit": "hard", "sLit": "soft", "diff": "difference", "smud": "exclusion", "lddg": "add", "pass": "normal",
              "hue ": "hue", "sat ": "saturation", "colr": "color", "lum ": "luminosity"}
PSD_KEYS = {v: k for k, v in PSD_BLENDS.items() if k != "pass"}


def _unpack_rle(data: bytes, pos: int, rows: int, width: int) -> tuple:
    """PackBits rows as Photoshop writes them: a table of row lengths, then the rows."""
    counts = np.frombuffer(data, ">u2", rows, pos).astype(int)
    pos += rows * 2
    out = np.zeros((rows, width), np.uint8)
    for y, n in enumerate(counts):
        row, i, end, x = data, pos, pos + n, 0
        line = bytearray()
        while i < end and len(line) < width:
            b = row[i]
            i += 1
            if b < 128:
                line += row[i:i + b + 1]
                i += b + 1
            elif b > 128:
                line += bytes([row[i]]) * (257 - b)
                i += 1
        out[y, :min(width, len(line))] = np.frombuffer(bytes(line[:width]), np.uint8)
        pos = end
    del x
    return out, pos


def _channel(data: bytes, pos: int, length: int, rows: int, width: int) -> np.ndarray:
    comp = int.from_bytes(data[pos:pos + 2], "big")
    body = pos + 2
    if rows <= 0 or width <= 0:
        return np.zeros((max(rows, 0), max(width, 0)), np.uint8)
    if comp == 0:
        return np.frombuffer(data, np.uint8, rows * width, body).reshape(rows, width).copy()
    if comp == 1:
        return _unpack_rle(data, body, rows, width)[0]
    raise ValueError("This Photoshop file packs its pictures in a way Easel can't read yet (ZIP compression).")


def read_psd(path: str) -> "Document":
    """Layers from a Photoshop file: 8-bit RGB or greyscale, with names, opacity, blend modes and visibility. Groups
    come in as their layers, one after another; text and smart objects come in as the pictures Photoshop saved."""
    data = Path(path).read_bytes()
    if data[:4] != b"8BPS" or int.from_bytes(data[4:6], "big") != 1:
        raise ValueError("That isn't a Photoshop file Easel can read (big PSB files aren't supported yet).")
    channels = int.from_bytes(data[12:14], "big")
    h, w = int.from_bytes(data[14:18], "big"), int.from_bytes(data[18:22], "big")
    depth, mode = int.from_bytes(data[22:24], "big"), int.from_bytes(data[24:26], "big")
    if depth != 8 or mode not in (1, 3):
        raise ValueError("Easel reads 8-bit RGB and greyscale Photoshop files; this one is " + ({16: "16-bit", 32: "32-bit"}.get(depth, f"{depth}-bit")) + " or another colour mode.")
    w, h = checked_size(w, h)
    if not 1 <= channels <= 56:
        raise ValueError("That Photoshop file is damaged (it says it has no colour channels).")
    pos = 26
    pos += 4 + int.from_bytes(data[pos:pos + 4], "big")              # colour mode data
    pos += 4 + int.from_bytes(data[pos:pos + 4], "big")              # image resources
    lm_len = int.from_bytes(data[pos:pos + 4], "big")
    lm_end = pos + 4 + lm_len
    doc = Document(w, h, None)
    doc.layers = []
    if lm_len:
        li_len = int.from_bytes(data[pos + 4:pos + 8], "big")
        q = pos + 8
        if li_len:
            count = abs(int.from_bytes(data[q:q + 2], "big", signed=True))
            checked_size(w, h, count + 1)
            q += 2
            records = []
            for _ in range(count):
                top, left, bottom, right = (int.from_bytes(data[q + i * 4:q + i * 4 + 4], "big", signed=True) for i in range(4))
                q += 16
                nch = int.from_bytes(data[q:q + 2], "big")
                q += 2
                chans = []
                for _ in range(nch):
                    chans.append((int.from_bytes(data[q:q + 2], "big", signed=True), int.from_bytes(data[q + 2:q + 6], "big")))
                    q += 6
                key = data[q + 4:q + 8].decode("latin-1")
                opacity, flags = data[q + 8], data[q + 10]
                extra = int.from_bytes(data[q + 12:q + 16], "big")
                ex, ex_end = q + 16, q + 16 + extra
                ex += 4 + int.from_bytes(data[ex:ex + 4], "big")         # layer mask data
                ex += 4 + int.from_bytes(data[ex:ex + 4], "big")         # blending ranges
                n = data[ex]
                name = data[ex + 1:ex + 1 + n].decode("latin-1", "replace")
                ex += ((n + 1 + 3) // 4) * 4
                divider = 0
                while ex + 12 <= ex_end and data[ex:ex + 4] in (b"8BIM", b"8B64"):
                    k, ln = data[ex + 4:ex + 8], int.from_bytes(data[ex + 8:ex + 12], "big")
                    body = data[ex + 12:ex + 12 + ln]
                    if k == b"luni" and len(body) >= 4:
                        chars = int.from_bytes(body[:4], "big")
                        name = body[4:4 + chars * 2].decode("utf-16-be", "replace").rstrip("\x00")
                    elif k in (b"lsct", b"lsdk") and len(body) >= 4:
                        divider = int.from_bytes(body[:4], "big")
                    ex += 12 + ln + (ln % 2)
                records.append({"rect": (top, left, bottom, right), "chans": chans, "blend": PSD_BLENDS.get(key, "normal"), "opacity": opacity / 255,
                                "visible": not (flags & 2), "name": name or "Layer", "divider": divider,
                                "clip": data[q + 9] == 1, "lockAlpha": bool(flags & 1)})
                q = ex_end
            for rec in records:                                      # then each layer's pictures, channel by channel
                top, left, bottom, right = rec["rect"]
                rh, rw = bottom - top, right - left
                planes = {}
                for cid, length in rec["chans"]:
                    if cid in (0, 1, 2, -1) or (mode == 1 and cid == 0):
                        try:
                            planes[cid] = _channel(data, q, length, rh, rw) if cid != -2 else None
                        except ValueError:
                            raise
                    q += length
                if rec["divider"] in (1, 2, 3) or rh <= 0 or rw <= 0:
                    continue                                         # the start or end of a group, or an empty layer
                if mode == 1:
                    grey = planes.get(0, np.zeros((rh, rw), np.uint8))
                    rgba = np.dstack([grey, grey, grey, planes.get(-1, np.full((rh, rw), 255, np.uint8))])
                else:
                    rgba = np.dstack([planes.get(0, np.zeros((rh, rw), np.uint8)), planes.get(1, np.zeros((rh, rw), np.uint8)),
                                      planes.get(2, np.zeros((rh, rw), np.uint8)), planes.get(-1, np.full((rh, rw), 255, np.uint8))])
                layer = new_layer("pixel", rec["name"], w, h)
                p = QPainter(layer["image"])
                p.drawImage(left, top, array_to_image(rgba))
                p.end()
                layer.update(opacity=rec["opacity"], visible=rec["visible"], blend=rec["blend"])
                for key in ("clip", "lockAlpha"):
                    if rec.get(key):
                        layer[key] = True
                doc.layers.append(layer)
    if not doc.layers:                                               # no layers: the merged picture at the end of the file
        q = lm_end
        comp = int.from_bytes(data[q:q + 2], "big")
        q += 2
        planes = []
        if comp == 1:
            counts = np.frombuffer(data, ">u2", channels * h, q).astype(int)
            q += channels * h * 2
            for c in range(channels):
                plane = np.zeros((h, w), np.uint8)
                for y in range(h):
                    n = counts[c * h + y]
                    row = _unpack_rle(n.to_bytes(2, "big") + data[q:q + n], 0, 1, w)[0]
                    plane[y] = row[0]
                    q += n
                planes.append(plane)
        else:
            for c in range(channels):
                planes.append(np.frombuffer(data, np.uint8, w * h, q + c * w * h).reshape(h, w))
        if mode == 1:
            planes = [planes[0]] * 3 + planes[1:2]
        rgba = np.dstack(planes[:3] + [planes[3] if len(planes) > 3 else np.full((h, w), 255, np.uint8)])
        layer = new_layer("pixel", "Background", w, h)
        layer["image"] = array_to_image(rgba)
        doc.layers.append(layer)
    doc.active = doc.layers[-1]["id"]
    return doc


def write_psd(doc: "Document", path: str) -> None:
    """A Photoshop file with every pixel and vector layer as a layer (shapes and type become pictures, since only
    Photoshop's own text engine could keep them editable), plus the whole picture flattened for quick previews."""
    import struct
    out = bytearray(b"8BPS" + struct.pack(">H6xHIIHH", 1, 4, doc.h, doc.w, 8, 3))
    out += struct.pack(">I", 0)                                       # colour mode data
    res = b"8BIM" + struct.pack(">H", 1005) + b"\x00\x00" + struct.pack(">I", 16) + struct.pack(">IHHIHH", doc.dpi << 16, 1, 1, doc.dpi << 16, 1, 1)
    out += struct.pack(">I", len(res)) + res                          # the resolution, so print sizes come across
    import huginn_easel_more as more

    layers = doc.export_layers(groups=False, clipping=True)
    records, pictures = bytearray(), bytearray()
    for l in layers:
        rgba = image_to_array(l["image"])
        ys, xs = np.nonzero(rgba[..., 3])
        if len(xs):
            top, left, bottom, right = int(ys.min()), int(xs.min()), int(ys.max()) + 1, int(xs.max()) + 1
        else:
            top = left = bottom = right = 0
        part = rgba[top:bottom, left:right]
        chans = []
        for cid, plane in ((-1, 3), (0, 0), (1, 1), (2, 2)):
            raw = part[..., plane].tobytes() if part.size else b""
            chans.append((cid, b"\x00\x00" + raw))
        name = l["name"].encode("latin-1", "replace")[:255]
        pascal = bytes([len(name)]) + name
        pascal += b"\x00" * ((4 - len(pascal) % 4) % 4)
        uni = l["name"].encode("utf-16-be")
        luni_body = struct.pack(">I", len(l["name"])) + uni
        luni_body += b"\x00" * (len(luni_body) % 2)
        luni = b"8BIM" + b"luni" + struct.pack(">I", len(luni_body)) + luni_body
        extra = struct.pack(">I", 0) + struct.pack(">I", 0) + pascal + luni
        records += struct.pack(">iiiiH", top, left, bottom, right, len(chans))
        for cid, body in chans:
            records += struct.pack(">hI", cid, len(body))
        records += b"8BIM" + PSD_KEYS.get(l["blend"], "norm").encode("latin-1") + bytes([int(round(max(0.0, min(1.0, l["opacity"])) * 255)), 1 if l["clip"] else 0,
                                                                                            (0 if l["visible"] else 2) | (1 if l["lockAlpha"] else 0), 0])
        records += struct.pack(">I", len(extra)) + extra
        for _, body in chans:
            pictures += body
    info = struct.pack(">h", len(layers)) + records + pictures
    if len(info) % 2:
        info += b"\x00"
    layer_info = struct.pack(">I", len(info)) + info
    out += struct.pack(">I", len(layer_info) + 4) + layer_info + struct.pack(">I", 0)
    flat = image_to_array(doc.flattened())
    out += struct.pack(">H", 0)
    for c in (0, 1, 2, 3):
        out += flat[..., c].tobytes()
    part = path + ".saving"
    Path(part).write_bytes(bytes(out))
    os.replace(part, path)
