#!/usr/bin/env python3
"""Tempo, pro pass five: a drum recording into notes, the chords of a recording or of written notes, mastering toward
a song you like (and hearing it in place of yours, as loud), and a film to score.
Usage: tempo_pass5_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)"""
import json, math, os, subprocess, sys, tempfile, time
from collections import Counter
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0:
    sys.exit("not as root: this test writes and removes files")
home = tempfile.mkdtemp(prefix="tempo5-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/data", XDG_CONFIG_HOME=home + "/config", XDG_CACHE_HOME=home + "/cache",
                  QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
for d in ("Music", "Videos"):
    os.makedirs(os.path.join(home, d), exist_ok=True)
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
import numpy as np
import huginn_tempo_engine as se

SR = se.SR
passed = failed = 0
def ok(what, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL", what, extra, flush=True)

def place(x, snd, t, v=1.0):
    snd = snd.mean(axis=1) if snd.ndim == 2 else snd
    s0 = int(t * SR); e = min(len(x), s0 + len(snd))
    x[s0:e] += snd[:e - s0] * v

def drums(kit, tempo, bars, hats_in=lambda bar: True, kicks=(0, 4), rng=None):
    beat = 60 / tempo
    x = np.zeros(int(SR * (bars * 4 * beat + 1)))
    want = []
    for bar in range(bars):
        for k in range(8):
            b = bar * 4 + k * 0.5
            for h in (["hat"] if hats_in(bar) else []) + (["kick"] if k in kicks else []) + (["snare"] if k in (2, 6) else []):
                v = (rng.uniform(0.5, 1.0) if rng is not None else 0.9) * (0.6 if h == "hat" else 1.0)
                place(x, se.drum_sound(kit, se.DRUM_PITCH[h]), b * beat, v)
                want.append((b * beat, h))
    return x, want

def score(got, want, tol=0.03):
    miss = [w for w in want if not any(g[1] == w[1] and abs(g[0] - w[0]) < tol for g in got)]
    extra = [g for g in got if not any(g[1] == w[1] and abs(g[0] - w[0]) < tol for w in want)]
    return miss, extra

# ================================================================================================ drums into notes
x, want = drums("studio", 120.0, 4, hats_in=lambda bar: bar < 3)
t0 = time.time()
got = se.drum_hits(x)
took = time.time() - t0
miss, extra = score(got, want)
ok("every hit of a beat found, kick, snare and hi-hat, none made up", not miss and not extra, (miss[:4], extra[:4]))
ok("hits at the same moment are each found (a hat under a kick, under a snare)", Counter(n for _t, n, _s in got) == Counter({"hat": 24, "kick": 8, "snare": 8}))
offs = [g[0] - w[0] for w in want for g in got if g[1] == w[1] and abs(g[0] - w[0]) < 0.03]
ok("each where it was struck, to a few milliseconds", max(abs(o) for o in offs) < 0.006, max(abs(o) for o in offs))
ok("quickly: 8 seconds in a fraction of one", took < 1.5, took)
ok("a hit right at the very start is found", any(abs(g[0]) < 0.01 and g[1] == "kick" for g in got))
rng = np.random.default_rng(3)
found = total = made_up = 0
for kit in ("studio", "vintage", "electronic"):
    for tempo in (95.0, 140.0):
        x2, want2 = drums(kit, tempo, 4, hats_in=lambda bar: bar != 2, kicks=(0, 3, 5), rng=rng)
        x2 += rng.normal(0, 10 ** (-45 / 20), len(x2))
        miss2, extra2 = score(se.drum_hits(x2), want2)
        found += len(want2) - len(miss2); total += len(want2); made_up += len(extra2)
ok("three kits, two tempos, hits from half as hard to full, under a noise floor: nine in ten found", found / total > 0.9, (found, total))
ok("…and next to nothing made up", made_up <= 3, made_up)
notes = se.hits_to_notes([(0.5, "kick", 1.0), (0.75, "snare", 0.5), (1.0, "hat", 0.0)], lambda t: t * 2, 0.5)
ok("hits become notes in beats from the region's start, by how hard", [(n["t"], n["p"], n["v"]) for n in notes] == [(0.5, 36, 127), (1.0, 38, 86), (1.5, 42, 45)], notes)
ok("silence has no hits", se.drum_hits(np.zeros(SR * 2)) == [] and se.drum_hits(np.zeros(100)) == [])

# ================================================================================================ chords
prog = ["C", "Am", "F", "G", "Em", "Bb", "D", "F#m"]
def played(inst):
    y = np.zeros(int(SR * (2 * len(prog) + 2)))
    for k, ch in enumerate(prog):
        for pch in se.chord_pitches(ch):
            place(y, se.instrument_note({"id": inst}, pch, 90, 1.9), k * 2.0)
    return y
beats = [i * 0.5 for i in range(len(prog) * 4)]
want_ch = [[float(4 * k), c] for k, c in enumerate(prog)]
for inst in ("organ", "epiano"):
    y = played(inst)
    names = se.name_chords([se.chroma_of(y, b, b + 0.5) for b in beats])
    ok(f"the chords of a progression played on {inst}: all eight, where they change", se.merge_chords(list(range(len(beats))), names) == want_ch,
       se.merge_chords(list(range(len(beats))), names))
y = played("pluck")
names = se.name_chords([se.chroma_of(y, b, b + 0.5) for b in beats])
right = sum(1 for k, c in enumerate(prog) if names[4 * k] == c)
ok("on a bright plucked synth, at least six of eight (a minor chord can read as major)", right >= 6, names[::4])
notes = [{"t": k * 4.0, "d": 3.5, "p": p, "v": 90} for k, ch in enumerate(prog) for p in se.chord_pitches(ch)]
ok("the chords of written notes", se.merge_chords(list(range(32)), se.name_chords([se.notes_chroma(notes, b, b + 1) for b in range(32)])) == want_ch)
walk = [{"t": 0.0, "d": 4, "p": 48, "v": 90}, {"t": 0.0, "d": 4, "p": 64, "v": 90}, {"t": 0.0, "d": 4, "p": 67, "v": 90}, {"t": 2.0, "d": 0.5, "p": 65, "v": 60}]
ok("a passing note doesn't make a chord", se.merge_chords(list(range(4)), se.name_chords([se.notes_chroma(walk, b, b + 1) for b in range(4)])) == [[0.0, "C"]])
ok("silence between chords ends the chord before it", se.merge_chords([0, 1, 2, 3], ["C", "C", "", "G"]) == [[0.0, "C"], [2.0, ""], [3.0, "G"]])
ok("a chord's notes: a low root and the chord near middle C", se.chord_pitches("Am") == [45, 57, 60, 64] and se.chord_pitches("C") == [36, 60, 64, 67] and se.chord_pitches("F#m") == [42, 54, 57, 61])

# ================================================================================================ the reference
def song(bright, loud):
    t = np.arange(SR * 8) / SR
    rngs = np.random.default_rng(1)
    low = np.sin(2 * math.pi * 55 * t) * 0.5 + np.sin(2 * math.pi * 220 * t) * 0.3
    hiss = rngs.normal(0, 1, len(t))
    hi = se.filt(hiss.astype(np.float32), "highpass", 4000) * bright
    y = (low + hi) * (0.4 + 0.3 * (np.sin(2 * math.pi * 0.5 * t) > 0))
    y = y / np.sqrt((y ** 2).mean()) * 10 ** (loud / 20)
    return np.stack([y, y * 0.97], axis=1).astype(np.float32)
dull, bright = song(0.05, -26), song(0.9, -16)
ref = se.reference_of(bright)
ok("a reference's loudness and balance, as streaming services hear it", abs(ref["loud"] - se.loudness(bright)) < 0.01 and len(ref["bands"]) == 4 and ref["width"] < 0.1, ref)
plain = se.assist_master(dull, "clean", "streaming")
toward = se.assist_master(dull, "clean", "streaming", ref)
gap = lambda m: sum(abs(a - b) for a, b in zip(se.band_levels(se.Mastering(m).run(dull)), ref["bands"]))
ok("mastered toward the reference, its balance comes nearer the reference's than plain mastering does", gap(toward) < gap(plain) - 3 and toward.get("toReference"), (gap(toward), gap(plain)))
ok("…moving the air up, as the reference has more of it", toward["eq"][3] > plain["eq"][3] and toward["eq"][3] <= 6.0, (toward["eq"], plain["eq"]))
like = se.assist_master(dull, "clean", "reference", ref)
ok("\"as loud as the reference\"", abs(like["after"] - ref["loud"]) < 0.6, (like["after"], ref["loud"]))
ok("without a reference, that target is streaming's", abs(se.assist_master(dull, "clean", "reference")["after"] - (-14.0)) < 0.6)

# ================================================================================================ in Tempo
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication
app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
import huginn_tempo as ht
def spin(ms):
    loop_ = QEventLoop(); QTimer.singleShot(ms, loop_.quit); loop_.exec()
def wait(cond, seconds=60):
    end = time.time() + seconds
    while time.time() < end and not cond():
        spin(50)
    return cond()

T = ht.Tempo(); T._demo = False
said = []
T.said.connect(lambda text, bad: said.append(text))
T.newProject("empty", "Harbour"); spin(100)
wav = Path(home) / "drums.wav"
x, want = drums("studio", float(T._p["tempo"]), 4, hats_in=lambda bar: bar < 3)
se.write_wav(str(wav), np.stack([x, x], axis=1).astype(np.float32), 24)
T.importFiles([str(wav)]); spin(200)
rec = next(r for r in T._p["regions"] if r.get("kind") == "audio")
T.seek(0.0)
n_tracks = len(T._p["tracks"])
T.drumNotes(rec["id"])
ok("drum notes: being listened to", T.region(rec["id"])["drumming"] is True)
ok("…and a drum track appears under the recording", wait(lambda: len(T._p["tracks"]) == n_tracks + 1, 30))
order = [t["id"] for t in T._p["tracks"]]
dt = order[order.index(rec["track"]) + 1]
dreg = next(r for r in T._p["regions"] if r["track"] == dt)
ok("on a drum kit, as one region the recording's length", (T._t(dt)["instrument"] or {}).get("id") == "drums" and dreg["start"] == rec["start"] and abs(dreg["length"] - rec["length"]) < 1e-6)
beat_of = 60 / float(T._p["tempo"])
ok("its notes are the hits, in beats", Counter((round(n["t"] * 2) / 2, n["p"]) for n in dreg["notes"]) == Counter((round(w[0] / beat_of * 2) / 2, se.DRUM_PITCH[w[1]]) for w in want), len(dreg["notes"]))
ok("and it says what it found", any("8 kick, 8 snare, 24 hi-hat" in s_ for s_ in said), said[-2:])
T.undo()
ok("undo takes the drum track away", len(T._p["tracks"]) == n_tracks)
midi_t = T.addTrack("instrument", "grand")
mreg = T.addRegion(midi_t, 0.0, 16.0)
for k, ch in enumerate(["C", "Am", "F", "G"]):
    for p in se.chord_pitches(ch):
        T.addNote(mreg, k * 4.0, p, 3.5, 90)
T.findChords(mreg)
ok("the chords of written notes, over the region", T._r(mreg).get("chords") == [[0.0, "C"], [4.0, "Am"], [8.0, "F"], [12.0, "G"]], T._r(mreg).get("chords"))
pad_r = T.chordsToTrack(mreg)
pr = T._r(pad_r)
ok("played on a pad under it, each chord held to the next", pr and len(pr["notes"]) == 16 and {n["d"] for n in pr["notes"]} == {4.0} and (T._t(pr["track"])["instrument"] or {}).get("id") == "pad", pr and pr["notes"][:3])
T.findChords(rec["id"])
ok("drums: no chords to find, said so", wait(lambda: not T.region(rec["id"])["chording"], 30) and not T._r(rec["id"]).get("chords"))
# a recording of chords
cw = Path(home) / "keys.wav"
y = np.zeros(int(SR * 9))
for k, ch in enumerate(["G", "Em", "C", "D"]):                 # a bar each, at the song's tempo
    for pch in se.chord_pitches(ch):
        place(y, se.instrument_note({"id": "organ"}, pch, 90, 3.8 * beat_of), k * 4 * beat_of)
se.write_wav(str(cw), np.stack([y, y], axis=1).astype(np.float32) * 0.5, 24)
T.seek(16.0)
T.importFiles([str(cw)]); spin(200)
krec = next(r for r in T._p["regions"] if r.get("kind") == "audio" and r["name"] == "keys")
T.findChords(krec["id"])
ok("the chords of a recording, beat by beat, where they change", wait(lambda: not T.region(krec["id"])["chording"], 60) and
   [c for c in (T._r(krec["id"]).get("chords") or []) if c[1]] == [[0.0, "G"], [4.0, "Em"], [8.0, "C"], [12.0, "D"]], T._r(krec["id"]).get("chords"))
ok("…said", any("G Em C D" in s_ for s_ in said), said[-1:])
# the reference
refwav = Path(home) / "reference.wav"
se.write_wav(str(refwav), bright, 24)
T.setReference(str(refwav))
ok("a reference song: listened to", T.referencing and wait(lambda: not T.referencing, 120))
r_ = T._p["master"].get("reference") or {}
ok("its loudness and balance kept, and how loud the song is", abs(r_.get("loud", 0) - ref["loud"]) < 0.05 and r_.get("name") == "reference" and "songLoud" in r_, r_)
song_loud = r_["songLoud"]
T.hearReference(True)
ok("hearing the reference instead", T.hearingReference)
mx = se.Mixer(json.loads(json.dumps(T._p)), T._folder)
mx.seek(int(SR * 2.0))
heard = np.concatenate([mx.render(se.BLOCK) for _ in range(int(SR * 3 / se.BLOCK))])
ok("the reference plays where the song is, at the same place", np.allclose(heard[:2048], bright[int(SR * 2):int(SR * 2) + 2048] * se.db(r_["match"]), atol=1e-4))
ok("…just as loud as the song, to compare fairly", abs(se.loudness(heard) - song_loud) < 1.5, (se.loudness(heard), song_loud))
T.hearReference(False)
mx = se.Mixer(json.loads(json.dumps(T._p)), T._folder)
ok("back to the song", mx.ref is None)
T.masterSong("clean", "reference")
ok("mastering toward it", wait(lambda: not T.mastering, 180) and (T._p["master"].get("mastering") or {}).get("toReference") is True)
ok("as loud as the reference", abs(T._p["master"]["mastering"]["after"] - ref["loud"]) < 1.0, T._p["master"]["mastering"]["after"])
T.hearReference(True)
ok("once mastered, the reference is matched to the mastered song", abs(T._p["master"]["reference"]["match"] - (T._p["master"]["mastering"]["after"] - r_["loud"])) < 0.01)
T.hearReference(False)
T.removeReference()
ok("the reference taken away", "reference" not in T._p["master"])
T.undo()
ok("and back with undo", "reference" in T._p["master"])
# the film
film = Path(home) / "Videos" / "boat.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=4", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(film)], check=True)
info = ht.probe_video(str(film))
ok("a film's length, rate and sound", abs(info["duration"] - 4.0) < 0.1 and info["fps"] == 25.0 and info["audio"] and info["width"] == 320, info)
ok("not a film", ht.probe_video(str(refwav)) == {} and ht.probe_video("/nonexistent.mp4") == {})
n_tracks = len(T._p["tracks"])
T.importFiles([str(film)])
ok("a film brought in is the song's picture", T.video.get("name") == "boat.mp4" and T.video.get("duration") > 3.9)
ok("its sound on a track of its own", len(T._p["tracks"]) == n_tracks + 1 and T._p["tracks"][-1]["name"].startswith("boat"))
ok("its pictures are made for the Picture window", wait(lambda: T.video.get("ready"), 60))
f1, f2 = T.videoFrame(1.0), T.videoFrame(1.05)
ok("a picture for each moment, from the right second", f1.endswith("f00011.jpg") and f2.endswith("f00011.jpg") and T.videoFrame(2.0).endswith("f00021.jpg"), (f1, T.videoFrame(2.0)))
ok("none before the film or after it", T.videoFrame(-0.5) == "" and T.videoFrame(9.0) == "" and T.videoFrame(float("nan")) == "")
T.setVideoOffset(1.5)
ok("the song can start partway into the film", T.video["offset"] == 1.5 and T.videoFrame(0.5).endswith("f00021.jpg"))
T.setVideoOffset(0.0)
out = T.export("video")
ok("Export › Film: the film with the song under it", wait(lambda: bool(T.lastExport) and T.lastExport.endswith(".mp4"), 240), T.lastExport)
streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name:format=duration", "-of", "json", T.lastExport], capture_output=True, text=True).stdout
st = json.loads(streams)
ok("its picture copied as it was, and the song's sound", sorted(s_["codec_type"] for s_ in st["streams"]) == ["audio", "video"] and
   next(s_ for s_ in st["streams"] if s_["codec_type"] == "video")["codec_name"] == "h264" and abs(float(st["format"]["duration"]) - 4.0) < 0.2, st)
ok("the mux: song later than the film's start, or earlier", ht.mux_command("v.mp4", "s.wav", "o.mp4", 2.0, 10)[6:10] == ["-itsoffset", "2.000", "-i", "s.wav"]
   and ht.mux_command("v.mp4", "s.wav", "o.mp4", -1.5, 10)[6:10] == ["-ss", "1.500", "-i", "s.wav"])
ok("a long film gets fewer pictures a second", ht.picture_rate(3600, 25) == 4.0 and ht.picture_rate(60, 25) == 10.0 and ht.picture_rate(60, 8) == 8.0)
T.undo(); T.undo()                          # (where the song starts in it, then the film)
ok("undo takes the film and its sound away together", not T.video and len(T._p["tracks"]) == n_tracks, (T.video, len(T._p["tracks"]), n_tracks))

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
