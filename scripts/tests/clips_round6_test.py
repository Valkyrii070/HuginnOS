"""Clips, pro round six: editing by what's said (and cutting the ums), adjustment layers, one colour changed on
its own, smooth slow motion, and chapters from markers."""
import os, sys, subprocess, tempfile, time, json, stat
home = tempfile.mkdtemp(prefix="clips7-")
os.environ["HOME"] = home
os.environ["XDG_DATA_HOME"] = home + "/data"
os.environ["XDG_CACHE_HOME"] = home + "/cache"
for d in ("Videos", "Pictures", "Music", "Downloads", "bin", ".local/share/huginn/whisper"):
    os.makedirs(os.path.join(home, d), exist_ok=True)
# a stand-in for whisper.cpp: it writes down the same words each time, one to an entry, and notes how it was asked
fake = os.path.join(home, "bin", "whisper-cli")
with open(fake, "w") as f:
    f.write("""#!/usr/bin/env python3
import sys, json, os
a = sys.argv[1:]
open(os.path.join(os.environ["HOME"], "asked.json"), "w").write(json.dumps(a))
base = a[a.index("-of") + 1]
words = [(0.5, 0.8, "So"), (0.9, 1.3, "um,"), (1.5, 1.9, "we"), (2.0, 2.4, "left"), (2.6, 3.0, "uh"), (3.2, 3.6, "before"), (3.7, 4.1, "light"), (4.4, 4.8, "Er")]
t = lambda s: "00:00:%02d,%03d" % (int(s), round(s % 1 * 1000))
open(base + ".srt", "w").write("".join("%d\\n%s --> %s\\n%s\\n\\n" % (n, t(x), t(y), w) for n, (x, y, w) in enumerate(words, 1)))
""")
os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
open(os.path.join(home, ".local/share/huginn/whisper", "ggml-base.bin"), "wb").write(b"\0" * 16)
os.environ["PATH"] = os.path.join(home, "bin") + ":" + os.environ.get("PATH", "/usr/bin:/bin")
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
red = os.path.join(work, "red.mp4")
ff("-f", "lavfi", "-i", "color=c=0xD02020:s=320x180:r=25:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", red)
blue = os.path.join(work, "blue.mp4")
ff("-f", "lavfi", "-i", "color=c=0x2040D0:s=320x180:r=25:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", blue)
talk = os.path.join(work, "talk.mp4")            # brightness tells the second; a tone to be heard
ff("-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=6,format=gray,geq=lum='255*T/6',format=yuv420p", "-f", "lavfi", "-i", "sine=frequency=330:duration=6",
   "-shortest", "-c:v", "libx264", "-g", "5", "-pix_fmt", "yuv420p", "-c:a", "aac", talk)
moving = os.path.join(work, "moving.mp4")        # a different picture every frame
ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=3", "-c:v", "libx264", "-g", "5", "-pix_fmt", "yuv420p", moving)

def fresh(files):
    c = hc.Clips(demo=False)
    c._p = c._root = hc.new_project(); c._path = []
    c._p["fps"] = 25
    c.importFiles(files)
    assert wait(lambda: len(c._p["media"]) == len(files), 90), c._p["media"]
    return c, {os.path.basename(m["path"]): m["id"] for m in c._p["media"]}

def picture(c, t):
    c._dirty_xml = True
    c._ensure_engine()
    img = c._engine.image(int(round(t * 25)))
    if img is None:
        return None
    img = img.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(bytes(img.constBits()), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), :3].astype(float)

def mean(a, part="all"):
    h, w = a.shape[:2]
    if part == "centre":
        a = a[int(h * 0.4):int(h * 0.6), int(w * 0.4):int(w * 0.6)]
    elif part == "corner":
        a = a[2:int(h * 0.15), 2:int(w * 0.15)]
    return a.reshape(-1, 3).mean(axis=0)

def clip_on(c, mid):
    return next(x for x in c._p["clips"] if x.get("media") == mid)

# ---------------------------------------------------------------- the small parts
ws = hc.word_list([(1.0, 2.0, "hello there"), (2.0, 2.5, "Um,")])
check("two words in one entry share its time", ws[:2] == [[1.0, 1.5, "hello"], [1.5, 2.0, "there"]], ws)
check("filler words: um with its comma, uh, er", hc.is_filler("Um,") and hc.is_filler("uh") and hc.is_filler("Er.") and not hc.is_filler("umbrella") and not hc.is_filler("like"))
words = [[0.5, 0.8, "So"], [0.9, 1.3, "um"], [1.5, 1.9, "we"], [2.0, 2.4, "left"]]
check("a word's cut reaches halfway into the quiet either side", hc.word_spans(words, [1], 0, 6) == [(0.85, 1.4)], hc.word_spans(words, [1], 0, 6))
check("neighbouring words go as one cut", hc.word_spans(words, [1, 2], 0, 6) == [(0.85, 1.95)], hc.word_spans(words, [1, 2], 0, 6))
check("cuts stay inside the clip", hc.word_spans(words, [0], 0.6, 6) == [(0.6, 0.85)], hc.word_spans(words, [0], 0.6, 6))
check("words that aren't there are ignored", hc.word_spans(words, [9, -1], 0, 6) == [])
cli = hc.whisper_words_command({"kind": "cli", "bin": "whisper-cli", "model": "m.bin"}, "a.wav", "b")
check("whisper.cpp asked for a word to an entry, with fillers kept", "-ml" in cli and cli[cli.index("-ml") + 1] == "1" and "--prompt" in cli and "um" in cli[cli.index("--prompt") + 1].lower(), cli)
py = hc.whisper_words_command({"kind": "python"}, "a.wav", "b")
check("faster-whisper asked for each word's time", "word_timestamps=True" in py[2] and "initial_prompt" in py[2], py[2][:80])
check("smooth slow motion: enough pictures for each frame", [hc.smooth_factor(s) for s in (0.75, 0.5, 0.3, 0.25, 0.1)] == [2, 2, 4, 4, 8])
cmd = hc.smooth_command("in.mp4", "out.mp4", 25, 2, [1.0, 3.5])
check("worked out by motion, for the part used", "minterpolate=fps=50:mi_mode=mci" in " ".join(cmd) and cmd[cmd.index("-ss") + 1] == "1.000" and cmd[cmd.index("-t") + 1] == "2.500", cmd)

cube = hc.range_cube({"on": True, "hue": 0, "width": 40, "shift": 120, "sat": 1, "light": 0}, size=17)
lines = open(cube).read().splitlines()
check("the colour range is a 3D LUT", lines[1] == "LUT_3D_SIZE 17" and len(lines) == 2 + 17 ** 3, lines[:2])
lut = np.array([[float(v) for v in l.split()] for l in lines[2:]]).reshape(17, 17, 17, 3)     # [b][g][r]
check("pure red turns green", np.allclose(lut[0, 0, 16], [0, 1, 0], atol=0.02), lut[0, 0, 16])
check("blue is left alone", np.allclose(lut[16, 0, 0], [0, 0, 1], atol=0.02), lut[16, 0, 0])
check("greys are left alone", np.allclose(lut[8, 8, 8], [0.5, 0.5, 0.5], atol=0.02), lut[8, 8, 8])
check("the same change is the same file", hc.range_cube({"on": True, "hue": 0, "width": 40, "shift": 120, "sat": 1, "light": 0}, size=17) == cube)
check("an untouched range isn't used", not hc.range_used({"range": {"on": True, "shift": 0, "sat": 1, "light": 0}}) and not hc.range_used({"range": {"on": False, "shift": 90}}))

p = {"clips": [{"at": 0, "in": 0, "out": 60, "speed": 1, "kind": "media"}], "markers": [{"t": 12.0, "name": "Harbour"}, {"t": 40.5, "name": ""}]}
ch = hc.chapter_list(p)
check("chapters from markers, the first from the start", ch == [(0.0, "Start"), (12.0, "Harbour"), (40.5, "Chapter 2")] or [x[::2] for x in ch] == [(0.0, "Start"), (12.0, "Harbour"), (40.5, "Chapter 2")], ch)
check("each chapter runs to the next", [x[1] for x in ch] == [12.0, 40.5, 60.0], ch)
check("a marker at the start names the first chapter", hc.chapter_list({"clips": p["clips"], "markers": [{"t": 0.2, "name": "Intro"}, {"t": 30, "name": "B"}]})[0] == (0.0, 30, "Intro"))
check("no markers, no chapters", hc.chapter_list({"clips": p["clips"], "markers": []}) == [])
meta = hc.chapters_meta([(0.0, 12.0, "Start"), (12.0, 60.0, "A=B; #1")])
check("ffmpeg's chapter file, in milliseconds, its marks escaped", meta.startswith(";FFMETADATA1") and "START=12000" in meta and "END=60000" in meta and "title=A\\=B\\; \\#1" in meta, meta)
check("the list video sites read", hc.chapters_text([(0.0, 12, "Start"), (75.0, 90, "Market"), (3725, 4000, "Late")]) == "0:00 Start\n1:15 Market\n1:02:05 Late")

# ---------------------------------------------------------------- adjustment layers
c, ids = fresh([red, blue])
v1 = "v1"
check("red on V1", c.place(ids["red.mp4"], v1, 0.0) == "")
before = mean(picture(c, 1.0))
check("it's red to start with", before[0] > before[2] + 100, before)
c.seek(1.0)
aid = c.addAdjustment(-1)
adj = c._c(aid)
check("an adjustment layer over the shot under the playhead", adj and adj["kind"] == "adjust" and adj["track"] != "v1" and abs(hc.clip_end(adj) - 6.0) < 0.05 and abs(adj["at"] - 1.0) < 1e-6, adj)
check("it's picked, and says what it is", c._picked == [aid] and c._get_clip().get("mediaKind") == "adjust")
check("an adjustment layer can't go on V1 or the captions", not hc.accepts({"id": "v1", "kind": "video"}, adj, {}) and not hc.accepts({"id": "v9", "kind": "video", "role": "captions"}, adj, {})
      and hc.accepts({"id": "v2", "kind": "video"}, adj, {}))
same = mean(picture(c, 2.0))
check("on its own it changes nothing", np.allclose(same, before, atol=4), (same, before))
c.set(aid, "effects.bw", True)
g = mean(picture(c, 2.0))
check("black and white on the layer: what's under it goes grey", abs(g[0] - g[2]) < 8 and abs(g[0] - g[1]) < 8, g)
r0 = mean(picture(c, 0.5))
check("before the layer starts, it's red", r0[0] > r0[2] + 100, r0)
xml = c._xml(320, 180)
check("what's under the layer is one picture of its own", f'{adj["track"]}_under' in xml)
# something over the layer isn't changed by it
c.addTrack("video")
top = [t for t in c._p["tracks"] if t["kind"] == "video"][0]["id"]
check("blue on a track over the layer", c.place(ids["blue.mp4"], top, 0.0) == "")
bid = clip_on(c, ids["blue.mp4"])["id"]
c.set(bid, "transform.scale", 0.4)
pic = picture(c, 2.0)
mid, corner = mean(pic, "centre"), mean(pic, "corner")
check("the clip over the layer keeps its colour", mid[2] > mid[0] + 100, mid)
check("what's under the layer is still grey around it", abs(corner[0] - corner[2]) < 10, corner)
# a second layer over everything darkens all of it
c.seek(1.0)
aid2 = c.addAdjustment(-1)
check("a second layer goes over the blue clip", [t["id"] for t in c._p["tracks"] if t["kind"] == "video"].index(c._c(aid2)["track"])
      < [t["id"] for t in c._p["tracks"] if t["kind"] == "video"].index(top), c._p["tracks"])
c.set(aid2, "colour.exposure", -2.0)
pic2 = picture(c, 2.0)
mid2, corner2 = mean(pic2, "centre"), mean(pic2, "corner")
check("the top layer darkens the blue clip", mid2[2] < mid[2] - 40 and mid2[2] > mid2[0], (mid2, mid))
check("and what's under the lower layer, still grey", corner2.mean() < corner.mean() - 30 and abs(corner2[0] - corner2[2]) < 10, (corner2, corner))
c.undo()
check("undo takes the darkening back", np.allclose(mean(picture(c, 2.0), "centre"), mid, atol=6))
c.undo()
check("and the second layer", c._c(aid2) is None)
solo_a = [t for t in c._p["tracks"] if t["kind"] == "audio"][0]["id"]
c.setTrack(solo_a, "solo", True)
xml = c._xml(320, 180)
check("a solo elsewhere still silences what's under the layer", 'hide="audio"' in xml.split(f'{adj["track"]}_under"')[0] or "hide=\"both\"" in xml, "")
c.setTrack(solo_a, "solo", False)

# ---------------------------------------------------------------- one colour on its own
c, ids = fresh([red, blue])
c.place(ids["red.mp4"], "v1", 0.0)
c.place(ids["blue.mp4"], "v1", 6.0)
rid, bid = clip_on(c, ids["red.mp4"])["id"], clip_on(c, ids["blue.mp4"])["id"]
for cid in (rid, bid):
    c.set(cid, "colour.range.on", True)
    c.set(cid, "colour.range.hue", 0)
    c.set(cid, "colour.range.shift", 120)
gr = mean(picture(c, 1.0))
check("the reds turned green", gr[1] > gr[0] + 60, gr)
bl = mean(picture(c, 7.0))
check("the blue clip, with the same change, stays blue", bl[2] > bl[0] + 100 and bl[2] > bl[1] + 60, bl)
c.set(rid, "colour.range.sat", 0.0)
gs = mean(picture(c, 1.0))
check("its colour taken away: only that range goes grey", abs(gs[0] - gs[1]) < 12 and abs(gs[0] - gs[2]) < 12, gs)
c.set(rid, "colour.range.hue", 999)
check("the hue stays a hue", c._c(rid)["colour"]["range"]["hue"] == 360.0)
c.set(rid, "colour.range.on", False)
back = mean(picture(c, 1.0))
check("turned off, it's red again", back[0] > back[2] + 100, back)
c._picked = [rid]
check("the inspector has the range", c._get_clip()["colourRange"]["shift"] == 120 and c._get_clip()["colourRange"]["on"] is False)

# ---------------------------------------------------------------- editing by what's said
c, ids = fresh([talk])
c.place(ids["talk.mp4"], "v1", 0.0)
tid = clip_on(c, ids["talk.mp4"])["id"]
c._picked = [tid]
check("not listened to yet", c._get_clip().get("heard") is False)
c.listenWords(tid)
check("listening", c._get_clip().get("hearing") is True)
check("the words are written down", wait(lambda: hc.heard_path(talk).is_file(), 60))
wait(lambda: not c._hearing, 10)
asked = json.load(open(os.path.join(home, "asked.json")))
check("asked for one word an entry, ums kept", asked[asked.index("-ml") + 1] == "1" and "--prompt" in asked and asked[asked.index("-f") + 1].endswith(".wav"), asked)
got = c.wordsOf(tid)
check("eight words, in order", [w["w"] for w in got] == ["So", "um,", "we", "left", "uh", "before", "light", "Er"], got)
check("the ums, uhs and ers are marked", [w["filler"] for w in got] == [False, True, False, False, True, False, False, True])
check("each word knows where it is on the timeline", abs(got[3]["at"] - 2.0) < 1e-3)
check("the clip says it's been listened to", c._get_clip().get("heard") is True and c._get_clip().get("hearing") is False)
c.listenWords(tid)
check("listening again uses what's written down", not c._hearing)
c.cutFillers(tid)
pieces = sorted((x for x in c._p["clips"] if x.get("media") == ids["talk.mp4"]), key=lambda x: x["at"])
gone = 6.0 - hc.total(c._p)
# um: 0.85..1.4 (0.55), uh: 2.5..3.1 (0.6), Er (the last word): 4.25..4.84 (0.59)
check("the three filler words are cut out, closing up", abs(gone - 1.74) < 0.02 and len(pieces) == 4, (gone, [(x["in"], x["out"]) for x in pieces]))
check("nothing of them is left to hear", c.wordsOf(pieces[0]["id"]) and all(not w["filler"] for p_ in pieces for w in c.wordsOf(p_["id"])))
check("what's left is still in order", [w["w"] for p_ in pieces for w in c.wordsOf(p_["id"])] == ["So", "we", "left", "before", "light"])
c.cutFillers(pieces[0]["id"])
check("no fillers left to cut", abs(6.0 - hc.total(c._p) - gone) < 1e-6)
second = pieces[1]
left = next(w for w in c.wordsOf(second["id"]) if w["w"] == "left")
c.cutWords(second["id"], [left["i"]])
check("a picked word cut out", "left" not in [w["w"] for x in c._p["clips"] if x.get("media") == ids["talk.mp4"] for w in c.wordsOf(x["id"])])
c.undo()
check("undo brings it back", "left" in [w["w"] for x in c._p["clips"] if x.get("media") == ids["talk.mp4"] for w in c.wordsOf(x["id"])])
c.cutWords(second["id"], [999, "x"])
check("nonsense picks cut nothing", "left" in [w["w"] for x in c._p["clips"] if x.get("media") == ids["talk.mp4"] for w in c.wordsOf(x["id"])])
c.setTrack("v1", "locked", True)
n_before = len(c._p["clips"])
c.cutWords(second["id"], [left["i"]])
check("a locked track isn't cut", len(c._p["clips"]) == n_before)
c.setTrack("v1", "locked", False)
c.set(second["id"], "reverse", True)
check("a clip played backwards has no words to cut", c.wordsOf(second["id"]) == [])

# ---------------------------------------------------------------- smooth slow motion
c, ids = fresh([moving])
c.place(ids["moving.mp4"], "v1", 0.0)
mid_ = clip_on(c, ids["moving.mp4"])["id"]
c._c(mid_)["in"] = 1.0; c._keep()
c.set(mid_, "speed", 0.5)
def repeats():
    frames = [picture(c, 1.0 + k / 25) for k in range(10)]
    return sum(1 for a, b in zip(frames, frames[1:]) if np.abs(a - b).mean() < 0.5)
plain = repeats()
check("slowed down, each picture shows twice", plain >= 4, plain)
c._picked = [mid_]
check("smooth slow motion is off to start with", c._get_clip()["smooth"] == "off")
c.smoothSlow(mid_, True)
check("the pictures in between are being worked out", c._get_clip()["smooth"] == "making" and mid_ in c._smoothing)
check("and they're done", wait(lambda: mid_ not in c._smoothing, 240))
m = c._p["media"][0]
made = hc.smooth_ready(m, c._c(mid_))
check("the copy is there", bool(made) and c._get_clip()["smooth"] == "ready", c._get_clip()["smooth"])
fps = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", made], capture_output=True, text=True).stdout.strip()
check("with twice the pictures", fps in ("50/1", "50"), fps)
smooth = repeats()
check("smooth: a new picture every frame", smooth <= 1, (smooth, plain))
same_place = mean(picture(c, 2.0)); c._c(mid_)["effects"]["smooth"] = False; plain_place = mean(picture(c, 2.0)); c._c(mid_)["effects"]["smooth"] = True
check("at the same moment of the footage", np.allclose(same_place, plain_place, atol=12), (same_place, plain_place))
c.set(mid_, "speed", 0.25)
check("slower again: more pictures are worked out", c._get_clip()["smooth"] in ("making", "ready") and wait(lambda: mid_ not in c._smoothing, 240))
check("four times as many", "-x4-" in hc.smooth_ready(m, c._c(mid_)))
check("what's made is the part used and a little more", c._c(mid_)["effects"]["smoothSpan"] == [0.5, 3.0], c._c(mid_)["effects"].get("smoothSpan"))
c._c(mid_)["in"] = 0.0
check("trimmed past what was made: it says so", c._get_clip()["smooth"] == "stale", c._get_clip()["smooth"])
c.set(mid_, "speed", 1.0)
check("at full speed there's nothing to work out", c._get_clip()["smooth"] == "even")
c.smoothSlow(mid_, False)
check("off", c._get_clip()["smooth"] == "off")

# ---------------------------------------------------------------- chapters in the video
c, ids = fresh([red, blue])
c.place(ids["red.mp4"], "v1", 0.0)
c.place(ids["blue.mp4"], "v1", 6.0)
c.setProject("name", "Harbour")
c.seek(4.0); c.addMarker("The market")
c.seek(8.0); c.addMarker("Evening")
check("the chapters the film will have", [x["name"] for x in c.chapters] == ["Start", "The market", "Evening"] and c.chaptersOn)
c.export("h264", "small", "half")
check("the video is made", wait(lambda: not c._export["busy"], 300) and wait(lambda: os.path.isfile(c._export["path"] or "/nonexistent"), 30), c._export.get("log", "")[-300:])
target = c._export["path"]
def chaps(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-of", "json", path], capture_output=True, text=True).stdout
    return json.loads(out or "{}").get("chapters", [])
check("with its chapters inside", wait(lambda: len(chaps(target)) == 3, 60), chaps(target))
cs = chaps(target)
check("named and timed by the markers", [x.get("tags", {}).get("title") for x in cs] == ["Start", "The market", "Evening"] and abs(float(cs[1]["start_time"]) - 4.0) < 0.05, cs)
listing = os.path.join(os.path.dirname(target), "Harbour chapters.txt")
check("and the list for video sites alongside", os.path.isfile(listing) and open(listing).read().splitlines()[:3] == ["0:00 Start", "0:04 The market", "0:08 Evening"])
check("the video still plays: its picture is there", "video" in subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", target], capture_output=True, text=True).stdout)
c.setProject("chapters", False)
check("chapters can be left out", not c.chaptersOn)

print(f"{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
