"""Comments and tracked changes for Writer.

Where they live in the text: in the characters' format, as its tool tip, which Qt keeps in its HTML as a title
attribute (so a document saved and opened again keeps them). The tool tip reads "hw" and then marks:

    ins.ID.U        an insertion (U: 1 if the text was underlined before the mark's underline went on)
    del.ID.FG.S     a deletion (FG: the text's own colour, or -; S: 1 if it was struck through before)
    note.ID.BG      a comment on this text (BG: the text's own highlight, or -)

What they say (who, when, the comment's words and replies) is kept beside the text, in the document's
"huginn-review" meta tag: {"next": n, "changes": {id: {by, when}}, "notes": {id: {by, when, text, replies, done}}}.
Word's own w:ins, w:del and comments come in and go out through huginn_docx.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextFormat

INS_LINE, DEL_INK, NOTE_BG = "#1A73E8", "#D93025", "#FFE7A3"
KINDS = ("ins", "del", "note")


def parse(tip: str) -> dict:
    """{"ins": [id, u], "del": [id, fg, s], "note": [id, bg]}, from a tool tip ({} when it isn't ours)."""
    if not tip or not tip.startswith("hw "):
        return {}
    out = {}
    for tok in tip[3:].split():
        parts = tok.split(".")
        if parts[0] in KINDS and len(parts) >= 2 and parts[1].isdigit():
            out[parts[0]] = parts[1:]
    return out


def unparse(marks: dict) -> str:
    return "hw " + " ".join(".".join([k] + list(marks[k])) for k in KINDS if k in marks) if marks else ""


def fragments(doc):
    """(start, length, format) for every run of text with one format, in order, tables included."""
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            f = it.fragment()
            if f.isValid():
                yield f.position(), f.length(), f.charFormat()
            it += 1
        block = block.next()


def _colour(brush) -> str:
    return brush.color().name()[1:] if brush.style() != Qt.NoBrush and brush.color().alpha() > 0 else "-"


def with_mark(cf: QTextCharFormat, kind: str, ident: int) -> QTextCharFormat:
    """The format with the mark on it, and its look (what it looked like before goes into the mark)."""
    marks = parse(cf.toolTip())
    out = QTextCharFormat(cf)
    if kind == "ins" and "ins" not in marks:
        marks["ins"] = [str(ident), "1" if cf.fontUnderline() else "0"]
        out.setFontUnderline(True)
        out.setUnderlineColor(QColor(INS_LINE))
    elif kind == "del" and "del" not in marks:
        marks["del"] = [str(ident), _colour(cf.foreground()), "1" if cf.fontStrikeOut() else "0"]
        out.setFontStrikeOut(True)
        out.setForeground(QColor(DEL_INK))
    elif kind == "note":
        bg = marks["note"][1] if "note" in marks and len(marks["note"]) > 1 else _colour(cf.background())
        marks["note"] = [str(ident), bg]
        out.setBackground(QColor(NOTE_BG))
    else:
        if kind in marks:
            marks[kind][0] = str(ident)
    out.setToolTip(unparse(marks))
    return out


def without_mark(cf: QTextCharFormat, kind: str) -> QTextCharFormat:
    """The format with that mark taken off, and the text looking as it did before it went on."""
    marks = parse(cf.toolTip())
    out = QTextCharFormat(cf)
    m = marks.pop(kind, None)
    if m is None:
        return out
    if kind == "ins":
        if (m[1:2] or ["0"])[0] != "1":
            out.setFontUnderline(False)
        out.clearProperty(QTextFormat.TextUnderlineColor)
    elif kind == "del":
        fg = (m[1:2] or ["-"])[0]
        if fg == "-":
            out.clearForeground()
        else:
            out.setForeground(QColor("#" + fg))
        out.setFontStrikeOut((m[2:3] or ["0"])[0] == "1")
    elif kind == "note":
        bg = (m[1:2] or ["-"])[0]
        if bg == "-":
            out.clearBackground()
        else:
            out.setBackground(QColor("#" + bg))
    if marks:
        out.setToolTip(unparse(marks))
    else:
        out.clearProperty(QTextFormat.TextToolTip)
    return out


def restyle(doc, start: int, end: int, change) -> None:
    """Run change(format) -> format over every run of text between start and end (the caller holds an edit block)."""
    pieces = [(max(p, start), min(p + n, end), cf) for p, n, cf in fragments(doc) if p < end and p + n > start]
    cur = QTextCursor(doc)
    for a, b, cf in pieces:
        new = change(cf)
        if new != cf:
            cur.setPosition(a)
            cur.setPosition(b, QTextCursor.KeepAnchor)
            cur.setCharFormat(new)


def spans(doc, kind: str) -> dict:
    """id -> [start, end] of each mark of a kind (from its first character to its last)."""
    out = {}
    for p, n, cf in fragments(doc):
        m = parse(cf.toolTip()).get(kind)
        if m:
            ident = int(m[0])
            if ident in out:
                out[ident][1] = p + n
            else:
                out[ident] = [p, p + n]
    return out


def text_sum(text: str) -> str:
    import zlib
    return f"{len(text)}:{zlib.crc32(text.encode('utf-8')):08x}"


def put_marks(doc, marks) -> None:
    """Put the marks back where they were saved ([start, end, tool tip]), where the text doesn't carry them already."""
    last = doc.characterCount() - 1
    cur = QTextCursor(doc)
    for m in marks:
        if not (isinstance(m, list) and len(m) == 3 and isinstance(m[0], int) and isinstance(m[1], int) and str(m[2]).startswith("hw ")):
            continue
        a, b = max(0, m[0]), min(last, m[1])
        if b <= a:
            continue
        fmt = QTextCharFormat()
        fmt.setToolTip(str(m[2])[:200])
        cur.setPosition(a)
        cur.setPosition(b, QTextCursor.KeepAnchor)
        cur.mergeCharFormat(fmt)


def now() -> int:
    return int(time.time())


def clean_review(raw) -> dict:
    r = {"next": 1, "track": False, "changes": {}, "notes": {}}
    if not isinstance(raw, dict):
        return r
    r["track"] = bool(raw.get("track"))
    try:
        r["next"] = max(1, int(raw.get("next", 1)))
    except (TypeError, ValueError):
        pass
    for k in ("changes", "notes"):
        got = raw.get(k)
        if isinstance(got, dict):
            for ident, v in got.items():
                if str(ident).isdigit() and isinstance(v, dict):
                    item = {"by": str(v.get("by") or "")[:80], "when": int(v.get("when") or 0) if str(v.get("when") or "0").lstrip("-").isdigit() else 0}
                    if k == "notes":
                        item["text"] = str(v.get("text") or "")[:4000]
                        item["done"] = bool(v.get("done"))
                        item["replies"] = [{"by": str(x.get("by") or "")[:80], "when": int(x.get("when") or 0) if str(x.get("when") or "0").isdigit() else 0,
                                            "text": str(x.get("text") or "")[:4000]} for x in (v.get("replies") or []) if isinstance(x, dict)][:200]
                    r[k][str(int(ident))] = item
                    r["next"] = max(r["next"], int(ident) + 1)
    return r
