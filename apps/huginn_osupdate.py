#!/usr/bin/env python3
"""Huginn OS updates itself: the shell, every app, the look, the helpers and system files, and the compositor, from
the branch it was built from, without a new installation.

What an update is. Huginn OS's own parts are files from one source tree (this repository): shell/ and apps/, the
system files under config/overlay/, the look made from tokens/, and the compositor. The image puts them in place
when it is built; this does the same on a running system, from a newer commit of the same branch:

    look     which commit this system is (/usr/share/huginn-os/SOURCE) against the branch's newest (GitHub's API)
    stage    fetch that commit's tree, check it (every Python file compiles, the pieces are all there), work out
             what would change, and install any Ubuntu packages its lists name that this computer lacks
    apply    put it in place: at the next start-up before the sign-in screen (so nothing changes under a running
             app), or at once when asked. Everything replaced is kept, so "back" undoes it whole.

What it will not touch: your files; settings you changed (a few system settings files, listed in YOURS, are only
replaced while they are still exactly what Huginn OS put there); Ubuntu's packages (Software Update's System part).
The compositor is a compiled program: it is replaced only when the tree carries a ready-built one for exactly its
compositor sources (prebuilt/), else it is left as it is and that is said. Huginn's Qt look (qt/: the platform
theme and widget style other apps' Qt loads) is the same, and also only for the Qt this system has.

Trust: the tree is fetched over HTTPS from the one repository and branch named in a root-owned file, by commit, and
nothing else is asked. It is not signed: this trusts GitHub and whoever can push to that branch.

Run as root by /usr/libexec/huginn-os-update (Software Update asks through pkexec; a timer stages on its own).
Every function takes the root folder it works in, so the tests run it on a made-up system as an ordinary user.
"""
from __future__ import annotations

import hashlib
import io
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

STATE_DIR = "var/lib/huginn-os-update"
SOURCE = "usr/share/huginn-os/SOURCE"
MANIFEST = "usr/share/huginn-os/files.json"
MAX_TREE = 600 * 1024 * 1024                  # a fetched tree, packed
MAX_FILE = 200 * 1024 * 1024                  # one file in it
# Settings files that are yours once you (or Settings) change them: replaced only while unchanged.
YOURS = ("etc/xdg/", "etc/sddm.conf.d/", "etc/huginn/signin.conf", "etc/default/", "etc/netplan/", "etc/NetworkManager/", "etc/sysctl.d/", "etc/skel/", "etc/gtk-3.0/", "etc/gtk-4.0/",
         "var/lib/flatpak/overrides/")
NEEDED = ("apps/huginn_app.py", "apps/qml", "shell/qml", "tokens/tokens.json", "tokens/gen_theme.py", "config/overlay/usr/bin/huginn-session", "config/package-lists")


class Problem(Exception):
    """Something that stops an update, said in words for the person at the computer."""


def fetch(url: str, timeout: float = 60, cap: int = 8 * 1024 * 1024) -> bytes:
    if not url.startswith("https://") and not os.environ.get("HUGINN_OSUPDATE_TEST"):
        raise Problem("Updates are only fetched over HTTPS.")
    req = urllib.request.Request(url, headers={"User-Agent": "Huginn-OS-Update", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as reply:      # noqa: S310 (checked above)
            data = reply.read(cap + 1)
    except urllib.error.HTTPError as err:
        raise Problem(f"GitHub answered {err.code} for the update." + (" Too many checks from this network in the last hour: it will try again later." if err.code in (403, 429) else "")) from err
    except (OSError, urllib.error.URLError) as err:
        raise Problem(f"The update server couldn't be reached ({getattr(err, 'reason', err)}).") from err
    if len(data) > cap:
        raise Problem("The update is larger than anything Huginn OS should be: it wasn't fetched.")
    return data


def run(argv: list, timeout: float = 1800, env: dict = None) -> tuple:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env={**os.environ, "LC_ALL": "C.UTF-8", **(env or {})})
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except FileNotFoundError:
        return 127, f"{argv[0]} isn't installed"
    except subprocess.TimeoutExpired:
        return 124, f"{argv[0]} took too long"
    except OSError as err:
        return 126, str(err)


# ------------------------------------------------------------------------------------------------ what this system is
def read_pairs(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition(":")
            if sep and k.strip() and not k.lstrip().startswith("#"):
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def repo_of(url: str) -> str:
    m = re.fullmatch(r"https://github\.com/([A-Za-z0-9][\w.-]*/[\w.-]+?)(?:\.git)?/?", url or "")
    return m.group(1) if m else ""


def source(root) -> dict:
    """{repo ("owner/name"), branch, commit, date} for the system under `root` ("" where it doesn't say)."""
    got = read_pairs(Path(root) / SOURCE)
    branch = got.get("branch", "")
    return {"repo": repo_of(got.get("repo", "")), "branch": branch if re.fullmatch(r"[\w./-]{1,100}", branch) and ".." not in branch else "",
            "commit": got.get("commit", "") if re.fullmatch(r"[0-9a-f]{40}", got.get("commit", "")) else "", "date": got.get("date", "")[:10]}


def write_source(root, repo: str, branch: str, commit: str, date: str) -> None:
    path = Path(root) / SOURCE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"repo: https://github.com/{repo}.git\nbranch: {branch}\ncommit: {commit}\ndate: {date}\n", encoding="utf-8")


def state_dir(root) -> Path:
    return Path(root) / STATE_DIR


def load_state(root) -> dict:
    try:
        got = json.loads((state_dir(root) / "state.json").read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(root, **changes) -> dict:
    st = load_state(root)
    st.update(changes)
    d = state_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    part = d / ".state.json.part"
    part.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.chmod(part, 0o644)
    os.replace(part, d / "state.json")
    return st


def is_live(root) -> bool:
    """The system started from the installation drive: it is thrown away at shutdown, so it isn't updated."""
    return (Path(root) / "cdrom/casper").is_dir() or (Path(root) / "run/live/medium").exists() or (Path(root) / "rofs").is_dir()


def auto_wanted(root) -> bool:
    """Staging on its own is on unless /etc/huginn/os-update.conf says `auto: no`."""
    return read_pairs(Path(root) / "etc/huginn/os-update.conf").get("auto", "yes").lower() not in ("no", "off", "false", "0")


# ------------------------------------------------------------------------------------------------ what there is to have
def latest(have: dict, get=fetch) -> dict:
    """The branch's newest commit: {sha, date, title}. A Problem when this system doesn't say where it came from."""
    if not have.get("repo") or not have.get("branch"):
        raise Problem("This system doesn't say which version of Huginn OS it is (it was installed before updates could do this). Install the newest image once; after that it keeps itself up to date.")
    try:
        head = json.loads(get(f"https://api.github.com/repos/{have['repo']}/commits/{have['branch']}"))
        sha = head["sha"]
        date = head["commit"]["committer"]["date"][:10]
        title = head["commit"]["message"].splitlines()[0][:160]
    except (ValueError, KeyError, TypeError, IndexError) as err:
        raise Problem("The update server's answer couldn't be read.") from err
    if not re.fullmatch(r"[0-9a-f]{40}", sha or ""):
        raise Problem("The update server's answer couldn't be read.")
    return {"sha": sha, "date": date, "title": title}


def whats_new(have: dict, sha: str, get=fetch, cap: int = 30) -> list:
    """The titles of the changes between this system's commit and `sha`, newest first ([] when it can't be told)."""
    if not have.get("commit"):
        return []
    try:
        cmp = json.loads(get(f"https://api.github.com/repos/{have['repo']}/compare/{have['commit']}...{sha}"))
        titles = [str(c["commit"]["message"]).splitlines()[0][:160] for c in cmp.get("commits", []) if isinstance(c, dict)]
    except (Problem, ValueError, KeyError, TypeError, IndexError):
        return []
    return titles[::-1][:cap]


def look(root, get=fetch) -> dict:
    """{have, latest, waiting (a newer version exists), skipped (it is the one this system went back from, so it
    isn't taken without being asked for), staged (sha or ""), news: [titles]} for the system under `root`."""
    have, st = source(root), load_state(root)
    new = latest(have, get)
    waiting = new["sha"] != have["commit"] and not (have["date"] and new["date"] < have["date"])
    return {"have": have, "latest": new, "waiting": waiting, "skipped": waiting and new["sha"] == st.get("skip"), "staged": st.get("staged", {}).get("sha", "") if isinstance(st.get("staged"), dict) else "",
            "news": whats_new(have, new["sha"], get) if waiting else []}


# ------------------------------------------------------------------------------------------------ fetching and checking
def unpack(data: bytes, dest: Path) -> None:
    """A tree as GitHub packs it (one top folder), unpacked into `dest`: plain files and folders only, none of them
    outside it, none absurdly large."""
    dest.mkdir(parents=True, exist_ok=True)
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except (tarfile.TarError, OSError, EOFError) as err:
        raise Problem("What was fetched isn't an update (it couldn't be unpacked).") from err
    total = 0
    with tar:
        try:
            members = tar.getmembers()
        except (tarfile.TarError, OSError, EOFError) as err:
            raise Problem("What was fetched isn't an update (it couldn't be unpacked).") from err
        for m in members:
            name = m.name.split("/", 1)[1] if "/" in m.name else ""
            parts = Path(name).parts
            if not name or name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir()):
                continue
            if m.isfile() and m.size > MAX_FILE:
                raise Problem("The update holds a file larger than anything Huginn OS should: it wasn't used.")
            total += m.size
            if total > 4 * MAX_TREE:
                raise Problem("The update is larger than anything Huginn OS should be: it wasn't used.")
            target = dest / name
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(m)
            with open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            os.chmod(target, 0o755 if m.mode & 0o111 else 0o644)


def check_kit(kit: Path) -> list:
    """What is wrong with a tree, as sentences ([] when it can be installed): its pieces, its Python, its numbers."""
    kit, bad = Path(kit), []
    for rel in NEEDED:
        if not (kit / rel).exists():
            bad.append(f"it has no {rel}")
    if bad:
        return bad
    for folder in ("apps", "shell", "tokens"):
        for py in sorted((kit / folder).glob("*.py")):
            try:
                compile(py.read_bytes(), str(py), "exec", dont_inherit=True)
            except (SyntaxError, ValueError) as err:
                bad.append(f"{folder}/{py.name} doesn't compile ({getattr(err, 'msg', err)}, line {getattr(err, 'lineno', '?')})")
    try:
        if not isinstance(json.loads((kit / "tokens/tokens.json").read_text(encoding="utf-8")), dict):
            bad.append("tokens/tokens.json isn't what the look is made from")
    except (OSError, ValueError):
        bad.append("tokens/tokens.json can't be read")
    return bad[:12]


def channel(kit: Path) -> dict:
    """config/update.conf in a tree: where the system it becomes should look next ({} to stay where it is)."""
    got = read_pairs(Path(kit) / "config/update.conf")
    return {"repo": repo_of(got.get("repo", "")), "branch": got.get("branch", "") if re.fullmatch(r"[\w./-]{1,100}", got.get("branch", "")) else ""}


def listed_packages(kit: Path) -> list:
    names = set()
    for f in sorted((Path(kit) / "config/package-lists").glob("*.list")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            word = line.split("#", 1)[0].split()
            if word and re.fullmatch(r"[a-z0-9][a-z0-9+.:-]+", word[0]):
                names.add(word[0])
    return sorted(names)


def missing_packages(kit: Path, runner=run) -> list:
    """The packages the tree's lists name that this computer doesn't have installed."""
    want = listed_packages(kit)
    code, out = runner(["dpkg-query", "-W", "-f", "${Package} ${db:Status-Status}\n"] + want, 120)
    have = {line.split()[0].split(":")[0] for line in out.splitlines() if line.endswith(" installed")}
    return [p for p in want if p.split(":")[0] not in have]


# ------------------------------------------------------------------------------------------------ what goes where
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def tree_hash(*folders: Path) -> str:
    """One number for the contents of some folders (names and bytes, not dates): the compositor's sources."""
    h = hashlib.sha256()
    for folder in folders:
        for f in sorted(p for p in Path(folder).rglob("*") if p.is_file() and "target" not in p.relative_to(folder).parts and ".git" not in p.parts):
            h.update(str(f.relative_to(folder)).encode() + b"\0" + sha256(f).encode() + b"\n")
    return h.hexdigest()


def make_theme(kit: Path, root: Path, out: Path, runner=run) -> bool:
    """The look's files from the tree's tokens (tokens/gen_theme.py), into `out`. False when it couldn't be made."""
    argv = [sys.executable, str(kit / "tokens/gen_theme.py"), str(kit / "tokens/tokens.json"), str(out)]
    code, _text = runner(argv, 300)
    return code == 0 and (out / "color-schemes").is_dir()


def wanted_files(kit: Path, theme: Path = None) -> dict:
    """{path on the system (no leading slash): (file in the tree, mode)} for everything a tree puts in place."""
    kit, out = Path(kit), {}
    overlay = kit / "config/overlay"
    for f in overlay.rglob("*"):
        if f.is_file() and not f.is_symlink():
            rel = str(f.relative_to(overlay))
            # (git keeps only whether a file can be run; netplan insists its files are the administrator's alone)
            out[rel] = (f, 0o600 if rel.startswith("etc/netplan/") else 0o755 if f.stat().st_mode & 0o111 else 0o644)
    for pattern, where, mode in (("shell/*.py", "usr/share/huginn-shell", 0o755), ("shell/qml/*.qml", "usr/share/huginn-shell/qml", 0o644), ("shell/qml/*.js", "usr/share/huginn-shell/qml", 0o644),
                                 ("apps/*.py", "usr/share/huginn-apps", 0o755), ("apps/qml/*.qml", "usr/share/huginn-apps/qml", 0o644), ("apps/qml/*.png", "usr/share/huginn-apps/qml", 0o644),
                                 ("apps/help/*.md", "usr/share/huginn-apps/help", 0o644),
                                 ("shell/layershell-fallback/org/huginn/layershell/qmldir", "usr/share/huginn-shell/layershell-fallback/org/huginn/layershell", 0o644)):
        for f in kit.glob(pattern):
            out[f"{where}/{f.name}"] = (f, mode)
    data = kit / "apps/data"
    for f in data.rglob("*") if data.is_dir() else []:
        if f.is_file():
            out[f"usr/share/huginn-apps/data/{f.relative_to(data)}"] = (f, 0o644)
    out["usr/share/huginn-os/tokens.json"] = (kit / "tokens/tokens.json", 0o644)
    if theme is not None and theme.is_dir():
        for f in (theme / "color-schemes").glob("*.colors"):
            out[f"usr/share/color-schemes/{f.name}"] = (f, 0o644)
        for f in (theme / "gtk").glob("*.css"):
            out[f"usr/share/huginn-os/gtk/{f.name}"] = (f, 0o644)
        for f in (theme / "qml").glob("*"):
            if f.is_file():
                out[f"usr/lib/x86_64-linux-gnu/qt6/qml/org/huginn/tokens/{f.name}"] = (f, 0o644)
        for f in (theme / "qt").glob("*.conf"):
            out[f"usr/share/huginn-os/qt/{f.name}"] = (f, 0o644)
        made = theme / "_made"                                     # the three settings files the image writes from the look
        made.mkdir(exist_ok=True)
        aurora = theme / "color-schemes/HuginnAuroraDark.colors"
        if aurora.is_file() and "etc/xdg/kdeglobals" in out:
            text, keep = aurora.read_text(encoding="utf-8"), []
            on = False
            for line in text.splitlines():
                if line.startswith("[Colors:"):
                    on = True
                elif line.startswith("[General]"):
                    break
                if on:
                    keep.append(line)
            (made / "kdeglobals").write_text(out["etc/xdg/kdeglobals"][0].read_text(encoding="utf-8") + "\n".join(keep) + "\n", encoding="utf-8")
            out["etc/xdg/kdeglobals"] = (made / "kdeglobals", 0o644)
        qt = theme / "qt/HuginnAuroraDark.conf"
        if qt.is_file():                                           # Qt apps' look until the shell writes each person's
            text = qt.read_text(encoding="utf-8")
            (made / "qt.conf").write_text(QT_DEFAULT + text[text.index("[Colours]"):], encoding="utf-8")
            out["etc/xdg/huginn/qt.conf"] = (made / "qt.conf", 0o644)
        (made / "settings.ini").write_text("[Settings]\ngtk-theme-name=Huginn\ngtk-icon-theme-name=Huginn\ngtk-cursor-theme-name=Huginn\n"
                                           "gtk-application-prefer-dark-theme=true\ngtk-font-name=Inter Variable 10\n", encoding="utf-8")
        for v in ("3.0", "4.0"):
            out[f"etc/gtk-{v}/settings.ini"] = (made / "settings.ini", 0o644)
        pointers = theme / "pointers"                              # Huginn's pointers, each realm's, when make_pointers drew them
        for one in sorted(pointers.glob("Huginn*")) if (pointers / "Huginn/cursors/default").is_file() else []:
            where = f"usr/share/icons/{one.name}"
            for f in (one / "cursors").glob("*") if (one / "cursors/default").is_file() else []:
                if f.is_file() and not f.is_symlink():
                    out[f"{where}/cursors/{f.name}"] = (f, 0o644)
            if (one / "cursor.theme").is_file():
                out[f"{where}/cursor.theme"] = (one / "cursor.theme", 0o644)
            if one.name != "Huginn" and (one / "index.theme").is_file():   # (Huginn's own index is the icon theme's)
                out[f"{where}/index.theme"] = (one / "index.theme", 0o644)
    return out


def compositor_ready(kit: Path) -> tuple:
    """(the ready-built compositor in a tree, or None; why not). It must be for exactly the tree's compositor sources
    and be the bytes its note says."""
    kit = Path(kit)
    note, blob = read_pairs(kit / "prebuilt/huginn-compositor.for"), kit / "prebuilt/huginn-compositor.xz"
    if not blob.is_file() or not note:
        return None, "this update carries no ready-built compositor"
    if note.get("sources") != tree_hash(kit / "compositor", kit / "third_party/smithay"):
        return None, "the compositor's sources changed after its ready-built copy was made"
    try:
        binary = lzma.decompress(blob.read_bytes())
    except (lzma.LZMAError, OSError, EOFError):
        return None, "the ready-built compositor couldn't be unpacked"
    if hashlib.sha256(binary).hexdigest() != note.get("sha256") or binary[:4] != b"\x7fELF":
        return None, "the ready-built compositor isn't the one its note describes"
    return binary, ""


QT_PLUGINS = "usr/lib/x86_64-linux-gnu/qt6/plugins"
QT_QML = "usr/lib/x86_64-linux-gnu/qt6/qml/org/huginn/layershell"
# each part of Huginn's Qt look as built (qt/: the folder cmake built into) and where it goes
QT_PARTS = {"theme": ("libhuginntheme.so", f"{QT_PLUGINS}/platformthemes/libhuginntheme.so"),
            "style": ("libhuginnstyle.so", f"{QT_PLUGINS}/styles/libhuginnstyle.so"),
            "layershell": ("org/huginn/layershell/libhuginnlayershell.so", f"{QT_QML}/libhuginnlayershell.so"),
            "layershell-qmldir": ("org/huginn/layershell/qmldir", f"{QT_QML}/qmldir"),
            "layershell-types": ("org/huginn/layershell/huginnlayershell.qmltypes", f"{QT_QML}/huginnlayershell.qmltypes")}
QT_DEFAULT = "; Huginn OS: Qt apps' look until the shell writes each person's own (~/.config/huginn/qt.conf)\n[Look]\nscheme=dark\nicons=Huginn\nfont=Inter Variable,10\nfixed=JetBrains Mono,10\n\n[Menus]\ntop_bar=true\n\n"


KSTYLE = "var/lib/flatpak/extension/org.kde.KStyle.Huginn/x86_64/{branch}/styles/libhuginnstyle.so"


def kstyle_paths(qt: str) -> list:
    """Where the style goes for App Store Qt apps: an extension Flatpak doesn't manage (org.kde.KStyle.Huginn) for
    KDE's runtimes from the Qt it was built with on, as build.sh puts it (a plugin loads in a newer Qt, not an older)."""
    found = re.fullmatch(r"(\d+)\.(\d+)\.\d+", qt or "")
    if not found:
        return []
    major, minor = int(found.group(1)), int(found.group(2))
    return [KSTYLE.format(branch=f"{major}.{minor + i}") for i in range(3)]


def qt_version(root) -> str:
    """The Qt this system has ("6.10.2"), from dpkg's records, or ""."""
    try:
        status = (Path(root) / "var/lib/dpkg/status").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for block in status.split("\n\n"):
        if re.search(r"^Package: libqt6core6(t64)?$", block, re.M) and re.search(r"^Status: install ok installed$", block, re.M):
            found = re.search(r"^Version: (?:\d+:)?(\d+\.\d+\.\d+)", block, re.M)
            if found:
                return found.group(1)
    return ""


def qt_ready(kit: Path, root) -> tuple:
    """({path on the system: bytes} of the ready-built Qt look in a tree, or {}; why not). It must be for exactly
    the tree's qt/ sources and for this system's Qt (the same major and minor version: the platform theme uses Qt's
    own inner interfaces), and be the bytes its note says."""
    kit = Path(kit)
    note = read_pairs(kit / "prebuilt/huginn-qt.for")
    if not note:
        return {}, "this update carries no ready-built Qt look"
    if note.get("sources") != tree_hash(kit / "qt"):
        return {}, "the Qt look's sources changed after its ready-built copy was made"
    have = qt_version(root)
    if not have or have.split(".")[:2] != note.get("qt", "").split(".")[:2]:
        return {}, f"the ready-built Qt look is for Qt {note.get('qt', '?')}, and this system has {have or 'no Qt'}"
    out = {}
    for part, (built, rel) in QT_PARTS.items():
        try:
            data = lzma.decompress((kit / f"prebuilt/huginn-qt-{part}.xz").read_bytes())
        except (lzma.LZMAError, OSError, EOFError):
            return {}, "the ready-built Qt look couldn't be unpacked"
        program = built.endswith(".so")
        if hashlib.sha256(data).hexdigest() != note.get(f"{part}_sha256") or (data[:4] == b"\x7fELF") != program:
            return {}, "the ready-built Qt look isn't the one its note describes"
        out[rel] = data
    for rel in kstyle_paths(note.get("qt", "")):
        out[rel] = out[QT_PARTS["style"][1]]
    return out, ""


GTK_MODULE = "usr/lib/x86_64-linux-gnu/gtk-3.0/modules/libhuginn-menus.so"


def gtk_sources(kit) -> str:
    """One number for the GTK menu module's sources (gtk/'s C files)."""
    h = hashlib.sha256()
    for f in sorted((Path(kit) / "gtk").glob("*.[ch]")):
        h.update(f.name.encode() + b"\0" + sha256(f).encode() + b"\n")
    return h.hexdigest()


def gtk_ready(kit: Path, root) -> tuple:
    """({path on the system: bytes}, why not): Huginn's GTK menu module ready-built (gtk/menus.c), for exactly the
    tree's sources. GTK 3 keeps its interface for modules, so any GTK 3 loads it. (The session asks GTK apps to load it
    only when it's there: huginn-desktop-session.)"""
    kit, root = Path(kit), Path(root)
    out, why = {}, ""
    note = read_pairs(kit / "prebuilt/huginn-gtk.for")
    if not note:
        why = "this update carries no ready-built GTK menu module"
    elif note.get("sources") != gtk_sources(kit):
        why = "the GTK menu module's sources changed after its ready-built copy was made"
    else:
        try:
            data = lzma.decompress((kit / "prebuilt/huginn-gtk-menus.xz").read_bytes())
        except (lzma.LZMAError, OSError, EOFError):
            data = b""
        if data[:4] != b"\x7fELF" or hashlib.sha256(data).hexdigest() != note.get("sha256"):
            why = "the ready-built GTK menu module isn't the one its note describes"
        else:
            out[GTK_MODULE] = data
    return out, why


POINTERS = "usr/share/icons/Huginn"


def make_pointers(kit: Path, out: Path, runner=run) -> bool:
    """Huginn's pointers from the tree (pointers/make_pointers.py), every realm's, into `out`: Huginn/ (Aurora's),
    Huginn-Bifrost/ and the rest, and the plain ones (Huginn-Plain/…), each with cursors/ and cursor.theme; every name a file of its own, since what an
    update puts in place is files. False when they couldn't be made."""
    if not (Path(kit) / "pointers/make_pointers.py").is_file():
        return False
    code, _text = runner([sys.executable, str(Path(kit) / "pointers/make_pointers.py"), "--realms", str(out)], 600)
    return code == 0 and (Path(out) / "Huginn/cursors/default").is_file()


def plan(kit: Path, root, theme: Path = None) -> dict:
    """What applying a tree would do to the system under `root`, without doing it:
    {write: {path: (source, mode)}, remove: [paths], kept: [your changed settings files left alone], compositor: bytes|None, note}."""
    root, want = Path(root), wanted_files(kit, theme)
    try:
        old = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        old = old if isinstance(old, dict) else {}
    except (OSError, ValueError):
        old = {}
    write, kept = {}, []
    for rel, (src, mode) in sorted(want.items()):
        dest = root / rel
        new_hash = sha256(src)
        if dest.is_file() and not dest.is_symlink():
            now = sha256(dest)
            if now == new_hash and (dest.stat().st_mode & 0o777) == mode:
                continue
            if rel.startswith(YOURS) and now != new_hash and now != old.get(rel):
                kept.append(rel)                                   # changed since Huginn OS put it there (or never recorded): yours
                continue
        elif dest.is_symlink() or dest.is_dir():
            continue                                               # (something else is there: not ours to replace)
        write[rel] = (src, mode)
    remove = []
    for folder, endings in (("usr/share/huginn-shell", (".py",)), ("usr/share/huginn-shell/qml", (".qml", ".js")), ("usr/share/huginn-apps", (".py",)),
                            ("usr/share/huginn-apps/qml", (".qml", ".png")), ("usr/share/huginn-apps/help", (".md",))):
        here = root / folder
        for f in sorted(here.iterdir()) if here.is_dir() else []:
            if f.is_file() and f.name.endswith(endings) and f"{folder}/{f.name}" not in want:
                remove.append(f"{folder}/{f.name}")                # a module or a page this version no longer has
    looks = ("usr/share/color-schemes/", "usr/share/huginn-os/gtk/", "usr/lib/x86_64-linux-gnu/qt6/qml/org/huginn/tokens/", "usr/share/huginn-os/qt/")
    held = {rel: was for rel, was in old.items() if rel.startswith(looks)} if theme is None else {}       # the look couldn't be made: its files stay
    for rel, was in old.items():                                   # a system file this version no longer ships, still as it was put
        if rel not in want and rel not in held and rel.startswith("usr/") and rel not in remove and (root / rel).is_file() and sha256(root / rel) == was:
            remove.append(rel)
    binary, note = compositor_ready(kit)
    here = root / "usr/bin/huginn-compositor"
    if binary is not None and here.is_file() and hashlib.sha256(binary).hexdigest() == sha256(here):
        binary = None                                              # (already this one)
    qt, qt_note = qt_ready(kit, root)
    qt = {rel: data for rel, data in qt.items() if not ((root / rel).is_file() and hashlib.sha256(data).hexdigest() == sha256(root / rel))}
    gtk, gtk_note = gtk_ready(kit, root)
    gtk = {rel: data for rel, data in gtk.items() if not ((root / rel).is_file() and hashlib.sha256(data).hexdigest() == sha256(root / rel))}
    return {"write": write, "remove": remove, "kept": kept, "compositor": binary, "note": note, "qt": qt, "qt_note": qt_note,
            "gtk": gtk, "gtk_note": gtk_note, "want": want, "held": held}


# ------------------------------------------------------------------------------------------------ putting it in place
def _put(src, dest: Path, mode: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(f".{dest.name}.huginn-part")
    if isinstance(src, bytes):
        part.write_bytes(src)
    else:
        shutil.copyfile(src, part)
    os.chmod(part, mode)
    os.replace(part, dest)                                         # (a running program keeps the file it has open)


def apply_plan(p: dict, root, keep: Path) -> dict:
    """Do what plan() worked out, keeping every file it replaces or removes in `keep` (a folder) with a list of what
    it made new, so undo() can put the system back exactly. Returns {written, removed, made}."""
    root, keep = Path(root), Path(keep)
    if keep.exists():
        shutil.rmtree(keep)
    (keep / "files").mkdir(parents=True)
    made, touched = [], []
    work = dict(p["write"])
    if p.get("compositor") is not None:
        work["usr/bin/huginn-compositor"] = (p["compositor"], 0o755)
    for rel, data in list((p.get("qt") or {}).items()) + list((p.get("gtk") or {}).items()):
        work[rel] = (data, 0o644)
    for rel in list(work) + list(p["remove"]):
        dest = root / rel
        if dest.is_file():
            (keep / "files" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, keep / "files" / rel)
            touched.append(rel)
        else:
            made.append(rel)
    for extra in (SOURCE, MANIFEST):
        if (root / extra).is_file() and extra not in touched:
            (keep / "files" / extra).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / extra, keep / "files" / extra)
            touched.append(extra)
        elif extra not in touched:
            made.append(extra)
    (keep / "undo.json").write_text(json.dumps({"made": made, "touched": touched}), encoding="utf-8")
    for rel, (src, mode) in work.items():
        _put(src, root / rel, mode)
    for rel in p["remove"]:
        try:
            (root / rel).unlink()
        except OSError:
            pass
    manifest = dict(p.get("held") or {})
    manifest.update({rel: sha256(root / rel) for rel in p["want"] if (root / rel).is_file() and rel not in p["kept"]})
    _put(json.dumps(manifest, indent=0, sort_keys=True).encode(), root / MANIFEST, 0o644)
    return {"written": sorted(work), "removed": list(p["remove"]), "made": made}


def undo(root, keep: Path) -> int:
    """Put back what apply_plan() kept. Returns how many files it restored or took away."""
    root, keep = Path(root), Path(keep)
    try:
        note = json.loads((keep / "undo.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise Problem("There's no earlier version kept to go back to.") from err
    n = 0
    for rel in note.get("touched", []):
        src = keep / "files" / rel
        if src.is_file() and ".." not in Path(rel).parts:
            _put(src, root / rel, src.stat().st_mode & 0o777)
            n += 1
    for rel in note.get("made", []):
        if ".." not in Path(rel).parts and (root / rel).is_file():
            (root / rel).unlink()
            n += 1
    return n


def after(root, written: list, removed: list, kit: Path = None, runner=run, real: bool = None) -> list:
    """What a real system needs told after its files changed (only on the real root, unless `real` says). Returns
    what didn't work."""
    if not (str(root) == "/" if real is None else real):
        return []
    changed, failed = set(written) | set(removed), []

    def any_under(*prefixes) -> bool:
        return any(c.startswith(prefixes) for c in changed)

    def do(argv, timeout=900, must=False):
        code, text = runner(argv, timeout)
        if code != 0 and (must or code not in (127,)):
            failed.append(f"{' '.join(argv[:3])}: {text.strip().splitlines()[-1][:160] if text.strip() else code}")
    do([sys.executable, "-m", "compileall", "-q", "/usr/share/huginn-apps", "/usr/share/huginn-shell"], 900)
    if any_under("etc/systemd/", "usr/lib/systemd/"):
        do(["systemctl", "daemon-reload"], 120)
    if kit is not None:                                            # the image's own steps that are safe to do again on a running system
        for hook in sorted((Path(kit) / "config/hooks").glob("*.sh")):
            if re.search(r"^# On update: run\b", hook.read_text(encoding="utf-8", errors="replace"), re.M):
                do(["sh", str(hook)], 600)
    if any_under("etc/udev/"):
        do(["udevadm", "control", "--reload"], 60)
    if any_under("usr/share/polkit-1/", "etc/polkit-1/"):
        pass                                                       # (polkit watches its folders)
    if any_under("usr/share/applications/"):
        do(["update-desktop-database", "-q", "/usr/share/applications"], 120)
    if any_under("usr/share/icons/"):
        for theme in ("hicolor", "Huginn"):
            do(["gtk-update-icon-cache", "-q", "-t", "-f", f"/usr/share/icons/{theme}"], 300)
    if any_under("usr/share/initramfs-tools/", "usr/share/plymouth/", "etc/modules-load.d/"):
        do(["update-initramfs", "-u"], 1200)
    if any_under("etc/grub.d/", "etc/default/grub"):
        do(["update-grub"], 600)
    return failed


def stamp_release(root, date: str) -> None:
    """BUILD_ID in /etc/os-release follows the version in place."""
    path = Path(root) / "etc/os-release"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    new = re.sub(r"^BUILD_ID=.*$", "BUILD_ID=" + date.replace("-", ""), text, flags=re.M)
    if new != text:
        _put(new.encode(), path, 0o644)


# ------------------------------------------------------------------------------------------------ the three steps
def stage(root, get=fetch, runner=run, sha: str = "", log=print, force: bool = False) -> dict:
    """Fetch and check the newest version and get its packages; leave it ready for apply(). Returns the state's
    "staged" ({sha, date, title, news, kit}) or {} when this system is already the newest (or the newest is the one
    it went back from, and this wasn't asked for by a person: `force`)."""
    root = Path(root)
    if is_live(root):
        raise Problem("This is Huginn OS running from the installation drive: it is as new as the drive. Install it, and the installed system keeps itself up to date.")
    have = source(root)
    found = look(root, get)
    new = found["latest"]
    if sha and sha != new["sha"]:
        raise Problem("A newer version arrived while this one was being looked at: look again.")
    if not found["waiting"] or (found["skipped"] and not force):
        save_state(root, checked=int(time.time()), problem="")
        return {}
    st = load_state(root)
    if isinstance(st.get("staged"), dict) and st["staged"].get("sha") == new["sha"] and Path(st["staged"].get("kit", "/nonexistent")).is_dir():
        return st["staged"]
    log(f"Fetching Huginn OS {new['date']} ({new['sha'][:7]})…")
    data = get(f"https://codeload.github.com/{have['repo']}/tar.gz/{new['sha']}", 900, MAX_TREE)
    hold = state_dir(root) / "staged"
    if hold.exists():
        shutil.rmtree(hold)
    kit = hold / new["sha"][:12]
    unpack(data, kit)
    bad = check_kit(kit)
    if bad:
        shutil.rmtree(hold, ignore_errors=True)
        raise Problem("That version of Huginn OS isn't sound, so it wasn't taken: " + "; ".join(bad[:3]) + ".")
    need = missing_packages(kit, runner) if str(root) == "/" else []
    if need:
        log(f"Installing {len(need)} package{'' if len(need) == 1 else 's'} this version needs: {', '.join(need[:8])}{'…' if len(need) > 8 else ''}")
        runner(["apt-get", "update"], 900)
        code, text = runner(["apt-get", "install", "-y", "--no-install-recommends", "-o", "Dpkg::Options::=--force-confold"] + need, 3600, {"DEBIAN_FRONTEND": "noninteractive"})
        if code != 0:
            shutil.rmtree(hold, ignore_errors=True)
            raise Problem("This version needs packages that couldn't be installed (" + (text.strip().splitlines() or ["apt failed"])[-1][:200] + "). Nothing was changed.")
    staged = {"sha": new["sha"], "date": new["date"], "title": new["title"], "news": found["news"], "kit": str(kit), "packages": need}
    save_state(root, staged=staged, checked=int(time.time()), problem="")
    return staged


def apply(root, runner=run, log=print) -> dict:
    """Put the staged version in place. Returns {sha, date, written, removed, kept, compositor, failed}."""
    root = Path(root)
    st = load_state(root)
    staged = st.get("staged") if isinstance(st.get("staged"), dict) else None
    if not staged or not Path(staged.get("kit", "/nonexistent")).is_dir():
        raise Problem("No update is waiting to be put in place.")
    kit = Path(staged["kit"])
    bad = check_kit(kit)
    if bad:
        raise Problem("The waiting update isn't sound any more (" + bad[0] + "). Look for updates again.")
    have = source(root)
    with tempfile.TemporaryDirectory(prefix="huginn-theme-") as tmp:
        theme = Path(tmp) / "theme"
        if not make_theme(kit, root, theme, runner):
            theme = None
            log("The look's files couldn't be made from this version's tokens: the look stays as it is.")
        elif not make_pointers(kit, theme / "pointers", runner):
            log("Huginn's pointers couldn't be drawn from this version: the pointers stay as they are.")
        p = plan(kit, root, theme)
        done = apply_plan(p, root, state_dir(root) / "previous")
    nxt = channel(kit)
    write_source(root, nxt["repo"] or have["repo"], nxt["branch"] or have["branch"], staged["sha"], staged["date"])
    stamp_release(root, staged["date"])
    failed = after(root, done["written"], done["removed"], kit, runner)
    result = {"sha": staged["sha"], "date": staged["date"], "written": len(done["written"]), "removed": len(done["removed"]), "kept": p["kept"],
              "compositor": "replaced" if p["compositor"] is not None else (p["note"] or "already this version's"),
              "qt": "replaced" if p.get("qt") else (p.get("qt_note") or "already this version's"),
              "gtk": "replaced" if p.get("gtk") else (p.get("gtk_note") or "already this version's"), "failed": failed, "from": have["commit"], "when": int(time.time())}
    shutil.rmtree(state_dir(root) / "staged", ignore_errors=True)
    save_state(root, staged=None, applied=result, previous={"commit": have["commit"], "date": have["date"]}, skip="", problem="")
    (state_dir(root) / "ready").unlink(missing_ok=True)
    return result


def back(root, runner=run) -> dict:
    """Go back to the version before the last update (once: the one before that isn't kept)."""
    root = Path(root)
    st = load_state(root)
    was = source(root)
    n = undo(root, state_dir(root) / "previous")
    shutil.rmtree(state_dir(root) / "previous", ignore_errors=True)
    now = source(root)
    stamp_release(root, now["date"])
    after(root, ["usr/share/huginn-apps/x", "usr/share/applications/x", "etc/systemd/x"], [], None, runner)
    save_state(root, staged=None, previous=None, skip=was["commit"], applied=dict(st.get("applied") or {}, undone=True), problem="")   # (not taken again on its own)
    (state_dir(root) / "ready").unlink(missing_ok=True)
    return {"files": n, "commit": now["commit"], "date": now["date"]}


def mark_ready(root, on: bool = True) -> None:
    """The mark the start-up service looks for: a staged update is put in place before the sign-in screen."""
    path = state_dir(root) / "ready"
    if on:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def record(kit, root, commit: str = "", date: str = "", theme: Path = None) -> int:
    """For the image's build: note which version this system is and what each of its own files was when it was put
    there, so a later update can tell your changes from its own. Returns how many files it noted."""
    kit, root = Path(kit), Path(root)
    where = channel(kit)
    if where["repo"] and where["branch"]:
        write_source(root, where["repo"], where["branch"], commit if re.fullmatch(r"[0-9a-f]{40}", commit or "") else "", date[:10])
    want = wanted_files(kit, theme)
    manifest = {rel: sha256(root / rel) for rel in want if (root / rel).is_file() and not (root / rel).is_symlink()}
    _put(json.dumps(manifest, indent=0, sort_keys=True).encode(), root / MANIFEST, 0o644)
    return len(manifest)


def make_prebuilt(kit, binary) -> dict:
    """For whoever builds the image: put a built compositor in the tree (prebuilt/), noted as being for exactly the
    tree's compositor sources, so systems updating to this tree get it."""
    kit, data = Path(kit), Path(binary).read_bytes()
    if data[:4] != b"\x7fELF":
        raise Problem("That isn't a program.")
    out = kit / "prebuilt"
    out.mkdir(exist_ok=True)
    note = {"sources": tree_hash(kit / "compositor", kit / "third_party/smithay"), "sha256": hashlib.sha256(data).hexdigest()}
    old = read_pairs(out / "huginn-compositor.for")
    if old.get("sources") != note["sources"] or old.get("sha256") != note["sha256"] or not (out / "huginn-compositor.xz").is_file():
        (out / "huginn-compositor.xz").write_bytes(lzma.compress(data, preset=6))
        (out / "huginn-compositor.for").write_text(f"# The compositor, built for exactly these sources (compositor/ and third_party/smithay/).\nsources: {note['sources']}\nsha256: {note['sha256']}\n", encoding="utf-8")
        note["written"] = True
    return note


def make_prebuilt_qt(kit, built, qt: str) -> dict:
    """The same for Huginn's Qt parts (qt/): the platform theme, the style and the shell's layer-shell module, from the
    folder cmake built them into, noted as being for exactly the tree's qt/ sources and for the Qt they were built
    with (systems with another major or minor Qt version keep theirs)."""
    kit, built, out = Path(kit), Path(built), Path(kit) / "prebuilt"
    if not re.fullmatch(r"\d+\.\d+\.\d+", qt or ""):
        raise Problem("That isn't a Qt version (6.10.2, say).")
    parts = {}
    for part, (name, _rel) in QT_PARTS.items():
        try:
            parts[part] = (built / name).read_bytes()
        except OSError:
            raise Problem(f"{name} isn't in {built}: build qt/ there first.") from None
        if (parts[part][:4] == b"\x7fELF") != name.endswith(".so"):
            raise Problem(f"{name} in {built} isn't what it should be.")
    out.mkdir(exist_ok=True)
    note = {"sources": tree_hash(kit / "qt"), "qt": qt}
    note.update({f"{k}_sha256": hashlib.sha256(v).hexdigest() for k, v in parts.items()})
    if read_pairs(out / "huginn-qt.for") != note or not all((out / f"huginn-qt-{k}.xz").is_file() for k in parts):
        for k, v in parts.items():
            (out / f"huginn-qt-{k}.xz").write_bytes(lzma.compress(v, preset=6))
        (out / "huginn-qt.for").write_text("# Huginn's Qt parts (qt/), built for exactly these sources and this Qt.\n"
                                           + "".join(f"{k}: {v}\n" for k, v in note.items()), encoding="utf-8")
        note["written"] = True
    return note


def make_prebuilt_gtk(kit, built) -> dict:
    """The same for the GTK menu module (gtk/), from the library gtk/build.sh made, noted as being for exactly the
    tree's gtk/ sources."""
    kit, out = Path(kit), Path(kit) / "prebuilt"
    try:
        data = Path(built).read_bytes()
    except OSError:
        raise Problem(f"{built} isn't there: build gtk/ first (gtk/build.sh).") from None
    if data[:4] != b"\x7fELF":
        raise Problem(f"{built} isn't a built library.")
    note = {"sources": gtk_sources(kit), "sha256": hashlib.sha256(data).hexdigest()}
    try:
        same = lzma.decompress((out / "huginn-gtk-menus.xz").read_bytes()) == data
    except (lzma.LZMAError, OSError, EOFError):
        same = False
    if read_pairs(out / "huginn-gtk.for") != note or not same:
        out.mkdir(exist_ok=True)
        (out / "huginn-gtk-menus.xz").write_bytes(lzma.compress(data, preset=6))
        (out / "huginn-gtk.for").write_text("# Huginn's GTK menu module (gtk/), built for exactly these sources.\n"
                                            + "".join(f"{k}: {v}\n" for k, v in note.items()), encoding="utf-8")
        note["written"] = True
    return note


# ------------------------------------------------------------------------------------------------ the command
def main(argv: list) -> int:
    what = argv[0] if argv else "look"
    root = Path(os.environ.get("HUGINN_OSUPDATE_ROOT") or "/")
    say = lambda obj: print(json.dumps(obj))                       # noqa: E731
    try:
        if what == "record" and len(argv) >= 3:                    # build.sh: record <tree> <root> [commit] [date] [theme folder]
            print(record(argv[1], argv[2], argv[3] if len(argv) > 3 else "", argv[4] if len(argv) > 4 else "", Path(argv[5]) if len(argv) > 5 else None))
            return 0
        if what == "prebuilt" and len(argv) >= 3:                  # prebuilt <tree> <built compositor>
            print(json.dumps(make_prebuilt(argv[1], argv[2])))
            return 0
        if what == "prebuilt-qt" and len(argv) >= 4:               # prebuilt-qt <tree> <folder qt/ was built in> <Qt version>
            print(json.dumps(make_prebuilt_qt(argv[1], argv[2], argv[3])))
            return 0
        if what == "prebuilt-gtk" and len(argv) >= 3:              # prebuilt-gtk <tree> <built libhuginn-menus.so>
            print(json.dumps(make_prebuilt_gtk(argv[1], argv[2])))
            return 0
        if what == "look":                                         # anyone may ask
            say(look(root))
            return 0
        if what == "state":
            say({"state": load_state(root), "have": source(root), "auto": auto_wanted(root), "canGoBack": (state_dir(root) / "previous/undo.json").is_file()})
            return 0
        if os.geteuid() != 0 and str(root) == "/":
            print("This needs to be run as the administrator (Software Update asks for you).", file=sys.stderr)
            return 77
        if what in ("stage", "auto"):
            if what == "auto" and not auto_wanted(root):
                return 0
            staged = stage(root, log=lambda t: print(t, flush=True), force=what == "stage")
            if staged:
                mark_ready(root)
                print(f"Ready: Huginn OS {staged['date']} ({staged['sha'][:7]}) goes in at the next start-up.")
            else:
                print("Huginn OS is up to date.")
            return 0
        if what in ("apply", "apply-at-start"):
            if what == "apply-at-start" and not (state_dir(root) / "ready").is_file():
                return 0
            st = load_state(root)
            kit = Path((st.get("staged") or {}).get("kit", "")) if isinstance(st.get("staged"), dict) else None
            mine = Path(__file__).resolve()
            newer = kit / "apps/huginn_osupdate.py" if kit else None
            if newer is not None and newer.is_file() and newer.resolve() != mine and os.environ.get("HUGINN_OSUPDATE_HANDED") != "1":
                # the version being installed knows best how it is installed: hand over to its own copy of this
                return subprocess.call([sys.executable, str(newer), what], env={**os.environ, "HUGINN_OSUPDATE_HANDED": "1"})
            done = apply(root, log=lambda t: print(t, flush=True))
            print(f"Huginn OS is now {done['date']} ({done['sha'][:7]}): {done['written']} file{'' if done['written'] == 1 else 's'} put in place, {done['removed']} taken away."
                  + (f" Left alone because you changed them: {', '.join(done['kept'][:6])}." if done["kept"] else "")
                  + ("" if done["compositor"] == "replaced" else f" The compositor: {done['compositor']}.")
                  + ("" if done.get("qt", "replaced") in ("replaced", "already this version's") else f" Qt apps' look: {done['qt']}.")
                  + ("" if done.get("gtk", "replaced") in ("replaced", "already this version's") else f" Old GTK apps' menus: {done['gtk']}.")
                  + (f" Not everything afterwards worked: {'; '.join(done['failed'][:3])}." if done["failed"] else ""))
            return 0
        if what == "back":
            done = back(root)
            print(f"Huginn OS went back to {done['date'] or 'the version before'} ({done['commit'][:7] or 'as installed'}).")
            return 0
        if what in ("auto-on", "auto-off"):
            conf = root / "etc/huginn/os-update.conf"
            conf.parent.mkdir(parents=True, exist_ok=True)
            conf.write_text(f"auto: {'yes' if what == 'auto-on' else 'no'}\n", encoding="utf-8")
            return 0
        print("huginn-os-update: look | state | stage | apply | back | auto | auto-on | auto-off", file=sys.stderr)
        return 64
    except Problem as why:
        try:
            if what in ("stage", "auto", "apply", "apply-at-start") and (os.geteuid() == 0 or str(root) != "/"):
                save_state(root, problem=str(why), checked=int(time.time()))
                if what == "apply-at-start":
                    mark_ready(root, False)                        # (a start-up never tries the same broken update twice)
        except OSError:
            pass
        print(str(why), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
