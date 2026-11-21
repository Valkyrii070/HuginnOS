"""Huginn OS's restore points: a copy of the system before each change to its software, to go back to.

The installer puts Huginn OS on btrfs, in subvolumes: @ (the system, mounted at /), @home (your files, never touched by
going back), @snapshots (the restore points) and @swap. A restore point is a read-only snapshot of @, taken in a
moment and taking room only for what changes after it. Going back renames @ out of the way (kept as
@before-undo-<when>, until Settings › Software Update tidies it) and makes a writable copy of the restore point the
new @, which the next start uses. With an encrypted disk the kernels live on a plain /boot that isn't snapshotted, so
each restore point keeps a copy of its kernel there too.

Restore points are taken by themselves before apt changes anything (an apt hook: DPkg::Pre-Invoke, which Software
Update's PackageKit runs too), at most one every ten minutes; Settings can make one too. The start-up menu lists them
("Huginn OS restore points"): starting one goes back first (the initramfs does it: huginn.undo=N), for a system that won't
start after an update.

Earlier versions of your files: every hour, a read-only snapshot of @home goes into /home/.versions (inside @home, so
it's yours to read with your own permissions and nobody else's; snapshots don't take in each other, nor caches and
game libraries, which the installer makes subvolumes of their own). Kept: every one from the last day, then one a day
for a week; fewer when the disk runs short. Files' Earlier Versions… reads them.

    huginn-snapshot list                    the restore points, as JSON (also kept in /var/lib/huginn/snapshots.json)
    huginn-snapshot create [reason]         a restore point now
    huginn-snapshot auto                    the apt hook: one now unless one was made in the last ten minutes
    huginn-snapshot undo N                  go back to restore point N (at the next start)
    huginn-snapshot forget N                remove a restore point
    huginn-snapshot tidy                    remove what going back left behind (@before-undo-…)
    huginn-snapshot menu                    write the start-up menu's list again
    huginn-snapshot finish                  at start-up: after going back from the start-up menu, put /boot in order
    huginn-snapshot home                    the hourly snapshot of your files, and thinning out the older ones
"""
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

KEEP = 6                     # restore points kept (the oldest go first; one you made yourself is kept over automatic ones)
BOOT_KEEP = 3                # of those, how many keep a kernel on a separate /boot (it has 1.5 GB)
AUTO_GAP = 600               # seconds: apt runs dpkg several times for one change
STATE = Path("/var/lib/huginn/snapshots.json")
MENU = "huginn-snapshots.cfg"


class Problem(Exception):
    pass


def run(cmd: list, check: bool = True, timeout: int = 600) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=dict(os.environ, LC_ALL="C"))
    if check and r.returncode != 0:
        raise Problem(f"{Path(cmd[0]).name}: {(r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else 'exit ' + str(r.returncode)}")
    return r.stdout


def mount_of(path: str = "/") -> dict:
    """What's mounted at `path`: {"source", "fstype", "options", "subvol"} (source without btrfs' [/subvol] tail)."""
    try:
        data = json.loads(run(["findmnt", "-J", "-o", "SOURCE,FSTYPE,OPTIONS,TARGET", "--mountpoint", path]))
        fs = data["filesystems"][0]
    except (Problem, ValueError, KeyError, IndexError, OSError):
        return {}
    opts = fs.get("options") or ""
    sub = re.search(r"(?:^|,)subvol=([^,]+)", opts)
    return {"source": re.sub(r"\[.*\]$", "", fs.get("source") or ""), "fstype": fs.get("fstype", ""), "options": opts,
            "subvol": sub.group(1) if sub else ""}


def system_device() -> str:
    """The btrfs device the system runs from, if it's laid out for restore points (/ is subvolume @); else ""."""
    root = mount_of("/")
    if root.get("fstype") != "btrfs" or root.get("subvol").strip("/") != "@":
        return ""
    return root["source"]


def separate_boot() -> bool:
    boot = mount_of("/boot")
    return bool(boot) and boot.get("fstype") != "btrfs"


@contextlib.contextmanager
def top_level(dev: str):
    """The btrfs file system's top (subvolid 5), where @, @home and @snapshots sit, mounted for a moment."""
    where = Path(tempfile.mkdtemp(prefix="huginn-top-", dir="/run" if os.access("/run", os.W_OK) else None))
    run(["mount", "-t", "btrfs", "-o", "subvolid=5", dev, str(where)])
    try:
        yield where
    finally:
        subprocess.run(["umount", str(where)], capture_output=True)
        with contextlib.suppress(OSError):
            where.rmdir()


def read_points(top: Path) -> list:
    out = []
    folder = top / "@snapshots"
    if not folder.is_dir():
        return out
    for d in folder.iterdir():
        if not d.name.isdigit() or not (d / "snapshot").is_dir():
            continue
        try:
            info = json.loads((d / "info.json").read_text())
        except (OSError, ValueError):
            info = {}
        out.append({"n": int(d.name), "date": float(info.get("date") or d.stat().st_mtime), "reason": info.get("reason") or "A restore point",
                    "kernel": info.get("kernel", ""), "mine": bool(info.get("mine")), "bootCopy": bool(info.get("bootCopy"))})
    return sorted(out, key=lambda p: p["n"], reverse=True)


def leftovers(top: Path) -> list:
    return sorted(p.name for p in top.iterdir() if p.name.startswith("@before-undo-"))


def save_state(points: list, left: list, state: Path = STATE) -> None:
    """What Settings shows, readable without root."""
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        part = state.with_name(".snapshots.json.saving")
        part.write_text(json.dumps({"points": points, "leftovers": left, "updated": time.time()}, indent=1))
        os.chmod(part, 0o644)
        os.replace(part, state)
    except OSError:
        pass


def subvolume_delete(path: Path) -> None:
    run(["btrfs", "subvolume", "delete", str(path)])


def prune(top: Path, boot: Path = None, keep: int = KEEP, boot_keep: int = BOOT_KEEP) -> None:
    """Keep the newest `keep` restore points (ones made by you before automatic ones), and kernel copies for the
    newest `boot_keep` of them."""
    points = read_points(top)
    autos = [p for p in points if not p["mine"]]
    while len(points) > keep and autos:
        gone = autos.pop()                                     # the oldest automatic one
        points.remove(gone)
        d = top / "@snapshots" / str(gone["n"])
        subvolume_delete(d / "snapshot")
        shutil.rmtree(d, ignore_errors=True)
    if boot is not None and (boot / "huginn-snapshots").is_dir():
        wanted = {str(p["n"]) for p in points[:boot_keep]}
        for d in (boot / "huginn-snapshots").iterdir():
            if d.name not in wanted:
                shutil.rmtree(d, ignore_errors=True)


def create(reason: str = "", dev: str = "", mine: bool = False, boot: Path = None, kernel: str = "", state: Path = STATE,
           menu: bool = True) -> dict:
    dev = dev or system_device()
    if not dev:
        raise Problem("Restore points need Huginn OS installed on btrfs (as the installer does). This system isn't.")
    if boot is None and separate_boot():
        boot = Path("/boot")
    kernel = kernel or boot_kernel(boot or Path("/boot"))
    with top_level(dev) as top:
        (top / "@snapshots").mkdir(exist_ok=True)
        if not (top / "@").is_dir():
            raise Problem("The system's subvolume (@) isn't where restore points expect it.")
        n = max([p["n"] for p in read_points(top)] + [0]) + 1
        d = top / "@snapshots" / str(n)
        d.mkdir(parents=True, exist_ok=True)
        run(["btrfs", "subvolume", "snapshot", "-r", str(top / "@"), str(d / "snapshot")])
        info = {"n": n, "date": time.time(), "reason": reason or "A restore point", "kernel": kernel, "mine": mine, "bootCopy": False}
        if boot is not None:
            copied = boot / "huginn-snapshots" / str(n)
            try:
                copied.mkdir(parents=True, exist_ok=True)
                for name in (f"vmlinuz-{kernel}", f"initrd.img-{kernel}"):
                    if (boot / name).exists():
                        shutil.copy2(boot / name, copied / name)
                info["bootCopy"] = (copied / f"vmlinuz-{kernel}").exists()
            except OSError:
                shutil.rmtree(copied, ignore_errors=True)
        (d / "info.json").write_text(json.dumps(info, indent=1))
        prune(top, boot)
        points, left = read_points(top), leftovers(top)
    save_state(points, left, state)
    if menu:
        write_menu(points)
    return info


def boot_kernel(boot: Path) -> str:
    """The kernel a restore point starts: the one running, if its files are in /boot (they are, normally), else the
    newest there. (Inside the installer, or a chroot, the running kernel can be another system's.)"""
    running = os.uname().release
    if (boot / f"vmlinuz-{running}").exists():
        return running
    found = sorted((p.name[len("vmlinuz-"):] for p in boot.glob("vmlinuz-*")),
                   key=lambda v: [int(x) if x.isdigit() else x for x in re.split(r"[.-]", v)])
    return found[-1] if found else running


def auto(reason: str = "Before software was installed or updated") -> dict:
    """The apt hook: never stops apt; skips when the last restore point is under ten minutes old, and while Huginn OS
    is being installed (the installer makes the first one itself, at the end)."""
    if os.environ.get("HUGINN_INSTALLING"):
        return {}
    dev = system_device()
    if not dev:
        return {}
    try:
        recent = json.loads(STATE.read_text()).get("points", [])
    except (OSError, ValueError):
        recent = []
    if recent and time.time() - max(p["date"] for p in recent) < AUTO_GAP:
        return {}
    return create(reason, dev)


def undo(n: int, dev: str = "", boot: Path = None, state: Path = STATE, finish_boot: bool = True) -> dict:
    """Make restore point n the system the next start runs. The system as it is now is kept beside it."""
    dev = dev or system_device()
    if not dev:
        raise Problem("This system has no restore points.")
    if boot is None and separate_boot():
        boot = Path("/boot")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with top_level(dev) as top:
        src = top / "@snapshots" / str(n) / "snapshot"
        if not src.is_dir():
            raise Problem(f"Restore point {n} isn't there any more.")
        point = next((p for p in read_points(top) if p["n"] == n), {})
        os.rename(top / "@", top / f"@before-undo-{stamp}")
        try:
            run(["btrfs", "subvolume", "snapshot", str(src), str(top / "@")])
        except Problem:
            os.rename(top / f"@before-undo-{stamp}", top / "@")         # nothing changed
            raise
        if boot is not None and finish_boot:
            boot_from(top / "@", boot, n, point.get("kernel", ""))
        points, left = read_points(top), leftovers(top)
    save_state(points, left, state)
    return {"n": n, "restart": True, "kept": f"@before-undo-{stamp}"}


def boot_from(system: Path, boot: Path, n: int, kernel: str) -> None:
    """A separate /boot, after going back: the restore point's kernel back on it, and kernels the restored system
    has no modules for taken off, then GRUB's list written again from inside the restored system."""
    copied = boot / "huginn-snapshots" / str(n)
    if kernel and copied.is_dir():
        for f in copied.iterdir():
            if not (boot / f.name).exists():
                shutil.copy2(f, boot / f.name)
    have = {p.name for p in (system / "lib/modules").iterdir()} if (system / "lib/modules").is_dir() else set()
    if not have:
        return
    for k in (boot.glob("vmlinuz-*")):
        version = k.name[len("vmlinuz-"):]
        if version not in have:
            for name in (f"vmlinuz-{version}", f"initrd.img-{version}", f"System.map-{version}", f"config-{version}"):
                with contextlib.suppress(OSError):
                    (boot / name).unlink()
    for link, prefix in (("vmlinuz", "vmlinuz-"), ("initrd.img", "initrd.img-")):
        newest = sorted((p.name for p in boot.glob(prefix + "*")), key=_vkey)
        if newest:
            q = boot / link
            with contextlib.suppress(OSError):
                q.unlink()
            with contextlib.suppress(OSError):
                q.symlink_to(newest[-1])
    if (system / "usr/sbin/update-grub").exists() and (system / "proc").is_dir():
        binds = []
        try:
            for what in ("/dev", "/proc", "/sys", "/run"):
                run(["mount", "--bind", what, str(system / what.lstrip("/"))])
                binds.append(system / what.lstrip("/"))
            run(["mount", "--bind", str(boot), str(system / "boot")])
            binds.append(system / "boot")
            efi = mount_of("/boot/efi")
            if efi:
                run(["mount", "--bind", "/boot/efi", str(system / "boot/efi")])
                binds.append(system / "boot/efi")
            run(["chroot", str(system), "update-grub"], check=False, timeout=900)
        finally:
            for b in reversed(binds):
                subprocess.run(["umount", "-l", str(b)], capture_output=True)


def _vkey(name: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", name))


def forget(n: int, dev: str = "", state: Path = STATE) -> None:
    dev = dev or system_device()
    if not dev:
        raise Problem("This system has no restore points.")
    with top_level(dev) as top:
        d = top / "@snapshots" / str(n)
        if (d / "snapshot").is_dir():
            subvolume_delete(d / "snapshot")
        shutil.rmtree(d, ignore_errors=True)
        points, left = read_points(top), leftovers(top)
    shutil.rmtree(Path("/boot/huginn-snapshots") / str(n), ignore_errors=True)
    save_state(points, left, state)
    write_menu(points)


def tidy(dev: str = "", state: Path = STATE) -> int:
    """Remove the systems going back left behind (@before-undo-…)."""
    dev = dev or system_device()
    if not dev:
        return 0
    with top_level(dev) as top:
        gone = 0
        for name in leftovers(top):
            # a subvolume holding others (systemd makes /var/lib/machines one) can't go until they have
            inner = [line.split(" path ", 1)[1] for line in run(["btrfs", "subvolume", "list", "-o", str(top / name)], check=False).splitlines()
                     if " path " in line]
            for path in sorted(inner, key=len, reverse=True):
                subprocess.run(["btrfs", "subvolume", "delete", str(top / path)], capture_output=True)
            subvolume_delete(top / name)
            gone += 1
        points, left = read_points(top), leftovers(top)
    save_state(points, left, state)
    return gone


# ---------------------------------------------------------------------------------------------- the start-up menu
def kernel_args(cmdline: str = None) -> str:
    """This start's kernel arguments, for starting a restore point the same way (minus GRUB's own and ours)."""
    if cmdline is None:
        try:
            cmdline = Path("/proc/cmdline").read_text()
        except OSError:
            cmdline = ""
    keep = [a for a in cmdline.split() if not a.startswith(("BOOT_IMAGE=", "huginn.undo=", "rootflags=", "initrd="))]
    return " ".join(keep + ["rootflags=subvol=@"])


def menu_text(points: list, fs_uuid: str, boot_uuid: str, args: str) -> str:
    """GRUB's submenu of restore points. With /boot inside btrfs each starts its own kernel from inside its snapshot;
    with a separate /boot, the kernel copy kept there for it."""
    if not points:
        return ""
    lines = ["# The restore points (huginn-snapshot writes this; /etc/grub.d/41_huginn_snapshots reads it).",
             "submenu 'Huginn OS restore points' --id huginn-restore-points {"]
    for p in points:
        when = time.strftime("%a %d %b %Y, %H:%M", time.localtime(p["date"]))
        title = f"{when}: {p['reason']}".replace("'", "")
        k = p.get("kernel", "")
        if not k:
            continue
        if boot_uuid:
            if not p.get("bootCopy"):
                continue
            where, base = boot_uuid, f"/huginn-snapshots/{p['n']}"
        else:
            where, base = fs_uuid, f"/@snapshots/{p['n']}/snapshot/boot"
        lines += [f"  menuentry '{title}' --class huginn {{",
                  "    insmod gzio", "    insmod part_gpt", "    insmod btrfs" if not boot_uuid else "    insmod ext2",
                  f"    search --no-floppy --fs-uuid --set=root {where}",
                  "    echo 'Going back to a restore point…'",
                  f"    linux {base}/vmlinuz-{k} {args} huginn.undo={p['n']}",
                  f"    initrd {base}/initrd.img-{k}",
                  "  }"]
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_menu(points: list = None, grub_dir: Path = Path("/boot/grub")) -> None:
    root, boot = mount_of("/"), mount_of("/boot")
    uuid = run(["blkid", "-s", "UUID", "-o", "value", root.get("source", "")], check=False).strip() if root else ""
    boot_uuid = ""
    if boot and boot.get("fstype") != "btrfs":
        boot_uuid = run(["blkid", "-s", "UUID", "-o", "value", boot["source"]], check=False).strip()
    if points is None:
        try:
            points = json.loads(STATE.read_text()).get("points", [])
        except (OSError, ValueError):
            points = []
    if not grub_dir.is_dir():
        return
    text = menu_text(points, uuid, boot_uuid, kernel_args())
    target = grub_dir / MENU
    if text:
        part = grub_dir / f".{MENU}.saving"
        part.write_text(text)
        os.replace(part, target)
    elif target.exists():
        target.unlink()


def finish() -> None:
    """At start-up: if the initramfs just went back to a restore point (it leaves /run/huginn-undone), put a separate
    /boot in order for the restored system and say so to the person (a notice Settings and the shell read)."""
    flag = Path("/run/huginn-undone")
    if not flag.exists():
        return
    try:
        n = int(flag.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        n = 0
    dev = system_device()
    if dev and separate_boot():
        point = {}
        with top_level(dev) as top:
            point = next((p for p in read_points(top) if p["n"] == n), {})
        boot_from(Path("/"), Path("/boot"), n, point.get("kernel", ""))
    with contextlib.suppress(OSError):
        Path("/var/lib/huginn").mkdir(parents=True, exist_ok=True)
        Path("/var/lib/huginn/undone").write_text(json.dumps({"n": n, "at": time.time()}))
    if dev:
        with top_level(dev) as top:
            save_state(read_points(top), leftovers(top))
    flag.unlink(missing_ok=True)


# ------------------------------------------------------------------------------- earlier versions of your files
VERSIONS = Path("/home/.versions")
VERSION_STAMP = "%Y-%m-%d_%H%M"
KEEP_DAYS = 7
MIN_FREE = 0.10                                                   # fewer versions when the disk has less than this free


def home_ready(home: Path = Path("/home")) -> bool:
    m = mount_of(str(home))
    return m.get("fstype") == "btrfs" and m.get("subvol", "").strip("/") == "@home"


def version_dirs(versions: Path = VERSIONS) -> list:
    """(time, path) of each snapshot of your files, newest first."""
    out = []
    try:
        for d in versions.iterdir():
            try:
                out.append((time.mktime(time.strptime(d.name, VERSION_STAMP)), d))
            except ValueError:
                continue
    except OSError:
        return []
    return sorted(out, reverse=True)


def thin(stamps: list, now: float) -> set:
    """Which to keep, of [(time, key)]: all from the last day, then the newest of each day for a week."""
    keep, days = set(), set()
    for t, key in sorted(stamps, reverse=True):
        if now - t <= 86400:
            keep.add(key)
        elif now - t <= KEEP_DAYS * 86400:
            day = time.strftime("%Y-%m-%d", time.localtime(t))
            if day not in days:
                days.add(day)
                keep.add(key)
    return keep


def free_share(path: Path) -> float:
    try:
        st = os.statvfs(path)
        return st.f_bavail / st.f_blocks if st.f_blocks else 1.0
    except OSError:
        return 1.0


def home_version(home: Path = Path("/home"), now: float = None, check_mount: bool = True) -> dict:
    """The hourly snapshot of @home, then the older ones thinned out (and more of them while the disk is short)."""
    if check_mount and not home_ready(home):
        return {"skipped": "your files aren't on btrfs subvolume @home"}
    now = now or time.time()
    versions = home / ".versions"
    versions.mkdir(mode=0o755, exist_ok=True)
    name = time.strftime(VERSION_STAMP, time.localtime(now))
    made = ""
    if not (versions / name).exists():
        run(["btrfs", "subvolume", "snapshot", "-r", str(home), str(versions / name)])
        made = name
    have = version_dirs(versions)
    keep = thin([(t, str(d)) for t, d in have], now)
    removed = []
    for t, d in have:
        if str(d) not in keep:
            run(["btrfs", "subvolume", "delete", str(d)])
            removed.append(d.name)
    have = version_dirs(versions)
    while len(have) > 1 and free_share(home) < MIN_FREE:              # short of room: the oldest go first, the newest stays
        t, d = have.pop()
        run(["btrfs", "subvolume", "delete", str(d)])
        removed.append(d.name)
    return {"made": made, "removed": removed, "kept": len(version_dirs(versions))}


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "list":
        try:
            print(STATE.read_text())
        except OSError:
            print(json.dumps({"points": [], "leftovers": [], "available": bool(system_device())}))
        return 0
    if os.geteuid() != 0:
        print(json.dumps({"error": "Restore points need root (pkexec)."}))
        return 1
    try:
        if cmd == "auto":
            auto()
        elif cmd == "create":
            print(json.dumps(create(" ".join(rest)[:80] or "Made by you", mine=True)))
        elif cmd == "undo" and rest and rest[0].isdigit():
            print(json.dumps(undo(int(rest[0]))))
        elif cmd == "forget" and rest and rest[0].isdigit():
            forget(int(rest[0]))
        elif cmd == "tidy":
            print(json.dumps({"removed": tidy()}))
        elif cmd == "menu":
            write_menu()
        elif cmd == "finish":
            finish()
        elif cmd == "home":
            print(json.dumps(home_version()))
        else:
            print(__doc__)
            return 2
    except Problem as err:
        if cmd == "auto":                                         # never stops apt
            print(f"huginn-snapshot: {err}", file=sys.stderr)
            return 0
        print(json.dumps({"error": str(err)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
