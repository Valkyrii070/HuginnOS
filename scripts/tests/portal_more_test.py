#!/usr/bin/env python3
"""What took KDE's place for apps: Huginn's portal keeping the screen on and starting App Store apps at sign-in
(apps/huginn_portal_more.py), qt6ct's settings from Huginn's look (apps/huginn_look.py), and the control centre's
night light (shell/huginn_system.py), on a D-Bus of its own with a stand-in for the session daemon.

    portal_more_test.py <kit root>        (not as root; needs dbus-daemon)
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace as NS

if os.geteuid() == 0:
    sys.exit("not as root")
KIT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(KIT / "apps"))
sys.path.insert(0, str(KIT / "shell"))
home = Path(tempfile.mkdtemp(prefix="portal-more-"))
os.environ["HOME"] = str(home)
os.environ["XDG_CONFIG_HOME"] = str(home / ".config")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL", name, detail)


bus = subprocess.run(["dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"], capture_output=True, text=True)
address, pid = bus.stdout.split()[:2]
os.environ["DBUS_SESSION_BUS_ADDRESS"] = address
from gi.repository import Gio, GLib  # noqa: E402
import huginn_portal_more as pm  # noqa: E402

# a stand-in for the session daemon's org.freedesktop.ScreenSaver
saver = Gio.bus_get_sync(Gio.BusType.SESSION, None)
held, cookies = set(), [100]
SAVER_XML = """<node><interface name="org.freedesktop.ScreenSaver">
  <method name="Inhibit"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="u" direction="out"/></method>
  <method name="UnInhibit"><arg type="u" direction="in"/></method></interface></node>"""


def saver_call(conn, sender, path, iface, method, params, inv):
    if method == "Inhibit":
        cookies[0] += 1
        held.add(cookies[0])
        inv.return_value(GLib.Variant("(u)", (cookies[0],)))
    else:
        held.discard(params.unpack()[0])
        inv.return_value(None)


saver.register_object("/org/freedesktop/ScreenSaver", Gio.DBusNodeInfo.new_for_xml(SAVER_XML).interfaces[0], saver_call, None, None)
saver.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName", GLib.Variant("(su)", ("org.freedesktop.ScreenSaver", 4)),
                GLib.VariantType("(u)"), 0, 3000, None)

# the portal side, on a connection of its own
mine = Gio.DBusConnection.new_for_address_sync(address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
keeper = pm.Keeper(mine, autostart=home / ".config/autostart")
portal_name = mine.get_unique_name()
app = Gio.DBusConnection.new_for_address_sync(address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
ctx = GLib.MainContext.default()


def call(iface, method, args, reply=None):
    """As xdg-desktop-portal would, from the side; the loop turns while it waits."""
    box = {}
    app.call(portal_name, "/org/freedesktop/portal/desktop", "org.freedesktop.impl.portal." + iface, method, args,
             GLib.VariantType(reply) if reply else None, 0, 5000, None, lambda c, r: box.setdefault("r", r))
    end = time.monotonic() + 5
    while "r" not in box and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.005)
    try:
        got = app.call_finish(box["r"])
        return got.unpack() if got is not None else ()
    except GLib.Error as err:
        return err


def spin(sec=0.2):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.005)


# Inhibit: the screen kept on while asked, let go when the request closes
handle = "/org/freedesktop/portal/desktop/request/1_2/t1"
got = call("Inhibit", "Inhibit", GLib.Variant("(ossua{sv})", (handle, "org.example.Player", "", pm.IDLE, {"reason": GLib.Variant("s", "Playing a film")})))
spin()
check("keeping the screen on: the session daemon is asked", got == () and len(held) == 1 and keeper.busy(), (got, held))
box = {}
app.call(portal_name, handle, "org.freedesktop.impl.portal.Request", "Close", None, None, 0, 3000, None, lambda c, r: box.setdefault("r", r))
spin(0.4)
check("…and let go when the app is done", not held and not keeper.busy(), (held, keeper.held))
got = call("Inhibit", "Inhibit", GLib.Variant("(ossua{sv})", ("/org/freedesktop/portal/desktop/request/1_2/t2", "org.example.Mail", "", pm.LOGOUT, {})))
check("asking only about signing out: an answer, nothing held on the screen", got == () and not held, (got, held))
keeper.release("/org/freedesktop/portal/desktop/request/1_2/t2")
got = call("Inhibit", "CreateMonitor", GLib.Variant("(ooss)", ("/r/1", "/org/freedesktop/portal/desktop/session/1_2/s1", "org.example.Chat", "")), "(u)")
check("a session monitor: given", got == (0,) and keeper.busy(), got)
keeper._end("/org/freedesktop/portal/desktop/session/1_2/s1")

# Background: starting at sign-in
got = call("Background", "EnableAutostart", GLib.Variant("(sbasu)", ("org.example.Chat", True, ["chat", "--hidden"], 0)), "(b)")
entry = home / ".config/autostart/org.example.Chat.desktop"
text = entry.read_text() if entry.exists() else ""
check("starting at sign-in: an entry that runs the app from its sandbox", got == (True,) and "Exec=flatpak run --command=chat org.example.Chat --hidden" in text
      and "X-Flatpak=org.example.Chat" in text, (got, text))
got = call("Background", "EnableAutostart", GLib.Variant("(sbasu)", ("org.example.Chat", False, [], 0)), "(b)")
check("…and taken away again", got == (True,) and not entry.exists())
for bad in ("../../.bashrc", "notanid", "org.example.x\nExec=evil"):
    got = call("Background", "EnableAutostart", GLib.Variant("(sbasu)", (bad, True, ["x"], 0)), "(b)")
    check(f"…not for an odd app id ({bad[:12]!r})", got == (False,) and not list((home / ".config/autostart").glob("*")), got)
got = call("Background", "EnableAutostart", GLib.Variant("(sbasu)", ("org.example.Evil", True, ["x\nExec=rm -rf ~"], 0)), "(b)")
check("…nor a command with a line in it", got == (False,))
(home / ".config/autostart/org.example.Own.desktop").write_text("[Desktop Entry]\nExec=own\n")
call("Background", "EnableAutostart", GLib.Variant("(sbasu)", ("org.example.Own", False, [], 0)), "(b)")
check("…and an entry the person made themselves is left alone", (home / ".config/autostart/org.example.Own.desktop").exists())
got = call("Background", "NotifyBackground", GLib.Variant("(oss)", ("/r/2", "org.example.Chat", "Chat")), "(ua{sv})")
check("running on with no window: allowed", got == (0, {"result": 1}), got)

# qt6ct's settings from Huginn's look
import huginn_look as hl  # noqa: E402
(home / ".config/kdeglobals").write_text("[Icons]\nTheme=Papirus\n")
qt = home / ".config/qt6ct/qt6ct.conf"
qt.parent.mkdir(parents=True)
qt.write_text("[Interface]\nwheel_scroll_lines=7\n")
check("qt6ct: written once", hl.write_qt6ct() and not hl.write_qt6ct())
text = qt.read_text()
check("…Kvantum, the chosen icon theme, Open and Save through the portal, Huginn's fonts (quoted: they have commas)",
      "style=kvantum" in text and "icon_theme=Papirus" in text and "standard_dialogs=xdgdesktopportal" in text
      and 'general="Inter Variable,10,' in text, text)
check("…and what the person set in qt6ct stays", "wheel_scroll_lines=7" in text)
check("…a new icon theme reaches it", hl.write_qt6ct("Huginn") and "icon_theme=Huginn" in qt.read_text())

# GTK apps: Huginn's own GTK 3 theme in the realm's colours, in place of Breeze-GTK
share = home / "share"
(share / "huginn-os/gtk").mkdir(parents=True)
subprocess.run([sys.executable, str(KIT / "tokens/gen_theme.py"), str(KIT / "tokens/tokens.json"), str(home / "gen")], capture_output=True)
for f in (home / "gen/gtk").glob("*.css"):
    (share / "huginn-os/gtk" / f.name).write_text(f.read_text())
theme_src = KIT / "config/overlay/usr/share/themes/Huginn"
(share / "themes").mkdir()
os.symlink(theme_src, share / "themes/Huginn")
hl.SHARE, hl.DATA = share, home / ".local/share"
hl.STATE = home / ".local/state/huginn/look"
hl._run = lambda cmd: None
check("the look is put in place", hl.apply("muspelheim", True, False))
g3, g4 = home / ".config/gtk-3.0", home / ".config/gtk-4.0"
check("GTK 3: Huginn's theme, the realm's colours where they win", "gtk-theme-name=Huginn" in (g3 / "settings.ini").read_text()
      and "@define-color huginn_accent #FF8C50;" in (g3 / "colors.css").read_text() and "@import 'colors.css';" in (g3 / "gtk.css").read_text(),
      ((g3 / "settings.ini").read_text(), (g3 / "colors.css").read_text()[:200]))
check("GTK 4: GTK's own theme, libadwaita's colours, nothing of Breeze's", "gtk-theme-name=Default" in (g4 / "settings.ini").read_text()
      and "accent_bg_color" in (g4 / "colors.css").read_text() and "_breeze" not in (g4 / "colors.css").read_text())
check("…and the theme copied where App Store apps can see it", (home / ".local/share/themes/Huginn/gtk-3.0/huginn.css").is_file())
check("the theme's own files: both modes, Adwaita's drawing underneath",
      all((theme_src / "gtk-3.0" / f).is_file() for f in ("gtk.css", "gtk-dark.css", "huginn.css", "colors-light.css", "colors-dark.css"))
      and "gtk-contained-dark.css" in (theme_src / "gtk-3.0/gtk-dark.css").read_text())

# the control centre's night light: Huginn's own (the session daemon follows kwinrc's [NightColor])
import huginn_system as hsys  # noqa: E402
rc = home / ".config/kwinrc"
rc.write_text("[Other]\nx=1\n")
fake = NS(NIGHT=rc, _demo=False, _night={}, changed=NS(emit=lambda: None))
hsys.System.setNightLight(fake, True)
hsys.System._read_night(fake)
check("night light on: written where the session daemon reads it", "[NightColor]\nActive=true" in rc.read_text() and fake._night == {"available": True, "on": True},
      (rc.read_text(), fake._night))
hsys.System.setNightLight(fake, False)
hsys.System._read_night(fake)
check("…and off; the rest of the file as it was", rc.read_text().count("Active=") == 1 and "Active=false" in rc.read_text() and "[Other]\nx=1" in rc.read_text()
      and fake._night["on"] is False, rc.read_text())

subprocess.run(["kill", pid])
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
