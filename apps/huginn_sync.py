#!/usr/bin/env python3
"""Huginn sync: your Notes, Reminders and Huginn OS's settings kept in step across your computers, beside what Huginn
(the browser) already syncs with Bifröst: Favorites, the Reading List, passwords and open tabs.

    one group   the browser's Bifröst group: the same 256-bit key (in the desktop's keyring, or a file only you can
                read) and the same sync folder you choose (Syncthing, Nextcloud, a network share, a USB stick). Set it
                up here or in the browser and both sync; a pairing key (HB1-… or HB2-…) from any Huginn joins it.
    files       each computer writes only its own sealed file into the group's folder (the browser
                <device>.huginnsync, the system <device>.huginnos), so a file-syncing service never sees a conflict.
    sealing     AES-256-GCM with a key made from the group key (HKDF), as the browser does: without the group key the
                folder is unreadable, to the service that copies it and to anyone who finds the USB stick.
    merging     per item, the newest change wins; deletions are remembered for 180 days. A note changed on two
                computers between syncs is never lost: the other version is kept beside it, named after its computer.
    when        a few minutes after sign-in and every five minutes after (huginn-sync.timer), and Sync Now in
                Settings › Sync.

The Bifröst pieces here are the browser's own (safari_browser.py), kept the same so the two always understand each
other; ci-smoke checks that against the browser's copy.

    huginn-sync run | status | setup FOLDER | join KEY [FOLDER] | folder PATH | key | collections a,b | leave
"""
import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:                                               # python3-cryptography is in the image
    AESGCM = None

    class InvalidTag(Exception):
        pass

# ------------------------------------------------------------------------------- Bifröst, as the browser has it
BIFROST_FORMAT = "Huginn Bifrost"
BIFROST_TOMBSTONE_DAYS = 180
BIFROST_MAX_BLOB = 64 * 1024 * 1024
BIFROST_KEY_PREFIX = "HB1"
BROWSER_COLLECTIONS = ("bookmarks", "reading", "passwords", "tabs")
COLLECTIONS = ("notes", "reminders", "settings")                  # what the system syncs
OWN_SUFFIX = ".huginnos"
BROWSER_SUFFIX = ".huginnsync"


def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _hkdf(key: bytes, info: bytes, length: int = 32) -> bytes:
    """HKDF-SHA256 (RFC 5869), no salt."""
    prk = hmac.new(b"\0" * 32, key, hashlib.sha256).digest()
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def bifrost_keys(secret: bytes) -> dict:
    return {"data": _hkdf(secret, b"huginn bifrost data v1"), "auth": _hkdf(secret, b"huginn bifrost auth v1"),
            "group": hashlib.sha256(b"huginn bifrost group v1" + secret).hexdigest()[:16]}


def bifrost_key_text(secret: bytes, password_key: bytes = None) -> str:
    raw = secret + (password_key or b"")
    check = hashlib.sha256(b"check" + raw).digest()[:3]
    body = base64.b32encode(raw + check).decode("ascii").rstrip("=")
    prefix = "HB2" if password_key else BIFROST_KEY_PREFIX
    return prefix + "-" + "-".join(body[i:i + 4] for i in range(0, len(body), 4))


def bifrost_key_from_text(text: str):
    """(group key, password key or None) from a pairing key, or None if it isn't one."""
    text = str(text or "").upper().strip()
    match = re.match(r"\s*(HB[12])\b", text)
    if not match:
        return None
    body = re.sub(r"[^A-Z2-7]", "", text[match.end():])
    try:
        raw = base64.b32decode(body + "=" * (-len(body) % 8))
    except (ValueError, base64.binascii.Error):
        return None
    size = 67 if match.group(1) == "HB2" else 35
    if len(raw) != size or not hmac.compare_digest(hashlib.sha256(b"check" + raw[:-3]).digest()[:3], raw[-3:]):
        return None
    return raw[:32], (raw[32:64] if size == 67 else None)


def bifrost_seal(secret: bytes, device: str, payload: dict) -> bytes:
    keys = bifrost_keys(secret)
    nonce = os.urandom(12)
    aad = f"bifrost1|{keys['group']}|{device}".encode()
    body = zlib.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 6)
    sealed = nonce + AESGCM(keys["data"]).encrypt(nonce, body, aad)
    return json.dumps({"format": BIFROST_FORMAT, "v": 1, "group": keys["group"], "device": device,
                       "data": _b64e(sealed)}).encode("utf-8")


def bifrost_open(secret: bytes, blob: bytes):
    """A device's sealed state, or None if it isn't one of ours (or was altered)."""
    keys = bifrost_keys(secret)
    try:
        envelope = json.loads(blob.decode("utf-8"))
        if envelope.get("format") != BIFROST_FORMAT or envelope.get("group") != keys["group"]:
            return None
        device = str(envelope["device"])
        sealed = _b64d(envelope["data"])
        aad = f"bifrost1|{keys['group']}|{device}".encode()
        body = AESGCM(keys["data"]).decrypt(sealed[:12], sealed[12:], aad)
        inflater = zlib.decompressobj()
        text = inflater.decompress(body, BIFROST_MAX_BLOB * 4)
        if inflater.unconsumed_tail:
            return None
        payload = json.loads(text.decode("utf-8"))
    except (ValueError, KeyError, TypeError, AttributeError, InvalidTag, zlib.error, UnicodeDecodeError, base64.binascii.Error):
        return None
    if not isinstance(payload, dict) or payload.get("device") != device or not isinstance(payload.get("records"), list):
        return None
    return payload


def bifrost_hash(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]


def bifrost_scan(known: dict, current: dict, device: str, collections, now: float = None) -> int:
    """Notes what changed here since the last look: new and changed items get this device and a time later than the
    item's last; items gone get a tombstone. Returns how many changed."""
    now = now or time.time()
    changed = 0
    for collection in collections:
        if collection not in current:
            continue
        have = known.setdefault(collection, {})
        items = current[collection]
        for item_id, data in items.items():
            h = bifrost_hash(data)
            record = have.get(item_id)
            if record is None or record.get("del") or record.get("h") != h:
                stamp = max(now, float((record or {}).get("m") or 0) + 0.001)
                have[item_id] = {"h": h, "m": stamp, "d": device, "x": data}
                changed += 1
        for item_id, record in list(have.items()):
            if item_id not in items and not record.get("del"):
                have[item_id] = {"h": "", "m": max(now, float(record.get("m") or 0) + 0.001), "d": device, "x": None, "del": True}
                changed += 1
    cutoff = now - BIFROST_TOMBSTONE_DAYS * 86400
    for have in known.values():
        for item_id, record in list(have.items()):
            if record.get("del") and record.get("m", 0) < cutoff:
                del have[item_id]
    return changed


def bifrost_records(known: dict, collections) -> list:
    return [{"c": c, "i": i, "m": r["m"], "d": r["d"], "h": r.get("h", ""), "x": r.get("x"), **({"del": True} if r.get("del") else {})}
            for c in collections for i, r in known.get(c, {}).items()]


def bifrost_merge(known: dict, records: list, collections, now: float = None) -> dict:
    """Takes what's newer from another device: {collection: {id: data or None}} to apply here (None: delete). A time far
    in the future counts as no later than tomorrow."""
    latest = (now or time.time()) + 86400
    changes = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        collection, item_id = record.get("c"), record.get("i")
        if collection not in collections or not isinstance(item_id, str) or not 0 < len(item_id) <= 64:
            continue
        try:
            when = float(record.get("m"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(when) or when <= 0:
            continue
        stamp = (min(when, latest), str(record.get("d") or "")[:32])
        deleted = bool(record.get("del"))
        data = None if deleted else record.get("x")
        if not deleted and not isinstance(data, dict):
            continue
        have = known.setdefault(collection, {})
        mine = have.get(item_id)
        if mine is not None and (float(mine.get("m", 0)), str(mine.get("d", ""))) >= stamp:
            continue
        h = record.get("h") if isinstance(record.get("h"), str) and 0 < len(record["h"]) <= 64 else bifrost_hash(data)
        have[item_id] = {"h": "" if deleted else h, "m": stamp[0], "d": stamp[1], "x": data, **({"del": True} if deleted else {})}
        changes.setdefault(collection, {})[item_id] = data
    return changes


def bifrost_item_id(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:24]


def read_device_file(path: Path):
    """A device's file from the sync folder: only a regular file (never a link, or a pipe that would never finish),
    and not a huge one."""
    try:
        if os.path.islink(path):
            return None
        handle = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode) or info.st_size > BIFROST_MAX_BLOB:
            return None
        with os.fdopen(handle, "rb") as f:
            handle = -1
            return f.read(BIFROST_MAX_BLOB + 1)
    except OSError:
        return None
    finally:
        if handle != -1:
            os.close(handle)


# ------------------------------------------------------------------------------------------------ where things are
def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def browser_dir() -> Path:
    """The browser's Bifröst folder (its key file, if there's no keyring, and its settings: the sync folder)."""
    for name in ("SafariQt/SafariQt", "Huginn/Huginn"):
        if (_data_home() / name / "bifrost").is_dir():
            return _data_home() / name / "bifrost"
    return _data_home() / "SafariQt/SafariQt/bifrost"


def own_dir() -> Path:
    return _data_home() / "huginn" / "sync"


def documents() -> Path:
    try:
        out = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True, text=True, timeout=5).stdout.strip()
        if out and out != str(Path.home()):
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Documents"


def notes_dir() -> Path:
    return documents() / "Notes"


def reminders_file() -> Path:
    return _data_home() / "huginn" / "reminders.json"


def settings_file() -> Path:
    return _config_home() / "huginn-shell" / "settings.json"


def device_name() -> str:
    try:
        for line in Path("/etc/machine-info").read_text().splitlines():
            if line.startswith("PRETTY_HOSTNAME="):
                name = line.split("=", 1)[1].strip().strip('"')
                if name:
                    return name[:60]
    except OSError:
        pass
    return (socket.gethostname() or "This computer")[:60]


# ------------------------------------------------------------------------------------------ the group key
class KeyKeeper:
    """Where the group key lives: the browser's place for it, so both find the same key. The desktop's keyring
    (secret-tool) when one is running, or a file only you can read."""
    SERVICE = "Huginn Bifrost"

    def __init__(self, folder: Path = None):
        self.folder = Path(folder) if folder else browser_dir()

    def _file(self) -> Path:
        return self.folder / "key"

    def load(self):
        if shutil.which("secret-tool"):
            try:
                out = subprocess.run(["secret-tool", "lookup", "service", "huginn-bifrost", "key", "group"], capture_output=True, timeout=20)
                if out.returncode == 0 and out.stdout.strip():
                    key = bytes.fromhex(out.stdout.decode().strip())
                    if len(key) == 32:
                        return key
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        try:
            key = bytes.fromhex(self._file().read_text().strip())
            return key if len(key) == 32 else None
        except (OSError, ValueError):
            return None

    def where(self) -> str:
        return "in a file only your account can read" if self._file().exists() else "in the desktop's keyring"

    def save(self, secret: bytes) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        if shutil.which("secret-tool"):
            try:
                subprocess.run(["secret-tool", "store", "--label", self.SERVICE, "service", "huginn-bifrost", "key", "group"],
                               input=secret.hex().encode(), check=True, capture_output=True, timeout=20)
                try:
                    self._file().unlink()
                except OSError:
                    pass
                return
            except (OSError, subprocess.SubprocessError):
                pass                                              # no keyring running: the file
        tmp = self._file().with_suffix(".tmp")
        try:
            tmp.unlink()
        except OSError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secret.hex())
        os.replace(tmp, self._file())

    def delete(self) -> None:
        if shutil.which("secret-tool"):
            subprocess.run(["secret-tool", "clear", "service", "huginn-bifrost", "key", "group"], capture_output=True, timeout=20)
        try:
            self._file().unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------------------------- what syncs here
SETTINGS_KEPT_HERE = {"uiScale", "adaptiveSync", "allowTearing", "sharpX11", "widgets", "wallpaperStamp", "overviewOpen",
                      "frameTimes", "gameStats", "barEverywhere", "spacesAllScreens"}   # this computer's screens and hardware
NOTE_MAX = 2 * 1024 * 1024


def _safe_name(name: str) -> str:
    """A note's file name from another computer: a plain name in the Notes folder, never a path."""
    name = str(name or "").replace("/", "-").replace("\\", "-").replace("\0", "").strip()
    name = re.sub(r"[\x00-\x1f]", "", name).lstrip(".")[:200]
    if not name or Path(name).suffix.lower() not in (".md", ".txt"):
        return ""
    return name


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".huginn-sync-", suffix=".part")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _to_trash(path: Path) -> None:
    """A note deleted on another computer goes to the Trash here, not away for good."""
    if shutil.which("gio") and subprocess.run(["gio", "trash", str(path)], capture_output=True, timeout=20).returncode == 0:
        return
    try:
        path.unlink()
    except OSError:
        pass


class Local:
    """This computer's Notes, Reminders and settings, as items: scan() reads them, apply() writes another computer's."""

    def __init__(self, notes: Path = None, reminders: Path = None, settings: Path = None, name: str = ""):
        self.notes = Path(notes) if notes else notes_dir()
        self.reminders = Path(reminders) if reminders else reminders_file()
        self.settings = Path(settings) if settings else settings_file()
        self.name = name or device_name()
        self.kept_copies = []                                     # notes kept beside another computer's version

    # notes: one item each, by name
    def _note_files(self) -> dict:
        out = {}
        if self.notes.is_dir():
            for p in self.notes.iterdir():
                try:
                    if p.suffix.lower() in (".md", ".txt") and p.is_file() and not p.is_symlink() and not p.name.startswith(".") \
                            and p.stat().st_size <= NOTE_MAX:
                        out[bifrost_item_id("note", p.name.lower())] = p
                except OSError:
                    continue
        return out

    def scan_notes(self) -> dict:
        items = {}
        for item_id, p in self._note_files().items():
            try:
                items[item_id] = {"name": p.name, "text": p.read_text(encoding="utf-8", errors="replace")}
            except OSError:
                continue
        return items

    def apply_notes(self, changes: dict, conflicts: set) -> None:
        files = self._note_files()
        for item_id, data in changes.items():
            here = files.get(item_id)
            if data is None:
                if here is not None:
                    _to_trash(here)
                continue
            name = _safe_name(data.get("name"))
            text = data.get("text")
            if not name or not isinstance(text, str) or len(text.encode("utf-8")) > NOTE_MAX:
                continue
            target = here or self.notes / name
            if here is not None and item_id in conflicts:         # changed here too, from another version: keep ours beside it
                try:
                    mine = here.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    mine = None
                if mine is not None and mine != text:
                    copy = self._free_name(here.stem + f" ({self.name})", here.suffix)
                    _write(copy, mine)
                    self.kept_copies.append(copy.name)
            _write(target, text)

    def _free_name(self, stem: str, suffix: str) -> Path:
        stem = stem.replace("/", "-")[:180]
        n, path = 1, self.notes / f"{stem}{suffix}"
        while path.exists():
            n += 1
            path = self.notes / f"{stem} {n}{suffix}"
        return path

    # reminders: each reminder by its id, each list by its name
    def _read_reminders(self) -> dict:
        try:
            data = json.loads(self.reminders.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def scan_reminders(self) -> dict:
        data = self._read_reminders()
        items = {}
        for item in data.get("items", []):
            if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("title"), str):
                items[bifrost_item_id("reminder", item["id"])] = {"item": item}
        for name in data.get("lists", []):
            if isinstance(name, str) and name.strip():
                items[bifrost_item_id("list", name)] = {"list": name}
        return items

    def apply_reminders(self, changes: dict) -> None:
        import fcntl
        self.reminders.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self.reminders) + ".lock", "w") as lock:   # the Reminders app's own lock
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self._read_reminders()
            items = [i for i in data.get("items", []) if isinstance(i, dict) and isinstance(i.get("id"), str)]
            lists = [n for n in data.get("lists", []) if isinstance(n, str)]
            by_id = {bifrost_item_id("reminder", i["id"]): n for n, i in enumerate(items)}
            drop, drop_lists = set(), set()
            for item_id, change in changes.items():
                if change is None:
                    if item_id in by_id:
                        drop.add(by_id[item_id])
                    for name in lists:
                        if bifrost_item_id("list", name) == item_id:
                            drop_lists.add(name)
                elif isinstance(change.get("item"), dict) and isinstance(change["item"].get("id"), str) and isinstance(change["item"].get("title"), str):
                    if item_id in by_id:
                        items[by_id[item_id]] = change["item"]
                    else:
                        by_id[item_id] = len(items)
                        items.append(change["item"])
                elif isinstance(change.get("list"), str) and change["list"].strip() and change["list"] not in lists:
                    lists.append(change["list"])
            items = [i for n, i in enumerate(items) if n not in drop]
            used = {i.get("list") for i in items}
            lists = [n for n in lists if n not in drop_lists or n in used]   # (a list still holding reminders stays)
            data["items"], data["lists"] = items, lists or ["Reminders"]
            data.setdefault("gone", {})
            part = self.reminders.with_name(".reminders.json.saving")
            part.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(part, self.reminders)

    # Huginn OS's settings: each setting by its name, but not this computer's own (its screens, its hardware)
    def _read_settings(self) -> dict:
        try:
            data = json.loads(self.settings.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _shared(key: str, value) -> bool:
        if key in SETTINGS_KEPT_HERE:
            return False
        if key == "wallpaper":                                    # one that comes with Huginn OS, never a file of yours
            return isinstance(value, str) and (value == "" or value.startswith("/usr/share/"))
        return True

    def scan_settings(self) -> dict:
        return {bifrost_item_id("setting", k): {"k": k, "v": v} for k, v in self._read_settings().items() if self._shared(k, v)}

    def apply_settings(self, changes: dict) -> None:
        data = self._read_settings()
        known = {bifrost_item_id("setting", k): k for k in data}
        before = dict(data)
        for item_id, change in changes.items():
            if change is None:
                if item_id in known and self._shared(known[item_id], data.get(known[item_id])):
                    data.pop(known[item_id], None)
            elif isinstance(change.get("k"), str) and self._shared(change["k"], change.get("v")):
                data[change["k"]] = change.get("v")
        if data != before:
            _write(self.settings, json.dumps(data, indent=1))     # the shell and the apps watch it, and follow

    # together
    def scan(self, collections) -> dict:
        out = {}
        if "notes" in collections:
            out["notes"] = self.scan_notes()
        if "reminders" in collections and (self.reminders.exists() or not self.reminders.parent.exists()):
            out["reminders"] = self.scan_reminders()
        if "settings" in collections:
            out["settings"] = self.scan_settings()
        return out

    def apply(self, changes: dict, conflicts: dict = None) -> None:
        conflicts = conflicts or {}
        if changes.get("notes"):
            self.apply_notes(changes["notes"], conflicts.get("notes", set()))
        if changes.get("reminders"):
            self.apply_reminders(changes["reminders"])
        if changes.get("settings"):
            self.apply_settings(changes["settings"])


# ------------------------------------------------------------------------------------------------------ the engine
def _content(note) -> str:
    return bifrost_hash({"name": note.get("name"), "text": note.get("text")}) if isinstance(note, dict) else ""


def with_parents(known_notes: dict, items: dict) -> dict:
    """Each note as it is here, with the version it was changed from ("from"): a note changed on two computers from
    the same version is a conflict, one changed from the other's version isn't."""
    out = {}
    for item_id, data in items.items():
        record = known_notes.get(item_id) or {}
        prev = record.get("x") if not record.get("del") else None
        if isinstance(prev, dict) and prev.get("name") == data["name"] and prev.get("text") == data["text"]:
            out[item_id] = prev                                   # unchanged: as it was, with where it came from
        else:
            out[item_id] = dict(data, **{"from": _content(prev)})
    return out


def note_conflicts(before: dict, changes: dict, device: str) -> set:
    """Notes another computer changed that this one had changed too, from a different version."""
    out = set()
    for item_id, data in changes.items():
        mine = before.get(item_id)
        if data is None or not mine or mine.get("del") or mine.get("d") != device or not isinstance(mine.get("x"), dict):
            continue
        if data.get("from") != _content(mine["x"]) and data.get("text") != mine["x"].get("text"):
            out.add(item_id)
    return out


class Sync:
    """One computer's part in the group."""

    def __init__(self, own: Path = None, browser: Path = None, local: Local = None, keeper: KeyKeeper = None):
        self.own = Path(own) if own else own_dir()
        self.browser = Path(browser) if browser else browser_dir()
        self.local = local or Local()
        self.keeper = keeper or KeyKeeper(self.browser)
        self.secret = self.keeper.load()
        self.config = self._load_config()
        self.state = self._load_state()

    # settings and state
    def _load_config(self) -> dict:
        try:
            config = json.loads((self.own / "config.json").read_text())
        except (OSError, ValueError):
            config = {}
        if not isinstance(config, dict):
            config = {}
        config.setdefault("device", secrets.token_hex(8))
        if not isinstance(config.get("collections"), list):
            config["collections"] = list(COLLECTIONS)
        return config

    def _save_config(self) -> None:
        self.own.mkdir(parents=True, exist_ok=True)
        _write(self.own / "config.json", json.dumps(self.config, indent=1))

    def browser_config(self) -> dict:
        try:
            config = json.loads((self.browser / "config.json").read_text())
        except (OSError, ValueError):
            config = {}
        return config if isinstance(config, dict) else {}

    def _save_browser_config(self, config: dict) -> None:
        self.browser.mkdir(parents=True, exist_ok=True)
        _write(self.browser / "config.json", json.dumps(config))

    def _load_state(self) -> dict:
        state = None
        if self.secret:
            try:
                state = bifrost_open(self.secret, (self.own / "state.sealed").read_bytes())
            except OSError:
                pass
        state = state or {}
        return {"known": state.get("known") if isinstance(state.get("known"), dict) else {},
                "devices": state.get("devices") if isinstance(state.get("devices"), dict) else {},
                "last_sync": float(state.get("last_sync") or 0), "sent": float(state.get("sent") or 0),
                "error": str(state.get("error") or ""), "kept": state.get("kept") if isinstance(state.get("kept"), list) else [],
                "fresh": bool(state.get("fresh"))}

    def _save_state(self) -> None:
        if not self.secret:
            return
        self.own.mkdir(parents=True, exist_ok=True)
        blob = bifrost_seal(self.secret, self.device, {"device": self.device, "records": [], **self.state})
        fd, tmp = tempfile.mkstemp(dir=self.own, prefix=".state-", suffix=".part")
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        os.replace(tmp, self.own / "state.sealed")

    @property
    def device(self) -> str:
        return self.config["device"]

    def group(self) -> str:
        return bifrost_keys(self.secret)["group"] if self.secret else ""

    def folder(self) -> str:
        return str(self.browser_config().get("folder") or "")

    def group_folder(self):
        folder = self.folder()
        return Path(folder) / f"bifrost-{self.group()}" if folder and self.secret else None

    def collections(self) -> list:
        return [c for c in self.config["collections"] if c in COLLECTIONS]

    # joining and leaving
    def setup(self, folder: str) -> None:
        """A new group, syncing through this folder (the browser joins it too)."""
        self._become(secrets.token_bytes(32), folder, maker=True)

    def join(self, key_text: str, folder: str = "") -> None:
        parsed = bifrost_key_from_text(key_text)
        if not parsed:
            raise ValueError("That isn't a pairing key. It starts with HB1- or HB2-; copy it from Huginn on the other device.")
        secret, password_key = parsed
        if password_key:
            self._keep_password_key(bifrost_keys(secret)["group"], password_key)
        self._become(secret, folder or self.folder())
        self.state["fresh"] = True
        self._save_state()

    def _become(self, secret: bytes, folder: str, maker: bool = False) -> None:
        folder = os.path.abspath(os.path.expanduser(folder)) if folder else ""
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
        self.keeper.save(secret)
        self.secret = secret
        group = bifrost_keys(secret)["group"]
        browser = self.browser_config()
        browser.setdefault("device", secrets.token_hex(8))
        browser.setdefault("lan", True)
        browser["folder"] = folder
        if maker:
            browser["pk_maker"] = group
        elif browser.get("pk_maker") != group:
            browser["pk_maker"] = ""
        if not isinstance(browser.get("collections"), list):
            browser["collections"] = list(BROWSER_COLLECTIONS)
        self._save_browser_config(browser)
        try:
            (self.browser / "state.sealed").unlink()               # (what the browser knew of its old group)
        except OSError:
            pass
        self.state = {"known": {}, "devices": {}, "last_sync": 0.0, "sent": 0.0, "error": "", "kept": []}
        self._save_config()
        self._save_state()

    def _keep_password_key(self, group: str, key: bytes) -> bool:
        """An HB2 key carries the group's password key: into the password vault, if it's unlocked in this session
        (where the browser looks for it). Otherwise the browser asks for it when it next pairs."""
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import huginn_vault
            vault = huginn_vault.VaultFile()
            if not vault.exists() or not huginn_vault.Session(vault).try_unlock():
                return False
            keys = vault.extras.get("bifrostPasswordKeys")
            keys = {g: k for g, k in keys.items() if g != group} if isinstance(keys, dict) else {}
            keys = dict(list(keys.items())[-3:])
            keys[group] = key.hex()
            vault.extras["bifrostPasswordKeys"] = keys
            vault.save()
            return True
        except Exception:                                         # noqa: BLE001 — the browser can still pair for it
            return False

    def password_key(self):
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import huginn_vault
            vault = huginn_vault.VaultFile()
            if not vault.exists() or not huginn_vault.Session(vault).try_unlock():
                return None
            keys = vault.extras.get("bifrostPasswordKeys")
            key = bytes.fromhex(str(keys.get(self.group()) or "")) if isinstance(keys, dict) else b""
            return key if len(key) == 32 else None
        except Exception:                                         # noqa: BLE001
            return None

    def key_text(self) -> str:
        if not self.secret:
            return ""
        wants_passwords = "passwords" in (self.browser_config().get("collections") or BROWSER_COLLECTIONS)
        return bifrost_key_text(self.secret, self.password_key() if wants_passwords else None)

    def set_folder(self, folder: str) -> None:
        browser = self.browser_config()
        browser["folder"] = os.path.abspath(os.path.expanduser(folder)) if folder else ""
        if browser["folder"]:
            Path(browser["folder"]).mkdir(parents=True, exist_ok=True)
        self._save_browser_config(browser)

    def set_collections(self, names) -> None:
        names = set(names)
        self.config["collections"] = [c for c in COLLECTIONS if c in names]
        self._save_config()
        browser = self.browser_config()
        browser["collections"] = [c for c in BROWSER_COLLECTIONS if c in names]
        self._save_browser_config(browser)

    def leave(self) -> None:
        own = self._own_file()
        if own:
            try:
                own.unlink()
            except OSError:
                pass
        self.keeper.delete()
        for path in (self.own / "state.sealed", self.browser / "state.sealed"):
            try:
                path.unlink()
            except OSError:
                pass
        self.secret = None
        self.state = {"known": {}, "devices": {}, "last_sync": 0.0, "sent": 0.0, "error": "", "kept": []}

    # syncing
    def _own_file(self):
        folder = self.group_folder()
        return folder / f"{self.device}{OWN_SUFFIX}" if folder else None

    def run(self, now: float = None) -> dict:
        """One round: what changed here, what the other computers have, the merge, then this computer's file."""
        if not self.secret:
            return {"error": "not set up"}
        now = now or time.time()
        folder = self.group_folder()
        if folder is None:
            self.state["error"] = "Choose a sync folder."
            self._save_state()
            return {"error": self.state["error"]}
        try:
            folder.mkdir(parents=True, exist_ok=True)
            names = sorted(os.listdir(folder))
        except OSError:
            self.state["error"] = "The sync folder isn't there. Is the drive connected, or the network share open?"
            self._save_state()
            return {"error": self.state["error"]}
        import fcntl
        self.own.mkdir(parents=True, exist_ok=True)
        with open(self.own / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)                      # (the timer and Sync Now, one at a time)
            self.state = self._load_state()                       # (as the other one left it)
            return self._round(folder, names, now)

    def _scan(self, collections, now: float) -> None:
        known = self.state["known"]
        current = self.local.scan(collections)
        if "notes" in current:
            current["notes"] = with_parents(known.get("notes", {}), current["notes"])
        if self.state.get("fresh") and "settings" in current:   # just joined: the group's settings win over these
            bifrost_scan(known, {"settings": current.pop("settings")}, self.device, ["settings"], 1.0)
        bifrost_scan(known, current, self.device, [c for c in collections if c in current], now)

    def _round(self, folder: Path, names: list, now: float) -> dict:
        collections = self.collections()
        known = self.state["known"]
        self._scan(collections, now)
        before = dict(known.get("notes", {}))
        changes, seen = {}, 0
        for name in names:
            if not name.endswith(OWN_SUFFIX) or name == f"{self.device}{OWN_SUFFIX}":
                continue
            payload = bifrost_open(self.secret, read_device_file(folder / name) or b"")
            if payload is None or payload.get("device") == self.device:
                continue
            seen += 1
            for collection, items in bifrost_merge(known, payload["records"], collections, now).items():
                changes.setdefault(collection, {}).update(items)
            try:
                at = min(float(payload.get("at") or 0), now + 86400)
            except (TypeError, ValueError):
                at = 0.0
            self.state["devices"][payload["device"]] = {"name": str(payload.get("name") or "Another computer")[:60], "seen": at if math.isfinite(at) else 0.0}
        self.local.kept_copies = []
        self.local.apply(changes, {"notes": note_conflicts(before, changes.get("notes", {}), self.device)})
        self.state["fresh"] = False
        if self.local.kept_copies:
            self.state["kept"] = (self.state["kept"] + self.local.kept_copies)[-20:]
            self._scan(collections, now)                         # (the copies sync too)
        payload = {"device": self.device, "name": self.local.name, "at": now, "records": bifrost_records(known, collections)}
        try:
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".huginn-", suffix=".part")
            with os.fdopen(fd, "wb") as f:
                f.write(bifrost_seal(self.secret, self.device, payload))
            os.replace(tmp, folder / f"{self.device}{OWN_SUFFIX}")
            self.state["sent"] = now
            self.state["error"] = ""
        except OSError:
            self.state["error"] = "Huginn couldn't write to the sync folder."
        self.state["last_sync"] = now
        self._save_state()
        return {"changed": sum(len(v) for v in changes.values()), "devices": seen, "error": self.state["error"], "kept": self.local.kept_copies}

    def devices(self) -> list:
        """Every computer in the group: from the sync folder, the system's files and the browser's."""
        rows = {}
        folder = self.group_folder()
        if self.secret and folder is not None and folder.is_dir():
            for path in folder.iterdir():
                kind = "system" if path.name.endswith(OWN_SUFFIX) else "browser" if path.name.endswith(BROWSER_SUFFIX) else ""
                if not kind:
                    continue
                payload = bifrost_open(self.secret, read_device_file(path) or b"")
                if payload is None:
                    continue
                mine = (kind == "system" and payload["device"] == self.device) or (kind == "browser" and payload["device"] == self.browser_config().get("device"))
                name = str(payload.get("name") or "Another device")[:60]
                row = rows.setdefault(name.lower(), {"name": name, "seen": 0.0, "what": [], "this": False})
                row["what"] = sorted(set(row["what"]) | {kind})
                row["this"] = row["this"] or mine
                try:
                    row["seen"] = max(row["seen"], min(float(payload.get("at") or 0), time.time() + 86400))
                except (TypeError, ValueError):
                    pass
        return sorted(rows.values(), key=lambda r: (not r["this"], -r["seen"]))

    def status(self) -> dict:
        browser = self.browser_config()
        return {"on": bool(self.secret), "folder": self.folder(), "group": self.group(), "device": self.local.name,
                "collections": self.collections(), "browser": [c for c in (browser.get("collections") or BROWSER_COLLECTIONS) if c in BROWSER_COLLECTIONS],
                "lastSync": self.state["last_sync"], "error": self.state["error"], "kept": self.state["kept"][-5:],
                "keyWhere": self.keeper.where() if self.secret else "", "devices": self.devices() if self.secret else []}


# ------------------------------------------------------------------------------------------- in the background
def signature(s: "Sync") -> tuple:
    """Cheap: the times and sizes of what syncs here and of the files in the sync folder. A round only when it moves
    (and every few minutes anyway)."""
    def st(p):
        try:
            x = os.stat(p)
            return (x.st_mtime_ns, x.st_size)
        except OSError:
            return None
    parts = [st(s.own / "config.json"), st(s.browser / "config.json"), st(s.local.reminders), st(s.local.settings), st(s.local.notes)]
    if s.local.notes.is_dir():
        parts += sorted((p.name, st(p)) for p in s.local.notes.iterdir() if p.suffix.lower() in (".md", ".txt"))
    folder = s.group_folder()
    if folder is not None and folder.is_dir():
        parts += sorted((p.name, st(p)) for p in folder.iterdir() if p.name.endswith(OWN_SUFFIX) and p.name != f"{s.device}{OWN_SUFFIX}")
    return tuple(parts)


def watch(every: float = 300, look: float = 20, first_wait: float = 60) -> None:
    """huginn_helpers' sync: a round a minute after sign-in, then whenever something changed here or another
    computer's file changed in the folder, and every five minutes anyway. Nothing at all while sync is off."""
    time.sleep(first_wait)
    s, made, last_sig, last_run, conf = None, 0.0, None, 0.0, None

    def conf_now():
        try:
            return (own_dir() / "config.json").stat().st_mtime_ns, (own_dir() / "state.sealed").exists()
        except OSError:
            return None
    while True:
        if s is None or conf_now() != conf or (s.secret and time.time() - made > 600):
            s, made, conf = Sync(), time.time(), conf_now()     # (set up, joined or left in Settings since)
        if s.secret:
            sig = signature(s)
            if sig != last_sig or time.time() - last_run >= every:
                try:
                    s.run()
                except Exception as err:                      # noqa: BLE001 — tried again next time
                    print("huginn-sync:", err, file=sys.stderr)
                s = Sync()                                      # (Settings may have changed it meanwhile)
                last_sig, last_run, made, conf = signature(s), time.time(), time.time(), conf_now()
        time.sleep(look)


# ---------------------------------------------------------------------------------------- Settings › Sync
try:
    from PySide6.QtCore import Property, QObject, Signal, Slot
except ImportError:
    QObject = object

if QObject is not object:
    import threading

    class SyncSettings(QObject):
        changed = Signal()
        said = Signal(str, bool)
        _back = Signal(object)

        def __init__(self, demo: bool = False):
            super().__init__()
            self._demo, self._busy = demo, ""
            self._status = self._demo_status() if demo else {}
            self._back.connect(lambda fn: fn())
            if not demo:
                self.refresh()

        @staticmethod
        def _demo_status() -> dict:
            now = time.time()
            return {"on": True, "folder": str(Path.home() / "Nextcloud/Huginn"), "group": "3fa9c2", "device": "astrid-desktop",
                    "collections": list(COLLECTIONS), "browser": list(BROWSER_COLLECTIONS), "lastSync": now - 140, "error": "", "kept": [],
                    "keyWhere": "in the desktop's keyring",
                    "devices": [{"name": "astrid-desktop", "seen": now - 140, "what": ["browser", "system"], "this": True},
                                {"name": "astrid-laptop", "seen": now - 3600 * 5, "what": ["browser", "system"], "this": False},
                                {"name": "Astrid's PC", "seen": now - 86400 * 2, "what": ["browser"], "this": False}]}

        def _work(self, busy: str, fn, then=None) -> None:
            if self._busy:
                return
            self._busy = busy
            self.changed.emit()

            def run():
                try:
                    result, err = fn(), ""
                except Exception as e:                            # noqa: BLE001 — said in Settings
                    result, err = None, str(e) or "It didn't work."
                status = Sync().status()

                def done():
                    self._busy, self._status = "", status
                    if err:
                        self.said.emit(err, True)
                    elif then:
                        then(result)
                    self.changed.emit()
                self._back.emit(done)
            threading.Thread(target=run, daemon=True).start()

        status = Property("QVariantMap", lambda self: self._status, notify=changed)
        busy = Property(str, lambda self: self._busy, notify=changed)
        demo = Property(bool, lambda self: self._demo, constant=True)

        @Slot()
        def refresh(self) -> None:
            if not self._demo:
                self._work("looking", lambda: None)

        @Slot(str)
        def setUp(self, folder: str) -> None:
            folder = folder.replace("file://", "")
            if self._demo:
                self._status = dict(self._demo_status(), folder=folder)
                self.changed.emit()
                return
            self._work("joining", lambda: (lambda s: (s.setup(folder), s.run()))(Sync()),
                       lambda r: self.said.emit("Syncing. On your other devices, join with this computer's pairing key.", False))

        @Slot(str, str)
        def join(self, key: str, folder: str) -> None:
            folder = folder.replace("file://", "")
            if self._demo:
                self.said.emit("Joined.", False)
                return
            self._work("joining", lambda: (lambda s: (s.join(key, folder), s.run()))(Sync()),
                       lambda r: self.said.emit("Joined. Notes, Reminders and settings come over in a moment.", False))

        @Slot()
        def syncNow(self) -> None:
            if self._demo:
                self._status = dict(self._status, lastSync=time.time())
                self.changed.emit()
                return

            def then(r):
                if r and r.get("error"):
                    self.said.emit(r["error"], True)
                elif r and r.get("kept"):
                    self.said.emit(f"A note was changed here and on another computer: yours is kept as \"{r['kept'][0]}\".", False)
            self._work("syncing", lambda: Sync().run(), then)

        @Slot(str)
        def setFolder(self, folder: str) -> None:
            folder = folder.replace("file://", "")
            if self._demo:
                self._status = dict(self._status, folder=folder)
                self.changed.emit()
                return
            self._work("syncing", lambda: (lambda s: (s.set_folder(folder), Sync().run()))(Sync()))

        @Slot(str, bool)
        def setCollection(self, name: str, on: bool) -> None:
            have = set(self._status.get("collections", [])) | set(self._status.get("browser", []))
            have = (have | {name}) if on else (have - {name})
            if self._demo:
                self._status = dict(self._status, collections=[c for c in COLLECTIONS if c in have], browser=[c for c in BROWSER_COLLECTIONS if c in have])
                self.changed.emit()
                return
            self._work("syncing", lambda: Sync().set_collections(have))

        @Slot(result=str)
        def pairingKey(self) -> str:
            if self._demo:
                return bifrost_key_text(b"\x11" * 32)
            return Sync().key_text()

        @Slot()
        def leave(self) -> None:
            if self._demo:
                self._status = {"on": False, "devices": [], "collections": list(COLLECTIONS), "browser": list(BROWSER_COLLECTIONS)}
                self.changed.emit()
                return
            self._work("leaving", lambda: Sync().leave(), lambda r: self.said.emit("This computer stopped syncing. What's on it stays.", False))


# ------------------------------------------------------------------------------------------------------- the command
def main(argv) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip().splitlines()[-1].strip())
        return 0
    s = Sync()
    cmd, rest = argv[0], argv[1:]
    if cmd == "run":
        if not s.secret:
            return 0                                              # (the timer, on a computer that doesn't sync)
        out = s.run()
    elif cmd == "status":
        out = s.status()
    elif cmd == "setup" and rest:
        s.setup(rest[0])
        out = s.run()
    elif cmd == "join" and rest:
        s.join(rest[0], rest[1] if len(rest) > 1 else "")
        out = s.run()
    elif cmd == "folder" and rest:
        s.set_folder(rest[0])
        out = s.status()
    elif cmd == "collections" and rest:
        s.set_collections(rest[0].split(","))
        out = s.status()
    elif cmd == "key":
        print(s.key_text())
        return 0 if s.secret else 1
    elif cmd == "leave":
        s.leave()
        out = {"left": True}
    else:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1))
    return 1 if isinstance(out, dict) and out.get("error") and cmd != "status" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
