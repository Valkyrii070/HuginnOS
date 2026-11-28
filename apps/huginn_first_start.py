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
# browsers in Windows whose bookmarks come over (each person's AppData): Chromium's keep a Bookmarks file in each
# profile, Firefox's a places.sqlite. Only the bookmarks: saved passwords and the like stay in Windows.
BOOKMARK_BROWSERS = [("Edge", "chromium", "AppData/Local/Microsoft/Edge/User Data"), ("Chrome", "chromium", "AppData/Local/Google/Chrome/User Data"),
                     ("Brave", "chromium", "AppData/Local/BraveSoftware/Brave-Browser/User Data"), ("Vivaldi", "chromium", "AppData/Local/Vivaldi/User Data"),
                     ("Opera", "chromium", "AppData/Roaming/Opera Software/Opera Stable"), ("Firefox", "firefox", "AppData/Roaming/Mozilla/Firefox/Profiles")]
BROWSER_DATA = ".local/share/SafariQt/SafariQt/browser-data.json"   # Huginn's (the browser's own name for its folder)
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


def windows_bookmarks(person: Path) -> list:
    """Bookmarks in a Windows person's browsers (their folder, read-only): [{"browser", "title", "url"}], web pages only,
    each address once, the bookmarks bar first."""
    out, seen = [], set()

    def add(browser, title, url):
        if isinstance(url, str) and url.startswith(("http://", "https://")) and len(url) < 4096 and url not in seen:
            seen.add(url)
            out.append({"browser": browser, "title": (str(title or "").strip() or url)[:300], "url": url})
    for browser, kind, rel in BOOKMARK_BROWSERS:
        base = person / rel
        try:
            dirs = [base] + sorted(d for d in base.iterdir() if d.is_dir()) if base.is_dir() else []
        except OSError:
            continue
        for d in dirs:
            if kind == "chromium" and (d / "Bookmarks").is_file():
                try:
                    roots = json.loads((d / "Bookmarks").read_text(encoding="utf-8")).get("roots", {})
                except (OSError, ValueError, AttributeError):
                    continue

                def walk(node, depth=0):
                    if not isinstance(node, dict) or depth > 40:
                        return
                    if node.get("type") == "url":
                        add(browser, node.get("name"), node.get("url"))
                    for child in node.get("children") or []:
                        walk(child, depth + 1)
                for key in ("bookmark_bar", "other", "synced"):
                    walk(roots.get(key) if isinstance(roots, dict) else None)
            elif kind == "firefox" and (d / "places.sqlite").is_file():
                import sqlite3
                try:                                             # (read where it is, changing nothing: immutable)
                    db = sqlite3.connect(f"file:{d / 'places.sqlite'}?mode=ro&immutable=1", uri=True)
                    rows = db.execute("SELECT b.title, p.url FROM moz_bookmarks b JOIN moz_places p ON b.fk = p.id "
                                      "WHERE b.type = 1 ORDER BY b.parent, b.position").fetchall()
                    db.close()
                except sqlite3.Error:
                    continue
                for title, url in rows:
                    add(browser, title, url)
    return out


def bookmarks_html(items: list) -> str:
    """A bookmarks file in the usual format (Huginn: File › Import › Bookmarks File; any browser can read it)."""
    from html import escape
    rows = "".join(f'    <DT><A HREF="{escape(b["url"])}">{escape(b["title"])}</A>\n' for b in items)
    return ("<!DOCTYPE NETSCAPE-Bookmark-file-1>\n<META HTTP-EQUIV=\"Content-Type\" CONTENT=\"text/html; charset=UTF-8\">\n"
            "<TITLE>Bookmarks</TITLE>\n<H1>Bookmarks from Windows</H1>\n<DL><p>\n" + rows + "</DL><p>\n")


def browser_running() -> bool:
    for p in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            if b"safari_browser" in p.read_bytes():
                return True
        except OSError:
            continue
    return False


def bring_bookmarks(person: Path, home: Path, owner: str, running=browser_running) -> str:
    """Windows' bookmarks into Huginn's Favorites (added after any already there, none twice). With Huginn open, its
    own copy would win, so then they're left in a bookmarks file in the home to import."""
    items = windows_bookmarks(person)
    if not items:
        return "No bookmarks were found in Windows"
    data_path = home / BROWSER_DATA
    made = []
    try:
        if running():
            raise OSError("open")
        data = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else {}
        if not isinstance(data, dict):
            raise OSError("not ours")
        have = data.get("bookmarks") if isinstance(data.get("bookmarks"), list) else []
        urls = {b.get("url") for b in have if isinstance(b, dict)}
        new = [{"title": b["title"], "url": b["url"]} for b in items if b["url"] not in urls]
        data["bookmarks"] = have + new
        for d in reversed(data_path.relative_to(home).parents[:-1]):
            if not (home / d).exists():
                (home / d).mkdir()
                made.append(home / d)
        tmp = data_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, data_path)
        made.append(data_path)
        note = f"{len(new)} bookmarks from Windows are in Huginn's Favorites"
    except (OSError, ValueError):
        target = home / "Bookmarks from Windows.html"
        target.write_text(bookmarks_html(items), encoding="utf-8")
        made.append(target)
        note = f"{len(items)} bookmarks from Windows are in “Bookmarks from Windows” in your home: Huginn's File › Import › Bookmarks File brings them in"
    if owner:
        for m in made:
            subprocess.run(["chown", f"{owner}:{owner}", str(m)], capture_output=True)
    return note


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
        note = "Windows' folders are in Files, under Windows"
        if win.get("bookmarks"):
            note += ". " + bring_bookmarks(root / "mnt/windows/Users" / win["user"], home, owner)
        return note
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
        note = f"{total} files brought over from Windows" if win.get("folders") else ""
        if win.get("bookmarks"):
            note = (note + ". " if note else "") + bring_bookmarks(where / "Users" / win["user"], home, owner)
        return note
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
