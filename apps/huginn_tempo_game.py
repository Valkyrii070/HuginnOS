"""Tempo for games: the parts of a music studio that only game audio asks for.

    seamless()        music that loops without a seam: the reverb and echo ringing past the end are folded onto the
                      start, so the last bar's tail is under the first bar every time round
    write_wav()       a WAV at any rate, 16 or 24 bit, mono or stereo, with loop points in a "smpl" chunk, which
                      Godot, FMOD and Wwise read (encode() puts LOOPSTART / LOOPLENGTH in an Ogg or FLAC)
    normalise()       each file to one loudness (LUFS, as BS.1770 measures it) or one peak, under a true-peak ceiling,
                      so forty sound effects made on forty days sit at one level in the game
    sound_spans()     where the sound is in a long recording: one take of fifty voice lines becomes fifty regions
    sfx()             small synthesised effects (coin, laser, explosion, jump…) in the manner of sfxr, the tool game
                      jams have used since 2007: one oscillator, slides, an envelope and two filters, from numbers
    variations()      several slightly different copies of one sound (pitch, level, start), so a footstep heard a
                      hundred times isn't the same footstep
    engine_name()     file names game engines are happy with (snake_case, no spaces)
    project_kind()    is this folder a Godot or an Unreal project, and where does sound go in it

Pure numpy, no Qt: every function is called directly by the tests.
"""
from __future__ import annotations

import math
import re
import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np

import huginn_tempo_engine as se

SR = se.SR
FORMATS = {"wav16": ("WAV, 16 bit", ".wav"), "wav24": ("WAV, 24 bit", ".wav"), "ogg": ("Ogg Vorbis", ".ogg"), "flac": ("FLAC", ".flac")}
RATES = (48000, 44100, 32000, 22050)
MAX_SECONDS = 3600.0                    # one exported file
MAX_FILES = 500                         # one export


# ------------------------------------------------------------------------------------------------- loops and levels
def stereo(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, np.float32)
    return np.repeat(x[:, None], 2, axis=1) if x.ndim == 1 else x


def seamless(audio: np.ndarray, body: int) -> np.ndarray:
    """`audio` is the music (`body` frames) and whatever rings on after it. The ringing is laid over the start, so
    the piece can be played end to start for ever and the join is what the music itself would have sounded like."""
    audio = stereo(audio)
    body = max(1, min(int(body), len(audio)))
    out = audio[:body].copy()
    tail = audio[body:]
    while len(tail):                                              # (a tail longer than the music wraps round again)
        n = min(len(tail), body)
        out[:n] += tail[:n]
        tail = tail[n:]
    return out


def true_peak(x: np.ndarray) -> float:
    """The highest the sound really goes between its samples, in dBTP (four times oversampled, as BS.1770 asks)."""
    x = np.asarray(x, np.float64)
    if x.size == 0:
        return -120.0
    if x.ndim == 1:
        x = x[:, None]
    peak = float(np.max(np.abs(x)))
    from scipy.signal import resample_poly
    for start in range(0, len(x), SR * 20):                       # in pieces: an hour of sound isn't oversampled at once
        piece = x[max(0, start - 64):start + SR * 20 + 64]
        peak = max(peak, float(np.max(np.abs(resample_poly(piece, 4, 1, axis=0)))))
    return 20 * math.log10(max(peak, 1e-6))


def normalise(audio: np.ndarray, how: str = "peak", target: float = -1.0, ceiling: float = -1.0) -> tuple:
    """(the sound at its new level, {gain, lufs, peak, note}). how: "lufs" brings it to `target` LUFS, "peak" to
    `target` dBTP, "none" leaves it. Never above `ceiling` dBTP: when the loudness asked for would go over, the gain
    stops at the ceiling and the note says by how much it fell short (a limiter would change the sound: this
    doesn't). A sound too short to measure for loudness (under 0.4 s) is brought to the ceiling instead."""
    audio = stereo(audio)
    peak = true_peak(audio)
    info = {"gain": 0.0, "lufs": round(se.loudness(audio), 1), "peak": round(peak, 1), "note": ""}
    if how == "none" or peak <= -119:
        return audio, info
    if how == "lufs":
        if info["lufs"] <= -69.9:
            gain, info["note"] = ceiling - peak, "too short to measure: brought to the peak instead"
        else:
            gain = float(target) - info["lufs"]
            if peak + gain > ceiling:
                info["note"] = f"{peak + gain - ceiling:.1f} dB quieter than asked: louder would clip"
                gain = ceiling - peak
    else:
        gain = min(float(target), ceiling) - peak
    gain = max(-60.0, min(60.0, gain))
    out = (audio * (10 ** (gain / 20))).astype(np.float32)
    info.update(gain=round(gain, 1), lufs=round(info["lufs"] + gain, 1) if info["lufs"] > -69.9 else info["lufs"], peak=round(peak + gain, 1))
    return out, info


def shaped(audio: np.ndarray, rate: int = SR, mono: bool = False) -> np.ndarray:
    """The sound at another sample rate, and as one channel when asked (the two halved and added)."""
    audio = stereo(audio)
    if rate != SR and len(audio):
        from scipy.signal import resample_poly
        g = math.gcd(int(rate), SR)
        audio = resample_poly(audio.astype(np.float64), int(rate) // g, SR // g, axis=0).astype(np.float32)
    return audio.mean(axis=1, keepdims=True).astype(np.float32) if mono else audio


def write_wav(path: str, audio: np.ndarray, bits: int = 24, rate: int = SR, loop: tuple = None) -> None:
    """`audio` is (frames, channels), already at `rate`. `loop` is (first frame, the frame after the last): written
    as one forward loop in a smpl chunk (whose own end is the last frame played, so one less)."""
    a = np.clip(np.asarray(audio, np.float32), -1, 1)
    if a.ndim == 1:
        a = a[:, None]
    ch = a.shape[1]
    if bits == 16:
        rng = np.random.default_rng(len(a))                       # (the same file every time it is made)
        dither = (rng.random(a.shape) - rng.random(a.shape)) / 32768.0
        data = np.clip((a + dither) * 32767, -32768, 32767).astype("<i2").tobytes()
    else:
        bits = 24
        v = np.clip(a * 8388607, -8388608, 8388607).astype(np.int32).reshape(-1)
        b = np.empty((v.size, 3), np.uint8)
        b[:, 0], b[:, 1], b[:, 2] = v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF
        data = b.tobytes()
    if len(data) % 2:
        data += b"\0"
    align = ch * bits // 8
    chunks = b"fmt " + struct.pack("<IHHIIHH", 16, 1, ch, rate, rate * align, align, bits) + b"data" + struct.pack("<I", len(a) * align) + data
    if loop and 0 <= loop[0] < loop[1] <= len(a):
        smpl = struct.pack("<9I", 0, 0, int(1e9 / rate), 60, 0, 0, 0, 1, 0) + struct.pack("<6I", 0, 0, int(loop[0]), int(loop[1]) - 1, 0, 0)
        chunks += b"smpl" + struct.pack("<I", len(smpl)) + smpl
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks)


def read_wav_info(path: str) -> dict:
    """What a WAV file says of itself: {rate, channels, bits, frames, loop: (first, after last) or None}."""
    blob = Path(path).read_bytes()
    if blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    out, at = {"loop": None}, 12
    while at + 8 <= len(blob):
        tag, size = blob[at:at + 4], struct.unpack("<I", blob[at + 4:at + 8])[0]
        body = blob[at + 8:at + 8 + size]
        if tag == b"fmt ":
            _fmt, ch, rate, _br, align, bits = struct.unpack("<HHIIHH", body[:16])
            out.update(rate=rate, channels=ch, bits=bits, align=align)
        elif tag == b"data":
            out["bytes"] = size
        elif tag == b"smpl" and len(body) >= 60 and struct.unpack("<I", body[28:32])[0] >= 1:
            first, last = struct.unpack("<II", body[44:52])
            out["loop"] = (first, last + 1)
        at += 8 + size + (size & 1)
    out["frames"] = out.get("bytes", 0) // max(1, out.get("align", 1))
    return out


def encode(audio: np.ndarray, target: str, kind: str, rate: int = SR, loop: tuple = None, quality: int = 6) -> bool:
    """Ogg Vorbis or FLAC through ffmpeg; loop points go in as the tags LOOPSTART and LOOPLENGTH (in samples), the
    convention RPG Maker began and many engines and players follow."""
    codec = {"ogg": ["-c:a", "libvorbis", "-q:a", str(quality)], "flac": ["-c:a", "flac"]}.get(kind)
    if not codec or not shutil.which("ffmpeg"):
        return False
    a = np.ascontiguousarray(audio, np.float32)
    ch = 1 if a.ndim == 1 else a.shape[1]
    tags = ["-metadata", f"LOOPSTART={int(loop[0])}", "-metadata", f"LOOPLENGTH={int(loop[1] - loop[0])}"] if loop else []
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(rate), "-ac", str(ch), "-i", "-"] + codec + tags + [target],
                           input=a.tobytes(), capture_output=True, timeout=900)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def write(path: str, audio: np.ndarray, fmt: str = "wav24", rate: int = SR, mono: bool = False, loop_seconds: tuple = None) -> bool:
    """One finished file: `audio` at Tempo's own rate, written as `fmt` at `rate`. `loop_seconds` is (start, end)."""
    a = shaped(audio, rate, mono)
    loop = None
    if loop_seconds:
        loop = (max(0, int(round(loop_seconds[0] * rate))), min(len(a), int(round(loop_seconds[1] * rate))))
        loop = loop if loop[1] > loop[0] else None
    if fmt in ("wav16", "wav24"):
        write_wav(path, a, 16 if fmt == "wav16" else 24, rate, loop)
        return True
    return encode(a, path, fmt, rate, loop)


class Meter:
    """How loud what is playing is, as it plays: momentary (the last 0.4 s), short-term (the last 3 s) and integrated
    (everything since it was reset, gated as BS.1770 says) loudness in LUFS, and the highest sample so far in dB."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._z1 = self._z2 = None                                # the two weighting filters' memories
        self._acc, self._n = 0.0, 0                               # the tenth of a second being gathered
        self._tenths = []                                         # each tenth's weighted energy
        self._peak = 0.0

    def feed(self, block: np.ndarray) -> None:
        x = stereo(block).astype(np.float64)
        if not len(x):
            return
        self._peak = max(self._peak, float(np.abs(x).max()))
        from scipy.signal import lfilter, lfilter_zi
        if self._z1 is None:
            self._z1 = np.zeros((len(lfilter_zi(*se.K_SHELF)), x.shape[1]))
            self._z2 = np.zeros((len(lfilter_zi(*se.K_HP)), x.shape[1]))
        y, self._z1 = lfilter(*se.K_SHELF, x, axis=0, zi=self._z1)
        y, self._z2 = lfilter(*se.K_HP, y, axis=0, zi=self._z2)
        tenth, at = SR // 10, 0
        while at < len(y):
            take = min(len(y) - at, tenth - self._n)
            self._acc += float((y[at:at + take] ** 2).sum())
            self._n += take
            at += take
            if self._n >= tenth:
                self._tenths.append(self._acc / tenth)
                self._acc, self._n = 0.0, 0
        if len(self._tenths) > 72000:                             # two hours: the oldest go
            del self._tenths[:36000]

    @staticmethod
    def _lufs(z: float) -> float:
        return -0.691 + 10 * math.log10(z) if z > 1e-12 else -70.0

    def read(self) -> dict:
        t = self._tenths
        m = self._lufs(sum(t[-4:]) / 4) if len(t) >= 4 else -70.0
        s = self._lufs(sum(t[-30:]) / 30) if len(t) >= 30 else m
        integrated = -70.0
        if len(t) >= 4:
            z = np.convolve(np.asarray(t), np.ones(4) / 4, "valid")
            z = z[z > 10 ** ((-70 + 0.691) / 10)]
            if len(z):
                z = z[z > z.mean() * 0.1]                          # 10 LU under what is left
                integrated = self._lufs(float(z.mean())) if len(z) else -70.0
        return {"m": round(max(-70.0, m), 1), "s": round(max(-70.0, s), 1), "i": round(max(-70.0, integrated), 1),
                "peak": round(20 * math.log10(max(self._peak, 1e-6)), 1), "over": self._peak >= 1.0}


# ---------------------------------------------------------------------------------------- finding the sound in a take
def _level(x: np.ndarray, win: int) -> np.ndarray:
    """How loud each stretch of `win` frames is (the highest sample in it), mono."""
    m = np.abs(stereo(x)).max(axis=1)
    n = len(m) // win
    return m[:n * win].reshape(n, win).max(axis=1) if n else np.zeros(0, np.float32)


def sound_spans(audio: np.ndarray, threshold_db: float = -45.0, min_gap: float = 0.3, min_sound: float = 0.05, pad: float = 0.02) -> list:
    """Where there is sound: [(first frame, the frame after the last)], split wherever it stays under `threshold_db`
    for `min_gap` seconds. Each span is given `pad` seconds of room either side (never into its neighbour), and
    anything shorter than `min_sound` (a click, a breath) is left out."""
    win = max(1, SR // 500)                                       # 2 ms
    lvl = _level(audio, win)
    if not len(lvl):
        return []
    loud = lvl > 10 ** (float(threshold_db) / 20)
    gap = max(1, int(min_gap * SR / win))
    spans, start, quiet = [], None, 0
    for k, on in enumerate(loud):
        if on:
            if start is None:
                start = k
            quiet, last = 0, k
        elif start is not None:
            quiet += 1
            if quiet >= gap:
                spans.append((start, last + 1))
                start = None
    if start is not None:
        spans.append((start, last + 1))
    out, p = [], int(pad * SR)
    for i, (a, b) in enumerate(spans):
        if (b - a) * win < min_sound * SR:
            continue
        lo = max(a * win - p, spans[i - 1][1] * win if i else 0)
        hi = min(b * win + p, spans[i + 1][0] * win if i + 1 < len(spans) else len(audio))
        out.append((int(lo), int(hi)))
    return out


# ------------------------------------------------------------------------------------------------- sound effects
# One voice: a wave whose pitch slides, steps and wobbles, shaped by an envelope and two filters. The numbers are
# sfxr's (Tomas Pettersson, 2007), each from 0 to 1 (or -1 to 1 where it can go either way), so its presets and the
# habit of pressing "another one" until it sounds right carry over.
WAVES = ("square", "saw", "sine", "noise", "triangle")
SFX_FIELDS = {"wave": "square", "freq": 0.3, "freq_limit": 0.0, "slide": 0.0, "slide_delta": 0.0, "duty": 0.5, "duty_sweep": 0.0,
              "vib_depth": 0.0, "vib_speed": 0.0, "attack": 0.0, "sustain": 0.3, "punch": 0.0, "decay": 0.4,
              "arp_amount": 0.0, "arp_time": 0.0, "repeat": 0.0, "lp_cutoff": 1.0, "lp_sweep": 0.0, "lp_resonance": 0.0,
              "hp_cutoff": 0.0, "hp_sweep": 0.0, "volume": 0.6}
SFX_KINDS = [("coin", "Coin"), ("laser", "Laser"), ("explosion", "Explosion"), ("powerup", "Power-up"), ("hit", "Hit"), ("jump", "Jump"), ("blip", "Blip"), ("random", "Surprise")]
SFX_KNOBS = [("freq", "Pitch", 0, 1), ("slide", "Slide", -1, 1), ("slide_delta", "Slide bend", -1, 1), ("duty", "Width", 0, 1), ("duty_sweep", "Width sweep", -1, 1),
             ("vib_depth", "Wobble", 0, 1), ("vib_speed", "Wobble speed", 0, 1), ("attack", "Attack", 0, 1), ("sustain", "Hold", 0, 1), ("punch", "Punch", 0, 1),
             ("decay", "Decay", 0, 1), ("arp_amount", "Step", -1, 1), ("arp_time", "Step after", 0, 1), ("repeat", "Repeat", 0, 1),
             ("lp_cutoff", "Low-pass", 0, 1), ("lp_sweep", "Low-pass sweep", -1, 1), ("lp_resonance", "Resonance", 0, 1), ("hp_cutoff", "High-pass", 0, 1), ("hp_sweep", "High-pass sweep", -1, 1),
             ("volume", "Volume", 0, 1)]


def sfx_clean(params: dict) -> dict:
    """Any dict as a full, safe set of numbers."""
    out = dict(SFX_FIELDS)
    for key, default in SFX_FIELDS.items():
        v = (params or {}).get(key, default)
        if key == "wave":
            out[key] = v if v in WAVES else default
        else:
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = default
            lo = -1.0 if key in ("slide", "slide_delta", "duty_sweep", "arp_amount", "lp_sweep", "hp_sweep") else 0.0
            out[key] = max(lo, min(1.0, v)) if math.isfinite(v) else default
    return out


def sfx_preset(kind: str, seed: int = 0) -> dict:
    """A new sound of a kind: sfxr's own recipes, each drawn afresh for every seed."""
    r = np.random.default_rng(int(seed) & 0x7FFFFFFF)
    u = lambda lo=0.0, hi=1.0: float(lo + (hi - lo) * r.random())     # noqa: E731
    flip = lambda: bool(r.integers(0, 2))                             # noqa: E731
    p = dict(SFX_FIELDS)
    if kind == "coin":
        p.update(freq=u(0.4, 0.9), attack=0.0, sustain=u(0.0, 0.1), decay=u(0.1, 0.5), punch=u(0.3, 0.6))
        if flip():
            p.update(arp_time=u(0.5, 0.7), arp_amount=u(0.2, 0.6))
    elif kind == "laser":
        p.update(wave=("square", "saw", "sine")[int(r.integers(0, 3))], freq=u(0.5, 1.0), freq_limit=u(0.0, 0.2), slide=-u(0.15, 0.35), attack=0.0, sustain=u(0.1, 0.3), decay=u(0.0, 0.4))
        if p["wave"] == "square":
            p.update(duty=u(0.0, 0.5), duty_sweep=u(0.0, 0.2))
        if flip():
            p.update(hp_cutoff=u(0.0, 0.3))
    elif kind == "explosion":
        p.update(wave="noise", freq=u(0.1, 0.5) ** 2 + 0.05, slide=(-0.1 + u(0, 0.4)) if flip() else -u(0.2, 0.4), attack=0.0, sustain=u(0.1, 0.4), decay=u(0.0, 0.5), punch=u(0.2, 0.8))
        if flip():
            p.update(repeat=u(0.3, 0.8))
        if flip():
            p.update(vib_depth=u(0.0, 0.7), vib_speed=u(0.0, 0.6))
    elif kind == "powerup":
        p.update(wave="saw" if flip() else "square", freq=u(0.2, 0.5), slide=u(0.1, 0.5), attack=0.0, sustain=u(0.0, 0.4), decay=u(0.1, 0.5))
        if flip():
            p.update(repeat=u(0.4, 0.8))
        else:
            p.update(vib_depth=u(0.0, 0.7), vib_speed=u(0.0, 0.6))
    elif kind == "hit":
        p.update(wave=("square", "saw", "noise")[int(r.integers(0, 3))], freq=u(0.2, 0.8), slide=-u(0.3, 0.7), attack=0.0, sustain=u(0.0, 0.1), decay=u(0.1, 0.3))
        if flip():
            p.update(hp_cutoff=u(0.0, 0.3))
    elif kind == "jump":
        p.update(wave="square", duty=u(0.0, 0.6), freq=u(0.3, 0.6), slide=u(0.1, 0.3), attack=0.0, sustain=u(0.1, 0.4), decay=u(0.1, 0.3))
        if flip():
            p.update(hp_cutoff=u(0.0, 0.3))
        if flip():
            p.update(lp_cutoff=u(0.4, 1.0))
    elif kind == "blip":
        p.update(wave="square" if flip() else "saw", duty=u(0.0, 0.6), freq=u(0.2, 0.6), attack=0.0, sustain=u(0.1, 0.2), decay=u(0.0, 0.2), hp_cutoff=0.1)
    else:                                                              # anything at all (most are odd; some are finds)
        p.update(wave=WAVES[int(r.integers(0, 4))], freq=u(0.1, 0.9) ** 2 + 0.1, slide=u(-1, 1) ** 5, slide_delta=u(-1, 1) ** 3, duty=u(), duty_sweep=u(-1, 1) ** 3,
                 vib_depth=u(-1, 1) ** 3, vib_speed=u(), attack=u(0, 1) ** 3, sustain=u() ** 2, decay=u(), punch=u() ** 2, lp_resonance=u(), lp_cutoff=1 - u() ** 3,
                 lp_sweep=u(-1, 1) ** 3, hp_cutoff=u() ** 5, hp_sweep=u(-1, 1) ** 5, repeat=u(), arp_time=u(), arp_amount=u(-1, 1) ** 2)
        if p["attack"] + p["sustain"] + p["decay"] < 0.2:
            p.update(sustain=p["sustain"] + 0.2 + u(0, 0.3), decay=p["decay"] + 0.2 + u(0, 0.3))
    return sfx_clean(p)


def sfx_mutate(params: dict, seed: int = 0, amount: float = 0.05) -> dict:
    """The same sound, a little different: half its numbers nudged."""
    r = np.random.default_rng(int(seed) & 0x7FFFFFFF)
    p = sfx_clean(params)
    for key in SFX_FIELDS:
        if key not in ("wave", "volume") and r.random() < 0.5:
            p[key] = p[key] + float(r.uniform(-amount, amount))
    return sfx_clean(p)


def sfx(params: dict, seed: int = 1) -> np.ndarray:
    """The sound those numbers make: mono float32 at Tempo's rate. It is made the way sfxr makes it, at sfxr's own
    44.1 kHz with the wave drawn eight times finer and averaged (so a square wave sliding up doesn't fold back down
    as a whistle), and brought to 48 kHz at the end: its numbers mean here what they mean there."""
    p = sfx_clean(params)
    a, s, d = (int(p[k] ** 2 * 100000) for k in ("attack", "sustain", "decay"))
    n = min(a + s + d, 44100 * 10)
    if n < 8:
        return np.zeros(0, np.float32)
    m = np.arange(n)
    rep = int((1 - p["repeat"]) ** 2 * 20000 + 32) if p["repeat"] > 0 else 0
    t = (m % rep) if rep else m                                       # (a repeat starts the slide and the step again)
    # ---- the wave's period, sample by sample: it is multiplied by the slide each sample, and the slide itself drifts
    slide, drift = 1.0 - p["slide"] ** 3 * 0.01, -p["slide_delta"] ** 3 * 0.000001
    steps = np.log(np.maximum(slide + drift * (t + 1), 1e-9))
    total = np.cumsum(steps)
    if rep:
        starts = np.arange(0, n, rep)
        total = total - np.repeat(np.concatenate([[0.0], total[starts[1:] - 1]]), rep)[:n]
    period = 100.0 / (p["freq"] ** 2 + 0.001) * np.exp(np.clip(total, -40, 40))
    alive = np.ones(n)
    longest = 100.0 / (p["freq_limit"] ** 2 + 0.001)
    over = np.nonzero(period > longest)[0]
    if len(over):
        period = np.minimum(period, longest)
        if p["freq_limit"] > 0:
            alive[over[0]:] = 0.0                                     # a sound sliding down stops at its lowest pitch
    if p["arp_amount"] != 0 and p["arp_time"] < 1:
        step = (1 - p["arp_amount"] ** 2 * 0.9) if p["arp_amount"] >= 0 else (1 + p["arp_amount"] ** 2 * 10)
        period = np.where(t >= int((1 - p["arp_time"]) ** 2 * 20000 + 32), period * step, period)
    if p["vib_depth"] > 0:
        period = period * (1.0 + np.sin((m + 1) * p["vib_speed"] ** 2 * 0.01) * p["vib_depth"] * 0.5)
    period = np.maximum(8.0, np.floor(period))
    duty = np.clip(0.5 - p["duty"] * 0.5 - p["duty_sweep"] * 0.00005 * (t + 1), 0.0, 0.5)
    # ---- the wave itself, eight times finer
    OVER = 8
    phase = np.cumsum(np.repeat(1.0 / period, OVER))
    cyc = np.floor(phase)
    frac = phase - cyc
    if p["wave"] == "square":
        w = np.where(frac < np.repeat(duty, OVER), 0.5, -0.5)
    elif p["wave"] == "saw":
        w = 1.0 - frac * 2
    elif p["wave"] == "sine":
        w = np.sin(frac * 2 * math.pi)
    elif p["wave"] == "triangle":
        w = 1.0 - np.abs(frac * 4 - 2)
    else:                                                              # noise: 32 new random values for each turn of the wave
        table = np.random.default_rng(int(seed) & 0x7FFFFFFF).uniform(-1, 1, size=(int(cyc[-1]) + 2, 32))
        w = table[cyc.astype(np.int64), np.minimum(31, (frac * 32).astype(np.int64))]
    w = _sfx_filters(w, p)
    # ---- the envelope: up, held (with a punch at its start), away
    e = np.zeros(n)
    if a:
        e[:a] = m[:a] / a
    hold = np.arange(max(0, min(s, n - a)))
    e[a:a + len(hold)] = 1.0 + (1.0 - hold / max(1, s)) * 2.0 * p["punch"]
    fall = np.arange(max(0, n - a - s))
    e[a + s:] = 1.0 - fall / max(1, d)
    out = w.reshape(n, OVER).mean(axis=1) * e * alive * (p["volume"] * 1.6)
    from scipy.signal import resample_poly
    g = math.gcd(SR, 44100)
    return np.clip(resample_poly(out, SR // g, 44100 // g), -1, 1).astype(np.float32)


def _sfx_filters(w: np.ndarray, p: dict) -> np.ndarray:
    """sfxr's two filters, on the finely drawn wave: a low-pass that can ring, then a high-pass. Each is a short
    recurrence, so scipy runs it; where a cutoff sweeps, it is run a little at a time with the setting of that moment."""
    lp_on, hp_on = p["lp_cutoff"] < 0.9999, p["hp_cutoff"] > 0 or p["hp_sweep"] != 0
    if not lp_on and not hp_on:
        return w
    lp, lp_mul = p["lp_cutoff"] ** 3 * 0.1, 1.0 + p["lp_sweep"] * 0.0001
    damp = min(0.8, 5.0 / (1.0 + p["lp_resonance"] ** 2 * 20.0) * (0.01 + lp))
    hp, hp_mul = p["hp_cutoff"] ** 2 * 0.1, 1.0 + p["hp_sweep"] * 0.0003
    block = len(w) if (lp_mul == 1.0 or not lp_on) and (hp_mul == 1.0 or not hp_on) else 64
    out = np.empty(len(w))
    zl, zh = np.zeros(2), np.zeros(1)
    for at in range(0, len(w), block):
        seg = w[at:at + block]
        if lp_on:
            lp = min(0.1, max(0.0, lp))
            k = 1.0 - damp
            seg, zl = se.lfilter([k * lp], [1.0, -(1.0 + k - k * lp), k], seg, zi=zl)
            lp *= lp_mul ** block
        if hp_on:
            hp = min(0.1, max(0.00001, hp))
            seg, zh = se.lfilter([1.0 - hp, -(1.0 - hp)], [1.0, -(1.0 - hp)], seg, zi=zh)
            hp *= hp_mul ** block
        out[at:at + block] = seg
    return out


def variations(audio: np.ndarray, count: int, seed: int = 1, pitch: float = 1.0, gain: float = 1.5, start: float = 0.0) -> list:
    """`count` copies of a sound, each a little different, the same for the same seed: played up to `pitch`
    semitones higher or lower (faster or slower, as a sampler would: for short effects that is what sounds
    natural), up to `gain` dB louder or quieter, and starting up to `start` seconds in."""
    audio, out = stereo(audio), []
    r = np.random.default_rng(int(seed) & 0x7FFFFFFF)
    for _ in range(max(0, min(int(count), 64))):
        semis, db, skip = float(r.uniform(-pitch, pitch)), float(r.uniform(-gain, gain)), int(r.uniform(0, max(0.0, start)) * SR)
        a = audio[min(skip, max(0, len(audio) - 64)):]
        if abs(semis) > 0.01 and len(a) > 16:
            a = se.resample_stereo(a, 2 ** (-semis / 12))
        a = a * (10 ** (db / 20))
        fade = min(64, len(a) // 2)
        if fade:
            a = a.copy()
            a[:fade] *= np.linspace(0, 1, fade)[:, None]
        out.append(np.clip(a, -1, 1).astype(np.float32))
    return out


# ------------------------------------------------------------------------------------------------- names and places
def engine_name(text: str, style: str = "snake") -> str:
    """A file name's stem a game engine and every file system takes: "Boss Fight (Loop)" → boss_fight_loop. With
    style "as" the name is only cleaned of what can't be in a file name."""
    text = str(text or "").strip()
    if style != "snake":
        return re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", text)).strip(" .")[:80] or "sound"
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:80] or "sound"


def project_kind(folder) -> dict:
    """Is this folder (or one above it) a game project? {kind: "godot" | "unreal" | "", root, sound: where sound
    goes in it, note: what its engine does with a loop}."""
    here = Path(folder).expanduser()
    for base in [here] + list(here.parents)[:6]:
        try:
            if (base / "project.godot").is_file():
                return {"kind": "godot", "root": str(base), "sound": str(base / "audio"),
                        "note": "Godot takes a WAV's loop from the file (Import: Loop Mode, Detect From WAV). For Ogg, tick Loop in the Import dock."}
            if any(base.glob("*.uproject")):
                return {"kind": "unreal", "root": str(base), "sound": str(base / "Content" / "Audio"),
                        "note": "Unreal imports WAV files put in Content. Tick Looping on the Sound Wave; the file's ends already join."}
        except OSError:
            break
    return {"kind": "", "root": "", "sound": "", "note": ""}
