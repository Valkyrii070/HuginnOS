#!/usr/bin/env python3
"""Code, round ten: debugging the game itself. Godot 4's editor is a debug adapter (port 6006 while the project is
open); here a stand-in speaks for it, the way Godot answers. Unreal's editor is run under GDB 14+; here a small C
program stands in for UnrealEditor in a made-up engine folder, and GDB really stops in it.
Usage: code_round10_test.py <kit root>   (not as root)"""
import json, os, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path
KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0:
    sys.exit("not as root")
home = Path(tempfile.mkdtemp(prefix="code10-"))
os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "c"), XDG_DATA_HOME=str(home / "d"), QT_QPA_PLATFORM="offscreen")
sys.path[:0] = [str(KIT / "apps")]
from PySide6.QtCore import QCoreApplication
app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
import huginn_debug as hd
import huginn_build as hb

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
        print("ok  ", name)
    else:
        bad += 1
        print("FAIL", name, extra, flush=True)
def pump(until, secs=20):
    end = time.time() + secs
    while not until() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return until()

# ---------------------------------------------------------------- a Godot project, and Godot's editor stood in for
game = home / "game"
(game / "player").mkdir(parents=True)
(game / "project.godot").write_text('config_version=5\n\n[application]\nrun/main_scene="res://main.tscn"\n')
(game / "main.tscn").write_text("[gd_scene format=3]\n")
(game / "player/player.gd").write_text("extends CharacterBody2D\n\nvar speed = 300\n\nfunc _physics_process(delta):\n\tvelocity.x = speed\n\tmove_and_slide()\n")
check("scenes asked for as Godot names them", hd.godot_scene(game, "main") == "main" and hd.godot_scene(game, "current") == "current"
      and hd.godot_scene(game, str(game / "main.tscn")) == "res://main.tscn")
for bad_scene, why in ((str(home / "elsewhere.tscn"), "outside the project"), (str(game / "player/player.gd"), "not a scene")):
    try:
        hd.godot_scene(game, bad_scene); check(f"a scene {why} is refused", False)
    except ValueError:
        check(f"a scene {why} is refused", True)
try:
    hd.godot_for(game, port=1, reachable=lambda h, p: False); check("Godot's editor not open: says to open it", False)
except ValueError as err:
    check("Godot's editor not open: says to open it (and where the port is set)", "Open the project in Godot's editor" in str(err) and "Debug Adapter" in str(err), str(err))
old = home / "old"; old.mkdir(); (old / "project.godot").write_text("config_version=4\n")
for folder, why in ((old, "Godot 3"), (home, "not Godot")):
    try:
        hd.godot_for(folder, reachable=lambda h, p: True); check(f"{why}: refused, saying why", False)
    except ValueError:
        check(f"{why}: refused, saying why", True)

heard = []
class FakeGodot(threading.Thread):
    """Answers as Godot 4's editor does: capabilities, then initialized; launch kept until configurationDone, then
    the game runs and stops at the first breakpoint; continue runs it to the end."""
    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(); self.sock.bind(("127.0.0.1", 0)); self.sock.listen(1)
        self.port = self.sock.getsockname()[1]; self.seq = 1
    def send(self, conn, msg):
        msg["seq"] = self.seq; self.seq += 1
        body = json.dumps(msg).encode()
        conn.sendall(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    def reply(self, conn, req, body=None, success=True, message=""):
        self.send(conn, {"type": "response", "request_seq": req["seq"], "command": req["command"], "success": success, "body": body or {}, **({"message": message} if message else {})})
    def run(self):
        while True:                      # (Code first checks the port is open: that connection just closes)
            conn, _ = self.sock.accept()
            self.serve(conn)
    def serve(self, conn):
        buf = b""; bps = {}
        while True:
            data = conn.recv(65536)
            if not data:
                return
            buf += data
            while b"\r\n\r\n" in buf:
                head, rest = buf.split(b"\r\n\r\n", 1)
                n = int(head.split(b":")[1])
                if len(rest) < n:
                    break
                req, buf = json.loads(rest[:n]), rest[n:]
                heard.append(req); c = req["command"]; a = req.get("arguments") or {}
                if c == "initialize":
                    self.reply(conn, req, {"supportsConfigurationDoneRequest": True})
                    self.send(conn, {"type": "event", "event": "initialized", "body": {}})
                elif c == "launch":
                    ok_project = a.get("project") == str(game)
                    self.reply(conn, req, success=ok_project, message="" if ok_project else "wrong_path")
                elif c == "setBreakpoints":
                    bps[a["source"]["path"]] = [b["line"] for b in a.get("breakpoints", [])]
                    self.reply(conn, req, {"breakpoints": [{"verified": True, "line": b["line"], "source": a["source"]} for b in a.get("breakpoints", [])]})
                elif c == "configurationDone":
                    self.reply(conn, req)
                    self.send(conn, {"type": "event", "event": "process", "body": {"name": str(game), "startMethod": "launch"}})
                    self.send(conn, {"type": "event", "event": "output", "body": {"category": "stdout", "output": "Godot Engine v4.5 - https://godotengine.org\n"}})
                    self.send(conn, {"type": "event", "event": "stopped", "body": {"reason": "breakpoint", "threadId": 1}})
                elif c == "threads":
                    self.reply(conn, req, {"threads": [{"id": 1, "name": "Main"}]})
                elif c == "stackTrace":
                    path, lines = next(iter(bps.items()), ("", [1]))
                    self.reply(conn, req, {"stackFrames": [{"id": 0, "name": "_physics_process", "line": lines[0], "column": 0, "source": {"name": "player.gd", "path": path}},
                                                            {"id": 1, "name": "_ready", "line": 3, "column": 0, "source": {"name": "main.gd", "path": str(game / "main.gd")}}], "totalFrames": 2})
                elif c == "scopes":
                    self.reply(conn, req, {"scopes": [{"name": "Locals", "variablesReference": 7, "expensive": False}, {"name": "Members", "variablesReference": 8, "expensive": False}]})
                elif c == "variables":
                    rows = {7: [{"name": "delta", "value": "0.016667", "type": "float", "variablesReference": 0}],
                            8: [{"name": "speed", "value": "300", "type": "int", "variablesReference": 0}]}.get(a.get("variablesReference"), [])
                    self.reply(conn, req, {"variables": rows})
                elif c == "evaluate":
                    self.reply(conn, req, {"result": "300", "variablesReference": 0})
                elif c == "continue":
                    self.reply(conn, req, {"allThreadsContinued": True})
                    self.send(conn, {"type": "event", "event": "continued", "body": {"threadId": 1}})
                    self.send(conn, {"type": "event", "event": "terminated", "body": {}})
                elif c == "disconnect":
                    self.reply(conn, req); conn.close(); return
                else:
                    self.reply(conn, req)

fake = FakeGodot(); fake.start()
argv, launch, name = hd.godot_for(game, "main", port=fake.port)
check("Code asks Godot's editor to play the main scene of this project, on this computer", launch["project"] == str(game) and launch["scene"] == "main"
      and launch["platform"] == "host" and name == "Godot" and argv[-2:] == ["127.0.0.1", str(fake.port)])
dbg = hd.Debugger()
script = str(game / "player/player.gd")
dbg.toggle(script, 5)                                    # (lines from 0, as the editor counts them: line 6)
dbg.start(argv, launch, name, str(game), "launch", "the game in Godot")
check("the game stops at the breakpoint in GDScript", pump(lambda: dbg.state == "stopped"), (dbg.state, dbg.console[-3:]))
cmds = [h["command"] for h in heard]
check("…the conversation in Godot's order: initialize, launch, breakpoints, configurationDone", cmds[:4] == ["initialize", "launch", "setBreakpoints", "configurationDone"], cmds)
bp = next(h for h in heard if h["command"] == "setBreakpoints")["arguments"]
check("…breakpoints sent by the file's real path (Godot makes res:// of it)", bp["source"]["path"] == script and [b["line"] for b in bp["breakpoints"]] == [6], bp)
check("…where it stopped: the script's line, the call stack", pump(lambda: dbg.whereFile == script and dbg.whereLine == 5) and [f.get("name") for f in dbg.frames][:2] == ["_physics_process", "_ready"],
      (dbg.whereFile, dbg.whereLine, dbg.frames[:2]))
check("…what Godot printed is in the debug console", pump(lambda: any("Godot Engine" in str(c) for c in dbg.console)))
check("…the variables", pump(lambda: any("delta" in str(r) for r in dbg.variables)), dbg.variables)
dbg.resume()
check("carried on: the game ends, the debugger with it", pump(lambda: dbg.state == "idle"), dbg.state)

# ---------------------------------------------------------------- Unreal: the editor under GDB
engine = home / "UE_5.7"
(engine / "Engine/Binaries/Linux").mkdir(parents=True)
(engine / "Engine/Build/BatchFiles/Linux").mkdir(parents=True)
(engine / "Engine/Build/BatchFiles/Linux/Build.sh").write_text("#!/bin/sh\n")
(engine / "Engine/Extras/GDBPrinters").mkdir(parents=True)
(engine / "Engine/Extras/GDBPrinters/UEPrinters.py").write_text("# Epic's pretty printers (stand-in)\nimport gdb\n")
src = home / "editor.c"
src.write_text('#include <stdio.h>\n#include <string.h>\n\nint tick(int frame) {\n    int speed = frame * 3;\n    return speed;\n}\n\n'
               'int main(int argc, char **argv) {\n    int game = 0;\n    for (int i = 1; i < argc; i++) if (strcmp(argv[i], "-game") == 0) game = 1;\n'
               '    printf("editor: %s game=%d\\n", argc > 1 ? argv[1] : "", game);\n    return tick(game ? 7 : 1) > 100;\n}\n')
built = subprocess.run(["cc", "-g", "-O0", "-o", str(engine / "Engine/Binaries/Linux/UnrealEditor"), str(src)], capture_output=True, text=True)
check("(a stand-in UnrealEditor built with debug information)", built.returncode == 0, built.stderr)
proj = home / "Shooter"; proj.mkdir()
(proj / "Shooter.uproject").write_text(json.dumps({"FileVersion": 3, "EngineAssociation": "5.7", "Modules": [{"Name": "Shooter", "Type": "Runtime"}]}))
os.environ["UE_ROOT"] = str(engine)
check("the engine found for the project", hb.unreal_root(proj / "Shooter.uproject") == str(engine))
argv, args, name, after = hd.unreal_for(proj / "Shooter.uproject", str(engine), game=True)
check("the game on its own: UnrealEditor with the project and -game, in the project's folder",
      args["program"].endswith("Engine/Binaries/Linux/UnrealEditor") and args["args"][:2] == [str(proj / "Shooter.uproject"), "-game"] and args["cwd"] == str(proj) and name == "GDB")
check("…Epic's pretty printers loaded, the engine's own signals not stops", f"source {engine}/Engine/Extras/GDBPrinters/UEPrinters.py" in after and any("SIGUSR1 nostop" in a for a in after), after)
check("the editor: the project without -game", hd.unreal_for(proj / "Shooter.uproject", str(engine))[1]["args"] == [str(proj / "Shooter.uproject")])
try:
    hd.unreal_for(proj / "Shooter.uproject", str(home / "nothing")); check("an engine folder without the editor built: says so", False)
except ValueError as err:
    check("an engine folder without the editor built: says so", "isn't built" in str(err))
if hd.gdb_has_dap():
    dbg2 = hd.Debugger()
    dbg2.toggle(str(src), 5)
    dbg2.start(argv, args, name, str(proj), "launch", "Shooter (the game)", after=after)
    check("GDB stops in the game's code at the breakpoint", pump(lambda: dbg2.state == "stopped" and dbg2.whereLine >= 0, 40) and dbg2.whereLine == 5 and dbg2.whereFile == str(src),
          (dbg2.state, dbg2.whereFile, dbg2.whereLine, dbg2.console[-4:]))
    check("…with its variables", pump(lambda: any("frame" in str(r) for r in dbg2.variables)), dbg2.variables)
    dbg2.resume()
    check("…and runs to the end with -game passed", pump(lambda: dbg2.state == "idle", 30) and any("game=1" in str(c) for c in dbg2.console), dbg2.console[-5:])
else:
    check("GDB 14 or later to try it for real (not here)", False)

print(f"\n{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
