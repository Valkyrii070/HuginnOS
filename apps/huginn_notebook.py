"""Notebooks (.ipynb) in Code.

A notebook is cells: Python to run, and text (Markdown) between. The file is Jupyter's own format (nbformat 4), read
and written so Jupyter, VS Code and GitHub open what Code saved and Code opens theirs: cell ids, outputs, execution
counts and the metadata Code doesn't use are all kept.

Code runs the cells itself with huginn_nb_kernel.py: a plain Python (the project's .venv when it has one), no Jupyter
and no ipykernel needed. That is also the limit: IPython's % magics and ! shell lines aren't Python, and say so.

parse() and dump() are plain functions; Kernel is the running Python behind one notebook.
"""
from __future__ import annotations

import json
import os
import re
import signal
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

KERNEL = Path(__file__).resolve().with_name("huginn_nb_kernel.py")
KINDS = ("code", "markdown", "raw")
MAX_TEXT = 400_000                    # the text kept under one cell (the oldest goes first)
MAX_OUTPUTS = 200                     # separate outputs kept under one cell
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _text(value) -> str:
    """nbformat writes text as a string or as a list of lines."""
    if isinstance(value, list):
        return "".join(str(v) for v in value)
    return value if isinstance(value, str) else ""


def _lines(text: str):
    """Text as nbformat writes it: a list of lines, each keeping its line end."""
    return text.splitlines(True)


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def new_cell(kind: str = "code", source: str = "") -> dict:
    return {"id": new_id(), "kind": kind if kind in KINDS else "code", "source": source, "outputs": [], "count": None, "meta": {}, "more": {}}


def parse(text: str) -> dict:
    """A notebook file's text as {cells: [{id, kind, source, outputs (nbformat's own), count, meta, more}], meta,
    minor, more}. A ValueError says why it isn't a notebook Code can read. An empty file is an empty notebook."""
    if not text.strip():
        return {"cells": [new_cell()], "meta": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}}, "minor": 5, "more": {}}
    try:
        raw = json.loads(text)
    except ValueError as err:
        raise ValueError(f"This isn't a notebook: its JSON couldn't be read ({err}).") from err
    if not isinstance(raw, dict) or not isinstance(raw.get("cells"), list):
        if isinstance(raw, dict) and isinstance(raw.get("worksheets"), list):
            raise ValueError("This notebook is in the old format (before 2015). Jupyter can convert it: jupyter nbconvert --to notebook.")
        raise ValueError("This isn't a notebook: it has no cells.")
    if raw.get("nbformat") not in (4, None):
        raise ValueError(f"This notebook is format {raw.get('nbformat')}, and Code reads format 4.")
    cells, seen = [], set()
    for c in raw["cells"]:
        if not isinstance(c, dict):
            continue
        kind = c.get("cell_type") if c.get("cell_type") in KINDS else "raw"
        ident = c.get("id") if isinstance(c.get("id"), str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", c["id"]) and c["id"] not in seen else new_id()
        seen.add(ident)
        cells.append({"id": ident, "kind": kind, "source": _text(c.get("source")),
                      "outputs": [o for o in c.get("outputs") if isinstance(o, dict)] if kind == "code" and isinstance(c.get("outputs"), list) else [],
                      "count": c.get("execution_count") if isinstance(c.get("execution_count"), int) else None,
                      "meta": c.get("metadata") if isinstance(c.get("metadata"), dict) else {},
                      "more": {k: v for k, v in c.items() if k not in ("id", "cell_type", "source", "outputs", "execution_count", "metadata")}})
    return {"cells": cells, "meta": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
            "minor": raw.get("nbformat_minor") if isinstance(raw.get("nbformat_minor"), int) else 5,
            "more": {k: v for k, v in raw.items() if k not in ("cells", "metadata", "nbformat", "nbformat_minor")}}


def dump(nb: dict) -> str:
    """The notebook as Jupyter writes it (one space of indent, keys in order, a last newline)."""
    cells = []
    for c in nb["cells"]:
        row = dict(c.get("more") or {}, cell_type=c["kind"], id=c["id"], metadata=c.get("meta") or {}, source=_lines(c["source"]))
        if c["kind"] == "code":
            row.update(execution_count=c.get("count"), outputs=c.get("outputs") or [])
        cells.append(row)
    out = dict(nb.get("more") or {}, cells=cells, metadata=nb.get("meta") or {}, nbformat=4, nbformat_minor=max(5, int(nb.get("minor") or 5)))
    return json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def plain(text: str) -> str:
    """Terminal colours taken out (tracebacks from IPython carry them)."""
    return _ANSI.sub("", text)


def shown(outputs: list) -> list:
    """A cell's outputs as what the window draws: [{kind: "text"|"error"|"image"|"html"|"markdown", text, src}]."""
    rows = []
    for o in outputs:
        kind = o.get("output_type")
        if kind == "stream":
            text = plain(_text(o.get("text")))
            if rows and rows[-1]["kind"] == ("error" if o.get("name") == "stderr" else "text") and rows[-1].get("stream"):
                rows[-1]["text"] += text
            else:
                rows.append({"kind": "error" if o.get("name") == "stderr" else "text", "text": text, "src": "", "stream": True})
        elif kind == "error":
            tb = o.get("traceback") if isinstance(o.get("traceback"), list) else []
            rows.append({"kind": "error", "text": plain("\n".join(str(t) for t in tb)) or f"{o.get('ename', 'Error')}: {o.get('evalue', '')}", "src": ""})
        elif kind in ("execute_result", "display_data"):
            data = o.get("data") if isinstance(o.get("data"), dict) else {}
            if isinstance(data.get("image/png"), (str, list)) or isinstance(data.get("image/jpeg"), (str, list)):
                mime = "image/png" if "image/png" in data else "image/jpeg"
                rows.append({"kind": "image", "text": "", "src": f"data:{mime};base64," + _text(data[mime]).replace("\n", "")})
            elif "image/svg+xml" in data:
                import base64
                rows.append({"kind": "image", "text": "", "src": "data:image/svg+xml;base64," + base64.b64encode(_text(data["image/svg+xml"]).encode()).decode("ascii")})
            elif "text/markdown" in data:
                rows.append({"kind": "markdown", "text": _text(data["text/markdown"]), "src": ""})
            elif "text/html" in data and "<script" not in _text(data["text/html"]).lower():
                rows.append({"kind": "html", "text": _text(data["text/html"]), "src": ""})
            elif "text/plain" in data:
                rows.append({"kind": "text", "text": _text(data["text/plain"]), "src": ""})
    for r in rows:
        if r.pop("stream", None) and r["text"].endswith("\n"):
            r["text"] = r["text"][:-1]                              # (print's own last line end isn't an empty line to show)
        if len(r["text"]) > MAX_TEXT:
            r["text"] = "… (the start of this output isn't shown)\n" + r["text"][-MAX_TEXT:]
    return rows


def add_output(cell: dict, msg: dict) -> None:
    """Put what the kernel said under the cell, as nbformat keeps it."""
    outs, kind = cell["outputs"], msg.get("type")
    if kind == "stream":
        name, text = ("stderr" if msg.get("name") == "stderr" else "stdout"), str(msg.get("text", ""))
        if outs and outs[-1].get("output_type") == "stream" and outs[-1].get("name") == name:
            joined = _text(outs[-1].get("text")) + text
            outs[-1]["text"] = _lines(joined[-MAX_TEXT:])
        else:
            outs.append({"output_type": "stream", "name": name, "text": _lines(text[-MAX_TEXT:])})
    elif kind in ("result", "display"):
        data = {k: (_lines(v) if k.startswith("text/") or k == "image/svg+xml" else v) for k, v in (msg.get("data") or {}).items() if isinstance(v, str)}
        row = {"output_type": "execute_result" if kind == "result" else "display_data", "data": data, "metadata": {}}
        if kind == "result":
            row["execution_count"] = msg.get("count")
        outs.append(row)
    elif kind == "error":
        outs.append({"output_type": "error", "ename": str(msg.get("ename", "Error")), "evalue": str(msg.get("evalue", "")), "traceback": [str(t) for t in msg.get("traceback") or []]})
    if len(outs) > MAX_OUTPUTS:
        del outs[:len(outs) - MAX_OUTPUTS]


def not_python(source: str) -> str:
    """IPython's own lines, which a plain Python can't run: said before the cell is tried ("" when there are none)."""
    for line in source.splitlines():
        s = line.lstrip()
        if s.startswith("%%") or (s.startswith("%") and re.match(r"%[A-Za-z_]", s)):
            return f"“{s.split()[0]}” is an IPython magic, not Python. Code runs plain Python: take the line out, or do the same in Python."
        if s.startswith("!") and len(s) > 1:
            return "A line starting with ! is IPython's way to run a shell command. In plain Python: import subprocess; subprocess.run([...])"
    return ""


def python_for(folder) -> str:
    """The Python that runs a notebook: the project's own .venv (or venv) when it has one, else python3."""
    folder = Path(folder)
    for base in [folder] + list(folder.parents)[:6]:
        for name in (".venv", "venv"):
            cand = base / name / "bin" / "python"
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
    return "python3"


class Kernel(QObject):
    """The Python behind one notebook. Cells are queued; said(message) carries each JSON line the kernel writes;
    idle() says the queue is empty; gone(why) says the Python has ended."""
    said = Signal(dict)
    idle = Signal()
    gone = Signal(str)

    def __init__(self, folder: str, python: str = "", parent=None):
        super().__init__(parent)
        self._folder, self._python = folder, python or python_for(folder)
        self._proc, self._queue, self._running, self._buf, self._about = None, [], "", b"", {}

    python = property(lambda self: self._python)
    about = property(lambda self: dict(self._about))
    running = property(lambda self: self._running)
    queued = property(lambda self: [q[0] for q in self._queue])
    alive = property(lambda self: self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning)

    def _start(self) -> None:
        proc = QProcess(self)
        proc.setWorkingDirectory(self._folder)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        env.remove("QT_QPA_PLATFORM")
        proc.setProcessEnvironment(env)
        proc.readyReadStandardOutput.connect(self._read)
        proc.readyReadStandardError.connect(self._read_err)
        proc.finished.connect(self._ended)
        proc.errorOccurred.connect(self._failed)
        self._proc, self._buf = proc, b""
        proc.start(self._python, ["-u", str(KERNEL)])

    def run(self, cell_id: str, code: str) -> None:
        self._queue.append((cell_id, code))
        if self._proc is None:
            self._start()
        self._next()

    def _next(self) -> None:
        if self._running or not self._queue or self._proc is None:
            return
        cell_id, code = self._queue.pop(0)
        self._running = cell_id
        self._proc.write((json.dumps({"id": cell_id, "code": code}) + "\n").encode("utf-8"))

    def _read(self) -> None:
        self._buf += bytes(self._proc.readAllStandardOutput())
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "ready":
                self._about = msg
                continue
            self.said.emit(msg)
            if msg.get("type") == "done":
                self._running = ""
                if self._queue:
                    self._next()
                else:
                    self.idle.emit()

    def _read_err(self) -> None:
        text = bytes(self._proc.readAllStandardError()).decode("utf-8", "replace")
        if text and self._running:                                   # what a child program printed, or Python's own dying words
            self.said.emit({"id": self._running, "type": "stream", "name": "stderr", "text": text})

    def interrupt(self) -> None:
        """Stop the running cell (and drop the ones waiting); the names made so far stay."""
        self._queue = []
        if self.alive and self._running:
            try:
                os.kill(self._proc.processId(), signal.SIGINT)
            except OSError:
                pass

    def _failed(self, _error) -> None:
        if self._proc is not None and self._proc.state() == QProcess.ProcessState.NotRunning:
            self._ended(-1, None)

    def _ended(self, code=0, _status=None) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        was, self._running, self._queue = self._running, "", []
        proc.deleteLater()
        why = (f"{self._python} couldn't be started." if code == -1 and not self._about else
               "The notebook's Python ended while this cell ran (it crashed, or was told to exit)." if was else "")
        if was:
            self.said.emit({"id": was, "type": "error", "ename": "KernelDied", "evalue": why, "traceback": [why]})
            self.said.emit({"id": was, "type": "done", "count": None, "ok": False})
        self.gone.emit(why)

    def stop(self) -> None:
        """End the Python: every name it held is forgotten."""
        proc, self._proc = self._proc, None
        self._queue, self._running, self._about = [], "", {}
        if proc is not None:
            for sig in (proc.readyReadStandardOutput, proc.readyReadStandardError, proc.finished, proc.errorOccurred):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass
            proc.kill()
            proc.waitForFinished(1500)
            proc.deleteLater()
