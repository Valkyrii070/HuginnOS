#!/usr/bin/env python3
"""Phone's link (apps/huginn_phoned.py), KDE Connect's protocol, against a stand-in phone written here from the
protocol itself (TLS the other way round, pairing with a code, payloads on ports of their own) and against a second
copy of the link (a paired computer it connects to); then the D-Bus service on a bus of its own.

    phone_test.py <kit root>        (not as root; on 127.0.0.1: ports 41700-41779, and KDE Connect's own 1716-1764)
"""
import ast
import asyncio
import datetime as dt
import hashlib
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

if os.geteuid() == 0:
    sys.exit("not as root")
KIT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(KIT / "apps"))
home = Path(tempfile.mkdtemp(prefix="phone-"))
os.environ["HOME"] = str(home)
os.environ["XDG_CONFIG_HOME"] = str(home / ".config")
os.environ["XDG_CACHE_HOME"] = str(home / ".cache")
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, rsa  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402
import huginn_phoned as ph  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL", name, str(detail)[:400])


def make_cert(folder: Path, ident: str, use_rsa=False):
    """A certificate the way KDE Connect's apps make theirs: self-signed, the id as common name, no extensions."""
    folder.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(65537, 2048) if use_rsa else ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ident), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "KDE"),
                      x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Kde connect")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=365)).not_valid_after(now + dt.timedelta(days=3650)).sign(key, hashes.SHA512()))
    (folder / "privateKey.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                                              serialization.NoEncryption()))
    (folder / "certificate.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert


class Desk:
    """What the link asks the desktop to do, written down."""

    def __init__(self):
        self.log, self.notes, self.closed, self.copied, self.opened, self.calls, self.asked, self.changes = [], {}, [], [], [], [], [], 0
        self.inputs, self.medias = [], []

    def input(self, method, sig, args):
        self.inputs.append((method, sig, args))

    def media(self, ident, body):
        self.medias.append((ident, body))

    def changed(self):
        self.changes += 1

    def call(self, *a):
        self.calls.append(a)

    def pair_asked(self, *a):
        self.asked.append(a)

    def notify(self, key, summary, body, **kw):
        self.notes[key] = dict(kw, summary=summary, body=body)
        self.log.append(key)

    def close(self, key):
        self.closed.append(key)

    def copy(self, text):
        self.copied.append(text)

    def open(self, uri):
        self.opened.append(uri)


class Wire(asyncio.Protocol):
    def __init__(self):
        self.buf, self.lines, self.transport, self.gone = bytearray(), asyncio.Queue(), None, asyncio.Event()

    def connection_made(self, t):
        self.transport = t

    def data_received(self, d):
        self.buf += d
        while b"\n" in self.buf:
            line, _, rest = bytes(self.buf).partition(b"\n")
            self.buf = bytearray(rest)
            self.lines.put_nowait(json.loads(line))

    def connection_lost(self, _e):
        self.gone.set()


class Phone:
    """A stand-in KDE Connect phone: it opens the connection, is TLS's server end, asks to pair, sends packets and
    payloads, and takes files."""

    def __init__(self, name="Astrid's Pixel", use_rsa=False):
        self.id = uuid.uuid4().hex
        self.dir = home / "phones" / self.id
        self.cert = make_cert(self.dir, self.id, use_rsa)
        self.der = self.cert.public_bytes(serialization.Encoding.DER)
        self.name, self.wire, self.next_port = name, None, 41760 + (hash(self.id) % 20)

    def ctx_server(self, their_pem):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.dir / "certificate.pem", self.dir / "privateKey.pem")
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        ctx.load_verify_locations(cadata=their_pem)
        return ctx

    def ctx_client(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        ctx.load_cert_chain(self.dir / "certificate.pem", self.dir / "privateKey.pem")
        return ctx

    def identity(self, extra=None):
        body = {"deviceId": self.id, "deviceName": self.name, "deviceType": "phone", "protocolVersion": 8, "incomingCapabilities": ["kdeconnect.ping"],
                "outgoingCapabilities": ["kdeconnect.battery"]}
        body.update(extra or {})
        return (json.dumps({"id": 1, "type": "kdeconnect.identity", "body": body}) + "\n").encode()

    async def dial(self, port, their_pem, greeting=None, target=None):
        loop = asyncio.get_running_loop()
        t, w = await loop.create_connection(Wire, "127.0.0.1", port)
        t.write(greeting if greeting is not None else self.identity({"targetDeviceId": target or me.id, "targetProtocolVersion": 8}))
        tls = await asyncio.wait_for(loop.start_tls(t, w, self.ctx_server(their_pem), server_side=True, ssl_handshake_timeout=5), 6)
        w.transport = tls
        tls.write(self.identity())
        theirs = await asyncio.wait_for(w.lines.get(), 5)
        self.wire = w
        return theirs

    def send(self, kind, body, payload=None):
        line = {"id": 2, "type": kind, "body": body}
        if payload:
            line["payloadSize"], line["payloadTransferInfo"] = payload[0], {"port": payload[1]}
        self.wire.transport.write((json.dumps(line) + "\n").encode())

    async def get(self, kind=None, wait=5):
        while True:
            got = await asyncio.wait_for(self.wire.lines.get(), wait)
            if kind is None or got["type"] == kind:
                return got

    async def offer(self, kind, body, data: bytes, their_pem, size=None):
        """A packet with a payload: a port of its own, TLS (theirs the only certificate taken), then the bytes."""
        sent = asyncio.Event()

        async def serve(r, w):
            w.write(data)
            await w.drain()
            w.close()
            sent.set()
        server = None
        for port in range(41740, 41760):
            try:
                server = await asyncio.start_server(serve, "127.0.0.1", port, ssl=self.ctx_server(their_pem))
                break
            except OSError:
                continue
        self.send(kind, body, (len(data) if size is None else size, port))
        with __import__("contextlib").suppress(asyncio.TimeoutError):
            await asyncio.wait_for(sent.wait(), 5)
        server.close()
        return sent.is_set()

    async def take(self, got, their_der):
        """A file offered by the computer: connect, TLS's client end, check it's the computer's certificate, read."""
        r, w = await asyncio.open_connection("127.0.0.1", got["payloadTransferInfo"]["port"], ssl=self.ctx_client(), server_hostname=None)
        ok = w.get_extra_info("ssl_object").getpeercert(binary_form=True) == their_der
        data = await r.readexactly(got["payloadSize"])
        w.close()
        return ok, data


def kde_key(a_der, b_der, stamp):
    """KDE Connect's verification key, written again from its description: SHA-256 over the larger public key, the
    smaller, and the time as decimal digits; eight hex digits in capitals."""
    a = x509.load_der_x509_certificate(a_der).public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    b = x509.load_der_x509_certificate(b_der).public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    hi, lo = max(a, b), min(a, b)
    return hashlib.sha256(hi + lo + str(stamp).encode()).hexdigest()[:8].upper()


async def until(cond, wait=5.0):
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return cond()


# ================================================================================================ the computer
conf = home / ".config/huginn/phone"
me = ph.Me(conf, "Huginn Desk", "desktop")
check("the computer's id: a certificate of its own, its common name a valid id", ph.ID_OK.match(me.id) and me.id == ph.common_name(me.cert_der))
check("…kept private", oct((conf / "key.pem").stat().st_mode & 0o777) == "0o600" and oct(conf.stat().st_mode & 0o777) == "0o700")
check("…and the same the next time", ph.Me(conf, "x").id == me.id)
my_pem = (conf / "cert.pem").read_text()
desk = Desk()
core = ph.Core(me, ph.Store(conf), desk, udp_port=0, tcp_ports=range(41700, 41710), payload_ports=range(41710, 41720), greet_to=0)
core.downloads = home / "Downloads"
idn = me.identity(41700)
check("its identity: name, kind, protocol 8, and what it takes in and sends out", idn["protocolVersion"] == 8 and idn["deviceType"] == "desktop"
      and "kdeconnect.telephony" in idn["incomingCapabilities"] and "kdeconnect.sms.request" in idn["outgoingCapabilities"]
      and "kdeconnect.findmyphone.request" in idn["outgoingCapabilities"])
check("names lose what KDE Connect leaves out, and stop at 32", ph.clean_name("Astrid's \"Pixel\" (8)!") == "Astrids Pixel 8" and len(ph.clean_name("x" * 50)) == 32)
check("file names arriving can't climb out of Downloads", ph.safe_filename("../../.bashrc") == "bashrc" and ph.safe_filename("a/b\\c.txt") == "c.txt")


async def scenario():
    await core.start()
    port = core.tcp_port
    check("listening on the first free port of its range", port == 41700)

    # ---- greetings that aren't
    loop = asyncio.get_running_loop()
    for label, greeting in (("not JSON", b"hello\n"), ("an id too short", Phone().identity({"deviceId": "abc"})),
                            ("protocol 7", Phone().identity({"protocolVersion": 7})), ("meant for another device", Phone().identity({"targetDeviceId": "f" * 32})),
                            ("our own id", Phone().identity({"deviceId": me.id}))):
        t, w = await loop.create_connection(Wire, "127.0.0.1", port)
        t.write(greeting)
        check(f"a greeting with {label} is shown the door", await until(lambda: w.gone.is_set(), 3))
    t, w = await loop.create_connection(Wire, "127.0.0.1", port)
    t.write(b"x" * 9000)
    check("…and so is one that never ends", await until(lambda: w.gone.is_set(), 3))
    t, w = await loop.create_connection(Wire, "127.0.0.1", port)
    check("…and one that says nothing, after a while", await until(lambda: w.gone.is_set(), 7))

    # ---- a phone pairs (it asks)
    pixel = Phone()
    theirs = await pixel.dial(port, my_pem)
    check("connected: TLS with the computer as its client end, then its identity", theirs["type"] == "kdeconnect.identity" and theirs["body"]["deviceId"] == me.id
          and theirs["body"]["deviceName"] == "Huginn Desk")
    check("an unpaired phone shows, in reach", await until(lambda: any(d["id"] == pixel.id and d["here"] and not d["paired"] for d in json.loads(core.snapshot))))
    pixel.send("kdeconnect.ping", {"message": "too soon"})
    await asyncio.sleep(0.2)
    check("before pairing, nothing it sends is acted on", not any(k.startswith("ping:") for k in desk.notes))
    stamp = int(time.time())
    pixel.send("kdeconnect.pair", {"pair": True, "timestamp": stamp})
    check("it asks to pair: the computer asks you, with the code", await until(lambda: desk.asked) and desk.asked[-1][0] == pixel.id
          and desk.notes.get(f"pair:{pixel.id}", {}).get("actions") == [("accept", "Pair"), ("reject", "Not Now")])
    check("the code is KDE Connect's (both keys and the time)", desk.asked[-1][2] == kde_key(me.cert_der, pixel.der, stamp), (desk.asked[-1], kde_key(me.cert_der, pixel.der, stamp)))
    view = {d["id"]: d for d in json.loads(core.snapshot)}
    check("…and Phone sees it waiting", view[pixel.id]["pairing"] == "asking" and view[pixel.id]["key"] == desk.asked[-1][2])
    core.notice(f"pair:{pixel.id}", "action", "accept")
    got = await pixel.get("kdeconnect.pair")
    check("Pair on the notification: the phone hears yes", got["body"] == {"pair": True})
    saved = json.loads((conf / "devices.json").read_text())["devices"]
    check("paired: its certificate pinned and kept", pixel.id in saved and ph.pem_to_der(saved[pixel.id]["cert"]) == pixel.der and saved[pixel.id]["name"] == "Astrids Pixel")
    check("…and the notification gives way to 'Paired'", f"pair:{pixel.id}" in desk.closed and desk.notes[f"pair:{pixel.id}"]["summary"].startswith("Paired"))
    check("…and the phone's remote is told it can type here", (await pixel.get("kdeconnect.mousepad.keyboardstate"))["body"] == {"state": True})

    # ---- the phone as a remote
    for body in ({"dx": 12.5, "dy": -3}, {"singleclick": True}, {"doubleclick": True}, {"rightclick": True}, {"singlehold": True}, {"singlerelease": True},
                 {"scroll": True, "dx": 0, "dy": 40}, {"key": "hé", "ctrl": True}, {"specialKey": 6}, {"specialKey": 31, "alt": True, "super": True},
                 {"specialKey": 99}, {"dx": "nan", "dy": None}):
        pixel.send("kdeconnect.mousepad.request", body)
    L, R = 272, 273
    want = [("PointerBy", "(dd)", (12.5, -3.0)), ("PointerButton", "(ub)", (L, True)), ("PointerButton", "(ub)", (L, False)),
            ("PointerButton", "(ub)", (L, True)), ("PointerButton", "(ub)", (L, False)), ("PointerButton", "(ub)", (L, True)), ("PointerButton", "(ub)", (L, False)),
            ("PointerButton", "(ub)", (R, True)), ("PointerButton", "(ub)", (R, False)), ("PointerButton", "(ub)", (L, True)), ("PointerButton", "(ub)", (L, False)),
            ("Scroll", "(dd)", (0.0, 40.0)), ("Key", "(ub)", (29, True)), ("TypeText", "(s)", ("hé",)), ("Key", "(ub)", (29, False)),
            ("Key", "(ub)", (106, True)), ("Key", "(ub)", (106, False)),
            ("Key", "(ub)", (56, True)), ("Key", "(ub)", (125, True)), ("Key", "(ub)", (87, True)), ("Key", "(ub)", (87, False)), ("Key", "(ub)", (125, False)),
            ("Key", "(ub)", (56, False))]
    check("the phone as a remote: its touchpad, clicks, drag, scrolling, typing with Ctrl, an arrow, Alt+Super+F11; nothing for nonsense",
          await until(lambda: len(desk.inputs) >= len(want)) and desk.inputs == want, desk.inputs)
    pixel.send("kdeconnect.mousepad.request", {"dx": 1, "dy": 1, "sendAck": True})
    got = await pixel.get("kdeconnect.mousepad.echo")
    check("…and an echo when it asks for one", got["body"].get("isAck") is True and got["body"].get("dx") == 1)

    # ---- the music here, from the phone
    pixel.send("kdeconnect.mpris.request", {"requestPlayerList": True})
    check("its media controls go to the desk's music players", await until(lambda: desk.medias) and desk.medias[0] == (pixel.id, {"requestPlayerList": True}))
    core.media_reply(pixel.id, {"playerList": ["Music"], "supportAlbumArtPayload": True})
    check("…and the players' answers come back", (await pixel.get("kdeconnect.mpris"))["body"] == {"playerList": ["Music"], "supportAlbumArtPayload": True})
    cover = home / "cover.png"
    cover.write_bytes(b"\x89PNG cover" * 50)
    core.media_reply(pixel.id, {"transferringAlbumArt": True, "player": "Music", "albumArtUrl": cover.as_uri()}, str(cover))
    got = await pixel.get("kdeconnect.mpris")
    ok, data = await pixel.take(got, me.cert_der)
    check("…a cover, as a payload of its own", got["body"]["transferringAlbumArt"] is True and ok and data == cover.read_bytes())

    # ---- what a paired phone sends
    pixel.send("kdeconnect.battery", {"currentCharge": 64, "isCharging": True, "thresholdEvent": 0})
    check("its battery", await until(lambda: any(d["id"] == pixel.id and d["battery"] == 64 and d["charging"] for d in json.loads(core.snapshot))))
    pixel.send("kdeconnect.battery", {"currentCharge": 9, "isCharging": False, "thresholdEvent": 1})
    check("…and a word when it runs low", await until(lambda: f"battery:{pixel.id}" in desk.notes) and "9%" in desk.notes[f"battery:{pixel.id}"]["body"])
    pixel.send("kdeconnect.ping", {"message": "hi there"})
    check("a ping", await until(lambda: desk.notes.get(f"ping:{pixel.id}", {}).get("body") == "hi there"))
    pixel.send("kdeconnect.telephony", {"event": "ringing", "phoneNumber": "+15550100", "contactName": "Sam"})
    pixel.send("kdeconnect.telephony", {"event": "ringing", "phoneNumber": "+15550100", "contactName": "Sam", "isCancel": True})
    pixel.send("kdeconnect.telephony", {"event": "missedCall", "phoneNumber": "+15550100", "contactName": "Sam"})
    check("a call, to the island: ringing, then over", await until(lambda: len(desk.calls) >= 3)
          and desk.calls[:2] == [(pixel.id, "ringing", "+15550100", "Sam"), (pixel.id, "ended", "+15550100", "Sam")], desk.calls)
    check("…and a missed one, remembered", desk.notes.get(f"missed:{pixel.id}:+15550100", {}).get("summary") == "Missed call from Sam")
    pixel.send("kdeconnect.clipboard", {"content": "copied on the phone"})
    pixel.send("kdeconnect.clipboard.connect", {"content": "old", "timestamp": 1})
    check("its clipboard (sent on purpose; not the one it reports on connecting)", await until(lambda: desk.copied == ["copied on the phone"]), desk.copied)
    pixel.send("kdeconnect.share.request", {"text": "a note"})
    pixel.send("kdeconnect.share.request", {"url": "https://example.org/x"})
    pixel.send("kdeconnect.share.request", {"url": "javascript:alert(1)"})
    check("words shared: copied", await until(lambda: "a note" in desk.copied))
    check("a web address: opened; anything else only copied", await until(lambda: desk.opened == ["https://example.org/x"] and "javascript:alert(1)" in desk.copied),
          (desk.opened, desk.copied))
    pixel.send("kdeconnect.findmyphone.request", {})
    check("'ring my computer'", await until(lambda: desk.notes.get(f"ring:{pixel.id}", {}).get("urgency") == 2))

    # ---- its notifications
    icon = b"\x89PNG fake icon"
    ok = await pixel.offer("kdeconnect.notification", {"id": "0|com.chat|7", "appName": "Chat", "title": "Sam", "text": "Lunch?", "isClearable": True,
                                                       "requestReplyId": "r-7", "actions": ["Mark read"], "payloadHash": "abc123"}, icon, my_pem)
    key = f"n:{pixel.id}:0|com.chat|7"
    check("a notification from the phone: its picture fetched over its own TLS port", ok and await until(lambda: key in desk.notes))
    n = desk.notes.get(key, {})
    check("…shown with its app, words, picture, buttons and a reply", n.get("app") == "Chat" and n.get("summary") == "Sam" and n.get("body") == "Lunch?"
          and Path(n.get("image", "/")).read_bytes() == icon and n.get("actions") == [("act:Mark read", "Mark read")] and n.get("reply") is True, n)
    core.notice(key, "reply", "Yes!")
    got = await pixel.get("kdeconnect.notification.reply")
    check("a reply typed in Huginn goes back to the app", got["body"] == {"requestReplyId": "r-7", "message": "Yes!"})
    core.notice(key, "action", "act:Mark read")
    got = await pixel.get("kdeconnect.notification.action")
    check("…and its buttons", got["body"] == {"key": "0|com.chat|7", "action": "Mark read"})
    core.notice(key, "closed", "2")
    got = await pixel.get("kdeconnect.notification.request")
    check("cleared here, cleared on the phone", got["body"] == {"cancel": "0|com.chat|7"})
    pixel.send("kdeconnect.notification", {"id": "9", "appName": "Mail", "title": "Old", "text": "x", "silent": True})
    pixel.send("kdeconnect.notification", {"id": "8", "appName": "Mail", "title": "New", "text": "y"})
    pixel.send("kdeconnect.notification", {"id": "8", "isCancel": True})
    check("cleared on the phone, cleared here; what was there already isn't shown again", await until(lambda: f"n:{pixel.id}:8" in desk.closed)
          and f"n:{pixel.id}:9" not in desk.notes)

    # ---- files from the phone
    ok = await pixel.offer("kdeconnect.share.request", {"filename": "../holiday.jpg", "lastModified": 1700000000000, "numberOfFiles": 1}, b"JPEGDATA" * 1000, my_pem)
    dest = home / "Downloads/holiday.jpg"
    check("a file from the phone: in Downloads, whole, with its time", ok and await until(lambda: dest.is_file()) and dest.read_bytes() == b"JPEGDATA" * 1000
          and int(dest.stat().st_mtime) == 1700000000)
    check("…and a word with Open and Show in Files", desk.notes.get(f"got:{pixel.id}", {}).get("actions") == [("open", "Open"), ("folder", "Show in Files")])
    await pixel.offer("kdeconnect.share.request", {"filename": "holiday.jpg"}, b"second", my_pem)
    check("the same name again: beside it, not over it", await until(lambda: (home / "Downloads/holiday (2).jpg").is_file()) and dest.read_bytes() == b"JPEGDATA" * 1000)
    await pixel.offer("kdeconnect.share.request", {"filename": "short.bin"}, b"abc", my_pem, size=10)
    check("one that stops short isn't kept", await until(lambda: "didn't arrive" in desk.notes.get(f"got:{pixel.id}", {}).get("body", ""))
          and not (home / "Downloads/short.bin").exists() and not (home / "Downloads/short.bin.part").exists())
    sneaky = Phone()                                              # (pixel's link, another device's certificate on the payload)
    sneaky.wire = pixel.wire
    await sneaky.offer("kdeconnect.share.request", {"filename": "sneaky.txt"}, b"nope", my_pem)
    check("a file offered from another certificate isn't taken", not (home / "Downloads/sneaky.txt").exists())

    # ---- to the phone
    for fn, args, kind, body in ((core.ring, (), "kdeconnect.findmyphone.request", {}), (core.ping, ("Hello from Huginn",), "kdeconnect.ping", {"message": "Hello from Huginn"}),
                                 (core.share_text, ("a note",), "kdeconnect.share.request", {"text": "a note"}),
                                 (core.share_url, ("https://example.org",), "kdeconnect.share.request", {"url": "https://example.org"}),
                                 (core.clipboard, ("clip",), "kdeconnect.clipboard", {"content": "clip"}),
                                 (core.mute, (), "kdeconnect.telephony.request_mute", {"action": "mute"})):
        res = fn(pixel.id, *args)
        got = await pixel.get()
        check(f"{fn.__name__}: {kind}", res[0] and got["type"] == kind and got["body"] == body, (res, got))
    res = core.sms(pixel.id, "+15550100", "Can't talk now")
    got = await pixel.get()
    check("a text message: both ways of addressing it (new apps and old)", res[0] and got["type"] == "kdeconnect.sms.request" and got["body"]["version"] == 2
          and got["body"]["addresses"] == [{"address": "+15550100"}] and got["body"]["phoneNumber"] == "+15550100" and got["body"]["messageBody"] == "Can't talk now")
    a, b = home / "one.txt", home / "two.bin"
    a.write_text("first file")
    b.write_bytes(os.urandom(300000))
    sending = asyncio.ensure_future(core.send_files(pixel.id, [str(a), str(b), str(home / "missing")]))
    took = []
    for _ in range(2):
        got = await pixel.get("kdeconnect.share.request")
        took.append((got["body"], await pixel.take(got, me.cert_der)))
    res = await sending
    check("files to the phone: each offered, then taken over TLS with the computer's certificate",
          res == (True, "Sent 2 files.") and [t[1][1] for t in took] == [a.read_bytes(), b.read_bytes()] and all(t[1][0] for t in took), res)
    check("…named, sized and counted as KDE Connect does", took[0][0]["filename"] == "one.txt" and took[0][0]["numberOfFiles"] == 2
          and took[1][0]["totalPayloadSize"] == a.stat().st_size + b.stat().st_size)
    stranger = Phone()
    res = core.ring(stranger.id)
    check("nothing goes to a device that isn't paired", res[0] is False)

    # ---- out of reach, and back
    pixel.wire.transport.close()
    check("gone from the network: still paired, out of reach", await until(lambda: any(d["id"] == pixel.id and d["paired"] and not d["here"] for d in json.loads(core.snapshot))))
    check("…and nothing can be sent to it", core.ping(pixel.id)[0] is False)
    await pixel.dial(port, my_pem)
    check("back again: in reach, still paired", await until(lambda: any(d["id"] == pixel.id and d["paired"] and d["here"] for d in json.loads(core.snapshot))))
    faker = Phone()
    faker.id = pixel.id                                           # pixel's id, another certificate
    try:
        await faker.dial(port, my_pem)
        theirs_ok = True
    except Exception:
        theirs_ok = False
    await asyncio.sleep(0.3)
    check("a device claiming a paired id with another certificate is refused", not theirs_ok or (faker.wire.gone.is_set()), theirs_ok)
    check("…and the real one stays connected", any(d["id"] == pixel.id and d["here"] for d in json.loads(core.snapshot)))

    # ---- the computer asks; the phone declines; then unpairs
    tab = Phone("Old tablet", use_rsa=True)
    await tab.dial(port, my_pem)
    await until(lambda: tab.id in core.devices)
    res = core.pair(tab.id)
    got = await tab.get("kdeconnect.pair")
    check("Pair from Phone: asked, with the time (an RSA certificate this time)", res[0] and got["body"]["pair"] is True
          and abs(got["body"]["timestamp"] - time.time()) < 5 and kde_key(me.cert_der, tab.der, got["body"]["timestamp"]) in res[1], res)
    tab.send("kdeconnect.pair", {"pair": False})
    check("declined there: not paired, and told so", await until(lambda: "didn't pair" in desk.notes.get(f"pair:{tab.id}", {}).get("summary", ""))
          and not core.devices[tab.id].paired)
    core.pair(tab.id)
    await tab.get("kdeconnect.pair")
    tab.send("kdeconnect.pair", {"pair": True})
    check("asked again and accepted: paired", await until(lambda: core.devices[tab.id].paired))
    tab.send("kdeconnect.pair", {"pair": False})
    check("unpaired on the device: forgotten here", await until(lambda: not core.devices[tab.id].paired)
          and tab.id not in json.loads((conf / "devices.json").read_text())["devices"])
    stamp = int(time.time()) - 7200
    tab.send("kdeconnect.pair", {"pair": True, "timestamp": stamp})
    check("a request from a clock two hours out is refused, with a reason", await until(lambda: "clocks" in desk.notes.get(f"pair:{tab.id}", {}).get("body", ""))
          and (await tab.get("kdeconnect.pair"))["body"] == {"pair": False})
    tab.send("kdeconnect.pair", {"pair": True, "timestamp": int(time.time())})
    await until(lambda: core.devices[tab.id].pairing == "asking")
    core.notice(f"pair:{tab.id}", "closed", "2")
    check("a pairing notification dismissed: Not Now", (await tab.get("kdeconnect.pair"))["body"] == {"pair": False} and core.devices[tab.id].pairing == "")
    old = ph.PAIR_TIMEOUT
    ph.PAIR_TIMEOUT = 0.3
    core.pair(tab.id)
    await tab.get("kdeconnect.pair")
    check("an unanswered request runs out", (await tab.get("kdeconnect.pair"))["body"] == {"pair": False} and core.devices[tab.id].pairing == "")
    ph.PAIR_TIMEOUT = old
    res = core.unpair(pixel.id)
    got = await pixel.get("kdeconnect.pair")
    check("Unpair in Phone: the phone told, and the computer forgets it", res[0] and got["body"] == {"pair": False} and not core.devices[pixel.id].paired)
    tab.wire.transport.close()
    check("an unpaired device that leaves is gone from the list", await until(lambda: tab.id not in core.devices))

    # ---- another computer: paired, found by its greeting, connected to
    other_home = home / "other"
    other = ph.Me(other_home, "Study PC", "desktop")
    other_desk = Desk()
    ph.Store(other_home).save_devices({me.id: {"name": "Huginn Desk", "type": "desktop", "cert": my_pem, "protocol": 8}})
    ph.Store(conf).save_devices({other.id: {"name": "Study PC", "type": "desktop", "cert": (other_home / "cert.pem").read_text(), "protocol": 8}})
    core2 = ph.Core(other, ph.Store(other_home), other_desk, udp_port=None, tcp_ports=ph.TCP_PORTS, payload_ports=range(41730, 41740))
    await core2.start()
    core.devices[other.id] = ph.Device(other.id, "Study PC", "desktop")
    core.devices[other.id].paired, core.devices[other.id].cert_pem = True, (other_home / "cert.pem").read_text()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        core.greet_to = s.getsockname()[1]
        udp = core.udp.get_extra_info("sockname")[1]
        s.sendto(ph.packet("kdeconnect.identity", other.identity(core2.tcp_port)), ("127.0.0.1", udp))
        check("a paired computer's greeting: this one connects to it (TLS's server end, its certificate pinned)",
              await until(lambda: core.devices[other.id].link is not None and me.id in core2.devices and core2.devices[me.id].link is not None))
        core.ping(other.id, "from the desk")
        check("…and they talk", await until(lambda: other_desk.notes.get(f"ping:{me.id}", {}).get("body") == "from the desk"))
        stranger = Phone()
        s.setblocking(False)
        s.sendto(stranger.identity({"tcpPort": 1760}), ("127.0.0.1", udp))
        reply = json.loads((await asyncio.wait_for(loop.sock_recvfrom(s, 9000), 3))[0])
        check("an unpaired device's greeting is answered with ours (so it's the one that connects)", reply["type"] == "kdeconnect.identity"
              and reply["body"]["deviceId"] == me.id and reply["body"]["tcpPort"] == port)
        s.sendto(stranger.identity({"tcpPort": 1760}), ("127.0.0.1", udp))
        try:
            await asyncio.wait_for(loop.sock_recvfrom(s, 9000), 0.6)
            again = True
        except asyncio.TimeoutError:
            again = False
        check("…once, not to every repeat", not again)
    core.unpair(other.id)


asyncio.run(scenario())

# ================================================================================ coming from KDE Connect
kde = home / "kde/.config/kdeconnect"
old_id = uuid.uuid4().hex.replace("a", "_")
cert = make_cert(kde, old_id)
kde.mkdir(parents=True, exist_ok=True)
phone_id = uuid.uuid4().hex
phone_cert = make_cert(home / "kde/phone", phone_id)
pem = (home / "kde/phone/certificate.pem").read_text()
escaped = pem.replace("\n", "\\n")
(kde / "trusted_devices").write_text(f'[{phone_id}]\ncertificate="{escaped}"\nname=Astrid\'s Pixel\nprotocolVersion=8\ntype=phone\n\n[bogus]\nname=x\n')
new = home / "kde/.config/huginn/phone"
check("from KDE Connect: its id, key and paired phones come along", ph.from_kde_connect(new, kde) and ph.Me(new).id == old_id
      and list(ph.Store(new).load()["devices"]) == [phone_id] and ph.pem_to_der(ph.Store(new).load()["devices"][phone_id]["cert"]) == phone_cert.public_bytes(serialization.Encoding.DER))
check("…only the first time", ph.from_kde_connect(new, kde) is False)

# ================================================================================================ on D-Bus
bus = subprocess.run(["dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"], capture_output=True, text=True)
address, pid = bus.stdout.split()[:2]
env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address, HOME=str(home / "dbus"), XDG_CONFIG_HOME=str(home / "dbus/.config"))
daemon = subprocess.Popen([sys.executable, str(KIT / "apps/huginn_phoned.py")], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def gdbus(method, *args):
    return subprocess.run(["gdbus", "call", "--session", "--dest", "org.huginn.Phone", "--object-path", "/org/huginn/Phone", "--method",
                           f"org.huginn.Phone.{method}", *args], env=env, capture_output=True, text=True, timeout=10)


for _ in range(60):
    if gdbus("Devices").returncode == 0:
        break
    time.sleep(0.25)
got = gdbus("Devices")
check("on D-Bus: org.huginn.Phone, an empty list to start", got.returncode == 0 and got.stdout.strip() == "('[]',)", got)
check("…things to do answer with yes or no and why", gdbus("Ring", "0" * 32).stdout.strip() == "(false, 'Pair with it first.')")
check("…files too", gdbus("SendFiles", "0" * 32, "['/etc/hostname']").stdout.strip() == "(false, 'Pair with it first.')")
check("…looking again", gdbus("Refresh").returncode == 0)
port = 0
for _ in range(40):
    line = daemon.stdout.readline()
    if "listening on" in line:
        port = int(line.split()[-1])
        break
monitor = subprocess.Popen(["gdbus", "monitor", "--session", "--dest", "org.huginn.Phone"], env=env, stdout=subprocess.PIPE, text=True)
time.sleep(0.5)
dpem = (home / "dbus/.config/huginn/phone/cert.pem").read_text()
did = ph.common_name(ph.pem_to_der(dpem))


# stand-ins on the test bus: the compositor's keys and mouse from afar, and a music player
heard, player_heard = [], []
COMP = """<node><interface name="org.huginn.Compositor">
  <method name="PointerBy"><arg type="d" direction="in"/><arg type="d" direction="in"/></method>
  <method name="PointerButton"><arg type="u" direction="in"/><arg type="b" direction="in"/></method>
  <method name="Scroll"><arg type="d" direction="in"/><arg type="d" direction="in"/></method>
  <method name="Key"><arg type="u" direction="in"/><arg type="b" direction="in"/></method>
  <method name="TypeText"><arg type="s" direction="in"/></method></interface></node>"""
PLAYER = """<node><interface name="org.mpris.MediaPlayer2"><property name="Identity" type="s" access="read"/></interface>
  <interface name="org.mpris.MediaPlayer2.Player">
  <method name="PlayPause"/><method name="Play"/><method name="Pause"/><method name="Next"/><method name="Previous"/><method name="Stop"/><method name="Quit"/>
  <method name="Seek"><arg type="x" direction="in"/></method>
  <method name="SetPosition"><arg type="o" direction="in"/><arg type="x" direction="in"/></method>
  <property name="Metadata" type="a{sv}" access="read"/><property name="PlaybackStatus" type="s" access="read"/>
  <property name="Position" type="x" access="read"/><property name="Volume" type="d" access="readwrite"/>
  <property name="CanPause" type="b" access="read"/><property name="CanPlay" type="b" access="read"/><property name="CanGoNext" type="b" access="read"/>
  <property name="CanGoPrevious" type="b" access="read"/><property name="CanSeek" type="b" access="read"/></interface></node>"""
music = {"PlaybackStatus": "Playing", "Volume": 0.5}
stand_ins = {}


def stand_in_bus():
    from gi.repository import Gio, GLib
    ctx = GLib.MainContext.new()
    ctx.push_thread_default()
    conn = Gio.DBusConnection.new_for_address_sync(address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
    stand_ins["conn"], stand_ins["GLib"] = conn, GLib

    def comp(_c, _s, _p, _i, method, params, inv):
        heard.append((method, params.unpack()))
        inv.return_value(None)
    conn.register_object("/org/huginn/Compositor", Gio.DBusNodeInfo.new_for_xml(COMP).interfaces[0], comp, None, None)
    node = Gio.DBusNodeInfo.new_for_xml(PLAYER)
    meta = {"mpris:trackid": GLib.Variant("o", "/track/1"), "xesam:title": GLib.Variant("s", "Song"), "xesam:artist": GLib.Variant("as", ["Band", "Friend"]),
            "xesam:album": GLib.Variant("s", "Album"), "mpris:length": GLib.Variant("x", 200_000_000), "mpris:artUrl": GLib.Variant("s", (home / "art.png").as_uri())}

    def play(_c, _s, _p, _i, method, params, inv):
        player_heard.append((method, params.unpack()))
        inv.return_value(None)

    def get(_c, _s, _p, iface, prop):
        values = {"Identity": GLib.Variant("s", "Test Player"), "Metadata": GLib.Variant("a{sv}", meta), "PlaybackStatus": GLib.Variant("s", music["PlaybackStatus"]),
                  "Position": GLib.Variant("x", 61_500_000), "Volume": GLib.Variant("d", music["Volume"])}
        return values.get(prop, GLib.Variant("b", True))

    def put(_c, _s, _p, _i, prop, value):
        music[prop] = value.unpack()
        player_heard.append(("set " + prop, value.unpack()))
        return True
    for iface in node.interfaces:
        conn.register_object("/org/mpris/MediaPlayer2", iface, play, get, put)
    for name in ("org.huginn.Compositor", "org.mpris.MediaPlayer2.testplayer"):
        conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName", GLib.Variant("(su)", (name, 4)), None,
                       Gio.DBusCallFlags.NONE, 3000, None)
    GLib.MainLoop(ctx).run()


(home / "art.png").write_bytes(b"cover art " * 300)
__import__("threading").Thread(target=stand_in_bus, daemon=True).start()
time.sleep(1)


async def over_dbus():
    phone = Phone("Sam's phone")
    await phone.dial(port, dpem, target=did)
    await asyncio.sleep(0.3)
    phone.send("kdeconnect.pair", {"pair": True, "timestamp": int(time.time())})
    await asyncio.sleep(0.5)
    view = json.loads(ast.literal_eval(gdbus("Devices").stdout)[0])
    check("over D-Bus: a phone asking to pair, with its code", view and view[0]["pairing"] == "asking" and len(view[0]["key"]) == 8, view)
    check("…accepted from Phone", gdbus("Answer", phone.id, "true").stdout.strip() == "(true, 'Paired with Sams phone.')"
          and (await phone.get("kdeconnect.pair"))["body"] == {"pair": True})
    phone.send("kdeconnect.telephony", {"event": "ringing", "phoneNumber": "+15550100", "contactName": "Sam"})
    await asyncio.sleep(0.5)
    check("a call: the island's signal", gdbus("SendSms", phone.id, "+15550100", "Can't talk now").stdout.strip() == "(true, 'Sent.')"
          and (await phone.get("kdeconnect.sms.request"))["body"]["messageBody"] == "Can't talk now")
    check("…Silence from the island", gdbus("Mute", phone.id).stdout.strip() == "(true, 'Silenced.')" and (await phone.get())["type"] == "kdeconnect.telephony.request_mute")
    for body in ({"dx": 5, "dy": 7}, {"key": "x", "shift": True}, {"specialKey": 12}):
        phone.send("kdeconnect.mousepad.request", body)
    await asyncio.sleep(0.8)
    check("over D-Bus: the remote reaches the compositor's keys and mouse from afar, in order",
          heard == [("PointerBy", (5.0, 7.0)), ("Key", (42, True)), ("TypeText", ("x",)), ("Key", (42, False)), ("Key", (28, True)), ("Key", (28, False))], heard)

    async def mpris(cond, wait=5):
        end = time.monotonic() + wait
        while time.monotonic() < end:
            got = await phone.get("kdeconnect.mpris", max(0.1, end - time.monotonic()))
            if cond(got["body"]):
                return got
        return None
    phone.send("kdeconnect.mpris.request", {"requestPlayerList": True})
    got = await mpris(lambda b: "playerList" in b)
    check("…the music players here, by name", got and got["body"]["playerList"] == ["Test Player"] and got["body"]["supportAlbumArtPayload"] is True, got)
    phone.send("kdeconnect.mpris.request", {"player": "Test Player", "requestNowPlaying": True, "requestVolume": True})
    got = await mpris(lambda b: "title" in b)
    b = got["body"] if got else {}
    check("…what's playing, as KDE Connect's apps expect it (milliseconds)", b.get("title") == "Song" and b.get("artist") == "Band, Friend" and b.get("album") == "Album"
          and b.get("length") == 200000 and b.get("pos") == 61500 and b.get("isPlaying") is True and b.get("volume") == 50 and b.get("canSeek") is True, b)
    for body in ({"action": "PlayPause"}, {"action": "Quit"}, {"setVolume": 80}, {"Seek": 5_000_000}, {"SetPosition": 30000}):
        phone.send("kdeconnect.mpris.request", dict(body, player="Test Player"))
    await asyncio.sleep(0.8)
    check("…play/pause, volume, seeking and a place in the song reach the player; anything else doesn't",
          player_heard == [("PlayPause", ()), ("set Volume", 0.8), ("Seek", (5000000,)), ("SetPosition", ("/track/1", 30000000))], player_heard)
    art = (home / "art.png").as_uri()
    phone.send("kdeconnect.mpris.request", {"player": "Test Player", "albumArtUrl": "file:///etc/passwd"})
    phone.send("kdeconnect.mpris.request", {"player": "Test Player", "albumArtUrl": art})
    got = await mpris(lambda b: b.get("transferringAlbumArt"))
    ok, data = await phone.take(got, ph.pem_to_der(dpem)) if got else (False, b"")
    check("…its cover, and only the file the player says is its cover", got and got["body"]["albumArtUrl"] == art and ok and data == (home / "art.png").read_bytes(), got)
    conn, GLib = stand_ins["conn"], stand_ins["GLib"]
    music["PlaybackStatus"] = "Paused"
    conn.emit_signal(None, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                     GLib.Variant("(sa{sv}as)", ("org.mpris.MediaPlayer2.Player", {"PlaybackStatus": GLib.Variant("s", "Paused")}, [])))
    got = await mpris(lambda b: b.get("isPlaying") is False)
    check("…and paused here, the phone hears so at once", got and got["body"]["player"] == "Test Player", got)

    f = home / "via-dbus.txt"
    f.write_text("sent over D-Bus")
    sending = asyncio.ensure_future(asyncio.to_thread(gdbus, "SendFiles", phone.id, f"['{f}']"))
    got = await phone.get("kdeconnect.share.request", 10)
    ok, data = await phone.take(got, ph.pem_to_der(dpem))
    check("…and a file", ok and data == b"sent over D-Bus" and (await sending).stdout.strip() == "(true, 'Sent “via-dbus.txt”.')")
    phone.wire.transport.close()                                  # (and out of reach)
    await asyncio.sleep(0.5)
    return phone.id

pid_phone = asyncio.run(over_dbus())
monitor.terminate()
signals = monitor.communicate(timeout=5)[0]
check("the signals: Changed, PairAsked (with the code) and Call (device, ringing, number, name)",
      "org.huginn.Phone.Changed ()" in signals and f"org.huginn.Phone.PairAsked ('{pid_phone}', 'Sams phone', '" in signals
      and f"org.huginn.Phone.Call ('{pid_phone}', 'ringing', '+15550100', 'Sam')" in signals, signals[-600:])
# Phone's own screen, talking to it
os.environ["DBUS_SESSION_BUS_ADDRESS"] = address
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
import huginn_extra as hx  # noqa: E402
qapp = QGuiApplication.instance() or QGuiApplication([])


def spin(cond, wait=8.0):
    end = time.monotonic() + wait
    while time.monotonic() < end and not cond():
        QCoreApplication.processEvents()
        time.sleep(0.02)
    return cond()


backend = hx.Phone()
check("Phone: ready, and the paired phone listed (out of reach now)", backend.ready and spin(lambda: any(d["id"] == pid_phone and d["paired"] and not d["here"]
                                                                                                         for d in backend.devices)), backend.devices)
said = []
backend.said.connect(lambda msg, wrong: said.append((msg, wrong)))
backend.pick(pid_phone)
backend.ring()
check("…and what it's told when the phone isn't there", spin(lambda: said) and said[0][1] is True and "isn't in reach" in said[0][0], said)
second = subprocess.run([sys.executable, str(KIT / "apps/huginn_phoned.py")], env=env, capture_output=True, text=True, timeout=20)
check("a second copy leaves it to the first", second.returncode == 0 and daemon.poll() is None, second)
daemon.terminate()
daemon.wait(5)
subprocess.run(["kill", pid])
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
