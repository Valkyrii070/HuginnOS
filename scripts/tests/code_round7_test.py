#!/usr/bin/env python3
"""Code, round seven (for game developers): GDScript, Godot's files, GLSL and HLSL; build tasks found from a project
(Godot, Unreal, CMake, Cargo, Make, Go, npm, your own); compiler output turned into places you can open; the tool
packs; and Godot's helper reached through a port.  Usage: code_round7_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)
Real builds (CMake with a C compiler, Cargo) run when those are installed and are skipped, and said so, when not."""
import json, os, shutil, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0:
    sys.exit("not as root: this test writes and removes files")
home = tempfile.mkdtemp(prefix="code7-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/data", XDG_CONFIG_HOME=home + "/config", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
os.environ.pop("UE_ROOT", None)
fake_bin = Path(home) / "bin"; fake_bin.mkdir()
os.environ["PATH"] = f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication, QTextDocument
app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
import huginn_build as hb
import huginn_code as hc
import huginn_lsp_tcp as tcp

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
def ids(found): return [t["id"] for t in found]
def task(found, tid): return next((t for t in found if t["id"] == tid), None)

# ---------------------------------------------------------------------------------------------------- languages
L = hc.language_of
ok("GDScript, Godot's scenes and resources, its shaders", L("player.gd") == "GDScript" and L("main.tscn") == "Godot Resource" and L("theme.tres") == "Godot Resource"
   and L("project.godot") == "Godot Resource" and L("water.gdshader") == "Godot Shader")
ok("GLSL by its many endings", all(L(f"x{e}") == "GLSL" for e in (".glsl", ".vert", ".frag", ".comp", ".geom")))
ok("HLSL, Unreal's shader files among them", all(L(f"x{e}") == "HLSL" for e in (".hlsl", ".hlsli", ".usf", ".ush", ".fx")))
ok("Unreal's project and plugin files are JSON, its .ini files settings", L("Game.uproject") == "JSON" and L("X.uplugin") == "JSON" and L("DefaultEngine.ini") == "Settings")
ok("a .h is C until it shows otherwise", L("a.h", "#include <stdio.h>\nint f(void);\n") == "C" and L("a.h", "class AActor;\n") == "C++"
   and L("Hero.h", "#pragma once\nUCLASS()\n") == "C++" and L("v.h", "namespace m {\n") == "C++" and L("s.h", "#include <vector>\n") == "C++")
src = Path(home) / "Source"; (src / "Public").mkdir(parents=True); (src / "Private").mkdir()
(src / "Public" / "Thing.h").write_text("void f();\n"); (src / "Private" / "Thing.cpp").write_text("void f() {}\n")
ok("and a .h with a .cpp of its name (beside it, or in Unreal's Private/) is C++", L(str(src / "Public" / "Thing.h"), "void f();\n") == "C++")
ok("every new language has a comment sign and key words", all(hc.LANGS[n][1] and hc.LANGS[n][3] for n in ("GDScript", "Godot Shader", "GLSL", "HLSL")))

def colours(lang, text):
    """{word: the name of the colour it got} for one line."""
    doc = QTextDocument(); doc.setPlainText(text)
    names = {n: f"#{i + 1:02x}0000" for i, n in enumerate(("key", "comment", "string", "number", "type", "func", "deco", "head"))}
    st = hc.CodeStyler(doc, lang, names); st.rehighlight()
    back, out = {v: k for k, v in names.items()}, {}
    block = doc.firstBlock()
    while block.isValid():
        for f in block.layout().formats():
            out[block.text()[f.start:f.start + f.length]] = back.get(f.format.foreground().color().name(), "?")
        block = block.next()
    return out
c = colours("GDScript", '@export var speed: float = 4.5  # fast\nfunc _ready():\n\t$Sprite2D.show()\n\tvar n := %Health\n\tprint("hi")')
ok("GDScript: key words, an annotation, a comment, a number, a string, a call", c.get("var") == "key" and c.get("func") == "key" and c.get("@export") == "deco" and c.get("# fast") == "comment"
   and c.get("4.5") == "number" and c.get('"hi"') == "string" and c.get("_ready") == "func" and c.get("float") == "type", c)
ok("GDScript: a node by its path and by its unique name", c.get("$Sprite2D") == "deco" and c.get("%Health") == "deco", c)
c = colours("GLSL", "#version 450\nuniform sampler2D tex;\nvoid main() { vec3 c = texture(tex, uv).rgb; }")
ok("GLSL: the preprocessor's line, key words, types, a call", c.get("#version 450") == "deco" and c.get("uniform") == "key" and c.get("sampler2D") == "type" and c.get("vec3") == "type" and c.get("texture") == "func", c)
c = colours("HLSL", "float4 PS(float2 uv : TEXCOORD0) : SV_Target { return float4(1, 0, 0, 1); }")
ok("HLSL: types and key words", c.get("float2") == "type" and c.get("return") == "key", c)
c = colours("Godot Resource", '[node name="Player" type="CharacterBody2D"]\nspeed = 300.0')
ok("a scene file: its section heads stand out", c.get("[node") == "head" and c.get('"Player"') == "string" and c.get("300.0") == "number", c)
c = colours("Settings", "; a comment\n[/Script/Engine.Engine]\nbSmoothFrameRate=true")
ok("an Unreal .ini: semicolon comments and section heads", c.get("; a comment") == "comment" and c.get("[/Script/Engine.Engine]") == "head", c)

import huginn_code_more as more
names = lambda lang, pre: [i["label"] for i in more.snippet_items(lang, pre)]              # noqa: E731
ok("snippets: Godot's callbacks, and Unreal's macros in C++", names("GDScript", "re") == ["ready"] and "physics" in names("GDScript", "p") and names("C++", "uc") == ["uclass"]
   and {"uprop", "ufunc", "uelog", "ustruct", "uenum"} <= set(names("C++", "u")) and names("Godot Shader", "c") == ["canvas"])
ok("every snippet reads as one", all(more.snippet_parse(body)["text"] for lang in ("GDScript", "C++", "GLSL", "HLSL", "Godot Shader") for _, body in more.SNIPPETS[lang].values()))
ok("a new file in each starts with something that runs", all(hc.TEMPLATES.get(n) for n in ("GDScript", "Godot Shader", "GLSL", "HLSL")) and hc.TEMPLATES["GDScript"].startswith("extends Node"))
ok("what the engines make is left out of the file list and the search", {".godot", "Intermediate", "Binaries", "DerivedDataCache", "Saved"} <= hc.HEAVY)

# ------------------------------------------------------------------------------------------- finding what to build
T = lambda root: hb.tasks(root, {})                                                       # noqa: E731
empty = Path(home) / "empty"; empty.mkdir()
ok("an empty folder offers nothing, and so does no folder", T(empty) == [] and hb.tasks(None, {}) == [] and hb.tasks(Path(home) / "nowhere", {}) == [])

godot = Path(home) / "godot-game"; godot.mkdir()
(godot / "project.godot").write_text('config_version=5\n\n[application]\nconfig/name="Demo"\n')
(godot / "export_presets.cfg").write_text('[preset.0]\n\nname="Linux"\nplatform="Linux"\nexport_path="build/demo.x86_64"\n\n[preset.0.options]\n\n[preset.1]\nname="Web Build"\nplatform="Web"\nexport_path=""\n')
ok("Godot isn't installed: the project says so and offers to add it", ids(T(godot)) == ["setup:Godot 4"] and T(godot)[0]["command"] == "", ids(T(godot)))
(fake_bin / "godot4").write_text("#!/bin/sh\necho godot \"$@\"\n"); (fake_bin / "godot4").chmod(0o755)
found = T(godot)
ok("with Godot: run, open in the editor, import, check", ids(found)[:4] == ["godot:run", "godot:editor", "godot:import", "godot:check"] and task(found, "godot:run")["command"] == "godot4 --path .", ids(found))
ok("and an export for each preset, to its own path or one made from its name", task(found, "godot:export:Linux")["command"].endswith("--export-release Linux build/demo.x86_64")
   and "build/Web-Build" in task(found, "godot:export:Web Build")["command"] and task(found, "godot:export:Linux")["group"] == "package", [t["command"] for t in found if "export" in t["id"]])
ok("what Build runs in a Godot project is a build task, not the game", hb.default_task(found)["id"] == "godot:import")
(fake_bin / "godot3").write_text("#!/bin/sh\n"); (fake_bin / "godot3").chmod(0o755)
(godot / "project.godot").write_text("config_version=4\n")
old = T(godot)
ok("a Godot 3 project gets Godot 3 and its own words: no import task, --no-window (or the server build), --export", task(old, "godot:run")["command"] == "godot3 --path ." and task(old, "godot:import") is None
   and (" --no-window " in task(old, "godot:check")["command"] or "godot3-server" in task(old, "godot:check")["command"]) and " --export Linux " in task(old, "godot:export:Linux")["command"], [t["command"] for t in old])
(fake_bin / "godot3").unlink(); (godot / "project.godot").write_text("config_version=5\n")
ok("which Godot a project was made with", hb.godot_major(godot) == 4 and (godot / "project.godot").write_text("config_version=4\n") and hb.godot_major(godot) == 3)
(godot / "project.godot").write_text('config_version=5\n[dotnet]\nproject/assembly_name="Demo"\n')
ok("a C# project is told from its project file", hb.godot_uses_dotnet(godot))
ok("the Godot you chose wins", hb.godot_command(godot, {"godot": "godot4 --verbose"}) == "godot4 --verbose" and hb.godot_command(godot, {"godot": "/no/such/godot"}) == "godot4")

ue = Path(home) / "engines" / "ue-5.6"; (ue / "Engine/Build/BatchFiles/Linux").mkdir(parents=True); (ue / "Engine/Build/BatchFiles/Linux/Build.sh").write_text("#!/bin/sh\n")
game = Path(home) / "My Game"; (game / "Source").mkdir(parents=True)
(game / "Shooter.uproject").write_text(json.dumps({"EngineAssociation": "5.6", "Modules": [{"Name": "Shooter", "Type": "Runtime"}]}))
ok("an Unreal project with no engine found asks where it is", [t["id"] for t in hb.tasks(game, {"unreal": "/nope"}) if t["group"] == "setup"] == ["setup:unreal"] or hb.unreal_root(game / "Shooter.uproject", {}) != "")
found = hb.tasks(game, {"unreal": str(ue)})
ok("with the engine: build the editor and the game, suggestions, open, play, package, clean", [i for i in ids(found) if i.startswith("ue:")] ==
   ["ue:editor", "ue:game", "ue:shipping", "ue:clangd", "ue:open", "ue:play", "ue:files", "ue:clean", "ue:package"], ids(found))
cmd = task(found, "ue:editor")["command"]
ok("the build command names the target and the project, quoted where there are spaces", "Build.sh ShooterEditor Linux Development" in cmd and "'-project=" not in cmd and f"-project='{game}/Shooter.uproject'" in cmd, cmd)
ok("the suggestions task leaves compile_commands.json in the project", task(found, "ue:clangd")["command"].endswith("compile_commands.json .") and "-mode=GenerateClangDatabase" in task(found, "ue:clangd")["command"])
bp = Path(home) / "BlueprintOnly"; bp.mkdir(); (bp / "Bp.uproject").write_text("{}")
ok("a project with no C++ gets no build tasks, only open, play and package", [i for i in ids(hb.tasks(bp, {"unreal": str(ue)}))] == ["ue:open", "ue:play", "ue:package"], ids(hb.tasks(bp, {"unreal": str(ue)})))
ok("the engine is found from UE_ROOT too, and a folder that isn't one is refused", (os.environ.__setitem__("UE_ROOT", str(ue)) or hb.unreal_root(None, {}) == str(ue)) and not hb.unreal_valid(home) and not hb.unreal_valid(""))
os.environ.pop("UE_ROOT")
ini = Path(home) / ".config/Epic/UnrealEngine"; ini.mkdir(parents=True); (ini / "Install.ini").write_text(f"[Installations]\n5.6={ue}\n")
ok("and from Epic's own list of installed engines", hb.unreal_root(game / "Shooter.uproject", {}) == str(ue))
shutil.rmtree(Path(home) / ".config/Epic")

many = Path(home) / "many"; many.mkdir()
(many / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.16)\nproject(x C)\n"); (many / "Cargo.toml").write_text("[package]\nname='x'\n")
(many / "Makefile").write_text(".PHONY: all clean test run\nall: prog\nprog: main.o\n\tcc -o prog main.o\nmain.o: main.c\nclean:\n\trm -f prog\ntest:\n\t./prog\nrun: prog\n\t./prog\nCC := gcc\n%.o: %.c\n")
(many / "go.mod").write_text("module x\n"); (many / "package.json").write_text(json.dumps({"scripts": {"build": "vite build", "dev": "vite", "test": "vitest"}}))
(many / ".huginn-tasks.json").write_text(json.dumps([{"name": "Bake Lightmaps", "command": "./tools/bake.sh", "group": "package"}, {"name": "broken"}, "nonsense"]))
(many / ".gitattributes").write_text("*.png filter=lfs diff=lfs merge=lfs -text\n")
found = T(many)
ok("your own tasks come first, the broken ones left out", ids(found)[0] == "own:0" and found[0]["group"] == "package" and "own:1" not in ids(found), ids(found)[:3])
ok("CMake: build, release, configure, test, clean", [i for i in ids(found) if i.startswith("cmake:")] == ["cmake:build", "cmake:release", "cmake:configure", "cmake:test", "cmake:clean"]
   and "CMAKE_EXPORT_COMPILE_COMMANDS=ON" in task(found, "cmake:build")["command"])
ok("Cargo: build, release, run, check, clippy, test, clean", [i for i in ids(found) if i.startswith("cargo:")] == ["cargo:build", "cargo:release", "cargo:run", "cargo:check", "cargo:clippy", "cargo:test", "cargo:clean"])
ok("Make: the targets meant to be asked for, each in its group", hb.make_targets(many) == ["all", "prog", "clean", "test", "run"] and task(found, "make:clean")["group"] == "clean"
   and task(found, "make:test")["group"] == "test" and task(found, "make:run")["group"] == "run" and task(found, "make:all") is None, hb.make_targets(many))
ok("Go and npm", {"go:build", "go:test", "go:vet", "npm:build", "npm:dev", "npm:test"} <= set(ids(found)) and task(found, "npm:build")["group"] == "build" and task(found, "npm:dev")["group"] == "run")
ok("a project that uses Git LFS", hb.uses_lfs(many) and any(i in ("setup:Git LFS", "lfs:pull") for i in ids(found)) and not hb.uses_lfs(empty))
ok("the task you chose is what Build runs; one that's gone falls back", hb.default_task(found, "cargo:check")["id"] == "cargo:check" and hb.default_task(found, "gone")["group"] == "build" and hb.default_task([], "x") is None)

# --------------------------------------------------------------------------------------------- reading the output
proj = Path(home) / "proj"; (proj / "src").mkdir(parents=True); (proj / "scripts").mkdir(); (proj / "build").mkdir()
for name in ("src/main.c", "src/lib.rs", "src/Hero.cpp", "src/Hero.h", "scripts/player.gd", "CMakeLists.txt", "Program.cs", "app.ts", "run.py", "main.go"):
    (proj / name).write_text("x\n")
def read(*lines):
    state, out = {}, []
    for line in lines:
        got = hb.parse_line(line, proj, state)
        if got:
            out.append(got)
    return out
def one(*lines):
    got = read(*lines)
    return (os.path.relpath(got[0]["path"], proj), got[0]["line"], got[0]["col"], got[0]["severity"], got[0]["message"]) if len(got) == 1 else got
ok("gcc and clang", one("src/main.c:12:5: error: expected ';' before 'return'") == ("src/main.c", 11, 4, 1, "expected ';' before 'return'"))
ok("a warning, and a note", one("src/main.c:3:9: warning: unused variable 'x' [-Wunused-variable]")[3] == 2 and one("src/main.c:1:1: note: declared here")[3] == 3)
ok("no column", one("src/main.c:7: error: stray character") == ("src/main.c", 6, 0, 1, "stray character"))
ok("an absolute path, and colour codes stripped", one(f"\x1b[1m{proj}/src/Hero.cpp:40:12:\x1b[0m \x1b[31merror:\x1b[0m no member named 'Fire'")[:4] == ("src/Hero.cpp", 39, 11, 1))
ok("a file that isn't there is not a place (a time is not a line number)", read("12:30:01: starting", "nofile.c:3:1: error: x", "http://example.org:80: note") == [])
ok("Rust: the message, then its place", one("error[E0425]: cannot find value `speed` in this scope", " --> src/lib.rs:8:13") == ("src/lib.rs", 7, 12, 1, "cannot find value `speed` in this scope [E0425]"))
ok("Rust: a warning; and its closing lines are not problems", one("warning: unused variable: `x`", "  --> src/lib.rs:2:9")[3] == 2 and read("error: could not compile `x` (lib) due to 1 previous error", " --> src/lib.rs:1:1") == [])
ok("Unreal's header tool, MSVC, C# and TypeScript: file(line)", one(f"{proj}/src/Hero.h(21): error: Missing '*' in Expected a pointer type")[:4] == ("src/Hero.h", 20, 0, 1)
   and one("Program.cs(9,13): error CS1002: ; expected [/x/y.csproj]")[:3] == ("Program.cs", 8, 12) and one("app.ts(4,7): error TS2322: Type 'string' is not assignable")[4].endswith("[TS2322]"))
ok("CMake: the message is on the next line", one("CMake Error at CMakeLists.txt:14 (add_executable):", "  Cannot find source file:", "    nope.c") == ("CMakeLists.txt", 13, 0, 1, "Cannot find source file: (add_executable)"))
ok("Godot: a script error and where", one('SCRIPT ERROR: Parse Error: Identifier "speeed" not declared in the current scope.', "          at: GDScript::reload (res://scripts/player.gd:14)")
   == ("scripts/player.gd", 13, 0, 1, 'Parse Error: Identifier "speeed" not declared in the current scope.'))
ok("Godot: an error raised while running, and the short form", one("ERROR: Node not found: \"Sprite\"", "   at: get_node (res://scripts/player.gd:22)")[1] == 21
   and one("res://scripts/player.gd:5 - Parse Error: Expected end of statement")[:2] == ("scripts/player.gd", 4))
ok("Go, and a Python traceback", one("./main.go:9:2: undefined: speed")[:3] == ("main.go", 8, 1) and one(f'  File "{proj}/run.py", line 3, in <module>')[:2] == ("run.py", 2))
(proj / "build" / "gen.c").write_text("x\n"); (proj / "sub").mkdir(); (proj / "sub" / "deep.c").write_text("x\n")
ok("paths relative to the build folder, and to a directory make entered", one("gen.c:2:1: error: x")[0] == "build/gen.c"
   and one(f"make[1]: Entering directory '{proj}/sub'", "deep.c:4:2: error: y", f"make[1]: Leaving directory '{proj}/sub'")[0] == "sub/deep.c")
ok("how a line is shown", hb.kind_of("x", {"severity": 1}) == "error" and hb.kind_of("x", {"severity": 2}) == "warning" and hb.kind_of("ninja: build stopped: subcommand failed.", None) == "error"
   and hb.kind_of("[3/9] Compiling Hero.cpp", None) == "plain" and hb.kind_of("ld: error: undefined symbol: Fire", None) == "error")
P = [{"severity": 1}, {"severity": 2}, {"severity": 2}]
ok("what it says at the end", hb.summary(0, False, [], 3.21) == "Done in 3.2 s" and hb.summary(0, False, P[1:], 75) == "Done in 1 min 15 s · 2 warnings"
   and hb.summary(2, False, P, 9) == "Failed after 9.0 s · 1 error, 2 warnings" and hb.summary(127, False, [], 0.1) == "Failed after 0.1 s · exit code 127"
   and hb.summary(-1, False, [], 4, stopped=True) == "Stopped after 4.0 s" and hb.summary(-1, True, [], 0) == "Couldn't be run (0.0 s)")

# ------------------------------------------------------------------------------------------------ running a task
c = hc.Code(); said = []; c.said.connect(lambda m, bad: said.append(m))
b = c.build
went = []; b.goTo.connect(lambda p, ln, col: went.append((os.path.basename(p), ln, col)))
c.openFolder(str(empty)); spin(100)
b.runDefault()
ok("nothing to build: said, not run", not b.running and any("nothing to build" in s for s in said), said)
(proj / ".huginn-tasks.json").write_text(json.dumps([
    {"name": "Fake Compile", "command": "echo 'src/main.c:12:5: error: expected ;'; echo 'src/main.c:3:9: warning: unused'; echo 'src/Hero.cpp:2:1: error: second'; echo plain; exit 2"},
    {"name": "Fine", "command": "printf 'one\\ntwo'; echo; echo \"$PWD\""}, {"name": "Slow", "command": "sleep 30 & sleep 30", "group": "run"},
    {"name": "Many Lines", "command": "seq 1 7000"}, {"name": "No Such Tool", "command": "definitely-not-a-program --x"}]))
shutil.rmtree(proj / "build"); (proj / "CMakeLists.txt").unlink()
c.openFolder(str(proj)); spin(150)
ok("the project's tasks are listed and the first is what Build runs", [t["name"] for t in b.tasks][:2] == ["Fake Compile", "Fine"] and b.tasks[0]["default"] and not b.tasks[1]["default"], [t["name"] for t in b.tasks])
c.openFile(str(proj / "run.py")); spin(100)
i = next(k for k, t in enumerate(c.tabs) if t["name"] == "run.py"); c.edited(i, 0, 0, "y") if hasattr(c, "edited") else None
b.runDefault()
ok("it runs", b.running and b.taskName == "Fake Compile" and b.status == "Running…")
b.run("own:1")
ok("a second task is refused while one runs", any("still running" in s for s in said) and b.taskName == "Fake Compile")
ok("and finishes", wait(lambda: not b.running, 20))
rows = b.lines.rows
ok("its output: the command, each line, the verdict", rows[0]["text"].startswith("$ echo") and rows[0]["kind"] == "command" and [r["text"] for r in rows[1:5]] ==
   ["src/main.c:12:5: error: expected ;", "src/main.c:3:9: warning: unused", "src/Hero.cpp:2:1: error: second", "plain"] and rows[-1]["text"] == b.status, [r["text"] for r in rows])
ok("lines that name a place carry it, plain ones don't", rows[1]["path"].endswith("src/main.c") and rows[1]["line"] == 11 and rows[1]["kind"] == "error" and rows[2]["kind"] == "warning" and rows[4]["path"] == "")
ok("the problems, counted", b.errors == 2 and b.warnings == 1 and [p["name"] for p in b.problems] == ["src/main.c", "src/main.c", "src/Hero.cpp"] and "2 errors, 1 warning" in b.status and b.status.startswith("Failed"), b.status)
b.open(1); spin(200)
ok("clicking a line opens the file at the place", went[-1] == ("main.c", 11, 4) and c.tabs[c.current]["name"] == "main.c", went)
b.open(4); b.open(999); b.openProblem(-1)
ok("a plain line, or one that isn't there, opens nothing", len(went) == 1)
b.step(1); b.step(1); b.step(1); b.step(-1)
ok("F8 walks the errors (not the warnings), round and round, and back", went[1:] == [("main.c", 11, 4), ("Hero.cpp", 1, 0), ("main.c", 11, 4), ("Hero.cpp", 1, 0)], went[1:])
b.run("own:1"); wait(lambda: not b.running, 20)
ok("a task that works: done, the earlier problems gone, run in the project's folder", b.status.startswith("Done in") and b.errors == 0 and b.problems == [] and [r["text"] for r in b.lines.rows[1:4]] == ["one", "two", str(proj)]
   and b.lines.rows[-1]["kind"] == "done", [r["text"] for r in b.lines.rows])
b.run("own:2"); spin(600)
pid = int(b._proc.processId())
kids = subprocess.run(["pgrep", "-g", str(pid)], capture_output=True, text=True).stdout.split()
b.stop()
ok("Stop ends a task, and what it started with it", wait(lambda: not b.running, 10) and b.status.startswith("Stopped after") and len(kids) >= 2
   and wait(lambda: not subprocess.run(["pgrep", "-g", str(pid)], capture_output=True, text=True).stdout.split(), 5), (b.status, kids))
b.run("own:3"); wait(lambda: not b.running, 30)
ok("long output keeps its latest lines", len(b.lines.rows) == hb.OUTPUT_LIMIT and b.lines.rows[-2]["text"] == "7000" and b.lines.rowCount() == hb.OUTPUT_LIMIT, len(b.lines.rows))
b.run("own:4"); wait(lambda: not b.running, 20)
ok("a program that isn't installed: failed, and the shell's own words shown", b.status.startswith("Failed") and "127" in b.status and any("not found" in r["text"] for r in b.lines.rows), b.status)
b.makeDefault("own:1"); b.refresh()
ok("choosing what Build runs is kept for this project", [t["name"] for t in b.tasks if t["default"]] == ["Fine"] and hb.load_config()["default"][str(proj)] == "own:1")
b.makeDefault("nonsense"); b.run("nonsense"); b.clear()
ok("a task that isn't there is ignored; Clear empties the output", [t["name"] for t in b.tasks if t["default"]] == ["Fine"] and b.lines.rows == [] and b.status == "")
ok("Unreal's folder: a wrong one is refused with why, a right one kept", "isn't an Unreal Engine" in b.setUnreal(home) and b.setUnreal(str(ue)) == "" and hb.load_config()["unreal"] == str(ue))
c.openFolder(str(game)); spin(150)
ok("and the Unreal project now has its tasks; Run opens it in the editor", b.tasks[0]["id"] == "ue:editor" and b.unrealRoot == str(ue) and "UnrealEditor" in c.runCommand() and "Shooter.uproject" in c.runCommand(), c.runCommand())
c.openFolder(str(godot)); spin(150)
ok("Run in a Godot project starts the game", c.runCommand() == "godot4 --path .", c.runCommand())
asked = []; c.askUnreal.connect(lambda: asked.append(1))
(Path(home) / "config/huginn/code-build.json").write_text("{}")
c.openFolder(str(bp)); spin(150)
b.run("setup:unreal")
ok("a set-up task asks instead of running", asked == [1] and not b.running, (asked, [t["id"] for t in b.tasks]))
packs = {p["name"]: p for p in b.packs}
ok("the tool packs, each with what it is for", {"Git LFS", "C++ build tools", "Godot 4", "Godot 4 (.NET)", "Shader tools", "Unreal Engine prerequisites"} == set(packs) and all(p["about"] for p in packs.values()))
ok("a pack is ready when its programs are there", hb.pack_ready("nonsense") is True and hb.pack_ready("Godot 4") == hb.flatpak_has("org.godotengine.Godot"))
langs = {x["name"]: x for x in c.languages}
ok("GDScript is ready when Godot is, and C#, GDScript and GLSL can be added", langs["GDScript"]["tools"] and langs["GDScript"]["helper"] == "Godot" and "C#" in hc.LANG_PACKS and "GLSL" in hc.LANG_PACKS)

# ------------------------------------------------------------------------------- real compilers, when they're here
if shutil.which("cmake") and shutil.which("cc"):
    real = Path(home) / "real-c"; real.mkdir()
    (real / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.16)\nproject(demo C)\nadd_executable(demo main.c)\n")
    (real / "main.c").write_text('#include <stdio.h>\nint main(void)\n{\n    int unused;\n    printf("hi\\n")\n    return 0;\n}\n')
    c.openFolder(str(real)); spin(150)
    b.run("cmake:build")
    ok("CMake and a C compiler: the build fails", wait(lambda: not b.running, 180) and b.status.startswith("Failed"), b.status)
    errs = [p for p in b.problems if p["severity"] == 1]
    ok("with the real error at its real place", errs and errs[0]["name"] == "main.c" and errs[0]["line"] in (4, 5) and "expected" in errs[0]["message"], b.problems)
    (real / "main.c").write_text('#include <stdio.h>\nint main(void)\n{\n    printf("hi\\n");\n    return 0;\n}\n')
    b.again()
    ok("fixed, and built again: done, with the program made", wait(lambda: not b.running, 180) and b.status.startswith("Done in") and (real / "build" / "demo").is_file(), b.status)
    spin(300)
    ok("clangd's list is put beside the sources", (real / "compile_commands.json").exists() and (real / "build" / "compile_commands.json").is_file())
else:
    print("(no cmake or C compiler here: the real CMake build is skipped)")
if shutil.which("cargo"):
    rs = Path(home) / "real-rs"; (rs / "src").mkdir(parents=True)
    (rs / "Cargo.toml").write_text('[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n')
    (rs / "src" / "main.rs").write_text('fn main() {\n    let unused = 1;\n    println!("{}", speed);\n}\n')
    c.openFolder(str(rs)); spin(150)
    b.run("cargo:build")
    ok("Cargo: the build fails", wait(lambda: not b.running, 240) and b.status.startswith("Failed"), b.status)
    errs = [p for p in b.problems if p["severity"] == 1]
    ok("with the real error at its real place", errs and errs[0]["name"] == "src/main.rs" and errs[0]["line"] == 2 and "speed" in errs[0]["message"], b.problems)
    (rs / "src" / "main.rs").write_text('fn main() {\n    let unused = 1;\n    println!("hi");\n}\n')
    b.again()
    ok("fixed: done, and the unused variable is a warning at its place", wait(lambda: not b.running, 240) and b.status.startswith("Done in") and b.errors == 0
       and [(p["name"], p["line"], p["severity"]) for p in b.problems][:1] == [("src/main.rs", 1, 2)], (b.status, b.problems))
else:
    print("(no cargo here: the real Cargo build is skipped)")

real_godot = next((p for p in (shutil.which("godot3-server"), shutil.which("godot3")) if p and not p.startswith(str(fake_bin))), None)
if real_godot and "server" in real_godot:
    g3 = Path(home) / "real-godot3"; (g3 / "scripts").mkdir(parents=True)
    (g3 / "project.godot").write_text('config_version=4\n\n[application]\nconfig/name="Demo"\nrun/main_scene="res://main.tscn"\n')
    (g3 / "main.tscn").write_text('[gd_scene load_steps=2 format=2]\n\n[ext_resource path="res://scripts/player.gd" type="Script" id=1]\n\n[node name="Main" type="Node"]\nscript = ExtResource( 1 )\n')
    (g3 / "scripts" / "player.gd").write_text('extends Node\n\nvar speed = 4\n\nfunc _ready():\n\tprint("ready")\n\tprint(speeed)\n')
    c.openFolder(str(g3)); spin(150)
    b.run("godot:check")
    wait(lambda: not b.running, 90) or b.stop()
    wait(lambda: not b.running, 10)
    errs = [(p["name"], p["line"], p["message"]) for p in b.problems if p["severity"] == 1]
    ok("Godot itself (3, from Ubuntu's archive): its script error lands on the script's line", errs and errs[0][:2] == ("scripts/player.gd", 6) and "speeed" in errs[0][2], (b.status, errs, [r["text"] for r in b.lines.rows][:8]))
else:
    print("(no Godot here: the check against the engine's own output is skipped)")

# --------------------------------------------------------------------------- Godot's helper, reached through a port
ok("no one listening: said at once", not tcp.port_open("127.0.0.1", 1))
server = socket.socket(); server.bind(("127.0.0.1", 0)); server.listen(1); port = server.getsockname()[1]
got = []
def serve():
    conn, _ = server.accept()
    got.append(conn.recv(4096)); conn.sendall(b"Content-Length: 2\r\n\r\n{}"); conn.close()
threading.Thread(target=serve, daemon=True).start()
ok("someone listening", tcp.port_open("127.0.0.1", port))
threading.Thread(target=serve, daemon=True).start()
done = subprocess.run([sys.executable, str(KIT / "apps" / "huginn_lsp_tcp.py"), "127.0.0.1", str(port)], input=b"Content-Length: 4\r\n\r\nping", capture_output=True, timeout=20)
ok("the bridge carries both ways and ends when the helper hangs up", got and got[-1].endswith(b"ping") and done.stdout == b"Content-Length: 2\r\n\r\n{}" and done.returncode == 0, (got, done.stdout, done.stderr))
done = subprocess.run([sys.executable, str(KIT / "apps" / "huginn_lsp_tcp.py"), "127.0.0.1", "1"], input=b"", capture_output=True, timeout=20)
ok("nothing there: it ends with 1 and says why", done.returncode == 1 and b"nothing is listening" in done.stderr)
done = subprocess.run([sys.executable, str(KIT / "apps" / "huginn_lsp_tcp.py"), "example.org", "80"], input=b"", capture_output=True, timeout=20)
ok("it only ever talks to this computer", done.returncode == 2)
c.openFolder(str(godot)); spin(100)
(godot / "player.gd").write_text("extends Node\n")
c.openFile(str(godot / "player.gd")); spin(300)
ok("a GDScript file with Godot closed: no helper, a note saying how to get one, and no complaint", c._servers.get("GDScript") is None and "Godot" in c._server_note.get("GDScript", "")
   and not any("helper" in s for s in said), (c._server_note, said[-3:]))

print(f"{passed} passed, {failed} failed")
shutil.rmtree(home, ignore_errors=True)
sys.exit(1 if failed else 0)
