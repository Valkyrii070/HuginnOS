#!/usr/bin/env python3
"""Code's dev containers against a real engine (Podman or Docker), not the stand-in code_round9_test.py uses.

It needs an engine that can run containers where it is run, and an image named by DEVBASE (default
localhost/huginn-devbase:1) that has python3, debugpy and make. Where only root can run containers (a build sandbox
without user namespaces), set REAL_ENGINE_AS_ROOT=1: this script makes one folder under the temp folder, changes
nothing outside it, and removes its own container at the end.
Usage: code_container_real_check.py <kit root>   (QT_QPA_PLATFORM=offscreen)"""
import os, subprocess, sys, tempfile, time
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0 and os.environ.get("REAL_ENGINE_AS_ROOT") != "1":
    sys.exit("not as root (set REAL_ENGINE_AS_ROOT=1 where only root can run containers)")
home = tempfile.mkdtemp(prefix="code-box-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/data", XDG_CONFIG_HOME=home + "/config", XDG_CACHE_HOME=home + "/cache", PYDEVD_DISABLE_FILE_VALIDATION="1",
                  QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication
app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
import huginn_code as code
import huginn_container as hc

BASE = os.environ.get("DEVBASE", "localhost/huginn-devbase:1")
eng = hc.engine()
if not eng or subprocess.run([eng, "image", "exists", BASE], capture_output=True).returncode != 0:
    print(f"(no engine, or no image {BASE} here: nothing checked)"); sys.exit(0)
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
        spin(100)
    return cond()

game = Path(home) / "Sky Game"; (game / ".devcontainer").mkdir(parents=True); (game / "src").mkdir()
(game / ".devcontainer" / "devcontainer.json").write_text("""{
    // a real one
    "name": "Sky box",
    "build": { "dockerfile": "Dockerfile", "context": "..", "args": { "FLAVOUR": "sky" } },
    "containerEnv": { "SKY": "blue" },
    "postCreateCommand": "echo created by $(id -un) in $PWD > .created",
    "postStartCommand": ["sh", "-c", "date +%s >> .started"]
}""")
(game / ".devcontainer" / "Dockerfile").write_text(f"FROM {BASE}\nARG FLAVOUR=none\nRUN echo built-$FLAVOUR > /built.txt\n")
(game / "src" / "calc.py").write_text("import os\ndef twice(n):\n    m = n * 2\n    return m\n\nprint(twice(21), open('/built.txt').read().strip(), os.environ.get('SKY'), os.getcwd())\n")
(game / "Makefile").write_text("all:\n\t@cat /built.txt\n\t@python3 src/broken.py\n")
(game / "src" / "broken.py").write_text("x = 1\ny = (\n")

c = code.Code(); c._demo = False
said = []
c.said.connect(lambda text, bad: said.append(text))
class Term:                                                        # Code's terminal, standing in: what is typed into it is run by a shell
    def __init__(self): self.typed, self.out = [], []
    def _send(self, data):
        self.typed.append(data.decode())
        r = subprocess.run(["bash", "-c", data.decode().strip()], capture_output=True, text=True, cwd=str(game), stdin=subprocess.DEVNULL, timeout=600)
        self.out.append((r.returncode, r.stdout[-600:], r.stderr[-600:]))
term = Term(); c._get_term = lambda: term
c.openFolder(str(game)); spin(200)
box = hc.where(eng, hc.read(game))
subprocess.run(hc.stop_command(box, True), capture_output=True)    # (one left by a run that was cut short)
ok(f"the project has a container, and the engine here is real ({eng})", c.container["has"] and c.container["engine"] == eng and not c.container["running"] and c.container["problem"] == "", c.container)
ok("starting it is under way", c.containerOpen() == "")
ok("the image was built from the Dockerfile and the container runs", wait(lambda: c.container["running"], 240) and term.out and term.out[-1][0] == 0 and hc.state(box) == "running", (term.out[-1:], said[-2:]))
ok("the project's create and start commands ran inside it, in the shared folder", (game / ".created").is_file() and (game / ".created").read_text().strip().endswith("/workspaces/Sky Game") and (game / ".started").is_file(), (game / ".created").read_text() if (game / ".created").exists() else "no file")
code_, out = hc.probe(box, "cat /built.txt; echo $SKY; pwd")
ok("inside: what the Dockerfile built, the environment asked for, the folder shared", code_ == 0 and out.split("\n") == ["built-sky", "blue", "/workspaces/Sky Game"], (code_, out))
b = c.build
b.refresh(); b.run("make"); wait(lambda: not b.running, 120)
texts = [r["text"] for r in b.lines.rows]
ok("Build ran in the container (it read a file only the container has), and Python's error there opens the file here", any(t == "built-sky" for t in texts) and b.status.startswith("Failed")
   and any(p["path"] == str(game / "src" / "broken.py") for p in b.problems), (b.status, texts[:8], b.problems))
c.openFile(str(game / "src" / "calc.py")); spin(300)
k = len(term.typed); c.run(f"python3 '{game}/src/calc.py'"); spin(300)
ok("Run is typed for the container, with the path as it is inside", len(term.typed) > k and "/workspaces/Sky Game/src/calc.py" in term.typed[-1] and str(game) not in term.typed[-1], term.typed[k:])
dbg = c.debug
dbg.toggle(str(game / "src" / "calc.py"), 2)
c.startDebug("")
ok("F5: debugpy runs inside the real container and stops at the breakpoint, shown in the file here", wait(lambda: dbg.state == "stopped" and dbg.whereLine == 2, 90) and dbg.whereFile == str(game / "src" / "calc.py"),
   (dbg.state, dbg.whereFile, dbg.whereLine, [r["text"] for r in dbg.output][-4:], said[-2:]))
ok("its variables come back", wait(lambda: any(r.get("name") == "n" and "21" in str(r.get("value")) for r in dbg.variables), 15), dbg.variables[:4])
dbg.stepOver()
ok("a step lands on the next line", wait(lambda: dbg.state == "stopped" and dbg.whereLine == 3, 30), (dbg.state, dbg.whereLine))
dbg.resume()
text = lambda: "".join(r["text"] for r in dbg.output)              # noqa: E731
ok("it ran to the end in there: its output has what only the container knows", wait(lambda: not dbg.active, 60) and "42 built-sky blue /workspaces/Sky Game" in text(), [r["text"] for r in dbg.output][-5:])
dbg.set_all({})
c.closeFolder(); c.openFolder(str(game)); spin(300)
ok("opened again, the running container is found", c.container["running"])
c.containerStop(False)
ok("stopped", wait(lambda: hc.state(box) == "stopped", 60), hc.state(box))
n_started = len((game / ".started").read_text().split())
ok("started again without building: only the start command runs again", c.containerOpen() == "" and wait(lambda: c.container["running"], 120) and "build" not in term.typed[-1].split("&&")[0]
   and len((game / ".started").read_text().split()) == n_started + 1, term.typed[-1][:120])
c.containerStop(True)
ok("stopped and removed: the engine has no such container, the project's files are all still here", wait(lambda: hc.state(box) == "", 60) and (game / "src" / "calc.py").is_file() and (game / "Makefile").is_file(), hc.state(box))
subprocess.run([eng, "rmi", "-f", hc.image_for(hc.read(game))], capture_output=True)
(game / ".devcontainer" / "Dockerfile").write_text(f"FROM {BASE}\nRUN echo this build fails on purpose && false\n")
k = len(said); t0 = time.time()
ok("a Dockerfile that fails: Code says the container didn't start, soon, and isn't left waiting", c.containerOpen() == "" and wait(lambda: any("didn't start" in s_ for s_ in said[k:]), 120)
   and not c.container["starting"] and not c.container["running"] and time.time() - t0 < 100, (said[k:], term.out[-1:]))
subprocess.run([eng, "image", "prune", "-f"], capture_output=True)
print(f"{passed} passed, {failed} failed")
