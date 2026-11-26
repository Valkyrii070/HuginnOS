"""Fuzz Clips: random editing, with the project checked after every step. Usage: clips_fuzz.py /src [steps] [seed]"""
import copy, json, math, os, random, subprocess, sys, tempfile, time, traceback
import xml.etree.ElementTree as ET
home = tempfile.mkdtemp(prefix="clipsfuzz-")
os.environ["HOME"] = home
os.environ["XDG_DATA_HOME"] = home + "/data"
os.environ["XDG_CACHE_HOME"] = home + "/cache"
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 1
sys.path.insert(0, SRC + "/apps"); sys.path.insert(0, SRC + "/shell")
from PySide6.QtCore import QEventLoop
from PySide6.QtGui import QGuiApplication
app = QGuiApplication(["x", "-platform", "offscreen"])
import huginn_clips as hc

random.seed(SEED)
problems = {}
log = []


def problem(kind, detail):
    import re as _re
    key = kind + " :: " + _re.sub(r"[-+]?\d+\.?\d*(e[-+]?\d+)?", "N", detail.strip().splitlines()[-1])[:140]
    if key not in problems:
        problems[key] = {"n": 0, "detail": detail[-1500:], "trail": list(log[-6:])}
    problems[key]["n"] += 1


def wait(cond, secs=60):
    end = time.time() + secs
    while time.time() < end and not cond():
        app.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.02)
    return cond()


def ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)


v1, v2, a1, im = (os.path.join(home, n) for n in ("one.mp4", "two.mp4", "music.wav", "still.png"))
ff("-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=10", "-f", "lavfi", "-i", "sine=frequency=330:duration=10", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", v1)
ff("-f", "lavfi", "-i", "testsrc2=size=180x320:rate=30:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", v2)       # upright, silent, another rate
ff("-f", "lavfi", "-i", "sine=frequency=110:duration=8", a1)
ff("-f", "lavfi", "-i", "color=c=teal:s=400x300:d=1", "-frames:v", "1", im)

c = hc.Clips(demo=False)
c.importFiles([v1, v2, a1, im])
assert wait(lambda: len(c._p["media"]) == 4 and all(m.get("duration", 0) > 0 or m["kind"] == "image" for m in c._p["media"]), 90), c._p["media"]
MEDIA = [m["id"] for m in c._p["media"]]
if os.environ.get("MEASURE"):
    grew = {"load": 0, "image": 0, "loads": 0, "images": 0, "biggest": []}
    _load, _image = c._engine.load, c._engine.image
    def load(xml, size, fps):
        a = rss_mb(); _load(xml, size, fps); d = rss_mb() - a
        grew["load"] += d; grew["loads"] += 1
        if d > 15:
            grew["biggest"].append(("load", d, size, len(xml), log[-1][:90]))
    def image(n):
        a = rss_mb(); r = _image(n); d = rss_mb() - a
        grew["image"] += d; grew["images"] += 1
        if d > 15:
            import re as _r
            svcs = sorted(set(_r.findall(r'mlt_service">([^<]+)', c._engine.xml)))
            grew["biggest"].append(("image", d, c._engine.size, log[-1][:90], svcs))
        return r
    c._engine.load, c._engine.image = load, image
if os.environ.get("NO_PREVIEW"):
    c._render_still = lambda: None
if os.environ.get("NO_UNDO"):
    _b = c._before
    def _trim():
        _b(); del c._undo[:-2]
    c._before = _trim
print("media", [(m["kind"], round(m.get("duration", 0), 2)) for m in c._p["media"]], flush=True)


def P():
    return c._p


def clips():
    return P().get("clips", [])


def tracks(kind=None):
    return [t["id"] for t in P()["tracks"] if kind is None or t["kind"] == kind]


def rc():
    cs = clips()
    return random.choice(cs)["id"] if cs else "nope"


def rt():
    return round(random.choice([0, random.uniform(0, 30), random.uniform(0, max(1.0, hc.total(P()))), -1, 1e6][: 3 if random.random() < 0.93 else 5]), random.choice([1, 2, 3, 6]))


SETS = [("speed", lambda: random.choice([0.25, 0.5, 1, 2, 8, 0, -1, 100, "x"])), ("volume", lambda: random.choice([0, 0.5, 1, 2, -3, 50])),
        ("colour.exposure", lambda: random.uniform(-2, 2)), ("colour.contrast", lambda: random.uniform(-1, 2)), ("colour.saturation", lambda: random.uniform(0, 2)),
        ("colour.temperature", lambda: random.uniform(-1, 1)), ("transform.scale", lambda: random.choice([0.1, 0.5, 1, 2, 0, -1, 40])), ("transform.x", lambda: random.uniform(-2, 2)),
        ("transform.y", lambda: random.uniform(-2, 2)), ("transform.rotate", lambda: random.uniform(-720, 720)), ("transform.opacity", lambda: random.uniform(-1, 2)),
        ("fade_in", lambda: random.uniform(0, 5)), ("fade_out", lambda: random.uniform(0, 5)), ("effects.blur", lambda: random.uniform(0, 1)),
        ("effects.mirror", lambda: random.random() < 0.5), ("effects.bw", lambda: random.random() < 0.5), ("text", lambda: random.choice(["Hello", "", "<&>\"'", "ünï ☃ " * 5, "x" * 3000])),
        ("style.size", lambda: random.choice([10, 60, 400, 0, -5])), ("crop.left", lambda: random.uniform(0, 1.2)), ("crop.right", lambda: random.uniform(0, 1.2)),
        ("nope.nothing", lambda: 1), ("", lambda: 1), ("colour", lambda: 5), ("sound.eq.low", lambda: random.uniform(-20, 20)), ("sound.voice", lambda: True), ("sound.echo", lambda: random.uniform(0, 1)),
        ("lut", lambda: "/no/such.cube"), ("key.on", lambda: True), ("shape.on", lambda: True), ("reverse", lambda: random.random() < 0.7), ("reverse", lambda: True), ("blend", lambda: random.choice(["screen", "multiply", "nope", ""]))]


def op_set():
    k, v = random.choice(SETS)
    return ("set", rc(), k, v())


OPS = [
    (8, lambda: ("place", random.choice(MEDIA + ["nope"]), random.choice(tracks() + ["nope"]), rt())),
    (5, lambda: ("edit", random.choice(MEDIA + ["nope"]), random.choice(["insert", "overwrite", "insert", "nope"]), random.choice(tracks() + ["", "", "nope"]))),
    (6, lambda: ("move", rc(), random.choice(tracks() + ["nope"]), rt())),
    (7, lambda: ("trim", rc(), random.choice(["in", "out", "sideways"]), rt(), random.random() < 0.4)),
    (5, lambda: ("seek", rt())),
    (5, lambda: ("pick", rc(), random.random() < 0.5)),
    (4, lambda: ("cut",)),
    (3, lambda: ("removePicked", random.random() < 0.5)),
    (3, lambda: ("duplicatePicked",)),
    (10, op_set),
    (3, lambda: ("setKey", rc(), random.choice(["opacity", "scale", "x", "y", "volume", "nope"]), random.uniform(-1, 3))),
    (1, lambda: ("clearKeys", rc(), random.choice(["opacity", "scale", "volume", "nope"]))),
    (3, lambda: ("setTransition", rc(), random.choice(["dissolve", "wipe_left", "", "nope"]), random.choice([0.2, 1, 5, 0, -1, 100]))),
    (2, lambda: ("addTitle", random.choice(["lower", "big", "heading", "subtitle", "nope"]), rt())),
    (1, lambda: ("addTrack", random.choice(["video", "audio", "nope"]))),
    (2, lambda: ("setTrack", random.choice(tracks() + ["nope"]), random.choice(["hidden", "muted", "locked", "gain", "pan", "name", "solo", "blend", "blend", "nope"]), random.choice([True, False, 0.5, -70, "Name", "screen", "multiply", "normal"]))),
    (1, lambda: ("removeTrack", random.choice(tracks() + ["nope"]))),
    (1, lambda: ("addMarker", random.choice(["m", "", "x" * 500]))),
    (1, lambda: ("removeMarker", rt())),
    (2, lambda: ("splitSpeed", rc())),
    (2, lambda: ("setSegmentSpeed", rc(), random.randrange(0, 4), random.choice([0.1, 0.5, 1, 3, 8, 0, -2, 99]))),
    (1, lambda: ("removeSpeedChange", rc(), random.randrange(0, 4))),
    (2, lambda: ("holdFrame", rc())),
    (1, lambda: ("setHold", rc(), random.randrange(0, 4), random.choice([0.5, 2, 0, -1, 500]))),
    (1, lambda: ("clearRamp", rc())),
    (2, lambda: ("slip", rc(), random.uniform(-20, 20))),
    (2, lambda: ("makeCompound",)),
    (1, lambda: ("openCompound", rc())),
    (2, lambda: ("closeCompound",)),
    (1, lambda: ("breakApart", rc())),
    (1, lambda: ("markRange", random.choice(["in", "out", "clear", "nope"]))),
    (1, lambda: ("jumpEdit", random.choice([1, -1]))),
    (1, lambda: ("step", random.choice([1, -1, 100, -100]))),
    (1, lambda: ("setProject", random.choice(["width", "height", "fps", "name", "nope"]), random.choice([1920, 1080, 25, 30, 0, -1, 99999, "Film", 23.976]))),
    (1, lambda: ("addCaption",)),
    (1, lambda: ("setShape", rc(), random.random() < 0.5)),
    (1, lambda: ("placeShape", rc(), random.uniform(-1, 2), random.uniform(-1, 2), random.uniform(-1, 2), random.uniform(-1, 2))),
    (1, lambda: ("setObscure", rc(), random.random() < 0.5)),
    (1, lambda: ("clearTracking", rc())),
    (1, lambda: ("clearBeats", rc())),
    (1, lambda: ("clearMatch", rc())),
    (1, lambda: ("showMatte", rc(), random.random() < 0.5)),
    (1, lambda: ("setZoom", random.choice([0.01, 1, 50, 0, -1, 1e9]))),
    (6, lambda: ("undo",)),
    (4, lambda: ("redo",)),
]
BAG = [f for w, f in OPS for _ in range(w)]


def numbers(o, where=""):
    if isinstance(o, float) and not math.isfinite(o):
        yield where
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from numbers(v, where + "." + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from numbers(v, where + f"[{i}]")


STATE = set()
NOW = set()


def state(kind, ident, detail):
    """A fault in the project itself: counted once, against the step that brought it in."""
    NOW.add((kind, ident))
    if (kind, ident) not in STATE:
        problem(kind, detail)


def check_project(p, where):
    tids = {t["id"] for t in p["tracks"]}
    if len(tids) != len(p["tracks"]):
        state("two tracks share an id", "", where)
    ids = [x["id"] for x in p.get("clips", [])]
    if len(ids) != len(set(ids)):
        state("two clips share an id", "", where)
    for bad in numbers(p):
        state("a number that isn't one", bad, where + " " + bad)
        break
    frame = 1.0 / float(p.get("fps", 25) or 25)
    for x in p.get("clips", []):
        if x.get("track") not in tids and x.get("kind") != "caption" and not str(x.get("track", "")).startswith("cap"):
            state("a clip on a track that isn't there", x["id"], f"{where} {x.get('kind')} on {x.get('track')}")
        try:
            n, at = hc.clip_len(x), float(x.get("at", 0))
        except Exception:
            problem("a clip whose length can't be worked out", where + "\n" + traceback.format_exc())
            continue
        if not n > frame * 0.5:
            state("a clip with no length", x["id"], f"{where} kind={x.get('kind')} len={n} in={x.get('in')} out={x.get('out')} speed={x.get('speed')}")
        if at < -1e-6:
            state("a clip before the start", x["id"], f"{where} at={at}")
        if "in" in x and "out" in x and x.get("kind") in (None, "video", "audio") and float(x["in"]) < -1e-6:
            state("footage from before its start", x["id"], f"{where} in={x['in']}")
        if x.get("kind") == "compound":
            check_project(x.get("project") or x.get("inner") or hc.compound_content(x), where + " (inside a compound)")
    for t in p["tracks"]:
        row = sorted(hc.on_track(p, t["id"]), key=lambda q: q["at"])
        for a, b in zip(row, row[1:]):
            over = hc.clip_end(a) - b["at"]
            allowed = float((a.get("transition") or {}).get("length", 0) or 0) if a.get("transition") else 0
            if over > allowed + frame * 1.5:
                state("two clips on top of each other", a["id"] + b["id"], f"{where} track={t['id']} by {over:.3f}s (transition {allowed})")


def call(name, *args):
    fn = getattr(c, name)
    return fn(*args)


def rss_mb():
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * 4096 // (1024 * 1024)


BIG = int(os.environ.get("BIG_MB", "4500"))
t0 = time.time()
melt_checks = xml_checks = undo_checks = 0
for n in range(STEPS):
    op = random.choice(BAG)()
    log.append(repr(op)[:160])
    root_before = copy.deepcopy(c._root)
    depth_before = len(c._path)
    try:
        call(*op)
    except Exception:
        problem(f"{op[0]} raised", traceback.format_exc())
    app.processEvents(QEventLoop.AllEvents, 5)
    if rss_mb() > BIG:
        problem("memory ran away", f"{rss_mb()} MB after {op!r}")
        print("MEMORY", rss_mb(), "MB at step", n, "after", repr(op)[:200], "\n  trail:", " ; ".join(log[-8:]), flush=True)
        json.dump(c._root, open("/tmp/big.json", "w"))
        os._exit(3)
    try:
        NOW.clear()
        check_project(c._root, op[0])
        STATE.clear(); STATE.update(NOW)
        json.dumps(c._root, allow_nan=False)
    except Exception:
        problem(f"checking after {op[0]}", traceback.format_exc())
    # undo takes back exactly one step, and redo puts it back
    if op[0] not in ("undo", "redo", "seek", "pick", "step", "jumpEdit", "setZoom", "openCompound", "closeCompound", "markRange", "showMatte") and random.random() < 0.3 and c._root != root_before and len(c._path) == depth_before:
        after = copy.deepcopy(c._root)
        try:
            c.undo()
            if c._root != root_before:
                keys = [k for k in set(c._root) | set(root_before) if c._root.get(k) != root_before.get(k)]
                problem(f"undo after {op[0]} didn't give back what was there", f"{op!r}  differs in {keys}")
            c.redo()
            if c._root != after:
                problem(f"redo after {op[0]} didn't give back the change", repr(op))
            undo_checks += 1
        except Exception:
            problem(f"undo/redo after {op[0]} raised", traceback.format_exc())
    if n % 20 == 0:
        try:
            before_mb = rss_mb()
            xml = c.mltProject()
            if len(xml) > 30_000_000 or rss_mb() - before_mb > 500:
                problem("the film's description ran away", f"{len(xml) // 1000000} MB of XML, memory {before_mb} -> {rss_mb()} MB")
                print("XML", len(xml), "bytes at step", n, "memory", before_mb, "->", rss_mb(), "\n  trail:", " ; ".join(log[-8:]), flush=True)
                json.dump(c._root, open("/tmp/big.json", "w"))
                os._exit(3)
            ET.fromstring(xml)
            xml_checks += 1
            if n % 140 == 0:
                f = os.path.join(home, "check.mlt")
                open(f, "w", encoding="utf-8").write(xml)
                r = subprocess.run(["melt", f, "out=3", "-consumer", "null", "real_time=0", "terminate_on_pause=1"], capture_output=True, text=True, timeout=120)
                melt_checks += 1
                err = (r.stderr or "")
                if r.returncode != 0 or "failed to load" in err.lower() or "Failed to load" in err:
                    problem("melt wouldn't play the project", f"exit {r.returncode}\n" + err[-600:])
        except subprocess.TimeoutExpired:
            problem("melt hung on the project", repr(op))
            import shutil as _sh
            _sh.copy(f, "/tmp/hung.mlt"); json.dump(c._root, open("/tmp/hung.json", "w"))
            for _n in ("one.mp4", "two.mp4", "music.wav", "still.png"):
                _sh.copy(os.path.join(home, _n), "/tmp/hung_" + _n)
        except Exception:
            problem(f"building the film after {op[0]}", traceback.format_exc())
    if n % 500 == 0:
        print(f"step {n}: {len(clips())} clips, {len(P()["tracks"])} tracks, depth {len(c._path)}, {len(problems)} kinds of problem, {time.time() - t0:.0f}s, {rss_mb()} MB", flush=True)

try:
    c._sync(); open("/tmp/last.mlt", "w", encoding="utf-8").write(hc.Builder(c._root, 960, 540, proxies={}, has_cairo=c._cairo).build(loudness=False)); print("clips at the end:", len(c._root["clips"]))
except Exception:
    pass
if os.environ.get("MEASURE"):
    print("MEASURE", {k: v for k, v in grew.items() if k != "biggest"})
    for b in grew["biggest"][:14]:
        print("   ", b)
print(f"\n{STEPS} steps, seed {SEED}: {xml_checks} films built, {melt_checks} played by melt, {undo_checks} undo/redo checks, {sum(v['n'] for v in problems.values())} problems of {len(problems)} kinds")
for k, v in sorted(problems.items(), key=lambda kv: -kv[1]["n"]):
    print(f"\n=== x{v['n']}  {k}")
    print("   ", v["detail"].strip().replace("\n", "\n    ")[-700:])
    print("    last steps:", " ; ".join(t[:110] for t in v["trail"][-4:]))
try:
    c.leaving()
except Exception:
    pass
os._exit(0)
