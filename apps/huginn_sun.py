"""When the sun sets and rises here, for night light's "Sunset to sunrise", without asking anyone where this computer
is: the time zone's own place (its main city, from the system's time-zone list, zone1970.tab) is near enough.

    place(zone)              (latitude, longitude) of a time zone's city, or None
    times(lat, lon, day)     (sunrise, sunset) in minutes after local midnight; None for a day the sun doesn't rise or set
    today()                  (sunrise, sunset) for this computer's time zone today, or None
"""
import math
import os
import re
import time
from datetime import date

TABLES = ("/usr/share/zoneinfo/zone1970.tab", "/usr/share/zoneinfo/zone.tab")


def local_zone() -> str:
    tz = os.environ.get("TZ", "").lstrip(":")
    if "/" in tz and not tz.startswith("/"):
        return tz
    try:
        return os.path.realpath("/etc/localtime").split("zoneinfo/", 1)[1]
    except (IndexError, OSError):
        return ""


def _degrees(text: str, width: int) -> float:
    """ISO 6709 (+DDMM, +DDMMSS, +DDDMM…) as degrees."""
    sign = -1 if text[0] == "-" else 1
    d = text[1:]
    whole, rest = int(d[:width]), d[width:]
    minutes = int(rest[:2]) if rest else 0
    seconds = int(rest[2:4]) if len(rest) >= 4 else 0
    return sign * (whole + minutes / 60 + seconds / 3600)


def place(zone: str):
    for table in TABLES:
        try:
            lines = open(table, encoding="utf-8").read().splitlines()
        except OSError:
            continue
        for line in lines:
            if line.startswith("#"):
                continue
            f = line.split("\t")
            if len(f) >= 3 and f[2] == zone:
                m = re.fullmatch(r"([+-]\d{4,6})([+-]\d{5,7})", f[1])
                if m:
                    return _degrees(m.group(1), 2), _degrees(m.group(2), 3)
    return None


def times(lat: float, lon: float, day: date, offset_min: float):
    """NOAA's sunrise equation (good to a minute or two): sunrise and sunset in local minutes."""
    n = day.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    c = math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl)
    if c < -1 or c > 1:
        return None                                       # midnight sun, or polar night
    ha = math.degrees(math.acos(c))
    rise = 720 - 4 * (lon + ha) - eqtime + offset_min
    sets = 720 - 4 * (lon - ha) - eqtime + offset_min
    return round(rise) % 1440, round(sets) % 1440


def today():
    where = place(local_zone())
    if not where:
        return None
    return times(where[0], where[1], date.today(), time.localtime().tm_gmtoff / 60)


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
