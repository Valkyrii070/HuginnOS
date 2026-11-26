"""How faithfully each file format carries a picture out of Easel and back. One feature at a time (each blend mode, a
mask, a clipped layer, a group, a style…): saved, opened again, and compared with what Easel showed.
Usage: easel_formats_check.py /src   (prints a table; exits 1 if Easel's own format isn't exact)"""
import os as _os, sys as _sys
if _os.geteuid() == 0:
    _sys.exit("run this as an ordinary user")
import os, sys, tempfile
home = tempfile.mkdtemp(prefix="easelfmt-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/d", XDG_CONFIG_HOME=home + "/c", QT_QPA_PLATFORM="offscreen")
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
sys.path.insert(0, SRC + "/apps"); sys.path.insert(0, SRC + "/shell")
from PySide6.QtGui import QGuiApplication, QPainter, QColor, QLinearGradient, QImage
app = QGuiApplication(sys.argv[:1])
import numpy as np
import huginn_easel as ez, huginn_easel_ui as eu

def base():
    e = eu.Easel(False, ""); e.newDoc(120, 90, "#FFFFFF")
    l = e.doc.layer(); p = QPainter(l["image"])
    g = QLinearGradient(0, 0, 120, 90); g.setColorAt(0, QColor("#2060E0")); g.setColorAt(1, QColor("#F0C020")); p.fillRect(0, 0, 120, 90, g); p.end(); e.doc.touch(l)
    return e
def blob(e, colour="#E03060", alpha=255, box=(30, 20, 60, 50)):
    e.addLayer("pixel"); l = e.doc.layer(); p = QPainter(l["image"]); c = QColor(colour); c.setAlpha(alpha)
    p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setBrush(c); p.setPen(QColor(0, 0, 0, 0)); p.drawEllipse(*box); p.end(); e.doc.touch(l); return l

CASES = {}
def case(name):
    def wrap(fn): CASES[name] = fn; return fn
    return wrap
case("one layer")(lambda e: None)
case("a soft-edged layer")(lambda e: blob(e))
case("half see-through paint")(lambda e: blob(e, alpha=128))
case("layer opacity 40%")(lambda e: (blob(e), e.setLayer(e.doc.active, "opacity", 0.4)))
case("a hidden layer")(lambda e: (blob(e), e.setLayer(e.doc.active, "visible", False)))
for mode in ez.BLENDS:
    if mode != "normal":
        case(f"blend: {mode}")(lambda e, mode=mode: (blob(e), e.setLayer(e.doc.active, "blend", mode)))
def with_mask(e):
    blob(e); e.setTool("select"); e.press(30, 20, 1, 0); e.move(60, 70, 0); e.release(60, 70, 0); e.addMask("selection"); e.deselect()
case("a mask")(with_mask)
case("a clipped layer")(lambda e: (blob(e), blob(e, "#20C040", box=(50, 10, 60, 70)), e.clipLayer()))
case("a group at 50%")(lambda e: (blob(e), e.groupLayer(), e.setLayer(e.doc.active, "opacity", 0.5)))
case("a group that multiplies")(lambda e: (blob(e), e.groupLayer(), e.setLayer(e.doc.active, "blend", "multiply")))
case("an adjustment layer")(lambda e: (blob(e), e.addAdjustment("colour"), e.setAdjust("hue", 0.4)))
case("a drop shadow")(lambda e: (blob(e), e.markFx(), e.setFx("shadow", "on", True)))
case("a smart object, turned")(lambda e: (blob(e), e.convertToSmart(), e.startTransform(), e.setTransform(70, 70, 25), e.applyTransform()))
def vec(e):
    e.addLayer("vector"); e.setPersona("vector"); e.setTool("rect"); e.press(20, 20, 1, 0); e.move(90, 60, 0); e.release(90, 60, 0)
    e.setTool("ellipse"); e.press(50, 30, 1, 0); e.move(110, 80, 0); e.release(110, 80, 0); e.setPersona("pixel")
case("shapes")(vec)
def txt(e):
    e.addLayer("vector"); e.setPersona("vector"); e.setTextStyle("size", 28); e.setTool("text"); e.press(10, 30, 1, 0); e.release(10, 30, 0); e.setText("Hej då"); e.doneText(); e.setPersona("pixel")
case("type")(txt)
case("an adjustment in a group")(lambda e: (blob(e), e.groupLayer(), e.addAdjustment("colour"), e.setAdjust("hue", 0.4), blob(e, "#20C040", box=(5, 5, 30, 30))))
case("clipped to a group")(lambda e: (blob(e), e.groupLayer(), e.selectLayer(e.doc.layers[-1]["id"]), e.addLayer("pixel"), None))
def clip_group(e):
    blob(e); e.groupLayer(); g = e.doc.active
    blob(e, "#20C040", box=(50, 10, 60, 70)); top = e.doc.active
    e.doc.layer(top).pop("group", None); import huginn_easel_more as more
    e.doc.layers = more.normalize(e.doc.layers); e.selectLayer(top); e.setLayer(top, "clip", True)
CASES["clipped to a group"] = clip_group
case("two layers in a group at 50%")(lambda e: (blob(e), e.groupLayer(), blob(e, "#20C040", box=(50, 10, 60, 70)), e.setLayer(e.doc.layer(e.doc.active).get("group") or e.doc.active, "opacity", 0.5)))
case("a clipped adjustment")(lambda e: (blob(e), e.addAdjustment("colour"), e.setAdjust("hue", 0.4), e.clipLayer()))
case("shapes over a multiply layer")(lambda e: (blob(e), e.setLayer(e.doc.active, "blend", "multiply"), vec(e)))

def diff(a: QImage, b: QImage, over_white=False):
    if a.size() != b.size():
        return f"size {b.width()}x{b.height()}"
    def arr(img):
        if over_white:
            flat = ez.new_image(img.width(), img.height(), "#FFFFFF"); p = QPainter(flat); p.drawImage(0, 0, img); p.end(); img = flat
        return ez.image_to_array(img.convertToFormat(ez.FMT)).astype(np.int16)
    d = np.abs(arr(a) - arr(b))
    return int(d.max()), float(d.mean())

FORMATS = [(".easel", False), (".psd", False), (".ora", False), (".png", False), (".tiff", False), (".webp", False), (".bmp", True), (".jpg", True), (".svg", False), (".pdf", True)]
print(f"{'':28s}" + "".join(f"{ext:>9s}" for ext, _ in FORMATS))
bad_own, notes = 0, {}
for name, build in CASES.items():
    e = base(); said = []; e.said.connect(lambda m, b: said.append(m)); build(e)
    want = e.doc.flattened()
    row = f"{name:28s}"
    for ext, white in FORMATS:
        p = f"{home}/t{ext}"
        if os.path.exists(p): os.remove(p)
        e.saveAs(p) if ext == ".easel" else e.exportAs(p, 100)
        try:
            if ext == ".svg":                                    # (opened in Easel a small drawing is drawn bigger: compare at its own size)
                from PySide6.QtSvg import QSvgRenderer
                from PySide6.QtCore import QRectF
                got = ez.new_image(want.width(), want.height()); qp = QPainter(got); QSvgRenderer(p).render(qp, QRectF(0, 0, want.width(), want.height())); qp.end()
            else:
                got = ez.open_any(p).flattened()
            d = diff(want, got, white)
        except Exception as err:
            d = "ERR " + type(err).__name__
        if isinstance(d, tuple):
            cell = "exact" if d[0] == 0 else f"{d[0]}" if d[0] <= 3 else f"{d[0]}!" if ext in (".easel", ".psd", ".ora", ".png", ".tiff") else f"~{d[0]}"
            if ext == ".easel" and d[0] > 0: bad_own += 1
            if d[0] > 3 and ext in (".psd", ".ora", ".png", ".tiff", ".bmp"): notes.setdefault(ext, []).append(f"{name} (off by up to {d[0]}, mean {d[1]:.1f})")
        else:
            cell = d[:8]
            notes.setdefault(ext, []).append(f"{name}: {d}")
        row += f"{cell:>9s}"
    print(row, flush=True)
print()
for ext, items in notes.items():
    print(f"{ext}: " + "; ".join(items))
sys.stdout.flush(); os._exit(1 if bad_own else 0)
