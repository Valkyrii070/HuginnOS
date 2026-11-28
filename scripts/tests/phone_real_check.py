#!/usr/bin/env python3
"""Phone's link against the real thing: KDE Connect's own daemon (kdeconnectd, as Ubuntu ships it) on a network of
two namespaces joined by a cable (veth), standing in for a phone. Huginn's link (apps/huginn_phoned.py) on one end,
kdeconnectd on the other, each finding the other by its greeting; then pairing both ways (the codes must match),
pings, words, a file each way, "ring", reconnecting both ways round, and unpairing.

    phone_real_check.py <kit root>      (as root, deliberately: it makes the two network namespaces and the cable; the
                                         link, kdeconnectd and its D-Bus run as uid 1500)
"""
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

if os.geteuid() != 0:
    sys.exit("as root: it makes network namespaces")
KIT = Path(sys.argv[1]).resolve()
UID = 1500
TOP = Path("/tmp/phone-real")
shutil.rmtree(TOP, ignore_errors=True)
for d in ("kde/Downloads", "kde/run", "ours/Downloads", "ours/.config", "ours/.cache"):
    (TOP / d).mkdir(parents=True)
for root, dirs, files in os.walk(TOP):
    for n in dirs + files + [""]:
        os.chown(os.path.join(root, n), UID, UID)
os.chmod(TOP / "kde/run", 0o700)
(TOP / "kde/hello.txt").write_text("hello from kdeconnectd\n" * 500)
os.chown(TOP / "kde/hello.txt", UID, UID)

# ---- two namespaces and a cable between them
holders = [subprocess.Popen(["unshare", "-n", "sleep", "900"]) for _ in range(2)]
time.sleep(0.3)
ours, theirs = (h.pid for h in holders)


def ip(pid, *steps):
    for step in steps:
        r = subprocess.run(["nsenter", "-t", str(pid), "-n", "ip", *step.split()], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"no cable ({step}): {r.stderr}")


ip(ours, f"link add va type veth peer name vb netns {theirs}", "addr add 10.77.0.1/24 dev va", "link set va up", "link set lo up")
ip(theirs, "addr add 10.77.0.2/24 dev vb", "link set vb up", "link set lo up")
drop = ["setpriv", f"--reuid={UID}", f"--regid={UID}", "--clear-groups"]
bus = subprocess.run(drop + ["dbus-daemon", "--session", f"--address=unix:path={TOP}/kde/bus", "--fork", "--print-pid=1"], capture_output=True, text=True)
bus_pid = int(bus.stdout.split()[0])
kenv = ["env", "-i", f"HOME={TOP}/kde", f"XDG_RUNTIME_DIR={TOP}/kde/run", f"DBUS_SESSION_BUS_ADDRESS=unix:path={TOP}/kde/bus", "QT_QPA_PLATFORM=offscreen",
        f"XDG_DOWNLOAD_DIR={TOP}/kde/Downloads", "PATH=/usr/bin:/bin", "LANG=C.UTF-8"]
logf = open(TOP / "kdeconnectd.log", "w")


def start_kde():
    return subprocess.Popen(["nsenter", "-t", str(theirs), "-n", *drop, *kenv, "/usr/bin/kdeconnectd"], stdout=logf, stderr=logf)


kde = start_kde()
time.sleep(2)
req_r, req_w = os.pipe()
ack_r, ack_w = os.pipe()
child = os.fork()
if child == 0:
    # ================================================================ our end: in the first namespace, as uid 1500
    with open(f"/proc/{ours}/ns/net") as f:
        os.setns(f.fileno(), os.CLONE_NEWNET)
    os.setgroups([])
    os.setgid(UID)
    os.setuid(UID)
    os.environ.update(HOME=str(TOP / "ours"), XDG_CONFIG_HOME=str(TOP / "ours/.config"), XDG_CACHE_HOME=str(TOP / "ours/.cache"))
    sys.path.insert(0, str(KIT / "apps"))
    from gi.repository import Gio, GLib
    import huginn_phoned as ph

    passed = failed = 0

    def check(name, ok, detail=""):
        global passed, failed
        if ok:
            passed += 1
        else:
            failed += 1
            print("FAIL", name, str(detail)[:500], flush=True)

    class Desk:
        def __init__(self):
            self.notes, self.copied, self.opened, self.asked, self.closed = {}, [], [], [], []

        def changed(self):
            pass

        def call(self, *a):
            pass

        def pair_asked(self, *a):
            self.asked.append(a)

        def notify(self, key, summary, body, **kw):
            self.notes[key] = dict(kw, summary=summary, body=body)

        def close(self, key):
            self.closed.append(key)

        def copy(self, text):
            self.copied.append(text)

        def open(self, uri):
            self.opened.append(uri)

    # kdeconnectd's D-Bus, and a stand-in for the notification server it shows things with
    kb = Gio.DBusConnection.new_for_address_sync(f"unix:path={TOP}/kde/bus", Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                                                 | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
    shown = []
    NOTES = """<node><interface name="org.freedesktop.Notifications">
      <method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/>
        <arg type="s" direction="in"/><arg type="as" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
      <method name="CloseNotification"><arg type="u" direction="in"/></method>
      <method name="GetCapabilities"><arg type="as" direction="out"/></method>
      <method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/></method>
    </interface></node>"""

    def notes_call(_c, _s, _p, _i, method, params, inv):
        if method == "Notify":
            a = params.unpack()
            shown.append((a[0], a[3], a[4]))
            inv.return_value(GLib.Variant("(u)", (len(shown),)))
        elif method == "GetCapabilities":
            inv.return_value(GLib.Variant("(as)", (["body", "actions"],)))
        elif method == "GetServerInformation":
            inv.return_value(GLib.Variant("(ssss)", ("stand-in", "test", "1", "1.2")))
        else:
            inv.return_value(None)

    def glib_side():
        ctx = GLib.MainContext.new()
        ctx.push_thread_default()
        conn = Gio.DBusConnection.new_for_address_sync(f"unix:path={TOP}/kde/bus", Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                                                       | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        conn.register_object("/org/freedesktop/Notifications", Gio.DBusNodeInfo.new_for_xml(NOTES).interfaces[0], notes_call, None, None)
        conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName", GLib.Variant("(su)", ("org.freedesktop.Notifications", 4)),
                       None, Gio.DBusCallFlags.NONE, 3000, None)
        GLib.MainLoop(ctx).run()
    threading.Thread(target=glib_side, daemon=True).start()

    def ask(what):
        """kdeconnectd is stopped and started by the root side (only it can enter the other namespace)."""
        os.write(req_w, (what + "\n").encode())
        return os.read(ack_r, 64).decode().strip()

    def kc(path, iface, method, args=None, sig=None):
        try:
            got = kb.call_sync("org.kde.kdeconnect", path, iface, method, args, GLib.VariantType(sig) if sig else None, Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error as err:
            return err
        return got.unpack() if got is not None else None

    def kprop(path, name):
        got = kc(path, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", ("org.kde.kdeconnect.device", name)), "(v)")
        return got[0] if isinstance(got, tuple) else got

    async def until(cond, wait=10.0):
        end = time.monotonic() + wait
        while time.monotonic() < end:
            try:
                if cond():
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.1)
        return bool(cond())

    def snap(core):
        return {d["id"]: d for d in json.loads(core.snapshot)}

    conf = TOP / "ours/.config/huginn/phone"

    def new_core():
        desk = Desk()
        core = ph.Core(ph.Me(conf, "Huginn Check", "desktop"), ph.Store(conf), desk, payload_ports=range(1739, 1765))
        core.downloads = TOP / "ours/Downloads"
        return core, desk

    async def scenario():
        await asyncio.sleep(1)
        kid = None
        for _ in range(60):
            kid = kc("/modules/kdeconnect", "org.kde.kdeconnect.daemon", "selfId", None, "(s)")
            if isinstance(kid, tuple):
                kid = kid[0]
                break
            await asyncio.sleep(0.25)
        check("kdeconnectd is up, on its own bus and network", isinstance(kid, str) and ph.ID_OK.match(kid), kid)
        dev = f"/modules/kdeconnect/devices/{kid}"
        core, desk = new_core()
        await core.start()
        me = core.me.id
        check("found each other: kdeconnectd heard our greeting and connected (we're TLS's client end)",
              await until(lambda: kid in snap(core) and snap(core)[kid]["here"]) and me in kc("/modules/kdeconnect", "org.kde.kdeconnect.daemon", "devices",
                                                                                                GLib.Variant("(bb)", (True, False)), "(as)")[0], snap(core))
        check("…its name and kind as it says them", snap(core).get(kid, {}).get("type") in ("desktop", "laptop") and snap(core).get(kid, {}).get("name"))

        # ---- kdeconnectd asks to pair
        kc(dev.replace(kid, me), "org.kde.kdeconnect.device", "requestPairing")
        check("it asks to pair: we ask you", await until(lambda: desk.asked))
        theirs = kprop(dev.replace(kid, me), "verificationKey")
        check("…and both show the same code", desk.asked and desk.asked[-1][2] == theirs, (desk.asked, theirs))
        core.answer(kid, True)
        check("Pair: paired on both sides", await until(lambda: kprop(dev.replace(kid, me), "isPaired") is True) and core.devices[kid].paired)

        # ---- both ways
        kc(dev.replace(kid, me) + "/ping", "org.kde.kdeconnect.device.ping", "sendPing", GLib.Variant("(s)", ("ping from KDE",)))
        check("a ping from kdeconnectd", await until(lambda: desk.notes.get(f"ping:{kid}", {}).get("body") == "ping from KDE"), desk.notes)
        core.ping(kid, "ping from Huginn")
        check("a ping from us, shown by kdeconnectd", await until(lambda: any("ping from Huginn" in (s[1] + s[2]) for s in shown)), shown)
        kc(dev.replace(kid, me) + "/share", "org.kde.kdeconnect.device.share", "shareText", GLib.Variant("(s)", ("words from KDE",)))
        check("words shared by kdeconnectd: copied here", await until(lambda: "words from KDE" in desk.copied), desk.copied)
        kc(dev.replace(kid, me) + "/share", "org.kde.kdeconnect.device.share", "shareUrl", GLib.Variant("(s)", ((TOP / "kde/hello.txt").as_uri(),)))
        got = TOP / "ours/Downloads/hello.txt"
        check("a file from kdeconnectd: fetched over its TLS, whole", await until(lambda: got.is_file() and got.read_text() == (TOP / "kde/hello.txt").read_text(), 15),
              sorted(p.name for p in (TOP / "ours/Downloads").iterdir()))
        mine = TOP / "ours/report.pdf"
        mine.write_bytes(os.urandom(200000))
        res = await core.send_files(kid, [str(mine)])
        there = TOP / "kde/Downloads/report.pdf"
        check("a file to kdeconnectd: it took it over TLS, checking our certificate", res[0] and await until(lambda: there.is_file() and there.read_bytes() == mine.read_bytes(), 15),
              (res, sorted(p.name for p in (TOP / "kde/Downloads").iterdir())))
        kc(dev.replace(kid, me) + "/findmyphone", "org.kde.kdeconnect.device.findmyphone", "ring")
        check("'ring' from kdeconnectd: we ring", await until(lambda: f"ring:{kid}" in desk.notes))
        res = core.share_text(kid, "words from Huginn")
        check("words to kdeconnectd: it shows them", res[0] and await until(lambda: any("words from Huginn" in (s[1] + s[2]) for s in shown)), shown[-3:])

        # ---- out of reach and back: kdeconnectd restarts, greets, and we connect to it (TLS's server end, its certificate pinned)
        ask("stop")
        check("kdeconnectd gone: out of reach, still paired", await until(lambda: not snap(core)[kid]["here"] and snap(core)[kid]["paired"]))
        ask("start")
        await asyncio.sleep(1.5)
        check("back: its greeting, and our connection to it", await until(lambda: snap(core)[kid]["here"], 20))
        await until(lambda: kc(dev.replace(kid, me) + "/ping", "org.freedesktop.DBus.Introspectable", "Introspect", None, "(s)") is not None and
                    not isinstance(kc(dev.replace(kid, me) + "/ping", "org.freedesktop.DBus.Introspectable", "Introspect", None, "(s)"), GLib.Error))
        kc(dev.replace(kid, me) + "/ping", "org.kde.kdeconnect.device.ping", "sendPing", GLib.Variant("(s)", ("again",)))
        check("…and it works", await until(lambda: desk.notes.get(f"ping:{kid}", {}).get("body") == "again"))

        # ---- we restart: our greeting, and kdeconnectd (paired) connects to us, checking our certificate
        core.server.close()
        if core.udp:
            core.udp.close()
        for d in core.devices.values():
            if d.link:
                d.link.close()
        await asyncio.sleep(1)
        core, desk = new_core()
        await core.start()
        check("we restart: kdeconnectd connects to us again, as paired", await until(lambda: snap(core).get(kid, {}).get("here") and snap(core)[kid]["paired"], 20), snap(core))
        core.ping(kid, "after the restart")
        check("…and it works", await until(lambda: any("after the restart" in (s[1] + s[2]) for s in shown)))

        # ---- kdeconnectd unpairs; we ask to pair; it accepts
        kc(dev.replace(kid, me), "org.kde.kdeconnect.device", "unpair")
        check("unpaired there: forgotten here", await until(lambda: not core.devices[kid].paired) and kid not in ph.Store(conf).load()["devices"])
        res = core.pair(kid)
        await until(lambda: kprop(dev.replace(kid, me), "isPairRequestedByPeer") is True)
        theirs = kprop(dev.replace(kid, me), "verificationKey")
        check("we ask to pair: kdeconnectd shows the same code", res[0] and theirs and theirs in res[1], (res, theirs))
        kc(dev.replace(kid, me), "org.kde.kdeconnect.device", "acceptPairing")
        check("…accepted there: paired here", await until(lambda: core.devices[kid].paired))
        core.unpair(kid)
        check("Unpair here: unpaired there", await until(lambda: kprop(dev.replace(kid, me), "isPaired") is False))

    try:
        asyncio.run(asyncio.wait_for(scenario(), 240))
    except Exception as err:
        failed += 1
        print("FAIL the check stopped:", repr(err), flush=True)
    print(f"{passed} passed, {failed} failed", flush=True)
    os._exit(1 if failed else 0)

os.close(req_w)
with os.fdopen(req_r) as requests:
    for line in requests:
        if line.strip() == "stop":
            kde.send_signal(signal.SIGTERM)
            kde.wait(10)
        elif line.strip() == "start":
            kde = start_kde()
        os.write(ack_w, b"ok\n")
_, status = os.waitpid(child, 0)
kde.send_signal(signal.SIGTERM)
subprocess.run(["pkill", "-u", str(UID), "-f", "kdeconnectd"])
os.kill(bus_pid, signal.SIGTERM)
for h in holders:
    h.kill()
code = os.waitstatus_to_exitcode(status)
if code:
    print("--- kdeconnectd's log (last lines)")
    print("".join((TOP / "kdeconnectd.log").read_text(errors="replace").splitlines(True)[-25:]))
sys.exit(code)
