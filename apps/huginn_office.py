"""Huginn Office: the engines behind Writer, Sheets and Slides.

Each app keeps its work in an open, readable format (Writer: HTML, Sheets: JSON, Slides: JSON) and can export to
PDF and to the usual open formats.

Files from other suites (hybrid): .docx, .xlsx and .pptx are read and written by Huginn's own converters
(huginn_convert.py). Older or rarer formats (.doc, .odt, .rtf, .xls, .ods, .ppt, .odp) are first turned into the
modern format by LibreOffice running invisibly, if it is installed, and then read by the same converters. Either way
the file opens here, as a copy, and the app says what could not be carried over. LibreOffice's window never opens.
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Property, QMarginsF, QObject, QSizeF, QStandardPaths, QTimer, QUrl, Signal, Slot
import huginn_convert as convert
from PySide6.QtGui import QDesktopServices, QImage, QPageSize, QPainter, QPdfWriter


def documents_dir() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or Path.home() / "Documents")


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".saving")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def fresh_path(folder: Path, stem: str, ext: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f"{stem}{ext}", 1
    while path.exists():
        n += 1
        path = folder / f"{stem} {n}{ext}"
    return path


def when(path: Path) -> str:
    stamp = dt.datetime.fromtimestamp(path.stat().st_mtime)
    return stamp.strftime("%H:%M") if stamp.date() == dt.date.today() else stamp.strftime("%b ") + str(stamp.day)



def note_recent(path: str) -> None:
    """Into the desktop's shared recent list (the start menu's app islands and Search everything read it)."""
    try:
        import huginn_recent
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.desktopFileName() or "huginn-writer"
        huginn_recent.note(path, app, f"python3 /usr/share/huginn-apps/huginn_app.py {app.replace('huginn-', '')} %u")
    except Exception:                                      # noqa: BLE001  (never in the way of opening the file)
        pass


class Bridge:
    """LibreOffice as a file converter, run headless. Present only when `soffice` is installed."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")

    @classmethod
    def available(cls) -> bool:
        return bool(cls.exe)

    @classmethod
    def convert(cls, source: Path, target_format: str, out_dir: Path = None) -> Path:
        """Convert `source` to e.g. 'html', 'docx', 'csv', 'xlsx'. Returns the new file. Raises OSError on failure."""
        if not cls.exe:
            raise OSError("LibreOffice isn't installed, so this kind of file can't be converted.")
        out_dir = out_dir or Path(tempfile.mkdtemp(prefix="huginn-office-"))
        profile = Path(tempfile.mkdtemp(prefix="huginn-lo-profile-"))        # a private profile: never touches the user's
        try:
            done = subprocess.run([cls.exe, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore",
                                   "--convert-to", target_format, "--outdir", str(out_dir), str(source)],
                                  capture_output=True, text=True, timeout=120)
        except subprocess.SubprocessError as err:
            raise OSError(f"The conversion didn't finish: {err}")
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        result = out_dir / (source.stem + "." + target_format.split(":")[0])
        if done.returncode != 0 or not result.is_file():
            raise OSError("LibreOffice couldn't convert this file.")
        return result


class FileList(QObject):
    """Shared by the three apps: the documents of one kind in the Documents folder, newest first."""
    changed = Signal()
    failed = Signal(str)
    NATIVE, OWN, VIA_BRIDGE, MODERN, STEM = (), (), (), "", "Untitled"
    imported = Signal(str, "QVariantList")       # original file name, what could not be carried over
    noteChanged = Signal()

    def __init__(self, target: Path = None):
        super().__init__()
        self._folder, self._path, self._dirty = documents_dir(), None, False
        self._saver = QTimer(self)
        self._saver.setSingleShot(True)
        self._saver.setInterval(800)
        self._saver.timeout.connect(self.save)
        self._extra = target if target and target.is_file() else None
        self._note_file, self._note_dropped = "", []
        self.imported.connect(self._remember)

    def _remember(self, name: str, dropped: list) -> None:
        self._note_file, self._note_dropped = name, list(dropped)
        self.noteChanged.emit()

    importedFile = Property(str, lambda self: self._note_file, notify=noteChanged)
    importedDropped = Property("QVariantList", lambda self: self._note_dropped, notify=noteChanged)

    @Slot()
    def dismissNote(self) -> None:
        self._remember("", [])

    def _kinds(self) -> tuple:
        return self.NATIVE + self.OWN + (self.VIA_BRIDGE if Bridge.available() else ())

    @property
    def FOREIGN(self) -> tuple:
        return self.OWN + self.VIA_BRIDGE

    def _modern(self, source: Path) -> Path:
        """The file in the modern format our converters read; older formats pass through LibreOffice first."""
        if source.suffix.lower() in self.OWN:
            return source
        return Bridge.convert(source, self.MODERN)

    @Property("QVariantList", notify=changed)
    def files(self):
        rows = [p for p in self._folder.iterdir() if p.is_file() and p.suffix.lower() in self._kinds()] if self._folder.is_dir() else []
        if self._extra and self._extra not in rows:
            rows.append(self._extra)
        rows.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"path": str(p), "name": p.stem, "when": when(p), "foreign": p.suffix.lower() in self.FOREIGN,
                 "kind": p.suffix.lstrip(".").upper()} for p in rows[:200]]

    current = Property(str, lambda self: str(self._path) if self._path else "", notify=changed)
    title = Property(str, lambda self: self._path.stem if self._path else "", notify=changed)
    saved = Property(bool, lambda self: not self._dirty, notify=changed)
    converter = Property(bool, lambda self: Bridge.available(), constant=True)
    folder = Property(str, lambda self: str(self._folder), constant=True)

    def touch(self) -> None:
        self._dirty = True
        self._saver.start()
        self.changed.emit()

    def save(self) -> None:           # each app writes its own format
        raise NotImplementedError

    @Slot(str)
    def reveal(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))


# ============================================================================================== Slides
class Slides(FileList):
    NATIVE, OWN, VIA_BRIDGE, MODERN, STEM = (".hslides",), (".pptx",), (".odp", ".ppt"), "pptx", "Untitled Talk"
    LAYOUTS = ("title", "content", "section", "blank")
    THEMES = ("realm", "paper", "night")

    def __init__(self, target: Path = None):
        super().__init__(target)
        self._deck = {"theme": "realm", "slides": []}
        self._index = 0
        self.changed.connect(self.deckChanged)
        if self._extra:
            self.open(str(self._extra))

    deckChanged = Signal()        # a subclass property needs a signal declared in the same class
    slides = Property("QVariantList", lambda self: self._deck["slides"], notify=deckChanged)
    theme = Property(str, lambda self: self._deck["theme"], notify=deckChanged)
    index = Property(int, lambda self: self._index, notify=deckChanged)
    count = Property(int, lambda self: len(self._deck["slides"]), notify=deckChanged)

    @Slot(str)
    def open(self, path: str) -> None:
        note_recent(path)
        if self._dirty:
            self.save()
        source, target, dropped = Path(path), Path(path), None
        try:
            if source.suffix.lower() in self.FOREIGN:
                found, dropped = convert.pptx_to_slides(self._modern(source))
                data, target = {"theme": "realm", "slides": found}, fresh_path(source.parent, source.stem, ".hslides")
            else:
                data = json.loads(source.read_text(encoding="utf-8"))
            slides = [{"layout": s.get("layout", "content") if s.get("layout") in self.LAYOUTS else "content",
                       "title": str(s.get("title", "")), "body": str(s.get("body", "")), "notes": str(s.get("notes", ""))}
                      for s in data.get("slides", []) if isinstance(s, dict)]
        except (OSError, ValueError, AttributeError, convert.ConvertError) as err:
            self.failed.emit(f"Couldn't open “{source.name}”: {getattr(err, 'strerror', None) or err}")
            return
        self._deck = {"theme": data.get("theme") if data.get("theme") in self.THEMES else "realm", "slides": slides or [self._blank("title")]}
        self._path, self._dirty, self._index = target, False, 0
        if target != source:
            self.touch()
            self.imported.emit(source.name, dropped or [])
        self.changed.emit()

    @staticmethod
    def _blank(layout: str) -> dict:
        return {"layout": layout, "title": "", "body": "", "notes": ""}

    @Slot()
    def create(self) -> None:
        if self._dirty:
            self.save()
        try:
            path = fresh_path(self._folder, self.STEM, ".hslides")
            path.write_text(json.dumps({"theme": "realm", "slides": [self._blank("title")]}), encoding="utf-8")
        except OSError as err:
            self.failed.emit(f"Couldn't create a presentation: {err.strerror or err}")
            return
        self.open(str(path))

    @Slot()
    def save(self) -> None:
        if not self._dirty or self._path is None:
            return
        try:
            write_atomic(self._path, json.dumps({"format": "huginn-slides-1", **self._deck}, indent=1, ensure_ascii=False))
            self._dirty = False
        except OSError as err:
            self.failed.emit(f"Couldn't save: {err.strerror or err}")
        self.changed.emit()

    @Slot(int)
    def select(self, index: int) -> None:
        if 0 <= index < len(self._deck["slides"]) and index != self._index:
            self._index = index
            self.changed.emit()

    @Slot(str)
    def add(self, layout: str) -> None:
        if self._path is None:
            return
        self._deck["slides"].insert(self._index + 1, self._blank(layout if layout in self.LAYOUTS else "content"))
        self._index += 1
        self.touch()

    @Slot()
    def duplicate(self) -> None:
        if self._path is None or not self._deck["slides"]:
            return
        self._deck["slides"].insert(self._index + 1, json.loads(json.dumps(self._deck["slides"][self._index])))
        self._index += 1
        self.touch()

    @Slot()
    def remove(self) -> None:
        if len(self._deck["slides"]) > 1:
            del self._deck["slides"][self._index]
            self._index = min(self._index, len(self._deck["slides"]) - 1)
            self.touch()

    @Slot(int)
    def move(self, delta: int) -> None:
        target = self._index + delta
        if 0 <= target < len(self._deck["slides"]):
            s = self._deck["slides"]
            s[self._index], s[target] = s[target], s[self._index]
            self._index = target
            self.touch()

    @Slot(int, str, str)
    def write(self, index: int, field: str, text: str) -> None:
        if 0 <= index < len(self._deck["slides"]) and field in ("title", "body", "notes", "layout") and self._deck["slides"][index][field] != text:
            if field == "layout" and text not in self.LAYOUTS:
                return
            self._deck["slides"][index][field] = text
            self.touch()

    @Slot(str)
    def setTheme(self, name: str) -> None:
        if name in self.THEMES and name != self._deck["theme"]:
            self._deck["theme"] = name
            self.touch()

    @Slot(result=str)
    def exportPowerPoint(self) -> str:
        if self._path is None:
            return ""
        self.save()
        try:
            out = fresh_path(self._path.parent, self._path.stem, ".pptx")
            convert.slides_to_pptx(self._deck["slides"], out, self._deck["theme"])
        except OSError as err:
            self.failed.emit(f"Couldn't export: {err.strerror or err}")
            return ""
        return str(out)

    @Slot(result=str)
    def scratch(self) -> str:
        """A temporary folder for the slide pictures an export is made from."""
        return tempfile.mkdtemp(prefix="huginn-slides-")

    @Slot("QVariantList", result=str)
    def pdf(self, pictures: list) -> str:
        """Bind one picture per slide into a PDF beside the presentation. Returns its path ('' on failure)."""
        if self._path is None or not pictures:
            return ""
        try:
            out = fresh_path(self._path.parent, self._path.stem, ".pdf")
            writer = QPdfWriter(str(out))
            writer.setPageSize(QPageSize(QSizeF(338.67, 190.5), QPageSize.Millimeter))          # 16:9
            writer.setPageMargins(QMarginsF(0, 0, 0, 0))
            writer.setResolution(144)
            writer.setTitle(self._path.stem)
            painter = QPainter(writer)
            for n, picture in enumerate(pictures):
                image = QImage(str(picture))
                if image.isNull():
                    painter.end()
                    raise OSError("a slide picture is missing")
                if n:
                    writer.newPage()
                painter.drawImage(painter.viewport(), image)
            painter.end()
            shutil.rmtree(Path(str(pictures[0])).parent, ignore_errors=True)
        except OSError as err:
            self.failed.emit(f"Couldn't export: {err.strerror or err}")
            return ""
        return str(out)
