"""Huginn Code's debugger, over the Debug Adapter Protocol (the protocol VS Code's debuggers speak).

    Python                  debugpy (python3 -m debugpy.adapter)
    C, C++, Rust, Go, …     GDB 14 and later (gdb -i dap), on the program you build; Code asks which one, and
                            remembers it in the project's .huginn-debug file

Code sets breakpoints, starts the program, and when it stops shows where (the call stack), what everything holds
(variables, opened a level at a time), and lets you step over, into and out, carry on, or type an expression to
work out in the stopped program. What the program prints shows in the Debug console.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, Signal, Slot

COMPILED = {"C", "C++", "Rust", "Go", "Zig", "Fortran", "D", "Pascal"}


def has_debugpy(python: str = "python3") -> bool:
    try:
        return subprocess.run([python, "-c", "import debugpy"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def gdb_has_dap() -> bool:
    if not shutil.which("gdb"):
        return False
    try:
        out = subprocess.run(["gdb", "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10).stdout
        major = int(out.split("\n")[0].rsplit(" ", 1)[-1].split(".")[0])
        return major >= 14
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return False


def adapter_for(lang: str, file: str, root: Path, program: str = "", python: str = "python3") -> tuple:
    """(adapter command, launch arguments, name) for a file, or a ValueError saying what's missing."""
    if lang == "Python":
        if not has_debugpy(python):
            raise ValueError("Debugging Python needs debugpy (the python3-debugpy package).")
        return ([python, "-m", "debugpy.adapter"],
                {"type": "python", "request": "launch", "name": "Huginn Code", "program": file, "cwd": str(root), "console": "internalConsole",
                 "justMyCode": True, "redirectOutput": True, "showReturnValue": True}, "debugpy")
    if lang in COMPILED:
        if not gdb_has_dap():
            raise ValueError("Debugging compiled programs needs GDB 14 or later (the gdb package).")
        if not program:
            raise LookupError("program")
        return (["gdb", "-q", "-i", "dap"], {"program": program, "args": [], "cwd": str(root), "stopAtBeginningOfMainSubprogram": False}, "GDB")
    raise ValueError(f"Code can't debug {lang or 'this kind of file'} yet. Run it instead (Ctrl+F5).")


# ---------------------------------------------------------------- attaching to a program that is already running
def processes(limit: int = 400) -> list:
    """The user's own running programs, newest first: [{pid, name, command, kind}] where kind is "python" (debugpy can
    attach) or "native" (GDB can). Code itself, its helpers and kernel threads are left out."""
    me, uid, out = os.getpid(), os.getuid(), []
    try:
        pids = sorted((int(n) for n in os.listdir("/proc") if n.isdigit()), reverse=True)
    except OSError:
        return out
    for pid in pids:
        if pid == me or pid == os.getppid():
            continue
        base = f"/proc/{pid}"
        try:
            if os.stat(base).st_uid != uid:
                continue
            raw = Path(base, "cmdline").read_bytes()
            if not raw:
                continue                                           # a kernel thread, or one that has gone
            args = [a.decode("utf-8", "replace") for a in raw.rstrip(b"\0").split(b"\0")]
            name = Path(base, "comm").read_text(encoding="utf-8", errors="replace").strip()
            try:
                exe = os.path.basename(os.readlink(base + "/exe"))
            except OSError:
                exe = os.path.basename(args[0])
        except (OSError, ValueError):
            continue
        if "debugpy" in " ".join(args[:6]) or (exe == "gdb" and "dap" in args) or "huginn_app.py" in " ".join(args[:3]):
            continue
        kind = "python" if re.match(r"python(\d+(\.\d+)?)?$", exe) else "native"
        out.append({"pid": pid, "name": name, "command": " ".join(" ".join(args).split())[:300], "kind": kind})
        if len(out) >= limit:
            break
    return out


def ptrace_note() -> str:
    """Why attaching to a running program may be refused on this system ("" when nothing stands in the way)."""
    try:
        scope = int(Path("/proc/sys/kernel/yama/ptrace_scope").read_text().strip())
    except (OSError, ValueError):
        return ""
    if scope >= 2:
        return "This system lets only an administrator attach to running programs (kernel.yama.ptrace_scope is 2 or more)."
    if scope == 1:
        return ("This system only lets a program be attached to by the one that started it (kernel.yama.ptrace_scope is 1, Ubuntu's default). "
                "To allow it until the next restart, run in a terminal:  sudo sysctl kernel.yama.ptrace_scope=0")
    return ""


def attach_for(kind: str, pid: int = 0, host: str = "", port: int = 0, program: str = "", mappings: list = (), python: str = "python3") -> tuple:
    """(adapter command, attach arguments, name) for a running program: by process number, or one waiting on a port
    (debugpy's --listen; gdbserver). `mappings` are [(folder here, the same folder where the program runs)]."""
    if kind == "python":
        if not has_debugpy(python):
            raise ValueError("Debugging Python needs debugpy (the python3-debugpy package).")
        args = {"type": "python", "request": "attach", "name": "Huginn Code", "justMyCode": False, "redirectOutput": True}
        if port:
            # A program started with "python3 -m debugpy --listen PORT" has its own adapter waiting on that port:
            # Code talks to it there (huginn_lsp_tcp.py carries the conversation; this computer only).
            if (host or "127.0.0.1") not in ("127.0.0.1", "localhost", "::1"):
                raise ValueError(f"Code attaches to debugpy on this computer only. For {host}, open that computer over SSH (Remote), or forward its port here with ssh -L.")
            args["connect"] = {"host": "127.0.0.1", "port": int(port)}
            if mappings:
                args["pathMappings"] = [{"localRoot": str(here), "remoteRoot": str(there)} for here, there in mappings]
            return ([python, str(Path(__file__).resolve().with_name("huginn_lsp_tcp.py")), "127.0.0.1", str(int(port))], args, "debugpy")
        elif pid > 1:
            args["processId"] = int(pid)
        else:
            raise ValueError("Which program? It needs a process number, or the port debugpy is listening on.")
        if mappings:
            args["pathMappings"] = [{"localRoot": str(here), "remoteRoot": str(there)} for here, there in mappings]
        return ([python, "-m", "debugpy.adapter"], args, "debugpy")
    if not gdb_has_dap():
        raise ValueError("Debugging compiled programs needs GDB 14 or later (the gdb package).")
    args = {}
    if port:
        args["target"] = f"{host or '127.0.0.1'}:{int(port)}"
    elif pid > 1:
        args["pid"] = int(pid)
    else:
        raise ValueError("Which program? It needs a process number, or the address gdbserver is listening on.")
    if program:
        args["program"] = program
    return (["gdb", "-q", "-i", "dap"], args, "GDB")


class DapClient(QObject):
    """One debug adapter, spoken to over its standard input and output, messages framed as in LSP."""
    event = Signal(str, "QVariantMap")
    gone = Signal()

    def __init__(self, argv: list, cwd: str, parent=None):
        super().__init__(parent)
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(cwd)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(lambda *_: self.gone.emit())
        self.proc.errorOccurred.connect(lambda e: self.gone.emit() if e == QProcess.ProcessError.FailedToStart else None)
        self._buf, self._seq, self._waiting = b"", 1, {}
        self.proc.start(argv[0], argv[1:])

    def request(self, command: str, args: dict = None, then=None) -> int:
        seq = self._seq
        self._seq += 1
        msg = {"seq": seq, "type": "request", "command": command}
        if args is not None:
            msg["arguments"] = args
        if then:
            self._waiting[seq] = then
        body = json.dumps(msg).encode("utf-8")
        self.proc.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        return seq

    def _read(self) -> None:
        self._buf += bytes(self.proc.readAllStandardOutput())
        while True:
            head, sep, rest = self._buf.partition(b"\r\n\r\n")
            if not sep:
                return
            length = next((int(l.split(b":", 1)[1]) for l in head.split(b"\r\n") if l.lower().startswith(b"content-length")), None)
            if length is None or len(rest) < length:
                return
            body, self._buf = rest[:length], rest[length:]
            try:
                msg = json.loads(body)
            except ValueError:
                continue
            if msg.get("type") == "response":
                then = self._waiting.pop(msg.get("request_seq"), None)
                if then:
                    then(msg.get("body") or {}, None if msg.get("success") else (msg.get("message") or "failed"))
            elif msg.get("type") == "event":
                self.event.emit(msg.get("event", ""), msg.get("body") or {})
            elif msg.get("type") == "request" and msg.get("command") == "runInTerminal":
                self._reply(msg, {})                                  # we always ask for the internal console

    def _reply(self, req: dict, body: dict) -> None:
        msg = {"seq": self._seq, "type": "response", "request_seq": req.get("seq"), "success": True, "command": req.get("command"), "body": body}
        self._seq += 1
        data = json.dumps(msg).encode("utf-8")
        self.proc.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)

    def stop(self) -> None:
        if self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.kill()
            self.proc.waitForFinished(1500)


class Debugger(QObject):
    """A debugging session as Code's window sees it."""
    changed = Signal()
    printed = Signal()
    said = Signal(str, bool)
    landed = Signal(str, int)                 # file, line (0-based): show it in the editor

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = None
        self._state, self._adapter, self._reason = "idle", "", ""
        self._there, self._here = (lambda p: p), (lambda p: p)
        self._frames, self._frame, self._thread = [], -1, 0
        self._rows, self._open = [], set()
        self._console = []
        self._breakpoints = {}                # path -> sorted 0-based lines
        self._verified = {}                   # path -> {line: verified}
        self._where = ("", -1)
        self._launch = None
        self._configured = False

    # -------------------------------------------------------------- what the window shows
    state = Property(str, lambda self: self._state, notify=changed)
    active = Property(bool, lambda self: self._state != "idle", notify=changed)
    attached = Property(bool, lambda self: self._state != "idle" and getattr(self, "_request", "launch") == "attach", notify=changed)
    adapter = Property(str, lambda self: self._adapter, notify=changed)
    reason = Property(str, lambda self: self._reason, notify=changed)
    frames = Property("QVariantList", lambda self: self._frames, notify=changed)
    frame = Property(int, lambda self: self._frame, notify=changed)
    variables = Property("QVariantList", lambda self: self._rows, notify=changed)
    console = Property("QVariantList", lambda self: self._console[-600:], notify=printed)
    output = Property("QVariantList", lambda self: self._console[-600:], notify=printed)       # the same, for QML (where "console" is taken)
    whereFile = Property(str, lambda self: self._where[0], notify=changed)
    whereLine = Property(int, lambda self: self._where[1], notify=changed)

    def lines_for(self, path: str) -> list:
        return list(self._breakpoints.get(path, []))

    def all_breakpoints(self) -> dict:
        return {k: list(v) for k, v in self._breakpoints.items() if v}

    def set_all(self, saved: dict) -> None:
        self._breakpoints = {k: sorted(set(int(x) for x in v)) for k, v in (saved or {}).items() if v}

    def toggle(self, path: str, line: int) -> list:
        lines = set(self._breakpoints.get(path, []))
        lines ^= {line}
        self._breakpoints[path] = sorted(lines)
        if self._client and self._configured:
            self._send_breakpoints(path)
        self.changed.emit()
        return self._breakpoints[path]

    def shift(self, path: str, at_line: int, delta: int) -> None:
        """Lines were added or removed in a file: breakpoints below keep pointing at the same code."""
        if not delta or path not in self._breakpoints:
            return
        self._breakpoints[path] = sorted({l + delta if l > at_line else l for l in self._breakpoints[path] if not (delta < 0 and at_line < l <= at_line - delta)})

    def _say(self, text: str, kind: str = "console") -> None:
        for line in text.rstrip("\n").split("\n"):
            self._console.append({"text": line, "kind": kind})
        self.printed.emit()

    # -------------------------------------------------------------- starting and stopping
    def start(self, argv: list, launch: dict, name: str, cwd: str, request: str = "launch", what: str = "", helper=None, after: list = (), paths=None) -> None:
        """Start a program under the debugger ("launch"), or join one already running ("attach": stopping the
        debugger then leaves the program running). `helper` is a process that must live as long as the session (the
        ssh that runs the program on another computer); `after` are commands for the debugger's own prompt once it
        has joined (GDB's "set substitute-path …"). `paths` is (there, here): two functions turning a file's path
        on this computer into its path where the debugger runs (another computer, a container) and back."""
        self.stop(quiet=True)
        self._console, self._frames, self._rows, self._open = [], [], [], set()
        self._adapter, self._state, self._reason, self._configured = name, "starting", "", False
        self._launch = (argv, launch, name, cwd, request, what, None, tuple(after), paths)
        self._there, self._here = paths or ((lambda p: p), (lambda p: p))
        self._request, self._helper, self._after, self._joined = request, helper, list(after), False
        self._say((f"Attaching to {what or 'the program'} with {name}…" if request == "attach" else f"Starting {what or launch.get('program', '')} with {name}…"), "info")
        self._client = DapClient(argv, cwd, self)
        self._client.event.connect(self._event)
        self._client.gone.connect(self._ended)
        self._client.request("initialize", {"clientID": "huginn-code", "clientName": "Huginn Code", "adapterID": name.lower(), "pathFormat": "path",
                                            "linesStartAt1": True, "columnsStartAt1": True, "supportsVariableType": True, "supportsRunInTerminalRequest": False,
                                            "locale": "en"}, self._initialized)
        self.changed.emit()

    def _initialized(self, body: dict, error) -> None:
        if error:
            self._fail(f"The debugger didn't start: {error}")
            return
        attach = self._request == "attach"

        def started(body, error):
            if error:
                self._fail((f"Couldn't attach: {error}" + (". " + ptrace_note() if "ptrace" in str(error).lower() or "permitted" in str(error).lower() else "")) if attach
                           else f"The program didn't start: {error}")
                return
            for line in self._after:                                   # (GDB's own commands, at its prompt)
                self._client.request("evaluate", {"expression": line, "context": "repl"}, lambda b, e: None)
        self._client.request(self._request, self._launch[1], started)

    def _configure(self) -> None:
        for path in list(self._breakpoints):
            self._send_breakpoints(path)
        self._client.request("configurationDone", {}, lambda b, e: None)
        self._configured = True
        self._state = "running"
        self.changed.emit()

    def _send_breakpoints(self, path: str) -> None:
        lines = self._breakpoints.get(path, [])

        def got(body, error):
            if not error:
                self._verified[path] = {b.get("line", 0) - 1: bool(b.get("verified")) for b in body.get("breakpoints", [])}
                self.changed.emit()
        self._client.request("setBreakpoints", {"source": {"path": self._there(path) or path, "name": Path(path).name}, "breakpoints": [{"line": l + 1} for l in lines],
                                                "lines": [l + 1 for l in lines]}, got)

    def _fail(self, text: str) -> None:
        self._say(text, "error")
        self.said.emit(text, True)
        self.stop(quiet=True)

    @Slot()
    def stop(self, quiet: bool = False) -> None:
        if self._client is not None:
            client, self._client = self._client, None
            client.gone.disconnect()
            try:
                client.request("disconnect", {"terminateDebuggee": getattr(self, "_request", "launch") != "attach"})      # (a program you joined is left running)
                client.proc.waitForBytesWritten(300)
            except RuntimeError:
                pass
            client.stop()
            client.deleteLater()
            if not quiet:
                self._say("Detached: the program is still running." if getattr(self, "_request", "launch") == "attach" else "Stopped.", "info")
        self._end_helper()
        self._state, self._frames, self._rows, self._where, self._frame = "idle", [], [], ("", -1), -1
        self.changed.emit()

    @Slot()
    def restart(self) -> None:
        if self._launch and getattr(self, "_request", "launch") == "launch":
            self.start(*self._launch[:4], paths=self._launch[8])

    def _end_helper(self) -> None:
        helper, self._helper = getattr(self, "_helper", None), None
        if helper is not None:
            try:
                helper.terminate()
                helper.wait(2)
            except Exception:                                         # noqa: BLE001 (gone already, or not ours to wait for)
                try:
                    helper.kill()
                except Exception:                                     # noqa: BLE001
                    pass

    def _ended(self) -> None:
        self._end_helper()
        if self._client is not None:
            self._client.deleteLater()
            self._client = None
            self._say("The program finished.", "info")
        self._state, self._frames, self._rows, self._where, self._frame = "idle", [], [], ("", -1), -1
        self.changed.emit()

    # -------------------------------------------------------------- what the program tells us
    def _event(self, name: str, body: dict) -> None:
        if name == "initialized":
            self._configure()
        elif name == "stopped":
            if getattr(self, "_request", "launch") == "attach" and not getattr(self, "_joined", False) and body.get("reason") not in ("breakpoint", "step", "exception", "pause", "function breakpoint"):
                # GDB holds a program still when it joins it. Its breakpoints can be placed now that the program's
                # own files are known, and then it is let go on.
                self._joined = True
                for path in list(self._breakpoints):
                    self._send_breakpoints(path)
                self._thread = body.get("threadId") or self._thread or 1
                self._client.request("continue", {"threadId": self._thread}, lambda b, e: None)
                self._state = "running"
                self.changed.emit()
                return
            self._state = "stopped"
            self._reason = {"breakpoint": "Paused at a breakpoint", "step": "Paused after a step", "exception": "Paused on an exception",
                            "pause": "Paused", "entry": "Paused at the start", "function breakpoint": "Paused at a breakpoint"}.get(body.get("reason", ""), "Paused")
            if body.get("text") or body.get("description"):
                self._reason += ": " + (body.get("text") or body.get("description"))
            self._thread = body.get("threadId") or self._thread or 1
            self._fetch_stack()
            self.changed.emit()
        elif name == "continued":
            self._state, self._frames, self._rows, self._where = "running", [], [], ("", -1)
            self.changed.emit()
        elif name == "output":
            cat = body.get("category", "console")
            if cat != "telemetry" and body.get("output"):
                self._say(body["output"], {"stderr": "error", "stdout": "out", "important": "error"}.get(cat, "console"))
        elif name in ("terminated", "exited"):
            if name == "exited":
                self._say(f"The program finished (exit code {body.get('exitCode', 0)}).", "info")
            if name == "terminated":
                if self._client is not None:
                    client, self._client = self._client, None
                    client.gone.disconnect()
                    client.stop()
                    client.deleteLater()
                self._state, self._frames, self._rows, self._where, self._frame = "idle", [], [], ("", -1), -1
                self.changed.emit()
        elif name == "thread" and body.get("reason") == "started" and not self._thread:
            self._thread = body.get("threadId", 1)

    def _fetch_stack(self) -> None:
        def got(body, error):
            if error or self._client is None:
                return
            frames = []
            for f in body.get("stackFrames", []):
                src = f.get("source") or {}
                if src.get("path"):
                    src = dict(src, path=self._here(src["path"]) or src["path"])       # (a file over there that isn't in the project keeps its own path)
                frames.append({"id": f.get("id"), "name": f.get("name", "?"), "file": src.get("path", ""), "short": Path(src.get("path", "") or src.get("name", "")).name,
                               "line": max(0, int(f.get("line", 1)) - 1)})
            self._frames = frames
            mine = next((f for f in frames if f["file"]), frames[0] if frames else None)
            if mine:
                self.selectFrame(mine["id"])
            self.changed.emit()
        self._client.request("stackTrace", {"threadId": self._thread, "startFrame": 0, "levels": 40}, got)

    @Slot(int)
    def selectFrame(self, frame_id: int) -> None:
        f = next((x for x in self._frames if x["id"] == frame_id), None)
        if f is None or self._client is None:
            return
        self._frame = frame_id
        self._where = (f["file"], f["line"])
        if f["file"]:
            self.landed.emit(f["file"], f["line"])
        self._open = set()

        def got(body, error):
            if error or self._client is None:
                return
            scopes = body.get("scopes", [])
            self._rows = [{"ref": s.get("variablesReference", 0), "name": s.get("name", ""), "value": "", "type": "", "depth": 0, "scope": True,
                           "expandable": s.get("variablesReference", 0) > 0, "open": False} for s in scopes]
            self.changed.emit()
            for row in self._rows:                                   # open the first scope (the locals) straight away
                if row["expandable"] and not s_is_big(row["name"]):
                    self.expand(row["ref"])
                    break
        self._client.request("scopes", {"frameId": frame_id}, got)
        self.changed.emit()

    @Slot(int)
    def expand(self, ref: int) -> None:
        """Open (or close) a scope or a variable that holds others."""
        if self._client is None or ref <= 0:
            return
        at = next((i for i, r in enumerate(self._rows) if r["ref"] == ref), -1)
        if at < 0:
            return
        row = self._rows[at]
        if row["open"]:                                              # close: drop everything deeper that follows
            end = at + 1
            while end < len(self._rows) and self._rows[end]["depth"] > row["depth"]:
                end += 1
            self._rows = self._rows[:at + 1] + self._rows[end:]
            row["open"] = False
            self.changed.emit()
            return

        def got(body, error):
            if error or self._client is None:
                return
            i = next((k for k, r in enumerate(self._rows) if r["ref"] == ref), -1)
            if i < 0:
                return
            kids = [{"ref": v.get("variablesReference", 0), "name": v.get("name", ""), "value": str(v.get("value", ""))[:300], "type": v.get("type", ""),
                     "depth": self._rows[i]["depth"] + 1, "scope": False, "expandable": v.get("variablesReference", 0) > 0, "open": False}
                    for v in body.get("variables", []) if not (v.get("name", "").startswith("__") and v.get("name", "").endswith("__")) and v.get("name") != "special variables"]
            self._rows[i]["open"] = True
            self._rows = self._rows[:i + 1] + kids[:500] + self._rows[i + 1:]
            self.changed.emit()
        self._client.request("variables", {"variablesReference": ref}, got)

    # -------------------------------------------------------------- stepping
    def _go(self, command: str) -> None:
        if self._client is None or (self._state != "stopped" and command != "pause"):
            return
        args = {"threadId": self._thread}
        self._client.request(command, args, lambda b, e: self._say(f"{command} didn't work: {e}", "error") if e else None)
        if command != "pause":
            self._state, self._frames, self._rows, self._where = "running", [], [], ("", -1)
            self.changed.emit()

    @Slot()
    def resume(self) -> None:
        self._go("continue")

    @Slot()
    def stepOver(self) -> None:
        self._go("next")

    @Slot()
    def stepIn(self) -> None:
        self._go("stepIn")

    @Slot()
    def stepOut(self) -> None:
        self._go("stepOut")

    @Slot()
    def pause(self) -> None:
        self._go("pause")

    @Slot(str)
    def evaluate(self, expression: str) -> None:
        """Work out an expression in the stopped program (or say it can't while it runs)."""
        expression = expression.strip()
        if not expression:
            return
        self._say("› " + expression, "input")
        if self._client is None:
            self._say("Nothing is being debugged.", "error")
            return

        def got(body, error):
            self._say(str(error) if error else str(body.get("result", "")), "error" if error else "result")
        args = {"expression": expression, "context": "repl"}
        if self._frame >= 0:
            args["frameId"] = self._frame
        self._client.request("evaluate", args, got)

    @Slot()
    def clearConsole(self) -> None:
        self._console = []
        self.printed.emit()


def s_is_big(name: str) -> bool:
    """Globals and the like are opened only when asked: there's a lot in them."""
    return name.lower() in ("globals", "global", "registers", "module")


def saved_program(root: Path) -> str:
    try:
        return (root / ".huginn-debug").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def guess_program(root: Path) -> str:
    """For compiled projects: the newest executable in the usual build folders."""
    best = None
    for folder in ("build", "target/debug", "bin", "out", "cmake-build-debug", "."):
        base = root / folder
        if not base.is_dir():
            continue
        for p in base.iterdir() if folder == "." else base.rglob("*"):
            try:
                if p.is_file() and os.access(p, os.X_OK) and p.suffix in ("", ".out") and not p.name.startswith(".") and p.stat().st_size > 1000:
                    with open(p, "rb") as f:
                        if f.read(4) != b"\x7fELF":
                            continue
                    if best is None or p.stat().st_mtime > best.stat().st_mtime:
                        best = p
            except OSError:
                continue
    return str(best) if best else ""
