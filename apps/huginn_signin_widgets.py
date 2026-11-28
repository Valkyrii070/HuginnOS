"""Widgets on Huginn's sign-in screen: what there is, where a person's choices and their data live, and the checks
every piece applies to them.

    ~/.config/huginn/signin-widgets.json     which widgets, in order, their sizes, and whether each may show before
                                             sign-in; and the person's own ways for the screen (OPTIONS: greet them
                                             by name, where the time sits, the wake). Settings › Sign-In Screen
                                             writes it
    ~/.cache/huginn/signin-snapshot.json     the latest data of the widgets that may show before sign-in, and only
                                             theirs (the desktop, huginn_shell.py, writes it every minute)

The sign-in service (huginn_signind.py) reads both as the person, never as root, keeps what `merge()` lets through and
hands that to the sign-in screen. A widget that may not show before sign-in reaches the screen as its name alone.

Nothing here reaches the network. The data is what the desktop last saw: the weather Weather last fetched, the next
events in Calendar, what last played, downloads that finished.

Widgets from apps. An app declares one in a small file, and keeps its data in another; no code of the app's ever runs
on the sign-in screen, which draws the app's words in one of its own templates:

    /usr/share/huginn/signin-widgets/<id>.json             what the widget is (installed with the app), or
    ~/.local/share/huginn/signin-widgets/<id>.json         for one person (an app installed in their home)
        {"id": "com.example.raid", "name": "Raid Night", "app": "Example Studio", "about": "Who's in tonight",
         "template": "status" | "list", "sizes": ["small", "wide"], "size": "wide", "before": false,
         "accent": "#E8505B"}
    ~/.cache/huginn/signin-widgets/<id>.json               what it says now, written by the app as it likes (or
                                                           with publish(), or `huginn-signin-widget set …`)
        status: {"big": "Build passed", "small": "huginn-os · Build", "state": "good" | "bad" | "", "at": <epoch>}
        list:   {"rows": [["20:00", "Raid: Molten Core"], …up to four], "at": <epoch>}

Every piece is checked and cut short here (ids, words, colours), so an odd or hostile file is a widget with less in it,
never anything more. In a person's layout an app's widget is "app:<id>", with its name, template and colour kept
beside it, so the sign-in service needs nothing of the app's to show it.
"""
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

# The widgets there are. `before`: whether a new one may show before sign-in (off for anything about your day).
CATALOG = {
    "today": {"name": "Today", "about": "Your next events, from Calendar", "sizes": ["small", "wide", "tall"], "size": "wide", "before": False},
    "weather": {"name": "Weather", "about": "Your first place in Weather", "sizes": ["small", "wide"], "size": "small", "before": True},
    "pc": {"name": "This PC", "about": "Updates, finished downloads and the battery", "sizes": ["small", "wide"], "size": "small", "before": True},
    "music": {"name": "Now Playing", "about": "What last played", "sizes": ["small", "wide"], "size": "wide", "before": False},
}
MOST = 6                                     # widgets at most (two columns, three rows of small ones)
# A person's own ways for the sign-in screen, while they're the one chosen in its dock (and on their lock screen):
#   greet   "Good morning, Astrid" rather than "Good morning"
#   clock   where the time sits without widgets: "centre" or "left" (with widgets it's always at the left)
#   wake    the wake when the password is right (the dock filling, the time blooming away); off, a plain fade
OPTIONS = {"greet": False, "clock": "centre", "wake": True}
LONGEST = 120                                # characters in any one piece of text


APP_DIRS = (Path("/usr/share/huginn/signin-widgets"),)      # (and ~/.local/share/huginn/signin-widgets, the person's own)
TEMPLATES = ("status", "list")
SIZES = ("small", "wide", "tall")
APP_ID = re.compile(r"[a-z0-9][a-z0-9.-]{2,62}")
ACCENT = re.compile(r"#[0-9A-Fa-f]{6}")


def layout_path(home) -> Path:
    return Path(home) / ".config/huginn/signin-widgets.json"


def snapshot_path(home) -> Path:
    return Path(home) / ".cache/huginn/signin-snapshot.json"


def _text(v, most: int = LONGEST) -> str:
    return str(v)[:most] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


# ---------------------------------------------------------------------------------------------------------- the layout
def app_id(kind) -> str:
    """The app widget's id in a layout's kind ("app:<id>"), or "" for anything else."""
    if isinstance(kind, str) and kind.startswith("app:") and APP_ID.fullmatch(kind[4:]):
        return kind[4:]
    return ""


def clean_layout(raw) -> list:
    """[{kind, size, before}] from whatever the file held: known kinds, each once, sizes they can have, at most MOST.
    An app's widget ("app:<id>") also keeps {name, template, accent}, checked."""
    rows = raw.get("widgets") if isinstance(raw, dict) else None
    out, seen = [], set()
    for w in rows if isinstance(rows, list) else []:
        if not isinstance(w, dict) or not isinstance(w.get("kind"), str) or w["kind"] in seen:
            continue
        kind = w["kind"]
        if kind in CATALOG:
            size = w.get("size") if w.get("size") in CATALOG[kind]["sizes"] else CATALOG[kind]["size"]
            out.append({"kind": kind, "size": size, "before": w.get("before") is True})
        elif app_id(kind):
            name = _text(w.get("name", ""), 40).strip() or app_id(kind)
            out.append({"kind": kind, "size": w.get("size") if w.get("size") in SIZES else "small", "before": w.get("before") is True,
                        "name": name, "template": w.get("template") if w.get("template") in TEMPLATES else "status",
                        "accent": w.get("accent") if isinstance(w.get("accent"), str) and ACCENT.fullmatch(w["accent"]) else ""})
        else:
            continue
        seen.add(kind)
        if len(out) >= MOST:
            break
    return out


# -------------------------------------------------------------------------------------------- widgets from apps
def clean_manifest(raw, where: str = "") -> dict:
    """An app's declaration of a widget, checked; {} when it isn't one."""
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not APP_ID.fullmatch(raw["id"]):
        return {}
    name = _text(raw.get("name", ""), 40).strip()
    if not name:
        return {}
    sizes = [z for z in SIZES if isinstance(raw.get("sizes"), list) and z in raw["sizes"]] or ["small"]
    return {"id": raw["id"], "name": name, "app": _text(raw.get("app", ""), 40).strip(), "about": _text(raw.get("about", ""), 80).strip(),
            "template": raw.get("template") if raw.get("template") in TEMPLATES else "status", "sizes": sizes,
            "size": raw.get("size") if raw.get("size") in sizes else sizes[0], "before": raw.get("before") is True,
            "accent": raw.get("accent") if isinstance(raw.get("accent"), str) and ACCENT.fullmatch(raw["accent"]) else "", "where": where}


def app_widgets(home=None, dirs=APP_DIRS) -> dict:
    """{id: declaration} of the widgets apps bring: the system's, then the person's own (which can't take a system id)."""
    found = {}
    places = [(d, "system") for d in dirs] + ([(Path(home) / ".local/share/huginn/signin-widgets", "yours")] if home else [])
    for folder, where in places:
        try:
            files = sorted(folder.glob("*.json"))[:64]
        except OSError:
            continue
        for f in files:
            try:
                if not f.is_file() or f.stat().st_size > 16 * 1024:
                    continue
                m = clean_manifest(json.loads(f.read_text(encoding="utf-8")), where)
            except (OSError, ValueError):
                continue
            if m and m["id"] not in found:
                found[m["id"]] = m
    return found


def display_name(m: dict) -> str:
    """"Code · Last Build": the app's name before the widget's, where it gave one (40 characters at most)."""
    return ((m["app"] + " · ") if m.get("app") and m["app"].lower() not in m["name"].lower() else "")[:20] + m["name"]


def app_data_path(home, wid: str) -> Path:
    return Path(home) / ".cache/huginn/signin-widgets" / f"{wid}.json"


def clean_app_data(d) -> dict:
    """What an app's widget says, as short plain text: {big, small, state, rows, at} (whichever it has)."""
    if not isinstance(d, dict):
        return {}
    at = d.get("at")
    out = {"big": _text(d.get("big", ""), 60), "small": _text(d.get("small", ""), 80),
           "state": d.get("state") if d.get("state") in ("good", "bad") else "",
           "rows": [[_text(r[0], 40), _text(r[1], 60)] for r in (d.get("rows") if isinstance(d.get("rows"), list) else [])
                    if isinstance(r, list) and len(r) == 2][:4],
           "at": int(at) if isinstance(at, (int, float)) and not isinstance(at, bool) and 0 <= at < 1e11 else 0}
    return out if out["big"] or out["small"] or out["rows"] else {}


def publish(wid: str, home=None, **fields) -> bool:
    """For apps: what their widget says now (see the top of this file). Written only when it changed; True if it was.
    Without "at", now."""
    if not APP_ID.fullmatch(wid or ""):
        raise ValueError(f"not a widget id: {wid!r}")
    data = clean_app_data({"at": int(time.time())} | fields)
    path = app_data_path(home or Path.home(), wid)
    if not data:
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed
    text = json.dumps(data, sort_keys=True)
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        if {k: v for k, v in old.items() if k != "at"} == {k: v for k, v in data.items() if k != "at"} and "at" not in fields:
            return False
    except (OSError, ValueError, AttributeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{wid}.json.new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return True


def clean_options(raw) -> dict:
    """The person's own ways (OPTIONS) from whatever the file held; anything missing or odd is the default."""
    raw = raw if isinstance(raw, dict) else {}
    return {"greet": raw.get("greet") is True, "clock": "left" if raw.get("clock") == "left" else "centre",
            "wake": raw.get("wake") is not False}


def _read(home) -> dict:
    try:
        raw = json.loads(layout_path(home).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def read_layout(home) -> list:
    return clean_layout(_read(home))


def read_options(home) -> dict:
    return clean_options(_read(home))


def _save(home, rows: list, options: dict) -> None:
    path = layout_path(home)
    if not rows and options == OPTIONS:                      # nothing chosen: no file at all
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".signin-widgets.json.new")
    tmp.write_text(json.dumps({"v": 1, "widgets": rows, **options}, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def write_layout(home, widgets: list, apps: dict = None) -> list:
    """Saves the person's widgets (cleaned), keeping their other choices. Returns what was saved. An app's widget takes
    its name, template and colour from its declaration (apps: app_widgets()) when it's installed, else keeps its own."""
    if apps:
        widgets = [w | {"name": display_name(apps[app_id(w.get("kind"))])} | {k: apps[app_id(w.get("kind"))][k] for k in ("template", "accent")}
                   if isinstance(w, dict) and app_id(w.get("kind")) in apps else w for w in widgets]
    rows = clean_layout({"widgets": widgets})
    _save(home, rows, read_options(home))
    return rows


def write_options(home, **changes) -> dict:
    """Changes some of the person's own ways (OPTIONS), keeping their widgets. Returns all of them as saved."""
    now = read_options(home)
    options = clean_options(now | {k: v for k, v in changes.items() if k in OPTIONS})
    _save(home, read_layout(home), options)
    return options


def new_widget(kind: str) -> dict:
    c = CATALOG[kind]
    return {"kind": kind, "size": c["size"], "before": c["before"]}


# ------------------------------------------------------------------------------------------------- the data (desktop)
def read_weather(home) -> dict:
    """The first place in Weather, from Weather's own file: {place, temp, words, high, low, at}."""
    try:
        saved = json.loads((Path(home) / ".local/share/huginn/weather.json").read_text(encoding="utf-8"))
        at = int(saved.get("at", 0))
        place = saved["places"][at]
        fc = saved.get("data", {}).get(str(at)) or {}
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return {}
    try:
        from huginn_more import WMO
    except Exception:                                       # noqa: BLE001  (only the words are missing then)
        WMO = {}
    cur, daily = fc.get("current") or {}, fc.get("daily") or {}

    def deg(v):
        return "" if not isinstance(v, (int, float)) else f"{round(v)}°".replace("-", "−")
    out = {"place": _text(place.get("name", "")), "temp": deg(cur.get("temperature_2m")),
           "words": WMO.get(cur.get("weather_code"), ("", ""))[0], "high": "", "low": "", "at": 0}
    today = dt.date.today().isoformat()
    for i, day in enumerate(daily.get("time") or []):
        if day == today:
            out["high"] = deg((daily.get("temperature_2m_max") or [None] * (i + 1))[i])
            out["low"] = deg((daily.get("temperature_2m_min") or [None] * (i + 1))[i])
    try:
        out["at"] = int(dt.datetime.fromisoformat(cur.get("time", "")).timestamp())
    except (ValueError, TypeError):
        out["at"] = int(time.time())
    return out if out["temp"] else {}


def read_today(calendar=None) -> dict:
    """The next events in Calendar and Reminders: {events: [{title, date, time, reminder}]}."""
    try:
        if calendar is None:
            from huginn_app import Calendar
            calendar = Calendar(False)
        rows = list(calendar.upcoming)[:6]
    except Exception:                                       # noqa: BLE001  (Calendar not installed, or its file unreadable)
        return {"events": []}
    return {"events": [{"title": _text(e.get("title", "")), "date": _text(e.get("date", ""), 10), "time": _text(e.get("time", ""), 5),
                        "reminder": bool(e.get("reminder"))} for e in rows if isinstance(e, dict)]}


def read_pc(home) -> dict:
    """Downloads that finished in the last day (files in Downloads, not ones still coming)."""
    folder, n, now = Path(home) / "Downloads", 0, time.time()
    try:
        for f in folder.iterdir():
            if f.name.startswith(".") or f.suffix in (".part", ".crdownload", ".download"):
                continue
            try:
                if now - f.stat().st_mtime < 86400 and f.is_file():
                    n += 1
            except OSError:
                continue
    except OSError:
        pass
    return {"downloads": n, "at": int(now)}


def collect(home, kinds, music: dict = None, calendar=None) -> dict:
    """The data of these widgets, as the desktop sees it now."""
    out = {}
    for kind in kinds:
        if kind == "weather":
            w = read_weather(home)
            if w:
                out["weather"] = w
        elif kind == "today":
            out["today"] = read_today(calendar)
        elif kind == "pc":
            out["pc"] = read_pc(home)
        elif kind == "music" and music:
            out["music"] = {k: _text(music.get(k, "")) for k in ("title", "sub", "app")} | {"at": int(music.get("at") or time.time())}
        elif app_id(kind):
            try:
                path = app_data_path(home, app_id(kind))
                d = clean_app_data(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() and path.stat().st_size < 16 * 1024 else {}
            except (OSError, ValueError):
                d = {}
            if d:
                out[kind] = d
    return out


def write_snapshot(home, data: dict) -> bool:
    """The desktop's latest data for the sign-in screen (only yours to read). True when it changed."""
    path = snapshot_path(home)
    if not data:
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed
    text = json.dumps({"v": 1, "data": data}, sort_keys=True)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".signin-snapshot.json.new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return True


# ------------------------------------------------------------------------------------------------- the sign-in service
def _clean_data(kind: str, d) -> dict:
    """Only the fields a tile draws, as plain short text and numbers."""
    if not isinstance(d, dict):
        return {}
    num = lambda v: int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) < 1e12 else 0  # noqa: E731
    if kind == "weather":
        out = {k: _text(d.get(k, ""), 40) for k in ("place", "temp", "words", "high", "low")} | {"at": num(d.get("at"))}
        return out if out["temp"] else {}
    if kind == "today":
        ev = d.get("events") if isinstance(d.get("events"), list) else []
        return {"events": [{"title": _text(e.get("title", "")), "date": _text(e.get("date", ""), 10), "time": _text(e.get("time", ""), 5),
                            "reminder": e.get("reminder") is True} for e in ev[:6] if isinstance(e, dict)]}
    if kind == "pc":
        return {"downloads": max(0, min(9999, num(d.get("downloads")))), "at": num(d.get("at"))}
    if kind == "music":
        out = {k: _text(d.get(k, "")) for k in ("title", "sub", "app")} | {"at": num(d.get("at"))}
        return out if out["title"] else {}
    if app_id(kind):
        return clean_app_data(d)
    return {}


def look_of(layout_text: str, settings_text: str = "") -> dict:
    """The person's own ways as the sign-in screen gets them: {greet, clock, wake}, wake being "full" or "fade" (off,
    or Reduce Motion on in Accessibility: ~/.config/huginn-shell/settings.json)."""
    try:
        opts = clean_options(json.loads(layout_text)) if layout_text else dict(OPTIONS)
    except ValueError:
        opts = dict(OPTIONS)
    try:
        settings = json.loads(settings_text) if settings_text else {}
        still = isinstance(settings, dict) and str(settings.get("reduceMotion", "")).lower() == "true"
    except ValueError:
        still = False
    return {"greet": opts["greet"], "clock": opts["clock"], "wake": "full" if opts["wake"] and not still else "fade"}


def settings_path(home) -> Path:
    return Path(home) / ".config/huginn-shell/settings.json"


def merge(layout_text: str, snapshot_text: str, system: dict = None) -> list:
    """What the sign-in screen gets for one person: their widgets in order, each {kind, name, size, private, data}.
    A private widget (not allowed before sign-in) carries its name and nothing else, whatever the snapshot holds."""
    try:
        layout = clean_layout(json.loads(layout_text)) if layout_text else []
    except ValueError:
        layout = []
    try:
        snap = json.loads(snapshot_text) if snapshot_text else {}
        snap = snap.get("data") if isinstance(snap, dict) and isinstance(snap.get("data"), dict) else {}
    except ValueError:
        snap = {}
    out = []
    for w in layout:
        if app_id(w["kind"]):
            row = {"kind": "app", "id": app_id(w["kind"]), "name": w["name"], "template": w["template"], "accent": w["accent"],
                   "size": w["size"], "private": not w["before"], "data": {}}
        else:
            row = {"kind": w["kind"], "name": CATALOG[w["kind"]]["name"], "size": w["size"], "private": not w["before"], "data": {}}
        if w["before"]:
            row["data"] = _clean_data(w["kind"], snap.get(w["kind"]))
            if w["kind"] == "pc" and system:
                row["data"]["update"] = _text(system.get("update", ""), 80)
        out.append(row)
    return out


def system_status(root=Path("/")) -> dict:
    """What This PC says that isn't anyone's: Huginn OS's own updates (huginn_osupdate.py's state, readable by all)."""
    try:
        st = json.loads((Path(root) / "var/lib/huginn-os-update/state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(st, dict):
        return {}
    if (Path(root) / "var/lib/huginn-os-update/ready").exists() and isinstance(st.get("staged"), dict):
        return {"update": "Update at next restart"}
    applied = st.get("applied") if isinstance(st.get("applied"), dict) else {}
    when = applied.get("when")
    if isinstance(when, (int, float)) and 0 <= time.time() - when < 2 * 86400:
        days = (dt.date.today() - dt.date.fromtimestamp(when)).days
        return {"update": "Updated " + ("today" if days <= 0 else "yesterday" if days == 1 else "this week")}
    return {}


# --------------------------------------------------------------------------------------------- for apps: a command
USAGE = """huginn-signin-widget: what an app's sign-in widget says (see /usr/share/huginn/signin-widgets)

    huginn-signin-widget set <id> [--big TEXT] [--small TEXT] [--state good|bad] [--row LEFT RIGHT]... [--at EPOCH]
    huginn-signin-widget clear <id>
    huginn-signin-widget list                  the widgets apps bring here, and where they're declared
"""


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE, end="")
        return 0 if argv else 2
    if argv[0] == "list":
        for wid, m in app_widgets(Path.home()).items():
            print(f"{wid}\t{m['name']}\t{m['template']}\t{m['where']}")
        return 0
    if argv[0] in ("set", "clear") and len(argv) >= 2:
        wid, rest, fields = argv[1], argv[2:], {}
        if not APP_ID.fullmatch(wid):
            print(f"huginn-signin-widget: not a widget id: {wid}", file=sys.stderr)
            return 2
        if argv[0] == "clear":
            app_data_path(Path.home(), wid).unlink(missing_ok=True)
            return 0
        i = 0
        while i < len(rest):
            flag = rest[i]
            if flag in ("--big", "--small", "--state", "--at") and i + 1 < len(rest):
                fields[flag[2:]] = int(rest[i + 1]) if flag == "--at" and rest[i + 1].isdigit() else rest[i + 1]
                i += 2
            elif flag == "--row" and i + 2 < len(rest):
                fields.setdefault("rows", []).append([rest[i + 1], rest[i + 2]])
                i += 3
            else:
                print(USAGE, end="", file=sys.stderr)
                return 2
        publish(wid, **fields)
        return 0
    print(USAGE, end="", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
