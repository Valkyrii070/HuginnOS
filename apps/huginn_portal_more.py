"""Two more questions Huginn's desktop portal answers for apps (with huginn_portal.py, which registers them):

    Inhibit      keep the screen on, or the computer from sleeping, while an app asks (a video, a call, a game, a
                 download): the screen through Huginn's session daemon (org.freedesktop.ScreenSaver, as games and
                 players ask it directly), sleep through logind (a "sleep" inhibitor held until the app lets go)
    Background   an app from the App Store asking to start when you sign in (autostart): a start-up entry in
                 ~/.config/autostart that Settings › Startup Apps lists like any other, and running on with no
                 window, which is allowed

These were KDE's portal's until KDE left the image; the questions the portal still can't answer itself (printing,
email, your name and picture) go to GTK's portal (huginn-portals.conf).
"""
import os
import re
import shlex
from pathlib import Path

from gi.repository import Gio, GLib

XML = """<node>
<interface name="org.freedesktop.impl.portal.Inhibit">
  <method name="Inhibit"><arg type="o" name="handle" direction="in"/><arg type="s" name="app_id" direction="in"/><arg type="s" name="window" direction="in"/>
    <arg type="u" name="flags" direction="in"/><arg type="a{sv}" name="options" direction="in"/></method>
  <method name="CreateMonitor"><arg type="o" name="handle" direction="in"/><arg type="o" name="session_handle" direction="in"/><arg type="s" name="app_id" direction="in"/>
    <arg type="s" name="window" direction="in"/><arg type="u" name="response" direction="out"/></method>
  <method name="QueryEndResponse"><arg type="o" name="session_handle" direction="in"/></method>
  <signal name="StateChanged"><arg type="o" name="session_handle"/><arg type="a{sv}" name="state"/></signal>
  <property name="version" type="u" access="read"/>
</interface>
<interface name="org.freedesktop.impl.portal.Background">
  <method name="GetAppState"><arg type="a{sv}" name="apps" direction="out"/></method>
  <method name="NotifyBackground"><arg type="o" name="handle" direction="in"/><arg type="s" name="app_id" direction="in"/><arg type="s" name="name" direction="in"/>
    <arg type="u" name="response" direction="out"/><arg type="a{sv}" name="results" direction="out"/></method>
  <method name="EnableAutostart"><arg type="s" name="app_id" direction="in"/><arg type="b" name="enable" direction="in"/><arg type="as" name="commandline" direction="in"/>
    <arg type="u" name="flags" direction="in"/><arg type="b" name="result" direction="out"/></method>
  <signal name="RunningApplicationsChanged"/>
</interface>
</node>"""
CLOSABLE = """<node><interface name="org.freedesktop.impl.portal.Request"><method name="Close"/></interface>
<interface name="org.freedesktop.impl.portal.Session"><method name="Close"/><signal name="Closed"/>
  <property name="version" type="u" access="read"/></interface></node>"""
LOGOUT, SWITCH, SUSPEND, IDLE = 1, 2, 4, 8
APP_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)+")
AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart"


def autostart_entry(app_id: str, commandline: list, dbus: bool = False) -> str:
    """The start-up entry for a sandboxed app (Flatpak), as `flatpak run` starts it."""
    cmd = ["flatpak", "run", f"--command={commandline[0]}", app_id, *commandline[1:]] if commandline else ["flatpak", "run", app_id]
    lines = ["[Desktop Entry]", "Type=Application", f"Name={app_id}", f"Exec={shlex.join(cmd)}", f"X-Flatpak={app_id}",
             "X-Huginn-Asked-By=the app (Background portal)"]
    if dbus:
        lines.append("DBusActivatable=true")
    return "\n".join(lines) + "\n"


class Keeper:
    """Inhibit and Background, answered at once (no window): registered beside the file chooser's interfaces."""

    def __init__(self, conn, autostart: Path = AUTOSTART, screensaver: str = "org.freedesktop.ScreenSaver"):
        self.conn, self.autostart, self.screensaver = conn, autostart, screensaver
        self.held = {}                                   # handle: {"cookie": int|None, "fd": int|None, "reg": id}
        self.sessions = {}                               # session handle: registration id
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        for iface in node.interfaces:
            conn.register_object("/org/freedesktop/portal/desktop", iface, self._call, self._get, None)

    def busy(self) -> bool:
        """Something is being kept on (the portal mustn't leave meanwhile)."""
        return bool(self.held or self.sessions)

    def _get(self, conn, sender, path, iface, prop):
        return GLib.Variant("u", 3 if iface.endswith("Inhibit") else 1) if prop == "version" else None

    def _call(self, conn, sender, path, iface, method, params, inv):
        args = params.unpack()
        try:
            if method == "Inhibit":
                handle, app_id, _window, flags, options = args
                self.inhibit(handle, app_id, flags, str(options.get("reason", "")) if isinstance(options, dict) else "")
                inv.return_value(None)
            elif method == "CreateMonitor":
                handle, session, _app_id, _window = args
                inv.return_value(GLib.Variant("(u)", (self.monitor(session),)))
            elif method == "QueryEndResponse":
                inv.return_value(None)
            elif method == "GetAppState":
                inv.return_value(GLib.Variant("(a{sv})", ({},)))
            elif method == "NotifyBackground":
                inv.return_value(GLib.Variant("(ua{sv})", (0, {"result": GLib.Variant("u", 1)})))    # allowed
            elif method == "EnableAutostart":
                app_id, enable, commandline, flags = args
                inv.return_value(GLib.Variant("(b)", (self.enable_autostart(app_id, enable, list(commandline), flags),)))
            else:
                inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
        except Exception as err:                         # noqa: BLE001  (an answer, always: the portal waits for one)
            inv.return_dbus_error("org.freedesktop.DBus.Error.Failed", str(err)[:200])

    # ............................................................................................ keeping things on
    def inhibit(self, handle: str, app_id: str, flags: int, reason: str) -> None:
        who = app_id or "An app"
        why = reason or "asked to"
        got = {"cookie": None, "fd": None, "reg": None}
        if flags & IDLE:                                 # (asked without waiting: the portal answers at once)
            self.conn.call(self.screensaver, "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver", "Inhibit",
                           GLib.Variant("(ss)", (who, why)), GLib.VariantType("(u)"), 0, 5000, None, self._cookie, handle)
        if flags & SUSPEND:
            got["fd"] = self._logind_sleep(who, why)
        node = Gio.DBusNodeInfo.new_for_xml(CLOSABLE)
        try:
            got["reg"] = self.conn.register_object(handle, node.interfaces[0], lambda *a: (a[-1].return_value(None), self.release(handle)), None, None)
        except GLib.Error:
            pass
        self.held[handle] = got

    def _cookie(self, conn, result, handle) -> None:
        try:
            cookie = conn.call_finish(result).unpack()[0]
        except GLib.Error:
            return
        if handle in self.held:
            self.held[handle]["cookie"] = cookie
        else:                                            # let go before the answer came
            self._uninhibit(cookie)

    def _uninhibit(self, cookie: int) -> None:
        self.conn.call(self.screensaver, "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver", "UnInhibit",
                       GLib.Variant("(u)", (cookie,)), None, 0, 5000, None, None, None)

    def _logind_sleep(self, who: str, why: str):
        try:
            system = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            r, fds = system.call_with_unix_fd_list_sync("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "Inhibit",
                                                        GLib.Variant("(ssss)", ("sleep", who, why, "block")), GLib.VariantType("(h)"), 0, 3000, None, None)
            return fds.get(r.unpack()[0]) if fds else None
        except GLib.Error:
            return None

    def release(self, handle: str) -> None:
        got = self.held.pop(handle, None)
        if not got:
            return
        if got["cookie"] is not None:
            self._uninhibit(got["cookie"])
        if got["fd"] is not None:
            try:
                os.close(got["fd"])
            except OSError:
                pass
        if got["reg"]:
            self.conn.unregister_object(got["reg"])

    def monitor(self, session: str) -> int:
        """Session state for an app that wants to know (the screen locked, the session ending): told once that it's
        running; Huginn doesn't ask apps before signing out."""
        node = Gio.DBusNodeInfo.new_for_xml(CLOSABLE)
        try:
            self.sessions[session] = self.conn.register_object(session, node.interfaces[1], lambda *a: (a[-1].return_value(None), self._end(session)),
                                                               lambda *a: GLib.Variant("u", 1), None)
        except GLib.Error:
            return 2
        GLib.idle_add(lambda: self.conn.emit_signal(None, "/org/freedesktop/portal/desktop", "org.freedesktop.impl.portal.Inhibit", "StateChanged",
                                                    GLib.Variant("(oa{sv})", (session, {"screensaver-active": GLib.Variant("b", False),
                                                                                        "session-state": GLib.Variant("u", 1)}))) and False)
        return 0

    def _end(self, session: str) -> None:
        reg = self.sessions.pop(session, None)
        if reg:
            self.conn.unregister_object(reg)

    # ..................................................................................................... start-up
    def enable_autostart(self, app_id: str, enable: bool, commandline: list, flags: int) -> bool:
        """Only for sandboxed apps (an app id the portal vouches for); anything else is told no."""
        if not APP_ID.fullmatch(app_id or "") or len(app_id) > 255:
            return False
        path = self.autostart / f"{app_id}.desktop"
        if not enable:
            try:
                if "X-Huginn-Asked-By=" in path.read_text(encoding="utf-8"):
                    path.unlink()
            except OSError:
                pass
            return True
        if any(not isinstance(c, str) or "\n" in c or "\x00" in c for c in commandline) or len(commandline) > 64:
            return False
        try:
            self.autostart.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.new")
            tmp.write_text(autostart_entry(app_id, commandline, bool(flags & 1)), encoding="utf-8")
            os.replace(tmp, path)
            return True
        except OSError:
            return False
