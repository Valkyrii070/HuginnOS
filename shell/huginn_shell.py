#!/usr/bin/env python3
"""Huginn Shell: the desktop shell of Huginn OS (top bar, dock, launcher, control centre, widgets).

  huginn_shell.py                      run as the session shell (Wayland + KWin, needs org.kde.layershell)
  huginn_shell.py --compositor         Huginn's own compositor with the shell inside it (the preview session, in cage)
  huginn_shell.py --compositor --windowed [--no-services]   the same in an ordinary window, for testing
  huginn_shell.py --preview            everything in one ordinary window, on any OS, for design work
  huginn_shell.py --preview --shot out.png [--dark|--light] [--realm aurora] [--open cc|launcher] [--menus] [--menu-style dropdown|inline]

All colours, radii and fonts come from ../tokens/tokens.json, the file Huginn itself will read.
"""
import argparse
import configparser
import json
import os
import re
import shlex
import shutil
import sys
import time
from pathlib import Path

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QProcess, QSettings, QSize, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QImage
from PySide6.QtQml import QQmlApplicationEngine, QQmlPropertyMap
from PySide6.QtQuick import QQuickImageProvider, QQuickWindow  # noqa: F401  (QQuickWindow: the root window type, for grabWindow)

HERE = Path(__file__).resolve().parent
TOKEN_PATHS = [HERE.parent / "tokens" / "tokens.json", Path("/usr/share/huginn-os/tokens.json")]
# The live wallpapers (shared with the sign-in screen): installed, or in the build kit when run from it.
LIVE_PATHS = [Path("/usr/share/huginn-os/live"), HERE.parent / "config" / "overlay" / "usr" / "share" / "huginn-os" / "live"]


def live_dir() -> str:
    """A file:// URL (ending in /) for the live wallpapers, or "" when they aren't anywhere."""
    for d in LIVE_PATHS:
        if (d / "LiveWallpaper.qml").exists():
            return QUrl.fromLocalFile(str(d) + "/").toString()
    return ""


_WALL_TOP: dict = {}


def wall_top(path: str) -> float:
    """How light the top of a picture is (0 dark … 1 light): where the top bar's text floats over it. -1: can't tell."""
    try:
        key = (path, os.stat(path).st_mtime_ns)
    except OSError:
        return -1.0
    if key not in _WALL_TOP:
        from PySide6.QtGui import QImageReader                  # (here: the apps' Theme doesn't need it)
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and size.width() > 0:                 # small: only its brightness is wanted
            reader.setScaledSize(QSize(64, max(8, round(64 * size.height() / size.width()))))
        img = reader.read()
        if img.isNull():
            _WALL_TOP[key] = -1.0
        else:
            img = img.convertToFormat(QImage.Format.Format_RGB32)
            rows, total = max(2, img.height() * 6 // 100), 0.0
            for y in range(rows):
                for x in range(img.width()):
                    c = img.pixel(x, y)
                    total += 0.2126 * ((c >> 16) & 255) + 0.7152 * ((c >> 8) & 255) + 0.0722 * (c & 255)
            _WALL_TOP[key] = round(total / (rows * img.width() * 255), 3)
    return _WALL_TOP[key]


_WALL_ACCENT: dict = {}


def wall_accent(path: str):
    """The colour a picture is most about, as (hue, lightness, saturation) 0…1, for an accent that matches it
    (Settings › Appearance › Accent colour: From the wallpaper). Vivid, middling-bright colours count most; greys,
    near-blacks and near-whites hardly at all. None when the picture has too little colour to pick from (a grey
    one) or can't be read."""
    import colorsys
    try:
        key = (path, os.stat(path).st_mtime_ns)
    except (OSError, TypeError, ValueError):
        return None
    if key not in _WALL_ACCENT:
        from PySide6.QtGui import QImageReader
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and size.width() > 0:               # small (JPEGs are decoded small to begin with): quick
            reader.setScaledSize(QSize(48, max(8, round(48 * size.height() / size.width()))))
        img = reader.read()
        picked = None
        if not img.isNull():
            img = img.convertToFormat(QImage.Format.Format_RGB32)
            weight, sums, n = [0.0] * 36, [[0.0, 0.0, 0.0] for _ in range(36)], img.width() * img.height()
            for y in range(img.height()):
                for x in range(img.width()):
                    c = img.pixel(x, y)
                    r, g, b = ((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255
                    hi, lo = max(r, g, b), min(r, g, b)
                    sat = (hi - lo) / hi if hi else 0.0
                    if sat < 0.18 or hi < 0.18:
                        continue
                    w = sat * sat * (1.0 - abs(hi - 0.65))
                    h = colorsys.rgb_to_hls(r, g, b)[0]
                    k = int(h * 36) % 36
                    weight[k] += w
                    sums[k][0] += r * w; sums[k][1] += g * w; sums[k][2] += b * w
            score = [weight[i - 1] * 0.5 + weight[i] + weight[(i + 1) % 36] * 0.5 for i in range(36)]
            best = max(range(36), key=lambda i: score[i])
            if score[best] > 0.015 * n:
                w = weight[best - 1] + weight[best] + weight[(best + 1) % 36]
                rgb = [(sums[best - 1][j] + sums[best][j] + sums[(best + 1) % 36][j]) / w for j in range(3)]
                picked = colorsys.rgb_to_hls(*rgb)
        _WALL_ACCENT[key] = picked
    return _WALL_ACCENT[key]


def _luminance(rgb) -> float:
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def accent_colour(hls, dark: bool) -> str:
    """A picked colour made into an accent that works: bright enough for the dark text on it in dark mode, deep enough
    for white text on it in light mode (the realms' accents follow the same rule), and never washed out."""
    import colorsys
    h, _l, s = hls
    s = max(0.5, min(0.85, s))
    on = (0x0B / 255, 0x15 / 255, 0x12 / 255) if dark else (1.0, 1.0, 1.0)
    want = 5.0 if dark else 3.6
    light = 0.64 if dark else 0.46
    for _ in range(40):
        rgb = colorsys.hls_to_rgb(h, light, s)
        if contrast(rgb, on) >= want:
            break
        light += 0.01 if dark else -0.01
    rgb = colorsys.hls_to_rgb(h, max(0.0, min(1.0, light)), s)
    return "#%02X%02X%02X" % tuple(round(c * 255) for c in rgb)


def me() -> dict:
    """Who's signed in, for the arrival after the sign-in screen: the name the sign-in screen showed and the picture."""
    import pwd
    try:
        pw = pwd.getpwuid(os.getuid())
        name, login, home = (pw.pw_gecos or "").split(",")[0].strip(), pw.pw_name, Path(pw.pw_dir)
    except KeyError:
        name, login, home = "", os.environ.get("USER", ""), Path.home()
    face = next((f for f in (home / ".face.icon", home / ".face") if f.is_file()), None)
    # First time in (or the installation drive's session, which is always new): "Welcome", not "Welcome back".
    seen = Path(os.environ.get("XDG_STATE_HOME") or home / ".local/state") / "huginn" / "arrived"
    first = not seen.exists() or os.path.exists("/cdrom/casper/filesystem.squashfs")
    try:
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.touch()
    except OSError:
        pass
    return {"name": name or login, "login": login, "face": QUrl.fromLocalFile(str(face)).toString() if face else "", "first": first}
WEB_APP_KEY = "X-Huginn-WebApp"          # set by Huginn's "Install as app" in the .desktop file


def qml_colour(value: str) -> str:
    """'#RRGGBB' stays; 'rgba(r,g,b,a)' becomes QML's '#AARRGGBB'."""
    m = re.fullmatch(r"rgba\(([^)]+)\)", value.strip())
    if not m:
        return value
    r, g, b, a = (float(x) for x in m.group(1).split(","))
    return "#%02X%02X%02X%02X" % (round(a * 255), round(r), round(g), round(b))


class Theme(QObject):
    """The active theme as one flat map (`Theme.t.accent`, `Theme.t.radiusCard`, ...).

    `t` is a QQmlPropertyMap made once: QML reads `Theme.t.accent` straight from it, without coming back to Python,
    and when the theme changes (dark mode, the realm, the accessibility settings) only the values that changed are
    set again, so only what uses them is redrawn. (It used to be a map built afresh on every read: an app's thousands
    of bindings each built it at start, and any setting at all, the dock's size say, rebuilt every binding in every
    app.)"""
    changed = Signal()

    def __init__(self, tokens: dict, settings: "Settings", app: str = ""):
        super().__init__()
        self._tokens, self._settings, self._app = tokens, settings, app
        self._values = {}
        self._map = QQmlPropertyMap(self)
        self._refresh(first=True)
        settings.changed.connect(self._refresh)

    def _refresh(self, first: bool = False) -> None:
        new = self._build()
        if new == self._values:
            return
        for key, value in new.items():
            if key not in self._values or self._values[key] != value:
                self._map.insert(key, value)
        for key in set(self._values) - set(new):
            self._map.clear(key)
        self._values = new
        if not first:
            self.changed.emit()

    values = property(lambda self: dict(self._values))

    _dark = property(lambda self: self._settings.dark)
    _realm = property(lambda self: self._settings.realm)

    def _wall_top(self) -> float:
        """How light the wallpaper is under the top bar (wall_top), for the bar to turn to glass where its text
        wouldn't read: dark text on a dark scene, light text on a bright picture. A realm's scene by its still for the
        appearance (the scene starts from it); a live wallpaper someone made by its picture or scene, darkened as it
        is; a video: -1."""
        wp = self._settings.wallpaper
        stills = Path(QUrl(live_dir()).toLocalFile()) / "stills" if live_dir() else None

        def still(realm: str, night: bool = False) -> float:
            if not stills:
                return -1.0
            day = stills / f"{realm}-day.jpg"
            return wall_top(str(day if not night and not self._dark and day.exists() else stills / f"{realm}.jpg"))
        if wp.endswith("/wallpaper.json"):
            spec = self._settings._wallpaper_spec()
            base = spec.get("base", "scene")
            v = (wall_top(str(Path(wp).parent / spec["file"])) if base == "picture" and spec.get("file")
                 else still(spec.get("scene") or "aurora", night=True) if base == "scene" else -1.0)   # (always its night)
            try:
                shade = max(0.0, min(0.7, float(spec.get("shade") or 0)))
            except (TypeError, ValueError):
                shade = 0.0
            return round(v * (1 - shade), 3) if v >= 0 else v
        return wall_top(wp) if wp else still(self._realm)

    def _wall_picture(self) -> str:
        """The picture the wallpaper is (or starts from), for its accent: a picture; a live wallpaper's picture, or
        the still of its scene; a realm's scene by its still. "" for a video."""
        wp = self._settings.wallpaper
        stills = Path(QUrl(live_dir()).toLocalFile()) / "stills" if live_dir() else None

        def still(realm: str) -> str:
            if not stills:
                return ""
            day = stills / f"{realm}-day.jpg"
            return str(day if not self._dark and day.exists() else stills / f"{realm}.jpg")
        if wp.endswith("/wallpaper.json"):
            spec = self._settings._wallpaper_spec()
            base = spec.get("base", "scene")
            if base == "picture" and spec.get("file"):
                return str(Path(wp).parent / spec["file"])
            return still(spec.get("scene") or "aurora") if base == "scene" else ""
        return wp or still(self._realm)

    def _build(self) -> dict:
        tk = self._tokens
        mode = "dark" if self._dark else "light"
        spec = tk["realms"][self._realm]
        t = {k: qml_colour(v) for k, v in tk[mode].items()}
        t.update({"tintA": spec[mode]["tint_a"], "tintB": spec[mode]["tint_b"], "accent": spec[mode]["accent"],
                  "glowA": spec["glow"][0], "glowB": spec["glow"][1], "danger": tk["danger"][mode],
                  "onAccent": "#0B1512" if self._dark else "#FFFFFF", "dark": self._dark, "realm": self._realm, "liveDir": live_dir()})
        # Settings › Appearance › Accent colour: the realm's, or one the wallpaper is most about
        t["accentFromWall"] = False
        if getattr(self._settings, "accentFrom", "realm") == "wallpaper":
            picked = wall_accent(self._wall_picture())
            if picked:
                t["accent"], t["accentFromWall"] = accent_colour(picked, self._dark), True
        t["wallTop"] = self._wall_top()
        t.update({"radius" + k.title(): v for k, v in tk["radius"].items()})
        t.update({"space" + k.title(): v for k, v in tk["space"].items()})
        t.update({"panelOpacity": tk["glass"]["panel_opacity"], "popupOpacity": tk["glass"]["popup_opacity"],
                  "hoverMs": tk["motion"]["hover_ms"], "pressScale": tk["motion"]["press_scale"],
                  "openMs": tk["motion"].get("open_ms", 220), "closeMs": tk["motion"].get("close_ms", 150), "moveMs": tk["motion"].get("move_ms", 260),
                  "font": tk["font"]["ui"], "fontMono": tk["font"]["mono"]})
        # Glass surfaces: the window colour at panel / popup opacity (KWin adds the blur behind them).
        base = tk[mode]["window"].lstrip("#")
        t["glass"] = "#%02X%s" % (round(tk["glass"]["panel_opacity"] * 255 * (0.72 if self._dark else 0.8)), base)
        t["popup"] = "#%02X%s" % (round(tk["glass"]["popup_opacity"] * 255), tk[mode]["menu_bg"].lstrip("#"))
        t["line"] = "#1AFFFFFF" if self._dark else "#33141E28"
        t["realms"] = [{"id": k, "label": v["label"], "a": v["glow"][0], "b": v["glow"][1]}
                       for k, v in tk["realms"].items()]
        # Islands (the shell's too: Huginn's compositor gives other apps' windows one)
        t.update({"island": "#D11A1E23" if self._dark else "#E0FFFFFF", "islandLine": "#21FFFFFF" if self._dark else "#29141E28",
                  "group": "#0FFFFFFF" if self._dark else "#A6FFFFFF", "separator": "#1CFFFFFF" if self._dark else "#24141E28"})
        own = tk.get("apps", {}).get(self._app)
        if own:                                          # a glass-and-islands app: its own colour, tint and light
            g = tk["app_glass"]
            colour = t["accent"] if self._app == "welcome" else own[0 if self._dark else 1]   # Welcome wears the realm
            base = g["base_dark" if self._dark else "base_light"]
            mix = [round(int(colour[i:i + 2], 16) * g["tint"] + int(base[i:i + 2], 16) * (1 - g["tint"])) for i in (1, 3, 5)]
            t.update({"realmAccent": t["accent"], "accent": colour, "onAccent": "#0C1013" if self._dark else "#FFFFFF",
                      "appBase": "#%02X%02X%02X" % tuple(mix), "glowStrength": g["glow_dark" if self._dark else "glow_light"],
                      "island": "#D11A1E23" if self._dark else "#E0FFFFFF", "islandLine": "#21FFFFFF" if self._dark else "#29141E28",
                      "group": "#0FFFFFFF" if self._dark else "#A6FFFFFF", "separator": "#1CFFFFFF" if self._dark else "#24141E28"})
        return self._accessible(t, tk, mode)

    def _accessible(self, t: dict, tk: dict, mode: str) -> dict:
        """Accessibility settings, for every surface at once: solid instead of glass, stronger lines and text, no motion."""
        s = self._settings
        t.update(contrast=s.contrast, solid=s.reduceTransparency, still=s.reduceMotion)
        if s.reduceTransparency or s.contrast:
            win = tk[mode]["window"].lstrip("#")
            t["glass"] = "#FF" + win
            t["popup"] = "#FF" + tk[mode]["menu_bg"].lstrip("#")
            if "island" in t:
                t["island"] = "#FF1A1E23" if self._dark else "#FFFFFFFF"
                t["glowStrength"] = 0.0
            t["panelOpacity"] = t["popupOpacity"] = 1.0
        if s.contrast:
            ink = "#FFFFFF" if self._dark else "#000000"
            t["text"] = ink
            t["text_secondary"] = "#E6FFFFFF" if self._dark else "#E0000000"
            t["line"] = t["separator"] = "#99FFFFFF" if self._dark else "#99000000"
            if "islandLine" in t:
                t["islandLine"] = "#CCFFFFFF" if self._dark else "#CC000000"
                t["group"] = "#1FFFFFFF" if self._dark else "#FFFFFFFF"
            t["icon"] = ink
        if s.reduceMotion:
            t["hoverMs"], t["pressScale"], t["openMs"], t["closeMs"], t["moveMs"] = 0, 1.0, 0, 0, 0
        return t

    t = Property(QObject, lambda self: self._map, constant=True)

    @Slot(bool)
    def setDark(self, dark: bool) -> None:
        self._settings.set("dark", "true" if dark else "false")

    @Slot(str)
    def setRealm(self, realm: str) -> None:
        self._settings.set("realm", realm)


class Settings(QObject):
    """User customisation, kept in ~/.config/huginn-shell/settings.json and shared by the shell and every app.
    Each process watches the file, so a change made anywhere (realm, dark mode, menu style) shows everywhere."""
    changed = Signal()
    DEFAULTS = {"menuStyle": "one", "barStyle": "islands", "liveAt": "top", "dark": "true", "realm": "aurora", "clock24": "true", "barDate": "true", "batteryPercent": "false", "barEverywhere": "true",
                "dockMakeRoom": "true", "dockDots": "true", "dockFollows": "true", "glass": "full", "frameTimes": "false", "gameStats": "false", "autoUpdate": "true", "liveWallpaper": "false",
                "contrast": "false", "reduceTransparency": "false", "reduceMotion": "false", "uiScale": "1",       # accessibility
                # Settings › Desktop & Dock
                "dockSize": "44", "hideStyle": "drop", "dockClickHides": "true", "overviewOpen": "glide", "hotCorner": "false",
                "spacesAllScreens": "true", "inAppMotion": "grow", "fillButtonLayouts": "true", "snapGaps": "true", "keepSnapped": "true",
                # windows and screens on Huginn's own compositor
                "reopenApps": "true", "rememberPlaces": "true", "adaptiveSync": "auto", "sharpX11": "true", "allowTearing": "true", "gameMode": "true",
                # Settings › Appearance › Wallpaper: a picture of your own (its path), or a live wallpaper someone made
                # (its wallpaper.json), instead of the realm's scene; the stamp changes when that one is edited
                "wallpaper": "", "wallpaperStamp": "0",
                # Settings › Appearance › Icons: the icon theme ("" as the system says: Huginn's)
                "iconTheme": "",
                # the desktop's widgets, in order (Widgets.qml; edited on the desktop or in Settings › Desktop & Dock)
                "widgets": "weather,privacy,next",
                # where the ones dragged out of the column were left: JSON, kind -> {"s": screen, "x", "y"} (parts of the screen)
                "widgetPlaces": "",
                # Settings › Desktop & Dock: the Desktop folder's files as icons on the desktop (DesktopIcons.qml), a dock
                # on every screen (not just the one you're using), and the Control Centre's quick tiles, in order
                "desktopFiles": "true", "dockEverywhere": "false", "quickTiles": "dnd,night,dark,captions",
                # Settings › Desktop & Dock › Screen corners: what pushing the pointer into each does ("" nothing; the
                # top right one also follows the older hotCorner switch)
                "cornerTL": "", "cornerTR": "", "cornerBL": "", "cornerBR": "",
                # Settings › Notifications: keep a week of them for the Control Centre's History
                "notifHistory": "true",
                # Settings › Keyboard: hold Super on its own a moment and every shortcut shows (KeysSheet.qml)
                "keySheet": "true",
                # Settings › Accessibility › Live captions (CaptionBar.qml): on, how big, where the bar was left (its
                # middle, as parts of the screen: "0.5,0.82"; "" low in the middle) and which speech model ("" the
                # quickest that's downloaded)
                "captions": "false", "captionsSize": "medium", "captionsPos": "", "captionsModel": "",
                # Settings › Appearance › Accent colour: the realm's own, or picked from the wallpaper (wall_accent)
                "accentFrom": "realm",
                # Settings › Appearance › Screen saver: what shows when the computer is left alone, and after how long
                "saver": "clock", "saverAfter": "5"}
    CORNERS = ("", "overview", "desktop", "launcher", "control", "today", "search", "lookup", "saver", "lock")
    SAVERS = ("off", "clock", "photos", "wallpaper")
    WIDGETS = ("weather", "privacy", "next", "clock", "month", "system", "music", "photo")
    PICTURES = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif", ".heic", ".jxl")
    SWITCHES = ("clock24", "barDate", "batteryPercent", "barEverywhere", "dockMakeRoom", "dockDots", "dockFollows", "frameTimes", "gameStats", "autoUpdate", "liveWallpaper", "contrast", "reduceTransparency", "reduceMotion",
                "dockClickHides", "hotCorner", "spacesAllScreens", "fillButtonLayouts", "snapGaps", "keepSnapped", "reopenApps", "rememberPlaces", "sharpX11", "allowTearing", "gameMode",
                "notifHistory", "keySheet", "captions", "desktopFiles", "dockEverywhere")
    QUICK_TILES = ("dnd", "night", "dark", "captions", "mute", "shot", "lookup", "saver")
    SCALES = ("1", "1.25", "1.5", "1.75", "2")

    def __init__(self, path: Path, realms: list, persist: bool = True):
        super().__init__()
        self._path, self._persist, self._values = path, persist, dict(self.DEFAULTS)
        self._choices = {"menuStyle": ("one", "row", "dropdown", "inline"), "barStyle": ("islands", "plain"), "liveAt": ("top", "dock"), "dark": ("true", "false"), "realm": tuple(realms), "uiScale": self.SCALES,
                         "dockSize": ("36", "40", "44", "52", "60"), "hideStyle": ("drop", "line", "comet"), "overviewOpen": ("glide", "light"),
                         "inAppMotion": ("grow", "slide"), "adaptiveSync": ("auto", "off"), "glass": ("full", "light", "off"),
                         **{k: self.CORNERS for k in ("cornerTL", "cornerTR", "cornerBL", "cornerBR")},
                         "saver": self.SAVERS, "saverAfter": ("1", "2", "5", "10", "15", "30"),
                         "accentFrom": ("realm", "wallpaper"), "captionsSize": ("small", "medium", "large"), "captionsModel": ("", "base", "small", "large-v3-turbo-q5_0"),
                         **{k: ("true", "false") for k in self.SWITCHES}}
        self._load()
        self._watcher = QFileSystemWatcher(self)
        if persist:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                # The folder tells of the file being replaced (how every Huginn process saves it, save_atomically);
                # the file itself of being written over in place (anything else that edits it).
                self._watcher.addPath(str(path.parent))
                self._watcher.directoryChanged.connect(self._reload)
                self._watcher.fileChanged.connect(self._reload)
                self._watch_file()
            except OSError:
                pass

    def _watch_file(self) -> None:
        if self._path.exists() and str(self._path) not in self._watcher.files():
            self._watcher.addPath(str(self._path))

    def _load(self) -> None:
        try:
            saved = json.loads(self._path.read_text(encoding="utf-8"))
            self._values.update({k: v for k, v in saved.items() if self._allowed(k, v)})
        except (OSError, ValueError, AttributeError):
            pass

    def _allowed(self, key: str, value) -> bool:
        if key == "wallpaper":                         # a path, not a choice: a picture or a live wallpaper that's there, or none
            return value == "" or (isinstance(value, str) and (value.lower().endswith(self.PICTURES) or value.endswith("/wallpaper.json"))
                                   and os.path.isfile(value))
        if key == "wallpaperStamp":
            return isinstance(value, str) and value.isdigit() and len(value) < 20
        if key == "widgets":                           # known kinds, each once, at most eight ("" none)
            got = value.split(",") if isinstance(value, str) and value else []
            return isinstance(value, str) and len(got) <= 8 and len(set(got)) == len(got) and all(w in self.WIDGETS for w in got)
        if key == "quickTiles":                        # known tiles, each once, at most eight ("" none)
            got = value.split(",") if isinstance(value, str) and value else []
            return isinstance(value, str) and len(got) <= 8 and len(set(got)) == len(got) and all(t in self.QUICK_TILES for t in got)
        if key == "widgetPlaces":
            return value == "" or self._places(value) is not None
        if key == "captionsPos":                       # the caption bar's middle, as parts of its screen
            return value == "" or (isinstance(value, str) and re.fullmatch(r"(0(\.\d{1,4})?|1(\.0{1,4})?),(0(\.\d{1,4})?|1(\.0{1,4})?)", value) is not None)
        if key == "iconTheme":                         # a theme's folder name (Settings checks it's installed)
            return value == "" or (isinstance(value, str) and re.fullmatch(r"[\w.+ -]{1,80}", value) is not None and ".." not in value)
        return value in self._choices.get(key, ())

    def _wallpaper_spec(self) -> dict:
        """A live wallpaper someone made: its wallpaper.json, and its folder (where its picture or video is)."""
        path = self._values.get("wallpaper", "")
        if not path.endswith("/wallpaper.json"):
            return {}
        try:
            spec = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(spec, dict):
            return {}
        spec["folder"] = QUrl.fromLocalFile(str(Path(path).parent) + "/").toString()
        spec["stamp"] = self._values.get("wallpaperStamp", "0")
        return spec

    def _reload(self) -> None:
        before = dict(self._values)
        self._load()
        self._watch_file()                 # a replaced file is a new file: watch that one
        if before != self._values:
            self.changed.emit()

    menuStyle = Property(str, lambda self: self._values["menuStyle"], notify=changed)
    barStyle = Property(str, lambda self: self._values["barStyle"], notify=changed)      # the top bar: "islands" (as the dock) or "plain"
    liveAt = Property(str, lambda self: self._values["liveAt"], notify=changed)          # the live island: "top" (in the bar) or "dock"
    dark = Property(bool, lambda self: self._values["dark"] == "true", notify=changed)
    realm = Property(str, lambda self: self._values["realm"], notify=changed)
    clock24 = Property(bool, lambda self: self._values["clock24"] == "true", notify=changed)
    barDate = Property(bool, lambda self: self._values["barDate"] == "true", notify=changed)
    batteryPercent = Property(bool, lambda self: self._values["batteryPercent"] == "true", notify=changed)
    barEverywhere = Property(bool, lambda self: self._values["barEverywhere"] == "true", notify=changed)   # a top bar on every screen, not just the main one
    dockFollows = Property(bool, lambda self: self._values["dockFollows"] == "true", notify=changed)       # the dock comes to the screen whose bottom the pointer rests at
    glass = Property(str, lambda self: self._values["glass"], notify=changed)                               # the frosted glass: full, light (cheaper) or off
    frameTimes = Property(bool, lambda self: self._values["frameTimes"] == "true", notify=changed)          # the frame-time display (Super+Alt+F)
    gameStats = Property(bool, lambda self: self._values["gameStats"] == "true", notify=changed)            # the game stats overlay (Super+Alt+G)
    # "Make room for windows": the dock slides away while a window covers its place (a filled one, or one dragged
    # over it), and comes back when the pointer reaches the bottom edge. (Was "dockHide", which nothing read.)
    dockMakeRoom = Property(bool, lambda self: self._values["dockMakeRoom"] == "true", notify=changed)
    dockDots = Property(bool, lambda self: self._values["dockDots"] == "true", notify=changed)
    autoUpdate = Property(bool, lambda self: self._values["autoUpdate"] == "true", notify=changed)
    liveWallpaper = Property(bool, lambda self: self._values["liveWallpaper"] == "true", notify=changed)   # the wallpaper moves on the desktop too
    contrast = Property(bool, lambda self: self._values["contrast"] == "true", notify=changed)
    reduceTransparency = Property(bool, lambda self: self._values["reduceTransparency"] == "true", notify=changed)
    reduceMotion = Property(bool, lambda self: self._values["reduceMotion"] == "true", notify=changed)
    uiScale = Property(str, lambda self: self._values["uiScale"], notify=changed)
    dockSize = Property(int, lambda self: int(self._values["dockSize"]), notify=changed)
    hideStyle = Property(str, lambda self: self._values["hideStyle"], notify=changed)
    dockClickHides = Property(bool, lambda self: self._values["dockClickHides"] == "true", notify=changed)
    overviewOpen = Property(str, lambda self: self._values["overviewOpen"], notify=changed)
    hotCorner = Property(bool, lambda self: self._values["hotCorner"] == "true", notify=changed)
    cornerTL = Property(str, lambda self: self._values["cornerTL"], notify=changed)
    cornerTR = Property(str, lambda self: self._values["cornerTR"] or ("overview" if self._values["hotCorner"] == "true" else ""), notify=changed)
    cornerBL = Property(str, lambda self: self._values["cornerBL"], notify=changed)
    cornerBR = Property(str, lambda self: self._values["cornerBR"], notify=changed)
    notifHistory = Property(bool, lambda self: self._values["notifHistory"] == "true", notify=changed)
    keySheet = Property(bool, lambda self: self._values["keySheet"] == "true", notify=changed)
    captions = Property(bool, lambda self: self._values["captions"] == "true", notify=changed)
    accentFrom = Property(str, lambda self: self._values["accentFrom"], notify=changed)
    captionsSize = Property(str, lambda self: self._values["captionsSize"], notify=changed)
    captionsPos = Property(str, lambda self: self._values["captionsPos"], notify=changed)
    captionsModel = Property(str, lambda self: self._values["captionsModel"], notify=changed)
    saver = Property(str, lambda self: self._values["saver"], notify=changed)
    saverAfter = Property(int, lambda self: int(self._values["saverAfter"]), notify=changed)
    spacesAllScreens = Property(bool, lambda self: self._values["spacesAllScreens"] == "true", notify=changed)
    inAppMotion = Property(str, lambda self: self._values["inAppMotion"], notify=changed)
    fillButtonLayouts = Property(bool, lambda self: self._values["fillButtonLayouts"] == "true", notify=changed)
    snapGaps = Property(bool, lambda self: self._values["snapGaps"] == "true", notify=changed)
    keepSnapped = Property(bool, lambda self: self._values["keepSnapped"] == "true", notify=changed)
    reopenApps = Property(bool, lambda self: self._values["reopenApps"] == "true", notify=changed)
    rememberPlaces = Property(bool, lambda self: self._values["rememberPlaces"] == "true", notify=changed)
    adaptiveSync = Property(str, lambda self: self._values["adaptiveSync"], notify=changed)
    sharpX11 = Property(bool, lambda self: self._values["sharpX11"] == "true", notify=changed)
    allowTearing = Property(bool, lambda self: self._values["allowTearing"] == "true", notify=changed)
    gameMode = Property(bool, lambda self: self._values["gameMode"] == "true", notify=changed)        # GameMode for games, by itself
    wallpaper = Property(str, lambda self: self._values["wallpaper"], notify=changed)
    wallpaperSpec = Property("QVariantMap", lambda self: self._wallpaper_spec(), notify=changed)
    iconTheme = Property(str, lambda self: self._values["iconTheme"], notify=changed)
    widgets = Property("QVariantList", lambda self: [w for w in self._values["widgets"].split(",") if w], notify=changed)
    desktopFiles = Property(bool, lambda self: self._values["desktopFiles"] == "true", notify=changed)
    dockEverywhere = Property(bool, lambda self: self._values["dockEverywhere"] == "true", notify=changed)
    quickTiles = Property("QVariantList", lambda self: [t for t in self._values["quickTiles"].split(",") if t], notify=changed)
    quickTileKinds = Property("QVariantList", lambda self: list(self.QUICK_TILES), constant=True)
    widgetPlaces = Property("QVariantMap", lambda self: self._places(self._values.get("widgetPlaces", "")) or {}, notify=changed)

    def _places(self, text: str):
        """The widgets' places as a map, or None when the text isn't one: known kinds, a screen's name, two parts of 1."""
        try:
            data = json.loads(text) if text else {}
        except ValueError:
            return None
        if not isinstance(data, dict) or len(text) > 2000:
            return None
        for kind, p in data.items():
            if kind not in self.WIDGETS or not isinstance(p, dict) or not isinstance(p.get("s"), str) or len(p["s"]) > 60:
                return None
            if not all(isinstance(p.get(k), (int, float)) and not isinstance(p.get(k), bool) and 0 <= p[k] <= 1 for k in ("x", "y")):
                return None
        return data
    widgetKinds = Property("QVariantList", lambda self: list(self.WIDGETS), constant=True)

    def override(self, key: str, value: str) -> None:
        """Set a value for this run only (command-line flags)."""
        if self._allowed(key, value):
            self._values[key] = value

    @Slot(str, str)
    def set(self, key: str, value: str) -> None:
        if key not in self._values or not self._allowed(key, value) or self._values[key] == value:
            return
        self._values[key] = value
        self.changed.emit()
        if self._persist:
            try:
                save_atomically(self._path, json.dumps(self._values, indent=2))
                self._watch_file()
                if key == "realm":
                    write_look(value)
            except OSError as err:
                print(f"Could not save settings: {err}", file=sys.stderr)


def save_atomically(path: Path, text: str) -> None:
    """Writes a file whole and then puts it in place, so a reader never sees half of it, and every process watching
    its folder (the shell, each app, the session daemon) is told: writing over a file in place only tells those
    watching the file itself, which is how a change made in Settings could go unseen until the next sign-in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{os.getpid()}.part")
    part.write_text(text, encoding="utf-8")
    os.replace(part, path)


def write_look(realm: str) -> None:
    """The realm for the lock screen, which runs inside KDE's screen locker and can only read a QML file:
    ~/.local/share/huginn/Look.qml."""
    if not re.fullmatch(r"[a-z]+", realm or ""):
        return
    look = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "Look.qml"
    text = f'import QtQuick\n// Written by the shell when the realm changes; the lock screen reads it.\nItem {{ readonly property string realm: "{realm}" }}\n'
    try:
        if not look.exists() or look.read_text(encoding="utf-8") != text:
            look.parent.mkdir(parents=True, exist_ok=True)
            look.write_text(text, encoding="utf-8")
    except OSError:
        pass


def unstick(shell) -> None:
    """A safety net for the first moments of a session. When KWin is very busy just after sign-in (a computer drawing
    with its CPU, apps all starting at once), a shell surface can miss the frame KWin owes it; Qt then stops drawing
    that surface until something else makes KWin repaint, and the desktop stays at the arrival's first picture. So:
    after a few seconds the arrival is over whatever happened, and any surface Qt has stopped drawing is mapped again.
    (Plain timers on the event loop, not QML's, which wait on the very frames that went missing.)"""
    import time

    def windows():
        return [w for w in QGuiApplication.topLevelWindows() if w.isVisible()]

    def kick():
        if os.environ.get("HUGINN_DEBUG_UNSTICK"):
            print("unstick:", time.monotonic(), shell.property("settled"), [(w.objectName() or w.title(), w.isExposed()) for w in windows()], file=sys.stderr, flush=True)
        for w in windows():
            if not w.isExposed():
                w.hide()
                w.show()

    def arrive():
        if not shell.property("settled"):
            shell.setProperty("settled", True)
            for w in windows():
                if w.objectName() == "arrival":
                    w.hide()
        kick()
    if os.environ.get("HUGINN_DEBUG_UNSTICK"):
        print("unstick: armed", time.monotonic(), file=sys.stderr, flush=True)
    QTimer.singleShot(6000, arrive)
    for t in (9000, 14000, 22000):
        QTimer.singleShot(t, kick)


def follow_look(settings) -> None:
    """Everyone else's apps wear the realm too (apps/huginn_look.py: Kvantum and KDE colours for Qt, Breeze-GTK in
    Huginn's colours for GTK). Done off the main thread: it runs a couple of small programs."""
    import threading
    for d in (HERE.parent / "apps", Path("/usr/share/huginn-apps")):
        if (d / "huginn_look.py").exists() and str(d) not in sys.path:
            sys.path.append(str(d))
    try:
        import huginn_look
    except ImportError:
        return
    def go():
        args = (settings.property("realm"), settings.property("dark"), settings.property("contrast"))
        threading.Thread(target=huginn_look.apply, args=args, daemon=True).start()
    settings.changed.connect(go)
    QTimer.singleShot(15000, go)          # at sign-in, once the desktop is up (it makes KWin and KDE's apps reload)


def load_tokens() -> dict:
    tokens_file = next((p for p in TOKEN_PATHS if p.is_file()), None)
    if tokens_file is None:
        raise SystemExit("tokens.json not found")
    return json.loads(tokens_file.read_text(encoding="utf-8"))


def make_theme(dark: bool, light: bool, realm: str, persist: bool, app: str = ""):
    """(tokens, settings, theme) for the shell or an app, with command-line overrides applied."""
    tokens = load_tokens()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    settings = Settings(config_home / "huginn-shell" / "settings.json", list(tokens["realms"]), persist=persist)
    if dark or light:
        settings.override("dark", "true" if dark else "false")
    if realm:
        settings.override("realm", realm)
    gui = QGuiApplication.instance()
    if isinstance(gui, QGuiApplication):                     # text with no family of its own is in Inter too
        gui.setFont(QFont(tokens["font"]["ui"], 10))
        follow_icons(settings)
    return tokens, settings, Theme(tokens, settings, app)


def follow_icons(settings) -> None:
    """Settings › Appearance › Icons, in this process at once (and again whenever it changes): Qt's icon theme. Other
    apps read it from kdeglobals, which Settings writes too."""
    from PySide6.QtGui import QIcon

    def apply():
        want = settings.property("iconTheme")
        if want and want != QIcon.themeName():
            QIcon.setThemeName(want)
    apply()
    settings.changed.connect(apply)


def icon_theme() -> str:
    from PySide6.QtGui import QIcon
    return QIcon.themeName() or "Huginn"


DEMO_APPS = [("News", True), ("Maps", True), ("Huginn", False), ("Files", False), ("Mail", False),
             ("Calendar", False), ("Notes", False), ("Writer", False), ("Music", False), ("Terminal", False),
             ("Settings", False), ("Photos", False), ("App Store", False)]
DEMO_RUNNING = ["Huginn", "Files", "Writer"]
DEMO_GROUPS = {"News": "internet", "Maps": "utilities", "Huginn": "internet", "Files": "system", "Mail": "internet", "Calendar": "work",
               "Notes": "utilities", "Writer": "work", "Music": "media", "Terminal": "system", "Settings": "system", "Photos": "media",
               "App Store": "system"}
# The start menu's groups, from a .desktop file's Categories (first rule that matches wins).
GROUP_RULES = (("games", {"Game"}), ("utilities", {"Utility", "Accessibility"}),
               ("internet", {"Network", "WebBrowser", "Email", "Chat", "InstantMessaging", "Feed", "News", "Telephony", "RemoteAccess", "P2P"}),
               ("work", {"Office", "Development", "IDE", "WordProcessor", "Spreadsheet", "Presentation", "Calendar", "ContactManagement",
                         "Finance", "ProjectManagement", "Education", "Science"}),
               ("create", {"AudioVideoEditing", "Recorder", "Midi", "Sequencer", "2DGraphics", "3DGraphics", "RasterGraphics", "VectorGraphics"}),
               ("media", {"AudioVideo", "Audio", "Video", "Player", "Graphics", "Photography", "TV", "Music"}))


def app_colours() -> dict:
    """Each of Huginn's own apps' colour, [dark, light], by app key (tokens.json "apps")."""
    try:
        return {k: v for k, v in load_tokens().get("apps", {}).items() if not k.startswith("_")}
    except SystemExit:
        return {}


RECENT = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "huginn" / "recent-apps.json"
DOCK = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "huginn" / "dock.json"
DEFAULT_PINNED = ["Huginn", "Files", "Mail", "Calendar", "Notes", "Writer", "Music", "Terminal", "App Store", "Settings"]
DEMO_RECENT = ["Huginn", "Files", "Writer", "Mail", "Music", "Notes"]


def group_of(categories: str) -> str:
    cats = {c for c in (categories or "").split(";") if c}
    return next((g for g, names in GROUP_RULES if cats & names), "system" if cats & {"System", "Settings"} else "utilities")
# Line icons for Huginn's own apps, by the app key in "huginn_app.py <key>" (see qml/Glyph.qml).
APP_GLYPHS = {"files": "folder", "calendar": "calendar", "mail": "mail", "settings": "gear", "monitor": "cpu",
              "store": "bag", "video": "video", "music": "music", "notes": "note", "photos": "image",
              "documents": "file", "calculator": "calc", "clock": "clock", "terminal": "terminal",
              "screenshot": "camera", "archives": "box", "welcome": "star", "writer": "edit", "sheets": "table",
              "slides": "slides", "passwords": "key", "contacts": "user", "weather": "cloudsun", "reminders": "bell", "phone": "phone", "print": "printer", "maps": "pin", "podcasts": "podcast", "books": "book", "translate": "translate", "games": "gamepad", "backup": "history",
              "disks": "disc", "camera": "camera", "recorder": "mic",
              "messages": "chat", "authenticator": "shield", "privacy": "eye", "feeds": "doc", "clips": "video", "shortcuts": "bolt",
              "money": "wallet", "characters": "smile", "fonts": "type", "sharing": "share", "help": "help", "code": "code"}
DEMO_GLYPHS = {"Huginn": "globe", "Files": "folder", "Mail": "mail", "Calendar": "calendar", "Notes": "note",
               "Writer": "edit", "Music": "music", "Terminal": "terminal", "Settings": "gear", "Photos": "image",
               "App Store": "bag", "News": "doc", "Maps": "globe"}
DOWNLOAD_PARTS = ("*.part", "*.crdownload", "*.download")   # what browsers name a file while it is arriving


class SysIcon(QQuickImageProvider):
    """image://sysicon/<name>: an icon from the system icon theme, for apps that are not Huginn's own."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Pixmap)

    def requestPixmap(self, name, size, requested):
        side = max(requested.width(), requested.height(), 64)
        name = name.split("?", 1)[0]                                         # (?v=N: asked again after the theme changed)
        pix = QIcon.fromTheme(name).pixmap(side, side)
        if pix.isNull() and name and "/" not in name and ".." not in name:   # no icon theme in force: look in hicolor ourselves
            for sub in ("scalable/apps/%s.svg", "128x128/apps/%s.png", "64x64/apps/%s.png", "48x48/apps/%s.png"):
                path = "/usr/share/icons/hicolor/" + sub % name
                if os.path.isfile(path):
                    pix = QIcon(path).pixmap(side, side)
                    if not pix.isNull():
                        break
        return pix


def own_icon(key: str) -> str:
    """The picture drawn for one of Huginn's own apps (scripts/make-icons.py), as an address QML can show; "" if none."""
    if not key:
        return ""
    for base in ("/usr/share/icons/hicolor", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "overlay", "usr", "share", "icons", "hicolor")):
        path = os.path.join(base, "128x128", "apps", f"huginn-{key}.png")
        if os.path.isfile(path):
            return "file://" + os.path.abspath(path)
    return ""


def _iconwrap():
    """huginn_iconwrap.py (other apps' icons in Huginn's glass), from the installed apps or the kit's."""
    for d in (Path("/usr/share/huginn-apps"), HERE.parent / "apps"):
        if (d / "huginn_iconwrap.py").exists():
            if str(d) not in sys.path:
                sys.path.append(str(d))
            import huginn_iconwrap
            return huginn_iconwrap
    return None


def wrapped_icon(icon: str, desktop_id: str) -> str:
    """Another app's icon on Huginn's glass tile (huginn_iconwrap.py made it), as an address QML can show; "" if
    there's none yet."""
    wrap = _iconwrap()
    found = wrap.find_wrapped(icon, desktop_id) if wrap and icon else ""
    return QUrl.fromLocalFile(found).toString() if found else ""


def app_key(command: str) -> str:
    """'python3 /usr/share/huginn-apps/huginn_app.py files' -> 'files'; anything else -> ''."""
    parts = shlex.split(command) if command else []
    for i, part in enumerate(parts[:-1]):
        if part.endswith("huginn_app.py"):
            return parts[i + 1]
    return ""


class Apps(QObject):
    """Installed applications from the XDG .desktop files; web apps (installed by Huginn) come first.

    `running` is the names of apps that have a live process. It is found by reading /proc every two
    seconds, so it follows processes, not windows: an app that keeps running with no window still counts.
    """
    changed = Signal()
    launched = Signal(str)          # an app was started from the shell (start menu, search, dock): the dock shows it starting
    runningChanged = Signal()

    def __init__(self, demo: bool):
        super().__init__()
        self._demo = demo
        if demo:
            self._apps = [{"name": n, "exec": "", "icon": "", "web": w, "glyph": DEMO_GLYPHS.get(n, ""), "image": "", "group": DEMO_GROUPS.get(n, "utilities"),
                           "keywords": "", "about": "",
                           "own": "" if w else own_icon("browser" if n == "Huginn" else next((k for k in APP_GLYPHS if k == n.lower() or n.lower().startswith(k)), ""))} for n, w in DEMO_APPS]
            colours = app_colours()
            for a in self._apps:
                a.update({"execRaw": "", "mimes": [], "actions": [{"name": "New Window", "exec": ""}] if a["name"] in ("Huginn", "Files", "Writer") else [],
                          "file": "", "flatpak": a["name"] == "Podcasts", "id": "huginn-" + a["name"].lower()})
                key = "browser" if a["name"] == "Huginn" else next((k for k in colours if k == a["name"].lower() or a["name"].lower().startswith(k)), "")
                a["colours"] = colours.get(key, [])
            self._apps.sort(key=lambda a: (not a["web"], a["name"].lower()))
            self._recent = list(DEMO_RECENT)
            self._running = list(DEMO_RUNNING) + ["Mail"]
            self._badges = {"Mail": 3}
        else:
            self._badges = {}
            self._apps = self._scan()
            self._recent = self._read_recent()
            self._running = []
            self._matchers = [(a["name"], self._matcher(a["exec"])) for a in self._apps]
            self._timer = QTimer(self, interval=2000, timeout=self._poll)
            self._timer.start()
            # New apps (installed with apt, Flatpak or the App Store, or a .desktop file dropped in place) show up in
            # the start menu at once, not at the next sign-in: every folder of .desktop files is watched, and a
            # folder that doesn't exist yet (Flatpak's, before the first Flatpak app) is looked for now and then.
            self._app_watch = QFileSystemWatcher(self)
            self._app_watch.directoryChanged.connect(lambda _path: self._rescan_soon.start())
            self._rescan_soon = QTimer(self, singleShot=True, interval=1200, timeout=self.rescan)
            self._watch_folders()
            self._folder_check = QTimer(self, interval=15000, timeout=self._watch_folders)
            self._folder_check.start()
            QTimer.singleShot(4000, self._wrap_new)              # icons for apps installed while signed out
            self._told = {}
            self._due = QTimer(self, interval=30000, timeout=self._reminders_due)
            self._due.start()
            self._poll()

    @staticmethod
    def _image(icon: str) -> str:
        """A URL QML can show for a .desktop Icon= value, or '' when the icon theme has none."""
        if not icon:
            return ""
        if os.path.isabs(icon):
            return QUrl.fromLocalFile(icon).toString() if os.path.isfile(icon) else ""
        return f"image://sysicon/{icon}?v={QIcon.themeName()}" if QIcon.hasThemeIcon(icon) else ""

    @staticmethod
    def _app_dirs() -> list:
        """Where .desktop files live: the user's own, every XDG data folder's, and Flatpak's exports (in case the
        session was started without Flatpak's XDG_DATA_DIRS)."""
        home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
        dirs = [home / "applications"]
        dirs += [Path(d) / "applications" for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if d]
        dirs += [home / "flatpak/exports/share/applications", Path("/var/lib/flatpak/exports/share/applications")]
        out = []
        for d in dirs:
            if d not in out:
                out.append(d)
        return out

    def _watch_folders(self) -> None:
        have = set(self._app_watch.directories())
        new = [str(d) for d in self._app_dirs() if d.is_dir() and str(d) not in have]
        if new:
            self._app_watch.addPaths(new)
            if have:                                  # a folder that appeared since: it may already hold apps
                self._rescan_soon.start()

    @Slot()
    def rescan(self) -> None:
        """Read the .desktop files again (something was installed, removed or changed)."""
        apps = self._scan()
        if apps == self._apps:
            return
        try:                                          # new apps' icons: Qt keeps what it found in the icon theme
            from PySide6.QtGui import QIcon
            QIcon.setThemeSearchPaths(QIcon.themeSearchPaths())
            apps = self._scan()
        except Exception:
            pass
        self._apps = apps
        self._matchers = [(a["name"], self._matcher(a["exec"])) for a in self._apps]
        self.changed.emit()
        self._poll()
        self._wrap_new()

    def _wrap_new(self) -> None:
        """Apps whose icon isn't on Huginn's glass yet (just installed): wrap them in the background, then look
        again. Each set of new icons is tried once, so an icon that can't be found doesn't keep it busy."""
        if self._demo or getattr(self, "_wrapping", None) is not None or icon_theme() != "Huginn":
            return                                    # (another icon theme: apps show its icons, not glass)
        missing = sorted({a["icon"] for a in self._apps if not a.get("own") and not a.get("web") and a.get("icon") and not a.get("glyph")})
        tried = getattr(self, "_wrap_tried", set())
        if not missing or set(missing) <= tried:
            return
        self._wrap_tried = tried | set(missing)
        wrap = _iconwrap()
        if wrap is None:
            return
        proc = QProcess(self)
        proc.finished.connect(lambda code, _status, proc=proc: self._wrapped(proc, code))
        self._wrapping = proc
        proc.start(sys.executable, [wrap.__file__, "--user", "--quiet"])

    def _wrapped(self, proc, code: int) -> None:
        self._wrapping = None
        proc.deleteLater()
        if code == 0:
            self.rescan()

    @classmethod
    def _scan(cls) -> list:
        dirs = cls._app_dirs()
        seen, apps = set(), []
        colours = app_colours()
        huginn_icons = icon_theme() == "Huginn"
        for folder in dirs:
            for path in sorted(folder.glob("*.desktop")) if folder.is_dir() else []:
                if path.name in seen:
                    continue
                seen.add(path.name)
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                try:
                    parser.read(path, encoding="utf-8")
                    entry = parser["Desktop Entry"]
                except (configparser.Error, KeyError, UnicodeDecodeError):
                    continue
                if entry.get("Type") != "Application" or entry.get("NoDisplay", "false").lower() == "true":
                    continue
                command = re.sub(r"\s*%[a-zA-Z]", "", entry.get("Exec", ""))
                name = entry.get("Name", path.stem)
                mine = entry.get("X-Huginn-Own-Icon", "false").lower() == "true"
                glyph = APP_GLYPHS.get(app_key(command), "globe" if name == "Huginn" else "")
                key = app_key(command)
                apps.append({"name": name, "icon": entry.get("Icon", ""), "exec": command, "id": path.stem,
                             "group": "internet" if entry.get(WEB_APP_KEY, "false").lower() == "true" else group_of(entry.get("Categories", "")),
                             "keywords": " ".join(filter(None, (entry.get("GenericName", ""), entry.get("Keywords", "").replace(";", " "),
                                                               entry.get("Comment", "")))),
                             "about": entry.get("GenericName", "") or entry.get("Comment", ""),
                             "colours": colours.get(key, []),
                             "wm": entry.get("StartupWMClass", "") or (f"huginn-{key}" if key else path.stem),
                             "web": entry.get(WEB_APP_KEY, "false").lower() == "true",
                             "glyph": "" if mine else glyph, "image": "" if glyph and not mine else cls._image(entry.get("Icon", "")),
                             # an icon of your own (Settings › Appearance) is the whole tile; then Huginn's own picture;
                             # then another app's icon on Huginn's glass, while the icons are Huginn's
                             "own": (QUrl.fromLocalFile(entry.get("Icon", "")).toString() if mine and os.path.isfile(entry.get("Icon", "")) else "")
                                    or ("" if mine else own_icon("browser" if name == "Huginn" else app_key(command) if app_key(command) in APP_GLYPHS else ""))
                                    or (wrapped_icon(entry.get("Icon", ""), path.stem) if huginn_icons and not mine else ""),
                             "execRaw": entry.get("Exec", ""), "mimes": [m for m in entry.get("MimeType", "").split(";") if m],
                             "actions": cls._actions(parser, entry), "file": str(path),
                             "flatpak": "flatpak" in str(path) or bool(entry.get("X-Flatpak", ""))})
        return sorted(apps, key=lambda a: (not a["web"], a["name"].lower()))

    @staticmethod
    def _actions(parser, entry) -> list:
        """The .desktop file's own extra actions ("New Window", "New Private Window"…), for the app's island."""
        out = []
        for key in [a for a in entry.get("Actions", "").split(";") if a]:
            section = f"Desktop Action {key}"
            if parser.has_section(section) and parser[section].get("Exec"):
                out.append({"name": parser[section].get("Name", key), "exec": parser[section]["Exec"]})
        return out[:4]

    @staticmethod
    def _matcher(command: str):
        """What to look for in a process's argument list to say 'this app is running'."""
        try:
            parts = shlex.split(command) if command else []
        except ValueError:
            parts = []
        if not parts:
            return None
        key = app_key(command)
        if key:
            return ("huginn_app.py", key)
        first = os.path.basename(parts[0])
        if first == "flatpak":                       # flatpak run [options] org.example.App: that app's id, anywhere in a process's arguments
            ident = next((p for p in parts[2:] if not p.startswith("-") and "." in p), "")
            return ("@flatpak", ident) if ident else None
        if first == "env":                           # env FOO=1 program …
            rest = [p for p in parts[1:] if "=" not in p and not p.startswith("-")]
            first = os.path.basename(rest[0]) if rest else first
        if first.startswith("python") and len(parts) > 1:
            return (os.path.basename(parts[1]), "")
        return (first, "")

    def _poll(self) -> None:
        procs = []
        for entry in os.scandir("/proc") if os.path.isdir("/proc") else []:
            if not entry.name.isdigit():
                continue
            try:
                with open(os.path.join(entry.path, "cmdline"), "rb") as fh:
                    argv = [os.path.basename(a.decode("utf-8", "replace")) for a in fh.read(4096).split(b"\0") if a]
            except OSError:
                continue
            if argv:
                procs.append(argv)
        running = []
        for name, match in self._matchers:
            if match and any(self._argv_matches(match, argv) for argv in procs):
                running.append(name)
        badges = self.read_badges(running)
        if running != self._running or badges != self._badges:
            self._running, self._badges = running, badges
            self.runningChanged.emit()

    @staticmethod
    def _argv_matches(match, argv: list) -> bool:
        program, arg = match
        if program == "@flatpak":
            return arg in argv
        head = argv[:2]
        return program in head and (not arg or arg in argv[head.index(program) + 1:head.index(program) + 2])

    def app_for_argv(self, argv: list) -> str:
        """The installed app whose command this process is (the window list asks, for windows it can't name)."""
        argv = [os.path.basename(a) for a in argv]
        return next((name for name, match in getattr(self, "_matchers", []) if match and self._argv_matches(match, argv)), "")

    def _reminders_due(self) -> None:
        """Every half minute: has a reminder just come due? Then say so, whether or not Reminders is open."""
        try:
            import subprocess
            if "/usr/share/huginn-apps" not in sys.path:
                sys.path.append("/usr/share/huginn-apps")
            import huginn_reminders
            for item in huginn_reminders.to_tell(huginn_reminders._read()["items"], self._told):
                subprocess.Popen(["notify-send", "-a", "Reminders", "-i", "appointment-soon", item["title"], (item.get("note") or "Due now").splitlines()[0]],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as err:                                   # the dock must never fall over because of a reminder
            print(f"reminders: {err}", file=sys.stderr)

    @staticmethod
    def read_badges(running: list) -> dict:
        """Numbers apps want on their dock tile (Mail: unread). Each open app keeps a tiny file in the login's runtime
        folder; a number only counts while its app is running, so a crashed app can't leave a stale one."""
        folder = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "", "huginn", "badges") if os.environ.get("XDG_RUNTIME_DIR") else ""
        out = {}
        if not folder or not os.path.isdir(folder):
            return out
        by_key = {name.lower(): name for name in running}
        try:
            for entry in os.scandir(folder):
                name = by_key.get(entry.name)
                if not name or not entry.is_file(follow_symlinks=False) or entry.stat(follow_symlinks=False).st_uid != os.getuid():
                    continue
                with open(entry.path, "r", encoding="ascii", errors="ignore") as fh:
                    text = fh.read(12).strip()
                if text.isdigit() and int(text) > 0:
                    out[name] = int(text)
        except OSError:
            pass
        return out

    def _pids_of(self, name: str) -> list:
        """The processes of a running app (by the same match the dock uses), and everything they started."""
        match = next((m for n, m in getattr(self, "_matchers", []) if n == name), None)
        if not match:
            return []
        procs = {}
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            try:
                with open(os.path.join(entry.path, "cmdline"), "rb") as fh:
                    argv = [os.path.basename(a.decode("utf-8", "replace")) for a in fh.read(4096).split(b"\0") if a]
                with open(os.path.join(entry.path, "stat")) as fh:
                    stat = fh.read()
                ppid = int(stat[stat.rindex(")") + 2:].split()[1])
                if os.stat(entry.path).st_uid != os.getuid():
                    continue
            except (OSError, ValueError, IndexError):
                continue
            procs[int(entry.name)] = (argv, ppid)
        roots = {pid for pid, (argv, _) in procs.items() if argv and self._argv_matches(match, argv)}
        out, grew = set(roots), True
        while grew:                                          # and what they started (helpers, a game Steam opened)
            grew = False
            for pid, (_, ppid) in procs.items():
                if ppid in out and pid not in out:
                    out.add(pid)
                    grew = True
        return sorted(out)

    @Slot(str, bool)
    def quit(self, name: str, force: bool) -> None:
        """The control centre's Running in the background › Quit: the app is asked to close (Steam the way it asks
        itself to, so it shuts down cleanly); Force Quit stops it at once."""
        if self._demo:
            self._running = [n for n in self._running if n != name]
            self.runningChanged.emit()
            return
        import signal
        app = next((a for a in self._apps if a["name"] == name), None)
        if not force and app and ("steam" in app.get("exec", "").lower() or "valvesoftware.Steam" in app.get("exec", "")):
            try:
                parts = [p for p in shlex.split(app["exec"]) if not p.startswith("%")]
                QProcess.startDetached(parts[0], parts[1:] + ["-shutdown"])
                QTimer.singleShot(1500, self._poll)
                return
            except (ValueError, IndexError):
                pass
        for pid in self._pids_of(name):
            try:
                os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
            except OSError:
                pass
        QTimer.singleShot(800, self._poll)

    all = Property("QVariantList", lambda self: self._apps, notify=changed)
    running = Property("QVariantList", lambda self: self._running, notify=runningChanged)
    badges = Property("QVariantMap", lambda self: self._badges, notify=runningChanged)

    @Slot(str)
    def launch(self, command: str) -> None:
        parts = shlex.split(command) if command else []
        if parts:
            QProcess.startDetached(parts[0], parts[1:])
        app = next((a for a in self._apps if a["exec"] and a["exec"] == command), None)
        if app:
            self.used(app["name"])
            self.launched.emit(app["name"])

    @Slot(str)
    def used(self, name: str) -> None:
        """The start menu's Recent row: the last six apps opened from the shell, newest first."""
        self._recent = [name] + [n for n in self._recent if n != name][:11]
        self.changed.emit()
        if self._demo:
            return
        try:
            RECENT.parent.mkdir(parents=True, exist_ok=True)
            RECENT.write_text(json.dumps(self._recent), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _read_recent() -> list:
        try:
            got = json.loads(RECENT.read_text(encoding="utf-8"))
            return [n for n in got if isinstance(n, str)][:12]
        except (OSError, ValueError):
            return []

    # ------------------------------------------------------------------ the dock's apps, and each app's island
    def _read_pins(self) -> list:
        if self._demo:
            return list(DEFAULT_PINNED)
        try:
            data = json.loads(DOCK.read_text(encoding="utf-8"))
            got = data.get("pinned")
            if not isinstance(got, list):
                return list(DEFAULT_PINNED)
            pins = [n for n in got if isinstance(n, str)]
            # The App Store joined the dock's first pins (2026-11-20): put in once for docks set up before, before
            # Settings; taken out again, it stays out
            if "App Store" not in pins and not data.get("storeOffered"):
                at = pins.index("Settings") if "Settings" in pins else len(pins)
                pins.insert(at, "App Store")
                try:
                    DOCK.write_text(json.dumps({"pinned": pins, "storeOffered": True}), encoding="utf-8")
                except OSError:
                    pass
            return pins
        except (OSError, ValueError, AttributeError):
            return list(DEFAULT_PINNED)

    def _pins(self) -> list:
        if not hasattr(self, "_pinned"):
            self._pinned = self._read_pins()
        return self._pinned
    pinned = Property("QVariantList", _pins, notify=changed)

    @Slot(str, bool)
    def setPinned(self, name: str, on: bool) -> None:
        pins = [n for n in self._pins() if n != name] + ([name] if on else [])
        self._pinned = pins
        self.changed.emit()
        if not self._demo:
            try:
                DOCK.parent.mkdir(parents=True, exist_ok=True)
                DOCK.write_text(json.dumps({"pinned": pins, "storeOffered": True}), encoding="utf-8")
            except OSError:
                pass

    def _find(self, name: str):
        return next((a for a in self._apps if a["name"] == name), None)

    @Slot(str, result="QVariantMap")
    def island(self, name: str) -> dict:
        """What an app's island shows: its recent files, its own actions, whether it's in the dock, and whether the
        App Store can remove it."""
        app = self._find(name)
        if not app:
            return {}
        if self._demo:
            recent = {"Writer": [("Iceland trip plan.odt", "Documents › Travel", "1:12 AM"), ("Cover letter, final.odt", "Documents", "yesterday"),
                                 ("Book club notes.odt", "Documents", "3 days ago")],
                      "Music": [("Late drive", "Playlist", "today")]}.get(name, [])
            files = [{"name": n, "path": "", "where": w, "when": t} for n, w, t in recent]
        else:
            for d in (Path("/usr/share/huginn-apps"), HERE.parent / "apps"):     # (the shared recent list lives with the apps)
                if (d / "huginn_recent.py").exists() and str(d) not in sys.path:
                    sys.path.append(str(d))
            import huginn_recent
            files = huginn_recent.for_app([app.get("id", ""), name, Path(shlex.split(app["exec"])[0]).name if app["exec"] else ""], app.get("mimes", []), 4)
        return {"name": name, "about": app.get("about", ""), "recent": files, "actions": [a["name"] for a in app.get("actions", [])],
                "pinned": name in self._pins(), "removable": bool(app.get("flatpak")), "running": name in self._running,
                "opensFiles": bool(app.get("mimes")) or self._demo}

    @staticmethod
    def _expand(exec_line: str, path: str = "") -> list:
        """A .desktop Exec line as an argument list, with %f/%u (and friends) filled in or dropped."""
        try:
            parts = shlex.split(exec_line)
        except ValueError:
            return []
        out = []
        for p in parts:
            if p in ("%f", "%F", "%u", "%U"):
                if path:
                    out.append(path)
            elif re.fullmatch(r"%[a-zA-Z]", p):
                continue
            else:
                out.append(p.replace("%%", "%"))
        if path and not any(p in ("%f", "%F", "%u", "%U") for p in parts):
            out.append(path)
        return out

    @Slot(str, str)
    def openWith(self, name: str, path: str) -> None:
        app = self._find(name)
        if not app or self._demo:
            return
        argv = self._expand(app.get("execRaw") or app["exec"], path)
        if argv:
            QProcess.startDetached(argv[0], argv[1:])
            self.used(name)

    @Slot(str, int)
    def runAction(self, name: str, index: int) -> None:
        app = self._find(name)
        if not app or self._demo or not (0 <= index < len(app.get("actions", []))):
            return
        argv = self._expand(app["actions"][index]["exec"])
        if argv:
            QProcess.startDetached(argv[0], argv[1:])
            self.used(name)

    @Slot(str)
    def showInStore(self, name: str) -> None:
        if not self._demo:
            QProcess.startDetached("python3", ["/usr/share/huginn-apps/huginn_app.py", "store", "--page", "installed"])

    def _recent_apps(self) -> list:
        """The last six apps opened; on a new account, topped up with the dock's apps so nothing starts empty."""
        by_name = {a["name"]: a for a in self._apps}
        names = [n for n in self._recent if n in by_name]
        names += [n for n in self._pins() if n in by_name and n not in names]
        return [by_name[n] for n in names][:6]
    recent = Property("QVariantList", _recent_apps, notify=changed)


class Tabs(QObject):
    """Huginn's open tabs, for the stack above its dock tile.

    Read-only: Huginn writes its session to its own settings a moment after any tab change, and this
    reads that copy. Private windows and burner tabs are never in it, because Huginn never saves them.
    """
    changed = Signal()

    def __init__(self, apps: Apps, demo: bool):
        super().__init__()
        self._apps, self._demo, self._tabs = apps, demo, []
        if demo:
            self._tabs = [{"title": "[Tab title]", "site": "[site name]", "url": ""} for _ in range(3)]

    @Slot()
    def refresh(self) -> None:
        if self._demo:
            return
        tabs = []
        try:
            data = json.loads(str(QSettings("SafariQt", "SafariQt").value("session", "") or "{}"))
            groups = data.get("groups", [])
            group = groups[min(int(data.get("group", 0)), len(groups) - 1)] if groups else {"tabs": []}
            for tab in group.get("tabs", [])[:8]:
                url = str(tab.get("url", ""))
                web = url.startswith(("http://", "https://"))   # Huginn's own pages (start page, settings) have no site
                tabs.append({"title": str(tab.get("title", "")) or url, "site": (QUrl(url).host() or url) if web else "Huginn",
                             "url": url})
        except (ValueError, TypeError, AttributeError, IndexError):
            tabs = []
        if tabs != self._tabs:
            self._tabs = tabs
            self.changed.emit()

    def _huginn(self) -> str:
        return next((a["exec"] for a in self._apps._apps if a["name"] == "Huginn"), "")

    list = Property("QVariantList", lambda self: self._tabs, notify=changed)
    installed = Property(bool, lambda self: self._demo or bool(self._huginn()), constant=True)

    @Slot(str)
    def open(self, url: str) -> None:
        """Open a page in Huginn ('' = a new tab). Huginn hands it to the window that is already open."""
        parts = shlex.split(self._huginn()) if self._huginn() else []
        if parts:
            QProcess.startDetached(parts[0], parts[1:] + ([url] if url else []))

    @Slot()
    def openPrivate(self) -> None:
        """A new private window (nothing from it is kept, and it never shows in this list)."""
        parts = shlex.split(self._huginn()) if self._huginn() else []
        if parts:
            QProcess.startDetached(parts[0], parts[1:] + ["--private-window"])


class SignInSnapshot(QObject):
    """The sign-in screen's widgets (Settings › Sign-In Screen): every minute, the latest data of the ones you've let
    show before sign-in, and only theirs, kept in ~/.cache/huginn/signin-snapshot.json for the sign-in service to
    read as you (huginn_signin_widgets.py). What last played is noted as it plays; the rest is read from the apps'
    own files, as the desktop's cards are."""

    def __init__(self, live, glance):
        super().__init__()
        self._live, self._glance, self._music = live, glance, {}
        try:
            import huginn_signin_widgets as sw
        except Exception:                                   # noqa: BLE001  (the apps aren't installed: nothing to keep)
            return
        self._sw = sw
        if live is not None:
            live.changed.connect(self._heard)
        QTimer(self, interval=60000, timeout=self.write).start()
        QTimer.singleShot(4000, self.write)

    def _heard(self) -> None:
        for item in [self._live.main] + list(self._live.bubbles) + list(self._live.others):
            if isinstance(item, dict) and item.get("kind") == "playing" and item.get("title"):
                now = {"title": item.get("title", ""), "sub": item.get("sub", ""), "app": item.get("app", ""), "at": int(time.time())}
                if {k: now[k] for k in ("title", "sub")} != {k: self._music.get(k) for k in ("title", "sub")}:
                    self._music = now
                    if any(w["kind"] == "music" and w["before"] for w in self._sw.read_layout(Path.home())):
                        self.write()
                return

    @Slot()
    def write(self) -> None:
        home = Path.home()
        kinds = [w["kind"] for w in self._sw.read_layout(home) if w["before"]]
        try:
            calendar = self._glance._calendar if self._glance is not None else None
            self._sw.write_snapshot(home, self._sw.collect(home, kinds, music=self._music, calendar=calendar))
        except OSError:
            pass


class Glance(QObject):
    """What the desktop's cards show: the weather for your first place in Weather, which apps used the camera,
    microphone, screen or location this week (Privacy Report's notebook), and what's next in Calendar and Reminders.
    Read from those apps' own files every minute; nothing is fetched from the network here."""
    changed = Signal()
    APPS = [Path("/usr/share/huginn-apps"), HERE.parent / "apps"]

    def __init__(self, demo: bool):
        super().__init__()
        self._demo = demo
        self._weather, self._privacy, self._next = {}, {}, []
        self._calendar = None
        self._system, self._photo, self._photo_at, self._cpu_last = {}, "", 0.0, None
        self.settings = None                               # (main sets it) which widgets are on the desktop
        if demo:
            self._weather = {"place": "Reykjavík", "temp": "−1°", "words": "Clear", "high": "4°", "low": "−1°",
                             "days": [{"day": "Thu", "temp": "1°"}, {"day": "Fri", "temp": "3°"}, {"day": "Sat", "temp": "2°"}], "stale": ""}
            self._privacy = {"line": "No app used your camera, microphone, screen or location this week.", "count": 0}
            self._next = [{"title": "Design review", "when": "Tomorrow 09:30 · Calendar"}, {"title": "Build ISO 0.1", "when": "Reminders"}]
            self._system = {"cpu": 12, "memUsed": 6.4, "memTotal": 31.2, "diskFree": 588.0, "diskTotal": 1000.0}
        else:
            for d in self.APPS:
                if (d / "huginn_app.py").exists() and str(d) not in sys.path:
                    sys.path.append(str(d))
            self._timer = QTimer(self, interval=60000, timeout=self.refresh)
            self._timer.start()
            QTimer.singleShot(1500, self.refresh)
            # the System widget: read every few seconds, only while it's on the desktop
            self._sys_timer = QTimer(self, interval=4000, timeout=self._read_system)
            self._sys_timer.start()

    @Slot()
    def refresh(self) -> None:
        data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
        self._weather = self._read_weather(data / "weather.json")
        self._privacy = self._read_privacy()
        self._next = self._read_next()
        if self._shown("photo") and (not self._photo or time.time() - self._photo_at > 3600):
            self._photo, self._photo_at = self._pick_photo(), time.time()
        self.changed.emit()

    def _shown(self, kind: str) -> bool:
        return self.settings is None or kind in (self.settings.widgets or [])

    def _read_system(self) -> None:
        if not self._shown("system"):
            return
        out = {}
        try:
            first = Path("/proc/stat").read_text().splitlines()[0].split()
            v = [int(x) for x in first[1:9]]
            idle, total = v[3] + v[4], sum(v)
            if self._cpu_last and total > self._cpu_last[1]:
                out["cpu"] = round(100 * (1 - (idle - self._cpu_last[0]) / (total - self._cpu_last[1])))
            self._cpu_last = (idle, total)
            mem = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                k, _, rest = line.partition(":")
                if k in ("MemTotal", "MemAvailable") and rest.split():
                    mem[k] = int(rest.split()[0])
            if mem.get("MemTotal"):
                out["memUsed"] = round((mem["MemTotal"] - mem.get("MemAvailable", 0)) / 2**20, 1)
                out["memTotal"] = round(mem["MemTotal"] / 2**20, 1)
            du = shutil.disk_usage(Path.home())
            out["diskFree"], out["diskTotal"] = round(du.free / 1e9, 1), round(du.total / 1e9, 1)
        except (OSError, ValueError, IndexError):
            pass
        if out != self._system:
            self._system = out
            self.changed.emit()

    @staticmethod
    def _pick_photo() -> str:
        """A picture from Pictures (and the folders in it), a different one every hour."""
        import random
        found = []
        pics = Path(os.environ.get("XDG_PICTURES_DIR") or Path.home() / "Pictures")
        for folder in [pics] + [d for d in sorted(pics.glob("*")) if d.is_dir() and not d.name.startswith(".")][:40]:
            try:
                for f in folder.iterdir():
                    if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and f.is_file():
                        found.append(f)
                        if len(found) >= 400:
                            break
            except OSError:
                continue
        return QUrl.fromLocalFile(str(random.choice(found))).toString() if found else ""

    @staticmethod
    def _read_weather(path: Path) -> dict:
        import datetime as dt
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            at = int(saved.get("at", 0))
            place = saved["places"][at]
            fc = saved.get("data", {}).get(str(at)) or {}
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return {}
        try:
            from huginn_more import WMO
        except Exception:                                   # noqa: BLE001 - only the words are missing then
            WMO = {}
        cur, daily = fc.get("current") or {}, fc.get("daily") or {}

        def deg(v):
            return "" if v is None else f"{round(v)}°".replace("-", "−")
        out = {"place": place.get("name", ""), "temp": deg(cur.get("temperature_2m")), "words": WMO.get(cur.get("weather_code"), ("", ""))[0],
               "high": "", "low": "", "days": [], "stale": ""}
        today = dt.date.today().isoformat()
        times = daily.get("time") or []
        for i, day in enumerate(times):
            if day == today:
                out["high"], out["low"] = deg((daily.get("temperature_2m_max") or [None])[i]), deg((daily.get("temperature_2m_min") or [None])[i])
            elif day > today and len(out["days"]) < 3:
                out["days"].append({"day": dt.date.fromisoformat(day).strftime("%a"), "temp": deg((daily.get("temperature_2m_max") or [None] * (i + 1))[i])})
        when = cur.get("time", "")
        try:
            age = dt.datetime.now() - dt.datetime.fromisoformat(when)
            if age.total_seconds() > 6 * 3600:
                out["stale"] = "As of " + dt.datetime.fromisoformat(when).strftime("%a %H:%M")
        except ValueError:
            pass
        return out if out["temp"] else {"place": out["place"]}

    @staticmethod
    def _read_privacy() -> dict:
        import time
        names = {"camera": "camera", "mic": "microphone", "screen": "screen", "location": "location"}
        try:
            from huginn_privacy import read_log
            events = read_log(time.time() - 7 * 86400)
        except Exception:                                   # noqa: BLE001 - no notebook yet
            events = []
        by = {}
        for e in events:
            by.setdefault(e.get("what"), set()).add(e.get("app") or "An app")
        if not by:
            return {"line": "No app used your camera, microphone, screen or location this week.", "count": 0}
        parts = [f"{' and '.join(sorted(a))} used the {names[w]}" for w, a in by.items() if w in names]
        return {"line": "This week: " + "; ".join(parts) + ".", "count": sum(len(a) for a in by.values())}

    def _read_next(self) -> list:
        import datetime as dt
        try:
            if self._calendar is None:
                from huginn_app import Calendar
                self._calendar = Calendar(False)
            rows = self._calendar.upcoming[:2]
        except Exception:                                   # noqa: BLE001 - Calendar not installed or its file unreadable
            return []
        today = dt.date.today()
        out = []
        for e in rows:
            day = dt.date.fromisoformat(e["date"])
            when = "Today" if day == today else "Tomorrow" if day == today + dt.timedelta(days=1) else e.get("when", day.isoformat())
            out.append({"title": e.get("title", ""), "when": when + (" " + e["time"] if e.get("time") else "") + (" · Reminders" if e.get("reminder") else " · Calendar")})
        return out

    weather = Property("QVariantMap", lambda self: self._weather, notify=changed)
    privacy = Property("QVariantMap", lambda self: self._privacy, notify=changed)
    upNext = Property("QVariantList", lambda self: self._next, notify=changed)
    system = Property("QVariantMap", lambda self: self._system, notify=changed)
    photo = Property(str, lambda self: self._photo, notify=changed)


def name_process(name: str) -> None:
    """The name top, Monitor and earlyoom see for this process (its comm), in place of "python3": earlyoom
    (/etc/default/earlyoom) is told to leave the shell, the session daemon and their helpers be."""
    try:
        import ctypes
        ctypes.CDLL(None).prctl(15, name.encode()[:15], 0, 0, 0)          # PR_SET_NAME
    except (OSError, AttributeError):
        pass


def main() -> int:
    name_process("huginn-shell")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--compositor", action="store_true", help="be the compositor too (Huginn's own; the preview session)")
    ap.add_argument("--windowed", action="store_true", help="--compositor in an ordinary window (tests)")
    ap.add_argument("--socket", default="huginn-0", help="--compositor: the Wayland socket apps connect to")
    ap.add_argument("--no-services", action="store_true", help="--compositor: don't start the session's services in it")
    ap.add_argument("--shot", metavar="PNG")
    ap.add_argument("--open", choices=["cc", "launcher", "tabs", "search", "live", "layouts"], default="")
    ap.add_argument("--query", default="", help="with --open search or launcher in a preview: what's typed")
    ap.add_argument("--realm", default="")
    ap.add_argument("--menus", action="store_true", help="preview: start with the app menus open")
    ap.add_argument("--arrive", action="store_true", help="preview: play the arrival after the sign-in screen")
    ap.add_argument("--menu-style", choices=["one", "row"], default="", help="override the saved menu style for this run")
    ap.add_argument("--live", default="", help="preview: what the live island shows (one, call, share, announce, event, none; default: music, a download, a timer)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dark", action="store_true")
    mode.add_argument("--light", action="store_true")
    args = ap.parse_args()
    if os.environ.get("HUGINN_DEBUG_UNSTICK"):
        import faulthandler
        import signal
        faulthandler.register(signal.SIGUSR1, file=open("/tmp/huginn-shell-stacks.txt", "w"), all_threads=True)

    if not os.environ.get("QT_SCALE_FACTOR"):                  # Accessibility: make everything bigger
        try:
            scale = float(json.loads((Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn-shell" / "settings.json")
                                     .read_text(encoding="utf-8")).get("uiScale", "1"))
            if 1.0 < scale <= 2.0:
                os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    app = QGuiApplication(sys.argv)
    app.setDesktopFileName("huginn-shell")
    tokens, settings, theme = make_theme(args.dark, args.light, args.realm, persist=not args.shot)
    if not args.preview:
        write_look(settings.realm)                             # the lock screen follows the realm from the start
        follow_look(settings)                                  # …and everyone else's apps, now and on every change
    if args.menu_style:
        settings.override("menuStyle", args.menu_style)
    apps = Apps(demo=args.preview)
    shown_icons = [icon_theme()]

    def icons_changed():                                      # Settings › Appearance › Icons: every app's tile again
        if icon_theme() != shown_icons[0]:
            shown_icons[0] = icon_theme()
            apps.rescan()
    settings.changed.connect(icons_changed)
    from huginn_island import Live
    tabs, live = Tabs(apps, demo=args.preview), Live(demo=args.preview, scenario=args.live)
    engine = QQmlApplicationEngine()
    engine.addImageProvider("sysicon", SysIcon())
    ctx = engine.rootContext()
    ctx.setContextProperty("Theme", theme)
    ctx.setContextProperty("Apps", apps)
    ctx.setContextProperty("Tabs", tabs)
    ctx.setContextProperty("Live", live)
    from huginn_tray import Tray                          # apps' tray icons (Steam, Discord…), in the control centre
    tray = Tray(apps, demo=args.preview)
    ctx.setContextProperty("Tray", tray)
    glance = Glance(demo=args.preview)
    glance.settings = settings
    if not args.preview:                                  # a photo for the Photo widget as soon as it's put on the desktop
        settings.changed.connect(lambda: QTimer.singleShot(0, glance.refresh) if "photo" in settings.widgets and not glance.photo else None)
    ctx.setContextProperty("Glance", glance)
    if not args.preview:
        signin_snapshot = SignInSnapshot(live, glance)          # noqa: F841  (kept for as long as the shell runs: it writes every minute)
    from huginn_system import System
    status = System(demo=args.preview, apps=apps)              # battery, network, Bluetooth, levels, the app in front
    apps.changed.connect(status._name_windows)                  # an app just installed: its open windows are its now
    ctx.setContextProperty("Status", status)
    from huginn_stacks import Stacks
    stacks = Stacks(demo=args.preview, icon=own_icon)               # the dock's stacks: Downloads, and folders put there
    ctx.setContextProperty("Stacks", stacks)
    from huginn_today import Today
    today = Today(demo=args.preview, settings=settings)                                 # the month, the weather, what's coming (the date, Super+T)
    ctx.setContextProperty("Today", today)
    from huginn_tour import Tour
    tour = Tour(demo=args.preview)                                    # the Welcome tour (first sign-in; what's new after updates)
    ctx.setContextProperty("Tour", tour)
    status.activeChanged.connect(lambda: live.setFront(status.active.get("appId", "")))    # two players: the one not in front wins
    from huginn_search import Search
    search = Search(apps, tabs, demo=args.preview)               # Search everything (Super+Space)
    ctx.setContextProperty("SearchData", search)
    ai = None
    try:                                                              # Huginn AI: Search's "Ask" (Settings › AI)
        for d in (HERE.parent / "apps", Path("/usr/share/huginn-apps")):
            if (d / "huginn_ai.py").exists() and str(d) not in sys.path:
                sys.path.append(str(d))
        import huginn_ai
        ai = huginn_ai.make(bool(args.preview), "search")
    except Exception as err:                                          # noqa: BLE001  (Search works without it)
        print("Huginn AI isn't available:", err, file=sys.stderr)
    ctx.setContextProperty("AI", ai)
    clips = None
    try:                                                              # clipboard history (Super+V)
        import huginn_clipboard
        clips = huginn_clipboard.qt_history()
    except Exception as err:                                          # noqa: BLE001
        print("Clipboard history isn't available:", err, file=sys.stderr)
    ctx.setContextProperty("ClipHistory", clips)
    emoji = None
    try:                                                                # Super+.: its data is read the first time it opens
        import huginn_chars
        emoji = huginn_chars.EmojiPicker()
    except Exception as err:                                          # noqa: BLE001
        print("The emoji picker isn't available:", err, file=sys.stderr)
    ctx.setContextProperty("EmojiPicker", emoji)
    ctx.setContextProperty("Settings", settings)
    from huginn_livecaptions import CaptionFeed
    captions = CaptionFeed(settings, demo=bool(args.preview))           # live captions (Super+Ctrl+L): CaptionBar.qml
    ctx.setContextProperty("Captions", captions)
    ctx.setContextProperty("startOpen", args.open)
    ctx.setContextProperty("startMenus", args.menus)
    ctx.setContextProperty("startQuery", args.query)
    ctx.setContextProperty("Me", me())
    ctx.setContextProperty("arriving", args.arrive or not (args.preview or args.windowed))
    comp = None
    if args.compositor:
        from huginn_compositor import Compositor
        comp = Compositor(args.socket, args.windowed, tokens, apps, services=not args.no_services)
        ctx.setContextProperty("Comp", comp)
        ctx.setContextProperty("liveDirUrl", live_dir())
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / ("Compositor.qml" if args.compositor else "Preview.qml" if args.preview else "Shell.qml"))))
    if not engine.rootObjects():
        return 1
    if not (args.compositor or args.preview or args.shot):
        unstick(engine.rootObjects()[0])
    if args.shot:
        window = engine.rootObjects()[0]

        def grab():
            window.grabWindow().save(args.shot)
            app.quit()
        QTimer.singleShot(int(os.environ.get("HUGINN_SHOT_DELAY", "600")), grab)
    code = app.exec()
    del engine          # tear the QML down before the Python objects it binds to
    return code


if __name__ == "__main__":
    sys.exit(main())
