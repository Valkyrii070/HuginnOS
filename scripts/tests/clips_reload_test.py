"""Clips: an edit while the film plays (found by the app fuzz). Each edit builds the project again with a new MLT
profile; the sound's consumer, on a thread of its own, was still reading the old one after it was freed, and MLT
divided by its width of 0 (a crash, "Floating point exception", about one time in three). Now the sound stops before
the swap and starts again on the new project, and keeps its own profile alive meanwhile. Checked here with the
project from the fuzz (an adjustment layer and a caption, made into a compound clip while playing), many times over,
in a process of its own so a crash is a failure and not the end of the test. Also from the same fuzz: a track asked
for with a kind that isn't one ("<b>bold</b>") put a "<" into the XML's ids, MLT couldn't read it, and the next seek
crashed; a film's name with a quote in it broke the XML the same way; XML MLT can't read now shows nothing instead of
crashing. Usage: clips_reload_test.py /src"""
import os, subprocess, sys, tempfile
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
ok = bad = 0


def check(name, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
        print("ok  ", name)
    else:
        bad += 1
        print("FAIL", name, extra, flush=True)


CHILD = r'''
import os, sys, time, tempfile, faulthandler
faulthandler.enable()
home = tempfile.mkdtemp(prefix="clipsreload-"); os.environ.update(HOME=home, QT_QPA_PLATFORM="offscreen")
sys.path[:0] = [sys.argv[1] + "/apps", sys.argv[1] + "/shell"]
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
import huginn_clips as hc
if hc.mlt is None:
    print("NO-MLT"); sys.exit(0)
b = hc.Clips(False, "", provider=hc.FrameProvider())
b.addAdjustment(0.0)
b.addCaption()
size = b._preview_size()
before = b._xml(*size)
b.makeCompound()
after = b._xml(*size)
print("STATES", before != after, flush=True)
e = hc.Engine(lambda n, img: None, lambda n: None)
rounds = int(sys.argv[2])
for k in range(rounds):
    e.load(before, size, 30)
    e.play(0)
    time.sleep(0.35)
    sounding = e._audio is not None
    e.load(after, size, 30)                # an edit while it plays
    import gc; gc.collect()
    time.sleep(0.9)
    still = e.playing
    keeps = e._audio is None or e._audio_profile is e.profile
    e.stop()
    print("ROUND", k, sounding, still, keeps, e._audio is None, flush=True)
tracks = len(b._p["tracks"])
b.addTrack("<b>bold</b>"); b.addTrack("")
print("ODDTRACK", len(b._p["tracks"]) == tracks, flush=True)
b.addTrack("video")
print("REALTRACK", len(b._p["tracks"]) == tracks + 1, flush=True)
b._p["name"] = 'Astrid\'s "Fjord" <cut> & more'
x = b._xml(*size)
e.load(x, size, 30)
print("NAMED", e.prod is not None, flush=True)
e.load("<mlt><not xml", size, 30)
img = e.image(0)
e.play(0); time.sleep(0.3); e.stop()
print("BROKEN", e.prod is None and img is None, flush=True)
print("DONE", flush=True)
'''

with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
    f.write(CHILD)
r = subprocess.run([sys.executable, "-X", "faulthandler", f.name, SRC, "10"], capture_output=True, text=True, timeout=300)
os.unlink(f.name)
out = r.stdout.splitlines()
if "NO-MLT" in out:
    print("(MLT's Python bindings aren't here: nothing to check)")
    sys.exit(0)
rounds = [l.split() for l in out if l.startswith("ROUND")]
check("the project before and after the edit differ (the edit is real)", "STATES True" in out, out[:3])
check("no crash: all ten edits while playing came through", r.returncode == 0 and "DONE" in out and len(rounds) == 10,
      (r.returncode, [l for l in r.stderr.splitlines() if "Fatal" in l or "File" in l][:6]))
check("the picture keeps playing through each edit", rounds and all(x[3] == "True" for x in rounds), rounds[:3])
check("the sound, when there is any, is on the new project's profile", rounds and all(x[4] == "True" for x in rounds), rounds[:3])
check("stopping lets the sound go", rounds and all(x[5] == "True" for x in rounds), rounds[:3])
check("a track of a kind that isn't one isn't made", "ODDTRACK True" in out)
check("…while a video track still is", "REALTRACK True" in out)
check("a film named with quotes, < and & still makes XML MLT reads", "NAMED True" in out)
check("XML MLT can't read: no picture, no sound, no crash", "BROKEN True" in out)
print(f"{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
