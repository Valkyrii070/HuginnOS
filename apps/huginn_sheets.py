"""Huginn Sheets: the spreadsheet behind Sheets.qml.

A workbook of sheets; each sheet keeps what was typed in each cell, how each cell looks (bold, colours, alignment,
number format...), its column widths and row heights, frozen rows and columns, a filter and its charts. The
arithmetic is huginn_sheet_engine's. Files: Huginn's own .hsheet (JSON), CSV, and Excel's .xlsx both ways
(huginn_xlsx); older formats through LibreOffice (huginn_office.Bridge).
"""
import copy
import csv
import io
import json
import math
import re
from pathlib import Path

from PySide6.QtCore import Property, QAbstractTableModel, QLocale, QModelIndex, QObject, Qt, Signal, Slot
from PySide6.QtGui import QFont, QFontMetrics

import huginn_sheet_engine as se
import huginn_sheet_rules as rules_
import huginn_sheet_checks as checks_
import huginn_xlsx as xlsx
from huginn_office import FileList, fresh_path, note_recent, write_atomic

COL_W, ROW_H = 100, 26
PALETTE = ["#4C6EF5", "#F59F00", "#12B886", "#E64980", "#7950F2", "#15AABF", "#FA5252", "#82C91E"]
FUNCTION_HELP = {
    "SUM": "SUM(numbers…): adds them up", "AVERAGE": "AVERAGE(numbers…): the mean", "COUNT": "COUNT(cells…): how many numbers",
    "COUNTA": "COUNTA(cells…): how many aren't empty", "MIN": "MIN(numbers…)", "MAX": "MAX(numbers…)", "IF": "IF(test, if true, if false)",
    "IFERROR": "IFERROR(value, if it's an error)", "SUMIF": "SUMIF(range, test, [what to add])", "SUMIFS": "SUMIFS(what to add, range, test, …)",
    "COUNTIF": "COUNTIF(range, test)", "COUNTIFS": "COUNTIFS(range, test, …)", "AVERAGEIF": "AVERAGEIF(range, test, [what to average])",
    "VLOOKUP": "VLOOKUP(value, table, column, [FALSE for exact])", "XLOOKUP": "XLOOKUP(value, look in, give back, [if missing])",
    "INDEX": "INDEX(range, row, [column])", "MATCH": "MATCH(value, range, [0 for exact])", "ROUND": "ROUND(number, places)",
    "CONCAT": "CONCAT(text…)", "TEXTJOIN": "TEXTJOIN(between, skip empty, text…)", "LEFT": "LEFT(text, [how many])", "RIGHT": "RIGHT(text, [how many])",
    "MID": "MID(text, start, how many)", "LEN": "LEN(text)", "TRIM": "TRIM(text)", "UPPER": "UPPER(text)", "LOWER": "LOWER(text)",
    "TODAY": "TODAY(): today's date", "NOW": "NOW(): the date and time", "DATE": "DATE(year, month, day)", "YEAR": "YEAR(date)",
    "MONTH": "MONTH(date)", "DAY": "DAY(date)", "EDATE": "EDATE(date, months)", "EOMONTH": "EOMONTH(date, months)", "DATEDIF": "DATEDIF(start, end, \"Y\"|\"M\"|\"D\")",
    "NETWORKDAYS": "NETWORKDAYS(start, end, [holidays])", "PMT": "PMT(rate, periods, amount)", "FV": "FV(rate, periods, payment, [now])",
    "PV": "PV(rate, periods, payment)", "NPV": "NPV(rate, flows…)", "IRR": "IRR(flows)", "SUMPRODUCT": "SUMPRODUCT(range, range…)",
    "MEDIAN": "MEDIAN(numbers…)", "STDEV": "STDEV(numbers…)", "TEXT": "TEXT(value, \"format\")", "VALUE": "VALUE(text)", "AND": "AND(tests…)",
    "OR": "OR(tests…)", "NOT": "NOT(test)", "IFS": "IFS(test, value, test, value…)", "SWITCH": "SWITCH(value, match, result, …, [otherwise])",
    "UNIQUE": "UNIQUE(range)", "SORT": "SORT(range, [column], [1 or -1])", "FILTER": "FILTER(range, tests, [if none])"}


def a1(r: int, c: int) -> str:
    return se.ref_name(r, c)


def span_name(r0, c0, r1, c1) -> str:
    return a1(r0, c0) if (r0, c0) == (r1, c1) else f"{a1(r0, c0)}:{a1(r1, c1)}"


def parse_span(text: str):
    t = text.strip().upper().replace("$", "")
    if ":" in t:
        a, b = t.split(":", 1)
        p, q = se.parse_cell(a), se.parse_cell(b)
        if p and q:
            return min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])
        return None
    p = se.parse_cell(t)
    return (p[0], p[1], p[0], p[1]) if p else None


def _me() -> str:
    """Who notes are signed by: the account's full name, else its user name."""
    try:
        import os
        import pwd
        entry = pwd.getpwuid(os.getuid())
        return (entry.pw_gecos or "").split(",")[0].strip() or entry.pw_name
    except (ImportError, KeyError):
        return "Me"


def blank_sheet(name: str) -> dict:
    return {"name": name, "raw": {}, "fmt": {}, "widths": {}, "heights": {}, "freeze": [0, 0], "filter": None, "charts": [], "merges": [], "rules": [], "pivot": None,
            "checks": [], "notes": {}}


# ------------------------------------------------------------------------------------------------ the grid, for TableView
class Grid(QAbstractTableModel):
    """One pane of the sheet in front (Sheets draws up to four: frozen rows and columns, and the rest), from (r0, c0)."""
    CELL = Qt.UserRole + 1

    def __init__(self, owner, r0=0, c0=0, rows=-1, cols=-1):
        super().__init__()
        self.owner, self.r0, self.c0, self._rows, self._cols = owner, r0, c0, rows, cols

    def rowCount(self, parent=QModelIndex()):
        return self._rows if self._rows >= 0 else max(0, self.owner.rows - self.r0)

    def columnCount(self, parent=QModelIndex()):
        return self._cols if self._cols >= 0 else max(0, self.owner.cols - self.c0)

    def roleNames(self):
        return {Qt.DisplayRole: b"display", self.CELL: b"cell"}

    def data(self, index, role=Qt.DisplayRole):
        r, c = index.row() + self.r0, index.column() + self.c0
        if role == Qt.DisplayRole:
            return self.owner.shown(r, c)
        if role == self.CELL:
            return self.owner.cell(r, c)
        return None

    def reset(self, r0=None, c0=None, rows=None, cols=None):
        self.beginResetModel()
        if r0 is not None:
            self.r0, self.c0, self._rows, self._cols = r0, c0, rows, cols
        self.endResetModel()

    def refresh(self):
        n, m = self.rowCount(), self.columnCount()
        if n and m:
            self.dataChanged.emit(self.index(0, 0), self.index(n - 1, m - 1))


class Heads(QAbstractTableModel):
    """Column letters (one row) or row numbers (one column) for a pane, from `start`, `count` of them (-1: to the end)."""

    def __init__(self, owner, axis: str, start=0, count=-1):
        super().__init__()
        self.owner, self.axis, self.start, self.count = owner, axis, start, count

    def _n(self):
        if self.count >= 0:
            return self.count
        return max(0, (self.owner.cols if self.axis == "c" else self.owner.rows) - self.start)

    def rowCount(self, parent=QModelIndex()):
        return 1 if self.axis == "c" else self._n()

    def columnCount(self, parent=QModelIndex()):
        return self._n() if self.axis == "c" else 1

    def roleNames(self):
        return {Qt.DisplayRole: b"display", Qt.UserRole: b"at"}

    def data(self, index, role=Qt.DisplayRole):
        k = (index.column() if self.axis == "c" else index.row()) + self.start
        if role == Qt.UserRole:
            return k
        return se.col_name(k) if self.axis == "c" else str(k + 1)

    def reset(self, start, count):
        self.beginResetModel()
        self.start, self.count = start, count
        self.endResetModel()


# ------------------------------------------------------------------------------------------------ Sheets
class Sheets(FileList):
    NATIVE, OWN, VIA_BRIDGE, MODERN, STEM = (".hsheet", ".csv"), (".xlsx",), (".ods", ".xls"), "xlsx", "Untitled Sheet"
    MAX_SHEETS = 64
    sheetsChanged = Signal()
    gridChanged = Signal()
    chartsChanged = Signal()
    historyChanged = Signal()
    refused = Signal(str)          # what was typed didn't go in (or went in with a warning): why

    def __init__(self, target: Path = None):
        super().__init__(target)
        self.book = se.Book()
        self.book.day_first = QLocale.system().dateFormat(QLocale.ShortFormat).lower().startswith("d")
        self.book.sheets = [blank_sheet("Sheet 1")]
        self.looks = rules_.Rules(self.book)
        self._at = 0
        self._undo, self._redo = [], []
        self.historyChanged.emit()
        self._clip = None
        self.rows, self.cols = 1000, 26
        self.main, self.top, self.left, self.corner = Grid(self), Grid(self, 0, 0, 0, 0), Grid(self, 0, 0, 0, 0), Grid(self, 0, 0, 0, 0)
        self.heads = {"c": Heads(self, "c"), "cf": Heads(self, "c", 0, 0), "r": Heads(self, "r"), "rf": Heads(self, "r", 0, 0)}
        self.changed.connect(self.sheetsChanged)
        if self._extra:
            self.open(str(self._extra))

    # ------------------------------------------------------------------ what QML sees
    @property
    def sh(self) -> dict:
        return self.book.sheets[self._at]

    sheetNames = Property("QVariantList", lambda self: [s["name"] for s in self.book.sheets], notify=sheetsChanged)
    sheetIndex = Property(int, lambda self: self._at, notify=sheetsChanged)
    oneSheetOnly = Property(bool, lambda self: self._path is not None and self._path.suffix.lower() == ".csv", notify=sheetsChanged)
    mainGrid = Property(QObject, lambda self: self.main, constant=True)
    topGrid = Property(QObject, lambda self: self.top, constant=True)
    leftGrid = Property(QObject, lambda self: self.left, constant=True)
    cornerGrid = Property(QObject, lambda self: self.corner, constant=True)
    colHeads = Property(QObject, lambda self: self.heads["c"], constant=True)
    colHeadsFrozen = Property(QObject, lambda self: self.heads["cf"], constant=True)
    rowHeads = Property(QObject, lambda self: self.heads["r"], constant=True)
    rowHeadsFrozen = Property(QObject, lambda self: self.heads["rf"], constant=True)
    rowCount = Property(int, lambda self: self.rows, notify=gridChanged)
    colCount = Property(int, lambda self: self.cols, notify=gridChanged)
    frozen = Property("QVariantList", lambda self: list(self.sh["freeze"]), notify=gridChanged)
    canUndo = Property(bool, lambda self: bool(self._undo), notify=historyChanged)
    canRedo = Property(bool, lambda self: bool(self._redo), notify=historyChanged)
    filterRange = Property("QVariantList", lambda self: list(self.sh["filter"]["range"]) if self.sh.get("filter") else [], notify=gridChanged)
    filterCols = Property("QVariantList", lambda self: sorted(int(k) for k, v in self.sh["filter"]["hide"].items() if v) if self.sh.get("filter") else [],
                          notify=gridChanged)
    functionNames = Property("QVariantList", lambda self: se.NAMES, constant=True)
    formats = Property("QVariantList", lambda self: [{"name": n, "code": c, "example": e} for n, c, e in se.FORMATS], constant=True)

    @Slot(str, result=str)
    def functionHelp(self, name: str) -> str:
        return FUNCTION_HELP.get(name.upper(), f"{name.upper()}(…)" if name.upper() in se.NAMES else "")

    def _size(self) -> None:
        """Enough rows and columns for what's there, and room beyond."""
        ur, uc = self.book.used(self._at)
        rows, cols = max(1000, ur + 200), min(se.MAX_COLS, max(26, uc + 6))
        if (rows, cols) != (self.rows, self.cols):
            self.rows, self.cols = rows, cols
            self._panes()

    def _panes(self) -> None:
        fr, fc = self.sh["freeze"]
        self.main.reset(fr, fc, -1, -1)
        self.top.reset(0, fc, fr, -1)
        self.left.reset(fr, 0, -1, fc)
        self.corner.reset(0, 0, fr, fc)
        self.heads["c"].reset(fc, -1)
        self.heads["cf"].reset(0, fc)
        self.heads["r"].reset(fr, -1)
        self.heads["rf"].reset(0, fr)
        self.gridChanged.emit()

    def _refresh(self) -> None:
        self.book.changed()
        self.looks.forget()
        old = (self.rows, self.cols)
        self._size()
        if (self.rows, self.cols) == old:
            for g in (self.main, self.top, self.left, self.corner):
                g.refresh()
        self.chartsChanged.emit()

    @Slot(int)
    def growTo(self, row: int) -> None:
        """The view came near the last row or column: more of them."""
        if row > self.rows - 60:
            self.rows = row + 500
            self._panes()

    @Slot(int)
    def growCols(self, col: int) -> None:
        if col > self.cols - 3 and self.cols < se.MAX_COLS:
            self.cols = min(se.MAX_COLS, col + 10)
            self._panes()

    # ------------------------------------------------------------------ cells
    def fmt_of(self, r: int, c: int) -> dict:
        return self.sh["fmt"].get((r, c)) or {}

    def shown(self, r: int, c: int) -> str:
        v = self.book.value(self._at, r, c)
        f = self.fmt_of(r, c).get("num", "")
        if f == "short-date":
            f = "d/m/yyyy" if self.book.day_first else "m/d/yyyy"
        return se.format_value(v, f)

    def cell(self, r: int, c: int) -> dict:
        v = self.book.value(self._at, r, c)
        f = self.fmt_of(r, c)
        number = isinstance(v, (int, float)) and not isinstance(v, bool)
        hidden = self._hidden(r)
        out = {"t": self.shown(r, c), "n": number, "e": isinstance(v, se.Err), "h": hidden}
        if f:
            out.update({k: f[k] for k in ("b", "i", "u", "s", "color", "fill", "align", "wrap", "size", "font") if k in f})
        if "align" not in out:
            out["align"] = "right" if number else ("center" if isinstance(v, (bool, se.Err)) else "left")
        if self.sh.get("rules"):
            out.update(self.looks.look(self._at, self.sh["rules"], r, c))
        if self.sh.get("notes") and (r, c) in self.sh["notes"]:
            out["note"] = True
        if self.sh.get("checks"):
            chk = self.check_at(r, c)
            if chk and chk["kind"] == "list":
                out["pick"] = True
        if self.sh.get("merges"):
            m = self.merge_at(r, c)
            if m:
                if (r, c) == (m[0], m[1]):
                    out["span"] = [m[2] - m[0] + 1, m[3] - m[1] + 1]       # rows, columns: the first cell draws them all
                else:
                    out["covered"] = True
                    out["t"] = ""
        return out

    # ------------------------------------------------------------------ merged cells (Excel's mergeCells)
    def merges(self) -> list:
        """The sheet's merged cells as [r0, c0, r1, c1]; they're kept as Excel writes them ("A1:C1")."""
        key = tuple(self.sh.get("merges") or ())
        if getattr(self, "_merge_key", None) != (id(self.sh), key):
            spans = []
            for text in key:
                got = parse_span(text) if isinstance(text, str) else None
                if got and (got[0], got[1]) != (got[2], got[3]):
                    spans.append(list(got))
            self._merge_key, self._merge_spans = (id(self.sh), key), spans
            self._merge_cells = {(r, c): m for m in spans for r in range(m[0], m[2] + 1) for c in range(m[1], m[3] + 1)} \
                if sum((m[2] - m[0] + 1) * (m[3] - m[1] + 1) for m in spans) <= 200_000 else None
        return self._merge_spans

    def merge_at(self, r: int, c: int):
        spans = self.merges()
        if not spans:
            return None
        if self._merge_cells is not None:
            return self._merge_cells.get((r, c))
        return next((m for m in spans if m[0] <= r <= m[2] and m[1] <= c <= m[3]), None)

    @Slot(int, int, result="QVariantList")
    def mergeAt(self, r: int, c: int) -> list:
        m = self.merge_at(r, c)
        return list(m) if m else []

    @Slot(int, int, int, int, result="QVariantList")
    def mergeBounds(self, r0: int, c0: int, r1: int, c1: int) -> list:
        """The selection grown until no merged cell is cut by its edges."""
        spans = self.merges()
        grown = True
        while grown and spans:
            grown = False
            for m in spans:
                if m[2] >= r0 and m[0] <= r1 and m[3] >= c0 and m[1] <= c1:
                    n0, n1, d0, d1 = min(r0, m[0]), max(r1, m[2]), min(c0, m[1]), max(c1, m[3])
                    if (n0, n1, d0, d1) != (r0, r1, c0, c1):
                        r0, r1, c0, c1, grown = n0, n1, d0, d1, True
        return [r0, c0, r1, c1]

    @Slot(int, int, int, int, result=str)
    def mergeCells(self, r0: int, c0: int, r1: int, c1: int) -> str:
        """Merge and centre, as Excel's button: one cell over these, keeping the first cell's value (the others'
        values go, as in Excel), centred. Returns what to tell the person, or ''."""
        r0, c0, r1, c1 = self.mergeBounds(r0, c0, r1, c1)
        if (r0, c0) == (r1, c1):
            return "Choose two or more cells to merge."
        self._keep("merge")
        lost = [k for k in self.sh["raw"] if r0 <= k[0] <= r1 and c0 <= k[1] <= c1 and k != (r0, c0)]
        for k in lost:
            self.sh["raw"].pop(k, None)
        kept = [t for t in self.sh.get("merges") or [] if not ((m := parse_span(t)) and m[2] >= r0 and m[0] <= r1 and m[3] >= c0 and m[1] <= c1)]
        kept.append(span_name(r0, c0, r1, c1))
        self.sh["merges"] = kept
        f = dict(self.sh["fmt"].get((r0, c0)) or {})
        f["align"] = "center"
        self.sh["fmt"][(r0, c0)] = f
        self._done()
        return f"Merged. Only the first cell's value is kept ({len(lost)} other {'value' if len(lost) == 1 else 'values'} went)." if lost else ""

    @Slot(int, int, int, int, result=bool)
    def unmergeCells(self, r0: int, c0: int, r1: int, c1: int) -> bool:
        merges = self.sh.get("merges") or []
        kept = [t for t in merges if not ((m := parse_span(t)) and m[2] >= r0 and m[0] <= r1 and m[3] >= c0 and m[1] <= c1)]
        if len(kept) == len(merges):
            return False
        self._keep("merge")
        self.sh["merges"] = kept
        self._done()
        return True

    @Slot(int, int, result=str)
    def raw(self, r: int, c: int) -> str:
        return self.sh["raw"].get((r, c), "")

    @Slot(int, int, result="QVariantMap")
    def fmtAt(self, r: int, c: int) -> dict:
        f = dict(self.fmt_of(r, c))
        f.setdefault("num", "General")
        return f

    @Slot(int, int, result=str)
    def name(self, r: int, c: int) -> str:
        return a1(r, c)

    @Slot(result="QVariantList")
    def lastCell(self) -> list:
        """Ctrl+End: the last row and the last column that have anything in them."""
        keys = self.sh["raw"].keys()
        return [max((k[0] for k in keys), default=0), max((k[1] for k in keys), default=0)]

    @Slot(int, int, int, int, result="QVariantList")
    def edge(self, r: int, c: int, dr: int, dc: int) -> list:
        """Ctrl+arrow: to the edge of the block of filled cells (or the next filled cell, or the sheet's edge)."""
        raw = self.sh["raw"]
        filled = lambda rr, cc: (rr, cc) in raw          # noqa: E731
        limit_r, limit_c = self.rows - 1, self.cols - 1
        nr, nc = r + dr, c + dc
        if not (0 <= nr <= limit_r and 0 <= nc <= limit_c):
            return [r, c]
        if filled(r, c) and filled(nr, nc):              # along the block to its last cell
            while 0 <= nr + dr <= limit_r and 0 <= nc + dc <= limit_c and filled(nr + dr, nc + dc):
                nr, nc = nr + dr, nc + dc
            return [nr, nc]
        used_r, used_c = self.book.used(self._at)
        while 0 <= nr <= limit_r and 0 <= nc <= limit_c:             # on to the next filled one, or the edge
            if filled(nr, nc):
                return [nr, nc]
            if (dr > 0 and nr > used_r) or (dc > 0 and nc > used_c):
                return [limit_r if dr > 0 else nr, limit_c if dc > 0 else nc]
            nr, nc = nr + dr, nc + dc
        return [max(0, min(limit_r, nr)), max(0, min(limit_c, nc))]

    @Slot(str, result="QVariantList")
    def spanOf(self, text: str) -> list:
        got = parse_span(text)
        return list(got) if got else []

    # ------------------------------------------------------------------ undo
    def _keep(self, what: str = "") -> None:
        """Before a change: what the sheet in front looks like now, to go back to."""
        self._undo.append((self._at, copy.deepcopy(self.sh), what))
        del self._undo[:-60]
        self._redo.clear()

    def _done(self) -> None:
        self.historyChanged.emit()
        self._refresh()
        if self._path is not None:
            self.touch()
        else:
            self.changed.emit()

    @Slot()
    def undo(self) -> None:
        if self._undo:
            at, snap, what = self._undo.pop()
            self._redo.append((at, copy.deepcopy(self.book.sheets[at]), what))
            self.book.sheets[at] = snap
            self._front(at)
            self._done()

    @Slot()
    def redo(self) -> None:
        if self._redo:
            at, snap, what = self._redo.pop()
            self._undo.append((at, copy.deepcopy(self.book.sheets[at]), what))
            self.book.sheets[at] = snap
            self._front(at)
            self._done()

    # ------------------------------------------------------------------ typing
    @Slot(int, int, str)
    def put(self, r: int, c: int, text: str) -> None:
        text = text.rstrip("\n")
        if text.startswith("=") and len(text) > 1:
            text = "=" + _fix_case(text[1:])
        if self.sh["raw"].get((r, c), "") == text:
            return
        chk = self.check_at(r, c)
        if chk:
            why = checks_.allowed(self.book, self._at, chk, text)
            if why and chk["stop"]:
                self.refused.emit(why)
                return
            if why:
                self.refused.emit("Let in, though: " + why[:1].lower() + why[1:])
            if chk["kind"] == "list" and text.strip():           # the choice as it's spelled in the list
                text = next((x for x in checks_.choices(self.book, self._at, chk) if x.lower() == text.strip().lower()), text)
        self._keep("typing")
        self._set(r, c, text)
        self._done()

    def _set(self, r: int, c: int, text: str, guess_format: bool = True) -> None:
        if text:
            self.sh["raw"][(r, c)] = text
            if guess_format and not text.startswith(("=", "'")):
                _, fmt = se.literal(text, self.book.day_first)
                f = self.sh["fmt"].get((r, c)) or {}
                if fmt and f.get("num", "General") == "General":
                    self.sh["fmt"][(r, c)] = dict(f, num=fmt)
        else:
            self.sh["raw"].pop((r, c), None)

    @Slot(int, int, int, int, str)
    def clear(self, r0: int, c0: int, r1: int, c1: int, what: str = "contents") -> None:
        keys = [k for k in list(self.sh["raw"]) + list(self.sh["fmt"]) if r0 <= k[0] <= r1 and c0 <= k[1] <= c1]
        if not keys:
            return
        self._keep("clear")
        for k in keys:
            if what in ("contents", "all"):
                self.sh["raw"].pop(k, None)
            if what in ("formats", "all"):
                self.sh["fmt"].pop(k, None)
        self._done()

    # ------------------------------------------------------------------ formatting
    @Slot(int, int, int, int, str, "QVariant")
    def setFormat(self, r0: int, c0: int, r1: int, c1: int, key: str, value) -> None:
        """b, i, u, s (toggles: value true/false), color, fill ("" clears), align (left/center/right/""), wrap, num
        (a number format code), places (+1/-1), size, font."""
        value = value.toVariant() if hasattr(value, "toVariant") else value
        if (r1 - r0 + 1) * (c1 - c0 + 1) > 200000:
            return
        self._keep("format")
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                f = dict(self.sh["fmt"].get((r, c)) or {})
                if key == "places":
                    v = self.book.value(self._at, r, c)
                    base = f.get("num", "General")
                    if base in ("General", "") and isinstance(v, float):
                        s = se.format_value(v)
                        base = "0." + "0" * len(s.split(".")[1]) if "." in s else "0"
                    f["num"] = se.more_places(base, int(value))
                elif value in ("", None, False) and key != "align":
                    f.pop(key, None)
                elif key == "align" and not value:
                    f.pop("align", None)
                else:
                    f[key] = value
                if f.get("num") == "General":
                    f.pop("num")
                if f:
                    self.sh["fmt"][(r, c)] = f
                else:
                    self.sh["fmt"].pop((r, c), None)
        self._done()

    # ------------------------------------------------------------------ copy, cut, paste, fill
    @Slot(int, int, int, int, bool, result=str)
    def copy(self, r0: int, c0: int, r1: int, c1: int, cut: bool = False) -> str:
        """What's selected, kept for pasting (formulas move, formats come too); returns it as text for other apps."""
        cells = {(r - r0, c - c0): (self.sh["raw"].get((r, c), ""), copy.deepcopy(self.sh["fmt"].get((r, c)))) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)}
        lines = ["\t".join(self.shown(r, c) for c in range(c0, c1 + 1)) for r in range(r0, r1 + 1)]
        text = "\n".join(lines)
        self._clip = {"cells": cells, "h": r1 - r0 + 1, "w": c1 - c0 + 1, "from": (self._at, r0, c0), "cut": cut, "text": text}
        return text

    @Slot(int, int, int, int, str, result="QVariantList")
    def paste(self, r: int, c: int, r1: int, c1: int, text: str) -> list:
        """Paste at (r, c): what was copied here (its formulas moved), or text from another app (tabs or commas
        between cells). A selection that's a whole number of copies wide and tall gets it repeated. Returns the cells
        pasted into [r0, c0, r1, c1]."""
        clip = self._clip if self._clip and (not text or text.replace("\r", "") == self._clip["text"]) else None
        self._keep("paste")
        if clip is not None:
            h, w = clip["h"], clip["w"]
            reps_r = max(1, (r1 - r + 1) // h) if (r1 - r + 1) % h == 0 else 1
            reps_c = max(1, (c1 - c + 1) // w) if (c1 - c + 1) % w == 0 else 1
            fs, fr, fc = clip["from"]
            if clip["cut"]:
                src = self.book.sheets[fs]
                for (dr, dc) in clip["cells"]:
                    src["raw"].pop((fr + dr, fc + dc), None)
                    src["fmt"].pop((fr + dr, fc + dc), None)
            for i in range(reps_r):
                for j in range(reps_c):
                    for (dr, dc), (raw, fmt) in clip["cells"].items():
                        tr, tc = r + i * h + dr, c + j * w + dc
                        moved = raw if clip["cut"] else se.shift_formula(raw, tr - (fr + dr), tc - (fc + dc))
                        self._set(tr, tc, moved, guess_format=False)
                        if fmt:
                            self.sh["fmt"][(tr, tc)] = copy.deepcopy(fmt)
                        else:
                            self.sh["fmt"].pop((tr, tc), None)
            if clip["cut"]:
                self._clip = None
            self._done()
            return [r, c, r + h * reps_r - 1, c + w * reps_c - 1]
        rows = _table_text(text)
        for dr, row in enumerate(rows):
            for dc, value in enumerate(row):
                self._set(r + dr, c + dc, value.strip())
        self._done()
        return [r, c, r + max(0, len(rows) - 1), c + max(0, max((len(x) for x in rows), default=1) - 1)]

    @Slot(int, int, int, int, int, int)
    def fill(self, r0: int, c0: int, r1: int, c1: int, tr: int, tc: int) -> None:
        """The fill handle dragged from the selection (r0..r1, c0..c1) to (tr, tc): down, up, right or left."""
        self._keep("fill")
        if tr > r1:                                    # down: each column goes on
            for c in range(c0, c1 + 1):
                self._fill_line([(r, c) for r in range(r0, r1 + 1)], [(r, c) for r in range(r1 + 1, tr + 1)])
        elif tr < r0:
            for c in range(c0, c1 + 1):
                self._fill_line([(r, c) for r in range(r1, r0 - 1, -1)], [(r, c) for r in range(r0 - 1, tr - 1, -1)])
        elif tc > c1:
            for r in range(r0, r1 + 1):
                self._fill_line([(r, c) for c in range(c0, c1 + 1)], [(r, c) for c in range(c1 + 1, tc + 1)])
        elif tc < c0:
            for r in range(r0, r1 + 1):
                self._fill_line([(r, c) for c in range(c1, c0 - 1, -1)], [(r, c) for c in range(c0 - 1, tc - 1, -1)])
        else:
            self._undo.pop()
            return
        self._done()

    def _fill_line(self, seed_cells: list, targets: list) -> None:
        seeds = [self.sh["raw"].get(k, "") for k in seed_cells]
        if any(s.startswith("=") for s in seeds):                # formulas: each target copies the seed it lines up with
            for n, (tr, tc) in enumerate(targets):
                sr, sc = seed_cells[n % len(seed_cells)]
                self._set(tr, tc, se.shift_formula(self.sh["raw"].get((sr, sc), ""), tr - sr, tc - sc), guess_format=False)
        else:
            vals = se.fill_values([s for s in seeds], len(targets), self.book.day_first) if any(seeds) else [""] * len(targets)
            for (tr, tc), v in zip(targets, vals):
                self._set(tr, tc, v, guess_format=False)
        for n, k in enumerate(targets):
            f = self.sh["fmt"].get(seed_cells[n % len(seed_cells)])
            if f:
                self.sh["fmt"][k] = copy.deepcopy(f)
            else:
                self.sh["fmt"].pop(k, None)

    @Slot(int, int, int, int, result="QVariantList")
    def autoSum(self, r0: int, c0: int, r1: int, c1: int) -> list:
        """Σ: under (or beside) the selection, a SUM of the numbers above it; one cell alone gets the run of numbers
        above (or to its left). Returns the cell to show."""
        if (r0, c0) == (r1, c1):
            r, c = r0, c0
            top = r - 1
            while top >= 0 and isinstance(self.book.value(self._at, top, c), float):
                top -= 1
            if top < r - 1:
                self.put(r, c, f"=SUM({a1(top + 1, c)}:{a1(r - 1, c)})")
                return [r, c]
            left = c - 1
            while left >= 0 and isinstance(self.book.value(self._at, r, left), float):
                left -= 1
            self.put(r, c, f"=SUM({a1(r, left + 1)}:{a1(r, c - 1)})" if left < c - 1 else "=SUM()")
            return [r, c]
        self._keep("sum")
        for c in range(c0, c1 + 1):
            self._set(r1 + 1, c, f"=SUM({a1(r0, c)}:{a1(r1, c)})")
        self._done()
        return [r1 + 1, c0]

    # ------------------------------------------------------------------ rows and columns
    @Slot(str, int, int)
    def insert(self, axis: str, at: int, count: int) -> None:
        """Put in `count` rows (axis 'r') or columns ('c') before `at`."""
        self._move(axis, at, max(1, count))

    @Slot(str, int, int)
    def remove(self, axis: str, at: int, count: int) -> None:
        self._move(axis, at, -max(1, count))

    def _move(self, axis: str, at: int, count: int) -> None:
        self._keep("rows" if axis == "r" else "columns")
        # every formula in the book that points here moves its references
        name = self.sh["name"]
        for s in self.book.sheets:
            for k, t in list(s["raw"].items()):
                if t.startswith("="):
                    s["raw"][k] = se.move_refs(t, s["name"], name, axis, at, count)
        idx = 0 if axis == "r" else 1

        def moved(key):
            v = key[idx]
            if v < at:
                return key
            if count < 0 and v < at - count:
                return None
            nv = v + count
            return (nv, key[1]) if idx == 0 else (key[0], nv)
        self.sh.setdefault("notes", {})
        for part in ("raw", "fmt", "notes"):
            old = self.sh[part]
            new = {}
            for k, v in old.items():
                nk = moved(k)
                if nk is not None:
                    new[nk] = v
            self.sh[part] = new
        sizes = self.sh["heights" if axis == "r" else "widths"]
        moved_sizes = {}
        for k, v in sizes.items():
            k = int(k)
            if k < at:
                moved_sizes[k] = v
            elif not (count < 0 and k < at - count):
                moved_sizes[k + count] = v
        self.sh["heights" if axis == "r" else "widths"] = moved_sizes
        for ch in self.sh["charts"]:
            ch["range"] = se.move_refs("=" + ch["range"], name, name, axis, at, count)[1:]
        lo, hi = (0, 2) if axis == "r" else (1, 3)

        def shifted(span):
            span = list(span)
            if span[lo] >= at:
                span[lo] = max(at, span[lo] + count)
            if span[hi] >= at:
                span[hi] = max(span[lo], span[hi] + count)
            return span
        if self.sh.get("filter"):
            self.sh["filter"]["range"] = shifted(self.sh["filter"]["range"])
        kept = []
        for rule in self.sh.get("rules") or []:
            span = shifted(rule["range"])
            if span[hi] >= span[lo] and not (count < 0 and rule["range"][lo] >= at and rule["range"][hi] < at - count):
                rule["range"] = span
                kept.append(rule)
        self.sh["rules"] = kept
        kept = []
        for chk in self.sh.get("checks") or []:
            span = shifted(chk["range"])
            if span[hi] >= span[lo] and not (count < 0 and chk["range"][lo] >= at and chk["range"][hi] < at - count):
                chk["range"] = span
                kept.append(chk)
        self.sh["checks"] = kept
        merges = []
        for text in self.sh.get("merges") or []:
            m = parse_span(text)
            if not m:
                continue
            if count < 0 and m[lo] >= at and m[hi] < at - count:
                continue                                    # all of it deleted
            span = shifted(m)
            if (span[0], span[1]) != (span[2], span[3]):
                merges.append(span_name(*span))
        self.sh["merges"] = merges
        self._done()

    # ------------------------------------------------------------------ what may go in cells (data validation)
    def check_at(self, r: int, c: int):
        return next((x for x in self.sh.get("checks") or [] if checks_.covers(x, r, c)), None)

    @Property("QVariantList", notify=historyChanged)
    def checks(self):
        return [{"id": x["id"], "range": list(x["range"]), "where": span_name(*x["range"]), "what": checks_.describe(x), "kind": x["kind"],
                 "items": ", ".join(x["items"]), "source": x["source"], "op": x["op"], "a": x["a"], "b": x["b"], "stop": x["stop"]}
                for x in self.sh.get("checks") or []]

    @Slot(int, int, result="QVariantMap")
    def checkAt(self, r: int, c: int) -> dict:
        x = self.check_at(r, c)
        return {} if x is None else {"id": x["id"], "range": list(x["range"]), "kind": x["kind"], "items": ", ".join(x["items"]), "source": x["source"],
                                     "op": x["op"], "a": x["a"], "b": x["b"], "stop": x["stop"], "what": checks_.describe(x)}

    @Slot(int, int, result="QVariantList")
    def choicesAt(self, r: int, c: int) -> list:
        x = self.check_at(r, c)
        return checks_.choices(self.book, self._at, x) if x else []

    @Slot(int, int, int, int, str, str, str, str, str, bool, result=str)
    def setCheck(self, r0: int, c0: int, r1: int, c1: int, kind: str, items: str, op: str, a: str, b: str, stop: bool) -> str:
        """What may go in these cells: kind list (items: 'Yes, No' or a range such as E1:E5), whole, decimal, date or
        length, with op and a (and b). It takes the place of any check these cells had. Returns why not, or ''."""
        source = ""
        if kind == "list":
            t = items.strip().lstrip("=")
            if re.fullmatch(r"(('[^']+'|[A-Za-z_][\w. ]*)!)?\$?[A-Za-z]{1,3}\$?\d+(:\$?[A-Za-z]{1,3}\$?\d+)?", t):
                source, items_list = t, []
            else:
                items_list = checks_.items_from_text(items)
                if not items_list:
                    return "Type the choices, with commas between them, or the cells that hold them (such as E1:E5)."
        else:
            items_list = []
            if not a.strip() and not b.strip():
                return "Say which values are allowed."
        self._keep("choices")
        self._drop_checks(r0, c0, r1, c1)
        ident = "v" + str(1 + max([int(x["id"][1:]) for sh in self.book.sheets for x in sh.get("checks") or [] if x["id"][1:].isdigit()] or [0]))
        chk = checks_.clean_check({"id": ident, "range": [r0, c0, r1, c1], "kind": kind, "items": items_list, "source": source, "op": op,
                                   "a": a.strip(), "b": b.strip(), "stop": stop})
        if chk is None:
            self._undo.pop()
            return "That can't be checked."
        self.sh.setdefault("checks", []).insert(0, chk)
        self._done()
        return ""

    def _drop_checks(self, r0, c0, r1, c1) -> int:
        """Take these cells out of the checks they're in (a check over other cells too keeps those)."""
        kept, n = [], 0
        for x in self.sh.get("checks") or []:
            a0, b0, a1, b1 = x["range"]
            if a1 < r0 or a0 > r1 or b1 < c0 or b0 > c1:
                kept.append(x)
                continue
            n += 1
            # the parts of it outside the cells: up to four blocks around them
            for part in ([a0, b0, r0 - 1, b1], [r1 + 1, b0, a1, b1], [max(a0, r0), b0, min(a1, r1), c0 - 1], [max(a0, r0), c1 + 1, min(a1, r1), b1]):
                if part[2] >= part[0] and part[3] >= part[1]:
                    kept.append(dict(x, range=part, id=x["id"] + chr(97 + len(kept) % 26) if len(x["id"]) < 10 else x["id"]))
        self.sh["checks"] = kept
        return n

    @Slot(int, int, int, int, result=int)
    def clearChecks(self, r0: int, c0: int, r1: int, c1: int) -> int:
        if not any(not (x["range"][2] < r0 or x["range"][0] > r1 or x["range"][3] < c0 or x["range"][1] > c1) for x in self.sh.get("checks") or []):
            return 0
        self._keep("choices")
        n = self._drop_checks(r0, c0, r1, c1)
        self._done()
        return n

    # ------------------------------------------------------------------ notes on cells
    @Slot(int, int, result="QVariantMap")
    def noteAt(self, r: int, c: int) -> dict:
        n = (self.sh.get("notes") or {}).get((r, c))
        return {} if not n else {"text": n["text"], "by": n.get("by", ""), "when": n.get("when", 0), "where": a1(r, c)}

    @Slot(int, int, str)
    def setNote(self, r: int, c: int, text: str) -> None:
        """A note on a cell ('' takes it off)."""
        notes = self.sh.setdefault("notes", {})
        old = notes.get((r, c))
        if (old["text"] if old else "") == text.strip():
            return
        self._keep("note")
        if text.strip():
            import time
            notes[(r, c)] = {"text": text.strip(), "by": (old or {}).get("by") or _me(), "when": int(time.time())}
        else:
            notes.pop((r, c), None)
        self._done()

    # ------------------------------------------------------------------ conditional formatting
    @Property("QVariantList", notify=historyChanged)
    def rules(self):
        out = []
        for rule in self.sh.get("rules") or []:
            look = rules_.look_of(rule) if rule["kind"] not in ("scale", "bar") else {}
            out.append({"id": rule["id"], "kind": rule["kind"], "range": list(rule["range"]), "where": span_name(*rule["range"]),
                        "what": rules_.describe(rule), "fill": look.get("fill", rule.get("high") or rule.get("color") or ""), "color": look.get("color", ""),
                        "low": rule.get("low", ""), "high": rule.get("high", rule.get("color", ""))})
        return out

    @Slot(int, int, int, int, str, str, str, int, str, result=str)
    def addRule(self, r0: int, c0: int, r1: int, c1: int, kind: str, a: str, b: str, n: int, style: str) -> str:
        """Colour the cells between (r0, c0) and (r1, c1) by a rule (huginn_sheet_rules); it goes first. Returns why
        not, or ""."""
        if (kind in rules_.COMPARE or kind in ("text", "starts")) and not a.strip():
            return "Say what to compare with."
        if kind == "between" and (not a.strip() or not b.strip()):
            return "Give both ends."
        ident = "c" + str(1 + max([int(x["id"][1:]) for s in self.book.sheets for x in s.get("rules") or [] if x["id"][1:].isdigit()] or [0]))
        extra = {}
        if kind == "scale":
            extra = {"low": "#F8696B", "high": "#63BE7B"} if style != "blue" else {"low": "#FFFFFF", "high": "#5A8AC6"}
            if style == "three":
                extra = {"low": "#F8696B", "mid": "#FFEB84", "high": "#63BE7B"}
        if kind == "bar":
            extra = {"color": {"green": "#63C384", "red": "#FF555A", "yellow": "#FFB628"}.get(style, "#638EC6")}
        rule = rules_.clean_rule({"id": ident, "range": [r0, c0, r1, c1], "kind": kind, "a": a.strip(), "b": b.strip(), "n": n, "style": style, **extra})
        if rule is None:
            return "That rule can't be used."
        self._keep("conditional formatting")
        self.sh.setdefault("rules", []).insert(0, rule)
        self._done()
        return ""

    @Slot(str)
    def removeRule(self, ident: str) -> None:
        rules = self.sh.get("rules") or []
        if any(x["id"] == ident for x in rules):
            self._keep("conditional formatting")
            self.sh["rules"] = [x for x in rules if x["id"] != ident]
            self._done()

    @Slot(str, bool)
    def moveRule(self, ident: str, up: bool) -> None:
        rules = self.sh.get("rules") or []
        i = next((k for k, x in enumerate(rules) if x["id"] == ident), -1)
        j = i - 1 if up else i + 1
        if i >= 0 and 0 <= j < len(rules):
            self._keep("conditional formatting")
            rules[i], rules[j] = rules[j], rules[i]
            self._done()

    @Slot(int, int, int, int, result=int)
    def clearRules(self, r0: int, c0: int, r1: int, c1: int) -> int:
        """Take off the rules that touch these cells; returns how many."""
        rules = self.sh.get("rules") or []
        keep = [x for x in rules if x["range"][2] < r0 or x["range"][0] > r1 or x["range"][3] < c0 or x["range"][1] > c1]
        if len(keep) != len(rules):
            self._keep("conditional formatting")
            self.sh["rules"] = keep
            self._done()
        return len(rules) - len(keep)

    # ------------------------------------------------------------------ summaries (pivot tables)
    PIVOT_FNS = {"sum": ("SUMIFS", "Sum"), "count": ("COUNTIFS", "Count"), "average": ("AVERAGEIFS", "Average"), "min": ("MINIFS", "Smallest"), "max": ("MAXIFS", "Largest")}

    @Slot(int, int, int, int, result="QVariantList")
    def headings(self, r0: int, c0: int, r1: int, c1: int) -> list:
        """The first row of a block, as the names of its columns: [{col, name}]."""
        return [{"col": c, "name": self.shown(r0, c) or f"Column {se.col_name(c)}"} for c in range(c0, c1 + 1)]

    def _pivot_cells(self, spec: dict) -> tuple:
        """What a summary sheet holds: (raw cells, formats, widths), worked out from its source (formulas, so the
        numbers follow the source; new names in it come in when the summary is refreshed)."""
        src = self.book.sheet_index(spec["source"])
        if src is None or src < 0:
            raise ValueError("The sheet it summarises isn't there any more.")
        r0, c0, r1, c1 = spec["range"]
        sheet = self.book.sheets[src]
        last = self.book.used(src)[0]
        while r1 < last and any(sheet["raw"].get((r1 + 1, c), "") != "" for c in range(c0, c1 + 1)):
            r1 += 1                                     # rows added under the table since are in it too
        r1 = max(r0 + 1, min(r1, last))
        spec["range"] = [r0, c0, r1, c1]
        rc, cc, vc, fn = spec["rows"], spec["cols"], spec["values"], spec["fn"]
        fx, word = self.PIVOT_FNS[fn]

        def key(r, c):
            v = se.scalar(self.book.value(src, r, c)) if sheet["raw"].get((r, c), "") != "" else None
            return None if v is None or isinstance(v, se.Err) or v == "" else v

        def order(v):
            return (0, v, "") if isinstance(v, (int, float)) and not isinstance(v, bool) else (1, 0, str(v).lower())
        rows = sorted({k for r in range(r0 + 1, r1 + 1) if (k := key(r, rc)) is not None}, key=order)
        cols = sorted({k for r in range(r0 + 1, r1 + 1) if (k := key(r, cc)) is not None}, key=order) if cc >= 0 else []
        if not rows:
            raise ValueError("The column for the rows has nothing in it.")
        if len(rows) > 5000 or len(cols) > 200:
            raise ValueError("Too many different names to summarise (more than 5,000 rows or 200 columns).")
        q = se.quote_sheet(sheet["name"]) + "!"

        def col_range(c):
            return f"{q}${se.col_name(c)}${r0 + 2}:${se.col_name(c)}${r1 + 1}"
        vals, rrng = col_range(vc), col_range(rc)
        crng = col_range(cc) if cc >= 0 else ""

        def lit(v):
            if isinstance(v, bool):
                return "TRUE" if v else "FALSE"
            if isinstance(v, (int, float)):
                return se.general(float(v))
            t = str(v)
            return "'" + t if t[:1] in ("=", "'") or se.literal(t)[1] or isinstance(se.literal(t)[0], (int, float)) else t

        def formula(row_ref, col_ref):
            parts = [] if fn == "count" else [vals]
            if row_ref:
                parts += [rrng, row_ref]
            if col_ref:
                parts += [crng, col_ref]
            if not row_ref and not col_ref:
                return {"sum": f"=SUM({vals})", "count": f"=COUNTA({vals})", "average": f"=AVERAGE({vals})", "min": f"=MIN({vals})", "max": f"=MAX({vals})"}[fn]
            body = f"{fx}({','.join(parts)})"
            if row_ref and col_ref:                     # nothing for that pair: left empty, as a pivot table does
                return f'=IF(COUNTIFS({rrng},{row_ref},{crng},{col_ref})=0,"",{body})'
            return "=" + body
        raw, fmt = {}, {}
        head = {"b": True, "fill": "#E7F1FB"}
        value_name = self.shown(r0, vc) or se.col_name(vc)
        raw[(0, 0)] = lit(self.shown(r0, rc) or se.col_name(rc))
        fmt[(0, 0)] = dict(head)
        num = (sheet["fmt"].get((r0 + 1, vc)) or {}).get("num", "") if fn != "count" else ""
        columns = cols or [None]
        for j, ck in enumerate(columns):
            raw[(0, 1 + j)] = lit(ck) if ck is not None else f"{word} of {value_name}"
            fmt[(0, 1 + j)] = dict(head, align="right")
        if cols:
            raw[(0, 1 + len(cols))] = "Total"
            fmt[(0, 1 + len(cols))] = dict(head, align="right")
        for i, rk in enumerate(rows):
            r = 1 + i
            raw[(r, 0)] = lit(rk)
            for j, ck in enumerate(columns):
                ref_c = f"{se.col_name(1 + j)}$1" if ck is not None else ""
                raw[(r, 1 + j)] = formula(f"$A{r + 1}", ref_c)
                if num:
                    fmt[(r, 1 + j)] = {"num": num}
            if cols:
                raw[(r, 1 + len(cols))] = formula(f"$A{r + 1}", "")
                fmt[(r, 1 + len(cols))] = {"b": True, **({"num": num} if num else {})}
        total = 1 + len(rows)
        raw[(total, 0)] = "Total"
        fmt[(total, 0)] = {"b": True, "fill": "#F1F3F5"}
        for j, ck in enumerate(columns + ([None] if cols else [])):
            ref_c = f"{se.col_name(1 + j)}$1" if ck is not None else ""
            raw[(total, 1 + j)] = formula("", ref_c)
            fmt[(total, 1 + j)] = {"b": True, "fill": "#F1F3F5", **({"num": num} if num else {})}
        widths = {0: 160.0, **{1 + j: 120.0 for j in range(len(columns) + (1 if cols else 0))}}
        return raw, fmt, widths

    @Slot(int, int, int, int, int, int, int, str, result=str)
    def makePivot(self, r0: int, c0: int, r1: int, c1: int, rows: int, cols: int, values: int, fn: str) -> str:
        """A summary of a block (its first row the column names) on a new sheet: a row for each name in one column,
        optionally a column for each name in another, and the sum (or count, average, smallest, largest) of a third.
        Returns why not, or ""."""
        if fn not in self.PIVOT_FNS:
            return "Choose how to sum it up."
        if r0 == r1 and c0 == c1:                       # one cell: the table round it
            r0, c0, r1, c1 = self.dataBlock(r0, c0, r0, c0)
        if r1 <= r0 or not (c0 <= rows <= c1 and c0 <= values <= c1 and (cols < 0 or c0 <= cols <= c1)):
            return "Select the table to summarise, its column names along the top."
        if cols == rows:
            cols = -1
        spec = {"source": self.sh["name"], "range": [r0, c0, r1, c1], "rows": rows, "cols": cols, "values": values, "fn": fn}
        try:
            raw, fmt, widths = self._pivot_cells(spec)
        except (ValueError, se.Err) as err:
            return str(err)
        if len(self.book.sheets) >= self.MAX_SHEETS:
            return "This file has as many sheets as it can."
        sh = blank_sheet(self._fresh_name(f"Summary of {self.sh['name']}")[:31])
        sh["raw"], sh["fmt"], sh["widths"], sh["pivot"] = raw, fmt, widths, spec
        sh["freeze"] = [1, 0]
        self._undo.clear()
        self._redo.clear()
        self.book.sheets.insert(self._at + 1, sh)
        self._front(self._at + 1)
        self._done()
        return ""

    isPivot = Property(bool, lambda self: bool(self.sh.get("pivot")), notify=sheetsChanged)

    @Slot(result=str)
    def refreshPivot(self) -> str:
        spec = self.sh.get("pivot")
        if not spec:
            return "This sheet isn't a summary."
        try:
            raw, fmt, widths = self._pivot_cells(spec)
        except (ValueError, se.Err) as err:
            return str(err)
        self._keep("refresh the summary")
        self.sh["raw"], self.sh["fmt"] = raw, fmt
        self._done()
        return ""

    # ------------------------------------------------------------------ sizes
    @Slot(int, result=float)
    def colWidth(self, c: int) -> float:
        return float(self.sh["widths"].get(c, COL_W))

    @Slot(int, result=float)
    def rowHeight(self, r: int) -> float:
        if self._hidden(r):
            return 0.0
        return float(self.sh["heights"].get(r, ROW_H))

    @Slot(int, float)
    def setColWidth(self, c: int, w: float) -> None:
        w = max(24.0, min(1200.0, round(w)))
        if self.sh["widths"].get(c) != w:
            self.sh["widths"][c] = w
            self.gridChanged.emit()
            if self._path is not None:
                self.touch()

    @Slot(int, float)
    def setRowHeight(self, r: int, h: float) -> None:
        h = max(14.0, min(600.0, round(h)))
        if self.sh["heights"].get(r) != h:
            self.sh["heights"][r] = h
            self.gridChanged.emit()
            if self._path is not None:
                self.touch()

    @Slot(int)
    def fitColumn(self, c: int) -> None:
        """A column as wide as what's in it (double-click its edge)."""
        fm = QFontMetrics(QFont("Inter", 10))
        widest = max([fm.horizontalAdvance(self.shown(r, cc)) for (r, cc) in self.sh["raw"] if cc == c] + [40])
        self.setColWidth(c, widest + 22)

    @Slot(int, int)
    def freeze(self, rows: int, cols: int) -> None:
        self.sh["freeze"] = [max(0, min(50, rows)), max(0, min(20, cols))]
        self._panes()
        if self._path is not None:
            self.touch()

    # ------------------------------------------------------------------ sorting and filtering
    @Slot(int, int, int, int, int, bool, bool)
    def sort(self, r0: int, c0: int, r1: int, c1: int, key: int, descending: bool, header: bool) -> None:
        """Sort the rows of a block by one of its columns (numbers before text, empty last), formats going along."""
        if header:
            r0 += 1
        if r1 <= r0:
            return
        self._keep("sort")
        rows = []
        for r in range(r0, r1 + 1):
            rows.append(([(self.sh["raw"].get((r, c), ""), self.sh["fmt"].get((r, c)), (self.sh.get("notes") or {}).get((r, c))) for c in range(c0, c1 + 1)],
                         self.book.value(self._at, r, key), r))

        def order(item):
            v = item[1]
            if v is se.BLANK or v == "":
                return (2, 0, "")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return (0, -float(v) if descending else float(v), "")
            return (1, 0, str(v).lower())
        filled = sorted([x for x in rows if not (x[1] is se.BLANK or x[1] == "")], key=order, reverse=False)
        if descending:                                      # text descending too (numbers already turned round)
            nums = [x for x in filled if order(x)[0] == 0]
            texts = sorted([x for x in filled if order(x)[0] == 1], key=lambda x: str(x[1]).lower(), reverse=True)
            filled = nums + texts
        rows = filled + [x for x in rows if x[1] is se.BLANK or x[1] == ""]
        for n, (cells, _, src) in enumerate(rows):
            tr = r0 + n
            for k, (raw, fmt, note) in enumerate(cells):
                c = c0 + k
                self._set(tr, c, se.shift_formula(raw, tr - src, 0) if raw.startswith("=") else raw, guess_format=False)
                if fmt:
                    self.sh["fmt"][(tr, c)] = fmt
                else:
                    self.sh["fmt"].pop((tr, c), None)
                if note:                                    # a note goes with its row
                    self.sh.setdefault("notes", {})[(tr, c)] = note
                else:
                    self.sh.get("notes", {}).pop((tr, c), None)
        self._done()

    @Slot(int, int, int, int, result="QVariantList")
    def dataBlock(self, r: int, c: int, r1: int, c1: int) -> list:
        """The block of filled cells round (r, c) when only one cell is chosen (Ctrl+A, sorting, filters, charts)."""
        if (r, c) != (r1, c1):
            return [r, c, r1, c1]
        raw = self.sh["raw"]
        if (r, c) not in raw:
            return [r, c, r1, c1]
        top, bottom, left, right = r, r, c, c
        grew = True
        while grew:
            grew = False
            if top > 0 and any((top - 1, k) in raw for k in range(left, right + 1)):
                top -= 1
                grew = True
            if any((bottom + 1, k) in raw for k in range(left, right + 1)):
                bottom += 1
                grew = True
            if left > 0 and any((k, left - 1) in raw for k in range(top, bottom + 1)):
                left -= 1
                grew = True
            if any((k, right + 1) in raw for k in range(top, bottom + 1)):
                right += 1
                grew = True
        return [top, left, bottom, right]

    @Slot(int, int, int, int)
    def setFilter(self, r0: int, c0: int, r1: int, c1: int) -> None:
        """Turn the filter on for a block (its first row has the arrows), or off when it's on."""
        if self.sh.get("filter"):
            self.sh["filter"] = None
        else:
            r0, c0, r1, c1 = self.dataBlock(r0, c0, r1, c1)
            self.sh["filter"] = {"range": [r0, c0, r1, c1], "hide": {}}
        self._refresh()
        self._panes()
        if self._path is not None:
            self.touch()

    def _hidden(self, r: int) -> bool:
        flt = self.sh.get("filter")
        if not flt or not flt["hide"]:
            return False
        r0, c0, r1, c1 = flt["range"]
        if not (r0 < r <= r1):
            return False
        for c, hidden in flt["hide"].items():
            if self.shown(r, int(c)) in hidden:
                return True
        return False

    @Slot(int, result="QVariantList")
    def filterValues(self, c: int) -> list:
        flt = self.sh.get("filter")
        if not flt:
            return []
        r0, _, r1, _ = flt["range"]
        hidden = set(flt["hide"].get(c, []))
        seen = []
        for r in range(r0 + 1, r1 + 1):
            t = self.shown(r, c)
            if t not in seen:
                seen.append(t)
        seen.sort(key=lambda t: (t == "", _sort_key(t)))
        return [{"value": t, "label": t or "(empty)", "shown": t not in hidden} for t in seen[:500]]

    @Slot(int, "QVariantList")
    def setFilterHidden(self, c: int, values) -> None:
        values = values.toVariant() if hasattr(values, "toVariant") else values
        flt = self.sh.get("filter")
        if not flt:
            return
        if values:
            flt["hide"][c] = list(values)
        else:
            flt["hide"].pop(c, None)
        self._refresh()
        self._panes()
        if self._path is not None:
            self.touch()

    # ------------------------------------------------------------------ charts
    @Property("QVariantList", notify=chartsChanged)
    def charts(self):
        return [dict(ch) for ch in self.sh["charts"]]

    @Slot(str, int, int, int, int, float, float, result=str)
    def addChart(self, kind: str, r0: int, c0: int, r1: int, c1: int, x: float, y: float) -> str:
        r0, c0, r1, c1 = self.dataBlock(r0, c0, r1, c1)
        if (r0, c0) == (r1, c1):
            return ""
        self._keep("chart")
        ident = f"chart{len(self.sh['charts']) + 1}"
        while any(ch["id"] == ident for ch in self.sh["charts"]):
            ident += "x"
        title = ""
        self.sh["charts"].append({"id": ident, "kind": kind, "range": span_name(r0, c0, r1, c1), "title": title, "x": x, "y": y, "w": 480, "h": 300, "legend": True})
        self._done()
        return ident

    @Slot(str, str, "QVariant")
    def setChart(self, ident: str, key: str, value) -> None:
        value = value.toVariant() if hasattr(value, "toVariant") else value
        ch = next((c for c in self.sh["charts"] if c["id"] == ident), None)
        if ch is None or key not in ("kind", "range", "title", "x", "y", "w", "h", "legend"):
            return
        if key == "range" and not parse_span(str(value)):
            return
        if key in ("x", "y", "w", "h"):
            value = max(0.0, float(value)) if key in ("x", "y") else max(160.0, min(2000.0, float(value)))
        if ch.get(key) == value:
            return
        if key not in ("x", "y", "w", "h"):
            self._keep("chart")
        ch[key] = value
        self.chartsChanged.emit()
        if self._path is not None:
            self.touch()

    @Slot(str)
    def removeChart(self, ident: str) -> None:
        if any(c["id"] == ident for c in self.sh["charts"]):
            self._keep("chart")
            self.sh["charts"] = [c for c in self.sh["charts"] if c["id"] != ident]
            self._done()

    @Slot(str, result="QVariantMap")
    def chartData(self, ident: str) -> dict:
        """A chart's numbers: {kind, title, labels, series: [{name, values, colour}], low, high}. The block's first
        column (or row, when it's wider than tall... by its shape) holds the labels when it's text; its first row the
        series' names when that's text."""
        ch = next((c for c in self.sh["charts"] if c["id"] == ident), None)
        if ch is None:
            return {}
        return chart_series(self.book, self._at, ch)

    # ------------------------------------------------------------------ find
    @Slot(str, int, int, bool, bool, result="QVariantList")
    def find(self, text: str, r: int, c: int, backwards: bool, case: bool) -> list:
        if not text:
            return []
        want = text if case else text.lower()
        cells = sorted(self.sh["raw"], key=lambda k: (k[0], k[1]), reverse=backwards)
        hits = [k for k in cells if want in (self.shown(*k) if case else self.shown(*k).lower()) or want in (self.sh["raw"][k] if case else self.sh["raw"][k].lower())]
        if not hits:
            return []
        for k in hits:
            if (k > (r, c)) if not backwards else (k < (r, c)):
                return list(k)
        return list(hits[0])

    @Slot(str, bool, result=int)
    def countFound(self, text: str, case: bool) -> int:
        if not text:
            return 0
        want = text if case else text.lower()
        return sum(1 for k in self.sh["raw"] if want in (self.shown(*k) if case else self.shown(*k).lower()))

    @Slot(str, str, bool, result=int)
    def replaceAll(self, text: str, by: str, case: bool) -> int:
        if not text:
            return 0
        pat = re.compile(re.escape(text), 0 if case else re.I)
        hits = [k for k, v in self.sh["raw"].items() if pat.search(v)]
        if not hits:
            return 0
        self._keep("replace")
        for k in hits:
            self._set(k[0], k[1], pat.sub(by.replace("\\", "\\\\"), self.sh["raw"][k]), guess_format=False)
        self._done()
        return len(hits)

    # ------------------------------------------------------------------ the status line
    @Slot(int, int, int, int, result=str)
    def summary(self, r0: int, c0: int, r1: int, c1: int) -> str:
        if (r0, c0) == (r1, c1):
            return ""
        nums, filled = [], 0
        keys = [k for k in self.sh["raw"] if r0 <= k[0] <= r1 and c0 <= k[1] <= c1] if (r1 - r0 + 1) * (c1 - c0 + 1) > 5000 else \
            [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1) if (r, c) in self.sh["raw"]]
        keys = [k for k in keys if not self._hidden(k[0])]      # rows a filter hides don't count, as in Excel
        for k in keys:
            v = self.book.value(self._at, *k)
            filled += 1
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                nums.append(float(v))
        if not filled:
            return ""
        if not nums:
            return f"Count {filled}"
        fmt = next((self.fmt_of(*k).get("num", "") for k in keys if isinstance(self.book.value(self._at, *k), float)), "")
        fmt = "" if fmt in ("short-date", "yyyy-mm-dd", "d mmm yyyy", "hh:mm", "@") else fmt
        total = math.fsum(nums)
        shown = lambda x: se.format_value(x, fmt) if fmt else se.format_value(round(x, 6))      # noqa: E731
        return f"Sum {shown(total)}   Average {shown(total / len(nums))}   Count {filled}"

    # ------------------------------------------------------------------ sheets
    def _front(self, index: int) -> None:
        self._at = max(0, min(index, len(self.book.sheets) - 1))
        self.book.changed()
        self.looks.forget()
        self.rows, self.cols = 0, 0
        self._size()
        self._panes()
        self.chartsChanged.emit()

    def _fresh_name(self, wanted: str, skip: int = -1) -> str:
        wanted = " ".join(re.sub(r"[\[\]:*?/\\]", " ", wanted).split())[:31] or "Sheet"
        taken = {sh["name"].lower() for i, sh in enumerate(self.book.sheets) if i != skip}
        name, n = wanted, 2
        while name.lower() in taken:
            name, n = f"{wanted[:27]} {n}", n + 1
        return name

    @Slot(int)
    def selectSheet(self, index: int) -> None:
        if 0 <= index < len(self.book.sheets) and index != self._at:
            self._front(index)
            self.changed.emit()

    @Slot()
    def addSheet(self) -> None:
        if self._path is None or self.oneSheetOnly or len(self.book.sheets) >= self.MAX_SHEETS:
            return
        self.book.sheets.append(blank_sheet(self._fresh_name(f"Sheet {len(self.book.sheets) + 1}")))
        self._front(len(self.book.sheets) - 1)
        self.touch()

    @Slot(int, str)
    def renameSheet(self, index: int, name: str) -> None:
        if 0 <= index < len(self.book.sheets) and name.strip() and name.strip() != self.book.sheets[index]["name"]:
            old = self.book.sheets[index]["name"]
            new = self._fresh_name(name, skip=index)
            self.book.sheets[index]["name"] = new
            for s in self.book.sheets:                         # formulas that name it follow
                for k, t in list(s["raw"].items()):
                    if t.startswith("=") and "!" in t:
                        s["raw"][k] = se.rename_sheet_refs(t, old, new)
                if s.get("pivot") and s["pivot"].get("source") == old:   # and a summary of it
                    s["pivot"]["source"] = new
            self._refresh()
            self.touch()

    @Slot(int)
    def removeSheet(self, index: int) -> None:
        if len(self.book.sheets) < 2 or not 0 <= index < len(self.book.sheets):
            return
        del self.book.sheets[index]
        self._undo = [u for u in self._undo if u[0] != index]
        self._undo = [(a - 1 if a > index else a, s, w) for a, s, w in self._undo]
        self._redo.clear()
        self._front(min(self._at if index > self._at else max(0, self._at - 1), len(self.book.sheets) - 1))
        self.touch()

    @Slot(int, int)
    def moveSheet(self, index: int, to: int) -> None:
        n = len(self.book.sheets)
        if 0 <= index < n and 0 <= to < n and index != to:
            sh = self.book.sheets.pop(index)
            self.book.sheets.insert(to, sh)
            self._undo, self._redo = [], []
            self.historyChanged.emit()
            self._front(to)
            self.touch()

    @Slot(int)
    def duplicateSheet(self, index: int) -> None:
        if 0 <= index < len(self.book.sheets) and len(self.book.sheets) < self.MAX_SHEETS:
            sh = copy.deepcopy(self.book.sheets[index])
            sh["name"] = self._fresh_name(sh["name"] + " copy")
            self.book.sheets.insert(index + 1, sh)
            self._undo, self._redo = [], []
            self.historyChanged.emit()
            self._front(index + 1)
            self.touch()

    # ------------------------------------------------------------------ files
    @Slot(str)
    def open(self, path: str) -> None:
        note_recent(path)
        if self._dirty:
            self.save()
        source = Path(path)
        dropped = []
        try:
            kind, target = source.suffix.lower(), source
            if kind in self.FOREIGN:
                sheets, dropped = xlsx.read(self._modern(source))
                target = fresh_path(source.parent, source.stem, ".hsheet")
            elif kind == ".csv":
                text = source.read_text(encoding="utf-8-sig", errors="replace")
                sh = blank_sheet("Sheet 1")
                for r, row in enumerate(_table_text(text)):
                    for c, v in enumerate(row):
                        if v.strip():
                            sh["raw"][(r, c)] = v.strip()
                sheets = [sh]
            else:
                sheets, self._front_hint = read_hsheet(source.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, csv.Error, xlsx.ConvertError) as err:
            self.failed.emit(f"Couldn't open “{source.name}”: {getattr(err, 'strerror', None) or err}")
            return
        self.book.sheets = sheets or [blank_sheet("Sheet 1")]
        front, self._front_hint = getattr(self, "_front_hint", 0), 0
        self._undo, self._redo, self._clip = [], [], None
        self.historyChanged.emit()
        self._path, self._dirty = target, False
        self._front(front if 0 <= front < len(self.book.sheets) else 0)
        if target != source:
            self.touch()
            self.imported.emit(source.name, dropped)
        self.changed.emit()

    @Slot()
    def create(self) -> None:
        if self._dirty:
            self.save()
        try:
            path = fresh_path(self._folder, self.STEM, ".hsheet")
            path.write_text(write_hsheet([blank_sheet("Sheet 1")], 0), encoding="utf-8")
        except OSError as err:
            self.failed.emit(f"Couldn't create a sheet: {err.strerror or err}")
            return
        self.open(str(path))

    @Slot()
    def save(self) -> None:
        if not self._dirty or self._path is None:
            return
        try:
            if self._path.suffix.lower() == ".csv":
                write_atomic(self._path, self._csv(values=False))
            else:
                write_atomic(self._path, write_hsheet(self.book.sheets, self._at))
            self._dirty = False
        except OSError as err:
            self.failed.emit(f"Couldn't save: {err.strerror or err}")
        self.changed.emit()

    def _csv(self, values: bool) -> str:
        out = io.StringIO()
        ur, uc = self.book.used(self._at)
        w = csv.writer(out)
        for r in range(ur + 1):
            w.writerow([(self.shown(r, c) if values else self.sh["raw"].get((r, c), "")) for c in range(uc + 1)])
        return out.getvalue()

    @Slot(str, result=str)
    def sendByMail(self, kind: str) -> str:
        """Export a copy (as `export` does) and start a message in Mail with it attached. Returns the copy's path."""
        out = self.export(kind)
        if out:
            import huginn_sendmail
            huginn_sendmail.send_files([out], Path(out).stem)
        return out

    @Slot(str, result=str)
    def export(self, kind: str) -> str:
        """csv (the sheet in front, as shown) | xlsx (every sheet: formulas with their results, formats, widths,
        frozen panes, charts) | pdf (the sheet in front, on pages)."""
        if self._path is None:
            return ""
        self.save()
        try:
            out = fresh_path(self._path.parent, self._path.stem, "." + kind)
            if kind == "csv":
                out.write_text(self._csv(values=True), encoding="utf-8")
            elif kind == "xlsx":
                xlsx.write(self.book, out, self.shown_in)
            elif kind == "pdf":
                sheet_pdf(self, out)
            else:
                return ""
        except (OSError, xlsx.ConvertError) as err:
            self.failed.emit(f"Couldn't export: {getattr(err, 'strerror', None) or err}")
            return ""
        return str(out)

    def shown_in(self, s: int, r: int, c: int) -> str:
        keep = self._at
        self._at = s
        try:
            return self.shown(r, c)
        finally:
            self._at = keep


# ------------------------------------------------------------------------------------------------ helpers
def _fix_case(src: str) -> str:
    """=sum(a1:b2) -> =SUM(A1:B2): function names and references in capitals, text left alone."""
    try:
        toks = se.tokens(src)
    except se.Err:
        return src
    out, last = [], 0
    for kind, val, a, b in toks:
        if kind in ("func",) or (kind == "ref" and "!" not in val):
            out.append(src[last:a] + val.upper())
            last = b
        elif kind == "ref":
            sheet, cells = val.rsplit("!", 1)
            out.append(src[last:a] + sheet + "!" + cells.upper())
            last = b
        elif kind == "name" and val.upper() in ("TRUE", "FALSE"):
            out.append(src[last:a] + val.upper())
            last = b
    out.append(src[last:])
    return "".join(out)


def _table_text(text: str) -> list:
    text = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if not text:
        return [[""]]
    if "\t" in text:
        return [line.split("\t") for line in text.split("\n")]
    try:
        dialect = csv.Sniffer().sniff(text[:2000], ",;")
        return list(csv.reader(io.StringIO(text), dialect))
    except csv.Error:
        return [[line] for line in text.split("\n")]


def _sort_key(t: str):
    val, _ = se.literal(t)
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return (0, float(val), "")
    return (1, 0, t.lower())


def chart_series(book, s: int, ch: dict) -> dict:
    span = parse_span(ch["range"])
    if not span:
        return {}
    r0, c0, r1, c1 = span
    vals = [[book.value(s, r, c) for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]
    isnum = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)     # noqa: E731
    head_row = any(isinstance(v, str) for v in vals[0][1:] or vals[0]) and len(vals) > 1
    head_col = all(not isnum(row[0]) for row in vals[1 if head_row else 0:]) and len(vals[0]) > 1
    body = vals[1:] if head_row else vals
    labels = [se.format_value(row[0]) for row in body] if head_col else [str(k + 1) for k in range(len(body))]
    first = 1 if head_col else 0
    series = []
    for k in range(first, len(vals[0])):
        name = se.format_value(vals[0][k]) if head_row else (f"Series {k - first + 1}")
        values = [float(row[k]) if isnum(row[k]) else 0.0 for row in body]
        series.append({"name": name, "values": values, "colour": PALETTE[len(series) % len(PALETTE)]})
    flat = [v for se_ in series for v in se_["values"]] or [0.0]
    return {"kind": ch["kind"], "title": ch.get("title") or (series[0]["name"] if len(series) == 1 and head_row else ""), "labels": labels,
            "series": series, "low": min(0.0, min(flat)), "high": max(0.0, max(flat)), "legend": ch.get("legend", True)}


def write_hsheet(sheets: list, front: int) -> str:
    out = []
    for sh in sheets:
        out.append({"name": sh["name"],
                    "cells": {a1(r, c): t for (r, c), t in sorted(sh["raw"].items())},
                    "formats": {a1(r, c): f for (r, c), f in sorted(sh["fmt"].items()) if f},
                    "widths": {se.col_name(int(c)): w for c, w in sorted(sh["widths"].items())},
                    "heights": {str(int(r) + 1): h for r, h in sorted(sh["heights"].items())},
                    "freeze": sh["freeze"], "filter": sh.get("filter"), "charts": sh["charts"], "merges": sh.get("merges", []),
                    **({"rules": sh["rules"]} if sh.get("rules") else {}), **({"pivot": sh["pivot"]} if sh.get("pivot") else {}),
                    **({"checks": sh["checks"]} if sh.get("checks") else {}),
                    **({"notes": {a1(r, c): n for (r, c), n in sorted(sh["notes"].items())}} if sh.get("notes") else {})})
    return json.dumps({"format": "huginn-sheet-3", "front": front, "sheets": out}, indent=1, ensure_ascii=False)


def read_hsheet(text: str) -> list:
    data = json.loads(text)
    found = data.get("sheets") if isinstance(data.get("sheets"), list) else [{"name": "Sheet 1", "cells": data.get("cells", {})}]
    sheets = []
    for entry in found:
        sh = blank_sheet(str(entry.get("name") or f"Sheet {len(sheets) + 1}")[:31])
        for ref, t in (entry.get("cells") or {}).items():
            p = se.parse_cell(ref)
            if p and str(t).strip():
                sh["raw"][p] = str(t)
        for ref, f in (entry.get("formats") or {}).items():
            p = se.parse_cell(ref)
            if p and isinstance(f, dict):
                sh["fmt"][p] = f
        for col, w in (entry.get("widths") or {}).items():
            sh["widths"][se.col_index(col)] = float(w)
        for row, h in (entry.get("heights") or {}).items():
            sh["heights"][int(row) - 1] = float(h)
        fz = entry.get("freeze") or [0, 0]
        sh["freeze"] = [int(fz[0]), int(fz[1])]
        flt = entry.get("filter")
        if isinstance(flt, dict) and isinstance(flt.get("range"), list):
            sh["filter"] = {"range": [int(x) for x in flt["range"]], "hide": {int(k): list(v) for k, v in (flt.get("hide") or {}).items()}}
        sh["charts"] = [c for c in entry.get("charts") or [] if isinstance(c, dict) and c.get("range")]
        sh["merges"] = entry.get("merges") or []
        sh["rules"] = [r for r in (rules_.clean_rule(x) for x in entry.get("rules") or []) if r]
        sh["pivot"] = entry.get("pivot") if isinstance(entry.get("pivot"), dict) else None
        sh["checks"] = [x for x in (checks_.clean_check(v) for v in entry.get("checks") or []) if x]
        for ref, n in (entry.get("notes") or {}).items():
            p, n = se.parse_cell(ref), checks_.clean_note(n)
            if p and n:
                sh["notes"][p] = n
        sheets.append(sh)
    return sheets, int(data.get("front", 0) or 0)


def sheet_pdf(owner: "Sheets", out: Path) -> None:
    """The sheet in front on A4 or Letter pages, with grid lines, the formats it has, and its column letters
    repeated on every page."""
    from PySide6.QtCore import QMarginsF, QRectF
    from PySide6.QtGui import QColor, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen
    ur, uc = owner.book.used(owner._at)
    if ur < 0:
        raise OSError("the sheet is empty")
    us = QLocale.system().territory() in (QLocale.UnitedStates, QLocale.Canada)
    pdf = QPdfWriter(str(out))
    pdf.setPageSize(QPageSize(QPageSize.Letter if us else QPageSize.A4))
    widths = [owner.colWidth(c) for c in range(uc + 1)]
    pdf.setPageOrientation(QPageLayout.Landscape if sum(widths) > 760 else QPageLayout.Portrait)
    pdf.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter)
    pdf.setResolution(96)
    pdf.setTitle(owner.title)
    p = QPainter(pdf)
    page = p.viewport()
    W, H = page.width(), page.height()
    # columns that fit across a page, then rows down it
    col_pages, start, acc = [], 0, 0.0
    for c, w in enumerate(widths):
        if acc + w > W and c > start:
            col_pages.append((start, c - 1))
            start, acc = c, 0.0
        acc += w
    col_pages.append((start, uc))
    font = QFont("Inter")
    font.setPointSizeF(9)
    first = True
    for c0, c1 in col_pages:
        r = 0
        while r <= ur:
            if not first:
                pdf.newPage()
            first = False
            y = 0.0
            while r <= ur and y + owner.rowHeight(r) <= H:
                h = owner.rowHeight(r)
                if h <= 0:
                    r += 1
                    continue
                x = 0.0
                for c in range(c0, c1 + 1):
                    w = widths[c]
                    cell = owner.cell(r, c)
                    rect = QRectF(x, y, w, h)
                    if cell.get("fill"):
                        p.fillRect(rect, QColor(cell["fill"]))
                    p.setPen(QPen(QColor("#D0D4DA"), 0.6))
                    p.drawRect(rect)
                    f = QFont(cell.get("font") or "Inter")
                    f.setPointSizeF(float(cell.get("size") or 9))
                    f.setBold(bool(cell.get("b")))
                    f.setItalic(bool(cell.get("i")))
                    f.setUnderline(bool(cell.get("u")))
                    f.setStrikeOut(bool(cell.get("s")))
                    p.setFont(f)
                    p.setPen(QColor(cell.get("color") or ("#C92A2A" if cell.get("e") else "#15181C")))
                    align = {"right": Qt.AlignRight, "center": Qt.AlignHCenter}.get(cell.get("align"), Qt.AlignLeft) | Qt.AlignVCenter
                    p.drawText(rect.adjusted(4, 0, -4, 0), int(align) | (int(Qt.TextWordWrap) if cell.get("wrap") else 0), cell["t"])
                    x += w
                y += h
                r += 1
    p.end()
