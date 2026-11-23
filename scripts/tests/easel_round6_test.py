#!/usr/bin/env python3
"""Easel, pro round six: clipping to the layer below, locked transparency, a steadier brush, outlining a selection, and
the hardening the fuzz asked for.  Usage: easel_round6_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)"""
import os, sys, tempfile, shutil
from pathlib import Path
KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
home = tempfile.mkdtemp(prefix="easel6-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/d", XDG_CONFIG_HOME=home + "/c", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor
from PySide6.QtCore import QPointF, QRectF
app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
import numpy as np
import huginn_easel as ez, huginn_easel_ui as eu

passed = failed = 0
def ok(what, cond, extra=""):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1
        print("FAIL", what, extra)
def px(e, x, y):
    c = e.doc.flattened().pixelColor(x, y)
    return (c.red(), c.green(), c.blue(), c.alpha())
def near(a, b, slack=6):
    return all(abs(p - q) <= slack for p, q in zip(a, b))
def paint_rect(layer, x, y, w, h, colour):
    p = QPainter(layer["image"]); p.fillRect(x, y, w, h, QColor(colour)); p.end()
def fresh(w=200, h=120, bg="transparent"):
    e = eu.Easel(False, "")
    e.newDoc(w, h, bg)
    msgs = []
    e.said.connect(lambda m, bad: msgs.append(m))
    return e, msgs

# ---- clipping to the layer below
e, said = fresh()
base = e.doc.layer(); paint_rect(base, 20, 20, 80, 80, "#FF0000"); e.doc.touch(base)
e.addLayer("pixel"); top = e.doc.layer(); paint_rect(top, 60, 0, 120, 120, "#0000FF"); e.doc.touch(top)
ok("before clipping the top layer covers freely", near(px(e, 150, 60), (0, 0, 255, 255)) and near(px(e, 70, 60), (0, 0, 255, 255)))
e.clipLayer()
ok("clipped: shows only where the layer below has paint", near(px(e, 70, 60), (0, 0, 255, 255)) and px(e, 150, 60)[3] == 0, (px(e, 70, 60), px(e, 150, 60)))
ok("the layer below still shows where the clipped one doesn't reach", near(px(e, 30, 60), (255, 0, 0, 255)))
ok("the window is told", e.layers[0]["clip"] is True and e.layers[1]["clip"] is False and e.activeLayer["clip"] is True)
ok("one step of undo", e.history[-1]["name"] == "Layer change")
e.undo(); ok("undo lets it go", near(px(e, 150, 60), (0, 0, 255, 255)) and not e.doc.layer().get("clip"))
e.redo(); ok("redo clips again", px(e, 150, 60)[3] == 0)
e.setLayer(base["id"], "opacity", 0.5)
ok("the pair fades with the lower layer", abs(px(e, 70, 60)[3] - 128) <= 3 and abs(px(e, 30, 60)[3] - 128) <= 3, (px(e, 70, 60), px(e, 30, 60)))
e.setLayer(base["id"], "opacity", 1.0)
e.setLayer(base["id"], "visible", False)
ok("hide the lower layer and the clipped one goes with it", px(e, 70, 60)[3] == 0)
e.setLayer(base["id"], "visible", True)
e.setLayer(top["id"], "opacity", 0.5)
c = px(e, 70, 60)
ok("the clipped layer's own opacity mixes it into the lower one", c[3] == 255 and 100 < c[0] < 160 and 100 < c[2] < 160, c)
e.setLayer(top["id"], "opacity", 1.0)
e.addLayer("pixel"); third = e.doc.layer(); paint_rect(third, 0, 50, 200, 20, "#00FF00"); e.doc.touch(third); e.clipLayer()
ok("two layers clipped to the same one", near(px(e, 30, 60), (0, 255, 0, 255)) and px(e, 150, 60)[3] == 0 and near(px(e, 70, 30), (0, 0, 255, 255)))
e.selectLayer(base["id"]); e.clipLayer()
ok("the bottom layer has nothing to clip to: said, unchanged", not base.get("clip") and any("no layer just below" in m for m in said), said)
p = home + "/clip.easel"; before = ez.image_to_array(e.doc.flattened()).tobytes()
ok("saved", e.saveAs(p))
e2, _ = fresh(); e2.open(p)
ok("clipping survives save and open", ez.image_to_array(e2.doc.flattened()).tobytes() == before and [bool(l.get("clip")) for l in e2.doc.layers] == [False, True, True])
e.exportAs(home + "/clip.psd", 90)
d = ez.read_psd(home + "/clip.psd")
ok("Photoshop files carry the clipping flag both ways", [bool(l.get("clip")) for l in d.layers] == [False, True, True] and ez.image_to_array(d.flattened()).tobytes() == before)
e.selectLayer(top["id"]); e.groupLayer()
ok("grouping doesn't break the picture", e.doc.flattened().width() == 200)
e, said = fresh()
base = e.doc.layer(); paint_rect(base, 20, 20, 80, 80, "#808080"); e.doc.touch(base)
e.addAdjustment("invert") if "invert" in ez.ADJUSTMENTS else e.addAdjustment("bw")
adj = e.doc.layer(); e.clipLayer()
ok("an adjustment clipped to a layer changes only that layer", adj.get("clip") is True and px(e, 150, 60)[3] == 0 and px(e, 50, 50)[3] == 255, (px(e, 150, 60), px(e, 50, 50)))
e.addLayer("pixel"); e.groupLayer(); g = e.doc.layer()
e.setLayer(g["id"], "clip", True)
ok("a group itself isn't clipped", not g.get("clip"))

# ---- locked transparency
e, said = fresh()
l = e.doc.layer(); paint_rect(l, 50, 30, 60, 60, "#FF0000"); e.doc.touch(l)
alpha0 = ez.alpha_of(l["image"]).copy()
e.lockTransparency()
ok("locked, and the window is told", l.get("lockAlpha") is True and e.layers[0]["lockAlpha"] is True)
e.setTool("brush"); e.setColour("fg", "#0000FF"); e.setBrush("size", 30); e.setBrush("hardness", 1.0); e.setBrush("flow", 1.0); e.setBrush("opacity", 1.0)
e.press(20, 60, 1, 0); e.move(100, 60, 0)
live = e.render()
ok("while painting, the stroke already stays inside", live.pixelColor(30, 60).alpha() == 0 and live.pixelColor(80, 60).blue() > 200, (live.pixelColor(30, 60).alpha(), live.pixelColor(80, 60).blue()))
e.move(180, 60, 0); e.release(180, 60, 0)
ok("paint lands only where there was paint", (ez.alpha_of(e.doc.layer()["image"]) == alpha0).all() and near(px(e, 80, 60), (0, 0, 255, 255)) and px(e, 150, 60)[3] == 0)
ok("away from the stroke it's untouched", near(px(e, 80, 35), (255, 0, 0, 255)))
e.setColour("bg", "#00FF00"); e.setTool("eraser"); e.press(60, 80, 1, 0); e.move(100, 80, 0); e.release(100, 80, 0)
ok("rubbing out paints the back colour instead of making holes", (ez.alpha_of(e.doc.layer()["image"]) == alpha0).all() and near(px(e, 80, 80), (0, 255, 0, 255)), px(e, 80, 80))
e.selectAll(); e.setColour("fg", "#FFFF00"); e.fillSelection(); e.deselect()
ok("Fill keeps the shape", (ez.alpha_of(e.doc.layer()["image"]) == alpha0).all() and near(px(e, 80, 60), (255, 255, 0, 255)) and px(e, 10, 10)[3] == 0)
e.lockTransparency(); e.setTool("brush"); e.setColour("fg", "#0000FF"); e.press(20, 60, 1, 0); e.move(40, 60, 0); e.release(40, 60, 0)
ok("unlocked: paint goes anywhere again", near(px(e, 25, 60), (0, 0, 255, 255)))
e.addLayer("vector"); e.lockTransparency()
ok("only pixel layers can be locked: said", not e.doc.layer().get("lockAlpha") and any("pixel layers" in m for m in said), said)
e, _ = fresh(); l = e.doc.layer(); paint_rect(l, 50, 30, 60, 60, "#FF0000"); e.lockTransparency(); e.saveAs(home + "/lock.easel")
e2, _ = fresh(); e2.open(home + "/lock.easel")
ok("the lock survives save and open", e2.doc.layers[0].get("lockAlpha") is True)

# ---- a steadier brush
def wobble(steady):
    e, _ = fresh(400, 200, "#FFFFFF")
    e.setTool("brush"); e.setColour("fg", "#000000"); e.setBrush("size", 4); e.setBrush("hardness", 1.0); e.setBrush("flow", 1.0); e.setBrush("opacity", 1.0)
    e.setBrush("smoothing", steady)
    e.press(20, 100, 1, 0)
    for k in range(1, 73):
        e.move(20 + k * 5, 100 + (12 if k % 2 else -12), 0)          # a shaky hand: 12 px up and down
    e.release(380, 100, 0)
    a = ez.image_to_array(e.doc.flattened())[..., 0] < 128
    ys = np.nonzero(a[:, 100:300])[0]
    return e, int(ys.max() - ys.min()), bool(a[96:105, 372:384].any())
e0, spread0, end0 = wobble(0.0)
e1, spread1, end1 = wobble(0.8)
ok("off: the stroke follows every wobble", spread0 >= 22, spread0)
ok("on: the wobble is evened out", spread1 <= spread0 * 0.45, (spread0, spread1))
ok("and the stroke still ends where the pointer let go", end1 and end0)
ok("the setting is kept between 0 and 1 and shown", e1.brushSmoothing == 0.8 and (e1.setBrush("smoothing", 7) or e1.brushSmoothing == 1.0) and (e1.setBrush("smoothing", float("nan")) or e1.brushSmoothing == 1.0))

# ---- outlining a selection
e, said = fresh(200, 160, "#FFFFFF")
e.strokeSelection(4, "centre")
ok("nothing chosen: said, nothing drawn", any("Choose a part" in m for m in said) and near(px(e, 100, 80), (255, 255, 255, 255)) and len(e.history) == 1)
e.setTool("select"); e.press(60, 40, 1, 0); e.move(140, 120, 0); e.release(140, 120, 0)
e.setColour("fg", "#FF0000"); e.setBrush("opacity", 1.0)
e.strokeSelection(6, "inside")
ok("inside: a band just within the edge", near(px(e, 62, 80), (255, 0, 0, 255)) and near(px(e, 57, 80), (255, 255, 255, 255)) and near(px(e, 100, 80), (255, 255, 255, 255)) and near(px(e, 70, 80), (255, 255, 255, 255)),
   (px(e, 62, 80), px(e, 57, 80), px(e, 70, 80)))
ok("one step of undo, named", e.history[-1]["name"] == "Outline selection")
e.undo(); e.strokeSelection(6, "outside")
ok("outside: a band just beyond the edge", near(px(e, 57, 80), (255, 0, 0, 255)) and near(px(e, 62, 80), (255, 255, 255, 255)) and near(px(e, 50, 80), (255, 255, 255, 255)), (px(e, 57, 80), px(e, 62, 80), px(e, 50, 80)))
e.undo(); e.strokeSelection(8, "centre")
ok("on the edge: half each side", near(px(e, 58, 80), (255, 0, 0, 255)) and near(px(e, 62, 80), (255, 0, 0, 255)) and near(px(e, 52, 80), (255, 255, 255, 255)) and near(px(e, 68, 80), (255, 255, 255, 255)))
ok("the selection is still there afterwards", e.doc.selection is not None)
e.undo(); e.strokeSelection(float("nan"), "centre"); e.strokeSelection(-5, "nope")
ok("a senseless width does no harm", e.doc.flattened().width() == 200)

# ---- what the fuzz found
e, said = fresh(200, 120, "#FFFFFF")
e.setTool("brush"); e.press(10, 10, 1, 0); e.move(float("inf"), float("nan"), 0); e.move(1e12, -1e12, 0); e.release(float("nan"), 5, 0)
ok("a pointer at infinity doesn't hang the brush", e.doc.flattened().width() == 200)
e.press(10, 10, 1, 0); e.move(50, 50, 0); e.press(60, 60, 1, 0); e.move(80, 80, 0); e.release(80, 80, 0)
ok("a second press with no release between doesn't crash", e.doc.flattened().width() == 200 and e._drag is None)
e.press(10, 10, 1, 0); e.move(50, 50, 0); e.undo(); e.press(10, 10, 1, 0); e.move(40, 40, 0); e.imageSize(100, 60)
ok("Undo and a resize in the middle of a stroke are safe", (e.doc.w, e.doc.h) == (100, 60) and all(l["image"].width() == 100 for l in e.doc.layers if l["kind"] == "pixel"))
e, said = fresh(200, 120, "#FFFFFF")
e.startTransform(); e.setTransform(50, 50, 30); e.imageSize(120, 80)
ok("a resize with a free transform open applies it first", (e.doc.w, e.doc.h) == (120, 80) and all(l["image"].width() == 120 and l["image"].height() == 80 for l in e.doc.layers if l["kind"] == "pixel") and e._xform is None)
e.startTransform(); e.transformCanvas("cw"); e.cancelTransform()
ok("…and turning the canvas too", all((l["image"].width(), l["image"].height()) == (e.doc.w, e.doc.h) for l in e.doc.layers if l["kind"] == "pixel"))
for call in (lambda: e.setStyle("width", None), lambda: e.setFx("shadow", "spread", None), lambda: e.setRetouch("liquifyStrength", None), lambda: e.setTextStyle("size", "big"),
             lambda: e.setAdjust("brightness", float("nan")), lambda: e.setLayer(e.doc.active, "opacity", None), lambda: e.canvasSize(100, 100, ""), lambda: e.exportAs(home + "/q.webp", 2 ** 31),
             lambda: e.moveLayer(e.doc.active, 0), lambda: e.feather(float("-inf")), lambda: e.nudge(float("nan"), 2), lambda: e.setTransform(float("nan"), 50, 0), lambda: e.addGuide("x", float("inf")),
             lambda: e.applyFilter("blur", None), lambda: e.setBrush("size", None), lambda: e.setPressure(float("nan"))):
    try:
        call(); fine = True
    except Exception as err:
        fine = repr(err)
    ok("a setting given nonsense is ignored, not a crash", fine is True, fine)
e.setLayer(e.doc.active, "visible", 0.3)
ok("a layer's on/off settings stay true or false", e.doc.layer()["visible"] is True)
e.imageSize(10 ** 6, 50); ok("no picture gets past the size limit", e.doc.w == ez.SIDE_LIMIT and e.doc.h == 50, (e.doc.w, e.doc.h))
e.newDoc(200, 120, "#FFFFFF"); e.canvasSize(30, 2 ** 31, "c"); ok("…from Canvas Size either", e.doc.h == ez.SIDE_LIMIT, e.doc.h); e.newDoc(200, 120, "#FFFFFF")
e.addLayer("pixel"); a = e.doc.active; e.groupLayer(); g = e.doc.active
try:
    e.dropLayer(a, g); fine = True
except Exception as err:
    fine = repr(err)
ok("a layer dropped on its own group", fine is True and len(e.doc.layers) == 3, fine)
e.newDoc(100, 100, "#FFFFFF"); e.addLayer("pixel"); e.groupLayer(); grp = e.doc.active
kid = next(l["id"] for l in e.doc.layers if l.get("group") == grp)
e.selectLayer(next(l["id"] for l in e.doc.layers if l["kind"] == "pixel" and not l.get("group"))); e.deleteLayer(); e.selectLayer(kid); e.deleteLayer(); e.selectLayer(grp); e.ungroup()
ok("the last thing left can't be ungrouped away", len(e.doc.layers) >= 1, len(e.doc.layers))
e.newDoc(200, 120, "#FFFFFF"); e.addGuide("x", 0.0); e.setTool("move"); e.addLayer("pixel"); paint_rect(e.doc.layer(), 10, 10, 20, 20, "#FF0000"); e.doc.touch(e.doc.layer())
try:
    e.nudge(5, 0); fine = True
except Exception as err:
    fine = repr(err)
ok("nudging with a guide at the corner moves the layer, not the guide", fine is True and near(px(e, 32, 15), (255, 0, 0, 255)) and e.doc.guides[0]["at"] == 0.0, (fine, px(e, 32, 15)))

shutil.rmtree(home, ignore_errors=True)
print(f"{passed} passed, {failed} failed")
sys.stdout.flush()
os._exit(1 if failed else 0)
