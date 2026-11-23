#!/usr/bin/env python3
"""Easel, round eleven: liquify a patch at a time, gradients without steps and gradients of your own, adjustment layers
worked as one, and choosing by colour or tone.  Usage: easel_round11_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)"""
import json, os, shutil, sys, tempfile, time
from pathlib import Path
KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
home = tempfile.mkdtemp(prefix="easel11-")
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
def fresh(w=320, h=240, bg="#FFFFFF"):
    e = eu.Easel(False, ""); e.newDoc(w, h, bg); msgs = []
    e.said.connect(lambda m, bad: msgs.append(m)); return e, msgs
def arr(img): return ez.image_to_array(img)
def same(a, b): return a.size() == b.size() and arr(a).tobytes() == arr(b).tobytes()
def off(a, b): return 999 if a.size() != b.size() else int(np.abs(arr(a).astype(np.int16) - arr(b).astype(np.int16)).max())
def sel(e): return ez.alpha_of(e.doc.selection) if e.doc.selection is not None else np.zeros((e.doc.h, e.doc.w), np.uint8)
rng = np.random.default_rng(11)
def photo(e):
    l = e.doc.layer(); a = np.clip(rng.normal(140, 40, (e.doc.h, e.doc.w, 4)), 0, 255).astype(np.uint8); a[..., 3] = 255; a[:, : e.doc.w // 2, 0] //= 2
    l["image"] = ez.array_to_image(a); e.doc.touch(l)
    e.addLayer("pixel"); t = e.doc.layer(); p = QPainter(t["image"]); p.fillRect(40, 40, 120, 90, QColor(255, 120, 0, 160)); p.end(); e.setLayer(t["id"], "blend", "overlay")
    e.addAdjustment("colour"); e.setAdjust("saturation", 0.3); e.selectLayer(l["id"]); return l

# ---- liquify draws a patch at a time, and it's the true picture
def frames(e, pts):
    e.press(*pts[0], 1, 0); e.render(); worst = 0
    for p in pts[1:]:
        e.move(*p, 0); worst = max(worst, off(e.render(), e.doc.composite(e._live)))
    patchy = (e._drag.get("patchy"), e._drag.get("patch") is not None)
    e.release(*pts[-1], 0)
    return worst, patchy, same(e.render(), e.doc.composite())
path = [(60, 60), (110, 90), (200, 120), (260, 190)]
for mode in list(eu.more.LIQUIFY):
    e, _ = fresh(); photo(e); e.setTool("liquify"); e.setRetouch("liquify", mode); e.setBrush("size", 50)
    before = e.doc.flattened(); worst, patchy, after = frames(e, path)
    ok(f"liquify, {mode}: every frame is the true picture, a patch at a time", worst == 0 and patchy == (True, True) and after and (mode == "restore" or not same(e.doc.flattened(), before)), (worst, patchy, after))
e, _ = fresh(); photo(e); e.setTool("liquify"); e.setRetouch("liquify", "push"); frames(e, path); mid = e.doc.flattened(); w2, _, a2 = frames(e, [(200, 60), (150, 150)])
ok("a second stroke goes on from the first", w2 == 0 and a2 and not same(e.doc.flattened(), mid))
e.undo(); ok("…and is one step of undo", same(e.doc.flattened(), mid))
e.setTool("select"); e.press(80, 40, 1, 0); e.move(200, 200, 0); e.release(200, 200, 0); e.setTool("liquify"); before = arr(e.doc.flattened()); worst, _, after = frames(e, path)
ok("inside a selection only", worst == 0 and after and (arr(e.doc.flattened())[:, 210:] == before[:, 210:]).all())
big, _ = fresh(3000, 2000); photo(big); big.setTool("liquify"); big.setBrush("size", 80)
big.press(300, 300, 1, 0); big.render(); t0 = time.time()
for k in range(1, 21):
    big.move(300 + k * 100, 300 + k * 60, 0); big.render()
took = (time.time() - t0) / 20; big.release(2300, 1500, 0)
ok("liquify on a 6-megapixel picture under an adjustment layer keeps up", took < 0.15, f"{took * 1000:.0f} ms a frame")

# ---- gradients without steps
g = arr(ez.gradient_image(3000, 200, "linear", QPointF(0, 0), QPointF(3000, 0), [(0, QColor(100, 100, 100)), (1, QColor(110, 110, 110))]))
plain = arr(ez.gradient_image(3000, 200, "linear", QPointF(0, 0), QPointF(3000, 0), [(0, QColor(100, 100, 100)), (1, QColor(110, 110, 110))], False))
want = 100 + (np.arange(3000) + 0.5) / 3000 * 10
def worst(x): return float(np.abs(np.convolve(x[..., 0].astype(np.float64).mean(axis=0) - want, np.ones(50) / 50, "valid")).max())
ok("a gentle gradient: the plain way is half a level out in bands hundreds of pixels wide (steps you can see)", worst(plain) > 0.4 and len(np.unique(plain[100, :, 0])) == 11, worst(plain))
ok("…the fine way is the right tone everywhere, to a small part of a level: no steps", worst(g) < 0.06, worst(g))
ok("…never more than one level from the truth", np.abs(g[..., 0].astype(np.float64) - want[None, :]).max() <= 1.01)
flat = arr(ez.gradient_image(400, 60, "radial", QPointF(200, 30), QPointF(300, 30), [(0, QColor(37, 99, 200)), (1, QColor(37, 99, 200))]))
ok("where the colour isn't changing it is exactly that colour", (flat.reshape(-1, 4) == (37, 99, 200, 255)).all())
again = arr(ez.gradient_image(3000, 200, "linear", QPointF(0, 0), QPointF(3000, 0), [(0, QColor(100, 100, 100)), (1, QColor(110, 110, 110))]))
ok("the grain is the same every time (a picture saved twice is the same file)", (again == g).all())
hard = arr(ez.gradient_image(200, 10, "linear", QPointF(0, 0), QPointF(200, 0), [(0, QColor("#FF0000")), (0.5, QColor("#FF0000")), (0.5, QColor("#0000FF")), (1, QColor("#0000FF"))]))
ok("two stops at one place make a hard edge", tuple(hard[5, 90, :3]) == (255, 0, 0) and tuple(hard[5, 110, :3]) == (0, 0, 255))
rad = arr(ez.gradient_image(200, 200, "radial", QPointF(100, 100), QPointF(180, 100), [(0, QColor("#FFFFFF")), (1, QColor("#000000"))]))
ok("a round one: light in the middle, dark past the rim, the same all the way round", rad[100, 100, 0] > 250 and rad[100, 190, 0] == 0 and abs(int(rad[100, 140, 0]) - int(rad[140, 100, 0])) <= 2 and abs(int(rad[100, 140, 0]) - 127) < 6)
clear = arr(ez.gradient_image(200, 10, "linear", QPointF(0, 0), QPointF(200, 0), [(0, QColor(255, 0, 0, 255)), (1, QColor(255, 0, 0, 0))]))
ok("to clear: it fades and keeps its colour", clear[5, 2, 3] > 250 and clear[5, 198, 3] < 5 and 110 < clear[5, 100, 3] < 145 and clear[5, 100, 0] > 250)
for bad in ([], [(0, "#FFF")], [(0, "nope"), (1, "#000")], [("x", "#FFF"), (1, "#000")], [(float("nan"), "#FFF"), (1, "#000")], None):
    try: ez.gradient_stops(bad); r = False
    except ValueError: r = True
    ok(f"stops that make no sense are refused: {bad!r}", r)
e, _ = fresh(400, 300); e.setTool("gradient"); e.setColour("fg", "#102030"); e.setColour("bg", "#E0D0C0"); e.press(20, 150, 1, 0); e.move(380, 150, 0); live = e.render(); e.release(380, 150, 0)
got = arr(e.doc.flattened())
ok("the gradient tool: front colour to back colour, as before", abs(int(got[150, 5, 0]) - 0x10) <= 1 and abs(int(got[150, 395, 0]) - 0xE0) <= 1 and off(live, e.doc.flattened()) <= 2 and e.history[-1]["name"] == "Gradient")
e.setOption("gradientReverse", True); e.setOption("gradient", "sunset"); e.press(0, 0, 1, 0); e.move(399, 0, 0); e.release(399, 0, 0); got = arr(e.doc.flattened())
ok("ready-made ones and Reverse still work", abs(int(got[10, 2, 0]) - 0xFF) <= 2 and abs(int(got[10, 397, 2]) - 0x64) <= 3, (got[10, 2], got[10, 397]))
bigg, _ = fresh(4000, 3000); bigg.setTool("gradient"); bigg.press(100, 100, 1, 0); t0 = time.time(); bigg.move(3000, 2500, 0); drag = time.time() - t0; t0 = time.time(); bigg.release(3000, 2500, 0); let = time.time() - t0
ok("on 12 megapixels: dragging stays quick, and the fine one on letting go takes under a second", let < 1.0, f"move {drag:.2f}s, release {let:.2f}s")

# ---- gradients of your own
e, said = fresh(); n0 = len(e.gradients)
key = e.saveGradient([{"at": 0.0, "colour": "#FF0000"}, {"at": 0.25, "colour": "#00FF00"}, {"at": 1.0, "colour": "#0000FF"}], "")
ok("a gradient made in the editor joins the list and is in hand", key.startswith("mg") and len(e.gradients) == n0 + 1 and e.gradientKey == key and e.gradients[-1]["mine"] and "My Gradient 1" in said[-1], said[-1:])
ok("the editor is given its colours back", [(round(s["at"], 2), s["colour"].lower()) for s in e.gradientStops(key)] == [(0.0, "#ff0000"), (0.25, "#00ff00"), (1.0, "#0000ff")], e.gradientStops(key))
e.newDoc(400, 40, "#FFFFFF"); e.setTool("gradient"); e.press(0, 20, 1, 0); e.move(400, 20, 0); e.release(400, 20, 0); got = arr(e.doc.flattened())
ok("drawn, it's those colours at those places", got[20, 1, 0] > 245 and got[20, 1, 2] == 0 and got[20, 100, 1] > 248 and got[20, 100, 0] < 6 and tuple(got[20, 398, :3])[2] > 250, (got[20, 1], got[20, 100], got[20, 398]))
k2 = e.saveGradient([{"at": 0.0, "colour": "#000000"}, {"at": 1.0, "colour": "#FFFFFF"}], key)
ok("changing one of your own keeps its place and name", k2 == key and len(e.gradients) == n0 + 1 and len(e.gradientStops(key)) == 2)
e2 = eu.Easel(False, ""); ok("a new Easel has it too", any(g["id"] == key and g["mine"] for g in e2.gradients) and len(e2.gradientStops(key)) == 2)
ok("bad stops are refused, with a word why", e.saveGradient([{"at": 0.5, "colour": "#FFF"}], "") == "" and e.saveGradient([{"at": "x"}, 5], "") == "" and "two colours" in said[-1] and len(e.gradients) == n0 + 1)
ok("a ready-made one can't be overwritten: it becomes a new one of yours", e.saveGradient([{"at": 0, "colour": "#111"}, {"at": 1, "colour": "#EEE"}], "sunset") not in ("", "sunset") and ez.GRADIENTS["sunset"][0] == "Sunset")
e.forgetGradient("sunset"); e.forgetGradient(key)
ok("yours can be forgotten; the ready-made can't", "sunset" in ez.GRADIENTS and key not in ez.GRADIENTS and e.gradientKey != key and key not in json.loads(next(Path(home).rglob("easel-gradients.json")).read_text()))
ok("the two from the colours in hand give the editor those colours", [s["colour"].lower() for s in e.gradientStops("fgbg")] == [e.fgColour.lower(), e.bg.lower()] and len(e.gradientStops("nope")) == 2)
f = next(Path(home).rglob("easel-gradients.json")); f.write_text('{"mg0000000a": {"name": 7, "stops": "x"}, "sunset": {"stops": [[0, "#000"], [1, "#FFF"]]}, "mg0000000b": {"stops": [[0, "#000"], [1, "#FFF"]]}, "x": 3}')
e3 = eu.Easel(False, ""); mine = [g["id"] for g in e3.gradients if g["mine"]]
ok("a damaged list of gradients: the good ones load, the rest are left, the ready-made stay as they were", "mg0000000b" in mine and "mg0000000a" not in mine and ez.GRADIENTS["sunset"][0] == "Sunset", mine)
f.write_text("not json"); eu.Easel(False, ""); ok("…and nonsense in the file stops nothing", True)

# ---- adjustment layers one over another are worked as one
def stack3(e):
    e.addAdjustment("light"); e.setAdjust("brightness", -0.6); e.addAdjustment("levels"); e.addAdjustment("light"); e.setAdjust("brightness", 0.6)
e, _ = fresh(1024, 64); l = e.doc.layer(); a = np.zeros((64, 1024, 4), np.uint8); a[..., 3] = 255; a[..., :3] = (np.arange(1024) // 4)[None, :, None]; l["image"] = ez.array_to_image(a); e.doc.touch(l)
stack3(e); got = arr(e.doc.composite())[32, :, 0]
one = ez.apply_adjust_image(ez.apply_adjust_image(ez.apply_adjust_image(l["image"], "light", {"brightness": -0.6}), "levels", {}), "light", {"brightness": 0.6})
old = arr(one)[32, :, 0]
ok("darken, then lighten again: as many tones come back as the sums allow (rounding at each layer loses more)", len(np.unique(got)) >= len(np.unique(old)) and np.abs(got.astype(int) - old.astype(int)).max() <= 2, (len(np.unique(got)), len(np.unique(old))))
runs = [l2 for l2 in e.doc.layers if l2["kind"] == "adjust"]
ok("three plain adjustments in a row count as a run", all(ez.Document._plain_adjust(x) for x in runs) and len(runs) == 3)
t = ez.apply_adjust_run(l["image"], [("light", {"brightness": 0.2})]); ok("one on its own gives just what it always did", same(t, ez.apply_adjust_image(l["image"], "light", {"brightness": 0.2})))
full = e.doc.composite(); e.setLayer(runs[2]["id"], "opacity", 0.5); half = e.doc.composite(); e.setLayer(runs[2]["id"], "opacity", 1.0)
ok("one at half strength breaks the run and is worked the old way", not ez.Document._plain_adjust(dict(runs[2], opacity=0.5)) and not same(half, full) and same(full, e.doc.composite()))
e.setLayer(runs[0]["id"], "visible", False); ok("a hidden one is left out", off(e.doc.composite(), ez.apply_adjust_image(ez.apply_adjust_image(l["image"], "levels", {}), "light", {"brightness": 0.6})) <= 1)
e.setLayer(runs[0]["id"], "visible", True)
e2, _ = fresh(300, 200, "transparent"); p = QPainter(e2.doc.layer()["image"]); p.fillRect(50, 50, 100, 80, QColor("#336699")); p.end(); e2.doc.touch(e2.doc.layer()); e2.addAdjustment("invert"); e2.addAdjustment("light"); e2.setAdjust("brightness", 0.1)
c = arr(e2.doc.composite()); step = arr(ez.apply_adjust_image(ez.apply_adjust_image(e2.doc.layers[0]["image"], "invert", {}), "light", {"brightness": 0.1}))
ok("see-through parts stay see-through, and the rest matches layer by layer", (c[..., 3] == step[..., 3]).all() and np.abs(c.astype(int) - step.astype(int)).max() <= 1)
e3, _ = fresh(600, 400); photo(e3); e3.selectLayer(e3.doc.layers[-1]["id"]); stack3(e3); whole = e3.doc.composite()
from PySide6.QtCore import QRect
pa = e3.doc.composite_patch(QRect(100, 80, 200, 150)); sm = e3.doc.composite_small(2)
ok("a patch of the picture agrees with the whole", same(pa, whole.copy(100, 80, 200, 150)), off(pa, whole.copy(100, 80, 200, 150)))
ok("…and so does the small picture the canvas shows", sm.width() == 300 and float(np.abs(arr(sm).astype(float) - arr(whole.scaled(300, 200, ez.Qt.AspectRatioMode.IgnoreAspectRatio, ez.Qt.TransformationMode.SmoothTransformation)).astype(float)).mean()) < 6)
b1, _ = fresh(4000, 3000); photo(b1); b1.selectLayer(b1.doc.layers[-1]["id"]); stack3(b1); b1.addAdjustment("warmth"); b1.addAdjustment("exposure")
t0 = time.time(); b1.doc.touch(b1.doc.layers[0]); b1.doc.composite(); took = time.time() - t0
ok("five adjustments over 12 megapixels cost about what one does", took < 1.5, f"{took:.2f}s")

# ---- choosing by colour or tone
e, said = fresh(300, 200, "#808080"); l = e.doc.layer(); p = QPainter(l["image"]); p.fillRect(0, 0, 100, 200, QColor("#D02020")); p.fillRect(100, 0, 100, 200, QColor("#20B040")); p.fillRect(200, 0, 100, 100, QColor("#FFFFFF")); p.fillRect(200, 100, 100, 100, QColor("#101010")); p.end(); e.doc.touch(l)
shown = e.render(); steps = len(e.history)
e.previewRange("reds", 0.4)
ov = e.overlay(); ok("trying a range washes what would be chosen, and changes nothing", ov.get("quick") is not None and ez.alpha_of(ov["quick"])[50, 50] > 200 and ez.alpha_of(ov["quick"])[50, 150] == 0 and e.doc.selection is None and len(e.history) == steps and same(e.render(), shown))
e.endRange(); ok("Cancel takes the wash away", e.overlay().get("quick") is None)
e.selectRange("reds", 0.4); a = sel(e); ok("Reds: the red part, not the green, the white, the black or the grey", a[50, 50] == 255 and a[50, 150] == 0 and a[50, 250] == 0 and a[150, 250] == 0 and e.history[-1]["name"] == "Colour range" and e.overlay().get("quick") is None)
e.undo(); ok("…one step of undo", e.doc.selection is None)
e.selectRange("greens", 0.4); a = sel(e); ok("Greens", a[50, 150] == 255 and a[50, 50] == 0); e.deselect()
e.selectRange("highlights", 0.3); a = sel(e); ok("Highlights: the white", a[50, 250] == 255 and a[150, 250] == 0 and a[50, 50] == 0); e.deselect()
e.selectRange("shadows", 0.3); a = sel(e); ok("Shadows: the black", a[150, 250] == 255 and a[50, 250] == 0); e.deselect()
e.selectRange("midtones", 0.2); a = sel(e); ok("Midtones: neither", a[150, 250] == 0 and a[50, 250] == 0 and a[50, 150] > 0); e.deselect()
e.setColour("fg", "#20B040"); e.selectRange("colour", 0.2); a = sel(e); ok("The front colour: just that colour", a[50, 150] == 255 and a[50, 50] == 0 and a[50, 250] == 0); e.deselect()
e.setColour("fg", "#40A060"); e.selectRange("colour", 0.05); tight = int((sel(e) > 127).sum()); e.deselect(); e.selectRange("colour", 0.6); wide = int((sel(e) > 127).sum()); e.deselect()
ok("Range sets how near a colour must be", wide > tight and wide >= 100 * 200, (tight, wide))
e.setTool("select"); e.press(0, 0, 1, 0); e.move(300, 100, 0); e.release(300, 100, 0); e.selectRange("shadows", 0.3); ok("with something selected already, only inside it", not sel(e).any() or sel(e)[150, 250] == 0)
e.deselect(); n = len(e.history); e.setColour("fg", "#FF00FF"); e.selectRange("colour", 0.01)
ok("nothing in range: nothing selected, and a word said", e.doc.selection is None and len(e.history) == n and "Nothing in the picture" in said[-1], said[-1:])
e.selectRange("nope", 0.3); e.selectRange("reds", float("nan")); e.previewRange("nope", 2); ok("nonsense is ignored", e.doc.selection is None and e.overlay().get("quick") is None)
soft, _ = fresh(256, 20); l = soft.doc.layer(); a = np.zeros((20, 256, 4), np.uint8); a[..., 3] = 255; a[..., :3] = np.arange(256)[None, :, None]; l["image"] = ez.array_to_image(a); soft.doc.touch(l); soft.selectRange("highlights", 0.5)
edge = sel(soft)[10]; ok("where the picture changes gently the selection has a soft edge", edge[255] == 255 and edge[0] == 0 and len(np.unique(edge)) > 20 and (np.diff(edge.astype(int)) >= 0).all())
e.previewRange("reds", 0.4); e.setTool("brush"); e.press(10, 10, 1, 0); e.release(10, 10, 0); ok("painting puts a range being tried away", e.overlay().get("quick") is None)
bigr, _ = fresh(4000, 3000); photo(bigr); t0 = time.time(); bigr.previewRange("midtones", 0.4); first = time.time() - t0; t0 = time.time(); bigr.selectRange("midtones", 0.4); second = time.time() - t0
ok("12 megapixels of grain: a preview in about a second, and Select (with its outline) not much more", first < 2.5 and second < 3.0, f"{first:.2f}s then {second:.2f}s")

shutil.rmtree(home, ignore_errors=True)
print(f"{passed} passed, {failed} failed")
sys.stdout.flush(); os._exit(1 if failed else 0)
