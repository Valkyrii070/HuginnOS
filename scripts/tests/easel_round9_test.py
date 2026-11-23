#!/usr/bin/env python3
"""Easel, round nine: brush tips and dynamics, gradients of several colours, the Quick Selection brush, Quick Mask, and
smoothing and bordering a selection.  Usage: easel_round9_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)"""
import os, random, shutil, sys, tempfile, time
from pathlib import Path
KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
home = tempfile.mkdtemp(prefix="easel9-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/d", XDG_CONFIG_HOME=home + "/c", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor
from PySide6.QtCore import QPointF
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
def fresh(w=300, h=200, bg="#FFFFFF"):
    e = eu.Easel(False, ""); e.newDoc(w, h, bg); msgs = []
    e.said.connect(lambda m, bad: msgs.append(m)); return e, msgs
def same(a, b): return a.size() == b.size() and ez.image_to_array(a).tobytes() == ez.image_to_array(b).tobytes()
def px(img, x, y):
    c = img.pixelColor(x, y); return (c.red(), c.green(), c.blue(), c.alpha())
def ink(e): return ez.image_to_array(e.doc.flattened())[..., 0] < 128      # where black paint is, on white
def sel(e): return ez.alpha_of(e.doc.selection) > 127 if e.doc.selection is not None else np.zeros((e.doc.h, e.doc.w), bool)

# ---- tips
for tip in ez.TIPS:
    a = ez.tip_alpha(tip, 60, 0.8)
    ok(f"the {tip} tip: a mark of the right size, the same every time", a.shape == (62, 62) and 0 <= a.min() and a.max() <= 1 and a.max() > 0.5 and a[0].max() < 0.2 and (a == ez.tip_alpha(tip, 60, 0.8)).all(), (a.shape, float(a.max())))
flat = ez.tip_alpha("flat", 80, 1.0); ys, xs = np.nonzero(flat > 0.5)
ok("the flat tip is long one way and thin the other", (xs.max() - xs.min()) > 4 * (ys.max() - ys.min()), (xs.max() - xs.min(), ys.max() - ys.min()))
ok("the bristle tip has gaps between its hairs", 0.25 < (ez.tip_alpha("bristle", 80, 1.0)[:, 40] > 0.3).mean() < 0.85)
ok("the spray tip is dots, thicker in the middle", (lambda a: a[20:60, 20:60].mean() > 3 * a[:12].mean() and 0.01 < a.mean() < 0.3)(ez.tip_alpha("spray", 80, 0.0)))
tiny = ez.tip_alpha("leaf", 1, 1.0); ok("a one-pixel tip doesn't break", tiny.shape[0] >= 3)
e, _ = fresh()
ok("the new brushes are in the list", {"bristle", "charcoal", "calligraphy", "ribbon", "spray", "splatter", "leaves"} <= {b["id"] for b in e.brushes})
def stroke(key, pts, seed=1, size=None):
    e, _ = fresh(); random.seed(seed); e.setTool("brush"); e.setColour("fg", "#000000"); e.setBrushPreset(key)
    if size: e.setBrush("size", size)
    e.setBrush("opacity", 1.0)
    e.press(*pts[0], 1, 0)
    for p in pts[1:]: e.move(*p, 0)
    e.release(*pts[-1], 0); return e
across, down = [(40, 100), (150, 100), (260, 100)], [(150, 20), (150, 100), (150, 180)]
def thick(e, across_stroke):
    m = ink(e); return int(m[:, 150].sum()) if across_stroke else int(m[100, :].sum())
ca, cd = stroke("calligraphy", across), stroke("calligraphy", down)
ok("a calligraphy pen keeps its angle: thick and thin depend on which way you go", thick(ca, True) > 8 and thick(cd, False) > 8 and abs(thick(ca, True) - thick(cd, False)) <= 8 and
   stroke("calligraphy", [(60, 160), (150, 85), (240, 10)]).doc is not None)
diag_with = thick(stroke("calligraphy", [(60, 20), (150, 95), (240, 170)]), True)      # along the nib (40 degrees): a hairline
diag_across = thick(stroke("calligraphy", [(60, 180), (150, 105), (240, 30)]), True)   # across it: a broad stroke
ok("…a hairline along the nib, broad across it", diag_across > 2 * diag_with, (diag_with, diag_across))
ra, rd = stroke("ribbon", across), stroke("ribbon", down)
ok("a ribbon turns with the stroke: the same width whichever way it goes", abs(thick(ra, True) - thick(rd, False)) <= 3 and thick(ra, True) <= 14, (thick(ra, True), thick(rd, False)))
b1 = stroke("bristle", across); col = ink(b1)[70:130, 150]
ok("a dry bristle stroke leaves streaks", 0.2 < col.mean() < 0.9 and np.abs(np.diff(col.astype(int))).sum() >= 4, float(col.mean()))
s1, s2, s3 = stroke("splatter", across, 1), stroke("splatter", across, 1), stroke("splatter", across, 2)
ok("splatter scatters blots of different sizes", 300 < ink(s1).sum() < 30000 and not ink(s1)[95:105, 40:260].all())
ok("…the same stroke twice with the same dice is the same picture; with other dice it isn't", same(s1.doc.flattened(), s2.doc.flattened()) and not same(s1.doc.flattened(), s3.doc.flattened()))
sp = stroke("spray", across); m = ez.image_to_array(sp.doc.flattened())[..., 0]
ok("a spray can builds up a soft speckled band", (m < 250).sum() > 2000 and (m < 60).mean() < 0.5 and int(m[100, 150]) < int(m[30, 150]), (int((m < 250).sum()), float((m < 60).mean()), int(m[100, 150]), int(m[30, 150]), float(m[60:140, 60:240].std())))
for key in ("bristle", "charcoal", "calligraphy", "ribbon", "spray", "splatter", "leaves"):
    e = stroke(key, [(30, 30), (120, 150), (250, 60), (280, 190)]); before = e.doc.flattened(); e.undo()
    ok(f"{ez.BRUSHES[key]['name']}: paints, stays on the canvas, and undoes", ink_ := bool((ez.image_to_array(before)[..., :3] < 250).any()) and e.doc.flattened().pixelColor(150, 100) == QColor("#FFFFFF") and e.history[-1]["state"] != "x")
e = stroke("leaves", across); random.seed(5); e.press(40, 150, 1, 0); e.render(); worst = 0
for p in [(120, 160), (200, 140), (270, 170)]:
    e.move(*p, 0); worst = max(worst, int(np.abs(ez.image_to_array(e.render()).astype(int) - ez.image_to_array(e.doc.composite(e._live)).astype(int)).max()))
e.release(270, 170, 0)
ok("a turning, varying tip: every frame of the stroke is the true picture (no dab falls outside what's redrawn)", worst == 0, worst)
e.setTool("eraser"); e.setBrushPreset("splatter"); e.press(40, 100, 1, 0); e.move(260, 100, 0); e.release(260, 100, 0)
ok("the eraser uses the tips too", True)
e.setBrushPreset("round"); ok("back to the round brush: a plain disc again", e.brush.get("tip", "round") == "round" and "follow" not in e.brush)

# ---- gradients
e, _ = fresh(256, 40)
ok("the gradients are offered", [g["id"] for g in e.gradients][:2] == ["fgbg", "fgclear"] and len(e.gradients) >= 8 and e.gradientKey == "fgbg")
def run(e): e.setTool("gradient"); e.press(0, 20, 1, 0); e.move(255, 20, 0); e.release(255, 20, 0)
e.setColour("fg", "#FF0000"); e.setColour("bg", "#0000FF"); run(e)
ok("front to back colour, as before", px(e.doc.flattened(), 2, 20)[0] > 240 and px(e.doc.flattened(), 253, 20)[2] > 240 and 100 < px(e.doc.flattened(), 128, 20)[0] < 160)
e.setOption("gradient", "spectrum"); run(e); img = e.doc.flattened()
ok("Spectrum: red, yellow, green, cyan, blue, magenta along the line", px(img, 2, 20)[:3] == (255, 0, 0) or px(img, 2, 20)[0] > 245 and px(img, 43, 20)[1] > 200 and px(img, 43, 20)[0] > 200 and px(img, 85, 20)[1] > 200 and px(img, 85, 20)[0] < 60
   and px(img, 128, 20)[2] > 200 and px(img, 128, 20)[1] > 200 and px(img, 171, 20)[2] > 200 and px(img, 171, 20)[1] < 60, [px(img, x, 20) for x in (2, 43, 85, 128, 171)])
ok("…the window is told which one", e.gradientKey == "spectrum" and not e.gradientClear)
e.setOption("gradient", "fire"); run(e); a = px(e.doc.flattened(), 3, 20); b = px(e.doc.flattened(), 252, 20)
e.setOption("gradientReverse", True); run(e); a2 = px(e.doc.flattened(), 3, 20); b2 = px(e.doc.flattened(), 252, 20)
ok("Reverse runs it the other way", sum(a[:3]) < 60 and sum(b[:3]) > 650 and sum(a2[:3]) > 650 and sum(b2[:3]) < 60 and e.gradientReversed, (a, b, a2, b2))
e.setOption("gradientReverse", False); e.setOption("gradient", "fgclear")
ok("Front Colour to Clear is the old To Clear switch", e.gradientClear and e.gradientKey == "fgclear")
e.setOption("gradient", "nope"); e.setOption("gradient", None); ok("a gradient that doesn't exist is ignored", e.gradientKey == "fgclear")
e.setOption("gradient", "sunset"); e.setOption("gradientKind", "radial"); e.press(128, 20, 1, 0); e.move(200, 20, 0); e.release(200, 20, 0)
ok("round gradients take the colours too", px(e.doc.flattened(), 128, 20) != px(e.doc.flattened(), 195, 20) and e.history[-1]["name"] == "Gradient")

# ---- the quick selection brush
e, _ = fresh(300, 200)
l = e.doc.layer(); p = QPainter(l["image"]); p.fillRect(0, 0, 300, 200, QColor("#3070C0")); p.setBrush(QColor("#E0B040")); p.setPen(QColor(0, 0, 0, 0)); p.drawEllipse(90, 40, 120, 120); p.end(); e.doc.touch(l)
disc = np.zeros((200, 300), bool); yy, xx = np.ogrid[0:200, 0:300]; disc[(xx - 150) ** 2 + (yy - 100) ** 2 <= 59 ** 2] = True
e.setTool("quick"); e.setBrush("size", 24)
ok("it's a tool", e.toolName == "quick" and "quick" in eu.PIXEL_TOOLS)
e.press(125, 100, 1, 0); e.move(150, 95, 0); e.move(175, 105, 0); e.release(175, 105, 0)
got = sel(e)
ok("dragged across a thing, the selection spreads to its edges and stops there", (got & disc).sum() > 0.93 * disc.sum() and (got & ~disc).sum() < 0.06 * disc.sum(), ((got & disc).sum() / disc.sum(), (got & ~disc).sum()))
ok("one step of undo", e.history[-1]["name"] == "Quick selection")
e.press(20, 20, 1, 0); e.move(40, 30, 0); e.release(40, 30, 0); got2 = sel(e)
ok("another drag adds to it, and only spreads so far from the brush", got2[25, 30] and (got2 & disc).sum() >= (got & disc).sum() and not got2[190, 290], (bool(got2[25, 30]), bool(got2[190, 290])))
e.press(150, 100, 1, eu.ALT); e.move(160, 100, eu.ALT); e.release(160, 100, eu.ALT); got3 = sel(e)
ok("with Alt it takes away", (got3 & disc).sum() < 0.2 * disc.sum() and got3[25, 30])
e.undo(); ok("undo brings that back", (sel(e) & disc).sum() > 0.9 * disc.sum())
e.deselect(); e.press(-50, -50, 1, 0); e.move(400, 300, 0); e.release(400, 300, 0)
ok("starting off the picture and dragging across is safe", e.doc.flattened().width() == 300)
big, _ = fresh(2400, 1600); big.setTool("quick"); big.setBrush("size", 60)
t0 = time.time(); big.press(300, 300, 1, 0)
for k in range(1, 21): big.move(300 + k * 60, 300 + k * 40, 0)
big.release(1500, 1100, 0); took = time.time() - t0
ok("a long drag on a 4-megapixel picture keeps up", took < 4.0 and sel(big).any(), f"{took:.1f}s")

# ---- Quick Mask
e, said = fresh(300, 200)
e.quickMask()
ok("Q turns it on, and says how it works", e.quickMaskOn and e.toolName == "brush" and any("Quick Mask" in m for m in said))
before = e.doc.flattened()
e.setBrushPreset("round"); e.setBrush("size", 40); e.setBrush("hardness", 1.0); e.setBrush("opacity", 1.0); e.setColour("fg", "#00FF00")
e.press(60, 100, 1, 0); e.move(150, 100, 0)
ok("while you paint, the wash shows where", e.overlay().get("quick") is not None and e.overlay()["quick"].pixelColor(100, 100).alpha() > 200 and e.overlay()["quick"].pixelColor(100, 20).alpha() == 0)
e.move(240, 100, 0); e.release(240, 100, 0)
ok("painting in Quick Mask doesn't touch the picture", same(e.doc.flattened(), before) and len(e.history) == 1)
ok("the marching ants are put away meanwhile", e.overlay()["selection"].isEmpty())
e.setTool("eraser"); e.press(150, 80, 1, 0); e.move(150, 120, 0); e.release(150, 120, 0)
e.undo(); ok("Undo takes back the last thing painted on the mask", e.quickMaskOn and e.overlay()["quick"].pixelColor(150, 100).alpha() > 200)
e.press(150, 80, 1, 0); e.move(150, 120, 0); e.release(150, 120, 0)
e.quickMask(); got = sel(e)
ok("Q again: what was painted is the selection, with the rubbed-out gap", not e.quickMaskOn and got[100, 80] and got[100, 220] and not got[100, 150] and not got[30, 80] and same(e.doc.flattened(), before), (bool(got[100, 80]), bool(got[100, 150])))
ok("…as one step of undo", e.history[-1]["name"] == "Quick Mask")
e.undo(); ok("…undone", e.doc.selection is None)
e.setTool("select"); e.press(50, 50, 1, 0); e.move(150, 150, 0); e.release(150, 150, 0); e.quickMask()
ok("it starts from the selection you had", e.overlay()["quick"].pixelColor(100, 100).alpha() > 200 and e.overlay()["quick"].pixelColor(200, 100).alpha() == 0)
e.setBrush("hardness", 0.0); e.setTool("brush"); e.press(220, 100, 1, 0); e.release(220, 100, 0); e.quickMask()
a = ez.alpha_of(e.doc.selection)
ok("a soft brush makes a soft-edged selection", a[100, 220] > 200 and 0 < a[100, 236] < 255 and a[100, 100] == 255, (int(a[100, 220]), int(a[100, 236])))
e.quickMask(); e.imageSize(150, 100)
ok("any other command finishes the mask first", not e.quickMaskOn and (e.doc.w, e.doc.h) == (150, 100) and (e.doc.selection is None or e.doc.selection.width() == 150))
e.quickMask(); e.escape(); ok("Escape finishes it too", not e.quickMaskOn)
e.quickMask(); e.newDoc(80, 60, "#FFFFFF"); ok("a new picture doesn't inherit a mask", not e.quickMaskOn and e.overlay().get("quick") is None)
e.quickMask(); e.quickMask(); ok("on and straight off with nothing painted: no selection", e.doc.selection is None)

# ---- smoothing and bordering a selection
e, said = fresh(300, 200)
rng = np.random.default_rng(4); ragged = np.zeros((200, 300), np.uint8); ragged[50:150, 80:220] = 255
holes = rng.random((200, 300)) < 0.04; ragged[holes & (ragged > 0)] = 0; ragged[(rng.random((200, 300)) < 0.01) & (ragged == 0)] = 255
e.doc.selection = ez.alpha_image(ragged); e._selection_changed(); e.smoothSelection(3)
got = sel(e)
ok("Smooth closes the pinholes and drops the specks", got[60:140, 90:210].all() and not got[:40].any() and not got[:, 240:].any(), (float(got[60:140, 90:210].mean()), int(got[:40].sum())))
ok("…as a step of undo", e.history[-1]["name"] == "Smooth selection")
e.borderSelection(12); got = sel(e)
ok("Border selects a band along the edge", got[50, 150] and got[100, 80] and not got[100, 150] and not got[20, 150] and 3 <= got[100, 70:95].sum() <= 16, (bool(got[50, 150]), bool(got[100, 150]), int(got[100, 70:95].sum())))
n = len(e.history); e.deselect(); e.smoothSelection(5); e.borderSelection(5); e.smoothSelection(float("nan"))
ok("with nothing selected, or a senseless width, nothing happens", len(e.history) == n + 1)

shutil.rmtree(home, ignore_errors=True)
print(f"{passed} passed, {failed} failed")
sys.stdout.flush(); os._exit(1 if failed else 0)
