#!/usr/bin/env python3
"""Huginn's sign-in service (apps/huginn_signind.py), without being root and without PAM: the service is run for real
in a throwaway folder, with stand-in workers that speak the workers' own protocol and act as a script says.

    signin_test.py <kit root>

What the workers really do (PAM, becoming the person, the screen) is checked by signin_real_check.py, as root, in a
throwaway system.
"""
import json
import os
import socket
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

KIT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT / "apps"))
import huginn_signind as sd  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL", name, detail)


# a worker that does what PLAN/<user> says: "no" (wrong password), "yes" then a session that lasts <seconds>,
# "die" (ends before answering), "nostart" (right password, session can't start). It logs what it's told.
FAKE = textwrap.dedent('''
    import json, os, socket, sys, time
    plan = os.environ["PLAN"]
    chan = socket.socket(fileno=int(sys.argv[1])); f = chan.makefile("rb")
    def send(m): chan.sendall((json.dumps(m) + "\\n").encode())
    job = json.loads(f.readline())
    def log(*a):
        with open(os.path.join(plan, "log"), "a") as fh: fh.write(" ".join(str(x) for x in a) + "\\n")
    log("job", job["class"], job["user"], job["service"], "pw" if job.get("password") is not None else "nopw", " ".join(job["command"]))
    try: what = open(os.path.join(plan, job["user"])).read().split()
    except OSError: what = ["no"]
    if what[0] == "die": sys.exit(3)
    if what[0] == "no" or (job["class"] == "user" and job.get("password") is not None and job["password"] != "right"):
        send({"auth": False, "why": "Wrong password."}); sys.exit(0)
    send({"auth": True, "why": ""})
    if not job.get("go"):
        m = f.readline()
        if not m or not json.loads(m).get("go"): log("cancelled", job["user"]); sys.exit(0)
    if what[0] == "nostart": send({"started": False, "why": "no screen"}); sys.exit(0)
    send({"started": True, "pid": 1}); log("started", job["user"])
    chan.settimeout(float(what[1]) if len(what) > 1 else 0.3)
    try:
        m = f.readline(); log("stopped", job["user"])
    except OSError: pass
    send({"ended": 0}); log("ended", job["user"])
''')


class Bench:
    def __init__(self, auto="", plans=None):
        self.tmp = Path(tempfile.mkdtemp(prefix="signin-"))
        (self.tmp / "etc/huginn/signin.conf.d").mkdir(parents=True)
        (self.tmp / "etc/login.defs").write_text("UID_MIN 1000\nUID_MAX 60000\n")
        (self.tmp / "etc/hostname").write_text("raven\n")
        (self.tmp / "usr/share/wayland-sessions").mkdir(parents=True)
        (self.tmp / "usr/share/wayland-sessions/huginn-game.desktop").write_text("")
        if auto:
            (self.tmp / "etc/huginn/signin.conf.d/20-autologin.conf").write_text(auto)
        self.plan = self.tmp / "plan"
        self.plan.mkdir()
        for user, what in (plans or {}).items():
            (self.plan / user).write_text(what)
        (self.tmp / "fake.py").write_text(FAKE)
        os.environ["PLAN"] = str(self.plan)
        self.clock = [1000.0]
        self.powered = []
        self.svc = sd.Service(root=self.tmp, worker_argv=[sys.executable, str(self.tmp / "fake.py")], run_dir=self.tmp / "run",
                              power=self.powered.append, now=lambda: self.clock[0])
        self.svc.listen()
        self.svc.next()

    def spin(self, seconds=0.6, until=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.svc.step(0.05)
            if until and until():
                return True
        return until() if until else True

    def connect(self):
        c = socket.socket(socket.AF_UNIX)
        c.connect(str(self.tmp / "run/greeter.sock"))
        c.settimeout(3)
        self.spin(0.1)
        return c

    def ask(self, c, msg, wait=3.0):
        c.sendall((json.dumps(msg) + "\n").encode())
        c.setblocking(False)
        buf, end = b"", time.monotonic() + wait
        while time.monotonic() < end and b"\n" not in buf:
            self.svc.step(0.05)
            try:
                buf += c.recv(65536)
            except BlockingIOError:
                pass
        return json.loads(buf.split(b"\n")[0]) if b"\n" in buf else None

    def log(self):
        try:
            return (self.plan / "log").read_text().splitlines()
        except OSError:
            return []

    def close(self):
        self.svc.stop()


# ------------------------------------------------------------------------------------------------- the small pieces
pw = lambda n, u, sh="/bin/bash", g="": SimpleNamespace(pw_name=n, pw_uid=u, pw_gid=u, pw_gecos=g, pw_dir="/home/" + n, pw_shell=sh)  # noqa: E731
everyone = [pw("root", 0), pw("daemon", 1, "/usr/sbin/nologin"), pw("astrid", 1000, g="Astrid Berg,,,"), pw("leif", 1001, "/bin/zsh", "Leif"),
            pw("svc", 1002, "/usr/sbin/nologin"), pw("nobody", 65534, "/usr/sbin/nologin"), pw("hidden", 1003, g="Hidden")]
tmp = Path(tempfile.mkdtemp(prefix="signin-p-"))
(tmp / "var/lib/AccountsService/users").mkdir(parents=True)
(tmp / "var/lib/AccountsService/icons").mkdir(parents=True)
(tmp / "var/lib/AccountsService/users/hidden").write_text("[User]\nSystemAccount=true\n")
(tmp / "var/lib/AccountsService/icons/astrid").write_text("x")
who = sd.people(tmp, everyone)
check("people: only people", [p["name"] for p in who] == ["astrid", "leif"], who)
check("people: full name and face", who[0]["full"] == "Astrid Berg" and who[0]["face"].endswith("icons/astrid") and who[1]["face"] == "")
check("root may not sign in", not sd.may_sign_in(everyone[0], 1000, 60000))
(tmp / "etc/huginn/signin.conf.d").mkdir(parents=True)
check("conf: nothing set", sd.read_conf(tmp) == {"user": "", "session": "huginn", "relogin": False})
(tmp / "etc/huginn/signin.conf.d/20-autologin.conf").write_text("[Autologin]\nUser=astrid\nSession=huginn.desktop\nRelogin=false\n")
check("conf: the installer's file", sd.read_conf(tmp) == {"user": "astrid", "session": "huginn", "relogin": False})
(tmp / "etc/huginn/signin.conf.d/30-x.conf").write_text("[Autologin]\nSession=huginn-game\nRelogin=true\n")
check("conf: later files win, game session", sd.read_conf(tmp) == {"user": "astrid", "session": "game", "relogin": True})
(tmp / "etc/huginn/signin.conf.d/40-bad.conf").write_text("not an ini file \x00\n[Autologin\nSession=/bin/sh\n")
check("conf: a broken file changes nothing", sd.read_conf(tmp)["session"] == "game")
(tmp / "etc/huginn/signin.conf.d/50-odd.conf").write_text("[Autologin]\nSession=/bin/sh\n")
check("conf: an unknown session is Huginn OS", sd.read_conf(tmp)["session"] == "huginn")
sd.save_state(tmp, user="leif", session="game")
check("state: remembered", sd.load_state(tmp) == {"user": "leif", "session": "game"})
(tmp / "var/lib/huginn-signin/state.json").write_text("[1, 2")
check("state: a broken file is empty", sd.load_state(tmp) == {})

t = [0.0]
m = sd.Misses(now=lambda: t[0])
for _ in range(4):
    m.missed("astrid")
check("misses: four wrong, no wait", m.wait("astrid") == 0)
m.missed("astrid")
check("misses: the fifth waits 30 s", m.wait("astrid") == 30, m.wait("astrid"))
check("misses: someone else isn't kept waiting", m.wait("leif") == 0)
t[0] = 29.5
check("misses: still waiting", m.wait("astrid") == 1)
t[0] = 31
check("misses: over", m.wait("astrid") == 0)
m.missed("astrid")
check("misses: the next wait is longer", m.wait("astrid") == 60)
for _ in range(10):
    m.missed("astrid")
check("misses: never more than ten minutes", m.wait("astrid") == 600)
m.right("astrid")
check("misses: a right password clears it", m.wait("astrid") == 0 and "astrid" not in m.count)
check("words", sd.wait_words(1) == "Too many tries. Wait 1 second." and sd.wait_words(30).endswith("30 seconds.") and sd.wait_words(600).endswith("10 minutes."))

# ---------------------------------------------------------------------------------------------- the service: a sign-in
b = Bench(plans={"huginn-greeter": "yes 30", "astrid": "yes 0.6", "leif": "no"})
check("starts the greeter", b.spin(2, lambda: any(line.startswith("started huginn-greeter") for line in b.log())), b.log())
check("the greeter's job", "job greeter huginn-greeter huginn-signin-greeter nopw /usr/libexec/huginn-greeter-session" in b.log(), b.log())
sock_mode = (b.tmp / "run/greeter.sock").stat().st_mode & 0o777
check("the socket is the greeter's alone", sock_mode == 0o600, oct(sock_mode))
c = b.connect()
r = b.ask(c, {"op": "people"})
check("people answered", r and r["op"] == "people" and r["host"] == "raven" and [s["id"] for s in r["sessions"]] == ["huginn", "game"], r)
r = b.ask(c, {"op": "signin", "user": "leif", "password": "nope"})
check("wrong password: no", r == {"op": "signin", "ok": False, "why": "Wrong password.", "wait": 0}, r)
r = b.ask(c, {"op": "signin", "user": "astrid", "password": "wrong"})
check("wrong password for a real person: no", r and r["ok"] is False, r)
check("no session started by a wrong password", not any(line.startswith("started astrid") for line in b.log()))
r = b.ask(c, {"op": "signin", "user": "astrid", "password": "right", "session": "game"})
check("right password: yes", r == {"op": "signin", "ok": True}, r)
check("the session waits for the greeter to leave", not any(line.startswith("started astrid") for line in b.log()), b.log())
r2 = b.ask(c, {"op": "signin", "user": "leif", "password": "right"}, wait=0.6)
check("a second sign-in while one is going through: no", r2 and r2["ok"] is False and "Still" in r2["why"], r2)
b.clock[0] += 13                                             # the greeter outstays its wake
check("a greeter that doesn't leave is closed", b.spin(3, lambda: "stopped huginn-greeter" in b.log()), b.log())
check("then the session starts", b.spin(3, lambda: "started astrid" in b.log()), b.log())
check("with the session asked for", any(line.startswith("job user astrid huginn-signin pw /usr/bin/huginn-session --game") for line in b.log()), b.log())
check("no greeter while someone is signed in", b.svc.greeter is None and b.svc.session is not None)
check("the greeter came back after sign-out", b.spin(4, lambda: b.log().count("started huginn-greeter") == 2), b.log())
check("who signed in last is remembered", sd.load_state(b.tmp) == {"user": "astrid", "session": "game"}, sd.load_state(b.tmp))
c = b.connect()
r = b.ask(c, {"op": "people"})
check("and offered next time", r and r["last"] == "astrid" and r["lastSession"] == "game", r)

# what the greeter may and may not send
for bad in ({"op": "signin", "user": "", "password": "x"}, {"op": "signin", "user": "a\nb", "password": "x"}, {"op": "signin", "user": "astrid"},
            {"op": "signin", "user": ["astrid"], "password": "right"}, {"op": "signin", "user": "astrid", "password": "x\x00y"},
            {"op": "signin", "user": "a" * 300, "password": "x"}):
    r = b.ask(c, bad)
    check("an odd request is a no: " + json.dumps(bad)[:50], r and r["ok"] is False, r)
c.sendall(b"this is not json\n{\"op\": 5}\n[1,2]\n")
b.spin(0.3)
r = b.ask(c, {"op": "people"})
check("rubbish is ignored and the service carries on", r and r["op"] == "people")
r = b.ask(c, {"op": "signin", "user": "astrid", "password": "right", "session": "/bin/sh"})
check("an unknown session is Huginn OS", r and r["ok"] is True)
b.clock[0] += 13
b.spin(3, lambda: b.log().count("started astrid") == 2)
check("…the plain session", b.log()[-3:] and any(line == "job user astrid huginn-signin pw /usr/bin/huginn-session" for line in b.log()), b.log()[-6:])
b.spin(4, lambda: b.log().count("started huginn-greeter") == 3)

# power: from the sign-in screen only
c = b.connect()
b.ask(c, {"op": "power", "what": "restart"}, wait=0.3)
b.ask(c, {"op": "power", "what": "format the disk"}, wait=0.3)
check("power: asked for once, as asked", b.powered == ["restart"], b.powered)
b.close()
check("stopping the service stops the greeter", "stopped huginn-greeter" in b.log()[-3:] or "ended huginn-greeter" in b.log()[-2:], b.log()[-4:])
check("and takes its socket away", not (b.tmp / "run/greeter.sock").exists())

# ------------------------------------------------------------------------------------------------------ waits
b = Bench(plans={"huginn-greeter": "yes 60", "astrid": "yes 0.3"})
b.spin(2, lambda: "started huginn-greeter" in b.log())
c = b.connect()
for i in range(5):
    r = b.ask(c, {"op": "signin", "user": "astrid", "password": "wrong"})
check("the fifth wrong try says to wait", r and r["ok"] is False and r["wait"] == 30 and "Wait 30 seconds" in r["why"], r)
n = len(b.log())
r = b.ask(c, {"op": "signin", "user": "astrid", "password": "right"})
check("while waiting even the right password isn't tried", r and r["ok"] is False and r["wait"] == 30 and len(b.log()) == n, r)
b.clock[0] += 31
r = b.ask(c, {"op": "signin", "user": "astrid", "password": "right"})
check("after the wait the right password works", r == {"op": "signin", "ok": True}, r)
b.close()

# ------------------------------------------------------------------------------------------- things going wrong
b = Bench(plans={"huginn-greeter": "yes 60", "astrid": "die", "leif": "nostart"})
b.spin(2, lambda: "started huginn-greeter" in b.log())
c = b.connect()
r = b.ask(c, {"op": "signin", "user": "astrid", "password": "right"})
check("a worker that dies while checking is a no, never a yes", r and r["ok"] is False and "can't be checked" in r["why"], r)
r = b.ask(c, {"op": "signin", "user": "leif", "password": "right"})
check("(right password)", r and r["ok"] is True, r)
b.clock[0] += 13
check("a session that can't start brings the sign-in screen back", b.spin(5, lambda: b.log().count("started huginn-greeter") == 2), b.log())
check("and nobody is signed in", b.svc.session is None)
b.close()

b = Bench(plans={"huginn-greeter": "die"})
check("a greeter that keeps dying: the service gives up (so the system can fall back)", b.spin(6, lambda: b.svc.ending and b.svc.failed), (b.svc.greeter_fails, b.log()))
check("after four tries", b.log().count("job greeter huginn-greeter huginn-signin-greeter nopw /usr/libexec/huginn-greeter-session") == 4, len(b.log()))
b.close()

# a stranger on the socket
b = Bench(plans={"huginn-greeter": "yes 60"})
b.spin(2, lambda: "started huginn-greeter" in b.log())
b.svc.greeter_uid = os.geteuid() + 12345                    # the greeter is somebody else: we are a stranger
c = socket.socket(socket.AF_UNIX)
c.connect(str(b.tmp / "run/greeter.sock"))
b.spin(0.3)
c.settimeout(1)
try:
    c.sendall(b'{"op": "people"}\n')
    b.spin(0.3)
    got = c.recv(100)
except OSError:
    got = b""
check("anyone but the greeter's account is hung up on", got == b"" or os.geteuid() == 0, got)
b.close()

# --------------------------------------------------------------------------------------------- signing in by itself
auto = "[Autologin]\nUser=astrid\nSession=huginn\nRelogin=false\n"
b = Bench(auto=auto, plans={"huginn-greeter": "yes 60", "astrid": "yes 0.5"})
check("by itself: the session starts with no greeter", b.spin(3, lambda: "started astrid" in b.log()) and "started huginn-greeter" not in b.log(), b.log())
check("by itself: no password, its own PAM service", "job user astrid huginn-signin-autologin nopw /usr/bin/huginn-session" in b.log(), b.log())
b.clock[0] += 60
check("after signing out: the sign-in screen, not straight back in", b.spin(4, lambda: "started huginn-greeter" in b.log()) and b.log().count("started astrid") == 1, b.log())
b.close()

b = Bench(auto=auto.replace("Relogin=false", "Relogin=true"), plans={"huginn-greeter": "yes 60", "astrid": "yes 0.4"})
b.spin(3, lambda: "started astrid" in b.log())
b.clock[0] += 60
check("Relogin: straight back in (the installation drive)", b.spin(4, lambda: b.log().count("started astrid") == 2) and "started huginn-greeter" not in b.log(), b.log())
check("Relogin, but the session ends at once: the sign-in screen", b.spin(5, lambda: "started huginn-greeter" in b.log()), b.log())
b.close()

b = Bench(auto="[Autologin]\nUser=nobody-here\n", plans={"huginn-greeter": "yes 60"})
check("by itself for someone who can't: the sign-in screen", b.spin(5, lambda: "started huginn-greeter" in b.log()), b.log())
b.close()

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
