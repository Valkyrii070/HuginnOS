"""The way Huginn looks, made your own (Settings › Appearance): live wallpapers you make, icon themes and pointer
themes, and themes you add from a file.

Live wallpapers live in ~/.local/share/huginn/wallpapers/live/<id>/: wallpaper.json (what CustomWallpaper.qml draws:
see the top of that file), its picture or video, and still.jpg (a picture of it for the choices). One can be shared as
a .huginn-wallpaper file (a zip of that folder) and added on another computer.

Icon and pointer themes are the freedesktop kind (a folder with an index.theme; a pointer theme has a cursors folder),
in ~/.local/share/icons for the ones added here. Settings shows each with a few of its own pictures.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import struct
import tarfile
import tempfile
import zipfile
from pathlib import Path

HOME = Path.home()
DATA = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share")
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache")
LIVE_DIR = DATA / "huginn" / "wallpapers" / "live"
USER_ICONS = DATA / "icons"
ICON_DIRS = [USER_ICONS, HOME / ".icons", Path("/usr/local/share/icons"), Path("/usr/share/icons")]

SCENES = ("aurora", "bifrost", "muspelheim", "niflheim")
SCENE_COLOURS = {
    "aurora": {"tintA": "#0F2624", "tintB": "#17192C", "glowA": "#3DD6B5", "glowB": "#7B61FF"},
    "bifrost": {"tintA": "#1D1932", "tintB": "#2A1727", "glowA": "#8E7BFF", "glowB": "#FF7AB8"},
    "muspelheim": {"tintA": "#2C1912", "tintB": "#1F1718", "glowA": "#FF8A4C", "glowB": "#FFC857"},
    "niflheim": {"tintA": "#12212F", "tintB": "#171A20", "glowA": "#7CC4FF", "glowB": "#CFEAFF"},
}
EFFECTS = ("snow", "rain", "stars", "fireflies", "lights", "leaves", "embers")
MOTIONS = ("drift", "breathe", "still")
PICTURES = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif", ".heic", ".jxl")
VIDEOS = (".mp4", ".webm", ".mkv", ".mov", ".m4v", ".ogv", ".avi")
SHARE_EXT = ".huginn-wallpaper"
HEX = re.compile(r"#[0-9A-Fa-f]{6}")


class Refused(Exception):
    """Something that can't be done, in words fit to show."""


# ============================================================================================ live wallpapers
def clean_spec(spec) -> dict:
    """A wallpaper.json as CustomWallpaper.qml expects it, whatever came in (Settings, or a shared file)."""
    spec = spec if isinstance(spec, dict) else {}
    base = spec.get("base") if spec.get("base") in ("scene", "picture", "video") else "scene"
    scene = spec.get("scene") if spec.get("scene") in SCENES else "aurora"
    colours = dict(SCENE_COLOURS[scene])
    for k, v in (spec.get("colours") or {}).items() if isinstance(spec.get("colours"), dict) else []:
        if k in colours and isinstance(v, str) and HEX.fullmatch(v):
            colours[k] = v.upper()

    def num(key, lo, hi, default):
        try:
            return round(max(lo, min(hi, float(spec.get(key, default)))), 3)
        except (TypeError, ValueError):
            return default
    out = {"version": 1, "name": re.sub(r"\s+", " ", str(spec.get("name") or "").strip())[:60] or "My wallpaper",
           "base": base, "scene": scene, "colours": colours,
           "motion": spec.get("motion") if spec.get("motion") in MOTIONS else "drift",
           "effects": [e for e in EFFECTS if e in (spec.get("effects") or [])],
           "amount": num("amount", 0, 1, 0.5), "pace": num("pace", 0.25, 3, 1.0), "shade": num("shade", 0, 0.7, 0.0),
           "effectColour": spec.get("effectColour").upper() if isinstance(spec.get("effectColour"), str) and HEX.fullmatch(spec.get("effectColour")) else ""}
    f = spec.get("file")
    if base != "scene" and isinstance(f, str) and f == Path(f).name and not f.startswith(".") \
            and f.lower().endswith(PICTURES if base == "picture" else VIDEOS):
        out["file"] = f
    return out


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "wallpaper"
    return f"{s}-{secrets.token_hex(3)}"


def live_folder(ident: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{1,48}", ident or ""):
        raise Refused("That wallpaper isn't one of yours.")
    return LIVE_DIR / ident


def list_live() -> list:
    out = []
    try:
        folders = sorted((d for d in LIVE_DIR.iterdir() if (d / "wallpaper.json").is_file()), key=lambda d: -(d / "wallpaper.json").stat().st_mtime)
    except OSError:
        return []
    for d in folders:
        try:
            spec = clean_spec(json.loads((d / "wallpaper.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        still = d / "still.jpg"
        if not still.is_file() and spec["base"] == "picture" and spec.get("file"):
            still = d / spec["file"]                             # (none taken yet: its picture will do)
        out.append({"id": d.name, "name": spec["name"], "path": str(d / "wallpaper.json"), "spec": spec, "folder": d.as_uri() + "/",
                    "still": f"{still.as_uri()}?{int(still.stat().st_mtime)}" if still.is_file() else "", "base": spec["base"]})
    return out


def save_live(ident: str, spec, media: str = "") -> str:
    """Make (ident "") or change one: its wallpaper.json, and its picture or video copied in from `media` when that's
    a new one. Returns its id."""
    spec = clean_spec(spec)
    folder = live_folder(ident) if ident else LIVE_DIR / _slug(spec["name"])
    folder.mkdir(parents=True, exist_ok=True)
    if spec["base"] != "scene" and media:
        src = Path(media)
        kinds = PICTURES if spec["base"] == "picture" else VIDEOS
        if not src.is_file() or not src.name.lower().endswith(kinds):
            raise Refused("That isn't a " + ("picture" if spec["base"] == "picture" else "video") + " Huginn can show.")
        name = ("picture" if spec["base"] == "picture" else "video") + src.suffix.lower()
        if src.resolve() != (folder / name).resolve():
            part = folder / f".{name}.part"
            shutil.copyfile(src, part)
            for old in folder.iterdir():                     # the one picture or video it shows, nothing else
                if old.is_file() and old.name.startswith(("picture", "video")) and old.name != name:
                    old.unlink()
            os.replace(part, folder / name)
        spec["file"] = name
    elif spec["base"] != "scene" and not spec.get("file"):
        have = [p.name for p in folder.iterdir() if p.is_file() and p.name.startswith("picture" if spec["base"] == "picture" else "video")] if folder.exists() else []
        if not have:
            raise Refused("Choose a " + ("picture" if spec["base"] == "picture" else "video") + " for it first.")
        spec["file"] = have[0]
    if spec["base"] == "scene":
        for old in folder.iterdir():
            if old.is_file() and old.name.startswith(("picture", "video")):
                old.unlink()
    part = folder / ".wallpaper.json.part"
    part.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    os.replace(part, folder / "wallpaper.json")
    return folder.name


def delete_live(ident: str) -> None:
    shutil.rmtree(live_folder(ident), ignore_errors=True)


def export_live(ident: str, to_folder: Path = None) -> Path:
    """A .huginn-wallpaper file of it (a zip of its folder) in Documents, to give someone."""
    folder = live_folder(ident)
    spec = clean_spec(json.loads((folder / "wallpaper.json").read_text(encoding="utf-8")))
    to_folder = to_folder or HOME / "Documents"
    to_folder.mkdir(parents=True, exist_ok=True)
    base = re.sub(r"[/\\:*?\"<>|]+", "", spec["name"]).strip() or "Wallpaper"
    out, n = to_folder / f"{base}{SHARE_EXT}", 2
    while out.exists():
        out, n = to_folder / f"{base} {n}{SHARE_EXT}", n + 1
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("wallpaper.json", json.dumps(spec, indent=1))
        for name in ([spec["file"]] if spec.get("file") else []) + ["still.jpg"]:
            if (folder / name).is_file():
                z.write(folder / name, name, compress_type=zipfile.ZIP_STORED if name != "still.jpg" else zipfile.ZIP_DEFLATED)
    return out


def import_live(path: str) -> str:
    """Add a .huginn-wallpaper someone shared: only its wallpaper.json, its one picture or video and its still are
    taken from it. Returns the new one's id."""
    src = Path(path)
    if not zipfile.is_zipfile(src):
        raise Refused("That isn't a Huginn wallpaper file.")
    with zipfile.ZipFile(src) as z:
        names = set(z.namelist())
        if "wallpaper.json" not in names:
            raise Refused("That isn't a Huginn wallpaper file.")
        if sum(i.file_size for i in z.infolist()) > 4 * 1024 ** 3:
            raise Refused("That wallpaper is too big to add.")
        spec = clean_spec(json.loads(z.read("wallpaper.json").decode("utf-8", "replace")))
        if spec["base"] != "scene" and spec.get("file") not in names:
            raise Refused("That wallpaper's picture or video is missing from the file.")
        folder = LIVE_DIR / _slug(spec["name"])
        folder.mkdir(parents=True, exist_ok=True)
        for name in [n for n in (spec.get("file"), "still.jpg") if n and n in names]:
            with z.open(name) as fin, open(folder / name, "wb") as fout:
                shutil.copyfileobj(fin, fout, 1 << 20)
        (folder / "wallpaper.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    return folder.name


# ============================================================================================ themes: finding them
def _index(folder: Path) -> dict:
    """index.theme's groups, as {group: {key: value}}."""
    out, group = {}, None
    try:
        for line in (folder / "index.theme").read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                group = out.setdefault(line[1:-1], {})
            elif group is not None and "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                group[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def theme_folders(ident: str) -> list:
    return [d / ident for d in ICON_DIRS if (d / ident).is_dir()]


def is_user_theme(ident: str) -> bool:
    """A theme that was added for this person alone (Huginn's own wrapped icons, in ~/.local/share/icons/Huginn, are
    part of a system theme, so they don't count)."""
    mine = any((d / ident).is_dir() for d in (USER_ICONS, HOME / ".icons"))
    system = any((d / ident).is_dir() for d in (Path("/usr/local/share/icons"), Path("/usr/share/icons")))
    return mine and not system


def find_icon(theme: str, names, size: int = 48, seen=None) -> str:
    """One of `names` (the first found) in an icon theme or what it inherits (not hicolor: a preview should show the
    theme's own), as a file path; "" if none."""
    seen = seen if seen is not None else set()
    if theme in seen or theme == "hicolor":
        return ""
    seen.add(theme)
    for folder in theme_folders(theme):
        info = _index(folder).get("Icon Theme", {})
        dirs = [d for d in (info.get("Directories", "") + "," + info.get("ScaledDirectories", "")).split(",") if d]
        groups = _index(folder)

        def closeness(d):
            g = groups.get(d, {})
            try:
                s = int(g.get("Size", "48"))
            except ValueError:
                s = 48
            scalable = g.get("Type", "") == "Scalable"
            return (0 if scalable else 1, abs(s - size))
        for name in names:
            for d in sorted(dirs, key=closeness):
                for ext in (".svg", ".png", ".svgz"):
                    p = folder / d / f"{name}{ext}"
                    if p.is_file():
                        return str(p)
    for parent in [p.strip() for p in theme_inherits(theme) if p.strip()]:
        found = find_icon(parent, names, size, seen)
        if found:
            return found
    return ""


def theme_inherits(theme: str) -> list:
    for folder in theme_folders(theme):
        info = _index(folder).get("Icon Theme", {})
        if "Inherits" in info:
            return [p for p in info["Inherits"].split(",") if p]
    return []


# what a preview shows: an app or a folder, each by the names themes give it
SAMPLES = [("folder", ["folder"]),
           ("files", ["system-file-manager", "org.kde.dolphin", "org.gnome.Nautilus", "file-manager", "nautilus"]),
           ("browser", ["internet-web-browser", "web-browser", "firefox", "applications-internet", "browser"]),
           ("terminal", ["utilities-terminal", "org.kde.konsole", "org.gnome.Terminal", "terminal", "konsole"]),
           ("text", ["accessories-text-editor", "org.kde.kate", "org.gnome.TextEditor", "text-editor", "gedit"]),
           ("music", ["multimedia-audio-player", "audio-player", "org.kde.elisa", "rhythmbox", "applications-multimedia"]),
           ("settings", ["preferences-system", "systemsettings", "org.gnome.Settings", "preferences-desktop", "gnome-control-center"])]
HUGINN_SAMPLES = {"files": "files", "browser": "browser", "terminal": "terminal", "text": "notes", "music": "music", "settings": "settings"}


def own_picture(key: str) -> str:
    for base in (Path("/usr/share/icons/hicolor"), Path(__file__).resolve().parent.parent / "config/overlay/usr/share/icons/hicolor"):
        p = base / "128x128" / "apps" / f"huginn-{key}.png"
        if p.is_file():
            return str(p)
    return ""


def list_icon_themes() -> list:
    """Icon themes there are (not pointer-only ones, not hicolor), each with its name, a line about it, whether it
    was added here (so can be removed) and a few of its pictures."""
    out, seen = [], set()
    for base in ICON_DIRS:
        try:
            folders = sorted(base.iterdir())
        except OSError:
            continue
        for folder in folders:
            ident = folder.name
            if ident in seen or ident in ("hicolor", "default", "locolor") or not folder.is_dir():
                continue
            info = _index(folder).get("Icon Theme", {})
            if not info.get("Directories") or info.get("Hidden", "").lower() == "true":
                continue
            seen.add(ident)
            if ident == "Huginn":
                samples = [find_icon("Huginn", ["folder"])] + [own_picture(HUGINN_SAMPLES[k]) for k, _ in SAMPLES[1:]]
            else:
                samples = [find_icon(ident, names) for _k, names in SAMPLES]
            found = [s for s in samples if s]
            if len(found) < 3:                      # a theme of symbols or a few extras: not one to pick for everything
                continue
            out.append({"id": ident, "name": info.get("Name", ident), "about": info.get("Comment", ""), "user": is_user_theme(ident),
                        "samples": [Path(s).as_uri() for s in found[:7]]})
    first = {"Huginn": 0}
    return sorted(out, key=lambda t: (first.get(t["id"], 3), t["name"].lower()))


# ============================================================================================ pointers
POINTER_SAMPLES = [("arrow", ["left_ptr", "default", "arrow", "top_left_arrow"]),
                   ("hand", ["pointer", "hand2", "hand1", "pointing_hand"]),
                   ("text", ["text", "xterm", "ibeam"]),
                   ("wait", ["wait", "watch", "left_ptr_watch", "progress"]),
                   ("move", ["move", "fleur", "grabbing", "size_all", "all-scroll"])]


def read_xcursor(path: str, want: int = 32):
    """The frame of an Xcursor file nearest `want` pixels: (width, height, xhot, yhot, ARGB32 bytes), or None."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if len(data) < 16 or data[:4] != b"Xcur":
        return None
    _magic, header, _version, ntoc = struct.unpack_from("<4sIII", data, 0)
    images = []
    for i in range(min(ntoc, 4096)):
        off = header + i * 12
        if off + 12 > len(data):
            break
        kind, sub, pos = struct.unpack_from("<III", data, off)
        if kind == 0xFFFD0002:
            images.append((abs(sub - want), sub, pos))
    for _d, _sub, pos in sorted(images):
        if pos + 36 > len(data):
            continue
        _h, kind, _sub, _v, w, h, xhot, yhot, _delay = struct.unpack_from("<9I", data, pos)
        if kind != 0xFFFD0002 or not (0 < w <= 1024 and 0 < h <= 1024) or pos + 36 + w * h * 4 > len(data):
            continue
        return w, h, xhot, yhot, data[pos + 36: pos + 36 + w * h * 4]
    return None


def list_pointer_themes() -> list:
    out, seen = [], set()
    for base in ICON_DIRS:
        try:
            folders = sorted(base.iterdir())
        except OSError:
            continue
        for folder in folders:
            ident = folder.name
            cur = folder / "cursors"
            if ident in seen or ident == "default" or not cur.is_dir():
                continue
            if ident.startswith("Huginn-") and ident != "Huginn-Plain":   # (Huginn's in another realm's colours: "Huginn" and
                continue                                                 # "Huginn-Plain" follow the realm)
            if not any((cur / n).exists() for n in ("left_ptr", "default", "arrow")):
                continue
            seen.add(ident)
            info = _index(folder).get("Icon Theme", {})
            out.append({"id": ident, "name": info.get("Name", ident).replace("_", " "), "user": is_user_theme(ident), "folder": str(folder)})
    first = {"Huginn": 0, "Huginn-Plain": 1, "Adwaita": 2}
    return sorted(out, key=lambda t: (first.get(t["id"], 3), t["name"].lower()))


def pointer_previews(theme: dict, size: int = 32) -> list:
    """Pictures of a pointer theme's arrow, hand, text, wait and move pointers (PNGs made once, kept in the cache)."""
    from PySide6.QtGui import QImage
    out_dir = CACHE / "huginn" / "pointers" / re.sub(r"[^\w.-]", "_", theme["id"])
    out = []
    for key, names in POINTER_SAMPLES:
        target = out_dir / f"{key}-{size}.png"
        src = next((Path(theme["folder"]) / "cursors" / n for n in names if (Path(theme["folder"]) / "cursors" / n).exists()), None)
        if src is None:
            continue
        try:
            fresh = target.is_file() and target.stat().st_mtime >= src.resolve().stat().st_mtime
        except OSError:
            fresh = False
        if not fresh:
            got = read_xcursor(str(src), size)
            if got is None:
                continue
            w, h, _x, _y, pixels = got
            img = QImage(pixels, w, h, w * 4, QImage.Format_ARGB32_Premultiplied).copy()
            out_dir.mkdir(parents=True, exist_ok=True)
            if not img.save(str(target)):
                continue
        out.append(f"{target.as_uri()}?{int(target.stat().st_mtime)}")
    return out


# ============================================================================================ adding a theme from a file
ARCHIVES = (".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tbz2", ".tar.zst", ".tar", ".zip")
MAX_BYTES, MAX_FILES = 1536 * 1024 ** 2, 200000


def _themes_in(root: Path) -> list:
    """Folders under `root` that are themes: an index.theme (icons) or a cursors folder (pointers)."""
    found = []
    for idx in list(root.rglob("index.theme")) + [c.parent / "index.theme" for c in root.rglob("cursors") if c.is_dir()]:
        folder = idx.parent
        if folder not in found and (idx.is_file() or (folder / "cursors").is_dir()):
            found.append(folder)
    # a theme inside another (the outer one only names it) counts once: the innermost real ones
    return [f for f in found if not any(o != f and o in f.parents and (o / "cursors").is_dir() for o in found)]


def add_theme(path: str) -> list:
    """Install the icon or pointer themes in a downloaded archive (as gnome-look.org and store.kde.org give them) into
    ~/.local/share/icons. Returns [(id, kind)]: kind "icons", "pointers" or "both". Nothing outside that folder is
    written, links and odd paths are left out (tarfile's "data" filter), and a huge one is refused."""
    src = Path(path)
    if not src.is_file() or not src.name.lower().endswith(ARCHIVES):
        raise Refused("That isn't a theme file Huginn can open (.tar.gz, .tar.xz or .zip).")
    with tempfile.TemporaryDirectory(dir=str(CACHE) if CACHE.exists() else None) as tmp:
        root = Path(tmp) / "x"
        root.mkdir()
        if src.name.lower().endswith(".zip"):
            with zipfile.ZipFile(src) as z:
                infos = z.infolist()
                if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_BYTES:
                    raise Refused("That theme is too big to add.")
                for i in infos:
                    p = Path(i.filename)
                    if p.is_absolute() or ".." in p.parts:
                        continue
                    z.extract(i, root)
        else:
            try:
                with tarfile.open(src) as t:
                    members = t.getmembers()
                    if len(members) > MAX_FILES or sum(m.size for m in members) > MAX_BYTES:
                        raise Refused("That theme is too big to add.")
                    t.extractall(root, filter="data")
            except (tarfile.TarError, OSError) as err:
                if isinstance(err, Refused):
                    raise
                raise Refused(f"That file couldn't be opened: {err}")
        themes = _themes_in(root)
        if not themes:
            raise Refused("There's no icon or pointer theme in that file.")
        USER_ICONS.mkdir(parents=True, exist_ok=True)
        added = []
        for folder in themes:
            ident = folder.name if folder != root else src.name.split(".")[0]
            ident = re.sub(r"[^\w.+ -]", "_", ident)[:80] or "Theme"
            dest = USER_ICONS / ident
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(folder), str(dest))
            icons = bool(_index(dest).get("Icon Theme", {}).get("Directories"))
            pointers = (dest / "cursors").is_dir()
            added.append((ident, "both" if icons and pointers else "pointers" if pointers else "icons"))
        return added


def remove_theme(ident: str) -> None:
    """Remove a theme that was added (only from your own folders; the system's stay)."""
    if not re.fullmatch(r"[\w.+ -]{1,80}", ident or "") or ".." in ident:
        raise Refused("That isn't a theme that was added.")
    if not is_user_theme(ident):
        raise Refused("Only themes you added can be removed.")
    gone = False
    for base in (USER_ICONS, HOME / ".icons"):
        if (base / ident).is_dir():
            shutil.rmtree(base / ident)
            gone = True
    if not gone:
        raise Refused("Only themes you added can be removed.")
    shutil.rmtree(CACHE / "huginn" / "pointers" / re.sub(r"[^\w.-]", "_", ident), ignore_errors=True)


# ============================================================================================ one app's own icon
APP_ICONS = DATA / "huginn" / "app-icons"
MARK, WAS, MADE = "X-Huginn-Own-Icon", "X-Huginn-Icon-Was", "X-Huginn-Icon-Override"


def _desktop_lines(path: Path) -> list:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _set_key(lines: list, key: str, value) -> list:
    """Set (value) or take out (None) one key in the [Desktop Entry] group of a .desktop file's lines."""
    out, inside, done = [], False, False
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            if inside and not done and value is not None:
                out.append(f"{key}={value}")
                done = True
            inside = s == "[Desktop Entry]"
        elif inside and s.split("=", 1)[0].strip() == key:
            if value is not None and not done:
                out.append(f"{key}={value}")
                done = True
            continue
        out.append(line)
    if inside and not done and value is not None:
        out.append(f"{key}={value}")
    return out


def _get_key(lines: list, key: str) -> str:
    inside = False
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            inside = s == "[Desktop Entry]"
        elif inside and s.split("=", 1)[0].strip() == key:
            return s.split("=", 1)[1].strip()
    return ""


def set_app_icon(desktop_id: str, picture: str, original: Path, glass: bool = True) -> str:
    """Give one app an icon of your own: the picture made into a 256-pixel icon (on Huginn's glass, or as it is) and
    the app's .desktop file in ~/.local/share/applications pointing at it (a copy of the app's own, if it had none
    there). Returns the icon's path."""
    import huginn_iconwrap as wrap
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    if not re.fullmatch(r"[\w.+-]+\.desktop", desktop_id or ""):
        raise Refused("That isn't an app.")
    app = QGuiApplication.instance()                           # noqa: F841  (QImage and SVG need one)
    img = wrap.load(picture)
    if img is None:
        raise Refused("That picture couldn't be read.")
    if glass:
        done = wrap.wrap(img)
        if done is None:
            raise Refused("That picture is empty.")
    else:                                                      # as it is: in the same square Huginn's own icons use
        done = QImage(wrap.SIZE, wrap.SIZE, QImage.Format_ARGB32_Premultiplied)
        done.fill(Qt.transparent)
        p = QPainter(done)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(QRectF(14, 14, 228, 228), img)
        p.end()
    APP_ICONS.mkdir(parents=True, exist_ok=True)
    icon = APP_ICONS / f"{desktop_id[:-len('.desktop')]}.png"
    part = icon.with_name(f".{icon.name}.part.png")
    if not done.save(str(part)):
        raise Refused("The icon couldn't be saved.")
    os.replace(part, icon)
    mine = DATA / "applications" / desktop_id
    if mine.is_file():
        lines = _desktop_lines(mine)
        if not _get_key(lines, MARK):
            lines = _set_key(lines, WAS, _get_key(lines, "Icon"))
    else:
        if not original or not Path(original).is_file():
            raise Refused("That app's own file isn't there.")
        lines = _set_key(_desktop_lines(Path(original)), MADE, "true")
    lines = _set_key(lines, "Icon", str(icon))
    lines = _set_key(lines, MARK, "true")
    mine.parent.mkdir(parents=True, exist_ok=True)
    part = mine.with_name(f".{mine.name}.part")
    part.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(part, mine)
    return str(icon)


def reset_app_icon(desktop_id: str) -> None:
    """The app's own icon again: the copy made for this goes, or (when you had your own file) its icon comes back."""
    if not re.fullmatch(r"[\w.+-]+\.desktop", desktop_id or ""):
        return
    mine = DATA / "applications" / desktop_id
    if mine.is_file():
        lines = _desktop_lines(mine)
        if _get_key(lines, MADE) == "true":
            mine.unlink()
        elif _get_key(lines, MARK):
            lines = _set_key(lines, "Icon", _get_key(lines, WAS) or None)
            lines = _set_key(_set_key(lines, MARK, None), WAS, None)
            mine.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        (APP_ICONS / f"{desktop_id[:-len('.desktop')]}.png").unlink()
    except OSError:
        pass


def changed_app_icons() -> list:
    """Apps given an icon of your own: [{"id", "icon"}]."""
    out = []
    try:
        for f in sorted((DATA / "applications").glob("*.desktop")):
            lines = _desktop_lines(f)
            if _get_key(lines, MARK) == "true":
                out.append({"id": f.name, "icon": _get_key(lines, "Icon")})
    except OSError:
        pass
    return out
