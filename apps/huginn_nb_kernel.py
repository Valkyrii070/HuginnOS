"""The program that runs a notebook's cells for Code: one Python, kept alive, with one set of names for all cells.

Code writes one JSON line per cell to run ({"id": cell, "code": text}); this answers with JSON lines on its own pipe:
    {"id", "type": "stream", "name": "stdout"|"stderr", "text"}
    {"id", "type": "result", "data": {"text/plain": …, "text/html": …, "image/png": base64, …}}     the last line's value
    {"id", "type": "display", "data": {…}}                                                          display(x), a figure
    {"id", "type": "error", "ename", "evalue", "traceback": [lines]}
    {"id", "type": "done", "count": n, "ok": bool}
It needs nothing but Python itself. With matplotlib there, figures left open by a cell are shown under it; anything
with _repr_html_ / _repr_png_ / _repr_svg_ / _repr_markdown_ (pandas tables, PIL images, sympy) shows that way.
Ctrl+C from Code arrives as SIGINT and stops the running cell, not the program.
"""
import ast
import base64
import builtins
import io
import json
import os
import sys
import traceback

proto = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)      # the pipe to Code
os.dup2(2, 1)                                                           # (what a child program prints goes to stderr's pipe, not into the conversation)
os.environ.setdefault("MPLBACKEND", "Agg")
current = {"id": ""}
CAP = 2_000_000                                                         # one piece of output


def send(kind: str, **more) -> None:
    proto.write(json.dumps(dict(more, id=current["id"], type=kind)) + "\n")
    proto.flush()


class Stream(io.TextIOBase):
    def __init__(self, name):
        self.name_ = name

    def writable(self):
        return True

    def write(self, text):
        text = str(text)
        if text:
            send("stream", name=self.name_, text=text[:CAP])
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


def bundle(value) -> dict:
    """What a value looks like, in every way it offers."""
    data = {}
    for mime, method in (("text/html", "_repr_html_"), ("text/markdown", "_repr_markdown_"), ("image/svg+xml", "_repr_svg_"), ("image/png", "_repr_png_"), ("image/jpeg", "_repr_jpeg_")):
        fn = getattr(value, method, None)
        if callable(fn) and not isinstance(value, type):
            try:
                got = fn()
            except Exception:                                           # noqa: BLE001 (its own repr failing must not fail the cell)
                continue
            if isinstance(got, tuple):
                got = got[0]
            if isinstance(got, bytes):
                got = base64.b64encode(got).decode("ascii")
            if isinstance(got, str) and got and len(got) <= 8 * CAP:
                data[mime] = got
    try:
        data["text/plain"] = repr(value)[:CAP]
    except Exception as err:                                            # noqa: BLE001
        data["text/plain"] = f"<a value whose repr failed: {err}>"
    return data


def display(*values) -> None:
    for v in values:
        send("display", data=bundle(v))


def figures() -> None:
    """Matplotlib figures the cell left open, shown under it and closed."""
    plt = sys.modules.get("matplotlib.pyplot")
    if plt is None:
        return
    try:
        for num in plt.get_fignums():
            buf = io.BytesIO()
            plt.figure(num).savefig(buf, format="png", bbox_inches="tight", dpi=110)
            send("display", data={"image/png": base64.b64encode(buf.getvalue()).decode("ascii"), "text/plain": "<Figure>"})
        plt.close("all")
    except Exception:                                                   # noqa: BLE001
        traceback.print_exc()


def no_input(prompt=""):
    raise RuntimeError("input() isn't answered in a notebook here: put the value in a variable in its own cell.")


def run(code: str, names: dict, count: int) -> bool:
    label = f"<cell {count}>"
    try:
        tree = ast.parse(code, label, "exec")
        last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
        import linecache
        linecache.cache[label] = (len(code), None, code.splitlines(True), label)       # so a traceback can show the cell's own lines
        exec(compile(tree, label, "exec"), names)                       # noqa: S102 (running the user's code is the point)
        if last is not None:
            value = eval(compile(ast.Expression(last.value), label, "eval"), names)     # noqa: S307
            if value is not None:
                names["_"] = value
                send("result", data=bundle(value), count=count)
        figures()
        return True
    except KeyboardInterrupt:
        send("error", ename="KeyboardInterrupt", evalue="Stopped.", traceback=["Stopped."])
    except SystemExit as err:
        send("error", ename="SystemExit", evalue=str(err.code), traceback=[f"The cell asked to exit ({err.code}). The notebook keeps running."])
    except BaseException as err:                                        # noqa: BLE001 (whatever the cell raises is its output)
        tb = traceback.extract_tb(err.__traceback__)
        mine = [] if isinstance(err, SyntaxError) and err.filename == label else [f for f in tb if f.filename != __file__]     # (a cell that doesn't parse: only say where)
        lines = traceback.format_list(mine) + traceback.format_exception_only(type(err), err)
        send("error", ename=type(err).__name__, evalue=str(err)[:4000], traceback=[l.rstrip("\n") for l in lines][-60:])
    return False


def main() -> None:
    names = {"__name__": "__main__", "__builtins__": builtins, "display": display}
    builtins.input = no_input
    sys.stdout, sys.stderr = Stream("stdout"), Stream("stderr")
    sys.path.insert(0, os.getcwd())
    count = 0
    current["id"] = ""
    send("ready", python=sys.version.split()[0], executable=sys.executable)
    while True:
        try:
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            continue                                                    # (Stop pressed with nothing running)
        if not line:
            return
        try:
            req = json.loads(line)
        except ValueError:
            continue
        current["id"], count = str(req.get("id", "")), count + 1
        ok = run(str(req.get("code", "")), names, count)
        try:
            sys.stdout.flush()
        except KeyboardInterrupt:
            pass
        send("done", count=count, ok=ok)
        current["id"] = ""


if __name__ == "__main__":
    main()
