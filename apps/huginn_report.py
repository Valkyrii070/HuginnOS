"""A problem report: what Huginn OS and this computer were doing, in one .zip to look over and send.

What goes in: the system's log for this start (and the problems from the one before), the kernel's, the desktop
session's own log, crashes, the hardware (processor, graphics, screens, sound, network devices, disks), the screens
as the compositor has them, and Huginn OS's version. Nothing from your files.

What doesn't: your name, user name and computer's name, network and Bluetooth device names, addresses (IP, MAC) and
e-mail addresses are replaced before anything is written. The .zip has plain text files: open it and look before
you send it.

From Settings › About (Make a Problem Report), or as a command, from a terminal or a text console (Ctrl+Alt+F3) when
the desktop won't start:  huginn-report  (prints where the report went).
"""
import datetime as dt
import getpass
import json
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

LIMIT = 2_000_000          # characters of one section at most (a log's newest part is kept)


def run(cmd: list, timeout: int = 25) -> str:
    """A command's output (and its errors), or why there's none."""
    if not shutil.which(cmd[0]):
        return f"({cmd[0]} isn't installed)\n"
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace",
                              env=dict(os.environ, LC_ALL="C.UTF-8", SYSTEMD_PAGER="", SYSTEMD_COLORS="0"))
    except subprocess.TimeoutExpired:
        return f"({' '.join(cmd)} took more than {timeout} s)\n"
    except OSError as err:
        return f"({' '.join(cmd)}: {err})\n"
    return (done.stdout or "") + (("\n" + done.stderr) if done.stderr.strip() and not done.stdout.strip() else "")


def read(path, tail_lines: int = 0) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as err:
        return f"({path}: {err.strerror or err})\n"
    if tail_lines:
        text = "\n".join(text.splitlines()[-tail_lines:]) + "\n"
    return text


def section(title: str, body: str) -> str:
    return f"\n===== {title} =====\n{body.rstrip()}\n"


# ---------------------------------------------------------------------------------------------- privacy
class Scrubber:
    """Replaces what says who or where you are with plain stand-ins."""
    MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
    IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    IPV6 = re.compile(r"(?<![\w:])(?:(?:[0-9A-Fa-f]{1,4}:){4,7}[0-9A-Fa-f]{1,4}|(?:[0-9A-Fa-f]{1,4}:){1,6}:(?:[0-9A-Fa-f]{1,4}:?){1,6})(?![\w:])")
    EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
    QUOTED_SSID = re.compile(r"(ssid|SSID|essid|ESSID)([=: ]+)(['\"])(.*?)\3")

    def __init__(self, extra: list = ()):
        self.words = []
        try:
            me = pwd.getpwuid(os.getuid())
            login, real = me.pw_name, (me.pw_gecos or "").split(",")[0].strip()
        except KeyError:
            login, real = getpass.getuser(), ""
        host = socket.gethostname()
        for word, stand_in in [(real, "Person"), (login, "user"), (host, "this-computer")] + [(w, "a-name") for w in extra]:
            if word and len(word) >= 3 and word not in ("root", "localhost", "ubuntu", "huginn", "user"):
                self.words.append((re.compile(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", re.IGNORECASE), stand_in))
                for part in word.split():                       # a real name's parts on their own too
                    if len(part) >= 3 and part != word:
                        self.words.append((re.compile(r"(?<![\w-])" + re.escape(part) + r"(?![\w-])", re.IGNORECASE), stand_in))
        self.words.sort(key=lambda w: -len(w[0].pattern))          # longest first

    def __call__(self, text: str) -> str:
        text = self.QUOTED_SSID.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}a-network{m.group(3)}", text)
        for pattern, stand_in in self.words:
            text = pattern.sub(stand_in, text)
        text = self.EMAIL.sub("someone@example.com", text)
        text = self.MAC.sub("xx:xx:xx:xx:xx:xx", text)
        text = self.IPV4.sub(lambda m: m.group(0) if self._keep_v4(m.group(0)) else "x.x.x.x", text)
        text = self.IPV6.sub(lambda m: m.group(0) if m.group(0) in ("::1",) else "x:x:x:x", text)
        return text

    @staticmethod
    def _keep_v4(addr: str) -> bool:
        parts = [int(p) for p in addr.split(".")]
        if any(p > 255 for p in parts):
            return True                                       # a version number, not an address
        return addr in ("127.0.0.1", "0.0.0.0", "255.255.255.255") or parts[0] == 127


def private_names() -> list:
    """Network, Bluetooth and printer names that would say where you are or what you have."""
    names = set()
    for line in run(["nmcli", "-t", "-f", "NAME", "connection", "show"]).splitlines():
        names.add(line.strip())
    for line in run(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "no"]).splitlines():
        names.add(line.strip().replace("\\:", ":"))
    for line in run(["bluetoothctl", "devices"]).splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[0] == "Device":
            names.add(parts[2].strip())
    names = {n for n in names if len(n) >= 3 and not n.startswith("(") and n not in ("lo", "--", "Wired connection 1")}
    return sorted(names, key=len, reverse=True)


# ---------------------------------------------------------------------------------------------- the report
def gather(say=print) -> dict:
    """Each file of the report, by name."""
    files = {}
    say("This computer and Huginn OS")
    live = Path("/cdrom/casper").is_dir()
    files["system.txt"] = "".join([
        section("Huginn OS", read("/etc/os-release") + ("Running from the installation drive (live session)\n" if live else "")),
        section("Kernel", run(["uname", "-a"]) + read("/proc/cmdline")),
        section("Started", run(["uptime"]) + ("UEFI\n" if Path("/sys/firmware/efi").is_dir() else "BIOS (legacy)\n") + run(["mokutil", "--sb-state"])),
        section("Virtual machine", run(["systemd-detect-virt"])),
        section("Processor", "\n".join(run(["lscpu"]).splitlines()[:24])),
        section("Memory", run(["free", "-h"])),
        section("Disks", run(["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS"]) + "\n" + run(["df", "-h", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay"])),
        section("Services that failed", run(["systemctl", "--failed", "--no-legend", "--no-pager"]) or "none\n"),
    ])
    say("Graphics, screens and other hardware")
    connectors = []
    for status in sorted(Path("/sys/class/drm").glob("card*-*/status")):
        try:
            modes = (status.parent / "modes").read_text().split()
            connectors.append(f"{status.parent.name}: {status.read_text().strip()}, {len(modes)} modes, first {modes[0] if modes else '-'}")
        except OSError:
            pass
    files["hardware.txt"] = "".join([
        section("PCI devices", run(["lspci", "-nnk"])),
        section("USB devices", run(["lsusb"])),
        section("Graphics (OpenGL)", run(["glxinfo", "-B"]) if shutil.which("glxinfo") else run(["eglinfo", "-B"])),
        section("Graphics (Vulkan)", run(["vulkaninfo", "--summary"])),
        section("Screen connectors", "\n".join(connectors) + "\n"),
        section("Screens, as the desktop has them", run(["gdbus", "call", "--session", "--dest", "org.huginn.Compositor", "--object-path",
                                                          "/org/huginn/Compositor", "--method", "org.huginn.Compositor.Displays"])),
        section("Sound", run(["wpctl", "status"]) + "\n" + run(["pactl", "info"])),
        section("Network devices", run(["nmcli", "general", "status"]) + "\n" + run(["nmcli", "-f", "DEVICE,TYPE,STATE", "device", "status"])
                + "\n" + run(["ip", "-br", "link"]) + "\n" + run(["rfkill", "list"])),
        section("Bluetooth", run(["bluetoothctl", "show"])),
        section("Temperatures", run(["sensors"])),
    ])
    say("The logs")
    files["log-this-start.txt"] = run(["journalctl", "-b", "-o", "short-monotonic", "--no-pager", "-n", "6000"], 60)
    files["problems.txt"] = "".join([
        section("Warnings and errors since this start", run(["journalctl", "-b", "-p", "warning", "-o", "short-monotonic", "--no-pager", "-n", "3000"], 60)),
        section("Errors in the start before (if it ended badly, its end is here)", run(["journalctl", "-b", "-1", "-p", "err", "--no-pager", "-n", "800"], 60)
                + run(["journalctl", "-b", "-1", "--no-pager", "-n", "150"], 60)),
    ])
    files["kernel.txt"] = run(["journalctl", "-k", "-b", "-o", "short-monotonic", "--no-pager", "-n", "4000"], 60)
    home = Path.home()
    sess = home / ".local" / "share" / "sddm" / "wayland-session.log"
    files["desktop-session.txt"] = (section("This session (the compositor, the shell and the apps)", read(sess, 6000))
                                    + (section("The session before", read(sess.with_name("wayland-session.log.old"), 3000))
                                       if sess.with_name("wayland-session.log.old").exists() else ""))
    say("Crashes")
    crashes = run(["coredumpctl", "list", "--no-pager", "--since", "-7d"])
    detail = ""
    try:
        listed = json.loads(run(["coredumpctl", "list", "--json=short", "--no-pager", "--since", "-7d"]) or "[]")
        for c in listed[-3:]:
            detail += section(f"Crash of {c.get('exe', '?')} (pid {c.get('pid')})", run(["coredumpctl", "info", "--no-pager", str(c.get("pid"))], 40))
    except ValueError:
        pass
    files["crashes.txt"] = section("Crashes in the last week", crashes) + detail
    displays = home / ".config" / "huginn" / "displays.json"
    if displays.exists():
        try:
            data = json.loads(displays.read_text())
            files["screens-saved.txt"] = json.dumps({(f"screen {n + 1}" if not k.startswith("_") else k): v for n, (k, v) in enumerate(data.items())}, indent=1)
        except (OSError, ValueError):
            pass
    return files


README = """Huginn OS problem report, made {when}.

These are plain text files: open any of them to see what's in it.
  system.txt            Huginn OS's version, the kernel, processor, memory, disks, services that failed
  hardware.txt          graphics (with the driver in use), screens, sound, network devices, Bluetooth, temperatures
  log-this-start.txt    the system's log since the computer started
  problems.txt          its warnings and errors, and the errors of the start before
  kernel.txt            the kernel's messages (drivers, graphics, sleep and wake)
  desktop-session.txt   the desktop's own log (the compositor, the shell, the apps)
  crashes.txt           programs that crashed in the last week, with where
  screens-saved.txt     the screen settings saved in Settings › Displays

Your name, user name and computer's name, the names of networks and Bluetooth devices, IP and MAC addresses and
e-mail addresses were replaced (by "Person", "user", "this-computer", "a-name", "a-network", x.x.x.x and so on).
Nothing from your own files is in it.
"""


def make(folder: Path = None, say=print) -> Path:
    """Gathers, scrubs and writes the report; returns the .zip."""
    scrub = Scrubber(private_names())
    files = gather(say)
    now = dt.datetime.now()
    folder = folder or next((p for p in (Path.home() / "Documents", Path.home()) if p.is_dir()), Path.home())
    out = folder / f"Huginn OS report {now:%Y-%m-%d %H.%M}.zip"
    n = 1
    while out.exists():
        n += 1
        out = folder / f"Huginn OS report {now:%Y-%m-%d %H.%M} ({n}).zip"
    say("Writing it")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README.format(when=now.strftime("%d %B %Y at %H:%M")))
        for name, text in files.items():
            text = text[-LIMIT:] if len(text) > LIMIT else text
            z.writestr(name, scrub(text))
    return out


if __name__ == "__main__":
    quiet = "--quiet" in sys.argv
    where = Path(sys.argv[sys.argv.index("--to") + 1]) if "--to" in sys.argv else None
    path = make(where, say=(lambda *_: None) if quiet else (lambda t: print(f"… {t}", file=sys.stderr)))
    print(path)
