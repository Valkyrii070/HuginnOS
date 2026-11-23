"""How Easel holds up on a big picture: how long the things you wait for take, and what it keeps in memory.
Usage: easel_speed_check.py /src [width height]   (prints timings; nothing is asserted)"""
import os as _os, sys as _sys
if _os.geteuid() == 0:
    _sys.exit("run this as an ordinary user")
import gc, os, sys, tempfile, time
home = tempfile.mkdtemp(prefix="easelspeed-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/d", XDG_CONFIG_HOME=home + "/c", QT_QPA_PLATFORM="offscreen")
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
W, H = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (4000, 3000)
sys.path.insert(0, SRC + "/apps"); sys.path.insert(0, SRC + "/shell")
from PySide6.QtGui import QGuiApplication, QPainter, QColor
app = QGuiApplication(sys.argv[:1])
import huginn_easel as ez, huginn_easel_ui as eu
def rss():
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * 4096 // (1 << 20)
def timed(label, fn, n=1):
    t = time.time()
    for _ in range(n):
        out = fn()
    ms = (time.time() - t) * 1000 / n
    print(f"  {label:54s} {ms:8.0f} ms" + (f"   ({rss()} MB)" if ms > 300 else ""), flush=True)
    return out
def stroke(e, y, frames=True):
    """A stroke across the picture: returns the slowest and the mean frame (a move plus drawing the canvas)."""
    e.press(100, y, 1, 0); times = []
    for k in range(1, 41):
        t = time.time(); e.move(100 + k * (W - 200) / 40, y + (40 if k % 2 else -40), 0)
        if frames: e.render()
        times.append((time.time() - t) * 1000)
    t = time.time(); e.release(W - 100, y, 0); e.render(); rel = (time.time() - t) * 1000
    return max(times), sum(times) / len(times), rel

print(f"{W} x {H}, memory at the start {rss()} MB")
e = eu.Easel(False, "")
timed("new picture", lambda: e.newDoc(W, H, "#FFFFFF"))
e.setTool("brush"); e.setBrush("size", 40)
print("one layer:")
mx, mean, rel = stroke(e, H * 0.2); print(f"  {'a brush stroke: each frame':54s} {mean:8.0f} ms   (slowest {mx:.0f}, letting go {rel:.0f})")
for _ in range(5):
    e.addLayer("pixel"); stroke(e, H * (0.2 + 0.1 * _), frames=False)
e.selectLayer(e.doc.layers[2]["id"])
print("six layers, painting on the third:")
mx, mean, rel = stroke(e, H * 0.5); print(f"  {'a brush stroke: each frame':54s} {mean:8.0f} ms   (slowest {mx:.0f}, letting go {rel:.0f})")
timed("the whole picture put together", lambda: e.doc.composite(), 3)
e.selectLayer(e.doc.layers[-1]["id"]); e.addAdjustment("colour"); e.setAdjust("hue", 0.2); e.selectLayer(e.doc.layers[2]["id"])
print("…with an adjustment layer on top:")
mx, mean, rel = stroke(e, H * 0.55); print(f"  {'a brush stroke: each frame':54s} {mean:8.0f} ms   (slowest {mx:.0f}, letting go {rel:.0f})")
timed("the whole picture put together", lambda: e.doc.composite(), 2)
e.selectLayer(e.doc.layers[3]["id"]); e.markFx(); e.setFx("shadow", "on", True); e.selectLayer(e.doc.layers[2]["id"])
print("…and a drop shadow on the layer above:")
mx, mean, rel = stroke(e, H * 0.6); print(f"  {'a brush stroke: each frame':54s} {mean:8.0f} ms   (slowest {mx:.0f}, letting go {rel:.0f})")
e.selectLayer(e.doc.layers[4]["id"]); e.clipLayer(); e.selectLayer(e.doc.layers[2]["id"])
print("…and the layer above that clipped:")
mx, mean, rel = stroke(e, H * 0.65); print(f"  {'a brush stroke: each frame':54s} {mean:8.0f} ms   (slowest {mx:.0f}, letting go {rel:.0f})")
print("commands:")
timed("Undo", e.undo); timed("Redo", e.redo)
timed("Blur", lambda: e.applyFilter("blur", 0.4)); timed("Sharpen", lambda: e.applyFilter("sharpen", 0.4))
e.setTool("select"); e.press(W * 0.3, H * 0.3, 1, 0); e.move(W * 0.6, H * 0.6, 0); e.release(W * 0.6, H * 0.6, 0)
timed("Feather the selection 20 px", lambda: e.feather(20)); timed("Fill the selection", e.fillSelection); timed("Outline the selection", lambda: e.strokeSelection(8, "centre"))
timed("Deselect", e.deselect)
e.setTool("fill"); timed("Bucket fill", lambda: (e.press(W * 0.8, H * 0.9, 1, 0), e.release(W * 0.8, H * 0.9, 0)))
e.setTool("wand"); timed("Magic wand", lambda: (e.press(W * 0.1, H * 0.9, 1, 0), e.release(W * 0.1, H * 0.9, 0))); e.deselect()
timed("Free transform: start", e.startTransform); timed("  …turn and show", lambda: (e.setTransform(80, 80, 15), e.render())); timed("  …apply", e.applyTransform)
timed("Move the layer (one step of a drag)", lambda: (e.setTool("move"), e.press(50, 50, 1, 0), e.move(80, 70, 0), e.render(), e.release(80, 70, 0)))
timed("Rotate the canvas", lambda: e.transformCanvas("cw")); e.undo()
timed("Layer list for the window", lambda: e.layers, 3)
p = home + "/big.easel"
timed("Save", lambda: e.saveAs(p)); print(f"  {'':54s} {os.path.getsize(p) / 1e6:8.1f} MB on disk")
timed("Export PNG", lambda: e.exportAs(home + "/big.png", 90)); timed("Export JPEG", lambda: e.exportAs(home + "/big.jpg", 90)); timed("Export Photoshop", lambda: e.exportAs(home + "/big.psd", 90))
steps = len(e._undo); print(f"memory with {steps} steps of undo kept: {rss()} MB")
for k in range(30):
    stroke(e, H * (0.1 + 0.02 * k), frames=False)
print(f"memory after 30 more strokes ({len(e._undo)} steps kept): {rss()} MB")
timed("Open what was saved", lambda: e.open(p)); gc.collect()
print(f"memory after opening it afresh: {rss()} MB")
e.closeDoc(); gc.collect(); print(f"memory with the picture closed: {rss()} MB")
base = rss()
for k in range(6):
    e.open(p); e.closeDoc()
gc.collect(); print(f"…and after opening and closing it six more times: {rss()} MB  ({rss() - base:+d})")
sys.stdout.flush(); os._exit(0)
