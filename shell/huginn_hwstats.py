"""The game stats overlay's readings (Super+Alt+G): the graphics card's load, temperature, memory, clock and power,
the processor's load and temperature, and memory in use. From the kernel's files, read once a second while the
overlay shows, so nothing runs otherwise and nothing needs installing.

AMD cards (amdgpu) give all of it: gpu_busy_percent, mem_info_vram_used/_total, and hwmon (temperatures edge,
junction and mem, power1_average or power1_input in µW, freq1_input for the shader clock). Intel's give no load or
temperature this way; NVIDIA's own driver answers nvidia-smi, asked from a thread so the overlay never waits.
Processors: /proc/stat for load, hwmon's k10temp or zenpower (AMD: Tctl) or coretemp (Intel: Package) for heat."""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

DRM = Path("/sys/class/drm")
HWMON = Path("/sys/class/hwmon")


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _num(p: Path) -> float | None:
    try:
        return float(_read(p))
    except ValueError:
        return None


def _cards(drm: Path = DRM) -> list[Path]:
    """The graphics cards' device folders, the one with most video memory first (the discrete card)."""
    seen, out = set(), []
    for card in sorted(drm.glob("card[0-9]*")):
        if "-" in card.name:
            continue
        dev = (card / "device").resolve()
        if dev in seen or not (dev / "vendor").exists():
            continue
        seen.add(dev)
        out.append(dev)
    return sorted(out, key=lambda d: -(_num(d / "mem_info_vram_total") or 0))


class Readings:
    def __init__(self, root: Path | None = None):
        self._drm = Path(root, "sys/class/drm") if root else DRM
        self._hw = Path(root, "sys/class/hwmon") if root else HWMON
        self._proc = Path(root, "proc") if root else Path("/proc")
        self._cpu_last: tuple[int, int] | None = None
        self._nv: dict = {}
        self._nv_busy = False

    # ------------------------------------------------------------------ graphics card
    def gpu(self) -> dict:
        for dev in _cards(self._drm):
            vendor = _read(dev / "vendor").lower()
            if vendor == "0x1002":                     # AMD
                out = {"kind": "amd"}
                busy = _num(dev / "gpu_busy_percent")
                if busy is not None:
                    out["load"] = round(busy)
                used, total = _num(dev / "mem_info_vram_used"), _num(dev / "mem_info_vram_total")
                if used is not None and total:
                    out["memUsed"], out["memTotal"] = round(used / 2**30, 1), round(total / 2**30, 1)
                for hw in sorted((dev / "hwmon").glob("hwmon*")):
                    temps = {}
                    for t in sorted(hw.glob("temp*_input")):
                        v = _num(t)
                        if v is not None:
                            temps[_read(t.with_name(t.name.replace("_input", "_label"))) or t.name] = round(v / 1000)
                    if temps:
                        out["temp"] = temps.get("edge", next(iter(temps.values())))
                        if "junction" in temps:
                            out["hot"] = temps["junction"]
                    for name in ("power1_average", "power1_input"):
                        w = _num(hw / name)
                        if w is not None:
                            out["watts"] = round(w / 1e6)
                            break
                    clock = _num(hw / "freq1_input")
                    if clock:
                        out["ghz"] = round(clock / 1e9, 2)
                    fan = _num(hw / "fan1_input")
                    if fan is not None:
                        out["fan"] = round(fan)
                return out
            if vendor == "0x10de" and shutil.which("nvidia-smi"):
                self._ask_nvidia()
                return dict(self._nv, kind="nvidia")
            if vendor == "0x8086":
                return {"kind": "intel"}               # no load or heat for Intel graphics this way
        return {}

    def _ask_nvidia(self) -> None:
        if self._nv_busy:
            return
        self._nv_busy = True

        def ask():
            try:
                line = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw,clocks.gr",
                                       "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3).stdout.splitlines()[0]
                load, temp, used, total, watts, mhz = (x.strip() for x in line.split(","))
                self._nv = {"load": round(float(load)), "temp": round(float(temp)), "memUsed": round(float(used) / 1024, 1),
                            "memTotal": round(float(total) / 1024, 1), "watts": round(float(watts)), "ghz": round(float(mhz) / 1000, 2)}
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                pass
            finally:
                self._nv_busy = False
        threading.Thread(target=ask, daemon=True).start()

    # ------------------------------------------------------------------ the card, for Settings › Graphics
    def card(self) -> dict:
        """What Settings › Graphics shows of the graphics card, beside gpu()'s readings: its name, driver, slot, the
        clocks it runs at now (its levels, the one in use marked by the driver), memory's temperature and clock,
        power now and its limit, the fan's share, and the performance level chosen (power_dpm_force_performance_level).
        AMD cards (amdgpu) only; for others just the name and driver."""
        for dev in _cards(self._drm):
            out = {"vendor": _read(dev / "vendor").lower(), "slot": dev.name}
            uevent = dict(line.split("=", 1) for line in _read(dev / "uevent").splitlines() if "=" in line)
            out["driver"] = uevent.get("DRIVER", "")
            out["pci"] = uevent.get("PCI_ID", "")
            if out["vendor"] != "0x1002":
                return out
            out.update(self.gpu())
            level = _read(dev / "power_dpm_force_performance_level")
            if level:
                out["level"] = level
            for name, key in (("pp_dpm_sclk", "coreMhz"), ("pp_dpm_mclk", "memMhz")):
                for line in _read(dev / name).splitlines():
                    if line.rstrip().endswith("*"):
                        digits = "".join(ch for ch in line.split(":", 1)[-1] if ch.isdigit())
                        if digits:
                            out[key] = int(digits)
            for hw in sorted((dev / "hwmon").glob("hwmon*")):
                for t in sorted(hw.glob("temp*_input")):
                    if _read(t.with_name(t.name.replace("_input", "_label"))) == "mem":
                        v = _num(t)
                        if v is not None:
                            out["memTemp"] = round(v / 1000)
                cap, top = _num(hw / "power1_cap"), _num(hw / "power1_cap_max")
                if cap:
                    out["capWatts"] = round(cap / 1e6)
                if top:
                    out["capMaxWatts"] = round(top / 1e6)
                pwm = _num(hw / "pwm1")
                if pwm is not None:
                    out["fanPercent"] = round(100 * pwm / 255)
            return out
        return {}

    # ------------------------------------------------------------------ processor and memory
    def cpu(self) -> dict:
        out = {}
        first = _read(self._proc / "stat").splitlines()[:1]
        if first and first[0].startswith("cpu "):
            v = [int(x) for x in first[0].split()[1:9]]
            idle, total = v[3] + v[4], sum(v)
            if self._cpu_last and total > self._cpu_last[1]:
                out["load"] = round(100 * (1 - (idle - self._cpu_last[0]) / (total - self._cpu_last[1])))
            self._cpu_last = (idle, total)
        for hw in sorted(self._hw.glob("hwmon*")):
            name = _read(hw / "name")
            if name in ("k10temp", "zenpower", "coretemp", "cpu_thermal"):
                temps = {}
                for t in sorted(hw.glob("temp*_input")):
                    v = _num(t)
                    if v is not None:
                        temps[_read(t.with_name(t.name.replace("_input", "_label")))] = round(v / 1000)
                pick = next((temps[k] for k in ("Tctl", "Tdie", "Package id 0") if k in temps), None)
                out["temp"] = pick if pick is not None else (max(temps.values()) if temps else None)
                break
        mem = {}
        for line in _read(self._proc / "meminfo").splitlines():
            k, _, rest = line.partition(":")
            if k in ("MemTotal", "MemAvailable"):
                mem[k] = int(rest.split()[0]) if rest.split() else 0
        if mem.get("MemTotal"):
            out["memUsed"] = round((mem["MemTotal"] - mem.get("MemAvailable", 0)) / 2**20, 1)
            out["memTotal"] = round(mem["MemTotal"] / 2**20, 1)
        return {k: v for k, v in out.items() if v is not None}
