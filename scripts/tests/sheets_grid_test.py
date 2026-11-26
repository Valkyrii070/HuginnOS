"""Sheets: the everyday commands, and that a cell place off the grid (before A1, a billion rows down, a selection named
backwards, a height that is not a number) is brought onto it instead of costing the sheet.
    python3 sheets_grid_test.py <kit root>"""
import os, shutil, sys, tempfile
ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
if os.geteuid() == 0:
    sys.exit("not as root: this writes and removes files")
home = tempfile.mkdtemp(prefix="shtry-"); os.environ.update(HOME=home, QT_QPA_PLATFORM="offscreen")
sys.path[:0] = [ROOT + "/apps", ROOT + "/shell"]
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
import huginn_sheets as hs
s = hs.Sheets(False)
s.create()
ok = fail = 0
def check(what, cond, extra=""):
    global ok, fail
    if cond: ok += 1
    else: fail += 1; print("FAIL", what, extra)
for r, v in enumerate(["3", "1", "2"]): s.put(r, 0, v)
s.put(0, 1, "=A1*2")
check("put and formula", s.shown(0, 1) == "6", s.shown(0, 1))
s.fill(0, 1, 0, 1, 2, 1)
check("fill down", [s.shown(r, 1) for r in range(3)] == ["6", "2", "4"], [s.shown(r, 1) for r in range(3)])
s.sort(0, 0, 2, 0, 0, False, False)
check("sort", [s.raw(r, 0) for r in range(3)] == ["1", "2", "3"], [s.raw(r, 0) for r in range(3)])
text = s.copy(0, 0, 2, 0, False)
check("copy text", text == "1\n2\n3", repr(text))
s.paste(0, 3, 0, 3, "")
check("paste", [s.raw(r, 3) for r in range(3)] == ["1", "2", "3"], [s.raw(r, 3) for r in range(3)])
check("selection named backwards", s.copy(2, 0, 0, 0, False) == "1\n2\n3")
s.put(-5, -5, "x"); check("a place before A1 lands on A1", s.raw(0, 0) == "x")
s.setFormat(0, 0, 2, 0, "b", True); check("format", s.fmtAt(1, 0).get("b") is True, s.fmtAt(1, 0))
s.clear(0, 3, 2, 3, "contents"); check("clear", s.raw(1, 3) == "")
s.setRowHeight(1, float("nan")); check("odd height", s.rowHeight(1) > 0)
check("export refuses odd kinds", s.export("../x") == "")
out = s.export("csv"); check("export csv", out.endswith(".csv") and os.path.exists(out), out)
s.fill(0, 0, 0, 0, 10**9, 0); check("fill far stays on the grid", max(r for r, c in s.sh["raw"]) < s.rows)
print(f"{ok} passed, {fail} failed")
shutil.rmtree(home, ignore_errors=True)
sys.exit(1 if fail else 0)
