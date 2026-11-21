#!/usr/bin/env python3
"""Dictation: talk, and what you say is typed where you're typing. Super+H starts it; Super+H again, Done in the
dock's live island, or a pause in what you say ends it. Everything happens on this computer: the sound never leaves it.

    listening   the microphone through PipeWire (pw-record, 16 kHz mono), read as it comes: the island shows that it's
                listening, and two and a half seconds of quiet after you've spoken ends it by itself (two minutes at
                most). Cancel throws it away.
    writing     whisper.cpp (whisper-cli, built into the image from vendor/whisper.cpp) turns it into text, then it's
                typed into the window in front, the way the emoji picker types (huginn_clipboard.type_text). With
                "Tidy it up" on, Huginn AI first makes it into clean written text: punctuation, no filler words, lists
                where you listed things (huginn_ai's "dictation" task; on this computer with a local model).
    the model   speech models are large, so none is in the image: one is downloaded the first time, from whisper.cpp's
                own models on Hugging Face, and checked against the SHA-1 whisper.cpp publishes for it. Three sizes:
                Quick (base, 142 MB), Balanced (small, 466 MB) and Accurate (large-v3-turbo, quantised, 547 MB).
                They go in ~/.local/share/huginn/whisper, where Clips also finds them for captions.

    huginn-dictate toggle            Super+H: start, or end the one listening
    huginn-dictate status            JSON: the engine, the models, which is chosen and which are here
    huginn-dictate get MODEL         download a model (prints progress lines)
    huginn-dictate file WAV          what a recording says (for a test)
"""
import array
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

RATE = 16000
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
MODELS = {                                                        # name: (label, size, SHA-1 from whisper.cpp's models/README.md)
    "base": ("Quick", "142 MB", "465707469ff3a37a2b9b8d8f89f2f99de7299dac"),
    "small": ("Balanced", "466 MB", "55356645c2b361a969dfd0ef2c5a50d530afd8d5"),
    "large-v3-turbo-q5_0": ("Accurate", "547 MB", "e050f7970618a659205450ad97eb95a18d69c9ee"),
}
DEFAULT_MODEL = "small"
QUIET_END = 2.5                                                   # seconds of quiet after speech that end it
LONGEST = 120.0
NOTHING_SAID = 8.0                                                # seconds with no speech at all: it gives up


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "whisper"


def prefs_file() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn" / "dictation.json"


def runtime_file() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "huginn" / "dictation.pid"


def prefs() -> dict:
    try:
        p = json.loads(prefs_file().read_text())
    except (OSError, ValueError):
        p = {}
    p = p if isinstance(p, dict) else {}
    p.setdefault("model", DEFAULT_MODEL)
    p.setdefault("language", "auto")
    p.setdefault("autoStop", True)
    p.setdefault("tidy", False)
    return p


def save_prefs(p: dict) -> None:
    prefs_file().parent.mkdir(parents=True, exist_ok=True)
    tmp = prefs_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(p, indent=1))
    os.replace(tmp, prefs_file())


def engine():
    for path in ("/usr/libexec/huginn/whisper-cli", shutil.which("whisper-cli") or "", shutil.which("whisper-cpp") or ""):
        if path and os.access(path, os.X_OK):
            return path
    return None


def cpu_ok() -> bool:
    """The image's whisper-cli is built for processors with AVX2 (2013 on); older ones can't run it."""
    try:
        return "avx2" in Path("/proc/cpuinfo").read_text()
    except OSError:
        return True


def model_path(name: str) -> Path:
    return data_dir() / f"ggml-{name}.bin"


def have_model(name: str) -> bool:
    return model_path(name).is_file()


def ai_ready() -> bool:
    try:
        import huginn_ai
        return huginn_ai.ready("dictation")
    except Exception:                                             # noqa: BLE001
        return False


def tidy_with_ai(text: str) -> str:
    """Huginn AI makes what was said into clean written text (Settings › Keyboard & Mouse › Tidy it up). What was
    heard is kept if it can't."""
    try:
        import huginn_ai
        tidied = huginn_ai.ask_once("dictation", text, surface="dictation", max_tokens=max(256, len(text)))
    except Exception as err:                                      # noqa: BLE001 — the words as heard are still typed
        print("dictation: not tidied:", err, file=sys.stderr)
        return text
    tidied = tidied.strip().strip('"').strip()
    return tidied if tidied and len(tidied) < len(text) * 3 + 200 else text   # (a runaway answer isn't what was said)


def status() -> dict:
    p = prefs()
    return {"engine": bool(engine()), "cpuOk": cpu_ok(), "model": p["model"], "language": p["language"], "autoStop": p["autoStop"],
            "tidy": bool(p.get("tidy")), "aiReady": ai_ready(),
            "models": [{"name": n, "label": m[0], "size": m[1], "here": have_model(n)} for n, m in MODELS.items()],
            "listening": _running_pid() is not None}


def download(name: str, progress=None, stop=None) -> str:
    """Fetch a model, checked against its published SHA-1. Returns "" or what went wrong."""
    if name not in MODELS:
        return "There's no such model."
    dest = model_path(name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    sha = hashlib.sha1()
    try:
        req = urllib.request.Request(MODEL_URL.format(name=name), headers={"User-Agent": "Huginn OS dictation"})
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                if stop and stop():
                    raise InterruptedError
                block = r.read(1 << 20)
                if not block:
                    break
                f.write(block)
                sha.update(block)
                got += len(block)
                if progress and total:
                    progress(got / total)
    except InterruptedError:
        part.unlink(missing_ok=True)
        return "Stopped."
    except (OSError, ValueError) as err:
        part.unlink(missing_ok=True)
        return f"Couldn't download it: {getattr(err, 'reason', None) or err}"
    if sha.hexdigest() != MODELS[name][2]:
        part.unlink(missing_ok=True)
        return "The download didn't match whisper.cpp's published checksum, so it wasn't kept."
    os.replace(part, dest)
    return ""


# ------------------------------------------------------------------------------------------------ the words
NOISE = re.compile(r"\[(?:BLANK_AUDIO|MUSIC|NOISE|SILENCE|INAUDIBLE)[^\]]*\]|\((?:music|silence|inaudible|noise|applause|laughs?)\)|\*[^*]{0,30}\*",
                   re.IGNORECASE)


def tidy(text: str) -> str:
    """whisper-cli's lines as one piece of text, without its marks for sounds that aren't words."""
    text = NOISE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def transcribe(wav: Path, model: Path, language: str = "auto") -> str:
    exe = engine()
    if not exe:
        raise RuntimeError("Dictation's speech engine isn't installed.")
    if language != "auto" and model.name.endswith(".en.bin"):
        language = "en"
    threads = str(max(1, min(8, (os.cpu_count() or 2) - 1)))
    out = subprocess.run([exe, "-m", str(model), "-f", str(wav), "-l", language or "auto", "-t", threads, "-nt", "-np"],
                         capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError((out.stderr.strip().splitlines() or ["whisper-cli stopped"])[-1])
    return tidy(out.stdout)


# ------------------------------------------------------------------------------------------------ listening
def _running_pid():
    try:
        pid = int(runtime_file().read_text().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


class Listener:
    """The microphone, read as it comes, with a level for the island and the end found by itself."""

    def __init__(self, auto_stop: bool = True):
        self.auto_stop = auto_stop
        self.pcm = bytearray()
        self.level = 0.0
        self.spoke = False
        self.done = threading.Event()
        self.cancelled = False
        self._proc = None

    def _command(self):
        if shutil.which("pw-record"):
            return ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "--media-role", "Communication", "-"]
        if shutil.which("parecord"):
            return ["parecord", "--raw", f"--rate={RATE}", "--channels=1", "--format=s16le"]
        return None

    def start(self) -> str:
        cmd = self._command()
        if not cmd:
            return "Nothing here can record from the microphone (pw-record)."
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as err:
            return f"Couldn't use the microphone: {err}"
        threading.Thread(target=self._read, daemon=True).start()
        return ""

    def _read(self) -> None:
        chunk = RATE // 10 * 2                                    # a tenth of a second of 16-bit samples
        quiet_for, started, noise = 0.0, time.time(), None
        while not self.done.is_set():
            block = self._proc.stdout.read(chunk)
            if not block:
                break
            self.pcm += block
            samples = array.array("h", block[: len(block) // 2 * 2])
            rms = math.sqrt(sum(s * s for s in samples) / max(1, len(samples))) if samples else 0.0
            # the room's own noise: follows quiet moments down at once, louder ones up only slowly
            noise = rms if noise is None else rms if rms < noise else noise * 0.995 + rms * 0.005
            loud = rms > max(400.0, noise * 3)
            self.level = min(1.0, rms / 6000.0)
            if loud:
                self.spoke, quiet_for = True, 0.0
            else:
                quiet_for += 0.1
            took = time.time() - started
            if took > LONGEST or (self.auto_stop and ((self.spoke and quiet_for >= QUIET_END) or (not self.spoke and took > NOTHING_SAID))):
                break
        self.done.set()

    def stop(self, cancel: bool = False) -> None:
        self.cancelled = self.cancelled or cancel
        self.done.set()

    def finish(self) -> bytes:
        self.done.wait()
        if self._proc and self._proc.poll() is None:
            self._proc.send_signal(signal.SIGINT)
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        return bytes(self.pcm)


def write_wav(pcm: bytes, path: Path) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def say(summary: str, body: str, settings_action: bool = False) -> None:
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        actions = ["settings", "Open Settings"] if settings_action else []
        bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                      GLib.Variant("(susssasa{sv}i)", ("Dictation", 0, "audio-input-microphone", summary, body, actions, {}, 6000)),
                      None, Gio.DBusCallFlags.NONE, 2000, None)
    except Exception:                                             # noqa: BLE001 — no notices: nothing to tell
        pass


def dictate() -> int:
    """One dictation, from Super+H to the words typed."""
    p = prefs()
    model = model_path(p["model"]) if have_model(p["model"]) else next((model_path(n) for n in MODELS if have_model(n)), None)
    if not engine() or not cpu_ok():
        say("Dictation can't run here", "Its speech engine needs a processor with AVX2." if engine() else "Its speech engine isn't installed.")
        return 1
    if model is None:
        subprocess.Popen(["python3", str(HERE / "huginn_app.py"), "settings", "--page", "input"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        say("Dictation needs its speech model", "Choose one in Settings › Keyboard & Mouse › Dictation. It's downloaded once and stays on this computer.")
        return 1
    runtime_file().parent.mkdir(parents=True, exist_ok=True)
    runtime_file().write_text(str(os.getpid()))
    listener = Listener(p.get("autoStop", True))
    signal.signal(signal.SIGUSR1, lambda *_: listener.stop())       # Super+H again
    signal.signal(signal.SIGUSR2, lambda *_: listener.stop(True))   # Cancel
    island = None
    try:
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance() or QCoreApplication(["huginn-dictate"])
        from huginn_live import LiveReport
        island = LiveReport("Dictation")
        island.action.connect(lambda key, what: listener.stop(what == "cancel"))
    except Exception:                                             # noqa: BLE001 — no island: the shortcut still works
        app = None
    problem = listener.start()
    if problem:
        runtime_file().unlink(missing_ok=True)
        say("Dictation couldn't listen", problem)
        return 1

    def show(title: str, sub: str, actions=True):
        if island is not None:
            island.report("dictation", {"kind": "progress", "title": title, "sub": sub, "glyph": "mic", "progress": -1,
                                        "actions": [{"id": "stop", "label": "Done", "glyph": "check", "tone": "primary"},
                                                    {"id": "cancel", "label": "Cancel", "glyph": "x", "tone": ""}] if actions else []})
    show("Listening…", "Speak, then pause, or press Super+H")
    while not listener.done.wait(0.1):
        if app is not None:
            app.processEvents()
    pcm = listener.finish()
    runtime_file().unlink(missing_ok=True)
    if listener.cancelled or not listener.spoke:
        if island is not None:
            island.end("dictation")
        if not listener.cancelled:
            say("Didn't hear anything", "Is the right microphone chosen in Settings › Sound?")
        return 0
    show("Writing it out…", "", actions=False)
    if app is not None:
        app.processEvents()
    with tempfile.TemporaryDirectory(prefix="huginn-dictate-") as tmp:
        wav = Path(tmp) / "speech.wav"
        write_wav(pcm, wav)
        try:
            text = transcribe(wav, model, p.get("language", "auto"))
        except (RuntimeError, OSError, subprocess.SubprocessError) as err:
            text = ""
            say("Dictation stopped", str(err))
    if text and p.get("tidy") and ai_ready():
        show("Tidying it up…", "Huginn AI", actions=False)
        if app is not None:
            app.processEvents()
        text = tidy_with_ai(text)
    if island is not None:
        island.end("dictation")
        if app is not None:
            app.processEvents()
    if text:
        import huginn_clipboard
        huginn_clipboard.type_text(text + " ")
    return 0


# ------------------------------------------------------------------------------- Settings › Keyboard & Mouse
try:
    from PySide6.QtCore import Property, QObject, Signal, Slot
except ImportError:
    QObject = object

if QObject is not object:
    class DictationSettings(QObject):
        changed = Signal()
        said = Signal(str, bool)
        _back = Signal(object)

        def __init__(self, demo: bool = False):
            super().__init__()
            self._demo, self._getting, self._fraction, self._stop = demo, "", 0.0, False
            self._back.connect(lambda fn: fn())
            self._st = self._demo_status() if demo else status()

        @staticmethod
        def _demo_status() -> dict:
            return {"engine": True, "cpuOk": True, "model": "small", "language": "auto", "autoStop": True, "listening": False, "tidy": False, "aiReady": True,
                    "models": [{"name": n, "label": m[0], "size": m[1], "here": n == "small"} for n, m in MODELS.items()]}

        st = Property("QVariantMap", lambda self: self._st, notify=changed)
        getting = Property(str, lambda self: self._getting, notify=changed)
        fraction = Property(float, lambda self: self._fraction, notify=changed)

        def _refresh(self):
            if not self._demo:
                self._st = status()
            self.changed.emit()

        @Slot(str)
        def choose(self, name: str) -> None:
            """Use this model; download it first if it isn't here."""
            if name not in MODELS:
                return
            if self._demo:
                self._st = dict(self._st, model=name)
                self.changed.emit()
                return
            p = prefs()
            p["model"] = name
            save_prefs(p)
            if not have_model(name):
                self.get(name)
            self._refresh()

        @Slot(str)
        def get(self, name: str) -> None:
            if self._getting or self._demo:
                return
            self._getting, self._fraction, self._stop = name, 0.0, False
            self.changed.emit()

            def progress(f):
                self._fraction = f
                self._back.emit(self.changed.emit)

            def work():
                err = download(name, progress, lambda: self._stop)

                def done():
                    self._getting = ""
                    if err and err != "Stopped.":
                        self.said.emit(err, True)
                    elif not err:
                        self.said.emit("Dictation is ready: press Super+H wherever you type.", False)
                    self._refresh()
                self._back.emit(done)
            threading.Thread(target=work, daemon=True).start()

        @Slot()
        def stopGetting(self) -> None:
            self._stop = True

        @Slot(str)
        def remove(self, name: str) -> None:
            if not self._demo:
                model_path(name).unlink(missing_ok=True)
            self._refresh()

        @Slot(str, "QVariant")
        def set(self, key: str, value) -> None:
            if key not in ("language", "autoStop", "tidy"):
                return
            if self._demo:
                self._st = dict(self._st, **{key: value})
                self.changed.emit()
                return
            p = prefs()
            p[key] = bool(value) if key in ("autoStop", "tidy") else str(value)
            save_prefs(p)
            self._refresh()


def toggle() -> int:
    pid = _running_pid()
    if pid is not None:
        os.kill(pid, signal.SIGUSR1)
        return 0
    return dictate()


def main(argv) -> int:
    cmd = argv[0] if argv else "toggle"
    if cmd == "toggle":
        return toggle()
    if cmd == "cancel":
        pid = _running_pid()
        if pid is not None:
            os.kill(pid, signal.SIGUSR2)
        return 0
    if cmd == "status":
        print(json.dumps(status(), indent=1))
        return 0
    if cmd == "get" and len(argv) > 1:
        err = download(argv[1], lambda f: print(f"{f:.3f}", flush=True))
        print(err or "done")
        return 1 if err else 0
    if cmd == "file" and len(argv) > 1:
        name = prefs()["model"]
        model = model_path(name) if have_model(name) else Path(argv[2]) if len(argv) > 2 else None
        if model is None:
            print("no model", file=sys.stderr)
            return 1
        print(transcribe(Path(argv[1]), model))
        return 0
    print(__doc__.strip().split("\n\n")[-1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
