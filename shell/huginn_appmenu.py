"""Menu bars exported as com.canonical.dbusmenu, read for the top bar's app menu: Qt apps on KDE's platform theme
(App Store apps on KDE's Flatpak runtime, which Huginn's own Qt look can't reach) and X11 apps that register a
global menu (Electron and Chromium apps under XWayland).

Such an app exports its menu bar only while com.canonical.AppMenu.Registrar is on the session bus: the shell owns it
(Registrar). On Wayland the app tells the compositor, for each window, on which bus name and path the menu bar is
(KDE's org_kde_kwin_appmenu: compositor/src/appmenu.rs; the window list's "appMenu"); an X11 app registers its
window's number with the registrar instead (RegisterWindow), which the window list's "xid" is matched against.

    Registrar(conn)                  owns com.canonical.AppMenu.Registrar; .lookup(xid, pid) -> {"service", "path"} or None
    read(conn, where, app)           -> (menus, refs): menus in the shell's shape (apps/huginn_menu.py), refs for activate()
    activate(conn, where, ref)       the app does it (an item's id, "dbm:<n>", looked up in refs)
"""
from __future__ import annotations

import re
import time

from gi.repository import Gio, GLib

from huginn_gtkmenus import plain

IFACE = "com.canonical.dbusmenu"
TIMEOUT = 800
MAX_ITEMS = 4000
MAX_WINDOWS = 4096
PROPS = ["type", "label", "enabled", "visible", "toggle-type", "toggle-state", "shortcut", "children-display"]
BUS_NAME = re.compile(r"^(:[0-9A-Za-z_.-]+|[A-Za-z_-][0-9A-Za-z_-]*(\.[A-Za-z_-][0-9A-Za-z_-]*)+)$")
OBJECT_PATH = re.compile(r"^/$|^(/[0-9A-Za-z_]+)+$")


def sound(where) -> bool:
    """A bus name and an object path as D-Bus has them (what an app says is checked before anything is asked of it)."""
    return (isinstance(where, dict) and isinstance(where.get("service"), str) and isinstance(where.get("path"), str)
            and len(where["service"]) <= 255 and len(where["path"]) <= 255
            and bool(BUS_NAME.match(where["service"])) and bool(OBJECT_PATH.match(where["path"])))


# ------------------------------------------------------------------------------------------------ the registrar
REGISTRAR_XML = """<node><interface name="com.canonical.AppMenu.Registrar">
<method name="RegisterWindow"><arg name="windowId" type="u" direction="in"/><arg name="menuObjectPath" type="o" direction="in"/></method>
<method name="UnregisterWindow"><arg name="windowId" type="u" direction="in"/></method>
<method name="GetMenuForWindow"><arg name="windowId" type="u" direction="in"/><arg name="service" type="s" direction="out"/><arg name="menuObjectPath" type="o" direction="out"/></method>
<signal name="WindowRegistered"><arg name="windowId" type="u"/><arg name="service" type="s"/><arg name="menuObjectPath" type="o"/></signal>
<signal name="WindowUnregistered"><arg name="windowId" type="u"/></signal>
</interface></node>"""
REGISTRAR_PATH = "/com/canonical/AppMenu/Registrar"


class Registrar:
    """com.canonical.AppMenu.Registrar: which X11 window's menu bar is where (an app says so for its own windows; it is
    forgotten when it says otherwise or leaves the bus). Its presence is what has apps export their menu bars."""

    def __init__(self, conn, changed=None):
        self.conn, self.changed, self.windows = conn, changed, {}
        node = Gio.DBusNodeInfo.new_for_xml(REGISTRAR_XML)
        self.registration = conn.register_object(REGISTRAR_PATH, node.interfaces[0], self._call, None, None)
        self.owning = Gio.bus_own_name_on_connection(conn, "com.canonical.AppMenu.Registrar", Gio.BusNameOwnerFlags.REPLACE
                                                     | Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT, None, None)
        self.watch = conn.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus",
                                           None, Gio.DBusSignalFlags.NONE, self._owner_changed)

    def close(self) -> None:
        Gio.bus_unown_name(self.owning)
        self.conn.unregister_object(self.registration)
        self.conn.signal_unsubscribe(self.watch)

    def lookup(self, xid, pid=0) -> dict | None:
        """The menu bar registered for an X11 window, when the app that registered it is the window's own (by its
        process, when both are known: a number a Wayland app registers could be any X11 window's)."""
        got = self.windows.get(int(xid)) if isinstance(xid, int) and xid > 0 else None
        if not got or (pid and got[2] and pid != got[2]):
            return None
        return {"service": got[0], "path": got[1]}

    def _pid_of(self, sender) -> int:
        try:
            return int(self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetConnectionUnixProcessID",
                                           GLib.Variant("(s)", (sender,)), GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 1000, None).unpack()[0])
        except GLib.Error:
            return 0

    def _told(self) -> None:
        if self.changed:
            self.changed()

    def _call(self, conn, sender, path, iface, method, params, inv):
        args = params.unpack()
        if method == "RegisterWindow":
            xid, menu = int(args[0]), str(args[1])
            if xid and (xid in self.windows or len(self.windows) < MAX_WINDOWS) and sound({"service": sender, "path": menu}):
                self.windows[xid] = (sender, menu, self._pid_of(sender))
                conn.emit_signal(None, REGISTRAR_PATH, iface, "WindowRegistered", GLib.Variant("(uso)", (xid, sender, menu)))
                self._told()
            inv.return_value(None)
        elif method == "UnregisterWindow":
            xid = int(args[0])
            if self.windows.get(xid, ("",))[0] == sender:           # (only its own)
                del self.windows[xid]
                conn.emit_signal(None, REGISTRAR_PATH, iface, "WindowUnregistered", GLib.Variant("(u)", (xid,)))
                self._told()
            inv.return_value(None)
        elif method == "GetMenuForWindow":
            got = self.windows.get(int(args[0]))
            if got:
                inv.return_value(GLib.Variant("(so)", got[:2]))
            else:
                inv.return_dbus_error("com.canonical.AppMenu.Registrar.Error.NotFound", "No menu for that window")
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _owner_changed(self, conn, sender, path, iface, signal, params):
        name, _old, new = params.unpack()
        if name.startswith(":") and not new:
            gone = [x for x, got in self.windows.items() if got[0] == name]
            for x in gone:
                del self.windows[x]
            if gone:
                self._told()


# ------------------------------------------------------------------------------------------------ reading a menu bar
MODIFIERS = {"control": "Ctrl", "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "super": "Super", "meta": "Meta", "hyper": "Hyper"}
KEY_NAMES = {"plus": "+", "minus": "-", "equal": "=", "comma": ",", "period": ".", "slash": "/", "backslash": "\\",
             "Return": "Enter", "BackSpace": "Backspace", "Delete": "Del", "Escape": "Esc", "Page_Up": "PgUp",
             "Page_Down": "PgDown", "space": "Space", "Insert": "Ins"}


def keys(shortcut) -> str:
    """dbusmenu's [["Control", "Shift", "S"]] as Huginn writes keys: "Ctrl+Shift+S" (the first of them)."""
    if not isinstance(shortcut, (list, tuple)) or not shortcut or not isinstance(shortcut[0], (list, tuple)) or not shortcut[0]:
        return ""
    chord = [str(k) for k in shortcut[0]]
    mods = [MODIFIERS[k.lower()] for k in chord[:-1] if k.lower() in MODIFIERS]
    order = ["Ctrl", "Alt", "Shift", "Super", "Meta", "Hyper"]
    mods = sorted(set(mods), key=order.index)
    key = chord[-1]
    key = KEY_NAMES.get(key, key.upper() if len(key) == 1 else key)
    return "+".join(mods + [key])


def _call(conn, where, method, args, reply):
    return conn.call_sync(where["service"], where["path"], IFACE, method, args, GLib.VariantType(reply) if reply else None,
                          Gio.DBusCallFlags.NO_AUTO_START, TIMEOUT, None)


def _layout(conn, where):
    return _call(conn, where, "GetLayout", GLib.Variant("(iias)", (0, -1, PROPS)), "(u(ia{sv}av))").unpack()[1]


def _submenus(node, depth=0, out=None):
    """The ids of the menus in a layout (items with children, or that say they have a submenu), outermost first."""
    out = [] if out is None else out
    ident, props, children = node
    if depth and (children or props.get("children-display") == "submenu"):
        out.append(ident)
    if depth < 5:
        for c in children:
            if isinstance(c, tuple) and len(c) == 3:
                _submenus(c, depth + 1, out)
    return out


def _opened(conn, where, ids) -> None:
    """Tell the app these menus are about to open (Qt's aboutToShow: menus filled as they open then have their items)."""
    ids = [i for i in ids if isinstance(i, int)][:256]
    if not ids:
        return
    try:
        _call(conn, where, "AboutToShowGroup", GLib.Variant("(ai)", (ids,)), "(aiai)")
        return
    except GLib.Error:
        pass
    for i in ids[:64]:                                           # (older menus: one by one)
        try:
            _call(conn, where, "AboutToShow", GLib.Variant("(i)", (i,)), "(b)")
        except GLib.Error:
            return


def read(conn, where: dict, app: str) -> tuple:
    """The app's menus in the shell's shape, and {id: dbusmenu item id}."""
    if not sound(where):
        raise GLib.Error("no menu bar there")
    layout = _layout(conn, where)
    seen = set()
    for _round in range(3):                                      # menus, then the menus inside those once they're filled
        fresh = [i for i in _submenus(layout) if i not in seen]
        if not fresh:
            break
        seen.update(fresh)
        _opened(conn, where, fresh)
        layout = _layout(conn, where)
    refs, count = {}, [0]

    def rows(children, depth, on):
        out, line = [], False
        for c in children:
            if count[0] >= MAX_ITEMS or not (isinstance(c, tuple) and len(c) == 3):
                continue
            ident, props, kids = c
            if props.get("visible", True) is False:
                continue
            if props.get("type") == "separator":
                line = bool(out)
                continue
            label = plain(str(props.get("label", "")))
            if not label:
                continue
            enabled = on and props.get("enabled", True) is not False
            count[0] += 1
            name = f"dbm:{count[0]}"
            if kids or props.get("children-display") == "submenu":
                inner = rows(kids, depth + 1, enabled) if depth < 4 else []
                if not inner:
                    continue
                row = {"label": label, "id": name, "keys": "", "enabled": enabled, "children": inner}
            else:
                row = {"label": label, "id": name, "keys": keys(props.get("shortcut")), "enabled": enabled}
                kind = props.get("toggle-type")
                if kind in ("checkmark", "radio"):
                    row["checked"] = props.get("toggle-state") == 1
                    if kind == "radio":
                        row["radio"] = True
                refs[name] = int(ident)
            if line and out:
                out.append({"sep": True})
            line = False
            out.append(row)
        return out

    groups = []
    for ident, props, kids in [c for c in layout[2] if isinstance(c, tuple) and len(c) == 3]:
        if props.get("visible", True) is False or props.get("type") == "separator":
            continue
        items = rows(kids, 1, props.get("enabled", True) is not False)
        if items:
            groups.append({"name": plain(str(props.get("label", ""))) or "Menu", "items": items})

    # About, Settings and Quit go where they are in every Huginn app's menu (first, and last), by what they say
    special = {"about": None, "settings": None, "quit": None}
    lower = app.lower()

    def kind_of(it) -> str:
        t = it["label"].lower().replace("…", "").replace("...", "").strip()
        if t.startswith("about ") and not any(x in t for x in (" qt", "kde", " gtk")):
            return "about"
        if t in ("preferences", "settings", "options", f"configure {lower}", f"{lower} preferences", f"{lower} settings"):
            return "settings"
        if t in ("quit", "exit", f"quit {lower}", f"exit {lower}"):
            return "quit"
        return ""

    def pull(items, depth):
        keep = []
        for it in items:
            if it.get("children"):
                if depth < 1:
                    it["children"] = pull(it["children"], depth + 1)
                if not it["children"]:
                    continue
            elif not it.get("sep"):
                kind = kind_of(it)
                if kind and special[kind] is None and it["id"] in refs:
                    special[kind] = it
                    continue
            keep.append(it)
        while keep and keep[0].get("sep"):
            keep.pop(0)
        while keep and keep[-1].get("sep"):
            keep.pop()
        return [k for i, k in enumerate(keep) if not (k.get("sep") and i and keep[i - 1].get("sep"))]

    for g in groups:
        g["items"] = pull(g["items"], 0)
    groups = [g for g in groups if g["items"]]

    def entry(label, ident, key="", on=True):
        return {"label": label, "id": ident, "keys": key, "enabled": on}
    about, settings, quit_ = special["about"], special["settings"], special["quit"]
    top = [dict(about) if about else entry(f"About {app}", "shell:aboutApp"),
           dict(settings, label=f"{app} Settings…") if settings else entry(f"{app} Settings…", "", "Ctrl+,", False)]
    bottom = [entry("Keep on Top", "shell:ontop", "Super+Ctrl+T"), entry("Minimise", "shell:minimise"), entry("Close window", "shell:close", "Ctrl+W"),
              dict(quit_, label=f"Quit {app}") if quit_ else entry(f"Quit {app}", "shell:quit", "Ctrl+Q")]
    return ({"app": app, "key": "", "toolkit": "dbusmenu", "settings": settings is not None, "groups": groups, "top": top,
             "middle": [entry("Show all its windows", "shell:appWindows"), entry("Keep in the dock", "shell:pin")], "bottom": bottom}, refs)


def activate(conn, where: dict, ref: int) -> bool:
    """Ask the app to do one of its menu items (Event "clicked", as a menu does when one is chosen)."""
    if not sound(where) or not isinstance(ref, int):
        return False
    try:
        conn.call(where["service"], where["path"], IFACE, "Event", GLib.Variant("(isvu)", (ref, "clicked", GLib.Variant("s", ""), int(time.time()) & 0xFFFFFFFF)),
                  None, Gio.DBusCallFlags.NO_AUTO_START, 2000, None, None)
        return True
    except GLib.Error:
        return False
