#!/usr/bin/env python3
"""Huginn's own pinentry: the window GnuPG (gpg-agent) opens to ask for a passphrase or a PIN, or for a yes, in
Huginn's look. It replaces pinentry-qt, the last thing in the image that brought KDE's libraries with it.

gpg-agent starts it (/etc/gnupg/gpg-agent.conf: pinentry-program /usr/libexec/huginn-pinentry) and speaks the Assuan
protocol on its standard input and output: SETDESC, SETPROMPT, SETERROR… to describe what's asked, then GETPIN (a
passphrase, typed twice when it asks for a new one with SETREPEAT), CONFIRM or MESSAGE. The window is made only when
it's needed. Without a screen (a text console, ssh) it hands over to pinentry-curses or pinentry-tty.

    huginn_pinentry.py                      (spoken to by gpg-agent)
    huginn_pinentry.py --demo               (the window with made-up words, for looking at it)
The passphrase goes from the box to gpg-agent and nowhere else: never logged, never on a command line."""
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for shell_dir in (HERE.parent / "shell", Path("/usr/share/huginn-shell")):
    if (shell_dir / "huginn_shell.py").exists():
        sys.path.insert(0, str(shell_dir))
        break

CANCELLED = "ERR 83886179 Operation cancelled <Pinentry>"       # GPG_ERR_CANCELED from the pinentry source
NOT_CONFIRMED = "ERR 83886194 Not confirmed <Pinentry>"
UNKNOWN = "ERR 83886355 Unknown IPC command <Pinentry>"


def unescape(text: str) -> str:
    """Assuan's percent escapes (%0A a new line, %25 a percent sign)."""
    out, i = bytearray(), 0
    raw = text.encode("utf-8")
    while i < len(raw):
        pair = raw[i + 1:i + 3]
        if raw[i] == 0x25 and len(pair) == 2 and all(c in b"0123456789abcdefABCDEF" for c in pair):
            out.append(int(raw[i + 1:i + 3], 16))
            i += 3
        else:
            out.append(raw[i])
            i += 1
    return out.decode("utf-8", "replace")


def escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def plain_label(text: str) -> str:
    """A button's words without pinentry's mnemonic marks (_OK; __ is an underscore)."""
    return text.replace("__", "\0").replace("_", "").replace("\0", "_")


class Session:
    """What gpg-agent has said so far, and the answers to its commands. `ask(kind)` shows the window (or, in tests,
    answers from a list) and returns (answer or None when cancelled)."""

    FIELDS = {"SETDESC": "desc", "SETPROMPT": "prompt", "SETTITLE": "title", "SETOK": "ok", "SETCANCEL": "cancel", "SETNOTOK": "notok",
              "SETERROR": "error", "SETREPEATERROR": "repeatError", "SETKEYINFO": "keyinfo"}

    def __init__(self, ask):
        self.ask = ask
        self.reset()

    def reset(self) -> None:
        self.s = {"desc": "", "prompt": "", "title": "", "ok": "", "cancel": "", "notok": "", "error": "", "repeat": None,
                  "repeatError": "", "keyinfo": ""}

    def handle(self, line: str) -> list:
        """One line from gpg-agent; the lines to answer with (the last is OK or ERR)."""
        cmd, _, arg = line.strip().partition(" ")
        cmd = cmd.upper()
        arg = unescape(arg)
        if not cmd or cmd.startswith("#"):
            return []
        if cmd in self.FIELDS:
            self.s[self.FIELDS[cmd]] = plain_label(arg) if cmd in ("SETOK", "SETCANCEL", "SETNOTOK") else arg
            return ["OK"]
        if cmd == "SETREPEAT":
            self.s["repeat"] = arg or "Type it again"
            return ["OK"]
        if cmd in ("OPTION", "SETQUALITYBAR", "SETQUALITYBAR_TT", "SETGENPIN", "SETGENPIN_TT", "SETTIMEOUT", "SETREPEATOK",
                   "CLEARPASSPHRASE", "NOP", "HELP", "SETCONSTRAINTS"):
            return ["OK"]
        if cmd == "RESET":
            self.reset()
            return ["OK"]
        if cmd == "GETINFO":
            info = {"flavor": "huginn", "version": "1.0", "pid": str(os.getpid()), "ttyinfo": "- - -"}.get(arg.strip())
            return ([f"D {escape(info)}"] if info is not None else []) + ["OK"]
        if cmd == "GETPIN":
            pin = self.ask("pin", dict(self.s))
            self.s["error"] = ""
            if pin is None:
                return [CANCELLED]
            return ([f"D {escape(pin)}"] if pin else []) + ["OK"]
        if cmd in ("CONFIRM", "MESSAGE"):
            one = cmd == "MESSAGE" or "--one-button" in arg
            yes = self.ask("message" if one else "confirm", dict(self.s))
            self.s["error"] = ""
            return ["OK"] if (yes or one) else [NOT_CONFIRMED]
        if cmd == "BYE":
            return ["OK closing connection"]
        return [UNKNOWN]


def serve(stdin, stdout, ask) -> int:
    session = Session(ask)
    stdout.write("OK Pleased to meet you\n")
    stdout.flush()
    for line in stdin:
        for out in session.handle(line):
            stdout.write(out + "\n")
        stdout.flush()
        if line.strip().upper().startswith("BYE"):
            break
    return 0


# ------------------------------------------------------------------------------------------------ the window
class Window:
    """The window, made the first time it's needed and kept for the rest of the conversation."""

    def __init__(self, demo: bool = False):
        self.demo = demo
        self.app = self.engine = self.pin = None

    def _make(self) -> None:
        from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine

        class Pin(QObject):
            changed = Signal()
            done = Signal()

            def __init__(self):
                super().__init__()
                self.s, self.kind, self.answer, self.open = {}, "pin", None, False
                self.mismatch = False

            def show(self, kind: str, s: dict) -> None:
                self.kind, self.s, self.answer, self.mismatch, self.open = kind, s, None, False, True
                self.changed.emit()

            title = Property(str, lambda self: self.s.get("title") or ("Passphrase" if self.kind == "pin" else "GnuPG"), notify=changed)
            desc = Property(str, lambda self: self.s.get("desc", ""), notify=changed)
            prompt = Property(str, lambda self: (self.s.get("prompt") or "Passphrase").rstrip(":"), notify=changed)
            error = Property(str, lambda self: "The two aren't the same." if self.mismatch else self.s.get("error", ""), notify=changed)
            repeat = Property(str, lambda self: self.s.get("repeat") or "", notify=changed)
            okText = Property(str, lambda self: self.s.get("ok") or ("OK" if self.kind != "confirm" else "Yes"), notify=changed)
            cancelText = Property(str, lambda self: self.s.get("cancel") or "Cancel", notify=changed)
            kindName = Property(str, lambda self: self.kind, notify=changed)
            active = Property(bool, lambda self: self.open, notify=changed)

            @Slot(str, str)
            def give(self, text: str, again: str) -> None:
                if self.kind == "pin" and self.s.get("repeat") and text != again:
                    self.mismatch = True
                    self.changed.emit()
                    return
                self.answer = text if self.kind == "pin" else True
                self.open = False
                self.changed.emit()
                self.done.emit()

            @Slot()
            def refuse(self) -> None:
                self.answer, self.open = None, False
                self.changed.emit()
                self.done.emit()

        self.app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        self.app.setApplicationName("Passphrase")
        self.app.setDesktopFileName("huginn-pinentry")
        from huginn_shell import make_theme
        _tokens, self.settings, self.theme = make_theme(False, False, "", persist=False, app="pinentry")   # (kept: QML holds no reference)
        self.pin = Pin()
        self.engine = QQmlApplicationEngine()
        for name, obj in (("Theme", self.theme), ("Settings", self.settings), ("Pin", self.pin)):
            self.engine.rootContext().setContextProperty(name, obj)
        self.engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Pinentry.qml")))
        self._keep = (Property, QObject, Signal, Slot)

    def ask(self, kind: str, s: dict):
        from PySide6.QtCore import QEventLoop
        if self.app is None:
            self._make()
        loop = QEventLoop()
        self.pin.done.connect(loop.quit)
        self.pin.show(kind, s)
        loop.exec()
        self.pin.done.disconnect(loop.quit)
        return self.pin.answer


def no_screen() -> bool:
    return not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def main() -> int:
    if "--demo" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", ""))
        w = Window(demo=True)
        got = w.ask("pin", {"desc": "Please enter the passphrase to unlock the OpenPGP secret key:\n\"Astrid Berg <astrid@example.org>\"\n"
                                    "255-bit EDDSA key, ID 0x1F2E3D4C5B6A7980,\ncreated 2026-11-02.", "prompt": "Passphrase:", "title": "Unlock your key"})
        print("answered" if got is not None else "cancelled")
        return 0
    if no_screen():                                              # a text console: the text pinentry, if there is one
        for other in ("pinentry-curses", "pinentry-tty"):
            if shutil.which(other):
                os.execvp(other, [other] + sys.argv[1:])
    return serve(sys.stdin, sys.stdout, Window().ask)


if __name__ == "__main__":
    sys.exit(main())
