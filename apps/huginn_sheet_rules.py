"""Conditional formatting for Sheets: rules that colour cells by what's in them.

A sheet keeps its rules in order, the first that matches a cell giving it its colours ("rules": [...]). A rule:
    {"id": "c3", "range": [r0, c0, r1, c1], "kind": ..., "a": "10", "b": "20", "n": 10, "style": "red"}
kinds: gt ge lt le eq ne between (cell value against a and b), text (contains a), starts (begins with a),
dup and unique, top and bottom (n of them), above and below (the average), blank, notblank, error,
scale (a colour scale: low, high, and mid when set) and bar (data bars, in "color").
Colour scales and data bars don't stop the rules after them; the others do once they match.
"""
from __future__ import annotations

import huginn_sheet_engine as se

STYLES = {"red": {"fill": "#FFC7CE", "color": "#9C0006"}, "yellow": {"fill": "#FFEB9C", "color": "#9C5700"},
          "green": {"fill": "#C6EFCE", "color": "#006100"}, "blue": {"fill": "#DDEBF7", "color": "#1F4E78"},
          "redtext": {"color": "#C00000"}, "bold": {"b": True}}
COMPARE = {"gt": ">", "ge": ">=", "lt": "<", "le": "<=", "eq": "=", "ne": "<>"}
KINDS = tuple(COMPARE) + ("between", "text", "starts", "dup", "unique", "top", "bottom", "above", "below", "blank", "notblank", "error", "scale", "bar")
WORDS = {"gt": "Greater than", "ge": "At least", "lt": "Less than", "le": "At most", "eq": "Equal to", "ne": "Not equal to", "between": "Between",
         "text": "Text that contains", "starts": "Text that begins with", "dup": "Duplicate values", "unique": "Values that appear once",
         "top": "Top", "bottom": "Bottom", "above": "Above average", "below": "Below average", "blank": "Empty cells", "notblank": "Cells with something",
         "error": "Errors", "scale": "Colour scale", "bar": "Data bars"}


def clean_rule(raw) -> dict | None:
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        return None
    rng = raw.get("range")
    if not (isinstance(rng, list) and len(rng) == 4 and all(isinstance(x, int) and x >= 0 for x in rng)):
        return None
    r0, c0, r1, c1 = rng
    rule = {"id": str(raw.get("id") or "")[:20], "range": [min(r0, r1), min(c0, c1), max(r0, r1), max(c0, c1)], "kind": raw["kind"]}
    for k in ("a", "b"):
        if raw.get(k) not in (None, ""):
            rule[k] = str(raw[k])[:200]
    try:
        rule["n"] = max(1, min(1000, int(raw.get("n", 10))))
    except (TypeError, ValueError):
        rule["n"] = 10
    rule["style"] = raw.get("style") if raw.get("style") in STYLES else "red"
    for k in ("fill", "ink"):                          # a look of its own (from Excel), instead of one of ours
        v = str(raw.get(k) or "")
        if len(v) == 7 and v.startswith("#"):
            rule[k] = v.upper()
    if raw.get("bold"):
        rule["bold"] = True
    for k in ("low", "mid", "high", "color"):
        v = str(raw.get(k) or "")
        if len(v) == 7 and v.startswith("#"):
            rule[k] = v.upper()
    if rule["kind"] == "scale":
        rule.setdefault("low", "#F8696B")
        rule.setdefault("high", "#63BE7B")
    if rule["kind"] == "bar":
        rule.setdefault("color", "#638EC6")
    return rule


def look_of(rule: dict) -> dict:
    """The colours a matching rule gives: its own, or its style's."""
    if any(k in rule for k in ("fill", "ink", "bold")):
        out = {}
        if rule.get("fill"):
            out["fill"] = rule["fill"]
        if rule.get("ink"):
            out["color"] = rule["ink"]
        if rule.get("bold"):
            out["b"] = True
        return out
    return dict(STYLES[rule["style"]])


def describe(rule: dict) -> str:
    k = rule["kind"]
    words = WORDS.get(k, k)
    if k in COMPARE or k in ("text", "starts"):
        return f"{words} {rule.get('a', '')}"
    if k == "between":
        return f"Between {rule.get('a', '')} and {rule.get('b', '')}"
    if k in ("top", "bottom"):
        return f"{words} {rule.get('n', 10)}"
    return words


def _number(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _value(book, s: int, r: int, c: int):
    try:
        return se.scalar(book.value(s, r, c))
    except se.Err as err:
        return err


def _lit(text: str):
    return se.literal(text or "")[0]


def _cmp(op: str, a, b) -> bool:
    try:
        return se.compare(op, a, b)
    except (se.Err, TypeError):
        return False


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ca, cb))


class Rules:
    """The colours rules give cells, worked out with what each needs to know about its whole range (the
    average, the top ten, which values repeat), kept until the sheet changes."""

    def __init__(self, book):
        self.book = book
        self._stats = {}

    def forget(self) -> None:
        self._stats.clear()

    def _values(self, s: int, rule: dict) -> list:
        r0, c0, r1, c1 = rule["range"]
        used_r, used_c = self.book.used(s)
        out = []
        for r in range(r0, min(r1, used_r) + 1):
            for c in range(c0, min(c1, used_c) + 1):
                if self.book.raw(s, r, c) != "":
                    v = _value(self.book, s, r, c)
                    if not isinstance(v, se.Err):
                        out.append(v)
        return out

    def stats(self, s: int, rule: dict) -> dict:
        key = (s, rule["id"], tuple(rule["range"]), rule["kind"], rule.get("n"))
        hit = self._stats.get(key)
        if hit is None:
            values = self._values(s, rule)
            nums = sorted(n for n in (_number(v) for v in values) if n is not None)
            seen = {}
            for v in values:
                k = v.lower() if isinstance(v, str) else v
                seen[k] = seen.get(k, 0) + 1
            n = rule.get("n", 10)
            hit = {"nums": nums, "seen": seen, "mean": sum(nums) / len(nums) if nums else 0.0,
                   "top": nums[-n] if len(nums) >= n else (nums[0] if nums else 0.0),
                   "bottom": nums[n - 1] if len(nums) >= n else (nums[-1] if nums else 0.0)}
            self._stats[key] = hit
        return hit

    def look(self, s: int, rules: list, r: int, c: int) -> dict:
        """What the rules do to one cell: fill, color, b, and bar (0..1) with barColor."""
        out, styled = {}, False
        for rule in rules:
            r0, c0, r1, c1 = rule["range"]
            if not (r0 <= r <= r1 and c0 <= c <= c1):
                continue
            k = rule["kind"]
            raw = self.book.raw(s, r, c)
            v = _value(self.book, s, r, c) if raw != "" else None
            num = _number(v) if not isinstance(v, se.Err) else None
            if k in ("scale", "bar"):
                if num is None:
                    continue
                st = self.stats(s, rule)
                lo, hi = (st["nums"][0], st["nums"][-1]) if st["nums"] else (0.0, 0.0)
                if k == "scale" and not styled and "fill" not in out:
                    t = 0.5 if hi == lo else (num - lo) / (hi - lo)
                    mid = rule.get("mid")
                    out["fill"] = (_mix(rule["low"], mid, t * 2) if t < 0.5 else _mix(mid, rule["high"], (t - 0.5) * 2)) if mid else _mix(rule["low"], rule["high"], t)
                elif k == "bar" and "bar" not in out:
                    base = min(0.0, lo)
                    out["bar"] = 0.0 if hi == base else max(0.0, min(1.0, (num - base) / (hi - base)))
                    out["barColor"] = rule["color"]
                continue
            if styled:
                continue
            hit = False
            if k in COMPARE:
                want = _lit(rule.get("a", ""))
                kinds_differ = (_number(want) is None) != (num is None) and k not in ("eq", "ne")   # (text isn't "more than 10")
                hit = raw != "" and not kinds_differ and _cmp(COMPARE[k], v, want)
            elif k == "between":
                a, b = _lit(rule.get("a", "")), _lit(rule.get("b", ""))
                lo_, hi_ = (a, b) if _number(a) is None or _number(b) is None or a <= b else (b, a)
                hit = raw != "" and (num is not None) == (_number(lo_) is not None) and _cmp(">=", v, lo_) and _cmp("<=", v, hi_)
            elif k in ("text", "starts"):
                want = (rule.get("a") or "").lower()
                try:
                    have = se.text(v).lower() if raw != "" else ""
                except se.Err:
                    have = ""
                hit = bool(want) and (have.startswith(want) if k == "starts" else want in have)
            elif k in ("dup", "unique"):
                if raw != "":
                    n = self.stats(s, rule)["seen"].get(v.lower() if isinstance(v, str) else v, 0)
                    hit = n > 1 if k == "dup" else n == 1
            elif k in ("top", "bottom", "above", "below"):
                if num is not None:
                    st = self.stats(s, rule)
                    hit = {"top": num >= st["top"], "bottom": num <= st["bottom"], "above": num > st["mean"], "below": num < st["mean"]}[k]
            elif k == "blank":
                hit = raw == "" or (isinstance(v, str) and v == "")
            elif k == "notblank":
                hit = raw != ""
            elif k == "error":
                hit = raw != "" and isinstance(v, se.Err)
            if hit:
                styled = True
                for key, val in look_of(rule).items():
                    out[key] = val
        return out
