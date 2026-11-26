"""Code's build tasks: what a project can build, run, test and package, found from the files it has; and the
compiler's output turned into problems you can click.

A project is read for what it is (several kinds can live in one folder):
    Godot      project.godot              run the game, open the editor, import, export each preset
    Unreal     *.uproject                 build the editor and the game, code suggestions for clangd, open, play, package
    CMake      CMakeLists.txt             configure (Ninja when it's there), build, release build, test, clean
    Cargo      Cargo.toml                 build, release, run, test, check, clippy, clean
    Make       Makefile                   make, and each target it names
    Go         go.mod                     build, test, vet
    npm        package.json               each script
    .NET       *.sln / *.csproj           build, run, test
    its own    .huginn-tasks.json         [{"name": "...", "command": "...", "group": "build"}]

The first half of this file is plain functions (tested without a window); Builder at the end runs a task and keeps
its output.
"""
import configparser
import json
import os
import re
import shlex
import shutil
import signal
import time
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, QObject, QProcess, QProcessEnvironment, Qt, QTimer, Property, Signal, Slot

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn" / "code-build.json"
GROUPS = ("build", "run", "test", "package", "clean", "setup")
OUTPUT_LIMIT = 5000           # lines kept of a task's output
PROBLEM_LIMIT = 500
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\r")

# What a game project needs that the system may not have yet. "apt" comes from Ubuntu's archive (the system asks for
# the password); "flatpak" from Flathub, into the user's own apps (no password).
TOOL_PACKS = {
    "Git LFS": {"apt": ["git-lfs"], "have": ["git-lfs"],
                "about": "Large files (textures, models, sound) kept out of Git's history. Most game projects need it."},
    "C++ build tools": {"apt": ["build-essential", "clang", "lld", "clangd", "cmake", "ninja-build", "gdb"], "have": ["clang", "cmake", "ninja", "clangd"],
                        "about": "Compilers, CMake and Ninja, the debugger, and clangd for suggestions and problems as you type."},
    "Godot 4": {"flatpak": ["org.godotengine.Godot"], "have": [],
                "about": "The Godot editor, from Flathub. Code runs your game with it and takes GDScript suggestions from it while it's open."},
    "Godot 4 (.NET)": {"flatpak": ["org.godotengine.GodotSharp"], "apt": ["dotnet-sdk-10.0"], "have": [],
                       "about": "Godot with C# support, and the .NET SDK it builds with."},
    "Shader tools": {"apt": ["glslang-tools", "spirv-tools"], "have": ["glslangValidator"],
                     "about": "Checks GLSL shaders (glslangValidator) and works with SPIR-V."},
    "Unreal Engine prerequisites": {"apt": ["build-essential", "clangd", "git-lfs", "shared-mime-info", "xdg-user-dirs", "libvulkan1", "vulkan-tools"], "have": ["clangd", "git-lfs", "vulkaninfo"],
                                    "about": "What Unreal's own Setup.sh expects of the system, and clangd for its C++. The engine itself comes from Epic (a download or its GitHub source)."},
}
FLATPAK_DIRS = (Path.home() / ".local/share/flatpak/app", Path("/var/lib/flatpak/app"))


# ------------------------------------------------------------------------------------------------ finding the engines
def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    except OSError:
        pass


def install_pack(pack: dict, installed=None) -> str:
    """Put in what a pack names: Ubuntu's packages (the system asks for the password) and Flathub's apps (into your
    own apps, no password). Returns "" when it is all there, else why not. Meant for a worker thread: it waits."""
    import subprocess
    why = ""
    missing = [p for p in pack.get("apt", []) if not (installed(p) if installed else False)]
    if missing:
        import huginn_packages                                       # fetches Ubuntu's package lists first when there are none
        why = huginn_packages.install(missing)
    for app in pack.get("flatpak", []) if not why else []:
        if flatpak_has(app):
            continue
        if not shutil.which("flatpak"):
            return "Flatpak isn't installed, so this can't be fetched from Flathub."
        try:
            subprocess.run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo"], capture_output=True, timeout=120)
            done = subprocess.run(["flatpak", "install", "--user", "--noninteractive", "-y", "flathub", app], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
            if done.returncode != 0:
                tail = (done.stderr or done.stdout).strip().splitlines()
                why = f"{app} wasn't fetched from Flathub" + (f" ({tail[-1][:140]})" if tail else "") + "."
        except (OSError, subprocess.TimeoutExpired) as e:
            why = f"{app} wasn't fetched from Flathub ({e})."
    return why


def flatpak_has(app_id: str) -> bool:
    return any((d / app_id).is_dir() for d in FLATPAK_DIRS)


def pack_ready(name: str) -> bool:
    pack = TOOL_PACKS.get(name) or {}
    return all(shutil.which(p) for p in pack.get("have", [])) and all(flatpak_has(f) for f in pack.get("flatpak", []))


def godot_major(root: Path) -> int:
    """4 or 3: which Godot a project was made with (project.godot's config_version: 5 is Godot 4, 4 is Godot 3)."""
    try:
        m = re.search(r"^config_version\s*=\s*(\d+)", (root / "project.godot").read_text(encoding="utf-8", errors="replace"), re.M)
    except OSError:
        return 4
    return 3 if m and int(m.group(1)) <= 4 else 4


def godot_uses_dotnet(root: Path) -> bool:
    """A Godot project written in C#: it has a .csproj or .sln, or project.godot lists the C# feature."""
    try:
        text = (root / "project.godot").read_text(encoding="utf-8", errors="replace")
        return any(root.glob("*.csproj")) or any(root.glob("*.sln")) or "[dotnet]" in text or '"C#"' in text
    except OSError:
        return False


def godot_command(root: Path = None, cfg: dict = None) -> str:
    """The command that starts Godot for this project ("" when no Godot is installed): one you chose, one on the PATH,
    or Flathub's. A Godot 3 project gets Godot 3, a C# project the .NET editor."""
    cfg = load_config() if cfg is None else cfg
    chosen = str(cfg.get("godot") or os.environ.get("HUGINN_GODOT") or "")
    if chosen and (shutil.which(shlex.split(chosen)[0]) or Path(shlex.split(chosen)[0]).is_file()):
        return chosen
    major = godot_major(root) if root else 4
    dotnet = bool(root) and godot_uses_dotnet(root)
    if major == 3:
        return next((n for n in ("godot3", "godot3-mono") if shutil.which(n)), "")
    names = (("godot-mono", "godot4-mono") if dotnet else ()) + ("godot4", "godot")
    for n in names:
        if shutil.which(n):
            return n
    for app in (("org.godotengine.GodotSharp",) if dotnet else ()) + ("org.godotengine.Godot", "org.godotengine.GodotSharp"):
        if flatpak_has(app):
            return f"flatpak run {app}"
    return ""


def uproject_of(root: Path):
    return next(iter(sorted(root.glob("*.uproject"))), None)


def unreal_valid(folder) -> bool:
    return bool(folder) and (Path(folder) / "Engine/Build/BatchFiles/Linux/Build.sh").is_file()


def unreal_root(uproject: Path = None, cfg: dict = None) -> str:
    """Where Unreal Engine is ("" when it isn't found): the folder you chose, UE_ROOT, the one this project names in
    Epic's own list (~/.config/Epic/UnrealEngine/Install.ini), or one of the usual places."""
    cfg = load_config() if cfg is None else cfg
    tried = [cfg.get("unreal"), os.environ.get("UE_ROOT"), os.environ.get("UNREAL_ENGINE_ROOT")]
    assoc = ""
    if uproject:
        try:
            assoc = str(json.loads(uproject.read_text(encoding="utf-8", errors="replace")).get("EngineAssociation") or "")
        except (OSError, ValueError):
            pass
        tried += [p for p in uproject.parents if unreal_valid(p)][:1]            # a project inside the engine's own tree
    ini = Path.home() / ".config/Epic/UnrealEngine/Install.ini"
    if ini.is_file():
        known = configparser.ConfigParser(strict=False, interpolation=None)
        known.optionxform = str
        try:
            known.read(ini, encoding="utf-8")
            rows = dict(known["Installations"]) if known.has_section("Installations") else {}
        except (configparser.Error, OSError):
            rows = {}
        tried += [rows.get(assoc), rows.get(assoc.strip("{}")), rows.get("{" + assoc.strip("{}") + "}")] + list(rows.values())
    home = Path.home()
    tried += [home / "UnrealEngine", home / "Unreal/UnrealEngine", Path("/opt/unreal-engine"), Path("/opt/UnrealEngine")]
    for base in (home, home / "Epic", home / "Unreal", Path("/opt")):
        try:
            tried += sorted((p for p in base.glob("UE_*") if p.is_dir()), reverse=True) + sorted((p for p in base.glob("Linux_Unreal_Engine_*") if p.is_dir()), reverse=True)
        except OSError:
            pass
    return next((str(Path(p)) for p in tried if unreal_valid(p)), "")


# ------------------------------------------------------------------------------------------------------------- tasks
def _task(tid: str, name: str, command: str, group: str = "build", detail: str = "", cwd: str = "") -> dict:
    return {"id": tid, "name": name, "command": command, "group": group, "detail": detail, "cwd": cwd}


def make_targets(root: Path, cap: int = 12) -> list:
    """The targets a Makefile names (the ones meant to be asked for: no patterns, no files with an ending)."""
    mk = next((root / n for n in ("GNUmakefile", "makefile", "Makefile") if (root / n).is_file()), None)
    if not mk:
        return []
    try:
        text = mk.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    phony = set(" ".join(re.findall(r"^\.PHONY\s*:\s*(.+)$", text, re.M)).split())
    found = []
    for m in re.finditer(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:(?!=)", text, re.M):
        name = m.group(1)
        if name not in found and (name in phony or "." not in name):
            found.append(name)
    return found[:cap]


def export_presets(root: Path) -> list:
    """Godot's export presets: [(name, platform, path)]."""
    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        cfg.read(root / "export_presets.cfg", encoding="utf-8")
    except (configparser.Error, OSError):
        return []
    out = []
    for sec in cfg.sections():
        if re.fullmatch(r"preset\.\d+", sec):
            get = lambda k: cfg.get(sec, k, fallback="").strip().strip('"')          # noqa: E731
            if get("name"):
                out.append((get("name"), get("platform"), get("export_path")))
    return out


def tasks(root: Path, cfg: dict = None, known: dict = None) -> list:
    """Every task this project offers, the most useful first. The first "build" task is what Build (Ctrl+Shift+B) runs
    until you choose another."""
    if not root or not Path(root).is_dir():
        return []
    root, cfg, out = Path(root), (load_config() if cfg is None else cfg), []
    q = shlex.quote

    own = root / ".huginn-tasks.json"
    if own.is_file():
        try:
            rows = json.loads(own.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows = []
        for i, row in enumerate(rows if isinstance(rows, list) else []):
            if isinstance(row, dict) and row.get("name") and row.get("command"):
                group = row.get("group") if row.get("group") in GROUPS else "build"
                out.append(_task(f"own:{i}", str(row["name"]), str(row["command"]), group, "from .huginn-tasks.json"))

    import huginn_vscode                                             # the project's .vscode/tasks.json, as VS Code would list them
    out += huginn_vscode.tasks(root, known)

    if (root / "project.godot").is_file():
        godot = godot_command(root, cfg)
        if godot:
            old = godot_major(root) == 3                               # (Godot 3 has other words for "no window" and "export")
            quiet = (shutil.which("godot3-server") or f"{godot} --no-window") if old else f"{godot} --headless"
            out += [_task("godot:run", "Run the Game", f"{godot} --path .", "run", "Godot"),
                    _task("godot:editor", "Open in Godot", f"{godot} --editor --path .", "run", "the editor; GDScript suggestions come from it while it's open")]
            if not old:
                out.append(_task("godot:import", "Import Assets", f"{godot} --headless --path . --import", "build", "what the editor does when it opens the project"))
            out.append(_task("godot:check", "Check Scripts", f"{quiet} --path . --quit", "build", "loads the project and its main scene, and reports script errors"))
            if godot_uses_dotnet(root) and shutil.which("dotnet"):
                out.append(_task("godot:dotnet", "Build C#", "dotnet build", "build", ".NET"))
            for name, platform, path in export_presets(root):
                dest = path or f"build/{re.sub(r'[^A-Za-z0-9_.-]+', '-', name)}"
                out.append(_task(f"godot:export:{name}", f"Export: {name}", f"mkdir -p {q(os.path.dirname(dest) or '.')} && {quiet} --path . {'--export' if old else '--export-release'} {q(name)} {q(dest)}",
                                 "package", platform))
        else:
            out.append(_task("setup:Godot 4", "Godot isn't installed: add it", "", "setup", "from Flathub"))

    uproj = uproject_of(root)
    if uproj:
        ue, name = unreal_root(uproj, cfg), uproj.stem
        try:
            has_code = bool(json.loads(uproj.read_text(encoding="utf-8", errors="replace")).get("Modules")) or (root / "Source").is_dir()
        except (OSError, ValueError):
            has_code = (root / "Source").is_dir()
        if ue:
            build, up = q(f"{ue}/Engine/Build/BatchFiles/Linux/Build.sh"), q(str(uproj))
            editor = q(f"{ue}/Engine/Binaries/Linux/UnrealEditor")
            if has_code:
                out += [_task("ue:editor", "Build Editor", f"{build} {name}Editor Linux Development -project={up} -waitmutex", "build", "Unreal, Development"),
                        _task("ue:game", "Build Game", f"{build} {name} Linux Development -project={up} -waitmutex", "build", "Unreal, Development"),
                        _task("ue:shipping", "Build Game (Shipping)", f"{build} {name} Linux Shipping -project={up} -waitmutex", "build", "Unreal, Shipping"),
                        _task("ue:clangd", "Refresh Code Suggestions", f"{build} -mode=GenerateClangDatabase -project={up} -game -engine {name}Editor Linux Development && cp {q(ue + '/compile_commands.json')} .",
                              "build", "writes compile_commands.json for clangd")]
            out += [_task("ue:open", "Open in Unreal Editor", f"{editor} {up}", "run", "Unreal"),
                    _task("ue:play", "Play", f"{editor} {up} -game -windowed -log", "run", "the game, without the editor")]
            if has_code:
                out += [_task("ue:files", "Generate Project Files", f"{q(ue + '/GenerateProjectFiles.sh')} -project={up} -game", "build", "after adding or removing source files"),
                        _task("ue:clean", "Clean", f"{build} {name}Editor Linux Development -project={up} -clean", "clean", "Unreal")]
            out.append(_task("ue:package", "Package for Linux", f"{q(ue + '/Engine/Build/BatchFiles/RunUAT.sh')} BuildCookRun -project={up} -platform=Linux -clientconfig=Development "
                                                               f"-build -cook -stage -pak -archive -archivedirectory={q(str(root / 'Packaged'))}", "package", "build, cook and stage into Packaged/"))
        else:
            out.append(_task("setup:unreal", "Unreal Engine isn't found: choose its folder", "", "setup", "the folder that holds Engine/ and Setup.sh"))

    if (root / "CMakeLists.txt").is_file():
        gen = " -G Ninja" if shutil.which("ninja") else ""
        conf = f"cmake -S . -B build{gen} -DCMAKE_BUILD_TYPE=Debug -DCMAKE_EXPORT_COMPILE_COMMANDS=ON"
        out += [_task("cmake:build", "Build", f"{conf} && cmake --build build --parallel", "build", "CMake, Debug, in build/"),
                _task("cmake:release", "Build (Release)", f"cmake -S . -B build-release{gen} -DCMAKE_BUILD_TYPE=Release && cmake --build build-release --parallel", "build", "CMake, in build-release/"),
                _task("cmake:configure", "Configure", conf, "build", "CMake; also writes compile_commands.json for clangd"),
                _task("cmake:test", "Run Tests", "ctest --test-dir build --output-on-failure", "test", "CTest"),
                _task("cmake:clean", "Clean", "cmake --build build --target clean", "clean", "CMake")]

    if (root / "Cargo.toml").is_file():
        out += [_task("cargo:build", "Build", "cargo build", "build", "Cargo"), _task("cargo:release", "Build (Release)", "cargo build --release", "build", "Cargo"),
                _task("cargo:run", "Run", "cargo run", "run", "Cargo"), _task("cargo:check", "Check", "cargo check", "build", "Cargo: errors without building"),
                _task("cargo:clippy", "Clippy", "cargo clippy", "build", "Cargo: lints"), _task("cargo:test", "Run Tests", "cargo test", "test", "Cargo"),
                _task("cargo:clean", "Clean", "cargo clean", "clean", "Cargo")]

    targets = make_targets(root)
    if targets or any((root / n).is_file() for n in ("GNUmakefile", "makefile", "Makefile")):
        jobs = f" -j{os.cpu_count() or 2}"
        out.append(_task("make", "Make", "make" + jobs, "build", "Makefile"))
        for t in targets:
            group = "clean" if "clean" in t else "test" if t in ("test", "check", "tests") else "run" if t == "run" else "package" if t in ("install", "dist", "package") else "build"
            if t != "all":
                out.append(_task(f"make:{t}", f"Make {t}", f"make{jobs if group == 'build' else ''} {q(t)}", group, "Makefile"))

    if (root / "go.mod").is_file():
        out += [_task("go:build", "Build", "go build ./...", "build", "Go"), _task("go:run", "Run", "go run .", "run", "Go"),
                _task("go:test", "Run Tests", "go test ./...", "test", "Go"), _task("go:vet", "Vet", "go vet ./...", "build", "Go")]

    if (root / "package.json").is_file():
        try:
            scripts = json.loads((root / "package.json").read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, ValueError):
            scripts = {}
        for name in list(scripts if isinstance(scripts, dict) else {})[:16]:
            group = "build" if "build" in name or name in ("lint", "typecheck", "check") else "test" if "test" in name else "run"
            out.append(_task(f"npm:{name}", f"npm run {name}", f"npm run {q(name)}", group, str(scripts[name])[:80]))

    if not (root / "project.godot").is_file() and (any(root.glob("*.sln")) or any(root.glob("*.csproj"))) and shutil.which("dotnet"):
        out += [_task("dotnet:build", "Build", "dotnet build", "build", ".NET"), _task("dotnet:run", "Run", "dotnet run", "run", ".NET"), _task("dotnet:test", "Run Tests", "dotnet test", "test", ".NET")]

    if uses_lfs(root) and not shutil.which("git-lfs"):
        out.append(_task("setup:Git LFS", "This project uses Git LFS: add it", "", "setup", "its large files are placeholders until then"))
    elif uses_lfs(root):
        out.append(_task("lfs:pull", "Fetch Large Files (Git LFS)", "git lfs install --local && git lfs pull", "setup", "Git LFS"))
    return out


def uses_lfs(root: Path) -> bool:
    try:
        return "filter=lfs" in (root / ".gitattributes").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def default_task(found: list, chosen: str = "") -> dict:
    """What Build runs: the task you chose for this project, else the first build task."""
    return next((t for t in found if t["id"] == chosen and t["command"]), None) or next((t for t in found if t.get("default") and t["command"]), None) \
        or next((t for t in found if t["group"] == "build" and t["command"]), None) \
        or next((t for t in found if t["command"]), None)


# ------------------------------------------------------------------------------------------- reading compiler output
SEVERITY = {"fatal error": 1, "error": 1, "warning": 2, "note": 3, "info": 3, "help": 3}
_GNU = re.compile(r"^\s*(?P<file>(?:[A-Za-z]:)?[^\s:()][^:()\n]*?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?:(?P<sev>fatal error|error|warning|note|info)\b[^:]*:)?\s*(?P<msg>.*)$")
_MS = re.compile(r"^\s*(?P<file>(?:[A-Za-z]:)?[^\s()][^()\n]*?)\((?P<line>\d+)(?:,(?P<col>\d+))?(?:,\d+,\d+)?\)\s*:\s*(?P<sev>fatal error|error|warning|note|info)\s*(?P<code>[A-Za-z]+\d+)?\s*:?\s*(?P<msg>.*)$")
_RUST_HEAD = re.compile(r"^(?P<sev>error|warning)(?:\[(?P<code>[A-Z]\d+)\])?:\s*(?P<msg>.+)$")
_RUST_AT = re.compile(r"^\s*-->\s*(?P<file>.+?):(?P<line>\d+):(?P<col>\d+)\s*$")
_CMAKE = re.compile(r"^CMake (?P<sev>Error|Warning)(?: \(dev\))? at (?P<file>.+?):(?P<line>\d+)\s*(?:\((?P<what>[^)]*)\))?:?\s*$")
_GODOT_HEAD = re.compile(r"^\s*(?:SCRIPT ERROR|ERROR|USER ERROR|USER SCRIPT ERROR|WARNING|USER WARNING):\s*(?P<msg>.+)$")
_GODOT_AT = re.compile(r"^\s*[Aa]t:\s*(?:.*?\()?(?P<file>res://[^:()]+):(?P<line>\d+)\)?")
_GODOT_LINE = re.compile(r"^\s*(?P<file>res://[^:\s]+):(?P<line>\d+)\s*-\s*(?P<msg>.+)$")
_PY = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)')
_MAKE_DIR = re.compile(r"^make(?:\[\d+\])?: (Entering|Leaving) directory [`'](.+)'$")


def locate(name: str, root: Path, dirs: list = (), there=None) -> str:
    """The real path of a file a compiler named ("" when there is no such file): absolute, relative to the project,
    to a directory make said it entered, or to one of the usual build folders. res:// is Godot's name for the project."""
    name = name.strip().strip('"')
    if name.startswith("res://"):
        name = name[6:]
    if there and name.startswith("/"):                               # a path on the other computer: the same file under the mount
        name = there[0].to_local(there[1], there[2], name) or name
    if not name or len(name) > 1024 or "\0" in name:
        return ""
    p = Path(name)
    entered = [Path(there[0].to_local(there[1], there[2], d) or d) if there else Path(d) for d in reversed(list(dirs))]      # (make's directories are the other computer's)
    tries = [p] if p.is_absolute() else [d / p for d in entered] + [root / p] + [root / b / p for b in ("build", "build-release", "Source", "src")]
    for t in tries:
        try:
            if t.is_file():
                return os.path.normpath(str(t))
        except OSError:
            pass
    return ""


def parse_line(line: str, root: Path, state: dict):
    """One line of a task's output. Returns a problem {path, line, col, severity, message} (line and col count from 0)
    when the line names a place in a real file, else None. `state` carries what earlier lines said (a Rust or Godot
    message comes a line before its place; make says which directory it is in)."""
    text = ANSI.sub("", line).rstrip()
    dirs = state.setdefault("dirs", [])
    m = _MAKE_DIR.match(text)
    if m:
        if m.group(1) == "Entering":
            dirs.append(m.group(2))
        elif dirs:
            dirs.pop()
        return None

    def problem(file, ln, col, sev, msg):
        path = locate(file, root, dirs, state.get("there"))
        if not path:
            return None
        return {"path": path, "line": max(0, int(ln) - 1), "col": max(0, int(col or 1) - 1), "severity": sev, "message": (msg or "").strip()[:600] or "here"}

    m = _RUST_AT.match(text)
    if m and state.get("head"):
        sev, msg = state.pop("head")
        return problem(m.group("file"), m.group("line"), m.group("col"), sev, msg)
    m = _GODOT_AT.match(text)
    if m and state.get("godot"):
        sev, msg = state.pop("godot")
        return problem(m.group("file"), m.group("line"), 1, sev, msg)
    if state.get("cmake") and text.strip():
        file, ln, sev, what = state.pop("cmake")
        return problem(file, ln, 1, sev, text.strip() + (f" ({what})" if what else ""))

    m = _RUST_HEAD.match(text)
    if m and not text.startswith(("error: could not compile", "error: aborting", "warning: unused manifest")):
        state["head"] = (SEVERITY[m.group("sev")], m.group("msg") + (f" [{m.group('code')}]" if m.group("code") else ""))
        return None
    m = _CMAKE.match(text)
    if m:
        state["cmake"] = (m.group("file"), m.group("line"), 1 if m.group("sev") == "Error" else 2, m.group("what") or "")
        return None
    m = _GODOT_LINE.match(text)
    if m:
        return problem(m.group("file"), m.group("line"), 1, 2 if "warning" in m.group("msg").lower()[:12] else 1, m.group("msg"))
    m = _GODOT_HEAD.match(text)
    if m:
        state["godot"] = (2 if "WARNING" in text.split(":")[0] else 1, m.group("msg"))
        return None
    m = _MS.match(text)
    if m:
        return problem(m.group("file"), m.group("line"), m.group("col"), SEVERITY.get(m.group("sev"), 1), m.group("msg") + (f" [{m.group('code')}]" if m.group("code") else ""))
    m = _GNU.match(text)
    if m and (m.group("sev") or m.group("msg")):
        return problem(m.group("file"), m.group("line"), m.group("col"), SEVERITY.get(m.group("sev") or "", 1), m.group("msg"))
    m = _PY.match(text)
    if m:
        return problem(m.group("file"), m.group("line"), 1, 1, "in the traceback")
    return None


def kind_of(text: str, found) -> str:
    """How a line of output is shown: error, warning, note or plain."""
    if found:
        return {1: "error", 2: "warning"}.get(found["severity"], "note")
    low = ANSI.sub("", text).lstrip().lower()
    if low.startswith(("error", "fatal error", "script error", "user error", "cmake error", "ld: error", "collect2: error", "ninja: build stopped", "failed")) or " error: " in low[:160]:
        return "error"
    if low.startswith(("warning", "user warning", "cmake warning")) or " warning: " in low[:160]:
        return "warning"
    return "plain"


def summary(code: int, crashed: bool, problems: list, seconds: float, stopped: bool = False) -> str:
    errors = sum(1 for p in problems if p["severity"] == 1)
    warnings = sum(1 for p in problems if p["severity"] == 2)
    took = f"{seconds:.1f} s" if seconds < 60 else f"{int(seconds // 60)} min {int(seconds % 60)} s"
    counts = ", ".join(f"{n} {word}{'' if n == 1 else 's'}" for n, word in ((errors, "error"), (warnings, "warning")) if n)
    if stopped:
        return f"Stopped after {took}"
    if crashed:
        return f"Couldn't be run ({took})"
    if code == 0:
        return f"Done in {took}" + (f" · {counts}" if counts else "")
    return f"Failed after {took}" + (f" · {counts}" if counts else f" · exit code {code}")


# ---------------------------------------------------------------------------------------------------- running a task
class Lines(QAbstractListModel):
    """A task's output: lines are added at the end (the view keeps its place) and the oldest dropped past the limit."""
    ROLES = {Qt.UserRole + 1: b"text", Qt.UserRole + 2: b"kind", Qt.UserRole + 3: b"path", Qt.UserRole + 4: b"line", Qt.UserRole + 5: b"col"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def roleNames(self) -> dict:
        return {k: QByteArray(v) for k, v in self.ROLES.items()}

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        return self.rows[index.row()].get(self.ROLES.get(role, b"text").decode())

    def add(self, rows: list) -> None:
        if not rows:
            return
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows) + len(rows) - 1)
        self.rows += rows
        self.endInsertRows()
        over = len(self.rows) - OUTPUT_LIMIT
        if over > 0:
            self.beginRemoveRows(QModelIndex(), 0, over - 1)
            del self.rows[:over]
            self.endRemoveRows()

    def clear(self) -> None:
        self.beginResetModel()
        self.rows = []
        self.endResetModel()


class Builder(QObject):
    changed = Signal()
    said = Signal(str, bool)
    goTo = Signal(str, int, int)              # path, line, column: open it there
    finished = Signal(str, int)               # the task's id and its exit code
    wantsTools = Signal(str)                  # a setup task was chosen: the pack's name, or "unreal" to choose the folder

    def __init__(self, parent=None, save_all=None, env_path: list = (), known=None, remote=None):
        super().__init__(parent)
        self._root, self._tasks, self._cfg = None, [], load_config()
        self._proc, self._task, self._status, self._started = None, None, "", 0.0
        self._problems, self._seen, self._state, self._tail, self._stopped = [], set(), {}, "", False
        self._save_all, self._env_path, self._at = save_all, list(env_path), -1
        self._known = known                      # () -> what ${file} and the rest stand for now (for .vscode/tasks.json)
        self._remote = remote                    # () -> (remote, mount) when the project is on another computer (huginn_remote)
        self._lines = Lines(self)
        self._pending = []
        self._flush = QTimer(self, interval=60, singleShot=True)
        self._flush.timeout.connect(self._show)

    # ---- the project
    def set_root(self, root) -> None:
        self._root = Path(root) if root else None
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        self._cfg = load_config()
        self._tasks = tasks(self._root, self._cfg, self._known() if self._known else None) if self._root else []
        self.changed.emit()

    def _chosen(self) -> str:
        return str((self._cfg.get("default") or {}).get(str(self._root), "")) if self._root else ""

    def _get_tasks(self) -> list:
        first = default_task(self._tasks, self._chosen())
        rows = [dict(t, default=bool(first) and t["id"] == first["id"]) for t in self._tasks]
        return sorted(rows, key=lambda t: GROUPS.index(t["group"]))          # (each group together, in the tasks' own order)
    tasks = Property("QVariantList", _get_tasks, notify=changed)
    lines = Property(QObject, lambda self: self._lines, constant=True)
    problems = Property("QVariantList", lambda self: self._problems, notify=changed)
    errors = Property(int, lambda self: sum(1 for p in self._problems if p["severity"] == 1), notify=changed)
    warnings = Property(int, lambda self: sum(1 for p in self._problems if p["severity"] == 2), notify=changed)
    running = Property(bool, lambda self: self._proc is not None, notify=changed)
    status = Property(str, lambda self: self._status, notify=changed)
    taskName = Property(str, lambda self: self._task["name"] if self._task else "", notify=changed)
    unrealRoot = Property(str, lambda self: unreal_root(uproject_of(self._root), self._cfg) if self._root and uproject_of(self._root) else "", notify=changed)
    godot = Property(str, lambda self: godot_command(self._root, self._cfg) if self._root else "", notify=changed)

    def _get_packs(self) -> list:
        return [{"name": name, "about": pack["about"], "ready": pack_ready(name)} for name, pack in TOOL_PACKS.items()]
    packs = Property("QVariantList", _get_packs, notify=changed)

    @Slot(str)
    def makeDefault(self, tid: str) -> None:
        """Build (Ctrl+Shift+B) runs this task in this project from now on."""
        if self._root and any(t["id"] == tid and t["command"] for t in self._tasks):
            self._cfg.setdefault("default", {})[str(self._root)] = tid
            save_config(self._cfg)
            self.changed.emit()

    @Slot(str, result=str)
    def setUnreal(self, folder: str) -> str:
        """Where Unreal Engine is. Returns "" when the folder is one, else why not."""
        folder = folder.replace("file://", "").strip()
        if not unreal_valid(folder):
            return "That folder isn't an Unreal Engine: it should hold Engine/ and Setup.sh."
        self._cfg["unreal"] = str(Path(folder))
        save_config(self._cfg)
        self.refresh()
        return ""

    # ---- running
    @Slot()
    def runDefault(self) -> None:
        first = default_task(self._tasks, self._chosen())
        if first:
            self.run(first["id"])
        else:
            self.said.emit("This project has nothing to build yet. A Makefile, CMakeLists.txt, Cargo.toml, project.godot or .uproject is what Code looks for." if self._root
                           else "Open a project folder first.", True)

    @Slot()
    def again(self) -> None:
        if self._task:
            self.run(self._task["id"])
        else:
            self.runDefault()

    @Slot(str)
    def run(self, tid: str) -> None:
        if self._root and self._proc is None and tid.startswith("vscode:"):
            self.refresh()                                               # (${file} means the file in front now)
        task = next((t for t in self._tasks if t["id"] == tid), None)
        if not task or not self._root:
            return
        if not task["command"] and task["group"] != "setup":
            self.said.emit(f"“{task['name']}” can't be run here: {task['detail']}.", True)
            return
        if task["group"] == "setup" and not task["command"]:
            self.wantsTools.emit(tid.split(":", 1)[1])
            return
        if self._proc is not None:
            self.said.emit(f"“{self._task['name']}” is still running. Stop it first.", True)
            return
        if self._save_all:
            self._save_all()
        self._task, self._problems, self._seen, self._state, self._tail, self._stopped = task, [], set(), {}, "", False
        self._pending, self._at = [], -1
        self._lines.clear()
        command, remote, mount = task["command"], None, None
        if self._remote:
            remote, mount = self._remote()
        if remote:                                                   # over ssh, in the folder there; its paths come back as ours
            import huginn_remote
            command = huginn_remote.wrap(remote, command, mount=mount)
            self._state["there"] = (huginn_remote, remote, mount)
        self._lines.add([{"text": "$ " + task["command"] + (f"     (on {remote['spec']})" if remote else ""), "kind": "command", "path": "", "line": 0, "col": 0}])
        self._status, self._started = "Running…", time.time()
        proc = QProcess(self)
        proc.setWorkingDirectory(str(self._root / task["cwd"]) if task.get("cwd") else str(self._root))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PATH", os.pathsep.join([env.value("PATH", os.defpath)] + self._env_path + [str(Path.home() / ".cargo/bin"), str(Path.home() / ".local/bin")]))
        for key, value in (("TERM", "dumb"), ("CLICOLOR", "0"), ("NO_COLOR", "1"), ("CARGO_TERM_COLOR", "never"), ("FORCE_COLOR", "0")):
            env.insert(key, value)
        proc.setProcessEnvironment(env)
        proc.readyRead.connect(self._read)
        proc.finished.connect(self._done)
        proc.errorOccurred.connect(self._failed)
        self._proc = proc
        # (its own session: Stop reaches the compiler's children too, not only the shell)
        proc.start("setsid", ["bash", "-c", command])
        self.changed.emit()

    @Slot()
    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        self._stopped = True
        pid = int(proc.processId() or 0)
        if pid > 1:
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                proc.terminate()
            QTimer.singleShot(3000, lambda: self._kill(proc, pid))

    def _kill(self, proc, pid: int) -> None:
        if self._proc is proc and pid > 1:
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                proc.kill()

    def _read(self) -> None:
        if self._proc is None:
            return
        data = self._tail + bytes(self._proc.readAll()).decode(errors="replace")
        parts = data.split("\n")
        self._tail = parts.pop()
        if len(self._tail) > 20000:                                 # a tool that never ends its line
            parts.append(self._tail)
            self._tail = ""
        self._take(parts)

    def _take(self, parts: list) -> None:
        for raw in parts:
            text = ANSI.sub("", raw).rstrip()[:2000]
            found = parse_line(text, self._root, self._state)
            row = {"text": text, "kind": kind_of(text, found), "path": found["path"] if found else "", "line": found["line"] if found else 0, "col": found["col"] if found else 0}
            if found:
                key = (found["path"], found["line"], found["col"], found["message"])
                if key not in self._seen and len(self._problems) < PROBLEM_LIMIT:
                    self._seen.add(key)
                    try:
                        rel = os.path.relpath(found["path"], self._root)
                    except ValueError:
                        rel = found["path"]
                    self._problems.append(dict(found, name=rel if not rel.startswith("..") else found["path"]))
            self._pending.append(row)
        if not self._flush.isActive():
            self._flush.start()

    def _show(self) -> None:
        rows, self._pending = self._pending, []
        self._lines.add(rows)
        self.changed.emit()

    def _failed(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:           # (no bash or setsid: anything else ends through _done)
            self._finish(-1, True)

    def _done(self, code: int, status) -> None:
        self._finish(code, status != QProcess.ExitStatus.NormalExit and not self._stopped)

    def _finish(self, code: int, crashed: bool) -> None:
        proc = self._proc
        if proc is None:
            return
        self._read()
        if self._tail:
            self._take([self._tail])
            self._tail = ""
        self._proc = None
        proc.deleteLater()
        self._flush.stop()
        self._status = summary(code, crashed, self._problems, time.time() - self._started, self._stopped)
        self._pending.append({"text": self._status, "kind": "error" if (code != 0 or crashed) and not self._stopped else "done", "path": "", "line": 0, "col": 0})
        self._show()
        self.finished.emit(self._task["id"] if self._task else "", code)

    @Slot(int)
    def open(self, row: int) -> None:
        """Go to the place a line of the output names."""
        if 0 <= row < len(self._lines.rows) and self._lines.rows[row]["path"]:
            r = self._lines.rows[row]
            self.goTo.emit(r["path"], r["line"], r["col"])

    @Slot(int)
    def openProblem(self, i: int) -> None:
        if 0 <= i < len(self._problems):
            p = self._problems[i]
            self.goTo.emit(p["path"], p["line"], p["col"])

    @Slot(int)
    def step(self, way: int) -> None:
        """F8 and Shift+F8: the next (1) or previous (-1) error, round and round."""
        errors = [p for p in self._problems if p["severity"] == 1] or self._problems
        if not errors:
            return
        self._at = (self._at + (1 if way >= 0 else -1)) % len(errors) if self._at >= 0 or way >= 0 else len(errors) - 1
        p = errors[self._at]
        self.goTo.emit(p["path"], p["line"], p["col"])

    @Slot()
    def clear(self) -> None:
        if self._proc is None:
            self._lines.clear()
            self._problems, self._seen, self._status = [], set(), ""
            self.changed.emit()
