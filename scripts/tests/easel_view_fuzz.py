"""Fuzz Easel's canvas itself: the item that draws the picture and turns the mouse, the wheel and the keys into
painting. Random presses, drags, wheel turns, keys and resizes, with the canvas drawn after each: nothing may raise,
and what it draws must be the picture Easel holds.  Usage: easel_view_fuzz.py /src [steps] [seed]"""
import os as _os, sys as _sys
if _os.geteuid() == 0:
    _sys.exit("easel_view_fuzz.py: run this as an ordinary user (it refuses to run as root).")
import faulthandler, os, random, sys, tempfile, time, traceback
faulthandler.enable()
home = tempfile.mkdtemp(prefix="easelview-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/d", XDG_CONFIG_HOME=home + "/c", QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 1
sys.path.insert(0, SRC + "/apps"); sys.path.insert(0, SRC + "/shell")
from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QGuiApplication, QHoverEvent, QImage, QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtQuick import QQuickWindow
app = QGuiApplication(sys.argv[:1])
import numpy as np
import huginn_easel as ez, huginn_easel_ui as eu
random.seed(SEED)
win = QQuickWindow(); win.resize(900, 640)
e = eu.Easel(True, "")                                   # the demo picture: layers, shapes, type, an adjustment
view = eu.EaselView(win.contentItem()); view.setWidth(900); view.setHeight(640)
view.backend = e
win.show()
problems, log = {}, []
def problem(kind, detail):
    kind = "".join("N" if ch.isdigit() else ch for ch in kind)[:150]
    problems.setdefault(kind, [0, detail[-1600:], " ; ".join(log[-6:])])[0] += 1
def spin(ms=1):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()
WILD = [float("nan"), float("inf"), -1e9, 1e9]
def pos():
    if random.random() < 0.03:
        return QPointF(random.choice(WILD), random.choice(WILD))
    return QPointF(random.uniform(-30, view.width() + 30), random.uniform(-30, view.height() + 30))
BUTTONS = [Qt.MouseButton.LeftButton] * 6 + [Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton]
MODS = [Qt.KeyboardModifier.NoModifier] * 6 + [Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.AltModifier, Qt.KeyboardModifier.ControlModifier,
                                               Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier]
KEYS = [getattr(Qt.Key, "Key_" + k) for k in "A B C D E F G H I J K L M N O P Q R S T U V W X Y Z 0 1 5 9 Space Delete Backspace Escape Return Enter Left Right Up Down BracketLeft BracketRight Tab Slash".split()]
down = [None]
def mouse(kind, p, button, mods):
    held = down[0] or Qt.MouseButton.NoButton
    return QMouseEvent(kind, p, p, button, held if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton, mods)
def do_press():
    b, m, p = random.choice(BUTTONS), random.choice(MODS), pos()
    down[0] = b; view.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, p, b, m))
def do_move():
    p = pos(); view.mouseMoveEvent(mouse(QEvent.Type.MouseMove, p, Qt.MouseButton.NoButton, random.choice(MODS)))
def do_release():
    b = down[0] or Qt.MouseButton.LeftButton; down[0] = None
    view.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, pos(), b, random.choice(MODS)))
def do_drag():
    do_press()
    for _ in range(random.randint(0, 6)):
        do_move()
    if random.random() < 0.95:
        do_release()
def do_double():
    p = pos(); view.mouseDoubleClickEvent(mouse(QEvent.Type.MouseButtonDblClick, p, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
def do_hover():
    p = pos(); view.hoverMoveEvent(QHoverEvent(QEvent.Type.HoverMove, p, p, p))
def do_leave():
    p = pos(); view.hoverLeaveEvent(QHoverEvent(QEvent.Type.HoverLeave, p, p, p))
def do_wheel():
    p = pos(); dy = random.choice([120, -120, 15, -15, 0, 1200, -2400, 10 ** 7])
    view.wheelEvent(QWheelEvent(p, p, QPoint(0, 0), QPoint(random.choice([0, 0, 120, -120]), dy), Qt.MouseButton.NoButton, random.choice(MODS), Qt.ScrollPhase.NoScrollPhase, False))
def do_key():
    k, m = random.choice(KEYS), random.choice(MODS)
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, k, m, "", random.random() < 0.1))
    if random.random() < 0.9:
        view.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, k, m))
def do_resize():
    view.setWidth(random.choice([900, 400, 60, 5, 0, 1600, 2500])); view.setHeight(random.choice([640, 300, 40, 3, 0, 1100]))
def do_zoom():
    random.choice([view.fit, view.actualSize, lambda: view.setZoom(random.choice([0.001, 0.05, 0.5, 3, 16, 64, 1e9, float("nan"), -2, 0]))])()
def do_pads():
    view.setPads(*[random.choice([0, 60, 300, 2000, -50, float("nan")]) for _ in range(4)])
def do_backend():
    random.choice([lambda: e.setTool(random.choice(eu.PIXEL_TOOLS + eu.VECTOR_TOOLS)), lambda: e.setPersona(random.choice(["pixel", "vector"])), e.undo, e.redo, e.selectAll, e.deselect,
                   lambda: e.setRulers(random.random() < 0.5), lambda: e.addGuide(random.choice("xy"), random.uniform(0, 900)), e.startTransform, e.applyTransform, e.escape,
                   lambda: e.selectLayer(random.choice(e.doc.layers)["id"]) if e.doc else None, lambda: e.addLayer("pixel"), lambda: e.setSnap(random.random() < 0.5),
                   lambda: e.newDoc(random.choice([1, 3, 40, 300, 2000]), random.choice([1, 2, 30, 200, 1500]), "#FFFFFF"), lambda: e.setOption("symmetry", random.choice(["", "x", "y", "xy"])),
                   lambda: e.setBrush("size", random.choice([1, 8, 60, 400, 1000])), lambda: e.imageSize(random.randint(1, 600), random.randint(1, 500)), e.closeDoc if random.random() < 0.1 else e.flatten])()
OPS = [(30, do_drag), (6, do_press), (10, do_move), (6, do_release), (4, do_double), (10, do_hover), (2, do_leave), (10, do_wheel), (14, do_key), (3, do_resize), (4, do_zoom), (1, do_pads), (10, do_backend)]
weights = [w for w, _ in OPS]
canvas = QImage(900, 640, QImage.Format.Format_ARGB32_Premultiplied)
t0 = time.time(); paints = compared = 0
for n in range(STEPS):
    op = random.choices(OPS, weights)[0][1]
    log.append(op.__name__)
    with open(home + "/now.txt", "w") as f:
        f.write(f"{n} " + " ".join(log[-8:]))
    faulthandler.dump_traceback_later(40, file=sys.stdout)
    t1 = time.time()
    try:
        op()
    except Exception:
        problem(f"{op.__name__} raised", traceback.format_exc())
    try:                                                 # and the canvas draws, whatever state that left it in
        w, h = max(1, min(3000, int(view.width() or 1))), max(1, min(3000, int(view.height() or 1)))
        if canvas.width() != w or canvas.height() != h:
            canvas = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(0)
        p = QPainter(canvas)
        try:
            view.paint(p)
        finally:
            p.end()
        paints += 1
        if e.doc and not view._img.isNull() and e._drag is None and e._xform is None and n % 5 == 0:
            compared += 1
            if view._img.size() != e.doc.composite(e._live).size():
                problem("the canvas holds a picture of the wrong size", f"{view._img.width()}x{view._img.height()} for {e.doc.w}x{e.doc.h}")
            elif ez.image_to_array(view._img).tobytes() != ez.image_to_array(e.render()).tobytes():
                problem("the canvas shows a picture that isn't the one Easel holds", op.__name__)
        z = view._zoom
        if not (isinstance(z, float) and 0.01 <= z <= 64.0) or not all(isinstance(v, (int, float)) and v == v and abs(v) < 1e12 for v in (view._ox, view._oy)):
            problem("the zoom or the picture's place on the canvas went wrong", f"{op.__name__}: zoom {z!r} at {view._ox!r}, {view._oy!r}")
            view.fit()
    except Exception:
        problem(f"drawing the canvas after {op.__name__} raised", traceback.format_exc())
    faulthandler.cancel_dump_traceback_later()
    if time.time() - t1 > 5:
        problem(f"{op.__name__} took long", f"{time.time() - t1:.1f}s")
    spin(1)
    if e.doc is None and random.random() < 0.8:
        e.newDoc(320, 240, "#FFFFFF")
    if e.doc and (len(e.doc.layers) > 12 or max(e.doc.w, e.doc.h) > 2500):
        e.newDoc(400, 300, "#FFFFFF")
    if n % 300 == 0:
        print(f"step {n}: {len(problems)} kinds of problem, {time.time() - t0:.0f}s", flush=True)
print(f"\n{STEPS} steps, seed {SEED}: the canvas drawn {paints} times, checked against the picture {compared} times, {len(problems)} kinds of problem")
for kind, (count, detail, last) in sorted(problems.items(), key=lambda kv: -kv[1][0]):
    print(f"\n=== x{count}  {kind}\n    " + detail.strip().replace("\n", "\n    ") + f"\n    last steps: {last}")
sys.stdout.flush(); os._exit(1 if problems else 0)
