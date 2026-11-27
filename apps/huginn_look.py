#!/usr/bin/env python3
"""Huginn's look for everyone else's apps: the realm's colours, and dark or light, for Qt and KDE apps (a Kvantum
widget style and a KDE colour scheme) and for GTK apps (Breeze-GTK with Huginn's colours, libadwaita's named colours).

The shell calls apply() when it starts and whenever the realm, dark or contrast changes; the themes themselves are
generated from the design tokens at build time (tokens/gen_theme.py) into:

    /usr/share/Kvantum/Huginn<Realm><Mode>/          Qt widget style (kdeglobals: widgetStyle=kvantum)
    /usr/share/color-schemes/Huginn<Realm><Mode>.colors
    /usr/share/huginn-os/gtk/Huginn<Realm><Mode>.css           libadwaita
    /usr/share/huginn-os/gtk/Huginn<Realm><Mode>-breeze.css    Breeze-GTK

Per user it writes ~/.config/Kvantum/kvantum.kvconfig, ~/.config/qt6ct/qt6ct.conf (Qt apps' platform theme: the
Kvantum style, the icon theme, Huginn's fonts, Open and Save through the portal), the colour scheme into kdeglobals
(for apps built on KDE's libraries, from the App Store), ~/.config/gtk-3.0 and gtk-4.0 (colors.css, a gtk.css that
imports it, settings.ini) and GNOME's interface settings, which GTK reads on Wayland. A gtk.css the user wrote
themselves is left alone.

    python3 huginn_look.py                 apply the look from ~/.config/huginn-shell/settings.json
    python3 huginn_look.py aurora --dark   apply a given realm
"""
import argparse
import configparser
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "huginn" / "look"
SHARE = Path(os.environ.get("HUGINN_LOOK_SHARE") or "/usr/share")
MARK = "/* Huginn OS: written by huginn_look.py. Delete this line to keep your own changes. */"


def name_for(realm: str, dark: bool) -> str:
    return f"Huginn{realm.title()}{'Dark' if dark else 'Light'}"


def read_settings() -> tuple:
    try:
        s = json.loads((CONFIG / "huginn-shell" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    return s.get("realm", "aurora"), s.get("dark", "true") == "true", s.get("contrast", "false") == "true"


def _write(path: Path, text: str) -> bool:
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".huginn-tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        return False


def _ours(path: Path) -> bool:
    """A file Huginn may write: not there yet, or written by Huginn (its first line)."""
    try:
        return not path.exists() or path.read_text(encoding="utf-8").startswith(MARK)
    except OSError:
        return False


def _ini(path: Path, values: dict) -> None:
    ini = configparser.ConfigParser(interpolation=None)
    ini.optionxform = str
    try:
        ini.read(path, encoding="utf-8")
    except configparser.Error:
        return
    if not ini.has_section("Settings"):
        ini.add_section("Settings")
    for k, v in values.items():
        ini.set("Settings", k, v)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        ini.write(f, space_around_delimiters=False)


QT_FONT = '"Inter Variable,10,-1,5,400,0,0,0,0,0,0,0,0,0,0,1"'
QT_FIXED = '"JetBrains Mono,10,-1,5,400,0,0,0,0,0,0,0,0,0,0,1"'


def icon_theme() -> str:
    """The icon theme chosen (Settings › Appearance keeps it in kdeglobals' [Icons], which apps built on KDE's
    libraries also read), else the system's, else Huginn's."""
    for f in (CONFIG / "kdeglobals", Path("/etc/xdg/kdeglobals")):
        try:
            in_icons = False
            for line in f.read_text(encoding="utf-8").splitlines():
                t = line.strip()
                if t.startswith("["):
                    in_icons = t == "[Icons]"
                elif in_icons and t.startswith("Theme="):
                    return t.split("=", 1)[1].strip() or "Huginn"
        except OSError:
            continue
    return "Huginn"


def write_qt6ct(icons: str = "") -> bool:
    """Qt apps' settings (qt6ct, the platform theme the session sets): Kvantum, the icon theme, Huginn's fonts, and
    Open and Save through the desktop portal (Huginn's own). The rest of the file, anything a person set in qt6ct
    themselves, stays. True when it changed."""
    path = CONFIG / "qt6ct" / "qt6ct.conf"
    ini = configparser.ConfigParser(interpolation=None, strict=False)
    ini.optionxform = str
    try:
        ini.read(path, encoding="utf-8")
    except configparser.Error:
        ini = configparser.ConfigParser(interpolation=None)
        ini.optionxform = str
    want = {"Appearance": {"style": "kvantum", "icon_theme": icons or icon_theme(), "standard_dialogs": "xdgdesktopportal",
                           "custom_palette": "false"},
            "Fonts": {"general": QT_FONT, "fixed": QT_FIXED}}
    before = {sec: dict(ini.items(sec)) for sec in ini.sections()}
    for section, values in want.items():
        if not ini.has_section(section):
            ini.add_section(section)
        for k, v in values.items():
            ini.set(section, k, v)
    if {sec: dict(ini.items(sec)) for sec in ini.sections()} == before:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name("qt6ct.conf.huginn-tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            ini.write(fh, space_around_delimiters=False)
        tmp.replace(path)
        return True
    except OSError:
        return False


def _apply_colours(scheme: Path, name: str) -> None:
    """A KDE colour scheme into ~/.config/kdeglobals, as plasma-apply-colorscheme does: its [Colors:*] groups (and
    the rest it carries) replace those in kdeglobals, which Qt apps read through KDE's platform theme."""
    import configparser

    def ini():
        c = configparser.ConfigParser(strict=False, interpolation=None)
        c.optionxform = str
        return c
    src, dst = ini(), ini()
    try:
        src.read(scheme, encoding="utf-8")
        dst.read(CONFIG / "kdeglobals", encoding="utf-8")
    except (configparser.Error, OSError):
        return
    for section in src.sections():
        if section == "ColorEffects:Disabled" or section.startswith(("Colors:", "ColorEffects:", "WM")):
            if dst.has_section(section):
                dst.remove_section(section)
            dst.add_section(section)
            for k, v in src.items(section):
                dst.set(section, k, v)
    if not dst.has_section("General"):
        dst.add_section("General")
    dst.set("General", "ColorScheme", name)
    try:
        (CONFIG).mkdir(parents=True, exist_ok=True)
        with open(CONFIG / "kdeglobals", "w", encoding="utf-8") as fh:
            dst.write(fh, space_around_delimiters=False)
    except OSError:
        pass


def _run(cmd: list) -> None:
    if shutil.which(cmd[0]):
        env = dict(os.environ)
        if not env.get("WAYLAND_DISPLAY") and not env.get("DISPLAY"):
            env["QT_QPA_PLATFORM"] = "offscreen"                 # (KDE's tools want a screen, even with nothing to show)
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, env=env)
        except (OSError, subprocess.SubprocessError):
            pass


def apply(realm: str, dark: bool, contrast: bool = False, force: bool = False) -> bool:
    """Put the realm's look in place for this user. Returns False when it was already in place."""
    name = name_for(realm, dark)
    stamp = f"{name} contrast={contrast}"
    changed = write_qt6ct()                                     # (each time: systems from before qt6ct need it once)
    if not force:
        try:
            if STATE.read_text(encoding="utf-8").strip() == stamp:
                return changed
        except OSError:
            pass
    # Qt apps: the widget style (Kvantum) and its colours (qt6ct's settings, above, name the style)
    if (SHARE / "Kvantum" / name).is_dir():
        _write(CONFIG / "Kvantum" / "kvantum.kvconfig", f"[General]\ntheme={name}\n")
        # A copy beside it: apps from the App Store (Flatpak) can't see /usr/share, but may read ~/.config/Kvantum
        # (a system-wide Flatpak override lets them), so they wear the same style.
        try:
            mine = CONFIG / "Kvantum" / name
            mine.mkdir(parents=True, exist_ok=True)
            for f in (SHARE / "Kvantum" / name).iterdir():
                if f.is_file() and (not (mine / f.name).exists() or (mine / f.name).stat().st_mtime < f.stat().st_mtime):
                    shutil.copy2(f, mine / f.name)
        except OSError:
            pass
    if (SHARE / "color-schemes" / f"{name}.colors").exists():
        # (for apps built on KDE's libraries, from the App Store: they read their colours from kdeglobals, and are told
        # it changed the way they listen for it, so the ones open take the new colours at once)
        _apply_colours(SHARE / "color-schemes" / f"{name}.colors", name)
        for kind in ("0", "2"):                                 # the palette; the style
            _run(["dbus-send", "--session", "--type=signal", "/KGlobalSettings", "org.kde.KGlobalSettings.notifyChange",
                  f"int32:{kind}", "int32:0"])
    # GTK 3 and 4: Breeze-GTK in Huginn's colours; libadwaita's named colours for GTK 4
    gtk = SHARE / "huginn-os" / "gtk"
    breeze = gtk / f"{name}-breeze.css"
    adw = gtk / f"{name}.css"
    if breeze.exists():
        colours = breeze.read_text(encoding="utf-8")
        adw_text = adw.read_text(encoding="utf-8") if adw.exists() else ""
        for version, text in (("gtk-3.0", colours), ("gtk-4.0", colours + "\n" + adw_text)):
            folder = CONFIG / version
            _write(folder / "colors.css", text)
            if _ours(folder / "gtk.css"):
                _write(folder / "gtk.css", f"{MARK}\n@import 'colors.css';\n")
            _ini(folder / "settings.ini", {"gtk-theme-name": "HighContrast" if contrast else "Breeze",
                                           "gtk-application-prefer-dark-theme": "true" if dark else "false",
                                           "gtk-font-name": "Inter Variable 10"})
    # GTK on Wayland reads GNOME's interface settings (dconf) rather than settings.ini
    iface = "org.gnome.desktop.interface"
    _run(["gsettings", "set", iface, "gtk-theme", "HighContrast" if contrast else "Breeze"])
    _run(["gsettings", "set", iface, "color-scheme", "prefer-dark" if dark else "prefer-light"])
    _run(["gsettings", "set", iface, "font-name", "Inter Variable 10"])
    _write(STATE, stamp + "\n")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("realm", nargs="?", help="aurora, bifrost, muspelheim or niflheim (default: the user's)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dark", action="store_true")
    mode.add_argument("--light", action="store_true")
    ap.add_argument("--force", action="store_true", help="even if it is in place already")
    args = ap.parse_args()
    realm, dark, contrast = read_settings()
    if args.realm:
        realm = args.realm
    if args.dark or args.light:
        dark = args.dark
    changed = apply(realm, dark, contrast, force=args.force)
    print(("Applied " if changed else "Already in place: ") + name_for(realm, dark))
    return 0


if __name__ == "__main__":
    sys.exit(main())
