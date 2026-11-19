"""Huginn Office: what Writer, Sheets and Slides share: the list of documents, saving, and files from other suites.

Each app keeps its work in an open, readable format (Writer: HTML, Sheets: JSON, Slides: JSON) and can export to
PDF and to the usual open formats.

Files from other suites (hybrid): .docx, .xlsx and .pptx are read and written by Huginn's own converters
(huginn_docx, huginn_xlsx, huginn_pptx). Older or rarer formats (.doc, .odt, .rtf, .xls, .ods, .ppt, .odp) are first turned into the
modern format by LibreOffice running invisibly, if it is installed, and then read by the same converters. Either way
the file opens here, as a copy, and the app says what could not be carried over. LibreOffice's window never opens.
"""
import datetime as dt
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Property, QObject, QStandardPaths, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices


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
