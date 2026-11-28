"""Huginn Software Update: one place for every kind of update.

    System       Ubuntu's packages (the kernel, drivers, Qt WebEngine, every library) through PackageKit (pkgcli, or pkcon before 1.3),
                 or apt through pkexec when PackageKit isn't there. The system asks for the administrator password
                 in its own window; this app never sees it.
    Apps         apps from Flathub, for you and for everyone on the computer (flatpak update).
    Firmware     the computer's own firmware and devices that take updates (fwupd, from the LVFS).
    Huginn OS    the desktop, every Huginn app, the look, system files and the compositor, from the branch this system
                 was built from (huginn_osupdate.py). Fetched and checked, then put in place at the next start-up
                 before the sign-in screen, or at once if asked; the version before is kept for "Go Back".
    Huginn       the browser, from its own repository (vendor/huginn/SOURCE says which). A newer Huginn goes into
                 ~/.local/share/huginn-os/browser, and /usr/bin/huginn starts whichever copy is newer, so it needs
                 no password and the previous copy stays for "Go Back".

Automatic updates (on by default): every six hours `huginn_updates.py watch` looks; apps and Huginn are brought up
to date at once, and system updates are downloaded and put in place for the next restart (PackageKit's offline
updates), so nothing changes under a running program. What it found is kept in ~/.cache/huginn/updates.json, which
Settings and the App Store read.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

HOME = Path.home()
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache") / "huginn"
STATE = CACHE / "updates.json"
BROWSER_HOME = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share") / "huginn-os" / "browser"
SYSTEM_BROWSER = Path("/usr/share/huginn")
RESTART_NAMES = re.compile(r"^(linux-(image|modules|firmware)|systemd|libc6|libsystemd|dbus|nvidia-|mesa|libgl|kwin|plasma-workspace|qt6-|libqt6)")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
RUNTIME_MARKS = (".Platform", ".Sdk", ".GL.", ".GL32.", ".Codecs", ".Extension", "openh264", ".Locale", ".Debug", ".Gtk3theme", ".KStyle",
                 ".PlatformTheme", ".WaylandDecoration", ".ffmpeg", ".VAAPI")



def pk(what: str) -> list:
    """PackageKit's command line for `what` (refresh, update, offline): pkgcli from PackageKit 1.3 (Ubuntu 26.04),
    pkcon before it; [] when neither is installed."""
    if HAVE("pkgcli"):
        return {"refresh": ["pkgcli", "refresh"], "update": ["pkgcli", "update", "-y"],
                "offline": ["pkgcli", "offline-update", "prepare", "-y"]}[what]
    if HAVE("pkcon"):
        return {"refresh": ["pkcon", "refresh", "--noninteractive"], "update": ["pkcon", "update", "-y", "--noninteractive"],
                "offline": ["pkcon", "update", "--only-download", "-y", "--noninteractive"]}[what]
    return []

def run(argv: list, stdin: str = None, timeout: float = 120) -> tuple:
    try:
        done = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout, env={**os.environ, "LC_ALL": "C.UTF-8"})
        return done.returncode, done.stdout, done.stderr
    except FileNotFoundError:
        return 127, "", f"{argv[0]} isn't installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]} took too long"
    except OSError as err:
        return 126, "", str(err)


RUN = run
HAVE = shutil.which


def fetch(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Huginn-OS-Software-Update", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as reply:          # noqa: S310  (https only, below)
        return reply.read()


FETCH = fetch


# ------------------------------------------------------------------------------------------- what's waiting
def parse_apt(text: str) -> list:
    """`apt list --upgradable` → [{id, name, version, from, security}]."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^([^/\s]+)/(\S+)\s+(\S+)\s+\S+(?:\s+\[upgradable from:\s*([^\]]+)\])?", line)
        if m:
            out.append({"id": "deb:" + m.group(1), "name": m.group(1), "version": m.group(3), "from": (m.group(4) or "").strip(),
                        "security": "-security" in m.group(2), "kind": "system"})
    return out


def parse_apt_simulation(text: str) -> list:
    """`apt-get -s dist-upgrade` → the same rows as parse_apt, for what apt would really put in: its "Inst" lines.
    Ubuntu holds some updates back for a while (phased updates, rolled out to a few computers at a time) and some
    need a choice apt won't make by itself; `apt list --upgradable` lists those too, so they'd be shown as ready,
    "installed", and still be there afterwards."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^Inst\s+(\S+)\s+(?:\[([^\]]+)\]\s+)?\((\S+)\s+([^)]*)\)", line)
        if m:
            out.append({"id": "deb:" + m.group(1), "name": m.group(1), "version": m.group(3), "from": (m.group(2) or "").strip(),
                        "security": "-security" in m.group(4), "kind": "system", "new": not m.group(2)})
    return out


class NoLists(Exception):
    """Ubuntu's package lists couldn't be fetched, so what's waiting for the system can't be known."""


def lists_stale() -> bool:
    try:
        import huginn_packages
    except ImportError:
        return False
    return huginn_packages.lists_stale()


STALE = lists_stale


def check_system(refresh: bool = True) -> list:
    # the drive and a fresh installation carry no package lists: with none (or old ones) apt sees nothing to update,
    # which would read as "up to date", so they're fetched whenever they're missing or stale, asked or not
    stale = STALE()
    if (refresh or stale) and pk("refresh"):
        code, out, err = RUN(pk("refresh"), None, 600)
        if code != 0 and stale:
            tail = [ln.strip() for ln in (err or out or "").splitlines() if ln.strip()]
            raise NoLists("Couldn't fetch the list of Ubuntu's updates" + (f" ({tail[-1][:140]})" if tail else "") + ". Is the computer online?")
    elif stale:
        raise NoLists("Couldn't look for system updates: PackageKit isn't installed.")
    code, out, _ = RUN(["apt-get", "-s", "-o", "Debug::NoLocking=1", "dist-upgrade"], None, 180)
    if code == 0:
        return [i for i in parse_apt_simulation(out) if not i.get("new")]      # new packages come with an update; they aren't one
    code, out, _ = RUN(["apt", "list", "--upgradable"], None, 120)
    return parse_apt(out) if code == 0 else []


def parse_flatpak(text: str, where: str) -> list:
    out = []
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) >= 2 and "." in f[0]:
            out.append({"id": f"flatpak:{where}:{f[0]}", "app": f[0], "name": f[1] or f[0], "version": f[2] if len(f) > 2 else "", "from": "",
                        "security": False, "kind": "app", "where": where, "runtime": any(w in f[0] for w in RUNTIME_MARKS)})
    return out


def check_flatpak() -> list:
    if not HAVE("flatpak"):
        return []
    out = []
    for where in ("user", "system"):
        code, text, _ = RUN(["flatpak", "remote-ls", f"--{where}", "--updates", "--columns=application,name,version"], None, 180)
        if code == 0:
            out += parse_flatpak(text, where)
    return out


def parse_fwupd(text: str) -> list:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out = []
    for dev in data.get("Devices", []):
        rel = (dev.get("Releases") or [{}])[0]
        if rel:
            out.append({"id": "fw:" + str(dev.get("DeviceId", dev.get("Name", ""))), "name": dev.get("Name", "Firmware"), "version": rel.get("Version", ""),
                        "from": dev.get("Version", ""), "security": "security" in (rel.get("Summary", "") + " ".join(rel.get("Issues", []) or [])).lower() or bool(rel.get("Issues")),
                        "kind": "firmware", "note": re.sub(r"<[^>]+>", " ", rel.get("Description", "")).strip()[:300]})
    return out


def check_firmware() -> list:
    if not HAVE("fwupdmgr"):
        return []
    code, text, _ = RUN(["fwupdmgr", "get-updates", "--json", "--no-unreported-check", "--no-metadata-check"], None, 120)
    return parse_fwupd(text) if code == 0 else []


def read_source(folder: Path) -> dict:
    """vendor/huginn/SOURCE: repo, commit, date."""
    out = {}
    try:
        for line in (folder / "SOURCE").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def browser_installed() -> dict:
    """The copy of Huginn that /usr/bin/huginn starts: the newer of the system's and the one Software Update fetched."""
    system, mine = read_source(SYSTEM_BROWSER), read_source(BROWSER_HOME / "current")
    if mine.get("date", "") > system.get("date", "") and (BROWSER_HOME / "current" / "safari_browser.py").is_file():
        return {**mine, "where": "yours"}
    return {**system, "where": "system"}


def github_repo(url: str) -> str:
    m = re.match(r"https://github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url or "")
    return m.group(1) if m else ""


def check_huginn() -> list:
    have = browser_installed()
    repo = github_repo(have.get("repo", "")) or github_repo(read_source(SYSTEM_BROWSER).get("repo", ""))
    if not repo:
        return []
    try:
        label = ""
        try:
            ref = json.loads(FETCH(f"https://api.github.com/repos/{repo}/releases/latest")).get("tag_name", "")
            label = ref
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
            ref = ""
        if not ref:                                                   # no releases: follow the main branch
            ref = json.loads(FETCH(f"https://api.github.com/repos/{repo}")).get("default_branch", "main")
        head = json.loads(FETCH(f"https://api.github.com/repos/{repo}/commits/{ref}"))
        sha = head.get("sha", "")
        date = ((head.get("commit") or {}).get("committer") or {}).get("date", "")[:10]
    except (OSError, ValueError, urllib.error.URLError, AttributeError):
        return []
    if not sha or sha == have.get("commit") or (date and date <= have.get("date", "")):
        return []
    return [{"id": "huginn", "name": "Huginn", "version": label or (date + " · " + sha[:7]), "from": have.get("date", ""), "security": False,
             "kind": "huginn", "repo": repo, "sha": sha, "date": date}]


OS_ROOT = Path("/")
OS_HELPER = "/usr/libexec/huginn-os-update"


def check_os() -> list:
    """A newer Huginn OS on this system's branch, as one item (none while it is already fetched and waiting for the
    restart, or when this system doesn't say what it is)."""
    import huginn_osupdate as osu
    try:
        found = osu.look(OS_ROOT, lambda url, timeout=60, cap=8 * 1024 * 1024: FETCH(url, timeout))
    except osu.Problem:
        return []
    if not found["waiting"] or found["staged"] == found["latest"]["sha"]:
        return []
    new = found["latest"]
    return [{"id": "os", "name": "Huginn OS", "version": f"{new['date']} · {new['sha'][:7]}", "from": found["have"]["date"], "security": False, "kind": "os",
             "sha": new["sha"], "date": new["date"], "note": new["title"], "news": found["news"][:12], "skipped": found["skipped"]}]


def os_view(demo: bool = False) -> dict:
    """What Software Update shows about Huginn OS itself: {known, date, commit, staged: {date, commit, title, news},
    canGoBack, problem, applied: {date, kept, compositor}, live}."""
    if demo:
        return {"known": True, "date": "2026-11-27", "commit": "db47fe0", "staged": {"date": "2026-11-28", "commit": "4b1e9c2", "title": "Tempo: sound for games",
                                                                                     "news": ["Tempo: sound for games", "Code: notebooks and workspaces"]},
                "canGoBack": True, "problem": "", "applied": {}, "live": False}
    import huginn_osupdate as osu
    have, st = osu.source(OS_ROOT), osu.load_state(OS_ROOT)
    staged = st.get("staged") if isinstance(st.get("staged"), dict) else None
    applied = st.get("applied") if isinstance(st.get("applied"), dict) else {}
    return {"known": bool(have["repo"] and have["branch"]), "date": have["date"], "commit": have["commit"][:7],
            "staged": {"date": staged.get("date", ""), "commit": str(staged.get("sha", ""))[:7], "title": staged.get("title", ""), "news": list(staged.get("news") or [])[:12]} if staged else {},
            "canGoBack": (osu.state_dir(OS_ROOT) / "previous/undo.json").is_file(), "problem": str(st.get("problem") or ""),
            "applied": {"date": applied.get("date", ""), "kept": list(applied.get("kept") or [])[:8], "compositor": applied.get("compositor", ""), "undone": bool(applied.get("undone"))} if applied else {},
            "live": osu.is_live(OS_ROOT)}


def needs_restart(items: list) -> bool:
    return Path("/var/run/reboot-required").exists() or any(i["kind"] == "system" and RESTART_NAMES.match(i["name"]) for i in items)


# ------------------------------------------------------------------------------------------- putting them in
class Stopped(Exception):
    pass


def safe_members(tar: tarfile.TarFile, top_only: bool = True):
    """Only plain files and folders that stay inside the folder they're unpacked into."""
    for m in tar.getmembers():
        name = m.name.split("/", 1)[1] if top_only and "/" in m.name else ("" if top_only else m.name)
        if not name or name.startswith("/") or ".." in Path(name).parts or not (m.isfile() or m.isdir()):
            continue
        m.name = name
        m.mode = 0o755 if m.isdir() else (0o644 | (m.mode & 0o111))
        yield m


def install_huginn(item: dict, root: Path = None) -> str:
    """Fetch that version of Huginn, check it, and make it the one /usr/bin/huginn starts. The old one stays."""
    root = root or BROWSER_HOME
    data = FETCH(f"https://codeload.github.com/{item['repo']}/tar.gz/{item['sha']}", 300)
    target = root / item["sha"][:12]
    part = root / f".{item['sha'][:12]}.part"
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True)
    import io
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = list(safe_members(tar))
        try:
            tar.extractall(part, members=members, filter="data")
        except TypeError:                                             # an older Python without extraction filters
            tar.extractall(part, members=members)                     # noqa: S202  (members checked by safe_members)
    if not (part / "safari_browser.py").is_file():
        shutil.rmtree(part, ignore_errors=True)
        raise RuntimeError("That version of Huginn is missing its main file, so it wasn't put in.")
    code, _, err = RUN([sys.executable, "-m", "py_compile", str(part / "safari_browser.py")], None, 60)
    if code != 0:
        shutil.rmtree(part, ignore_errors=True)
        raise RuntimeError("That version of Huginn doesn't start (" + (err.strip().splitlines() or ["it has an error"])[-1][:120] + "), so it wasn't put in.")
    (part / "SOURCE").write_text(f"repo: https://github.com/{item['repo']}.git\ncommit: {item['sha']}\ndate: {item['date']}\n", encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    os.replace(part, target)
    current = root / "current"
    if current.is_symlink() or current.exists():
        old = os.readlink(current) if current.is_symlink() else ""
        if old and old != target.name:
            (root / "previous").unlink(missing_ok=True)
            os.symlink(old, root / "previous")
        current.unlink()
    os.symlink(target.name, current)
    keep = {target.name, os.readlink(root / "previous") if (root / "previous").is_symlink() else ""}
    for old in root.iterdir():                                       # keep the newest two copies
        if old.is_dir() and not old.is_symlink() and old.name not in keep and not old.name.startswith("."):
            shutil.rmtree(old, ignore_errors=True)
    return "Huginn is up to date. Open windows keep the old version until you start Huginn again."


def roll_back_huginn(root: Path = None) -> str:
    root = root or BROWSER_HOME
    prev, current = root / "previous", root / "current"
    if prev.is_symlink():
        target = os.readlink(prev)
        mine = os.readlink(current) if current.is_symlink() else ""
        current.unlink(missing_ok=True)
        os.symlink(target, current)
        prev.unlink()
        if mine:
            os.symlink(mine, prev)
        return "Huginn went back to the version before."
    if current.is_symlink():
        current.unlink()
        return "Huginn went back to the version that came with the system."
    return "There's no other version to go back to."


def run_stream(argv: list, on_line, stopped=lambda: False) -> int:
    """Run a tool, handing each line it prints to on_line; stop it if asked."""
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env={**os.environ, "LC_ALL": "C.UTF-8"})
    except FileNotFoundError:
        return 127
    for line in proc.stdout:
        on_line(ANSI.sub("", line).rstrip())
        if stopped():
            proc.terminate()
            break
    return proc.wait()


def save_state(state: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        part = STATE.with_name(".updates.json.part")
        part.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(part, STATE)
    except OSError:
        pass


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def auto_wanted() -> bool:
    try:
        cfg = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "huginn-shell" / "settings.json"
        return json.loads(cfg.read_text(encoding="utf-8")).get("autoUpdate", "true") == "true"
    except (OSError, ValueError, AttributeError):
        return True


def look_everywhere(refresh: bool = True, problems: list = None) -> list:
    """Everything waiting; `problems` (if given) gets a sentence for each place that couldn't be looked at."""
    items = []
    for check in (lambda: check_system(refresh), check_flatpak, check_firmware, check_huginn, check_os):
        try:
            items += check()
        except NoLists as why:
            if problems is not None:
                problems.append(str(why))
        except Exception:                                            # noqa: BLE001  (one source failing mustn't hide the rest)
            pass
    return items


DEMO = [{"id": "deb:linux-image-generic", "name": "linux-image-generic", "version": "6.17.0-9", "from": "6.17.0-8", "security": True, "kind": "system"},
        {"id": "deb:libqt6webenginecore6", "name": "libqt6webenginecore6", "version": "6.10.1-1ubuntu2", "from": "6.10.1-1ubuntu1", "security": True, "kind": "system"},
        {"id": "deb:mesa-vulkan-drivers", "name": "mesa-vulkan-drivers", "version": "25.2.4-1", "from": "25.2.3-1", "security": False, "kind": "system"},
        {"id": "deb:firefox-locale", "name": "openssl", "version": "3.5.1-2ubuntu0.2", "from": "3.5.1-2ubuntu0.1", "security": True, "kind": "system"},
        {"id": "flatpak:system:org.kde.krita", "app": "org.kde.krita", "name": "Krita", "version": "5.3.1", "from": "", "security": False, "kind": "app", "where": "system", "runtime": False},
        {"id": "flatpak:system:org.libreoffice.LibreOffice", "app": "org.libreoffice.LibreOffice", "name": "LibreOffice", "version": "25.8.3", "from": "", "security": False, "kind": "app", "where": "system", "runtime": False},
        {"id": "flatpak:system:org.freedesktop.Platform.GL.default", "app": "org.freedesktop.Platform.GL.default", "name": "Mesa", "version": "25.2.4", "from": "", "security": False, "kind": "app", "where": "system", "runtime": True},
        {"id": "fw:uefi", "name": "System Firmware", "version": "0.3.22", "from": "0.3.18", "security": True, "kind": "firmware", "note": "Fixes a security problem in the firmware's network boot and makes sleep more reliable."},
        {"id": "huginn", "name": "Huginn", "version": "2026-11-14 · 4b1e9c2", "from": "2026-11-13", "security": False, "kind": "huginn", "repo": "Valkyrii070/Huginn", "sha": "4b1e9c2", "date": "2026-11-14"}]



def _when(stamp: float) -> str:
    """A restore point's time, said plainly: today 14:05, yesterday 09:30, Tue 18 Nov 22:10."""
    t, now = time.localtime(stamp), time.localtime()
    hm = time.strftime("%H:%M", t)
    if t.tm_yday == now.tm_yday and t.tm_year == now.tm_year:
        return f"Today {hm}"
    if time.localtime(stamp + 86400).tm_yday == now.tm_yday and time.localtime(stamp + 86400).tm_year == now.tm_year:
        return f"Yesterday {hm}"
    return time.strftime("%a %d %b", t) + f" {hm}"

class Updates(QObject):
    """Software Update in Settings, and the App Store's Updates page."""
    changed = Signal()
    said = Signal(str, bool)
    _back = Signal(str, object)

    def __init__(self, demo: bool = False, shell_settings=None):
        super().__init__()
        self._demo, self._settings = demo, shell_settings
        saved = {} if demo else load_state()
        self._items = list(DEMO) if demo else saved.get("items", [])
        self._checked = time.time() - 1800 if demo else float(saved.get("checked", 0))
        self._phase, self._progress, self._line = "idle", 0.0, ""
        self._restart = bool(saved.get("restart")) if not demo else False
        self._stop = False
        self._problem = ""
        self._back.connect(self._take)

    def _emit(self, what, data=None):
        self._back.emit(what, data)

    @Slot(str, object)
    def _take(self, what: str, data) -> None:
        if what == "restore":
            then, result = data
            self._restore_busy = ""
            if result.get("error") and result["error"] != "cancelled":
                self.said.emit("Restore points: " + result["error"], True)
            elif not result.get("error"):
                then(result)
            self.restoreChanged.emit()
            return
        if what == "said":
            self.said.emit(*data)
        elif what == "problem":
            self._problem = data
        elif what == "items":
            self._items, self._checked, self._phase = data, time.time(), "idle"
            save_state({"checked": self._checked, "items": self._items, "restart": self._restart})
        elif what == "phase":
            self._phase = data
        elif what == "progress":
            self._progress, self._line = data
        elif what == "done":
            gone, restart = data
            self._items = [i for i in self._items if i["id"] not in gone]
            self._restart = self._restart or restart
            self._phase, self._progress = "idle", 0.0
            save_state({"checked": self._checked, "items": self._items, "restart": self._restart})
        self.changed.emit()

    items = Property("QVariantList", lambda self: self._items, notify=changed)
    count = Property(int, lambda self: len([i for i in self._items if not i.get("runtime")]), notify=changed)
    phase = Property(str, lambda self: self._phase, notify=changed)
    progress = Property(float, lambda self: self._progress, notify=changed)
    line = Property(str, lambda self: self._line, notify=changed)
    restart = Property(bool, lambda self: self._restart, notify=changed)
    demo = Property(bool, lambda self: self._demo, constant=True)
    # why the last look couldn't see everything ("" when it could): Software Update says so instead of "up to date"
    problem = Property(str, lambda self: self._problem, notify=changed)

    @Property(str, notify=changed)
    def checked(self):
        if not self._checked:
            return "Never"
        ago = time.time() - self._checked
        return "Just now" if ago < 90 else f"{int(ago // 60)} minutes ago" if ago < 3600 else f"{int(ago // 3600)} hours ago" if ago < 86400 else time.strftime("%B %-d", time.localtime(self._checked))

    @Property("QVariantMap", notify=changed)
    def huginn(self):
        have = {"commit": "dc892f21", "date": "2026-11-13", "where": "system"} if self._demo else browser_installed()
        return {"date": have.get("date", ""), "commit": have.get("commit", "")[:7], "yours": have.get("where") == "yours",
                "canGoBack": not self._demo and ((BROWSER_HOME / "previous").is_symlink() or (BROWSER_HOME / "current").is_symlink())}

    @Slot(bool)
    def look(self, force: bool) -> None:
        if self._phase != "idle" or (not force and time.time() - self._checked < 3600):
            return
        if self._demo:
            self._checked = time.time()
            self.changed.emit()
            return
        self._phase = "checking"
        self.changed.emit()

        def looking():
            problems = []
            items = look_everywhere(force, problems)
            self._emit("problem", " ".join(problems))
            self._emit("items", items)
        threading.Thread(target=looking, daemon=True).start()

    @Slot(str)
    def install(self, which: str) -> None:
        """which: "all", or a kind (system, app, firmware, huginn), or one item's id."""
        if self._phase != "idle":
            return
        chosen = [i for i in self._items if which == "all" or i["kind"] == which or i["id"] == which]
        if not chosen:
            return
        if self._demo:
            self._items = [i for i in self._items if i not in chosen]
            self._restart = self._restart or any(i["kind"] in ("system", "firmware") and (i["kind"] == "firmware" or RESTART_NAMES.match(i["name"])) for i in chosen)
            self.changed.emit()
            self.said.emit("Everything chosen is up to date.", False)
            return
        self._phase, self._stop = "installing", False
        self.changed.emit()
        threading.Thread(target=self._install, args=(chosen,), daemon=True).start()

    def _install(self, chosen: list) -> None:
        done, restart, problems = set(), False, []
        steps = [k for k in ("app", "huginn", "firmware", "system", "os") if any(i["kind"] == k for i in chosen)]
        for n, kind in enumerate(steps):
            part = [i for i in chosen if i["kind"] == kind]
            base = n / len(steps)

            def line(text, base=base):
                m = re.search(r"(\d{1,3})(?:\.\d+)?%", text)
                frac = min(1.0, int(m.group(1)) / 100) if m else None
                self._emit("progress", (base + (frac or 0) / len(steps), text[:140]))
            stopped = lambda: self._stop                                      # noqa: E731
            last = {"text": ""}

            def line(text, base=base, line=line, last=last):
                if text.strip():
                    last["text"] = text.strip()
                line(text)

            def why(what: str) -> str:
                tail = re.sub(r"^(E|Error|error):\s*", "", last["text"])[:120]
                return what + (f" ({tail})" if tail and not re.search(r"\d+%", tail) else "")
            try:
                if kind == "app":
                    for where in sorted({i["where"] for i in part}):
                        ids = [i["app"] for i in part if i["where"] == where]
                        everything = len(ids) == len([i for i in self._items if i["kind"] == "app" and i["where"] == where])
                        code = run_stream(["flatpak", "update", f"--{where}", "-y", "--noninteractive"] + ([] if everything else ids), line, stopped)
                        if code == 0:
                            done |= {i["id"] for i in part if i["where"] == where}
                        else:
                            problems.append(why("Some apps weren't updated"))
                elif kind == "huginn":
                    line("Fetching Huginn…")
                    self._emit("said", (install_huginn(part[0]), False))
                    done.add("huginn")
                elif kind == "os":
                    line("Fetching Huginn OS…")
                    code = run_stream(["pkexec", OS_HELPER, "stage"], line, stopped)
                    if code == 0:
                        done.add("os")
                        restart = True
                        self._emit("said", ("Huginn OS is fetched and checked. It goes in when the computer restarts (or now: Finish Now).", False))
                    else:
                        problems.append("Huginn OS wasn't updated" + (" (the password wasn't given)" if code in (126, 127) else why("")))
                elif kind == "firmware":
                    code = run_stream(["fwupdmgr", "update", "-y", "--no-reboot-check"], line, stopped)
                    if code == 0:
                        done |= {i["id"] for i in part}
                        restart = True
                    else:
                        problems.append(why("The firmware wasn't updated"))
                else:
                    if pk("update"):
                        code = run_stream(pk("update"), line, stopped)
                    else:
                        code = run_stream(["pkexec", "apt-get", "-y", "-o", "Dpkg::Options::=--force-confold", "full-upgrade"], line, stopped)
                    if code == 0:
                        done |= {i["id"] for i in part}
                        restart = restart or needs_restart(part)
                    else:
                        problems.append("The system wasn't updated" + (" (the password wasn't given)" if code in (126, 127) else why("")))
            except Exception as err:                                      # noqa: BLE001
                problems.append(str(err)[:160])
            if self._stop:
                problems.append("Stopped")
                break
        # What's really still waiting: look again rather than trusting the tools' exit codes (PackageKit and apt can
        # end well having put in only part of it), and say so plainly.
        self._emit("progress", (1.0, "Checking what went in…"))
        try:
            fresh = look_everywhere(False)
        except Exception:                                                 # noqa: BLE001
            fresh = None
        if fresh is None:
            self._emit("done", (done, restart))
        else:
            self._emit("done", ({i["id"] for i in chosen} | done, restart))
            self._emit("items", fresh)
        waiting = [i for i in chosen if fresh is not None and any(f["id"] == i["id"] for f in fresh)]
        put_in = len(chosen) - len(waiting)
        if not waiting and not problems:
            self._emit("said", ("Up to date." + (" Restart to finish." if restart else ""), False))
        else:
            names = ", ".join(i["name"] for i in waiting[:3]) + (f" and {len(waiting) - 3} more" if len(waiting) > 3 else "")
            text = (f"{put_in} of {len(chosen)} updates went in. " if put_in else "The updates didn't go in. ") + \
                   (f"Still waiting: {names}. " if waiting else "") + ("; ".join(problems) + "." if problems else "")
            self._emit("said", (text.strip(), True))

    @Slot()
    def stop(self) -> None:
        self._stop = True

    @Slot()
    def goBack(self) -> None:
        if self._demo:
            self.said.emit("Huginn went back to the version before.", False)
            return
        try:
            self.said.emit(roll_back_huginn(), False)
        except OSError as err:
            self.said.emit(f"Couldn't go back: {err}", True)
        self.changed.emit()

    # ---- Huginn OS itself (huginn_osupdate.py, as root through pkexec)
    os = Property("QVariantMap", lambda self: os_view(self._demo), notify=changed)

    def _os_do(self, word: str, good: str, bad: str) -> None:
        if self._demo:
            self.said.emit(good, False)
            return
        if self._phase != "idle":
            return
        self._phase, self._stop = "installing", False
        self._progress, self._line = 0.0, ""
        self.changed.emit()

        def work():
            last = {"text": ""}

            def line(text):
                if text.strip():
                    last["text"] = text.strip()
                    self._emit("progress", (0.5, text[:140]))
            code = run_stream(["pkexec", OS_HELPER, word], line, lambda: False)
            self._emit("phase", "idle")
            if code == 0:
                self._emit("said", (last["text"] or good, False))
            else:
                self._emit("said", (bad + (" (the password wasn't given)." if code in (126, 127) else f": {last['text'][:200]}" if last["text"] else "."), True))
        threading.Thread(target=work, daemon=True).start()

    @Slot(bool)
    def osSetAuto(self, on: bool) -> None:
        """Whether the system fetches a newer Huginn OS on its own (for everyone on this computer, so it asks)."""
        if self._demo or not os_view().get("known"):
            return
        threading.Thread(target=lambda: RUN(["pkexec", OS_HELPER, "auto-on" if on else "auto-off"], None, 130), daemon=True).start()

    @Slot()
    def osFinishNow(self) -> None:
        """Put the fetched Huginn OS in place now instead of at the next start-up. Open apps keep the old version
        until they are opened again; the desktop itself until you sign out."""
        self._os_do("apply", "Huginn OS is up to date. Sign out and in (or restart) for the desktop to be the new one.", "Huginn OS wasn't put in place")

    @Slot()
    def osGoBack(self) -> None:
        self._os_do("back", "Huginn OS went back to the version before. Sign out and in (or restart) to be using it.", "Huginn OS couldn't go back")

    @Slot()
    def restartNow(self) -> None:
        if not self._demo:
            RUN(["systemctl", "reboot"], None, 10)

    # ---- restore points (huginn-snapshot): a copy of the system before each change to it, to go back to
    restoreChanged = Signal()

    def _restore(self) -> dict:
        if self._demo:
            now = time.time()
            pts = getattr(self, "_demo_points", None) or [
                {"n": 7, "date": now - 2 * 3600, "reason": "Before software was installed or updated", "mine": False},
                {"n": 6, "date": now - 3 * 86400, "reason": "Before software was installed or updated", "mine": False},
                {"n": 1, "date": now - 9 * 86400, "reason": "Just installed", "mine": True}]
            return {"available": True, "points": pts, "leftovers": getattr(self, "_demo_left", []), "pending": getattr(self, "_demo_pending", 0), "undone": 0, "busy": self._restore_busy}
        try:
            data = json.loads(Path("/var/lib/huginn/snapshots.json").read_text())
        except (OSError, ValueError):
            data = {}
        try:
            undone = json.loads(Path("/var/lib/huginn/undone").read_text()).get("n", 0)
        except (OSError, ValueError):
            undone = 0
        return {"available": "points" in data, "points": data.get("points", []), "leftovers": data.get("leftovers", []),
                "pending": self._restore_pending, "undone": undone, "busy": self._restore_busy}

    def _restore_view(self) -> dict:
        r = self._restore()
        r["points"] = [dict(p, when=_when(p["date"])) for p in r["points"]]
        return r
    restore = Property("QVariantMap", _restore_view, notify=restoreChanged)
    _restore_busy = ""
    _restore_pending = 0

    def _snapshot(self, words: list, busy: str, then) -> None:
        """Runs huginn-snapshot as root (pkexec: org.huginn.snapshot), off the window's thread."""
        self._restore_busy = busy
        self.restoreChanged.emit()

        def work():
            code, out, err = RUN(["pkexec", "/usr/libexec/huginn-snapshot", *words], None, 900)
            try:
                data = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
            except (ValueError, IndexError):
                data = {}
            if code in (126, 127):
                data = {"error": "cancelled"}
            elif code and not data.get("error"):
                data = {"error": (err or out).strip().splitlines()[-1] if (err or out).strip() else "It didn't work."}
            self._emit("restore", (then, data))
        threading.Thread(target=work, daemon=True).start()

    @Slot()
    def makeRestorePoint(self) -> None:
        if self._demo:
            self._demo_points = [{"n": 8, "date": time.time(), "reason": "Made by you", "mine": True}] + self._restore()["points"]
            self.restoreChanged.emit()
            return
        self._snapshot(["create", "Made by you"], "making", lambda d: self.said.emit("Made a restore point.", False))

    @Slot(int)
    def undoTo(self, n: int) -> None:
        if self._demo:
            self._demo_pending = n
            self.restoreChanged.emit()
            return

        def then(d):
            self._restore_pending = n
            self.said.emit("Done. Restart, and the system is as it was then.", False)
        self._snapshot(["undo", str(int(n))], "undoing", then)

    @Slot(int)
    def forgetPoint(self, n: int) -> None:
        if self._demo:
            self._demo_points = [p for p in self._restore()["points"] if p["n"] != n]
            self.restoreChanged.emit()
            return
        self._snapshot(["forget", str(int(n))], "forgetting", lambda d: None)

    @Slot()
    def tidyRestore(self) -> None:
        if self._demo:
            self._demo_left = []
            self.restoreChanged.emit()
            return
        self._snapshot(["tidy"], "tidying", lambda d: self.said.emit("Removed what going back left behind.", False))


# ------------------------------------------------------------------------------------------- in the background
GAME_PLAYING = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "huginn" / "game-playing"


def watch(every: float = 6 * 3600, first_wait: float = 300) -> None:
    """Look for updates now and then. With automatic updates on, apps and Huginn are updated straight away and
    system updates are downloaded and set to go in at the next restart."""
    time.sleep(first_wait)
    while True:
        # not while a game has the screen (the compositor's mark): downloads and unpacking take the network, the disk
        # and the processor from it. Looked at again every minute, for up to six hours.
        for _ in range(360):
            if not GAME_PLAYING.exists():
                break
            time.sleep(60)
        items = look_everywhere(True)
        restart = needs_restart(items)
        if auto_wanted():
            for where in ("user", "system"):
                if any(i["kind"] == "app" and i.get("where") == where for i in items):
                    if RUN(["flatpak", "update", f"--{where}", "-y", "--noninteractive"], None, 3600)[0] == 0:
                        items = [i for i in items if not (i["kind"] == "app" and i.get("where") == where)]
            for i in [i for i in items if i["kind"] == "huginn"]:
                try:
                    install_huginn(i)
                    items.remove(i)
                except Exception:                                    # noqa: BLE001
                    pass
            if any(i["kind"] == "system" for i in items) and pk("offline"):
                if HAVE("pkgcli"):                             # PackageKit 1.3 (26.04): one step downloads and triggers
                    RUN(pk("offline"), None, 7200)
                elif RUN(pk("offline"), None, 7200)[0] == 0:
                    RUN(["pkcon", "offline-trigger"], None, 60)
        save_state({"checked": time.time(), "items": items, "restart": restart, "auto": auto_wanted()})
        if items and HAVE("notify-send"):
            security = any(i.get("security") for i in items)
            RUN(["notify-send", "--app-name=Software Update", "--icon=huginn-settings", "Updates are ready" if not auto_wanted() else "Updates will go in when you restart",
                 ("Some fix security problems. " if security else "") + "Open Settings › Software Update."], None, 10)
        time.sleep(every)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        watch()
    elif len(sys.argv) > 1 and sys.argv[1] == "check":
        print(json.dumps(look_everywhere(True), indent=1))
