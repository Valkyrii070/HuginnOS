#!/usr/bin/env python3
"""Huginn's pinentry (apps/huginn_pinentry.py): the Assuan conversation gpg-agent has with it, its window (offscreen),
and a real gpg-agent using it to encrypt and decrypt with a passphrase (the window's answer stood in for by a small
wrapper made here, so nothing in the pinentry itself is there for tests).
Usage: pinentry_test.py <kit root>   (not as root)"""
import io, os, shutil, subprocess, sys, tempfile
from pathlib import Path
KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0:
    sys.exit("not as root")
home = Path(tempfile.mkdtemp(prefix="pinentry-"))
os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "c"), XDG_DATA_HOME=str(home / "d"), QT_QPA_PLATFORM="offscreen")
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
import huginn_pinentry as hp

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
        print("ok  ", name)
    else:
        bad += 1
        print("FAIL", name, extra, flush=True)

check("percent escapes both ways", hp.unescape("line one%0Aline two 100%25 %zz") == "line one\nline two 100% %zz" and hp.escape("a%b\nc") == "a%25b%0Ac")
check("buttons lose pinentry's mnemonic marks", hp.plain_label("_OK") == "OK" and hp.plain_label("Save__as") == "Save_as")
asked = []
def answers(*replies):
    it = iter(replies)
    def ask(kind, s):
        asked.append((kind, s))
        return next(it)
    return ask
def talk(lines, ask):
    out = io.StringIO()
    hp.serve(io.StringIO("".join(l + "\n" for l in lines)), out, ask)
    return out.getvalue().splitlines()
got = talk(["OPTION ttyname=/dev/pts/1", "SETDESC Unlock the key for%0A\"Astrid Berg\"", "SETPROMPT Passphrase:", "SETOK _Unlock", "GETPIN", "BYE"], answers("fjord 100% sky"))
check("greets, answers each line, gives the passphrase escaped", got == ["OK Pleased to meet you", "OK", "OK", "OK", "OK", "D fjord 100%25 sky", "OK", "OK closing connection"], got)
check("…the window was told what to say", asked[-1][0] == "pin" and asked[-1][1]["desc"] == "Unlock the key for\n\"Astrid Berg\"" and asked[-1][1]["ok"] == "Unlock")
got = talk(["GETPIN", "BYE"], answers(None))
check("cancelled: GnuPG's cancelled error", got[1] == hp.CANCELLED)
got = talk(["SETREPEAT Repeat:", "GETPIN"], answers("new-pass"))
check("a new passphrase: the window asks for it twice", asked[-1][1]["repeat"] == "Repeat:" and got[-2:] == ["D new-pass", "OK"])
got = talk(["CONFIRM", "CONFIRM", "MESSAGE", "CONFIRM --one-button"], answers(True, False, True, True))
check("CONFIRM: yes is OK, no is not confirmed; MESSAGE and one button are OK", got[1:] == ["OK", hp.NOT_CONFIRMED, "OK", "OK"] and asked[-2][0] == "message" and asked[-1][0] == "message", got)
got = talk(["GETINFO flavor", "GETINFO pid", "GETINFO nonsense", "FROBNICATE", "SETERROR Bad passphrase", "RESET", "GETPIN"], answers("x"))
check("GETINFO, unknown commands refused, RESET forgets the error", got[1:3] == ["D huginn", "OK"] and got[3].startswith("D ") and got[5] == "OK" and got[6] == hp.UNKNOWN
      and asked[-1][1]["error"] == "", got)
check("no screen: the text pinentry instead", (os.environ.pop("WAYLAND_DISPLAY", None) or True) and (os.environ.pop("DISPLAY", None) or True) and hp.no_screen())

# the window, offscreen: shown with the words, an answer given, a mismatch held
from PySide6.QtCore import QTimer, QObject
w = hp.Window()
w._make()                                    # (the window's Qt first, so the test's timers have a loop to run in)
def answer_later(text, again=""):
    def go():
        root = w.engine.rootObjects()[0]
        texts = [o.property("text") for o in root.findChildren(QObject) if o.objectName() in ("title", "desc")]
        answer_later.seen = texts
        w.pin.give(text, again)
    QTimer.singleShot(300, go)
answer_later("open sesame")
check("the window answers with what was typed", w.ask("pin", {"desc": "Unlock the key", "title": "Unlock your key", "prompt": "Passphrase:"}) == "open sesame")
check("…showing the title and what's asked", "Unlock your key" in answer_later.seen and "Unlock the key" in answer_later.seen, answer_later.seen)
def mismatch_then_match():
    w.pin.give("one", "two")
    answer_later.mismatch = w.pin.property("error")
    QTimer.singleShot(100, lambda: w.pin.give("same", "same"))
QTimer.singleShot(300, mismatch_then_match)
check("a new passphrase typed differently twice: said, and asked again", w.ask("pin", {"repeat": "Repeat:"}) == "same" and answer_later.mismatch == "The two aren't the same.")
QTimer.singleShot(300, w.pin.refuse)
check("Cancel: no answer", w.ask("pin", {}) is None)
QTimer.singleShot(300, lambda: w.pin.give("", ""))
check("a yes for CONFIRM", w.ask("confirm", {"desc": "Allow?"}) is True)

# a real gpg-agent, with the pinentry's own conversation (only the window's answer stood in for)
if shutil.which("gpg") and shutil.which("gpg-agent"):
    gh = home / "gnupg"; gh.mkdir(mode=0o700)
    wrapper = home / "pinentry-under-test"
    wrapper.write_text(f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(KIT / 'apps')!r})\nimport huginn_pinentry as hp\n"
                       f"sys.exit(hp.serve(sys.stdin, sys.stdout, lambda kind, s: 'huginn-test-only' if kind == 'pin' else True))\n")
    wrapper.chmod(0o755)
    (gh / "gpg-agent.conf").write_text(f"pinentry-program {wrapper}\n")
    env = dict(os.environ, GNUPGHOME=str(gh))
    (home / "note.txt").write_text("the fjord at dawn\n")
    enc = subprocess.run(["gpg", "--batch", "--pinentry-mode", "ask", "--symmetric", "--cipher-algo", "AES256", "-o", str(home / "note.gpg"), str(home / "note.txt")],
                         env=env, capture_output=True, text=True, timeout=60)
    subprocess.run(["gpgconf", "--kill", "gpg-agent"], env=env, capture_output=True)
    dec = subprocess.run(["gpg", "--batch", "--pinentry-mode", "ask", "-d", str(home / "note.gpg")], env=env, capture_output=True, text=True, timeout=60)
    check("gpg-agent asks it for a passphrase: encrypted, and decrypted again with it", enc.returncode == 0 and dec.stdout == "the fjord at dawn\n", (enc.stderr[-300:], dec.stderr[-300:]))
    subprocess.run(["gpgconf", "--kill", "gpg-agent"], env=env, capture_output=True)
else:
    print("(no gpg here: the real gpg-agent part is skipped)")
check("gpg-agent is pointed at it in the image", "pinentry-program /usr/libexec/huginn-pinentry" in (KIT / "config/overlay/etc/gnupg/gpg-agent.conf").read_text())
print(f"\n{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
