#!/usr/bin/env python3
"""Easel, round eight: the canvas put together at the size it's shown, the four hue/saturation/colour/luminosity blend
modes, Exposure, Colour Balance, Threshold and Channel Mixer, five more filters, and the tone histogram.
Usage: easel_round8_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)"""
import os, shutil, sys, tempfile, time
from pathlib import Path
KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
home = tempfile.mkdtemp(prefix="easel8-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/d", XDG_CONFIG_HOME=home + "/c", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"), EASEL_CHECK_MIPS="1")
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor, QLinearGradient
from PySide6.QtCore import Qt
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
def arr(img): return ez.image_to_array(img).astype(np.int16)
def same(a, b): return a.size() == b.size() and ez.image_to_array(a).tobytes() == ez.image_to_array(b).tobytes()
def fresh(w=160, h=120, bg="#FFFFFF"):
    e = eu.Easel(False, ""); e.newDoc(w, h, bg); msgs = []
    e.said.connect(lambda m, bad: msgs.append(m)); return e, msgs
def fill(layer, colour, box=None):
    p = QPainter(layer["image"]); p.setCompositionMode(ez.CM.CompositionMode_Source)
    p.fillRect(*(box or (0, 0, layer["image"].width(), layer["image"].height())), QColor(colour)); p.end()
def blob(e, colour="#E03060", box=(30, 20, 60, 50)):
    e.addLayer("pixel"); l = e.doc.layer(); p = QPainter(l["image"]); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(colour)); p.setPen(QColor(0, 0, 0, 0)); p.drawEllipse(*box); p.end(); e.doc.touch(l); return l
def px(img, x, y):
    c = img.pixelColor(x, y); return (c.red(), c.green(), c.blue(), c.alpha())
rng = np.random.default_rng(8)

# ---- the four blend modes Qt doesn't have
def lum(c): return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]
def clipc(c):
    l, n, x = lum(c), min(c), max(c)
    if n < 0: c = [l + (v - l) * l / (l - n) for v in c]
    if x > 1: c = [l + (v - l) * (1 - l) / (x - l) for v in c]
    return c
def setlum(c, l):
    d = l - lum(c); return clipc([v + d for v in c])
def sat(c): return max(c) - min(c)
def setsat(c, s):
    n, x = min(c), max(c)
    return [(v - n) * s / (x - n) for v in c] if x > n else [0.0, 0.0, 0.0]
def reference(b, s, mode, opacity):
    cb, ab, cs, as_ = [v / 255 for v in b[:3]], b[3] / 255, [v / 255 for v in s[:3]], s[3] / 255 * opacity
    mix = {"hue": lambda: setlum(setsat(cs, sat(cb)), lum(cb)), "saturation": lambda: setlum(setsat(cb, sat(cs)), lum(cb)),
           "color": lambda: setlum(cs, lum(cb)), "luminosity": lambda: setlum(cb, lum(cs))}[mode]()
    ao = as_ + ab * (1 - as_)
    co = [as_ * (1 - ab) * cs[i] + as_ * ab * mix[i] + (1 - as_) * ab * cb[i] for i in range(3)]
    return [min(255, max(0, int((co[i] / ao if ao > 0 else 0) * 255 + 0.5))) for i in range(3)] + [int(ao * 255 + 0.5)]
under = rng.integers(0, 256, (40, 50, 4), dtype=np.uint8); top = rng.integers(0, 256, (40, 50, 4), dtype=np.uint8)
under[:5, :, 3] = 0; top[5:10, :, 3] = 0; under[10:20, :, 3] = 255; top[10:20, :, 3] = 255
for mode in ez.HSL_BLENDS:
    got = ez.hsl_blend(under, top, mode, 0.8)
    worst = max(max(abs(int(g) - r) for g, r in zip(got[y, x], reference(under[y, x], top[y, x], mode, 0.8))) for y, x in rng.integers(0, 40, (300, 2)).tolist())
    ok(f"{mode}: the textbook answer for every pixel tried", worst <= 1, worst)
grey = np.full((4, 4, 4), 255, np.uint8); grey[..., :3] = 128
red = np.zeros((4, 4, 4), np.uint8); red[..., 0] = 255; red[..., 3] = 255
c = ez.hsl_blend(grey, red, "color", 1.0)[0, 0]
ok("Colour: red over grey is a red as light as the grey was", abs(lum(c[:3]) - 128) <= 2 and c[0] > c[1] + 60 and c[1] == c[2], tuple(c))
c = ez.hsl_blend(red, grey, "luminosity", 1.0)[0, 0]
ok("Luminosity: grey over red is red at the grey's lightness", abs(lum(c[:3]) - 128) <= 2 and c[0] > c[1], tuple(c))
ok("Saturation: grey over red takes the colour out", len(set(ez.hsl_blend(red, grey, "saturation", 1.0)[0, 0][:3].tolist())) == 1)
ok("at no opacity nothing changes", (ez.hsl_blend(under, top, "hue", 0.0) == under)[under[..., 3] > 0].all())
e, _ = fresh(); l0 = e.doc.layer(); p = QPainter(l0["image"]); g = QLinearGradient(0, 0, 160, 0); g.setColorAt(0, QColor("#202020")); g.setColorAt(1, QColor("#E0E0E0")); p.fillRect(0, 0, 160, 120, g); p.end()
tint = blob(e, "#FF6000", (20, 20, 120, 80)); e.setLayer(tint["id"], "blend", "color")
ok("the window offers them", [b["id"] for b in e.blends][-4:] == ["hue", "saturation", "color", "luminosity"] and e.activeLayer["blend"] == "color")
a = px(e.doc.flattened(), 40, 60); b = px(e.doc.flattened(), 120, 60); under_a = px(l0["image"], 40, 60); under_b = px(l0["image"], 120, 60)
ok("a Colour layer tints a picture and keeps its light and dark", abs(lum(a) - lum(under_a)) <= 3 and abs(lum(b) - lum(under_b)) <= 3 and a[0] > a[2] and b[0] > b[2], (a, b))
ok("outside the layer the picture is untouched", px(e.doc.flattened(), 5, 5) == px(l0["image"], 5, 5))
want = e.doc.flattened()
e.setTool("brush"); e.setColour("fg", "#0040FF"); e.setBrush("size", 16); e.press(30, 30, 1, 0); e.render(); worst = 0
for x, y in ((60, 50), (100, 70), (140, 40)):
    e.move(x, y, 0); worst = max(worst, int(np.abs(arr(e.render()) - arr(e.doc.composite(e._live))).max()))
e.release(140, 40, 0)
ok("painting on a Colour layer: every frame is the true picture", worst == 0 and same(e.render(), e.doc.composite()), worst)
want = e.doc.flattened()
e.saveAs(home + "/c.easel"); ok("kept in Easel's own file", same(ez.open_any(home + "/c.easel").flattened(), want) and ez.open_any(home + "/c.easel").layers[1]["blend"] == "color")
for ext in (".psd", ".ora"):
    e.exportAs(home + "/c" + ext, 100); d = ez.open_any(home + "/c" + ext)
    ok(f"{ext}: goes out and comes back as a Colour layer, the same picture", same(d.flattened(), want) and d.layers[1]["blend"] == "color", [l["blend"] for l in d.layers])
e.selectLayer(l0["id"]); e.mergeDown(); e.selectLayer(tint["id"]); e.mergeDown()
ok("Merge Down bakes the blend in", len(e.doc.layers) == 1 and same(e.doc.flattened(), want))

# ---- four more adjustments
ramp = np.repeat((np.arange(256, dtype=np.float32) / 255.0)[:, None, None], 3, axis=2)
out = ez.adjust_array(ramp, "exposure", {"exposure": 1 / 3})
ok("Exposure: one stop up doubles the light (and stops at white)", abs(out[60, 0, 0] - 2 * 60 / 255) < 0.01 and out[200, 0, 0] == 1.0)
ok("…offset lifts the shadows, gamma bends the middle and leaves the ends", ez.adjust_array(ramp, "exposure", {"offset": 0.4})[0, 0, 0] > 0.05
   and ez.adjust_array(ramp, "exposure", {"gamma": 0.5})[128, 0, 0] > 0.55 and ez.adjust_array(ramp, "exposure", {"gamma": 0.5})[[0, 255], 0, 0].tolist() == [0.0, 1.0])
out = ez.adjust_array(ramp, "balance", {"red": 1.0, "blue": -1.0})
ok("Colour Balance: toward red and yellow in the midtones, black and white left alone", out[128, 0, 0] > 0.75 and out[128, 0, 2] < 0.25 and out[128, 0, 1] == ramp[128, 0, 1]
   and out[0].tolist() == [[0.0, 0.0, 0.0]] and out[255].tolist() == [[1.0, 1.0, 1.0]])
out = ez.adjust_array(rng.random((30, 30, 3), dtype=np.float32), "threshold", {"level": 0.0})
ok("Threshold: nothing but black and white", set(np.unique(out).tolist()) == {0.0, 1.0})
ok("…and the level moves the line", ez.adjust_array(ramp, "threshold", {"level": 0.5}).mean() < ez.adjust_array(ramp, "threshold", {"level": -0.5}).mean())
pic = rng.random((10, 10, 3), dtype=np.float32)
ok("Channel Mixer: at rest it changes nothing", np.allclose(ez.adjust_array(pic, "mixer", {}), pic))
out = ez.adjust_array(pic, "mixer", {"red_green": 1.0})
ok("…and all the way over, red is made from green", np.allclose(out[..., 0], pic[..., 1]) and np.allclose(out[..., 1:], pic[..., 1:]))
ok("…greys stay grey whatever the mix", np.allclose(ez.adjust_array(ramp, "mixer", {"red_green": 0.4, "green_blue": 0.7, "blue_red": 0.2}), ramp, atol=1e-6))
e, _ = fresh()
for kind in ("exposure", "balance", "threshold", "mixer"):
    e.addAdjustment(kind); info = e.activeLayer
    ok(f"{ez.ADJUSTMENTS[kind]}: offered, with its sliders", any(a["id"] == kind for a in e.adjustments) and len(info["paramList"]) == len(ez.ADJUST_PARAMS[kind]) >= 1 and not e.doc.flattened().isNull())
e.exportAs(home + "/adj.easel", 100) if False else e.saveAs(home + "/adj.easel")
ok("they're kept in a saved picture", [l.get("adjust") for l in ez.open_any(home + "/adj.easel").layers][1:] == ["exposure", "balance", "threshold", "mixer"])

# ---- five more filters
noisy = np.clip(rng.normal(128, 25, (120, 160, 4)), 0, 255).astype(np.uint8); noisy[..., 3] = 255; noisy[:, 80:, :3] //= 3
soft_alpha = noisy.copy(); soft_alpha[..., 3] = rng.integers(0, 256, (120, 160))
for name in ("clarity", "highpass", "denoise", "glow", "vignette"):
    out = ez.filter_array(soft_alpha.copy(), name, 0.5)
    ok(f"{ez.FILTERS[name]}: changes the picture, keeps its size and its see-through parts", out.shape == soft_alpha.shape and out.dtype == np.uint8 and (out[..., 3] == soft_alpha[..., 3]).all() and (out[..., :3] != soft_alpha[..., :3]).any())
flat = np.full((60, 80, 4), 255, np.uint8); flat[..., :3] = (90, 140, 200)
ok("High Pass of a flat colour is flat grey", np.abs(ez.filter_array(flat.copy(), "highpass", 0.5)[..., :3].astype(int) - 128).max() <= 1)
ok("Clarity of a flat colour changes nothing", np.abs(ez.filter_array(flat.copy(), "clarity", 0.8)[..., :3].astype(int) - flat[..., :3]).max() <= 1)
v = ez.filter_array(flat.copy(), "vignette", 0.8)
ok("Vignette: the middle untouched, the corners darker", (v[30, 40, :3] == flat[30, 40, :3]).all() and v[0, 0, :3].sum() < flat[0, 0, :3].sum() * 0.6 and v[0, 0, 2] < v[10, 10, 2] < v[30, 40, 2] + 1)
d = ez.filter_array(noisy.copy(), "denoise", 0.7)
ok("Reduce Noise: the grain goes down and the edge stays", d[:, :70, 0].astype(float).std() < noisy[:, :70, 0].astype(float).std() * 0.75
   and abs(float(d[:, 60:78, 0].mean()) - float(d[:, 82:100, 0].mean())) > 60, (d[:, :70, 0].std(), noisy[:, :70, 0].std()))
gl = ez.filter_array(noisy.copy(), "glow", 0.5)
ok("Soft Glow only ever lightens", (gl[..., :3].astype(int) >= noisy[..., :3].astype(int) - 1).all())
e, _ = fresh(); e.doc.layer()["image"] = ez.array_to_image(noisy.copy()); e.doc.touch(e.doc.layer()); before = e.doc.flattened()
e.applyFilter("clarity", 0.5); ok("from the Filters menu, as one step of undo", any(f["id"] == "clarity" for f in e.filters) and e.history[-1]["name"] == "Clarity" and not same(e.doc.flattened(), before))
e.undo(); ok("…undone exactly", same(e.doc.flattened(), before))

# ---- the canvas's picture, at the size it's shown
eu.MIP_FROM = 0                                    # (so these small pictures count as big ones)
def rich(w=320, h=240):
    e, msgs = fresh(w, h)
    l = e.doc.layer(); p = QPainter(l["image"]); g = QLinearGradient(0, 0, w, h); g.setColorAt(0, QColor("#2060E0")); g.setColorAt(1, QColor("#F0C020")); p.fillRect(0, 0, w, h, g); p.end()
    a = blob(e, "#E03060", (w // 6, h // 6, w // 2, h // 2)); e.setLayer(a["id"], "blend", "multiply")
    b = blob(e, "#20C040", (w // 3, h // 12, w // 2, h * 2 // 3)); e.clipLayer()
    e.addLayer("pixel"); paint = e.doc.layer()
    e.setTool("select"); e.press(w // 8, h // 8, 1, 0); e.move(w * 7 // 8, h * 5 // 6, 0); e.release(w * 7 // 8, h * 5 // 6, 0); e.addMask("selection"); e.deselect()
    c = blob(e, "#8040C0", (w // 2, h // 2, w // 3, h // 3)); e.setLayer(c["id"], "blend", "luminosity")
    e.groupLayer(); e.setLayer(e.doc.active, "opacity", 0.8)
    e.selectLayer(e.doc.layers[-1]["id"]); e.addAdjustment("colour"); e.setAdjust("hue", 0.3)
    d = blob(e, "#FFFFFF", (w // 10, h * 2 // 3, w // 4, h // 4)); e.markFx(); e.setFx("shadow", "on", True)
    e.selectLayer(paint["id"]); e.setTool("brush"); e.setColour("fg", "#101010"); e.setBrush("size", 20); e.setBrush("opacity", 1.0)
    return e, paint
def shrunk(img, k):
    return img.scaled(-(-img.width() // k), -(-img.height() // k), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
def near(got, want, mean=3.5, far=0.03):
    d = np.abs(arr(got) - arr(want)); return got.size() == want.size() and d.mean() <= mean and (d > 60).mean() <= far, (round(float(d.mean()), 2), round(float((d > 60).mean()), 3))
e, paint = rich()
ok("at full size the canvas gets the true picture", e.mip() == 1 and same(e.render(), e.doc.composite()))
for zoom, k in ((0.5, 2), (0.3, 2), (0.25, 4), (0.2, 4), (0.125, 8), (0.05, 8)):
    e.zoom = zoom; got = e.render()
    r = near(got, shrunk(e.doc.composite(), k))
    ok(f"at {int(zoom * 100)}% it's put together at 1/{k} size, and is the picture", e.mip() == k and (got.width(), got.height()) == e.doc.small_size(k) and r[0], (e.mip(), r[1]))
e.zoom = 0.25; first = e.render(); kept = dict(e.doc._mip_cache)
e.render(); ok("nothing changed: every layer's small copy is used again", all(e.doc._mip_cache[key][1] is kept[key][1] for key in kept) and len(kept) >= 4)
other = e.doc.layers[1]; fill(other, "#00FFFF", (0, 0, 40, 40)); e.doc.touch(other); e.render()
changed = [key for key in kept if e.doc._mip_cache[key][1] is not kept[key][1]]
ok("one layer changed: only its small copy is made again", changed == [(other["id"], 4)], changed)
ok("…and the canvas shows the change", near(e.render(), shrunk(e.doc.composite(), 4))[0] and px(e.render(), 3, 3) != px(first, 3, 3))
e.selectLayer(paint["id"])
e.press(40, 40, 1, 0); e.render(); worst = (0, 0)
for x, y in ((120, 90), (200, 60), (280, 200)):
    e.move(x, y, 0); r = near(e.render(), shrunk(e.doc.composite(e._live), 4), 4.5, 0.05); worst = max(worst, r[1]) if r[0] else (99, 99)
ok("a brush stroke at 25%: each frame is the picture, a patch at a time", worst[0] < 5 and e._drag.get("patchy") and e._drag["frame"].width() == 80, worst)
e.release(280, 200, 0)
ok("…and when the brush lifts", near(e.render(), shrunk(e.doc.composite(), 4))[0])
shown = e.render(); e.undo()
e.press(60, 200, 1, 0); e.move(250, 210, 0); e.release(250, 210, 0)               # undo, then paint something else, with no draw in between
ok("undo, then a different stroke: the canvas shows the new one, not a kept copy of the old", near(e.render(), shrunk(e.doc.composite(), 4))[0] and not same(e.render(), shown))
e.undo(); e.undo(); e.redo()
ok("undo and redo land on the right picture", near(e.render(), shrunk(e.doc.composite(), 4))[0])
e.setTool("move"); e.selectLayer(e.doc.layers[1]["id"]); e.press(50, 50, 1, 0); e.move(90, 80, 0)
r = near(e.render(), shrunk(e.doc.composite((e._live[0], e._live[1])), 4), 4.5, 0.05)
ok("moving a layer at 25%: the preview is the picture", r[0] and e._live[3] is not None, r[1])
e.release(90, 80, 0); ok("…and where it's dropped", near(e.render(), shrunk(e.doc.composite(), 4))[0])
e.selectLayer(e.doc.layers[1]["id"]); e.startTransform(); e.setTransform(70, 60, 25)
r = near(e.render(), shrunk(e.doc.composite((e._live[0], e._live[1])), 4), 4.5, 0.05)
ok("free transform at 25%: the preview is the picture", r[0], r[1])
e.applyTransform(); ok("…and once applied", near(e.render(), shrunk(e.doc.composite(), 4))[0])
adj = next(l for l in e.doc.layers if l["kind"] == "adjust"); e.selectLayer(adj["id"]); before = e.render(); e.setAdjust("hue", -0.6)
ok("an adjustment's slider at 25%", near(e.render(), shrunk(e.doc.composite(), 4))[0] and not same(e.render(), before))
e.zoom = 1.0; ok("zoomed back in: the true picture again", same(e.render(), e.doc.composite()))
ok("saving and exporting never use the small copies", e.doc._mip == 0 and e.doc.flattened().width() == 320)
eu.MIP_FROM = 2_000_000
small, _ = fresh(400, 300); small.zoom = 0.1
ok("a small picture is always put together at full size", small.mip() == 1 and small.render().width() == 400)

# ---- a layer's version is never used twice
e, _ = fresh(); l = e.doc.layer(); seen = set()
for k in range(6):
    e.setTool("brush"); e.press(10 + k * 10, 10, 1, 0); e.release(20 + k * 10, 60, 0); seen.add(e.doc.layer()["v"]); e.undo()
ok("paint, undo, paint again: each picture gets a number of its own", len(seen) == 6, seen)
v0 = e.doc.layer()["v"]; e.press(5, 5, 1, 0); e.release(50, 50, 0); e.undo()
ok("undo brings a pixel layer back with the number it had (so what was kept for it is still good)", e.doc.layer()["v"] == v0)

# ---- the tone histogram
e, _ = fresh(200, 100, "#FFFFFF")
h = e.doc.histogram()
ok("a white picture: everything in the last bar", len(h["l"]) == 64 and h["l"][63] == 1.0 and sum(h["l"]) == 1.0 and h["r"][63] == 1.0)
fill(e.doc.layer(), "#000000", (0, 0, 100, 100)); e.doc.touch(e.doc.layer()); h = e.doc.histogram()
ok("half black, half white: two bars, equal", h["l"][0] == 1.0 and h["l"][63] == 1.0 and sum(h["l"]) == 2.0)
fill(e.doc.layer(), "#FF0000", (0, 0, 200, 100)); e.doc.touch(e.doc.layer()); h = e.doc.histogram()
ok("pure red: red full, green and blue empty", h["r"][63] == 1.0 and h["g"][0] == 1.0 and h["b"][0] == 1.0 and h["g"][63] == 0.0)
e.addAdjustment("invert")
ok("for an adjustment: what it's given, and what it makes of it", e.histogram("r", "in")[63] == 1.0 and e.histogram("r", "out")[0] == 1.0 and e.histogram("g", "out")[63] == 1.0)
bars = e.histogram("rgb", "out"); again = e.histogram("rgb", "out")
ok("asked again with nothing changed, it isn't counted again", bars == again and e._hist[0][1] == e.doc.version)
e.closeDoc(); ok("no picture, no bars", e.histogram("rgb", "out") == [])
big, _ = fresh(3000, 2000)
t0 = time.time(); big.doc.histogram(); took = time.time() - t0
ok("on a 6-megapixel picture it's counted in a moment", took < 0.6, f"{took:.2f}s")

shutil.rmtree(home, ignore_errors=True)
print(f"{passed} passed, {failed} failed")
sys.stdout.flush(); os._exit(1 if failed else 0)
