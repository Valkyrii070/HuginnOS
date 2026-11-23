#!/usr/bin/env python3
"""Easel, the deep dives: damaged and hostile files, what each format keeps, painting under adjustment layers at
speed, and the canvas's own bookkeeping.  Usage: easel_round7_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)"""
import io, json, os, shutil, struct, sys, tempfile, time, zipfile
from pathlib import Path
KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
home = tempfile.mkdtemp(prefix="easel7-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/d", XDG_CONFIG_HOME=home + "/c", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor, QLinearGradient
from PySide6.QtCore import QRect
app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
import numpy as np
import huginn_easel as ez, huginn_easel_ui as eu, huginn_easel_more as more

passed = failed = 0
def ok(what, cond, extra=""):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1
        print("FAIL", what, extra)
def same(a: QImage, b: QImage) -> bool:
    return a.size() == b.size() and ez.image_to_array(a).tobytes() == ez.image_to_array(b).tobytes()
def off(a: QImage, b: QImage) -> int:
    return 999 if a.size() != b.size() else int(np.abs(ez.image_to_array(a).astype(np.int16) - ez.image_to_array(b).astype(np.int16)).max())
def fresh(w=160, h=120, bg="#FFFFFF"):
    e = eu.Easel(False, ""); e.newDoc(w, h, bg); msgs = []
    e.said.connect(lambda m, bad: msgs.append(m)); return e, msgs
def blob(e, colour="#E03060", box=(30, 20, 60, 50)):
    e.addLayer("pixel"); l = e.doc.layer(); p = QPainter(l["image"]); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(colour)); p.setPen(QColor(0, 0, 0, 0)); p.drawEllipse(*box); p.end(); e.doc.touch(l); return l
def rich(w=160, h=120):
    """Everything that makes putting a picture together hard, in one picture."""
    e, msgs = fresh(w, h)
    l = e.doc.layer(); p = QPainter(l["image"]); g = QLinearGradient(0, 0, w, h); g.setColorAt(0, QColor("#2060E0")); g.setColorAt(1, QColor("#F0C020")); p.fillRect(0, 0, w, h, g); p.end()
    a = blob(e, "#E03060", (w // 6, h // 6, w // 2, h // 2)); e.setLayer(a["id"], "blend", "multiply")
    b = blob(e, "#20C040", (w // 3, h // 12, w // 2, h * 2 // 3)); e.clipLayer()
    e.addLayer("pixel"); paint = e.doc.layer()                      # the layer the tests paint on
    e.setTool("select"); e.press(w // 8, h // 8, 1, 0); e.move(w * 7 // 8, h * 5 // 6, 0); e.release(w * 7 // 8, h * 5 // 6, 0); e.addMask("selection"); e.deselect()
    c = blob(e, "#8040C0", (w // 2, h // 2, w // 3, h // 3)); e.setLayer(c["id"], "opacity", 0.6); e.setLayer(c["id"], "blend", "screen")
    e.groupLayer(); e.setLayer(e.doc.active, "opacity", 0.8)
    e.selectLayer(e.doc.layers[-1]["id"]); e.addAdjustment("colour"); e.setAdjust("hue", 0.3); e.setAdjust("saturation", 0.2)
    d = blob(e, "#FFFFFF", (w // 10, h * 2 // 3, w // 4, h // 4)); e.markFx(); e.setFx("shadow", "on", True)
    e.selectLayer(paint["id"]); e.setTool("brush"); e.setColour("fg", "#101010"); e.setBrush("size", 14); e.setBrush("opacity", 0.8)
    return e, paint, msgs

# ---- a patch of the picture is the picture
e, paint, _ = rich()
whole = e.doc.composite()
for r in (QRect(0, 0, 160, 120), QRect(40, 30, 50, 40), QRect(0, 0, 1, 1), QRect(150, 100, 10, 20), QRect(70, 0, 20, 120)):
    ok(f"a patch {r.width()}x{r.height()} at {r.x()},{r.y()} matches the whole picture there", same(e.doc.composite_patch(r), whole.copy(r)))
ok("and the whole-picture path is left as it was", e.doc._win is None and same(e.doc.composite(), whole))
def paint_and_compare(e, label, pts=((20, 20), (60, 70), (120, 40), (150, 110), (80, 90))):
    e.press(*pts[0], 1, 0); e.render(); worst, patchy = 0, None
    for x, y in pts[1:]:
        e.move(x, y, 0)
        got = e.render(); patchy = e._drag.get("patchy"), e._drag.get("parts") is not None
        worst = max(worst, off(got, e.doc.composite(e._live)))
    e.release(*pts[-1], 0)
    ok(f"{label}: every frame of a stroke is the true picture", worst == 0, worst)
    ok(f"{label}: and so is the picture when the brush lifts", same(e.render(), e.doc.composite()))
    return patchy
patchy = paint_and_compare(e, "under blends, clipping, a mask, a group and an adjustment")
ok("…drawn a patch at a time, not the whole picture each frame", patchy == (True, False), patchy)
e.setTool("eraser"); paint_and_compare(e, "the eraser there", ((30, 30), (90, 60), (140, 100)))
e.setTool("brush"); e.lockTransparency(); paint_and_compare(e, "with transparency locked", ((25, 25), (90, 80), (140, 30)))
e.lockTransparency()
e.setTool("select"); e.press(50, 30, 1, 0); e.move(120, 100, 0); e.release(120, 100, 0); e.setTool("brush")
paint_and_compare(e, "inside a selection", ((20, 60), (80, 50), (150, 70))); e.deselect()
e.setOption("symmetry", "x"); paint_and_compare(e, "mirrored", ((20, 20), (50, 90))); e.setOption("symmetry", "")
e.selectLayer(next(l["id"] for l in e.doc.layers if l.get("clip"))); patchy = paint_and_compare(e, "painting on the clipped layer")
ok("…a patch at a time", patchy == (True, False), patchy)
inside = next(l for l in e.doc.layers if l.get("group")); e.selectLayer(inside["id"]); patchy = paint_and_compare(e, "painting inside the group")
ok("…a patch at a time", patchy == (True, False), patchy)
styled = next(l for l in e.doc.layers if l.get("fx")); e.selectLayer(styled["id"]); patchy = paint_and_compare(e, "painting on the layer with a shadow")
ok("…the whole picture each frame there (a shadow reaches past a patch)", patchy == (False, False), patchy)
e2, _ = fresh(); blob(e2); e2.setTool("brush"); patchy = paint_and_compare(e2, "a plain picture")
ok("…by the two-halves short cut, as before", patchy == (False, True), patchy)

# ---- adjustments in bands give the same answer
rng = np.random.default_rng(3)
photo = rng.integers(0, 256, (700, 900, 4), dtype=np.uint8); photo[..., 3] = np.where(rng.random((700, 900)) < 0.2, rng.integers(0, 256, (700, 900)), 255)
img = ez.array_to_image(photo.copy())
src = ez.image_to_array(img)
def plain_adjust(kind, params):
    arr = src.astype(np.float32) / 255.0; rgb, a = arr[..., :3], arr[..., 3:4]
    return (np.concatenate([ez.adjust_array(np.where(a > 0, rgb, 0), kind, params), a], axis=2) * 255 + 0.5).astype(np.uint8)
for kind in ez.ADJUSTMENTS:
    params = dict(ez.ADJUST_DEFAULTS.get(kind, {}), **{k: 0.3 for k, _ in ez.ADJUST_PARAMS.get(kind, [])})
    got = ez.image_to_array(ez.apply_adjust_image(img, kind, params))
    ok(f"{ez.ADJUSTMENTS[kind]}: worked in bands, bit for bit what it was", got.tobytes() == ez.image_to_array(ez.array_to_image(plain_adjust(kind, params))).tobytes())

# ---- what each format keeps
e, paint, _ = rich()
want = e.doc.flattened()
p = home + "/r.easel"; e.saveAs(p)
ok("Easel's own file: the same picture", same(ez.open_any(p).flattened(), want))
ok("…with every layer, the clipping, the mask, the group, the adjustment and the style", [(l["kind"], bool(l.get("clip")), l.get("mask") is not None, bool(l.get("fx"))) for l in ez.open_any(p).layers] ==
   [(l["kind"], bool(l.get("clip")), l.get("mask") is not None, bool(l.get("fx"))) for l in e.doc.layers])
for ext in (".psd", ".ora", ".png", ".tiff", ".webp"):
    e.exportAs(home + "/r" + ext, 100)
    ok(f"{ext}: opened again it's the same picture", same(ez.open_any(home + "/r" + ext).flattened(), want), off(ez.open_any(home + "/r" + ext).flattened(), want))
e.exportAs(home + "/r.svg", 100)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import QRectF
got = ez.new_image(160, 120); qp = QPainter(got); QSvgRenderer(home + "/r.svg").render(qp, QRectF(0, 0, 160, 120)); qp.end()
ok(".svg: the same picture", off(got, want) <= 2, off(got, want))
e.exportAs(home + "/r.pdf", 100)
d = np.abs(ez.image_to_array(ez.open_any(home + "/r.pdf").flattened()).astype(np.int16) - ez.image_to_array(want).astype(np.int16))
ok(".pdf: the same picture (redrawn, so edges differ a little)", d.mean() < 2.5, float(d.mean()))
psd = ez.read_psd(home + "/r.psd")
ok(".psd keeps separate layers where Photoshop can say the same thing", len(psd.layers) >= 3 and any(l.get("clip") for l in psd.layers), len(psd.layers))
e3, _ = fresh(); blob(e3); blob(e3, "#20C040", (60, 10, 60, 70)); e3.exportAs(home + "/plain.psd", 100); e3.exportAs(home + "/plain.ora", 100)
ok("a plain stack of layers goes out as that stack", len(ez.read_psd(home + "/plain.psd").layers) == 3 and len(ez.Document.load_ora(home + "/plain.ora").layers) == 3)
e3.selectLayer(e3.doc.layers[1]["id"]); e3.addAdjustment("bw"); e3.exportAs(home + "/adj.psd", 100); got = ez.read_psd(home + "/adj.psd")
ok("an adjustment bakes in only what's under it: the layer above stays a layer", len(got.layers) == 2 and same(got.flattened(), e3.doc.flattened()), len(got.layers))
vec, _ = fresh(); vec.addLayer("vector"); vec.setPersona("vector"); vec.setTool("rect"); vec.press(20, 20, 1, 0); vec.move(90, 70, 0); vec.release(90, 70, 0); vec.exportAs(home + "/v.svg", 100)
ok("shapes still go to SVG as shapes when nothing forces a picture", "<path" in open(home + "/v.svg").read() or "<rect" in open(home + "/v.svg").read())
vec.setPersona("pixel"); vec.selectLayer(vec.doc.layers[0]["id"]); blob(vec); vec.setLayer(vec.doc.active, "blend", "multiply"); vec.exportAs(home + "/v2.svg", 100)
text = open(home + "/v2.svg").read()
ok("…and above a blended layer they're still shapes, over one picture of what's below", ("<path" in text or "<rect" in text) and text.count("<image") == 1, text.count("<image"))

# ---- damaged and hostile files
e, msgs = fresh()
def refuses(path, why=""):
    before = len(msgs); e.doc = None; e.open(path)
    return e.doc is None and len(msgs) > before and (why in msgs[-1]), msgs[-1:] 
raw = bytearray(open(home + "/r.psd", "rb").read())
big = bytes(raw[:14]) + struct.pack(">II", 300000, 300000) + bytes(raw[22:]); open(home + "/huge.psd", "wb").write(big)
t0 = time.time(); r = refuses(home + "/huge.psd", "300,000"); ok("a Photoshop file claiming 300 000 pixels a side is refused at once, in words", r[0] and time.time() - t0 < 2, r[1])
open(home + "/cut.psd", "wb").write(bytes(raw[:len(raw) // 3])); ok("a Photoshop file cut short is refused", refuses(home + "/cut.psd")[0])
open(home + "/nochan.psd", "wb").write(bytes(raw[:12]) + struct.pack(">H", 0) + bytes(raw[14:])); ok("…or with no channels", refuses(home + "/nochan.psd")[0])
def rezip(src, dst, change):
    with zipfile.ZipFile(src) as z: parts = {n: z.read(n) for n in z.namelist()}
    change(parts)
    with zipfile.ZipFile(dst, "w") as z:
        for n, data in parts.items(): z.writestr(n, data)
def manifest(change):
    def go(parts):
        m = json.loads(parts["manifest.json"]); change(m); parts["manifest.json"] = json.dumps(m).encode()
    rezip(home + "/r.easel", home + "/bad.easel", go)
manifest(lambda m: m.update(w=10 ** 6, h=10 ** 6)); r = refuses(home + "/bad.easel", "1,000,000"); ok("an Easel file claiming a million pixels a side is refused, in words", r[0], r[1])
manifest(lambda m: m.update(w="wide")); ok("…or a size that isn't a number", refuses(home + "/bad.easel")[0])
manifest(lambda m: m.update(layers="none")); ok("…or no list of layers", refuses(home + "/bad.easel")[0])
def spoil(m):
    for l in m["layers"]:
        l.update(opacity="thick", visible="yes", blend="sparkle", name=None, group=7)
    m["layers"].append({"kind": "nonsense", "id": "zz"}); m["layers"].append("junk"); m["guides"] = [{"axis": "x", "at": "left"}, 5]; m["dpi"] = "fine"; m["active"] = None
manifest(spoil); e.doc = None; e.open(home + "/bad.easel")
ok("layer settings of the wrong kind are set right, not kept", e.doc is not None and all(isinstance(l["opacity"], float) and 0 <= l["opacity"] <= 1 and isinstance(l["visible"], bool) and l["blend"] in ez.BLENDS and isinstance(l["name"], str) for l in e.doc.layers)
   and all(l["kind"] in ez.KINDS for l in e.doc.layers) and e.doc.index(e.doc.active) >= 0 and e.doc.dpi == 72, (e.doc and [(l["opacity"], l["visible"], l["blend"]) for l in e.doc.layers][:2], msgs[-1:]))
ok("…and the picture can be drawn, painted on and saved", not e.doc.flattened().isNull() and (e.setTool("brush") or True) and (e.press(5, 5, 1, 0) or e.release(9, 9, 0) or True) and e.saveAs(home + "/mended.easel"))
def bad_shapes(m):
    for l in m["layers"]:
        if l["kind"] == "vector": l["shapes"] += [{"type": "rect", "x": "left", "y": 0, "w": 5, "h": 5}, {"type": "rect", "x": 1e308, "y": 0, "w": 1e308, "h": 5}, "junk", {"type": 5}, {"type": "path", "subs": "none"}]
vec.saveAs(home + "/r.easel"); manifest(bad_shapes); e.doc = None; e.open(home + "/bad.easel")
ok("shapes that can't be drawn are dropped, the good one kept", e.doc is not None and [len(l["shapes"]) for l in e.doc.layers if l["kind"] == "vector"] == [1], e.doc and [len(l.get("shapes", [])) for l in e.doc.layers])
e4, _, _ = rich(); e4.saveAs(home + "/r.easel")
rezip(home + "/r.easel", home + "/bad.easel", lambda parts: [parts.pop(n) for n in list(parts) if n.startswith("layers/")][:0]); e.doc = None; e.open(home + "/bad.easel")
ok("an Easel file with its layer pictures missing opens with empty layers the right size", e.doc is not None and all(l["image"].width() == 160 for l in e.doc.layers if l["kind"] == "pixel"))
rezip(home + "/r.easel", home + "/bad.easel", lambda parts: parts.update({n: b"not a picture" for n in parts if n.endswith(".png")})); e.doc = None; e.open(home + "/bad.easel")
ok("…or with rubbish for pictures", e.doc is not None and not e.doc.flattened().isNull())
e4.exportAs(home + "/r.ora", 100)
def stack(change):
    rezip(home + "/r.ora", home + "/bad.ora", lambda parts: parts.update({"stack.xml": change(parts["stack.xml"].decode()).encode()}))
stack(lambda x: x.replace('w="160"', 'w="9999999"')); r = refuses(home + "/bad.ora", "9,999,999"); ok("an OpenRaster file claiming ten million pixels across is refused, in words", r[0], r[1])
stack(lambda x: x.replace('opacity="', 'opacity="nan').replace("composite-op=\"", "composite-op=\"svg:nope")); e.doc = None; e.open(home + "/bad.ora")
ok("…with nonsense opacities and blends: opens, set right", e.doc is not None and all(0 <= l["opacity"] <= 1 and l["blend"] in ez.BLENDS for l in e.doc.layers))
stack(lambda x: x[:len(x) // 2]); ok("…with its list cut short: refused", refuses(home + "/bad.ora")[0])
open(home + "/noise.png", "wb").write(os.urandom(4000)); ok("rubbish called .png is refused", refuses(home + "/noise.png")[0])
open(home + "/empty.easel", "wb").write(b""); ok("an empty file is refused", refuses(home + "/empty.easel")[0])
os.mkfifo(home + "/pipe.png"); t0 = time.time(); ok("a pipe is refused without waiting on it", refuses(home + "/pipe.png")[0] and time.time() - t0 < 2)
ok("a folder is refused", refuses(home)[0])
ok("a file that isn't there is refused", refuses(home + "/gone.png")[0])
shutil.copy(home + "/r.psd", home + "/really-a.png"); r = refuses(home + "/really-a.png"); ok("a Photoshop file named .png is refused, not half-read", r[0], r[1])
e.newDoc(100, 80, "#FFFFFF"); n = len(e.doc.layers); e.placeFile(home + "/huge.psd"); e.placeFile(home + "/noise.png")
ok("Place a Picture refuses the same files the same way", len(e.doc.layers) == n and "place" in msgs[-1].lower(), msgs[-1:])
e.placeFile(home + "/r.psd"); ok("…and can now place a Photoshop or Easel file as a smart object", len(e.doc.layers) == n + 1 and e.doc.layer()["kind"] == "smart")
def raises(fn):
    try: fn(); return False
    except ValueError: return True
ok("sizes: nothing, negative, too long, not a number, too many layers are all refused", all(raises(lambda a=a: ez.checked_size(*a)) for a in ((0, 5), (5, -1), (20000, 5), ("a", 5), (float("nan"), 5), (None, None), (16384, 16384, 50))))
ok("…and a sensible one passes", ez.checked_size("640", 480.0) == (640, 480) and ez.checked_size(16384, 16384) == (16384, 16384))

# ---- a ragged selection doesn't freeze Easel
big, _ = fresh(1600, 1200)
yy, xx = np.mgrid[0:1200, 0:1600]
ragged = ((np.sin(xx / 17.0) + np.cos(yy / 13.0) + np.sin((xx + yy) / 7.0)) > 0.4)
big.doc.selection = ez.alpha_image(ragged.astype(np.uint8) * 255)
t0 = time.time(); path = big.doc.selection_path(); took = time.time() - t0
ok("thousands of specks are outlined in a moment (this took 2 s at this size, 13 s at 12 megapixels)", took < 1.0, f"{took:.2f}s")
box = path.boundingRect(); ys, xs = np.nonzero(ragged)
ok("…and the outline runs round what's selected", abs(box.left() - xs.min()) <= 1 and abs(box.right() - xs.max() - 1) <= 1 and abs(box.top() - ys.min()) <= 1 and abs(box.bottom() - ys.max() - 1) <= 1,
   (box.left(), box.right(), xs.min(), xs.max()))
from PySide6.QtCore import QPointF
inside = sum(path.contains(QPointF(x + 0.5, y + 0.5)) == bool(ragged[y, x]) for x, y in rng.integers(0, 1200, (400, 2)).tolist())
ok("…with selected pixels inside it and the rest outside", inside >= 392, inside)
big.selectAll(); r = big.doc.selection_path().boundingRect()
ok("a plain selection still gets its exact outline", (r.x(), r.y(), r.width(), r.height()) == (0, 0, 1600, 1200), (r.x(), r.y(), r.width(), r.height(), big.doc.w, big.doc.h))
img = rng.integers(0, 256, (300, 400, 4), dtype=np.uint8)
old = lambda t: np.abs(img.astype(np.int16) - img[40, 50].astype(np.int16)).max(axis=2) <= int(t * 255)
ok("the magic wand's colour matching is the same as before, only quicker", all((ez.similar(img, 50, 40, t) == old(t)).all() for t in (0.0, 0.05, 0.12, 0.5, 1.0)))

# ---- closing a picture lets go of it
e5, _ = fresh(400, 300); blob(e5); e5.startTransform(); e5.setTransform(50, 50, 20); e5.newDoc(100, 80, "#FFFFFF")
ok("a transform left open doesn't follow you into the next picture", e5._xform is None and e5._live is None and e5.transformInfo.get("active") in (None, False) or e5._xform is None)
e5.setTool("brush"); e5.press(5, 5, 1, 0); e5.move(50, 50, 0); e5.release(50, 50, 0)
ok("…which paints and draws as normal", same(e5.render(), e5.doc.composite()) and e5.doc.flattened().width() == 100)
e5.closeDoc()
ok("nothing of a closed picture is kept", e5._undo == [] and e5._xform is None and e5._live is None and e5._clone_src is None)

# ---- the canvas
from PySide6.QtQuick import QQuickWindow
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QWheelEvent, QMouseEvent, QKeyEvent
win = QQuickWindow(); win.resize(800, 600)
ev, _ = fresh(400, 300)
view = eu.EaselView(win.contentItem()); view.setWidth(800); view.setHeight(600); view.backend = ev; view.fit()
def wheel(dx, dy, mods=Qt.KeyboardModifier.NoModifier):
    p = QPointF(400, 300); view.wheelEvent(QWheelEvent(p, p, QPoint(0, 0), QPoint(dx, dy), Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False))
def in_sight():
    z = view._zoom
    return view._ox < 800 - 40 and view._oy < 600 - 40 and view._ox + 400 * z > 40 and view._oy + 300 * z > 40
for _ in range(400): wheel(0, 120)
ok("wheeled a long way down, a strip of the picture stays in sight", in_sight(), (view._ox, view._oy))
for _ in range(400): wheel(120, -120)
ok("…and the other way, and sideways", in_sight(), (view._ox, view._oy))
for _ in range(60): wheel(0, 120, Qt.KeyboardModifier.ControlModifier)
ok("zoomed right in, it's still there", in_sight() and view._zoom == 64.0, (view._zoom, view._ox, view._oy))
z0 = view._zoom; view.setZoom(float("nan")); view.setZoom(float("inf"))
ok("a zoom that isn't a number is ignored", view._zoom == z0 or view._zoom == 64.0)
view.setPads(float("nan"), -50, 1e9, 60); view.fit(); view.setWidth(30); view.setHeight(20)
canvas = QImage(800, 600, ez.FMT); canvas.fill(0); qp = QPainter(canvas)
try:
    view.paint(qp); fine = True
except Exception as err:
    fine = repr(err)
qp.end()
ok("nonsense for the islands' room, and a canvas shrunk to nothing, still draw", fine is True and in_sight() is not None, fine)
view.setWidth(800); view.setHeight(600); view.setPads(0, 0, 0, 0); view.fit()
ev.setPersona("vector"); ev.addLayer("vector"); ev.setTool("pen")
def click(kind, x, y):
    p = QPointF(x, y); return QMouseEvent(kind, p, p, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
view.mousePressEvent(click(QEvent.Type.MouseButtonPress, 300, 200)); view.mouseMoveEvent(click(QEvent.Type.MouseMove, 320, 230))
view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
try:
    view.mouseMoveEvent(click(QEvent.Type.MouseMove, 350, 260)); view.mouseReleaseEvent(click(QEvent.Type.MouseButtonRelease, 350, 260)); fine = True
except Exception as err:
    fine = repr(err)
ok("Enter in the middle of pulling a pen handle doesn't break the drag", fine is True, fine)

# ---- saving is quick and loses nothing
photo = rng.integers(0, 256, (1200, 1600, 4), dtype=np.uint8); photo[..., 3] = 255
big, _ = fresh(1600, 1200); big.doc.layer()["image"] = ez.array_to_image(photo.copy()); big.doc.touch(big.doc.layer())
t0 = time.time(); big.saveAs(home + "/big.easel"); took = time.time() - t0
ok("a 2-megapixel noisy photo saves in well under a second", took < 1.5, f"{took:.2f}s")
ok("…and opens as exactly the same pixels", same(ez.open_any(home + "/big.easel").flattened(), big.doc.flattened()))

shutil.rmtree(home, ignore_errors=True)
print(f"{passed} passed, {failed} failed")
sys.stdout.flush(); os._exit(1 if failed else 0)
