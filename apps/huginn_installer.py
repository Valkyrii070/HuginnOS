"""Huginn OS's installer: the app on the live system that puts Huginn OS on a computer. Its steps are islands in a
dock (each keeps its answer): the language, the keyboard (with a place to try it), whether the computer is ready
(power, room, the internet, Secure Boot, Windows' Fast Startup and BitLocker, what works out of the box), where Huginn
lives (erase a disk, the free space beside another system, room made in Windows, or partitions you choose), extras
(media formats from Ubuntu or built here, fonts, drivers), what comes with it, your things from Windows, you (name,
user name, computer name, password), the time zone, and keeping it safe (encryption with a recovery key, the
firewall, restore points, updates). The orb at the end shows everything once more before anything is touched. Installing runs huginn_install_engine.py as root through pkexec (on the live system a polkit rule lets the
live user do that without a password); the plan, passwords included, goes to it on stdin and never to a file.

Everything about the computer is read without root: disks and partitions from lsblk and /sys, firmware from
/sys/firmware/efi, Wi‑Fi from NetworkManager (nmcli). `--demo` makes up a computer, for screenshots and tests.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, QObject, QProcess, Qt, QTimer, QUrl, Signal, Slot

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import huginn_install_engine as engine                       # noqa: E402  (the plan's checks and names are shared)

ENGINE = "/usr/libexec/huginn-install-engine"
MIN_BYTES = 20 * 10 ** 9                                    # Huginn OS wants about 20 GB
GIB = 1 << 30
SECTOR = 512
STEPS = ["welcome", "keyboard", "check", "disk", "extras", "apps", "windows", "you", "time", "safety", "ready"]
LABELS = ["Language", "Keyboard", "Ready?", "Where it lives", "Extras", "Apps", "From Windows", "You", "Time zone", "Safety", "Install"]

LANGUAGES = ["en_US", "en_GB", "de_DE", "fr_FR", "es_ES", "es_MX", "it_IT", "pt_BR", "pt_PT", "nl_NL", "sv_SE", "nb_NO",
             "da_DK", "fi_FI", "is_IS", "pl_PL", "cs_CZ", "uk_UA", "ru_RU", "tr_TR", "el_GR", "ar_SA", "he_IL", "hi_IN",
             "ja_JP", "ko_KR", "zh_CN", "zh_TW", "id_ID", "vi_VN", "th_TH", "en_CA", "fr_CA", "en_AU"]
# the keyboard and time zone a language most likely means
GUESS = {"en_US": ("us", "America/New_York"), "en_GB": ("gb", "Europe/London"), "de_DE": ("de", "Europe/Berlin"),
         "fr_FR": ("fr", "Europe/Paris"), "es_ES": ("es", "Europe/Madrid"), "es_MX": ("latam", "America/Mexico_City"),
         "it_IT": ("it", "Europe/Rome"), "pt_BR": ("br", "America/Sao_Paulo"), "pt_PT": ("pt", "Europe/Lisbon"),
         "nl_NL": ("nl", "Europe/Amsterdam"), "sv_SE": ("se", "Europe/Stockholm"), "nb_NO": ("no", "Europe/Oslo"),
         "da_DK": ("dk", "Europe/Copenhagen"), "fi_FI": ("fi", "Europe/Helsinki"), "is_IS": ("is", "Atlantic/Reykjavik"),
         "pl_PL": ("pl", "Europe/Warsaw"), "cs_CZ": ("cz", "Europe/Prague"), "uk_UA": ("ua", "Europe/Kyiv"),
         "ru_RU": ("ru", "Europe/Moscow"), "tr_TR": ("tr", "Europe/Istanbul"), "el_GR": ("gr", "Europe/Athens"),
         "ar_SA": ("ara", "Asia/Riyadh"), "he_IL": ("il", "Asia/Jerusalem"), "hi_IN": ("in", "Asia/Kolkata"),
         "ja_JP": ("jp", "Asia/Tokyo"), "ko_KR": ("kr", "Asia/Seoul"), "zh_CN": ("cn", "Asia/Shanghai"),
         "zh_TW": ("tw", "Asia/Taipei"), "id_ID": ("id", "Asia/Jakarta"), "vi_VN": ("vn", "Asia/Ho_Chi_Minh"),
         "th_TH": ("th", "Asia/Bangkok"), "en_CA": ("us", "America/Toronto"), "fr_CA": ("ca", "America/Toronto"),
         "en_AU": ("us", "Australia/Sydney")}


# shown while it installs: what's waiting on the other side
SLIDES = [("browser", "Huginn", "The browser at the heart of it all. Private by default: trackers stop at the door."),
          ("mail", "Mail", "Your accounts in one calm inbox. Sign-ins stay locked in the Passwords vault."),
          ("easel", "Easel", "Paint, retouch and design, with layers, masks and type along a path."),
          ("clips", "Clips", "Cut films from several cameras at once, with titles that follow what moves."),
          ("tempo", "Tempo", "Make music: instruments, drums, takes and a full mixer."),
          ("code", "Code", "Write, run and test your code, with Git built in."),
          ("writer", "Huginn Office", "Writer, Sheets and Slides, for documents that open anywhere."),
          ("photos", "Photos", "Every picture, sorted by when and where, edited without losing the original."),
          ("passwords", "Passwords", "One vault for the browser, Mail and Messages, under one master password.")]
ICON_DIRS = [Path("/usr/share/icons/hicolor/256x256/apps"), HERE.parent / "config/overlay/usr/share/icons/hicolor/256x256/apps"]


def slides() -> list:
    from PySide6.QtCore import QUrl
    out = []
    for icon, name, line in SLIDES:
        f = next((d / f"huginn-{icon}.png" for d in ICON_DIRS if (d / f"huginn-{icon}.png").is_file()), None)
        out.append({"name": name, "line": line, "icon": QUrl.fromLocalFile(str(f)).toString() if f else ""})
    return out


def run(argv: list, stdin: str = None, timeout: float = 20) -> tuple:
    try:
        r = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as err:
        return 127, "", str(err)


def size_text(n: int) -> str:
    gb = n / 10 ** 9
    return f"{gb / 1000:.1f} TB" if gb >= 1000 else f"{gb:.0f} GB" if gb >= 10 else f"{gb:.1f} GB"


def guess_system(part: dict) -> str:
    """What a partition probably holds, in words: 'Windows', 'Linux', 'EFI' … (os-prober needs root; this doesn't)."""
    fs, ptype, label = (part.get("fstype") or ""), (part.get("parttype") or "").lower(), (part.get("label") or "")
    if ptype == "c12a7328-f81f-11d2-ba4b-00a0c93ec93b" or ptype == "0xef":
        return "EFI"
    if ptype == "e3c9e316-0b5c-4db8-817d-f92df00215ae":
        return "Microsoft reserved"
    if ptype == "de94bba4-06d1-4d40-a16a-bfd50179d6ac":
        return "Windows recovery"
    if fs == "ntfs" or fs == "bitlocker":
        return "Windows" if "recovery" not in label.lower() else "Windows recovery"
    if fs in ("ext4", "ext3", "btrfs", "xfs", "f2fs"):
        return "Linux"
    if fs == "crypto_LUKS":
        return "Locked (LUKS)"
    if fs == "swap":
        return "Swap"
    if fs in ("vfat", "exfat"):
        return "FAT"
    if fs == "apfs" or fs == "hfsplus":
        return "macOS"
    return fs or "Empty"


def live_disk() -> str:
    """The disk the live system itself is running from (never offered)."""
    code, out, _ = run(["findmnt", "-n", "-o", "SOURCE", "/cdrom"])
    src = out.strip()
    if code or not src:
        return ""
    code, out, _ = run(["lsblk", "-n", "-o", "PKNAME", src])
    return "/dev/" + out.strip().splitlines()[0] if code == 0 and out.strip() else src


def free_spans(disk_name: str, disk_sectors: int, parts: list) -> list:
    """Unused stretches of a disk, from /sys (no root needed): [(start sector, sectors)], each at least 1 GiB,
    aligned to 1 MiB, keeping clear of the partition table at both ends."""
    used = sorted((p["start"], p["start"] + p["sectors"]) for p in parts)
    spans, at = [], 2048
    end = disk_sectors - 34                                   # GPT keeps a copy of itself at the end
    for a, b in used + [(end, end)]:
        if a > at:
            start = (at + 2047) // 2048 * 2048
            if a - start >= GIB // SECTOR:
                spans.append((start, a - start))
        at = max(at, b)
    return spans


def read_disks() -> list:
    code, out, _ = run(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,MODEL,TRAN,RM,RO,PTTYPE,FSTYPE,LABEL,PARTTYPE,PARTLABEL,MOUNTPOINTS"])
    if code:
        return []
    skip = live_disk()
    disks = []
    for d in json.loads(out).get("blockdevices", []):
        if d.get("type") != "disk" or d.get("ro") in (True, "1") or d["path"] == skip or int(d.get("size") or 0) < 8 * 10 ** 9:
            continue
        if re.match(r"(loop|sr|zram|ram|fd)", d["name"]):
            continue
        parts = []
        for c in d.get("children") or []:
            try:
                start = int(Path(f"/sys/class/block/{c['name']}/start").read_text())
                sectors = int(Path(f"/sys/class/block/{c['name']}/size").read_text())
            except (OSError, ValueError):
                start, sectors = 0, int(c.get("size") or 0) // SECTOR
            parts.append({"path": c["path"], "name": c["name"], "size": int(c.get("size") or 0), "sizeText": size_text(int(c.get("size") or 0)),
                          "fstype": c.get("fstype") or "", "label": c.get("label") or c.get("partlabel") or "",
                          "parttype": c.get("parttype") or "", "start": start, "sectors": sectors,
                          "mounted": any(m for m in (c.get("mountpoints") or []) if m)})
        for p in parts:
            p["holds"] = guess_system(p)
        size = int(d.get("size") or 0)
        try:
            disk_sectors = int(Path(f"/sys/class/block/{d['name']}/size").read_text())
        except (OSError, ValueError):
            disk_sectors = size // SECTOR
        free = free_spans(d["name"], disk_sectors, parts)
        disks.append(disk_view(d["path"], (d.get("model") or "").strip(), d.get("tran") or "", d.get("rm") in (True, "1"), size, parts, free))
    return disks


def disk_view(path: str, model: str, tran: str, removable: bool, size: int, parts: list, free: list) -> dict:
    systems = sorted({p["holds"] for p in parts if p["holds"] in ("Windows", "Linux", "macOS")})
    best = max(free, key=lambda s: s[1]) if free else None
    kind = {"nvme": "NVMe drive", "sata": "SATA drive", "usb": "USB drive", "mmc": "Memory card", "virtio": "Virtual disk"}.get(tran, "Disk")
    windows = [p for p in parts if p["holds"] == "Windows" and p.get("fstype") == "ntfs" and p["size"] >= 50 * 10 ** 9]
    shrink = max(windows, key=lambda p: p["size"]) if windows else None
    locked = any((p.get("fstype") or "").lower() == "bitlocker" for p in parts)
    return {"path": path, "model": model or kind, "kind": kind, "removable": removable, "size": size, "sizeText": size_text(size),
            "shrinkPart": shrink["path"] if shrink else "", "shrinkSize": shrink["size"] if shrink else 0,
            "shrinkLabel": (shrink["label"] or "Windows") if shrink else "", "bitlocker": locked,
            "parts": parts, "systems": systems, "big": size >= MIN_BYTES,
            "freeStart": best[0] if best else 0, "freeBytes": best[1] * SECTOR if best else 0, "freeText": size_text(best[1] * SECTOR) if best else "",
            "hasEsp": any(p["holds"] == "EFI" for p in parts), "mounted": any(p["mounted"] for p in parts),
            "bar": [{"label": p["label"] or p["holds"], "holds": p["holds"], "share": p["size"] / size if size else 0, "sizeText": p["sizeText"], "free": False} for p in parts]
                   + ([{"label": "Free space", "holds": "Free", "share": best[1] * SECTOR / size, "sizeText": size_text(best[1] * SECTOR), "free": True}] if best else [])}


def demo_disks() -> list:
    w = [{"path": "/dev/nvme0n1p1", "name": "nvme0n1p1", "size": 272629760, "fstype": "vfat", "label": "SYSTEM", "parttype": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "start": 2048, "sectors": 532480, "mounted": False},
         {"path": "/dev/nvme0n1p2", "name": "nvme0n1p2", "size": 16777216, "fstype": "", "label": "", "parttype": "e3c9e316-0b5c-4db8-817d-f92df00215ae", "start": 534528, "sectors": 32768, "mounted": False},
         {"path": "/dev/nvme0n1p3", "name": "nvme0n1p3", "size": 299 * 10 ** 9, "fstype": "ntfs", "label": "Windows", "parttype": "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7", "start": 567296, "sectors": 299 * 10 ** 9 // 512, "mounted": False},
         {"path": "/dev/nvme0n1p4", "name": "nvme0n1p4", "size": 1 * 10 ** 9, "fstype": "ntfs", "label": "Recovery", "parttype": "de94bba4-06d1-4d40-a16a-bfd50179d6ac", "start": 584529000, "sectors": 1953125, "mounted": False}]
    for p in w:
        p["sizeText"] = size_text(p["size"]); p["holds"] = guess_system(p)
    free = [(586483712, (512 * 10 ** 9 - 586483712 * 512) // 512 - 34)]
    usb = [{"path": "/dev/sda1", "name": "sda1", "size": 64 * 10 ** 9, "fstype": "exfat", "label": "PHOTOS", "parttype": "0x7", "start": 2048, "sectors": 125000000, "mounted": False}]
    for p in usb:
        p["sizeText"] = size_text(p["size"]); p["holds"] = guess_system(p)
    return [disk_view("/dev/nvme0n1", "Samsung SSD 980 PRO", "nvme", False, 512 * 10 ** 9, w, free),
            disk_view("/dev/sda", "SanDisk Extreme", "usb", True, 64 * 10 ** 9, usb, [])]


def read_wifi() -> dict:
    if not shutil.which("nmcli"):
        return {"available": False, "networks": [], "wired": False, "connected": ""}
    _, devs, _ = run(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device"])
    wired = any(line.startswith("ethernet:connected") for line in devs.splitlines())
    if not any(line.startswith("wifi:") for line in devs.splitlines()):          # no Wi‑Fi adapter at all
        return {"available": False, "networks": [], "wired": wired, "connected": ""}
    connected = next((line.split(":", 2)[2] for line in devs.splitlines() if line.startswith("wifi:connected")), "")
    _, scan, _ = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "auto"], timeout=25)
    best = {}
    for line in scan.splitlines():
        f = re.split(r"(?<!\\):", line)
        if len(f) < 4 or not f[1]:
            continue
        ssid = f[1].replace("\\:", ":")
        sig = int(f[2]) if f[2].isdigit() else 0
        if ssid not in best or sig > best[ssid]["signal"]:
            best[ssid] = {"ssid": ssid, "signal": sig, "secure": f[3] not in ("", "--"), "inUse": f[0] == "*"}
    return {"available": True, "networks": sorted(best.values(), key=lambda n: (not n["inUse"], -n["signal"])), "wired": wired, "connected": connected}


def locale_label(code: str) -> str:
    from PySide6.QtCore import QLocale
    q = QLocale(code)
    lang = q.nativeLanguageName() or code
    region = q.nativeTerritoryName() if hasattr(q, "nativeTerritoryName") else q.nativeCountryName()
    return f"{lang[:1].upper()}{lang[1:]} ({region})" if region else lang


ZONEINFO = Path("/usr/share/zoneinfo")
# The United States' zones as people say them (zone.tab lists 29, most for a few counties).
US_MAIN = [("America/New_York", "Eastern"), ("America/Chicago", "Central"), ("America/Denver", "Mountain"),
           ("America/Phoenix", "Arizona"), ("America/Los_Angeles", "Pacific"), ("America/Anchorage", "Alaska"),
           ("Pacific/Honolulu", "Hawaii")]
TWELVE_HOUR = ("en_US", "en_CA", "en_AU", "hi_IN", "ar_SA")


def utc_text(seconds: int) -> str:
    """UTC−6, UTC+5:30, UTC."""
    if not seconds:
        return "UTC"
    sign, s = ("+" if seconds > 0 else "−"), abs(seconds)
    h, m = divmod(s // 60, 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


def zone_list() -> list:
    """Every place in tzdata's zone.tab: its city, country, what the zone is called there ("Central"), its offset
    now, and words to find it by (the city, country, region, abbreviations like CST, "utc-6")."""
    import datetime
    try:
        import zoneinfo
    except ImportError:                                      # pragma: no cover
        return [{"id": "UTC", "city": "UTC", "country": "", "place": "Coordinated Universal Time", "cc": "", "offset": "UTC", "minutes": 0, "note": "", "find": "utc gmt"}]
    from PySide6.QtCore import QLocale
    countries = {}
    try:
        for line in (ZONEINFO / "iso3166.tab").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "\t" in line:
                cc, name = line.split("\t", 1)
                countries[cc] = name.strip()
    except OSError:
        pass

    def country(cc: str) -> str:
        try:
            t = QLocale.codeToTerritory(cc)
            name = QLocale.territoryToString(t) if t.value else ""      # 0: AnyTerritory (an unknown code)
        except (AttributeError, TypeError, ValueError):
            name = ""
        return name or countries.get(cc, cc)

    rows = []
    try:
        lines = (ZONEINFO / "zone.tab").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    us = dict(US_MAIN)
    now = datetime.datetime.now(datetime.timezone.utc)
    jan, jul = datetime.datetime(now.year, 1, 15, 12, tzinfo=datetime.timezone.utc), datetime.datetime(now.year, 7, 15, 12, tzinfo=datetime.timezone.utc)
    for line in lines:
        if not line or line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) < 3:
            continue
        cc, zid, note = f[0], f[2], (f[3].strip() if len(f) > 3 else "")
        try:
            tz = zoneinfo.ZoneInfo(zid)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
            continue
        off = int(now.astimezone(tz).utcoffset().total_seconds())
        abbrs = {jan.astimezone(tz).tzname(), jul.astimezone(tz).tzname()}
        abbrs = sorted(a for a in abbrs if a and a.isalpha())
        note = us.get(zid) or re.sub(r"\s*\(most areas\)", "", note)
        name = country(cc)
        city = zid.rsplit("/", 1)[-1].replace("_", " ")
        hours = utc_text(off).replace("−", "-").lower()
        rows.append({"id": zid, "city": city, "cc": cc, "country": name, "place": name + (f" · {note}" if note else ""), "offset": utc_text(off),
                     "minutes": off // 60, "note": note,
                     "find": " ".join([city, name, note, zid.replace("_", " ").replace("/", " "), " ".join(abbrs), hours, hours.replace("utc", "gmt"),
                                       (note + " time") if note in us.values() else ""]).lower()})
    if not rows:                                            # no zone.tab: the names Python knows
        for zid in sorted(z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/", "US/", "posix/", "right/"))):
            city = zid.rsplit("/", 1)[-1].replace("_", " ")
            rows.append({"id": zid, "city": city, "cc": "", "country": zid.split("/", 1)[0], "place": zid.split("/", 1)[0], "offset": "", "minutes": 0, "note": "",
                         "find": (city + " " + zid).lower()})
    rows.sort(key=lambda r: (r["city"].lower(), r["id"]))
    return rows


def suggested_zones(rows: list, cc: str) -> list:
    """The few zones a country's people mostly mean: the US's seven, else zone.tab's for that country (its main
    ones when it has many)."""
    if cc == "US":
        by = {r["id"]: r for r in rows}
        return [by[z] for z, _ in US_MAIN if z in by]
    mine = [r for r in rows if r["cc"] == cc]
    if len(mine) > 8:
        main = [r for r in mine if not r["note"] or "most" in r["note"].lower()]
        mine = main if 0 < len(main) <= 8 else mine[:8]
    return sorted(mine, key=lambda r: -r["minutes"])


class ZoneModel(QAbstractListModel):
    """The time zone list: the suggested ones (for the language's country) above them all, or what matches a search
    (every word of it, the city's start first). Filtering here, in Python, keeps typing quick: the list QML had
    filtered itself was converted again, all 400-odd zones of it, at every key."""
    ROLES = {Qt.UserRole + 1: b"zid", Qt.UserRole + 2: b"city", Qt.UserRole + 3: b"place", Qt.UserRole + 4: b"offset",
             Qt.UserRole + 5: b"clock", Qt.UserRole + 6: b"group"}
    minuteChanged = Signal()

    def __init__(self, rows: list, parent=None):
        super().__init__(parent)
        self._all = rows
        self._by = {r["id"]: r for r in rows}
        self._shown = []                                    # (row, group)
        self._query = ""
        self._cc = ""
        self._twelve = True
        self._clocks = {}
        self._minute = ""
        self._tz = {}
        self._timer = QTimer(self, interval=15000, timeout=self._tick)
        self._timer.start()
        self._refill()

    def roleNames(self):
        return self.ROLES

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._shown)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._shown):
            return None
        r, group = self._shown[index.row()]
        name = self.ROLES.get(role)
        if name == b"zid":
            return r["id"]
        if name == b"city":
            return r["city"]
        if name == b"place":
            return r["place"]
        if name == b"offset":
            return r["offset"]
        if name == b"clock":
            return self.clock(r["id"])
        if name == b"group":
            return group
        return None

    def rows(self) -> list:
        return self._all

    def find(self, zid: str):
        return self._by.get(zid)

    @Slot(str, result=str)
    def clock(self, zid: str) -> str:
        """The time there now: 9:53 PM (or 21:53, by the language)."""
        if zid not in self._clocks:
            import datetime
            import zoneinfo
            try:
                tz = self._tz.get(zid) or self._tz.setdefault(zid, zoneinfo.ZoneInfo(zid))
            except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
                return ""
            t = datetime.datetime.now(tz)
            self._clocks[zid] = (f"{(t.hour % 12) or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}" if self._twelve
                                 else f"{t.hour:02d}:{t.minute:02d}")
        return self._clocks[zid]

    minute = Property(str, lambda self: self._minute, notify=minuteChanged)

    def _tick(self) -> None:
        import time
        m = time.strftime("%H:%M")
        if m != self._minute:
            self._minute = m
            self._clocks = {}
            if self._shown:
                self.dataChanged.emit(self.index(0), self.index(len(self._shown) - 1), [Qt.UserRole + 5])
            self.minuteChanged.emit()

    def setLanguage(self, lang: str) -> None:
        cc = lang.partition("_")[2]
        twelve = lang in TWELVE_HOUR
        if cc != self._cc or twelve != self._twelve:
            self._cc, self._twelve, self._clocks = cc, twelve, {}
            self._refill()

    @Slot(str)
    def setFilter(self, text: str) -> None:
        q = " ".join((text or "").lower().replace("−", "-").split())
        if q != self._query:
            self._query = q
            self._refill()

    def _refill(self) -> None:
        q = self._query
        if q:
            words = q.split()
            hits = [r for r in self._all if all(w in r["find"] for w in words)]
            hits.sort(key=lambda r: (not r["city"].lower().startswith(q), not r["find"].startswith(words[0]), r["city"].lower()))
            shown = [(r, "Matches") for r in hits]
        else:
            sug = suggested_zones(self._all, self._cc) if self._cc else []
            name = sug[0]["country"] if sug else ""
            shown = [(r, f"Suggested for {name}") for r in sug] + [(r, "All time zones") for r in self._all]
        self.beginResetModel()
        self._shown = shown
        self.endResetModel()

    @Slot(str, result=int)
    def indexOf(self, zid: str) -> int:
        return next((i for i, (r, _) in enumerate(self._shown) if r["id"] == zid), -1)


def xkb_list() -> list:
    out, inside = [], False
    try:
        for line in Path("/usr/share/X11/xkb/rules/evdev.lst").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("!"):
                inside = line.strip() == "! layout"
                continue
            if inside and line.strip():
                code, _, label = line.strip().partition(" ")
                out.append({"id": code, "label": label.strip()})
    except OSError:
        out = [{"id": c, "label": n} for c, n in (("us", "English (US)"), ("gb", "English (UK)"), ("de", "German"), ("fr", "French"),
                                                 ("es", "Spanish"), ("no", "Norwegian"), ("se", "Swedish"), ("jp", "Japanese"))]
    return sorted(out, key=lambda l: l["label"].lower())


def chassis() -> str:
    try:
        kind = int(Path("/sys/class/dmi/id/chassis_type").read_text().strip())
    except (OSError, ValueError):
        return "pc"
    return "laptop" if kind in (8, 9, 10, 14, 30, 31, 32) else "pc"


# ---------------------------------------------------------------- is this computer ready? (read without root)
def power_state() -> dict:
    """{battery: has one, plugged: on mains power, level: percent}."""
    out = {"battery": False, "plugged": True, "level": 100}
    base = Path("/sys/class/power_supply")
    try:
        for d in base.iterdir():
            kind = (d / "type").read_text().strip() if (d / "type").exists() else ""
            if kind == "Battery" and (d / "present").exists() and (d / "present").read_text().strip() != "0":
                out["battery"] = True
                try:
                    out["level"] = int((d / "capacity").read_text().strip())
                except (OSError, ValueError):
                    pass
            if kind == "Mains":
                out["plugged"] = (d / "online").read_text().strip() == "1" if (d / "online").exists() else True
    except OSError:
        pass
    if out["battery"] and not any((base / n / "type").exists() and (base / n / "type").read_text().strip() == "Mains" for n in os.listdir(base) if (base / n).is_dir()):
        try:
            out["plugged"] = any((d / "status").read_text().strip() in ("Charging", "Full") for d in base.iterdir() if (d / "status").exists())
        except OSError:
            pass
    return out


def secure_boot() -> str:
    """'on', 'off', or '' (an older computer that starts the old way: no Secure Boot)."""
    vars_ = Path("/sys/firmware/efi/efivars")
    if not vars_.is_dir():
        return ""
    try:
        f = next(vars_.glob("SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"))
        return "on" if f.read_bytes()[-1:] == b"\x01" else "off"
    except (StopIteration, OSError):
        return "off"


def graphics() -> list:
    """The graphics in this computer: [{vendor: nvidia | amd | intel | other, name}] (from /sys, no lspci needed)."""
    names = {"0x10de": ("nvidia", "NVIDIA graphics"), "0x1002": ("amd", "AMD Radeon graphics"), "0x8086": ("intel", "Intel graphics"),
             "0x1af4": ("other", "Virtual graphics"), "0x15ad": ("other", "Virtual graphics"), "0x1234": ("other", "Virtual graphics")}
    out = []
    try:
        for d in sorted(Path("/sys/bus/pci/devices").iterdir()):
            try:
                if not (d / "class").read_text().strip().startswith("0x03"):
                    continue
                vendor = (d / "vendor").read_text().strip()
            except OSError:
                continue
            kind, name = names.get(vendor, ("other", "Graphics"))
            if not any(g["vendor"] == kind for g in out):
                out.append({"vendor": kind, "name": name})
    except OSError:
        pass
    return out


def hardware() -> dict:
    """What works out of the box: Wi‑Fi, Bluetooth, sound, a camera, and how much memory."""
    def any_in(path, test=lambda d: True):
        try:
            return any(test(d) for d in Path(path).iterdir())
        except OSError:
            return False
    mem = 0
    try:
        mem = int(re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text()).group(1)) * 1024
    except (OSError, AttributeError, ValueError):
        pass
    return {"wifi": any_in("/sys/class/net", lambda d: (d / "wireless").exists() or (d / "phy80211").exists()),
            "bluetooth": any_in("/sys/class/bluetooth"), "sound": any_in("/proc/asound", lambda d: d.name.startswith("card")),
            "camera": any_in("/sys/class/video4linux"), "memory": mem, "tpm": Path("/sys/class/tpm/tpm0").exists()}


class Installer(QObject):
    # Each part says when it changes, so a click on a time zone or a key in a name doesn't make every list and
    # field in the installer look again (one signal for everything made the time zone list slow to answer).
    changed = Signal()                               # the step, the state, the network, the disk
    langChanged = Signal()
    layoutChanged = Signal()
    zoneChanged = Signal()
    youChanged = Signal()
    problemChanged = Signal()                        # after any of the above (what's missing on this step)
    summaryChanged = Signal()
    _wifiRead = Signal(object)                       # from the thread that asks NetworkManager (a scan takes seconds)
    _wifiJoined = Signal(str, int, str)
    progressed = Signal()
    said = Signal(str, bool)

    def __init__(self, demo: bool = False):
        super().__init__()
        self._demo = demo
        self._step = 0
        self._langs = sorted(({"id": c, "label": locale_label(c)} for c in LANGUAGES), key=lambda l: l["label"].lower())
        self._lang = "en_US"
        self._layouts = xkb_list()
        self._layout = "us"
        self._zones = ZoneModel(zone_list(), self)
        self._zones.setLanguage(self._lang)
        self._zone = self._guess_zone()
        if not self._zones.find(self._zone):                # the live system's clock is in UTC: the language's guess
            self._zone = GUESS.get(self._lang, ("us", "UTC"))[1]
        self._you_view = None
        for sig in (self.changed, self.langChanged, self.layoutChanged, self.zoneChanged, self.youChanged):
            sig.connect(self.problemChanged)
            sig.connect(self.summaryChanged)
        self._wifi = {"available": True, "networks": [], "wired": False, "connected": ""}
        self._disks = demo_disks() if demo else read_disks()
        self._disk = next((d["path"] for d in self._disks if d["big"] and not d["removable"]), self._disks[0]["path"] if self._disks else "")
        self._mode = "erase"
        self._shrink = {"state": "", "size": 0, "min": 0, "huginn": 0, "why": ""}     # beside Windows: probing → ok | no
        self._probe = None
        self._root = ""
        self._efi = ""
        self._format_efi = False
        self._encrypt = False
        self._passphrase = ""
        self._you = {"realName": "", "name": "", "hostname": "", "password": "", "again": "", "autologin": False, "hostTouched": False, "nameTouched": False}
        self._firmware = "uefi" if (demo or Path("/sys/firmware/efi").is_dir()) else "bios"
        # the computer as it is, and what was chosen in the newer steps
        if demo:
            self._power, self._secure = {"battery": True, "plugged": True, "level": 82}, "on"
            self._gpus = [{"vendor": "amd", "name": "AMD Radeon graphics"}]
            self._hw = {"wifi": True, "bluetooth": True, "sound": True, "camera": True, "memory": 32 * GIB, "tpm": True}
        else:
            self._power, self._secure, self._gpus, self._hw = power_state(), secure_boot(), graphics(), hardware()
        self._extras = {"codecs": "download", "msfonts": True, "scripts": False, "printers": True,
                        "nvidia": any(g["vendor"] == "nvidia" for g in self._gpus)}
        self._apps = {"gamedev": False, "flathub": True, "fromWindows": []}
        self._windows = {"state": "", "part": "", "users": [], "apps": [], "fastStartup": False, "problem": "", "counted": True}
        self._bring = {"user": "", "folders": ["documents", "pictures", "music", "videos", "desktop", "downloads"], "how": "copy", "skip": False}
        self._win_probe = None
        self._safety = {"restorePoints": True, "firewall": True, "autoUpdates": True}
        self._access = {"reader": False, "bigger": False, "contrast": False, "motion": False, "osk": False}
        self._recovery = engine.recovery_key()
        self._state = "setup"                               # setup → installing → done | error
        self._fraction = 0.0
        self._label = ""
        self._note = ""
        self._error = ""
        self._log = []
        self._proc = None
        self._demo_timer = None
        self._wifi_busy = False
        self._wifiRead.connect(self._got_wifi)
        self._wifiJoined.connect(self._joined)
        if demo:
            self._wifi = {"available": True, "wired": False, "connected": "",
                          "networks": [{"ssid": "Valhalla", "signal": 92, "secure": True, "inUse": False}, {"ssid": "Bifrost-5G", "signal": 74, "secure": True, "inUse": False},
                                       {"ssid": "Library guest", "signal": 41, "secure": False, "inUse": False}]}

    # ------------------------------------------------------------------ where we are
    step = Property(int, lambda self: self._step, notify=changed)
    steps = Property("QVariantList", lambda self: [{"id": s, "label": l} for s, l in zip(STEPS, LABELS)], constant=True)
    state = Property(str, lambda self: self._state, notify=changed)
    slides = Property("QVariantList", lambda self: slides(), constant=True)
    demo = Property(bool, lambda self: self._demo, constant=True)

    @Slot()
    def next(self) -> None:
        problem = self.problem
        if problem:
            self.said.emit(problem, True)
            return
        if self._step < len(STEPS) - 1:
            self._step += 1
            if STEPS[self._step] == "windows" and not self._windows_here():
                self._step += 1                              # (no Windows that stays: nothing to bring)
            self._entered()
            self.changed.emit()

    def _entered(self) -> None:
        """A step's own reading, the first time it's needed: the Wi‑Fi and Windows for Ready?, Windows for From Windows."""
        here = STEPS[self._step]
        if here == "check":
            if not self._demo:
                QTimer.singleShot(0, self.refreshWifi)
            self._probe_windows()
        if here == "windows":
            self._probe_windows()

    @Slot()
    def back(self) -> None:
        if self._step > 0 and self._state == "setup":
            self._step -= 1
            if STEPS[self._step] == "windows" and not self._windows_here():
                self._step -= 1
            self.changed.emit()

    def showStep(self, name: str) -> None:
        """(previews) open a step by its name, as if the ones before it were done."""
        if name in STEPS:
            self._step = STEPS.index(name)
            self._entered()
            self.changed.emit()

    @Slot(int)
    def goTo(self, i: int) -> None:
        """A step's island in the dock: any step before this one, or the next ones as long as each on the way has no
        problem (an island with its answer already given)."""
        if not (0 <= i < len(STEPS)) or self._state != "setup" or i == self._step:
            return
        if STEPS[i] == "windows" and not self._windows_here():
            return
        while self._step < i:                                 # forward: only past steps that are ready
            if self.problem:
                self.said.emit(self.problem, True)
                self.changed.emit()
                return
            self._step += 1
            if STEPS[self._step] == "windows" and not self._windows_here() and self._step < i:
                self._step += 1
        self._step = i
        self._entered()
        self.changed.emit()

    def _problem(self) -> str:
        s = STEPS[self._step]
        if s == "disk":
            d = self.chosenDisk
            if not d:
                return "There's no disk to put Huginn OS on."
            if self._mode == "erase" and not d.get("big"):
                return f"Huginn OS needs about {size_text(MIN_BYTES)}; this disk has {d.get('sizeText')}."
            if self._mode == "shrink":
                sh = self._shrink
                if sh["state"] == "probing":
                    return "Looking at how much room Windows can give\u2026"
                if sh["state"] != "ok":
                    return sh["why"] or "Windows' partition couldn't be looked at."
                if sh["huginn"] < MIN_BYTES:
                    return f"Give Huginn OS about {size_text(MIN_BYTES)} at least."
            if self._mode == "free" and d.get("freeBytes", 0) < MIN_BYTES:
                return f"The free space on this disk is {d.get('freeText') or 'none'}; Huginn OS needs about {size_text(MIN_BYTES)}."
            if self._mode == "manual":
                if not self._root:
                    return "Choose the partition for Huginn OS."
                if self._firmware == "uefi" and not self._efi:
                    return "Choose the EFI system partition."
                if self._root == self._efi:
                    return "Huginn OS and the EFI partition can't be the same partition."
        if s == "safety" and self._encrypt:
            if len(self._passphrase) < 8:
                return "The disk password needs 8 characters at least."
            if self._mode == "manual":
                return "To encrypt, let the installer make the partitions (erase the disk, or use its free space)."
        if s == "windows" and not self._bring["skip"] and self._windows["state"] == "ok" and not self._bring["user"]:
            return "Choose whose things to bring."
        if s == "you":
            u = self._you
            if not u["realName"].strip():
                return "What's your name?"
            if not engine.good_username(u["name"]):
                return "The user name can have small letters, digits, - and _, and must start with a letter."
            if not u["password"]:
                return "Choose a password."
            if u["password"] != u["again"]:
                return "The two passwords aren't the same."
        return ""

    problem = Property(str, _problem, notify=problemChanged)

    # ------------------------------------------------------------------ language, keyboard, time zone
    languages = Property("QVariantList", lambda self: self._langs, constant=True)
    language = Property(str, lambda self: self._lang, notify=langChanged)
    layouts = Property("QVariantList", lambda self: self._layouts, constant=True)
    layout = Property(str, lambda self: self._layout, notify=layoutChanged)
    layoutLabel = Property(str, lambda self: next((l["label"] for l in self._layouts if l["id"] == self._layout), self._layout), notify=layoutChanged)
    languageLabel = Property(str, lambda self: next((l["label"] for l in self._langs if l["id"] == self._lang), self._lang), notify=langChanged)
    zoneModel = Property(QObject, lambda self: self._zones, constant=True)
    zone = Property(str, lambda self: self._zone, notify=zoneChanged)

    def _zone_label(self) -> str:
        """Chicago (Central, United States)"""
        r = self._zones.find(self._zone)
        if not r:
            return self._zone
        where = ", ".join(x for x in (r["note"], r["country"]) if x)
        return f"{r['city']} ({where})" if where else r["city"]
    zoneLabel = Property(str, _zone_label, notify=zoneChanged)
    zoneCity = Property(str, lambda self: (self._zones.find(self._zone) or {}).get("city", self._zone), notify=zoneChanged)
    zonePlace = Property(str, lambda self: (self._zones.find(self._zone) or {}).get("place", ""), notify=zoneChanged)
    zoneOffset = Property(str, lambda self: (self._zones.find(self._zone) or {}).get("offset", ""), notify=zoneChanged)

    def _guess_zone(self) -> str:
        try:
            return os.path.realpath("/etc/localtime").split("zoneinfo/", 1)[1]
        except (IndexError, OSError):
            return "UTC"

    @Slot(str)
    def setLanguage(self, code: str) -> None:
        if code not in LANGUAGES:
            return
        self._lang = code
        lay, zone = GUESS.get(code, ("us", "UTC"))
        if any(l["id"] == lay for l in self._layouts):
            self.setLayout(lay)
        self._zones.setLanguage(code)
        if self._zones.find(zone):
            self._zone = zone
        self.langChanged.emit()
        self.zoneChanged.emit()

    @Slot(str)
    def setLayout(self, lay: str) -> None:
        if not re.fullmatch(r"[a-z]{2,8}", lay or ""):
            return
        self._layout = lay
        self.layoutChanged.emit()
        if not self._demo:                                  # try it right away, in the live session
            rc = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kxkbrc"
            try:
                rc.parent.mkdir(parents=True, exist_ok=True)
                rc.write_text(f"[Layout]\nLayoutList={lay}\nUse=true\nResetOldOptions=true\n", encoding="utf-8")
                run(["dbus-send", "--session", "--type=signal", "/Layouts", "org.kde.keyboard.reloadConfig"], timeout=5)
            except OSError:
                pass
            if shutil.which("setxkbmap") and os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                run(["setxkbmap", lay], timeout=5)

    @Slot(str)
    def setZone(self, zone: str) -> None:
        if zone != self._zone and self._zones.find(zone):
            self._zone = zone
            self.zoneChanged.emit()

    # ------------------------------------------------------------------ network
    wifi = Property("QVariantMap", lambda self: self._wifi, notify=changed)

    @Slot()
    def refreshWifi(self) -> None:
        if self._demo or self._wifi_busy:
            return
        self._wifi_busy = True
        threading.Thread(target=lambda: self._wifiRead.emit(read_wifi()), daemon=True).start()

    def _got_wifi(self, wifi: dict) -> None:
        self._wifi_busy = False
        self._wifi = wifi
        self.changed.emit()

    def _joined(self, ssid: str, code: int, message: str) -> None:
        self.said.emit(f"Connected to {ssid}." if code == 0 else "That didn't connect: " + message, code != 0)
        self.refreshWifi()

    @Slot(str, str)
    def connectWifi(self, ssid: str, password: str) -> None:
        if self._demo:
            self._wifi = dict(self._wifi, connected=ssid, networks=[dict(n, inUse=n["ssid"] == ssid) for n in self._wifi["networks"]])
            self.changed.emit()
            self.said.emit(f"Connected to {ssid}.", False)
            return
        argv = ["nmcli", "--wait", "25", "device", "wifi", "connect", ssid] + (["password", password] if password else [])

        def join():
            code, out, err = run(argv, timeout=40)
            self._wifiJoined.emit(ssid, code, ((err or out).strip().splitlines() or ["no reason given"])[-1])
        threading.Thread(target=join, daemon=True).start()

    # ------------------------------------------------------------------ the disk
    disks = Property("QVariantList", lambda self: self._disks, notify=changed)
    disk = Property(str, lambda self: self._disk, notify=changed)
    mode = Property(str, lambda self: self._mode, notify=changed)
    firmware = Property(str, lambda self: self._firmware, notify=changed)
    encrypt = Property(bool, lambda self: self._encrypt, notify=changed)
    root = Property(str, lambda self: self._root, notify=changed)
    efi = Property(str, lambda self: self._efi, notify=changed)
    chosenDisk = Property("QVariantMap", lambda self: next((d for d in self._disks if d["path"] == self._disk), {}), notify=changed)

    @Slot()
    def refreshDisks(self) -> None:
        if not self._demo:
            self._disks = read_disks()
        if not any(d["path"] == self._disk for d in self._disks):
            self._disk = self._disks[0]["path"] if self._disks else ""
        self.changed.emit()

    @Slot(str)
    def setDisk(self, path: str) -> None:
        if any(d["path"] == path for d in self._disks):
            self._disk, self._root, self._efi = path, "", ""
            d = self.chosenDisk
            if (self._mode == "free" and not d.get("freeBytes")) or (self._mode == "shrink" and not d.get("shrinkPart")):
                self._mode = "erase"
            elif self._mode == "shrink":
                self._start_probe()
            self.changed.emit()

    @Slot(str)
    def setMode(self, mode: str) -> None:
        if mode in ("erase", "free", "shrink", "manual"):
            self._mode = mode
            if mode == "shrink":
                self._start_probe()
            if mode == "manual":
                self._encrypt = False
                esp = next((p["path"] for p in self.chosenDisk.get("parts", []) if p["holds"] == "EFI"), "")
                self._efi = self._efi or esp
            self.changed.emit()

    @Slot(str)
    def setRoot(self, path: str) -> None:
        self._root = path
        self.changed.emit()

    @Slot(str)
    def setEfi(self, path: str) -> None:
        self._efi = path
        self.changed.emit()

    @Slot(bool, str)
    def setEncrypt(self, on: bool, passphrase: str) -> None:
        self._encrypt, self._passphrase = bool(on) and self._mode != "manual", passphrase
        self.changed.emit()

    # ------------------------------------------------------------------ you
    def _you_map(self) -> dict:
        if self._you_view is None:                   # read by a dozen bindings: made once per change
            u = self._you
            self._you_view = ({k: v for k, v in u.items() if k not in ("password", "again")}
                              | {"hasPassword": bool(u["password"]), "same": u["password"] == u["again"], "strength": strength(u["password"])})
        return self._you_view
    you = Property("QVariantMap", _you_map, notify=youChanged)

    @Slot(str, str)
    def setYou(self, key: str, value: str) -> None:
        u = self._you
        if key == "realName":
            u["realName"] = value[:80]
            first = re.sub(r"[^a-z0-9]", "", ascii_name((value.strip().split() or [""])[0].lower()))
            if not u["nameTouched"]:
                u["name"] = (first if first[:1].isalpha() else "") [:32]
            if not u["hostTouched"]:
                u["hostname"] = f"{first or 'huginn'}-{chassis()}"
        elif key == "name":
            u["name"], u["nameTouched"] = value.strip().lower()[:32], True
        elif key == "hostname":
            u["hostname"], u["hostTouched"] = value[:63], True
        elif key in ("password", "again"):
            u[key] = value
        elif key == "autologin":
            u["autologin"] = value == "true"
        self._you_view = None
        self.youChanged.emit()

    # ------------------------------------------------------------------ is this computer ready?
    def _check(self) -> list:
        """Ready?: each thing looked at, {key, state: ok | warn | info, title, line}, before anything is asked."""
        rows, pw, w = [], self._power, self._wifi
        if pw["battery"]:
            rows.append({"key": "power", "state": "ok" if pw["plugged"] else "warn", "title": "Plugged in" if pw["plugged"] else f"On its battery ({pw['level']} %)",
                         "line": "Installing is safe on mains power." if pw["plugged"] else "Plug it in before installing: if the battery runs out halfway, the disk is left half done."})
        big = [d for d in self._disks if d.get("big")]
        rows.append({"key": "room", "state": "ok" if big else "warn", "title": "Room for Huginn" if big else "No disk big enough",
                     "line": (f"{len(self._disks)} drive{'s' if len(self._disks) != 1 else ''}. Huginn needs at least {size_text(MIN_BYTES)}." if big
                              else f"Huginn needs at least {size_text(MIN_BYTES)} on one drive.")})
        net = w.get("wired") or w.get("connected")
        rows.append({"key": "online", "state": "ok" if net else "info",
                     "title": ("Online by cable" if w.get("wired") else f"Online through {w['connected']}") if net else "Not online",
                     "line": "For media formats, drivers and the latest fixes. Huginn installs without it too." if net
                             else "Huginn installs without it; media formats, drivers and apps then come the first time it's online.",
                     "action": "" if net or not w.get("available", True) else "wifi"})
        if self._firmware == "uefi":
            rows.append({"key": "secureboot", "state": "ok", "title": "Secure Boot is on, and that's fine" if self._secure == "on" else "Secure Boot is off",
                         "line": "Huginn starts with it on. Nothing to change in the firmware." if self._secure == "on"
                                 else "Huginn starts either way. You can turn it on in the firmware later."})
        else:
            rows.append({"key": "secureboot", "state": "info", "title": "An older way of starting (BIOS)", "line": "Huginn starts this way too."})
        win = self._windows
        if win["state"] in ("ok", "no") and win.get("fastStartup"):
            rows.append({"key": "faststartup", "state": "warn", "title": "Windows' Fast Startup is on",
                         "line": "Windows only half shuts down, so its drive isn't safe to share or read. In Windows: Power Options › "
                                 "Choose what the power buttons do › untick Turn on fast startup, then shut down."})
        elif any(d.get("shrinkPart") for d in self._disks):
            rows.append({"key": "faststartup", "state": "ok", "title": "Windows is fully shut down", "line": "Its drive can be shared and read."})
        if any(d.get("bitlocker") for d in self._disks):
            rows.append({"key": "bitlocker", "state": "warn", "title": "BitLocker is on", "line": "Huginn can't make room in a locked Windows. Turn BitLocker off in Windows first, or install on another drive."})
        elif any(d.get("shrinkPart") for d in self._disks):
            rows.append({"key": "bitlocker", "state": "ok", "title": "BitLocker is off", "line": "Windows' drive can make room for Huginn."})
        if self._hw["memory"]:
            gb = self._hw["memory"] / GIB
            rows.append({"key": "memory", "state": "ok" if gb >= 3.5 else "warn", "title": f"{gb:.0f} GB of memory",
                         "line": "Plenty for Huginn." if gb >= 7.5 else "Enough for Huginn." if gb >= 3.5 else "Huginn wants 4 GB; it will be slow with less."})
        return rows

    def _works(self) -> list:
        """What works out of the box: {state, title, line}."""
        out = []
        for g in self._gpus:
            line = {"nvidia": "Works now; NVIDIA's own driver (faster for games) can be added in Extras.", "amd": "Built in. Games and Clips get full speed.",
                    "intel": "Built in.", "other": "Works."}[g["vendor"]]
            out.append({"state": "ok", "title": g["name"], "line": line})
        hw = self._hw
        if hw["wifi"] or hw["bluetooth"]:
            out.append({"state": "ok", "title": " and ".join(x for x, on in (("Wi‑Fi", hw["wifi"]), ("Bluetooth", hw["bluetooth"])) if on), "line": "Found."})
        found = [x for x, on in (("sound", hw["sound"]), ("a camera", hw["camera"])) if on]
        if found:
            out.append({"state": "ok", "title": " and ".join(found).capitalize(), "line": "Found."})
        return out

    check = Property("QVariantList", _check, notify=changed)
    works = Property("QVariantList", _works, notify=changed)

    # ------------------------------------------------------------------ extras, apps, Windows, safety
    def _extras_view(self) -> dict:
        return dict(self._extras, hasNvidia=any(g["vendor"] == "nvidia" for g in self._gpus), online=bool(self._wifi.get("wired") or self._wifi.get("connected")))
    extras = Property("QVariantMap", _extras_view, notify=changed)

    @Slot(str, "QVariant")
    def setExtra(self, key: str, value) -> None:
        value = value.toVariant() if hasattr(value, "toVariant") else value
        if key == "codecs" and value in ("download", "build", "none"):
            self._extras["codecs"] = value
        elif key in ("msfonts", "scripts", "printers", "nvidia"):
            self._extras[key] = bool(value) and (key != "nvidia" or any(g["vendor"] == "nvidia" for g in self._gpus))
        else:
            return
        self.changed.emit()

    def _apps_view(self) -> dict:
        found = [{"key": k, "name": engine.WINDOWS_APPS[k][0], "on": k in self._apps["fromWindows"]} for k in self._windows.get("apps", []) if k in engine.WINDOWS_APPS]
        return dict(self._apps, windowsApps=found)
    apps = Property("QVariantMap", _apps_view, notify=changed)

    @Slot(str, "QVariant")
    def setApp(self, key: str, value) -> None:
        value = value.toVariant() if hasattr(value, "toVariant") else value
        if key in ("gamedev", "flathub"):
            self._apps[key] = bool(value)
        elif key == "windowsApp" and isinstance(value, str) and value in engine.WINDOWS_APPS:
            have = self._apps["fromWindows"]
            self._apps["fromWindows"] = [k for k in have if k != value] if value in have else have + [value]
        elif key == "allWindowsApps":
            self._apps["fromWindows"] = list(self._windows.get("apps", [])) if value else []
        else:
            return
        self.changed.emit()

    def _windows_part(self) -> str:
        return next((d["shrinkPart"] for d in self._disks if d.get("shrinkPart")), "")

    def _windows_here(self) -> bool:
        """Windows found, and staying (it isn't on the disk being erased)."""
        part = self._windows_part()
        if not part:
            return False
        disk = next((d for d in self._disks if d.get("shrinkPart") == part), {})
        return not (self._mode == "erase" and disk.get("path") == self._disk)

    def _probe_windows(self) -> None:
        """What's in Windows: its people, their folders and apps (the engine looks, read-only, as root)."""
        part = self._windows_part()
        if not part or self._win_probe is not None or self._windows["state"] in ("probing", "ok"):
            return
        self._windows = dict(self._windows, state="probing", part=part)
        if self._demo:
            demo = {"users": [{"name": "Astrid", "folders": {"documents": {"files": 2140, "bytes": 3 * 10 ** 9}, "pictures": {"files": 8902, "bytes": 41 * 10 ** 9},
                                                             "music": {"files": 1100, "bytes": 9 * 10 ** 9}, "videos": {"files": 210, "bytes": 60 * 10 ** 9},
                                                             "desktop": {"files": 66, "bytes": 2 * 10 ** 8}, "downloads": {"files": 400, "bytes": 5 * 10 ** 9}}}],
                    "apps": ["discord", "obs", "spotify", "vlc"], "fastStartup": False, "problem": "", "counted": True}
            QTimer.singleShot(500, lambda: self._windows_read(json.dumps(demo), part))
            return
        proc = QProcess(self)
        self._win_probe = proc
        proc.setProgram("pkexec")
        proc.setArguments([ENGINE, "--probe-windows", part])
        proc.finished.connect(lambda *_: self._windows_read(bytes(proc.readAllStandardOutput()).decode("utf-8", "replace"), part))
        proc.start()

    def _windows_read(self, out: str, part: str) -> None:
        self._win_probe = None
        try:
            got = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
        except ValueError:
            got = {}
        users = got.get("users") or []
        self._windows = {"state": "ok" if users else "no", "part": part, "users": users, "apps": [a for a in got.get("apps") or [] if a in engine.WINDOWS_APPS],
                         "fastStartup": bool(got.get("fastStartup")), "counted": got.get("counted", True),
                         "problem": got.get("problem") or ("" if users else "No one's things were found in Windows.")}
        if users and not self._bring["user"]:
            self._bring["user"] = max(users, key=lambda u: sum(f["files"] for f in u["folders"].values()))["name"]
        self.changed.emit()

    def _windows_view(self) -> dict:
        w, b = self._windows, self._bring
        person = next((u for u in w["users"] if u["name"] == b["user"]), None)
        folders = []
        for key, name in engine.WINDOWS_FOLDERS.items():
            f = (person or {}).get("folders", {}).get(key, {"files": 0, "bytes": 0})
            folders.append({"key": key, "name": name, "files": f["files"], "sizeText": size_text(f["bytes"]) if f["bytes"] else "", "on": key in b["folders"]})
        total = sum(f["bytes"] for k, f in ((person or {}).get("folders") or {}).items() if k in b["folders"])
        return {"state": w["state"], "here": self._windows_here(), "problem": w["problem"], "fastStartup": w["fastStartup"], "users": [u["name"] for u in w["users"]],
                "user": b["user"], "folders": folders, "how": b["how"], "skip": b["skip"], "sizeText": size_text(total) if total else "", "counted": w["counted"]}
    windows = Property("QVariantMap", _windows_view, notify=changed)

    @Slot(str, "QVariant")
    def setBring(self, key: str, value) -> None:
        value = value.toVariant() if hasattr(value, "toVariant") else value
        b = self._bring
        if key == "user" and value in [u["name"] for u in self._windows["users"]]:
            b["user"] = value
        elif key == "folder" and value in engine.WINDOWS_FOLDERS:
            b["folders"] = [f for f in b["folders"] if f != value] if value in b["folders"] else b["folders"] + [value]
        elif key == "how" and value in ("copy", "link"):
            b["how"] = value
        elif key == "skip":
            b["skip"] = bool(value)
        else:
            return
        self.changed.emit()

    def _safety_view(self) -> dict:
        return dict(self._safety, encrypt=self._encrypt, canEncrypt=self._mode != "manual", recoveryKey=self._recovery if self._encrypt else "",
                    recoveryWords=self._recovery.split("-") if self._encrypt else [])
    safety = Property("QVariantMap", _safety_view, notify=changed)

    @Slot(str, bool)
    def setSafety(self, key: str, on: bool) -> None:
        if key in self._safety:
            self._safety[key] = bool(on)
            self.changed.emit()

    @Slot()
    def newRecoveryKey(self) -> None:
        self._recovery = engine.recovery_key()
        self.changed.emit()

    # ------------------------------------------------------------------ help seeing, hearing and typing, from the first second
    access = Property("QVariantMap", lambda self: dict(self._access, hasReader=bool(shutil.which("orca")) or self._demo,
                                                     hasOsk=bool(shutil.which("squeekboard")) or self._demo), notify=changed)

    @Slot(str, bool)
    def setAccess(self, key: str, on: bool) -> None:
        """Turned on here at once (the window grows, stills, gets more contrast; the screen reader and on-screen keyboard
        start), and kept on in Huginn once it's installed."""
        if key not in self._access:
            return
        self._access[key] = bool(on)
        if not self._demo:
            prog = {"reader": ["orca", "--replace"], "osk": ["squeekboard"]}.get(key)
            if prog and shutil.which(prog[0]):
                if on:
                    subprocess.Popen(prog, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                else:
                    run(["pkill", "-x", prog[0]], timeout=5)
        self.changed.emit()

    sky = Property(str, lambda self: next((QUrl.fromLocalFile(str(f)).toString() for f in (Path("/usr/share/huginn-os/live/stills/aurora.jpg"),
                                                                                         HERE.parent / "config/overlay/usr/share/huginn-os/live/stills/aurora.jpg") if f.is_file()), ""), constant=True)

    # ------------------------------------------------------------------ what the dock shows on each island
    def _answers(self) -> list:
        d = self.chosenDisk
        where = {"erase": f"All of {d.get('model', 'a disk')}", "free": "Its free space", "shrink": "Beside Windows", "manual": "Your partitions"}.get(self._mode, "")
        warn = sum(1 for r in self._check() if r["state"] == "warn")
        codecs = {"download": "From Ubuntu", "build": "Built here", "none": "Open only"}[self._extras["codecs"]]
        w = self._windows_view()
        win = ("Not needed" if not w["here"] else "Skipped" if w["skip"] else f"{len(self._bring['folders'])} folders" if w["state"] == "ok"
               else "Looking…" if w["state"] == "probing" else "Nothing found" if w["state"] == "no" else "")
        out = {"welcome": self.languageLabel.split(" (")[0].replace("American English", "English").replace("British English", "English (UK)"), "keyboard": self._layout.upper(),
               "check": ("All good" if not warn else f"{warn} to see to"), "disk": where, "extras": codecs,
               "apps": "+ game tools" if self._apps["gamedev"] else ("+ " + str(len(self._apps["fromWindows"])) + " apps" if self._apps["fromWindows"] else "Included"),
               "windows": win, "you": (self._you["name"] or ""), "time": self.zoneCity, "safety": "Encrypted" if self._encrypt else "Not locked", "ready": ""}
        return [{"id": k, "label": l, "answer": out.get(k, ""), "here": i == self._step, "done": i < self._step,
                 "off": k == "windows" and not self._windows_here()} for i, (k, l) in enumerate(zip(STEPS, LABELS))]
    answers = Property("QVariantList", _answers, notify=summaryChanged)

    # ------------------------------------------------------------------ the plan, and installing it
    def _plan(self) -> dict:
        d = self.chosenDisk
        u = self._you
        p = {"mode": self._mode, "disk": self._disk, "firmware": self._firmware, "encrypt": self._encrypt, "passphrase": self._passphrase if self._encrypt else "",
             "hostname": engine.good_hostname(u["hostname"] or (u["name"] + "-" + chassis())),
             "user": {"name": u["name"], "realName": u["realName"].strip(), "password": u["password"], "autologin": u["autologin"]},
             "timezone": self._zone, "locale": self._lang + ".UTF-8", "keyboard": {"layout": self._layout, "variant": ""}}
        p["removable"] = bool(d.get("removable")) or d.get("kind") == "USB drive"
        if self._mode == "free":
            p["freeStart"] = d.get("freeStart", 0)
        if self._mode == "shrink":
            p.update(shrinkPart=d.get("shrinkPart", ""), keepBytes=self._shrink["size"] - self._shrink["huginn"])
        if self._mode == "manual":
            p.update(root=self._root, efi=self._efi, formatEfi=self._format_efi)
        if self._encrypt:
            p["recoveryKey"] = self._recovery
        p["extras"] = dict(self._extras)
        p["apps"] = {"gamedev": self._apps["gamedev"], "flathub": self._apps["flathub"], "fromWindows": list(self._apps["fromWindows"])}
        p["safety"] = dict(self._safety)
        p["access"] = {k: v for k, v in self._access.items() if k != "contrast"}
        b = self._bring
        if self._windows_here() and self._windows["state"] == "ok" and not b["skip"] and b["user"]:
            p["windows"] = {"part": self._windows["part"], "user": b["user"], "folders": list(b["folders"]), "how": b["how"]}
        return p

    def _summary(self) -> list:
        d, u = self.chosenDisk, self._you
        where = {"erase": f"Erase {d.get('model', '')} ({d.get('sizeText', '')}) and put Huginn OS on all of it",
                 "free": f"Put Huginn OS in the {d.get('freeText', '')} of free space on {d.get('model', '')}" + (f", beside {' and '.join(d.get('systems'))}" if d.get("systems") else ""),
                 "shrink": f"Shrink {d.get('shrinkLabel', 'Windows')} to {size_text(self._shrink['size'] - self._shrink['huginn'])} and put Huginn OS "
                           f"in the {size_text(self._shrink['huginn'])} that frees, on {d.get('model', '')}. You'll choose which to start each time, "
                           f"and Windows checks its disk once, the first time it starts again",
                 "manual": f"Put Huginn OS on {self._root} (it will be formatted)" + (f", starting from {self._efi}" if self._efi else "")}[self._mode]
        rows = [{"label": "Disk", "value": where, "warn": self._mode in ("erase", "shrink")},
                {"label": "Encryption", "value": "On: the disk asks for its password when the computer starts, and the recovery key opens it too" if self._encrypt else "Off"},
                {"label": "Extras", "value": ", ".join(x for x in (
                    {"download": "Media formats from Ubuntu", "build": "Media formats built on this computer", "none": ""}[self._extras["codecs"]],
                    "Microsoft's fonts" if self._extras["msfonts"] else "", "fonts for every script" if self._extras["scripts"] else "",
                    "printer drivers" if self._extras["printers"] else "", "NVIDIA's driver" if self._extras["nvidia"] else "") if x) or "None"},
                {"label": "Apps", "value": "Huginn's own" + (", game-development tools" if self._apps["gamedev"] else "")
                    + (", " + ", ".join(engine.WINDOWS_APPS[k][0] for k in self._apps["fromWindows"]) if self._apps["fromWindows"] else "")
                    + ("; Flathub on" if self._apps["flathub"] else "; Flathub off")},
                {"label": "You", "value": f"{u['realName'].strip()} ({u['name']})" + (", signing in by yourself" if u["autologin"] else "")},
                {"label": "Computer name", "value": engine.good_hostname(u["hostname"])},
                {"label": "Language", "value": self.languageLabel},
                {"label": "Keyboard", "value": self.layoutLabel},
                {"label": "Time zone", "value": self.zoneLabel}]
        plan_win = self._plan().get("windows")
        if plan_win:
            rows.insert(4, {"label": "From Windows", "value": (f"{plan_win['user']}'s " + ", ".join(engine.WINDOWS_FOLDERS[f] for f in plan_win["folders"])
                                                               + " copied after the first start" if plan_win["how"] == "copy" else f"{plan_win['user']}'s folders shown in Files, read-only")})
        if any(self._plan().get(k) for k in ("extras",)) and (self._extras["codecs"] != "none" or self._extras["msfonts"] or self._extras["scripts"] or self._apps["gamedev"] or self._apps["fromWindows"]):
            rows.append({"label": "After the first start", "value": "What needs the internet comes in the background the first time Huginn is online."})
        return rows

    # ---------------------------------------------------------------- beside Windows
    def _start_probe(self) -> None:
        """How far Windows' partition can shrink: the engine asks ntfsresize (as root, through pkexec; on the live
        system no password is asked). It also says when Windows can't be shrunk now (Fast Startup, a disk check)."""
        d = self.chosenDisk
        part = d.get("shrinkPart", "")
        if not part:
            self._shrink = {"state": "no", "size": 0, "min": 0, "huginn": 0, "why": "There's no Windows partition here to make room in."}
            return
        if self._probe is not None:
            return
        self._shrink = {"state": "probing", "size": d.get("shrinkSize", 0), "min": 0, "huginn": 0, "why": ""}
        if self._demo:
            QTimer.singleShot(600, lambda: self._probed(json.dumps({"size": d.get("shrinkSize", 0), "min": 142 * 10 ** 9, "problem": ""}), part))
            return
        proc = QProcess(self)
        self._probe = proc
        proc.setProgram("pkexec")
        proc.setArguments([ENGINE, "--probe-ntfs", part])
        proc.finished.connect(lambda *_: self._probed(bytes(proc.readAllStandardOutput()).decode("utf-8", "replace"), part))
        proc.start()

    def _probed(self, out: str, part: str) -> None:
        self._probe = None
        try:
            got = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
        except ValueError:
            got = {}
        size, least, why = int(got.get("size") or 0), int(got.get("min") or 0), got.get("problem") or ""
        if not size or not least or why:
            self._shrink = {"state": "no", "size": size, "min": least, "huginn": 0,
                            "why": why or "Windows' partition couldn't be looked at (the password may have been refused)."}
        else:
            keep_least = least + 10 * 10 ** 9                       # Windows keeps what it has, and room to work in
            room = max(0, size - keep_least)
            huginn = min(room, max(MIN_BYTES * 2, size // 3)) // GIB * GIB
            self._shrink = {"state": "ok", "size": size, "min": keep_least, "huginn": huginn, "why": ""}
        self.changed.emit()

    @Slot(float)
    def setShare(self, fraction: float) -> None:
        """The slider: how much of the room Windows can give goes to Huginn OS (0…1)."""
        sh = self._shrink
        if sh["state"] != "ok":
            return
        room = max(0, sh["size"] - sh["min"])
        self._shrink = dict(sh, huginn=int(max(0.0, min(1.0, fraction)) * room) // GIB * GIB)
        self.changed.emit()

    def _shrink_view(self) -> dict:
        sh = self._shrink
        room = max(1, sh["size"] - sh["min"])
        return {"state": sh["state"], "why": sh["why"], "share": sh["huginn"] / room if sh["state"] == "ok" else 0,
                "huginnText": size_text(sh["huginn"]), "windowsText": size_text(sh["size"] - sh["huginn"]),
                "huginnFraction": sh["huginn"] / max(1, self.chosenDisk.get("size", 1)), "windowsLeast": size_text(sh["min"])}
    shrink = Property("QVariantMap", _shrink_view, notify=changed)

    summary = Property("QVariantList", _summary, notify=summaryChanged)

    def _phases(self) -> list:
        """While installing: each of the engine's steps, done, being done or still to do."""
        out, base = [], 0.0
        for _k, label, w in engine.WEIGHTS:
            state = "done" if self._state == "done" or self._fraction >= base + w - 1e-6 else "now" if self._fraction >= base else "todo"
            out.append({"label": label, "state": state})
            base += w
        return out
    phases = Property("QVariantList", _phases, notify=progressed)

    def _later(self) -> str:
        """What comes after the first start, said once while installing."""
        t = engine.first_start_tasks(self._plan(), "x" if self._plan().get("windows") else "")
        parts = [x for x, on in (("media formats", self._extras["codecs"] != "none"), ("fonts", bool(set(t["packages"]) & {"ttf-mscorefonts-installer", *engine.SCRIPT_FONTS})),
                                ("drivers", t["drivers"] or bool(set(t["packages"]) & set(engine.PRINTER_PACKAGES))), ("apps", bool(t["flatpaks"])),
                                ("your things from Windows", bool(t["windows"]))) if on]
        if not parts:
            return ""
        said = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
        return said[0].upper() + said[1:] + " come after the first start, in the background, the first time Huginn is online."
    later = Property(str, _later, notify=summaryChanged)
    fraction = Property(float, lambda self: self._fraction, notify=progressed)
    label = Property(str, lambda self: self._label, notify=progressed)
    note = Property(str, lambda self: self._note, notify=progressed)
    error = Property(str, lambda self: self._error, notify=changed)
    log = Property(str, lambda self: "\n".join(self._log[-400:]), notify=progressed)

    @Slot()
    def install(self) -> None:
        if self._state == "installing":
            return
        plan = self._plan()
        problems = engine.check_plan(plan)
        if problems:
            self.said.emit(" ".join(problems), True)
            return
        self._state, self._fraction, self._label, self._error, self._log = "installing", 0.0, "Starting", "", []
        self.changed.emit(); self.progressed.emit()
        if self._demo:
            self._demo_install()
            return
        self._proc = QProcess(self)
        self._proc.setProgram("pkexec")
        self._proc.setArguments([ENGINE])
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.readyReadStandardError.connect(lambda: self._log.extend(bytes(self._proc.readAllStandardError()).decode(errors="replace").splitlines()))
        self._proc.finished.connect(self._ended)
        self._buf = b""
        self._proc.start()
        self._proc.write(json.dumps(plan).encode())        # the plan, passwords included, only ever goes down this pipe
        self._proc.closeWriteChannel()
        self._you["password"] = self._you["again"] = ""
        self._passphrase = ""

    def _read(self) -> None:
        self._buf += bytes(self._proc.readAllStandardOutput())
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            self._take(line.decode(errors="replace"))

    def _take(self, line: str) -> None:
        try:
            msg = json.loads(line)
        except ValueError:
            self._log.append(line)
            self.progressed.emit()
            return
        if "fraction" in msg:
            self._fraction, self._label, self._note = msg["fraction"], msg.get("label", ""), msg.get("note", "")
            self._log.append(f"{msg.get('label', '')} {msg.get('note', '')}".strip())
        elif msg.get("done"):
            self._state, self._fraction = "done", 1.0
            self.changed.emit()
        elif "error" in msg:
            self._state, self._error = "error", msg["error"]
            self._log.extend((msg.get("log") or "").splitlines())
            self.changed.emit()
        self.progressed.emit()

    def _ended(self, code: int, _status) -> None:
        if self._state == "installing":                     # it stopped without saying why (pkexec refused, a crash)
            self._state = "error"
            self._error = "The installer couldn't get permission to change the disks." if code in (126, 127) else f"The installer stopped (code {code})."
            self.changed.emit()

    def _demo_install(self) -> None:
        self._demo_t = 0

        def tick():
            self._demo_t += 1
            f = min(1.0, self._demo_t / 60)
            base = 0.0
            for k, label, w in engine.WEIGHTS:
                if f <= base + w:
                    self._label = label
                    break
                base += w
            self._fraction = f
            self._note = f"{int((f - 0.07) / 0.68 * 100)}%" if 0.07 < f < 0.75 else ""
            self._log.append(f"{self._label} {self._note}".strip())
            self.progressed.emit()
            if f >= 1.0:
                self._demo_timer.stop()
                self._state = "done"
                self.changed.emit()
        self._demo_timer = QTimer(self, interval=80, timeout=tick)
        self._demo_timer.start()

    @Slot()
    def retry(self) -> None:
        if self._state == "error":
            self._state, self._step = "setup", STEPS.index("ready")
            self.changed.emit()

    @Slot()
    def restart(self) -> None:
        if self._demo:
            self.said.emit("(Demo: this would restart the computer.)", False)
            return
        run(["systemctl", "reboot"], timeout=10)

    @Slot(result=str)
    def saveLog(self) -> str:
        path = Path.home() / "huginn-installer.log"
        try:
            path.write_text("\n".join(self._log) + "\n", encoding="utf-8")
            return str(path)
        except OSError:
            return ""


def ascii_name(text: str) -> str:
    """Hélène → helene, Bjørn → bjorn, Æsa → aesa: a name as plain letters, for a user name."""
    import unicodedata
    for a, b in (("æ", "ae"), ("ø", "o"), ("ß", "ss"), ("þ", "th"), ("ð", "d"), ("œ", "oe")):
        text = text.replace(a, b)
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def strength(pw: str) -> int:
    """0 (none) … 4 (strong): length and variety, roughly."""
    if not pw:
        return 0
    kinds = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    score = (len(pw) >= 8) + (len(pw) >= 12) + (len(pw) >= 16) + (kinds >= 3)
    return max(1, min(4, score))
