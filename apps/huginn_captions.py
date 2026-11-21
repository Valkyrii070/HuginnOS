#!/usr/bin/env python3
"""Live captions: what the computer is playing (a video, a call, a game) written out in a bar on the screen.

The sound going to the speakers is read as it plays (PipeWire's monitor of the default output: pw-record with
stream.capture.sink), cut where the speech pauses (or every few seconds when it doesn't), and each piece is written out
by whisper.cpp's whisper-cli with one of dictation's speech models (huginn_dictate; got in Settings › Keyboard & Mouse ›
Dictation), on this computer only: nothing is sent anywhere and nothing is kept.

The shell runs `huginn_captions.py listen` while captions are on (Control Centre, Super+Ctrl+L) and reads its lines,
one JSON object each on standard output:

  {"state": "listening", "model": "base"}      ready, and which model it's using
  {"state": "no-model"} / {"state": "no-engine"} / {"state": "no-sound", "why": "..."}   it can't, and why
  {"caption": "words", "n": 3}                  a piece as it's written out
  {"error": "..."}                              one piece went wrong (it carries on)

`--wav FILE` reads a recording instead of the speakers (for trying it), `--demo` makes up captions.
"""
import argparse
import array
import json
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import huginn_dictate as hd    # noqa: E402  (the speech engine and its models)

RATE = hd.RATE
BLOCK = RATE // 10 * 2              # a tenth of a second of 16-bit samples
PAUSE = 0.45                        # seconds of quiet after speech that end a piece
LONGEST = 5.0                       # a piece is written out after this long even without a pause
MERGE_UP_TO = 10.0                  # pieces waiting while one is being written out go together, up to this long
LEAD = 0.3                          # the quiet just before speech starts is kept with it (the first sound of a word)
QUICKEST_FIRST = ("base", "small", "large-v3-turbo-q5_0")
# What whisper says over music, silence or applause when nothing was said (on a whole piece only)
NOT_SAID = {"you", "thank you.", "thank you", "thanks for watching!", "thanks for watching.", "thank you for watching.",
            "thank you for watching!", "bye.", "bye!", "subtitles by the amara.org community", "please subscribe.",
            ".", "..", "...", "-", "♪", "♪♪"}


def emit(obj: dict) -> None:
    try:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()
    except (BrokenPipeError, ValueError):    # the shell stopped listening: so do we
        os._exit(0)


def pick_model(wanted: str = "") -> str:
    """The model to write with: the one asked for if it's here, else the quickest that is ("" when none is)."""
    if wanted and hd.have_model(wanted):
        return wanted
    for name in QUICKEST_FIRST:
        if hd.have_model(name):
            return name
    return ""


def clean(text: str) -> str:
    """whisper-cli's words for a piece, without its marks for sounds and its stock lines for no speech at all."""
    text = hd.tidy(text)
    text = re.sub(r"[♪♫]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return "" if text.lower() in NOT_SAID else text


def sound_command() -> list:
    """What reads the speakers' sound: PipeWire's monitor of the default output, 16 kHz mono 16-bit to stdout."""
    if shutil.which("pw-record"):
        return ["pw-record", "-P", "{ stream.capture.sink = true node.name = huginn-captions media.name = \"Live captions\" }",
                "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"]
    if shutil.which("parecord"):
        return ["parecord", "--raw", "--device=@DEFAULT_MONITOR@", f"--rate={RATE}", "--channels=1", "--format=s16le",
                "--client-name=Live captions"]
    return []


class Cutter:
    """Sound in, pieces of speech out: a piece ends at a pause after speech or when it's grown long."""

    def __init__(self, pause: float = PAUSE, longest: float = LONGEST):
        self.pause, self.longest = pause, longest
        self.piece = bytearray()
        self.lead = bytearray()
        self.quiet_for = 0.0
        self.spoke = False
        self.noise = None

    def feed(self, block: bytes) -> list:
        """Pieces finished by this block (usually none)."""
        samples = array.array("h", block[: len(block) // 2 * 2])
        rms = math.sqrt(sum(s * s for s in samples) / max(1, len(samples))) if samples else 0.0
        # the steady sound under the speech (a fan, a game's music): follows quiet moments down at once, louder ones
        # up slowly; speech is what stands out of it
        self.noise = rms if self.noise is None else rms if rms < self.noise else self.noise * 0.995 + rms * 0.005
        loud = rms > max(220.0, self.noise * 2.2)
        out = []
        if not self.spoke and not loud:
            self.lead += block
            del self.lead[: max(0, len(self.lead) - int(LEAD * RATE) * 2)]
            return out
        if not self.spoke:
            self.piece, self.lead, self.spoke, self.quiet_for = bytearray(self.lead), bytearray(), True, 0.0
        self.piece += block
        self.quiet_for = 0.0 if loud else self.quiet_for + len(block) / 2 / RATE
        if self.quiet_for >= self.pause or len(self.piece) / 2 / RATE >= self.longest:
            out.append(bytes(self.piece))
            self.piece, self.spoke, self.quiet_for = bytearray(), False, 0.0
        return out

    def rest(self) -> list:
        return [bytes(self.piece)] if self.spoke and len(self.piece) > RATE else []      # (over half a second)


def write_wav(pcm: bytes, path: Path) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def read_wav(path: Path) -> bytes:
    """A recording as 16 kHz mono 16-bit (the speech engine's own sample, jfk.wav, is already that)."""
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("Use a 16 kHz mono 16-bit recording.")
        return w.readframes(w.getnframes())


def write_out(pcm: bytes, model: Path, language: str, prompt: str) -> str:
    """One piece written out by whisper-cli: greedy and without second tries, so it keeps up."""
    exe = hd.engine()
    with tempfile.TemporaryDirectory(prefix="huginn-captions-") as tmp:
        wav = Path(tmp) / "piece.wav"
        write_wav(pcm, wav)
        threads = str(max(1, min(8, (os.cpu_count() or 2) - 1)))
        argv = [exe, "-m", str(model), "-f", str(wav), "-l", language or "auto", "-t", threads, "-nt", "-np",
                "-bs", "1", "-bo", "1", "-nf", "-sns"]
        if prompt:
            argv += ["--prompt", prompt[-200:]]
        out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError((out.stderr.strip().splitlines() or ["whisper-cli stopped"])[-1])
    return clean(out.stdout)


class Captions:
    def __init__(self, model: Path, language: str):
        self.model, self.language = model, language
        self.pieces = queue.Queue()
        self.said = ""
        self.n = 0

    def writer(self) -> None:
        """Writes out pieces as they come; ones that waited meanwhile go together (it never falls far behind)."""
        while True:
            pcm = self.pieces.get()
            if pcm is None:
                return
            while not self.pieces.empty() and len(pcm) / 2 / RATE < MERGE_UP_TO:
                more = self.pieces.get()
                if more is None:
                    self.pieces.put(None)
                    break
                pcm += more
            try:
                text = write_out(pcm, self.model, self.language, self.said)
            except (OSError, RuntimeError, subprocess.SubprocessError) as err:
                emit({"error": str(err)})
                continue
            if text:
                self.n += 1
                self.said = (self.said + " " + text).strip()[-400:]
                emit({"caption": text, "n": self.n})


def listen(args) -> int:
    if args.demo:
        return demo()
    exe = hd.engine()
    if not exe or not hd.cpu_ok():
        emit({"state": "no-engine"})
        return 1
    name = pick_model(args.model)
    if not name:
        emit({"state": "no-model"})
        return 1
    language = args.language or hd.prefs().get("language", "auto")
    caps = Captions(hd.model_path(name), language)
    writer = threading.Thread(target=caps.writer, daemon=True)
    writer.start()
    cutter = Cutter()

    if args.wav:                    # a recording, played through as if it were coming from the speakers
        try:
            pcm = read_wav(Path(args.wav))
        except (OSError, ValueError, EOFError) as err:
            emit({"state": "no-sound", "why": str(err)})
            return 1
        emit({"state": "listening", "model": name})
        for i in range(0, len(pcm), BLOCK):
            for piece in cutter.feed(pcm[i:i + BLOCK]):
                caps.pieces.put(piece)
        for piece in cutter.rest():
            caps.pieces.put(piece)
        caps.pieces.put(None)
        writer.join()
        emit({"state": "stopped"})
        return 0

    cmd = sound_command()
    if not cmd:
        emit({"state": "no-sound", "why": "Nothing here can read what's playing (pw-record)."})
        return 1
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as err:
        emit({"state": "no-sound", "why": str(err)})
        return 1

    def stop(*_):
        try:
            os.killpg(proc.pid, signal.SIGTERM)      # the recorder and anything it started
        except OSError:
            pass
        os._exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    emit({"state": "listening", "model": name})
    parent = os.getppid()
    while True:
        block = proc.stdout.read(BLOCK)
        if not block:
            break
        for piece in cutter.feed(block):
            caps.pieces.put(piece)
        if os.getppid() != parent:          # the shell went away without saying
            break
    emit({"state": "no-sound", "why": "the sound system isn't answering."})
    stop()
    return 1


DEMO = ["Welcome back to the channel.", "Today we're building a cabin out of reclaimed timber,",
        "starting with the frame and the roof beams.", "The first thing you want is a level base,",
        "so we're putting down gravel and compacting it.", "It took about two days with a rented plate compactor."]


def demo() -> int:
    emit({"state": "listening", "model": "base"})
    for n, line in enumerate(DEMO, 1):
        time.sleep(1.6)
        emit({"caption": line, "n": n})
    while True:
        time.sleep(3600)


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="huginn-captions", description="Live captions of what the computer is playing.")
    sub = ap.add_subparsers(dest="cmd")
    li = sub.add_parser("listen")
    li.add_argument("--model", default="")
    li.add_argument("--language", default="")
    li.add_argument("--wav", default="")
    li.add_argument("--demo", action="store_true")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    if args.cmd == "listen":
        return listen(args)
    if args.cmd == "status":
        print(json.dumps({"engine": bool(hd.engine()), "model": pick_model(), "models": [n for n in QUICKEST_FIRST if hd.have_model(n)]}))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
