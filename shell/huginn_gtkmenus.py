"""A GTK app's menu bar, read for the top bar's app menu.

Huginn's compositor tells GTK it shows menu bars (gtkshell.rs: GTK's gtk_shell1 protocol), so GTK apps hide their
own and say where their menus are: a bus name, the menu bar's path (org.gtk.Menus, a GMenuModel) and the paths
of their actions (org.gtk.Actions: "app." on the app's path, "win." on the window's, "unity." on the menu bar's
own, where appmenu-gtk-module puts the actions of an app's GtkMenuBar). The compositor's window list carries them
("gtkMenus"); this reads them into the same shape as every other app's menus (apps/huginn_menu.py) and does what
is chosen.

    read(conn, where, app)       -> (menus, actions): menus for the shell, actions for activate()
    activate(conn, where, ref)   the app does it (ref: an item's id, "gtk:<n>", looked up in actions)
"""
from __future__ import annotations

import re

from gi.repository import Gio, GLib

TIMEOUT = 800
MAX_GROUPS = 64


def plain(label: str) -> str:
    """"_File" -> "File" ("__" is a plain underscore)."""
    return (label or "").replace("__", "\x01").replace("_", "").replace("\x01", "_").strip()


KEY_NAMES = {"plus": "+", "minus": "-", "equal": "=", "comma": ",", "period": ".", "slash": "/", "backslash": "\\",
             "Return": "Enter", "KP_Enter": "Enter", "BackSpace": "Backspace", "Delete": "Del", "Escape": "Esc",
             "Page_Up": "PgUp", "Page_Down": "PgDown", "space": "Space", "Tab": "Tab", "Home": "Home", "End": "End",
             "Insert": "Ins", "bracketleft": "[", "bracketright": "]", "semicolon": ";", "apostrophe": "'",
             "grave": "`", "question": "?", "exclam": "!", "asterisk": "*", "underscore": "_", "Left": "Left",
             "Right": "Right", "Up": "Up", "Down": "Down"}
MODIFIERS = {"primary": "Ctrl", "control": "Ctrl", "ctrl": "Ctrl", "ctl": "Ctrl", "shift": "Shift", "shft": "Shift",
             "alt": "Alt", "mod1": "Alt", "super": "Super", "meta": "Meta", "hyper": "Hyper"}


def keys(accel: str) -> str:
    """GTK's "<Primary><Shift>z" as Huginn writes keys: "Ctrl+Shift+Z"."""
    if not accel:
        return ""
    mods = [m.lower() for m in re.findall(r"<([^>]+)>", accel)]
    key = re.sub(r"<[^>]+>", "", accel).strip()
    if not key:
        return ""
    out = []
    for name in ("primary", "control", "ctrl", "ctl", "alt", "mod1", "shift", "shft", "super", "meta", "hyper"):
        if name in mods and MODIFIERS[name] not in out:
            out.append(MODIFIERS[name])
    order = ["Ctrl", "Alt", "Shift", "Super", "Meta", "Hyper"]
    out.sort(key=order.index)
    key = KEY_NAMES.get(key, key.upper() if len(key) == 1 else key.replace("_", " "))
    return "+".join(out + [key])


def _call(conn, where, path, iface, method, args, reply):
    return conn.call_sync(where["bus"], path, iface, method, args, GLib.VariantType(reply), Gio.DBusCallFlags.NO_AUTO_START, TIMEOUT, None)


def _groups(conn, where) -> dict:
    """{(group, menu): [items]} of the menu bar and every menu linked from it (subscribed, read, unsubscribed)."""
    found, asked, want = {}, set(), {0}
    try:
        while want and len(asked) < MAX_GROUPS:
            ask = sorted(want - asked)[:MAX_GROUPS - len(asked)]
            asked.update(ask)
            got = _call(conn, where, where["menubar"], "org.gtk.Menus", "Start", GLib.Variant("(au)", (ask,)), "(a(uuaa{sv}))").unpack()[0]
            want = set()
            for group, menu, items in got:
                found[(group, menu)] = items
                for it in items:
                    for link in (":section", ":submenu"):
                        if isinstance(it.get(link), tuple) and it[link][0] not in asked:
                            want.add(it[link][0])
    except GLib.Error:
        if not found:
            raise
    finally:
        try:
            _call(conn, where, where["menubar"], "org.gtk.Menus", "End", GLib.Variant("(au)", (sorted(asked),)), "()")
        except GLib.Error:
            pass
    return found


def _actions(conn, where, prefixes) -> dict:
    """{"app.quit": (enabled, parameter type, state or None, path)} for each prefix whose path is known."""
    paths = {"app": where.get("app"), "win": where.get("window"), "unity": where.get("menubar")}
    out = {}
    for prefix in prefixes:
        path = paths.get(prefix)
        if not path:
            continue
        try:
            got = _call(conn, where, path, "org.gtk.Actions", "DescribeAll", None, "(a{s(bgav)})").unpack()[0]
        except GLib.Error:
            continue
        for name, (enabled, ptype, state) in got.items():
            out[f"{prefix}.{name}"] = (bool(enabled), ptype, state[0] if state else None, path)
    return out


def read(conn, where: dict, app: str) -> tuple:
    """The app's menus in the shell's shape, and {id: (path, action name, parameter as a GLib.Variant or None)}."""
    menus = _groups(conn, where)
    prefixes = set()
    for items in menus.values():
        for it in items:
            if isinstance(it.get("action"), str) and "." in it["action"]:
                prefixes.add(it["action"].split(".", 1)[0])
    actions = _actions(conn, where, prefixes)
    refs, kinds, count = {}, {}, [0]

    def row(it, depth):
        label = plain(it.get("label") or "")
        action = it.get("action") if isinstance(it.get("action"), str) else ""
        known = actions.get(action)
        hidden = it.get("hidden-when")
        if (hidden == "action-missing" and not known) or (hidden == "action-disabled" and not (known and known[0])):
            return None
        sub = it.get(":submenu")
        if isinstance(sub, tuple):
            children = rows(menus.get(sub) or [], depth + 1) if depth < 4 else []
            return {"label": label, "id": "", "keys": "", "enabled": bool(children), "children": children} if children and label else None
        if not label:
            return None
        count[0] += 1
        ident = f"gtk:{count[0]}"
        target = it.get("target")
        out = {"label": label, "id": ident, "keys": keys(it.get("accel") or ""), "enabled": bool(known and known[0])}
        kinds[ident] = action
        if known:
            enabled, ptype, state, path = known
            param = None
            if ptype and target is not None:
                try:
                    param = GLib.Variant(ptype, target)
                except (TypeError, ValueError):
                    out["enabled"] = False
            elif ptype:
                out["enabled"] = False                    # (it needs a value the menu doesn't give)
            refs[ident] = (path, action.split(".", 1)[1], param)
            if isinstance(state, bool) and target is None:
                out["checked"] = state
            elif state is not None and target is not None:
                out["checked"] = state == target
                out["radio"] = True
        return out

    def rows(items, depth):
        out, line = [], False
        for it in items:
            sec = it.get(":section")
            if isinstance(sec, tuple):
                inner = rows(menus.get(sec) or [], depth)
                if inner:
                    if out:
                        out.append({"sep": True})
                    out.extend(inner)
                    line = True
                continue
            r = row(it, depth)
            if r:
                if line and out and not out[-1].get("sep"):
                    out.append({"sep": True})
                line = False
                out.append(r)
        while out and out[-1].get("sep"):
            out.pop()
        return out

    special = {"about": None, "settings": None, "quit": None}
    names = {"about": ("app.about", "win.about", "unity.about"), "settings": ("app.preferences", "app.settings", "win.preferences", "win.settings"),
             "quit": ("app.quit", "win.quit")}

    def pull(items):
        """About, Settings and Quit out of the app's groups, to where they are in every app's menu."""
        keep = []
        for it in items:
            if it.get("children"):
                it["children"] = pull(it["children"])
                if not it["children"]:
                    continue
            action = kinds.get(it.get("id", ""), "")
            name = next((k for k, v in names.items() if action in v), None)
            if name and special[name] is None:
                special[name] = it
                continue
            keep.append(it)
        while keep and keep[0].get("sep"):
            keep.pop(0)
        while keep and keep[-1].get("sep"):
            keep.pop()
        return [k for i, k in enumerate(keep) if not (k.get("sep") and i and keep[i - 1].get("sep"))]

    groups = []
    for it in rows(menus.get((0, 0)) or [], 0):
        if it.get("children"):
            groups.append({"name": it["label"], "items": it["children"]})
    for g in groups:
        g["items"] = pull(g["items"])
    groups = [g for g in groups if g["items"]]

    def entry(label, ident, key="", on=True):
        return {"label": label, "id": ident, "keys": key, "enabled": on}
    about, settings, quit_ = special["about"], special["settings"], special["quit"]
    top = [dict(about, label=about["label"]) if about else entry(f"About {app}", "shell:aboutApp"),
           dict(settings, label=f"{app} Settings…") if settings else entry(f"{app} Settings…", "", "Ctrl+,", False)]
    bottom = [entry("Keep on Top", "shell:ontop", "Super+Ctrl+T"), entry("Minimise", "shell:minimise"), entry("Close window", "shell:close", "Ctrl+W"),
              dict(quit_, label=f"Quit {app}") if quit_ else entry(f"Quit {app}", "shell:quit", "Ctrl+Q")]
    return ({"app": app, "key": "", "toolkit": "gtk", "settings": settings is not None, "groups": groups, "top": top,
             "middle": [entry("Show all its windows", "shell:appWindows"), entry("Keep in the dock", "shell:pin")], "bottom": bottom}, refs)


def activate(conn, where: dict, ref: tuple) -> bool:
    """Ask the app to do one of its actions (org.gtk.Actions.Activate)."""
    path, name, param = ref
    try:
        conn.call(where["bus"], path, "org.gtk.Actions", "Activate",
                  GLib.Variant("(sava{sv})", (name, [param] if param is not None else [], {})), None,
                  Gio.DBusCallFlags.NO_AUTO_START, 2000, None, None)
        return True
    except GLib.Error:
        return False
