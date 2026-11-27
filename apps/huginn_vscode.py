"""Code reads what Visual Studio Code leaves in a project, so a project made there opens here as it is:

    .vscode/tasks.json          its tasks join the Build tab (labels, arguments, working folder, environment, dependsOn,
                                the default build task)
    .vscode/launch.json         its debug configurations (Python, and C, C++ and Rust through GDB)
    .vscode/settings.json       indentation, format and trim on save, final newline, line endings, rulers, excluded
                                files, file associations: per language too ("[python]": {...})
    .vscode/*.code-snippets     the project's snippets
    a colour theme (.json)      a VS Code theme's syntax and editor colours

and, from VS Code's own folder in the home (~/.config/Code/User, VSCodium's and Code - OSS's too), the user's
snippets, settings and key bindings, when asked to bring them over.

None of VS Code's code is used: these are its file formats, read. Its extensions are programs for VS Code's own
extension host and do not run here.

Everything in this file is plain functions, tested without a window.
"""
import json
import os
import re
import shlex
from fnmatch import fnmatchcase
from pathlib import Path

USER_DIRS = ("Code", "VSCodium", "Code - OSS", "Code - Insiders", "Cursor")

# VS Code's names for languages -> Code's (the ones whose names differ; the rest match on the helper id in LANGS)
LANGUAGE_IDS = {"shellscript": "Shell", "cpp": "C++", "c": "C", "csharp": "C#", "javascriptreact": "JavaScript", "typescriptreact": "TypeScript", "jsonc": "JSON",
                "plaintext": "", "ini": "Settings", "properties": "Settings", "dockerfile": "Docker", "makefile": "Make", "gdscript": "GDScript", "gdshader": "Godot Shader",
                "gdresource": "Godot Resource", "glsl": "GLSL", "hlsl": "HLSL", "usf": "HLSL", "scss": "CSS", "less": "CSS", "objective-c": "C", "objective-cpp": "C++"}


def language_name(vs_id: str, langs: dict) -> str:
    """Code's name for one of VS Code's language ids ("" when Code has no such language)."""
    vs_id = (vs_id or "").strip().lower()
    if vs_id in LANGUAGE_IDS:
        return LANGUAGE_IDS[vs_id] if LANGUAGE_IDS[vs_id] in langs else ""
    for name, info in langs.items():
        if name.lower() == vs_id or (len(info) > 4 and info[4] == vs_id):
            return name
    return ""


# ------------------------------------------------------------------------------------------------ JSON with comments
def strip_jsonc(text: str) -> str:
    """JSON as VS Code writes it (// and /* */ comments, a comma before a closing bracket) made into plain JSON.
    Comments inside strings are left alone."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(ch)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_jsonc(path, limit: int = 4 * 1024 * 1024):
    """The file's value, or None when it isn't there, is too large or doesn't read as JSON."""
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > limit:
            return None
        return json.loads(strip_jsonc(p.read_text(encoding="utf-8-sig", errors="replace")))
    except (OSError, ValueError, RecursionError):
        return None


# ------------------------------------------------------------------------------------------------------- ${variables}
def variables(root, file: str = "", line: int = 0, selected: str = "") -> dict:
    """What VS Code's ${...} names stand for, for this project and the file in front."""
    root = Path(root)
    f = Path(file) if file and not file.startswith("untitled:") else None
    try:
        rel = os.path.relpath(f, root) if f else ""
    except ValueError:
        rel = str(f)
    return {"workspaceFolder": str(root), "workspaceRoot": str(root), "workspaceFolderBasename": root.name, "cwd": str(root), "userHome": str(Path.home()),
            "pathSeparator": os.sep, "/": os.sep, "file": str(f) if f else "", "relativeFile": rel, "relativeFileDirname": os.path.dirname(rel) or ".",
            "fileBasename": f.name if f else "", "fileBasenameNoExtension": f.stem if f else "", "fileExtname": f.suffix if f else "",
            "fileDirname": str(f.parent) if f else str(root), "fileDirnameBasename": f.parent.name if f else root.name, "fileWorkspaceFolder": str(root),
            "lineNumber": str(line + 1), "selectedText": selected, "execPath": "code", "defaultBuildTask": ""}


_VAR = re.compile(r"\$\{([^}]+)\}")


def substitute(value, known: dict, config: dict = None, missing: list = None):
    """Fill ${...} in a string (or every string in a list or dict). ${env:NAME} is the environment's, ${config:a.b} a
    setting's. What Code can't answer (${input:...}, ${command:...}) is left as it is and named in `missing`."""
    if isinstance(value, list):
        return [substitute(v, known, config, missing) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, known, config, missing) for k, v in value.items()}
    if not isinstance(value, str):
        return value

    def fill(m):
        name = m.group(1)
        if name in known:
            return known[name]
        if name.startswith("env:"):
            return os.environ.get(name[4:], "")
        if name.startswith("config:") and config is not None and name[7:] in config:
            return str(config[name[7:]])
        if name.startswith("workspaceFolder:"):
            return known.get("workspaceFolder", "")
        if missing is not None and name not in missing:
            missing.append(name)
        return m.group(0)
    return _VAR.sub(fill, value)


# -------------------------------------------------------------------------------------------------------- tasks.json
def _arg(a) -> str:
    """One argument for the shell: VS Code's {"value": ..., "quoting": "escape" | "strong" | "weak"} or a plain string."""
    if isinstance(a, dict):
        value, how = str(a.get("value", "")), a.get("quoting", "strong")
        return '"' + value.replace('"', '\\"') + '"' if how == "weak" else shlex.quote(value)
    a = str(a)
    return a if a and re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", a) else shlex.quote(a)


def _linux(task: dict) -> dict:
    """A task with its "linux" overrides applied (VS Code lets a task differ by system)."""
    over = task.get("linux")
    if not isinstance(over, dict):
        return task
    merged = dict(task, **{k: v for k, v in over.items() if k != "options"})
    if isinstance(over.get("options"), dict):
        merged["options"] = dict(task.get("options") or {}, **over["options"])
    return merged


def _one_command(task: dict, known: dict, config: dict, missing: list) -> str:
    """The shell command a task stands for ("" when it has none of its own: one that only runs others)."""
    kind = task.get("type", "shell")
    if kind == "npm":
        cmd, args = "npm", ["run", str(task.get("script", ""))] if task.get("script") not in (None, "install") else ["install"]
    elif kind == "cargo":
        cmd, args = "cargo", [str(task.get("command", "build"))] + [str(a) for a in task.get("args", []) if isinstance(a, (str, int, float))]
    elif kind == "cmake":
        cmd, args = "cmake", ["--build", "build"] + (["--target", str(t)] if (t := (task.get("targets") or [None])[0]) and t != "all" else [])
    elif kind in ("shell", "process", "cppbuild"):
        cmd, args = task.get("command", ""), task.get("args", [])
        if isinstance(cmd, dict):
            cmd = _arg(cmd)
    else:
        return ""
    if not cmd:
        return ""
    # (${...} is filled in before quoting, so a path with a space in it stays one argument)
    fill = lambda v: substitute(v, known, config, missing)                                    # noqa: E731
    args = fill(args) if isinstance(args, list) else []
    line = " ".join([str(fill(cmd))] + [_arg(a) for a in args])
    opts = fill(task.get("options")) if isinstance(task.get("options"), dict) else {}
    env = opts.get("env") if isinstance(opts.get("env"), dict) else {}
    sets = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in env.items() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)))
    line = (f"env {sets} " if sets and kind == "process" else f"export {sets}; " if sets else "") + line
    if opts.get("cwd"):
        line = f"cd {shlex.quote(str(opts['cwd']))} && {line}"
    return line


def tasks(root, known: dict = None, config: dict = None) -> list:
    """The project's .vscode/tasks.json as Build-tab tasks: {id, name, command, group, detail, cwd, default}. A task's
    dependsOn tasks run first, in order (one that failed stops the rest). A task Code can't run as written (it asks
    for an input, or is of a kind only an extension knows) is listed with why, and no command."""
    root = Path(root)
    data = load_jsonc(root / ".vscode" / "tasks.json")
    rows = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    known = known or variables(root)
    top_opts = data.get("options") if isinstance(data.get("options"), dict) else {}
    named, order = {}, []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row = _linux(row)
        label = str(row.get("label") or row.get("taskName") or row.get("script") or row.get("command") or "").strip()
        if not label or label in named:
            continue
        if top_opts:                                                   # the file's own options are each task's starting point
            own = row.get("options") if isinstance(row.get("options"), dict) else {}
            env = dict(top_opts.get("env") if isinstance(top_opts.get("env"), dict) else {}, **(own.get("env") if isinstance(own.get("env"), dict) else {}))
            row = dict(row, options=dict(top_opts, **own, **({"env": env} if env else {})))
        named[label] = row
        order.append(label)

    def command_of(label: str, seen: tuple, missing: list) -> str:
        row = named.get(label)
        if row is None or label in seen or len(seen) > 20:
            return ""
        deps = row.get("dependsOn", [])
        deps = [deps] if isinstance(deps, str) else [d for d in deps if isinstance(d, str)] if isinstance(deps, list) else []
        parts = [c for c in (command_of(d, seen + (label,), missing) for d in deps) if c]
        own = _one_command(row, known, config, missing)
        if own:
            parts.append(own)
        return " && ".join(f"( {p} )" if len(parts) > 1 else p for p in parts)

    out = []
    for label in order:
        row, missing = named[label], []
        group = row.get("group")
        kind = group.get("kind") if isinstance(group, dict) else group
        default = isinstance(group, dict) and bool(group.get("isDefault")) and kind == "build"
        command = command_of(label, (), missing)
        why = ""
        if missing:
            why, command = "needs " + ", ".join("${" + m + "}" for m in missing[:3]) + ", which Code can't answer", ""
        elif not command:
            why = f"a “{row.get('type', 'shell')}” task, which only a VS Code extension can run"
        if row.get("hide"):
            continue
        out.append({"id": f"vscode:{label}", "name": label, "command": command, "group": kind if kind in ("build", "test") else "clean" if kind == "clean" else "run" if row.get("isBackground") else "build",
                    "detail": why or str(row.get("detail") or "from .vscode/tasks.json"), "cwd": "", "default": default})
    return out


# ------------------------------------------------------------------------------------------------------- launch.json
PYTHON_TYPES = ("python", "debugpy")
GDB_TYPES = ("cppdbg", "lldb", "gdb", "cppvsdbg", "lldb-dap", "lldb-mi", "codelldb")


def launches(root, known: dict = None, config: dict = None) -> list:
    """The project's .vscode/launch.json: [{name, kind ("python" | "gdb" | ""), launch (the adapter's arguments),
    before (a task to run first), why (when Code can't start it)}]."""
    root = Path(root)
    data = load_jsonc(root / ".vscode" / "launch.json")
    rows = data.get("configurations") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    known = known or variables(root)
    out = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        over = row.get("linux")
        if isinstance(over, dict):
            row = dict(row, **over)
        missing = []
        row = {k: ("${pick}" if isinstance(v, str) and v.strip() in ("${command:pickProcess}", "${command:pickRemoteProcess}", "${command:PickProcess}") else v) for k, v in row.items()}
        cfg = substitute({k: v for k, v in row.items() if k not in ("linux", "windows", "osx", "presentation")}, dict(known, pick="${pick}"), config, missing)
        kind_in, request = str(cfg.get("type", "")), str(cfg.get("request", "launch"))
        cwd = str(cfg.get("cwd") or root)
        env = {str(k): str(v) for k, v in cfg.get("env", {}).items()} if isinstance(cfg.get("env"), dict) else {}
        if isinstance(cfg.get("environment"), list):                    # cppdbg's form: [{"name": ..., "value": ...}]
            env.update({str(e.get("name")): str(e.get("value", "")) for e in cfg["environment"] if isinstance(e, dict) and e.get("name")})
        args = [str(a) for a in cfg["args"]] if isinstance(cfg.get("args"), list) else shlex.split(cfg["args"]) if isinstance(cfg.get("args"), str) else []
        kind, launch, why = "", {}, ""
        if missing:
            why = "needs " + ", ".join("${" + m + "}" for m in missing[:3]) + ", which Code can't answer"
        elif request == "attach" and kind_in in PYTHON_TYPES + GDB_TYPES:
            # join a program that is running: by its process number (asked for when the file says "pick"), or where
            # debugpy or gdbserver is listening
            python = kind_in in PYTHON_TYPES
            connect = cfg.get("connect") if isinstance(cfg.get("connect"), dict) else {}
            host, port = str(connect.get("host") or cfg.get("host") or ""), connect.get("port") or cfg.get("port") or 0
            if not python and isinstance(cfg.get("miDebuggerServerAddress"), str) and ":" in cfg["miDebuggerServerAddress"]:
                host, _, port = cfg["miDebuggerServerAddress"].rpartition(":")
            pid = cfg.get("processId", cfg.get("pid", 0))
            pick = pid == "${pick}"
            try:
                port, pid = int(port or 0), (0 if pick else int(pid or 0))
            except (TypeError, ValueError):
                port, pid = 0, 0
            maps = [(str(m.get("localRoot", "")), str(m.get("remoteRoot", ""))) for m in cfg.get("pathMappings", []) if isinstance(m, dict)] if isinstance(cfg.get("pathMappings"), list) else []
            if not (port or pid or pick):
                why = "names no process and no port to attach to"
            else:
                kind = "python-attach" if python else "gdb-attach"
                launch = {"pid": pid, "pick": pick, "host": host, "port": port, "program": str(cfg.get("program") or ""), "mappings": maps}
        elif request != "launch":
            why = f"“{request}” isn't a way of starting Code knows"
        elif kind_in in PYTHON_TYPES:
            kind = "python"
            launch = {"type": "python", "request": "launch", "name": str(cfg["name"]), "cwd": cwd, "console": "internalConsole", "args": args, "env": env,
                      "justMyCode": bool(cfg.get("justMyCode", True)), "redirectOutput": True, "showReturnValue": True, "stopOnEntry": bool(cfg.get("stopOnEntry", False))}
            if cfg.get("module"):
                launch["module"] = str(cfg["module"])
            elif cfg.get("program"):
                launch["program"] = str(cfg["program"])
            else:
                kind, why = "", "names no program or module"
            if cfg.get("python"):
                launch["python"] = str(cfg["python"])
        elif kind_in in GDB_TYPES:
            program = str(cfg.get("program") or cfg.get("cargo") or "")
            if not program or isinstance(cfg.get("cargo"), dict):
                why = "names no program (one built by an extension's own step)" if not program or cfg.get("cargo") else ""
            if not why:
                kind = "gdb"
                launch = {"program": program, "args": args, "cwd": cwd, "env": env, "stopAtBeginningOfMainSubprogram": bool(cfg.get("stopAtEntry") or cfg.get("stopOnEntry", False))}
        else:
            why = f"its kind (“{kind_in or 'none'}”) needs a VS Code extension's debugger"
        before = cfg.get("preLaunchTask")
        out.append({"name": str(cfg["name"]), "kind": kind, "launch": launch, "before": str(before) if isinstance(before, str) else "", "why": why})
    return out


# ----------------------------------------------------------------------------------------------------- settings.json
def settings(root) -> dict:
    """The project's .vscode/settings.json ({} when there is none)."""
    data = load_jsonc(Path(root) / ".vscode" / "settings.json")
    return data if isinstance(data, dict) else {}


def workspace_settings(path) -> tuple:
    """A .code-workspace file: (its folders as absolute paths, its settings)."""
    data = load_jsonc(path)
    if not isinstance(data, dict):
        return [], {}
    base, folders = Path(path).parent, []
    for f in data.get("folders", []) if isinstance(data.get("folders"), list) else []:
        if isinstance(f, dict) and isinstance(f.get("path"), str):
            p = Path(f["path"])
            folders.append(str((p if p.is_absolute() else base / p).resolve()))
    return folders, data.get("settings") if isinstance(data.get("settings"), dict) else {}


def for_language(cfg: dict, vs_ids: list) -> dict:
    """The settings as they are for a language: the "[python]": {...} blocks laid over the general ones. A block can
    name several languages ("[javascript][typescript]")."""
    out = {k: v for k, v in cfg.items() if not k.startswith("[")}
    for key, block in cfg.items():
        if key.startswith("[") and isinstance(block, dict) and any(i in re.findall(r"\[([^\]]+)\]", key) for i in vs_ids):
            out.update(block)
    return out


def editor_config(cfg: dict, vs_ids: list = ()) -> dict:
    """VS Code's editor settings in .editorconfig's words (what Code already follows): indent_style, indent_size,
    tab_width, end_of_line, insert_final_newline, trim_trailing_whitespace, plus format_on_save, rulers and wrap."""
    c, out = for_language(cfg, list(vs_ids)), {}
    if isinstance(c.get("editor.insertSpaces"), bool):
        out["indent_style"] = "space" if c["editor.insertSpaces"] else "tab"
    size = c.get("editor.tabSize")
    if isinstance(size, int) and not isinstance(size, bool) and 1 <= size <= 16:
        out["indent_size"] = out["tab_width"] = str(size)
    if c.get("files.eol") in ("\n", "\r\n"):
        out["end_of_line"] = "lf" if c["files.eol"] == "\n" else "crlf"
    for theirs, ours in (("files.insertFinalNewline", "insert_final_newline"), ("files.trimTrailingWhitespace", "trim_trailing_whitespace"), ("editor.formatOnSave", "format_on_save")):
        if isinstance(c.get(theirs), bool):
            out[ours] = "true" if c[theirs] else "false"
    rulers = c.get("editor.rulers")
    if isinstance(rulers, list):
        cols = [r if isinstance(r, int) else r.get("column") if isinstance(r, dict) else None for r in rulers]
        out["rulers"] = [int(r) for r in cols if isinstance(r, int) and not isinstance(r, bool) and 1 <= r <= 400][:8]
    if c.get("editor.wordWrap") in ("on", "off", "bounded", "wordWrapColumn"):
        out["wrap"] = "false" if c["editor.wordWrap"] == "off" else "true"
    return out


def excluded(cfg: dict) -> list:
    """The glob patterns the project hides from its file list and search (files.exclude and search.exclude set true)."""
    out = []
    for key in ("files.exclude", "search.exclude"):
        block = cfg.get(key)
        if isinstance(block, dict):
            out += [str(k) for k, v in block.items() if v is True and str(k) not in out]
    return out


def is_excluded(rel: str, patterns: list) -> bool:
    """Does a path (relative to the project, / between its parts) match one of VS Code's glob patterns?"""
    rel = rel.strip("/")
    parts = rel.split("/")
    for pat in patterns:
        pat = pat.strip("/")
        if not pat:
            continue
        deep = pat.startswith("**/")
        core = pat[3:] if deep else pat
        core = core[:-3] if core.endswith("/**") else core
        if "/" not in core:
            names = parts if deep else parts[:1]
            if any(fnmatchcase(n, core) for n in names):
                return True
        else:
            regex = re.escape(core).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
            if re.match(("(?:.*/)?" if deep else "") + regex + "(?:/.*)?$", rel):
                return True
    return False


def associations(cfg: dict, langs: dict) -> list:
    """files.associations as [(glob, Code's language name)], the ones Code has a language for."""
    block, out = cfg.get("files.associations"), []
    if isinstance(block, dict):
        for glob, vs_id in block.items():
            name = language_name(str(vs_id), langs)
            if name:
                out.append((str(glob), name))
    return out


def associated(path: str, pairs: list) -> str:
    name = os.path.basename(path)
    for glob, lang in pairs:
        if fnmatchcase(name, glob.split("/")[-1]) or fnmatchcase(path, glob):
            return lang
    return ""


# ---------------------------------------------------------------------------------------------------------- snippets
def _body(body) -> str:
    return "\n".join(str(b) for b in body) if isinstance(body, list) else str(body or "")


def snippets(data, langs: dict, file_language: str = "") -> dict:
    """A VS Code snippet file's value as Code's {language: {prefix: (description, body)}}. A user file is for the one
    language its name says (`file_language`); a .code-snippets file says per snippet ("scope": "python,rust"), and a
    snippet with no scope is for every language ("*")."""
    out = {}
    if not isinstance(data, dict):
        return out
    for title, row in data.items():
        if not isinstance(row, dict) or not row.get("body"):
            continue
        prefixes = row.get("prefix")
        prefixes = [prefixes] if isinstance(prefixes, str) else [p for p in prefixes if isinstance(p, str)] if isinstance(prefixes, list) else []
        if file_language:
            names = [file_language]
        elif row.get("scope"):
            names = [n for n in (language_name(s, langs) for s in str(row["scope"]).split(",")) if n]
        else:
            names = ["*"]
        for lang in names:
            for prefix in prefixes:
                if prefix.strip():
                    out.setdefault(lang, {})[prefix.strip()] = (str(row.get("description") or title)[:120], _body(row["body"]))
    return out


def project_snippets(root, langs: dict) -> dict:
    out = {}
    try:
        files = sorted((Path(root) / ".vscode").glob("*.code-snippets"))[:20]
    except OSError:
        files = []
    for f in files:
        for lang, rows in snippets(load_jsonc(f), langs).items():
            out.setdefault(lang, {}).update(rows)
    return out


# ------------------------------------------------------------------------------------------------------ colour themes
# Code colours eight kinds of word. Each takes the first of these TextMate scopes a theme gives a colour to.
SCOPES = {
    "key": ("keyword.control", "keyword", "storage.type", "storage", "storage.modifier"),
    "comment": ("comment", "punctuation.definition.comment"),
    "string": ("string", "string.quoted"),
    "number": ("constant.numeric", "constant.language", "constant"),
    "type": ("entity.name.type", "support.type", "entity.name.class", "support.class", "storage.type"),
    "func": ("entity.name.function", "support.function", "meta.function-call"),
    "deco": ("meta.preprocessor", "entity.name.function.decorator", "meta.decorator", "punctuation.definition.annotation", "entity.name.tag", "variable.language"),
    "head": ("markup.heading", "entity.name.section", "entity.name.tag"),
}
_HEX = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _colour(value) -> str:
    """#rrggbb from a theme's colour (its #rgb, #rrggbb or #rrggbbaa: the see-through part is dropped), else ""."""
    if not isinstance(value, str) or not _HEX.match(value.strip()):
        return ""
    v = value.strip()[1:]
    if len(v) in (3, 4):
        v = "".join(ch * 2 for ch in v[:3])
    return "#" + v[:6].upper()


def theme(data, name: str = "") -> dict:
    """A VS Code colour theme's value as what Code uses: {name, dark, paper (the editor's background), ink (its text),
    line (the current line), select, key, comment, string, number, type, func, deco, head}. {} when it isn't a theme
    (no editor colours and no token colours)."""
    if not isinstance(data, dict):
        return {}
    colors = data.get("colors") if isinstance(data.get("colors"), dict) else {}
    rules = data.get("tokenColors") if isinstance(data.get("tokenColors"), list) else []
    by_scope = {}
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("settings"), dict):
            continue
        fg = _colour(rule["settings"].get("foreground"))
        scopes = rule.get("scope")
        scopes = [s.strip() for s in scopes.split(",")] if isinstance(scopes, str) else [s for s in scopes if isinstance(s, str)] if isinstance(scopes, list) else []
        for s in scopes:
            if fg and s and s not in by_scope:
                by_scope[s] = fg
    out = {}
    for kind, wanted in SCOPES.items():
        for scope in wanted:
            hit = by_scope.get(scope) or next((c for s, c in by_scope.items() if s.startswith(scope + ".") or scope.startswith(s + ".")), "")
            if hit:
                out[kind] = hit
                break
    paper, ink = _colour(colors.get("editor.background")), _colour(colors.get("editor.foreground"))
    if not out and not paper:
        return {}
    if paper:
        out["paper"] = paper
    if ink:
        out["ink"] = ink
    for theirs, ours in (("editor.lineHighlightBackground", "line"), ("editor.selectionBackground", "select"), ("editorLineNumber.foreground", "gutter")):
        if _colour(colors.get(theirs)):
            out[ours] = _colour(colors[theirs])
    kind = str(data.get("type") or "").lower()
    if kind in ("dark", "light", "hc", "hcdark", "hclight"):
        out["dark"] = kind in ("dark", "hc", "hcdark")
    elif paper:
        r, g, b = (int(paper[i:i + 2], 16) for i in (1, 3, 5))
        out["dark"] = (r * 299 + g * 587 + b * 114) / 1000 < 128
    else:
        out["dark"] = True
    out["name"] = str(data.get("name") or name or "Imported theme")[:80]
    return out


# ------------------------------------------------------------------------------------- what VS Code kept in the home
def user_dir():
    """VS Code's own folder for this user (VSCodium's and others' too), or None: where its settings, snippets and key
    bindings are."""
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    for name in USER_DIRS:
        d = base / name / "User"
        if d.is_dir():
            return d
    return None


def user_snippets(langs: dict, folder=None) -> dict:
    folder = Path(folder) if folder else user_dir()
    out = {}
    if not folder:
        return out
    try:
        files = sorted((folder / "snippets").glob("*"))[:200]
    except OSError:
        files = []
    for f in files:
        if f.suffix == ".json":
            lang = language_name(f.stem, langs)
            rows = snippets(load_jsonc(f), langs, lang) if lang else {}
        elif f.suffix == ".code-snippets":
            rows = snippets(load_jsonc(f), langs)
        else:
            continue
        for lang, items in rows.items():
            out.setdefault(lang, {}).update(items)
    return out


# VS Code's command names -> Code's command names (as the command palette lists them)
COMMANDS = {
    "workbench.action.files.save": "Save", "workbench.action.files.saveAll": "Save All", "workbench.action.closeActiveEditor": "Close Tab",
    "workbench.action.quickOpen": "Quick Open a File", "workbench.action.gotoLine": "Go to Line…", "workbench.action.navigateBack": "Go Back",
    "workbench.action.navigateForward": "Go Forward", "workbench.action.reopenClosedEditor": "Reopen Closed File", "workbench.action.gotoSymbol": "Go to Symbol…",
    "editor.action.revealDefinition": "Go to Definition", "editor.action.showHover": "Show Information Here", "editor.action.triggerSuggest": "Suggest",
    "actions.find": "Find", "editor.action.startFindReplaceAction": "Replace", "workbench.action.findInFiles": "Search the Project",
    "workbench.view.explorer": "Show Files", "workbench.view.scm": "Show Changes (Git)", "workbench.actions.view.problems": "Show Problems",
    "workbench.action.toggleSidebarVisibility": "Toggle the Side Panel", "workbench.action.terminal.toggleTerminal": "Toggle the Terminal",
    "workbench.action.debug.start": "Start Debugging / Continue", "workbench.action.debug.continue": "Start Debugging / Continue", "workbench.action.debug.run": "Run Without Debugging",
    "workbench.action.debug.stop": "Stop Debugging", "workbench.action.debug.stepOver": "Step Over", "workbench.action.debug.stepInto": "Step Into",
    "workbench.action.debug.stepOut": "Step Out", "editor.debug.action.toggleBreakpoint": "Toggle Breakpoint", "editor.action.rename": "Rename Symbol…",
    "editor.action.goToReferences": "Find All References", "references-view.findReferences": "Find All References", "workbench.action.splitEditor": "Split the Editor",
    "workbench.action.tasks.build": "Build", "workbench.action.tasks.runTask": "Build: Show Tasks and Output", "editor.action.marker.nextInFiles": "Build: Next Error",
    "editor.action.marker.prevInFiles": "Build: Previous Error", "editor.action.formatDocument": "Format Document", "editor.action.quickFix": "Quick Fix…",
    "editor.action.addSelectionToNextFindMatch": "Add the Next Match to the Selection (another cursor)", "editor.action.selectHighlights": "Select Every Match (a cursor on each)",
    "editor.action.insertCursorBelow": "Add a Cursor Below", "editor.action.insertCursorAbove": "Add a Cursor Above", "editor.action.commentLine": "Comment or Uncomment Lines",
    "editor.action.moveLinesUpAction": "Move Lines Up", "editor.action.moveLinesDownAction": "Move Lines Down", "editor.action.copyLinesUpAction": "Copy Lines Up",
    "editor.action.copyLinesDownAction": "Copy Lines Down", "editor.action.deleteLines": "Delete Lines", "editor.action.joinLines": "Join Lines",
    "expandLineSelection": "Select the Line", "editor.action.insertLineAfter": "New Line Below", "editor.action.insertLineBefore": "New Line Above",
    "editor.action.toggleWordWrap": "Toggle Word Wrap", "workbench.action.zoomIn": "Bigger Text", "workbench.action.zoomOut": "Smaller Text",
    "editor.action.fontZoomIn": "Bigger Text", "editor.action.fontZoomOut": "Smaller Text", "workbench.action.files.newUntitledFile": "New File",
    "editor.action.jumpToBracket": "Go to Matching Bracket", "workbench.action.files.openFolder": "Open Folder…", "workbench.action.closeFolder": "Close Folder",
    "workbench.action.showCommands": "Show All Commands", "editor.fold": "Fold", "editor.unfold": "Unfold", "editor.foldAll": "Fold All", "editor.unfoldAll": "Unfold All",
    "workbench.action.toggleZenMode": "Zen Mode", "editor.action.peekDefinition": "Peek at the Definition", "editor.emmet.action.expandAbbreviation": "Emmet: Expand the Abbreviation",
    "workbench.action.openSettings": "Settings…", "workbench.action.openGlobalKeybindings": "Keyboard Shortcuts…", "editor.action.transformToUppercase": "Make Upper Case",
    "editor.action.transformToLowercase": "Make Lower Case", "editor.action.transformToTitlecase": "Make Title Case", "editor.action.sortLinesAscending": "Sort Lines",
    "editor.action.sortLinesDescending": "Sort Lines, Z to A", "git.commit": "Git: Commit…", "git.pull": "Git: Pull", "git.push": "Git: Push", "git.sync": "Git: Pull, Then Push",
    "git.stageAll": "Git: Stage Everything", "git.checkout": "Git: Switch Branch…", "git.branch": "Git: Start a Branch…", "workbench.action.toggleMinimap": "Toggle the Minimap",
    "editor.action.toggleMinimap": "Toggle the Minimap",
}
_KEYS = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "meta": "Meta", "cmd": "Meta", "win": "Meta", "escape": "Esc", "enter": "Return", "backspace": "Backspace",
         "delete": "Del", "pageup": "PgUp", "pagedown": "PgDown", "up": "Up", "down": "Down", "left": "Left", "right": "Right", "space": "Space", "tab": "Tab",
         "home": "Home", "end": "End", "insert": "Ins", "oem_period": ".", "oem_comma": ",", "oem_minus": "-", "oem_plus": "=", "oem_1": ";", "oem_2": "/", "oem_3": "`",
         "oem_4": "[", "oem_5": "\\", "oem_6": "]", "oem_7": "'"}


def key_sequence(vs_key: str) -> str:
    """One of VS Code's key names ("ctrl+shift+p", or a chord "ctrl+k ctrl+s") as Qt writes it ("Ctrl+Shift+P",
    "Ctrl+K, Ctrl+S"). "" when it has a key Qt has no name for."""
    chords = []
    for chord in str(vs_key or "").strip().lower().split():
        parts = []
        for part in chord.replace("++", "+plus").split("+"):
            part = "+" if part == "plus" else part
            if part in _KEYS:
                parts.append(_KEYS[part])
            elif re.fullmatch(r"f\d{1,2}", part):
                parts.append(part.upper())
            elif len(part) == 1:
                parts.append(part.upper())
            elif part.startswith("numpad") and part[6:].isdigit():
                parts.append(part[6:])
            else:
                return ""
        if not parts:
            return ""
        chords.append("+".join(parts))
    return ", ".join(chords[:2])


def keybindings(data) -> dict:
    """A keybindings.json value as {Code's command name: key sequence}, for the commands Code has. A binding that
    takes a key away ("-command") is skipped; the last binding of a command wins, as in VS Code."""
    out = {}
    for row in data if isinstance(data, list) else []:
        if not isinstance(row, dict):
            continue
        ours = COMMANDS.get(str(row.get("command", "")))
        seq = key_sequence(row.get("key", ""))
        if ours and seq:
            out[ours] = seq
    return out


def user_import(langs: dict, folder=None) -> dict:
    """Everything worth bringing from VS Code's own folder: {found (the folder, or ""), snippets, settings (editor
    settings in .editorconfig's words), keys ({command: sequence}), theme (the colour theme's name, if it names one)}."""
    folder = Path(folder) if folder else user_dir()
    if not folder or not folder.is_dir():
        return {"found": "", "snippets": {}, "settings": {}, "keys": {}, "theme": ""}
    cfg = load_jsonc(folder / "settings.json")
    cfg = cfg if isinstance(cfg, dict) else {}
    return {"found": str(folder), "snippets": user_snippets(langs, folder), "settings": editor_config(cfg), "keys": keybindings(load_jsonc(folder / "keybindings.json")),
            "theme": str(cfg.get("workbench.colorTheme") or "")}


# ------------------------------------------------------------------------------------------------- Code's own settings
# Code keeps its settings under VS Code's names where VS Code has one, so a settings.json from there means the same
# here, and a project's .vscode/settings.json lays over the user's. (key, group, kind, default, title, about, choices)
SETTINGS_FILE = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn" / "code-settings.json"
SCHEMA = [
    ("editor.fontSize", "Editor", "int", 14, "Text size", "In points, 9 to 32.", (9, 32)),
    ("editor.tabSize", "Editor", "int", 4, "Tab size", "How wide a tab is, and how many spaces one level of indentation is in a new file.", (1, 16)),
    ("editor.insertSpaces", "Editor", "bool", True, "Indent with spaces", "Off: indent with tabs. A file that already indents one way keeps it.", None),
    ("editor.detectIndentation", "Editor", "bool", True, "Follow the file's own indentation", "A file that indents with tabs, or two spaces, keeps doing so whatever is set above.", None),
    ("editor.wordWrap", "Editor", "choice", "off", "Wrap long lines", "", ("off", "on")),
    ("editor.minimap.enabled", "Editor", "bool", True, "Minimap", "The small picture of the whole file down the right edge.", None),
    ("editor.guides.indentation", "Editor", "bool", True, "Indentation guides", "Faint lines down each level of indentation.", None),
    ("editor.occurrencesHighlight", "Editor", "bool", True, "Highlight the word under the cursor", "Everywhere else it appears in the file.", None),
    ("editor.stickyScroll.enabled", "Editor", "bool", True, "Keep the enclosing function in view", "Its first line stays at the top while you scroll through it.", None),
    ("editor.folding", "Editor", "bool", True, "Folding", "Arrows beside the line numbers that fold a function or block away.", None),
    ("editor.inlayHints.enabled", "Editor", "bool", True, "Inlay hints", "Parameter names and inferred types shown in the code, when the language's helper offers them.", None),
    ("editor.rulers", "Editor", "numbers", [], "Rulers", "Columns to draw a faint line at, for example 80, 120.", None),
    ("editor.formatOnSave", "Saving", "bool", False, "Format when saving", "With the language's formatter, when it has one.", None),
    ("files.trimTrailingWhitespace", "Saving", "bool", True, "Trim spaces at line ends when saving", "", None),
    ("files.insertFinalNewline", "Saving", "bool", True, "End files with a newline when saving", "", None),
    ("files.autoSave", "Saving", "choice", "off", "Save automatically", "afterDelay: a second after you stop typing. onFocusChange: when you go to another tab or app.", ("off", "afterDelay", "onFocusChange")),
    ("huginn.localHistory", "Saving", "bool", True, "Keep a history of each file", "A copy at every save, kept for a month, to compare with and go back to.", None),
    ("files.exclude", "Files", "globs", {}, "Hide from the file list and search", "Patterns such as **/*.o or **/Generated, one to a line.", None),
    ("workbench.colorTheme", "Look", "text", "", "Colour theme", "A VS Code theme you imported, or empty for the system's light and dark.", None),
    ("huginn.keymap", "Keys", "choice", "Huginn", "Keyboard shortcuts", "VS Code: the shortcuts VS Code uses on Linux, where they differ from Code's.", ("Huginn", "VS Code")),
    ("zenMode.hideLineNumbers", "Look", "bool", False, "Zen mode hides line numbers", "", None),
]
DEFAULTS = {row[0]: row[3] for row in SCHEMA}
KINDS = {row[0]: row[2] for row in SCHEMA}
_BOUNDS = {row[0]: row[6] for row in SCHEMA}


def clean(key: str, value):
    """A setting's value made right for its kind, or None when it can't be (so the next layer down is used)."""
    kind = KINDS.get(key)
    if kind == "bool":
        return value if isinstance(value, bool) else None
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        low, high = _BOUNDS[key]
        return max(low, min(high, int(value)))
    if kind == "choice":
        if key == "editor.wordWrap" and value in ("bounded", "wordWrapColumn"):
            return "on"
        return value if value in _BOUNDS[key] else None
    if kind == "text":
        return value[:200] if isinstance(value, str) else None
    if kind == "numbers":
        if not isinstance(value, list):
            return None
        cols = [v.get("column") if isinstance(v, dict) else v for v in value]
        return sorted({int(v) for v in cols if isinstance(v, (int, float)) and not isinstance(v, bool) and 1 <= v <= 400})[:8]
    if kind == "globs":
        if isinstance(value, list):
            value = {str(v): True for v in value}
        return {str(k)[:200]: bool(v) for k, v in list(value.items())[:200] if str(k).strip()} if isinstance(value, dict) else None
    return None


def load_user(path=None) -> dict:
    data = load_jsonc(path or SETTINGS_FILE)
    return data if isinstance(data, dict) else {}


def save_user(cfg: dict, path=None) -> bool:
    path = Path(path or SETTINGS_FILE)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".saving")
        tmp.write_text(json.dumps(cfg, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def value(key: str, user: dict, project: dict = None, vs_ids: list = ()):
    """A setting as it stands: the project's (.vscode/settings.json, its block for this language first), else the
    user's, else Code's own default. files.exclude is the two laid together."""
    layers = [for_language(project or {}, list(vs_ids)), for_language(user or {}, list(vs_ids))]
    if KINDS.get(key) == "globs":
        merged = {}
        for layer in reversed(layers):
            merged.update(clean(key, layer.get(key)) or {})
        return merged
    for layer in layers:
        if key in layer:
            got = clean(key, layer[key])
            if got is not None:
                return got
    return DEFAULTS.get(key)


def where_set(key: str, user: dict, project: dict = None) -> str:
    """"project", "user" or "" (the default): which layer a setting's value comes from."""
    if project and key in project and clean(key, project[key]) is not None:
        return "project"
    return "user" if user and key in user and clean(key, user[key]) is not None else ""


# The shortcuts VS Code uses on Linux where they differ from Code's own (Code's command name -> key sequence).
VSCODE_KEYMAP = {
    "Quick Open a File": "Ctrl+P", "Show All Commands": "Ctrl+Shift+P", "Go to Line…": "Ctrl+G", "Go to Symbol…": "Ctrl+Shift+O", "Go to Definition": "F12",
    "Find All References": "Shift+F12", "Rename Symbol…": "F2", "Quick Fix…": "Ctrl+.", "Format Document": "Ctrl+Shift+I", "Search the Project": "Ctrl+Shift+F",
    "Replace": "Ctrl+H", "Toggle the Side Panel": "Ctrl+B", "Toggle the Terminal": "Ctrl+`", "Show Files": "Ctrl+Shift+E", "Show Changes (Git)": "Ctrl+Shift+G",
    "Show Problems": "Ctrl+Shift+M", "Split the Editor": "Ctrl+\\", "Close Tab": "Ctrl+W", "Reopen Closed File": "Ctrl+Shift+T", "Comment or Uncomment Lines": "Ctrl+/",
    "Move Lines Up": "Alt+Up", "Move Lines Down": "Alt+Down", "Copy Lines Up": "Shift+Alt+Up", "Copy Lines Down": "Shift+Alt+Down", "Delete Lines": "Ctrl+Shift+K",
    "New Line Below": "Ctrl+Return", "New Line Above": "Ctrl+Shift+Return", "Select the Line": "Ctrl+L", "Go to Matching Bracket": "Ctrl+Shift+\\",
    "Add the Next Match to the Selection (another cursor)": "Ctrl+D", "Select Every Match (a cursor on each)": "Ctrl+Shift+L", "Add a Cursor Below": "Ctrl+Shift+Down",
    "Add a Cursor Above": "Ctrl+Shift+Up", "Start Debugging / Continue": "F5", "Run Without Debugging": "Ctrl+F5", "Stop Debugging": "Shift+F5", "Step Over": "F10",
    "Step Into": "F11", "Step Out": "Shift+F11", "Toggle Breakpoint": "F9", "Build": "Ctrl+Shift+B", "Build: Next Error": "F8", "Build: Previous Error": "Shift+F8",
    "Go Back": "Ctrl+Alt+-", "Go Forward": "Ctrl+Shift+-", "Toggle Word Wrap": "Alt+Z", "Fold": "Ctrl+Shift+[", "Unfold": "Ctrl+Shift+]", "Fold All": "Ctrl+K, Ctrl+0",
    "Unfold All": "Ctrl+K, Ctrl+J", "Zen Mode": "Ctrl+K, Z", "Peek at the Definition": "Ctrl+Shift+F10", "Settings…": "Ctrl+,", "Keyboard Shortcuts…": "Ctrl+K, Ctrl+S",
    "Save All": "Ctrl+K, S", "New File": "Ctrl+N", "Open Folder…": "Ctrl+K, Ctrl+O", "Bigger Text": "Ctrl+=", "Smaller Text": "Ctrl+-", "Show Information Here": "Ctrl+K, Ctrl+I",
    "Suggest": "Ctrl+Space", "Save": "Ctrl+S", "Find": "Ctrl+F",
}


def vs_ids_for(lang: str, langs: dict) -> list:
    """VS Code's ids for one of Code's languages (for "[python]" blocks): the helper's id and any other names."""
    ids = [k for k, v in LANGUAGE_IDS.items() if v == lang]
    info = langs.get(lang)
    if info and len(info) > 4 and info[4] and info[4] not in ids:
        ids.append(info[4])
    return ids or [lang.lower()]
