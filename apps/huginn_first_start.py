"""What was chosen while installing that needs the internet, or time, done in the background after the first start
(huginn-first-start.service, as root): media formats from Ubuntu or built here, fonts, printer drivers, NVIDIA's
driver, game-development tools, apps from Flathub, and the person's things from Windows.

    huginn_first_start.py                   do what /var/lib/huginn/first-start.json asks; exits 75 while offline,
                                            so systemd tries again later; the file becomes first-start.done at the end
    huginn_first_start.py --dry-run FILE    say what would be run for FILE, run nothing

Each task is done once: what's finished is kept in first-start.status.json (readable by everyone, for Settings), and a
task that fails three times is left, said so there, so one broken package doesn't hold the rest back.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

STATE = Path("/var/lib/huginn")
TASKS = STATE / "first-start.json"
STATUS = STATE / "first-start.status.json"
FFMPEG = "https://ffmpeg.org/releases/ffmpeg-8.0.tar.xz"
CODEC_BUILD_DEPS = ["build-essential", "nasm", "pkg-config", "curl", "xz-utils", "libx264-dev", "libx265-dev", "libfdk-aac-dev", "libvpx-dev",
                    "libopus-dev", "libdav1d-dev", "libmp3lame-dev", "libvorbis-dev", "libass-dev", "libfreetype-dev"]
CODEC_FLAGS = ["--prefix=/usr/local", "--enable-gpl", "--enable-nonfree", "--enable-libx264", "--enable-libx265", "--enable-libfdk-aac",
               "--enable-libvpx", "--enable-libopus", "--enable-libdav1d", "--enable-libmp3lame", "--enable-libvorbis", "--enable-libass",
               "--enable-libfreetype", "--disable-doc", "--disable-debug"]
FOLDER_NAMES = {"documents": "Documents", "pictures": "Pictures", "music": "Music", "videos": "Videos", "desktop": "Desktop", "downloads": "Downloads"}
OFFLINE = 75                                                     # EX_TEMPFAIL: systemd starts it again later


def plan_steps(tasks: dict) -> list:
    """The work, in order, as (key, words for a person, [commands]). Commands are argv lists, or ("copy", …) and
    ("link", …) for the Windows steps, done in Python."""
    steps = []
    env_apt = ["env", "DEBIAN_FRONTEND=noninteractive"]
    if tasks.get("packages") or tasks.get("build") or tasks.get("drivers"):
        steps.append(("update", "Looking for the latest packages", [env_apt + ["apt-get", "update"]]))
    if tasks.get("debconf"):
        steps.append(("debconf", "Accepting the licences you agreed to", [["debconf-set-selections", "\n".join(tasks["debconf"]) + "\n"]]))
    groups = {"formats": "Media formats", "fonts": "Fonts", "printers": "Printer drivers", "tools": "Game-development tools"}
    by = {"formats": [], "fonts": [], "printers": [], "tools": []}
    for p in tasks.get("packages") or []:
        key = ("formats" if p.startswith(("ubuntu-restricted", "libavcodec", "gstreamer")) else
               "fonts" if p.startswith(("fonts-", "ttf-")) else "printers" if p in ("printer-driver-all", "hplip") else "tools")
        by[key].append(p)
    for key, pkgs in by.items():
        if pkgs:
            steps.append((f"apt-{key}", f"Adding {groups[key].lower()}", [env_apt + ["apt-get", "install", "-y", "--no-install-recommends", *pkgs]]))
    if tasks.get("drivers"):
        steps.append(("drivers", "Adding NVIDIA's driver", [["ubuntu-drivers", "install"]]))
    if "codecs" in (tasks.get("build") or []):
        work = "/var/cache/huginn/codecs"
        steps.append(("build-codecs", "Building media formats on this computer", [
            env_apt + ["apt-get", "install", "-y", "--no-install-recommends", *CODEC_BUILD_DEPS],
            ["mkdir", "-p", work],
            ["curl", "-fsSL", "-o", f"{work}/ffmpeg.tar.xz", FFMPEG],
            ["tar", "-xJf", f"{work}/ffmpeg.tar.xz", "-C", work, "--strip-components=1"],
            ["sh", "-c", f"cd {work} && ./configure {' '.join(CODEC_FLAGS)} && nice -n 19 make -j$(nproc) && make install && ldconfig"]]))
    if tasks.get("flathub") is False:
        steps.append(("flathub", "Leaving out Flathub", [["flatpak", "remote-modify", "--disable", "flathub"]]))
    elif tasks.get("flatpaks"):
        steps.append(("flathub", "Adding Flathub", [["flatpak", "remote-add", "--if-not-exists", "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo"]]))
        for app in tasks["flatpaks"]:
            steps.append((f"flatpak-{app}", f"Adding {app.split('.')[-1]}", [["flatpak", "install", "-y", "--noninteractive", "flathub", app]]))
    win = tasks.get("windows")
    if win:
        if win.get("how") == "link":
            steps.append(("windows", "Putting Windows' folders in Files", [("link", win, tasks.get("owner", ""))]))
        else:
            steps.append(("windows", "Bringing your things from Windows", [("copy", win, tasks.get("owner", ""))]))
    return steps


def needs_internet(steps: list) -> bool:
    return any(k != "windows" and k != "debconf" for k, _w, _c in steps)


def online() -> bool:
    for host in ("archive.ubuntu.com", "dl.flathub.org"):
        if subprocess.run(["getent", "hosts", host], capture_output=True, timeout=20).returncode == 0:
            return True
    return False


def copy_new(src: Path, dst: Path, owner: str) -> tuple:
    """Copy a folder's files where they aren't already (nothing is overwritten); -> (files, bytes)."""
    files = size = 0
    for dirpath, _dirs, names in os.walk(src):
        rel = Path(dirpath).relative_to(src)
        for n in names:
            a, b = Path(dirpath) / n, dst / rel / n
            if b.exists() or a.is_symlink():
                continue
            try:
                b.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(a, b)
                files += 1
                size += b.stat().st_size
            except OSError:
                continue
    if owner:
        subprocess.run(["chown", "-R", f"{owner}:{owner}", str(dst)], capture_output=True)
    return files, size


def windows_step(kind: str, win: dict, owner: str, root: Path = Path("/"), mount=True) -> str:
    """Copy the chosen folders from Windows' person into the owner's home, or (link) mount Windows by itself at each
    start and put a Windows folder in the home that opens theirs. Windows is only ever read."""
    home = root / "home" / owner
    if kind == "link":
        fstab = root / "etc/fstab"
        try:
            import pwd
            ids = pwd.getpwnam(owner)
            uid, gid = ids.pw_uid, ids.pw_gid
        except (KeyError, ImportError):
            uid = gid = 1000
        line = f"UUID={win['uuid']} /mnt/windows ntfs3 ro,nofail,nodev,nosuid,uid={uid},gid={gid} 0 0\n"
        text = fstab.read_text() if fstab.exists() else ""
        if f"UUID={win['uuid']} " not in text:
            fstab.write_text(text + ("" if text.endswith("\n") or not text else "\n") + "# Windows, read-only (the installer, From Windows)\n" + line)
        (root / "mnt/windows").mkdir(parents=True, exist_ok=True)
        if mount:
            subprocess.run(["mount", "/mnt/windows"], capture_output=True, timeout=60)
        link = home / "Windows"
        if not link.exists() and not link.is_symlink():
            link.symlink_to(f"/mnt/windows/Users/{win['user']}")
        return "Windows' folders are in Files, under Windows"
    where = Path("/run/huginn-windows") if mount else root / "run/huginn-windows"
    where.mkdir(parents=True, exist_ok=True)
    if mount:
        r = subprocess.run(["mount", "-t", "ntfs3", "-o", "ro,nodev,nosuid,noexec", f"UUID={win['uuid']}", str(where)], capture_output=True, timeout=60)
        if r.returncode != 0:
            r = subprocess.run(["mount", "-t", "ntfs-3g", "-o", "ro", f"UUID={win['uuid']}", str(where)], capture_output=True, timeout=60)
            if r.returncode != 0:
                raise OSError("Windows couldn't be opened (if it's half shut down, start it and shut it down fully)")
    try:
        total = 0
        for key in win.get("folders") or []:
            name = FOLDER_NAMES.get(key)
            src = where / "Users" / win["user"] / name if name else None
            if src and src.is_dir():
                total += copy_new(src, home / name, owner)[0]
        return f"{total} files brought over from Windows"
    finally:
        if mount:
            subprocess.run(["umount", str(where)], capture_output=True, timeout=60)


def read_status() -> dict:
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {"done": [], "failed": {}, "now": "", "notes": []}


def write_status(st: dict) -> None:
    STATUS.write_text(json.dumps(st, indent=1))
    os.chmod(STATUS, 0o644)


def run_all(tasks: dict, runner=subprocess.run) -> int:
    steps = plan_steps(tasks)
    st = read_status()
    if needs_internet([s for s in steps if s[0] not in st["done"]]) and not online():
        st["now"] = "Waiting for the internet"
        write_status(st)
        return OFFLINE
    for key, words, cmds in steps:
        if key in st["done"] or st["failed"].get(key, 0) >= 3:
            continue
        st["now"] = words
        write_status(st)
        ok = True
        for cmd in cmds:
            if isinstance(cmd, tuple):
                try:
                    st["notes"].append(windows_step(cmd[0], cmd[1], cmd[2]))
                except OSError as err:
                    st["notes"].append(str(err))
                    ok = False
                continue
            if cmd[0] == "debconf-set-selections":
                r = runner(["debconf-set-selections"], input=cmd[1], text=True, capture_output=True)
            else:
                r = runner(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                ok = False
                st["notes"].append(f"{words}: {((r.stderr or '').strip().splitlines() or ['it stopped'])[-1][:200]}")
                break
        if ok:
            st["done"].append(key)
        else:
            st["failed"][key] = st["failed"].get(key, 0) + 1
        write_status(st)
    st["now"] = ""
    write_status(st)
    left = [k for k, _w, _c in steps if k not in st["done"] and st["failed"].get(k, 0) < 3]
    if not left:
        if TASKS.exists():
            TASKS.rename(TASKS.with_suffix(".done"))
        return 0
    return OFFLINE


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--dry-run":
        for key, words, cmds in plan_steps(json.loads(Path(sys.argv[2]).read_text())):
            print(f"{key}: {words}")
            for c in cmds:
                print("   ", c[0] if isinstance(c, tuple) else " ".join(c))
        return 0
    if os.geteuid() != 0:
        print("huginn-first-start runs as root (huginn-first-start.service)", file=sys.stderr)
        return 1
    if not TASKS.exists():
        return 0
    time.sleep(30)                                             # (the session first: this is the background)
    return run_all(json.loads(TASKS.read_text()))


if __name__ == "__main__":
    sys.exit(main())
