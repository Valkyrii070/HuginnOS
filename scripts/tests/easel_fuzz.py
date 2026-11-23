"""Fuzz Easel's backend: random commands with sensible and senseless values, checking the picture stays whole and that
Undo really undoes. Usage: easel_fuzz.py /src [steps] [seed]"""
import os as _os, sys as _sys
if _os.geteuid() == 0:        # it saves, exports and opens at random: never as root
    _sys.exit("easel_fuzz.py: run this as an ordinary user (it refuses to run as root).")
import faulthandler, hashlib, math, os, random, sys, tempfile, time, traceback
faulthandler.enable()
home = tempfile.mkdtemp(prefix="easelfuzz-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/d", XDG_CONFIG_HOME=home + "/c", XDG_CACHE_HOME=home + "/k", QT_QPA_PLATFORM="offscreen")
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 1200
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 1
sys.path.insert(0, SRC + "/apps"); sys.path.insert(0, SRC + "/shell")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication, QImage
app = QGuiApplication(sys.argv[:1])
import numpy as np
import huginn_easel as ez, huginn_easel_ui as eu
random.seed(SEED)
e = eu.Easel(False, "")
said = []
e.said.connect(lambda m, bad: said.append(m))
e.newDoc(320, 240, "#FFFFFF")
problems, log = {}, []

def problem(kind, detail):
    kind = "".join("N" if ch.isdigit() else ch for ch in kind)[:150]
    if kind not in problems:
        problems[kind] = [0, detail[-1800:], " ; ".join(log[-6:])]
    problems[kind][0] += 1

def spin(ms=2):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

def settle(secs=20):
    end = time.time() + secs
    while e.busy and time.time() < end:
        spin(20)

WILD = [float("nan"), float("inf"), -float("inf"), 1e12, -1e12, 0, -1, 1e-9]
def num(lo, hi):
    return random.choice(WILD) if random.random() < 0.06 else random.uniform(lo, hi)
def whole(lo, hi):
    return random.choice([0, -1, -5, 10 ** 6, 2 ** 31]) if random.random() < 0.06 else random.randint(lo, hi)
def sides(hi):
    """A width and height: sensible, or one of them senseless (never both huge: a 16384-square picture is a gigabyte a layer)."""
    w, h = random.randint(1, hi), random.randint(1, hi)
    if random.random() < 0.1:
        if random.random() < 0.5:
            w, h = random.choice([0, -1, -5, 10 ** 6, 2 ** 31]), random.randint(1, 40)
        else:
            w, h = random.randint(1, 40), random.choice([0, -1, -5, 10 ** 6, 2 ** 31])
    return w, h
def px():
    d = e.doc
    return num(-40, (d.w if d else 300) + 40)
def py():
    d = e.doc
    return num(-40, (d.h if d else 300) + 40)
def ident():
    d = e.doc
    pool = [l["id"] for l in d.layers] if d else []
    return random.choice(pool + ["", "nope", "0" * 10] if pool else ["", "nope"])
def col():
    return random.choice(["#FF0000", "#00FF0080", "#123", "red", "", "not a colour", "#GGGGGG", "#FFFFFF", "#000000", "transparent"])
def word():
    return random.choice(["", "x", "normal", "multiply", "nope", "💥", "a" * 500, "\0", "..", "/"])
def pick(d):
    return random.choice(list(d)) if d and random.random() > 0.08 else word()

TOOLS = eu.PIXEL_TOOLS + eu.VECTOR_TOOLS
FILES = {}
def out_path():
    ext = random.choice([".easel", ".ora", ".psd", ".png", ".jpg", ".webp", ".svg", ".pdf", ".bmp", ".tiff", ".nope", ""])
    p = f"{home}/out{random.randrange(6)}{ext}"
    FILES[p] = 1
    return p
def in_path():
    made = [p for p in FILES if os.path.isfile(p)]
    return random.choice(made + [home, home + "/missing.png", "", "/dev/null"]) if made else random.choice([home + "/missing.png", ""])

def stroke():
    n = random.randint(0, 9)
    e.press(px(), py(), random.choice([1, 1, 1, 2, 4]), random.choice([0, 0, 0, 0x02000000, 0x04000000, 0x08000000]))
    for _ in range(n):
        e.move(px(), py(), random.choice([0, 0, 0x02000000]))
    if random.random() < 0.95:
        e.release(px(), py(), 0)

OPS = [
    (30, lambda: ("stroke",)),
    (8, lambda: ("setTool", random.choice(TOOLS + ["nope", ""]))),
    (2, lambda: ("setPersona", random.choice(["pixel", "vector", "nope"]))),
    (3, lambda: ("setColour", random.choice(["fg", "bg", "nope"]), col())),
    (1, lambda: ("swapColours",)),
    (2, lambda: ("setBrushPreset", pick(ez.BRUSHES))),
    (4, lambda: ("setBrush", random.choice(["size", "hardness", "opacity", "flow", "smoothing", "nope"]), num(0, 200))),
    (2, lambda: ("setPressure", num(0, 1))),
    (4, lambda: ("setOption", random.choice(["tolerance", "contiguous", "gradient", "gradientClear", "symmetry", "opacity", "pressure", "nope"]),
                 random.choice([num(0, 1), True, False, "x", "xy", "radial", "linear", "", None]))),
    (3, lambda: ("setStyle", random.choice(["fill", "stroke", "width", "radius", "points", "inner", "opacity", "nope"]), random.choice([col(), num(0, 50), None]))),
    (2, lambda: ("setTextStyle", random.choice(["font", "size", "weight", "italic", "align", "nope"]), random.choice(["Inter", num(1, 300), True, "center", None]))),
    (5, lambda: ("addLayer", random.choice(["pixel", "vector", "group", "nope"]))),
    (3, lambda: ("addAdjustment", pick(ez.ADJUSTMENTS))),
    (3, lambda: ("setAdjust", random.choice(["brightness", "contrast", "hue", "saturation", "lightness", "black", "white", "gamma", "levels", "vibrance", "nope"]), num(-1, 1))),
    (4, lambda: ("selectLayer", ident())),
    (5, lambda: ("setLayer", ident(), random.choice(["visible", "locked", "opacity", "blend", "name", "maskOn", "clip", "lockAlpha", "nope", "id", "kind", "image"]),
                 random.choice([True, False, num(0, 1), pick(ez.BLENDS), "name", None]))),
    (3, lambda: ("moveLayer", ident(), random.choice([-1, 1, 5, -5, 0]))),
    (2, lambda: ("dropLayer", ident(), ident())),
    (3, lambda: ("duplicateLayer",)),
    (3, lambda: ("deleteLayer",)),
    (2, lambda: ("rasterize",)),
    (3, lambda: ("mergeDown",)),
    (1, lambda: ("flatten",)),
    (2, lambda: ("addMask", random.choice(["reveal", "hide", "selection", "nope"]))),
    (1, lambda: ("deleteMask",)),
    (1, lambda: ("applyMask",)),
    (2, lambda: ("editMask", random.random() < 0.5)),
    (2, lambda: ("selectAll",)),
    (3, lambda: ("deselect",)),
    (2, lambda: ("invertSelection",)),
    (2, lambda: ("feather", num(0, 30))),
    (2, lambda: ("growSelection", whole(-20, 20))),
    (1, lambda: ("applyCrop",)),
    (1, lambda: ("cancelCrop",)),
    (2, lambda: ("canvasSize", *sides(500), random.choice(["c", "tl", "br", "t", "nope", ""]))),
    (2, lambda: ("imageSize", *sides(500))),
    (2, lambda: ("transformCanvas", random.choice(["cw", "ccw", "180", "fliph", "flipv", "nope"]))),
    (1, lambda: ("trim",)),
    (3, lambda: ("fillSelection",)),
    (1, lambda: ("fillAware",)),
    (2, lambda: ("clearSelection",)),
    (2, lambda: ("layerFromSelection", random.random() < 0.5)),
    (4, lambda: ("applyFilter", pick(ez.FILTERS), num(0, 1))),
    (2, lambda: ("copy", random.random() < 0.3)),
    (2, lambda: ("paste",)),
    (1, lambda: ("deleteShapes",)),
    (1, lambda: ("arrange", random.choice(["front", "back", "forward", "backward", "nope"]))),
    (1, lambda: ("align", random.choice(["left", "right", "top", "bottom", "hcentre", "vcentre", "nope"]))),
    (1, lambda: ("combine", random.choice(["unite", "subtract", "intersect", "exclude", "nope"]))),
    (2, lambda: ("finishPen",)),
    (2, lambda: ("setText", random.choice(["Hej", "", "två\nrader", "💥" * 40, "x" * 3000]))),
    (2, lambda: ("doneText",)),
    (3, lambda: ("escape",)),
    (2, lambda: ("nudge", num(-20, 20), num(-20, 20))),
    (3, lambda: ("startTransform",)),
    (3, lambda: ("applyTransform",)),
    (1, lambda: ("cancelTransform",)),
    (1, lambda: ("flipTransform", random.choice(["x", "y", "nope"]))),
    (2, lambda: ("setTransform", num(1, 300), num(1, 300), num(-360, 360))),
    (1, lambda: ("setHealSpot", random.random() < 0.5)),
    (1, lambda: ("deleteNode",)),
    (1, lambda: ("toggleSmooth",)),
    (1, lambda: ("outline",)),
    (2, lambda: ("setCurve", random.choice(["rgb", "r", "g", "b", "nope"]), random.choice([[[0, 0], [1, 1]], [[0, 1], [1, 0]], [], [[0.5, 0.5]], "junk", None, [[float("nan"), 2], [1, 1]], [[0, 0], [0, 1], [0, 0.5]]]))),
    (1, lambda: ("curveSamples", random.choice(["rgb", "r", "nope"]))),
    (3, lambda: ("clipLayer",)),
    (2, lambda: ("lockTransparency",)),
    (2, lambda: ("strokeSelection", num(0, 60), random.choice(["inside", "outside", "centre", "nope"]))),
    (3, lambda: ("groupLayer",)),
    (2, lambda: ("ungroup",)),
    (1, lambda: ("toggleOpen", ident())),
    (1, lambda: ("markFx",)),
    (3, lambda: ("setFx", random.choice(["shadow", "glow", "outline", "inner", "overlay", "nope"]), random.choice(["on", "colour", "opacity", "size", "distance", "angle", "spread", "where", "nope"]),
                 random.choice([True, False, col(), num(0, 60), "inside", "centre", None]))),
    (1, lambda: ("clearFx",)),
    (2, lambda: ("convertToSmart",)),
    (2, lambda: ("placeFile", in_path())),
    (1, lambda: ("toggleSmartFilter", whole(0, 3))),
    (1, lambda: ("removeSmartFilter", whole(0, 3))),
    (1, lambda: ("setSmartFilter", whole(0, 3), num(0, 1))),
    (2, lambda: ("setRetouch", random.choice(["tool", "range", "strength", "liquify", "liquifyStrength", "smudge", "nope"]), random.choice(["dodge", "burn", "sponge", "soften", "sharpen", "mid", "shadows", "push", "twirl", "bloat", num(0, 1), None]))),
    (2, lambda: ("addGuide", random.choice(["x", "y", "nope"]), num(-50, 600))),
    (1, lambda: ("moveGuide", whole(0, 4), num(-50, 600))),
    (1, lambda: ("removeGuide", whole(0, 4))),
    (1, lambda: ("clearGuides",)),
    (1, lambda: ("setSnap", random.random() < 0.5)),
    (1, lambda: ("textOnPath",)),
    (1, lambda: ("textOffPath",)),
    (1, lambda: ("setPathOffset", num(-200, 200))),
    (1, lambda: ("hover", px(), py())),
    (2, lambda: ("doubleClick", px(), py())),
    (10, lambda: ("undo",)),
    (5, lambda: ("redo",)),
    (1, lambda: ("historyTo", whole(0, 30))),
    (2, lambda: ("saveAs", out_path())),
    (1, lambda: ("save",)),
    (2, lambda: ("exportAs", out_path(), whole(1, 100))),
    (2, lambda: ("open", in_path())),
    (1, lambda: ("newDoc", *sides(400), random.choice(["#FFFFFF", "", "transparent", "junk"]))),
    (0.3, lambda: ("closeDoc",)),
    (3, lambda: ("UNDOCHECK",)),
    (2, lambda: ("ROUNDTRIP",)),
]
weights = [w for w, _ in OPS]

def digest(img):
    if img is None or img.isNull():
        return "null"
    a = ez.image_to_array(img)
    return hashlib.sha1(a.tobytes()).hexdigest()[:16] + f" {img.width()}x{img.height()}"

def picture():
    return digest(e.doc.flattened()) if e.doc else "none"

def check(op):
    d = e.doc
    if d is None:
        return
    if not (0 < d.w <= 20000 and 0 < d.h <= 20000):
        problem("the picture's size went wrong", f"{op[0]}: {d.w}x{d.h}")
        return
    if not d.layers:
        problem("no layers left", op[0]); return
    if d.index(d.active) < 0:
        problem("the active layer isn't one of the layers", op[0])
    ids = [l["id"] for l in d.layers]
    if len(set(ids)) != len(ids):
        problem("two layers share an id", op[0])
    for l in d.layers:
        if l["kind"] == "pixel" and "source" not in l:
            im = l.get("image")
            if im is None or im.isNull() or im.width() != d.w or im.height() != d.h:
                problem("a pixel layer isn't the picture's size", f"{op[0]}: {None if im is None else (im.width(), im.height())} in {d.w}x{d.h}; transform {'open' if e._xform else 'no'}, crop {e._crop is not None}, pen {e._pen is not None}, drag {e._drag and e._drag.get('kind')}")
        m = l.get("mask")
        if m is not None and (m.isNull() or m.width() != d.w or m.height() != d.h):
            problem("a mask isn't the picture's size", f"{op[0]}: {(m.width(), m.height())} in {d.w}x{d.h}")
        o = l.get("opacity", 1.0)
        if not isinstance(o, (int, float)) or not (0.0 <= o <= 1.0):
            problem("a layer's opacity is out of range", f"{op[0]}: {o!r}")
        if not isinstance(l.get("name"), str) or not isinstance(l.get("visible"), bool) or l.get("kind") not in ("pixel", "vector", "adjust", "group", "smart"):
            problem("a layer's own fields were overwritten", f"{op[0]}: name {l.get('name')!r} visible {l.get('visible')!r} kind {l.get('kind')!r}")
    s = d.selection
    if s is not None and (s.isNull() or s.width() != d.w or s.height() != d.h):
        problem("the selection isn't the picture's size", op[0])
    try:
        flat = d.flattened()
        if flat.isNull() or flat.width() != d.w or flat.height() != d.h:
            problem("the finished picture is the wrong size", op[0])
    except Exception:
        problem(f"drawing the picture after {op[0]}", traceback.format_exc())
    for name in ("layers", "history", "transformInfo", "activeLayer"):
        try:
            getattr(e, name)
        except Exception:
            problem(f"reading {name} after {op[0]}", traceback.format_exc())

def rss():
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * 4096 // (1 << 20)

t0 = time.time()
undo_checks = trips = 0
for n in range(STEPS):
    op = random.choices(OPS, weights)[0][1]()
    log.append(repr(op)[:140])
    open(home + "/now.txt", "w").write(f"{n} {op!r}\n" + "\n".join(log[-8:]))
    faulthandler.dump_traceback_later(40, file=sys.stdout)   # (a command that never returns: say where it is)
    t1 = time.time()
    try:
        if op[0] == "stroke":
            stroke()
        elif op[0] == "UNDOCHECK":
            # one thing done and undone leaves the picture exactly as it was
            if e.doc and not e._drag and not e._xform and not e._crop and not e._pen and not e.busy:
                e.doneText(); e.escape(); settle(); before, depth = picture(), len(e._undo)
                inner = random.choice([("applyFilter", pick(ez.FILTERS), 0.5), ("fillSelection",), ("stroke",), ("addLayer", "pixel"), ("duplicateLayer",), ("mergeDown",), ("flatten",),
                                       ("transformCanvas", "cw"), ("imageSize", 200, 150), ("canvasSize", 300, 300, "c"), ("deleteLayer",), ("groupLayer",), ("addAdjustment", "bw"),
                                       ("clearSelection",), ("layerFromSelection", True), ("clipLayer",), ("lockTransparency",), ("strokeSelection", 6, "centre"), ("convertToSmart",), ("rasterize",), ("trim",), ("addMask", "hide"), ("applyMask",)])
                log.append("  inner " + repr(inner))
                stroke() if inner[0] == "stroke" else getattr(e, inner[0])(*inner[1:])
                settle()
                grew = len(e._undo) - depth
                if grew == 1 and not e._xform and not e._drag:
                    e.undo(); settle()
                    undo_checks += 1
                    if picture() != before:
                        problem(f"undo after {inner[0]} doesn't give the picture back", f"{inner!r}")
                    e.redo()
                elif grew > 1:
                    problem(f"{inner[0]} made more than one step of undo", f"{inner!r}: {grew}: {[name for name, _ in e._undo[-grew:]]}; tool {e.tool}")
        elif op[0] == "ROUNDTRIP":
            # saved in Easel's own format and opened again, the picture is the same
            if e.doc and not e._drag and not e._xform and not e.busy:
                e.escape(); settle(); before = picture(); layers = len(e.doc.layers)
                p = f"{home}/trip.easel"
                if e.saveAs(p):
                    e.open(p); settle(); trips += 1
                    if e.doc is None:
                        problem("a saved picture didn't open again", "")
                    elif picture() != before:
                        problem("a picture saved and opened isn't the same", f"{layers} layers before, {len(e.doc.layers)} after: " + ", ".join(f"{l['kind']}{'+fx' if l.get('fx') else ''}{'+smart' if l.get('source') is not None else ''}{'+mask' if l.get('mask') is not None else ''}{'+clip' if l.get('clip') else ''}:{l['blend']}" for l in e.doc.layers))
        else:
            getattr(e, op[0])(*op[1:])
    except MemoryError:
        problem(f"{op[0]} ran out of memory", repr(op)[:200])
    except Exception:
        problem(f"{op[0]} raised", traceback.format_exc())
    faulthandler.cancel_dump_traceback_later()
    took = time.time() - t1
    if took > 4:
        problem(f"{op[0]} took long", f"{took:.1f}s: {op!r}"[:300])
    spin(1)
    if n % 3 == 0:
        try:
            check(op)
        except Exception:
            problem(f"checking after {op[0]}", traceback.format_exc())
    if e.doc is not None and max(e.doc.w, e.doc.h) > 1500:     # (a huge size asked for is held to the limit: fine, but too slow to go on fuzzing at)
        if max(e.doc.w, e.doc.h) > ez.SIDE_LIMIT:
            problem("a picture got past the size limit", f"{op!r}: {e.doc.w}x{e.doc.h}")
        e.newDoc(300, 200, "#FFFFFF")
    if e.doc is None and random.random() < 0.7:
        e.newDoc(random.randint(40, 360), random.randint(40, 300), "#FFFFFF")
    if n % 200 == 0:
        print(f"step {n}: {len(e.doc.layers) if e.doc else 0} layers, {len(problems)} kinds of problem, {rss()} MB, {time.time() - t0:.0f}s", flush=True)
        if e.doc and len(e.doc.layers) > 14:
            e.flatten()
settle()
e._drop_drag()
print(f"\n{STEPS} steps, seed {SEED}: {undo_checks} undo checks, {trips} save-and-open checks, {rss()} MB, {len(problems)} kinds of problem")
for kind, (count, detail, last) in sorted(problems.items(), key=lambda kv: -kv[1][0]):
    print(f"\n=== x{count}  {kind}\n    " + detail.strip().replace("\n", "\n    ") + f"\n    last steps: {last}")
sys.stdout.flush()
os._exit(1 if problems else 0)    # (leaving at once: a fill still working in the background mustn't outlive the app)
