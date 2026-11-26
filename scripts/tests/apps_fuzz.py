#!/usr/bin/env python3
"""A fuzz for any app: it is started for real (not its demo) in a throwaway home folder with a few files in it, and
then every command its window can give (every slot of its backend) is called, over and over, with arguments drawn
from what the app itself is showing (names, paths and ids found in its properties) and from awkward ones (empty,
huge, wrong type, paths that aren't there). Nothing is known about any one app.

(A zero byte is left out of the awkward strings: no text box or file list can hand one over, and every path
function refuses it the same way, so it only drowned the real finds.)

What counts as a problem: a command that raises (a traceback where a person would see nothing happen, or a
half-done change), one that holds the window frozen (slower than SLOW seconds), and one that never comes back.

    apps_fuzz.py <kit root> <app> [steps=600] [seed=1]        (QT_QPA_PLATFORM=offscreen; refuses to run as root)

Never as root: the commands are real. They can rename, move and delete what they can reach, which as an ordinary
user in a throwaway home is that home. Commands that would end the session or the app are left out (SKIP).
"""
import faulthandler, os, random, re, signal, subprocess, sys, tempfile, time, traceback
from pathlib import Path

if os.geteuid() == 0:
    sys.exit("not as root: this fuzz gives real commands")
KIT = Path(sys.argv[1]).resolve()
APP = sys.argv[2]
STEPS = int(sys.argv[3]) if len(sys.argv) > 3 else 600
SEED = int(sys.argv[4]) if len(sys.argv) > 4 else 1
SLOW, HUNG = 2.0, 25
# (System Monitor's end/force/pause would be turned on the fuzz itself: its own process is in the list it shows)
# (attach/attachEditor are handed the window's own text box by the window: anything else is not a case to test)
SKIP = re.compile(r"^(attach|attachEditor|end|force|pause|quit|exit|close|closeWindow|shutdown|shutDown|restart|reboot|powerOff|suspend|sleep|hibernate|signOut|logOut|logout|lock"
                  r"|stop|leave|leaving|eraseDisk|formatDisk|format|erase|wipe|factoryReset|resetEverything|install|startInstall|begin)$")
random.seed(SEED)
os.setpgrp()                                                         # whatever the commands start (other apps, helpers) is ended with the fuzz

home = Path(tempfile.mkdtemp(prefix=f"appfuzz-{APP}-"))
# (a folder beside the home that no command has any business in: gone at the end means something deleted far too widely)
canary = Path(tempfile.mkdtemp(prefix=f"appfuzz-canary-{APP}-"))
(canary / "keep.txt").write_text("still here")
# (and two inside it, beside where apps keep their own things: a "../" too far takes these)
inner = [home / ".local/share/appfuzz-canary/keep.txt", home / ".config/appfuzz-canary/keep.txt"]
for f in inner:
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("still here")
for v in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "DISPLAY"):
    os.environ.pop(v, None)
run_dir = home / ".run"; run_dir.mkdir(mode=0o700)
os.environ.update(HOME=str(home), XDG_RUNTIME_DIR=str(run_dir), QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"), PYTHONDONTWRITEBYTECODE="1")
# ---- a home with something in it
for d in ("Documents", "Pictures", "Music", "Videos", "Downloads", "Desktop", "Documents/Work", "Documents/Notes"):
    (home / d).mkdir(parents=True, exist_ok=True)
(home / "Documents/letter.txt").write_text("Dear Astrid,\n\nThe fjord froze over on Tuesday.\n", encoding="utf-8")
(home / "Documents/Work/plan.md").write_text("# Plan\n\n- one\n- two\n", encoding="utf-8")
(home / "Documents/Notes/Shopping.md").write_text("- [ ] milk\n- [x] bread\n", encoding="utf-8")
(home / "Documents/numbers.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
(home / "Documents/ünï cödé – name.txt").write_text("x\n", encoding="utf-8")
(home / "Documents/empty.txt").write_text("")
(home / "Downloads/not-really.zip").write_bytes(b"PK\x03\x04 this is not a zip")
(home / "Downloads/binary.bin").write_bytes(bytes(range(256)) * 40)
(home / "Documents/latin1.txt").write_bytes("café\n".encode("latin-1"))
os.chdir(str(KIT / "apps"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
sys.argv = ["huginn_app.py", APP]

import huginn_app                                                    # noqa: E402
from PySide6.QtCore import QMetaMethod, QObject, QUrl, QPointF, QRectF   # noqa: E402
from PySide6.QtGui import QImage, QColor, QGuiApplication            # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine                      # noqa: E402

img = QImage(64, 48, QImage.Format.Format_RGB32); img.fill(QColor("#3366AA"))
img.save(str(home / "Pictures/blue.png")); img.save(str(home / "Pictures/photo.jpg")); img.save(str(home / "Desktop/shot.png"))

engines = []


class Engine(QQmlApplicationEngine):
    def __init__(self, *a):
        super().__init__(*a)
        engines.append(self)


problems, slow, calls, hung = {}, {}, 0, []
WILD_S = ["", " ", "/", "..", "../../etc/passwd", "~", "x" * 5000, "a\nb", "ünï cödé", "'; DROP TABLE x; --", "<b>bold</b>", "%s%n", "file:///etc/passwd",
          "https://example.invalid/x", "0", "-1", "nope", "/nonexistent/place/file.txt", "name with spaces.txt", ".hidden", "CON", "a/b/c"]
WILD_N = [0, 1, -1, 2, 3, 7, 10, 100, -100, 10 ** 6, 10 ** 12, -10 ** 12, 2 ** 31 - 1, 2 ** 31]
WILD_F = [0.0, 1.0, -1.0, 0.5, 1e-9, 1e12, -1e12, float("nan"), float("inf"), float("-inf")]


def harvest(backend, pool_s, pool_n, pool_any, depth=0):
    """What the app is showing: every string and number in its readable properties, a few levels down."""
    mo = backend.metaObject()
    for i in range(QObject.staticMetaObject.propertyCount(), mo.propertyCount()):
        p = mo.property(i)
        try:
            walk(p.read(backend), pool_s, pool_n, pool_any, 0)
        except Exception:                                            # a property that raises is itself a find
            note(f"reading property {p.name()}", traceback.format_exc())


def walk(v, pool_s, pool_n, pool_any, depth):
    if depth > 4 or len(pool_s) > 4000:
        return
    if isinstance(v, str):
        if 0 < len(v) < 400:
            if "appfuzz-canary" not in v:                    # (a file manager told to delete the canary may)
                pool_s.add(v)
    elif isinstance(v, bool):
        pass
    elif isinstance(v, int):
        pool_n.add(v)
    elif isinstance(v, float):
        pool_n.add(int(v) if v == v and abs(v) < 1e15 else 0)
    elif isinstance(v, dict):
        if len(pool_any) < 300:
            pool_any.append(v)
        for x in list(v.values())[:60]:
            walk(x, pool_s, pool_n, pool_any, depth + 1)
    elif isinstance(v, (list, tuple)):
        if len(pool_any) < 300:
            pool_any.append(list(v)[:20])
        for x in list(v)[:80]:
            walk(x, pool_s, pool_n, pool_any, depth + 1)


def note(what, tb):
    lines = [l for l in tb.strip().splitlines() if l.strip()]
    where = next((l.strip() for l in reversed(lines) if l.strip().startswith("File ") and "apps_fuzz.py" not in l), "")
    key = (lines[-1].split(":", 1)[0][:60], where[:160])              # one of each kind of error at each place
    if key not in problems:
        problems[key] = (what, tb)


def _hook(kind, value, tb):                                         # raised where nobody called from: a timer, a signal, a thread
    note("in the background (a timer, a signal or a thread)", "".join(traceback.format_exception(kind, value, tb)))


sys.excepthook = _hook
import threading                                                     # noqa: E402
threading.excepthook = lambda a: _hook(a.exc_type, a.exc_value, a.exc_traceback)


def arg_for(kind, pool_s, pool_n, pool_any):
    files = [str(p) for p in home.rglob("*") if ".run" not in p.parts][:200]
    r = random.random()
    if kind in ("QString", "QUrl"):
        s = random.choice(files) if r < 0.3 and files else random.choice(sorted(pool_s)) if r < 0.75 and pool_s else random.choice(WILD_S)
        return QUrl.fromLocalFile(s) if kind == "QUrl" and s.startswith("/") else QUrl(s) if kind == "QUrl" else s
    if kind in ("int", "uint", "qlonglong", "qulonglong", "long", "short"):
        v = random.choice(sorted(pool_n)) if r < 0.5 and pool_n else random.choice(WILD_N) if r < 0.8 else random.randint(-3, 40)
        return max(-2 ** 31, min(2 ** 31 - 1, int(v))) if kind in ("int", "short") else abs(int(v)) % 2 ** 31 if kind == "uint" else int(v)
    if kind in ("double", "float", "qreal"):
        return random.choice(WILD_F) if r < 0.4 else random.uniform(-2, 2) if r < 0.7 else float(random.choice(sorted(pool_n))) if pool_n else 0.0
    if kind == "bool":
        return r < 0.5
    if kind in ("QVariantList", "QStringList", "QList<QVariant>"):
        return random.choice([[], [random.choice(WILD_S)], random.sample(files, min(len(files), 3)), [1, "a", None, {}],
                              [x for x in pool_any if isinstance(x, list)][:1] and random.choice([x for x in pool_any if isinstance(x, list)]) or []])
    if kind in ("QVariantMap", "QJsonObject"):
        maps = [x for x in pool_any if isinstance(x, dict)]
        return random.choice(maps) if maps and r < 0.7 else random.choice([{}, {"id": "x"}, {"name": None, "path": "/"}, {"a": [1, 2, {"b": "c"}]}])
    if kind in ("QVariant", "QJSValue", "PyObject"):
        return random.choice([None, 0, 1, -1, "", "x", [], {}, 1.5, True]) if r < 0.4 else arg_for(random.choice(["QString", "int", "QVariantMap", "QVariantList", "double"]), pool_s, pool_n, pool_any)
    if kind == "QPointF":
        return QPointF(random.uniform(-50, 900), random.uniform(-50, 700))
    if kind == "QRectF":
        return QRectF(random.uniform(-50, 500), random.uniform(-50, 400), random.uniform(-10, 600), random.uniform(-10, 400))
    return None


# Another app the one under test would open (a browser, Translate) is not started: dozens of them starve the machine.
really_start = subprocess.Popen.__init__


def start(self, *args, **kw):
    if kw.get("start_new_session") and kw.get("stdout") == subprocess.DEVNULL:
        args, kw = (["sh", "-c", "cat > /dev/null"],), {"stdin": kw.get("stdin"), "stdout": subprocess.DEVNULL}
    really_start(self, *args, **kw)


subprocess.Popen.__init__ = start


def home_size() -> int:
    total = 0
    for f in home.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:                                              # gone since it was listed
            pass
    return total


def alarm(*_):
    raise TimeoutError("the command never came back")


def fuzz(app):
    global calls
    engine = engines[-1]
    backend = engine.rootContext().contextProperty("Backend")
    if backend is None:
        print("no Backend in this app's window"); return
    mo = backend.metaObject()
    slots = []
    for i in range(QObject.staticMetaObject.methodCount(), mo.methodCount()):
        m = mo.method(i)
        if m.methodType() == QMetaMethod.MethodType.Slot and m.access() == QMetaMethod.Access.Public:
            name = bytes(m.name()).decode()
            if not SKIP.match(name) and not name.startswith("_") and callable(getattr(backend, name, None)):
                slots.append((name, [bytes(t).decode() for t in m.parameterTypes()]))
    slots = sorted(set((n, tuple(t)) for n, t in slots))
    print(f"{APP}: {len(slots)} commands, {STEPS} steps, seed {SEED}", flush=True)
    signal.signal(signal.SIGALRM, alarm)
    pool_s, pool_n, pool_any = set(), set(), []
    t_end = time.time() + 480
    for step in range(STEPS):
        if time.time() > t_end:
            print(f"(out of time after {step} steps)"); break
        if step % 15 == 0:
            harvest(backend, pool_s, pool_n, pool_any)
            if home_size() > 400_000_000:
                print(f"(stopped after {step} steps: the app has written more than 400 MB into its home)"); break
        if not slots:                                               # (Welcome: every button is another app's)
            break
        name, kinds = random.choice(slots)
        args = [arg_for(k, pool_s, pool_n, pool_any) for k in kinds]
        shown = f"{name}({', '.join(repr(a)[:60] for a in args)})"
        if os.environ.get("FUZZ_SAY"):
            print("   ", shown[:200], flush=True)
        t0 = time.time()
        # (the alarm only reaches Python: stuck inside Qt, this says where and gives up on the app)
        faulthandler.dump_traceback_later(HUNG + 20, exit=True)
        signal.alarm(HUNG)
        try:
            getattr(backend, name)(*args)
            for _ in range(3):
                app.processEvents()
        except TimeoutError:
            hung.append(shown)
            print(f"HUNG   {shown}", flush=True)
            signal.alarm(0); faulthandler.cancel_dump_traceback_later()
            break                                                  # whatever it was holding, the rest can't be trusted
        except Exception:
            note(shown, traceback.format_exc())
        finally:
            signal.alarm(0); faulthandler.cancel_dump_traceback_later()
        took = time.time() - t0
        calls += 1
        if took > SLOW and (name not in slow or took > slow[name][0]):
            slow[name] = (took, shown)
    time.sleep(0.3)
    for _ in range(5):
        app.processEvents()


class App(QGuiApplication):
    def exec(self):                                                  # where the window would start taking clicks, the fuzz gives them
        try:
            fuzz(self)
        except Exception:
            note("the fuzz itself", traceback.format_exc())
        return 0


huginn_app.QQmlApplicationEngine = Engine
huginn_app.QGuiApplication = App
code = 0
try:
    code = huginn_app.main()
except SystemExit as e:
    code = e.code
except Exception:
    note("starting the app", traceback.format_exc())
print(f"\n{APP}: {calls} calls, {len(problems)} kinds of problem, {len(slow)} slow commands, {len(hung)} hung (seed {SEED})")
for (last, where), (what, tb) in problems.items():
    print(f"\nPROBLEM  {what[:300]}\n" + "\n".join("    " + l for l in tb.strip().splitlines()[-7:]))
for name, (took, shown) in sorted(slow.items(), key=lambda kv: -kv[1][0]):
    print(f"SLOW  {took:5.1f}s  {shown[:260]}")
sys.stdout.flush()
import shutil                                                        # noqa: E402
if APP != "files" and not all(f.is_file() for f in inner):       # (a file manager may be told to delete any folder)
    print("PROBLEM  a command removed files beside the app's own folder (a canary in .local/share or .config is gone)\n    RuntimeError: canary", flush=True)
if not (canary / "keep.txt").is_file():
    print("PROBLEM  a command removed files outside the app's own folders (the canary beside the home is gone)\n    RuntimeError: canary", flush=True)
shutil.rmtree(canary, ignore_errors=True)
shutil.rmtree(home, ignore_errors=True)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
try:
    os.killpg(0, signal.SIGTERM)                                     # the apps and helpers the commands started
except OSError:
    pass
os._exit(1 if problems or hung else 0)
