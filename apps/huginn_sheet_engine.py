"""Huginn Sheets' arithmetic: formulas read the way Excel reads them, worked out over a whole workbook.

No Qt here, so it can be tested and used on its own. A workbook is a list of sheets; each sheet keeps the text
typed in each cell (`raw`, keyed (row, col) from 0). Values are worked out when asked for and kept until anything
changes.

Formulas: numbers, "text", TRUE/FALSE, cell references (A1, $A$1, A:A, 3:3, Sheet2!B4, 'My sheet'!A1:C9),
+ - * / ^ & % = <> < > <= >=, and about 120 functions. References are rewritten when cells are copied, filled,
or rows and columns are put in or taken out, as in Excel. Dates are numbers of days since 30 December 1899
(Excel's way), so they add and subtract.
"""
import calendar
import datetime as dt
import math
import random
import re
import statistics

EPOCH = dt.date(1899, 12, 30)
MAX_ROWS, MAX_COLS = 100000, 702          # (to ZZ)


# ------------------------------------------------------------------------------------------------ values
class Err(Exception):
    """An error value (#DIV/0! and friends); also raised to stop working out a formula."""
    CODES = ("#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A", "#CYCLE!", "#SPILL!", "#ERROR!")

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

    def __eq__(self, other):
        return isinstance(other, Err) and other.code == self.code

    def __hash__(self):
        return hash(self.code)

    def __repr__(self):
        return self.code


class Blank:
    """An empty cell: 0 in sums, "" in text, and not counted."""
    def __repr__(self):
        return "BLANK"


BLANK = Blank()


class Area:
    """A block of cells (a range), as values in rows."""
    __slots__ = ("rows", "sheet", "r0", "c0")

    def __init__(self, rows, sheet=None, r0=0, c0=0):
        self.rows, self.sheet, self.r0, self.c0 = rows, sheet, r0, c0

    def flat(self):
        for row in self.rows:
            yield from row

    @property
    def height(self):
        return len(self.rows)

    @property
    def width(self):
        return len(self.rows[0]) if self.rows else 0


def col_name(c: int) -> str:
    out = ""
    c = max(0, c) + 1                                               # (a column before A has no name, and would never finish)
    while c:
        c, rem = divmod(c - 1, 26)
        out = chr(65 + rem) + out
    return out


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def ref_name(r: int, c: int) -> str:
    return f"{col_name(c)}{r + 1}"


def parse_cell(text: str):
    m = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d{1,6})", text.strip())
    if not m:
        return None
    return int(m.group(2)) - 1, col_index(m.group(1))


def to_date(serial: float) -> dt.datetime:
    return dt.datetime.combine(EPOCH, dt.time()) + dt.timedelta(days=float(serial))


def from_date(d) -> float:
    if isinstance(d, dt.datetime):
        return (d - dt.datetime.combine(EPOCH, dt.time())).total_seconds() / 86400
    return float((d - EPOCH).days)


# ------------------------------------------------------------------------------------------------ reading what's typed
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m} | {m.lower(): i for i, m in enumerate(calendar.month_name) if m}


def literal(text: str, day_first: bool = False):
    """What a typed value is: (value, format it suggests or "")."""
    t = text.strip()
    if not t:
        return BLANK, ""
    up = t.upper()
    if up in ("TRUE", "FALSE"):
        return up == "TRUE", ""
    if up in Err.CODES:
        return Err(up), ""
    s = t.replace("−", "-")
    cur = ""
    m = re.fullmatch(r"(-?)([$€£¥])\s*(.+)", s) or re.fullmatch(r"(-?)(.+?)\s*([$€£¥])", s)
    if m:
        sign = m.group(1)
        sym, body = (m.group(2), m.group(3)) if m.group(2) in "$€£¥" else (m.group(3), m.group(2))
        if re.fullmatch(r"[\d,]*\.?\d+", body):
            cur, s = sym, sign + body
    num = re.fullmatch(r"([+-]?)(\d{1,3}(,\d{3})+|\d+)?(\.\d+)?([eE][+-]?\d+)?(%?)", s)
    if num and (num.group(2) or num.group(4)):
        value = float(s.rstrip("%").replace(",", ""))
        if num.group(6):
            return value / 100, "0%" if "." not in s else "0.00%"
        if cur:
            return value, cur + "#,##0.00"
        return value, "#,##0" if "," in s and "." not in s else ("#,##0.00" if "," in s else "")
    # dates and times
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?", s)
    if m:
        try:
            d = dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0))
            return from_date(d), "yyyy-mm-dd hh:mm" if m.group(4) else "yyyy-mm-dd"
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 50 else y + 1900 if y < 100 else y
        mo, d = (b, a) if day_first else (a, b)
        try:
            return from_date(dt.date(y, mo, d)), "short-date"
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})", s) or re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m:
        g = m.groups()
        day, mon = (g[0], g[1]) if g[0].isdigit() else (g[1], g[0])
        if mon.lower() in MONTHS:
            try:
                return from_date(dt.date(int(g[2]), MONTHS[mon.lower()], int(day))), "d mmm yyyy"
            except ValueError:
                pass
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?", s)
    if m:
        h, mi, sec = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        if m.group(4):
            h = h % 12 + (12 if m.group(4).lower() == "pm" else 0)
        if h < 24 and mi < 60 and sec < 60:
            return (h * 3600 + mi * 60 + sec) / 86400, "hh:mm" if not m.group(3) else "hh:mm:ss"
    return t, ""


# ------------------------------------------------------------------------------------------------ formulas: reading
TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<err>\#(?:NULL!|DIV/0!|VALUE!|REF!|NAME\?|NUM!|N/A|CYCLE!))
  | (?P<ref>(?:(?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!)?(?:\$?[A-Za-z]{1,3}\$?\d{1,6}(?::\$?[A-Za-z]{1,3}\$?\d{1,6})?|\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}|\$?\d{1,6}:\$?\d{1,6})(?![\w(]))
  | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<func>[A-Za-z_][\w.]*(?=\s*\())
  | (?P<name>[A-Za-z_][\w.]*)
  | (?P<op><>|<=|>=|[-+*/^&=<>%(),;:{}])
""", re.X)


def tokens(src: str) -> list:
    out, pos = [], 0
    while pos < len(src):
        m = TOKEN.match(src, pos)
        if not m:
            raise Err("#ERROR!")
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind, m.group(kind), m.start(), m.end()))
        pos = m.end()
    return out


class Parser:
    """Formula text -> a tree of tuples: ("num", v), ("str", s), ("bool", b), ("err", code), ("ref", sheet, r0, c0, r1, c1),
    ("fn", NAME, [args]), ("op", sym, a, b), ("neg", a), ("pct", a), ("array", rows)."""
    PREC = {"=": 1, "<>": 1, "<": 1, ">": 1, "<=": 1, ">=": 1, "&": 2, "+": 3, "-": 3, "*": 4, "/": 4, "^": 5}

    def __init__(self, src: str):
        self.t = tokens(src)
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None, 0, 0)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        node = self.expr(0)
        if self.i != len(self.t):
            raise Err("#ERROR!")
        return node

    def expr(self, least: int):
        left = self.unary()
        while True:
            kind, val, *_ = self.peek()
            if kind != "op" or val not in self.PREC or self.PREC[val] < least:
                return left
            self.take()
            prec = self.PREC[val]
            right = self.expr(prec + (0 if val == "^" else 1))
            left = ("op", val, left, right)

    def unary(self):
        kind, val, *_ = self.peek()
        if kind == "op" and val in "+-":
            self.take()
            inner = self.unary()
            return ("neg", inner) if val == "-" else inner
        node = self.atom()
        while self.peek()[0] == "op" and self.peek()[1] == "%":
            self.take()
            node = ("pct", node)
        return node

    def atom(self):
        kind, val, *_ = self.take()
        if kind == "num":
            return ("num", float(val))
        if kind == "str":
            return ("str", val[1:-1].replace('""', '"'))
        if kind == "err":
            return ("err", val.upper())
        if kind == "ref":
            return ref_node(val)
        if kind == "name":
            up = val.upper()
            if up in ("TRUE", "FALSE"):
                return ("bool", up == "TRUE")
            return ("name", val)
        if kind == "func":
            name = val.upper()
            self.take()                                 # (
            args = []
            if not (self.peek()[0] == "op" and self.peek()[1] == ")"):
                while True:
                    if self.peek()[0] == "op" and self.peek()[1] in (",", ";"):
                        args.append(("blank",))
                    else:
                        args.append(self.expr(0))
                    k, v, *_ = self.take()
                    if k == "op" and v == ")":
                        break
                    if not (k == "op" and v in (",", ";")):
                        raise Err("#ERROR!")
            else:
                self.take()
            return ("fn", name, args)
        if kind == "op" and val == "(":
            node = self.expr(0)
            k, v, *_ = self.take()
            if not (k == "op" and v == ")"):
                raise Err("#ERROR!")
            return node
        if kind == "op" and val == "{":                  # an array constant {1,2;3,4}
            rows, row = [], []
            while True:
                row.append(self.expr(0))
                k, v, *_ = self.take()
                if v == ",":
                    continue
                rows.append(row)
                row = []
                if v == ";":
                    continue
                if v == "}":
                    break
                raise Err("#ERROR!")
            return ("array", rows)
        raise Err("#ERROR!")


def split_ref(text: str):
    """'Sheet 2'!A1:B3 -> (sheet name or None, the cells part)."""
    if "!" in text:
        sheet, cells = text.rsplit("!", 1)
        if sheet.startswith("'"):
            sheet = sheet[1:-1].replace("''", "'")
        return sheet, cells
    return None, text


def ref_node(text: str):
    sheet, cells = split_ref(text)
    if ":" in cells:
        a, b = cells.split(":")
        if re.fullmatch(r"\$?[A-Za-z]{1,3}", a):                       # whole columns
            return ("ref", sheet, 0, col_index(a.lstrip("$")), MAX_ROWS - 1, col_index(b.lstrip("$")))
        if re.fullmatch(r"\$?\d+", a):                                  # whole rows
            return ("ref", sheet, int(a.lstrip("$")) - 1, 0, int(b.lstrip("$")) - 1, MAX_COLS - 1)
        p, q = parse_cell(a), parse_cell(b)
        return ("ref", sheet, min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
    r, c = parse_cell(cells)
    return ("ref", sheet, r, c, r, c)


def quote_sheet(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_][\w.]*", name) else "'" + name.replace("'", "''") + "'"


# ------------------------------------------------------------------------------------------------ moving references
def shift_formula(src: str, dr: int, dc: int) -> str:
    """A formula copied dr rows and dc columns away: relative references move, $-fixed ones stay."""
    if not src.startswith("="):
        return src

    def cell(part: str) -> str:
        m = re.fullmatch(r"(\$?)([A-Za-z]{1,3})(\$?)(\d{1,6})", part)
        if not m:
            m2 = re.fullmatch(r"(\$?)([A-Za-z]{1,3})", part)
            if m2:
                c = col_index(m2.group(2)) + (0 if m2.group(1) else dc)
                return m2.group(1) + (col_name(c) if c >= 0 else "#REF!")
            m3 = re.fullmatch(r"(\$?)(\d{1,6})", part)
            if m3:
                r = int(m3.group(2)) + (0 if m3.group(1) else dr)
                return m3.group(1) + (str(r) if r >= 1 else "#REF!")
            return part
        c = col_index(m.group(2)) + (0 if m.group(1) else dc)
        r = int(m.group(4)) - 1 + (0 if m.group(3) else dr)
        if c < 0 or r < 0:
            return "#REF!"
        return f"{m.group(1)}{col_name(c)}{m.group(3)}{r + 1}"
    return _rewrite_refs(src, lambda sheet, cells: ":".join(cell(p) for p in cells.split(":")))


def _rewrite_refs(src: str, fn) -> str:
    try:
        toks = tokens(src[1:])
    except Err:
        return src
    out, last = [], 0
    body = src[1:]
    for kind, val, a, b in toks:
        if kind == "ref":
            sheet, cells = split_ref(val)
            new = fn(sheet, cells)
            if "#REF!" in new:
                new = "#REF!"
            elif sheet is not None:
                new = val[:len(val) - len(cells)] + new
            out.append(body[last:a] + new)
            last = b
    out.append(body[last:])
    return "=" + "".join(out)


def move_refs(src: str, this_sheet: str, target_sheet: str, axis: str, at: int, count: int) -> str:
    """Rows (axis 'r') or columns ('c') put in (count > 0) or taken out (count < 0) at `at` on `target_sheet`:
    the references to cells there move the same way; a reference wholly inside what was taken out becomes #REF!,
    and a range losing one end ends where the cut was."""
    if not src.startswith("="):
        return src
    gone_to = at - count if count < 0 else at          # [at, gone_to) taken out

    def moved(v: int, end: bool):
        """Where index v goes; None when it was taken out (an end of a range: to the edge of the cut)."""
        if count > 0:
            return v + count if v >= at else v
        if v >= gone_to:
            return v + count
        if v >= at:
            return None
        return v

    def fix(sheet, cells):
        if (sheet or this_sheet) != target_sheet:
            return cells
        parts = cells.split(":")
        ends = []
        for k, p in enumerate(parts):
            m = re.fullmatch(r"(\$?)([A-Za-z]{1,3})?(\$?)(\d{1,6})?", p)
            if not m or not (m.group(2) or m.group(4)):
                return cells
            ends.append([m.group(1), m.group(2), m.group(3), m.group(4)])
        out = []
        for k, (d1, letters, d2, digits) in enumerate(ends):
            if axis == "c" and letters:
                c = moved(col_index(letters), k == len(ends) - 1)
                if c is None:
                    if len(ends) == 1:
                        return "#REF!"
                    c = at if k == 0 else at - 1
                letters = col_name(c) if c >= 0 else None
                if letters is None:
                    return "#REF!"
            if axis == "r" and digits:
                r = moved(int(digits) - 1, k == len(ends) - 1)
                if r is None:
                    if len(ends) == 1:
                        return "#REF!"
                    r = at if k == 0 else at - 1
                if r < 0:
                    return "#REF!"
                digits = str(r + 1)
            out.append(f"{d1}{letters or ''}{d2}{digits or ''}")
        if len(out) == 2:                                  # both ends in what went: the whole range went
            a, b = ends[0], ends[1]
            idx = (lambda e: col_index(e[1]) if axis == "c" else int(e[3]) - 1)
            if count < 0 and (a[1] if axis == "c" else a[3]) and at <= idx(a) and idx(b) < gone_to:
                return "#REF!"
        return ":".join(out)
    return _rewrite_refs(src, fix)


def rename_sheet_refs(src: str, old: str, new: str) -> str:
    if not src.startswith("=") or "!" not in src:
        return src
    try:
        toks = tokens(src[1:])
    except Err:
        return src
    body, out, last = src[1:], [], 0
    for kind, val, a, b in toks:
        if kind == "ref":
            sheet, cells = split_ref(val)
            if sheet == old:
                out.append(body[last:a] + quote_sheet(new) + "!" + cells)
                last = b
    out.append(body[last:])
    return "=" + "".join(out)


# ------------------------------------------------------------------------------------------------ working them out
class Book:
    """The workbook: sheets of cells, and the values worked out from them."""

    def __init__(self):
        self.sheets = []                 # [{"name", "raw": {(r, c): text}}]
        self._cache = {}
        self._parsed = {}
        self._bounds = {}
        self.day_first = False

    def sheet_index(self, name):
        if name is None:
            return None
        low = name.lower()
        for i, sh in enumerate(self.sheets):
            if sh["name"].lower() == low:
                return i
        return -1

    def changed(self):
        self._cache.clear()
        self._bounds = {}

    _bounds = {}

    def used(self, s: int) -> tuple:
        """(last row, last column) with anything in them on sheet s, or (-1, -1)."""
        hit = self._bounds.get(s)
        if hit is None:
            raw = self.sheets[s]["raw"]
            hit = (max(r for r, _ in raw), max(c for _, c in raw)) if raw else (-1, -1)
            self._bounds[s] = hit
        return hit

    def raw(self, s: int, r: int, c: int) -> str:
        return self.sheets[s]["raw"].get((r, c), "")

    def value(self, s: int, r: int, c: int, _stack=None):
        key = (s, r, c)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        stack = _stack if _stack is not None else set()
        if key in stack:
            return Err("#CYCLE!")
        text = self.sheets[s]["raw"].get((r, c), "")
        if not text:
            v = BLANK
        elif text.startswith("=") and len(text) > 1:
            stack.add(key)
            try:
                tree = self._parsed.get(text)
                if tree is None:
                    tree = Parser(text[1:]).parse()
                    if len(self._parsed) > 20000:
                        self._parsed.clear()
                    self._parsed[text] = tree
                v = self.eval(tree, s, stack)
                if isinstance(v, Area):                    # a range on its own: its first value (no spilling yet)
                    v = v.rows[0][0] if v.rows and v.rows[0] else BLANK
                if v is BLANK:
                    v = 0.0
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    v = Err("#NUM!")
            except Err as e:
                v = e
            except ZeroDivisionError:
                v = Err("#DIV/0!")
            except (ValueError, TypeError, OverflowError, IndexError):
                v = Err("#VALUE!")
            except RecursionError:
                v = Err("#CYCLE!")
            stack.discard(key)
        else:
            v = literal(text, self.day_first)[0] if not text.startswith("'") else text[1:]
        self._cache[key] = v
        return v

    # -- the tree
    def eval(self, node, s, stack):
        kind = node[0]
        if kind == "num":
            return node[1]
        if kind == "str":
            return node[1]
        if kind == "bool":
            return node[1]
        if kind == "err":
            return Err(node[1])
        if kind == "blank":
            return BLANK
        if kind == "ref":
            _, sheet, r0, c0, r1, c1 = node
            si = s if sheet is None else self.sheet_index(sheet)
            if si is None or si < 0:
                raise Err("#REF!")
            if r0 == r1 and c0 == c1:
                v = self.value(si, r0, c0, stack)
                return v
            used_r, used_c = self.used(si)                   # a whole column or row: only as far as there's something
            if r1 - r0 > 2000 or c1 - c0 > 200:
                r1, c1 = min(r1, max(r0, used_r)), min(c1, max(c0, used_c))
            return Area([[self.value(si, r, c, stack) for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)], si, r0, c0)
        if kind == "array":
            return Area([[self.eval(x, s, stack) for x in row] for row in node[1]])
        if kind == "neg":
            return -num(self.eval(node[1], s, stack))
        if kind == "pct":
            return num(self.eval(node[1], s, stack)) / 100
        if kind == "op":
            return binary(node[1], self.eval(node[2], s, stack), self.eval(node[3], s, stack))
        if kind == "name":
            raise Err("#NAME?")
        if kind == "fn":
            name, args = node[1], node[2]
            if name in LAZY:
                return LAZY[name](self, args, s, stack)
            fn = FUNCS.get(name) or FUNCS.get(name.replace("_XLFN.", ""))
            if fn is None:
                raise Err("#NAME?")
            vals = [self.eval(a, s, stack) for a in args]
            return fn(*vals)
        raise Err("#ERROR!")


def scalar(v):
    if isinstance(v, Area):
        if v.height == 1 and v.width == 1:
            return v.rows[0][0]
        raise Err("#VALUE!")
    return v


def num(v) -> float:
    v = scalar(v)
    if isinstance(v, Err):
        raise v
    if v is BLANK:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        val, _ = literal(v)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
    raise Err("#VALUE!")


def text(v) -> str:
    v = scalar(v)
    if isinstance(v, Err):
        raise v
    if v is BLANK:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return general(v)
    return str(v)


def truth(v) -> bool:
    v = scalar(v)
    if isinstance(v, Err):
        raise v
    if v is BLANK:
        return False
    if isinstance(v, str):
        up = v.upper()
        if up in ("TRUE", "FALSE"):
            return up == "TRUE"
        raise Err("#VALUE!")
    return bool(v)


def general(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    s = f"{v:.10g}"
    return s


def compare(op: str, a, b) -> bool:
    a, b = scalar(a), scalar(b)
    for x in (a, b):
        if isinstance(x, Err):
            raise x
    rank = lambda x: 0 if isinstance(x, (int, float)) and not isinstance(x, bool) else 1 if isinstance(x, str) else 2   # noqa: E731
    if a is BLANK:
        a = "" if isinstance(b, str) else (False if isinstance(b, bool) else 0.0)
    if b is BLANK:
        b = "" if isinstance(a, str) else (False if isinstance(a, bool) else 0.0)
    if rank(a) != rank(b):
        x, y = rank(a), rank(b)
    else:
        x, y = (a.lower(), b.lower()) if isinstance(a, str) else (a, b)
    return {"=": x == y, "<>": x != y, "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]


def binary(op, a, b):
    if isinstance(a, Area) or isinstance(b, Area):
        A = a if isinstance(a, Area) else None
        B = b if isinstance(b, Area) else None
        shape = A or B
        if A and B and (A.height, A.width) != (B.height, B.width):
            if not (A.height * A.width == 1 or B.height * B.width == 1):
                raise Err("#VALUE!")
        rows = []
        for i in range(shape.height):
            row = []
            for j in range(shape.width):
                x = A.rows[min(i, A.height - 1)][min(j, A.width - 1)] if A else a
                y = B.rows[min(i, B.height - 1)][min(j, B.width - 1)] if B else b
                try:
                    row.append(binary(op, x, y))
                except Err as e:
                    row.append(e)
                except ZeroDivisionError:
                    row.append(Err("#DIV/0!"))
            rows.append(row)
        return Area(rows)
    if op in ("=", "<>", "<", ">", "<=", ">="):
        return compare(op, a, b)
    if op == "&":
        return text(a) + text(b)
    x, y = num(a), num(b)
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if op == "/":
        if y == 0:
            raise Err("#DIV/0!")
        return x / y
    if op == "^":
        if x == 0 and y < 0:
            raise Err("#DIV/0!")
        r = x ** y
        if isinstance(r, complex):
            raise Err("#NUM!")
        return float(r)
    raise Err("#ERROR!")


# ------------------------------------------------------------------------------------------------ the functions
def flat(args, keep_text_args=False):
    """Every value in the arguments, ranges opened up."""
    for a in args:
        if isinstance(a, Area):
            yield from a.flat()
        else:
            yield a


def numbers(args):
    """The numbers among the arguments (Excel's way: in a range only numbers count; typed straight in, numbers,
    true/false and number-like text)."""
    out = []
    for a in args:
        if isinstance(a, Area):
            for v in a.flat():
                if isinstance(v, Err):
                    raise v
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append(float(v))
        elif a is BLANK:
            continue
        else:
            out.append(num(a))
    return out


def criterion(spec):
    """A test from SUMIF's criteria: 5, ">5", "<>x", "a*", "=", ..."""
    spec = scalar(spec)
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == float(spec)
    if isinstance(spec, bool):
        return lambda v: v is spec
    s = text(spec)
    m = re.match(r"(<>|<=|>=|=|<|>)?(.*)", s, re.S)
    op, rest = m.group(1) or "=", m.group(2)
    val, _ = literal(rest) if rest else (BLANK, "")
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        def test(v):
            if not (isinstance(v, (int, float)) and not isinstance(v, bool)):
                return op == "<>"
            return {"=": v == val, "<>": v != val, "<": v < val, ">": v > val, "<=": v <= val, ">=": v >= val}[op]
        return test
    if rest == "" and op in ("=", "<>"):
        return (lambda v: v is BLANK or v == "") if op == "=" else (lambda v: not (v is BLANK or v == ""))
    if any(ch in rest for ch in "*?~"):
        pat = re.compile("".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in rest), re.I | re.S)
        hit = lambda v: isinstance(v, str) and pat.fullmatch(v) is not None      # noqa: E731
        return hit if op == "=" else (lambda v: not hit(v))
    low = rest.lower()
    if op == "=":
        return lambda v: isinstance(v, str) and v.lower() == low
    if op == "<>":
        return lambda v: not (isinstance(v, str) and v.lower() == low)
    return lambda v: isinstance(v, str) and {"<": v.lower() < low, ">": v.lower() > low, "<=": v.lower() <= low, ">=": v.lower() >= low}[op]


def _ifs(agg, target, *pairs):
    if len(pairs) % 2:
        raise Err("#VALUE!")
    tests = [(p if isinstance(p, Area) else Area([[p]]), criterion(c)) for p, c in zip(pairs[::2], pairs[1::2])]
    target = target if isinstance(target, Area) else Area([[target]])
    picked = []
    for i in range(target.height):
        for j in range(target.width):
            if all(i < a.height and j < a.width and t(a.rows[i][j]) for a, t in tests):
                v = target.rows[i][j]
                picked.append(v)
    return agg(picked)


def _sum_of(vals):
    return math.fsum(float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool))


def _avg_of(vals):
    xs = [float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not xs:
        raise Err("#DIV/0!")
    return math.fsum(xs) / len(xs)


def _lookup_eq(a, b, exact=True):
    if isinstance(a, str) and isinstance(b, str):
        if exact and any(ch in b for ch in "*?"):
            return criterion(b)(a)
        return a.lower() == b.lower()
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return float(a) == float(b)
    return a == b


def _match(value, values, mode=1.0):
    value = scalar(value)
    mode = int(num(mode))
    if mode == 0:
        for i, v in enumerate(values):
            if _lookup_eq(v, value):
                return i
        raise Err("#N/A")
    best = None
    for i, v in enumerate(values):                      # sorted: the last one not past it (or not before it, for -1)
        if v is BLANK or type(v) is not type(value) and not (isinstance(v, (int, float)) and isinstance(value, (int, float))):
            continue
        try:
            ok = compare("<=", v, value) if mode > 0 else compare(">=", v, value)
        except Err:
            continue
        if ok:
            best = i
        else:
            break
    if best is None:
        raise Err("#N/A")
    return best


def _vlookup(value, table, col, approx=True, horizontal=False):
    if not isinstance(table, Area):
        raise Err("#VALUE!")
    col = int(num(col)) - 1
    rows = table.rows if not horizontal else [list(x) for x in zip(*table.rows)]
    if col < 0 or (rows and col >= len(rows[0])):
        raise Err("#REF!")
    keys = [r[0] for r in rows]
    exact = not truth(approx) if approx is not BLANK else False
    i = _match(value, keys, 0 if exact else 1)
    return rows[i][col]


def _xlookup(value, look, back, missing=None, mode=0.0, *_):
    lv = list(look.flat()) if isinstance(look, Area) else [look]
    mode = int(num(mode)) if mode is not None and mode is not BLANK else 0
    value = scalar(value)
    idx = None
    for i, v in enumerate(lv):
        if _lookup_eq(v, value, exact=True):
            idx = i
            break
    if idx is None and mode in (-1, 1):
        cands = [(v, i) for i, v in enumerate(lv) if isinstance(v, (int, float)) and isinstance(value, (int, float))]
        cands = [c for c in cands if (c[0] < value if mode == -1 else c[0] > value)]
        if cands:
            idx = (max(cands) if mode == -1 else min(cands))[1]
    if idx is None:
        if missing is not None and missing is not BLANK:
            return missing
        raise Err("#N/A")
    if isinstance(back, Area):
        if back.height == len(lv) and back.width >= 1 and look.height == len(lv):
            return back.rows[idx][0] if back.width == 1 else Area([back.rows[idx]])
        flatb = list(back.flat())
        return flatb[idx] if idx < len(flatb) else Err("#N/A")
    return back


def _index(area, row, col=None):
    if not isinstance(area, Area):
        return area
    r = int(num(row)) if row is not BLANK else 0
    c = int(num(col)) if col is not None and col is not BLANK else 0
    if area.height == 1 and col is None:
        r, c = 1, r
    if r < 0 or c < 0 or r > area.height or c > area.width:
        raise Err("#REF!")
    if r == 0:
        return Area([[row_[c - 1]] for row_ in area.rows])
    if c == 0:
        return Area([area.rows[r - 1]]) if area.width > 1 else area.rows[r - 1][0]
    return area.rows[r - 1][c - 1]


def _text_fmt(v, fmt):
    return format_value(v, text(fmt))


def _round(v, d, how):
    x, d = num(v), int(num(d)) if d is not BLANK else 0
    f = 10 ** d
    if how == "half":
        q = abs(x) * f
        r = math.floor(q + 0.5 + 1e-9)
        return math.copysign(r / f, x) if x else 0.0
    if how == "up":
        return math.copysign(math.ceil(abs(x) * f - 1e-9) / f, x)
    return math.copysign(math.floor(abs(x) * f + 1e-9) / f, x)


def _date(y, m, d):
    y, m, d = int(num(y)), int(num(m)), int(num(d))
    if y < 1900:
        y += 1900
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    base = dt.date(y, m, 1)
    return from_date(base) + d - 1


def _edate(start, months, end_of_month=False):
    d = to_date(num(start)).date()
    m = d.month - 1 + int(num(months))
    y, m = d.year + m // 12, m % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return from_date(dt.date(y, m, last if end_of_month else min(d.day, last)))


def _datedif(a, b, unit):
    d1, d2 = to_date(num(a)).date(), to_date(num(b)).date()
    if d1 > d2:
        raise Err("#NUM!")
    u = text(unit).upper()
    months = (d2.year - d1.year) * 12 + d2.month - d1.month - (1 if d2.day < d1.day else 0)
    if u == "D":
        return float((d2 - d1).days)
    if u == "M":
        return float(months)
    if u == "Y":
        return float(months // 12)
    if u == "YM":
        return float(months % 12)
    if u == "MD":                                     # the days, as if in the same month
        if d2.day >= d1.day:
            return float(d2.day - d1.day)
        py, pm = (d2.year, d2.month - 1) if d2.month > 1 else (d2.year - 1, 12)
        return float(calendar.monthrange(py, pm)[1] - d1.day + d2.day)
    if u == "YD":
        x = d1.replace(year=d2.year)
        if x > d2:
            x = d1.replace(year=d2.year - 1)
        return float((d2 - x).days)
    raise Err("#NUM!")


def _networkdays(a, b, holidays=None):
    d1, d2 = to_date(num(a)).date(), to_date(num(b)).date()
    sign = 1
    if d1 > d2:
        d1, d2, sign = d2, d1, -1
    off = {to_date(v).date() for v in numbers([holidays])} if holidays is not None and holidays is not BLANK else set()
    n = sum(1 for k in range((d2 - d1).days + 1) if (d1 + dt.timedelta(k)).weekday() < 5 and (d1 + dt.timedelta(k)) not in off)
    return float(n * sign)


def _workday(start, days, holidays=None):
    d = to_date(num(start)).date()
    n = int(num(days))
    off = {to_date(v).date() for v in numbers([holidays])} if holidays is not None and holidays is not BLANK else set()
    step = 1 if n >= 0 else -1
    while n:
        d += dt.timedelta(step)
        if d.weekday() < 5 and d not in off:
            n -= step
    return from_date(d)


def _pmt(rate, nper, pv, fv=0.0, when=0.0):
    r, n, p, f, w = num(rate), num(nper), num(pv), num(fv) if fv is not BLANK else 0.0, num(when) if when is not BLANK else 0.0
    if n == 0:
        raise Err("#NUM!")
    if r == 0:
        return -(p + f) / n
    g = (1 + r) ** n
    return -(r * (p * g + f)) / ((1 + r * w) * (g - 1))


def _fv(rate, nper, pmt, pv=0.0, when=0.0):
    r, n, m, p, w = num(rate), num(nper), num(pmt), num(pv) if pv is not BLANK else 0.0, num(when) if when is not BLANK else 0.0
    if r == 0:
        return -(p + m * n)
    g = (1 + r) ** n
    return -(p * g + m * (1 + r * w) * (g - 1) / r)


def _pv(rate, nper, pmt, fv=0.0, when=0.0):
    r, n, m, f, w = num(rate), num(nper), num(pmt), num(fv) if fv is not BLANK else 0.0, num(when) if when is not BLANK else 0.0
    if r == 0:
        return -(f + m * n)
    g = (1 + r) ** n
    return -(f + m * (1 + r * w) * (g - 1) / r) / g


def _nper(rate, pmt, pv, fv=0.0, when=0.0):
    r, m, p, f, w = num(rate), num(pmt), num(pv), num(fv) if fv is not BLANK else 0.0, num(when) if when is not BLANK else 0.0
    if r == 0:
        if m == 0:
            raise Err("#NUM!")
        return -(p + f) / m
    z = m * (1 + r * w) / r
    if (-f + z) / (p + z) <= 0:
        raise Err("#NUM!")
    return math.log((-f + z) / (p + z)) / math.log(1 + r)


def _npv(rate, *flows):
    r = num(rate)
    return math.fsum(v / (1 + r) ** (i + 1) for i, v in enumerate(numbers(flows)))


def _irr(values, guess=0.1):
    flows = numbers([values])
    r = num(guess) if guess is not BLANK else 0.1
    for _ in range(100):
        f = sum(v / (1 + r) ** i for i, v in enumerate(flows))
        d = sum(-i * v / (1 + r) ** (i + 1) for i, v in enumerate(flows))
        if d == 0:
            break
        nr = r - f / d
        if abs(nr - r) < 1e-10:
            return nr
        r = nr
    raise Err("#NUM!")


def _rate(nper, pmt, pv, fv=0.0, when=0.0, guess=0.1):
    n, m, p = num(nper), num(pmt), num(pv)
    f = num(fv) if fv is not BLANK else 0.0
    w = num(when) if when is not BLANK else 0.0
    r = num(guess) if guess is not BLANK else 0.1
    for _ in range(200):
        if abs(r) < 1e-12:
            r = 1e-12
        g = (1 + r) ** n
        y = p * g + m * (1 + r * w) * (g - 1) / r + f
        dg = n * (1 + r) ** (n - 1)
        dy = p * dg + m * ((1 + r * w) * (dg * r - (g - 1)) / r ** 2 + w * (g - 1) / r)
        if dy == 0:
            break
        nr = r - y / dy
        if abs(nr - r) < 1e-12:
            return nr
        r = nr
    raise Err("#NUM!")


def _textjoin(sep, skip, *args):
    s, sk = text(sep), truth(skip)
    parts = [text(v) for v in flat(args)]
    return s.join(p for p in parts if not (sk and p == ""))


def _proper(v):
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), text(v))


def _find(needle, hay, start=1.0, case=True):
    n, h, st = text(needle), text(hay), int(num(start)) if start is not BLANK else 1
    if st < 1 or st > len(h) + 1:
        raise Err("#VALUE!")
    if case:
        i = h.find(n, st - 1)
    else:
        if any(ch in n for ch in "*?"):
            pat = re.compile("".join(".*?" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in n), re.I)
            m = pat.search(h, st - 1)
            i = m.start() if m else -1
        else:
            i = h.lower().find(n.lower(), st - 1)
    if i < 0:
        raise Err("#VALUE!")
    return float(i + 1)


def _substitute(t, old, new, which=None):
    t, o, n = text(t), text(old), text(new)
    if not o:
        return t
    if which is None or which is BLANK:
        return t.replace(o, n)
    k, idx = int(num(which)), -1
    for _ in range(k):
        idx = t.find(o, idx + 1)
        if idx < 0:
            return t
    return t[:idx] + n + t[idx + len(o):]


def _switch(value, *rest):
    v = scalar(value)
    pairs = list(rest)
    default = pairs.pop() if len(pairs) % 2 else None
    for a, b in zip(pairs[::2], pairs[1::2]):
        if _lookup_eq(v, scalar(a), exact=False):
            return b
    if default is None:
        raise Err("#N/A")
    return default


def _percentile(area, k, exclusive=False):
    xs = sorted(numbers([area]))
    p = num(k)
    if not xs or not 0 <= p <= 1:
        raise Err("#NUM!")
    pos = p * (len(xs) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _rank(v, area, order=0.0):
    x = num(v)
    xs = numbers([area])
    if x not in xs:
        raise Err("#N/A")
    asc = order is not BLANK and num(order) != 0
    return float(1 + sum(1 for y in xs if (y < x if asc else y > x)))


def _countif(area, spec):
    t = criterion(spec)
    return float(sum(1 for v in (area.flat() if isinstance(area, Area) else [area]) if t(v)))


def _choose(i, *opts):
    k = int(num(i))
    if not 1 <= k <= len(opts):
        raise Err("#VALUE!")
    return opts[k - 1]


def _weeknum(d, kind=1.0):
    day = to_date(num(d)).date()
    k = int(num(kind)) if kind is not BLANK else 1
    if k == 21:
        return float(day.isocalendar()[1])
    first = dt.date(day.year, 1, 1)
    start = 6 if k == 1 else 0                         # weeks start on Sunday (1) or Monday (2)
    offset = (first.weekday() - start) % 7
    return float((day - first).days + offset) // 7 + 1


def _sumproduct(*areas):
    rows = [list(a.flat()) if isinstance(a, Area) else [a] for a in areas]
    n = len(rows[0])
    if any(len(r) != n for r in rows):
        raise Err("#VALUE!")
    total = 0.0
    for k in range(n):
        p = 1.0
        for r in rows:
            v = r[k]
            p *= float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else (1.0 if v is True else 0.0)
        total += p
    return total


def _value(v):
    v = scalar(v)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    val, _ = literal(text(v))
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    raise Err("#VALUE!")


def _unique_rows(area):
    seen, out = set(), []
    rows = area.rows if isinstance(area, Area) else [[area]]
    for row in rows:
        key = tuple(str(v).lower() if isinstance(v, str) else v for v in row)
        if key not in seen:
            seen.add(key)
            out.append(row)
    return Area(out)


def _sort_rows(area, idx=1.0, order=1.0):
    rows = list(area.rows) if isinstance(area, Area) else [[area]]
    k = int(num(idx)) - 1 if idx is not BLANK else 0
    desc = order is not BLANK and num(order) < 0
    key = lambda r: (0, float(r[k])) if isinstance(r[k], (int, float)) and not isinstance(r[k], bool) else (1, str(r[k]).lower())   # noqa: E731
    return Area(sorted(rows, key=key, reverse=desc))


def _filter_rows(area, include, empty=None):
    rows = area.rows if isinstance(area, Area) else [[area]]
    flags = list(include.flat()) if isinstance(include, Area) else [include]
    out = [row for row, f in zip(rows, flags) if truth(f)]
    if not out:
        if empty is not None:
            return empty
        raise Err("#N/A")
    return Area(out)


def _nonzero(v, msg="#NUM!"):
    if v == 0:
        raise Err(msg)
    return v


def _stdev(args, pop):
    xs = numbers(args)
    if len(xs) < (1 if pop else 2):
        raise Err("#DIV/0!")
    return statistics.pstdev(xs) if pop else statistics.stdev(xs)


def _var(args, pop):
    xs = numbers(args)
    if len(xs) < (1 if pop else 2):
        raise Err("#DIV/0!")
    return statistics.pvariance(xs) if pop else statistics.variance(xs)


def _mode(*a):
    xs = numbers(a)
    if not xs:
        raise Err("#N/A")
    counts = {}
    for x in xs:
        counts[x] = counts.get(x, 0) + 1
    best = max(counts.values())
    if best == 1:
        raise Err("#N/A")
    return next(x for x in xs if counts[x] == best)


def _large(area, k, small=False):
    xs = sorted(numbers([area]), reverse=not small)
    k = int(num(k))
    if not 1 <= k <= len(xs):
        raise Err("#NUM!")
    return xs[k - 1]


def _ceiling(x, sig=1.0):
    x, s = num(x), num(sig) if sig is not BLANK else 1.0
    if s == 0:
        return 0.0
    return math.ceil(x / s - 1e-12) * s


def _floor(x, sig=1.0):
    x, s = num(x), num(sig) if sig is not BLANK else 1.0
    if s == 0:
        raise Err("#DIV/0!")
    return math.floor(x / s + 1e-12) * s


def _log(x, base=10.0):
    v, b = num(x), num(base) if base is not BLANK else 10.0
    if v <= 0 or b <= 0 or b == 1:
        raise Err("#NUM!")
    return math.log(v, b)


def _sqrt(x):
    v = num(x)
    if v < 0:
        raise Err("#NUM!")
    return math.sqrt(v)


def _ln(x):
    v = num(x)
    if v <= 0:
        raise Err("#NUM!")
    return math.log(v)


def _iserr(v):
    return isinstance(scalar(v) if not isinstance(v, Area) else v, Err)


FUNCS = {
    # maths
    "SUM": lambda *a: math.fsum(numbers(a)), "PRODUCT": lambda *a: math.prod(numbers(a)) if numbers(a) else 0.0,
    "AVERAGE": lambda *a: math.fsum(numbers(a)) / _nonzero(len(numbers(a)), "#DIV/0!"),
    "AVERAGEA": lambda *a: math.fsum(num(v) if not isinstance(v, str) else 0.0 for v in flat(a) if v is not BLANK) / _nonzero(sum(1 for v in flat(a) if v is not BLANK), "#DIV/0!"),
    "MIN": lambda *a: min(numbers(a), default=0.0), "MAX": lambda *a: max(numbers(a), default=0.0),
    "COUNT": lambda *a: float(sum(1 for v in flat(a) if isinstance(v, (int, float)) and not isinstance(v, bool))),
    "COUNTA": lambda *a: float(sum(1 for v in flat(a) if v is not BLANK and v != "")),
    "COUNTBLANK": lambda *a: float(sum(1 for v in flat(a) if v is BLANK or v == "")),
    "ROUND": lambda v, d=0.0: _round(v, d, "half"), "ROUNDUP": lambda v, d=0.0: _round(v, d, "up"), "ROUNDDOWN": lambda v, d=0.0: _round(v, d, "down"),
    "INT": lambda v: float(math.floor(num(v))), "TRUNC": lambda v, d=0.0: _round(v, d, "down"), "ABS": lambda v: abs(num(v)),
    "SQRT": _sqrt, "POWER": lambda a, b: binary("^", a, b), "MOD": lambda a, b: num(a) - num(b) * math.floor(num(a) / _nonzero(num(b), "#DIV/0!")),
    "EXP": lambda v: math.exp(num(v)), "LN": _ln, "LOG": _log, "LOG10": lambda v: _log(v, 10.0), "PI": lambda: math.pi,
    "RAND": lambda: random.random(), "RANDBETWEEN": lambda a, b: float(random.randint(math.ceil(num(a)), math.floor(num(b)))),
    "CEILING": _ceiling, "CEILING.MATH": _ceiling, "FLOOR": _floor, "FLOOR.MATH": _floor, "SIGN": lambda v: float((num(v) > 0) - (num(v) < 0)),
    "MROUND": lambda v, m: round(num(v) / _nonzero(num(m), "#NUM!")) * num(m), "EVEN": lambda v: math.copysign(math.ceil(abs(num(v)) / 2) * 2, num(v)),
    "ODD": lambda v: math.copysign(math.ceil((abs(num(v)) - 1) / 2) * 2 + 1, num(v)), "QUOTIENT": lambda a, b: float(int(num(a) / _nonzero(num(b), "#DIV/0!"))),
    "MEDIAN": lambda *a: statistics.median(numbers(a)) if numbers(a) else (_ for _ in ()).throw(Err("#NUM!")),
    "MODE": _mode, "MODE.SNGL": _mode,
    "STDEV": lambda *a: _stdev(a, False), "STDEV.S": lambda *a: _stdev(a, False), "STDEV.P": lambda *a: _stdev(a, True), "STDEVP": lambda *a: _stdev(a, True),
    "VAR": lambda *a: _var(a, False), "VAR.S": lambda *a: _var(a, False), "VAR.P": lambda *a: _var(a, True), "VARP": lambda *a: _var(a, True),
    "LARGE": lambda a, k: _large(a, k), "SMALL": lambda a, k: _large(a, k, True),
    "RANK": _rank, "RANK.EQ": _rank, "PERCENTILE": _percentile, "PERCENTILE.INC": _percentile,
    "QUARTILE": lambda a, q: _percentile(a, num(q) / 4), "QUARTILE.INC": lambda a, q: _percentile(a, num(q) / 4),
    "SUMPRODUCT": _sumproduct, "SUMSQ": lambda *a: math.fsum(x * x for x in numbers(a)),
    "SUMIF": lambda area, spec, target=None: _ifs(_sum_of, target if target is not None else area, area, spec),
    "SUMIFS": lambda target, *pairs: _ifs(_sum_of, target, *pairs),
    "AVERAGEIF": lambda area, spec, target=None: _ifs(_avg_of, target if target is not None else area, area, spec),
    "AVERAGEIFS": lambda target, *pairs: _ifs(_avg_of, target, *pairs),
    "COUNTIF": _countif, "COUNTIFS": lambda *pairs: _ifs(lambda vals: float(len(vals)), pairs[0], *pairs),
    "MAXIFS": lambda target, *pairs: _ifs(lambda vals: max([float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)], default=0.0), target, *pairs),
    "MINIFS": lambda target, *pairs: _ifs(lambda vals: min([float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)], default=0.0), target, *pairs),
    "FACT": lambda v: float(math.factorial(int(num(v)))) if num(v) >= 0 else (_ for _ in ()).throw(Err("#NUM!")),
    "GCD": lambda *a: float(math.gcd(*[int(x) for x in numbers(a)])), "LCM": lambda *a: float(math.lcm(*[int(x) for x in numbers(a)])),
    "DEGREES": lambda v: math.degrees(num(v)), "RADIANS": lambda v: math.radians(num(v)),
    "SIN": lambda v: math.sin(num(v)), "COS": lambda v: math.cos(num(v)), "TAN": lambda v: math.tan(num(v)),
    "ASIN": lambda v: math.asin(num(v)), "ACOS": lambda v: math.acos(num(v)), "ATAN": lambda v: math.atan(num(v)), "ATAN2": lambda x, y: math.atan2(num(y), num(x)),
    # logic
    "IF": None, "IFS": None, "IFERROR": None, "IFNA": None, "AND": None, "OR": None,   # (worked out lazily: see LAZY)
    "NOT": lambda v: not truth(v), "XOR": lambda *a: sum(1 for v in flat(a) if truth(v)) % 2 == 1,
    "TRUE": lambda: True, "FALSE": lambda: False, "SWITCH": _switch, "CHOOSE": _choose, "NA": lambda: (_ for _ in ()).throw(Err("#N/A")),
    # lookups
    "VLOOKUP": lambda v, t, c, a=True: _vlookup(v, t, c, a), "HLOOKUP": lambda v, t, r, a=True: _vlookup(v, t, r, a, horizontal=True),
    "XLOOKUP": _xlookup, "INDEX": _index,
    "MATCH": lambda v, area, mode=1.0: float(_match(v, list(area.flat()) if isinstance(area, Area) else [area], mode) + 1),
    "XMATCH": lambda v, area, mode=0.0: float(_match(v, list(area.flat()) if isinstance(area, Area) else [area], mode) + 1),
    "ROWS": lambda a: float(a.height if isinstance(a, Area) else 1), "COLUMNS": lambda a: float(a.width if isinstance(a, Area) else 1),
    "UNIQUE": _unique_rows, "SORT": _sort_rows, "FILTER": _filter_rows, "TRANSPOSE": lambda a: Area([list(r) for r in zip(*a.rows)]) if isinstance(a, Area) else a,
    # text
    "LEN": lambda v: float(len(text(v))), "UPPER": lambda v: text(v).upper(), "LOWER": lambda v: text(v).lower(), "PROPER": _proper,
    "TRIM": lambda v: " ".join(text(v).split()), "CLEAN": lambda v: "".join(ch for ch in text(v) if ch >= " "),
    "LEFT": lambda v, n=1.0: text(v)[:max(0, int(num(n)))], "RIGHT": lambda v, n=1.0: text(v)[-int(num(n)):] if int(num(n)) > 0 else "",
    "MID": lambda v, s, n: text(v)[max(0, int(num(s)) - 1):max(0, int(num(s)) - 1) + max(0, int(num(n)))],
    "FIND": lambda a, b, s=1.0: _find(a, b, s, True), "SEARCH": lambda a, b, s=1.0: _find(a, b, s, False),
    "SUBSTITUTE": _substitute, "REPLACE": lambda t, s, n, new: text(t)[:int(num(s)) - 1] + text(new) + text(t)[int(num(s)) - 1 + int(num(n)):],
    "CONCAT": lambda *a: "".join(text(v) for v in flat(a)), "CONCATENATE": lambda *a: "".join(text(v) for v in a),
    "TEXTJOIN": _textjoin, "TEXT": _text_fmt, "VALUE": _value, "NUMBERVALUE": _value, "REPT": lambda t, n: text(t) * max(0, int(num(n))),
    "EXACT": lambda a, b: text(a) == text(b), "CHAR": lambda n: chr(int(num(n))), "CODE": lambda t: float(ord(text(t)[0])) if text(t) else (_ for _ in ()).throw(Err("#VALUE!")),
    "UNICHAR": lambda n: chr(int(num(n))), "UNICODE": lambda t: float(ord(text(t)[0])) if text(t) else (_ for _ in ()).throw(Err("#VALUE!")),
    "T": lambda v: scalar(v) if isinstance(scalar(v), str) else "", "N": lambda v: num(v) if not isinstance(scalar(v), str) else 0.0,
    "DOLLAR": lambda v, d=2.0: format_value(num(v), "$#,##0." + "0" * int(num(d)) if int(num(d)) > 0 else "$#,##0"),
    "FIXED": lambda v, d=2.0, nc=False: format_value(_round(v, d, "half"), ("0" if truth(nc) else "#,##0") + ("." + "0" * int(num(d)) if int(num(d)) > 0 else "")),
    # dates
    "TODAY": lambda: float(from_date(dt.date.today())), "NOW": lambda: from_date(dt.datetime.now()),
    "DATE": _date, "TIME": lambda h, m, s: (num(h) * 3600 + num(m) * 60 + num(s)) % 86400 / 86400,
    "YEAR": lambda d: float(to_date(num(d)).year), "MONTH": lambda d: float(to_date(num(d)).month), "DAY": lambda d: float(to_date(num(d)).day),
    "HOUR": lambda d: float(to_date(num(d)).hour), "MINUTE": lambda d: float(to_date(num(d)).minute), "SECOND": lambda d: float(round(to_date(num(d)).second + to_date(num(d)).microsecond / 1e6) % 60),
    "WEEKDAY": lambda d, k=1.0: float({1: (to_date(num(d)).weekday() + 1) % 7 + 1, 2: to_date(num(d)).weekday() + 1, 3: to_date(num(d)).weekday()}[int(num(k)) if k is not BLANK else 1]),
    "WEEKNUM": _weeknum, "ISOWEEKNUM": lambda d: float(to_date(num(d)).isocalendar()[1]),
    "EDATE": lambda s, m: _edate(s, m), "EOMONTH": lambda s, m: _edate(s, m, True), "DATEDIF": _datedif,
    "DAYS": lambda a, b: float(math.floor(num(a)) - math.floor(num(b))), "NETWORKDAYS": _networkdays, "WORKDAY": _workday,
    "DATEVALUE": lambda t: float(math.floor(_value(t))), "TIMEVALUE": lambda t: _value(t) % 1,
    "YEARFRAC": lambda a, b, basis=0.0: abs(num(b) - num(a)) / 365.25,
    # information
    "ISBLANK": lambda v: scalar(v) is BLANK, "ISNUMBER": lambda v: isinstance(scalar(v), (int, float)) and not isinstance(scalar(v), bool),
    "ISTEXT": lambda v: isinstance(scalar(v), str), "ISNONTEXT": lambda v: not isinstance(scalar(v), str), "ISLOGICAL": lambda v: isinstance(scalar(v), bool),
    "ISERROR": _iserr, "ISERR": lambda v: _iserr(v) and scalar(v) != Err("#N/A"), "ISNA": lambda v: scalar(v) == Err("#N/A") if not isinstance(v, Area) else False,
    "ISEVEN": lambda v: int(num(v)) % 2 == 0, "ISODD": lambda v: int(num(v)) % 2 == 1,
    # money
    "PMT": _pmt, "FV": _fv, "PV": _pv, "NPER": _nper, "NPV": _npv, "IRR": _irr, "RATE": _rate,
    "IPMT": lambda r, per, n, pv, fv=0.0, w=0.0: _ipmt(r, per, n, pv, fv, w), "PPMT": lambda r, per, n, pv, fv=0.0, w=0.0: _pmt(r, n, pv, fv, w) - _ipmt(r, per, n, pv, fv, w),
}


def _ipmt(rate, per, nper, pv, fv=0.0, when=0.0):
    r, p = num(rate), int(num(per))
    payment = _pmt(rate, nper, pv, fv, when)
    balance = _fv(rate, p - 1, payment, pv, when)
    return balance * r if not (num(when) if when is not BLANK else 0) else (balance - payment) * r if p > 1 else 0.0


def _lazy_if(book, args, s, stack):
    if len(args) < 1:
        raise Err("#VALUE!")
    cond = book.eval(args[0], s, stack)
    if isinstance(cond, Area):
        return Area([[book.eval(args[1], s, stack) if truth(v) else (book.eval(args[2], s, stack) if len(args) > 2 else False) for v in row] for row in cond.rows])
    if truth(cond):
        return book.eval(args[1], s, stack) if len(args) > 1 else True
    return book.eval(args[2], s, stack) if len(args) > 2 else False


def _lazy_ifs(book, args, s, stack):
    for c, v in zip(args[::2], args[1::2]):
        if truth(book.eval(c, s, stack)):
            return book.eval(v, s, stack)
    raise Err("#N/A")


def _lazy_iferror(book, args, s, stack, only=None):
    try:
        v = book.eval(args[0], s, stack)
        if isinstance(v, Area):
            return v
        if isinstance(v, Err) and (only is None or v.code == only):
            return book.eval(args[1], s, stack)
        return v
    except Err as e:
        if only is None or e.code == only:
            return book.eval(args[1], s, stack)
        raise
    except ZeroDivisionError:
        if only is None:
            return book.eval(args[1], s, stack)
        raise


def _lazy_bool(book, args, s, stack, every):
    vals = []
    for a in args:
        v = book.eval(a, s, stack)
        for x in (v.flat() if isinstance(v, Area) else [v]):
            if isinstance(x, Err):
                raise x
            if x is BLANK or isinstance(x, str) and isinstance(v, Area):
                continue
            vals.append(truth(x))
    if not vals:
        raise Err("#VALUE!")
    return all(vals) if every else any(vals)


def _lazy_row(book, args, s, stack, col=False):
    if not args:
        raise Err("#VALUE!")
    node = args[0]
    if node[0] != "ref":
        raise Err("#VALUE!")
    return float((node[3] if col else node[2]) + 1)


LAZY = {"IF": _lazy_if, "IFS": _lazy_ifs, "IFERROR": _lazy_iferror,
        "IFNA": lambda b, a, s, st: _lazy_iferror(b, a, s, st, "#N/A"),
        "AND": lambda b, a, s, st: _lazy_bool(b, a, s, st, True), "OR": lambda b, a, s, st: _lazy_bool(b, a, s, st, False),
        "ROW": _lazy_row, "COLUMN": lambda b, a, s, st: _lazy_row(b, a, s, st, True)}
FUNCS = {k: v for k, v in FUNCS.items() if v is not None}
NAMES = sorted(set(FUNCS) | set(LAZY))


# ------------------------------------------------------------------------------------------------ showing values
def _thousands(s: str) -> str:
    head, _, tail = s.partition(".")
    neg = head.startswith("-")
    head = head.lstrip("-")
    out = ""
    while len(head) > 3:
        out = "," + head[-3:] + out
        head = head[:-3]
    return ("-" if neg else "") + head + out + ("." + tail if tail else "")


def format_value(v, fmt: str = "") -> str:
    """A value as it shows in its cell, by its number format (a subset of Excel's codes)."""
    if isinstance(v, Area):
        v = v.rows[0][0] if v.rows and v.rows[0] else BLANK
    if v is BLANK:
        return ""
    if isinstance(v, Err):
        return v.code
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, str):
        return v
    x = float(v)
    f = fmt or "General"
    if f in ("General", ""):
        if x == int(x) and abs(x) < 1e15:
            return str(int(x))
        if abs(x) >= 1e11 or (abs(x) < 1e-9 and x != 0):
            return f"{x:.5E}"
        s = f"{x:.10f}".rstrip("0").rstrip(".")
        digits = len(s.replace("-", "").replace(".", ""))
        if digits > 11:
            s = f"{x:.{max(0, 10 - len(str(int(abs(x)))))}f}".rstrip("0").rstrip(".")
        return s
    if f == "@":
        return general(x)
    if f in ("short-date", "yyyy-mm-dd", "d mmm yyyy", "mmm d, yyyy", "yyyy-mm-dd hh:mm", "m/d/yyyy", "d/m/yyyy", "dd/mm/yyyy", "mm/dd/yyyy", "dddd"):
        try:
            d = to_date(x)
        except (OverflowError, ValueError):
            return "#####"
        return {"yyyy-mm-dd": d.strftime("%Y-%m-%d"), "d mmm yyyy": f"{d.day} {d.strftime('%b %Y')}", "mmm d, yyyy": f"{d.strftime('%b')} {d.day}, {d.year}",
                "yyyy-mm-dd hh:mm": d.strftime("%Y-%m-%d %H:%M"), "m/d/yyyy": f"{d.month}/{d.day}/{d.year}", "d/m/yyyy": f"{d.day}/{d.month}/{d.year}",
                "dd/mm/yyyy": d.strftime("%d/%m/%Y"), "mm/dd/yyyy": d.strftime("%m/%d/%Y"), "dddd": d.strftime("%A"),
                "short-date": f"{d.month}/{d.day}/{d.year}"}[f]
    if f in ("hh:mm", "hh:mm:ss", "h:mm AM/PM"):
        secs = round((x % 1) * 86400)
        h, m, sec = secs // 3600 % 24, secs // 60 % 60, secs % 60
        if f == "h:mm AM/PM":
            return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"
        return f"{h:02d}:{m:02d}" + (f":{sec:02d}" if f == "hh:mm:ss" else "")
    m = re.fullmatch(r"([$€£¥]?)(#,##)?0(\.0+)?(%?)(E\+00)?([$€£¥]?)", f.replace('"', ""))
    if m:
        cur, comma, dec, pct, sci, cur2 = m.groups()
        places = len(dec) - 1 if dec else 0
        y = x * 100 if pct else x
        if sci:
            return f"{y:.{places}E}"
        s = f"{abs(y):.{places}f}"
        if comma:
            s = _thousands(s)
        s = (cur or "") + s + (cur2 or "") + ("%" if pct else "")
        return ("-" + s) if y < 0 and float(f"{abs(y):.{places}f}") != 0 else s
    if ";" in f:                                       # positive;negative: use the first part's shape
        return format_value(x, f.split(";")[0])
    return general(x)


FORMATS = [("General", "General", ""), ("Number", "#,##0.00", "1,234.50"), ("Whole number", "#,##0", "1,235"),
           ("Currency", "$#,##0.00", "$1,234.50"), ("Percent", "0%", "12%"), ("Percent, 2 places", "0.00%", "12.34%"),
           ("Date", "short-date", "11/19/2026"), ("Date (ISO)", "yyyy-mm-dd", "2026-11-19"), ("Long date", "d mmm yyyy", "19 Nov 2026"),
           ("Time", "hh:mm", "14:30"), ("Scientific", "0.00E+00", "1.23E+03"), ("Text", "@", "plain text")]


def more_places(fmt: str, delta: int) -> str:
    """A number format with one decimal place more or fewer."""
    if fmt in ("General", "", "@"):
        return "0." + "0" * max(1, delta + 1) if delta > 0 else "0"
    m = re.fullmatch(r"([$€£¥]?(?:#,##)?0)(\.0+)?(%?)(E\+00)?", fmt)
    if not m:
        return fmt
    places = len(m.group(2)) - 1 if m.group(2) else 0
    places = max(0, min(10, places + delta))
    return m.group(1) + ("." + "0" * places if places else "") + m.group(3) + (m.group(4) or "")


# ------------------------------------------------------------------------------------------------ filling
SERIES = [[calendar.day_name[i] for i in range(7)], [calendar.day_abbr[i] for i in range(7)],
          [calendar.month_name[i] for i in range(1, 13)], [calendar.month_abbr[i] for i in range(1, 13)], ["Q1", "Q2", "Q3", "Q4"]]


def fill_values(seed: list, count: int, day_first: bool = False) -> list:
    """What dragging the fill handle over `count` more cells puts in them, from the cells already there (`seed`, raw
    texts, in order): numbers and dates go on by their step, names of days and months go round, "Item 3" counts up,
    formulas move their references, and anything else repeats."""
    if not seed:
        return [""] * count
    vals = [literal(t, day_first) for t in seed]
    nums = [v for v, _ in vals]
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in nums) and not any(t.startswith("=") for t in seed):
        if len(nums) == 1:
            step = 1.0 if vals[0][1] in ("short-date", "yyyy-mm-dd", "d mmm yyyy") else 0.0
            if step == 0.0:
                return [seed[0]] * count
        else:
            step = (nums[-1] - nums[0]) / (len(nums) - 1)
        fmt = vals[-1][1]
        return [format_value(nums[-1] + step * k, fmt) if fmt else general(nums[-1] + step * k) for k in range(1, count + 1)]
    for names in SERIES:
        low = [n.lower() for n in names]
        if all(t.strip().lower() in low for t in seed):
            idx = [low.index(t.strip().lower()) for t in seed]
            step = (idx[-1] - idx[0]) // max(1, len(idx) - 1) if len(idx) > 1 else 1
            case = (lambda s: s.upper()) if seed[-1].isupper() and len(seed[-1]) > 1 else (lambda s: s.lower()) if seed[-1].islower() else (lambda s: s)
            return [case(names[(idx[-1] + step * k) % len(names)]) for k in range(1, count + 1)]
    m = [re.fullmatch(r"(.*?)(\d+)(\D*)", t) for t in seed]
    if all(m) and not any(t.startswith("=") for t in seed) and len({(x.group(1), x.group(3)) for x in m}) == 1:
        ns = [int(x.group(2)) for x in m]
        step = (ns[-1] - ns[0]) // max(1, len(ns) - 1) if len(ns) > 1 else 1
        width = len(m[-1].group(2))
        return [f"{m[-1].group(1)}{str(ns[-1] + step * k).zfill(width)}{m[-1].group(3)}" for k in range(1, count + 1)]
    return [seed[k % len(seed)] for k in range(count)]
