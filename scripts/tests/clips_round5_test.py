"""Clips, round six: blend modes, backwards, insert and overwrite, a frame as a picture, missing footage, J K L, and the limits the fuzz run found."""
import os, sys, subprocess, tempfile, time, json, shutil
home = tempfile.mkdtemp(prefix="clips6-")
os.environ["HOME"] = home
os.environ["XDG_DATA_HOME"] = home + "/data"
os.environ["XDG_CACHE_HOME"] = home + "/cache"
for d in ("Videos", "Pictures", "Music", "Downloads"):
    os.makedirs(os.path.join(home, d), exist_ok=True)
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
sys.path.insert(0, SRC + "/apps"); sys.path.insert(0, SRC + "/shell")
from PySide6.QtCore import QEventLoop
from PySide6.QtGui import QGuiApplication, QImage
app = QGuiApplication(["x", "-platform", "offscreen"])
import numpy as np
import huginn_clips as hc

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
    else:
        bad += 1
        print("FAIL", name, extra, flush=True)

def wait(cond, secs=60):
    end = time.time() + secs
    while time.time() < end and not cond():
        app.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.02)
    return cond()

def ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)

work = os.path.join(home, "footage"); os.makedirs(work)
ramp = os.path.join(work, "ramp.mp4")        # brightness tells the second: black at 0, white at 10
ff("-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=10,format=gray,geq=lum='255*T/10',format=yuv420p", "-f", "lavfi", "-i", "sine=frequency=330:duration=10",
   "-shortest", "-c:v", "libx264", "-g", "5", "-pix_fmt", "yuv420p", "-c:a", "aac", ramp)
grey = os.path.join(work, "grey.mp4")
ff("-f", "lavfi", "-i", "color=c=0x808080:s=320x180:r=25:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", grey)
light = os.path.join(work, "light.mp4")
ff("-f", "lavfi", "-i", "color=c=0xC0C0C0:s=320x180:r=25:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", light)
music = os.path.join(work, "music.wav")
ff("-f", "lavfi", "-i", "sine=frequency=110:duration=12", music)

def fresh(files):
    c = hc.Clips(demo=False)
    c._p = c._root = hc.new_project(); c._path = []
    c._p["fps"] = 25
    c.importFiles(files)
    assert wait(lambda: len(c._p["media"]) == len(files), 90), c._p["media"]
    return c, {os.path.basename(m["path"]): m["id"] for m in c._p["media"]}

def luma(c, t):
    c._dirty_xml = True
    c._ensure_engine()
    img = c._engine.image(int(round(t * 25)))
    if img is None:
        return -1
    img = img.convertToFormat(QImage.Format_RGBA8888)
    a = np.frombuffer(bytes(img.constBits()), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), :3]
    return float(a[20:-20, 20:-20].mean())

# ---------------------------------------------------------------- blend modes
c, ids = fresh([grey, light])
vids = [t["id"] for t in c._p["tracks"] if t["kind"] == "video"]          # top first
check("two video tracks to start with", len(vids) >= 2, vids)
low, top = vids[-1], vids[-2]
check("grey below", c.place(ids["grey.mp4"], low, 0.0) == "")
check("light above", c.place(ids["light.mp4"], top, 0.0) == "")
normal = luma(c, 1.0)
check("normal: the layer on top is what shows", abs(normal - 192) < 8, normal)
seen = {}
for mode in ("multiply", "screen", "add", "darken", "lighten", "difference"):
    c.setTrack(top, "blend", mode)
    seen[mode] = luma(c, 1.0)
check("multiply darkens (128 x 192 / 255 = 96)", abs(seen["multiply"] - 96) < 10, seen)
check("screen brightens (224)", abs(seen["screen"] - 224) < 10, seen)
check("add (clipped at white)", seen["add"] > 245, seen)
check("darken keeps the darker (128)", abs(seen["darken"] - 128) < 8, seen)
check("lighten keeps the lighter (192)", abs(seen["lighten"] - 192) < 8, seen)
check("difference (64)", abs(seen["difference"] - 64) < 10, seen)
c.setTrack(top, "blend", "nonsense")
check("a mode that isn't one is refused", hc.track_of(c._p, top).get("blend") == "difference")
c.setTrack(top, "blend", "normal")
check("back to normal", abs(luma(c, 1.0) - 192) < 8)
aud = next(t["id"] for t in c._p["tracks"] if t["kind"] == "audio")
c.setTrack(aud, "blend", "screen")
check("sound tracks have no blend", not hc.track_of(c._p, aud).get("blend"))
c.setTrack(top, "blend", "multiply"); c.undo()
check("one undo", hc.track_of(c._p, top).get("blend") in (None, "normal"))
check("ten modes offered", len(c.blends) == 10 and c.blends[0]["key"] == "normal")

# ---------------------------------------------------------------- backwards
c, ids = fresh([ramp])
v1 = [t["id"] for t in c._p["tracks"] if t["kind"] == "video"][-1]
c.place(ids["ramp.mp4"], v1, 0.0)
k = c._p["clips"][0]["id"]
f1, f8 = luma(c, 1.0), luma(c, 8.0)
check("forwards: dark early, light late", abs(f1 - 25.5) < 9 and abs(f8 - 204) < 9, (f1, f8))
c.set(k, "reverse", True)
b1, b8 = luma(c, 1.0), luma(c, 8.0)
check("backwards: light early (the footage's ninth second)", abs(b1 - 229.5) < 10, b1)
check("backwards: dark late (its second second)", abs(b8 - 51) < 10, b8)
check("as long as it was", abs(hc.clip_len(c._c(k)) - 10) < 0.05)
c.set(k, "reverse", False); c.trim(k, "in", 2.0, False); c.trim(k, "out", 6.0, False); c.set(k, "reverse", True)
cl = c._c(k)
check("trimmed to the footage's 2 s to 6 s", abs(cl["in"] - 2) < 0.05 and abs(cl["out"] - 6) < 0.05, (cl["in"], cl["out"], cl["at"]))
t0 = cl["at"]
s0, s3 = luma(c, t0 + 0.2), luma(c, t0 + 3.8)
check("trimmed and backwards: starts near its 6th second", abs(s0 - 255 * 5.8 / 10) < 10, s0)
check("trimmed and backwards: ends near its 2nd second", abs(s3 - 255 * 2.2 / 10) < 10, s3)
c.set(k, "speed", 2.0)
check("twice as fast backwards: half as long", abs(hc.clip_len(c._c(k)) - 2.0) < 0.05, hc.clip_len(c._c(k)))
m1 = luma(c, t0 + 1.0)
check("twice as fast backwards: the middle is its 4th second", abs(m1 - 255 * 4.0 / 10) < 12, m1)
c.set(k, "reverse", False)
check("forwards again at double speed", abs(luma(c, t0 + 1.0) - 255 * 4.0 / 10) < 12 and luma(c, t0 + 0.2) < luma(c, t0 + 1.8))
xml = c.mltProject()
open(os.path.join(home, "rev.mlt"), "w").write(xml)
c.set(k, "reverse", True)
open(os.path.join(home, "rev.mlt"), "w").write(c.mltProject())
r = subprocess.run(["melt", os.path.join(home, "rev.mlt"), "-consumer", "null", "real_time=-1", "terminate_on_pause=1"], capture_output=True, text=True, timeout=120)
check("melt plays the backwards film", r.returncode == 0, r.stderr[-300:])

# ---------------------------------------------------------------- insert and overwrite
c, ids = fresh([ramp, grey, music])
v1 = [t["id"] for t in c._p["tracks"] if t["kind"] == "video"][-1]
a1 = next(t["id"] for t in c._p["tracks"] if t["kind"] == "audio")
c.place(ids["ramp.mp4"], v1, 0.0); c.place(ids["music.wav"], a1, 0.0)
c.addMarker("later"); c.seek(8.0); c.addMarker("eight")
before = json.dumps(c._root, sort_keys=True)
c.seek(4.0)
check("insert", c.edit(ids["grey.mp4"], "insert", "") == "")
row = sorted(hc.on_track(c._p, v1), key=lambda q: q["at"])
check("the clip under the playhead was cut and the new one sits between", len(row) == 3 and [round(x["at"], 2) for x in row] == [0.0, 4.0, 10.0], [(x["at"], hc.clip_end(x)) for x in row])
check("the new one is the grey clip, whole", row[1]["media"] == ids["grey.mp4"] and abs(hc.clip_len(row[1]) - 6) < 0.05)
check("the second half carries on where the first stopped", abs(row[0]["out"] - 4) < 0.05 and abs(row[2]["in"] - 4) < 0.05)
mus = sorted(hc.on_track(c._p, a1), key=lambda q: q["at"])
check("the music moved along too, cut at the same place", len(mus) == 2 and abs(mus[1]["at"] - 10) < 0.05 and abs(mus[1]["in"] - 4) < 0.05, [(x["at"], x["in"]) for x in mus])
check("the film is six seconds longer", abs(hc.total(c._p) - 18) < 0.05, hc.total(c._p))
check("the marker after it moved, the one before didn't", sorted(round(float(m["t"]), 1) for m in c._p["markers"]) == [0.0, 14.0], c._p["markers"])
check("the playhead is after the new clip", abs(c.head - 10) < 0.05, c.head)
check("picture: grey where it was put, the ramp after", abs(luma(c, 5.0) - 128) < 8 and abs(luma(c, 10.5) - 255 * 4.5 / 10) < 10)
c.undo()
check("one undo puts it all back", json.dumps(c._root, sort_keys=True) == before)

c, ids = fresh([ramp, grey, music])
v1 = [t["id"] for t in c._p["tracks"] if t["kind"] == "video"][-1]
a1 = next(t["id"] for t in c._p["tracks"] if t["kind"] == "audio")
c.place(ids["ramp.mp4"], v1, 0.0); c.place(ids["music.wav"], a1, 0.0)
c.seek(3.0)
check("overwrite", c.edit(ids["grey.mp4"], "overwrite", "") == "")
row = sorted(hc.on_track(c._p, v1), key=lambda q: q["at"])
check("what was there is replaced, the rest stays put", [(round(x["at"], 2), round(hc.clip_end(x), 2)) for x in row] == [(0.0, 3.0), (3.0, 9.0), (9.0, 10.0)], [(x["at"], hc.clip_end(x)) for x in row])
check("the tail still shows its own footage", abs(row[2]["in"] - 9) < 0.05)
check("the music wasn't touched", len(hc.on_track(c._p, a1)) == 1 and abs(hc.total(c._p) - 12) < 0.05)
check("picture: ramp, grey, ramp", abs(luma(c, 1.0) - 25.5) < 9 and abs(luma(c, 5.0) - 128) < 8 and abs(luma(c, 9.5) - 242) < 10)
c.seek(2.0); c.markRange("in"); c.seek(3.5); c.markRange("out")
check("overwrite into a marked stretch", c.edit(ids["grey.mp4"], "overwrite", "") == "")
row = sorted(hc.on_track(c._p, v1), key=lambda q: q["at"])
new = next(x for x in row if abs(x["at"] - 2.0) < 0.01)
check("it fills exactly In to Out", abs(hc.clip_len(new) - 1.5) < 0.02 and abs(hc.clip_end(new) - 3.5) < 0.02, (new["at"], hc.clip_end(new)))
check("nothing overlaps", all(hc.clip_end(a) <= b["at"] + 0.001 for a, b in zip(row, row[1:])), [(x["at"], hc.clip_end(x)) for x in row])
check("sound into a video track is steered to a sound track", c.edit(ids["music.wav"], "overwrite", v1) == "" and c._c(c._picked[0])["track"] != v1)
check("something not in the library", c.edit("nope", "insert", "") != "")
check("a way that isn't one", c.edit(ids["grey.mp4"], "sideways", "") != "")
hc.track_of(c._p, v1)["locked"] = True
check("a locked track says so", "locked" in c.edit(ids["grey.mp4"], "overwrite", v1))
hc.track_of(c._p, v1)["locked"] = False

# ---------------------------------------------------------------- editing a clip that plays backwards
c, ids = fresh([ramp, grey])
v1 = [t["id"] for t in c._p["tracks"] if t["kind"] == "video"][-1]
c.place(ids["ramp.mp4"], v1, 0.0)
k = c._p["clips"][0]["id"]
c.set(k, "reverse", True)
c.pick(k, False); c.seek(3.0)
check("a cut in a backwards clip", c.cut() == 1)
a, b = sorted(hc.on_track(c._p, v1), key=lambda q: q["at"])
check("the earlier piece keeps the later footage (7 s to 10 s)", abs(a["in"] - 7) < 0.05 and abs(a["out"] - 10) < 0.05 and abs(hc.clip_len(a) - 3) < 0.05, (a["in"], a["out"]))
check("the later piece the earlier footage (0 s to 7 s)", abs(b["in"]) < 0.05 and abs(b["out"] - 7) < 0.05 and abs(b["at"] - 3) < 0.05, (b["in"], b["out"], b["at"]))
check("and the picture runs on across the cut", abs(luma(c, 2.8) - 255 * 7.2 / 10) < 10 and abs(luma(c, 3.2) - 255 * 6.8 / 10) < 10, (luma(c, 2.8), luma(c, 3.2)))
c.undo()
c.trim(k, "in", 2.0, False)
cl = c._c(k)
check("trimming its start takes away the later footage", abs(cl["out"] - 8) < 0.05 and abs(cl["in"]) < 0.05 and abs(cl["at"] - 2) < 0.05, (cl["in"], cl["out"], cl["at"]))
check("it starts on the footage's eighth second", abs(luma(c, 2.2) - 255 * 7.8 / 10) < 10, luma(c, 2.2))
c.trim(k, "out", 7.0, False)
cl = c._c(k)
check("trimming its end takes away the earlier footage", abs(cl["in"] - 3) < 0.05 and abs(cl["out"] - 8) < 0.05 and abs(hc.clip_end(cl) - 7) < 0.05, (cl["in"], cl["out"]))
check("it ends on the footage's third second", abs(luma(c, 6.8) - 255 * 3.2 / 10) < 10, luma(c, 6.8))
check("slipping shows later footage", c.slip(k, 1.0) == "" and abs(c._c(k)["in"] - 2) < 0.05 and abs(c._c(k)["out"] - 7) < 0.05, (c._c(k)["in"], c._c(k)["out"]))
c.seek(4.0); c.pick(k, False)
check("overwriting the middle of it", c.edit(ids["grey.mp4"], "overwrite", v1) == "")
row = sorted(hc.on_track(c._p, v1), key=lambda q: q["at"])
check("leaves its start as it was", abs(luma(c, 2.2) - 255 * 6.8 / 10) < 10, luma(c, 2.2))
check("three pieces, none over another", len(row) >= 2 and all(hc.clip_end(x) <= y["at"] + 0.001 for x, y in zip(row, row[1:])), [(x["at"], hc.clip_end(x)) for x in row])
said = []
c.said.connect(lambda text, warn: said.append(text))
first = row[0]["id"]
c.pick(first, False); c.seek(row[0]["at"] + 0.5)
check("no speed ramp on a backwards clip, and it says why", c.splitSpeed(first) in (0, -1, None) and any("backwards" in x for x in said), said)
check("nothing ramped", not hc.ramped(c._c(first)))
c.set(first, "reverse", False); c.splitSpeed(first); c.set(first, "reverse", True)
check("nor backwards on a ramped clip", hc.ramped(c._c(first)) and not c._c(first).get("reverse"))
t = c.addTitle("lower", 30.0)
c.set(c._p["clips"][-1]["id"], "reverse", True)
check("a title can't go backwards", not c._p["clips"][-1].get("reverse"))

# ---------------------------------------------------------------- an emptied compound clip
c, ids = fresh([ramp, grey])
v1 = [t["id"] for t in c._p["tracks"] if t["kind"] == "video"][-1]
c.place(ids["ramp.mp4"], v1, 0.0); c.place(ids["grey.mp4"], v1, 10.0)
c._picked = [x["id"] for x in c._p["clips"]]
check("a compound clip", c.makeCompound() == "")
comp = c._picked[0]
c.openCompound(comp)
c._picked = [x["id"] for x in c._p["clips"]]
c.removePicked(False)
c._sync()
check("emptied from inside, it keeps a sliver to be found by", hc.clip_len(next(x for x in c._root["clips"] if x["id"] == comp)) >= hc.SHORTEST - 1e-6)
c.closeCompound()
check("and is gone once it's closed", not any(x["id"] == comp for x in c._root["clips"]) and not c._path)
c.undo()
check("undo brings it back with its clips", any(x.get("kind") == "compound" and len(x["inner"]["clips"]) == 2 for x in c._root["clips"]), [x.get("kind") for x in c._root["clips"]])

c, ids = fresh([ramp, grey])
v1 = [t["id"] for t in c._p["tracks"] if t["kind"] == "video"][-1]
c.place(ids["ramp.mp4"], v1, 5.0)
c.seek(5.04)
check("insert a frame after a clip's start", c.edit(ids["grey.mp4"], "insert", v1) == "")
row = sorted(hc.on_track(c._p, v1), key=lambda q: q["at"])
check("the clip moves whole rather than being left under the new one", len(row) == 2 and all(hc.clip_end(x) <= y["at"] + 0.001 for x, y in zip(row, row[1:])) and abs(hc.clip_len(row[1]) - 10) < 0.05, [(x["at"], hc.clip_end(x)) for x in row])
c.undo(); c.seek(14.96)
check("insert a frame before a clip's end", c.edit(ids["grey.mp4"], "insert", v1) == "")
row = sorted(hc.on_track(c._p, v1), key=lambda q: q["at"])
check("the sliver that hung over is trimmed off", len(row) == 2 and all(hc.clip_end(x) <= y["at"] + 0.001 for x, y in zip(row, row[1:])), [(x["at"], hc.clip_end(x)) for x in row])
c.undo(); c.seek(5.03)
check("overwrite a frame after a clip's start", c.edit(ids["grey.mp4"], "overwrite", v1) == "")
row = sorted(hc.on_track(c._p, v1), key=lambda q: q["at"])
check("no sliver is left before it", all(hc.clip_len(x) >= hc.SHORTEST - 1e-6 for x in row) and all(hc.clip_end(x) <= y["at"] + 0.001 for x, y in zip(row, row[1:])), [(x["at"], hc.clip_end(x)) for x in row])

# ---------------------------------------------------------------- a frame as a picture
c.seek(8.0)
path = c.saveFrame()
check("saving a frame names a file in Pictures/Clips", path.endswith(".png") and "/Pictures/Clips/" in path, path)
check("the picture is made", wait(lambda: os.path.exists(path) and os.path.getsize(path) > 500, 60), path)
img = QImage(path)
check("at the film's full size", (img.width(), img.height()) == hc.SIZES[c._p.get("size", "1080p")][:2], (img.width(), img.height()))
a = np.frombuffer(bytes(img.convertToFormat(QImage.Format_RGBA8888).constBits()), np.uint8)
check("and it is the frame under the playhead (grey)", abs(float(a.reshape(-1, 4)[:, :3].mean()) - 128) < 8)
second = c.saveFrame()
check("never over another picture", second != path)
wait(lambda: os.path.exists(second), 60)

# ---------------------------------------------------------------- missing footage
c, ids = fresh([ramp, grey])
v1 = [t["id"] for t in c._p["tracks"] if t["kind"] == "video"][-1]
c.place(ids["ramp.mp4"], v1, 0.0); c.place(ids["grey.mp4"], v1, 10.0)
check("nothing missing", c.missingCount == 0 and not any(m["missing"] for m in c.media))
moved = os.path.join(home, "Videos", "old shoots", "ramp.mp4")
os.makedirs(os.path.dirname(moved)); shutil.move(ramp, moved)
check("one missing", c.missingCount == 1 and [m["missing"] for m in c.media] == [True, False])
c._dirty_xml = True
open(os.path.join(home, "miss.mlt"), "w").write(c.mltProject())
r = subprocess.run(["melt", os.path.join(home, "miss.mlt"), "out=20", "-consumer", "null", "real_time=-1", "terminate_on_pause=1"], capture_output=True, text=True, timeout=120)
check("the film still plays with a card where the footage was", r.returncode == 0 and "ramp.mp4" not in (r.stderr or ""), r.stderr[-300:])
card = luma(c, 2.0)
check("the card is dark red, not black or white", 5 < card < 90, card)
check("what isn't missing still shows", abs(luma(c, 12.0) - 128) < 8)
said = []
c.said.connect(lambda text, warn: said.append(text))
c.findMissing()
check("found in Videos by its name", wait(lambda: c.missingCount == 0, 40), said)
check("and pointed at where it is now", hc.media_of(c._p, ids["ramp.mp4"])["path"] == moved)
check("the footage shows again", abs(luma(c, 2.0) - 51) < 10, luma(c, 2.0))
c.undo()
check("undo: missing again", c.missingCount == 1)
c.redo()
hidden = os.path.join(home, "elsewhere", "ramp.mp4")
os.makedirs(os.path.dirname(hidden)); shutil.move(moved, hidden)
said.clear(); c.findMissing()
check("not found: says to drop it on the window", wait(lambda: any("Drop" in s for s in said), 60), said)
n_media = len(c._p["media"])
c.importFiles([hidden])
check("dropping the file picks up where it left off", c.missingCount == 0 and len(c._p["media"]) == n_media and hc.media_of(c._p, ids["ramp.mp4"])["path"] == hidden)
c.findMissing()
check("nothing to find", wait(lambda: any("Nothing is missing" in s for s in said), 10), said)
shutil.move(hidden, ramp); c.importFiles([ramp])

# ---------------------------------------------------------------- J K L
if c._engine.ok:
    c.pause(); c.seek(4.0)
    c.shuttle(1)
    check("L plays", wait(lambda: c.playing, 5) and c.rate == 1.0)
    time.sleep(0.2); app.processEvents()
    c.shuttle(1)
    check("L again: twice as fast", c.rate == 2.0)
    h0 = c.head; wait(lambda: False, 1.0); moved_by = c.head - h0
    check("about two seconds of film in one", 1.5 < moved_by < 2.6, moved_by)
    c.shuttle(1); check("four times", c.rate == 4.0)
    c.shuttle(1); check("eight times", c.rate == 8.0)
    c.shuttle(1); check("no faster than eight", c.rate == 8.0)
    c.shuttle(-1); check("J slows it a step", c.rate == 4.0)
    c.shuttle(0)
    check("K stops", not c.playing and c.rate == 0.0)
    c.seek(8.0)
    c.shuttle(-1)
    check("J plays backwards", wait(lambda: c.playing, 5) and c.rate == -1.0)
    h0 = c.head; wait(lambda: False, 1.0)
    check("the playhead goes back about a second", -1.5 < c.head - h0 < -0.6, c.head - h0)
    c.shuttle(-1); check("J again: twice as fast backwards", c.rate == -2.0)
    c.shuttle(1); c.shuttle(1)
    check("L, L from backwards: stopped", not c.playing)
    c.seek(0.2); c.shuttle(-1); c.shuttle(-1); c.shuttle(-1)
    check("backwards stops at the start", wait(lambda: not c.playing and c.head < 0.1, 6), c.head)
    c.pause()
else:
    print("(no MLT bindings: J K L not run)")

# ---------------------------------------------------------------- limits the fuzz run found
c, ids = fresh([ramp])
v1 = [t["id"] for t in c._p["tracks"] if t["kind"] == "video"][-1]
c.place(ids["ramp.mp4"], v1, 0.0)
k = c._p["clips"][0]["id"]
c.trim(k, "out", 0.2, False)
c.set(k, "speed", 16)
check("a fifth of a second can't be sped up into nothing", hc.clip_len(c._c(k)) >= hc.SHORTEST - 1e-6, hc.clip_len(c._c(k)))
c.set(k, "speed", "fast")
check("a speed that isn't a number changes nothing", isinstance(c._c(k)["speed"], float))
check("an end that isn't one", c.trim(k, "sideways", 5.0, False) is False)
c.set(k, "colour", 5)
check("a group of settings isn't swapped for a number", isinstance(c._c(k)["colour"], dict))
c.set(k, "", 1); c.set(k, "colour..x", 1)
check("an empty setting name changes nothing", "" not in c._c(k))
c.setProject("name", 1080)
check("a film's name is always words", c._p["name"] == "1080")
c.setProject("fps", "soon")
check("a rate that isn't a number changes nothing", c._p["fps"] == 25)
c.setTrack(v1, "gain", "loud"); c.setTrack(v1, "name", 3.5)
check("a fader given words changes nothing; a name given a number is words", hc.track_of(c._p, v1).get("gain", 0) in (0, 0.0) and hc.track_of(c._p, v1)["name"] == "3.5")
t = c.addTitle("lower", 2.0)
tid = c._p["clips"][-1]["id"]
c.set(tid, "speed", 8)
check("a title has no speed", c._c(tid).get("speed", 1.0) == 1.0)
c.set(k, "transform.scale", 40); c.set(k, "transform.opacity", -3); c.set(k, "effects.blur", 9); c.set(k, "style.size", 1)
tr = c._c(k)["transform"]
check("no clip is made forty times its size (that much picture won't fit in memory)", tr["scale"] == hc.LIMITS["transform.scale"][1] and tr["opacity"] == 0.0 and c._c(k)["effects"]["blur"] == 1.0, tr)
c.set(k, "transform.scale", float("nan"))
check("a size that isn't a number changes nothing", tr["scale"] == c._c(k)["transform"]["scale"] == hc.LIMITS["transform.scale"][1])
c.seek(c._c(k)["at"] + 0.05); c.setKey(k, "scale", 500)
check("nor a keyframe", max(v for _, v in c._c(k)["keys"]["scale"]) <= hc.LIMITS["transform.scale"][1])
c.set(tid, "text", "x" * 100000)
check("a title's words have an end", len(c._c(tid)["text"]) == 4000)
c.set(k, "transform.scale", 1.0); c.clearKeys(k, "scale")
import xml.etree.ElementTree as ET
check("and the film still builds", ET.fromstring(c.mltProject()) is not None)
c2, ids2 = fresh([ramp])
c2.place(ids2["ramp.mp4"], v1, 0.0)
k2 = c2._p["clips"][0]["id"]
c2.trim(k2, "out", 0.5, False); c2.seek(0.25); c2.splitSpeed(k2)
c2.setSegmentSpeed(k2, 0, 16); c2.setSegmentSpeed(k2, 1, 16)
check("nor can a ramp leave almost nothing", hc.clip_len(c2._c(k2)) >= hc.SHORTEST - 1e-6, hc.clip_len(c2._c(k2)))
c2.seek(0.02); n_before = len(c2._p["clips"]); c2.cut()
check("a cut a frame from the end isn't made", len(c2._p["clips"]) == n_before)

print(f"{ok} passed, {bad} failed")
for x in (c, c2):
    try:
        x.leaving()
    except Exception:
        pass
os._exit(1 if bad else 0)
