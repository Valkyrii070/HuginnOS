#!/usr/bin/env python3
"""Easel, round ten: retouching brushes that draw a patch at a time, filters tried on the canvas, Refine Edge, brushes
made from your own pictures, and spacing for type.  Usage: easel_round10_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)"""
import os, shutil, sys, tempfile, time
from pathlib import Path
KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
home = tempfile.mkdtemp(prefix="easel10-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/d", XDG_CONFIG_HOME=home + "/c", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtGui import QGuiApplication, QPainter, QColor
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
def fresh(w=320, h=240, bg="#FFFFFF"):
    e = eu.Easel(False, ""); e.newDoc(w, h, bg); msgs = []
    e.said.connect(lambda m, bad: msgs.append(m)); return e, msgs
def same(a, b): return a.size() == b.size() and ez.image_to_array(a).tobytes() == ez.image_to_array(b).tobytes()
def off(a, b): return 999 if a.size() != b.size() else int(np.abs(ez.image_to_array(a).astype(np.int16) - ez.image_to_array(b).astype(np.int16)).max())
def sel(e): return ez.alpha_of(e.doc.selection) if e.doc.selection is not None else np.zeros((e.doc.h, e.doc.w), np.uint8)
rng = np.random.default_rng(10)
def photo(e):
    """Something with texture to retouch, under an adjustment and a blended layer (so the short cuts can't be taken)."""
    l = e.doc.layer(); a = np.clip(rng.normal(140, 40, (e.doc.h, e.doc.w, 4)), 0, 255).astype(np.uint8); a[..., 3] = 255; a[:, : e.doc.w // 2, 0] //= 2
    l["image"] = ez.array_to_image(a); e.doc.touch(l)
    e.addLayer("pixel"); t = e.doc.layer(); p = QPainter(t["image"]); p.fillRect(40, 40, 120, 90, QColor(255, 120, 0, 160)); p.end(); e.setLayer(t["id"], "blend", "overlay")
    e.addAdjustment("colour"); e.setAdjust("saturation", 0.3); e.selectLayer(l["id"]); return l

# ---- the retouching brushes draw a patch at a time, and it's the true picture
def frames(e, pts):
    e.press(*pts[0], 1, 0); e.render(); worst = 0
    for p in pts[1:]:
        e.move(*p, 0); worst = max(worst, off(e.render(), e.doc.composite(e._live)))
    patchy = (e._drag.get("patchy"), e._drag.get("patch") is not None)
    e.release(*pts[-1], 0)
    return worst, patchy, same(e.render(), e.doc.composite())
path = [(40, 60), (120, 100), (220, 80), (290, 200)]
for mode in ("dodge", "burn", "sponge", "soften", "sharpen"):
    e, _ = fresh(); photo(e); e.setTool("dodge"); e.setRetouch("mode", mode); e.setBrush("size", 40)
    before = e.doc.flattened(); worst, patchy, after = frames(e, path)
    ok(f"{mode}: every frame is the true picture, a patch at a time", worst == 0 and patchy == (True, True) and after and not same(e.doc.flattened(), before), (worst, patchy))
e, _ = fresh(); photo(e); e.setTool("smudge"); e.setBrush("size", 30); before = e.doc.flattened(); worst, patchy, after = frames(e, path)
ok("smudge: every frame is the true picture, a patch at a time", worst <= 1 and patchy == (True, True) and after and not same(e.doc.flattened(), before), (worst, patchy))
e, _ = fresh(); photo(e); e.setTool("clone"); e.setBrush("size", 30); e.press(250, 60, 1, eu.ALT); e.release(250, 60, eu.ALT)
before = e.doc.flattened(); worst, patchy, after = frames(e, [(60, 160), (100, 170), (140, 150)])
ok("clone: every frame is the true picture, a patch at a time", worst == 0 and patchy == (True, True) and after and not same(e.doc.flattened(), before), (worst, patchy))
e.setTool("heal"); e.setHealSpot(False); e.press(250, 60, 1, eu.ALT); e.release(250, 60, eu.ALT); worst, patchy, after = frames(e, [(60, 60), (90, 70)])
ok("heal: the same while dragging, and right when let go", worst == 0 and after, (worst, patchy))
e.setTool("select"); e.press(80, 40, 1, 0); e.move(200, 200, 0); e.release(200, 200, 0); e.setTool("dodge"); worst, patchy, after = frames(e, path)
ok("inside a selection too", worst == 0 and after, worst)
e, _ = fresh(); l = e.doc.layer(); e.setTool("dodge"); worst, patchy, after = frames(e, path)
ok("on a plain one-layer picture as well (the two-halves short cut)", worst == 0 and after and e.history[-1]["name"] in ("Dodge", "Burn", "Sponge", "Soften", "Sharpen"))
big, _ = fresh(3000, 2000); photo(big); big.setTool("dodge"); big.setBrush("size", 60)
big.press(300, 300, 1, 0); big.render(); t0 = time.time()
for k in range(1, 21):
    big.move(300 + k * 100, 300 + k * 60, 0); big.render()
took = (time.time() - t0) / 20; big.release(2300, 1500, 0)
ok("dodging on a 6-megapixel picture under an adjustment layer: each frame in a few hundredths of a second (it was most of one)", took < 0.12, f"{took * 1000:.0f} ms a frame")

# ---- a filter tried on the canvas before it's applied
e, _ = fresh(); photo(e); before = e.doc.flattened(); shown = e.render(); steps = len(e.history)
e.previewFilter("blur", 0.6)
ok("the canvas shows the filter", not same(e.render(), shown))
ok("…the picture itself is untouched, with no step of undo", same(e.doc.flattened(), before) and len(e.history) == steps)
a = e.render(); e.previewFilter("blur", 0.6); ok("asked again with the same amount, it isn't worked out again", same(e.render(), a) and e._fprev is not None)
e.previewFilter("blur", 0.1); ok("a new amount, a new preview", not same(e.render(), a))
e.endPreview(); ok("Cancel puts the canvas back", same(e.render(), shown) and e._fprev is None)
e.previewFilter("vignette", 0.7); want = e.render(); e.applyFilter("vignette", 0.7)
ok("Apply gives what the preview showed", same(e.render(), want) and e._fprev is None and e.history[-1]["name"] == "Vignette")
e.undo(); ok("…as one step of undo", same(e.doc.flattened(), before))
e.previewFilter("blur", 0.5); e.setTool("brush"); e.press(10, 10, 1, 0); e.move(60, 60, 0); e.release(60, 60, 0)
ok("painting while a filter is being tried puts the preview away first", e._fprev is None and same(e.render(), e.doc.composite()))
e.setTool("select"); e.press(100, 60, 1, 0); e.move(220, 180, 0); e.release(220, 180, 0); base = e.render(); e.previewFilter("invert", 1.0); got = e.render()
ok("with a selection, the preview stays inside it", got.pixelColor(20, 20) == base.pixelColor(20, 20) and got.pixelColor(160, 120) != base.pixelColor(160, 120))
e.endPreview(); e.addLayer("vector"); r0 = e.render(); e.previewFilter("blur", 0.5); e.previewFilter("nope", 0.5); e.previewFilter("blur", float("nan"))
ok("on a layer filters can't work on, or with nonsense, nothing happens", same(e.render(), r0))

# ---- Refine Edge
e, _ = fresh(300, 200)
l = e.doc.layer(); p = QPainter(l["image"]); p.fillRect(0, 0, 300, 200, QColor("#2060B0")); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setBrush(QColor("#F0D070")); p.setPen(QColor(0, 0, 0, 0)); p.drawEllipse(90, 40, 120, 120); p.end(); e.doc.touch(l)
yy, xx = np.ogrid[0:200, 0:300]; true_disc = (xx - 150) ** 2 + (yy - 100) ** 2 <= 60 ** 2
rough = np.zeros((200, 300), np.uint8); rough[48:152, 98:202] = 255                     # a clumsy square round a disc
e.doc.selection = ez.alpha_image(rough); e._selection_changed()
wrong0 = int(((rough > 127) != true_disc).sum())
e.refineSelection(14); got = sel(e)
wrong1 = int(((got > 127) != true_disc).sum())
ok("a clumsy selection round a thing is pulled onto the thing's own edge", wrong1 < wrong0 * 0.35, (wrong0, wrong1))
ok("…well inside stays selected, well outside stays out", got[100, 150] == 255 and got[10, 10] == 0 and got[100, 20] == 0)
ok("…one step of undo", e.history[-1]["name"] == "Refine edge")
e.undo(); ok("…undone", (sel(e) == rough).all())
hair = np.full((200, 300, 4), 255, np.uint8); hair[..., :3] = (40, 90, 160)
hair[60:140, 100:200, :3] = (230, 200, 150)
for k in range(0, 100, 6): hair[30:60, 100 + k:102 + k, :3] = (230, 200, 150)         # fine strands sticking up from the block
block = np.zeros((200, 300), np.uint8); block[60:140, 100:200] = 255; block[45:60, 100:200] = 255   # a selection that cuts across them
out = ez.refine_edge(block, hair, 18)
ok("fine strands: the refined edge goes partly through them instead of cutting straight across", out[40, 100:200][0::6].mean() > out[40, 100:200][3::6].mean() + 40 and 0 < out[50, 103] < 255 or out[50, 100] > out[50, 103] + 40,
   (float(out[40, 100:200][0::6].mean()), float(out[40, 100:200][3::6].mean())))
ok("it keeps the picture's size and stays within 0..255", out.shape == block.shape and out.dtype == np.uint8)
big_a = np.zeros((1500, 2000), np.uint8); big_a[300:1200, 400:1600] = 255; big_p = rng.integers(0, 256, (1500, 2000, 4), dtype=np.uint8)
t0 = time.time(); ez.refine_edge(big_a, big_p, 30); took = time.time() - t0
ok("3 megapixels refined in well under a second", took < 1.0, f"{took:.2f}s")
e.deselect(); n = len(e.history); e.refineSelection(10); e.refineSelection(float("nan")); ok("nothing selected, or a senseless reach: nothing happens", len(e.history) == n)

# ---- a brush from your own picture
e, said = fresh(300, 200)
l = e.doc.layer(); p = QPainter(l["image"]); p.setBrush(QColor("#000000")); p.setPen(QColor(0, 0, 0, 0)); p.drawRect(100, 60, 60, 20); p.drawRect(120, 40, 20, 60); p.end(); e.doc.touch(l)   # a black cross on white
e.setTool("select"); e.press(90, 30, 1, 0); e.move(170, 110, 0); e.release(170, 110, 0)
n0 = len(e.brushes); e.brushFromSelection(); key = e.brushKey
ok("the selection becomes a brush, in the list and in your hand", len(e.brushes) == n0 + 1 and key in ez.CUSTOM_TIPS and e.toolName == "brush" and any("My Brush" in m for m in said), said[-1:])
tip = ez.CUSTOM_TIPS[key]
ok("the mark is trimmed to its shape: the cross, dark where it was dark", tip.shape[0] == tip.shape[1] and tip[tip.shape[0] // 2, tip.shape[1] // 2] > 0.9 and tip[1, 1] < 0.1 and tip[tip.shape[0] // 2, 2] > 0.9, tip.shape)
ok("it's kept as a file for next time", (Path(home) / "d" / "huginn" / "easel-brushes" / f"{key}.png").is_file() or any(Path(home).rglob(f"{key}.png")))
e.deselect(); e.newDoc(300, 200, "#FFFFFF"); e.setColour("fg", "#0000FF"); e.setBrush("size", 60); e.setBrush("opacity", 1.0); e.press(150, 100, 1, 0); e.release(150, 100, 0)
img = e.doc.flattened()
ok("stamped once, it leaves its own shape in the colour in hand", img.pixelColor(150, 100).blue() > 200 and img.pixelColor(150, 100).red() < 60 and img.pixelColor(125, 75) == QColor("#FFFFFF") and img.pixelColor(150, 78).red() < 60,
   (img.pixelColor(150, 100).name(), img.pixelColor(125, 75).name(), img.pixelColor(150, 78).name()))
e2 = eu.Easel(False, ""); ok("a new Easel finds the brush again", any(b["id"] == key for b in e2.brushes) and key in ez.CUSTOM_TIPS)
e.forgetBrush(key); ok("and it can be forgotten", key not in ez.CUSTOM_TIPS and not any(b["id"] == key for b in e.brushes) and e.brushKey == "round" and not any(Path(home).rglob(f"{key}.png")))
cut = np.zeros((40, 60, 4), np.uint8); cut[10:30, 20:40] = (255, 255, 255, 255)
t = ez.tip_from_picture(cut); ok("a light cut-out on nothing still makes a tip", t.max() == 1.0 and t.shape == (20, 20))
try:
    ez.tip_from_picture(np.full((20, 20, 4), 255, np.uint8)); raised = False
except ValueError:
    raised = True
e.newDoc(50, 50, "#FFFFFF"); n1 = len(e.brushes); e.brushFromSelection()
ok("blank white makes no brush, and says why", raised and len(e.brushes) == n1 and "nothing dark" in said[-1], said[-1:])
huge = np.zeros((900, 700, 4), np.uint8); huge[..., 3] = 255; huge[100:800, 100:600, :3] = 0; huge[:100] = 255; huge[800:] = 255; huge[:, :100] = 255; huge[:, 600:] = 255
ok("a big mark is brought down to 256 across", ez.tip_from_picture(huge).shape == (256, 256))

# ---- spacing for type
def text_box(**style):
    e, _ = fresh(600, 300, "transparent"); e.addLayer("vector"); e.setPersona("vector"); e.setTextStyle("size", 40)
    for k, v in style.items(): e.setTextStyle(k, v)
    e.setTool("text"); e.press(20, 20, 1, 0); e.release(20, 20, 0); e.setText("Huginn\nEasel"); e.doneText()
    return e, ez.shape_bounds(e.doc.layer()["shapes"][0])
e0, plain = text_box()
e1, wide = text_box(tracking=50)
e2, tight = text_box(tracking=-10)
e3, tall = text_box(leading=2.0)
ok("wider letter spacing makes the line longer, tighter makes it shorter", wide.width() > plain.width() * 1.25 and tight.width() < plain.width() * 0.97 and abs(wide.height() - plain.height()) < 2, (plain.width(), wide.width(), tight.width()))
ok("more room between lines makes the block taller, and no wider", tall.height() > plain.height() * 1.4 and abs(tall.width() - plain.width()) < 2, (plain.height(), tall.height()))
ok("the window is told, and a new text box starts with them", e1.textStyle["tracking"] == 50 and e3.textStyle["leading"] == 2.0 and e1.doc.layer()["shapes"][0].get("tracking") == 50)
e1.setTextStyle("tracking", float("nan")); e1.setTextStyle("leading", 99); e1.setTextStyle("tracking", 9999)
ok("senseless spacing is refused or held to a limit", e1.textStyle["tracking"] == 300 and e1.textStyle["leading"] == 5.0)
e3.saveAs(home + "/t.easel"); d = ez.open_any(home + "/t.easel")
ok("spacing is kept in a saved picture", same(d.flattened(), e3.doc.flattened()) and d.layers[-1]["shapes"][0].get("leading") == 2.0)

shutil.rmtree(home, ignore_errors=True)
print(f"{passed} passed, {failed} failed")
sys.stdout.flush(); os._exit(1 if failed else 0)
