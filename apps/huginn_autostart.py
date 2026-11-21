#!/usr/bin/env python3
"""Programs that start when you sign in (XDG autostart), for Huginn's session, and how heavy each is.

Huginn's session starts its own helpers itself (huginn-session-apps); this starts the rest: what you or an app put in
~/.config/autostart (Steam's "start with the computer", Discord, Settings › Default Apps › Start-up apps) and the
system's own entries (/etc/xdg/autostart) that are for this desktop and that Huginn doesn't already do another way.

    huginn_autostart.py run        at sign-in (huginn-session-apps): start them, then measure each one's first minute
    huginn_autostart.py list       what would start, as JSON

Each program is started in a session of its own (setsid), so everything it starts can be found again by that session
number. A minute after sign-in, the processor time and disk reading of all of it are added up and each program gets an
impact, as Windows' Task Manager gives one: High (more than a second of processor or 3 MB read), Medium (more than
0.3 s or 300 KB), else Low. System Monitor's Startup view shows them, with turning each off and on.

Turning one off is the XDG way: a copy in ~/.config/autostart with Hidden=true (for the system's own, that hides it
for you only); on again, Hidden=false.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
STATE = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local/state") / "huginn" / "startup.json"
DESKTOPS = {"Huginn"}
MEASURE_S = 60
# The system's entries Huginn already covers another way (its own password prompt, network, Bluetooth and sound; the
# accessibility bus and KDE Connect start when something asks for them; the folders are made by the session).
COVERED = re.compile(r"^(at-spi-dbus-bus|xdg-user-dirs|orca-autostart|geoclue-demo-agent|org\.kde\.kdeconnect\.daemon|polkit-.*|"
                     r".*polkit.*agent.*|nm-applet|blueman|pulseaudio|gnome-keyring-.*|org\.kde\..*|kde.*|xembedsniproxy|baloo.*|"
                     r"powerdevil|gsettings-data-convert|user-dirs-update-gtk|print-applet|spice-vdagent)\.desktop$")
CODES = re.compile(r"%[fFuUdDnNickvm]")


def system_dirs() -> list:
    return [Path(d) / "autostart" for d in (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":") if d]


def read_entry(path: Path) -> dict:
    out, section = {}, ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for line in text.splitlines():
        if line.startswith("["):
            section = line.strip()
            continue
        if section == "[Desktop Entry]" and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out.setdefault(k.strip(), v.strip())
    return out


def _for_here(e: dict) -> bool:
    only = {d for d in e.get("OnlyShowIn", "").split(";") if d}
    never = {d for d in e.get("NotShowIn", "").split(";") if d}
    return (not only or bool(only & DESKTOPS)) and not (never & DESKTOPS)


def _condition(e: dict) -> bool:
    cond = e.get("AutostartCondition", "").split()
    if not cond:
        return True
    if cond[0] in ("if-exists", "unless-exists") and len(cond) > 1:
        there = (CONFIG / cond[1]).exists()
        return there if cond[0] == "if-exists" else not there
    return False                                             # GNOME's GSettings conditions and the like: not ours


def argv_of(e: dict) -> list:
    """The command an entry runs, its %-codes taken out."""
    cmd = CODES.sub("", e.get("Exec", "")).replace("%%", "%")
    try:
        return shlex.split(cmd)
    except ValueError:
        return []


def entries(config: Path = None, sysdirs: list = None) -> list:
    """Every sign-in program for this desktop, yours first: {id, name, comment, icon, exec, enabled, mine, system,
    path, runs (it would start), why (why not, if it wouldn't)}."""
    config = config or CONFIG
    found = {}
    for d in (sysdirs if sysdirs is not None else system_dirs()):
        for f in sorted(d.glob("*.desktop")) if d.is_dir() else []:
            if f.name not in found:
                found[f.name] = {"system": f}
    mine_dir = config / "autostart"
    for f in sorted(mine_dir.glob("*.desktop")) if mine_dir.is_dir() else []:
        found.setdefault(f.name, {})["mine"] = f
    out = []
    for ident, where in found.items():
        path = where.get("mine") or where["system"]
        e = read_entry(path)
        if not e or e.get("Type", "Application") != "Application":
            continue
        if "mine" not in where and (COVERED.match(ident) or not _for_here(e)):
            continue                                         # the system's, for another desktop or done by Huginn
        enabled = e.get("Hidden", "false") != "true" and e.get("X-GNOME-Autostart-enabled", "true") != "false"
        why = ""
        argv = argv_of(e)
        if not argv:
            why = "Its command can't be read."
        elif e.get("TryExec") and not shutil.which(e["TryExec"]):
            why = "Its program isn't installed any more."
        elif not shutil.which(argv[0]) and not os.path.isfile(argv[0]):
            why = "Its program isn't installed any more."
        elif not _for_here(e):
            why = "It's made for another desktop."
        elif not _condition(e):
            why = "It only starts on other desktops, when a setting there is on."
        elif e.get("Terminal") == "true":
            why = "It runs in a terminal, which sign-in doesn't open."
        out.append({"id": ident, "name": e.get("Name") or ident[:-8], "comment": e.get("Comment", ""), "icon": e.get("Icon", ""),
                    "exec": " ".join(argv), "enabled": enabled, "mine": "mine" in where, "system": "system" in where,
                    "path": str(path), "runs": enabled and not why, "why": why,
                    "delay": float(e.get("X-GNOME-Autostart-Delay", "0") or 0) if re.fullmatch(r"\d+(\.\d+)?", e.get("X-GNOME-Autostart-Delay", "0") or "0") else 0.0})
    out.sort(key=lambda x: (not x["mine"], x["name"].lower()))
    return out


def set_enabled(ident: str, on: bool, config: Path = None, sysdirs: list = None) -> str:
    """Turn one on or off for you: "" or why not."""
    config = config or CONFIG
    if "/" in ident or not ident.endswith(".desktop"):
        return "That isn't a sign-in program."
    mine = config / "autostart" / ident
    if not mine.exists():
        src = next((d / ident for d in (sysdirs if sysdirs is not None else system_dirs()) if (d / ident).is_file()), None)
        if src is None:
            return "It isn't there any more."
        mine.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, mine)
    # its switch, right under the [Desktop Entry] line (GNOME's own switch for it taken out: one switch)
    out, section, placed = [], "", False
    for line in mine.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("["):
            section = line.strip()
            out.append(line)
            if section == "[Desktop Entry]" and not placed:
                out.append(f"Hidden={'false' if on else 'true'}")
                placed = True
            continue
        if section == "[Desktop Entry]" and re.match(r"^\s*(Hidden|X-GNOME-Autostart-enabled)\s*=", line):
            continue
        out.append(line)
    if not placed:
        out = ["[Desktop Entry]", f"Hidden={'false' if on else 'true'}"] + out
    tmp = mine.with_suffix(".desktop.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(tmp, mine)
    return ""


def remove(ident: str, config: Path = None, sysdirs: list = None) -> str:
    """Take one of yours out of sign-in (the system's own can only be turned off)."""
    config = config or CONFIG
    mine = config / "autostart" / ident
    if "/" in ident or not mine.is_file():
        return "That isn't one of yours."
    if any((d / ident).is_file() for d in (sysdirs if sysdirs is not None else system_dirs())):
        return set_enabled(ident, False, config, sysdirs)
    mine.unlink()
    return ""


# ------------------------------------------------------------------------------------------- how heavy each is
def impact(cpu_s: float, disk: float) -> str:
    """Windows' measure: high over a second of processor or 3 MB read, medium over 0.3 s or 300 KB, else low."""
    if cpu_s > 1.0 or disk > 3e6:
        return "high"
    if cpu_s > 0.3 or disk > 3e5:
        return "medium"
    return "low"


def usage_of(sids: set, proc: Path = Path("/proc")) -> dict:
    """{sid: {cpu (s), disk (bytes read), memory (bytes), count}} for the processes in those sessions now."""
    ticks = os.sysconf("SC_CLK_TCK")
    page = os.sysconf("SC_PAGE_SIZE")
    out = {s: {"cpu": 0.0, "disk": 0, "memory": 0, "count": 0} for s in sids}
    for entry in os.scandir(proc):
        if not entry.name.isdigit():
            continue
        try:
            stat = Path(entry.path, "stat").read_text()
            rest = stat[stat.rindex(")") + 2:].split()
            sid = int(rest[3])
            if sid not in out:
                continue
            o = out[sid]
            o["cpu"] += (int(rest[11]) + int(rest[12])) / ticks
            o["memory"] += int(rest[21]) * page
            o["count"] += 1
            try:
                io = dict(line.split(": ") for line in Path(entry.path, "io").read_text().splitlines())
                o["disk"] += int(io.get("read_bytes", 0))
            except (OSError, ValueError):
                pass
        except (OSError, ValueError, IndexError):
            continue
    return out


def _save(data: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, STATE)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def run(measure: float = MEASURE_S) -> int:
    """Sign-in: start every program that should, then a minute on, write down how heavy each was."""
    now = time.time()
    state = {"signin": now, "apps": {}}
    started = {}
    todo = sorted((e for e in entries() if e["runs"]), key=lambda e: e["delay"])
    t0 = time.monotonic()
    for e in todo:
        wait = e["delay"] - (time.monotonic() - t0)
        if wait > 0:
            time.sleep(min(wait, 30))
        try:
            p = subprocess.Popen(argv_of(read_entry(Path(e["path"]))), start_new_session=True, cwd=str(HOME),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError as err:
            state["apps"][e["id"]] = {"name": e["name"], "failed": str(err)[:160]}
            continue
        started[e["id"]] = p
        state["apps"][e["id"]] = {"name": e["name"], "pid": p.pid, "sid": p.pid, "started": time.time()}
        print(f"huginn-autostart: started {e['name']} ({p.pid})", file=sys.stderr, flush=True)
    _save(state)
    if not started:
        return 0
    end = time.monotonic() + measure
    # keep the most each program reached in the minute (a launcher that hands over and quits takes its share with it)
    seen = {}
    while time.monotonic() < end:
        time.sleep(5)
        use = usage_of({r["sid"] for r in state["apps"].values() if "sid" in r})
        for ident, r in state["apps"].items():
            if "sid" not in r:
                continue
            u = use.get(r["sid"], {})
            best = seen.setdefault(ident, {"cpu": 0.0, "disk": 0, "memory": 0})
            best["cpu"] = max(best["cpu"], u.get("cpu", 0.0))
            best["disk"] = max(best["disk"], u.get("disk", 0))
            best["memory"] = max(best["memory"], u.get("memory", 0))
        for p in started.values():
            p.poll()                                         # (no zombies from programs that hand over and leave)
    for ident, r in state["apps"].items():
        if ident in seen:
            r.update(cpu=round(seen[ident]["cpu"], 2), disk=seen[ident]["disk"], memory=seen[ident]["memory"],
                      impact=impact(seen[ident]["cpu"], seen[ident]["disk"]))
    _save(state)
    return 0


def report() -> dict:
    """For System Monitor: each sign-in program with its impact at the last sign-in and what it uses now."""
    state = load_state()
    rows = entries()
    sids = {r["sid"] for r in (state.get("apps") or {}).values() if isinstance(r, dict) and "sid" in r}
    now = usage_of(sids) if sids else {}
    for e in rows:
        r = (state.get("apps") or {}).get(e["id"]) or {}
        e["impact"] = r.get("impact", "")
        e["cpu"] = r.get("cpu", -1)
        e["disk"] = r.get("disk", -1)
        e["failed"] = r.get("failed", "")
        u = now.get(r.get("sid", -1), {})
        e["running"] = u.get("count", 0) > 0
        e["memoryNow"] = u.get("memory", 0)
    return {"entries": rows, "signin": state.get("signin", 0), "measured": any(e["impact"] for e in rows)}


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        if os.environ.get("XDG_SESSION_DESKTOP", "huginn") != "huginn" and "Huginn" not in os.environ.get("XDG_CURRENT_DESKTOP", ""):
            return 0                                         # another desktop runs its own
        return run()
    print(json.dumps(report() if len(sys.argv) > 1 and sys.argv[1] == "report" else entries(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
