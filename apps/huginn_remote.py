"""Code on another computer, over SSH. The other computer needs nothing but an SSH server: its folder is mounted
here with sshfs (so every part of Code that reads files works on it as it is), and what should run there (Run, the
Build tab's tasks, a shell) is sent over ssh. One connection is shared by all of it, so a password or a key's
passphrase is asked for once, in Code's terminal, by ssh itself: Code never sees it.

    parse_target("astrid@build-box:/srv/game")   who, where, which folder
    mount_command(remote, mount)                 the sshfs line typed into the terminal
    wrap(remote, command, cwd)                   a command as it is run over there
    to_local / to_remote                         a path on one side as it is on the other

Plain functions, tested without a window. Not done over SSH: debugging, and the language helpers run here on the
mounted files (so they know this computer's installed libraries, not the other's).
"""
import os
import re
import shlex
import shutil
from pathlib import Path

MOUNTS = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn" / "remote"
_HOST = re.compile(r"[A-Za-z0-9]([A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$|\[[0-9A-Fa-f:]+\]$")
_USER = re.compile(r"[A-Za-z_][A-Za-z0-9._-]{0,63}$")


def parse_target(text: str) -> dict:
    """`user@host:/path`, `host:path`, `host`, or `ssh://user@host:2222/path` as {user, host, port, path, spec, label}.
    Raises ValueError (with words for the person) when it isn't one. A path not starting with / is from the home
    folder over there; no path at all is the home folder."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Type the computer's name, like astrid@build-box:/srv/game.")
    user, port, path = "", 0, ""
    if text.startswith("ssh://"):
        rest = text[6:]
        where, _, path = rest.partition("/")
        path = "/" + path if path else ""
        if "@" in where:
            user, where = where.rsplit("@", 1)
        m = re.match(r"(\[[0-9A-Fa-f:]+\]|[^:]+)(?::(\d+))?$", where)
        if not m:
            raise ValueError("That address doesn't read as a computer's name.")
        host, port = m.group(1), int(m.group(2) or 0)
    else:
        where, sep, path = text.partition(":") if not text.startswith("[") and "@[" not in text else _split_v6(text)
        if "@" in where:
            user, where = where.rsplit("@", 1)
        host = where
    host = host.strip()
    if not _HOST.match(host) or host.startswith("-"):
        raise ValueError(f"“{host}” isn't a computer's name Code can use.")
    if user and not _USER.match(user):
        raise ValueError(f"“{user}” isn't a user name Code can use.")
    if port and not 1 <= port <= 65535:
        raise ValueError("That port number is out of range.")
    if "\n" in path or "\0" in path or len(path) > 1024:
        raise ValueError("That folder's name can't be used.")
    spec = f"{user}@{host}" if user else host
    label = spec + (f":{port}" if port else "") + (":" + path if path else "")
    return {"user": user, "host": host, "port": port, "path": path, "spec": spec, "label": label}


def _split_v6(text: str) -> tuple:
    end = text.find("]")
    if end < 0:
        return text, "", ""
    return text[:end + 1], ":", text[end + 2:] if text[end + 1:end + 2] == ":" else ""


def mount_point(remote: dict) -> Path:
    """Where a remote folder is mounted here: one folder for each computer-and-folder."""
    name = re.sub(r"[^A-Za-z0-9._@-]+", "_", remote["label"]).strip("._") or "remote"
    return MOUNTS / name[:120]


def control_path() -> str:
    """ssh's shared connection: the first one asks for the password or passphrase, the rest ride on it."""
    return str(Path.home() / ".ssh" / "huginn-%C")


def ssh_options(remote: dict) -> list:
    opts = ["-o", "ControlMaster=auto", "-o", f"ControlPath={control_path()}", "-o", "ControlPersist=600", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3"]
    return opts + (["-p", str(remote["port"])] if remote.get("port") else [])


def mount_command(remote: dict, mount) -> str:
    """The line that mounts the folder (typed into Code's terminal, where ssh asks whatever it must). The remote user
    is shown as you (idmap), a dropped connection comes back (reconnect), and ssh's own options are the shared ones."""
    ssh = " ".join(shlex.quote(o) for o in ["ssh"] + ssh_options(remote))
    where = f"{remote['spec']}:{remote['path']}"
    return (f"mkdir -p -m 700 {shlex.quote(str(Path.home() / '.ssh'))} {shlex.quote(str(mount))} && sshfs -o reconnect,idmap=user,follow_symlinks,ServerAliveInterval=15,ssh_command={shlex.quote(ssh)} "
            f"{shlex.quote(where)} {shlex.quote(str(mount))} && echo 'Connected: Code is opening the folder.'")


def remote_root(remote: dict) -> str:
    """The folder over there, as its shell would name it ("." is the home folder)."""
    return remote.get("path") or "."


def to_remote(remote: dict, mount, local: str) -> str:
    """A path under the mount, as it is on the other computer."""
    mount, base = str(mount).rstrip("/"), remote_root(remote).rstrip("/") or "/"
    if local == mount:
        return base
    if local.startswith(mount + "/"):
        rest = local[len(mount) + 1:]
        return rest if base == "." else ("/" + rest if base == "/" else f"{base}/{rest}")
    return local


def to_local(remote: dict, mount, there: str) -> str:
    """A path on the other computer, as it is under the mount here ("" when it is outside the mounted folder)."""
    mount, base = str(mount).rstrip("/"), remote_root(remote).rstrip("/") or "/"
    if base == ".":
        return f"{mount}/{there}" if there and not there.startswith("/") else ""
    if there == base:
        return mount
    prefix = "/" if base == "/" else base + "/"
    return f"{mount}/{there[len(prefix):]}" if there.startswith(prefix) else ""


def wrap(remote: dict, command: str, cwd: str = "", tty: bool = False, mount=None) -> str:
    """A command as it is run on the other computer: in its folder there, with this computer's paths under the mount
    turned into the other's. Without a terminal (the Build tab) ssh must not stop to ask a question (BatchMode)."""
    if mount is not None:
        m, base = str(mount).rstrip("/"), remote_root(remote).rstrip("/") or "/"
        deep = "" if base == "." else "/" if base == "/" else base + "/"
        command = re.sub(re.escape(m) + r"(?![A-Za-z0-9._-])", lambda _: base, command.replace(m + "/", deep))
    there = cwd or remote_root(remote)
    inner = f"cd {shlex.quote(there)} && {command}" if there != "." else command
    opts = ssh_options(remote) + (["-t"] if tty else ["-o", "BatchMode=yes"])
    return " ".join(shlex.quote(a) for a in ["ssh"] + opts + [remote["spec"], inner])


def shell_command(remote: dict) -> str:
    """A shell over there, in the project's folder."""
    there = remote_root(remote)
    inner = f"cd {shlex.quote(there)} && exec \"$SHELL\" -l" if there != "." else 'exec "$SHELL" -l'
    return " ".join(shlex.quote(a) for a in ["ssh"] + ssh_options(remote) + ["-t", remote["spec"], inner])


def unmount_command(mount) -> list:
    tool = shutil.which("fusermount3") or shutil.which("fusermount")
    return [tool, "-u", str(mount)] if tool else ["umount", str(mount)]


def is_mounted(mount) -> bool:
    try:
        return os.path.ismount(str(mount))
    except OSError:
        return False


def config_hosts(path=None, cap: int = 40) -> list:
    """The computers ~/.ssh/config names (not its patterns), to choose from."""
    path = Path(path) if path else Path.home() / ".ssh" / "config"
    out = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for m in re.finditer(r"^[ \t]*Host[ \t]+(.+)$", text, re.M | re.I):
        for name in m.group(1).split():
            if not re.search(r"[*?!]", name) and _HOST.match(name) and name not in out:
                out.append(name)
    return out[:cap]


def tools_missing() -> list:
    return [t for t in ("ssh", "sshfs") if not shutil.which(t)]
