"""Clipboard history: what you copied lately (text and pictures), brought back with Super+V.

It is off until you turn it on (Super+V says how, and Settings › Privacy & Security has the switch). While it's on,
`wl-paste --watch` runs `huginn_clipboard.py store` each time the clipboard changes; that keeps the newest 50 things
(and any you pinned) in ~/.local/share/huginn/clipboard, readable only by you. Passwords are never kept: anything
copied with the password managers' mark (x-kde-passwordManagerHint, which Passwords and Authenticator set, as
KeePassXC and Bitwarden do) is skipped, and so are copied files (Files keeps those itself).

    python3 huginn_clipboard.py watch     the watcher (the session starts it)
    python3 huginn_clipboard.py store     one change, the clipboard's content on stdin (wl-paste runs it)
    python3 huginn_clipboard.py clear     forget everything but the pinned
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("HOME") or Path.home())
DIR = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share") / "huginn" / "clipboard"
FLAG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "huginn" / "clipboard-history-on"
KEEP = 50
TEXT_MAX = 1 << 20          # 1 MB of text
IMAGE_MAX = 16 << 20        # 16 MB of picture
SKIP_TYPES = ("x-kde-passwordManagerHint", "text/uri-list", "x-special/gnome-copied-files", "application/x-kde-cutselection")


def enabled() -> bool:
    return FLAG.exists()


def set_enabled(on: bool) -> None:
    FLAG.parent.mkdir(parents=True, exist_ok=True)
    if on:
        FLAG.touch()
    else:
        FLAG.unlink(missing_ok=True)
        clear(keep_pinned=False)


def _index() -> list:
    try:
        rows = json.loads((DIR / "index.json").read_text(encoding="utf-8"))
        return [r for r in rows if isinstance(r, dict) and (DIR / r.get("file", "-")).exists()]
    except (OSError, ValueError):
        return []


def _save(rows: list) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DIR, 0o700)
    tmp = DIR / "index.json.saving"
    tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, DIR / "index.json")


def _trim(rows: list) -> list:
    """The newest KEEP (pinned ones always stay); the files of the rest go."""
    kept, n = [], 0
    for r in rows:
        if r.get("pinned") or n < KEEP:
            kept.append(r)
            n += 0 if r.get("pinned") else 1
        else:
            (DIR / r["file"]).unlink(missing_ok=True)
    return kept


def entries() -> list:
    return _index()


def add(data: bytes, kind: str, size: tuple = (0, 0)) -> dict:
    """One copied thing into the history (the same thing again just moves to the top)."""
    digest = hashlib.sha1(data).hexdigest()[:16]
    rows = _index()
    same = next((r for r in rows if r.get("hash") == digest), None)
    if same is not None:
        rows.remove(same)
        same["at"] = time.time()
        rows.insert(0, same)
        _save(rows)
        return same
    DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DIR, 0o700)
    name = f"{int(time.time() * 1000)}-{digest}.{'png' if kind == 'image' else 'txt'}"
    path = DIR / name
    path.write_bytes(data)
    os.chmod(path, 0o600)
    row = {"id": name.split(".")[0], "kind": kind, "file": name, "hash": digest, "at": time.time(), "pinned": False}
    if kind == "text":
        text = data.decode("utf-8", errors="replace")
        row["preview"] = text[:400]
        row["lines"] = text.count("\n") + 1
        row["chars"] = len(text)
    else:
        row["w"], row["h"] = size
    rows.insert(0, row)
    _save(_trim(rows))
    return row


def find(ident: str) -> dict:
    return next((r for r in _index() if r.get("id") == ident), None)


def pin(ident: str, on: bool) -> None:
    rows = _index()
    for r in rows:
        if r.get("id") == ident:
            r["pinned"] = bool(on)
    _save(_trim(rows))


def remove(ident: str) -> None:
    rows = _index()
    for r in [r for r in rows if r.get("id") == ident]:
        (DIR / r["file"]).unlink(missing_ok=True)
        rows.remove(r)
    _save(rows)


def clear(keep_pinned: bool = True) -> None:
    rows = _index()
    kept = [r for r in rows if keep_pinned and r.get("pinned")]
    for r in rows:
        if r not in kept:
            (DIR / r["file"]).unlink(missing_ok=True)
    if DIR.exists():
        _save(kept)


def copy_back(ident: str, wait: bool = False) -> bool:
    """Put an entry on the clipboard again (wl-copy keeps offering it until something else is copied). With wait,
    return once the clipboard really holds it (up to a second), so a paste straight after gets it and not the last."""
    row = find(ident)
    if row is None or not shutil.which("wl-copy"):
        return False
    path = DIR / row["file"]
    kind = "image/png" if row["kind"] == "image" else "text/plain;charset=utf-8"
    try:
        with open(path, "rb") as f:
            proc = subprocess.Popen(["wl-copy", "--type", kind], stdin=f, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
        if wait:
            try:
                proc.wait(timeout=2)                          # it goes on in the background once it holds the clipboard
            except subprocess.TimeoutExpired:
                pass
            want = path.read_bytes() if row["kind"] != "image" else None
            end = time.time() + 1.0
            while time.time() < end and shutil.which("wl-paste"):
                try:
                    if want is None:
                        now = subprocess.run(["wl-paste", "--list-types"], capture_output=True, timeout=1).stdout
                        if b"image/png" in now:
                            break
                    else:
                        now = subprocess.run(["wl-paste", "--no-newline", "--type", "text/plain;charset=utf-8"], capture_output=True, timeout=1).stdout
                        if now.rstrip(b"\n") == want.rstrip(b"\n"):
                            break
                except (OSError, subprocess.SubprocessError):
                    break
                time.sleep(0.04)
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------------------------- Super+V, in the shell
def type_text(text: str) -> bool:
    """Type some text into the window in front, by way of the clipboard (Ctrl+V from the compositor), then put back
    what was on the clipboard before. Neither goes into clipboard history. Blocks for a second or two: run it off
    the caller's thread."""
    if not text or not shutil.which("wl-copy"):
        return False
    saved_type, saved = "", b""
    try:
        types = subprocess.run(["wl-paste", "--list-types"], capture_output=True, text=True, timeout=2).stdout.split()
        saved_type = next((t for t in types if t.startswith(("text/plain;charset=utf-8", "image/png"))), next((t for t in types if not t.isupper()), ""))
        if saved_type:
            saved = subprocess.run(["wl-paste", "--no-newline", "--type", saved_type], capture_output=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        saved_type, saved = "", b""
    try:
        PASSING.touch()
        subprocess.run(["wl-copy", "--type", "text/plain;charset=utf-8", text], timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        end = time.time() + 1.0
        while time.time() < end:
            got = subprocess.run(["wl-paste", "--no-newline", "--type", "text/plain;charset=utf-8"], capture_output=True, timeout=1).stdout
            if got.decode("utf-8", "replace") == text:
                break
            time.sleep(0.04)
        from gi.repository import Gio
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor", "Paste", None, None,
                      Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
    except Exception:                                            # noqa: BLE001
        return False
    if saved_type and saved and len(saved) <= IMAGE_MAX:
        time.sleep(0.9)                                         # long enough for the app to have read it
        try:
            PASSING.touch()
            subprocess.run(["wl-copy", "--type", saved_type], input=saved, timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass
    return True


def when_text(t: float) -> str:
    d = time.time() - t
    if d < 60:
        return "Just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return time.strftime("%H:%M", time.localtime(t))
    return time.strftime("%d %b", time.localtime(t))


def qt_history():
    """The history as the shell's Super+V panel shows it (Qt is only needed here, not by the watcher)."""
    from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QTimer, QUrl, Signal, Slot

    class ClipHistory(QObject):
        changed = Signal()

        def __init__(self):
            super().__init__()
            self._rows, self._on = [], enabled()
            self._watch = QFileSystemWatcher(self)
            self._watch.directoryChanged.connect(lambda *_: self._soon.start())
            self._watch.fileChanged.connect(lambda *_: self._soon.start())
            self._soon = QTimer(self, singleShot=True, interval=120, timeout=self.refresh)
            self.refresh()

        def _rewatch(self) -> None:
            for p in (DIR, DIR / "index.json", FLAG.parent):
                if p.exists() and str(p) not in self._watch.files() + self._watch.directories():
                    self._watch.addPath(str(p))

        @Slot()
        def refresh(self) -> None:
            self._on = enabled()
            self._rows = [dict(r, when=when_text(r.get("at", 0)), url=QUrl.fromLocalFile(str(DIR / r["file"])).toString() if r["kind"] == "image" else "")
                          for r in entries()]
            self._rewatch()
            self.changed.emit()

        items = Property("QVariantList", lambda self: self._rows, notify=changed)
        on = Property(bool, lambda self: self._on, notify=changed)

        @Slot(bool)
        def setOn(self, on: bool) -> None:
            set_enabled(on)
            self.refresh()

        @Slot(str, result=bool)
        def pick(self, ident: str) -> bool:
            """Back on the clipboard, and pasted into the window in front (once this panel has gone): off the
            shell's thread, as waiting for the clipboard to change takes a moment."""
            if find(ident) is None:
                return False

            def go():
                if not copy_back(ident, wait=True):
                    return
                try:
                    from gi.repository import Gio
                    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                    bus.call_sync("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor", "Paste", None, None,
                                  Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
                except Exception:                                # noqa: BLE001  (on the clipboard is still useful)
                    pass
            import threading
            threading.Thread(target=go, daemon=True).start()
            return True

        @Slot(str, bool)
        def pin(self, ident: str, on: bool) -> None:
            pin(ident, on)
            self.refresh()

        @Slot(str)
        def remove(self, ident: str) -> None:
            remove(ident)
            self.refresh()

        @Slot()
        def clearAll(self) -> None:
            clear()
            self.refresh()

        @Slot(str, result=str)
        def fullText(self, ident: str) -> str:
            row = find(ident)
            if row is None or row["kind"] != "text":
                return ""
            try:
                return (DIR / row["file"]).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""

    return ClipHistory()


# ---------------------------------------------------------------------------------------------- the watcher's side
def _png_size(data: bytes) -> tuple:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return (0, 0)


PASSING = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "huginn-clipboard-passing"


def passing() -> bool:
    """The clipboard is only being borrowed (an emoji typed in, the old clipboard put back): history leaves it."""
    try:
        return time.time() - PASSING.stat().st_mtime < 4
    except OSError:
        return False


def store_from_stdin() -> int:
    if not enabled() or os.environ.get("CLIPBOARD_STATE", "data") in ("sensitive", "nil", "clear") or passing():
        sys.stdin.buffer.read()
        return 0
    data = sys.stdin.buffer.read(IMAGE_MAX + 1)
    if not data or len(data) > IMAGE_MAX:
        return 0
    try:
        types = subprocess.run(["wl-paste", "--list-types"], capture_output=True, text=True, timeout=3).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        types = []
    if any(t.startswith(SKIP_TYPES) for t in types):
        return 0
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        add(data, "image", _png_size(data))
        return 0
    if any(t.startswith("image/") for t in types) and not any(t.startswith("text/") for t in types):
        try:                                                          # a picture offered in another format: ask for PNG
            png = subprocess.run(["wl-paste", "--type", "image/png"], capture_output=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            png = b""
        if png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) <= IMAGE_MAX:
            add(png, "image", _png_size(png))
        return 0
    if len(data) > TEXT_MAX:
        return 0
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return 0
    if text.strip():
        add(text.encode("utf-8"), "text")
    return 0


def watch() -> int:
    """The session's watcher: one small shell command per change, so a change costs nothing while history is off."""
    if not shutil.which("wl-paste"):
        print("Clipboard history needs wl-paste (wl-clipboard).", file=sys.stderr)
        return 1
    me = str(Path(__file__).resolve())
    cmd = f'[ -e "{FLAG}" ] && exec python3 "{me}" store || exec cat >/dev/null'
    os.execvp("wl-paste", ["wl-paste", "--watch", "sh", "-c", cmd])


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what == "store":
        sys.exit(store_from_stdin())
    if what == "watch":
        sys.exit(watch())
    if what == "clear":
        clear()
        sys.exit(0)
    print(__doc__)
    sys.exit(2)
