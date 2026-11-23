"""Fuzz the files Easel opens: its own, OpenRaster, Photoshop and plain pictures, damaged at random and built to be
hostile (huge sizes, missing parts, wrong types). Opening one must either work or say why not: never crash, hang or
eat the machine's memory.  Usage: easel_files_fuzz.py /src [rounds] [seed]"""
import os as _os, sys as _sys
if _os.geteuid() == 0:
    _sys.exit("easel_files_fuzz.py: run this as an ordinary user (it refuses to run as root).")
import faulthandler, io, json, os, random, struct, sys, tempfile, time, traceback, zipfile
faulthandler.enable()
home = tempfile.mkdtemp(prefix="easelfiles-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/d", XDG_CONFIG_HOME=home + "/c", QT_QPA_PLATFORM="offscreen")
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 400
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 1
sys.path.insert(0, SRC + "/apps"); sys.path.insert(0, SRC + "/shell")
from PySide6.QtGui import QGuiApplication, QPainter, QColor
app = QGuiApplication(sys.argv[:1])
import huginn_easel as ez, huginn_easel_ui as eu
random.seed(SEED)
problems = {}
def problem(kind, detail):
    kind = "".join("N" if ch.isdigit() else ch for ch in kind)[:160]
    problems.setdefault(kind, [0, detail[-1500:]])[0] += 1
def rss():
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * 4096 // (1 << 20)

# ---- a rich picture to start from, saved every way
e = eu.Easel(False, ""); said = []
e.said.connect(lambda m, bad: said.append(m))
e.newDoc(160, 120, "#FFFFFF")
e.setTool("brush"); e.press(10, 10, 1, 0); e.move(120, 90, 0); e.release(120, 90, 0)
e.addLayer("pixel"); e.press(30, 80, 1, 0); e.move(140, 20, 0); e.release(140, 20, 0); e.clipLayer()
e.addMask("reveal"); e.addAdjustment("colour"); e.addLayer("vector"); e.setPersona("vector")
e.setTool("rect"); e.press(20, 20, 1, 0); e.move(90, 70, 0); e.release(90, 70, 0)
e.setTool("text"); e.press(30, 40, 1, 0); e.release(30, 40, 0); e.setText("Hej"); e.doneText()
e.setPersona("pixel"); e.addLayer("pixel"); e.groupLayer(); e.markFx(); e.setFx("shadow", "on", True)
e.addLayer("pixel"); e.press(60, 60, 1, 0); e.move(70, 70, 0); e.release(70, 70, 0); e.convertToSmart(); e.applyFilter("blur", 0.3)
seeds = {}
for ext in (".easel", ".ora", ".psd", ".png", ".jpg", ".webp", ".bmp", ".tiff", ".svg", ".pdf"):
    p = home + "/seed" + ext
    if ext == ".easel":
        e.saveAs(p)
    else:
        e.exportAs(p, 80)
    if os.path.isfile(p):
        seeds[ext] = open(p, "rb").read()
    else:
        problem(f"couldn't write a {ext} to start from", "; ".join(said[-2:]))
print("seeds:", {k: len(v) for k, v in seeds.items()}, flush=True)

def mutate(raw: bytes) -> bytes:
    b = bytearray(raw)
    how = random.random()
    if how < 0.35:                                   # a few bytes changed
        for _ in range(random.randint(1, 8)):
            if b:
                b[random.randrange(len(b))] = random.choice([0, 255, random.randrange(256), 0x7F, 0x80])
    elif how < 0.5:                                  # cut short
        del b[random.randrange(len(b) + 1):]
    elif how < 0.62:                                 # a run of the same byte
        at = random.randrange(len(b) + 1); n = random.randint(1, 64)
        b[at:at + n] = bytes([random.choice([0, 255])]) * n
    elif how < 0.74:                                 # a 4-byte number made huge, zero or negative
        if len(b) >= 4:
            at = random.randrange(len(b) - 3)
            b[at:at + 4] = struct.pack(">I", random.choice([0, 0xFFFFFFFF, 0x7FFFFFFF, 0x80000000, 65536, 30000, 1 << 24]))
    elif how < 0.86:                                 # a piece moved or doubled
        if len(b) > 8:
            a = random.randrange(len(b)); n = random.randint(1, min(200, len(b) - a))
            piece = b[a:a + n]; at = random.randrange(len(b)); b[at:at] = piece
    else:                                            # rubbish on the end, or only rubbish
        b = bytearray(os.urandom(random.randint(0, 300))) if random.random() < 0.3 else b + os.urandom(random.randint(1, 300))
    return bytes(b)

def rezip(raw: bytes, change) -> bytes:
    """A zip (Easel's own, OpenRaster) with its insides changed by `change(names -> bytes)`."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            parts = {n: z.read(n) for n in z.namelist()}
    except Exception:
        return raw
    change(parts)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in parts.items():
            z.writestr(n, data)
    return out.getvalue()

WILD = [None, True, -1, 0, 10 ** 9, 1e308, float("nan"), "", "x" * 2000, [], {}, [[]], {"a": 1}, "../../../etc/passwd", "\0"]
def spoil(o, depth=0):
    """A manifest with some value, somewhere, swapped for something it shouldn't be (or a key dropped)."""
    if isinstance(o, dict) and o:
        k = random.choice(list(o))
        r = random.random()
        if r < 0.25:
            del o[k]
        elif r < 0.6 or not isinstance(o[k], (dict, list)):
            o[k] = random.choice(WILD)
        else:
            spoil(o[k], depth + 1)
    elif isinstance(o, list) and o:
        i = random.randrange(len(o))
        if random.random() < 0.5 or not isinstance(o[i], (dict, list)):
            o[i] = random.choice(WILD)
        else:
            spoil(o[i], depth + 1)

def bad_manifest(parts):
    if "manifest.json" in parts:
        try:
            m = json.loads(parts["manifest.json"])
        except Exception:
            return
        for _ in range(random.randint(1, 3)):
            spoil(m)
        if random.random() < 0.15:
            m["w"], m["h"] = random.choice([(10 ** 6, 10 ** 6), (0, 0), (-5, 40), (70000, 3), ("wide", "tall"), (1e9, 2)])
        parts["manifest.json"] = json.dumps(m).encode()
    if random.random() < 0.3 and len(parts) > 1:
        del parts[random.choice([n for n in parts if n != "manifest.json"])]
    if random.random() < 0.2:
        n = random.choice(list(parts)); parts[n] = mutate(parts[n])
    if random.random() < 0.1:
        parts["../outside.txt"] = b"should never be written anywhere"

def bad_stack(parts):
    if "stack.xml" in parts:
        x = parts["stack.xml"].decode("utf-8", "replace")
        for a, b in random.sample([('w="160"', 'w="9999999"'), ('h="120"', 'h="-4"'), ('opacity="', 'opacity="nan'), ('src="', 'src="../../'), ('<stack', '<stack x="1e99"'),
                                   ('visibility="visible"', 'visibility=""'), ('composite-op="', 'composite-op="svg:nope'), ("</stack>", ""), ('x="', 'x="1e400')], 3):
            x = x.replace(a, b, random.choice([1, 99]))
        parts["stack.xml"] = x.encode()
    if random.random() < 0.3 and len(parts) > 1:
        del parts[random.choice(list(parts))]
    if random.random() < 0.2:
        n = random.choice(list(parts)); parts[n] = mutate(parts[n])

def huge_psd() -> bytes:
    """A Photoshop file whose header promises an enormous picture, or whose layers lie about their size."""
    raw = bytearray(seeds.get(".psd", b""))
    if len(raw) > 26:
        which = random.random()
        if which < 0.4:
            raw[14:22] = struct.pack(">II", random.choice([300000, 0x7FFFFFFF, 0, 30001]), random.choice([300000, 0x7FFFFFFF, 0, 30001]))
        elif which < 0.6:
            raw[12:14] = struct.pack(">H", random.choice([0, 57, 65535]))      # channels
        elif which < 0.8:
            raw[22:26] = struct.pack(">HH", random.choice([1, 16, 32, 0]), random.choice([0, 1, 4, 9]))   # depth, colour mode
        else:
            at = random.randrange(26, len(raw) - 4); raw[at:at + 4] = struct.pack(">i", random.choice([-1, -2 ** 31, 2 ** 31 - 1]))
    return bytes(raw)

MEM0 = rss()
opened = refused = 0
t0 = time.time()
for n in range(ROUNDS):
    ext = random.choice(list(seeds))
    raw = seeds[ext]
    r = random.random()
    if ext == ".easel" and r < 0.6:
        data, what = rezip(raw, bad_manifest), "manifest"
    elif ext == ".ora" and r < 0.6:
        data, what = rezip(raw, bad_stack), "stack"
    elif ext == ".psd" and r < 0.35:
        data, what = huge_psd(), "header"
    else:
        data, what = mutate(raw), "bytes"
    name = f"{home}/case{ext}"
    if random.random() < 0.08:                        # the wrong ending for what's inside
        name = f"{home}/case{random.choice(list(seeds))}"
    with open(name, "wb") as f:
        f.write(data)
    with open(home + "/now.txt", "w") as f:
        f.write(f"{n} {ext} {what} {len(data)}")
    faulthandler.dump_traceback_later(60, file=sys.stdout)
    t1, before = time.time(), len(said)
    place = random.random() < 0.25
    try:
        if place:
            e.newDoc(100, 80, "#FFFFFF"); e.placeFile(name)
        else:
            e.doc = None
            e.open(name)
        d = e.doc
        if d is None:
            refused += 1
            if len(said) == before:
                problem("a file was refused without a word", f"{ext} {what}")
        else:
            opened += 1
            if not (0 < d.w <= ez.SIDE_LIMIT and 0 < d.h <= ez.SIDE_LIMIT) or not d.layers:
                problem("a file opened into an impossible picture", f"{ext} {what}: {d.w}x{d.h}, {len(d.layers)} layers")
            else:
                for l in d.layers:
                    if l["kind"] == "pixel" and (l["image"].isNull() or l["image"].width() != d.w or l["image"].height() != d.h):
                        problem("a file opened with a layer the wrong size", f"{ext} {what}: {(l['image'].width(), l['image'].height())} in {d.w}x{d.h}")
                    if not isinstance(l.get("opacity"), (int, float)) or not (0 <= l["opacity"] <= 1) or not isinstance(l.get("name"), str) or not isinstance(l.get("visible"), bool) \
                            or l.get("blend") not in ez.BLENDS or l.get("kind") not in ("pixel", "vector", "adjust", "group", "smart"):
                        problem("a file opened with a layer setting that makes no sense", f"{ext} {what}: opacity {l.get('opacity')!r} name {type(l.get('name')).__name__} visible {l.get('visible')!r} blend {l.get('blend')!r} kind {l.get('kind')!r}")
                # and the opened picture must be usable: drawn, listed, painted on, saved
                flat = d.flattened()
                if flat.isNull() or flat.width() != d.w:
                    problem("a file opened but couldn't be drawn", f"{ext} {what}")
                e.layers; e.activeLayer; e.history
                if max(d.w, d.h) <= 2000:
                    e.setTool("brush"); e.press(5, 5, 1, 0); e.move(20, 20, 0); e.release(20, 20, 0)
                    e.setTool("move"); e.press(5, 5, 1, 0); e.move(9, 9, 0); e.release(9, 9, 0)
                    e.undo(); e.flatten(); e.undo()
                    if not e.saveAs(home + "/again.easel"):
                        problem("a file opened but couldn't be saved again", f"{ext} {what}: " + "; ".join(said[-2:]))
    except MemoryError:
        problem("opening a file ran out of memory", f"{ext} {what}")
    except Exception:
        problem(f"opening a damaged {ext} raised", traceback.format_exc())
        open(f"{home}/keep{len(problems)}{ext}", "wb").write(data)
    faulthandler.cancel_dump_traceback_later()
    took = time.time() - t1
    if took > 8:
        problem(f"opening a damaged {ext} took long", f"{took:.1f}s ({what})")
    if rss() - MEM0 > 1500:
        problem("opening files kept growing in memory", f"{rss()} MB after {n} files ({ext} {what} was last)"); MEM0 = rss()
    if os.path.exists(os.path.dirname(home) + "/outside.txt") or os.path.exists(home + "/../outside.txt"):
        problem("a file wrote outside its own folder", ext)
    if n % 100 == 0:
        print(f"round {n}: {opened} opened, {refused} refused, {len(problems)} kinds of problem, {rss()} MB, {time.time() - t0:.0f}s", flush=True)
print(f"\n{ROUNDS} files, seed {SEED}: {opened} opened, {refused} refused, {rss()} MB, {len(problems)} kinds of problem")
for kind, (count, detail) in sorted(problems.items(), key=lambda kv: -kv[1][0]):
    print(f"\n=== x{count}  {kind}\n    " + detail.strip().replace("\n", "\n    "))
sys.stdout.flush()
os._exit(1 if problems else 0)
