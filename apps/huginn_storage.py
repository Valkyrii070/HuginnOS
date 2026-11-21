#!/usr/bin/env python3
"""Settings › Storage: how full the drive is, and every app you installed with the space it takes (the app itself and
what it keeps in your home folder), biggest first, each with a button that takes it off. Steam's games are listed
too, from Steam's own records, since on a gaming computer they're most of the drive.

    load()            -> {"disk": {...}, "apps": [...], "games": [...], "shared": bytes}
    uninstall(app)    -> "" or why not
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

HOME = Path.home()
STEAM_ROOTS = [HOME / ".var/app/com.valvesoftware.Steam/.local/share/Steam", HOME / ".local/share/Steam", HOME / ".steam/steam"]
UNITS = {"bytes": 1, "byte": 1, "b": 1, "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4,
         "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4}


def parse_size(text: str) -> int:
    """flatpak's sizes ("1.2 GB", "512 bytes", "12,5 MB") back into bytes; 0 when it can't tell."""
    m = re.match(r"^\s*([\d.,  ]+)\s*([A-Za-z]+)\s*$", text or "")
    if not m:
        return 0
    num = m.group(1).replace(" ", "").replace(" ", "")
    if "," in num and "." not in num:
        num = num.replace(",", ".")
    num = num.replace(",", "")
    try:
        return int(float(num) * UNITS.get(m.group(2).lower(), 0))
    except ValueError:
        return 0


def folder_size(path: Path, budget: float = 4.0) -> int:
    """What a folder takes, adding up its files (not following links); stops counting after `budget` seconds."""
    total, until = 0, time.monotonic() + budget
    stack = [path]
    while stack:
        if time.monotonic() > until:
            break
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_blocks * 512
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def disk(path: Path = HOME) -> dict:
    try:
        u = shutil.disk_usage(path)
        return {"total": u.total, "used": u.used, "free": u.free}
    except OSError:
        return {"total": 0, "used": 0, "free": 0}


def flatpak_apps(run=subprocess.run, which=shutil.which) -> list:
    """[{id, name, size, where}] for the apps flatpak has (not the runtimes they share)."""
    fp = which("flatpak")
    if not fp:
        return []
    try:
        out = run([fp, "list", "--app", "--columns=application,name,size,installation"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    apps = []
    for line in out.splitlines():
        f = line.split("\t")
        if len(f) < 4 or "." not in f[0]:
            continue
        apps.append({"id": f[0], "name": f[1] or f[0], "size": parse_size(f[2]), "where": f[3].strip() or "system"})
    return apps


def shared_size(run=subprocess.run, which=shutil.which) -> int:
    """What the runtimes take (the shared parts apps are built on)."""
    fp = which("flatpak")
    if not fp:
        return 0
    try:
        out = run([fp, "list", "--runtime", "--columns=size"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    return sum(parse_size(line) for line in out.splitlines())


def _acf(text: str) -> dict:
    """The few keys wanted from one of Steam's appmanifest_*.acf files."""
    out = {}
    for key in ("appid", "name", "SizeOnDisk", "installdir"):
        m = re.search(r'"%s"\s+"([^"]*)"' % key, text)
        if m:
            out[key] = m.group(1)
    return out


def steam_games(roots: list = None) -> list:
    """[{appid, name, size, library}] from every Steam library this person has (libraryfolders.vdf lists the others)."""
    libraries = []
    for root in roots or STEAM_ROOTS:
        apps = root / "steamapps"
        if apps.is_dir() and apps.resolve() not in [l.resolve() for l in libraries]:
            libraries.append(apps)
            try:
                vdf = (apps / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
                for p in re.findall(r'"path"\s+"([^"]+)"', vdf):
                    extra = Path(p) / "steamapps"
                    if extra.is_dir() and extra.resolve() not in [l.resolve() for l in libraries]:
                        libraries.append(extra)
            except OSError:
                pass
    games, seen = [], set()
    for lib in libraries:
        for acf in sorted(lib.glob("appmanifest_*.acf")):
            try:
                g = _acf(acf.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if not g.get("appid") or g["appid"] in seen:
                continue
            seen.add(g["appid"])
            name = g.get("name", "")
            if name.startswith(("Proton", "Steam Linux Runtime", "Steamworks Common")):
                continue                                         # Steam's own tools: Steam looks after those
            games.append({"appid": g["appid"], "name": name or g["appid"], "size": int(g.get("SizeOnDisk") or 0), "library": str(lib)})
    return sorted(games, key=lambda g: -g["size"])


def load(run=subprocess.run, which=shutil.which, data_budget: float = 2.0) -> dict:
    apps = flatpak_apps(run, which)
    for a in apps:
        a["data"] = folder_size(HOME / ".var/app" / a["id"], data_budget)
        a["icon"] = "image://sysicon/" + a["id"]
    games = steam_games()
    # Steam's games live in its data: shown once, as games, not counted again as Steam's own
    in_games = sum(g["size"] for g in games if "com.valvesoftware.Steam" in g["library"])
    for a in apps:
        if a["id"] == "com.valvesoftware.Steam":
            a["data"] = max(0, a["data"] - in_games)
    apps.sort(key=lambda a: -(a["size"] + a["data"]))
    return {"disk": disk(), "apps": apps, "games": games, "shared": shared_size(run, which), "flatpak": bool(which("flatpak"))}


def uninstall(app: dict, run=subprocess.run, which=shutil.which) -> str:
    """Take an app off (its files in your home stay unless `app["data"]` asks: then they go too)."""
    fp = which("flatpak")
    if not fp:
        return "Flatpak isn't installed."
    argv = [fp, "uninstall", "-y", "--noninteractive", "--" + ("user" if app.get("where") == "user" else "system"), app["id"]]
    try:
        done = run(argv, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as err:
        return f"It wasn't uninstalled ({err})."
    if done.returncode != 0:
        tail = [ln.strip() for ln in (done.stderr or done.stdout or "").splitlines() if ln.strip()]
        return "It wasn't uninstalled" + (f" ({tail[-1][:140]})" if tail else "") + "."
    if app.get("dropData"):
        shutil.rmtree(HOME / ".var/app" / app["id"], ignore_errors=True)
    return ""


def remove_unused(run=subprocess.run, which=shutil.which) -> str:
    """Runtimes no app uses any more (left behind by apps taken off)."""
    fp = which("flatpak")
    if not fp:
        return "Flatpak isn't installed."
    msgs = []
    for where in ("--user", "--system"):
        try:
            done = run([fp, "uninstall", "--unused", "-y", "--noninteractive", where], capture_output=True, text=True, timeout=900)
        except (OSError, subprocess.SubprocessError) as err:
            return f"Nothing was removed ({err})."
        if done.returncode != 0:
            tail = [ln.strip() for ln in (done.stderr or done.stdout or "").splitlines() if ln.strip()]
            if tail:
                msgs.append(tail[-1][:140])
    return "; ".join(msgs)


def steam_uninstall(appid: str) -> str:
    """Steam asks first and takes the game off itself (it knows its own files, cloud saves and other libraries)."""
    url = f"steam://uninstall/{int(appid)}"
    for argv in (["flatpak", "run", "com.valvesoftware.Steam", url], ["steam", url]):
        if shutil.which(argv[0]) and (argv[0] != "flatpak" or (HOME / ".var/app/com.valvesoftware.Steam").exists() or
                                       Path("/var/lib/flatpak/app/com.valvesoftware.Steam").exists()):
            try:
                subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return ""
            except OSError:
                continue
    return "Steam isn't installed, so its games can't be taken off from here."
