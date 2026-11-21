"""Look Up (Super+A): circle or drag over anything on the screen, and do something with it. The screen freezes, you
mark what you mean, and its words are read on this computer (tesseract, as Scan uses): copy them, translate them,
search the web for them, ask Huginn AI about them, or keep the picture.

    the picture   from Huginn's compositor (org.huginn.Compositor.Capture: one picture per screen), taken before the
                  window shows, so it isn't in it; the window shows the screen it opened on, frozen.
    the words     tesseract, in English and the system's language when its pack is installed, on the part you marked,
                  enlarged first (screen text is small for it). Nothing leaves the computer unless you search the web,
                  or ask Huginn AI with a model in one of your accounts.
    copying       through wl-copy, which keeps what's copied after this window closes.
"""
from __future__ import annotations

import json
import locale
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote_plus

from PySide6.QtCore import Property, QObject, QPoint, QRect, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter

HERE = Path(__file__).resolve().parent
RUN = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "huginn" / "lens"
TESS_LANG = {"de": "deu", "fr": "fra", "es": "spa", "it": "ita", "nb": "nor", "nn": "nor", "no": "nor", "pt": "por", "nl": "nld",
             "sv": "swe", "da": "dan", "fi": "fin", "pl": "pol", "ja": "jpn", "zh": "chi_sim", "ko": "kor", "ru": "rus",
             "uk": "ukr", "ar": "ara", "tr": "tur", "hi": "hin"}


def capture_parts() -> list:
    """Each screen as {"image": QImage, "x", "y", "lw", "lh"} (where it is on the desktop), or [] when it can't."""
    try:
        from gi.repository import Gio
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        text = bus.call_sync("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor", "Capture",
                             None, None, 0, 20000, None).unpack()[0]
        parts = json.loads(text) if text.startswith("[") else []
    except Exception:                                             # noqa: BLE001 — not Huginn's compositor
        return []
    import huginn_capture
    out = []
    for p in parts:
        image = huginn_capture.raw_image(p["path"])
        try:
            os.unlink(p["path"])
        except OSError:
            pass
        if not isinstance(image, str):
            out.append({"image": image, "x": p["x"], "y": p["y"], "lw": p["lw"], "lh": p["lh"]})
    return out


def demo_picture() -> QImage:
    """A made-up screen for previews: a window with some words on it."""
    img = QImage(1600, 1000, QImage.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, 1600, 1000)
    g.setColorAt(0, QColor("#0E2A3A"))
    g.setColorAt(1, QColor("#1C1240"))
    p.fillRect(img.rect(), g)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#F4F1EA"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRect(260, 160, 1080, 640), 18, 18)
    p.setPen(QColor("#1A1D24"))
    f = QFont("Inter")
    f.setPixelSize(44)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QPoint(330, 270), "Northern lights tonight")
    f.setPixelSize(26)
    f.setBold(False)
    p.setFont(f)
    for i, line in enumerate(["The aurora should be visible after 10 pm", "from Tromsø, Abisko and Fairbanks.",
                              "Best viewing: away from city lights,", "facing north, with a clear sky."]):
        p.drawText(QPoint(330, 350 + i * 44), line)
    p.end()
    return img


def ocr_languages() -> str:
    try:
        have = set(subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10).stdout.split()[1:])
    except (OSError, subprocess.SubprocessError):
        return "eng"
    lang = (locale.getlocale()[0] or os.environ.get("LANG", "en")).split("_")[0].lower()
    want = ["eng"] + ([TESS_LANG[lang]] if lang in TESS_LANG else [])
    return "+".join(l for l in dict.fromkeys(want) if l in have) or "eng"


def read_text(png: Path) -> str:
    if not shutil.which("tesseract"):
        return ""
    try:
        out = subprocess.run(["tesseract", str(png), "-", "-l", ocr_languages(), "--psm", "3"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = [l.rstrip() for l in out.stdout.replace("\f", "").splitlines()]
    text = "\n".join(lines).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def browser_command(query: str) -> list:
    """Huginn (the browser) with something to search for, as the shell's Search does; else the web's default."""
    for d in (Path.home() / ".local/share/applications", Path("/usr/share/applications")):
        for f in sorted(d.glob("*.desktop")) if d.is_dir() else []:
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            if "\nName=Huginn\n" in text:
                exe = next((l.split("=", 1)[1] for l in text.splitlines() if l.startswith("Exec=")), "")
                import shlex
                try:
                    argv = [a for a in shlex.split(exe) if not (len(a) == 2 and a.startswith("%"))]
                except ValueError:
                    continue
                if argv:
                    return argv + [query]
    return ["xdg-open", "https://duckduckgo.com/?q=" + quote_plus(query)]


class Lens(QObject):
    changed = Signal()
    said = Signal(str, bool)
    _back = Signal(object)

    def __init__(self, demo: bool = False):
        super().__init__()
        self._demo = demo
        self._back.connect(lambda fn: fn())
        RUN.mkdir(parents=True, exist_ok=True)
        self._parts = [{"image": demo_picture(), "x": 0, "y": 0, "lw": 1600, "lh": 1000}] if demo else capture_parts()
        self._screen, self._image, self._pixels = None, "", [1, 1]
        self._crop, self._text, self._reading, self._looked = None, "", False, False
        self._answer, self._asking = "", False
        self._stamp = 0
        if self._parts:
            self._use(self._parts[0])

    def _use(self, part: dict) -> None:
        self._screen = part["image"]
        self._stamp += 1
        path = RUN / f"screen-{self._stamp}.png"
        part["image"].save(str(path), "PNG")
        for old in RUN.glob("screen-*.png"):
            if old != path:
                old.unlink(missing_ok=True)
        self._image = QUrl.fromLocalFile(str(path)).toString()
        self._pixels = [part["image"].width(), part["image"].height()]
        self.changed.emit()

    image = Property(str, lambda self: self._image, notify=changed)
    pixels = Property("QVariantList", lambda self: self._pixels, notify=changed)
    text = Property(str, lambda self: self._text, notify=changed)
    reading = Property(bool, lambda self: self._reading, notify=changed)
    looked = Property(bool, lambda self: self._looked, notify=changed)
    answer = Property(str, lambda self: self._answer, notify=changed)
    asking = Property(bool, lambda self: self._asking, notify=changed)
    have = Property(bool, lambda self: bool(self._parts), constant=True)

    @Property(bool, notify=changed)
    def aiReady(self) -> bool:
        if self._demo:
            return True
        try:
            import huginn_ai
            return huginn_ai.ready("lens")
        except Exception:                                         # noqa: BLE001
            return False

    @Slot(int, int, int, int)
    def useScreen(self, x: int, y: int, w: int, h: int) -> None:
        """The window is on this screen (its place on the desktop): show that screen's picture."""
        if len(self._parts) < 2:
            return
        best = min(self._parts, key=lambda p: abs(p["x"] - x) + abs(p["y"] - y) + abs(p["lw"] - w) + abs(p["lh"] - h))
        if best["image"] is not self._screen:
            self._use(best)

    @Slot(float, float, float, float)
    def look(self, fx: float, fy: float, fw: float, fh: float) -> None:
        """Read what's in this part of the picture (shares of its width and height)."""
        if self._screen is None:
            return
        W, H = self._screen.width(), self._screen.height()
        r = QRect(int(fx * W), int(fy * H), max(1, int(fw * W)), max(1, int(fh * H))).intersected(QRect(0, 0, W, H))
        self._crop = self._screen.copy(r)
        self._text, self._answer, self._reading, self._looked = "", "", True, True
        self.changed.emit()
        crop = self._crop
        stamp = self._stamp = self._stamp + 1

        def work():
            path = RUN / "look.png"
            big = crop.scaled(crop.width() * 2, crop.height() * 2, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            big.convertToFormat(QImage.Format_Grayscale8).save(str(path), "PNG")
            text = read_text(path)
            path.unlink(missing_ok=True)

            def done():
                if stamp == self._stamp:
                    self._text, self._reading = text, False
                    self.changed.emit()
            self._back.emit(done)
        threading.Thread(target=work, daemon=True).start()

    def _wl_copy(self, data: bytes, mime: str) -> bool:
        if not shutil.which("wl-copy"):
            return False
        try:
            subprocess.run(["wl-copy", "--type", mime], input=data, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    @Slot(str)
    def copyText(self, text: str) -> None:
        if self._demo or self._wl_copy(text.encode("utf-8"), "text/plain;charset=utf-8"):
            self.said.emit("Copied.", False)

    @Slot()
    def copyPicture(self) -> None:
        if self._crop is None:
            return
        path = RUN / "copy.png"
        self._crop.save(str(path), "PNG")
        if self._demo or self._wl_copy(path.read_bytes(), "image/png"):
            self.said.emit("Picture copied.", False)
        path.unlink(missing_ok=True)

    @Slot(result=str)
    def savePicture(self) -> str:
        if self._crop is None:
            return ""
        import huginn_capture
        folder = huginn_capture.pictures_dir() / "Screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"Screenshot {time.strftime('%Y-%m-%d at %H.%M.%S')}.png"
        if not self._demo:
            self._crop.save(str(path), "PNG")
        self.said.emit("Saved in Pictures › Screenshots.", False)
        return str(path)

    def _start(self, argv: list) -> None:
        if not self._demo:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    @Slot(str)
    def search(self, text: str) -> None:
        text = " ".join(text.split())[:400]
        if text:
            self._start(browser_command(text))

    @Slot(str)
    def translate(self, text: str) -> None:
        if not text.strip():
            return
        folder = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn" / "look-up"
        folder.mkdir(parents=True, exist_ok=True)
        f = folder / "Text from the screen.txt"
        f.write_text(text, encoding="utf-8")
        self._start([sys.executable, str(HERE / "huginn_app.py"), "translate", str(f)])

    @Slot(str, str)
    def ask(self, text: str, question: str) -> None:
        question = question.strip() or "What is this, and what should I know about it?"
        self._answer, self._asking = "", True
        self.changed.emit()

        def work():
            if self._demo:
                time.sleep(0.3)
                answer, bad = "A forecast for the aurora: it should be visible after 10 pm in the far north, best away from city lights.", False
            else:
                try:
                    import huginn_ai
                    answer, bad = huginn_ai.ask_once("lens", text or "(no words could be read there)", {"ask": question}, surface="lens"), False
                except Exception as err:                          # noqa: BLE001 — said in the window
                    answer, bad = str(err), True

            def done():
                self._answer, self._asking = answer, False
                if bad:
                    self.said.emit(answer, True)
                self.changed.emit()
            self._back.emit(done)
        threading.Thread(target=work, daemon=True).start()

    @Slot()
    def again(self) -> None:
        self._crop, self._text, self._answer, self._looked, self._reading = None, "", "", False, False
        self.changed.emit()
