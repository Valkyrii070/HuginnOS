#!/usr/bin/env python3
"""Code, round nine: joining a running program with the debugger; debugging where the project runs (another computer
over SSH, a dev container); dev containers; extensions; notebooks; and workspaces of several folders.
Usage: code_round9_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)
The SSH parts need a test server this user reaches as "testbox" with a key; the container parts use a stand-in
engine written here (a script named docker), so they need neither Docker nor Podman."""
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0:
    sys.exit("not as root: this test writes and removes files")
home = tempfile.mkdtemp(prefix="code9-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/data", XDG_CONFIG_HOME=home + "/config", XDG_CACHE_HOME=home + "/cache", PYDEVD_DISABLE_FILE_VALIDATION="1",
                  QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication
app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
import huginn_code as code
import huginn_container as hc
import huginn_debug as hd
import huginn_extensions as hx
import huginn_notebook as nbk
import huginn_code_more as more
import huginn_remote as hr
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
kids = []
def start(argv, **kw):
    p = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw); kids.append(p); return p

c = code.Code() if hasattr(code, "Code") else code.Backend()
c._demo = False
said = []
c.said.connect(lambda text, bad: said.append(text))
dbg = c.debug
def tab(name): return next((i for i, t in enumerate(c.tabs) if t["name"] == name), -1)
def close_all():
    while c.tabs:
        c.close(0, True)

# ============================================================================== joining a program that is already running
proj = Path(home) / "attach"; proj.mkdir()
(proj / "loop.py").write_text("import time\nn = 0\nwhile True:\n    n += 1\n    time.sleep(0.2)\n")
(proj / "loop.c").write_text("#include <unistd.h>\nint main(void)\n{\n    volatile int n = 0;\n    for (;;) {\n        n++;\n        usleep(200000);\n    }\n}\n")
py = start([sys.executable, str(proj / "loop.py")])
rows = hd.processes(4000)
mine = next((r for r in rows if r["pid"] == py.pid), None)
ok("your running programs are listed, a Python one known as Python", mine is not None and mine["kind"] == "python" and "loop.py" in mine["command"], mine)
ok("this test itself and pid 1 are not offered", all(r["pid"] not in (os.getpid(), 1) for r in rows))
ok("the list is found by name, by command, by number", [r["pid"] for r in c.runningPrograms("loop.py")] == [py.pid] and [r["pid"] for r in c.runningPrograms(str(py.pid))][:1] == [py.pid]
   and c.runningPrograms("no-such-program-xyz") == [])
argv, args, name = hd.attach_for("python", pid=py.pid)
ok("a Python program is joined by debugpy, by its number", name == "debugpy" and args["request"] == "attach" and args["processId"] == py.pid and argv[-2:] == ["-m", "debugpy.adapter"], (argv, args))
argv, args, name = hd.attach_for("python", port=5678, mappings=[("/here/p", "/there/p")])
ok("…or through the port its own debugpy listens on, with where its files are here", args["connect"] == {"host": "127.0.0.1", "port": 5678} and args["pathMappings"] == [{"localRoot": "/here/p", "remoteRoot": "/there/p"}]
   and argv[-2:] == ["127.0.0.1", "5678"] and argv[-3].endswith("huginn_lsp_tcp.py"), (argv, args))
try:
    hd.attach_for("python", host="build-box", port=5678); refused = ""
except ValueError as err:
    refused = str(err)
ok("a debugpy on another computer is not dialled in the clear: SSH is named instead", "SSH" in refused and "build-box" in refused, refused)
argv, args, name = hd.attach_for("native", pid=4242, program="/bin/prog")
ok("anything else is joined by GDB", name == "GDB" and args.get("pid") == 4242 and argv[:1] == ["gdb"], (argv, args))
for bad in (0, 1, -5):
    try:
        hd.attach_for("native", pid=bad); got = "taken"
    except ValueError:
        got = "refused"
    ok(f"pid {bad} is refused", got == "refused")

(proj / ".vscode").mkdir()
(proj / ".vscode" / "launch.json").write_text('''{ "version": "0.2.0", "configurations": [
  { "name": "Join by pick", "type": "debugpy", "request": "attach", "processId": "${command:pickProcess}" },
  { "name": "Join the port", "type": "python", "request": "attach", "connect": { "host": "localhost", "port": 5701 },
    "pathMappings": [ { "localRoot": "${workspaceFolder}", "remoteRoot": "${workspaceFolder}" } ] },
  { "name": "Join C", "type": "cppdbg", "request": "attach", "program": "${workspaceFolder}/loop", "processId": "${command:pickProcess}" },
  { "name": "Old style", "type": "python", "request": "attach", "host": "127.0.0.1", "port": 5702 } ] }''')
found = {l["name"]: l for l in vsc.launches(proj, vsc.variables(proj, "", 0), {})}
ok("launch.json's attach entries are read: pick a process, a port with path mappings, a compiled program", found["Join by pick"]["kind"] == "python-attach" and found["Join by pick"]["launch"]["pick"] is True
   and found["Join the port"]["launch"]["port"] == 5701 and found["Join the port"]["launch"]["mappings"] == [(str(proj), str(proj))]
   and found["Join C"]["kind"] == "gdb-attach" and found["Join C"]["launch"]["program"] == str(proj / "loop") and found["Old style"]["launch"]["port"] == 5702, found)

c.openFolder(str(proj)); spin(200)
asked = []
c.askAttach.connect(asked.append)
c.startLaunch("Join by pick")
ok("an entry that says “pick the process” opens the list of programs", asked == ["Join by pick"] and not dbg.active, asked)

c.openFile(str(proj / "loop.py")); spin(200)
dbg.toggle(str(proj / "loop.py"), 3)
c.attachTo(py.pid, "")
ok("joining a running Python program: it stops at the breakpoint", wait(lambda: dbg.state == "stopped" and dbg.whereLine == 3, 60) and dbg.attached and dbg.whereFile == str(proj / "loop.py"),
   (dbg.state, dbg.whereFile, dbg.whereLine, [r["text"] for r in dbg.output][-3:]))
ok("its variables are there to read", wait(lambda: any(r.get("name") == "n" for r in dbg.variables), 10), [r.get("name") for r in dbg.variables][:8])
dbg.stop(); spin(600)
ok("detaching leaves it running, and says so", py.poll() is None and not dbg.active and any("still running" in r["text"] for r in dbg.output), [r["text"] for r in dbg.output][-2:])
ok("a program that has gone can't be joined", (py.kill(), py.wait(), c.attachTo(py.pid, ""), any("isn't running" in s for s in said[-2:]))[-1] and not dbg.active, said[-2:])

port = start([sys.executable, "-m", "debugpy", "--listen", "127.0.0.1:5701", "--wait-for-client", str(proj / "loop.py")], cwd=str(proj)); time.sleep(4)
c.startLaunch("Join the port")
ok("joining through a port: the program waiting for a debugger starts and stops at the breakpoint", wait(lambda: dbg.state == "stopped" and dbg.whereLine == 3, 40) and dbg.attached, (dbg.state, dbg.whereLine, [r["text"] for r in dbg.output][-3:]))
dbg.stop(); spin(500)
ok("detached, it runs on", port.poll() is None)
port.kill()

if shutil.which("gcc") and hd.gdb_has_dap():
    subprocess.run(["gcc", "-g", "-O0", "-o", str(proj / "loop"), str(proj / "loop.c")], check=True)
    nat = start([str(proj / "loop")]); time.sleep(0.5)
    ok("a compiled program is listed as one", next((r["kind"] for r in hd.processes(4000) if r["pid"] == nat.pid), "") == "native")
    dbg.set_all({}); dbg.toggle(str(proj / "loop.c"), 5)
    c.attachTo(nat.pid, "")
    ok("joining a running compiled program: GDB lets it go on, then it stops at the breakpoint", wait(lambda: dbg.state == "stopped" and dbg.whereLine == 5, 40) and dbg.attached and dbg.whereFile == str(proj / "loop.c"),
       (dbg.state, dbg.whereFile, dbg.whereLine, dbg.reason, [r["text"] for r in dbg.output][-3:]))
    dbg.stop(); spin(600)
    ok("detached, it runs on", nat.poll() is None and not dbg.active)
    nat.kill()
else:
    print("(no gcc or GDB here: joining a compiled program is skipped)")
dbg.set_all({}); close_all()

# ==================================================================== debugging where the project runs: paths there and back
RM = hr.parse_target("astrid@box:/srv/game"); MT = Path(home) / "mnt"
ok("a debugger on the other computer is run by ssh, in the folder there, never stopping to ask", hr.adapter_argv(RM, ["gdb", "-q", "-i", "dap"], "/srv/game/build")[-1] == "cd /srv/game/build && exec gdb -q -i dap"
   and "BatchMode=yes" in hr.adapter_argv(RM, ["gdb"]) and hr.adapter_argv(RM, ["gdb"])[-2] == "astrid@box" and hr.adapter_argv(RM, ["gdb"])[0] == "ssh")
ok("an argument with a space or a quote stays one argument there", hr.adapter_argv(RM, ["python3", "it's a b.py"])[-1].endswith("exec python3 'it'\"'\"'s a b.py'"), hr.adapter_argv(RM, ["python3", "it's a b.py"])[-1])

reach = shutil.which("ssh") and shutil.which("sshfs") and subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "testbox", "true"], capture_output=True).returncode == 0
if reach:
    remote = hr.parse_target("testbox:r9-proj"); mount = hr.mount_point(remote)
    subprocess.run(["ssh", "-o", "BatchMode=yes", "testbox", "rm -rf r9-proj && mkdir -p r9-proj && printf 'def twice(n):\\n    m = n * 2\\n    return m\\n\\nprint(twice(21))\\n' > r9-proj/calc.py && "
                    "printf '#include <stdio.h>\\nint main(void)\\n{\\n    int n = 21;\\n    n = n * 2;\\n    printf(\"%%d\\\\n\", n);\\n    return 0;\\n}\\n' > r9-proj/calc.c && gcc -g -O0 -o r9-proj/calc r9-proj/calc.c"],
                   capture_output=True, timeout=60)
    if hr.is_mounted(mount):
        subprocess.run(hr.unmount_command(mount), capture_output=True)
    done = subprocess.run(["bash", "-c", hr.mount_command(remote, mount)], capture_output=True, text=True, timeout=60)
    ok("a real SSH server: the folder mounts", done.returncode == 0 and hr.is_mounted(mount), (done.returncode, done.stderr[:200]))
    ok("Code opens it", c.remoteConnect("testbox:r9-proj") == "" and str(c._root) == str(mount) and c._place()[0] is hr)
    there, here = c._place_paths()
    far = there(str(mount / "calc.py"))
    ok("a file here is named as it is there (a folder named from the home folder gets the home's full path)", far.startswith("/") and far.endswith("/r9-proj/calc.py") and here(far) == str(mount / "calc.py")
       and here("/usr/lib/python3/x.py") == "", (far, here(far)))
    c.openFile(str(mount / "calc.py")); spin(300)
    dbg.toggle(str(mount / "calc.py"), 1)
    c.startDebug("")
    ok("F5 on a Python file there: debugpy runs on that computer and stops at the breakpoint, shown in the file here",
       wait(lambda: dbg.state == "stopped" and dbg.whereLine == 1, 60) and dbg.whereFile == str(mount / "calc.py") and "testbox" in dbg.output[0]["text"],
       (dbg.state, dbg.reason, dbg.frames, dbg.whereFile, dbg.whereLine, [r["text"] for r in dbg.output][-4:], said[-2:]))
    ok("its variables come back", wait(lambda: any(r.get("name") == "n" and "21" in str(r.get("value")) for r in dbg.variables), 10), dbg.variables[:4])
    dbg.stepOver()
    ok("stepping works there", wait(lambda: dbg.state == "stopped" and dbg.whereLine == 2, 20), (dbg.state, dbg.whereLine))
    dbg.resume()
    ok("it runs to the end and its output is shown here", wait(lambda: not dbg.active, 30) and any("42" in r["text"] for r in dbg.output), [r["text"] for r in dbg.output][-4:])
    dbg.set_all({})
    c.openFile(str(mount / "calc.c")); spin(300)
    dbg.toggle(str(mount / "calc.c"), 4)
    c.startDebug("calc")
    ok("F5 on a C file there: GDB runs on that computer, on the program built there, and stops in the file here",
       wait(lambda: dbg.state == "stopped" and dbg.whereLine == 4, 60) and dbg.whereFile == str(mount / "calc.c"),
       (dbg.state, dbg.whereFile, dbg.whereLine, [r["text"] for r in dbg.output][-4:], said[-2:]))
    ok("…with its variables", wait(lambda: any(r.get("name") == "n" and "21" in str(r.get("value")) for r in dbg.variables), 10), dbg.variables[:4])
    dbg.stop(); spin(500); dbg.set_all({})
    subprocess.run(["ssh", "-o", "BatchMode=yes", "testbox", "true"], capture_output=True)
    close_all(); c.remoteDisconnect(); spin(300)
    ok("disconnecting still lets the mount go", c._root is None and not hr.is_mounted(mount), said[-2:])
else:
    print("(no test SSH server here: debugging on another computer for real is skipped)")

# ======================================================================================================= dev containers
game = Path(home) / "Sky Game"; (game / ".devcontainer").mkdir(parents=True); (game / "src").mkdir()
WS = home + "/ws/sky"                                              # (the stand-in engine makes this a link to the folder, as a real one mounts it)
(game / ".devcontainer" / "devcontainer.json").write_text("""{
    // the studio's build box
    "name": "Sky build box",
    "build": { "dockerfile": "Dockerfile", "context": "..", "args": { "VARIANT": "noble", "bad name": "x" }, "target": "dev" },
    "workspaceFolder": "%s",
    "remoteUser": "dev",
    "containerEnv": { "SKY": "1", "WHERE": "${containerWorkspaceFolder}/out", "9bad": "no" },
    "forwardPorts": [8080, "db:5432", 8080, 99999],
    "mounts": ["source=sky-cache,target=/cache,type=volume", { "type": "bind", "source": "${localWorkspaceFolder}/assets", "target": "/assets" }],
    "runArgs": ["--cap-add=SYS_PTRACE"],
    "postCreateCommand": "make deps",
    "postStartCommand": ["echo", "it's up"],
    "features": { "ghcr.io/devcontainers/features/node:1": {} },
}""" % WS)
(game / ".devcontainer" / "Dockerfile").write_text("FROM ubuntu:26.04\n")
cfg = hc.read(game)
ok("devcontainer.json is read, comments and all", cfg["title"] == "Sky build box" and cfg["workspace"] == WS and cfg["user"] == "dev" and cfg["dockerfile"] == str(game / ".devcontainer" / "Dockerfile")
   and cfg["context"] == str(game) and cfg["args"] == {"VARIANT": "noble"} and cfg["target"] == "dev", cfg)
ok("its variables are filled in; names that aren't names are dropped; ports are numbers, once each", cfg["env"] == {"SKY": "1", "WHERE": WS + "/out"} and cfg["ports"] == [8080, 5432]
   and cfg["mounts"] == ["source=sky-cache,target=/cache,type=volume", f"type=bind,source={game}/assets,target=/assets"], (cfg["env"], cfg["ports"], cfg["mounts"]))
ok("its commands: a line stays a line, a list becomes one quoted line", cfg["created"] == ["make deps"] and cfg["started"] == ["echo 'it'\"'\"'s up'"], (cfg["created"], cfg["started"]))
asks = hc.asks(cfg)
ok("before anything starts, what it will do is said in words", asks[0] == "Build an image from Dockerfile" and any("port" in a and "8080, 5432" in a for a in asks) and any(a == "Run inside it, once: make deps" for a in asks)
   and any("--cap-add=SYS_PTRACE" in a for a in asks) and any(a.startswith("NOT done by Code") and "node:1" in a for a in asks), asks)
name = hc.name_for(game)
ok("the container is named for the folder, and two folders of one name differ", name.startswith("huginn-sky-game-") and hc.name_for("/a/Sky Game") != hc.name_for("/b/Sky Game") and len(name) < 60, name)
B = hc.build_command("docker", cfg); R_ = hc.run_command("docker", cfg)
ok("the image is built from its Dockerfile, with its arguments and target", B[:4] == ["docker", "build", "-t", name + "-image"] and "VARIANT=noble" in B and B[B.index("--target") + 1] == "dev" and B[-1] == str(game), B)
ok("the container shares the folder, opens its ports on this computer only, and is kept alive", f"{game}:{WS}" in R_ and "127.0.0.1:8080:8080" in R_ and "127.0.0.1:5432:5432" in R_ and "SKY=1" in R_
   and R_[R_.index("--name") + 1] == name and "--cap-add=SYS_PTRACE" in R_ and R_[R_.index("--entrypoint") + 1] == "/bin/sh" and "--privileged" not in R_ and "-d" in R_, R_)
ok("Podman keeps your files your own; run by root it has no such mode and isn't asked for it", "--userns=keep-id" in hc.run_command("podman", cfg) and "--userns=keep-id" not in R_
   and "--userns=keep-id" not in hc.run_command("podman", cfg, rootless=False))
box = hc.where("docker", cfg)
ok("a command inside it: as its user, in its folder, this computer's paths turned into its own", hc.wrap(box, f"python3 '{game}/src/a.py' && ls {game}", mount=game)
   == f"docker exec -u dev -w {WS} {name} sh -c " + __import__("shlex").quote(f"python3 '{WS}/src/a.py' && ls {WS}"), hc.wrap(box, f"python3 '{game}/src/a.py' && ls {game}", mount=game))
ok("with a terminal it is interactive", hc.wrap(box, "make", tty=True, mount=game).startswith("docker exec -it -u dev"))
ok("paths go in and come back; one outside the shared folder has no place here", hc.to_remote(box, game, str(game / "src" / "a.py")) == WS + "/src/a.py" and hc.to_local(box, game, WS + "/src/a.py") == str(game / "src" / "a.py")
   and hc.to_local(box, game, WS) == str(game) and hc.to_local(box, game, "/usr/include/stdio.h") == "" and hc.to_local(box, game, WS + "x/a") == "")
ok("the debugger's adapter is run inside, its talk carried by exec", hc.adapter_argv(box, ["gdb", "-q", "-i", "dap"], WS + "/build") == ["docker", "exec", "-i", "-u", "dev", "-w", WS + "/build", name, "gdb", "-q", "-i", "dap"])
lines = hc.start_lines("docker", cfg, exists=False)[0]
ok("a first start: build, run, the once-only commands, the every-start ones", lines.index("docker build") < lines.index("docker run") < lines.index("make deps") < lines.index("s up'") and lines.endswith("echo 'The container is ready.'"), lines)
again = hc.start_lines("docker", cfg, exists=True)[0]
ok("a later start: only start, and the every-start commands", again.startswith(f"docker start {name} && ") and "docker build" not in again and "make deps" not in again and "s up'" in again, again)
def refuses(text):
    d = Path(tempfile.mkdtemp(prefix="dc-", dir=home)); (d / ".devcontainer.json").write_text(text)
    try:
        hc.read(d); return ""
    except ValueError as err:
        return str(err)
ok("Docker Compose projects are declined in words", "Compose" in refuses('{"dockerComposeFile": "compose.yml", "service": "app"}'))
ok("no image and no Dockerfile; an image name with a space or an option in it; a relative workspace; a strange user: all refused",
   "neither" in refuses("{}") and "image name" in refuses('{"image": "ubuntu --privileged"}') and "image name" in refuses('{"image": "-v/:/host"}')
   and "full path" in refuses('{"image": "ubuntu", "workspaceFolder": "rel"}') and "user" in refuses('{"image": "ubuntu", "remoteUser": "a b"}') and "couldn't be read" in refuses("[1]"))
simple = Path(home) / "simple"; simple.mkdir(); (simple / ".devcontainer.json").write_text('{"image": "mcr.microsoft.com/devcontainers/base:ubuntu", "privileged": true}')
sc = hc.read(simple)
ok("the short form: an image, and the usual workspace folder", sc["image"].endswith("base:ubuntu") and sc["workspace"] == "/workspaces/simple" and hc.build_command("docker", sc) == [] and hc.run_command("docker", sc)[-3] == sc["image"])
ok("a privileged container is said loudly", any("PRIVILEGED" in a for a in hc.asks(sc)) and "--privileged" in hc.run_command("docker", sc))
ok("a project without one has none", hc.find_config(proj) is None and c.container == {"has": False})

# ---- a stand-in engine: it keeps one "container" (a state file), and exec runs the command on this computer in the linked folder
bindir = Path(home) / "bin"; bindir.mkdir()
(bindir / "docker").write_text(r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
S = Path(os.environ["FAKE_ENGINE"]); log = S / "log"; a = sys.argv[1:]
with open(log, "a") as f: f.write(json.dumps(a) + "\n")
def state(): return (S / "state").read_text() if (S / "state").exists() else ""
if a[0] == "inspect": sys.exit(print("true" if state() == "running" else "false") or 0) if state() else sys.exit(1)
if a[0] == "build": print("built"); sys.exit(0)
if a[0] == "run":
    v = a[a.index("-v") + 1]; here, there = v.split(":"); Path(there).parent.mkdir(parents=True, exist_ok=True)
    if not os.path.lexists(there): os.symlink(here, there)
    (S / "state").write_text("running"); print("0123abcd"); sys.exit(0)
if a[0] == "start": (S / "state").write_text("running"); sys.exit(0)
if a[0] == "stop": (S / "state").write_text("stopped"); sys.exit(0)
if a[0] == "rm": (S / "state").unlink(missing_ok=True); sys.exit(0)
if a[0] == "exec":
    if state() != "running": sys.exit("Error: container is not running")
    i, cwd = 1, None
    while a[i].startswith("-"):
        if a[i] in ("-w", "-u"):
            if a[i] == "-w": cwd = a[i + 1]
            i += 2
        else: i += 1
    os.chdir(cwd); os.environ["IN_BOX"] = "1"; os.execvp(a[i + 1], a[i + 1:])
sys.exit(2)
""")
(bindir / "docker").chmod(0o755)
fake = Path(home) / "engine"; fake.mkdir()
os.environ["FAKE_ENGINE"] = str(fake); os.environ["PATH"] = str(bindir) + os.pathsep + os.environ["PATH"]
log = lambda: [json.loads(l) for l in (fake / "log").read_text().splitlines()] if (fake / "log").exists() else []      # noqa: E731
(game / "src" / "calc.py").write_text("import os\ndef twice(n):\n    m = n * 2\n    return m\n\nprint(twice(21), os.environ.get('IN_BOX'))\n")
(game / "Makefile").write_text("all:\n\tcc -o prog src/main.c\n\ndeps:\n\t@echo deps done\n")
(game / "src" / "main.c").write_text('#include <stdio.h>\nint main(void)\n{\n    printf("hi\\n")\n    return 0;\n}\n')
close_all(); c.openFolder(str(game)); spin(200)
box_now = c.container
ok("opening the project: it has a container, not running, and says what starting it would do", box_now["has"] and not box_now["running"] and box_now["title"] == "Sky build box" and box_now["engine"] == "docker"
   and box_now["asks"] == asks and box_now["problem"] == "" and c._place() == (None, None, None), box_now)
class Term:                                                        # Code's terminal, standing in: what is typed into it is run by a shell
    def __init__(self): self.typed = []
    def _send(self, data):
        self.typed.append(data.decode()); subprocess.run(["bash", "-c", data.decode().strip()], capture_output=True, cwd=str(game), stdin=subprocess.DEVNULL, timeout=60)
term = Term(); c._get_term = lambda: term
ok("starting it is under way", c.containerOpen() == "" and c.container["starting"] is True)
ok("the lines went to the terminal, and when the engine says it runs, Code works inside it", wait(lambda: c.container["running"], 20) and not c.container["starting"] and c._place()[0] is hc
   and any("Working in the container" in s_ for s_ in said[-2:]), (term.typed, said[-2:]))
ran = log()
ok("the engine was asked to build, run, then run the project's own commands inside", [r[0] for r in ran if r[0] in ("build", "run", "exec")] == ["build", "run", "exec", "exec"]
   and ran[[r[0] for r in ran].index("exec")][-3:] == ["sh", "-c", "make deps"], [r[:3] for r in ran])
b = c.build
b.refresh(); b.run("make"); wait(lambda: not b.running, 60)
ok("Build runs inside the container, and its error opens the file here", b.status.startswith("Failed") and [(p["name"], p["line"]) for p in b.problems if p["severity"] == 1][:1] == [("src/main.c", 3)]
   and b.lines.rows[0]["text"].endswith("(in Sky build box)") and any(r[0] == "exec" and r[-1].startswith("make") for r in log()), (b.status, b.problems, [r["text"] for r in b.lines.rows][:5]))
c.openFile(str(game / "src" / "calc.py")); spin(300)
k = len(term.typed); c.run(f"python3 '{game}/src/calc.py'"); spin(300)
ok("Run is typed as a command inside the container, with the file's path as it is in there", len(term.typed) > k and term.typed[-1].startswith("docker exec -it -u dev -w " + WS) and WS + "/src/calc.py" in term.typed[-1]
   and str(game) not in term.typed[-1], term.typed[k:])
dbg.set_all({}); dbg.toggle(str(game / "src" / "calc.py"), 2)
c.startDebug("")
ok("F5: debugpy runs inside the container and stops at the breakpoint, shown in the file here", wait(lambda: dbg.state == "stopped" and dbg.whereLine == 2, 60) and dbg.whereFile == str(game / "src" / "calc.py")
   and "in the container" in dbg.output[0]["text"], (dbg.state, dbg.whereFile, dbg.whereLine, [r["text"] for r in dbg.output][-4:], said[-2:]))
adapter = next((r for r in log() if r[0] == "exec" and "debugpy.adapter" in r), None)
ok("…its adapter was started by the engine's exec, and the program was named by its path inside", adapter is not None and adapter[:2] == ["exec", "-i"] and dbg._launch[1]["program"] == WS + "/src/calc.py", adapter)
dbg.resume()
ok("it ran in there: its output says so", wait(lambda: not dbg.active, 30) and "42 1" in "".join(r["text"] for r in dbg.output), [r["text"] for r in dbg.output][-4:])
k = len(term.typed); c.containerShell()
ok("a shell inside is one command away", len(term.typed) > k and term.typed[-1].startswith("docker exec -it -u dev"))
close_all(); c.closeFolder(); c.openFolder(str(game)); spin(200)
ok("opened again later, the running container is found again", c.container["running"] and c._place()[0] is hc)
c.containerStop(False)
ok("stopping it: Code works here again, and the engine was told", c._place() == (None, None, None) and wait(lambda: (fake / "state").read_text() == "stopped", 10) and wait(lambda: any("was stopped" in s_ for s_ in said[-2:]), 5), said[-2:])
ok("a stopped container is started again, not built again", c.containerOpen() == "" and wait(lambda: c.container["running"], 20) and term.typed[-1].startswith("docker start "), term.typed[-1][:80])
c.containerStop(True)
ok("stop and remove: it is gone", wait(lambda: not (fake / "state").exists(), 10) and not c.container["running"])
(game / ".devcontainer" / "devcontainer.json").write_text('{"dockerComposeFile": "c.yml"}'); spin(50)
ok("an edited devcontainer.json is read again; what Code can't start says why", "Compose" in c.container["problem"] and "Compose" in c.containerOpen())
os.environ["PATH"] = os.pathsep.join(p_ for p_ in os.environ["PATH"].split(os.pathsep) if p_ != str(bindir))
(game / ".devcontainer" / "devcontainer.json").write_text('{"image": "ubuntu:26.04"}'); spin(50)
if not hc.engine():
    ok("with neither Docker nor Podman installed, it says what to install", "Podman" in c.container["problem"] and "Podman" in c.containerOpen(), c.container)
close_all(); c.closeFolder()

# =========================================================================================================== extensions
import zipfile
def vsix(name, manifest, files=None, top="extension/"):
    path = Path(home) / name
    with zipfile.ZipFile(path, "w") as z:
        if manifest is not None:
            z.writestr(top + "package.json", manifest if isinstance(manifest, str) else json.dumps(manifest))
        for rel, text in (files or {}).items():
            z.writestr(rel if rel.startswith("/") or rel.startswith("..") else top + rel, text)
    return str(path)
NIGHT = {"name": "Night Owl", "type": "dark", "colors": {"editor.background": "#011627", "editor.foreground": "#d6deeb"},
         "tokenColors": [{"scope": "comment", "settings": {"foreground": "#637777"}}, {"scope": "keyword", "settings": {"foreground": "#c792ea"}}]}
pack = vsix("owl.vsix", {"name": "night-owl", "publisher": "Sarah", "displayName": "Night Owl", "version": "2.1.0", "description": "A theme for the night owls.", "main": "./out/extension.js",
                         "contributes": {"themes": [{"label": "Night Owl", "uiTheme": "vs-dark", "path": "./themes/night.json"}, {"label": "Light Owl", "uiTheme": "vs", "path": "./themes/light.json"},
                                                    {"label": "Gone", "path": "./themes/none.json"}, {"label": "Escape", "path": "../../../../etc/passwd"}],
                                         "snippets": [{"language": "python", "path": "snippets/py.json"}, {"language": "klingon", "path": "snippets/kl.json"}],
                                         "languages": [{"id": "python", "extensions": [".pyowl", ".py", "bad ending"], "filenames": ["OWLFILE"]}, {"id": "klingon", "extensions": [".kl"]}],
                                         "grammars": [{"language": "python", "path": "x.tmLanguage.json"}],
                                         "keybindings": [{"command": "workbench.action.files.save", "key": "ctrl+alt+s"}, {"command": "owl.hoot", "key": "ctrl+h"}]}},
            {"themes/night.json": "// a theme\n" + json.dumps(NIGHT), "themes/light.json": json.dumps(dict(NIGHT, name="Light Owl", type="light", colors={"editor.background": "#fbfbfb", "editor.foreground": "#403f53"})),
             "snippets/py.json": json.dumps({"Owl main": {"prefix": "owlmain", "body": ["def main():", "\t$0"], "description": "A main"}}), "snippets/kl.json": "{}",
             "out/extension.js": "require('child_process').exec('touch " + home + "/RAN')", "node_modules/big/index.js": "x" * 5000})
row = hx.install(pack)
there = hx.DIR / "sarah.night-owl"
ok("a .vsix installs under its maker's and its own name", row["id"] == "sarah.night-owl" and row["name"] == "Night Owl" and row["version"] == "2.1.0" and there.is_dir(), row)
ok("what Code takes and what it leaves are both said", row["takes"] == "2 colour themes, 2 snippet files, 2 file types, 2 key bindings" and "its program" in row["leaves"] and "syntax colouring" in row["leaves"], row)
ok("only its data is unpacked: no program, nothing else from the package, and nothing was run", sorted(str(f.relative_to(there)) for f in there.rglob("*") if f.is_file())
   == ["package.json", "snippets/kl.json", "snippets/py.json", "themes/light.json", "themes/night.json"] and not (Path(home) / "RAN").exists(), sorted(str(f.relative_to(there)) for f in there.rglob("*")))
got = hx.gather(code.LANGS)
ok("its themes that are really there are offered, light and dark known; one pointing outside the package is not", [(t["label"], t["dark"]) for t in got["themes"]] == [("Night Owl", True), ("Light Owl", False)], got["themes"])
ok("its snippets are for the language it names; a language Code doesn't have is passed over", got["snippets"] == {"Python": {"owlmain": ("A main", "def main():\n\t$0")}}, got["snippets"])
ok("new endings for a language Code knows; not ones it already has, nor ones that aren't endings", got["types"] == [("*.pyowl", "Python"), ("OWLFILE", "Python")], got["types"])
ok("key bindings for commands Code has", got["keys"] == {"Save": "Ctrl+Alt+S"}, got["keys"])
def refused(path):
    try:
        hx.install(path); return ""
    except ValueError as err:
        return str(err)
ok("a package that is only a program is refused, and why is said", "only a program" in refused(vsix("prog.vsix", {"name": "copilot", "publisher": "x", "main": "./x.js", "contributes": {"commands": [{"command": "a.b", "title": "T"}]}})))
ok("not a zip; a zip with no package.json; one that names no name; a file that isn't there", "isn't an extension package" in refused(str(proj / "loop.py")) and "no package.json" in refused(vsix("empty.vsix", None, {"a.txt": "a"}))
   and "who made it" in refused(vsix("anon.vsix", {"publisher": "../..", "name": "x", "contributes": {"themes": [{"path": "a.json"}]}})) and "isn't there" in refused(home + "/none.vsix"))
evil = vsix("evil.vsix", {"name": "evil", "publisher": "bad", "contributes": {"themes": [{"label": "E", "path": "../../../evil-out.json"}, {"label": "A", "path": "/etc/hostname"}, {"label": "Ok", "path": "ok.json"}]}},
            {"../../../evil-out.json": "{}", "/etc/hostname": "x", "ok.json": json.dumps(NIGHT)})
hx.install(evil)
ok("a package with paths that climb out writes nothing outside its own folder", not (hx.DIR.parent / "evil-out.json").exists() and not (hx.DIR.parent.parent / "evil-out.json").exists()
   and sorted(f.name for f in (hx.DIR / "bad.evil").rglob("*") if f.is_file()) == ["ok.json", "package.json"], sorted(str(f) for f in (hx.DIR / "bad.evil").rglob("*")))
ok("removing takes only that extension's folder; a name that isn't one removes nothing", hx.remove("bad.evil") and not (hx.DIR / "bad.evil").exists() and there.is_dir()
   and not hx.remove("../sarah.night-owl") and not hx.remove("") and not hx.remove("sarah.night-owl/../..") and there.is_dir())

# ---- in Code
ok("Code lists it, with its themes", [e["id"] for e in c.extensions] == ["sarah.night-owl"] and c.extensions[0]["on"] is True and "manifest" not in c.extensions[0])
c._ext_changed()
ok("its snippet is offered in a Python file, its key binding is in force, its file ending is Python", more.EXTRA_SNIPPETS.get("Python", {}).get("owlmain") == ("A main", "def main():\n\t$0")
   and c.keys.get("Save") == "Ctrl+Alt+S" and code.language_of("/x/nest.pyowl") == "Python" and code.language_of("/x/OWLFILE") == "Python", (c.keys, code.ASSOCIATIONS))
c.setKey("Save", "Ctrl+Shift+S")
ok("your own shortcut lies over an extension's", c.keys.get("Save") == "Ctrl+Shift+S")
c.resetKey("Save")
ok("its theme is put on by name", c.useExtensionTheme("sarah.night-owl", "Night Owl") == "" and c.theme["name"] == "Night Owl" and c.theme["paper"].lower() == "#011627" and c.theme["ext"] == "sarah.night-owl", c.theme)
ok("a theme that isn't there says so", "isn't installed" in c.useExtensionTheme("sarah.night-owl", "Nope"))
c.setExtensionOn("sarah.night-owl", False)
ok("switched off: listed still, but its snippets, keys and endings are gone", c.extensions[0]["on"] is False and "owlmain" not in more.EXTRA_SNIPPETS.get("Python", {}) and "Save" not in c.keys
   and code.language_of("/x/nest.pyowl") != "Python" and c.extensionThemes == [])
c.setExtensionOn("sarah.night-owl", True)
ok("switched on again, they are back", "owlmain" in more.EXTRA_SNIPPETS.get("Python", {}) and len(c.extensionThemes) == 2)
ok("installing from the window: a message in words either way", c.installExtension(pack).startswith("Installed “Night Owl”: 2 colour themes") and "only a program" in c.installExtension(home + "/prog.vsix") and c.installExtension("  ") == "")
c.removeExtension("sarah.night-owl")
ok("removed: gone from the list, and the theme it gave is taken off", c.extensions == [] and c.theme == {} and not there.exists(), (c.extensions, c.theme))

# ---- Code's own extensions: a folder, and commands that are lines for the terminal
own = Path(home) / "my-ext"; own.mkdir()
(own / "package.json").write_text(json.dumps({"name": "studio-tools", "publisher": "astrid", "displayName": "Studio Tools", "contributes": {
    "huginnCommands": [{"title": "Studio: Count Lines", "run": "wc -l ${file}"}, {"title": "Studio: Ask", "run": "echo ${input:what}"}, {"title": "", "run": "x"}, {"title": "No run"}]}}))
ok("a folder with a package.json installs too, and its commands are counted", c.installExtension(str(own)).startswith("Installed “Studio Tools”: 2 commands"), c.installExtension(str(own)))
ok("its commands are offered", [x["title"] for x in c.extensionCommands] == ["Studio: Count Lines", "Studio: Ask"] and c.extensionCommands[0]["from"] == "Studio Tools")
odd = Path(home) / "odd dir"; odd.mkdir(); (odd / "it's; rm -rf ~.py").write_text("x = 1\n")
close_all(); c.openFolder(str(odd)); c.openFile(str(odd / "it's; rm -rf ~.py")); spin(200)
term2 = Term(); term2._send = lambda data: term2.typed.append(data.decode()); c._get_term = lambda: term2
c.runExtensionCommand(0); spin(100)
ok("picked, its line is typed into the terminal with the file filled in as ONE word, whatever its name", term2.typed and term2.typed[-1] == "wc -l " + __import__("shlex").quote(str(odd / "it's; rm -rf ~.py")) + "\r", term2.typed[-2:])
k = len(said); n_typed = len(term2.typed); c.runExtensionCommand(1); c.runExtensionCommand(99)
ok("a command asking what Code can't answer isn't run, and says so", len(term2.typed) == n_typed and any("input:what" in s_ for s_ in said[k:]), said[k:])
c.removeExtension("astrid.studio-tools"); close_all(); c.closeFolder()

# ---- the Open VSX registry, standing in on this computer
import http.server, threading
class Registry(http.server.BaseHTTPRequestHandler):
    seen = []
    def log_message(self, *a): pass
    def do_GET(self):
        Registry.seen.append(self.path)
        base = f"http://127.0.0.1:{self.server.server_port}"
        if self.path.startswith("/api/-/search"):
            body = json.dumps({"extensions": [{"namespace": "sarah", "name": "night-owl", "displayName": "Night Owl", "description": "For the night owls", "version": "2.1.0", "downloadCount": 12345},
                                              {"namespace": "../x", "name": "bad"}, {"namespace": "ok", "name": "minimal"}, "junk"]}).encode()
        elif self.path == "/api/sarah/night-owl":
            body = json.dumps({"files": {"download": base + "/files/owl.vsix"}}).encode()
        elif self.path == "/api/else/where":
            body = json.dumps({"files": {"download": "http://example.invalid/x.vsix"}}).encode()
        elif self.path == "/api/no/package":
            body = b"{}"
        elif self.path == "/files/owl.vsix":
            body = Path(pack).read_bytes()
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Registry); threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["HUGINN_OPENVSX"] = f"http://127.0.0.1:{srv.server_port}"
for proxy in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(proxy, None)
rows = hx.search("night owl")
ok("searching the registry: its answer as rows, odd ones dropped", [(r["namespace"], r["name"], r["downloads"]) for r in rows] == [("sarah", "night-owl", 12345), ("ok", "minimal", 0)] and "query=night+owl" in Registry.seen[0], (rows, Registry.seen))
got_rows = []
c.extensionsFound.connect(lambda r, why: got_rows.append((r, why)))
c.searchExtensions("owl")
ok("…and from the window, without holding it up", wait(lambda: got_rows, 10) and got_rows[0][1] == "" and got_rows[0][0][0]["title"] == "Night Owl", got_rows)
k = len(said); c.fetchExtension("sarah", "night-owl")
ok("an extension is fetched and its data part installed", wait(lambda: any(s_.startswith("Installed “Night Owl”") for s_ in said[k:]), 20) and [e["id"] for e in c.extensions] == ["sarah.night-owl"] and len(c.extensionThemes) == 2, said[k:])
ok("the fetched package itself isn't kept", not list((Path(home) / "cache" / "huginn" / "code-extensions").glob("*.vsix")))
def fetch_fails(ns, name):
    try:
        hx.fetch(ns, name); return ""
    except ValueError as err:
        return str(err)
ok("a package offered from somewhere that isn't the registry is not fetched", "isn't the Open VSX registry" in fetch_fails("else", "where"))
ok("no package, a name that isn't one, a registry that isn't answering: each says so", "no package" in fetch_fails("no", "package") and "isn't an extension's name" in fetch_fails("../..", "x")
   and "couldn't be reached" in fetch_fails("not", "there"))
srv.shutdown(); os.environ["HUGINN_OPENVSX"] = "http://127.0.0.1:9"
got_rows.clear(); c.searchExtensions("x")
ok("with no network the window is told why, in words", wait(lambda: got_rows, 15) and got_rows[0][0] == [] and "couldn't be reached" in got_rows[0][1], got_rows)
del os.environ["HUGINN_OPENVSX"]
ok("only the registry's own address is ever asked", hx._allowed("https://open-vsx.org/api/x") and hx._allowed("https://openvsxorg.blob.core.windows.net/x") is False and not hx._allowed("http://open-vsx.org/x")
   and not hx._allowed("https://evil.example/open-vsx.org") and not hx._allowed("file:///etc/passwd"))
c.removeExtension("sarah.night-owl")

# ============================================================================================================ notebooks
JUP = {"cells": [{"cell_type": "markdown", "id": "intro", "metadata": {"tags": ["title"]}, "source": ["# Waves\n", "How many per wave."]},
                 {"cell_type": "code", "execution_count": 7, "id": "calc", "metadata": {"collapsed": False}, "source": "waves = [3 * n for n in range(1, 4)]\nprint('total', sum(waves))\nwaves",
                  "outputs": [{"name": "stdout", "output_type": "stream", "text": ["total 18\n"]}, {"data": {"text/plain": ["[3, 6, 9]"]}, "execution_count": 7, "metadata": {}, "output_type": "execute_result"}]},
                 {"cell_type": "code", "execution_count": None, "id": "calc", "metadata": {}, "outputs": [], "source": [], "attachments": {"keep": 1}},
                 {"cell_type": "weird", "metadata": {}, "source": "x"}, "junk"],
       "metadata": {"kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"}, "custom": {"studio": "astrid"}}, "nbformat": 4, "nbformat_minor": 4, "extra_top": [1, 2]}
nb = nbk.parse(json.dumps(JUP))
ok("a Jupyter notebook is read: text and code cells, sources as lines or as one string, outputs, counts", [(c_["id"], c_["kind"]) for c_ in nb["cells"]][:2] == [("intro", "markdown"), ("calc", "code")]
   and nb["cells"][0]["source"] == "# Waves\nHow many per wave." and nb["cells"][1]["source"].endswith("\nwaves") and nb["cells"][1]["count"] == 7 and len(nb["cells"][1]["outputs"]) == 2 and len(nb["cells"]) == 4, nb["cells"])
ok("two cells with one id: the second gets its own; a kind Code doesn't know is kept as raw", nb["cells"][2]["id"] not in ("calc", "") and nb["cells"][3]["kind"] == "raw")
back = json.loads(nbk.dump(nb))
ok("written back, what Code doesn't use is all still there", back["metadata"] == JUP["metadata"] and back["extra_top"] == [1, 2] and back["cells"][0]["metadata"] == {"tags": ["title"]} and back["cells"][2]["attachments"] == {"keep": 1}
   and back["cells"][1]["outputs"] == JUP["cells"][1]["outputs"] and back["cells"][1]["execution_count"] == 7 and back["nbformat"] == 4 and back["nbformat_minor"] == 5)
ok("…in Jupyter's own shape: sources as lines keeping their ends, text cells without outputs, a last newline", back["cells"][1]["source"] == ["waves = [3 * n for n in range(1, 4)]\n", "print('total', sum(waves))\n", "waves"]
   and "outputs" not in back["cells"][0] and "execution_count" not in back["cells"][0] and nbk.dump(nb).endswith("}\n") and nbk.dump(nbk.parse(nbk.dump(nb))) == nbk.dump(nb))
def not_nb(text):
    try:
        nbk.parse(text); return ""
    except ValueError as err:
        return str(err)
ok("what isn't a notebook says why: not JSON, no cells, the old format, a format from the future", "JSON" in not_nb("{nope") and "no cells" in not_nb('{"a": 1}') and "no cells" in not_nb("[1]")
   and "old format" in not_nb('{"worksheets": [], "nbformat": 3}') and "format 5" in not_nb('{"cells": [], "nbformat": 5}'))
ok("an empty file is an empty notebook with one cell", [c_["kind"] for c_ in nbk.parse("")["cells"]] == ["code"] and nbk.parse("  \n")["meta"]["kernelspec"]["name"] == "python3")
sh = nbk.shown(JUP["cells"][1]["outputs"] + [{"output_type": "error", "ename": "E", "evalue": "v", "traceback": ["\x1b[0;31mE\x1b[0m: v"]},
                                                 {"output_type": "display_data", "data": {"image/png": "iVBORw0KGgo=\n", "text/plain": "<Figure>"}},
                                                 {"output_type": "execute_result", "data": {"text/html": "<script>alert(1)</script><b>x</b>", "text/plain": "safe"}},
                                                 {"output_type": "execute_result", "data": {"text/html": "<table><tr><td>1</td></tr></table>", "text/plain": "t"}}])
ok("outputs as the window draws them: text, an error without terminal colours, a picture, a table; HTML with a script falls back to its plain text",
   [(r["kind"], r["text"]) for r in sh[:3]] == [("text", "total 18"), ("text", "[3, 6, 9]"), ("error", "E: v")] and sh[3] == {"kind": "image", "text": "", "src": "data:image/png;base64,iVBORw0KGgo="}
   and (sh[4]["kind"], sh[4]["text"]) == ("text", "safe") and sh[5]["kind"] == "html", sh)
ok("IPython's own lines are named before a cell is tried", "magic" in nbk.not_python("x = 1\n%matplotlib inline") and "magic" in nbk.not_python("%%time\nx") and "shell" in nbk.not_python("!pip install x")
   and nbk.not_python("x = 5 % 3\ny = not x\ns = '%d' % 3") == "")
venv = Path(home) / "vp" / ".venv" / "bin"; venv.mkdir(parents=True); (venv / "python").write_text("#!/bin/sh\n"); (venv / "python").chmod(0o755); (Path(home) / "vp" / "sub").mkdir()
ok("the project's own .venv is the notebook's Python, also from a folder inside; else python3", nbk.python_for(Path(home) / "vp" / "sub") == str(venv / "python") and nbk.python_for("/") == "python3")

nbdir = Path(home) / "nbproj"; nbdir.mkdir(); (nbdir / "helper.py").write_text("def triple(n):\n    return n * 3\n")
(nbdir / "waves.ipynb").write_text(json.dumps(JUP))
close_all(); c.openFolder(str(nbdir)); c.openFile(str(nbdir / "waves.ipynb")); spin(200)
i = tab("waves.ipynb")
ok("opened in Code: a notebook tab, its cells and its saved outputs shown, nothing changed yet", c.tabs[i]["notebook"] is True and c.tabs[i]["dirty"] is False and c.notebook(i)["ok"] and [x["kind"] for x in c.notebook(i)["cells"]] == ["markdown", "code", "code", "raw"]
   and c.notebook(i)["cells"][1]["count"] == 7 and [o["text"] for o in c.notebook(i)["cells"][1]["outputs"]] == ["total 18", "[3, 6, 9]"] and c.tabs[tab("waves.ipynb")]["lang"] == "JSON", c.notebook(i))
cells = lambda: c.notebook(i)["cells"]                              # noqa: E731
done = lambda: not c.notebook(i)["busy"] and all(x["state"] == "" for x in cells())      # noqa: E731
turns = []
c.nbChanged.connect(turns.append)
cid = cells()[1]["id"]
c.nbRun(i, cid)
ok("running a cell: it is marked running, its old output goes", cells()[1]["state"] == "running" and cells()[1]["outputs"] == [] and c.notebook(i)["busy"])
ok("…then what it printed and its last line's value come under it, with its number", wait(done, 30) and [(o["kind"], o["text"]) for o in cells()[1]["outputs"]] == [("text", "total 18"), ("text", "[3, 6, 9]")] and cells()[1]["count"] == 1
   and c.notebook(i)["alive"] and c.notebook(i)["python"][:1] == "3" and wait(lambda: turns, 3), (cells()[1], turns))
ok("the file's text holds the new outputs, and the tab is changed", wait(lambda: c.tabs[i]["dirty"], 5) and json.loads(c.textOf(i))["cells"][1]["execution_count"] == 1)
new = c.nbAdd(i, 2, "code"); c.nbSetSource(i, new, "import helper, os\nprint(helper.triple(len(waves)), os.path.basename(os.getcwd()))")
c.nbRun(i, new)
ok("a new cell sees the names earlier cells made, and runs in the notebook's own folder (its modules import)", wait(done, 30) and [o["text"] for o in cells()[2]["outputs"]] == ["9 nbproj"] and cells()[2]["count"] == 2, cells()[2])
bad = c.nbAdd(i, 3, "code"); c.nbSetSource(i, bad, "def f():\n    return waves[99]\nf()"); c.nbRun(i, bad); wait(done, 30)
err = cells()[3]["outputs"]
ok("an error is shown as an error, with the cell's own lines and none of Code's", len(err) == 1 and err[0]["kind"] == "error" and "IndexError: list index out of range" in err[0]["text"] and "return waves[99]" in err[0]["text"]
   and "huginn_nb_kernel" not in err[0]["text"] and cells()[3]["count"] == 3, err)
c.nbSetSource(i, bad, "def f(:\n"); c.nbRun(i, bad); wait(done, 30)
ok("a cell that isn't Python says where, briefly", cells()[3]["outputs"][0]["kind"] == "error" and "SyntaxError" in cells()[3]["outputs"][0]["text"] and "ast.py" not in cells()[3]["outputs"][0]["text"], cells()[3]["outputs"])
c.nbSetSource(i, bad, "%timeit sum(waves)"); c.nbRun(i, bad)
ok("an IPython magic is declined in words, without running", "IPython magic" in cells()[3]["outputs"][0]["text"] and cells()[3]["state"] == "" and done())
c.nbSetSource(i, bad, "import sys, subprocess\nprint('to err', file=sys.stderr)\nsubprocess.run(['echo', 'from a child'])\nclass T:\n    def _repr_html_(self): return '<b>bold</b>'\ndisplay(T())\ninput('?')"); c.nbRun(i, bad); wait(done, 30)
kinds = [(o["kind"], o["text"][:22]) for o in cells()[3]["outputs"]]
ok("stderr, a child program's output, display() and input() each come out as what they are", any(k_ == "error" and t_.startswith("to err") for k_, t_ in kinds) and ("html", "<b>bold</b>") in kinds and any(k_ == "error" and "input() isn't answered" in t_ for k_, t_ in [(o["kind"], o["text"]) for o in cells()[3]["outputs"]])
   and any("from a child" in o["text"] for o in cells()[3]["outputs"]), cells()[3]["outputs"])
c.nbSetSource(i, bad, "import time\nfor k in range(200):\n    time.sleep(0.1)\nprint('finished')"); c.nbRun(i, bad); c.nbRun(i, new)
ok("a second cell waits its turn", wait(lambda: cells()[3]["state"] == "running", 10) and cells()[2]["state"] == "queued")
spin(600); c.nbInterrupt(i)
ok("Stop ends the running cell and drops the ones waiting; the names made so far stay", wait(done, 15) and "Stopped" in cells()[3]["outputs"][-1]["text"] and not any("finished" in o["text"] for o in cells()[3]["outputs"])
   and cells()[2]["state"] == "" and c.notebook(i)["alive"], cells()[3]["outputs"])
c.nbSetSource(i, bad, "k"); c.nbRun(i, bad); wait(done, 20)
ok("…and the Python is the same one afterwards", cells()[3]["outputs"] and cells()[3]["outputs"][0]["text"].isdigit(), cells()[3]["outputs"])
c.nbSetSource(i, bad, "import os\nos._exit(3)"); c.nbRun(i, bad)
ok("a cell that kills its Python: said under the cell, and the next run starts a fresh one", wait(lambda: done() and not c.notebook(i)["alive"], 20) and "ended while this cell ran" in cells()[3]["outputs"][-1]["text"], cells()[3]["outputs"])
c.nbSetSource(i, bad, "'waves' in dir()"); c.nbRun(i, bad); wait(done, 30)
ok("…which has none of the old names", [o["text"] for o in cells()[3]["outputs"]] == ["False"] and c.notebook(i)["alive"], cells()[3]["outputs"])
c.nbRunAll(i)
ok("Run All runs the code cells in order", wait(done, 60) and [x["count"] for x in cells() if x["kind"] == "code"][:2] == [2, 3] and [o["text"] for o in cells()[2]["outputs"]] == ["9 nbproj"], [(x["count"], x["outputs"]) for x in cells()])
c.nbKind(i, bad, "markdown"); c.nbSetSource(i, bad, "## Notes\nThese are *notes*.")
c.nbMove(i, bad, -10)
ok("a cell becomes text, loses its outputs, and moves", [x["kind"] for x in cells()][:2] == ["markdown", "markdown"] and cells()[0]["id"] == bad and cells()[0]["outputs"] == [] and cells()[0]["source"].startswith("## Notes"))
n_before = len(cells()); c.nbRemove(i, new)
ok("a cell is removed", len(cells()) == n_before - 1 and new not in [x["id"] for x in cells()])
ok("saved: the file is a notebook Jupyter reads, with the cells as they are now", c.save(i, False) == "" and not c.tabs[i]["dirty"]
   and [x["cell_type"] for x in json.loads((nbdir / "waves.ipynb").read_text())["cells"]][:3] == ["markdown", "markdown", "code"]
   and json.loads((nbdir / "waves.ipynb").read_text())["cells"][0]["source"] == ["## Notes\n", "These are *notes*."] and json.loads((nbdir / "waves.ipynb").read_text())["metadata"]["custom"] == {"studio": "astrid"})
c.nbSetSource(i, bad, "typed and saved at once")
ok("typing then saving straight away loses nothing", c.save(i, False) == "" and json.loads((nbdir / "waves.ipynb").read_text())["cells"][0]["source"] == ["typed and saved at once"])
c.nbClear(i); spin(500)
ok("Clear Outputs empties every cell's, and the text follows", all(x["outputs"] == [] and x["count"] == 0 for x in cells()) and all(not x.get("outputs") for x in json.loads(c.textOf(i))["cells"]))
c.edit(i, c.textOf(i).replace("typed and saved at once", "edited as JSON")); spin(50)
ok("its text edited as JSON is what the cells show next", cells()[0]["source"] == "edited as JSON")
c.edit(i, "{ not json")
ok("text that stops being a notebook says so, and nothing is lost or overwritten", c.notebook(i)["ok"] is False and "JSON" in c.notebook(i)["why"] and (c.nbAdd(i, 0, "code"), c.textOf(i))[1] == "{ not json")
c.reload(i); spin(100)
ok("taken again from disk, it is the saved notebook", c.notebook(i)["ok"] and cells()[0]["source"] == "typed and saved at once")
c.nbRestart(i)
ok("Restart ends its Python", not c.notebook(i)["alive"])
c.nbRun(i, cells()[2]["id"]); wait(done, 30); pid = c._kernels[str(nbdir / "waves.ipynb")]._proc.processId()
c.close(i, True); spin(300)
ok("closing the notebook ends its Python", str(nbdir / "waves.ipynb") not in c._kernels and not Path(f"/proc/{pid}/cmdline").exists())
(nbdir / "new.ipynb").write_text("")
c.openFile(str(nbdir / "new.ipynb")); spin(100); i = tab("new.ipynb")
first = cells()[0]["id"]; c.nbSetSource(i, first, "6 * 7"); c.nbRun(i, first); wait(done, 30)
ok("a new, empty .ipynb is a notebook with one cell, and runs", [o["text"] for o in cells()[0]["outputs"]] == ["42"] and c.save(i, False) == "" and json.loads((nbdir / "new.ipynb").read_text())["nbformat"] == 4)
try:
    import matplotlib                                              # noqa: F401
    has_plots = True
except ImportError:
    has_plots = False
if has_plots:
    fig_cell = c.nbAdd(i, 1, "code")
    c.nbSetSource(i, fig_cell, "import matplotlib.pyplot as plt\nplt.plot([1, 4, 9, 16])\nplt.title('waves')\nplt.figure()\nplt.bar(['a', 'b'], [3, 5])")
    c.nbRun(i, fig_cell); wait(done, 90)
    outs = cells()[1]["outputs"]
    pics = [o for o in outs if o["kind"] == "image"]
    import base64
    raw = [base64.b64decode(p_["src"].split(",", 1)[1]) for p_ in pics]
    ok("matplotlib: the two figures a cell leaves open are shown under it as pictures, with no window asked for", len(pics) == 2 and all(r[:8] == b"\x89PNG\r\n\x1a\n" and len(r) > 3000 for r in raw)
       and not any(o["kind"] == "error" for o in outs), [(o["kind"], o["text"][:200]) for o in outs])
    from PySide6.QtGui import QImage
    img = QImage.fromData(raw[0]) if raw else QImage()
    ok("…a real picture of a sensible size, not blank", not img.isNull() and img.width() > 300 and img.height() > 200 and len({img.pixel(x, img.height() // 2) for x in range(0, img.width(), 7)}) > 1, (img.width(), img.height()))
    c.nbRun(i, fig_cell); wait(done, 60)
    ok("run again, it shows two figures, not four (they are closed once shown)", len([o for o in cells()[1]["outputs"] if o["kind"] == "image"]) == 2)
    ok("saved, the pictures are in the file as Jupyter keeps them", c.save(i, False) == "" and [o["output_type"] for o in json.loads((nbdir / "new.ipynb").read_text())["cells"][1]["outputs"]].count("display_data") == 2
       and all("image/png" in o["data"] for o in json.loads((nbdir / "new.ipynb").read_text())["cells"][1]["outputs"] if o["output_type"] == "display_data"))
else:
    print("(no matplotlib here: figures in notebooks are skipped)")
close_all(); c.closeFolder()
ok("no notebook Pythons are left running", c._kernels == {})

# ========================================================================================== workspaces of several folders
ws = Path(home) / "studio"; eng = ws / "engine"; gam = ws / "game"; tools = ws / "kit" / "tools"; twin = ws / "other" / "tools"
for d_ in (eng / "src", gam / "scripts", gam / ".vscode", tools, twin):
    d_.mkdir(parents=True)
(eng / "src" / "core.c").write_text("int core(void) { return 42; }\n"); (eng / "Makefile").write_text("all:\n\t@echo engine built\n")
(gam / "scripts" / "player.py").write_text("SPEED = 42\n"); (gam / "main.py").write_text("print('game')\n")
(gam / ".vscode" / "settings.json").write_text('{"editor.tabSize": 3}')
(tools / "bake.py").write_text("ANSWER = 42\n"); (twin / "lint.py").write_text("pass\n")
subprocess.run(["git", "init", "-q", "-b", "main", str(gam)], check=True); (gam / "scripts" / "new.py").write_text("x = 1\n")
(ws / "studio.code-workspace").write_text("""{
    // the studio's workspace
    "folders": [ { "path": "engine" }, { "name": "Game", "path": "./game" }, { "path": "gone" }, { "path": "%s" } ],
    "settings": { "editor.tabSize": 8, "files.exclude": { "**/*.tmp": true } },
}""" % tools)
close_all(); c.closeFolder(); k = len(said)
c.openFolder(str(ws / "studio.code-workspace")); spin(300)
ok("a .code-workspace file opens all its folders that are there, and says which weren't", [f["path"] for f in c.folders] == [str(eng), str(gam), str(tools)] and c.root == str(eng) and c.folders[0]["active"]
   and any("left out" in s_ for s_ in said[k:]) and c.workspaceFile == str(ws / "studio.code-workspace"), (c.folders, said[k:]))
heads = [(r["name"], r.get("active")) for r in c.tree if r.get("root")]
ok("the Files list has a heading per folder, the working one marked, each folder's files under its own", heads == [("engine", True), ("game", False), ("tools", False)]
   and [r["name"] for r in c.tree if r["depth"] == 1] == ["src", "Makefile", ".vscode", "scripts", "main.py", "bake.py"], [(r["name"], r["depth"]) for r in c.tree])
ok("the workspace's settings apply", c.setting("editor.tabSize") == 8)
names = [r["rel"] for r in c.quickOpen("")]
ok("quick open names every folder's files, each under its folder", {"engine/src/core.c", "game/scripts/player.py", "game/main.py", "tools/bake.py"} <= set(names), names)
ok("…and finds across them", [r["rel"] for r in c.quickOpen("player")][:1] == ["game/scripts/player.py"] and [r["rel"] for r in c.quickOpen("bake")][:1] == ["tools/bake.py"])
c.openRel("game/scripts/player.py"); spin(300)
ok("opening a file in another folder makes that the working folder: its settings, its Git, its Build", c.root == str(gam) and [f["active"] for f in c.folders] == [False, True, False] and c.setting("editor.tabSize") == 3
   and c.isGit and tab("player.py") >= 0, (c.root, c.setting("editor.tabSize"), c.isGit))
ok("…and no tab was closed for it, and Git's marks are that folder's", wait(lambda: any(r["name"] == "scripts" and r["git"] for r in c.tree), 10) and not any(r["git"] for r in c.tree if r["path"].startswith(str(eng))), [(r["name"], r["git"]) for r in c.tree])
c.openFile(str(eng / "src" / "core.c")); spin(300)
ok("back in a file of the first folder: Build is that folder's again, and it isn't a Git folder", c.root == str(eng) and not c.isGit and any(t["name"] == "make" or "make" in t["command"] for t in c.build.tasks) and len(c.tabs) == 2, (c.root, [t["name"] for t in c.build.tasks]))
c.select(tab("player.py")); spin(200)
ok("picking a tab moves the working folder too", c.root == str(gam))
got = []
c.searchDone.connect(lambda: got.append(1))
c.search("42", True, False, False); wait(lambda: not c.searching and got, 20)
ok("search looks in every folder, and names where", sorted({r["path"] for r in c.results}) == ["engine/src/core.c", "game/scripts/player.py", "tools/bake.py"], c.results)
n = c.replaceAll("42", "43", True, False, False)
ok("replace in all reaches each folder's file", n == 3 and (tools / "bake.py").read_text() == "ANSWER = 43\n" and c.textOf(tab("player.py")) == "SPEED = 43\n" and c.textOf(tab("core.c")).count("43") == 1, n)
c.saveAll(); spin(100)
c.toggle(str(tools))
ok("a folder's heading folds it shut, and open again", not any(r["name"] == "bake.py" for r in c.tree) and (c.toggle(str(tools)), any(r["name"] == "bake.py" for r in c.tree))[1])
ok("adding a folder: listed, searched; two of one name are told apart", c.addFolder(str(twin)) == "" and [f["name"] for f in c.folders] == ["engine", "game", "kit-tools", "other-tools"]
   and "other-tools/lint.py" in [r["rel"] for r in c.quickOpen("lint")] and "kit-tools/bake.py" in [r["rel"] for r in c.quickOpen("bake")], c.folders)
ok("the same folder twice, or one that isn't there, is declined", "already" in c.addFolder(str(twin)) and "isn't there" in c.addFolder(str(ws / "nope")) and c.addFolder("  ") == "")
c.openRel("other-tools/lint.py"); spin(200); i = tab("lint.py"); c.edit(i, "pass  # changed\n")
ok("a folder with unsaved files isn't removed", "Save or close" in c.removeFolder(str(twin)) and len(c.folders) == 4)
c.save(i, False)
ok("removed: its tabs close, its files stay, and the working folder moves on", c.removeFolder(str(twin)) == "" and tab("lint.py") < 0 and (twin / "lint.py").read_text() == "pass  # changed\n" and len(c.folders) == 3
   and c.root in (str(eng), str(gam), str(tools)) and "isn't one" in c.removeFolder(str(twin)), (c.folders, c.root))
out = ws / "saved"
ok("saved as a .code-workspace: VS Code's own file, folders named from where the file is", c.saveWorkspace(str(out)) == "" and c.workspaceFile == str(out) + ".code-workspace"
   and json.loads(Path(c.workspaceFile).read_text())["folders"] == [{"path": "engine"}, {"path": "game"}, {"path": "kit/tools"}] and json.loads(Path(c.workspaceFile).read_text())["settings"]["editor.tabSize"] == 8,
   Path(str(out) + ".code-workspace").read_text() if Path(str(out) + ".code-workspace").exists() else "none")
c._keep(); was_tabs = sorted(t["name"] for t in c.tabs)
c2 = code.Code(); c2._demo = False; c2._restore_last(); spin(300)
ok("Code started again comes back to the workspace: its folders, its settings, its tabs", [f["path"] for f in c2.folders] == [str(eng), str(gam), str(tools)] and sorted(t["name"] for t in c2.tabs) == was_tabs
   and c2.workspaceFile == c.workspaceFile, (c2.folders, c2.tabs))
c2._close_all()
close_all(); c.closeFolder()
c.openFolder(str(eng)); spin(200)
ok("a plain folder that was a workspace's first is one folder again only if the workspace was closed as one", c.root == str(eng), c.folders)
ok("two folders added by hand make a workspace with no file, remembered under the first", (c.closeFolder(), c.openFolder(str(gam)), c.addFolder(str(tools)))[2] == "" and len(c.folders) == 2 and c.workspaceFile == ""
   and (c._keep(), code.Code())[1]._state.get("spaces", {}).get(str(gam)) == [str(tools)], c.folders)
ok("one folder of the two removed: no workspace is left, only the folder", c.removeFolder(str(tools)) == "" and c.folders == [] and c.root == str(gam) and not any(r.get("root") for r in c.tree)
   and "isn't a workspace" in c.saveWorkspace(str(ws / "x")))
close_all(); c.closeFolder()

for k in kids:
    if k.poll() is None: k.kill()
print(f"{passed} passed, {failed} failed")
