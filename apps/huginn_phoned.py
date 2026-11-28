#!/usr/bin/env python3
"""Phone link (huginn-phoned): Huginn's own side of KDE Connect, with nothing of KDE's in it.

The free KDE Connect app (Android, iPhone) and GSConnect speak an open protocol over the local network; this daemon
speaks it too (version 8). They find each other by a UDP greeting (port 1716) and talk over TCP (1716-1764), inside
TLS, each side with a certificate of its own: pairing pins the other's, after both screens have shown the same
eight-character code. Then:

  from the phone: its battery; calls (to the island, with Silence and a text back); its notifications, in Huginn's,
  with their buttons and replies, cleared on one side when cleared on the other; files (to Downloads), web addresses
  (opened) and words (copied) it shares; its clipboard; a ping; "ring my computer"; the phone as a remote (its
  touchpad and keyboard, and slides' Next and Back, through the compositor's keys and mouse from afar:
  org.huginn.Compositor PointerBy, PointerButton, Scroll, Key, TypeText); and the music playing here, played, paused,
  skipped, sought and turned up from the phone (every MPRIS player, with its cover);
  to the phone: files, words, a web address, the clipboard, a ping, ring it, silence a call, and text messages.

Phone, the island and Shortcuts use it over D-Bus (session bus): org.huginn.Phone at /org/huginn/Phone (XML below);
the session starts it, and D-Bus does if it isn't running. Its id, key and certificate and the phones it trusts are in
~/.config/huginn/phone; a computer that had KDE Connect brings its id and paired phones along the first time, so they
stay paired.

Structure: Core is the protocol, on an asyncio loop in its own thread; it tells a Desk what to show (Huginn's
notifications, the clipboard, signals), and the Desk (GLib's main loop: D-Bus) hands the answers back.
"""
import asyncio
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

PROTOCOL = 8
UDP_PORT = 1716
TCP_PORTS = range(1716, 1765)
PAYLOAD_PORTS = range(1739, 1765)
MAX_IDENTITY = 8192                       # a greeting longer than this isn't one
MAX_PACKET = 32 * 1024 * 1024             # nor is a packet past this (a notification with a whole conversation in it is less)
MAX_UNPAIRED = 42                         # devices that aren't paired, connected at once
MAX_ICON = 1024 * 1024
PAIR_TIMEOUT = 30.0
CLOCK_SLACK = 1800                        # a pairing request's time may be this far from ours (seconds)
ID_OK = re.compile(r"^[A-Za-z0-9_-]{32,38}$")
NAME_BAD = re.compile(r"[\"',;:.!?()\[\]<>]")

# What this side takes in, and sends out (the phone turns on what matches)
INCOMING = ["kdeconnect.ping", "kdeconnect.battery", "kdeconnect.telephony", "kdeconnect.notification", "kdeconnect.share.request",
            "kdeconnect.mousepad.request", "kdeconnect.mpris.request",
            "kdeconnect.clipboard", "kdeconnect.clipboard.connect", "kdeconnect.findmyphone.request"]
OUTGOING = ["kdeconnect.ping", "kdeconnect.findmyphone.request", "kdeconnect.share.request", "kdeconnect.clipboard", "kdeconnect.clipboard.connect",
            "kdeconnect.mousepad.keyboardstate", "kdeconnect.mousepad.echo", "kdeconnect.mpris",
            "kdeconnect.telephony.request_mute", "kdeconnect.sms.request", "kdeconnect.notification.request", "kdeconnect.notification.reply",
            "kdeconnect.notification.action"]

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")


def log(*words) -> None:
    print("huginn-phoned:", *words, file=sys.stderr, flush=True)


def clean_name(name) -> str:
    return NAME_BAD.sub("", str(name or "")).strip()[:32]


def packet(kind: str, body: dict, payload: tuple = None) -> bytes:
    """One line of JSON: {"id", "type", "body"}, and "payloadSize"/"payloadTransferInfo" when a payload follows on a
    port of its own."""
    out = {"id": int(time.time() * 1000), "type": kind, "body": body}
    if payload:
        out["payloadSize"], out["payloadTransferInfo"] = int(payload[0]), {"port": int(payload[1])}
    return (json.dumps(out, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def unpack(line: bytes):
    try:
        got = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(got, dict) or not isinstance(got.get("type"), str) or not got["type"]:
        return None
    if not isinstance(got.get("body"), dict):
        got["body"] = {}
    return got


def number(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def common_name(der: bytes) -> str:
    try:
        names = x509.load_der_x509_certificate(der).subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    except ValueError:
        return ""
    return str(names[0].value) if names else ""


def public_der(der: bytes) -> bytes:
    return x509.load_der_x509_certificate(der).public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def pem_to_der(pem: str) -> bytes:
    return x509.load_pem_x509_certificate(pem.encode()).public_bytes(serialization.Encoding.DER)


def der_to_pem(der: bytes) -> str:
    return x509.load_der_x509_certificate(der).public_bytes(serialization.Encoding.PEM).decode()


def verification_key(mine: bytes, theirs: bytes, stamp: int) -> str:
    """The code both screens show while pairing: the two public keys (larger first) and the request's time, hashed;
    the first eight hex digits, in capitals. The same on both sides only if nobody is in between."""
    a, b = public_der(mine), public_der(theirs)
    if a < b:
        a, b = b, a
    return hashlib.sha256(a + b + str(int(stamp)).encode()).hexdigest()[:8].upper()


def local_ipv4() -> list:
    """This computer's IPv4 addresses, but not 127.x: the greeting goes out from each, to reach every network."""
    out = []
    try:
        names = [n for _i, n in socket.if_nameindex()]
    except OSError:
        return out
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for name in names:
            try:
                raw = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))       # SIOCGIFADDR
            except OSError:
                continue
            addr = socket.inet_ntoa(raw[20:24])
            if not addr.startswith("127.") and addr not in out:
                out.append(addr)
    return out


def this_kind() -> str:
    """A laptop if it has a battery of its own (not a mouse's or a phone's: those have scope "Device")."""
    for p in Path("/sys/class/power_supply").glob("*"):
        try:
            scope = (p / "scope").read_text().strip() if (p / "scope").exists() else ""
            if (p / "type").read_text().strip() == "Battery" and scope != "Device":
                return "laptop"
        except OSError:
            continue
    return "desktop"


def this_name() -> str:
    try:
        out = subprocess.run(["hostnamectl", "--pretty"], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return clean_name(out or socket.gethostname()) or "Huginn OS"


# ================================================================================================== who we are
class Me:
    """This computer's id, key and certificate (an EC P-256 key; the certificate's common name is the id)."""

    def __init__(self, home: Path, name: str = "", kind: str = ""):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        os.chmod(self.home, 0o700)
        self.key_file, self.cert_file = self.home / "key.pem", self.home / "cert.pem"
        if not (self.key_file.is_file() and self.cert_file.is_file()):
            self._make()
        self.cert_der = pem_to_der(self.cert_file.read_text())
        self.id = common_name(self.cert_der)
        if not ID_OK.match(self.id):
            self._make()
            self.cert_der = pem_to_der(self.cert_file.read_text())
            self.id = common_name(self.cert_der)
        self.name, self.kind = clean_name(name) or "Huginn OS", kind or "desktop"
        self.client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)               # (when the other side opened the connection)
        self.client.check_hostname = False
        self.client.verify_mode = ssl.CERT_NONE                              # their certificate is compared with the pinned one ourselves
        self.client.minimum_version = ssl.TLSVersion.TLSv1_2
        self.client.load_cert_chain(self.cert_file, self.key_file)
        self._servers = {}

    def _make(self) -> None:
        key = ec.generate_private_key(ec.SECP256R1())
        ident = uuid.uuid4().hex
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ident), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Huginn OS"),
                          x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Phone")])
        now = dt.datetime.now(dt.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(int.from_bytes(os.urandom(19), "big") >> 1).not_valid_before(now - dt.timedelta(days=365))
                .not_valid_after(now + dt.timedelta(days=3650)).sign(key, hashes.SHA256()))
        write_private(self.key_file, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        write_private(self.cert_file, cert.public_bytes(serialization.Encoding.PEM))

    def server(self, their_pem: str) -> ssl.SSLContext:
        """For a paired device, when this side opened the connection (or offers a file): TLS's server end, and their
        certificate, and only theirs, accepted."""
        if their_pem not in self._servers:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(self.cert_file, self.key_file)
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN                 # their own certificate is the trust anchor
            ctx.load_verify_locations(cadata=their_pem)
            self._servers[their_pem] = ctx
        return self._servers[their_pem]

    def identity(self, tcp_port: int = 0, target: tuple = None) -> dict:
        body = {"deviceId": self.id, "deviceName": self.name, "deviceType": self.kind, "protocolVersion": PROTOCOL,
                "incomingCapabilities": INCOMING, "outgoingCapabilities": OUTGOING}
        if tcp_port:
            body["tcpPort"] = tcp_port
        if target:
            body["targetDeviceId"], body["targetProtocolVersion"] = target
        return body


def write_private(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def from_kde_connect(home: Path, kde: Path) -> bool:
    """The first time, on a computer that had KDE Connect: its id, key and certificate, and the phones it trusted, so
    phones paired before stay paired."""
    if (home / "cert.pem").exists() or not ((kde / "certificate.pem").is_file() and (kde / "privateKey.pem").is_file()):
        return False
    try:
        cert, key = (kde / "certificate.pem").read_bytes(), (kde / "privateKey.pem").read_bytes()
        if not ID_OK.match(common_name(pem_to_der(cert.decode()))):
            return False
        serialization.load_pem_private_key(key, None)
    except (OSError, ValueError, TypeError):
        return False
    home.mkdir(parents=True, exist_ok=True)
    write_private(home / "key.pem", key)
    write_private(home / "cert.pem", cert)
    devices = {}
    for ident, values in read_ini(kde / "trusted_devices").items():
        pem = values.get("certificate", "")
        if ID_OK.match(ident) and "BEGIN CERTIFICATE" in pem:
            try:
                pem_to_der(pem)
            except ValueError:
                continue
            devices[ident] = {"name": clean_name(values.get("name")) or "Phone", "type": values.get("type", "phone"), "cert": pem,
                              "protocol": number(values.get("protocolVersion"), PROTOCOL)}
    Store(home).save_devices(devices)
    return True


def read_ini(path: Path) -> dict:
    """QSettings' INI: [group] and key=value, a value maybe in quotes and with \\n and \\" escaped."""
    out, group = {}, None
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            group = out.setdefault(line[1:-1], {})
        elif group is not None and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            value = re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t", "r": "\r"}.get(m.group(1), m.group(1)), value)
            group[key.strip()] = value
    return out


class Store:
    """devices.json: the paired devices (name, kind, certificate, protocol, where last seen) and addresses to greet
    directly (for networks that don't pass the greeting along)."""

    def __init__(self, home: Path):
        self.path = Path(home) / "devices.json"

    def load(self) -> dict:
        try:
            got = json.loads(self.path.read_text())
        except (OSError, ValueError):
            got = {}
        got = got if isinstance(got, dict) else {}
        devices = {k: v for k, v in (got.get("devices") or {}).items() if ID_OK.match(k) and isinstance(v, dict) and "BEGIN CERTIFICATE" in str(v.get("cert", ""))}
        return {"devices": devices, "addresses": [str(a) for a in got.get("addresses") or [] if isinstance(a, str)][:32]}

    def save_devices(self, devices: dict) -> None:
        got = self.load()
        got["devices"] = devices
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_private(self.path, json.dumps(got, indent=1).encode())


# =================================================================================================== devices
class Device:
    def __init__(self, ident: str, name: str = "", kind: str = "phone"):
        self.id, self.name, self.kind = ident, clean_name(name) or "Device", kind or "phone"
        self.paired, self.cert_pem, self.protocol, self.address = False, "", PROTOCOL, ""
        self.link = None
        self.battery, self.charging = -1, False
        self.pairing, self.pair_stamp, self.pair_timer, self.key = "", 0, None, ""
        self.sending = asyncio.Lock()
        self.fetching = asyncio.Lock()

    def view(self) -> dict:
        here = self.link is not None
        return {"id": self.id, "name": self.name, "type": self.kind, "paired": self.paired, "here": here,
                "battery": self.battery if here and self.paired else -1, "charging": self.charging and here and self.paired,
                "pairing": self.pairing, "key": self.key if self.pairing else ""}


class Link(asyncio.Protocol):
    """One connection: the greeting in plain text, then TLS, then each side's identity again, then packets, a line each.
    Whoever opened the connection is TLS's server (KDE Connect's way round)."""

    def __init__(self, core, outgoing: tuple = None):
        self.core, self.outgoing = core, outgoing              # outgoing: (their id, their protocol) when we opened it
        self.transport, self.buf, self.phase = None, bytearray(), "plain"
        self.id, self.protocol, self.info, self.cert, self.address = "", 0, {}, b"", ""
        self.replaced, self.timer = False, None
        if outgoing:
            self.id, self.protocol = outgoing

    # ---- the stages
    def connection_made(self, transport) -> None:
        self.transport = transport
        peer = transport.get_extra_info("peername") or ("", 0)
        self.address = str(peer[0])
        sock = transport.get_extra_info("socket")
        if sock is not None:
            with contextlib.suppress(OSError, AttributeError):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if not self.outgoing:
            self.timer = self.core.loop.call_later(5, self.close)               # say who you are, or go

    def data_received(self, data: bytes) -> None:
        self.buf += data
        if self.phase == "plain":
            if b"\n" not in self.buf:
                if len(self.buf) > MAX_IDENTITY:
                    self.close()
                return
            line, _, rest = bytes(self.buf).partition(b"\n")
            self.buf.clear()
            if rest or len(line) > MAX_IDENTITY or not self._greeted(unpack(line)):
                self.close()
                return
            self.phase = "securing"
            self.transport.pause_reading()
            self.core.loop.create_task(self.secure(server_side=False))
        elif self.phase == "identity":
            if b"\n" not in self.buf:
                if len(self.buf) > MAX_IDENTITY:
                    self.close()
                return
            line, _, rest = bytes(self.buf).partition(b"\n")
            self.buf = bytearray(rest)
            got = unpack(line)
            body = got["body"] if got else {}
            if (not got or got["type"] != "kdeconnect.identity" or body.get("deviceId") != self.id or number(body.get("protocolVersion")) < 8
                    or not clean_name(body.get("deviceName"))):
                self.close()
                return
            self._cancel_timer()
            self.info, self.protocol, self.phase = body, number(body.get("protocolVersion")), "ready"
            if not self.core.link_ready(self):
                self.close()
                return
            self._lines()
        elif self.phase == "ready":
            self._lines()

    def _greeted(self, got) -> bool:
        if not got or got["type"] != "kdeconnect.identity":
            return False
        body = got["body"]
        ident, target = str(body.get("deviceId", "")), body.get("targetDeviceId")
        if not ID_OK.match(ident) or ident == self.core.me.id or number(body.get("protocolVersion")) < 8:
            return False
        if target not in (None, "", self.core.me.id) or number(body.get("targetProtocolVersion"), -1) not in (-1, PROTOCOL):
            return False
        self.id, self.protocol = ident, number(body.get("protocolVersion"))
        return True

    async def secure(self, server_side: bool) -> None:
        dev = self.core.devices.get(self.id)
        trusted = dev.cert_pem if dev and dev.paired else ""
        if server_side and not trusted:
            self.close()
            return
        ctx = self.core.me.server(trusted) if server_side else self.core.me.client
        try:
            tls = await asyncio.wait_for(self.core.loop.start_tls(self.transport, self, ctx, server_side=server_side, ssl_handshake_timeout=10), 12)
        except (OSError, ssl.SSLError, asyncio.TimeoutError, ConnectionError, RuntimeError):
            self.close()
            return
        if tls is None:
            self.close()
            return
        self.transport = tls
        sslobj = tls.get_extra_info("ssl_object")
        der = sslobj.getpeercert(binary_form=True) if sslobj else None
        if not der or common_name(der) != self.id or (trusted and der != pem_to_der(trusted)):
            self.close()                                       # not the certificate this device is known by
            return
        self.cert, self.phase = der, "identity"
        self._cancel_timer()
        self.timer = self.core.loop.call_later(5, self.close)
        tls.write(packet("kdeconnect.identity", self.core.me.identity(self.core.tcp_port)))
        if self.buf:
            self.data_received(b"")                            # their identity may have come before this got its turn

    def _lines(self) -> None:
        while self.phase == "ready":
            cut = self.buf.find(b"\n")
            if cut < 0:
                if len(self.buf) > MAX_PACKET:
                    self.close()
                return
            line = bytes(self.buf[:cut])
            del self.buf[:cut + 1]
            got = unpack(line)
            if got:
                try:
                    self.core.received(self, got)
                except Exception as err:                       # one bad packet mustn't end the link
                    log("a packet couldn't be handled:", got.get("type"), repr(err))

    # ---- the rest
    def send(self, kind: str, body: dict, payload: tuple = None) -> bool:
        if self.phase != "ready" or self.transport is None or self.transport.is_closing():
            return False
        self.transport.write(packet(kind, body, payload))
        return True

    def _cancel_timer(self) -> None:
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def close(self) -> None:
        self._cancel_timer()
        if self.transport is not None and not self.transport.is_closing():
            self.transport.abort()

    def connection_lost(self, _exc) -> None:
        self._cancel_timer()
        if self.phase != "securing":                           # (TLS's start hands the connection over and back)
            self.phase = "gone"
            self.core.link_lost(self)


class Greeter(asyncio.DatagramProtocol):
    def __init__(self, core):
        self.core = core

    def datagram_received(self, data: bytes, addr) -> None:
        self.core.greeted(data, addr)


# ====================================================================================================== Core
class Core:
    """The protocol. Everything here runs on one asyncio loop; the desk's answers come in with call_soon_threadsafe."""

    def __init__(self, me: Me, store: Store, desk, *, udp_port=UDP_PORT, tcp_ports=TCP_PORTS, payload_ports=PAYLOAD_PORTS, greet_to: int = UDP_PORT):
        self.me, self.store, self.desk = me, store, desk
        self.udp_port, self.tcp_ports, self.payload_ports, self.greet_to = udp_port, tcp_ports, payload_ports, greet_to
        self.loop = None
        self.devices, self.tcp_port, self.server, self.udp = {}, 0, None, None
        self.seen, self.addresses, self.notes, self.gone = {}, [], {}, set()
        self.snapshot = "[]"
        self.downloads = downloads_folder()
        got = store.load()
        self.addresses = got["addresses"]
        for ident, v in got["devices"].items():
            d = Device(ident, v.get("name"), v.get("type"))
            d.paired, d.cert_pem, d.protocol, d.address = True, v["cert"], number(v.get("protocol"), PROTOCOL), str(v.get("address", ""))
            self.devices[ident] = d
        self._view()

    # ---- starting
    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        for port in self.tcp_ports:
            try:
                self.server = await self.loop.create_server(lambda: Link(self), host=None, port=port, reuse_address=True)
                self.tcp_port = port
                break
            except OSError:
                continue
        if not self.server:
            raise OSError("no free port between %d and %d" % (self.tcp_ports[0], self.tcp_ports[-1]))
        if self.udp_port is not None:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind(("0.0.0.0", self.udp_port))
            self.udp, _ = await self.loop.create_datagram_endpoint(lambda: Greeter(self), sock=s)
        self.broadcast()
        self.loop.create_task(self._watch_networks())

    async def _watch_networks(self) -> None:
        known = local_ipv4()
        while True:
            await asyncio.sleep(20)
            now = local_ipv4()
            if now != known:
                known = now
                self.broadcast()                               # a new network: say hello on it

    def broadcast(self) -> None:
        """The greeting: to everyone on each network this computer is on, and straight to paired devices' last
        addresses and any added by hand."""
        if self.udp_port is None:
            return
        line = packet("kdeconnect.identity", self.me.identity(self.tcp_port))
        for source in local_ipv4():
            with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.bind((source, 0))
                s.sendto(line, ("255.255.255.255", self.greet_to))
        direct = {d.address for d in self.devices.values() if d.paired and d.address} | set(self.addresses)
        for addr in direct:
            with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(line, (addr, self.greet_to))

    # ---- finding each other
    def greeted(self, data: bytes, addr) -> None:
        """A greeting from another device. Paired: connect to it. Not paired: greet it back, so it connects to us
        (then TLS's server end is theirs, and their certificate is seen before anything is trusted)."""
        got = unpack(data[:MAX_IDENTITY]) if len(data) <= MAX_IDENTITY else None
        if not got or got["type"] != "kdeconnect.identity":
            return
        body = got["body"]
        ident, port, version = str(body.get("deviceId", "")), number(body.get("tcpPort")), number(body.get("protocolVersion"))
        if not ID_OK.match(ident) or ident == self.me.id or version < 8 or port not in TCP_PORTS:
            return
        now = time.monotonic()
        if now - self.seen.get(ident, -99) < 2:
            return
        self.seen[ident] = now
        if len(self.seen) > 1024:
            self.seen = {k: v for k, v in self.seen.items() if now - v < 60}
        dev = self.devices.get(ident)
        if dev and dev.link:
            return
        if dev and dev.paired:
            self.loop.create_task(self.connect(addr[0], port, ident, version))
        elif self.udp:
            self.udp.sendto(packet("kdeconnect.identity", self.me.identity(self.tcp_port)), (addr[0], self.greet_to))

    async def connect(self, host: str, port: int, ident: str, version: int) -> None:
        try:
            transport, link = await asyncio.wait_for(self.loop.create_connection(lambda: Link(self, (ident, version)), host, port), 5)
        except (OSError, asyncio.TimeoutError):
            return
        link.phase = "securing"
        transport.write(packet("kdeconnect.identity", self.me.identity(self.tcp_port, (ident, version))))
        await link.secure(server_side=True)                    # (at once: their TLS greeting must find TLS waiting)

    def link_ready(self, link: Link) -> bool:
        dev = self.devices.get(link.id)
        if dev is None:
            if sum(1 for d in self.devices.values() if d.link and not d.paired) >= MAX_UNPAIRED:
                return False
            dev = self.devices[link.id] = Device(link.id)
        dev.name, dev.kind = clean_name(link.info.get("deviceName")) or dev.name, str(link.info.get("deviceType") or dev.kind)
        if dev.link is not None and dev.link is not link:
            old, dev.link = dev.link, None
            old.replaced = True
            old.close()
        dev.link, dev.address = link, link.address
        if dev.paired:
            dev.protocol = link.protocol
            self._save()
            link.send("kdeconnect.mousepad.keyboardstate", {"state": True})     # (the phone's remote shows its keyboard)
        self._view()
        return True

    def link_lost(self, link: Link) -> None:
        dev = self.devices.get(link.id)
        if not dev or dev.link is not link:
            return
        dev.link = None
        if dev.pairing:
            self._pair_over(dev)
        if not dev.paired:
            self.devices.pop(dev.id, None)
        self._view()

    # ---- what arrives
    def received(self, link: Link, got: dict) -> None:
        dev = self.devices.get(link.id)
        if not dev or dev.link is not link:
            return
        kind, body = got["type"], got["body"]
        if kind == "kdeconnect.pair":
            self._pair_packet(dev, body)
            return
        if not dev.paired:
            return                                             # nothing else before pairing
        if kind == "kdeconnect.battery":
            low = number(body.get("thresholdEvent")) == 1 and not body.get("isCharging")
            dev.battery, dev.charging = max(-1, min(100, number(body.get("currentCharge"), -1))), bool(body.get("isCharging"))
            if low:
                self.desk.notify(f"battery:{dev.id}", f"{dev.name}'s battery is low", f"{dev.battery}% left." if dev.battery >= 0 else "", glyph="battery-low")
            self._view()
        elif kind == "kdeconnect.ping":
            self.desk.notify(f"ping:{dev.id}", dev.name, str(body.get("message") or "Ping!"))
        elif kind == "kdeconnect.telephony":
            self._call(dev, body)
        elif kind == "kdeconnect.notification":
            self.loop.create_task(self._phone_note(dev, link, got))
        elif kind == "kdeconnect.share.request":
            self.loop.create_task(self._shared(dev, link, got))
        elif kind == "kdeconnect.clipboard":
            content = body.get("content")
            if isinstance(content, str) and content:
                self.desk.copy(content)
        elif kind == "kdeconnect.mousepad.request":
            self._remote(dev, body)
        elif kind == "kdeconnect.mpris.request":
            self.desk.media(dev.id, body)
        elif kind == "kdeconnect.findmyphone.request":
            self.desk.notify(f"ring:{dev.id}", "Looking for this computer", f"{dev.name} is ringing it. Here it is.", urgency=2, category="call.incoming",
                             actions=[("found", "Found It")])

    def _remote(self, dev: Device, body: dict) -> None:
        """The phone as a remote: its touchpad, buttons, scrolling, keys and typing, to the compositor."""
        if body.get("sendAck"):
            dev.link.send("kdeconnect.mousepad.echo", dict(body, isAck=True))
        clicks = {"singleclick": [(272, True), (272, False)], "doubleclick": [(272, True), (272, False)] * 2,
                  "middleclick": [(274, True), (274, False)], "rightclick": [(273, True), (273, False)],
                  "singlehold": [(272, True)], "singlerelease": [(272, False)]}
        for what, presses in clicks.items():
            if body.get(what):
                for code, down in presses:
                    self.desk.input("PointerButton", "(ub)", (code, down))
                return
        dx, dy = float_or(body.get("dx")), float_or(body.get("dy"))
        if body.get("scroll"):
            if dx or dy:
                self.desk.input("Scroll", "(dd)", (dx, dy))
            return
        special = number(body.get("specialKey"))
        text = body.get("key") if isinstance(body.get("key"), str) else ""
        if (0 < special < len(SPECIAL_KEYS) and SPECIAL_KEYS[special]) or text:
            mods = [code for name, code in (("ctrl", 29), ("alt", 56), ("shift", 42), ("super", 125)) if body.get(name)]
            for code in mods:
                self.desk.input("Key", "(ub)", (code, True))
            if 0 < special < len(SPECIAL_KEYS) and SPECIAL_KEYS[special]:
                self.desk.input("Key", "(ub)", (SPECIAL_KEYS[special], True))
                self.desk.input("Key", "(ub)", (SPECIAL_KEYS[special], False))
            else:
                self.desk.input("TypeText", "(s)", (text[:2000],))
            for code in reversed(mods):
                self.desk.input("Key", "(ub)", (code, False))
            return
        if dx or dy:
            self.desk.input("PointerBy", "(dd)", (dx, dy))

    def media_reply(self, ident: str, body: dict, art: str = "") -> None:
        """From the desk's music players to one phone (`art`: a cover to send along), or to every paired phone in
        reach (ident "")."""
        for dev in list(self.devices.values()):
            if (ident and dev.id != ident) or not dev.paired or not dev.link:
                continue
            if art:
                self.loop.create_task(self.offer(dev, "kdeconnect.mpris", body, Path(art)))
            else:
                dev.link.send("kdeconnect.mpris", body)

    async def offer(self, dev: Device, kind: str, body: dict, path: Path) -> bool:
        """One packet with a file as its payload, on a port of its own (as files are sent; used for covers)."""
        try:
            size = path.stat().st_size
        except OSError:
            return False
        came = asyncio.Queue()
        server, port = None, 0
        for p in self.payload_ports:
            try:
                server = await asyncio.start_server(lambda r, w: came.put_nowait((r, w)), host=None, port=p, ssl=self.me.server(dev.cert_pem),
                                                    ssl_handshake_timeout=15)
                port = p
                break
            except OSError:
                continue
        if not server:
            return False
        try:
            if not dev.link or not dev.link.send(kind, body, (size, port)):
                return False
            _reader, writer = await asyncio.wait_for(came.get(), 20)
            with open(path, "rb") as src:
                while chunk := src.read(1 << 16):
                    writer.write(chunk)
                    await asyncio.wait_for(writer.drain(), 30)
            writer.close()
            return True
        except (OSError, ssl.SSLError, asyncio.TimeoutError, ConnectionError):
            return False
        finally:
            server.close()

    def _call(self, dev: Device, body: dict) -> None:
        event, num = str(body.get("event", "")), str(body.get("phoneNumber", ""))
        name = str(body.get("contactName") or num)
        if body.get("isCancel"):
            event = "ended"
        if event in ("ringing", "talking", "missedCall", "ended"):
            self.desk.call(dev.id, event, num, name)
        if event == "missedCall" and not body.get("isCancel"):
            self.desk.notify(f"missed:{dev.id}:{num}", f"Missed call from {name or 'an unknown number'}", f"On {dev.name}.", glyph="phone")

    async def _phone_note(self, dev: Device, link: Link, got: dict) -> None:
        body = got["body"]
        key = str(body.get("id", ""))
        if not key:
            return
        ident = f"n:{dev.id}:{key}"
        if body.get("isCancel"):
            self.notes.pop(ident, None)
            self.gone.add(ident)
            self.desk.close(ident)
            return
        self.gone.discard(ident)
        if body.get("silent"):
            return                                             # what was already on the phone when it connected
        title, text = str(body.get("title") or body.get("ticker") or ""), str(body.get("text") or "")
        if not title and not text:
            return
        image = ""
        info, size = got.get("payloadTransferInfo"), number(got.get("payloadSize"))
        if isinstance(info, dict) and 0 < size <= MAX_ICON:
            name = re.sub(r"[^A-Za-z0-9]", "", str(body.get("payloadHash") or "")) or hashlib.sha1(key.encode()).hexdigest()
            icon = CACHE / "huginn/phone-icons" / f"{name[:64]}.png"
            if icon.is_file() or await self.fetch(dev, link, number(info.get("port")), size, icon):
                image = str(icon)
        if ident in self.gone:
            self.gone.discard(ident)                           # cleared on the phone while its picture came
            return
        actions = [("act:" + str(a), str(a)) for a in (body.get("actions") or []) if isinstance(a, str) and a][:3]
        reply = str(body.get("requestReplyId") or "")
        self.notes[ident] = {"device": dev.id, "key": key, "clearable": bool(body.get("isClearable")), "reply": reply}
        self.desk.notify(ident, title or str(body.get("appName") or ""), text, app=str(body.get("appName") or dev.name), image=image, actions=actions,
                         reply=bool(reply))

    async def _shared(self, dev: Device, link: Link, got: dict) -> None:
        body = got["body"]
        info, size = got.get("payloadTransferInfo"), number(got.get("payloadSize"), -1)
        if isinstance(info, dict) and info.get("port"):
            name = safe_filename(body.get("filename")) or f"from-{dev.name or 'phone'}-{int(time.time())}"
            async with dev.fetching:
                dest = unique_path(self.downloads, name)
                ok = await self.fetch(dev, link, number(info.get("port")), size, dest)
                if ok:
                    with contextlib.suppress(OSError, TypeError, ValueError):
                        when = number(body.get("lastModified")) / 1000
                        if when > 0:
                            os.utime(dest, (when, when))
                    many = number(body.get("numberOfFiles"), 1)
                    self.desk.notify(f"got:{dev.id}", f"From {dev.name}", f"“{dest.name}” is in Downloads." if many <= 1 else f"{many} files, in Downloads.",
                                     actions=[("open", "Open"), ("folder", "Show in Files")], glyph="download", target=str(dest))
                else:
                    self.desk.notify(f"got:{dev.id}", f"From {dev.name}", f"“{name}” didn't arrive whole.", glyph="download")
        elif isinstance(body.get("url"), str):
            url = body["url"].strip()
            if re.match(r"^https?://", url, re.I):
                self.desk.open(url)
            else:
                self.desk.copy(url)
                self.desk.notify(f"text:{dev.id}", f"From {dev.name}", f"Copied: {url[:200]}")
        elif isinstance(body.get("text"), str):
            self.desk.copy(body["text"])
            self.desk.notify(f"text:{dev.id}", f"Copied, from {dev.name}", body["text"][:240])

    async def fetch(self, dev: Device, link: Link, port: int, size: int, dest: Path) -> bool:
        """A payload: connect to the port they offered, TLS (their certificate must be the paired one), read it into a
        file beside the destination, and put it in place when it's all there."""
        if not (0 < port < 65536) or not dev.cert_pem:
            return False
        part = dest.with_name(dest.name + ".part")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            reader, writer = await asyncio.wait_for(asyncio.open_connection(link.address, port, ssl=self.me.client, server_hostname=None,
                                                                            ssl_handshake_timeout=10), 15)
        except (OSError, ssl.SSLError, asyncio.TimeoutError):
            return False
        try:
            sslobj = writer.get_extra_info("ssl_object")
            if not sslobj or sslobj.getpeercert(binary_form=True) != pem_to_der(dev.cert_pem):
                return False
            got = 0
            with open(part, "wb") as f:
                while size < 0 or got < size:
                    chunk = await asyncio.wait_for(reader.read(1 << 16 if size < 0 else min(1 << 16, size - got)), 60)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
            if size >= 0 and got != size:
                part.unlink(missing_ok=True)
                return False
            os.replace(part, dest)
            return True
        except (OSError, ssl.SSLError, asyncio.TimeoutError, ConnectionError):
            part.unlink(missing_ok=True)
            return False
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(), 2)

    # ---- pairing
    def _pair_packet(self, dev: Device, body: dict) -> None:
        wants = bool(body.get("pair"))
        if not wants:
            if dev.pairing:
                asked = dev.pairing == "asked"
                self._pair_over(dev)
                if asked:
                    self.desk.notify(f"pair:{dev.id}", f"{dev.name} didn't pair", "It was declined on the device.")
            elif dev.paired:
                self._untrust(dev)
                self.desk.notify(f"pair:{dev.id}", f"{dev.name} unpaired", "It was unpaired on the device.")
            self._view()
            return
        if dev.pairing == "asked":
            self._trust(dev)
            return
        if dev.pairing == "asking":
            return
        if dev.paired:
            if "timestamp" not in body:
                return                                         # (an answer to nothing: already paired)
            self._untrust(dev)                                 # they forgot us and ask again: start over
        stamp = number(body.get("timestamp"), -1)
        if "timestamp" in body and abs(stamp - time.time()) > CLOCK_SLACK:
            self.desk.notify(f"pair:{dev.id}", f"{dev.name} couldn't pair", "The two clocks are too far apart. Set both to the right time.")
            dev.link.send("kdeconnect.pair", {"pair": False})
            return
        dev.pairing, dev.pair_stamp = "asking", stamp
        dev.key = verification_key(self.me.cert_der, dev.link.cert, stamp) if stamp >= 0 else ""
        dev.pair_timer = self.loop.call_later(PAIR_TIMEOUT, self._pair_timeout, dev)
        self.desk.pair_asked(dev.id, dev.name, dev.key)
        self.desk.notify(f"pair:{dev.id}", f"Pair with {dev.name}?",
                         (f"Check that it shows {dev.key}. " if dev.key else "") + "Paired, it can send you files and notifications, and you can send to it.",
                         actions=[("accept", "Pair"), ("reject", "Not Now")], urgency=2, glyph="phone")
        self._view()

    def pair(self, ident: str) -> tuple:
        dev = self.devices.get(ident)
        if not dev or not dev.link:
            return False, "That device isn't in reach."
        if dev.paired:
            return True, "Already paired."
        if dev.pairing == "asking":
            return self.answer(ident, True)
        dev.pair_stamp = int(time.time())
        if not dev.link.send("kdeconnect.pair", {"pair": True, "timestamp": dev.pair_stamp}):
            return False, "That device isn't in reach."
        dev.pairing, dev.key = "asked", verification_key(self.me.cert_der, dev.link.cert, dev.pair_stamp)
        if dev.pair_timer:
            dev.pair_timer.cancel()
        dev.pair_timer = self.loop.call_later(PAIR_TIMEOUT, self._pair_timeout, dev)
        self._view()
        return True, f"Accept it on {dev.name}: both should show {dev.key}."

    def answer(self, ident: str, accept: bool) -> tuple:
        dev = self.devices.get(ident)
        if not dev or dev.pairing != "asking" or not dev.link:
            return False, "Nothing is waiting to pair."
        self.desk.close(f"pair:{dev.id}")
        if not accept:
            dev.link.send("kdeconnect.pair", {"pair": False})
            self._pair_over(dev)
            self._view()
            return True, "Not paired."
        if not dev.link.send("kdeconnect.pair", {"pair": True}):
            self._pair_over(dev)
            return False, "That device isn't in reach."
        self._trust(dev)
        return True, f"Paired with {dev.name}."

    def unpair(self, ident: str) -> tuple:
        dev = self.devices.get(ident)
        if not dev:
            return False, "No such device."
        if dev.link:
            dev.link.send("kdeconnect.pair", {"pair": False})
        if dev.pairing:
            self._pair_over(dev)
        self._untrust(dev)
        if not dev.link:
            self.devices.pop(ident, None)
        self._view()
        return True, "Unpaired."

    def _trust(self, dev: Device) -> None:
        self._pair_over(dev)
        dev.paired, dev.cert_pem, dev.protocol = True, der_to_pem(dev.link.cert), dev.link.protocol
        self._save()
        dev.link.send("kdeconnect.mousepad.keyboardstate", {"state": True})
        self.desk.close(f"pair:{dev.id}")
        self.desk.notify(f"pair:{dev.id}", f"Paired with {dev.name}", "Open Phone to send it something.", glyph="phone")
        self._view()

    def _untrust(self, dev: Device) -> None:
        dev.paired, dev.cert_pem, dev.battery, dev.charging = False, "", -1, False
        self._save()

    def _pair_over(self, dev: Device) -> None:
        if dev.pair_timer:
            dev.pair_timer.cancel()
        dev.pairing, dev.pair_timer, dev.key = "", None, ""
        self.desk.close(f"pair:{dev.id}")

    def _pair_timeout(self, dev: Device) -> None:
        if dev.pairing:
            if dev.link:
                dev.link.send("kdeconnect.pair", {"pair": False})
            self._pair_over(dev)
            self._view()

    def _save(self) -> None:
        self.store.save_devices({d.id: {"name": d.name, "type": d.kind, "cert": d.cert_pem, "protocol": d.protocol, "address": d.address}
                                 for d in self.devices.values() if d.paired})

    # ---- sending
    def _ready(self, ident: str):
        dev = self.devices.get(ident)
        if not dev or not dev.paired:
            return None, "Pair with it first."
        if not dev.link:
            return None, f"{dev.name} isn't in reach. Open KDE Connect on it, on the same network."
        return dev, ""

    def send(self, ident: str, kind: str, body: dict, good: str) -> tuple:
        dev, why = self._ready(ident)
        if not dev:
            return False, why
        return (True, good) if dev.link.send(kind, body) else (False, f"{dev.name} isn't in reach.")

    def ring(self, ident):
        return self.send(ident, "kdeconnect.findmyphone.request", {}, "Ringing it.")

    def ping(self, ident, message=""):
        return self.send(ident, "kdeconnect.ping", {"message": message} if message else {}, "Sent a ping.")

    def share_text(self, ident, text):
        return self.send(ident, "kdeconnect.share.request", {"text": text[:100000]}, "Sent.")

    def share_url(self, ident, url):
        return self.send(ident, "kdeconnect.share.request", {"url": url}, "The link is opening on it.")

    def clipboard(self, ident, text):
        if not text:
            return False, "The clipboard is empty."
        return self.send(ident, "kdeconnect.clipboard", {"content": text[:100000]}, "Clipboard sent.")

    def mute(self, ident):
        return self.send(ident, "kdeconnect.telephony.request_mute", {"action": "mute"}, "Silenced.")

    def sms(self, ident, num, text):
        if not num or not text:
            return False, "A number and a message, please."
        return self.send(ident, "kdeconnect.sms.request", {"version": 2, "addresses": [{"address": num}], "phoneNumber": num, "sendSms": True,
                                                            "messageBody": text}, "Sent.")

    async def send_files(self, ident: str, paths: list) -> tuple:
        """Each file offered on a port of its own range; the device connects, TLS (the paired certificate only), and
        the bytes follow. One batch to a device at a time."""
        dev, why = self._ready(ident)
        if not dev:
            return False, why
        files = [Path(p) for p in paths if Path(p).is_file()]
        if not files:
            return False, "Nothing to send."
        async with dev.sending:
            came = asyncio.Queue()
            server, port = None, 0
            for p in self.payload_ports:
                try:
                    server = await asyncio.start_server(lambda r, w: came.put_nowait((r, w)), host=None, port=p, ssl=self.me.server(dev.cert_pem),
                                                        ssl_handshake_timeout=15)
                    port = p
                    break
                except OSError:
                    continue
            if not server:
                return False, "No free port to send from."
            total = sum(f.stat().st_size for f in files)
            try:
                for f in files:
                    st = f.stat()
                    body = {"filename": f.name, "lastModified": int(st.st_mtime * 1000), "creationTime": int(st.st_mtime * 1000), "open": False,
                            "numberOfFiles": len(files), "totalPayloadSize": total}
                    if not dev.link or not dev.link.send("kdeconnect.share.request", body, (st.st_size, port)):
                        return False, f"{dev.name} went out of reach."
                    try:
                        reader, writer = await asyncio.wait_for(came.get(), 30)
                    except asyncio.TimeoutError:
                        return False, f"{dev.name} didn't take “{f.name}”."
                    try:
                        with open(f, "rb") as src:
                            while chunk := src.read(1 << 16):
                                writer.write(chunk)
                                await asyncio.wait_for(writer.drain(), 60)
                        writer.close()
                        with contextlib.suppress(Exception):
                            await asyncio.wait_for(writer.wait_closed(), 10)
                    except (OSError, ssl.SSLError, asyncio.TimeoutError, ConnectionError):
                        return False, f"“{f.name}” didn't go."
                return True, f"Sent “{files[0].name}”." if len(files) == 1 else f"Sent {len(files)} files."
            finally:
                server.close()

    # ---- the desk's answers (notification buttons, replies, closing)
    def notice(self, ident: str, kind: str, value: str = "") -> None:
        parts = ident.split(":")
        if ident.startswith("pair:") and kind == "action":
            self.answer(parts[1], value == "accept")
        elif ident.startswith("pair:") and kind == "closed" and value == "2":
            dev = self.devices.get(parts[1])
            if dev and dev.pairing == "asking":
                self.answer(dev.id, False)
        elif ident.startswith("n:") and ident in self.notes:
            note = self.notes[ident]
            dev = self.devices.get(note["device"])
            link = dev.link if dev and dev.paired else None
            if kind == "closed":
                self.notes.pop(ident, None)
                if value == "2" and note["clearable"] and link:
                    link.send("kdeconnect.notification.request", {"cancel": note["key"]})
            elif kind == "reply" and note["reply"] and link:
                link.send("kdeconnect.notification.reply", {"requestReplyId": note["reply"], "message": value})
            elif kind == "action" and value.startswith("act:") and link:
                link.send("kdeconnect.notification.action", {"key": note["key"], "action": value[4:]})

    def _view(self) -> None:
        order = sorted(self.devices.values(), key=lambda d: (not d.paired, d.link is None, d.name.lower()))
        snap = json.dumps([d.view() for d in order], sort_keys=True)
        if snap != self.snapshot:
            self.snapshot = snap
            self.desk.changed()


# KDE Connect's remote keys (specialKey), as evdev codes: Backspace, Tab, Linefeed, the arrows, Page Up and Down, Home,
# End, Enter, Delete, Escape, SysRq, Scroll Lock, Ctrl, Alt, Shift, Super, F1-F12
SPECIAL_KEYS = [0, 14, 15, 101, 105, 103, 106, 108, 104, 109, 102, 107, 28, 111, 1, 99, 70, 29, 56, 42, 125,
                59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 87, 88]


def float_or(value, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out and abs(out) < 1e6 else default


def safe_filename(name) -> str:
    name = os.path.basename(str(name or "").replace("\\", "/")).strip().lstrip(".")
    name = re.sub(r"[\x00-\x1f/]", "", name)
    return name[:200]


def unique_path(folder: Path, name: str) -> Path:
    p = folder / name
    stem, ext = os.path.splitext(name)
    n = 2
    while p.exists() or p.with_name(p.name + ".part").exists():
        p = folder / f"{stem} ({n}){ext}"
        n += 1
    return p


def downloads_folder() -> Path:
    try:
        out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return Path(out) if out and out != str(Path.home()) else Path.home() / "Downloads"


# ====================================================================================================== Desk
XML = """<node><interface name="org.huginn.Phone">
  <method name="Devices"><arg type="s" direction="out"/></method>
  <method name="Refresh"/>
  <method name="Pair"><arg type="s" name="id" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  <method name="Unpair"><arg type="s" name="id" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  <method name="Answer"><arg type="s" name="id" direction="in"/><arg type="b" name="accept" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  <method name="Ring"><arg type="s" name="id" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  <method name="Ping"><arg type="s" name="id" direction="in"/><arg type="s" name="message" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  <method name="SendText"><arg type="s" name="id" direction="in"/><arg type="s" name="text" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  <method name="SendUrl"><arg type="s" name="id" direction="in"/><arg type="s" name="url" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  <method name="SendClipboard"><arg type="s" name="id" direction="in"/><arg type="s" name="text" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  <method name="SendFiles"><arg type="s" name="id" direction="in"/><arg type="as" name="paths" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  <method name="SendSms"><arg type="s" name="id" direction="in"/><arg type="s" name="number" direction="in"/><arg type="s" name="text" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  <method name="Mute"><arg type="s" name="id" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  <signal name="Changed"/>
  <signal name="Call"><arg type="s" name="id"/><arg type="s" name="event"/><arg type="s" name="number"/><arg type="s" name="name"/></signal>
  <signal name="PairAsked"><arg type="s" name="id"/><arg type="s" name="name"/><arg type="s" name="key"/></signal>
</interface></node>"""
NAME, PATH, IFACE = "org.huginn.Phone", "/org/huginn/Phone", "org.huginn.Phone"
GLYPHS = {"phone": "phone", "battery-low": "battery-caution", "download": "folder-download"}


class Desk:
    """GLib's side: the D-Bus service, Huginn's notifications, the clipboard, opening things. Called from the core's
    thread; everything is passed over with GLib.idle_add."""

    def __init__(self):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.core, self.bus = None, None
        self.ids, self.keys, self.targets = {}, {}, {}           # our key -> notification id, and back; key -> file
        self.music = None

    def attach(self, core: Core, bus) -> None:
        Gio = self.Gio
        self.core, self.bus = core, bus
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        bus.register_object(PATH, node.interfaces[0], self._method, None, None)
        for signal in ("ActionInvoked", "NotificationClosed", "NotificationReplied"):
            bus.signal_subscribe(None, "org.freedesktop.Notifications", signal, "/org/freedesktop/Notifications", None, Gio.DBusSignalFlags.NONE, self._noted)
        self.music = Music(bus, lambda ident, body, art="": core.loop.call_soon_threadsafe(core.media_reply, ident, body, art))

    # ---- the core asks
    def _idle(self, fn, *args) -> None:
        self.GLib.idle_add(lambda: (fn(*args), False)[1])

    def changed(self) -> None:
        self._idle(self._emit, "Changed", None)

    def call(self, ident, event, num, name) -> None:
        self._idle(self._emit, "Call", self.GLib.Variant("(ssss)", (ident, event, num, name)))

    def pair_asked(self, ident, name, key) -> None:
        self._idle(self._emit, "PairAsked", self.GLib.Variant("(sss)", (ident, name, key)))

    def notify(self, key, summary, body, app="Phone", image="", actions=(), reply=False, urgency=1, category="", glyph="phone", target="") -> None:
        self._idle(self._notify, key, summary, body, app, image, list(actions), reply, urgency, category, glyph, target)

    def close(self, key) -> None:
        self._idle(self._close, key)

    def copy(self, text) -> None:
        threading.Thread(target=self._copy, args=(text,), daemon=True).start()

    def input(self, method: str, sig: str, args: tuple) -> None:
        """The phone as a remote: to the compositor's keys and mouse from afar (in order; nothing waits)."""
        self._idle(self._input, method, sig, args)

    def media(self, ident: str, body: dict) -> None:
        """A phone's media controls, to the music players here."""
        self._idle(lambda: self.music and self.music.handle(ident, body))

    def open(self, uri) -> None:
        threading.Thread(target=lambda: subprocess.run(["xdg-open", uri], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                         daemon=True).start()

    # ---- on GLib's side
    def _input(self, method, sig, args) -> None:
        self.bus.call("org.huginn.Compositor", "/org/huginn/Compositor", "org.huginn.Compositor", method, self.GLib.Variant(sig, args), None,
                      self.Gio.DBusCallFlags.NO_AUTO_START, 2000, None, None, None)

    def _emit(self, signal, params) -> None:
        with contextlib.suppress(Exception):
            self.bus.emit_signal(None, PATH, IFACE, signal, params)

    def _notify(self, key, summary, body, app, image, actions, reply, urgency, category, glyph, target) -> None:
        GLib = self.GLib
        flat = []
        for k, label in actions:
            flat += [k, label]
        if reply:
            flat += ["inline-reply", "Reply"]
        hints = {"urgency": GLib.Variant("y", urgency), "desktop-entry": GLib.Variant("s", "huginn-phone")}
        if image:
            hints["image-path"] = GLib.Variant("s", image)
        if category:
            hints["category"] = GLib.Variant("s", category)
        if target:
            self.targets[key] = target
        args = GLib.Variant("(susssasa{sv}i)", (app, self.ids.get(key, 0), GLYPHS.get(glyph, glyph), summary, body, flat, hints, -1))

        def done(bus, res):
            try:
                nid = bus.call_finish(res).unpack()[0]
            except Exception:
                return
            self.ids[key], self.keys[nid] = nid, key
        self.bus.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify", args,
                      GLib.VariantType("(u)"), self.Gio.DBusCallFlags.NONE, 5000, None, done)

    def _close(self, key) -> None:
        nid = self.ids.pop(key, 0)
        if nid:
            self.keys.pop(nid, None)
            self.bus.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "CloseNotification",
                          self.GLib.Variant("(u)", (nid,)), None, self.Gio.DBusCallFlags.NONE, 2000, None, None)

    def _noted(self, _c, _s, _p, _i, signal, params) -> None:
        nid, value = params.unpack()
        key = self.keys.get(nid)
        if not key:
            return
        if signal == "NotificationClosed":
            self.keys.pop(nid, None)
            self.ids.pop(key, None)
            kind, value = "closed", str(value)
        elif signal == "NotificationReplied":
            kind = "reply"
        else:
            kind = "action"
            if key.startswith("got:") and value in ("open", "folder", "default"):
                target = self.targets.get(key, "")
                if target:
                    self.open(Path(target).as_uri() if value != "folder" else Path(target).parent.as_uri())
                return
        self.core.loop.call_soon_threadsafe(self.core.notice, key, kind, str(value))

    @staticmethod
    def _copy(text) -> None:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(["wl-copy", "--", text], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)

    def _method(self, _conn, _sender, _path, _iface, method, params, invocation) -> None:
        GLib, core = self.GLib, self.core
        args = params.unpack()
        if method == "Devices":
            invocation.return_value(GLib.Variant("(s)", (core.snapshot,)))
            return
        if method == "Refresh":
            core.loop.call_soon_threadsafe(core.broadcast)
            invocation.return_value(None)
            return
        plain = {"Pair": core.pair, "Unpair": core.unpair, "Answer": core.answer, "Ring": core.ring, "Ping": core.ping, "SendText": core.share_text,
                 "SendUrl": core.share_url, "SendClipboard": core.clipboard, "SendSms": core.sms, "Mute": core.mute}
        if method == "SendFiles":
            future = asyncio.run_coroutine_threadsafe(core.send_files(*args), core.loop)
        elif method in plain:
            async def run():
                return plain[method](*args)
            future = asyncio.run_coroutine_threadsafe(run(), core.loop)
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
            return

        def answer(f):
            try:
                ok, msg = f.result()
            except Exception as err:
                ok, msg = False, f"That didn't work ({type(err).__name__})."
            GLib.idle_add(lambda: (invocation.return_value(GLib.Variant("(bs)", (bool(ok), str(msg)))), False)[1])
        future.add_done_callback(answer)


class Music:
    """The music players here (MPRIS), for a phone's media controls: their list, what each is playing, and play, pause,
    skip, seek, volume, repeat and shuffle; a cover that's a file here goes to the phone. Changes are passed on as
    they happen. (On GLib's side; `reply(ident, body, art)` sends to one phone, or to all with ident "".)"""
    PREFIX = "org.mpris.MediaPlayer2."
    PATH = "/org/mpris/MediaPlayer2"
    ACTIONS = {"Play", "Pause", "PlayPause", "Stop", "Next", "Previous"}

    def __init__(self, bus, reply):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib, self.bus, self.reply = Gio, GLib, bus, reply
        self.players, self.owners, self.listed, self.soon = {}, {}, None, False
        flags = Gio.DBusSignalFlags.NONE
        bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus", None, flags, self._owner)
        bus.signal_subscribe(None, "org.freedesktop.DBus.Properties", "PropertiesChanged", self.PATH, None, flags, self._changed)
        bus.signal_subscribe(None, "org.mpris.MediaPlayer2.Player", "Seeked", self.PATH, None, flags, self._seeked)
        self._refresh()

    def _call(self, dest, iface, method, args=None, reply=None, path=None):
        try:
            got = self.bus.call_sync(dest, path or self.PATH, iface, method, args, self.GLib.VariantType(reply) if reply else None,
                                     self.Gio.DBusCallFlags.NO_AUTO_START, 1500, None)
        except Exception:
            return None
        return got.unpack() if got is not None else ()

    def _refresh(self) -> None:
        self.soon = False
        names = (self._call("org.freedesktop.DBus", "org.freedesktop.DBus", "ListNames", reply="(as)", path="/org/freedesktop/DBus") or ([],))[0]
        players, owners = {}, {}
        for name in sorted(n for n in names if n.startswith(self.PREFIX) and not n.startswith(self.PREFIX + "kdeconnect.") and n != self.PREFIX + "playerctld"):
            got = self._call(name, "org.freedesktop.DBus.Properties", "Get", self.GLib.Variant("(ss)", ("org.mpris.MediaPlayer2", "Identity")), "(v)")
            shown = str(got[0]) if got and got[0] else name[len(self.PREFIX):]
            unique, n = shown, 2
            while unique in players:
                unique, n = f"{shown} [{n}]", n + 1
            players[unique] = name
            owner = self._call("org.freedesktop.DBus", "org.freedesktop.DBus", "GetNameOwner", self.GLib.Variant("(s)", (name,)), "(s)",
                               "/org/freedesktop/DBus")
            if owner:
                owners[owner[0]] = unique
        self.players, self.owners = players, owners
        listed = sorted(players)
        if listed != self.listed:
            self.listed = listed
            self.reply("", self.player_list())

    def player_list(self) -> dict:
        return {"playerList": sorted(self.players), "supportAlbumArtPayload": True}

    def _owner(self, _c, _s, _p, _i, _sig, params) -> None:
        name = params.unpack()[0]
        if name.startswith(self.PREFIX) and not self.soon:
            self.soon = True
            self.GLib.timeout_add(300, lambda: (self._refresh(), False)[1])        # (a player starting registers more than once)

    def _changed(self, _c, sender, _p, _i, _sig, params) -> None:
        iface = params.unpack()[0]
        player = self.owners.get(sender)
        if player and iface == "org.mpris.MediaPlayer2.Player":
            self.reply("", self.now_playing(player))

    def _seeked(self, _c, sender, _p, _i, _sig, params) -> None:
        player = self.owners.get(sender)
        if player:
            self.reply("", {"player": player, "pos": int(params.unpack()[0]) // 1000})

    def _props(self, player: str) -> dict:
        got = self._call(self.players[player], "org.freedesktop.DBus.Properties", "GetAll", self.GLib.Variant("(s)", ("org.mpris.MediaPlayer2.Player",)), "(a{sv})")
        return got[0] if got else {}

    def now_playing(self, player: str) -> dict:
        """What KDE Connect's apps expect: the song, where in it, and what can be done (times in milliseconds)."""
        p = self._props(player)
        meta = p.get("Metadata") or {}
        artist = meta.get("xesam:artist") or []
        url = str(meta.get("xesam:url") or "")
        title, album = str(meta.get("xesam:title") or ""), str(meta.get("xesam:album") or "")
        if not title and not artist and url.startswith("file://"):
            parts = url.rstrip("/").split("/")
            title = self.GLib.uri_unescape_string(parts[-1], None) or parts[-1]
            album = album or (self.GLib.uri_unescape_string(parts[-2], None) if len(parts) > 3 else "")
        length = meta.get("mpris:length")
        out = {"player": player, "title": title, "artist": ", ".join(artist) if isinstance(artist, list) else str(artist), "album": album,
               "albumArtUrl": str(meta.get("mpris:artUrl") or ""), "url": url, "length": int(length) // 1000 if isinstance(length, (int, float)) else -1,
               "pos": int(p.get("Position") or 0) // 1000, "isPlaying": p.get("PlaybackStatus") == "Playing",
               "canPause": bool(p.get("CanPause")), "canPlay": bool(p.get("CanPlay")), "canGoNext": bool(p.get("CanGoNext")),
               "canGoPrevious": bool(p.get("CanGoPrevious")), "canSeek": bool(p.get("CanSeek"))}
        if "Volume" in p:
            out["volume"] = int(round(float(p["Volume"]) * 100))
        if "LoopStatus" in p:
            out["loopStatus"] = str(p["LoopStatus"])
        if "Shuffle" in p:
            out["shuffle"] = bool(p["Shuffle"])
        return out

    def _set(self, player: str, prop: str, value) -> None:
        self._call(self.players[player], "org.freedesktop.DBus.Properties", "Set",
                   self.GLib.Variant("(ssv)", ("org.mpris.MediaPlayer2.Player", prop, value)))

    def handle(self, ident: str, body: dict) -> None:
        GLib = self.GLib
        player = body.get("player") if isinstance(body.get("player"), str) else ""
        if "albumArtUrl" in body:
            # a cover asked for: only the one this player says it has, and only a file here
            art = str(body.get("albumArtUrl") or "")
            if player in self.players and art.startswith("file://") and art == self.now_playing(player)["albumArtUrl"]:
                path = Path(GLib.filename_from_uri(art)[0])
                if path.is_file():
                    self.reply(ident, {"transferringAlbumArt": True, "player": player, "albumArtUrl": art}, str(path))
            return
        if player not in self.players or body.get("requestPlayerList"):
            self.reply(ident, self.player_list())
            if player not in self.players:
                return
        name = self.players[player]
        action = body.get("action")
        if isinstance(action, str) and action in self.ACTIONS:
            self._call(name, "org.mpris.MediaPlayer2.Player", action)
        if body.get("setLoopStatus") in ("None", "Track", "Playlist"):
            self._set(player, "LoopStatus", GLib.Variant("s", body["setLoopStatus"]))
        if isinstance(body.get("setShuffle"), bool):
            self._set(player, "Shuffle", GLib.Variant("b", body["setShuffle"]))
        if isinstance(body.get("setVolume"), (int, float)):
            self._set(player, "Volume", GLib.Variant("d", max(0.0, min(1.0, float(body["setVolume"]) / 100))))
        if isinstance(body.get("Seek"), (int, float)):
            self._call(name, "org.mpris.MediaPlayer2.Player", "Seek", GLib.Variant("(x)", (int(body["Seek"]),)))
        if isinstance(body.get("SetPosition"), (int, float)):
            track = (self._props(player).get("Metadata") or {}).get("mpris:trackid")
            if track:
                self._call(name, "org.mpris.MediaPlayer2.Player", "SetPosition", GLib.Variant("(ox)", (str(track), max(0, int(body["SetPosition"])) * 1000)))
        if body.get("requestNowPlaying") or body.get("requestVolume"):
            self.reply(ident, self.now_playing(player))


def name_process(name: str) -> None:
    with contextlib.suppress(Exception):
        import ctypes
        ctypes.CDLL(None).prctl(15, name.encode()[:15], 0, 0, 0)          # PR_SET_NAME


def main() -> int:
    from gi.repository import Gio, GLib
    name_process("huginn-phoned")
    home = CONFIG / "huginn/phone"
    if from_kde_connect(home, CONFIG / "kdeconnect"):
        log("brought KDE Connect's id and paired devices along")
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    got = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName", GLib.Variant("(su)", (NAME, 4)),
                        GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
    if got not in (1, 4):                                      # (another copy has it: that one carries on)
        return 0
    me = Me(home, this_name(), this_kind())
    desk = Desk()
    core = Core(me, Store(home), desk)
    loop = asyncio.new_event_loop()
    started = threading.Event()
    failed = []

    def network():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(core.start())
        except OSError as err:
            failed.append(str(err))
            started.set()
            return
        started.set()
        loop.run_forever()
    threading.Thread(target=network, daemon=True, name="phone-link").start()
    started.wait(15)
    if failed:
        log("can't listen:", failed[0])
        return 1
    desk.attach(core, bus)
    main_loop = GLib.MainLoop()
    log(f"{me.name} ({me.id}) listening on {core.tcp_port}")
    with contextlib.suppress(KeyboardInterrupt):
        main_loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
