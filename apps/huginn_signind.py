#!/usr/bin/env python3
"""Huginn's sign-in service: what stands between the computer starting and somebody's desktop.

It runs as root from huginn-signin.service (the system's display-manager.service), owns the first screen (VT 1), and
does three things and nothing else:

  * shows the sign-in screen: Huginn's own greeter (shell/huginn_greeter.py under huginn-compositor), as the
    `huginn-greeter` account, which can do nothing but draw and ask this service;
  * checks a password when the greeter asks, through PAM (/etc/pam.d/huginn-signin), with a wait that grows after
    wrong tries;
  * starts that person's session (/usr/bin/huginn-session) as them, registered with logind, and when it ends shows
    the sign-in screen again.

The greeter never sees a password checked and never becomes anyone: it sends a name and a password down a socket only
its account can open, and is told yes or no. On yes it plays the wake and leaves; the session starts on the same
screen once it has gone.

Each sign-in is done by a worker process of its own (this file with --worker): PAM's modules run there, so one that
crashes or hangs takes a worker down, not the service. The worker keeps the PAM session open for as long as the
person is signed in and closes it when their session ends.

    /etc/huginn/signin.conf.d/*.conf     [Autologin] User= Session= Relogin=   (the installer and Settings write it)
    /var/lib/huginn-signin/state.json    who signed in last
    /run/huginn-signin/greeter.sock      the greeter's way in (owned by huginn-greeter, mode 600)

Messages are one JSON object per line. From the greeter: {"op": "people"}, {"op": "signin", "user", "password",
"session"}, {"op": "power", "what": "sleep" | "restart" | "off"}.

    huginn_signind.py                 the service (root)
    huginn_signind.py --worker FD     one sign-in (started by the service)
    huginn_signind.py --people        prints who the sign-in screen would list (anyone may ask)
"""
import configparser
import fcntl
import json
import os
import pwd
import selectors
import signal
import socket
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

GREETER_USER = "huginn-greeter"
GREETER_COMMAND = ["/usr/libexec/huginn-greeter-session"]
SESSIONS = {"huginn": ("Huginn OS", ["/usr/bin/huginn-session"]), "game": ("Game Mode", ["/usr/bin/huginn-session", "--game"])}
VT = 1
SHELLS_THAT_READ_A_PROFILE = ("sh", "bash", "dash", "zsh", "ksh")
NO_SIGN_IN_SHELLS = ("nologin", "false", "sync", "halt", "shutdown")
PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin"
TRIES_BEFORE_WAITING = 5          # wrong passwords in a row for one name before a wait
FIRST_WAIT, LONGEST_WAIT = 30, 600
GREETER_LEAVES_WITHIN = 8.0       # after a right password: its wake, then it must be gone
GREETER_QUICK, GREETER_GIVES_UP = 20.0, 4   # a greeter that ends this soon, this many times running: something's broken
AUTOLOGIN_QUICK = 10.0            # a by-itself sign-in that ends this soon isn't tried again
WRONG = "Wrong password."


def say(*a) -> None:
    print("huginn-signin:", *a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------------------------------- what's on disk
def uid_range(root: Path = Path("/")) -> tuple:
    """The uids of people (not services), from login.defs."""
    lo, hi = 1000, 60000
    try:
        for line in (root / "etc/login.defs").read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                if parts[0] == "UID_MIN":
                    lo = int(parts[1])
                elif parts[0] == "UID_MAX":
                    hi = int(parts[1])
    except OSError:
        pass
    return lo, hi


def may_sign_in(pw, lo: int, hi: int) -> bool:
    """A person's account: an ordinary uid and a shell that is one. (Never root: the sign-in screen is for people.)"""
    return lo <= pw.pw_uid <= hi and os.path.basename(pw.pw_shell or "") not in NO_SIGN_IN_SHELLS


def people(root: Path = Path("/"), everyone=None) -> list:
    """Who the sign-in screen lists: [{name, full, face}], by name. AccountsService's hidden accounts are left out."""
    lo, hi = uid_range(root)
    out = []
    for pw in (everyone if everyone is not None else pwd.getpwall()):
        if not may_sign_in(pw, lo, hi):
            continue
        acc = root / "var/lib/AccountsService/users" / pw.pw_name
        try:
            if "SystemAccount=true" in acc.read_text(encoding="utf-8", errors="replace"):
                continue
        except OSError:
            pass
        face = root / "var/lib/AccountsService/icons" / pw.pw_name
        out.append({"name": pw.pw_name, "full": (pw.pw_gecos or "").split(",")[0] or pw.pw_name,
                    "face": str(face) if face.is_file() else ""})
    return sorted(out, key=lambda p: p["full"].lower())


def read_conf(root: Path = Path("/")) -> dict:
    """{user, session, relogin} from /etc/huginn/signin.conf and signin.conf.d/*.conf (later files win)."""
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    files = [root / "etc/huginn/signin.conf"] + sorted((root / "etc/huginn/signin.conf.d").glob("*.conf"))
    for f in files:
        try:
            cp.read_string(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, configparser.Error):
            continue
    auto = cp["Autologin"] if cp.has_section("Autologin") else {}
    session = (auto.get("Session", "") or "huginn").strip().removesuffix(".desktop")
    session = {"huginn-game": "game"}.get(session, session)
    return {"user": auto.get("User", "").strip(), "session": session if session in SESSIONS else "huginn",
            "relogin": auto.get("Relogin", "false").strip().lower() == "true"}


def look_realm(root: Path = Path("/")) -> str:
    """Which realm the sign-in screen wears: [Look] Realm= in the same files (Settings › Appearance writes
    signin.conf.d/10-look.conf through huginn-login-look), aurora when nothing says."""
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    for f in [root / "etc/huginn/signin.conf"] + sorted((root / "etc/huginn/signin.conf.d").glob("*.conf")):
        try:
            cp.read_string(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, configparser.Error):
            continue
    realm = cp.get("Look", "Realm", fallback="aurora").strip().lower()
    return realm if realm in ("aurora", "bifrost", "muspelheim", "niflheim") else "aurora"


def sessions(root: Path = Path("/")) -> list:
    """The sessions there are to choose from: Huginn OS always, Game Mode when its entry is installed."""
    out = [{"id": "huginn", "name": SESSIONS["huginn"][0]}]
    if (root / "usr/share/wayland-sessions/huginn-game.desktop").exists():
        out.append({"id": "game", "name": SESSIONS["game"][0]})
    return out


def load_state(root: Path) -> dict:
    try:
        d = json.loads((root / "var/lib/huginn-signin/state.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(root: Path, **changes) -> None:
    d = {**load_state(root), **changes}
    where = root / "var/lib/huginn-signin"
    try:
        where.mkdir(parents=True, exist_ok=True)
        tmp = where / ".state.json.new"
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, where / "state.json")
    except OSError as err:
        say("can't remember who signed in:", err)


# ------------------------------------------------------------------------------------------------- waits after misses
class Misses:
    """Wrong passwords per name: after TRIES_BEFORE_WAITING in a row, a wait that doubles each time (30 s … 10 min).
    Kept in memory: it starts fresh when the computer does, as a person at the keyboard would expect."""

    def __init__(self, now=time.monotonic):
        self.now, self.count, self.until = now, {}, {}

    def wait(self, user: str) -> int:
        """Seconds until this name may be tried again (0: now)."""
        return max(0, int(self.until.get(user, 0) - self.now() + 0.999))

    def missed(self, user: str) -> None:
        if len(self.count) > 500 and user not in self.count:        # names nobody has: don't keep them for ever
            self.count.clear()
            self.until.clear()
        n = self.count[user] = self.count.get(user, 0) + 1
        if n >= TRIES_BEFORE_WAITING:
            self.until[user] = self.now() + min(LONGEST_WAIT, FIRST_WAIT * 2 ** (n - TRIES_BEFORE_WAITING))

    def right(self, user: str) -> None:
        self.count.pop(user, None)
        self.until.pop(user, None)


def wait_words(seconds: int) -> str:
    if seconds >= 90:
        return f"Too many tries. Wait {round(seconds / 60)} minutes."
    return f"Too many tries. Wait {seconds} second{'' if seconds == 1 else 's'}."


# ------------------------------------------------------------------------------------------------------ the service
class Line:
    """A socket that speaks one JSON object per line."""

    def __init__(self, sock: socket.socket):
        self.sock, self.buf, self.gone = sock, b"", False
        sock.setblocking(False)

    def fileno(self) -> int:
        return self.sock.fileno()

    def read(self) -> list:
        """Every whole message that has arrived; sets `gone` when the other end has closed."""
        try:
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    self.gone = True
                    break
                self.buf += chunk
                if len(self.buf) > 1 << 20:                         # nothing honest sends a megabyte
                    self.gone, self.buf = True, b""
                    break
        except BlockingIOError:
            pass
        except OSError:
            self.gone = True
        out = []
        while b"\n" in self.buf:
            raw, self.buf = self.buf.split(b"\n", 1)
            try:
                msg = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(msg, dict):
                out.append(msg)
        return out

    def send(self, msg: dict) -> None:
        try:
            self.sock.setblocking(True)
            self.sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        except OSError:
            self.gone = True
        finally:
            try:
                self.sock.setblocking(False)
            except OSError:
                pass

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class Worker(Line):
    """One sign-in's worker process, from the service's side."""

    def __init__(self, argv: list, job: dict):
        ours, theirs = socket.socketpair()
        self.proc = subprocess.Popen(argv + [str(theirs.fileno())], pass_fds=[theirs.fileno()], stdin=subprocess.DEVNULL)
        theirs.close()
        super().__init__(ours)
        self.user, self.kind, self.asked_by, self.started_at = job["user"], job["class"], None, time.monotonic()
        self.session = job.get("session", "")
        self.auto = False
        self.send(job)

    def stop(self) -> None:
        self.send({"stop": True})

    def kill(self) -> None:
        try:
            self.proc.terminate()
        except OSError:
            pass


class Service:
    def __init__(self, root: Path = Path("/"), worker_argv=None, run_dir=None, power=None, now=time.monotonic):
        self.root = root
        self.worker_argv = worker_argv or [sys.executable, "-I", os.path.abspath(__file__), "--worker"]
        self.run_dir = Path(run_dir) if run_dir else root / "run/huginn-signin"
        self.power = power or self._power
        self.now = now
        self.misses = Misses(now)
        self.sel = selectors.DefaultSelector()
        self.clients, self.greeter, self.checking, self.pending, self.session = [], None, None, None, None
        self.pending_since = 0.0
        self.greeter_fails, self.autologin_done, self.ending = 0, False, False
        self.server = None

    # .................................................................................................. setting up
    def listen(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.run_dir, 0o755)                              # noqa: S103  (a folder anyone may look in; the socket in it is the greeter's alone)
        path = self.run_dir / "greeter.sock"
        try:
            path.unlink()
        except OSError:
            pass
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            self.server.bind(str(path))
        finally:
            os.umask(old)
        try:
            self.greeter_uid = pwd.getpwnam(GREETER_USER).pw_uid
        except KeyError:
            self.greeter_uid = os.geteuid()                         # (a test, or a system without the account: us)
        if os.geteuid() == 0:
            os.chown(path, self.greeter_uid, 0)
        self.server.listen(4)
        self.server.setblocking(False)
        self.sel.register(self.server, selectors.EVENT_READ, "server")

    def _allowed(self, conn: socket.socket) -> bool:
        """Only the greeter's account (or root) may talk to the service, whatever the file's permissions say."""
        try:
            _pid, uid, _gid = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        except OSError:
            return False
        return uid in (0, self.greeter_uid)

    # ................................................................................................ starting things
    def _spawn(self, job: dict) -> Worker:
        w = Worker(self.worker_argv, job)
        w.started_at = self.now()
        self.sel.register(w, selectors.EVENT_READ, "worker")
        return w

    def start_greeter(self) -> None:
        self.greeter = self._spawn({"class": "greeter", "service": "huginn-signin-greeter", "user": GREETER_USER, "password": None,
                                    "command": GREETER_COMMAND, "vt": VT, "go": True,
                                    "env": {"HUGINN_SIGNIN_SOCK": str(self.run_dir / "greeter.sock")}})

    def start_autologin(self, conf: dict) -> None:
        say("signing", conf["user"], "in by itself")
        self.session = self._spawn({"class": "user", "service": "huginn-signin-autologin", "user": conf["user"], "password": None,
                                    "command": SESSIONS[conf["session"]][1], "session": conf["session"], "vt": VT, "go": True, "env": {}})
        self.session.auto = True

    def next(self) -> None:
        """Nobody is signed in and no sign-in screen is up: put up whichever comes next."""
        if self.ending or self.greeter or self.session or self.pending:
            return
        conf = read_conf(self.root)
        if conf["user"] and not self.autologin_broken and (not self.autologin_done or conf["relogin"]):
            self.autologin_done = True
            self.start_autologin(conf)
        else:
            self.start_greeter()

    # ................................................................................................... the greeter asks
    def _people(self) -> dict:
        last = load_state(self.root)
        who = people(self.root)
        try:
            host = (self.root / "etc/hostname").read_text(encoding="utf-8").strip()
        except OSError:
            host = ""
        return {"op": "people", "people": who, "last": last.get("user", ""), "lastSession": last.get("session", "huginn"),
                "sessions": sessions(self.root), "host": host}

    def _signin(self, client: Line, msg: dict) -> None:
        user, password, session = msg.get("user"), msg.get("password"), msg.get("session") or "huginn"
        if not isinstance(user, str) or not isinstance(password, str) or not user or len(user) > 256 or len(password) > 4096 \
                or "\n" in user or "\x00" in user or "\x00" in password:
            client.send({"op": "signin", "ok": False, "why": WRONG})
            return
        if self.checking or self.pending or self.session:
            client.send({"op": "signin", "ok": False, "why": "Still working on the last try."})
            return
        wait = self.misses.wait(user)
        if wait:
            client.send({"op": "signin", "ok": False, "why": wait_words(wait), "wait": wait})
            return
        if session not in SESSIONS:
            session = "huginn"
        self.checking = self._spawn({"class": "user", "service": "huginn-signin", "user": user, "password": password,
                                     "command": SESSIONS[session][1], "session": session, "vt": VT, "go": False, "env": {}})
        self.checking.asked_by = client

    def _power(self, what: str) -> None:
        verb = {"sleep": "suspend", "restart": "reboot", "off": "poweroff"}[what]
        subprocess.Popen(["systemctl", verb], stdin=subprocess.DEVNULL)

    def on_client(self, client: Line) -> None:
        for msg in client.read():
            op = msg.get("op")
            if op == "people":
                client.send(self._people())
            elif op == "signin":
                self._signin(client, msg)
            elif op == "power" and msg.get("what") in ("sleep", "restart", "off"):
                # (only from the sign-in screen, where nobody's work is open: a session asks logind itself)
                if not self.session:
                    say("the sign-in screen asked to", msg["what"])
                    self.power(msg["what"])
        if client.gone:
            self.drop(client)

    def drop(self, line: Line) -> None:
        try:
            self.sel.unregister(line)
        except (KeyError, ValueError):
            pass
        line.close()
        if line in self.clients:
            self.clients.remove(line)

    # ....................................................................................................... the workers say
    def on_worker(self, w: Worker) -> None:
        for msg in w.read():
            if "auth" in msg and w is self.checking:
                self.checking = None
                asker = w.asked_by
                if msg["auth"]:
                    self.misses.right(w.user)
                    self.pending, self.pending_since = w, self.now()
                    if asker and not asker.gone:
                        asker.send({"op": "signin", "ok": True})
                    if not self.greeter:                               # (the greeter already went: don't wait for it)
                        self._go()
                else:
                    self.misses.missed(w.user)
                    wait = self.misses.wait(w.user)
                    why = msg.get("why") or WRONG
                    if asker and not asker.gone:
                        asker.send({"op": "signin", "ok": False, "why": wait_words(wait) if wait else why, "wait": wait})
            elif "started" in msg:
                if w is self.session and msg["started"]:
                    say(w.user, "is signed in" if w.kind == "user" else "(the sign-in screen) is up")
                elif not msg["started"]:
                    say("couldn't start", "the sign-in screen:" if w.kind == "greeter" else f"{w.user}'s session:", msg.get("why", ""))
        if w.gone or w.proc.poll() is not None:
            self._ended(w)

    def _go(self) -> None:
        """The greeter has left the screen: the person whose password was right gets it."""
        w, self.pending = self.pending, None
        if w is None:
            return
        self.session = w
        w.send({"go": True})

    def _ended(self, w: Worker) -> None:
        for m in w.read():                                             # (anything it said on its way out)
            if m.get("started") is False:
                say("couldn't start", w.user + ":", m.get("why", ""))
        self.drop(w)
        try:
            w.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            w.kill()
        if w is self.checking:                                         # died while checking: say no, never yes
            self.checking = None
            if w.asked_by and not w.asked_by.gone:
                w.asked_by.send({"op": "signin", "ok": False, "why": "The password can't be checked right now."})
        elif w is self.pending:
            self.pending = None
        elif w is self.greeter:
            self.greeter = None
            for c in list(self.clients):                               # its connections go with it
                self.drop(c)
            if self.pending:
                self.greeter_fails = 0
                self._go()
                return
            quick = self.now() - w.started_at < GREETER_QUICK
            self.greeter_fails = self.greeter_fails + 1 if quick else 0
            if self.greeter_fails >= GREETER_GIVES_UP:
                say("the sign-in screen keeps stopping: giving up, so the system can fall back to something that works")
                self.ending = True
                self.failed = True
                return
        elif w is self.session:
            self.session = None
            if w.kind == "user":
                say(w.user, "signed out")
                if w.auto and self.now() - w.started_at < AUTOLOGIN_QUICK:
                    say("signing in by itself ended at once: showing the sign-in screen instead")
                    self.autologin_broken = True
                save_state(self.root, user=w.user, session=w.session or "huginn")
        self.next()

    # ......................................................................................................... running
    failed = False
    autologin_broken = False

    def tick(self) -> None:
        """Things that depend on time passing."""
        if self.pending and self.greeter and self.now() - self.pending_since > GREETER_LEAVES_WITHIN:
            say("the sign-in screen didn't leave after a right password: closing it")
            self.greeter.stop()
            self.pending_since = self.now() + 3600                     # (once)

    def step(self, timeout: float = 0.5) -> None:
        for key, _ in self.sel.select(timeout):
            if key.data == "server":
                try:
                    conn, _ = self.server.accept()
                except OSError:
                    continue
                if not self._allowed(conn) or len(self.clients) >= 8:
                    conn.close()
                    continue
                line = Line(conn)
                self.clients.append(line)
                self.sel.register(line, selectors.EVENT_READ, "client")
            elif key.data == "client":
                self.on_client(key.fileobj)
            elif key.data == "worker":
                self.on_worker(key.fileobj)
        for w in (self.greeter, self.checking, self.pending, self.session):   # one that died without a word
            if w and w.proc.poll() is not None:
                self.on_worker(w)
        self.tick()

    def stop(self) -> None:
        """Ending the service ends what it started: the sign-in screen, and a session if there is one."""
        self.ending = True
        ws = [w for w in (self.greeter, self.checking, self.pending, self.session) if w]
        for w in ws:
            w.stop()
        until = time.monotonic() + 12
        for w in ws:
            try:
                w.proc.wait(timeout=max(0.1, until - time.monotonic()))
            except subprocess.TimeoutExpired:
                w.kill()
        if self.server:
            self.server.close()
            try:
                (self.run_dir / "greeter.sock").unlink()
            except OSError:
                pass

    def run(self) -> int:
        self.listen()
        self.next()
        while not self.ending:
            self.step()
        self.stop()
        return 1 if self.failed else 0


# ----------------------------------------------------------------------------------------------------------- a worker
KDSETMODE, KD_TEXT, VT_ACTIVATE, VT_WAITACTIVE = 0x4B3A, 0, 0x5606, 0x5607


def take_screen(vt: int) -> int:
    """Opens the screen's terminal and brings it to the front; returns its fd (or -1: no such terminal, as in a test)."""
    try:
        fd = os.open(f"/dev/tty{vt}", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return -1
    for req, arg in ((KDSETMODE, KD_TEXT), (VT_ACTIVATE, vt), (VT_WAITACTIVE, vt)):
        try:
            fcntl.ioctl(fd, req, arg)
        except OSError:
            pass
    return fd


def session_log(home: str, kind: str) -> int:
    """Where the session's own messages go (problem reports read it): ~/.local/share/huginn/session.log, the one
    before it kept as session.log.1. Opened as the person."""
    where = Path(home) / ".local/share/huginn"
    name = "greeter.log" if kind == "greeter" else "session.log"
    try:
        where.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(where / name, where / (name + ".1"))
        except OSError:
            pass
        return os.open(where / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    except OSError:
        return os.open(os.devnull, os.O_WRONLY)


def become(pw, tty: int, env: dict, command: list, kind: str) -> None:
    """In the child: this process becomes the person and then their session. Never returns."""
    try:
        os.setsid()
        if tty >= 0:
            try:
                fcntl.ioctl(tty, termios.TIOCSCTTY, 1)
            except OSError:
                pass
            os.dup2(tty, 0)
        else:
            os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGPIPE, signal.SIGCHLD):
            signal.signal(sig, signal.SIG_DFL)
        os.initgroups(pw.pw_name, pw.pw_gid)
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
        if os.getuid() != pw.pw_uid or os.geteuid() != pw.pw_uid or (pw.pw_uid != 0 and os.getgid() != pw.pw_gid):
            os._exit(126)                                             # not who it should be: start nothing
        os.umask(0o022)
        try:
            os.chdir(pw.pw_dir)
        except OSError:
            os.chdir("/")
        log = session_log(pw.pw_dir, kind)
        os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
        os.dup2(log, 2)
        os.closerange(3, 4096)
        shell = pw.pw_shell if os.path.basename(pw.pw_shell or "") in SHELLS_THAT_READ_A_PROFILE and os.access(pw.pw_shell, os.X_OK) else "/bin/sh"
        # a login shell, so /etc/profile and the person's own profile set up the session's environment
        os.execve(shell, ["-" + os.path.basename(shell), "-c", 'exec "$@"', "huginn-session", *command], env)
    except BaseException as err:                                      # noqa: BLE001  (whatever went wrong: don't carry on as root)
        try:
            os.write(2, f"huginn-signin: couldn't start the session: {err}\n".encode())
        finally:
            os._exit(127)


def worker(fd: int) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import huginn_pam
    chan = socket.socket(fileno=fd)
    rfile = chan.makefile("rb")

    def send(msg: dict) -> None:
        try:
            chan.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        except OSError:
            pass

    def recv():
        line = rfile.readline()
        try:
            return json.loads(line) if line else None
        except ValueError:
            return None

    job = recv()
    if not job:
        return 2
    user, kind, password = job["user"], job["class"], job.get("password")
    lo, hi = uid_range()
    try:
        pw = pwd.getpwnam(user)
    except KeyError:
        pw = None
    if kind == "user" and (pw is None or not may_sign_in(pw, lo, hi)):
        time.sleep(2)                                                  # as long as PAM takes over a wrong password
        send({"auth": False, "why": WRONG})
        return 0
    if pw is None:
        send({"auth": False, "why": f"There's no {user} account."})
        return 0
    pam = huginn_pam.Session(job["service"], user)
    ok, why = pam.authenticate(password or "")
    password = job["password"] = None
    send({"auth": ok, "why": why})
    if not ok:
        pam.close()
        return 0
    if not job.get("go"):
        msg = recv()                                                   # waits here while the greeter plays its wake and leaves
        if not msg or not msg.get("go"):
            pam.close()
            return 0
    vt = int(job.get("vt") or VT)
    tty = take_screen(vt)
    asks = {"XDG_SEAT": "seat0", "XDG_VTNR": str(vt), "XDG_SESSION_CLASS": kind, "XDG_SESSION_TYPE": "wayland", "XDG_SESSION_DESKTOP": "huginn"}
    ok, why = pam.open(asks, f"/dev/tty{vt}" if tty >= 0 else "")
    if not ok:
        send({"started": False, "why": why})
        pam.close()
        return 0
    env = {"PATH": PATH, "TERM": "linux", **asks, **pam.env(), **(job.get("env") or {}),
           "HOME": pw.pw_dir, "USER": pw.pw_name, "LOGNAME": pw.pw_name, "SHELL": pw.pw_shell or "/bin/sh"}
    pid = os.fork()
    if pid == 0:
        chan.close()
        become(pw, tty, env, list(job["command"]), kind)
    if tty >= 0:
        os.close(tty)
    send({"started": True, "pid": pid})
    stop_at, killed = None, False
    signal.signal(signal.SIGTERM, lambda *_: None)                     # ending is asked for below, in order
    sel = selectors.DefaultSelector()
    sel.register(chan, selectors.EVENT_READ)
    code, asked = None, False
    while code is None:
        try:
            done, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            done, status = pid, 0
        if done:
            code = os.waitstatus_to_exitcode(status)
            break
        if not asked and sel.select(0.2):
            msg = recv()
            if msg is None or msg.get("stop"):                         # told to stop, or the service has gone
                asked = True
                sel.unregister(chan)
        elif asked:
            time.sleep(0.2)
        if asked and stop_at is None:
            stop_at = time.monotonic()
            for sig_to in (os.killpg, os.kill):
                try:
                    sig_to(pid, signal.SIGTERM)
                except OSError:
                    pass
        if stop_at and not killed and time.monotonic() - stop_at > 8:
            killed = True
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
    pam.close()
    send({"ended": code})
    return 0


def main(argv: list) -> int:
    if len(argv) >= 2 and argv[0] == "--worker":
        return worker(int(argv[1]))
    if argv[:1] == ["--people"]:
        print(json.dumps({"people": people(), "conf": read_conf(), "sessions": sessions()}, indent=1))
        return 0
    if os.geteuid() != 0:
        print("huginn-signind: the sign-in service runs as root (systemctl start huginn-signin)", file=sys.stderr)
        return 2
    svc = Service()
    signal.signal(signal.SIGTERM, lambda *_: setattr(svc, "ending", True))
    signal.signal(signal.SIGINT, lambda *_: setattr(svc, "ending", True))
    return svc.run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
