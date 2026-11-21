"""Live captions in the shell: runs the caption engine (apps/huginn_captions.py) while Settings says captions are on
(Control Centre, Super+Ctrl+L, Settings › Accessibility) and keeps what it writes out for the caption bar
(CaptionBar.qml). The engine's lines are JSON, one per line; see huginn_captions.py."""
import json
import sys
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, QTimer, Signal, Slot

HERE = Path(__file__).resolve().parent
KEEP = 600            # characters of what was said kept for the bar (it shows the last lines of them)


def engine_argv(demo: bool) -> list:
    for d in (Path("/usr/share/huginn-apps"), HERE.parent / "apps"):
        if (d / "huginn_captions.py").exists():
            return [str(d / "huginn_captions.py"), "listen"] + (["--demo"] if demo else [])
    return []


class CaptionFeed(QObject):
    changed = Signal()

    def __init__(self, settings, demo: bool = False):
        super().__init__()
        self._settings, self._demo = settings, demo
        self._proc = None
        self._buf = b""
        self._state, self._why, self._model, self._text, self._error = "off", "", "", "", ""
        self._last = 0
        self._stopping = False
        self._tries = 0
        self._retry = QTimer(self, singleShot=True, interval=4000, timeout=self._follow)
        settings.changed.connect(self._follow)
        QTimer.singleShot(0, self._follow)

    # ------------------------------------------------------------------ what the bar shows
    state = Property(str, lambda self: self._state, notify=changed)       # off, starting, listening, no-model, no-engine, no-sound
    why = Property(str, lambda self: self._why, notify=changed)
    model = Property(str, lambda self: self._model, notify=changed)
    text = Property(str, lambda self: self._text, notify=changed)         # what was said lately, oldest first
    error = Property(str, lambda self: self._error, notify=changed)
    count = Property(int, lambda self: self._last, notify=changed)        # pieces so far (the bar wakes up on each)

    def _set(self, **kv) -> None:
        for k, v in kv.items():
            setattr(self, "_" + k, v)
        self.changed.emit()

    # ------------------------------------------------------------------ on and off
    def _wanted(self) -> bool:
        return bool(getattr(self._settings, "captions", False))

    def _follow(self) -> None:
        want = self._wanted()
        running = self._proc is not None and self._proc.state() != QProcess.NotRunning
        if want and not running:
            self._start()
        elif not want and running:
            self._stop()
        elif not want and self._state != "off":
            self._set(state="off", text="", error="", why="")

    def _start(self) -> None:
        argv = engine_argv(self._demo)
        if not argv:
            self._set(state="no-engine", why="")
            return
        model = getattr(self._settings, "captionsModel", "") or ""
        if model and not self._demo:
            argv += ["--model", model]
        self._buf, self._stopping = b"", False
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.SeparateChannels)
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.finished.connect(self._ended)
        self._set(state="starting", text="", error="", why="")
        self._proc.start(sys.executable or "python3", argv)

    def _stop(self) -> None:
        self._stopping = True
        if self._proc is not None:
            self._proc.terminate()
            if not self._proc.waitForFinished(1500):
                self._proc.kill()
        self._set(state="off", text="", error="", why="")

    def _ended(self, *_):
        proc, self._proc = self._proc, None
        if proc is not None:
            proc.deleteLater()
        if self._stopping or not self._wanted():
            return
        if self._state in ("listening", "starting"):        # it stopped by itself: start again in a moment
            self._tries = 0
            self._set(state="starting")
            self._retry.start(4000)
        elif self._state == "no-sound" and self._tries < 6:  # (the sound server may still be starting, at sign-in)
            self._tries += 1
            self._retry.start(10000)

    def _read(self) -> None:
        if self._proc is None:
            return
        self._buf += bytes(self._proc.readAllStandardOutput())
        *lines, self._buf = self._buf.split(b"\n")
        for raw in lines:
            try:
                msg = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if "caption" in msg:
                said = (self._text + " " + str(msg["caption"])).strip()
                self._set(text=said[-KEEP:], error="", last=self._last + 1)
            elif "state" in msg:
                if msg["state"] == "listening":
                    self._tries = 0
                self._set(state=str(msg["state"]), why=str(msg.get("why", "")), model=str(msg.get("model", self._model)))
            elif "error" in msg:
                self._set(error=str(msg["error"]))

    # ------------------------------------------------------------------ from the bar
    @Slot()
    def toggle(self) -> None:
        self._settings.set("captions", "false" if self._wanted() else "true")

    @Slot()
    def clear(self) -> None:
        self._set(text="")

    @Slot(str)
    def openSettings(self, page: str) -> None:
        for d in (Path("/usr/share/huginn-apps"), HERE.parent / "apps"):
            if (d / "huginn_app.py").exists():
                QProcess.startDetached("python3", [str(d / "huginn_app.py"), "settings", "--page", page or "a11y"])
                return
