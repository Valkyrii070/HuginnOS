"""Dev containers for Code: a project's .devcontainer/devcontainer.json, run with Docker or Podman.

The project's folder is shared into the container at its workspace folder, so the files stay where they are and are
edited here as always. What runs (Run, the Build tab, the debugger, a shell) runs inside the container, and paths
are translated on the way in and on the way out, the same way they are for a folder on another computer.

What is read from devcontainer.json: image, or build (dockerfile, context, args, target); workspaceFolder and
workspaceMount; remoteUser / containerUser; containerEnv and remoteEnv; forwardPorts and appPort (published on this
computer only, 127.0.0.1); mounts; runArgs; init, privileged, capAdd, securityOpt; overrideCommand; and the
commands onCreateCommand, postCreateCommand and postStartCommand. Not done: Dev Container Features and Docker
Compose projects (Code says so instead of half-starting them).

Pure helpers, no Qt: every function here builds a command or reads a file, and the tests call them directly.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path

ENGINES = ("docker", "podman")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,254}$")
_USER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,63})?$")
_ENV = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def engine(prefer: str = "") -> str:
    """docker or podman, whichever is installed ("" when neither is)."""
    for name in ([prefer] if prefer in ENGINES else []) + list(ENGINES):
        if shutil.which(name):
            return name
    return ""


def find_config(root) -> Path | None:
    """The project's devcontainer.json: .devcontainer/devcontainer.json, .devcontainer.json, or the first one in a
    folder under .devcontainer/."""
    root = Path(root)
    for rel in (".devcontainer/devcontainer.json", ".devcontainer.json"):
        if (root / rel).is_file():
            return root / rel
    try:
        for sub in sorted((root / ".devcontainer").iterdir()):
            if (sub / "devcontainer.json").is_file():
                return sub / "devcontainer.json"
    except OSError:
        pass
    return None


def _strings(value) -> list:
    return [str(v) for v in value if isinstance(v, (str, int))] if isinstance(value, list) else []


def _commands(value) -> list:
    """A lifecycle command as shell lines: a string is a line, a list is a program and its arguments, an object is
    several of either (run one after another here, not side by side)."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        words = _strings(value)
        return [" ".join(shlex.quote(w) for w in words)] if words else []
    if isinstance(value, dict):
        return [line for v in value.values() for line in _commands(v)]
    return []


def read(root, load=None) -> dict:
    """The container a project asks for, as plain values, or a ValueError saying what Code can't do with it.
    `load` reads JSON with comments (huginn_vscode.load_jsonc)."""
    root = Path(root)
    path = find_config(root)
    if path is None:
        raise ValueError("This project has no .devcontainer/devcontainer.json.")
    if load is None:
        import huginn_vscode
        load = huginn_vscode.load_jsonc
    raw = load(path)
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} couldn't be read.")
    if raw.get("dockerComposeFile"):
        raise ValueError("This container is a Docker Compose project, which Code doesn't start yet. Start it yourself (docker compose up) and use the terminal.")
    name = root.name

    def put(text: str) -> str:
        """devcontainer.json's own variables."""
        text = str(text)
        for key, value in (("${localWorkspaceFolder}", str(root)), ("${localWorkspaceFolderBasename}", name),
                           ("${containerWorkspaceFolder}", workspace), ("${containerWorkspaceFolderBasename}", Path(workspace).name)):
            text = text.replace(key, value)
        return text
    workspace = f"/workspaces/{name}"
    workspace = put(raw.get("workspaceFolder") or workspace) if isinstance(raw.get("workspaceFolder") or "", str) else workspace
    if not workspace.startswith("/"):
        raise ValueError("workspaceFolder must be a full path inside the container.")
    build = raw.get("build") if isinstance(raw.get("build"), dict) else {}
    dockerfile = build.get("dockerfile") or build.get("dockerFile") or raw.get("dockerFile") or ""
    image = raw.get("image") if isinstance(raw.get("image"), str) else ""
    if not image and not dockerfile:
        raise ValueError(f"{path.name} names neither an image nor a Dockerfile.")
    if image and not _IMAGE.match(image):
        raise ValueError(f"“{image[:60]}” isn't an image name.")
    user = raw.get("remoteUser") or raw.get("containerUser") or ""
    if user and not (isinstance(user, str) and _USER.match(user)):
        raise ValueError("remoteUser isn't a user name.")
    env = {}
    for block in (raw.get("containerEnv"), raw.get("remoteEnv")):
        if isinstance(block, dict):
            env.update({k: put(v) for k, v in block.items() if isinstance(k, str) and _ENV.match(k) and isinstance(v, (str, int, float))})
    ports = []
    for p in (raw.get("forwardPorts") if isinstance(raw.get("forwardPorts"), list) else []) + (raw.get("appPort") if isinstance(raw.get("appPort"), list) else [raw.get("appPort")]):
        try:
            n = int(str(p).rsplit(":", 1)[-1])
        except (TypeError, ValueError):
            continue
        if 0 < n < 65536 and n not in ports:
            ports.append(n)
    mounts = []
    for m in raw.get("mounts") if isinstance(raw.get("mounts"), list) else []:
        if isinstance(m, dict) and m.get("target"):
            m = ",".join(f"{k}={m[k]}" for k in ("type", "source", "target") if m.get(k)) + (",readonly" if m.get("readonly") else "")
        if isinstance(m, str) and m.strip():
            mounts.append(put(m))
    context = (path.parent / str(build.get("context") or ".")).resolve()
    features = sorted(raw["features"]) if isinstance(raw.get("features"), dict) else []
    return {"file": str(path), "root": str(root), "title": str(raw.get("name") or name)[:80], "image": image,
            "dockerfile": str((path.parent / dockerfile).resolve()) if dockerfile else "", "context": str(context),
            "args": {str(k): put(v) for k, v in (build.get("args") if isinstance(build.get("args"), dict) else {}).items() if _ENV.match(str(k)) and isinstance(v, (str, int, float))},
            "target": build.get("target") if isinstance(build.get("target"), str) and _NAME.match(build["target"]) else "",
            "workspace": workspace, "mount": put(raw["workspaceMount"]) if isinstance(raw.get("workspaceMount"), str) and raw["workspaceMount"].strip() else "",
            "user": user, "env": env, "ports": ports, "mounts": mounts, "run_args": [put(a) for a in _strings(raw.get("runArgs"))],
            "init": raw.get("init") is True, "privileged": raw.get("privileged") is True,
            "cap_add": [c for c in _strings(raw.get("capAdd")) if re.fullmatch(r"[A-Za-z_]+", c)], "security_opt": _strings(raw.get("securityOpt")),
            "override": raw.get("overrideCommand") is not False,
            "created": _commands(raw.get("onCreateCommand")) + _commands(raw.get("updateContentCommand")) + _commands(raw.get("postCreateCommand")),
            "started": _commands(raw.get("postStartCommand")), "features": features}


def name_for(root) -> str:
    """The container's name: the folder's, and a few characters of its full path so two folders of one name differ."""
    root = str(Path(root))
    slug = re.sub(r"[^a-z0-9]+", "-", Path(root).name.lower()).strip("-")[:30] or "project"
    return f"huginn-{slug}-{hashlib.sha256(root.encode()).hexdigest()[:8]}"


def image_for(cfg: dict) -> str:
    return cfg["image"] or name_for(cfg["root"]) + "-image"


def asks(cfg: dict) -> list:
    """What starting this container does on this computer, in plain words: shown before the first start, since a
    project's devcontainer.json is somebody else's instructions."""
    out = [f"Build an image from {Path(cfg['dockerfile']).name}" if cfg["dockerfile"] else f"Use the image {cfg['image']}",
           f"Share this folder with it, at {cfg['workspace']}"]
    if cfg["mount"]:
        out.append(f"Its own workspace mount: {cfg['mount']}")
    out += [f"Share: {m}" for m in cfg["mounts"]]
    if cfg["ports"]:
        out.append("Open on this computer only: port" + ("s " if len(cfg["ports"]) > 1 else " ") + ", ".join(str(p) for p in cfg["ports"]))
    if cfg["privileged"]:
        out.append("Run PRIVILEGED: the container can do anything this computer's administrator can")
    if cfg["cap_add"] or cfg["security_opt"]:
        out.append("Extra powers: " + ", ".join(cfg["cap_add"] + cfg["security_opt"]))
    if cfg["run_args"]:
        out.append("Extra options for the engine: " + " ".join(cfg["run_args"]))
    out += [f"Run inside it, once: {c}" for c in cfg["created"]] + [f"Run inside it, at each start: {c}" for c in cfg["started"]]
    if cfg["features"]:
        out.append("NOT done by Code: Dev Container Features (" + ", ".join(f.rsplit("/", 1)[-1] for f in cfg["features"][:6]) + ")")
    return out


def build_command(eng: str, cfg: dict) -> list:
    """The image, built from the project's Dockerfile ([] when it names an image instead)."""
    if not cfg["dockerfile"]:
        return []
    cmd = [eng, "build", "-t", image_for(cfg), "-f", cfg["dockerfile"]]
    for k, v in cfg["args"].items():
        cmd += ["--build-arg", f"{k}={v}"]
    if cfg["target"]:
        cmd += ["--target", cfg["target"]]
    return cmd + [cfg["context"]]


def run_command(eng: str, cfg: dict, rootless: bool = None) -> list:
    """The container, started in the background and kept alive, with the project's folder shared into it."""
    if rootless is None:
        import os
        rootless = os.geteuid() != 0
    cmd = [eng, "run", "-d", "--name", name_for(cfg["root"]), "--label", "huginn.code.folder=" + cfg["root"], "--label", "devcontainer.local_folder=" + cfg["root"]]
    cmd += ["--mount", cfg["mount"]] if cfg["mount"] else ["-v", f"{cfg['root']}:{cfg['workspace']}"]
    cmd += ["-w", cfg["workspace"]]
    for m in cfg["mounts"]:
        cmd += ["--mount", m]
    for p in cfg["ports"]:
        cmd += ["-p", f"127.0.0.1:{p}:{p}"]
    for k, v in cfg["env"].items():
        cmd += ["-e", f"{k}={v}"]
    if cfg["init"]:
        cmd.append("--init")
    if cfg["privileged"]:
        cmd.append("--privileged")
    for c in cfg["cap_add"]:
        cmd += ["--cap-add", c]
    for s in cfg["security_opt"]:
        cmd += ["--security-opt", s]
    if eng == "podman" and rootless:
        cmd.append("--userns=keep-id")                               # your own files stay your own, seen from inside (Podman run by root has no such mode)
    cmd += cfg["run_args"]
    if cfg["override"]:
        cmd += ["--entrypoint", "/bin/sh", image_for(cfg), "-c", "echo Container started; trap 'exit 0' TERM; while sleep 1 & wait $!; do :; done"]
    else:
        cmd.append(image_for(cfg))
    return cmd


def where(eng: str, cfg: dict) -> dict:
    """What Code remembers about a started container (what the rest of this file calls `box`)."""
    return {"engine": eng, "name": name_for(cfg["root"]), "workspace": cfg["workspace"], "user": cfg["user"], "root": cfg["root"],
            "spec": cfg["title"], "label": cfg["title"], "env": dict(cfg.get("env") or {})}


def exec_argv(box: dict, argv: list, cwd: str = "", tty: bool = False, stdin: bool = True) -> list:
    cmd = [box["engine"], "exec"] + (["-it"] if tty else ["-i"] if stdin else [])
    if box.get("user"):
        cmd += ["-u", box["user"]]
    return cmd + ["-w", cwd or box["workspace"], box["name"]] + list(argv)


def status_file(root) -> Path:
    """Where the line typed into the terminal leaves how it ended (0: the container is up), for Code to read."""
    import os
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn" / "containers" / (name_for(root) + ".status")


def start_lines(eng: str, cfg: dict, exists: bool, status=None) -> list:
    """The lines typed into Code's terminal to bring the container up: build, run (or start again), and the
    project's own commands inside it. With `status` (a file), how it all ended is written there, so Code knows a
    failed build from one still going."""
    q = lambda argv: " ".join(shlex.quote(a) for a in argv)          # noqa: E731
    box, lines = where(eng, cfg), []
    if exists:
        lines.append(q([eng, "start", box["name"]]))
    else:
        if cfg["dockerfile"]:
            lines.append(q(build_command(eng, cfg)))
        lines.append(q(run_command(eng, cfg)))
        lines += [q(exec_argv(box, ["sh", "-c", c], stdin=False)) for c in cfg["created"]]
    lines += [q(exec_argv(box, ["sh", "-c", c], stdin=False)) for c in cfg["started"]]
    line = " && ".join(lines) + " && echo 'The container is ready.'"
    if status is not None:
        line += f"; echo $? > {shlex.quote(str(status))}"
    return [line]


def state(box_or_eng, name: str = "") -> str:
    """"running", "stopped", or "" when there is no such container (or no engine answering)."""
    eng, name = (box_or_eng["engine"], box_or_eng["name"]) if isinstance(box_or_eng, dict) else (box_or_eng, name)
    try:
        done = subprocess.run([eng, "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    return "running" if done.stdout.strip() == "true" else "stopped"


def stop_command(box: dict, remove: bool = False) -> list:
    return [box["engine"], "rm", "-f", box["name"]] if remove else [box["engine"], "stop", "-t", "3", box["name"]]


# ---- the same doors huginn_remote has, so Run, Build and the debugger treat a container like another computer
def to_remote(box: dict, mount, local: str) -> str:
    """A path in the project, as the container sees it."""
    mount, base = str(mount).rstrip("/"), box["workspace"].rstrip("/") or "/"
    if local == mount:
        return base
    return (base.rstrip("/") + "/" + local[len(mount) + 1:]) if local.startswith(mount + "/") else local


def to_local(box: dict, mount, there: str) -> str:
    """A path inside the container, as it is here ("" when it is outside the shared folder)."""
    mount, base = str(mount).rstrip("/"), box["workspace"].rstrip("/") or "/"
    if there == base:
        return mount
    prefix = "/" if base == "/" else base + "/"
    return f"{mount}/{there[len(prefix):]}" if there.startswith(prefix) else ""


def wrap(box: dict, command: str, cwd: str = "", tty: bool = False, mount=None) -> str:
    """A command as it is run inside the container, with this computer's paths turned into the container's."""
    if mount is not None:
        m, base = str(mount).rstrip("/"), box["workspace"].rstrip("/") or "/"
        command = re.sub(re.escape(m) + r"(?![A-Za-z0-9._-])", lambda _: base, command.replace(m + "/", base.rstrip("/") + "/"))
    return " ".join(shlex.quote(a) for a in exec_argv(box, ["sh", "-c", command], cwd, tty, stdin=tty))


def adapter_argv(box: dict, argv: list, cwd: str = "") -> list:
    """A debug adapter run inside the container, its conversation carried by the engine's exec."""
    return exec_argv(box, argv, cwd)


def probe(box: dict, command: str, timeout: int = 15) -> tuple:
    try:
        done = subprocess.run(exec_argv(box, ["sh", "-c", command], stdin=False), capture_output=True, text=True, timeout=timeout)
        return done.returncode, (done.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return 255, ""


def shell_command(box: dict) -> str:
    return " ".join(shlex.quote(a) for a in exec_argv(box, ["sh", "-c", "command -v bash >/dev/null && exec bash -l || exec sh"], tty=True))


def describe(box: dict) -> str:
    return json.dumps({k: box[k] for k in ("engine", "name", "workspace")})
