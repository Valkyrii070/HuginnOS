#!/usr/bin/env python3
"""Tray icons (StatusNotifierItem), for Huginn's shell.

Apps like Steam, Discord and anything made with Qt or Electron put an icon in "the tray" so they can keep running with
no window and offer a small menu (Steam: Library, Friends, Exit Steam). They look for a watcher on the session bus
(org.kde.StatusNotifierWatcher); with none, they can't: closing their window quits them, or they keep running unseen.

This is that watcher, and the host that shows them: Tray.items for QML (the control centre's Running in the background
lists them with the app they belong to), activate() for a click (the app shows its window), menu() for its own menu
(com.canonical.dbusmenu, read when it's opened) and click() for a choice in it.

Items register as a bus name ("org.kde.StatusNotifierItem-PID-N", the object at /StatusNotifierItem) or as an object
path on the caller's connection (libappindicator's /org/ayatana/NotificationItem/…); both are taken. One that leaves the
bus is dropped.
"""
import hashlib
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QImage

from gi.repository import Gio, GLib

WATCHER = "org.kde.StatusNotifierWatcher"
ITEM = "org.kde.StatusNotifierItem"
MENU = "com.canonical.dbusmenu"
WATCHER_XML = """<node><interface name="org.kde.StatusNotifierWatcher">
 <method name="RegisterStatusNotifierItem"><arg name="service" type="s" direction="in"/></method>
 <method name="RegisterStatusNotifierHost"><arg name="service" type="s" direction="in"/></method>
 <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
 <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
 <property name="ProtocolVersion" type="i" access="read"/>
 <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
 <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
 <signal name="StatusNotifierHostRegistered"/>
 <signal name="StatusNotifierHostUnregistered"/>
</interface></node>"""
ICONS = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "huginn-tray"


def label_of(text: str) -> str:
    """A menu label without its keyboard-mnemonic underscores ("_Quit" → "Quit", "__" stays one)."""
    out, i = [], 0
    while i < len(text):
        if text[i] == "_":
            if i + 1 < len(text) and text[i + 1] == "_":
                out.append("_")
                i += 2
                continue
            i += 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def parse_layout(node) -> list:
    """A dbusmenu layout (id, {props}, [children]) as a list for QML: {id, label, enabled, separator, check, checked,
    children}; hidden entries left out."""
    out = []
    for child in node[2]:
        cid, props, kids = child[0], child[1], child
        if not props.get("visible", True):
            continue
        sep = props.get("type") == "separator"
        out.append({"id": int(cid), "label": label_of(props.get("label", "")), "enabled": bool(props.get("enabled", True)),
                    "separator": sep, "check": props.get("toggle-type", "") in ("checkmark", "radio"),
                    "checked": props.get("toggle-state", 0) == 1, "children": parse_layout(kids) if kids[2] else []})
    # no separators at the ends, nor two together
    clean = []
    for e in out:
        if e["separator"] and (not clean or clean[-1]["separator"]):
            continue
        clean.append(e)
    while clean and clean[-1]["separator"]:
        clean.pop()
    return clean


def pixmap_png(pixmaps, key: str) -> str:
    """The biggest of an item's IconPixmap pictures (ARGB32, network order) as a PNG in the runtime folder; its URL."""
    try:
        w, h, data = max(pixmaps, key=lambda p: p[0] * p[1])
    except ValueError:
        return ""
    if w <= 0 or h <= 0 or len(data) < w * h * 4:
        return ""
    raw = bytes(data)
    # network byte order ARGB → QImage's ARGB32 (native: little-endian BGRA)
    swapped = bytearray(len(raw))
    swapped[0::4], swapped[1::4], swapped[2::4], swapped[3::4] = raw[3::4], raw[2::4], raw[1::4], raw[0::4]
    img = QImage(bytes(swapped), w, h, w * 4, QImage.Format.Format_ARGB32).copy()
    ICONS.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(key.encode() + raw[:4096]).hexdigest()[:16] + ".png"
    path = ICONS / name
    if not path.exists():
        img.save(str(path), "PNG")
    return QUrl.fromLocalFile(str(path)).toString()


class Tray(QObject):
    """The watcher and the host (see the module's notes)."""
    changed = Signal()

    def __init__(self, apps=None, demo: bool = False):
        super().__init__()
        self._apps = apps                       # huginn_shell.Apps: which app a tray icon belongs to
        self._items = {}                        # "service|path" -> {...}
        self._subs = {}
        self._bus = None
        self._demo = demo
        if demo:
            self._items = {"demo|steam": {"key": "demo|steam", "title": "Steam", "icon": "", "iconName": "", "app": "Steam", "status": "Active",
                                          "isMenu": True, "tooltip": ""},
                           "demo|discord": {"key": "demo|discord", "title": "Discord", "icon": "", "iconName": "", "app": "Discord", "status": "NeedsAttention",
                                            "isMenu": False, "tooltip": "1 unread message"}}
            return
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            return
        node = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML)
        self._iface = node.interfaces[0]
        self._bus.register_object("/StatusNotifierWatcher", self._iface, self._on_call, self._on_get, None)
        Gio.bus_own_name_on_connection(self._bus, WATCHER, Gio.BusNameOwnerFlags.REPLACE | Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT,
                                       self._owned, None)
        # this process is also the host
        Gio.bus_own_name_on_connection(self._bus, f"org.kde.StatusNotifierHost-{os.getpid()}", Gio.BusNameOwnerFlags.NONE, None, None)
        self._bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus", None,
                                   Gio.DBusSignalFlags.NONE, self._on_owner)

    def _owned(self, *_):
        self._emit("StatusNotifierHostRegistered", None)

    # ------------------------------------------------------------------------------------------- the watcher
    def _on_call(self, conn, sender, path, iface, method, params, invocation):
        if method == "RegisterStatusNotifierItem":
            arg = params.unpack()[0]
            if arg.startswith("/"):
                service, obj = sender, arg
            else:
                service, obj = arg, "/StatusNotifierItem"
            invocation.return_value(None)
            self._add(service, obj)
        elif method == "RegisterStatusNotifierHost":
            invocation.return_value(None)
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _on_get(self, conn, sender, path, iface, prop):
        if prop == "RegisteredStatusNotifierItems":
            return GLib.Variant("as", [f"{i['service']}{i['path']}" for i in self._items.values()])
        if prop == "IsStatusNotifierHostRegistered":
            return GLib.Variant("b", True)
        if prop == "ProtocolVersion":
            return GLib.Variant("i", 0)
        return None

    def _emit(self, signal, params):
        if self._bus:
            try:
                self._bus.emit_signal(None, "/StatusNotifierWatcher", WATCHER, signal, params)
            except GLib.Error:
                pass

    def _on_owner(self, conn, sender, path, iface, signal, params):
        name, old, new = params.unpack()
        if new:
            return
        gone = [k for k, i in self._items.items() if i["service"] == name or i.get("unique") == name]
        for k in gone:
            item = self._items.pop(k)
            sub = self._subs.pop(k, None)
            if sub is not None:
                self._bus.signal_unsubscribe(sub)
            self._emit("StatusNotifierItemUnregistered", GLib.Variant("(s)", (f"{item['service']}{item['path']}",)))
        if gone:
            self.changed.emit()

    # ------------------------------------------------------------------------------------------- the items
    def _add(self, service: str, path: str) -> None:
        key = f"{service}|{path}"
        if key in self._items:
            self._read(key)
            return
        item = {"key": key, "service": service, "path": path, "title": "", "icon": "", "iconName": "", "app": "", "status": "Active",
                "isMenu": False, "menu": "", "tooltip": ""}
        self._items[key] = item
        # the unique name (for when the well-known one leaves), and whose it is
        try:
            unique = self._bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner",
                                         GLib.Variant("(s)", (service,)), GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
            item["unique"] = unique
            pid = self._bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetConnectionUnixProcessID",
                                      GLib.Variant("(s)", (service,)), GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
            item["app"] = self._app_of(pid)
        except GLib.Error:
            pass
        self._subs[key] = self._bus.signal_subscribe(item.get("unique") or service, ITEM, None, path, None, Gio.DBusSignalFlags.NONE,
                                                     lambda *a, k=key: self._read(k))
        self._emit("StatusNotifierItemRegistered", GLib.Variant("(s)", (f"{service}{path}",)))
        self._read(key)

    def _app_of(self, pid: int) -> str:
        """The installed app this process (or the one that started it) is. A Flatpak's tray icon comes through its
        sandbox's bus proxy, so its sandbox (the app-flatpak-<id> scope it runs in) says whose it is."""
        if not self._apps:
            return ""
        try:
            m = re.search(r"app-flatpak-([A-Za-z][\w.-]+?)-\d+\.scope", Path(f"/proc/{pid}/cgroup").read_text())
            if m:
                name = next((n for n, match in getattr(self._apps, "_matchers", []) if match == ("@flatpak", m.group(1))), "")
                if name:
                    return name
        except OSError:
            pass
        for _ in range(6):
            try:
                argv = [a.decode(errors="replace") for a in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if a]
                stat = Path(f"/proc/{pid}/stat").read_text()
            except OSError:
                return ""
            name = self._apps.app_for_argv(argv)
            if name:
                return name
            pid = int(stat[stat.rindex(")") + 2:].split()[1])
            if pid <= 1:
                return ""
        return ""

    def _read(self, key: str) -> None:
        item = self._items.get(key)
        if not item:
            return
        self._bus.call(item["service"], item["path"], "org.freedesktop.DBus.Properties", "GetAll", GLib.Variant("(s)", (ITEM,)),
                       GLib.VariantType("(a{sv})"), Gio.DBusCallFlags.NONE, 2000, None, self._got, key)

    def _got(self, conn, result, key):
        try:
            props = conn.call_finish(result).unpack()[0]
        except GLib.Error:
            return
        item = self._items.get(key)
        if not item:
            return
        tip = props.get("ToolTip")
        status = props.get("Status", "Active")
        icon_name = props.get("AttentionIconName") if status == "NeedsAttention" and props.get("AttentionIconName") else props.get("IconName", "")
        pix = props.get("AttentionIconPixmap") if status == "NeedsAttention" and props.get("AttentionIconPixmap") else props.get("IconPixmap")
        theme = props.get("IconThemePath", "")
        icon = ""
        if icon_name and theme:
            for ext in (".png", ".svg"):
                f = Path(theme) / (icon_name + ext)
                if f.is_file():
                    icon = QUrl.fromLocalFile(str(f)).toString()
                    break
        if not icon and pix:
            icon = pixmap_png(pix, key)
        if not item["app"] and self._apps:                 # by its name, when its process didn't say
            for word in (props.get("Title") or "", props.get("Id") or ""):
                w = word.strip().lower()
                hit = next((a["name"] for a in self._apps.all if w and (a["name"].lower() == w or a.get("id", "").lower().endswith(w))), "")
                if hit:
                    item["app"] = hit
                    break
        item.update(title=props.get("Title") or props.get("Id") or item["app"] or "", status=status, iconName=icon_name or "", icon=icon,
                    isMenu=bool(props.get("ItemIsMenu", False)), menu=props.get("Menu", "") or "",
                    tooltip=(tip[2] or tip[3]) if isinstance(tip, tuple) and len(tip) >= 4 else "")
        self.changed.emit()

    @Property("QVariantList", notify=changed)
    def items(self):
        return [{k: v for k, v in i.items() if k in ("key", "title", "icon", "iconName", "app", "status", "isMenu", "tooltip")}
                for i in self._items.values() if i["status"] != "Passive" or i["app"]]

    # ------------------------------------------------------------------------------------------- what you do
    @Slot(str, int, int)
    def activate(self, key: str, x: int, y: int) -> None:
        """A click: the app shows its window (or, for one whose icon is only a menu, nothing: QML opens the menu)."""
        item = self._items.get(key)
        if not item or self._demo:
            return
        self._bus.call(item["service"], item["path"], ITEM, "Activate", GLib.Variant("(ii)", (x, y)), None, Gio.DBusCallFlags.NONE, 2000, None,
                       lambda c, r, k: self._done(c, r), key)

    def _done(self, conn, result):
        try:
            conn.call_finish(result)
        except GLib.Error as err:
            print(f"tray: {err.message}", file=sys.stderr)

    @Slot(str, result="QVariantList")
    def menu(self, key: str) -> list:
        """The app's own menu, read now (it can change: Steam's lists your friends' status)."""
        if self._demo:
            return {"demo|steam": [{"id": 1, "label": "Store", "enabled": True, "separator": False, "check": False, "checked": False, "children": []},
                                   {"id": 2, "label": "Library", "enabled": True, "separator": False, "check": False, "checked": False, "children": []},
                                   {"id": 3, "label": "Friends", "enabled": True, "separator": False, "check": False, "checked": False, "children": []},
                                   {"id": 4, "label": "", "enabled": True, "separator": True, "check": False, "checked": False, "children": []},
                                   {"id": 5, "label": "Big Picture", "enabled": True, "separator": False, "check": False, "checked": False, "children": []},
                                   {"id": 6, "label": "Exit Steam", "enabled": True, "separator": False, "check": False, "checked": False, "children": []}]}.get(key, [])
        item = self._items.get(key)
        if not item or not item.get("menu"):
            return []
        try:
            self._bus.call_sync(item["service"], item["menu"], MENU, "AboutToShow", GLib.Variant("(i)", (0,)), None, Gio.DBusCallFlags.NONE, 500, None)
        except GLib.Error:
            pass
        try:
            rev, layout = self._bus.call_sync(item["service"], item["menu"], MENU, "GetLayout", GLib.Variant("(iias)", (0, -1, [])),
                                              None, Gio.DBusCallFlags.NONE, 1500, None).unpack()
        except GLib.Error:
            return []
        return parse_layout(layout)

    @Slot(str, int)
    def click(self, key: str, ident: int) -> None:
        item = self._items.get(key)
        if not item or not item.get("menu") or self._demo:
            return
        self._bus.call(item["service"], item["menu"], MENU, "Event", GLib.Variant("(isvu)", (ident, "clicked", GLib.Variant("s", ""), 0)),
                       None, Gio.DBusCallFlags.NONE, 2000, None, lambda c, r, k: self._done(c, r), key)
