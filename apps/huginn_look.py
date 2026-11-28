#!/usr/bin/env python3
"""Huginn's look for everyone else's apps: the realm's colours, and dark or light, for Qt apps (Huginn's own Qt
look, qt/: its platform theme and widget style; and a colour scheme for apps from the App Store built on KDE's
libraries) and for GTK apps (Huginn's own GTK 3 theme in the realm's colours, libadwaita's named colours).

The shell calls apply() when it starts and whenever the realm, dark or contrast changes; the colours themselves are
generated from the design tokens at build time (tokens/gen_theme.py) into:

    /usr/share/huginn-os/qt/Huginn<Realm><Mode>.conf           Huginn's Qt look (QT_QPA_PLATFORMTHEME=huginn)
    /usr/share/color-schemes/Huginn<Realm><Mode>.colors
    /usr/share/huginn-os/gtk/Huginn<Realm><Mode>.css           libadwaita (GTK 4)
    /usr/share/huginn-os/gtk/Huginn<Realm><Mode>-gtk3.css      Huginn's GTK 3 theme (/usr/share/themes/Huginn)

Per user it writes ~/.config/huginn/qt.conf (Qt apps' colours, dark or light, icon theme and fonts: open apps
follow it at once), the colour scheme into kdeglobals (for apps built on KDE's libraries, from the App Store),
~/.config/gtk-3.0 and gtk-4.0 (colors.css, a gtk.css that imports it, settings.ini) and GNOME's interface settings,
which GTK reads on Wayland. A gtk.css the user wrote themselves is left alone.

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
DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
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


def _copy_tree(src: Path, dst: Path) -> None:
    """A copy kept up to date (only what's newer is copied)."""
    try:
        for f in src.rglob("*"):
            if f.is_file():
                to = dst / f.relative_to(src)
                if not to.exists() or to.stat().st_mtime < f.stat().st_mtime:
                    to.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, to)
    except OSError:
        pass


def _ours(path: Path) -> bool:
    """A file Huginn may write: not there yet, or written by Huginn (its first line)."""
    try:
        return not path.exists() or path.read_text(encoding="utf-8").startswith(MARK)
    except OSError:
        return False


def _ini(path: Path, values: dict, section: str = "Settings") -> None:
    ini = configparser.ConfigParser(interpolation=None)
    ini.optionxform = str
    try:
        ini.read(path, encoding="utf-8")
    except configparser.Error:
        return
    if not ini.has_section(section):
        ini.add_section(section)
    for k, v in values.items():
        ini.set(section, k, v)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        ini.write(f, space_around_delimiters=False)


QT_FONT = "Inter Variable,10"
KDE_FONTS = {"font": "Inter Variable,10,-1,5,400,0,0,0,0,0,0,0,0,0,0,1", "menuFont": "Inter Variable,10,-1,5,400,0,0,0,0,0,0,0,0,0,0,1",
             "toolBarFont": "Inter Variable,9,-1,5,400,0,0,0,0,0,0,0,0,0,0,1",
             "smallestReadableFont": "Inter Variable,8,-1,5,400,0,0,0,0,0,0,0,0,0,0,1",
             "fixed": "JetBrains Mono,10,-1,5,400,0,0,0,0,0,0,0,0,0,0,1"}
QT_FIXED = "JetBrains Mono,10"
QT_MARK = "; Huginn OS: written by huginn_look.py (Qt apps' look: Huginn's own, qt/). It is written again when the look changes."


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


def write_qt(realm: str = "", dark=None, icons: str = "") -> bool:
    """Qt apps' look (Huginn's platform theme, qt/theme, reads it and open apps follow it at once): the realm's
    colours in dark or light, the icon theme and Huginn's fonts, in ~/.config/huginn/qt.conf. Menu bars go to the
    top bar unless [Menus] top_bar=false was set there by hand (that stays). True when it changed."""
    if not realm or dark is None:
        mine_realm, mine_dark, _ = read_settings()
        realm, dark = realm or mine_realm, mine_dark if dark is None else dark
    path = CONFIG / "huginn" / "qt.conf"
    colours = ""
    try:
        text = (SHARE / "huginn-os" / "qt" / f"{name_for(realm, dark)}.conf").read_text(encoding="utf-8")
        colours = text[text.index("[Colours]"):].strip() + "\n"
    except (OSError, ValueError):
        pass                                                    # (the theme's own: Aurora dark)
    top_bar = "true"
    try:
        old = path.read_text(encoding="utf-8")
        if "[Menus]" in old and "top_bar=false" in old.replace(" ", "").split("[Menus]", 1)[1].split("[", 1)[0]:
            top_bar = "false"
    except OSError:
        pass
    text = (f"{QT_MARK}\n[Look]\nscheme={'dark' if dark else 'light'}\nicons={icons or icon_theme()}\n"
            f"font={QT_FONT}\nfixed={QT_FIXED}\n\n[Menus]\ntop_bar={top_bar}\n\n{colours}")
    return _write(path, text)


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
    # App Store Qt apps (KDE's Flatpak runtime) see only this file, not /etc/xdg's: Huginn's widget style (put where
    # they find it: build.sh, the org.kde.KStyle.Huginn extension) and Huginn's fonts, unless fonts were chosen here
    for key, font in KDE_FONTS.items():
        if not dst.get("General", key, fallback=""):
            dst.set("General", key, font)
    if not dst.has_section("KDE"):
        dst.add_section("KDE")
    dst.set("KDE", "widgetStyle", "Huginn")
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


OLD_POINTERS = ("", "breeze_cursors", "Breeze_Light", "Oxygen_Black", "Oxygen_White", "Oxygen_Blue", "Oxygen_Yellow", "Oxygen_Zion")


def _huginn_pointers() -> None:
    """Huginn's own pointers, once, for anyone still on KDE's (Breeze's were the default, so they count as never
    chosen; Oxygen's only once they're gone): the compositor and Qt read kcminputrc, GTK its settings, X11 apps
    ~/.icons/default. Any other theme chosen in Settings stays."""
    kin = CONFIG / "kcminputrc"
    ini = configparser.ConfigParser(interpolation=None, strict=False)
    ini.optionxform = str
    try:
        ini.read(kin, encoding="utf-8")
    except configparser.Error:
        return
    now = ini.get("Mouse", "cursorTheme", fallback="")
    if now not in OLD_POINTERS or not (SHARE / "icons" / "Huginn" / "cursors" / "default").exists():
        return
    if now.startswith("Oxygen") and (SHARE / "icons" / now / "cursors").is_dir():
        return                                                  # (still there and never the default: a choice)
    _ini(kin, {"cursorTheme": "Huginn"}, "Mouse")
    for version in ("gtk-3.0", "gtk-4.0"):
        if (CONFIG / version / "settings.ini").exists():
            _ini(CONFIG / version / "settings.ini", {"gtk-cursor-theme-name": "Huginn"})
    _run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", "Huginn"])
    default = Path.home() / ".icons" / "default" / "index.theme"
    try:
        if default.exists() and any(f"Inherits={old}" in default.read_text(encoding="utf-8") for old in OLD_POINTERS if old):
            default.write_text("[Icon Theme]\nInherits=Huginn\n", encoding="utf-8")
    except OSError:
        pass


POINTER_THEMES = {"aurora": "Huginn", "bifrost": "Huginn-Bifrost", "muspelheim": "Huginn-Muspelheim", "niflheim": "Huginn-Niflheim"}
# the same pointers with an ordinary outline and no glow (Settings › Appearance › Pointer: Huginn Plain)
PLAIN_POINTER_THEMES = {realm: theme + "-Plain" for realm, theme in POINTER_THEMES.items()}


def pointer_theme_for(realm: str, plain: bool = False) -> str:
    """Huginn's pointers in a realm's colours (Aurora's are "Huginn"; plain ones "Huginn-Plain"…), when they're there."""
    for want in ((PLAIN_POINTER_THEMES.get(realm, "Huginn-Plain"), "Huginn-Plain") if plain else ()) + (POINTER_THEMES.get(realm, "Huginn"),):
        if (SHARE / "icons" / want / "cursors" / "default").exists():
            return want
    return "Huginn"


def is_huginn_pointers(theme: str) -> bool:
    return theme == "Huginn" or theme in POINTER_THEMES.values() or theme in PLAIN_POINTER_THEMES.values()


def is_plain_pointers(theme: str) -> bool:
    return theme in PLAIN_POINTER_THEMES.values()


def _realm_pointers(realm: str) -> bool:
    """Huginn's pointers follow the realm: when the pointer theme is Huginn's (any realm's), it becomes this realm's
    (the compositor, Qt, GTK and X11 apps' default), plain ones staying plain. Any other theme chosen in Settings stays.
    True when it changed."""
    kin = CONFIG / "kcminputrc"
    ini = configparser.ConfigParser(interpolation=None, strict=False)
    ini.optionxform = str
    try:
        ini.read(kin, encoding="utf-8")
    except configparser.Error:
        return False
    now = ini.get("Mouse", "cursorTheme", fallback="Huginn") or "Huginn"
    want = pointer_theme_for(realm, is_plain_pointers(now))
    if not is_huginn_pointers(now) or now == want:
        return False
    _ini(kin, {"cursorTheme": want}, "Mouse")
    for version in ("gtk-3.0", "gtk-4.0"):
        if (CONFIG / version / "settings.ini").exists():
            _ini(CONFIG / version / "settings.ini", {"gtk-cursor-theme-name": want})
    _run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", want])
    default = Path.home() / ".icons" / "default" / "index.theme"
    try:
        if default.exists() and any(f"Inherits={t}\n" in default.read_text(encoding="utf-8") + "\n"
                                     for t in (*POINTER_THEMES.values(), *PLAIN_POINTER_THEMES.values())):
            default.write_text(f"[Icon Theme]\nInherits={want}\n", encoding="utf-8")
    except OSError:
        pass
    _run(["gdbus", "call", "--session", "--dest", "org.huginn.Compositor", "--object-path", "/org/huginn/Compositor",
          "--method", "org.huginn.Compositor.ReloadAccess"])          # (Huginn's compositor draws the new ones at once)
    return True


def apply(realm: str, dark: bool, contrast: bool = False, force: bool = False) -> bool:
    """Put the realm's look in place for this user. Returns False when it was already in place."""
    name = name_for(realm, dark)
    stamp = f"{name} contrast={contrast} gtk=huginn qt=huginn kstyle=huginn pointers=huginn"  # (a new part of the look: in place once more)
    changed = write_qt(realm, dark)                             # (each time: cheap, and only written when it changed)
    changed = _realm_pointers(realm) or changed
    if not force:
        try:
            if STATE.read_text(encoding="utf-8").strip() == stamp:
                return changed
        except OSError:
            pass
    if (SHARE / "color-schemes" / f"{name}.colors").exists():
        # (for apps built on KDE's libraries, from the App Store: they read their colours from kdeglobals, and are told
        # it changed the way they listen for it, so the ones open take the new colours at once)
        _apply_colours(SHARE / "color-schemes" / f"{name}.colors", name)
        for kind in ("0", "2"):                                 # the palette; the style
            _run(["dbus-send", "--session", "--type=signal", "/KGlobalSettings", "org.kde.KGlobalSettings.notifyChange",
                  f"int32:{kind}", "int32:0"])
    # GTK 3: Huginn's own theme (Adwaita's shapes) in the realm's colours; GTK 4: libadwaita's named colours
    _copy_tree(SHARE / "themes" / "Huginn", DATA / "themes" / "Huginn")   # (App Store apps see this copy, not /usr/share)
    gtk = SHARE / "huginn-os" / "gtk"
    three, adw = gtk / f"{name}-gtk3.css", gtk / f"{name}.css"
    theme = "HighContrast" if contrast else "Huginn"
    for version, source, named in (("gtk-3.0", three, theme), ("gtk-4.0", adw, "HighContrast" if contrast else "Default")):
        if not source.exists():
            continue
        folder = CONFIG / version
        _write(folder / "colors.css", source.read_text(encoding="utf-8"))
        if _ours(folder / "gtk.css"):
            _write(folder / "gtk.css", f"{MARK}\n@import 'colors.css';\n")
        _ini(folder / "settings.ini", {"gtk-theme-name": named, "gtk-application-prefer-dark-theme": "true" if dark else "false",
                                       "gtk-font-name": "Inter Variable 10"})
    _huginn_pointers()
    _realm_pointers(realm)
    # GTK on Wayland reads GNOME's interface settings (dconf) rather than settings.ini
    iface = "org.gnome.desktop.interface"
    _run(["gsettings", "set", iface, "gtk-theme", theme])
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
