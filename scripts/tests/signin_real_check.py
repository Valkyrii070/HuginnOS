#!/usr/bin/env python3
"""Huginn's sign-in workers against the real thing: real PAM, real accounts, really becoming the person.

    signin_real_check.py <kit root>          AS ROOT, in a throwaway system only (it makes and removes two accounts
                                             and installs the kit's PAM files into /etc/pam.d)

It refuses to run unless SIGNIN_REAL_AS_ROOT=1 says the system is one to throw away. What it can't see from here:
logind and the screen (there's no systemd or terminal in a build root); those need a started computer.
"""
import json
import os
import pwd
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

if os.geteuid() != 0 or os.environ.get("SIGNIN_REAL_AS_ROOT") != "1":
    sys.exit("only as root in a throwaway system, with SIGNIN_REAL_AS_ROOT=1")
KIT = Path(sys.argv[1]).resolve()
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL", name, detail)


def sh(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, **k)


PERSON, OTHER = "signin-check", "signin-nologin"
secret = secrets.token_urlsafe(12)
for f in ("huginn-signin", "huginn-signin-greeter", "huginn-signin-autologin"):
    shutil.copy(KIT / "config/overlay/etc/pam.d" / f, "/etc/pam.d/" + f)
for u in (PERSON, OTHER):
    sh("userdel", "-r", u)
sh("useradd", "-m", "-s", "/bin/bash", "-c", "Sign-in Check,,,", PERSON)
sh("useradd", "-m", "-s", "/usr/sbin/nologin", OTHER)
sh("chpasswd", input=f"{PERSON}:{secret}\n{OTHER}:{secret}\n")
made_greeter = False
try:
    pwd.getpwnam("huginn-greeter")
except KeyError:
    r = sh("systemd-sysusers", str(KIT / "config/overlay/usr/lib/sysusers.d/huginn-signin.conf"))
    made_greeter = True
    check("the greeter's account can be made from the kit's file", r.returncode == 0, r.stderr)
try:
    g = pwd.getpwnam("huginn-greeter")
    check("the greeter's account: no shell to sign in with, a home of its own", g.pw_shell.endswith("nologin") and g.pw_dir == "/var/lib/huginn-greeter", g)
    os.makedirs(g.pw_dir, exist_ok=True)
    os.chown(g.pw_dir, g.pw_uid, g.pw_gid)
except KeyError:
    g = None
    check("the greeter's account exists", False)

out = Path("/tmp/signin-real")
shutil.rmtree(out, ignore_errors=True)
out.mkdir()
os.chmod(out, 0o1777)                                          # noqa: S103  (a scratch folder each test account writes to)
probe = out / "probe.sh"
probe.write_text('#!/bin/sh\n{ id -un; id -Gn; pwd; echo "$HOME|$USER|$LOGNAME|$SHELL|$XDG_SESSION_CLASS|$XDG_SESSION_TYPE|$XDG_SEAT|$XDG_VTNR|$EXTRA"; echo "$0"; '
                 'ls /proc/$$/fd | tr "\\n" " "; echo; umask; } > /tmp/signin-real/$(id -un).out 2>&1\necho to-the-log >&2\nsleep ${1:-0}\n')
probe.chmod(0o755)


class W:
    def __init__(self, job):
        ours, theirs = socket.socketpair()
        self.p = subprocess.Popen([sys.executable, "-I", str(KIT / "apps/huginn_signind.py"), "--worker", str(theirs.fileno())], pass_fds=[theirs.fileno()])
        theirs.close()
        self.s, self.f = ours, ours.makefile("rb")
        self.send(job)

    def send(self, m):
        self.s.sendall((json.dumps(m) + "\n").encode())

    def get(self, timeout=30):
        self.s.settimeout(timeout)
        try:
            line = self.f.readline()
        except OSError:
            return None
        return json.loads(line) if line else None


def job(user, password, cls="user", service="huginn-signin", go=False, args=(), env=None):
    return {"class": cls, "service": service, "user": user, "password": password, "command": [str(probe), *args], "vt": 63, "go": go, "env": env or {}}


# wrong, unknown, and accounts that may not
t = time.monotonic()
w = W(job(PERSON, "not-it"))
r = w.get()
check("a wrong password is a no", r and r["auth"] is False and r["why"] == "Wrong password.", r)
check("and takes a moment (PAM's own wait)", time.monotonic() - t > 1.0, time.monotonic() - t)
check("the worker ends", w.p.wait(10) == 0)
check("nothing was started", not (out / f"{PERSON}.out").exists())
t = time.monotonic()
w = W(job("nobody-called-this", secret))
r = w.get()
check("an unknown name is the same no, as slowly", r and r["auth"] is False and r["why"] == "Wrong password." and time.monotonic() - t > 1.8, (r, time.monotonic() - t))
w = W(job("root", secret))
r = w.get()
check("root can't sign in here", r and r["auth"] is False, r)
w = W(job(OTHER, secret))
r = w.get()
check("an account with no shell can't, even with its password", r and r["auth"] is False, r)
w = W(job("daemon", ""))
r = w.get()
check("a service account can't", r and r["auth"] is False, r)
w = W(job(PERSON, ""))
r = w.get()
check("an empty password is a no", r and r["auth"] is False, r)

# right, but cancelled
w = W(job(PERSON, secret))
r = w.get()
check("the right password is a yes", r == {"auth": True, "why": ""}, r)
check("nothing starts until told to", w.get(1.0) is None and not (out / f"{PERSON}.out").exists())
w.s.shutdown(socket.SHUT_RDWR)
check("the service going away cancels it", w.p.wait(10) == 0 and not (out / f"{PERSON}.out").exists())

# right, and through to a session
w = W(job(PERSON, secret, env={"EXTRA": "given"}))
r = w.get()
w.send({"go": True})
r = w.get()
check("the session starts", r and r.get("started") is True, r)
r = w.get()
check("and ends with its own exit code", r == {"ended": 0}, r)
w.p.wait(10)
got = (out / f"{PERSON}.out").read_text().splitlines() if (out / f"{PERSON}.out").exists() else []
p = pwd.getpwnam(PERSON)
check("it ran as the person", got[:1] == [PERSON], got)
check("in their groups only", len(got) > 1 and got[1].split() == [PERSON], got[1:2])
check("in their home", got[2:3] == [p.pw_dir], got[2:3])
check("with their environment", len(got) > 3 and got[3] == f"{p.pw_dir}|{PERSON}|{PERSON}|/bin/bash|user|wayland|seat0|63|given", got[3:4])
check("the session command itself is what runs (the shell is replaced by it)", got[4:5] == [str(probe)], got[4:5])
check("with nothing of the service's left open", len(got) > 5 and set(got[5].split()) <= {"0", "1", "2", "3", "10", "11", "12", "255"}, got[5:6])
check("umask 022", got[6:7] == ["0022"], got[6:7])
st = os.stat(out / f"{PERSON}.out")
check("what it wrote is theirs", st.st_uid == p.pw_uid and st.st_gid == p.pw_gid)
log = Path(p.pw_dir) / ".local/share/huginn/session.log"
check("its messages are in the person's session log", log.exists() and "to-the-log" in log.read_text() and log.stat().st_uid == p.pw_uid and log.stat().st_mode & 0o777 == 0o600,
      log.exists() and log.read_text())

# the log before it is kept; stop ends a session
w = W(job(PERSON, secret, args=("30",)))
w.get()
w.send({"go": True})
r = w.get()
check("(a long session started)", r and r.get("started") is True, r)
time.sleep(0.6)
check("the earlier log is kept beside the new one", (log.parent / "session.log.1").exists() and "to-the-log" in (log.parent / "session.log.1").read_text())
t = time.monotonic()
w.send({"stop": True})
r = w.get(20)
check("stop ends the session", r is not None and "ended" in r and time.monotonic() - t < 6, (r, time.monotonic() - t))
w.p.wait(10)
left = [x for x in sh("pgrep", "-u", PERSON, "-a").stdout.splitlines() if "<defunct>" not in x]   # (no init in a build root to bury the dead)
check("and leaves nothing of theirs running", left == [], left)

# by itself, and the greeter
w = W(job(PERSON, None, service="huginn-signin-autologin", go=True))
r = w.get()
check("signing in by itself: no password asked", r == {"auth": True, "why": ""}, r)
r = w.get()
check("…and it starts", r and r.get("started") is True, r)
w.get()
w.p.wait(10)
w = W(job("root", None, service="huginn-signin-autologin", go=True))
r = w.get()
check("signing in by itself as root: no", r and r["auth"] is False, r)
if g:
    w = W(job("huginn-greeter", None, cls="greeter", service="huginn-signin-greeter", go=True, env={"EXTRA": "sock"}))
    r = w.get()
    check("the greeter needs no password", r == {"auth": True, "why": ""}, r)
    r = w.get()
    check("the greeter's session starts", r and r.get("started") is True, r)
    w.get()
    w.p.wait(10)
    got = (out / "huginn-greeter.out").read_text().splitlines() if (out / "huginn-greeter.out").exists() else []
    check("as the greeter's account, in its own home", got[:1] == ["huginn-greeter"] and got[2:3] == ["/var/lib/huginn-greeter"], got[:3])
    check("with only the groups it needs", len(got) > 1 and set(got[1].split()) <= {"huginn-greeter", "video", "render"}, got[1:2])
    check("as a greeter's kind of session, with the way to the service", len(got) > 3 and got[3].split("|")[4:] == ["greeter", "wayland", "seat0", "63", "sock"], got[3:4])
    check("its messages are in its own log", Path("/var/lib/huginn-greeter/.local/share/huginn/greeter.log").exists())
    w = W(job("huginn-greeter", secret))
    r = w.get()
    check("nobody can sign in AS the greeter's account", r and r["auth"] is False, r)

# ---------------------------------------------------------------------------------- sign-in widgets, read as them
sys.path.insert(0, str(KIT / "apps"))
import huginn_signind as sd  # noqa: E402
import huginn_signin_widgets as sw  # noqa: E402
home = Path(p.pw_dir)


def as_them(path: Path, text: str, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.chmod(path, mode)
    for q in (path, *[x for x in path.parents if str(x).startswith(str(home)) and x != home]):
        os.chown(q, p.pw_uid, p.pw_gid)


as_them(sw.layout_path(home), json.dumps({"widgets": [{"kind": "today", "size": "wide", "before": False}, {"kind": "weather", "size": "small", "before": True}]}))
as_them(sw.snapshot_path(home), json.dumps({"data": {"today": {"events": [{"title": "Private thing", "date": "2026-11-27", "time": "10:30"}]},
                                                     "weather": {"place": "Reykjavík", "temp": "4°", "words": "Clear", "at": 1}}}), 0o600)
got = sd.widgets_of(PERSON, {})
check("their widgets, read as them", [(w["kind"], w["private"]) for w in got] == [("today", True), ("weather", False)], got)
check("the private one carries nothing; the other its weather", got[0]["data"] == {} and got[1]["data"].get("temp") == "4°", got)
snap = sw.snapshot_path(home)
snap.unlink()
os.symlink("/etc/shadow", snap)
os.lchown(snap, p.pw_uid, p.pw_gid)
got = sd.widgets_of(PERSON, {})
check("a link from their snapshot to /etc/shadow: nothing of it is read", got and got[1]["data"] == {} and "root:" not in json.dumps(got), got)
raw = sd.read_as(p, ["/etc/shadow", str(sw.layout_path(home))])
check("reading as them: /etc/shadow can't be read, their own file can", raw[0] == "" and "today" in raw[1], [r[:30] for r in raw])
snap.unlink()
as_them(snap, json.dumps({"data": {"weather": {"temp": "5°", "at": 1}}}), 0o600)
os.chown(snap, 0, 0)                                           # root's file in their folder, theirs to see no longer
os.chmod(snap, 0o600)
got = sd.widgets_of(PERSON, {})
check("a file in their folder that they can't read stays unread", got and got[1]["data"] == {}, got)
as_them(sw.layout_path(home), "x" * (300 * 1024))
check("a layout file far too big is no widgets", sd.widgets_of(PERSON, {}) == [])
check("someone with no layout has no widgets", sd.widgets_of(OTHER, {}) == [] and sd.widgets_of("nobody-called-this", {}) == [])

for u in (PERSON, OTHER):
    sh("pkill", "-KILL", "-u", u)
    sh("userdel", "-r", u)
if made_greeter:
    sh("userdel", "huginn-greeter")
    shutil.rmtree("/var/lib/huginn-greeter", ignore_errors=True)
shutil.rmtree(out, ignore_errors=True)
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
