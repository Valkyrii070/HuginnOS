#!/usr/bin/env python3
"""System Monitor's backend: what the computer is doing, read from /proc and /sys every two seconds on a thread of its
own (so the window never waits on it), and what you can do about a program.

- vitals: the processor, memory, graphics card, disks and network now, each with the last two minutes;
- apps: the processes put together the way you think of them: an app is one row (the browser and its helpers, a
  Huginn app, a Flatpak, a Steam game by its name), then the session's helpers ("Background"), then everyone else's
  ("System"); each with its processor, memory, graphics and disk use;
- rows: every process, for the Processes view;
- cpu / mem / gpu / disks / nets: the Performance view's detail.

Processor use is the share of the whole processor (all cores), so the rows add up to the number at the top. Memory is
what a process has to itself plus its share of what it shares (PSS) where it can be read, else its resident size.
Graphics is the share of the card's time a process used, from the driver's per-process counters (amdgpu, i915/xe,
nouveau's fdinfo), for your own processes.
"""
import datetime as dt
import os
import re
import signal
import socket
import struct
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

HERE = Path(__file__).resolve().parent
POINTS = 60                       # two minutes at one reading every two seconds
SESSION = {"huginn-session", "huginn-compositor", "huginn-shell", "huginn-sessiond", "systemd", "sh", "bash", "dbus-daemon",
           "dbus-broker", "sddm-helper", "sddm", "login", "gamescope", "gamescope-wl", "kwin_wayland", "plasmashell"}
SHELLS = {"bash", "sh", "zsh", "fish", "dash"}
# the session's helpers: a name you can recognise and what each does
KNOWN = {
    "huginn-compositor": ("Huginn's compositor", "Draws every window on the screens"),
    "huginn-shell": ("Huginn Shell", "The top bar, the dock, the start menu and the control centre"),
    "huginn-sessiond": ("Huginn session", "Sign-in, the lock screen, idle and power"),
    "huginn-session": ("Huginn session", "Starts and watches the desktop"),
    "Xwayland": ("Xwayland", "Shows older apps (X11) on Huginn's compositor"),
    "pipewire": ("PipeWire", "Sound and screen sharing"),
    "pipewire-pulse": ("PipeWire for PulseAudio apps", "Sound for apps made for PulseAudio"),
    "wireplumber": ("WirePlumber", "Chooses the speakers and microphones"),
    "dbus-daemon": ("D-Bus", "Lets programs talk to each other"),
    "dbus-broker": ("D-Bus", "Lets programs talk to each other"),
    "systemd": ("systemd", "Starts and stops services"),
    "xdg-desktop-portal": ("Desktop portal", "Lets apps open files and share the screen safely"),
    "xdg-document-portal": ("Document portal", "Hands apps the files you choose"),
    "xdg-permission-store": ("Permission store", "Remembers what each app may do"),
    "gvfsd": ("GVfs", "Drives, phones and network places in Files"),
    "at-spi-bus-launcher": ("Accessibility bus", "For the screen reader and other helpers"),
    "at-spi2-registryd": ("Accessibility registry", "For the screen reader and other helpers"),
    "earlyoom": ("earlyoom", "Stops the biggest program if memory runs out"),
    "gnome-keyring-daemon": ("Keyring", "Keeps passwords for apps"),
    "kwalletd6": ("KWallet", "Keeps passwords for apps"),
    "kdeconnectd": ("KDE Connect", "Your phone, linked to the computer"),
    "llama-server": ("Huginn AI's model", "The model on this computer, answering questions"),
    "gamemoded": ("GameMode", "Gives games the processor while they run"),
    "steamwebhelper": ("Steam's web views", "Part of Steam"),
    "obex": ("Bluetooth file sharing", ""),
    "NetworkManager": ("NetworkManager", "Wi‑Fi and wired networks"),
    "bluetoothd": ("Bluetooth", ""),
    "upowerd": ("UPower", "Batteries and power"),
    "polkitd": ("polkit", "Asks for the password when a program needs it"),
    "cupsd": ("Printing", ""),
    "packagekitd": ("PackageKit", "Puts in system updates and packages"),
    "flatpak-system-helper": ("Flatpak's helper", "Installs and removes apps"),
}
ENGINES = re.compile(r"^drm-engine-(\w+):\s+(\d+)\s*ns", re.M)


def human(n: float) -> str:
    if n != n or n in (float("inf"), float("-inf")):              # (not a number: nothing to show)
        return "–"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _read(p, default=""):
    try:
        return Path(p).read_text(errors="replace")
    except OSError:
        return default


def _desktop_index() -> dict:
    """What a running program may be, from the apps' .desktop files: {"exe:steam" | "flatpak:<id>" | "huginn:<key>":
    {name, icon}} (the first place found wins, as in the start menu)."""
    dirs = [Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "applications"]
    dirs += [Path(d) / "applications" for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    dirs += [Path.home() / ".local/share/flatpak/exports/share/applications", Path("/var/lib/flatpak/exports/share/applications")]
    out = {}
    for d in dirs:
        try:
            files = sorted(d.glob("*.desktop"))
        except OSError:
            continue
        for f in files:
            name = icon = exe = ""
            nodisplay = False
            section = ""
            for line in _read(f).splitlines():
                if line.startswith("["):
                    section = line.strip()
                    continue
                if section != "[Desktop Entry]" or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k == "Name":
                    name = v
                elif k == "Icon":
                    icon = v
                elif k == "Exec":
                    exe = v
                elif k == "NoDisplay":
                    nodisplay = v.strip() == "true"
            if not name or not exe:
                continue
            words = [w for w in exe.split() if "=" not in w or w.startswith("--")]
            keys = []
            m = re.search(r"huginn_app\.py\s+(\w+)", exe)
            if m:
                keys.append("huginn:" + m.group(1))
            elif "flatpak" in exe and " run " in f" {exe} ":
                ids = [w for w in words if re.fullmatch(r"[A-Za-z][\w-]*(\.[\w-]+){2,}", w)]
                if ids:
                    keys.append("flatpak:" + ids[-1])
            else:
                first = next((w for w in words if w not in ("env",)), "")
                base = os.path.basename(first.strip('"'))
                if base in ("python3", "python", "sh", "bash") and len(words) > 1:
                    base = os.path.basename(words[1].strip('"'))
                if base:
                    keys.append("exe:" + base)
            for k in keys:
                if k not in out or (out[k].get("nodisplay") and not nodisplay):
                    out[k] = {"name": name, "icon": icon, "nodisplay": nodisplay}
    return out


def _steam_names() -> dict:
    try:
        import huginn_storage
        return {g["appid"]: g["name"] for g in huginn_storage.steam_games()}
    except Exception:                                                # noqa: BLE001
        return {}


def _ipv4(ifname: str) -> str:
    try:
        import fcntl
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            raw = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", ifname[:15].encode()))   # SIOCGIFADDR
            return socket.inet_ntoa(raw[20:24])
        finally:
            s.close()
    except OSError:
        return ""


class Sampler:
    """One reading of everything; keeps what it needs from the last one to turn counters into rates."""

    def __init__(self):
        self.page = os.sysconf("SC_PAGE_SIZE")
        self.ticks = os.sysconf("SC_CLK_TCK")
        self.cores = os.cpu_count() or 1
        self.me = os.getuid()
        self.prev_t = 0.0
        self.prev_cpu = None             # (total, idle)
        self.prev_cores = []             # [(total, idle)]
        self.prev_proc = {}              # pid -> cpu ticks
        self.prev_io = {}                # pid -> bytes
        self.prev_gpu = {}               # (pid, client) -> ns
        self.prev_net = {}               # iface -> (rx, tx)
        self.prev_disk = {}              # disk -> (read, written, busy ms)
        self.pss = {}                    # pid -> (bytes, when)
        self.index = {}
        self.index_at = 0.0
        self.steam = {}
        self.users = {}
        self.hist = {k: [0.0] * POINTS for k in ("cpu", "mem", "gpu", "read", "write", "down", "up")}
        self.card = None
        self.card_name = ""
        self.cpu_model = ""
        for line in _read("/proc/cpuinfo").splitlines():
            if line.startswith("model name"):
                self.cpu_model = re.sub(r"\s+", " ", line.split(":", 1)[1]).strip()
                break

    def _user(self, uid: int) -> str:
        if uid not in self.users:
            try:
                import pwd
                self.users[uid] = pwd.getpwuid(uid).pw_name
            except (ImportError, KeyError):
                self.users[uid] = str(uid)
        return self.users[uid]

    def _push(self, key, v):
        self.hist[key] = self.hist[key][1:] + [v]

    # ----------------------------------------------------------------------------------------------- one reading
    def sample(self) -> dict:
        now = time.monotonic()
        span = now - self.prev_t if self.prev_t else 0.0
        if now - self.index_at > 30:                       # apps put in or taken off since
            self.index, self.steam, self.index_at = _desktop_index(), _steam_names(), now
        out = {"cpu": self._cpu(), "mem": self._mem()}
        procs = self._procs(span, out["cpu"].get("delta", 0))
        out["gpu"] = self._gpu(procs)
        out["disks"] = self._disks(span)
        out["nets"] = self._nets(span)
        out["rows"] = procs
        out["apps"] = self._apps(procs)
        rd = sum(d["read"] for d in out["disks"])
        wr = sum(d["write"] for d in out["disks"])
        down = sum(n["down"] for n in out["nets"])
        up = sum(n["up"] for n in out["nets"])
        self._push("cpu", out["cpu"]["load"])
        self._push("mem", out["mem"]["used"] / out["mem"]["total"] if out["mem"]["total"] else 0)
        self._push("gpu", (out["gpu"].get("load", 0) or 0) / 100)
        for k, v in (("read", rd), ("write", wr), ("down", down), ("up", up)):
            self._push(k, v)
        out["hist"] = {k: list(v) for k, v in self.hist.items()}
        out["totals"] = {"read": rd, "write": wr, "down": down, "up": up}
        out["counts"] = {"processes": len(procs), "threads": sum(p["threads"] for p in procs),
                         "apps": sum(1 for a in out["apps"] if a["kind"] == "app"),
                         "background": sum(1 for a in out["apps"] if a["kind"] == "background"),
                         "system": sum(1 for a in out["apps"] if a["kind"] == "system")}
        try:
            out["uptime"] = float(_read("/proc/uptime", "0").split()[0])
        except (ValueError, IndexError):
            out["uptime"] = 0.0
        self.prev_t = now
        return out

    def _cpu(self) -> dict:
        lines = [l.split() for l in _read("/proc/stat").splitlines() if l.startswith("cpu")]
        out = {"load": 0.0, "cores": [], "model": self.cpu_model, "count": self.cores, "delta": 0}
        cores = []
        for i, cols in enumerate(lines):
            v = [int(x) for x in cols[1:9]]
            total, idle = sum(v), v[3] + v[4]
            if i == 0:
                if self.prev_cpu and total > self.prev_cpu[0]:
                    out["load"] = max(0.0, min(1.0, 1 - (idle - self.prev_cpu[1]) / (total - self.prev_cpu[0])))
                    out["delta"] = total - self.prev_cpu[0]
                self.prev_cpu = (total, idle)
            else:
                j = i - 1
                load = 0.0
                if j < len(self.prev_cores) and total > self.prev_cores[j][0]:
                    load = max(0.0, min(1.0, 1 - (idle - self.prev_cores[j][1]) / (total - self.prev_cores[j][0])))
                cores.append((total, idle))
                out["cores"].append(round(load, 3))
        self.prev_cores = cores
        freqs = []
        for f in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq"):
            try:
                freqs.append(int(f.read_text()) / 1e6)
            except (OSError, ValueError):
                pass
        out["ghz"] = round(sum(freqs) / len(freqs), 2) if freqs else 0
        tops = []
        for f in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/cpuinfo_max_freq"):
            try:
                tops.append(int(f.read_text()) / 1e6)
            except (OSError, ValueError):
                pass
        out["maxGhz"] = round(max(tops), 2) if tops else 0
        out["temp"] = None
        for hw in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            if _read(hw / "name").strip() in ("k10temp", "zenpower", "coretemp", "cpu_thermal"):
                temps = {}
                for t in sorted(hw.glob("temp*_input")):
                    try:
                        temps[_read(t.with_name(t.name.replace("_input", "_label"))).strip()] = round(int(t.read_text()) / 1000)
                    except (OSError, ValueError):
                        pass
                out["temp"] = next((temps[k] for k in ("Tctl", "Tdie", "Package id 0") if k in temps), max(temps.values()) if temps else None)
                break
        return out

    def _mem(self) -> dict:
        m = {}
        for line in _read("/proc/meminfo").splitlines():
            k, _, rest = line.partition(":")
            if rest.split():
                m[k] = int(rest.split()[0]) * 1024
        total, avail = m.get("MemTotal", 0), m.get("MemAvailable", 0)
        cached = m.get("Cached", 0) + m.get("Buffers", 0) + m.get("SReclaimable", 0) - m.get("Shmem", 0)
        zram = any(l.startswith("/dev/zram") for l in _read("/proc/swaps").splitlines())
        return {"total": total, "used": max(0, total - avail), "available": avail, "cached": max(0, cached),
                "free": m.get("MemFree", 0), "swapTotal": m.get("SwapTotal", 0), "swapUsed": m.get("SwapTotal", 0) - m.get("SwapFree", 0),
                "zram": zram}

    def _procs(self, span: float, delta: int) -> list:
        rows, ticks, ios, now = [], {}, {}, time.monotonic()
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            try:
                stat = Path(entry.path, "stat").read_text()
                name = stat[stat.index("(") + 1:stat.rindex(")")]
                rest = stat[stat.rindex(")") + 2:].split()
                used, rss, ppid, threads, uid = int(rest[11]) + int(rest[12]), int(rest[21]) * self.page, int(rest[1]), int(rest[17]), entry.stat().st_uid
            except (OSError, ValueError, IndexError):
                continue
            if rss == 0:
                continue                                                  # kernel threads
            ticks[pid] = used
            cpu = (used - self.prev_proc.get(pid, used)) / delta if delta > 0 else 0.0
            mine = uid == self.me
            disk = -1.0
            mem = rss
            if mine:
                try:
                    io = dict(line.split(": ") for line in Path(entry.path, "io").read_text().splitlines())
                    moved = int(io["read_bytes"]) + int(io["write_bytes"])
                    ios[pid] = moved
                    disk = max(0.0, (moved - self.prev_io.get(pid, moved)) / span) if span > 0 else 0.0
                except (OSError, ValueError, KeyError):
                    pass
                got = self.pss.get(pid)
                if got is None or now - got[1] > 6:                        # PSS every few seconds: it walks the memory
                    try:
                        for line in Path(entry.path, "smaps_rollup").read_text().splitlines():
                            if line.startswith("Pss:"):
                                got = (int(line.split()[1]) * 1024, now)
                                self.pss[pid] = got
                                break
                    except (OSError, ValueError, IndexError):
                        got = None
                if got:
                    mem = got[0]
            try:
                argv = Path(entry.path, "cmdline").read_bytes().split(b"\0")
                argv = [a.decode(errors="replace") for a in argv if a]
            except OSError:
                argv = []
            if len(name) == 15 and argv:                              # the kernel keeps 15 letters of a name: the whole one
                full = os.path.basename(argv[0])
                if full.startswith(name):
                    name = full
            rows.append({"pid": pid, "ppid": ppid, "name": name, "argv": argv, "user": self._user(uid), "mine": mine,
                         "cpu": round(max(0.0, cpu) * 100, 1), "memory": mem, "disk": disk, "gpu": 0.0, "threads": threads,
                         "state": rest[0], "paused": rest[0] in ("T", "t")})
        self.prev_proc, self.prev_io = ticks, ios
        self.pss = {p: v for p, v in self.pss.items() if p in ticks}
        self._gpu_per_process(rows, span)
        return rows

    def _gpu_per_process(self, rows: list, span: float) -> None:
        """The share of the graphics card's time each of your processes used (drm-engine-* in fdinfo)."""
        seen, now_ns = {}, {}
        for r in rows:
            if not r["mine"]:
                continue
            base = f"/proc/{r['pid']}/fd"
            try:
                fds = os.listdir(base)
            except OSError:
                continue
            clients = {}
            for fd in fds:
                try:
                    if not os.readlink(f"{base}/{fd}").startswith("/dev/dri/"):
                        continue
                    info = Path(f"/proc/{r['pid']}/fdinfo/{fd}").read_text()
                except OSError:
                    continue
                m = re.search(r"^drm-client-id:\s+(\d+)", info, re.M)
                if not m or m.group(1) in clients:
                    continue
                clients[m.group(1)] = sum(int(ns) for eng, ns in ENGINES.findall(info) if eng in ("gfx", "render", "compute", "0"))
            for cid, ns in clients.items():
                key = (r["pid"], cid)
                now_ns[key] = ns
                if span > 0 and key in self.prev_gpu:
                    seen[r["pid"]] = seen.get(r["pid"], 0.0) + max(0, ns - self.prev_gpu[key]) / (span * 1e9)
        self.prev_gpu = now_ns
        for r in rows:
            if r["pid"] in seen:
                r["gpu"] = round(min(1.0, seen[r["pid"]]) * 100, 1)

    def _gpu(self, procs) -> dict:
        if self.card is None:
            for d in (HERE.parent / "shell", Path("/usr/share/huginn-shell")):
                if (d / "huginn_hwstats.py").exists() and str(d) not in sys.path:
                    sys.path.insert(0, str(d))
            try:
                import huginn_hwstats
                self.card = huginn_hwstats.Readings()
            except Exception:                                        # noqa: BLE001
                self.card = False
            try:
                import huginn_settings
                self.card_name = huginn_settings.card_name()
            except Exception:                                        # noqa: BLE001
                self.card_name = ""
        if not self.card:
            return {}
        try:
            g = self.card.card()
        except Exception:                                            # noqa: BLE001
            g = {}
        if not g:
            return {}
        g["name"] = self.card_name or "Graphics card"
        return g

    def _disks(self, span: float) -> list:
        try:
            whole = [d.name for d in os.scandir("/sys/block") if not d.name.startswith(("loop", "ram", "zram", "dm-", "sr", "fd"))]
        except OSError:
            whole = []
        stats = {}
        for line in _read("/proc/diskstats").splitlines():
            c = line.split()
            if len(c) >= 13:
                stats[c[2]] = (int(c[5]) * 512, int(c[9]) * 512, int(c[12]))
        mounts = []
        for line in _read("/proc/mounts").splitlines():
            c = line.split()
            if len(c) > 2 and c[0].startswith("/dev/") and c[1] not in [m[1] for m in mounts]:
                mounts.append((os.path.basename(os.path.realpath(c[0])), c[1].replace("\\040", " ")))
        out, now = [], {}
        for d in sorted(whole):
            if d not in stats:
                continue
            r, w, busy = stats[d]
            now[d] = (r, w, busy)
            pr = self.prev_disk.get(d)
            read = write = load = 0.0
            if pr and span > 0:
                read, write = max(0, r - pr[0]) / span, max(0, w - pr[1]) / span
                load = min(1.0, max(0, busy - pr[2]) / (span * 1000))
            model = _read(f"/sys/block/{d}/device/model").strip() or (_read(f"/sys/block/{d}/device/name").strip())
            try:
                size = int(_read(f"/sys/block/{d}/size", "0")) * 512
            except ValueError:
                size = 0
            parts = []
            for dev, where in mounts:
                if dev.startswith(d) and where not in ("/boot/efi",) and not where.startswith(("/snap", "/var/lib/snapd")):
                    try:
                        st = os.statvfs(where)
                        total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
                        if total:
                            parts.append({"where": where, "total": total, "used": total - free})
                    except OSError:
                        pass
            ssd = _read(f"/sys/block/{d}/queue/rotational").strip() == "0"
            out.append({"name": d, "model": model, "size": size, "read": read, "write": write, "busy": load, "parts": parts,
                        "kind": "NVMe drive" if d.startswith("nvme") else ("SSD" if ssd else "Hard drive") if not d.startswith("mmc") else "Memory card"})
        self.prev_disk = now
        return out

    def _nets(self, span: float) -> list:
        out, now = [], {}
        for line in _read("/proc/net/dev").splitlines()[2:]:
            name, _, data = line.partition(":")
            name = name.strip()
            c = data.split()
            if name == "lo" or len(c) < 9:
                continue
            # the computer's own connections and VPNs; not the software bridges and pipes containers and the like make
            virtual = "/virtual/" in os.path.realpath(f"/sys/class/net/{name}")
            if virtual and not name.startswith(("wg", "tun", "tailscale", "ppp", "proton", "nordlynx")):
                continue
            rx, tx = int(c[0]), int(c[8])
            now[name] = (rx, tx)
            pr = self.prev_net.get(name)
            down = up = 0.0
            if pr and span > 0:
                down, up = max(0, rx - pr[0]) / span, max(0, tx - pr[1]) / span
            wireless = Path(f"/sys/class/net/{name}/wireless").exists()
            state = _read(f"/sys/class/net/{name}/operstate").strip()
            out.append({"name": name, "kind": "Wi‑Fi" if wireless else ("VPN" if virtual else "Ethernet"),
                        "up_": state == "up", "down": down, "up": up, "rx": rx, "tx": tx, "address": _ipv4(name) if state == "up" else ""})
        self.prev_net = now
        out.sort(key=lambda n: (not n["up_"], -(n["rx"] + n["tx"])))
        return out

    # ----------------------------------------------------------------------------------------------- apps
    def _identity(self, r: dict):
        """(key, name, icon) when this process is, by itself, an app; else None."""
        argv, name = r["argv"], r["name"]
        for i, a in enumerate(argv[:3]):
            if a.endswith("huginn_app.py") and i + 1 < len(argv):
                key = "huginn:" + argv[i + 1]
                got = self.index.get(key)
                return key, got["name"] if got else argv[i + 1].title(), got["icon"] if got else ""
        if name == "reaper" or "SteamLaunch" in " ".join(argv[:4]):
            m = re.search(r"AppId=(\d+)", " ".join(argv))
            if m:
                return "steam:" + m.group(1), self.steam.get(m.group(1), "Steam game " + m.group(1)), "steam_icon_" + m.group(1)
        if r["mine"]:
            cg = _read(f"/proc/{r['pid']}/cgroup")
            m = re.search(r"app-flatpak-([A-Za-z][\w.-]+?)-\d+\.scope", cg)
            if m:
                key = "flatpak:" + m.group(1)
                got = self.index.get(key)
                return key, got["name"] if got else m.group(1).split(".")[-1], got["icon"] if got else m.group(1)
        exe = ""
        try:
            exe = os.path.basename(os.readlink(f"/proc/{r['pid']}/exe"))
        except OSError:
            pass
        bases = [name, exe]
        if argv:
            bases.append(os.path.basename(argv[0]))
            if os.path.basename(argv[0]).startswith("python") and len(argv) > 1:
                bases.append(os.path.basename(argv[1]))
        for b in bases:
            got = self.index.get("exe:" + b) if b else None
            if got and not got.get("nodisplay"):
                return "exe:" + b, got["name"], got["icon"]
        return None

    def _apps(self, procs: list) -> list:
        by_pid = {r["pid"]: r for r in procs}
        ident = {}
        for r in procs:
            got = self._identity(r)
            if got:
                ident[r["pid"]] = got

        def owner(r):
            """The app this process belongs to: its own, or its nearest parent's (not past the session)."""
            seen, cur = 0, r
            while cur and seen < 12:
                if cur["pid"] in ident:
                    return ident[cur["pid"]]
                parent = by_pid.get(cur["ppid"])
                if not parent or parent["name"] in SESSION or parent["pid"] <= 1:
                    return None
                cur, seen = parent, seen + 1
            return None

        groups = {}
        for r in procs:
            app = owner(r) if r["mine"] else (ident.get(r["pid"]) if r["pid"] in ident and r["mine"] else None)
            if app:
                key, name, icon = app
                kind, sub = "app", ""
            elif r["mine"]:
                known = KNOWN.get(r["name"])
                key, name, icon, kind = "bg:" + r["name"], known[0] if known else r["name"], "", "background"
                sub = known[1] if known else ""
            else:
                known = KNOWN.get(r["name"])
                key, name, icon, kind = "sys:" + r["name"], known[0] if known else r["name"], "", "system"
                sub = known[1] if known else ""
            r["app"] = key
            g = groups.get(key)
            if g is None:
                g = groups[key] = {"key": key, "name": name, "icon": icon, "kind": kind, "sub": sub, "cpu": 0.0, "memory": 0, "gpu": 0.0,
                                   "disk": 0.0, "pids": [], "paused": True, "user": r["user"]}
            g["cpu"] += r["cpu"]
            g["memory"] += r["memory"]
            g["gpu"] += r["gpu"]
            g["disk"] += max(0.0, r["disk"])
            g["pids"].append(r["pid"])
            g["paused"] = g["paused"] and r["paused"]
        out = []
        for g in groups.values():
            g["cpu"], g["gpu"] = round(g["cpu"], 1), round(min(100.0, g["gpu"]), 1)
            g["count"] = len(g["pids"])
            if g["kind"] == "app" and not g["sub"]:
                g["sub"] = f"{g['count']} processes" if g["count"] > 1 else ""
            out.append(g)
        return out


# --------------------------------------------------------------------------------------------- for the window
class Monitor(QObject):
    """System Monitor's backend for QML (see the module's notes)."""
    changed = Signal()
    failed = Signal(str)
    _got = Signal(object)

    def __init__(self, demo: bool = False):
        super().__init__()
        self._demo = demo
        self._data = demo_data() if demo else {}
        self._supported = Path("/proc/stat").is_file()
        self._sampler = Sampler() if self._supported and not demo else None
        self._busy = False
        self._got.connect(self._take)
        self._timer = QTimer(self, interval=2000, timeout=self.refresh)
        if not demo:
            self.refresh()
            QTimer.singleShot(700, self.refresh)                     # the first rates need two readings
            self._timer.start()

    @Slot(object)
    def _take(self, data: dict) -> None:
        self._busy = False
        self._data = data
        self.changed.emit()

    @Slot()
    def refresh(self) -> None:
        if not self._sampler or self._busy:
            return
        self._busy = True

        def work():
            try:
                data = self._sampler.sample()
            except Exception as err:                                 # noqa: BLE001  (a bad reading mustn't stop the next)
                print(f"huginn-monitor: {err}", file=sys.stderr)
                self._busy = False
                return
            for r in data["rows"]:
                r.pop("argv", None)
            self._got.emit(data)
        threading.Thread(target=work, daemon=True).start()

    def _get(key, default):                                        # noqa: N805
        return lambda self: self._data.get(key, default)

    supported = Property(bool, lambda self: self._supported or self._demo, constant=True)
    demo = Property(bool, lambda self: self._demo, constant=True)
    rows = Property("QVariantList", _get("rows", []), notify=changed)
    apps = Property("QVariantList", _get("apps", []), notify=changed)
    cpuInfo = Property("QVariantMap", _get("cpu", {}), notify=changed)
    memInfo = Property("QVariantMap", _get("mem", {}), notify=changed)
    gpuInfo = Property("QVariantMap", _get("gpu", {}), notify=changed)
    disks = Property("QVariantList", _get("disks", []), notify=changed)
    nets = Property("QVariantList", _get("nets", []), notify=changed)
    history = Property("QVariantMap", _get("hist", {}), notify=changed)
    totals = Property("QVariantMap", _get("totals", {}), notify=changed)
    counts = Property("QVariantMap", _get("counts", {}), notify=changed)
    uptime = Property(float, _get("uptime", 0.0), notify=changed)
    del _get

    # ------------------------------------------------------------------------------------------- sign-in programs
    startupChanged = Signal()
    _startup_got = Signal(object)

    def _startup_take(self, data):
        self._startup = data
        self.startupChanged.emit()

    startup = Property("QVariantMap", lambda self: getattr(self, "_startup", {}), notify=startupChanged)

    @Slot()
    def loadStartup(self) -> None:
        """The Startup view: what starts when you sign in, how heavy each was then, what it uses now
        (huginn_autostart.py)."""
        if not getattr(self, "_startup_wired", False):
            self._startup_got.connect(self._startup_take)
            self._startup_wired = True
        if self._demo:
            if not getattr(self, "_startup", None):
                self._startup_take(demo_startup())
            return

        def work():
            try:
                import huginn_autostart
                self._startup_got.emit(huginn_autostart.report())
            except Exception as err:                                 # noqa: BLE001
                self._startup_got.emit({"entries": [], "error": str(err)})
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, bool)
    def setStartup(self, ident: str, on: bool) -> None:
        if self._demo:
            st = dict(self._startup)
            st["entries"] = [dict(e, enabled=on, runs=on and not e["why"]) if e["id"] == ident else e for e in st["entries"]]
            self._startup_take(st)
            return
        import huginn_autostart
        why = huginn_autostart.set_enabled(ident, on)
        if why:
            self.failed.emit(why)
        self.loadStartup()

    @Slot(str)
    def removeStartup(self, ident: str) -> None:
        if self._demo:
            st = dict(self._startup)
            st["entries"] = [e for e in st["entries"] if e["id"] != ident]
            self._startup_take(st)
            return
        import huginn_autostart
        why = huginn_autostart.remove(ident)
        if why:
            self.failed.emit(why)
        self.loadStartup()

    @Slot()
    def addStartup(self) -> None:
        """Settings › Default Apps, where Start-up apps has Add an app…."""
        if not self._demo:
            import subprocess
            subprocess.Popen([sys.executable, str(HERE / "huginn_app.py"), "settings", "--page", "defaults"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @Slot(str)
    def showFile(self, path: str) -> None:
        if not self._demo and path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    @Slot(float, result=str)
    def size(self, n: float) -> str:
        return human(n)

    @Slot(float, result=str)
    def rate(self, n: float) -> str:
        return human(n) + "/s"

    # ------------------------------------------------------------------------------------------- what you can do
    def _signal(self, pids: list, sig: int) -> None:
        if self._demo:
            return
        refused = False
        for pid in pids:
            # (only one real process at a time: to the system, 0 and below mean "a whole group" or "everything of yours")
            if isinstance(pid, bool) or not isinstance(pid, (int, float)) or int(pid) < 2:
                continue
            try:
                os.kill(int(pid), sig)
            except ProcessLookupError:
                pass
            except PermissionError:
                refused = True
        if refused:
            self.failed.emit("Part of it belongs to the system, so it can't be changed from here.")
        QTimer.singleShot(500, self.refresh)

    @Slot("QVariantList")
    def end(self, pids) -> None:
        """Ask it to close (an app may save first)."""
        self._signal(list(pids), signal.SIGTERM)

    @Slot("QVariantList")
    def force(self, pids) -> None:
        """Stop it at once, for something that ignores End."""
        self._signal(list(pids), signal.SIGKILL)

    @Slot("QVariantList")
    def pause(self, pids) -> None:
        self._signal(list(pids), signal.SIGSTOP)

    @Slot("QVariantList")
    def resume(self, pids) -> None:
        self._signal(list(pids), signal.SIGCONT)

    @Slot(int, int)
    def setNice(self, pid: int, nice: int) -> None:
        """Its priority: 10 (in the background, gives way to everything else) or 0 (normal). Raising it again needs
        nothing; going above normal would need the system's password, so it isn't offered."""
        if self._demo or pid < 2:
            return
        try:
            os.setpriority(os.PRIO_PROCESS, pid, max(0, min(19, nice)))
        except PermissionError:
            self.failed.emit("Its priority can only go back to normal with the system's password.")
        except OSError:
            pass
        QTimer.singleShot(400, self.refresh)

    @Slot(int, result="QVariantList")
    def details(self, pid: int) -> list:
        if self._demo:
            return [{"name": "Process number", "value": str(pid)}, {"name": "Started", "value": "Nov 21, 09:12"}, {"name": "Threads", "value": "24"},
                    {"name": "Priority", "value": "Normal"}, {"name": "Owner", "value": "astrid"}, {"name": "Program file", "value": "/usr/bin/python3.14"},
                    {"name": "Started as", "value": "python3 /usr/share/huginn-apps/huginn_app.py writer"}]
        base, out = Path("/proc", str(pid)), []
        try:
            stat = (base / "stat").read_text()
            rest = stat[stat.rindex(")") + 2:].split()
            boot = time.time() - float(Path("/proc/uptime").read_text().split()[0])
            ticks = os.sysconf("SC_CLK_TCK")
            started = dt.datetime.fromtimestamp(boot + int(rest[19]) / ticks).strftime("%b %d, %H:%M")
            nice = int(rest[16])
            out += [("Process number", str(pid)), ("Parent", rest[1]), ("Started", started), ("Threads", rest[17]),
                    ("State", "Paused" if rest[0] in ("T", "t") else "Running" if rest[0] == "R" else "Waiting"),
                    ("Priority", "Normal" if nice == 0 else ("Lower (" if nice > 0 else "Higher (") + str(nice) + ")")]
            try:
                import pwd
                out.append(("Owner", pwd.getpwuid(base.stat().st_uid).pw_name))
            except (ImportError, KeyError):
                pass
            try:
                out.append(("Program file", os.readlink(base / "exe")))
            except OSError:
                pass
            try:
                out.append(("Working in", os.readlink(base / "cwd")))
            except OSError:
                pass
            command = (base / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            if command:
                out.append(("Started as", command[:300]))
        except (OSError, ValueError, IndexError):
            return [{"name": "Status", "value": "This has already closed."}]
        return [{"name": k, "value": v} for k, v in out]

    @Slot(int)
    def showLocation(self, pid: int) -> None:
        if self._demo:
            return
        try:
            folder = str(Path(os.readlink(f"/proc/{pid}/exe")).parent)
        except OSError:
            self.failed.emit("Where that program is can't be read.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


# --------------------------------------------------------------------------------------------- the preview
def demo_data() -> dict:
    """What the window shows in --demo: a working afternoon on a gaming PC."""
    import math
    import random
    random.seed(7)
    G = 1024 ** 3
    wave = lambda base, amp, ph: [max(0.0, min(1.0, base + amp * math.sin(i / 6 + ph) + random.uniform(-0.04, 0.04))) for i in range(POINTS)]
    hist = {"cpu": wave(0.24, 0.12, 0), "mem": wave(0.46, 0.02, 1), "gpu": wave(0.58, 0.3, 2),
            "read": [max(0, 20e6 * math.sin(i / 4) ** 8 + random.uniform(0, 2e6)) for i in range(POINTS)],
            "write": [max(0, 6e6 * math.sin(i / 5 + 1) ** 8 + random.uniform(0, 1e6)) for i in range(POINTS)],
            "down": [max(0, 3.2e6 + 2.5e6 * math.sin(i / 3) + random.uniform(-4e5, 4e5)) for i in range(POINTS)],
            "up": [max(0, 2.4e5 + 1e5 * math.sin(i / 4) + random.uniform(-3e4, 3e4)) for i in range(POINTS)]}
    apps = [("flatpak:com.valvesoftware.Steam", "Steam", "com.valvesoftware.Steam", 2.1, 0.62 * G, 1.2, 0.2e6, 14),
            ("steam:1145360", "Hades", "", 9.8, 2.1 * G, 41.5, 1.4e6, 6),
            ("exe:huginn", "Huginn", "huginn", 6.4, 1.84 * G, 7.9, 0.3e6, 17),
            ("huginn:writer", "Writer", "huginn-writer", 0.6, 0.21 * G, 0.0, 0, 1),
            ("huginn:music", "Music", "huginn-music", 1.1, 0.16 * G, 0.4, 0.02e6, 2),
            ("flatpak:com.discordapp.Discord", "Discord", "com.discordapp.Discord", 1.4, 0.58 * G, 1.1, 0.05e6, 9),
            ("huginn:monitor", "System Monitor", "huginn-monitor", 0.9, 0.12 * G, 0.0, 0, 1)]
    bg = [("huginn-compositor", 3.2, 0.21 * G, 18.3), ("huginn-shell", 0.8, 0.11 * G, 0.6), ("Xwayland", 0.4, 0.09 * G, 0.2),
          ("pipewire", 0.6, 0.02 * G, 0), ("wireplumber", 0.1, 0.03 * G, 0), ("huginn-sessiond", 0.1, 0.04 * G, 0),
          ("xdg-desktop-portal", 0.0, 0.02 * G, 0), ("gamemoded", 0.0, 0.01 * G, 0)]
    sysrows = [("systemd", "root", 0.1, 0.01 * G), ("NetworkManager", "root", 0.0, 0.02 * G), ("bluetoothd", "root", 0.0, 0.01 * G),
               ("earlyoom", "root", 0.0, 0.002 * G), ("polkitd", "polkitd", 0.0, 0.01 * G), ("upowerd", "root", 0.0, 0.01 * G)]
    rows, groups, pid = [], [], 1200
    for key, name, icon, cpu, mem, gpu, disk, n in apps:
        # (no icon: letters, since the preview can't count on the icons being there)
        g = {"key": key, "name": name, "icon": "", "kind": "app", "sub": f"{n} processes" if n > 1 else "", "cpu": cpu, "memory": mem, "gpu": gpu,
             "disk": disk, "pids": [], "paused": False, "count": n, "user": "astrid"}
        for i in range(n):
            pid += random.randint(3, 40)
            share = 1.0 / n if i else 0.5 + 0.5 / n
            rname = {"Huginn": ["huginn", "QtWebEngineProc"], "Steam": ["steam", "steamwebhelper"], "Hades": ["reaper", "Hades.exe", "wineserver"],
                     "Discord": ["Discord", "Discord"]}.get(name, ["python3"])
            rows.append({"pid": pid, "ppid": 1100, "name": rname[min(i, len(rname) - 1)], "user": "astrid", "mine": True, "cpu": round(cpu * share, 1),
                         "memory": mem * share, "disk": disk * share, "gpu": round(gpu * share, 1), "threads": random.randint(3, 60), "state": "S",
                         "paused": False, "app": key})
            g["pids"].append(pid)
        groups.append(g)
    for name, cpu, mem, gpu in bg:
        pid += random.randint(3, 40)
        known = KNOWN.get(name, (name, ""))
        groups.append({"key": "bg:" + name, "name": known[0], "icon": "", "kind": "background", "sub": known[1], "cpu": cpu, "memory": mem, "gpu": gpu,
                       "disk": 0, "pids": [pid], "paused": False, "count": 1, "user": "astrid"})
        rows.append({"pid": pid, "ppid": 1000, "name": name, "user": "astrid", "mine": True, "cpu": cpu, "memory": mem, "disk": 0, "gpu": gpu,
                     "threads": random.randint(2, 30), "state": "S", "paused": False, "app": "bg:" + name})
    for name, user, cpu, mem in sysrows:
        pid = random.randint(300, 900)
        known = KNOWN.get(name, (name, ""))
        groups.append({"key": "sys:" + name, "name": known[0], "icon": "", "kind": "system", "sub": known[1], "cpu": cpu, "memory": mem, "gpu": 0,
                       "disk": 0, "pids": [pid], "paused": False, "count": 1, "user": user})
        rows.append({"pid": pid, "ppid": 1, "name": name, "user": user, "mine": False, "cpu": cpu, "memory": mem, "disk": -1, "gpu": 0,
                     "threads": random.randint(1, 8), "state": "S", "paused": False, "app": "sys:" + name})
    cores = [round(random.uniform(0.05, 0.6), 2) for _ in range(16)]
    return {"rows": rows, "apps": groups, "hist": hist,
            "cpu": {"load": 0.27, "cores": cores, "model": "AMD Ryzen 7 9800X3D 8-Core Processor", "count": 16, "ghz": 4.71, "maxGhz": 5.27, "temp": 61},
            "mem": {"total": 32 * G, "used": 14.6 * G, "available": 17.4 * G, "cached": 9.1 * G, "free": 8.3 * G, "swapTotal": 16 * G, "swapUsed": 0.3 * G, "zram": True},
            "gpu": {"name": "AMD Radeon RX 9070 XT", "load": 64, "memUsed": 9.4, "memTotal": 15.9, "temp": 63, "hot": 79, "watts": 238, "capWatts": 304,
                    "coreMhz": 2950, "memMhz": 1258, "fan": 1640, "fanPercent": 48},
            "disks": [{"name": "nvme0n1", "model": "Samsung SSD 990 PRO 2TB", "size": 2000 * 1000 ** 3, "read": 1.4e6, "write": 0.3e6, "busy": 0.04, "kind": "NVMe drive",
                       "parts": [{"where": "/", "total": 412 * G, "used": 188 * G}, {"where": "/home", "total": 1450 * G, "used": 702 * G}]},
                      {"name": "sda", "model": "WDC WD40EZAZ", "size": 4000 * 1000 ** 3, "read": 0, "write": 0, "busy": 0.0, "kind": "Hard drive",
                       "parts": [{"where": "/mnt/Games", "total": 3600 * G, "used": 2210 * G}]}],
            "nets": [{"name": "enp6s0", "kind": "Ethernet", "up_": True, "down": 3.4e6, "up": 2.2e5, "rx": 18.2 * G, "tx": 1.3 * G, "address": "192.168.1.24"},
                     {"name": "wlp7s0", "kind": "Wi‑Fi", "up_": False, "down": 0, "up": 0, "rx": 0, "tx": 0, "address": ""}],
            "totals": {"read": 1.4e6, "write": 0.3e6, "down": 3.4e6, "up": 2.2e5},
            "counts": {"processes": len(rows) + 212, "threads": 1840, "apps": len(apps), "background": len(bg), "system": len(sysrows)},
            "uptime": 3 * 3600 + 12 * 60}


def demo_startup() -> dict:
    """The preview's sign-in programs."""
    M = 1024 ** 2
    rows = [("steam.desktop", "Steam", "com.valvesoftware.Steam", "/usr/bin/flatpak run com.valvesoftware.Steam -silent", True, True, "high", 4.8, 412 * M, True, 690 * M),
            ("discord.desktop", "Discord", "com.discordapp.Discord", "/usr/bin/flatpak run com.discordapp.Discord --start-minimized", True, True, "high", 2.6, 188 * M, True, 540 * M),
            ("org.signal.Signal.desktop", "Signal", "org.signal.Signal", "/usr/bin/flatpak run org.signal.Signal --start-in-tray", False, True, "", -1, -1, False, 0),
            ("huginn-notes.desktop", "Notes", "huginn-notes", "python3 /usr/share/huginn-apps/huginn_app.py notes", True, True, "low", 0.21, 90 * 1024, False, 0),
            ("vendor-rgb.desktop", "RGB Lighting", "", "/opt/rgb/rgb-tray --minimized", True, False, "medium", 0.6, 1.2 * M, True, 38 * M)]
    entries = []
    for ident, name, icon, ex, on, mine, imp, cpu, disk, running, mem in rows:
        entries.append({"id": ident, "name": name, "comment": "", "icon": icon, "exec": ex, "enabled": on, "mine": mine, "system": not mine,
                        "path": ("/home/astrid/.config/autostart/" if mine else "/etc/xdg/autostart/") + ident, "runs": on, "why": "",
                        "impact": imp if on else "", "cpu": cpu, "disk": disk, "failed": "", "running": running, "memoryNow": mem, "delay": 0})
    return {"entries": entries, "signin": time.time() - 3 * 3600 - 12 * 60, "measured": True}
