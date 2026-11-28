#!/usr/bin/env python3
"""Tempo, pro pass three: sound for games. Loops that join, loop points in the file, one loudness for every file,
finding the sound in a long take, synthesised effects, variations, and the commands in Tempo that use them.
Usage: tempo_game_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)"""
import json, math, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0:
    sys.exit("not as root: this test writes and removes files")
home = tempfile.mkdtemp(prefix="tempo3-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/data", XDG_CONFIG_HOME=home + "/config", XDG_CACHE_HOME=home + "/cache", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
import numpy as np
import huginn_tempo_engine as se
import huginn_tempo_game as tg

SR = se.SR
passed = failed = 0
def ok(what, cond, extra=""):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1
        print("FAIL", what, extra)
def tone(f, secs, amp=0.5):
    t = np.arange(int(secs * SR)) / SR
    return (np.sin(2 * math.pi * f * t) * amp).astype(np.float32)
def pitch_of(x):
    x = np.asarray(x, np.float64); x = x if x.ndim == 1 else x.mean(axis=1)
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.argmax(spec) * SR / len(x))

# ================================================================================================ loops that join
body = int(SR * 2.0)
music = tg.stereo(tone(220, 2.0))
ring = tg.stereo(tone(220, 0.5, 0.25) * np.linspace(1, 0, int(SR * 0.5)).astype(np.float32))     # what rings on after the last bar
loop = tg.seamless(np.concatenate([music, ring]), body)
ok("a loop is exactly as long as the music, not the music and its tail", len(loop) == body)
ok("the tail is under the start: the first half second is louder, the rest untouched", np.abs(loop[:SR // 2]).max() > 0.6 and np.allclose(loop[SR // 2:], music[SR // 2:]))
again = np.concatenate([loop, loop])
jump = np.abs(np.diff(again[:, 0]))[body - 3:body + 3].max()
ok("played round, the join is no bigger a step than the wave's own", jump <= np.abs(np.diff(music[:, 0])).max() * 1.6, jump)
plain = np.concatenate([np.concatenate([music, ring])[:body], np.concatenate([music, ring])[:body]])
ok("…whereas the tail cut off is silence after a ringing bar (what the fold is for)", np.abs(plain[body:body + 64]).max() < np.abs(again[body + 1000:body + 5000]).max())
ok("a tail longer than the music wraps round more than once and nothing is lost", abs(tg.seamless(np.ones((1000, 2), np.float32), 300).sum() - 2000) < 1e-3 and len(tg.seamless(np.ones((1000, 2), np.float32), 300)) == 300)

# =============================================================================================== loop points in files
out = Path(home) / "out"; out.mkdir()
tg.write_wav(str(out / "a.wav"), loop, 24, SR, (0, body))
info = tg.read_wav_info(str(out / "a.wav"))
ok("a 24 bit WAV with its loop written in it", info["rate"] == SR and info["channels"] == 2 and info["bits"] == 24 and info["frames"] == body and info["loop"] == (0, body), info)
back = se.load_audio(str(out / "a.wav"))
ok("Tempo (and so anything else) reads the file back as the same sound", len(back) == body and np.abs(back - loop).max() < 2e-4, np.abs(back[:len(loop)] - loop[:len(back)]).max())
tg.write_wav(str(out / "b.wav"), tg.shaped(loop, 22050, True), 16, 22050, None)
info = tg.read_wav_info(str(out / "b.wav"))
ok("16 bit, mono, 22.05 kHz: half the samples and one channel, no loop written", info["rate"] == 22050 and info["channels"] == 1 and info["bits"] == 16 and abs(info["frames"] - body * 22050 // SR) <= 1 and info["loop"] is None, info)
ok("it is still the same note", abs(pitch_of(se.load_audio(str(out / "b.wav"))) - 220) < 2, pitch_of(se.load_audio(str(out / "b.wav"))))
ok("a one-channel file at another rate comes into Tempo at its own level (it came in 3 dB down)", abs(np.abs(se.load_audio(str(out / "b.wav"))).max() - np.abs(loop).max()) < 0.03, float(np.abs(se.load_audio(str(out / "b.wav"))).max()))
ok("an intro and a loop in one file: the loop starts where the intro ends", (tg.write(str(out / "c.wav"), np.concatenate([music, loop]), "wav16", 44100, False, (2.0, 4.0)), tg.read_wav_info(str(out / "c.wav"))["loop"])[1] == (88200, 176400))
ok("a loop that isn't inside the sound isn't written", (tg.write_wav(str(out / "d.wav"), loop, 16, SR, (10, body + 5)), tg.read_wav_info(str(out / "d.wav"))["loop"])[1] is None)
if shutil.which("ffmpeg") and shutil.which("ffprobe"):
    good = tg.write(str(out / "e.ogg"), loop, "ogg", 44100, False, (0.0, 2.0))
    tags = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream_tags:format_tags:stream=sample_rate,channels", "-of", "json", str(out / "e.ogg")], capture_output=True, text=True).stdout)
    flat = {k.upper(): v for blk in [tags.get("format", {}).get("tags", {})] + [s.get("tags", {}) for s in tags.get("streams", [])] for k, v in blk.items()}
    ok("an Ogg carries the loop as LOOPSTART and LOOPLENGTH, in samples of its own rate", good and flat.get("LOOPSTART") == "0" and flat.get("LOOPLENGTH") == "88200" and tags["streams"][0]["sample_rate"] == "44100", (good, flat))
    ok("FLAC too, in mono", tg.write(str(out / "f.flac"), loop, "flac", SR, True, None) and se.load_audio(str(out / "f.flac")).shape[0] == body)
else:
    print("(no ffmpeg here: Ogg and FLAC files are skipped)")

# ================================================================================================= one level for all
quiet, loud = tg.stereo(tone(440, 3.0, 0.05)), tg.stereo(tone(440, 3.0, 0.7))
a, ia = tg.normalise(quiet, "lufs", -16.0); b, ib = tg.normalise(loud, "lufs", -16.0)
ok("a quiet sound and a loud one come out at the loudness asked for", abs(se.loudness(a) + 16) < 0.2 and abs(se.loudness(b) + 16) < 0.2 and ia["gain"] > 10 and ib["gain"] < -10, (se.loudness(a), se.loudness(b), ia, ib))
c, ic = tg.normalise(quiet, "peak", -1.0)
ok("to a peak: the highest it goes is the peak asked for", abs(tg.true_peak(c) + 1.0) < 0.05 and ic["peak"] == -1.0, (tg.true_peak(c), ic))
spiky = quiet.copy(); spiky[SR] = 0.9
d, idn = tg.normalise(spiky, "lufs", -10.0)
ok("when the loudness asked for would clip, it stops at the ceiling and says how far short", tg.true_peak(d) <= -0.95 and "quieter than asked" in idn["note"] and se.loudness(d) < -10.5, (tg.true_peak(d), idn))
e, ie = tg.normalise(tg.stereo(tone(880, 0.1, 0.1)), "lufs", -16.0)
ok("a sound too short to measure is brought to the peak, and says so", abs(tg.true_peak(e) + 1.0) < 0.1 and "too short" in ie["note"], ie)
ok("silence stays silence, and “none” changes nothing", np.all(tg.normalise(np.zeros((SR, 2), np.float32), "lufs", -16)[0] == 0) and np.array_equal(tg.normalise(loud, "none")[0], loud))
between = np.zeros(4000, np.float32); between[1000:1008] = [0.9, -0.9] * 4       # the wave between these samples goes higher than they do
ok("the true peak is what the sound reaches between its samples", tg.true_peak(between) > 20 * math.log10(0.9) + 0.3, tg.true_peak(between))

# ============================================================================================ the sound in a long take
take = np.zeros(int(SR * 6.0), np.float32)
for at, secs in ((0.5, 0.8), (2.0, 0.4), (3.5, 1.2)):
    take[int(at * SR):int((at + secs) * SR)] = tone(300, secs, 0.4)
take[int(5.5 * SR):int(5.5 * SR) + 200] = 0.3                      # a click
take += (np.random.default_rng(1).standard_normal(len(take)) * 0.0008).astype(np.float32)     # the room
spans = tg.sound_spans(take, -45.0, 0.3, 0.05, 0.02)
ok("three lines in one take are three spans, the click left out", len(spans) == 3 and all(abs(a_ / SR - want) < 0.03 for (a_, _b), want in zip(spans, (0.48, 1.98, 3.48))), [(round(a_ / SR, 3), round(b_ / SR, 3)) for a_, b_ in spans])
ok("each has a little room either side, and none runs into the next", all(b_ <= spans[k + 1][0] for k, (_a, b_) in enumerate(spans[:-1])) and abs(spans[0][1] / SR - 1.32) < 0.03)
ok("a longer gap asked for joins lines that are close", len(tg.sound_spans(take, -45.0, 0.9, 0.05, 0.02)) == 2)
ok("silence has no spans; one unbroken sound has one", tg.sound_spans(np.zeros(SR, np.float32)) == [] and len(tg.sound_spans(tone(200, 1.0))) == 1)

# ==================================================================================================== sound effects
kinds = [k for k, _n in tg.SFX_KINDS]
sounds = {k: tg.sfx(tg.sfx_preset(k, 3), 3) for k in kinds}
ok("every kind makes a sound: not silent, not clipped flat, not endless", all(0.02 < len(x) / SR < 10.5 and 0.01 < np.abs(x).max() <= 1.0 and np.isfinite(x).all() for x in sounds.values()), {k: (round(len(x) / SR, 2), round(float(np.abs(x).max()), 2)) for k, x in sounds.items()})
ok("the same numbers make the same sound; another seed makes another sound of the kind", np.array_equal(tg.sfx(tg.sfx_preset("explosion", 5), 5), tg.sfx(tg.sfx_preset("explosion", 5), 5))
   and tg.sfx_preset("coin", 1) != tg.sfx_preset("coin", 2))
sine = dict(tg.SFX_FIELDS, wave="sine", freq=0.3, sustain=0.6, decay=0.1)
ok("its pitch is sfxr's: “0.3” is 321 Hz", abs(pitch_of(tg.sfx(sine)[2000:20000]) - 44100 * 8 / int(100 / (0.3 ** 2 + 0.001))) < 6, pitch_of(tg.sfx(sine)[2000:20000]))
up = tg.sfx(dict(sine, slide=0.25)); down = tg.sfx(dict(sine, slide=-0.25))
ok("a slide up ends higher than it starts, a slide down lower", pitch_of(up[-9000:-3000]) > pitch_of(up[:6000]) * 1.2 and pitch_of(down[-9000:-3000]) < pitch_of(down[:6000]) * 0.85, (pitch_of(up[:6000]), pitch_of(up[-9000:-3000]), pitch_of(down[:6000]), pitch_of(down[-9000:-3000])))
step = tg.sfx(dict(sine, arp_amount=0.5, arp_time=0.6))
ok("a step jumps the pitch part way through (the coin's two notes)", pitch_of(step[-12000:-4000]) > pitch_of(step[:3000]) * 1.15, (pitch_of(step[:3000]), pitch_of(step[-12000:-4000])))
env = tg.sfx(dict(sine, attack=0.3, sustain=0.3, decay=0.5))
ok("attack, hold and decay: quiet at the start, full in the middle, gone at the end", np.abs(env[:500]).max() < 0.1 and np.abs(env[len(env) // 3:len(env) // 2]).max() > 0.5 and np.abs(env[-300:]).max() < 0.05)
stopped = tg.sfx(dict(sine, slide=-0.4, freq_limit=0.25, sustain=0.8))
ok("with a lowest pitch set, a sound sliding down stops there", np.abs(stopped[-2000:]).max() == 0 and np.abs(stopped[:2000]).max() > 0.1)
bright = tg.sfx(dict(tg.SFX_FIELDS, wave="noise", sustain=0.5), 1); dull = tg.sfx(dict(tg.SFX_FIELDS, wave="noise", sustain=0.5, lp_cutoff=0.3), 1); thin = tg.sfx(dict(tg.SFX_FIELDS, wave="noise", sustain=0.5, hp_cutoff=0.8), 1)
hf = lambda x: float(np.abs(np.fft.rfft(x))[len(x) // 8:].sum() / max(1e-9, np.abs(np.fft.rfft(x)).sum()))      # noqa: E731
ok("the low-pass takes the top off noise, the high-pass takes the bottom", hf(dull) < hf(bright) * 0.5 and hf(thin) > hf(bright), (hf(bright), hf(dull), hf(thin)))
swept = tg.sfx(dict(tg.SFX_FIELDS, wave="noise", sustain=0.7, lp_cutoff=0.25, lp_sweep=0.2), 1)
ok("a low-pass sweep opens as it goes", hf(swept[-6000:]) > hf(swept[:6000]) * 1.5, (hf(swept[:6000]), hf(swept[-6000:])))
m1 = tg.sfx_mutate(tg.sfx_preset("laser", 1), 7)
ok("“a little different” changes some numbers, keeps the wave, and stays in range", m1 != tg.sfx_preset("laser", 1) and m1["wave"] == tg.sfx_preset("laser", 1)["wave"] and all(-1 <= v <= 1 for k, v in m1.items() if k != "wave"))
ok("nonsense is made safe", tg.sfx_clean({"wave": "banjo", "freq": "x", "slide": 99, "decay": float("nan"), "extra": 1}) == dict(tg.SFX_FIELDS, slide=1.0) and len(tg.sfx({"sustain": 0, "decay": 0, "attack": 0})) == 0)
t0 = time.time(); long_one = tg.sfx(dict(tg.SFX_FIELDS, wave="noise", attack=1, sustain=1, decay=1, lp_cutoff=0.5, lp_sweep=0.2, hp_cutoff=0.2, hp_sweep=0.1)); took = time.time() - t0
ok("the longest sound there can be is capped at ten seconds and made in a few", 6.5 < len(long_one) / SR <= 10.1 and took < 8, (len(long_one) / SR, took))

# ======================================================================================================= variations
step_sound = tg.stereo(tone(500, 0.3, 0.5))
vs = tg.variations(step_sound, 5, seed=4, pitch=2.0, gain=3.0)
ok("five variations of a footstep: five sounds, no two the same", len(vs) == 5 and len({(len(v), round(float(np.abs(v).max()), 4)) for v in vs}) == 5)
ok("each within the pitch and level asked for", all(500 * 2 ** (-2.1 / 12) < pitch_of(v) < 500 * 2 ** (2.1 / 12) and 0.5 * 10 ** (-3.1 / 20) < np.abs(v).max() < 0.5 * 10 ** (3.1 / 20) for v in vs), [(round(pitch_of(v)), round(float(np.abs(v).max()), 3)) for v in vs])
ok("the same seed gives the same five; none starts with a click", all(np.array_equal(x, y) for x, y in zip(vs, tg.variations(step_sound, 5, seed=4, pitch=2.0, gain=3.0))) and all(abs(v[0, 0]) < 0.01 for v in vs))
ok("a silly count is capped", len(tg.variations(step_sound, 10 ** 6, 1)) == 64 and tg.variations(step_sound, -3, 1) == [])

# ================================================================================================= names and places
ok("names a game engine takes", tg.engine_name("Boss Fight (Loop)") == "boss_fight_loop" and tg.engine_name("PlayerJump 02") == "player_jump_02" and tg.engine_name("  ../../etc/passwd ") == "etc_passwd"
   and tg.engine_name("???") == "sound" and tg.engine_name('Voice: "Hello"/there', "as") == "Voice Hello there" and tg.engine_name("..", "as") == "sound")
godot = Path(home) / "MyGame"; (godot / "scenes").mkdir(parents=True); (godot / "project.godot").write_text("[application]\n")
unreal = Path(home) / "Shooter"; (unreal / "Content" / "Maps").mkdir(parents=True); (unreal / "Shooter.uproject").write_text("{}")
ok("a Godot project is known from any folder inside it, and where its sound goes", tg.project_kind(godot / "scenes")["kind"] == "godot" and tg.project_kind(godot)["sound"] == str(godot / "audio") and "Detect From WAV" in tg.project_kind(godot)["note"])
ok("an Unreal project too", tg.project_kind(unreal / "Content" / "Maps")["kind"] == "unreal" and tg.project_kind(unreal)["sound"] == str(unreal / "Content" / "Audio"))
ok("any other folder is just a folder", tg.project_kind(home)["kind"] == "" and tg.project_kind("/nonexistent/x")["kind"] == "")

# ========================================================================================================== in Tempo
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
T.newProject("empty", "Boss Fight"); spin(100)
piano = T.tracks[0]["id"]; bass = T.addTrack("instrument", "fingered"); T.setTrack(bass, "name", "Bass")
T.setTrack(piano, "reverb", 0.5)
for tid, pitch in ((piano, 60), (bass, 36)):
    rid = T.addRegion(tid, 0.0, 16.0)
    for beat in range(0, 16, 2):
        T.addNote(rid, float(beat), pitch + (beat % 5), 1.5, 100)
intro = T.addSection("Intro", 0.0, 8.0); loop_sec = T.addSection("Fight", 8.0, 8.0)
ok("a song with two tracks of music and two sections", len(T._p["regions"]) == 2 and [s_["name"] for s_ in T.sections] == ["Intro", "Fight"] and se.song_length(T._p) == 16.0, (T._p["regions"], T.sections))
godot = Path(home) / "MyGame"
dest = godot / "audio" / "music"
opt = {"what": "sections", "format": "wav16", "rate": 44100, "loop": True, "loud": "lufs", "target": -20.0, "folder": str(dest), "names": "snake", "prefix": "mus "}
plan = T.gamePlan(opt)
ok("the plan before anything is written: a file per section, named for an engine; an intro isn't looped, the rest is", [(r["file"], r["loop"]) for r in plan] == [("mus_intro.wav", False), ("mus_fight.wav", True)]
   and all(r["canLoop"] for r in plan) and abs(plan[0]["seconds"] - 8 * 60 / T._p["tempo"]) < 0.02, plan)
ok("each row's loop can be set by hand", [r["loop"] for r in T.gamePlan(dict(opt, loops={intro: True, loop_sec: False}))] == [True, False])
ok("a folder is known for what it is", T.gameFolder(str(godot))["kind"] == "godot" and T.gameFolder(str(godot))["there"] and T.gameFolder(str(dest))["there"] is False and T.gameFolder("")["path"] == "")
k = len(said)
ok("the export starts and the window is told it is busy", T.gameExport(opt) == "" and T.gameBusy.startswith("Exporting") and "already under way" in T.gameExport(opt))
ok("…and finishes, saying where the files went and what Godot does with a loop", wait(lambda: not T.gameBusy, 120) and any(f"Wrote 2 files to {dest}" in s_ and "Detect From WAV" in s_ for s_ in said[k:]), said[k:])
i_info, f_info = tg.read_wav_info(str(dest / "mus_intro.wav")), tg.read_wav_info(str(dest / "mus_fight.wav"))
sec_frames = round(8 * 60 / T._p["tempo"] * 44100)
ok("the loop is exactly its bars long, with its loop points; the intro rings on past its bars and has none", abs(f_info["frames"] - sec_frames) <= 1 and f_info["loop"] == (0, f_info["frames"]) and f_info["rate"] == 44100 and f_info["bits"] == 16
   and i_info["frames"] > sec_frames + 44100 and i_info["loop"] is None, (i_info, f_info, sec_frames))
fight = se.load_audio(str(dest / "mus_fight.wav")); intro_a = se.load_audio(str(dest / "mus_intro.wav"))
ok("both are at the loudness asked for", abs(se.loudness(fight) + 20) < 0.6 and abs(se.loudness(intro_a) + 20) < 0.6, (se.loudness(fight), se.loudness(intro_a)))
dry = se.render_song(T._p, T._folder, tail=0.0, start_beats=8.0, end_beats=16.0)        # (a file read back is at Tempo's own rate)
n_ = min(len(dry), len(fight)); fight, dry = fight[:n_], dry[:n_]
late = slice(n_ - SR // 4, n_)                # where the ringing folded in has died away, the loop is the plain bars at a gain
gain_ = float((fight[late] * dry[late]).sum() / max(1e-12, (dry[late] ** 2).sum()))
diff = np.abs(fight - gain_ * dry)
ok("the loop's start carries the last bar's ringing; by its end it is the plain bars again", diff[:SR // 4].max() > 5 * max(diff[late].max(), 1e-5), (float(diff[:SR // 4].max()), float(diff[late].max()), gain_))
T.gameExport(dict(opt, what="song", layers=True, loop=True, format="wav24", rate=48000, prefix="", folder=str(dest / "layers"))); wait(lambda: not T.gameBusy, 180)
layer_files = sorted(f.name for f in (dest / "layers").iterdir())
ok("the song as layers: a file per track that has music, all the same length", layer_files == ["boss_fight_bass.wav", "boss_fight_piano.wav"] and len({tg.read_wav_info(str(dest / "layers" / f))["frames"] for f in layer_files}) == 1, layer_files)
whole = tg.seamless(se.render_song(T._p, T._folder, tail=4.0), int(round(T._tm().seconds(16.0) * se.SR)))
mix, info = tg.normalise(whole, "lufs", -20.0)
summed = sum(se.load_audio(str(dest / "layers" / f)) for f in layer_files)
ok("played together the layers are the mix at the loudness asked for (they share one gain; each isn't brought up on its own)", abs(se.loudness(summed) + 20) < 1.0 and np.abs(summed - mix[:len(summed)]).max() < 0.05, (se.loudness(summed), float(np.abs(summed - mix[:len(summed)]).max())))
if shutil.which("ffmpeg"):
    T.gameExport(dict(opt, what="song", loop=True, format="ogg", mono=True, loud="peak", target=-3.0, folder=str(dest / "ogg"), names="as", prefix="")); wait(lambda: not T.gameBusy, 120)
    og = se.load_audio(str(dest / "ogg" / "Boss Fight.ogg"))
    ok("the whole song as one mono Ogg, named as it is, to a peak", (dest / "ogg" / "Boss Fight.ogg").is_file() and abs(tg.true_peak(og) + 3.0) < 1.0, tg.true_peak(og) if len(og) else "none")
ok("exporting again replaces the files rather than numbering new ones", (T.gameExport(opt), wait(lambda: not T.gameBusy, 120), sorted(f.name for f in dest.iterdir() if f.is_file()))[2] == ["mus_fight.wav", "mus_intro.wav"])
ok("what can't be done says why, and nothing starts", "no regions" in T.gameExport(dict(opt, what="regions", track="nope")) and not T.gameBusy)
blocked = Path(home) / "afile"; blocked.write_text("x")
ok("a folder that can't be made says so", "can't be made" in T.gameExport(dict(opt, folder=str(blocked / "sub"))) and not T.gameBusy)

# ---- a long take of voice lines: strip the silence, name, export each
vo = T.addTrack("audio", ""); T.setTrack(vo, "name", "Guard"); T.setTrack(vo, "reverb", 0.0)
take_rid = T._add_audio_region(vo, tg.stereo(take), 0.0, "Guard line")
n_before = len(T._p["regions"])
made = T.stripSilence(take_rid, -45.0, 0.3)
lines = sorted((r for r in T._p["regions"] if r["track"] == vo), key=lambda r: r["start"])
tm = T._tm()
ok("one take becomes a region per line, in place, named and numbered", made == 3 and len(lines) == 3 and [r["name"] for r in lines] == ["Guard line 01", "Guard line 02", "Guard line 03"]
   and all(abs(tm.seconds(r["start"]) - want) < 0.04 for r, want in zip(lines, (0.48, 1.98, 3.48))) and len({r["file"] for r in lines}) == 1, [(r["name"], round(tm.seconds(r["start"]), 2), r["offset"]) for r in lines])
heard = se.Mixer(T._p, T._folder)._region_audio(T._t(vo), lines[1])
ok("each region plays its own line (nothing was cut from the recording itself)", abs(len(heard) / SR - 0.44) < 0.05 and np.abs(heard[SR // 20:SR // 4]).max() > 0.3 and len(se.load_audio(se.resolve(lines[0]["file"], T._folder))) == len(take), (len(heard) / SR, float(np.abs(heard).max())))
T.undo()
ok("one step back and it is one region again", len([r for r in T._p["regions"] if r["track"] == vo]) == 1)
T.redo() if hasattr(T, "redo") else None
ok("a region with no silence in it is left alone, and says so", (T.stripSilence(sorted((r for r in T._p["regions"] if r["track"] == vo), key=lambda r: r["start"])[0]["id"], -45.0, 0.3), any("no silence" in s_ for s_ in said[-2:]))[0] == 0)
lines = sorted((r for r in T._p["regions"] if r["track"] == vo), key=lambda r: r["start"])
g = T.normalizeRegion(lines[0]["id"])
ok("Normalize sets a region's gain so it peaks 1 dB under full", abs(g - (-1.0 - 20 * math.log10(0.4))) < 0.3 and T._r(lines[0]["id"])["gain"] == g, g)
T.selectTrack(vo)
vo_dest = godot / "audio" / "vo"
T.gameExport({"what": "regions", "track": vo, "format": "wav16", "rate": 22050, "mono": True, "loud": "peak", "target": -1.0, "folder": str(vo_dest), "prefix": "guard_"}); wait(lambda: not T.gameBusy, 120)
vo_files = sorted(f.name for f in vo_dest.iterdir())
ok("each line is written as its own file, small enough for speech", vo_files == ["guard_guard_line_01.wav", "guard_guard_line_02.wav", "guard_guard_line_03.wav"]
   and all(tg.read_wav_info(str(vo_dest / f))["channels"] == 1 and tg.read_wav_info(str(vo_dest / f))["rate"] == 22050 and tg.read_wav_info(str(vo_dest / f))["loop"] is None for f in vo_files), vo_files)
lens = [tg.read_wav_info(str(vo_dest / f))["frames"] / 22050 for f in vo_files]
ok("…as long as its line (the silence after isn't in the file), every one at the same peak", all(abs(a_ - b_) < 0.12 for a_, b_ in zip(lens, (0.84, 0.44, 1.24)))
   and all(abs(tg.true_peak(se.load_audio(str(vo_dest / f))) + 1.0) < 0.3 for f in vo_files), (lens, [tg.true_peak(se.load_audio(str(vo_dest / f))) for f in vo_files]))

# ---- sound effects and variations
ok("the effect maker's kinds and knobs are there for the window", [k_["id"] for k_ in T.sfxKinds][:3] == ["coin", "laser", "explosion"] and len(T.sfxKnobs) == 20 and "noise" in T.sfxWaves)
coin = T.sfxNew("coin")
ok("a new coin each time it is asked; a little different keeps its kind", T.sfxNew("coin") != coin and T.sfxMutate(coin)["wave"] == coin["wave"] and T.sfxNew("nonsense")["wave"] in tg.WAVES)
ok("its outline for drawing, and playing it returns its length", len(T.sfxShape(coin, 120)) == 120 and max(T.sfxShape(coin, 120)) > 0.05 and 0.02 < T.sfxPlay(coin) < 5 and T.sfxShape({"sustain": 0, "decay": 0}, 50) == [])
T.selectTrack(piano); n_tracks = len(T.tracks)
rid = T.sfxAdd(coin, "Coin")
fx_track = T._r(rid)["track"]
ok("added to the song: on a Sound Effects track of its own when a sound track isn't selected, as a region at the playhead", rid and T._t(fx_track)["name"] == "Sound Effects" and len(T.tracks) == n_tracks + 1 and T._r(rid)["name"] == "Coin"
   and T.selectedRegion == rid and Path(se.resolve(T._r(rid)["file"], T._folder)).is_file())
T.selectTrack(fx_track); rid2 = T.sfxAdd(T.sfxNew("laser"), "Laser/Zap?")
ok("the next goes on the same track; a name is cleaned", T._r(rid2)["track"] == fx_track and len(T.tracks) == n_tracks + 1 and T._r(rid2)["name"] == "Laser Zap")
ok("a sound with no length isn't added, and says how to give it one", T.sfxAdd({"sustain": 0, "decay": 0, "attack": 0}, "x") == "" and any("no length" in s_ for s_ in said[-1:]))
n_regions = len(T._p["regions"]); undo_n = len(T._undo)
ok("five variations of the coin land after it, numbered", T.makeVariations(rid, 5, 2.0, 2.0) == 5 and len(T._p["regions"]) == n_regions + 5
   and sorted(r["name"] for r in T._p["regions"] if r.get("name", "").startswith("Coin")) == ["Coin 01", "Coin 02", "Coin 03", "Coin 04", "Coin 05", "Coin 06"], sorted(r["name"] for r in T._p["regions"] if r["track"] == fx_track))
coins = sorted((r for r in T._p["regions"] if r.get("name", "").startswith("Coin")), key=lambda r: r["start"])
ok("none overlaps the next, each is its own file", all(a_["start"] + a_["length"] <= b_["start"] + 1e-6 for a_, b_ in zip(coins, coins[1:])) and len({r["file"] for r in coins}) == 6)
ok("one step back takes all five away", len(T._undo) == undo_n + 1 and (T.undo(), len(T._p["regions"]))[1] == n_regions)

# ---- the loudness meter
m = tg.Meter()
sig = tg.stereo(tone(1000, 5.0, 0.5))
for at in range(0, len(sig), 1024):
    m.feed(sig[at:at + 1024])
now = m.read()
ok("fed block by block, the meter reads what the whole sound measures", abs(now["i"] - se.loudness(sig)) < 0.3 and abs(now["s"] - now["i"]) < 0.3 and abs(now["m"] - now["i"]) < 0.3 and abs(now["peak"] + 6.0) < 0.1 and not now["over"], (now, se.loudness(sig)))
for at in range(0, SR * 2, 1024):
    m.feed(np.zeros((1024, 2), np.float32))
ok("silence after it: momentary falls to the floor, the integrated figure stays (silence is gated out)", m.read()["m"] <= -69 and abs(m.read()["i"] - now["i"]) < 0.3, m.read())
m.feed(np.full((10, 2), 1.2, np.float32))
ok("over full is flagged; reset clears it", m.read()["over"] and (m.reset(), m.read())[1] == {"m": -70.0, "s": -70.0, "i": -70.0, "peak": -120.0, "over": False})
T.play(); spin(1200); playing = T.loudnessNow; T.stop(); spin(100)
ok("playing the song moves Tempo's own meter", playing["peak"] > -60 and playing["m"] > -69, playing)
T.resetLoudness()
ok("…and Reset clears it", T.loudnessNow["peak"] == -120.0)
T.stop(); T._player.stop_live("preview") if hasattr(T._player, "stop_live") else None
t0 = time.time(); curve = T.tempoCurve(0.0, 16.0, 2147483647)
ok("asked for two thousand million points of the tempo line, Tempo draws four thousand and answers at once (it hung)", 2 <= len(curve) <= 4100 and time.time() - t0 < 2, (len(curve), time.time() - t0))

print(f"{passed} passed, {failed} failed")
