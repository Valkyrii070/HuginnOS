"""Ubuntu's own packages of the apps the App Store lists from Flathub, so an app can come from either.

An app from Ubuntu's archive runs on the system's own libraries: a Qt app then wears Huginn's own Qt look and puts its
menus in the top bar, which a Flathub app (with its own Qt, in its sandbox) can't. Flathub's is usually newer, and
sandboxed. The App Store offers both where both exist (apps/huginn_app.py, Store).

Which package is which app comes from Ubuntu's AppStream catalogue (DEP-11), which apt fetches with the package lists
when the `appstream` package is installed: /var/lib/apt/lists/*_dep11_Components-<arch>.yml.gz. An app is matched by
its AppStream id (ignoring case and a trailing .desktop), the ids it says it provides, or its launcher's name.

    catalogue()                  {matching id: {"package", "desktop", "name"}}
    match(cat, ids)              the entry for the first of an app's ids that Ubuntu has, or None
    installed()                  the names of the packages installed (dpkg's records)
    details(package)             {"version", "size"} of the package apt would install
    command(verb, package)       the command that installs or removes it (PackageKit, else apt under the password prompt)
"""
from __future__ import annotations

import gzip
import os
import re
import shutil
import subprocess
from pathlib import Path

LISTS = Path("/var/lib/apt/lists")
STATUS = Path("/var/lib/dpkg/status")
PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]{0,99}")
DESKTOP = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]{0,200}\.desktop")
# Ubuntu's packages of these are only a way to install the Snap (and Snap itself): not what anyone means here
SNAP_ONLY = {"firefox", "thunderbird", "chromium-browser", "chromium", "snapd", "snap-store"}
ARCH = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "armhf", "i686": "i386", "riscv64": "riscv64", "ppc64le": "ppc64el", "s390x": "s390x"}


def norm(ident: str) -> str:
    ident = (ident or "").strip().lower()
    return ident[:-8] if ident.endswith(".desktop") else ident


def _components(path: Path):
    """The desktop apps in one DEP-11 file: dicts with type, id, package, name, desktop ids and provided ids."""
    doc, top, sub = {}, "", ""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("---"):
                if doc:
                    yield doc
                doc, top, sub = {}, "", ""
                continue
            if not line.strip():
                continue
            if not line.startswith((" ", "-")):                  # a key of the component itself
                key, _, value = line.partition(":")
                top, sub = key.strip(), ""
                value = value.strip()
                if top in ("Type", "ID", "Package") and value:
                    doc[top] = value.strip("'\"")
                continue
            stripped = line.strip()
            if top == "Name" and line.startswith("  ") and not line.startswith("   ") and stripped.startswith("C:"):
                doc.setdefault("Name", stripped[2:].strip().strip("'\""))
            elif top in ("Launchable", "Provides") and line.startswith("  ") and not line.startswith("  -") and stripped.endswith(":"):
                sub = stripped[:-1]
            elif top in ("Launchable", "Provides") and stripped.startswith("- "):
                value = stripped[2:].strip().strip("'\"")
                if top == "Launchable" and sub == "desktop-id":
                    doc.setdefault("desktop", []).append(value)
                elif top == "Provides" and sub == "ids":
                    doc.setdefault("provides", []).append(value)
    if doc:
        yield doc


def catalogue(lists: Path = None, arch: str = "") -> dict:
    """{matching id: {"package", "desktop", "name"}} for every desktop app in Ubuntu's catalogue on this computer."""
    lists = lists or LISTS
    arch = arch or ARCH.get(os.uname().machine, os.uname().machine)
    out = {}
    try:
        files = sorted(Path(lists).glob(f"*_dep11_Components-{arch}.yml.gz"))
    except OSError:
        return out
    for f in files:
        try:
            for c in _components(f):
                if c.get("Type") not in ("desktop-application", "desktop") or not PACKAGE.fullmatch(c.get("Package", "")) \
                        or c["Package"] in SNAP_ONLY:
                    continue
                desktops = [d for d in c.get("desktop", []) if DESKTOP.fullmatch(d)]
                if not desktops and DESKTOP.fullmatch(c.get("ID", "")):
                    desktops = [c["ID"]]
                entry = {"package": c["Package"], "desktop": desktops[0] if desktops else "", "name": c.get("Name", "")}
                for ident in [c.get("ID", "")] + c.get("provides", []) + desktops:
                    if ident:
                        out.setdefault(norm(ident), entry)
        except (OSError, EOFError, UnicodeDecodeError):
            continue
    return out


def match(cat: dict, ids) -> dict | None:
    for ident in ids:
        found = cat.get(norm(ident)) if ident else None
        if found:
            return found
    return None


def installed(status: Path = None) -> set:
    """The packages dpkg says are installed."""
    status = status or STATUS
    out = set()
    try:
        text = Path(status).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for block in text.split("\n\n"):
        name = re.search(r"^Package: (\S+)", block, re.M)
        if name and re.search(r"^Status: install ok installed$", block, re.M):
            out.add(name.group(1))
    return out


def lists_age(lists: Path = None) -> float:
    """Seconds since Ubuntu's catalogue was last fetched (a very large number when it never was)."""
    import time
    lists = lists or LISTS
    try:
        newest = max((p.stat().st_mtime for p in Path(lists).glob("*_dep11_Components-*.yml.gz")), default=0.0)
    except OSError:
        newest = 0.0
    return time.time() - newest if newest else 1e12


def details(package: str, run=subprocess.run) -> dict:
    """The version apt would install, and its download size."""
    if not PACKAGE.fullmatch(package or ""):
        return {}
    try:
        text = run(["apt-cache", "show", "--no-all-versions", package], capture_output=True, text=True, timeout=20,
                   env={**os.environ, "LC_ALL": "C.UTF-8"}).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    version = re.search(r"^Version: (?:\d+:)?(\S+)", text, re.M)
    size = re.search(r"^Size: (\d+)", text, re.M)
    out = {}
    if version:                                              # 1:5.2.9+dfsg-2ubuntu1 -> 5.2.9 (the app's own version)
        v = version.group(1).rsplit("-", 1)[0] if "-" in version.group(1) else version.group(1)
        out["version"] = re.split(r"[+~]", v)[0]
    if size:
        n = int(size.group(1))
        out["size"] = f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{max(1, round(n / 1e3))} kB"
    return out


def command(verb: str, package: str, refresh: bool = False, which=shutil.which) -> list:
    """The command that installs ("install") or removes ("remove") one package: PackageKit's (it asks for the
    administrator's password itself), else apt-get under the system's password prompt. [] for a bad name."""
    if verb not in ("install", "remove") or not PACKAGE.fullmatch(package or ""):
        return []
    if which("pkgcli"):
        steps = (["pkgcli refresh"] if refresh else []) + [f"pkgcli {verb} -y {package}"]
        return ["sh", "-c", " && ".join(steps)] if refresh else ["pkgcli", verb, "-y", package]
    script = ("apt-get update && " if refresh and verb == "install" else "") + f'apt-get {verb} -y "$1"'
    return ["pkexec", "env", "DEBIAN_FRONTEND=noninteractive", "sh", "-c", script, "sh", package]


def refresh(run=subprocess.run, which=shutil.which) -> bool:
    """Fetch Ubuntu's package lists, and with them its app catalogue (PackageKit lets the person at the computer do
    this without a password). False where it can't (no PackageKit, offline)."""
    if not which("pkgcli"):
        return False
    try:
        return run(["pkgcli", "refresh"], capture_output=True, text=True, timeout=900).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


LAUNCHERS = ("/usr/share/applications", "/usr/local/share/applications")


def launcher(desktop: str, roots=None) -> str:
    """The launcher file of an app Ubuntu put in, or ""."""
    if not DESKTOP.fullmatch(desktop or ""):
        return ""
    for root in roots or LAUNCHERS:
        f = Path(root) / desktop
        if f.is_file():
            return str(f)
    return ""
