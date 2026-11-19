"""Sheets: what may go in cells (Excel's data validation) and notes on cells.

A check covers a block of cells: a list to pick from (typed out, or the cells of a range), or whole numbers, numbers,
dates or text of a length, between two values or above or below one. With `stop` anything else is turned away;
without it, it's let in with a word of warning. Checks follow rows and columns inserted and deleted (huginn_sheets),
and go to Excel's dataValidations and come back (huginn_xlsx).

A note is a few words on a cell, with who wrote it and when; it shows as a small red corner on the cell.
"""
import re

import huginn_sheet_engine as se

KINDS = ("list", "whole", "decimal", "date", "length")
OPS = ("between", "notBetween", "equal", "notEqual", "greaterThan", "lessThan", "greaterThanOrEqual", "lessThanOrEqual")
OP_WORDS = {"between": "between {a} and {b}", "notBetween": "not between {a} and {b}", "equal": "equal to {a}", "notEqual": "not {a}",
            "greaterThan": "more than {a}", "lessThan": "less than {a}", "greaterThanOrEqual": "{a} or more", "lessThanOrEqual": "{a} or less"}


def clean_check(raw) -> dict:
    """A check as Sheets keeps it, or None."""
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        return None
    try:
        span = [int(x) for x in raw.get("range")][:4]
    except (TypeError, ValueError):
        return None
    if len(span) != 4 or span[2] < span[0] or span[3] < span[1]:
        return None
    items = [str(x)[:255] for x in raw.get("items") or [] if str(x).strip()][:500]
    return {"id": str(raw.get("id") or "v1")[:12], "range": span, "kind": raw["kind"], "items": items,
            "source": str(raw.get("source") or "")[:120], "op": raw.get("op") if raw.get("op") in OPS else "between",
            "a": str(raw.get("a") or "")[:60], "b": str(raw.get("b") or "")[:60], "stop": bool(raw.get("stop", True)),
            "say": str(raw.get("say") or "")[:255]}


def covers(check: dict, r: int, c: int) -> bool:
    r0, c0, r1, c1 = check["range"]
    return r0 <= r <= r1 and c0 <= c <= c1


def choices(book, at: int, check: dict) -> list:
    """The values a list offers: typed out, or what the cells of its range show (each once, blanks left out)."""
    if check["kind"] != "list":
        return []
    if not check["source"]:
        return list(check["items"])
    try:
        node = se.ref_node(check["source"].lstrip("="))
    except (TypeError, ValueError, AttributeError, IndexError):
        return []
    _, sheet, r0, c0, r1, c1 = node
    s = book.sheet_index(sheet) if sheet else at
    if s is None or s < 0:
        return []
    out, seen = [], set()
    for r in range(r0, min(r1, r0 + 2000) + 1):
        for c in range(c0, min(c1, c0 + 50) + 1):
            v = book.value(s, r, c)
            if v is se.BLANK or isinstance(v, se.Err):
                continue
            t = se.format_value(v, "") if isinstance(v, (int, float)) and not isinstance(v, bool) else ("TRUE" if v is True else "FALSE" if v is False else str(v))
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


def _number(text: str, day_first: bool):
    v, _ = se.literal(text, day_first)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def describe(check: dict) -> str:
    k, a, b = check["kind"], check["a"], check["b"]
    if k == "list":
        return "Pick from " + (check["source"] if check["source"] else ", ".join(check["items"][:6]) + ("…" if len(check["items"]) > 6 else ""))
    what = {"whole": "Whole numbers", "decimal": "Numbers", "date": "Dates", "length": "Text"}[k]
    rule = OP_WORDS[check["op"]].format(a=a, b=b)
    return f"{what} {rule}" + (" characters long" if k == "length" else "")


def allowed(book, at: int, check: dict, text: str) -> str:
    """'' when the text may go in (empty always may), else why not, in plain words."""
    t = text.strip()
    if not t or t.startswith("="):
        return ""
    if check["kind"] == "list":
        offered = choices(book, at, check)
        if t in offered or t.lower() in (x.lower() for x in offered):
            return ""
        return check["say"] or "Pick one of the choices for this cell."
    day_first = getattr(book, "day_first", False)
    if check["kind"] == "length":
        v = float(len(t))
    else:
        v = _number(t, day_first)
        if v is None or (check["kind"] == "whole" and float(v) != int(v)):
            return check["say"] or ("This cell takes a whole number." if check["kind"] == "whole" else "This cell takes a date." if check["kind"] == "date" else "This cell takes a number.")
    a, b = _number(check["a"], day_first), _number(check["b"], day_first)
    if a is None and check["op"] != "between":
        return ""
    ok = {"between": lambda: (a is None or v >= a) and (b is None or v <= b), "notBetween": lambda: not ((a is None or v >= a) and (b is None or v <= b)),
          "equal": lambda: v == a, "notEqual": lambda: v != a, "greaterThan": lambda: v > a, "lessThan": lambda: v < a,
          "greaterThanOrEqual": lambda: v >= a, "lessThanOrEqual": lambda: v <= a}[check["op"]]()
    return "" if ok else (check["say"] or describe(check) + " here.")


def items_from_text(text: str) -> list:
    """'Yes, No, Maybe' (or one per line) -> the items."""
    parts = re.split(r"[,;\n]", text)
    out = []
    for p in parts:
        p = p.strip()
        if p and p not in out:
            out.append(p)
    return out


# ------------------------------------------------------------------------------------------------ notes
def clean_note(raw) -> dict:
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
        return None
    return {"text": str(raw["text"])[:4000], "by": str(raw.get("by") or "")[:80], "when": int(raw.get("when") or 0)}
