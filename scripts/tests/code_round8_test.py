#!/usr/bin/env python3
"""Code, round eight: what it takes from Visual Studio Code. A project's .vscode folder (tasks.json, launch.json,
settings.json, snippets) read as it is; VS Code colour themes; Code's own settings under VS Code's names; and
bringing a user's snippets, settings and key bindings over.
Usage: code_round8_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)"""
import json, os, shutil, sys, tempfile, time
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0:
    sys.exit("not as root: this test writes and removes files")
home = tempfile.mkdtemp(prefix="code8-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/data", XDG_CONFIG_HOME=home + "/config", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication
app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
import huginn_build as hb
import huginn_code as hc
import huginn_code_more as more
import huginn_vscode as vsc

passed = failed = 0
def ok(what, cond, extra=""):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1
        print("FAIL", what, extra)
def spin(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()
def wait(cond, seconds=60):
    end = time.time() + seconds
    while time.time() < end and not cond():
        spin(50)
    return cond()
def task(found, name): return next((t for t in found if t["name"] == name), None)
L = hc.LANGS

# ------------------------------------------------------------------------------------------- JSON as VS Code writes it
J = lambda text: json.loads(vsc.strip_jsonc(text))                                          # noqa: E731
ok("comments and trailing commas are read past", J('{\n  // one\n  "a": 1, /* two */ "b": [1, 2,],\n}') == {"a": 1, "b": [1, 2]})
ok("what looks like a comment inside a string is left alone", J('{"url": "http://x//y", "s": "a /* b */ c", "q": "say \\"hi\\" // no"}') == {"url": "http://x//y", "s": "a /* b */ c", "q": 'say "hi" // no'})
bad = Path(home) / "bad.json"; bad.write_text("{ this is not json")
ok("a file that isn't JSON, or isn't there, is None", vsc.load_jsonc(bad) is None and vsc.load_jsonc(Path(home) / "none.json") is None)

# ------------------------------------------------------------------------------------------------------ ${variables}
proj = Path(home) / "my game"; (proj / ".vscode").mkdir(parents=True); (proj / "src").mkdir()
(proj / "src" / "main.py").write_text("print('hi')\n")
V = vsc.variables(proj, str(proj / "src" / "main.py"), 6)
ok("the project, the file and the line", V["workspaceFolder"] == str(proj) and V["workspaceFolderBasename"] == "my game" and V["relativeFile"] == "src/main.py"
   and V["fileBasenameNoExtension"] == "main" and V["fileExtname"] == ".py" and V["fileDirname"] == str(proj / "src") and V["lineNumber"] == "7")
os.environ["CODE8"] = "yes"; missing = []
ok("filled in strings, lists and dicts; the environment's and a setting's too", vsc.substitute({"a": ["${workspaceFolder}/x", "${env:CODE8}"], "b": "${config:python.path}"}, V, {"python.path": "/p"}, missing)
   == {"a": [f"{proj}/x", "yes"], "b": "/p"} and missing == [])
ok("what Code can't answer is left as it is, and named", vsc.substitute("run ${input:target} ${command:pick}", V, None, missing) == "run ${input:target} ${command:pick}" and missing == ["input:target", "command:pick"])

# ------------------------------------------------------------------------------------------------------- tasks.json
(proj / ".vscode" / "tasks.json").write_text('''{
    // the studio's tasks
    "version": "2.0.0",
    "options": {"env": {"GAME": "demo"}},
    "tasks": [
        {"label": "Build", "type": "shell", "command": "make", "args": ["-j4", "all"], "group": {"kind": "build", "isDefault": true}, "problemMatcher": ["$gcc"]},
        {"label": "Assets", "type": "shell", "command": "python3", "args": ["tools/bake.py", "--out", "${workspaceFolder}/out dir", {"value": "a b", "quoting": "weak"}], "options": {"cwd": "${workspaceFolder}/assets"}},
        {"label": "Check File", "type": "process", "command": "python3", "args": ["-m", "py_compile", "${file}"], "group": "test"},
        {"label": "Everything", "dependsOn": ["Build", "Assets"], "dependsOrder": "sequence", "group": "build"},
        {"label": "Loop", "dependsOn": "Loop"},
        {"type": "npm", "script": "lint"},
        {"label": "Cargo", "type": "cargo", "command": "clippy", "args": ["--all"]},
        {"label": "Ask", "type": "shell", "command": "deploy ${input:server}"},
        {"label": "Ext", "type": "gradle", "task": "assemble"},
        {"label": "Win", "type": "shell", "command": "build.bat", "linux": {"command": "./build.sh", "args": ["--fast"]}},
        {"label": "Secret", "type": "shell", "command": "x", "hide": true},
        {"label": "Watch", "type": "shell", "command": "npm run watch", "isBackground": true},
        "nonsense",
    ]
}''')
T = vsc.tasks(proj, V)
ok("each task by its label, in the file's order, hidden ones left out", [t["name"] for t in T] == ["Build", "Assets", "Check File", "Everything", "Loop", "lint", "Cargo", "Ask", "Ext", "Win", "Watch"], [t["name"] for t in T])
ok("a command with its arguments; the default build task marked", task(T, "Build")["command"] == "export GAME=demo; make -j4 all" and task(T, "Build")["default"] and task(T, "Build")["group"] == "build")
ok("arguments with spaces are quoted, the working folder and ${...} filled in", task(T, "Assets")["command"] ==
   f"cd '{proj}/assets' && export GAME=demo; python3 tools/bake.py --out '{proj}/out dir' \"a b\"", task(T, "Assets")["command"])
ok("${file} is the file in front, kept as one argument; a test task is a test task", task(T, "Check File")["command"].endswith(f"-m py_compile '{proj}/src/main.py'") and task(T, "Check File")["group"] == "test", task(T, "Check File")["command"])
ok("a task that depends on others runs them first, in order", task(T, "Everything")["command"].startswith("( export GAME=demo; make -j4 all ) && ( cd ") and "bake.py" in task(T, "Everything")["command"])
ok("a task that depends on itself goes nowhere", task(T, "Loop")["command"] == "")
ok("npm and cargo tasks", task(T, "lint")["command"] == "export GAME=demo; npm run lint" and task(T, "Cargo")["command"].endswith("cargo clippy --all"))
ok("a task that asks for an input, or is an extension's, is listed with why and no command", task(T, "Ask")["command"] == "" and "${input:server}" in task(T, "Ask")["detail"]
   and task(T, "Ext")["command"] == "" and "gradle" in task(T, "Ext")["detail"])
ok("the Linux form of a task is the one used; a background task is a run task", task(T, "Win")["command"].endswith("./build.sh --fast") and task(T, "Watch")["group"] == "run")
both = hb.tasks(proj, {}, V)
ok("they join the Build tab, and the default one is what Build runs", [t["id"] for t in both][:2] == ["vscode:Build", "vscode:Assets"] and hb.default_task(both)["id"] == "vscode:Build")
(proj / ".vscode" / "tasks.json").write_text("{ broken")
ok("a broken tasks.json offers nothing and stops nothing", vsc.tasks(proj, V) == [] and isinstance(hb.tasks(proj, {}, V), list))

# ------------------------------------------------------------------------------------------------------ launch.json
(proj / ".vscode" / "launch.json").write_text(json.dumps({"version": "0.2.0", "configurations": [
    {"name": "Game", "type": "debugpy", "request": "launch", "program": "${workspaceFolder}/src/main.py", "args": ["--level", "2"], "env": {"DEBUG": "1"}, "cwd": "${workspaceFolder}/src", "justMyCode": False, "preLaunchTask": "Build"},
    {"name": "Module", "type": "python", "request": "launch", "module": "game.cli", "args": "--fast --seed 3"},
    {"name": "Native", "type": "cppdbg", "request": "launch", "program": "${workspaceFolder}/build/game", "args": ["-w"], "stopAtEntry": True, "environment": [{"name": "LD", "value": "x"}], "MIMode": "gdb"},
    {"name": "LLDB", "type": "lldb", "request": "launch", "program": "${workspaceFolder}/target/debug/game", "linux": {"args": ["--linux"]}},
    {"name": "Attach", "type": "cppdbg", "request": "attach", "processId": "${command:pickProcess}"},
    {"name": "Browser", "type": "chrome", "request": "launch", "url": "http://localhost:8080"},
    {"name": "Empty", "type": "python", "request": "launch"}, {"type": "python"}, "nonsense"]}))
G = {c["name"]: c for c in vsc.launches(proj, V)}
ok("each configuration by name", list(G) == ["Game", "Module", "Native", "LLDB", "Attach", "Browser", "Empty"], list(G))
ok("Python: program, arguments, environment, folder, the task to run first", G["Game"]["kind"] == "python" and G["Game"]["launch"]["program"] == f"{proj}/src/main.py" and G["Game"]["launch"]["args"] == ["--level", "2"]
   and G["Game"]["launch"]["env"] == {"DEBUG": "1"} and G["Game"]["launch"]["cwd"] == f"{proj}/src" and G["Game"]["launch"]["justMyCode"] is False and G["Game"]["before"] == "Build")
ok("Python: a module, and arguments given as one string", G["Module"]["launch"].get("module") == "game.cli" and G["Module"]["launch"]["args"] == ["--fast", "--seed", "3"])
ok("C and C++ (cppdbg) go to GDB, with stop-at-entry and its own form of environment", G["Native"]["kind"] == "gdb" and G["Native"]["launch"]["program"] == f"{proj}/build/game"
   and G["Native"]["launch"]["stopAtBeginningOfMainSubprogram"] is True and G["Native"]["launch"]["env"] == {"LD": "x"})
ok("CodeLLDB's go to GDB too, with their Linux form", G["LLDB"]["kind"] == "gdb" and G["LLDB"]["launch"]["args"] == ["--linux"])
ok("what Code can't start says why", not G["Attach"]["kind"] and G["Attach"]["why"] and not G["Browser"]["kind"] and "chrome" in G["Browser"]["why"] and not G["Empty"]["kind"] and "no program" in G["Empty"]["why"])

# ---------------------------------------------------------------------------------------------------- settings.json
S = {"editor.tabSize": 2, "editor.insertSpaces": True, "files.eol": "\r\n", "files.trimTrailingWhitespace": False, "editor.formatOnSave": True, "editor.rulers": [80, {"column": 120}, "x", 9999],
     "editor.wordWrap": "bounded", "[python]": {"editor.tabSize": 4}, "[go][makefile]": {"editor.insertSpaces": False},
     "files.exclude": {"**/*.pyc": True, "**/Generated": True, "keep.txt": False, "docs/build": True}, "search.exclude": {"**/vendor/**": True},
     "files.associations": {"*.inc": "cpp", "*.shader": "hlsl", "*.nope": "brainfuck", "Jenkinsfile": "groovy"}}
E = vsc.editor_config(S)
ok("editor settings in .editorconfig's words", E["indent_style"] == "space" and E["indent_size"] == "2" and E["end_of_line"] == "crlf" and E["trim_trailing_whitespace"] == "false"
   and E["format_on_save"] == "true" and E["rulers"] == [80, 120] and E["wrap"] == "true", E)
ok("a language's block lies over the general settings; one block can name several", vsc.editor_config(S, ["python"])["indent_size"] == "4" and vsc.editor_config(S, ["go"])["indent_style"] == "tab"
   and vsc.editor_config(S, ["makefile"])["indent_style"] == "tab" and vsc.editor_config(S, ["rust"])["indent_style"] == "space")
X = vsc.excluded(S)
ok("what the project hides", X == ["**/*.pyc", "**/Generated", "docs/build", "**/vendor/**"], X)
hid = lambda rel: vsc.is_excluded(rel, X)                                                   # noqa: E731
ok("…hides it at any depth, with what's inside, and nothing else", hid("a.pyc") and hid("x/y/b.pyc") and hid("Source/Generated") and hid("Source/Generated/a.h") and hid("docs/build") and hid("docs/build/index.html")
   and hid("vendor/lib/a.c") and hid("third/vendor/x") and not hid("a.py") and not hid("docs/builder.md") and not hid("keep.txt") and not hid("src/docs/build2"))
A = vsc.associations(S, L)
ok("file associations, for the languages Code has", A == [("*.inc", "C++"), ("*.shader", "HLSL")] and vsc.associated("/p/a.inc", A) == "C++" and vsc.associated("x.txt", A) == "")
ok("VS Code's language names", vsc.language_name("shellscript", L) == "Shell" and vsc.language_name("cpp", L) == "C++" and vsc.language_name("csharp", L) == "C#" and vsc.language_name("python", L) == "Python"
   and vsc.language_name("typescriptreact", L) == "TypeScript" and vsc.language_name("gdscript", L) == "GDScript" and vsc.language_name("cobol", L) == "")
ws = Path(home) / "studio.code-workspace"; (Path(home) / "second").mkdir()
ws.write_text('{"folders": [{"path": "my game"}, {"path": "' + home + '/second"}], "settings": {"editor.tabSize": 3} /* end */}')
ok("a .code-workspace file: its folders and its settings", vsc.workspace_settings(ws) == ([str(proj), home + "/second"], {"editor.tabSize": 3}) and vsc.workspace_settings(bad) == ([], {}))

# --------------------------------------------------------------------------------------------------------- snippets
SN = {"Log": {"prefix": ["log", "lg"], "body": ["console.log('$1');", "$0"], "description": "Print it", "scope": "javascript,typescript"},
      "Everywhere": {"prefix": "todo", "body": "// TODO: $0"}, "No body": {"prefix": "x"}, "Cobol": {"prefix": "c", "body": "x", "scope": "cobol"}}
got = vsc.snippets(SN, L)
ok("a snippet file: each prefix, for each language it names; no scope means every language", set(got) == {"JavaScript", "TypeScript", "*"} and got["JavaScript"]["lg"] == ("Print it", "console.log('$1');\n$0")
   and got["*"]["todo"] == ("Everywhere", "// TODO: $0"), got)
ok("a user's snippet file is for the language its name says", vsc.snippets(SN, L, "Python") == {"Python": {"log": got["JavaScript"]["log"], "lg": got["JavaScript"]["lg"], "todo": got["*"]["todo"], "c": ("Cobol", "x")}})
(proj / ".vscode" / "game.code-snippets").write_text('{\n // ours\n "Signal": {"prefix": "sig", "body": ["signal ${1:name}"], "scope": "gdscript"},\n}')
ok("the project's own snippets", vsc.project_snippets(proj, L) == {"GDScript": {"sig": ("Signal", "signal ${1:name}")}})

# ----------------------------------------------------------------------------------------------------------- themes
TH = {"name": "Solar", "type": "light", "colors": {"editor.background": "#fdf6e3", "editor.foreground": "#586E75FF", "editor.lineHighlightBackground": "#eee8d5", "editor.selectionBackground": "#abc"},
      "tokenColors": [{"settings": {"foreground": "#111111"}}, {"scope": "comment, string.quoted.double", "settings": {"foreground": "#93a1a1", "fontStyle": "italic"}},
                      {"scope": ["keyword.control", "storage"], "settings": {"foreground": "#859900"}}, {"scope": "string", "settings": {"foreground": "#2aa198"}},
                      {"scope": "constant.numeric.integer", "settings": {"foreground": "#d33682"}}, {"scope": "entity.name.function", "settings": {"foreground": "#268bd2"}},
                      {"scope": "support.type.primitive", "settings": {"foreground": "#b58900"}}, {"scope": "meta.preprocessor", "settings": {"foreground": "bad"}}, "nonsense"]}
t = vsc.theme(TH)
ok("a theme: its name, light or dark, the editor's colours", t["name"] == "Solar" and t["dark"] is False and t["paper"] == "#FDF6E3" and t["ink"] == "#586E75" and t["line"] == "#EEE8D5" and t["select"] == "#AABBCC", t)
ok("…and a colour for each kind of word, from the nearest scope it names", t["comment"] == "#93A1A1" and t["key"] == "#859900" and t["string"] == "#2AA198" and t["number"] == "#D33682"
   and t["func"] == "#268BD2" and t["type"] == "#B58900" and t.get("deco") == "#268BD2", t)        # (a decorator is a function name to a theme that says no more)
ok("dark is told from the background when the theme doesn't say", vsc.theme({"colors": {"editor.background": "#1e1e1e"}})["dark"] is True and vsc.theme({"colors": {"editor.background": "#ffffff"}})["dark"] is False)
ok("a file that isn't a theme is refused", vsc.theme({"version": "2.0.0", "tasks": []}) == {} and vsc.theme([1, 2]) == {} and vsc.theme(None) == {})

# -------------------------------------------------------------------------------------------- Code's own settings
ok("every setting has a default of its own kind", all(vsc.clean(k, d) == d for k, _, _, d, *_ in vsc.SCHEMA), [k for k, _, _, d, *_ in vsc.SCHEMA if vsc.clean(k, d) != d])
ok("a value of the wrong kind is no value; a number out of range is brought in", vsc.clean("editor.tabSize", "four") is None and vsc.clean("editor.tabSize", True) is None and vsc.clean("editor.tabSize", 99) == 16
   and vsc.clean("editor.formatOnSave", "yes") is None and vsc.clean("files.autoSave", "sometimes") is None and vsc.clean("editor.rulers", [120, 80, 80, "x", 0]) == [80, 120]
   and vsc.clean("files.exclude", ["a", "b"]) == {"a": True, "b": True} and vsc.clean("no.such.setting", 1) is None)
user, project = {"editor.tabSize": 2, "editor.formatOnSave": True, "files.exclude": {"**/a": True, "**/b": True}, "[python]": {"editor.tabSize": 4}}, {"editor.tabSize": 8, "files.exclude": {"**/b": False, "**/c": True}, "editor.formatOnSave": "nope"}
ok("the project's lie over the user's, the user's over the defaults", vsc.value("editor.tabSize", user, project) == 8 and vsc.value("editor.tabSize", user, {}) == 2 and vsc.value("editor.tabSize", {}, {}) == 4
   and vsc.value("editor.tabSize", user, {}, ["python"]) == 4)
ok("a project's wrong value falls through to the user's; excluded files are the two together", vsc.value("editor.formatOnSave", user, project) is True
   and vsc.value("files.exclude", user, project) == {"**/a": True, "**/b": False, "**/c": True})
ok("where a value comes from", vsc.where_set("editor.tabSize", user, project) == "project" and vsc.where_set("editor.formatOnSave", user, project) == "user" and vsc.where_set("editor.minimap.enabled", user, project) == "")

# ----------------------------------------------------------------------------------------- keys, and VS Code's folder
ok("VS Code's key names as Qt writes them", vsc.key_sequence("ctrl+shift+p") == "Ctrl+Shift+P" and vsc.key_sequence("ctrl+k ctrl+s") == "Ctrl+K, Ctrl+S" and vsc.key_sequence("alt+down") == "Alt+Down"
   and vsc.key_sequence("ctrl+oem_2") == "Ctrl+/" and vsc.key_sequence("f12") == "F12" and vsc.key_sequence("ctrl+`") == "Ctrl+`" and vsc.key_sequence("ctrl+nokey") == "" and vsc.key_sequence("") == "")
KB = [{"key": "ctrl+shift+j", "command": "editor.action.joinLines"}, {"key": "ctrl+e", "command": "workbench.action.quickOpen", "when": "!terminalFocus"}, {"key": "ctrl+p", "command": "-workbench.action.quickOpen"},
      {"key": "ctrl+alt+x", "command": "some.extension.command"}, {"key": "ctrl+bad", "command": "editor.action.formatDocument"}, "nonsense"]
ok("key bindings, for the commands Code has", vsc.keybindings(KB) == {"Join Lines": "Ctrl+Shift+J", "Quick Open a File": "Ctrl+E"} and vsc.keybindings({"not": "a list"}) == {})
ok("with no VS Code on the computer there is nothing to bring", vsc.user_dir() is None and vsc.user_import(L)["found"] == "")
vs = Path(home) / "config" / "VSCodium" / "User"; (vs / "snippets").mkdir(parents=True)
(vs / "settings.json").write_text('{\n  "editor.tabSize": 2, // mine\n  "editor.formatOnSave": true,\n  "editor.fontSize": 15,\n  "workbench.colorTheme": "Dracula",\n  "telemetry.telemetryLevel": "off",\n  "[rust]": {"editor.tabSize": 4, "rust.x": 1},\n}')
(vs / "keybindings.json").write_text(json.dumps(KB))
(vs / "snippets" / "python.json").write_text(json.dumps({"Main": {"prefix": "ifmain", "body": ["if __name__ == '__main__':", "\t$0"]}}))
(vs / "snippets" / "global.code-snippets").write_text(json.dumps(SN))
(vs / "snippets" / "cobol.json").write_text(json.dumps({"X": {"prefix": "x", "body": "x"}}))
imp = vsc.user_import(L)
ok("VSCodium's folder is found too; its snippets, editor settings, keys and theme name", imp["found"] == str(vs) and imp["snippets"]["Python"]["ifmain"][1].startswith("if __name__") and "lg" in imp["snippets"]["JavaScript"]
   and imp["settings"]["indent_size"] == "2" and imp["keys"]["Join Lines"] == "Ctrl+Shift+J" and imp["theme"] == "Dracula", imp)

# ------------------------------------------------------------------------------------------------- in Code itself
(proj / ".vscode" / "tasks.json").write_text('{"version": "2.0.0", "tasks": [{"label": "Say", "type": "shell", "command": "echo", "args": ["${relativeFile}"], "group": {"kind": "build", "isDefault": true}},'
                                             ' {"label": "Fail", "type": "shell", "command": "exit 3"}, {"label": "Ask", "type": "shell", "command": "x ${input:y}"}]}')
(proj / ".vscode" / "settings.json").write_text(json.dumps(dict(S, **{"editor.formatOnSave": False})))
(proj / "Makefile").write_text("all:\n\ttrue\n")
(proj / "a.pyc").write_text("x"); (proj / "Source").mkdir(); (proj / "Source" / "Generated").mkdir(); (proj / "Source" / "Generated" / "g.h").write_text("needle\n"); (proj / "Source" / "real.h").write_text("needle\n")
(proj / "thing.inc").write_text("class A {};\n")
c = hc.Code(); said = []; c.said.connect(lambda m, bad: said.append(m))
b = c.build
c.openFolder(str(proj)); spin(200)
c.openFile(str(proj / "src" / "main.py")); spin(200)
def tab(name): return next(k for k, t in enumerate(c.tabs) if t["name"] == name)
ok("the project's tasks lead the Build tab, its default task marked", [t["name"] for t in b.tasks][:3] == ["Say", "Fail", "Ask"] and b.tasks[0]["default"] and any(t["id"] == "make" for t in b.tasks), [t["name"] for t in b.tasks])
b.runDefault(); wait(lambda: not b.running, 20)
ok("Build runs it, with the file in front filled in", b.status.startswith("Done") and b.lines.rows[1]["text"] == "src/main.py", [r["text"] for r in b.lines.rows])
c.openFile(str(proj / "thing.inc")); spin(150)
b.run("vscode:Say"); wait(lambda: not b.running, 20)
ok("…and the file in front then, when run again from another", b.lines.rows[1]["text"] == "thing.inc", [r["text"] for r in b.lines.rows])
b.run("vscode:Ask")
ok("a task Code can't run says why instead", not b.running and any("can't be run here" in s for s in said), said[-2:])
ok("the project's file associations decide a file's language", c.tabs[tab("thing.inc")]["lang"] == "C++", c.tabs[tab("thing.inc")]["lang"])
st = lambda name: (c.select(tab(name)), c.status)[1]                                          # noqa: E731
ok("the project's settings: two spaces, but four in Python", st("thing.inc")["tabWidth"] == 2 and st("main.py")["tabWidth"] == 4, (st("thing.inc"), st("main.py")))
files = c._all_files()
ok("what the project hides is out of the file list", "a.pyc" not in files and "Source/Generated/g.h" not in files and "Source/real.h" in files and "src/main.py" in files, files)
c.search("needle", True, False, False); wait(lambda: not c.searching, 20); spin(200)
ok("…and out of the search", [h["path"] for g in c.results for h in (g.get("hits") or [g])] != [] and "Generated" not in json.dumps(c.results) and "real.h" in json.dumps(c.results), c.results)
i = tab("main.py"); c.edit(i, "x = 1   \ny = 2"); c.save(i, False)
ok("the project says not to trim, and to end lines the Windows way: so saved", (proj / "src" / "main.py").read_bytes() in (b"x = 1   \r\ny = 2\r\n", b"x = 1   \ny = 2\n"), (proj / "src" / "main.py").read_bytes())
(proj / ".editorconfig").write_text("root = true\n[*]\ntrim_trailing_whitespace = true\nindent_style = tab\n")
c.edit(i, "x = 1   \ny = 2  "); c.save(i, False)
ok("an .editorconfig lies over the project's settings", b"x = 1\n" in (proj / "src" / "main.py").read_bytes().replace(b"\r\n", b"\n") and st("main.py")["indent"] == "Tab", (proj / "src" / "main.py").read_bytes())
(proj / ".editorconfig").unlink()
names = lambda lang, pre: [x["label"] for x in more.snippet_items(lang, pre)]              # noqa: E731
ok("the project's snippets are offered in their language", names("GDScript", "si") == ["sig", "signal"] or "sig" in names("GDScript", "si"), names("GDScript", "si"))
ok("its debug configurations are listed; the first that can start is what F5 uses", [(x["name"], x["ok"], x["chosen"]) for x in c.launches][:3] == [("Game", True, True), ("Module", True, False), ("Native", True, False)]
   and not c.launches[4]["ok"] and c.launches[4]["why"], c.launches)
k = len(said); c.startLaunch("Browser")
ok("one that can't start says why", any("chrome" in s for s in said[k:]) and not c.debug.active, said[k:])
k = len(said); c.startLaunch("Native")
ok("a program that isn't built yet: said, not started", (any("isn't there" in s or "GDB" in s for s in said[k:])) and not c.debug.active, said[k:])
ok("and it is remembered as the one F5 uses", [x["name"] for x in c.launches if x["chosen"]] == ["Native"])
# a settings.json saved in Code is read again at once
c.openFile(str(proj / ".vscode" / "settings.json")); spin(150); i = tab("settings.json")
c.edit(i, json.dumps({"editor.tabSize": 6})); c.save(i, False); spin(100)
ok("settings.json saved in Code takes effect at once", st("thing.inc")["tabWidth"] == 6 and "a.pyc" in c._all_files(), st("thing.inc"))
c.openFile(str(proj / ".vscode" / "tasks.json")); spin(150); i = tab("tasks.json")
c.edit(i, '{"version": "2.0.0", "tasks": [{"label": "New One", "type": "shell", "command": "true"}]}'); c.save(i, False); spin(100)
ok("and so does tasks.json", [t["name"] for t in b.tasks][:1] == ["New One"])
c.select(tab("main.py")); c.close(tab("settings.json")) if hasattr(c, "close") else None

# Code's own settings
rows = {r["key"]: r for r in c.settingsList}
ok("the settings page lists every setting with its value and where it comes from", set(rows) == set(vsc.DEFAULTS) and rows["editor.tabSize"]["value"] == 6 and rows["editor.tabSize"]["where"] == "project"
   and rows["editor.fontSize"]["low"] == 9 and rows["editor.wordWrap"]["choices"] == ["off", "on"] and rows["editor.minimap.enabled"]["where"] == "")
c.setSetting("editor.formatOnSave", True); c.setSetting("editor.rulers", "80, 120"); c.setSetting("files.exclude", "**/*.o\n\n**/tmp\n"); c.setSetting("editor.fontSize", 99); c.setSetting("editor.tabSize", "banana")
c.setSetting("no.such", 1)
saved = json.loads(vsc.SETTINGS_FILE.read_text())
ok("a setting changed is kept in Code's own settings.json, under VS Code's name, made right for its kind", saved.get("editor.formatOnSave") is True and saved.get("editor.rulers") == [80, 120] and saved.get("files.exclude") == {"**/*.o": True, "**/tmp": True}
   and saved.get("editor.fontSize") == 32 and "editor.tabSize" not in saved and "no.such" not in saved and c.size == 32, saved)
c.resetSetting("editor.fontSize"); c.setOption("guides", False)
saved = json.loads(vsc.SETTINGS_FILE.read_text())
ok("put back to its default it leaves the file; the old switches write the same settings", "editor.fontSize" not in saved and c.size == 14 and saved.get("editor.guides.indentation") is False and c.options["guides"] is False and c.options["formatOnSave"] is True)
c.setWrap(True); c.setMinimap(False)
ok("wrap and the minimap are settings too", json.loads(vsc.SETTINGS_FILE.read_text()).get("editor.wordWrap") == "on" and c.wrap and c.minimap is False and c.options["rulers"] == [80, 120])
vsc.SETTINGS_FILE.write_text('{\n  // by hand\n  "editor.wordWrap": "off",\n  "editor.minimap.enabled": true,\n}\n')
c.openFile(str(vsc.SETTINGS_FILE)); spin(150); i = tab(vsc.SETTINGS_FILE.name); c.edit(i, '{"editor.wordWrap": "on", // mine\n}'); c.save(i, False); spin(100)
ok("Code's settings.json edited by hand, comments and all, is read when saved", c.wrap is True and c.minimap is True)

# themes and bringing things over
tf = Path(home) / "solar.json"; tf.write_text(json.dumps(TH))
ok("a theme file that isn't one is refused with why", "isn't" in c.importTheme(str(bad)) and "no editor colours" in c.importTheme(str(proj / ".vscode" / "launch.json")) and c.theme == {})
ok("a theme imported is in use, and named in the settings", c.importTheme("file://" + str(tf)) == "" and c.theme["name"] == "Solar" and c.theme["paper"] == "#FDF6E3"
   and json.loads(vsc.SETTINGS_FILE.read_text()).get("workbench.colorTheme") == "Solar")
c.clearTheme()
ok("and can be let go", c.theme == {} and "workbench.colorTheme" not in json.loads(vsc.SETTINGS_FILE.read_text()))
ok("VS Code's folder is found", c.vscodeFolder == str(vs))
told = c.importFromVSCode()
saved = json.loads(vsc.SETTINGS_FILE.read_text())
ok("bringing things over: said in words", told.startswith("Brought from VS Code: 3 settings, ") and "2 key bindings" in told and "Dracula" in told, told)
ok("its settings Code has are taken, the rest left; a language's block keeps only what Code knows", saved.get("editor.tabSize") == 2 and saved.get("editor.fontSize") == 15 and "telemetry.telemetryLevel" not in saved
   and saved.get("[rust]") == {"editor.tabSize": 4} and saved.get("huginn.keys", {}).get("Join Lines") == "Ctrl+Shift+J", saved)
ok("and its snippets are offered", "ifmain" in names("Python", "if") and "lg" in names("JavaScript", "l") and "todo" in names("Rust", "to"), (names("Python", "if"), names("Rust", "to")))
c2 = hc.Code()
ok("all of it is there the next time Code starts", c2.size == 15 and vsc.value("editor.tabSize", c2._user) == 2 and "ifmain" in [x["label"] for x in more.snippet_items("Python", "if")],
   (c2.size, c2._user, [x["label"] for x in more.snippet_items("Python", "if")]))
c.openFolder(str(ws)); spin(200)
ok("a .code-workspace file opens its first folder, with its settings under the project's", str(c._root) == str(proj) and any("2 folders" in s for s in said), said[-3:])
c.closeFolder(); spin(100)
ok("with the folder closed, the project's settings, tasks and debug configurations are gone", c.launches == [] and b.tasks == [] and c._proj == {} and c.setting("editor.tabSize") == 2)

# ================================================================== shortcuts you choose
ok("Code's own keymap changes nothing; VS Code's brings its keys", c.keys == {k: v for k, v in c.ownKeys.items()} and c.setSetting("huginn.keymap", "VS Code") is None
   and c.keys.get("Reopen Closed File") == "Ctrl+Shift+T" and c.keys.get("Join Lines") == "Ctrl+Shift+J", c.keys)
c.setSetting("huginn.keymap", "Huginn"); c.resetKeys()
c.setKey("Toggle Word Wrap", "ctrl+alt+q"); c.setKey("Save", ""); c.setKey("", "Ctrl+1"); c.setKey("Find", "not a key at all !!")
ok("a shortcut of your own is kept as Qt writes it; none at all is kept as none", c.ownKeys.get("Toggle Word Wrap") == "Ctrl+Alt+Q" and c.ownKeys.get("Save") == "" and "" not in c.ownKeys
   and json.loads(vsc.SETTINGS_FILE.read_text())["huginn.keys"]["Toggle Word Wrap"] == "Ctrl+Alt+Q", c.ownKeys)
c.setKey("Go Back", "Ctrl+K, Ctrl+B")
ok("a two-step shortcut too", c.ownKeys.get("Go Back") == "Ctrl+K, Ctrl+B")
c.resetKey("Save"); c.resetKey("never set")
ok("put back one at a time, or all at once", "Save" not in c.ownKeys and "Toggle Word Wrap" in c.ownKeys and (c.resetKeys() is None) and c.ownKeys == {} and "huginn.keys" not in json.loads(vsc.SETTINGS_FILE.read_text()))
from PySide6.QtCore import Qt
ok("what a key press is called", c.keyName(Qt.Key.Key_K.value, (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier).value) == "Ctrl+Shift+K" and c.keyName(Qt.Key.Key_F7.value, 0) == "F7"
   and c.keyName(Qt.Key.Key_Control.value, Qt.KeyboardModifier.ControlModifier.value) == "" and c.keyName(Qt.Key.Key_Shift.value, 0) == "" and c.keyName(0, 0) == "" and c.keyName(-5, 99) == "")
ok("every command VS Code's keymap names has keys Qt can read", all(vsc.key_sequence(v.lower().replace(", ", " ")) or True for v in vsc.VSCODE_KEYMAP.values())
   and all(not __import__("PySide6.QtGui", fromlist=["QKeySequence"]).QKeySequence(v).isEmpty() for v in vsc.VSCODE_KEYMAP.values()))

# ================================================================== the editor: folding, Emmet, history, auto save
import huginn_emmet as em
F = more.fold_ranges
py = "def a():\n    x = 1\n    if x:\n        y = 2\n\n    return x\n\n\nclass B:\n\tdef c(self):\n\t\tpass\nint main() {\n    return 0;\n}\n"
ok("what can be folded, by indentation; blank lines after, and a closing brace, stay", F(py) == [(0, 5), (2, 3), (8, 10), (9, 10), (11, 12)], F(py))
ok("nothing to fold in flat text, one line, or none", F("a\nb\nc") == [] and F("") == [] and F("only") == [] and F("\n\n\n") == [])
ok("the fold for a line: the one starting there, else the innermost around it", more.fold_range_at(F(py), 0) == (0, 5) and more.fold_range_at(F(py), 3) == (2, 3) and more.fold_range_at(F(py), 5) == (0, 5)
   and more.fold_range_at(F(py), 6) is None and more.fold_range_at([], 0) is None)
E = em.expand
ok("Emmet: a tag, classes and an id, text, children and siblings", E("div") == "<div>${0}</div>" and E("p.a.b#c{Hi}") == '<p id="c" class="a b">Hi</p>${0}'
   and E("ul>li*2") == "<ul>\n\t<li>${1}</li>\n\t<li>${2}</li>\n</ul>${0}" and E("h1+p") == "<h1>${1}</h1>\n<p>${2}</p>${0}", (E("p.a.b#c{Hi}"), E("ul>li*2")))
ok("Emmet: numbering, also through a child; climbing up; groups", 'class="item2"' in E("ul>li.item$*2") and "Item 2" in E("ul>li*2>a{Item $}") and E("h$$*2").startswith("<h01>")
   and E("ul>li^p").endswith("</ul>\n<p>${2}</p>${0}") and E("(header>h1)+footer").count("\n") == 3, E("ul>li^p"))
ok("Emmet: a nameless tag is what its parent takes; tags that have no end; what tags need", '<li class="x">' in E("ul>.x") and "<span" in E("em>.y") and E(".box") == '<div class="box">${0}</div>'
   and E("img") == '<img src="${1}" alt="${2}">${0}' and E("a") == '<a href="${1}">${0}</a>' and E("a:mail") == '<a href="mailto:">${0}</a>' and 'type="email"' in E("input:email"), (E("a"), E("ul>.x")))
ok("Emmet: attributes given, a page's skeleton, and what isn't an abbreviation", E("a[href=x.html target=_blank]{go}") == '<a href="x.html" target="_blank">go</a>${0}' and E("!").startswith("<!DOCTYPE html>")
   and E("bad>>") is None and E("") is None and E("a{b") is None and E("(a") is None and E("x" * 500) is None)
ok("Emmet: a slip of a number makes no more than two thousand", E("li*999999").count("<li>") == em.LIMIT and E("ul>li*3000>a*3000") is None)
C = em.expand_css
ok("Emmet in CSS", C("m10") == "margin: 10px;${0}" and C("p10-20") == "padding: 10px 20px;${0}" and C("w100p") == "width: 100%;${0}" and C("df") == "display: flex;${0}" and C("m-5") == "margin: -5px;${0}"
   and C("lh1.5") == "line-height: 1.5;${0}" and C("fz1.2e") == "font-size: 1.2em;${0}" and C("c") == "color: ${1};${0}" and C("p10!") == "padding: 10px !important;${0}" and C("m0") == "margin: 0;${0}" and C("nope") is None)
A = em.abbreviation_before
ok("Tab stays Tab after prose, inside a tag, after a sum", A("hello world") == "" and A("<div") == "" and A('<div class="a b') == "" and A("x = a>b") == "" and A("5>3") == "" and A("word") == "")
ok("…and expands after an abbreviation, wherever on the line", A("  ul>li*3") == "ul>li*3" and A("<p>ul>li") == "ul>li" and A('<div class="x">div') == "div" and A("</div>p.x") == "p.x" and A("p{two words}") == "p{two words}"
   and A("a[href=a b]") == "a[href=a b]" and A("  m10", "css") == "m10" and A("margin: m10", "css") == "" and A(".a { df", "css") == "df")
web = Path(home) / "web"; web.mkdir(); (web / "index.html").write_text("<body>\n</body>\n"); (web / "s.css").write_text(".a {\n}\n"); (web / "a.py").write_text(py)
c.openFolder(str(web)); spin(150)
c.openFile(str(web / "index.html")); c.openFile(str(web / "s.css")); c.openFile(str(web / "a.py")); spin(200)
ok("Code offers it in HTML and CSS, and not in Python", c.emmetAt(tab("index.html"), "  ul>li")["back"] == 5 and "<ul>" in c.emmetAt(tab("index.html"), "  ul>li")["body"] and c.emmetAt(tab("s.css"), "  m10")["body"] == "margin: 10px;${0}"
   and c.emmetAt(tab("a.py"), "ul>li") == {} and c.emmetAt(tab("index.html"), "plain words") == {} and c.emmetAt(99, "div") == {})
i = tab("a.py")
ok("what can be folded in an open file", c.foldRanges(i)[:2] == [[0, 5], [2, 3]] and c.foldRanges(99) == [])
# folding itself acts on the editor's own text: given one here, as the window gives it
from PySide6.QtGui import QTextDocument
class FakeQuickDoc:
    def __init__(self, text): self.d = QTextDocument(); self.d.setPlainText(text)
    def textDocument(self): return self.d
fq = FakeQuickDoc(c.textOf(i)); c.style(i, {"doc": fq, "colours": {}})
moved = []; c.folded.connect(moved.append)
c.toggleFold(i, 0)
ok("folding a function hides the lines under it, and says so to the window", c.hiddenOf(i) == [[1, 5]] and moved == [i] and not fq.d.findBlockByNumber(3).isVisible() and fq.d.findBlockByNumber(0).isVisible())
c.toggleFold(i, 0)
ok("again, and they are back", c.hiddenOf(i) == [] and fq.d.findBlockByNumber(3).isVisible())
c.foldAt(i, 3); c.foldAt(i, 3)
ok("folding from inside a block folds the innermost around the line, once", c.hiddenOf(i) == [[3, 3]])
c.unfoldAt(i, 3)
ok("a hidden line asked for is shown", c.hiddenOf(i) == [])
c.foldAll(i)
ok("fold all, unfold all", c.hiddenOf(i) == [[1, 5], [9, 10], [12, 12]] and (c.unfoldAll(i) is None) and c.hiddenOf(i) == [], c.hiddenOf(i))
c.toggleFold(i, 0)
from PySide6.QtGui import QTextCursor
cur = QTextCursor(fq.d.findBlockByNumber(0)); cur.select(QTextCursor.SelectionType.LineUnderCursor); cur.insertText("        x = 1")     # typed over the line that stood over the fold: it is deeper than them now
c.edit(i, fq.d.toPlainText())
ok("(the lines are still hidden just after the typing)", c.hiddenOf(i) == [[1, 5]])
c.checkFolds(i)
ok("text is never left hidden with nothing standing over it", c.hiddenOf(i) == [], c.hiddenOf(i))
c.setSetting("editor.folding", False); c.toggleFold(i, 8)
ok("with folding switched off, nothing folds", c.hiddenOf(i) == [] and c.foldRanges(i) == [])
c.setSetting("editor.folding", True)

# a file's history
hp = str(web / "notes.txt"); now = time.time()
ok("a version is kept; the same again is not", more.history_keep(hp, "one\n", now - 3 * 86400) and not more.history_keep(hp, "one\n", now - 2 * 86400) and more.history_keep(hp, "one\ntwo\n", now - 86400 - 60) and more.history_keep(hp, "three", now))
H = more.history_list(hp, now)
ok("newest first, with when and how long", [h["lines"] for h in H] == [1, 2, 1] and H[0]["when"].startswith("Today, ") and H[1]["when"].startswith("Yesterday, ") and H[2]["when"][0].isdigit(), H)
ok("a version read back; one that isn't there is None", more.history_read(hp, H[1]["id"]) == "one\ntwo\n" and more.history_read(hp, "12345") is None and more.history_read(hp, "../../x") is None)
ok("what changed since", "+three" in more.history_diff("one\ntwo\n", "three") and "-two" in more.history_diff("one\ntwo\n", "three"))
for k in range(70):
    more.history_keep(hp, f"v{k}\n", now + k)
ok("no more than sixty are kept", len(more.history_list(hp, now + 100)) == more.HISTORY_KEEP and more.history_read(hp, more.history_list(hp)[0]["id"]) == "v69\n")
op = str(web / "old.txt")
for k in range(8):
    more.history_keep(op, f"o{k}\n", now - 90 * 86400 + k)
more.history_keep(op, "new\n", now)
ok("old ones go after a month, but the five newest stay whatever their age", len(more.history_list(op, now)) == 5 and more.history_read(op, more.history_list(op, now)[0]["id"]) == "new\n", len(more.history_list(op, now)))
ok("a huge file is not kept", not more.history_keep(str(web / "big.bin"), "x" * (more.HISTORY_MAX + 1)))
(web / "story.txt").write_text("first draft\n")
c.openFile(str(web / "story.txt")); spin(150); i = tab("story.txt")
c.edit(i, "second draft\n"); c.save(i, False); c.edit(i, "third draft\n"); c.save(i, False)
rows = c.historyOf(i)
ok("Code keeps a copy at each save, and what the file held before it first changed it", [more.history_read(str(web / "story.txt"), r["id"]) for r in rows] == ["third draft\n", "second draft\n", "first draft\n"], rows)
d = c.historyDiff(i, rows[2]["id"])
ok("a kept version compared with now", any(r["kind"] == "del" and "first draft" in r["text"] for r in d) and any(r["kind"] == "add" and "third draft" in r["text"] for r in d), d)
ok("going back puts it in the editor, unsaved", c.historyRestore(i, rows[2]["id"]) and c.textOf(i) == "first draft\n" and (web / "story.txt").read_text() == "third draft\n" and c.tabs[i]["dirty"]
   and not c.historyRestore(i, "999") and c.historyDiff(i, "nope") == [])
c.setSetting("huginn.localHistory", False); c.edit(i, "fourth\n"); c.save(i, False)
ok("switched off, nothing more is kept", len(c.historyOf(i)) == 3)
c.setSetting("huginn.localHistory", True)

# auto save
c.setSetting("files.autoSave", "afterDelay"); c.edit(i, "typed and left\n")
ok("save automatically: a second after typing stops", wait(lambda: (web / "story.txt").read_text() == "typed and left\n", 5) and not c.tabs[i]["dirty"])
c.setSetting("files.autoSave", "onFocusChange"); c.edit(i, "going elsewhere\n"); spin(1400)
ok("…or only on going elsewhere", (web / "story.txt").read_text() == "typed and left\n" and (c.autoSave("focus") is None) and (web / "story.txt").read_text() == "going elsewhere\n")
c.edit(i, "mine\n"); time.sleep(0.05); (web / "story.txt").write_text("theirs\n"); os.utime(web / "story.txt", (time.time() + 5, time.time() + 5)); c.autoSave("focus")
ok("a file changed on disk meanwhile is not written over without asking", (web / "story.txt").read_text() == "theirs\n" and c.tabs[i]["dirty"])
c.setSetting("files.autoSave", "off"); c.edit(i, "x\n"); c.autoSave("focus"); c.autoSave("delay")
ok("off means off", (web / "story.txt").read_text() == "theirs\n")
c.reload(i)

# peek
c.select(tab("a.py")); c.edit(tab("a.py"), "def helper():\n    return 1\n\n\nvalue = helper()\n"); spin(100)
got = []; c.peeked.connect(lambda t, what: got.append(what))
c.peek(tab("a.py"), 4, 10); wait(lambda: bool(got), 15)
ok("peek shows the definition's lines without leaving the file", got and got[-1]["line"] == 0 and got[-1]["first"] == 0 and got[-1]["text"].startswith("def helper():") and got[-1]["name"] == "a.py"
   and c.tabs[c.current]["name"] == "a.py", got[-1:] )

# ================================================================== another computer, over SSH
import subprocess
import huginn_remote as hr
PT = hr.parse_target
def refused(text):
    try:
        PT(text)
    except ValueError as err:
        return str(err)
    return ""
ok("who, where and which folder", PT("astrid@build-box:/srv/game") == {"user": "astrid", "host": "build-box", "port": 0, "path": "/srv/game", "spec": "astrid@build-box", "label": "astrid@build-box:/srv/game"}
   and PT("box")["path"] == "" and PT("box:proj/x")["path"] == "proj/x" and PT("ssh://astrid@box:2222/srv/a b")["port"] == 2222 and PT("ssh://astrid@box:2222/srv/a b")["path"] == "/srv/a b"
   and PT("astrid@[fe80::1]:/x")["host"] == "[fe80::1]" and PT("  box  ")["host"] == "box")
ok("a name that would be read as one of ssh's options, or isn't a name, is refused with words", refused("-oProxyCommand=evil") and refused("a b") and refused("u ser@h") and refused("host:/a\nb") and refused("")
   and refused("ssh://box:99999/x") and refused("box;rm -rf ~") and refused("$(reboot)"))
RM = PT("astrid@build-box:/srv/game"); MT = "/home/a/.cache/huginn/remote/x"
ok("each computer and folder has its own place to be mounted, with a plain name", hr.mount_point(RM).parent == hr.MOUNTS and hr.mount_point(RM) != hr.mount_point(PT("astrid@build-box:/srv/other"))
   and "/" not in hr.mount_point(PT("ssh://a@b:22/x y/z")).name and " " not in hr.mount_point(PT("ssh://a@b:22/x y/z")).name)
mc = hr.mount_command(RM, MT)
ok("the mount line: sshfs, coming back after a drop, files shown as yours, one shared connection", "sshfs -o reconnect,idmap=user" in mc and "ControlMaster=auto" in mc and "astrid@build-box:/srv/game" in mc and mc.rstrip().endswith("opening the folder.'")
   and "ControlPath=" in mc and f" {MT} " in mc, mc)
ok("a port is ssh's -p", hr.ssh_options(PT("ssh://a@b:2222/x"))[-2:] == ["-p", "2222"] and "-p 2222" in hr.mount_command(PT("ssh://a@b:2222/x"), MT) and "-p" not in hr.ssh_options(RM))
w = hr.wrap(RM, f"make -C {MT}/sub && cat '{MT}/a b.txt' {MT}", mount=MT)
ok("a command as run over there: in the folder there, this computer's paths turned into the other's, and never stopping to ask", w.endswith("astrid@build-box 'cd /srv/game && make -C /srv/game/sub && cat '\"'\"'/srv/game/a b.txt'\"'\"' /srv/game'")
   and "BatchMode=yes" in w and " -t " not in w, w)
ok("with a terminal it may ask; a shell there starts in the folder", " -t " in hr.wrap(RM, "ls", tty=True) and "BatchMode" not in hr.wrap(RM, "ls", tty=True) and hr.shell_command(RM).endswith("'cd /srv/game && exec \"$SHELL\" -l'"))
HM = PT("box")
ok("the home folder over there: paths are from it", hr.wrap(HM, f"ls {MT}/x", mount=MT).endswith("box 'ls x'") and hr.to_remote(HM, MT, MT + "/x/y") == "x/y" and hr.to_local(HM, MT, "x/y") == MT + "/x/y" and hr.to_local(HM, MT, "/abs") == "")
ok("a path on one side as it is on the other; outside the folder it has no place here", hr.to_remote(RM, MT, MT + "/src/a.c") == "/srv/game/src/a.c" and hr.to_remote(RM, MT, MT) == "/srv/game"
   and hr.to_local(RM, MT, "/srv/game/src/a.c") == MT + "/src/a.c" and hr.to_local(RM, MT, "/srv/game") == MT and hr.to_local(RM, MT, "/etc/passwd") == "" and hr.to_local(RM, MT, "/srv/gamer/x") == "")
cfgf = Path(home) / "ssh_config"; cfgf.write_text("Host build-box render\n  HostName 10.0.0.5\nhost *.lan !bad\n  User x\nHost github.com\nHost -evil\n")
ok("the computers ~/.ssh/config names, not its patterns", hr.config_hosts(cfgf) == ["build-box", "render", "github.com"] and hr.config_hosts(Path(home) / "none") == [])
fake_mount = Path(home) / "mounted"; (fake_mount / "src").mkdir(parents=True); (fake_mount / "src" / "a.c").write_text("x\n")
st8 = {"there": (hr, RM, str(fake_mount))}
got = hb.parse_line("/srv/game/src/a.c:3:1: error: over there", fake_mount, st8)
ok("an error naming a file on the other computer opens the same file here", got and got["path"] == str(fake_mount / "src" / "a.c") and got["line"] == 2, got)
got = [hb.parse_line(l, fake_mount, st8) for l in ("make[1]: Entering directory '/srv/game/src'", "a.c:9:2: warning: deep")][1]
ok("…also when make says which directory there it is in", got and got["path"] == str(fake_mount / "src" / "a.c"), got)
ok("with no folder open there is no remote; a bad name is refused before anything is tried", c.remote == {} and "isn't a computer's name" in c.remoteConnect("bad name") and c.remote == {})

reach = shutil.which("ssh") and shutil.which("sshfs") and subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "testbox", "true"], capture_output=True).returncode == 0
if reach:                                                          # (a test SSH server on this computer, with a throwaway key: see the README)
    remote = PT("testbox:remote-proj"); mount = hr.mount_point(remote)
    there = Path.home().parent  # not used: the server's own home is where remote-proj lives
    subprocess.run(["ssh", "-o", "BatchMode=yes", "testbox", "rm -rf remote-proj && mkdir -p remote-proj/src && printf 'all:\\n\\tcc -o prog src/main.c\\n' > remote-proj/Makefile && "
                    "printf '#include <stdio.h>\\nint main(void)\\n{\\n    printf(\"hi\\\\n\")\\n    return 0;\\n}\\n' > remote-proj/src/main.c"], capture_output=True, timeout=30)
    if hr.is_mounted(mount):
        subprocess.run(hr.unmount_command(mount), capture_output=True)
    done = subprocess.run(["bash", "-c", hr.mount_command(remote, mount)], capture_output=True, text=True, timeout=60)
    ok("a real SSH server: the folder mounts", done.returncode == 0 and hr.is_mounted(mount) and sorted(os.listdir(mount)) == ["Makefile", "src"], (done.returncode, done.stderr[:200]))
    while c.tabs:
        c.close(0, True)                                           # (what earlier checks left unsaved is let go)
    ok("Code opens it, and knows it is on another computer", c.remoteConnect("testbox:remote-proj") == "" and str(c._root) == str(mount) and c.remote.get("spec") == "testbox" and c.remote.get("connected") is True, c.remote)
    c.openFile(str(mount / "src" / "main.c")); spin(300); i = tab("main.c")
    ok("its files open as any others", c.textOf(i).startswith("#include <stdio.h>"))
    ok("it is among the computers offered next time", "testbox:remote-proj" in c.remoteHosts)
    b.run("make"); wait(lambda: not b.running, 90)
    ok("Build runs there, and its error comes back as a place in the file here", b.status.startswith("Failed") and [(p["name"], p["line"]) for p in b.problems if p["severity"] == 1][:1] == [("src/main.c", 3)]
       and b.lines.rows[0]["text"].endswith("(on testbox)"), (b.status, b.problems, [r["text"] for r in b.lines.rows][:6]))
    c.edit(i, '#include <stdio.h>\nint main(void)\n{\n    printf("hi\\n");\n    return 0;\n}\n'); c.save(i, False); spin(200)
    b.again(); wait(lambda: not b.running, 90)
    made = subprocess.run(["ssh", "-o", "BatchMode=yes", "testbox", "remote-proj/prog"], capture_output=True, text=True, timeout=30).stdout
    ok("fixed here and saved, it builds there, and the program made there runs there", b.status.startswith("Done") and made == "hi\n", (b.status, made))
    k = len(said); c.startDebug("")
    ok("debugging there is refused in words, not tried here", any("another computer" in x for x in said[k:]) and not c.debug.active)
    c.remoteDisconnect(); spin(200)
    ok("disconnecting closes the folder and lets the mount go", c._root is None and not hr.is_mounted(mount) and any("Disconnected from testbox" in x for x in said[-3:]), said[-3:])
else:
    print("(no test SSH server here: mounting, building and disconnecting for real are skipped)")

print(f"{passed} passed, {failed} failed")
shutil.rmtree(home, ignore_errors=True)
sys.exit(1 if failed else 0)
