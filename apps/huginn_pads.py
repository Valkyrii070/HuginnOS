"""Game controllers for Settings › Controllers: the ones connected (the kernel's list of input devices, those a
joystick handler took), how they're connected, their battery, and a tester that shows every button, stick and
trigger as it's pressed, read straight from the controller's event device (the person at the computer may read a
controller: systemd's uaccess rule for joysticks).

The kernel's names for a pad's parts are positions (BTN_SOUTH is the bottom face button: A, or Cross); the test
view draws them where they are on the pad, with the face buttons' marks a Sony or a Nintendo pad has."""

from __future__ import annotations

import fcntl
import os
import struct
from pathlib import Path

from PySide6.QtCore import Property, QObject, QSocketNotifier, QTimer, Signal, Slot

EV_KEY, EV_ABS = 0x01, 0x03
EVENT = struct.Struct("qqHHi")                       # struct input_event on 64-bit Linux
ABSINFO = struct.Struct("iiiiii")                    # value, minimum, maximum, fuzz, flat, resolution
VENDORS = {"054c": "sony", "045e": "xbox", "057e": "nintendo", "28de": "steam", "2dc8": "8bitdo", "0f0d": "hori", "0e6f": "pdp", "24c6": "powera"}
# the parts the test view draws: kernel button codes and axes, by the name the view uses
BUTTONS = {0x130: "south", 0x131: "east", 0x133: "north", 0x134: "west", 0x136: "lb", 0x137: "rb", 0x138: "lt", 0x139: "rt",
           0x13a: "select", 0x13b: "start", 0x13c: "home", 0x13d: "ls", 0x13e: "rs",
           0x220: "up", 0x221: "down", 0x222: "left", 0x223: "right"}
AXES = {0x00: "lx", 0x01: "ly", 0x03: "rx", 0x04: "ry", 0x02: "lt", 0x05: "rt", 0x10: "hatx", 0x11: "haty"}


def _ioc_read(nr: int, size: int) -> int:
    return (2 << 30) | (size << 16) | (ord("E") << 8) | nr


def list_controllers(root: Path = Path("/")) -> list[dict]:
    """The connected game controllers: name, kind (sony, xbox, nintendo, steam, other), USB or Bluetooth, battery
    and whether it's charging, and the event device to test it with. A pad's motion sensors and touchpad are
    devices of their own, left out."""
    try:
        text = (root / "proc/bus/input/devices").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    pads = []
    for block in text.split("\n\n"):
        info = {}
        for line in block.splitlines():
            kind, _, rest = line.partition(": ")
            info.setdefault(kind, rest)
        handlers = info.get("H", "").split("=", 1)[-1].split()
        event = next((h for h in handlers if h.startswith("event")), "")
        if not event or not any(h.startswith("js") for h in handlers):
            continue
        name = info.get("N", "").split("=", 1)[-1].strip('"')
        if any(w in name for w in ("Motion Sensors", "Touchpad", "IMU", "Accelerometer")):
            continue
        ident = dict(p.split("=", 1) for p in info.get("I", "").split() if "=" in p)
        vendor = ident.get("Vendor", "").lower()
        bus = ident.get("Bus", "")
        pad = {"id": event, "name": name or "Game controller", "kind": VENDORS.get(vendor, "other"),
               "conn": {"0005": "Bluetooth", "0003": "USB"}.get(bus, "Connected"), "battery": -1, "charging": False,
               "path": str(Path("/dev/input") / event)}
        sysfs = info.get("S", "").split("=", 1)[-1]
        if sysfs:
            here = root / "sys" / sysfs.lstrip("/")
            for folder in (here.parent.parent, here.parent, here):            # the HID device holds its battery
                cap = sorted(folder.glob("power_supply/*/capacity"))
                if cap:
                    try:
                        pad["battery"] = int(cap[0].read_text().strip())
                        pad["charging"] = (cap[0].parent / "status").read_text().strip() in ("Charging", "Full")
                    except (OSError, ValueError):
                        pass
                    break
        pads.append(pad)
    return pads


class PadTester(QObject):
    """Shows one controller's buttons, sticks and triggers as they move: its event device, read as it speaks."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fd = -1
        self._note: QSocketNotifier | None = None
        self._ranges: dict[int, tuple[int, int]] = {}
        self._pressed: set[str] = set()
        self._axes: dict[str, float] = {}
        self._error = ""
        self._dirty = False
        self._pretend = False
        self._tick = QTimer(self, interval=33, timeout=self._flush)  # the view, about 30 times a second

    def _get(self) -> dict:
        return {"open": self._fd >= 0 or self._pretend, "error": self._error, "pressed": sorted(self._pressed), "axes": dict(self._axes)}

    state = Property("QVariantMap", _get, notify=changed)

    @Slot(str)
    def start(self, path: str) -> None:
        self.stop()
        self._error = ""
        if not path.startswith("/dev/input/event"):
            return
        try:
            self._fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            self._error = "Huginn OS isn't allowed to read this controller." if e.errno in (1, 13) else "The controller went away."
            self.changed.emit()
            return
        for code, name in AXES.items():
            try:
                buf = fcntl.ioctl(self._fd, _ioc_read(0x40 + code, ABSINFO.size), bytes(ABSINFO.size))
                value, lo, hi, *_ = ABSINFO.unpack(buf)
                if hi > lo:
                    self._ranges[code] = (lo, hi)
                    self._axes[name] = self._scale(code, value)
            except OSError:
                pass
        self._note = QSocketNotifier(self._fd, QSocketNotifier.Read, self)
        self._note.activated.connect(self._read)
        self._tick.start()
        self.changed.emit()

    @Slot()
    def pretend(self) -> None:
        """A controller that isn't there, at rest (Settings' demo, and pictures: feed() moves it)."""
        self.stop()
        self._pretend = True
        for code, name in AXES.items():
            lo, hi = (-1, 1) if name in ("hatx", "haty") else (0, 255) if name in ("lt", "rt") else (-32768, 32767)
            self._ranges[code] = (lo, hi)
            self._axes[name] = 0.0
        self._tick.start()
        self.changed.emit()

    @Slot()
    def stop(self) -> None:
        self._pretend = False
        self._tick.stop()
        if self._note is not None:
            self._note.setEnabled(False)
            self._note.deleteLater()
            self._note = None
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
        self._ranges.clear()
        self._pressed.clear()
        self._axes.clear()
        self.changed.emit()

    def _scale(self, code: int, value: int) -> float:
        lo, hi = self._ranges.get(code, (0, 1))
        name = AXES.get(code, "")
        if name in ("lt", "rt"):                    # triggers: 0 at rest to 1 pressed
            return round((value - lo) / (hi - lo), 3)
        if name in ("hatx", "haty"):
            return float(max(-1, min(1, value)))
        return round(2 * (value - lo) / (hi - lo) - 1, 3)   # sticks: -1 to 1, 0 in the middle

    def _read(self, *_):
        while True:
            try:
                data = os.read(self._fd, EVENT.size * 64)
            except BlockingIOError:
                break
            except OSError:                          # unplugged
                self._error = "The controller went away."
                self.stop()
                return
            if not data:
                break
            for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                self.feed(*EVENT.unpack_from(data, i)[2:])

    def feed(self, kind: int, code: int, value: int) -> None:
        """One event from the controller (also how tests speak to it)."""
        if kind == EV_KEY and code in BUTTONS:
            (self._pressed.add if value else self._pressed.discard)(BUTTONS[code])
            self._dirty = True
        elif kind == EV_ABS and code in AXES:
            self._axes[AXES[code]] = self._scale(code, value)
            self._dirty = True

    def set_range(self, code: int, lo: int, hi: int) -> None:   # tests: an axis's range without a device
        self._ranges[code] = (lo, hi)

    def _flush(self) -> None:
        if self._dirty:
            self._dirty = False
            self.changed.emit()
