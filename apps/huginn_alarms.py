"""Clock's alarms and world-clock cities: kept in ~/.config/huginn/clock.json, read by Clock (which edits them) and by
the shell's live island (which rings an alarm whether or not Clock is open: huginn_island.py).

An alarm: {"id", "time": "07:30", "days": [0..6 for Monday..Sunday; none: once], "label", "on"}. One that rings once
turns itself off when it has rung. Snoozing keeps "snooze": the moment (ISO) it rings again.
"""
import datetime as dt
import json
import os
import time
from pathlib import Path

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SNOOZE_MINUTES = 9
RING_FOR = 10 * 60               # an alarm nobody stops gives up after this long (seconds)
LATE = 10 * 60                   # one missed by more than this (the computer was asleep or off) isn't rung
DEFAULT_CITIES = [["Reykjavík", "Atlantic/Reykjavik"], ["London", "Europe/London"], ["New York", "America/New_York"],
                  ["Los Angeles", "America/Los_Angeles"], ["Tokyo", "Asia/Tokyo"], ["Sydney", "Australia/Sydney"]]


def path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn" / "clock.json"


def read() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    alarms = [a for a in data.get("alarms", []) if isinstance(a, dict) and valid_time(a.get("time", "")) and a.get("id")]
    cities = [c for c in data.get("cities", DEFAULT_CITIES) if isinstance(c, list) and len(c) == 2 and all(isinstance(x, str) for x in c)]
    return {"alarms": alarms, "cities": cities, "rang": data.get("rang") if isinstance(data.get("rang"), dict) else {}}


def write(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.part")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def change(edit) -> dict:
    data = read()
    edit(data)
    write(data)
    return data


def valid_time(text: str) -> bool:
    try:
        h, m = text.split(":")
        return len(h) == 2 and len(m) == 2 and 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except (ValueError, AttributeError):
        return False


def parse_time(text: str) -> str:
    """What someone typed as a time, as "HH:MM" ("" when it isn't one): 7, 730, 7:30, 7.30, 7:30 pm, 19:30."""
    t = (text or "").strip().lower().replace(".", ":").replace(" ", "")
    half = "pm" if t.endswith(("pm", "p")) else "am" if t.endswith(("am", "a")) else ""
    t = t.rstrip("apm")
    if ":" not in t:
        if not t.isdigit() or len(t) > 4:
            return ""
        t = (t + ":00") if len(t) <= 2 else (t[:-2] + ":" + t[-2:])
    try:
        h, m = (int(x) for x in t.split(":"))
    except ValueError:
        return ""
    if half:
        if not 1 <= h <= 12:
            return ""
        h = h % 12 + (12 if half == "pm" else 0)
    return f"{h:02d}:{m:02d}" if 0 <= h <= 23 and 0 <= m <= 59 else ""


def days_words(days: list) -> str:
    d = sorted(set(int(x) for x in days if 0 <= int(x) <= 6))
    if not d:
        return "Once"
    if d == list(range(7)):
        return "Every day"
    if d == [0, 1, 2, 3, 4]:
        return "Weekdays"
    if d == [5, 6]:
        return "Weekends"
    return ", ".join(DAY_NAMES[i] for i in d)


def next_ring(alarm: dict, now: dt.datetime):
    """When this alarm next rings (None when it's off)."""
    if not alarm.get("on"):
        return None
    snooze = alarm.get("snooze")
    if snooze:
        try:
            when = dt.datetime.fromisoformat(snooze)
            if when > now - dt.timedelta(seconds=LATE):
                return when
        except ValueError:
            pass
    h, m = (int(x) for x in alarm["time"].split(":"))
    days = set(int(x) for x in alarm.get("days") or [])
    for ahead in range(8):
        day = now.date() + dt.timedelta(days=ahead)
        when = dt.datetime.combine(day, dt.time(h, m))
        if when <= now or (days and day.weekday() not in days):
            continue
        return when
    return None


def until_words(when: dt.datetime, now: dt.datetime) -> str:
    mins = max(1, round((when - now).total_seconds() / 60))
    d, rest = divmod(mins, 1440)
    h, m = divmod(rest, 60)
    parts = ([f"{d} d"] if d else []) + ([f"{h} h"] if h else []) + ([f"{m} min"] if m and not d else [])
    return "in " + " ".join(parts)


def due(now: dt.datetime, ringing: dict) -> list:
    """Alarms to ring now: [(key, alarm)], key naming this ringing (the alarm and its moment). `ringing` maps the keys
    already ringing to when they started; one is rung when its moment has come within the last LATE seconds and it
    hasn't been rung for that moment already (kept in the file, so a shell started again doesn't ring it twice)."""
    data, out = read(), []
    for a in data["alarms"]:
        if not a.get("on"):
            continue
        moments = []
        if a.get("snooze"):
            try:
                moments.append(dt.datetime.fromisoformat(a["snooze"]))
            except ValueError:
                pass
        h, m = (int(x) for x in a["time"].split(":"))
        today = dt.datetime.combine(now.date(), dt.time(h, m))
        days = set(int(x) for x in a.get("days") or [])
        if not days or now.weekday() in days:
            moments.append(today)
        for when in moments:
            key = f"{a['id']}@{when.isoformat(timespec='minutes')}"
            if 0 <= (now - when).total_seconds() <= LATE and data["rang"].get(a["id"]) != key and key not in ringing:
                out.append((key, a))
                break
    return out


def rang(key: str, snooze: bool = False, now: dt.datetime = None) -> None:
    """An alarm was stopped (or gave up), or snoozed: a one-off turns off; a snoozed one rings again in nine minutes."""
    now = now or dt.datetime.now()
    ident = key.split("@")[0]

    def edit(data):
        for a in data["alarms"]:
            if a["id"] != ident:
                continue
            data["rang"][ident] = key
            a.pop("snooze", None)
            if snooze:
                a["snooze"] = (now + dt.timedelta(minutes=SNOOZE_MINUTES)).replace(second=0, microsecond=0).isoformat()
            elif not a.get("days"):
                a["on"] = False
        data["rang"] = {k: v for k, v in data["rang"].items() if any(a["id"] == k for a in data["alarms"])}
    change(edit)


def new_id() -> str:
    return format(int(time.time() * 1000), "x")


def zones() -> list:
    """Every time zone as (city, zone): "America/New_York" -> "New York"."""
    try:
        from zoneinfo import available_timezones
    except ImportError:
        return []
    out = []
    for z in sorted(available_timezones()):
        if "/" not in z or z.startswith(("Etc/", "SystemV/", "posix/", "right/", "US/", "Brazil/", "Canada/", "Chile/", "Mexico/")):
            continue
        out.append((z.split("/")[-1].replace("_", " "), z))
    return out
