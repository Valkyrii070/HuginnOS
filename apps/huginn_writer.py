"""Huginn Writer: a word processor that works on pages.

The live text is the QML editor's own QTextDocument. Writer lays it out in pages (Qt's text layout breaks blocks
over pages when the document has a page height): each page is the paper plus a gap, and the root frame's margins
are the page's margins, with the gap added to the bottom one, so the editor shows real pages with real page breaks
and the window draws a sheet of paper behind each. Headers, footers and page numbers are drawn on the sheets, and
into the PDF and Word files.

Writer's own files are HTML (pictures inside as data URIs), with the page setup in a <meta> of its own. Word
files are read and written by huginn_docx; older formats go through LibreOffice first (huginn_office.Bridge).
"""
import base64
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import (Property, QBuffer, QByteArray, QDateTime, QIODevice, QLocale, QMarginsF, QObject, QRectF, QSizeF, Qt, QTimer,
                            QUrl, Signal, Slot)
from PySide6.QtGui import (QAbstractTextDocumentLayout, QBrush, QColor, QFont, QFontDatabase, QImage, QPageLayout, QPageSize,
                           QPainter, QPdfWriter, QSyntaxHighlighter, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument,
                           QTextDocumentWriter, QTextFormat, QTextFrameFormat, QTextImageFormat, QTextLength, QTextListFormat,
                           QTextOption, QTextTableFormat)

import huginn_docx as docx
import huginn_review as rv
from huginn_office import FileList, fresh_path, note_recent, write_atomic

PX_PER_MM = 96 / 25.4
GAP = 28                       # between two sheets of paper on screen (part of each page's bottom margin)
PAPERS = {"letter": ("Letter", 215.9, 279.4), "a4": ("A4", 210.0, 297.0), "legal": ("Legal", 215.9, 355.6), "a5": ("A5", 148.0, 210.0)}
QPAGE = {"letter": QPageSize.Letter, "a4": QPageSize.A4, "legal": QPageSize.Legal, "a5": QPageSize.A5}
META = re.compile(r'<meta name="huginn-writer" content="([^"]*)"\s*/?>')
BASE_PT = 11
STYLES = {        # paragraph styles: size (pt), weight, heading level, space before / after (px)
    "title": (26, QFont.Bold, 1, 6, 10), "heading": (18, QFont.DemiBold, 2, 18, 6), "subheading": (14, QFont.DemiBold, 3, 14, 4),
    "minor": (12, QFont.DemiBold, 4, 12, 4), "body": (BASE_PT, QFont.Normal, 0, 0, 8)}
QUOTE_MARGIN, CODE_BG = 36, "#F1F3F5"
BULLETS = (QTextListFormat.ListDisc, QTextListFormat.ListCircle, QTextListFormat.ListSquare)
NUMBERS = (QTextListFormat.ListDecimal, QTextListFormat.ListLowerAlpha, QTextListFormat.ListLowerRoman)
WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
FAVOURITE_FONTS = ("Inter", "Noto Sans", "Noto Serif", "Carlito", "Caladea", "Liberation Sans", "Liberation Serif", "Liberation Mono",
                   "DejaVu Sans", "DejaVu Serif", "Ubuntu", "JetBrains Mono")


REVIEW_META = re.compile(r'<meta name="huginn-review" content="([^"]*)"\s*/?>')


def me() -> str:
    """The name changes and comments are signed with: the account's full name, else its user name."""
    try:
        import pwd
        entry = pwd.getpwuid(os.getuid())
        return (entry.pw_gecos or "").split(",")[0].strip() or entry.pw_name
    except (ImportError, KeyError):
        return os.environ.get("USER", "") or "Me"


def ago(when: int) -> str:
    if not when:
        return ""
    import time as _t
    d = _t.time() - when
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    return QDateTime.fromSecsSinceEpoch(int(when)).toString("d MMM yyyy")


def default_setup() -> dict:
    us = QLocale.system().territory() in (QLocale.UnitedStates, QLocale.Canada, QLocale.Mexico, QLocale.Philippines, QLocale.Chile, QLocale.Colombia)
    return {"paper": "letter" if us else "a4", "landscape": False, "margins": [25.4, 25.4, 25.4, 25.4],   # top, right, bottom, left (mm)
            "header": "", "footer": "", "numbers": "none", "firstPage": True}


def clean_setup(raw) -> dict:
    s = default_setup()
    if isinstance(raw, dict):
        if raw.get("paper") in PAPERS:
            s["paper"] = raw["paper"]
        s["landscape"] = bool(raw.get("landscape", False))
        m = raw.get("margins")
        if isinstance(m, list) and len(m) == 4:
            s["margins"] = [max(5.0, min(80.0, float(x))) for x in m]
        for k in ("header", "footer"):
            s[k] = str(raw.get(k) or "")[:300]
        if raw.get("numbers") in ("none", "bottom-center", "bottom-right", "top-right"):
            s["numbers"] = raw["numbers"]
        s["firstPage"] = bool(raw.get("firstPage", True))
    return s


def paper_px(setup: dict) -> tuple:
    _, w, h = PAPERS[setup["paper"]]
    if setup["landscape"]:
        w, h = h, w
    return w * PX_PER_MM, h * PX_PER_MM


def field_text(text: str, page: int, pages: int, title: str) -> str:
    """A header or footer with its fields filled in: {page}, {pages}, {title}, {date}."""
    return (text.replace("{page}", str(page)).replace("{pages}", str(pages)).replace("{title}", title)
            .replace("{date}", QLocale.system().toString(dt.date.today(), QLocale.ShortFormat)))


def image_data_uri(path: str, max_side: int = 2400) -> tuple:
    """(data URI, width, height) of a picture file; very large pictures are scaled down, others kept as they are."""
    raw = Path(path).read_bytes()
    img = QImage()
    if not img.loadFromData(raw):
        raise OSError("that isn't a picture Writer can read")
    kind = "jpeg" if raw[:3] == b"\xff\xd8\xff" else "png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else ""
    if not kind or max(img.width(), img.height()) > max_side:
        if max(img.width(), img.height()) > max_side:
            img = img.scaled(max_side, max_side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        kind = "jpeg" if not img.hasAlphaChannel() else "png"
        img.save(buf, kind.upper(), 88 if kind == "jpeg" else -1)
        raw = bytes(ba)
    return f"data:image/{kind};base64," + base64.b64encode(raw).decode(), img.width(), img.height()


# ---------------------------------------------------------------------------------------------- spelling
class Speller:
    """Spelling through enchant (hunspell's dictionaries), with the person's own words kept in
    ~/.config/huginn/words.txt. Without enchant there is simply no spelling."""

    def __init__(self):
        self._dict, self._lang, self._cache = None, "", {}
        self.langs = []
        try:
            import enchant
            self._enchant = enchant
            self.langs = sorted(set(enchant.list_languages()))
        except Exception:                                   # noqa: BLE001  (no enchant, or a broken one: no spelling)
            self._enchant = None
        self.words_file = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "huginn" / "words.txt"

    @property
    def available(self) -> bool:
        return bool(self._enchant and self.langs)

    def use(self, lang: str = "") -> str:
        if not self.available:
            return ""
        want = lang or QLocale.system().name()
        pick = want if want in self.langs else next((l for l in self.langs if l.split("_")[0] == want.split("_")[0]), "")
        pick = pick or ("en_US" if "en_US" in self.langs else self.langs[0])
        if pick != self._lang:
            self.words_file.parent.mkdir(parents=True, exist_ok=True)
            self.words_file.touch(exist_ok=True)
            try:
                self._dict = self._enchant.DictWithPWL(pick, str(self.words_file))
            except Exception:                               # noqa: BLE001
                self._dict = self._enchant.Dict(pick)
            self._lang, self._cache = pick, {}
        return pick

    lang = property(lambda self: self._lang)

    OWN_WORDS = frozenset({"Huginn", "Muninn", "Ubuntu", "Linux", "Flathub", "Wayland", "PipeWire", "GNOME", "KDE", "OpenDocument"})

    def ok(self, word: str) -> bool:
        if self._dict is None or len(word) < 2 or word.isupper() or word in self.OWN_WORDS:
            return True
        hit = self._cache.get(word)
        if hit is None:
            try:
                hit = self._dict.check(word) or self._dict.check(word.replace("’", "'"))
            except Exception:                               # noqa: BLE001
                hit = True
            self._cache[word] = hit
        return hit

    def suggest(self, word: str) -> list:
        try:
            return self._dict.suggest(word)[:6] if self._dict else []
        except Exception:                                   # noqa: BLE001
            return []

    def add(self, word: str) -> None:
        if self._dict is not None:
            try:
                self._dict.add(word)
            except Exception:                               # noqa: BLE001
                with open(self.words_file, "a", encoding="utf-8") as f:
                    f.write(word + "\n")
            self._cache[word] = True


class Marks(QSyntaxHighlighter):
    """What's drawn over the text without being part of it: what Find found. (Words spelled wrong get their red
    waves from the window: Qt Quick's text draws only plain underlines, so it can't show them itself.)"""

    def __init__(self, doc, speller: Speller):
        super().__init__(doc)
        self.speller, self.find = speller, None
        self.ignored = set()
        self._found = QTextCharFormat()
        self._found.setBackground(QColor("#FFE58F"))

    def highlightBlock(self, text: str) -> None:
        if self.find is not None:
            for m in self.find.finditer(text):
                if m.end() > m.start():
                    self.setFormat(m.start(), m.end() - m.start(), self._found)



# ---------------------------------------------------------------------------------------------- Writer
class Writer(FileList):
    """Word processor. The live text is the QML editor's document; formatting is applied to it from here."""
    NATIVE, OWN, VIA_BRIDGE, MODERN, STEM = (".html", ".htm", ".md", ".txt"), (".docx",), (".odt", ".rtf", ".doc"), "docx", "Untitled"
    loaded = Signal()
    pageChanged = Signal()
    wordsChanged = Signal()
    reviewChanged = Signal()
    BASE_CSS = "body { font-family: 'Inter', sans-serif; font-size: 11pt; color: #15181C; }"

    def __init__(self, target: Path = None):
        super().__init__(target)
        self._doc, self._quick, self._pending, self._words, self._chars = None, None, None, 0, 0
        self._setup = default_setup()
        self._speller = Speller()
        self._marks = None
        self._spell_on = True
        self._pages = 1
        self._fixing = False
        self._review, self._own, self._fix, self._mine, self._plain = rv.clean_review(None), False, [], set(), ""
        self._me = me()
        self._review_tick = QTimer(self)
        self._review_tick.setSingleShot(True)
        self._review_tick.setInterval(250)
        self._review_tick.timeout.connect(self.reviewChanged)
        self.changed.connect(self.wordsChanged)
        if self._extra:
            self.open(str(self._extra))

    words = Property(int, lambda self: self._words, notify=wordsChanged)
    characters = Property(int, lambda self: self._chars, notify=wordsChanged)

    # ------------------------------------------------------------------ the document from the editor
    @Slot(QObject)
    def attach(self, quick_doc) -> None:
        self._quick = quick_doc                    # keep the editor's wrapper alive: the document belongs to it
        self._doc = quick_doc.textDocument()
        self._doc.setDefaultStyleSheet(self.BASE_CSS)
        font = QFont("Inter")
        font.setPointSizeF(BASE_PT)
        self._doc.setDefaultFont(font)
        self._doc.setDocumentMargin(0)
        self._doc.documentLayout().documentSizeChanged.connect(self._sized)
        self._marks = Marks(self._doc, self._speller)
        if self._speller.available:
            self._speller.use("")
        if self._pending is not None:
            self._fill(*self._pending)
            self._pending = None
        self._apply_page()
        self._doc.contentsChanged.connect(self._edited)
        self._plain = self._doc.toRawText()
        self._doc.contentsChange.connect(self._typed)

    def _apply_page(self) -> None:
        """The page size and margins on the live document (the gap between sheets goes into the bottom margin)."""
        if self._doc is None:
            return
        w, h = paper_px(self._setup)
        top, right, bottom, left = (m * PX_PER_MM for m in self._setup["margins"])
        self._fixing = True
        ff = self._doc.rootFrame().frameFormat()
        ff.setTopMargin(top)
        ff.setBottomMargin(bottom + GAP)
        ff.setLeftMargin(left)
        ff.setRightMargin(right)
        ff.setPadding(0)
        ff.setBorder(0)
        self._doc.rootFrame().setFrameFormat(ff)
        self._doc.setPageSize(QSizeF(w, h + GAP))
        self._fixing = False
        self._sized()
        self.pageChanged.emit()

    def _sized(self, *_):
        if self._doc is None:
            return
        # the editor sets the page size to (width, no height) when it re-measures: put the pages back
        if not self._fixing and self._doc.pageSize().height() <= 0:
            QTimer.singleShot(0, self._apply_page)
            return
        n = max(1, self._doc.pageCount())
        if n != self._pages:
            self._pages = n
            self.pageChanged.emit()

    @Property("QVariantMap", notify=pageChanged)
    def paper(self):
        w, h = paper_px(self._setup)
        top, right, bottom, left = (m * PX_PER_MM for m in self._setup["margins"])
        return {"w": w, "h": h, "stride": h + GAP, "top": top, "right": right, "bottom": bottom, "left": left, **self._setup,
                "pages": self._pages, "sizeName": PAPERS[self._setup["paper"]][0]}

    pages = Property(int, lambda self: self._pages, notify=pageChanged)

    @Slot(int, result=str)
    def headerFor(self, page: int) -> str:
        return self._band("header", page)

    @Slot(int, result=str)
    def footerFor(self, page: int) -> str:
        return self._band("footer", page)

    def _band(self, which: str, page: int, pages: int = 0) -> str:
        """The header or footer of a page, its fields filled in ("" on the first page when it has none)."""
        if page == 1 and not self._setup["firstPage"]:
            return ""
        return field_text(self._setup[which], page, pages or self._pages, self.title)

    @Slot(int, result=str)
    def numberFor(self, page: int) -> str:
        if self._setup["numbers"] == "none" or (page == 1 and not self._setup["firstPage"]):
            return ""
        return str(page)

    @Slot(str, "QVariant")
    def setPage(self, key: str, value) -> None:
        """Page setup: paper, landscape, margins ([t, r, b, l] mm or a preset name), header, footer, numbers, firstPage."""
        value = value.toVariant() if hasattr(value, "toVariant") else value
        s = dict(self._setup)
        if key == "margins" and isinstance(value, str):
            value = {"normal": [25.4] * 4, "narrow": [12.7] * 4, "wide": [25.4, 50.8, 25.4, 50.8], "moderate": [25.4, 19.05, 25.4, 19.05]}.get(value, s["margins"])
        s[key] = value
        s = clean_setup(s)
        if s != self._setup:
            self._setup = s
            self._apply_page()
            self.touch()

    # ------------------------------------------------------------------ editing and counting
    def _edited(self) -> None:
        text = self._doc.toPlainText()
        self._words, self._chars = len(text.split()), len(text.replace("\n", "").replace(" ", ""))
        if self._path is not None and not self._loading:
            self.touch()
        else:
            self.changed.emit()

    _loading = False

    def _fill(self, kind: str, text: str) -> None:
        self._loading = True
        setup = None
        if kind == "html":
            m = META.search(text)
            if m:
                try:
                    setup = json.loads(html.unescape(m.group(1)))
                except ValueError:
                    setup = None
        self._setup = clean_setup(setup) if setup else (clean_setup(self._incoming_setup) if self._incoming_setup else default_setup())
        self._incoming_setup = None
        review = None
        if kind == "html":
            m = REVIEW_META.search(text)
            if m:
                try:
                    review = json.loads(html.unescape(m.group(1)))
                except ValueError:
                    review = None
        marks, mark_sum = (review.pop("marks", None), review.pop("sum", None)) if isinstance(review, dict) else (None, None)
        self._review, self._mine = rv.clean_review(review), set()
        if kind == "md":
            self._doc.setMarkdown(text)
        elif kind == "txt":
            self._doc.setPlainText(text)
        else:
            self._doc.setHtml(text)
            if marks and mark_sum == rv.text_sum(self._doc.toPlainText()):
                rv.put_marks(self._doc, marks)
        self._doc.setModified(False)
        self._doc.clearUndoRedoStacks()
        self._loading = False
        plain = self._doc.toPlainText()
        self._words, self._chars = len(plain.split()), len(plain.replace("\n", "").replace(" ", ""))
        self._apply_page()
        self.loaded.emit()
        self.changed.emit()
        self.reviewChanged.emit()

    _incoming_setup = None

    @Slot(str)
    def open(self, path: str) -> None:
        note_recent(path)
        if self._dirty:
            self.save()
        source = Path(path)
        try:
            kind = source.suffix.lower()
            dropped = None
            if kind in self.FOREIGN:
                text, setup, dropped = docx.docx_to_html(self._modern(source))
                self._incoming_setup = setup
                kind, target = "html", fresh_path(source.parent, source.stem, ".html")    # edits go to a copy; the original is untouched
            else:
                text, target = source.read_text(encoding="utf-8", errors="replace"), source
                kind = "md" if kind == ".md" else "txt" if kind == ".txt" else "html"
        except (OSError, docx.ConvertError) as err:
            self.failed.emit(f"Couldn't open “{source.name}”: {getattr(err, 'strerror', None) or err}")
            return
        self._path, self._dirty = target, False
        if self._doc is None:
            self._pending = (kind, text)
        else:
            self._fill(kind, text)
        if target != source:
            self.touch()
            self.imported.emit(source.name, dropped or [])
        self.changed.emit()

    @Slot()
    def create(self) -> None:
        if self._dirty:
            self.save()
        try:
            path = fresh_path(self._folder, self.STEM, ".html")
            path.write_text("", encoding="utf-8")
        except OSError as err:
            self.failed.emit(f"Couldn't create a document: {err.strerror or err}")
            return
        self.open(str(path))

    def html_text(self) -> str:
        """The document as Writer keeps it: HTML with the page setup inside."""
        out = self._doc.toHtml()
        meta = f'<meta name="huginn-writer" content="{html.escape(json.dumps(self._setup), quote=True)}" />'
        if self._review.get("changes") or self._review.get("notes") or self._review.get("track"):
            self._tidy_review()
            # where the marks are, as well as in the text's title attributes: Qt before 6.11 reads those but
            # doesn't write them (checked against the text, so a file changed elsewhere isn't marked wrongly)
            marks = []
            for p, n, cf in rv.fragments(self._doc):
                tip = cf.toolTip()
                if tip.startswith("hw "):
                    if marks and marks[-1][1] == p and marks[-1][2] == tip:
                        marks[-1][1] = p + n
                    else:
                        marks.append([p, p + n, tip])
            out_review = dict(self._review, marks=marks, sum=rv.text_sum(self._doc.toPlainText()))
            meta += f'<meta name="huginn-review" content="{html.escape(json.dumps(out_review), quote=True)}" />'
        return out.replace("<head>", "<head>" + meta, 1) if "<head>" in out else meta + out

    @Slot()
    def save(self) -> None:
        if not self._dirty or self._path is None or self._doc is None:
            return
        try:
            kind = self._path.suffix.lower()
            text = self._doc.toMarkdown() if kind == ".md" else self._doc.toPlainText() if kind == ".txt" else self.html_text()
            write_atomic(self._path, text)
            self._dirty = False
        except OSError as err:
            self.failed.emit(f"Couldn't save: {err.strerror or err}")
        self.changed.emit()

    # ------------------------------------------------------------------ comments and tracked changes
    tracking = Property(bool, lambda self: bool(self._review.get("track")), notify=reviewChanged)
    author = Property(str, lambda self: self._me, constant=True)

    @Slot(bool)
    def setTracking(self, on: bool) -> None:
        if bool(self._review.get("track")) != bool(on):
            self._review["track"] = bool(on)
            self._mine = set()
            self.touch()
            self.reviewChanged.emit()

    def _new_id(self) -> int:
        n = self._review["next"]
        self._review["next"] = n + 1
        return n

    def _typed(self, position: int, removed: int, added: int) -> None:
        """Something typed or pasted: once it's in, it takes no comment or deletion from the text beside it, and while
        changes are tracked it's marked as inserted (signed by whoever is at the keyboard)."""
        if self._doc is None:
            return
        text, before = self._doc.toRawText(), self._plain
        self._plain = text
        if self._own or self._loading or self._fixing:
            return
        if added > 0 and not (removed == added and before[position:position + removed] == text[position:position + added]):  # (not just its look)
            self._fix.append((position, position + added))
            QTimer.singleShot(0, self._fix_typed)
        self._review_tick.start()

    def _fix_typed(self) -> None:
        todo, self._fix = self._fix, []
        if self._doc is None or not todo:
            return
        tracking = bool(self._review.get("track"))
        last = self._doc.characterCount() - 1
        for a, b in todo:
            a, b = max(0, min(a, last)), max(0, min(b, last))
            if b <= a:
                continue
            marked = any(rv.parse(cf.toolTip()) for p, n, cf in rv.fragments(self._doc) if p < b and p + n > a)
            if not marked and not tracking:
                continue
            ident = 0
            if tracking:
                before = self._marks_at(a - 1).get("ins") if a > 0 else None
                ident = int(before[0]) if before and int(before[0]) in self._mine else self._new_id()
                if ident not in self._mine:
                    self._mine.add(ident)
                    self._review["changes"][str(ident)] = {"by": self._me, "when": rv.now()}

            def fix(cf, ident=ident):
                cf = rv.without_mark(rv.without_mark(cf, "note"), "del")
                if tracking:
                    m = rv.parse(cf.toolTip()).get("ins")
                    if m and m[0] != str(ident):
                        cf = rv.without_mark(cf, "ins")
                    return rv.with_mark(cf, "ins", ident)
                return rv.without_mark(cf, "ins")
            self._restyle(a, b, fix, join=True)
        self._review_tick.start()

    def _marks_at(self, position: int) -> dict:
        if self._doc is None or position < 0:
            return {}
        for p, n, cf in rv.fragments(self._doc):
            if p <= position < p + n:
                return rv.parse(cf.toolTip())
        return {}

    def _restyle(self, a: int, b: int, change, join: bool = False) -> None:
        cur = QTextCursor(self._doc)
        self._own = True
        if join:
            cur.joinPreviousEditBlock()
        else:
            cur.beginEditBlock()
        try:
            rv.restyle(self._doc, a, b, change)
        finally:
            cur.endEditBlock()
            self._own = False

    def _remove(self, ranges) -> None:
        """Take these stretches of text out, last first (the caller holds an edit block)."""
        cur = QTextCursor(self._doc)
        for a, b in sorted(ranges, reverse=True):
            cur.setPosition(a)
            cur.setPosition(b, QTextCursor.KeepAnchor)
            cur.removeSelectedText()

    @Slot(int, int, bool, result=int)
    def trackDelete(self, start: int, end: int, back: bool) -> int:
        """Delete (Backspace when back, Delete when not) while changes are tracked: the text stays, struck through,
        except what was itself inserted and not yet accepted, which goes. Returns where the cursor goes; -1 when
        changes aren't tracked (the editor deletes as usual)."""
        if self._doc is None or not self._review.get("track"):
            return -1
        last = self._doc.characterCount() - 1
        if start == end:
            if back:
                if start <= 0:
                    return 0
                start -= 1
            else:
                if end >= last:
                    return end
                end += 1
        text = self._doc.toPlainText()[start:end] if end <= last else ""
        if text and all(ch in "\u2029\n" for ch in text):              # a paragraph's end: step over it, it stays
            return start if back else end
        pieces = [(max(p, start), min(p + n, end), cf) for p, n, cf in rv.fragments(self._doc) if p < end and p + n > start]
        gone = [(a, b) for a, b, cf in pieces if "ins" in rv.parse(cf.toolTip())]
        before = self._marks_at(start - 1).get("del") if start > 0 else None
        after = self._marks_at(end).get("del")
        reuse = [int(m[0]) for m in (before, after) if m and int(m[0]) in self._mine]
        ident = reuse[0] if reuse else self._new_id()
        if ident not in self._mine:
            self._mine.add(ident)
            self._review["changes"][str(ident)] = {"by": self._me, "when": rv.now()}
        cur = QTextCursor(self._doc)
        self._own = True
        cur.beginEditBlock()
        try:
            rv.restyle(self._doc, start, end, lambda cf: cf if "ins" in rv.parse(cf.toolTip()) or "del" in rv.parse(cf.toolTip()) else rv.with_mark(cf, "del", ident))
            self._remove(gone)
        finally:
            cur.endEditBlock()
            self._own = False
        removed = sum(b - a for a, b in gone)
        self._review_tick.start()
        return start if back else end - removed

    def _tidy_review(self) -> None:
        """Forget changes and comments whose text is gone (a comment stays while it has words of its own)."""
        if self._doc is None:
            return
        have = {str(i) for k in ("ins", "del") for i in rv.spans(self._doc, k)}
        self._review["changes"] = {i: v for i, v in self._review["changes"].items() if i in have}

    @Property("QVariantList", notify=reviewChanged)
    def changes(self):
        if self._doc is None:
            return []
        text = self._doc.toPlainText()
        out = []
        for kind in ("ins", "del"):
            for ident, (a, b) in rv.spans(self._doc, kind).items():
                info = self._review["changes"].get(str(ident), {})
                words = text[a:b].replace("\u2029", " ").replace("\n", " ").strip()
                out.append({"id": ident, "kind": kind, "start": a, "end": b, "by": info.get("by") or "Someone", "when": ago(info.get("when", 0)),
                            "text": words[:80] + ("…" if len(words) > 80 else "")})
        return sorted(out, key=lambda c: c["start"])

    @Slot(int, bool, result=int)
    def settle(self, ident: int, accept: bool) -> int:
        """Accept or reject one change. Returns where it was (-1 when it's gone already)."""
        if self._doc is None:
            return -1
        mine = str(ident)
        found = [(p, p + n, k) for p, n, cf in rv.fragments(self._doc) for k, m in rv.parse(cf.toolTip()).items() if k in ("ins", "del") and m[0] == mine]
        if not found:
            return -1
        kind = found[0][2]
        cur = QTextCursor(self._doc)
        self._own = True
        cur.beginEditBlock()
        try:
            if (kind == "ins") == accept:             # the text stays: only the mark goes
                rv.restyle(self._doc, found[0][0], found[-1][1], lambda cf: rv.without_mark(cf, kind) if (rv.parse(cf.toolTip()).get(kind) or [""])[0] == mine else cf)
            else:
                self._remove([(a, b) for a, b, _ in found])
        finally:
            cur.endEditBlock()
            self._own = False
        self._review["changes"].pop(mine, None)
        self.touch()
        self.reviewChanged.emit()
        return found[0][0]

    @Slot(bool, result=int)
    def settleAll(self, accept: bool) -> int:
        if self._doc is None:
            return 0
        ids = [c["id"] for c in self.changes]
        cur = QTextCursor(self._doc)
        cur.beginEditBlock()
        try:
            for ident in ids:
                self.settle(ident, accept)
        finally:
            cur.endEditBlock()
        return len(ids)

    @Slot(int, bool, result="QVariantList")
    def nextChange(self, position: int, back: bool) -> list:
        """[start, end] of the change after (or before) a place, going round; [] when there are none."""
        found = self.changes
        if not found:
            return []
        if back:
            earlier = [c for c in found if c["start"] < position]
            c = earlier[-1] if earlier else found[-1]
        else:
            later = [c for c in found if c["start"] > position]
            c = later[0] if later else found[0]
        return [c["start"], c["end"], c["id"]]

    # comments
    @Property("QVariantList", notify=reviewChanged)
    def notes(self):
        if self._doc is None:
            return []
        text = self._doc.toPlainText()
        where = rv.spans(self._doc, "note")
        out = []
        for ident, v in self._review["notes"].items():
            a, b = where.get(int(ident), (-1, -1))
            quote = text[a:b].replace("\u2029", " ").replace("\n", " ").strip() if a >= 0 else ""
            out.append({"id": int(ident), "start": a, "end": b, "quote": quote[:120] + ("…" if len(quote) > 120 else ""), "gone": a < 0,
                        "by": v.get("by") or "Someone", "when": ago(v.get("when", 0)), "text": v.get("text", ""), "done": bool(v.get("done")),
                        "replies": [{"by": r.get("by") or "Someone", "when": ago(r.get("when", 0)), "text": r.get("text", "")} for r in v.get("replies", [])]})
        return sorted(out, key=lambda n: (n["gone"], n["start"], n["id"]))

    @Slot(int, int, str, result=int)
    def addNote(self, start: int, end: int, text: str) -> int:
        """A comment on the text between start and end. Returns its number (0 when there's nothing to comment on)."""
        if self._doc is None or not text.strip():
            return 0
        start, end = min(start, end), max(start, end)
        if start == end:
            w = self.wordAt(start)
            start, end = (w.get("start", start), w.get("end", end)) if w else (start, end)
        if start == end:
            return 0
        ident = self._new_id()
        self._review["notes"][str(ident)] = {"by": self._me, "when": rv.now(), "text": text.strip()[:4000], "done": False, "replies": []}
        self._restyle(start, end, lambda cf: rv.with_mark(cf, "note", ident))
        self.touch()
        self.reviewChanged.emit()
        return ident

    @Slot(int, str)
    def replyNote(self, ident: int, text: str) -> None:
        note = self._review["notes"].get(str(ident))
        if note is not None and text.strip():
            note["replies"].append({"by": self._me, "when": rv.now(), "text": text.strip()[:4000]})
            note["done"] = False
            self.touch()
            self.reviewChanged.emit()

    @Slot(int, str)
    def editNote(self, ident: int, text: str) -> None:
        note = self._review["notes"].get(str(ident))
        if note is not None and text.strip() and note["text"] != text.strip():
            note["text"] = text.strip()[:4000]
            self.touch()
            self.reviewChanged.emit()

    @Slot(int, bool)
    def resolveNote(self, ident: int, done: bool) -> None:
        note = self._review["notes"].get(str(ident))
        if note is not None:
            note["done"] = bool(done)
            self.touch()
            self.reviewChanged.emit()

    @Slot(int)
    def deleteNote(self, ident: int) -> None:
        if self._review["notes"].pop(str(ident), None) is None or self._doc is None:
            return
        mine = str(ident)
        self._restyle(0, self._doc.characterCount() - 1, lambda cf: rv.without_mark(cf, "note") if (rv.parse(cf.toolTip()).get("note") or [""])[0] == mine else cf)
        self.touch()
        self.reviewChanged.emit()

    @Slot(int, result=int)
    def noteAt(self, position: int) -> int:
        m = self._marks_at(position).get("note") or (self._marks_at(position - 1).get("note") if position > 0 else None)
        return int(m[0]) if m else 0

    # ------------------------------------------------------------------ cursors
    def _cursor(self, start: int, end: int) -> QTextCursor:
        cursor = QTextCursor(self._doc)
        last = self._doc.characterCount() - 1
        cursor.setPosition(max(0, min(start, last)))
        cursor.setPosition(max(0, min(end, last)), QTextCursor.KeepAnchor)
        return cursor

    @Slot(int, int, result=str)
    def textOf(self, start: int, end: int) -> str:
        if self._doc is None:
            return ""
        if start == end:
            return self._doc.toPlainText()
        return self._cursor(start, end).selectedText().replace(" ", "\n").replace(" ", "\n").replace("￼", "")

    @Slot(int, int, result=int)
    def wordsIn(self, start: int, end: int) -> int:
        return len(self.textOf(start, end).split()) if self._doc is not None and start != end else 0

    @Slot(int, int, str, result=int)
    def putText(self, start: int, end: int, text: str) -> int:
        """Replace a stretch (start == end: insert there) with text, keeping the formatting where it goes; one undo.
        Returns where the new text ends."""
        if self._doc is None:
            return start
        cursor = self._cursor(start, end)
        cursor.beginEditBlock()
        cursor.insertText(text)
        cursor.endEditBlock()
        return cursor.position()

    # ------------------------------------------------------------------ character and paragraph formatting
    @Slot(int, int, str)
    def style(self, start: int, end: int, what: str) -> None:
        """One formatting change on a stretch (or the word / paragraph at the cursor):
        bold, italic, underline, strike, super, sub, clear, bigger, smaller, size:N, font:Family, #RRGGBB (colour),
        mark:#RRGGBB or mark:none (highlight), left/center/right/justify, title/heading/subheading/minor/body/quote/code,
        bullet/number/check, indent/outdent, spacing:N (line height %), page-break."""
        if self._doc is None:
            return
        cursor = self._cursor(start, end)
        cursor.beginEditBlock()
        try:
            self._style(cursor, what)
        finally:
            cursor.endEditBlock()

    def _chars_of(self, cursor: QTextCursor, fmt: QTextCharFormat) -> None:
        if not cursor.hasSelection():
            word = QTextCursor(cursor)
            word.select(QTextCursor.WordUnderCursor)
            if word.hasSelection() and word.selectionStart() < cursor.position() < word.selectionEnd():
                word.mergeCharFormat(fmt)
                return
            cursor.mergeCharFormat(fmt)                     # (typing on from here gets it)
            return
        cursor.mergeCharFormat(fmt)

    def _blocks(self, cursor: QTextCursor):
        """Each paragraph the cursor's selection touches."""
        b = self._doc.findBlock(cursor.selectionStart())
        last = self._doc.findBlock(cursor.selectionEnd())
        while b.isValid():
            yield b
            if b == last:
                break
            b = b.next()

    def _style(self, cursor: QTextCursor, what: str) -> None:
        now = cursor.charFormat()
        fmt = QTextCharFormat()
        if what == "bold":
            fmt.setFontWeight(QFont.Normal if now.fontWeight() >= QFont.DemiBold else QFont.Bold)
        elif what == "italic":
            fmt.setFontItalic(not now.fontItalic())
        elif what == "underline":
            fmt.setFontUnderline(not now.fontUnderline())
        elif what == "strike":
            fmt.setFontStrikeOut(not now.fontStrikeOut())
        elif what in ("super", "sub"):
            want = QTextCharFormat.AlignSuperScript if what == "super" else QTextCharFormat.AlignSubScript
            fmt.setVerticalAlignment(QTextCharFormat.AlignNormal if now.verticalAlignment() == want else want)
        elif what in ("bigger", "smaller"):
            size = now.fontPointSize() or BASE_PT
            steps = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 60, 72, 96]
            nxt = [s for s in steps if s > size] if what == "bigger" else [s for s in steps if s < size]
            fmt.setFontPointSize((nxt[0] if what == "bigger" else nxt[-1]) if nxt else size)
        elif what.startswith("size:"):
            fmt.setFontPointSize(max(4.0, min(400.0, float(what[5:] or BASE_PT))))
        elif what.startswith("font:"):
            fmt.setFontFamilies([what[5:]])
        elif what.startswith("#"):
            fmt.setForeground(QColor(what))
        elif what.startswith("mark:"):
            if what == "mark:none":
                fmt.setBackground(QBrush(Qt.NoBrush))
            else:
                fmt.setBackground(QColor(what[5:]))
        elif what == "clear":
            if not cursor.hasSelection():
                cursor.select(QTextCursor.BlockUnderCursor)
            plain = QTextCharFormat()
            level = cursor.blockFormat().headingLevel()
            if level:
                plain.setFontPointSize(STYLES[[k for k, v in STYLES.items() if v[2] == level][0]][0])
                plain.setFontWeight(STYLES[[k for k, v in STYLES.items() if v[2] == level][0]][1])
            cursor.setCharFormat(plain)
            return
        elif what in ("left", "center", "right", "justify"):
            block = QTextBlockFormat()
            block.setAlignment({"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight, "justify": Qt.AlignJustify}[what])
            cursor.mergeBlockFormat(block)
        elif what in STYLES or what in ("quote", "code"):
            self._paragraph_style(cursor, what)
        elif what in ("bullet", "number", "check"):
            self._list(cursor, what)
        elif what in ("indent", "outdent"):
            self._indent(cursor, 1 if what == "indent" else -1)
        elif what.startswith("spacing:"):
            pct = max(80.0, min(300.0, float(what[8:] or 100)))
            for b in list(self._blocks(cursor)):
                c = QTextCursor(b)
                bf = QTextBlockFormat()
                bf.setLineHeight(pct, 1)                       # proportional
                c.mergeBlockFormat(bf)
        elif what.startswith("space:"):                        # space after paragraphs (px)
            for b in list(self._blocks(cursor)):
                c = QTextCursor(b)
                bf = QTextBlockFormat()
                bf.setBottomMargin(max(0.0, float(what[6:] or 0)))
                c.mergeBlockFormat(bf)
        if fmt.propertyCount():
            self._chars_of(cursor, fmt)

    def _paragraph_style(self, cursor: QTextCursor, what: str) -> None:
        for b in list(self._blocks(cursor)):
            c = QTextCursor(b)
            c.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            bf = QTextBlockFormat()
            cf = QTextCharFormat()
            if what in STYLES:
                size, weight, level, before, after = STYLES[what]
                bf.setHeadingLevel(level)
                bf.setTopMargin(before)
                bf.setBottomMargin(after)
                bf.setLeftMargin(0)
                bf.setRightMargin(0)
                bf.setBackground(QBrush(Qt.NoBrush))
                cf.setFontPointSize(size)
                cf.setFontWeight(weight)
                cf.setFontItalic(False)
                if c.charFormat().fontFixedPitch():                # (out of a code paragraph: its typewriter letters go too)
                    cf.setFontFixedPitch(False)
                    cf.setFontFamilies([self._doc.defaultFont().family()])
            elif what == "quote":
                bf.setHeadingLevel(0)
                bf.setLeftMargin(QUOTE_MARGIN)
                bf.setRightMargin(QUOTE_MARGIN)
                bf.setTopMargin(6)
                bf.setBottomMargin(10)
                bf.setBackground(QBrush(Qt.NoBrush))
                cf.setFontPointSize(BASE_PT + 1)
                cf.setFontWeight(QFont.Normal)
                cf.setFontItalic(True)
                cf.setForeground(QColor("#4B5563"))
            else:                                              # code
                bf.setHeadingLevel(0)
                bf.setLeftMargin(0)
                bf.setRightMargin(0)
                bf.setTopMargin(2)
                bf.setBottomMargin(2)
                bf.setBackground(QColor(CODE_BG))
                bf.setNonBreakableLines(True)
                cf.setFontFamilies(["JetBrains Mono", "Liberation Mono", "monospace"])
                cf.setFontFixedPitch(True)
                cf.setFontPointSize(BASE_PT - 1)
                cf.setFontWeight(QFont.Normal)
                cf.setFontItalic(False)
            c.mergeBlockFormat(bf)
            c.mergeBlockCharFormat(cf)
            c.mergeCharFormat(cf)

    @staticmethod
    def _unlist(b) -> None:
        """A paragraph out of its list, where it was (Qt adds the list's indent to the paragraph's own: undone)."""
        lst = b.textList()
        if lst is None:
            return
        indent = b.blockFormat().indent()
        lst.remove(b)
        c = QTextCursor(b)
        bf = c.blockFormat()
        bf.setIndent(indent)
        c.setBlockFormat(bf)

    def _list(self, cursor: QTextCursor, what: str) -> None:
        current = cursor.currentList()
        check = what == "check"
        wanted = BULLETS if what in ("bullet", "check") else NUMBERS
        if current is not None and current.format().style() in wanted:
            is_check = cursor.blockFormat().marker() != QTextBlockFormat.MarkerType.NoMarker
            if is_check == check:                              # the same button again: out of the list
                for b in list(self._blocks(cursor)):
                    self._unlist(b)
                    c = QTextCursor(b)
                    bf = c.blockFormat()
                    bf.setIndent(0)
                    bf.setMarker(QTextBlockFormat.MarkerType.NoMarker)
                    c.setBlockFormat(bf)
                return
            for b in list(self._blocks(cursor)):              # bullets <-> checklist
                c = QTextCursor(b)
                bf = c.blockFormat()
                bf.setMarker(QTextBlockFormat.MarkerType.Unchecked if check else QTextBlockFormat.MarkerType.NoMarker)
                c.setBlockFormat(bf)
            return
        level = max(0, (current.format().indent() - 1)) if current is not None else 0
        lf = QTextListFormat()
        lf.setStyle(wanted[level % 3])
        lf.setIndent(level + 1)
        for b in list(self._blocks(cursor)):
            self._unlist(b)
        cursor.createList(lf)
        for b in list(self._blocks(cursor)):
            c = QTextCursor(b)
            bf = c.blockFormat()
            bf.setMarker(QTextBlockFormat.MarkerType.Unchecked if check else QTextBlockFormat.MarkerType.NoMarker)
            c.setBlockFormat(bf)

    def _indent(self, cursor: QTextCursor, delta: int) -> None:
        lst = cursor.currentList()
        if lst is not None:                                    # in a list: a level deeper or shallower
            old = lst.format()
            level = max(1, min(9, old.indent() + delta))
            numbered = old.style() in NUMBERS
            lf = QTextListFormat()
            lf.setStyle((NUMBERS if numbered else BULLETS)[(level - 1) % 3])
            lf.setIndent(level)
            blocks = list(self._blocks(cursor))
            # join a list at that level just before, so the numbering carries on; else start one
            prev, target = blocks[0].previous(), None
            while prev.isValid() and prev.textList() is not None:
                pf = prev.textList().format()
                if pf.indent() == level and (pf.style() in NUMBERS) == numbered:
                    target = prev.textList()
                    break
                if pf.indent() < level:
                    break
                prev = prev.previous()
            for b in blocks:
                self._unlist(b)
                if target is not None:
                    target.add(b)
                else:
                    target = QTextCursor(b).createList(lf)
            return
        for b in list(self._blocks(cursor)):
            c = QTextCursor(b)
            bf = c.blockFormat()
            bf.setIndent(max(0, min(12, bf.indent() + delta)))
            c.setBlockFormat(bf)

    @Slot(int, result=bool)
    def toggleCheck(self, position: int) -> bool:
        """A checklist's box clicked: tick or untick it. False when there's no box there."""
        if self._doc is None:
            return False
        b = self._doc.findBlock(position)
        bf = b.blockFormat()
        if bf.marker() == QTextBlockFormat.MarkerType.NoMarker:
            return False
        c = QTextCursor(b)
        bf.setMarker(QTextBlockFormat.MarkerType.Unchecked if bf.marker() == QTextBlockFormat.MarkerType.Checked else QTextBlockFormat.MarkerType.Checked)
        c.setBlockFormat(bf)
        return True

    @Slot(int, result=int)
    def newParagraph(self, position: int) -> int:
        """Return at the end of a heading or a quote: the next paragraph is body text (as in Word). -1: not here."""
        if self._doc is None:
            return -1
        b = self._doc.findBlock(position)
        bf = b.blockFormat()
        if b.textList() is not None and b.length() <= 1:      # Return on an empty list item: out of the list (one level at a time)
            c = QTextCursor(b)
            if b.textList().format().indent() > 1:
                self._indent(c, -1)
            else:
                self._unlist(b)
                nb = QTextCursor(b).blockFormat()
                nb.setMarker(QTextBlockFormat.MarkerType.NoMarker)
                QTextCursor(b).setBlockFormat(nb)
            return b.position()
        quote = bf.leftMargin() == QUOTE_MARGIN and bf.rightMargin() == QUOTE_MARGIN
        if not (bf.headingLevel() or quote) or position != b.position() + b.length() - 1 or b.textList() is not None:
            return -1
        size, weight, _, before, after = STYLES["body"]
        nb = QTextBlockFormat()
        nb.setTopMargin(before)
        nb.setBottomMargin(after)
        nb.setAlignment(bf.alignment())
        nc = QTextCharFormat()
        nc.setFontPointSize(size)
        nc.setFontWeight(weight)
        nc.setFontItalic(False)
        nc.setForeground(QColor("#15181C"))
        c = self._cursor(position, position)
        c.insertBlock(nb, nc)
        return c.position()

    @Slot(int, result=int)
    def checkboxAt(self, position: int) -> int:
        """Where the paragraph at `position` starts, when it's a checklist item; else -1."""
        if self._doc is None:
            return -1
        b = self._doc.findBlock(position)
        return b.position() if b.isValid() and b.blockFormat().marker() != QTextBlockFormat.MarkerType.NoMarker else -1

    @Slot(int, bool, result=int)
    def cellStep(self, position: int, back: bool) -> int:
        """Tab in a table: the next cell (Shift+Tab: the one before); Tab in the last cell adds a row."""
        c = self._cursor(position, position)
        t = c.currentTable()
        if t is None:
            return position
        cell = t.cellAt(c)
        r, k = cell.row(), cell.column() + (-1 if back else cell.columnSpan())
        if k >= t.columns():
            r, k = r + 1, 0
        elif k < 0:
            r, k = r - 1, t.columns() - 1
        if r < 0:
            return position
        if r >= t.rows():
            t.appendRows(1)
        nxt = t.cellAt(r, k)
        return nxt.firstCursorPosition().position()

    @Slot(int, result="QVariantMap")
    def state(self, position: int) -> dict:
        if self._doc is None:
            return {}
        cursor = self._cursor(position, position)
        char, block = cursor.charFormat(), cursor.blockFormat()
        level = block.headingLevel()
        align = block.alignment()
        lst = cursor.currentList()
        fam = char.fontFamilies() or [self._doc.defaultFont().family()]
        bg = char.background()
        style = {1: "title", 2: "heading", 3: "subheading", 4: "minor"}.get(level, "body")
        if not level and block.leftMargin() == QUOTE_MARGIN and block.rightMargin() == QUOTE_MARGIN:
            style = "quote"
        elif not level and block.background().style() != Qt.NoBrush and char.fontFixedPitch():
            style = "code"
        table = cursor.currentTable()
        return {"bold": char.fontWeight() >= QFont.DemiBold, "italic": char.fontItalic(), "underline": char.fontUnderline(),
                "strike": char.fontStrikeOut(), "super": char.verticalAlignment() == QTextCharFormat.AlignSuperScript,
                "sub": char.verticalAlignment() == QTextCharFormat.AlignSubScript, "style": style,
                "align": "center" if align & Qt.AlignHCenter else "right" if align & Qt.AlignRight else "justify" if align & Qt.AlignJustify else "left",
                "list": "" if lst is None else ("check" if block.marker() != QTextBlockFormat.MarkerType.NoMarker else
                                                "number" if lst.format().style() in NUMBERS else "bullet"),
                "size": round(char.fontPointSize() or BASE_PT, 1), "font": str(fam[0]) if fam else "Inter",
                "colour": char.foreground().color().name() if char.foreground().style() != Qt.NoBrush else "",
                "mark": bg.color().name() if bg.style() != Qt.NoBrush and bg.color().alpha() > 0 else "",
                "spacing": round(block.lineHeight()) if block.lineHeightType() == 1 else 100,
                "table": table is not None, "image": self._image_at(position) is not None}

    @Property("QVariantList", constant=True)
    def fonts(self):
        have = QFontDatabase.families()
        first = [f for f in FAVOURITE_FONTS if f in have]
        rest = sorted({f for f in have if not f.startswith(("Noto Sans ", "Noto Serif ", "Noto Kufi", "Noto Naskh", "Noto Nastaliq", "Noto Rashi"))
                       and f not in first and not QFontDatabase.isPrivateFamily(f)}, key=str.lower)
        return first + rest

    # ------------------------------------------------------------------ inserting: page breaks, tables, pictures, lines, links
    @Slot(int, result=int)
    def pageBreak(self, position: int) -> int:
        if self._doc is None:
            return position
        c = self._cursor(position, position)
        c.beginEditBlock()
        c.insertBlock()
        bf = c.blockFormat()
        bf.setPageBreakPolicy(QTextFormat.PageBreak_AlwaysBefore)
        c.setBlockFormat(bf)
        c.endEditBlock()
        return c.position()

    @Slot(int, int, int, result=int)
    def insertTable(self, position: int, rows: int, cols: int) -> int:
        if self._doc is None:
            return position
        c = self._cursor(position, position)
        c.beginEditBlock()
        if c.block().length() > 1:
            c.insertBlock()
        tf = QTextTableFormat()
        tf.setBorder(1)
        tf.setBorderBrush(QColor("#9AA0A6"))
        tf.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
        tf.setBorderCollapse(True)
        tf.setCellPadding(6)
        tf.setCellSpacing(0)
        tf.setWidth(QTextLength(QTextLength.PercentageLength, 100))
        cols = max(1, min(20, cols))
        tf.setColumnWidthConstraints([QTextLength(QTextLength.PercentageLength, 100 / cols)] * cols)
        table = c.insertTable(max(1, min(200, rows)), cols, tf)
        c.endEditBlock()
        return table.cellAt(0, 0).firstCursorPosition().position()

    @Slot(int, result="QVariantMap")
    def tableAt(self, position: int) -> dict:
        if self._doc is None:
            return {}
        c = self._cursor(position, position)
        t = c.currentTable()
        if t is None:
            return {}
        cell = t.cellAt(c)
        return {"rows": t.rows(), "cols": t.columns(), "row": cell.row(), "col": cell.column()}

    @Slot(int, int, str, result=int)
    def tableDo(self, start: int, end: int, action: str) -> int:
        """rowAbove, rowBelow, colLeft, colRight, delRow, delCol, delTable, merge, split, header (shade the first row).
        Returns where the cursor should go."""
        if self._doc is None:
            return start
        c = self._cursor(start, end)
        t = c.currentTable()
        if t is None:
            return start
        cell = t.cellAt(min(start, end) if start != end else start)
        r, k = cell.row(), cell.column()
        c.beginEditBlock()
        try:
            if action == "rowAbove":
                t.insertRows(r, 1)
            elif action == "rowBelow":
                t.insertRows(r + cell.rowSpan(), 1)
            elif action == "colLeft":
                t.insertColumns(k, 1)
            elif action == "colRight":
                t.insertColumns(k + cell.columnSpan(), 1)
            elif action == "delRow":
                if t.rows() == 1:
                    action = "delTable"
                else:
                    t.removeRows(r, 1)
            elif action == "delCol":
                if t.columns() == 1:
                    action = "delTable"
                else:
                    t.removeColumns(k, 1)
            elif action == "merge" and c.hasSelection():
                t.mergeCells(c)
            elif action == "split":
                t.splitCell(r, k, 1, 1)
            elif action == "header":
                first = t.cellAt(0, 0).format()
                shaded = first.background().style() != Qt.NoBrush
                for col in range(t.columns()):
                    tc = t.cellAt(0, col)
                    f = tc.format()
                    f.setBackground(Qt.NoBrush if shaded else QColor("#E9EEF4"))
                    tc.setFormat(f)
                    cc = tc.firstCursorPosition()
                    cc.setPosition(tc.lastCursorPosition().position(), QTextCursor.KeepAnchor)
                    cf = QTextCharFormat()
                    cf.setFontWeight(QFont.Normal if shaded else QFont.DemiBold)
                    cc.mergeCharFormat(cf)
            if action == "delTable":
                at = max(0, t.firstPosition() - 1)
                t.removeRows(0, t.rows())                      # (no rows left: the table goes)
                return at
            if t.columns():
                n = t.columns()
                tf = t.format()
                tf.setColumnWidthConstraints([QTextLength(QTextLength.PercentageLength, 100 / n)] * n)
                t.setFormat(tf)
        finally:
            c.endEditBlock()
        return start

    def _image_at(self, position: int):
        """(cursor on the picture, its format) for a picture at or just before `position`, else None."""
        if self._doc is None:
            return None
        for p in (position, position - 1):
            if p < 0:
                continue
            c = self._cursor(p, p + 1)
            fmt = c.charFormat()
            if c.selectedText() == "￼" and fmt.isImageFormat():
                return c, fmt.toImageFormat()
        return None

    @Slot(int, str, result=str)
    def insertPicture(self, position: int, path: str) -> str:
        """A picture at the cursor, as wide as the text at most. Returns "" or why not."""
        if self._doc is None:
            return "No document"
        try:
            uri, w, h = image_data_uri(path)
        except OSError as err:
            return str(err)
        room = paper_px(self._setup)[0] - (self._setup["margins"][1] + self._setup["margins"][3]) * PX_PER_MM
        scale = min(1.0, room / max(1, w))
        fmt = QTextImageFormat()
        fmt.setName(uri)
        fmt.setWidth(round(w * scale))
        fmt.setHeight(round(h * scale))
        c = self._cursor(position, position)
        c.insertImage(fmt)
        return ""

    @Slot(int, int)
    def sizePicture(self, position: int, percent: int) -> None:
        """A picture's width as a share of the text's width (its shape kept)."""
        hit = self._image_at(position)
        if hit is None:
            return
        c, fmt = hit
        img = self._doc.resource(QTextDocument.ImageResource, QUrl(fmt.name()))
        w0, h0 = (img.width(), img.height()) if img is not None and hasattr(img, "width") and img.width() > 0 else (fmt.width() or 100, fmt.height() or 100)
        room = paper_px(self._setup)[0] - (self._setup["margins"][1] + self._setup["margins"][3]) * PX_PER_MM
        w = room * max(5, min(100, percent)) / 100
        fmt.setWidth(round(w))
        fmt.setHeight(round(w * h0 / max(1, w0)))
        c.setCharFormat(fmt)

    @Slot(int, result=int)
    def pictureShare(self, position: int) -> int:
        hit = self._image_at(position)
        if hit is None:
            return 0
        room = paper_px(self._setup)[0] - (self._setup["margins"][1] + self._setup["margins"][3]) * PX_PER_MM
        return round(100 * hit[1].width() / max(1, room))

    @Slot(int, int, str, str)
    def link(self, start: int, end: int, url: str, text: str) -> None:
        if self._doc is None:
            return
        url = url.strip()
        if url and not re.match(r"^[a-z][a-z0-9+.-]*:", url):
            url = "https://" + url
        c = self._cursor(start, end)
        c.beginEditBlock()
        fmt = QTextCharFormat()
        if url:
            fmt.setAnchor(True)
            fmt.setAnchorHref(url)
            fmt.setForeground(QColor("#2361AE"))
            fmt.setFontUnderline(True)
        else:
            fmt.setAnchor(False)
            fmt.setAnchorHref("")
            fmt.setForeground(QColor("#15181C"))
            fmt.setFontUnderline(False)
        if c.hasSelection():
            c.mergeCharFormat(fmt)
        else:
            c.insertText(text or url, fmt)
        c.endEditBlock()

    @Slot(int, result=str)
    def linkAt(self, position: int) -> str:
        if self._doc is None:
            return ""
        c = self._cursor(position, position + 1)
        return c.charFormat().anchorHref() if c.charFormat().isAnchor() else ""

    @Slot(int)
    def insertLine(self, position: int) -> None:
        if self._doc is not None:
            c = self._cursor(position, position)
            c.insertHtml("<hr/>")

    @Slot(int, result=int)
    def insertContents(self, position: int) -> int:
        """A table of contents from the headings (plain text with their page numbers), at the cursor."""
        if self._doc is None:
            return position
        items = self.outline()
        room = paper_px(self._setup)[0] - (self._setup["margins"][1] + self._setup["margins"][3]) * PX_PER_MM
        c = self._cursor(position, position)
        c.beginEditBlock()
        bf = QTextBlockFormat()
        bf.setHeadingLevel(0)
        cf = QTextCharFormat()
        cf.setFontPointSize(14)
        cf.setFontWeight(QFont.DemiBold)
        c.insertBlock(bf, cf)
        c.insertText("Contents", cf)
        for it in items:
            if it["level"] <= 1:
                continue
            bf = QTextBlockFormat()
            bf.setLeftMargin(18 * (it["level"] - 2))
            bf.setBottomMargin(2)
            bf.setTabPositions([QTextOption.Tab(room - 18 * (it["level"] - 2), QTextOption.RightTab)])
            cf = QTextCharFormat()
            cf.setFontPointSize(BASE_PT)
            cf.setFontWeight(QFont.Normal)
            c.insertBlock(bf, cf)
            c.insertText(f"{it['text']}\t{it['page']}", cf)
        c.insertBlock(QTextBlockFormat(), QTextCharFormat())
        c.endEditBlock()
        return c.position()

    @Slot(result="QVariantList")
    def outline(self) -> list:
        """The headings, for the navigation pane: [{text, level, at, page}]."""
        if self._doc is None:
            return []
        out, b = [], self._doc.begin()
        stride = paper_px(self._setup)[1] + GAP
        lay = self._doc.documentLayout()
        while b.isValid():
            lvl = b.blockFormat().headingLevel()
            if lvl and b.text().strip():
                out.append({"text": b.text().strip()[:120], "level": lvl, "at": b.position(), "page": int(lay.blockBoundingRect(b).y() // stride) + 1})
            b = b.next()
        return out[:400]

    # ------------------------------------------------------------------ find and replace
    def _pattern(self, text: str, case: bool, whole: bool):
        if not text:
            return None
        body = re.escape(text)
        if whole:
            body = rf"(?<!\w){body}(?!\w)"
        return re.compile(body, 0 if case else re.IGNORECASE)

    @Slot(str, bool, bool, result=int)
    def findAll(self, text: str, case: bool, whole: bool) -> int:
        """Mark every match (the Marks layer) and say how many there are."""
        if self._doc is None or self._marks is None:
            return 0
        pat = self._pattern(text, case, whole)
        self._marks.find = pat
        self._marks.rehighlight()
        if pat is None:
            return 0
        return sum(len(pat.findall(b)) for b in self._doc.toPlainText().split("\n"))

    @Slot(str, bool, bool, int, bool, result="QVariantList")
    def findNext(self, text: str, case: bool, whole: bool, start: int, backwards: bool) -> list:
        """[start, end] of the next match from `start` (round from the other end when none), or []."""
        if self._doc is None or not text:
            return []
        flags = QTextDocument.FindFlag(0)
        if case:
            flags |= QTextDocument.FindCaseSensitively
        if whole:
            flags |= QTextDocument.FindWholeWords
        if backwards:
            flags |= QTextDocument.FindBackward
        c = self._doc.find(text, start, flags)
        if c.isNull():
            c = self._doc.find(text, self._doc.characterCount() - 1 if backwards else 0, flags)
        return [] if c.isNull() else [c.selectionStart(), c.selectionEnd()]

    @Slot(int, int, str, result=int)
    def replaceAt(self, start: int, end: int, text: str) -> int:
        return self.putText(start, end, text)

    @Slot(str, str, bool, bool, result=int)
    def replaceAll(self, text: str, by: str, case: bool, whole: bool) -> int:
        if self._doc is None or not text:
            return 0
        flags = QTextDocument.FindFlag(0)
        if case:
            flags |= QTextDocument.FindCaseSensitively
        if whole:
            flags |= QTextDocument.FindWholeWords
        n, at = 0, 0
        edit = QTextCursor(self._doc)
        edit.beginEditBlock()
        while True:
            c = self._doc.find(text, at, flags)
            if c.isNull():
                break
            c.insertText(by)
            at = c.position()
            n += 1
            if n > 100000:
                break
        edit.endEditBlock()
        return n

    # ------------------------------------------------------------------ spelling
    spellChanged = Signal()

    @Property("QVariantMap", notify=spellChanged)
    def spelling(self):
        return {"available": self._speller.available, "on": self._spell_on and self._speller.available, "lang": self._speller.lang,
                "langs": [{"id": l, "name": QLocale(l).nativeLanguageName().capitalize() + (" (" + QLocale(l).nativeTerritoryName() + ")" if "_" in l else "")}
                          for l in self._speller.langs if len(l) <= 5]}

    @Slot(bool)
    def setSpelling(self, on: bool) -> None:
        self._spell_on = bool(on)
        self.spellChanged.emit()

    @Slot(str)
    def setSpellLang(self, lang: str) -> None:
        self._speller.use(lang)
        self.spellChanged.emit()

    @Slot(int, result="QVariantMap")
    def wordAt(self, position: int) -> dict:
        """The word under a point, and if it's spelled wrong, what it might be: {start, end, word, wrong, suggestions}."""
        if self._doc is None:
            return {}
        b = self._doc.findBlock(position)
        text, off = b.text(), position - b.position()
        for m in WORD.finditer(text):
            if m.start() <= off <= m.end():
                w = m.group(0)
                wrong = self._spell_on and self._speller.available and w not in self._marks.ignored and not self._speller.ok(w)
                return {"start": b.position() + m.start(), "end": b.position() + m.end(), "word": w, "wrong": wrong,
                        "suggestions": self._speller.suggest(w) if wrong else []}
        return {}

    @Slot(int, int, result="QVariantList")
    def spellMarks(self, start: int, end: int) -> list:
        """[[start, end], ...] of the words spelled wrong in the paragraphs between two places (what's on screen)."""
        if self._doc is None or not (self._spell_on and self._speller.available):
            return []
        out, b = [], self._doc.findBlock(max(0, start))
        last = self._doc.findBlock(max(0, end))
        while b.isValid() and len(out) < 600:
            if b.length() > 1:
                for m in WORD.finditer(b.text()):
                    w = m.group(0)
                    if w not in self._marks.ignored and not self._speller.ok(w):
                        out.append([b.position() + m.start(), b.position() + m.end()])
            if b == last:
                break
            b = b.next()
        return out

    @Slot(str)
    def learnWord(self, word: str) -> None:
        self._speller.add(word)
        self.spellChanged.emit()

    @Slot(str)
    def ignoreWord(self, word: str) -> None:
        if self._marks is not None:
            self._marks.ignored.add(word)
            self.spellChanged.emit()

    @Slot(result="QVariantList")
    def misspelled(self) -> list:
        """Every word spelled wrong, in order: [{start, end, word}] (for stepping through them)."""
        if self._doc is None or not (self._spell_on and self._speller.available):
            return []
        out, b = [], self._doc.begin()
        while b.isValid() and len(out) < 2000:
            for m in WORD.finditer(b.text()):
                w = m.group(0)
                if w not in self._marks.ignored and not self._speller.ok(w):
                    out.append({"start": b.position() + m.start(), "end": b.position() + m.end(), "word": w})
            b = b.next()
        return out

    # ------------------------------------------------------------------ pages out: PDF, print
    def _print_doc(self) -> QTextDocument:
        """A copy of the document laid out on the paper itself (no gaps between sheets)."""
        copy = self._doc.clone()
        copy.setDocumentMargin(0)
        w, h = paper_px(self._setup)
        top, right, bottom, left = (m * PX_PER_MM for m in self._setup["margins"])
        ff = copy.rootFrame().frameFormat()
        ff.setTopMargin(top)
        ff.setBottomMargin(bottom)
        ff.setLeftMargin(left)
        ff.setRightMargin(right)
        copy.rootFrame().setFrameFormat(ff)
        copy.setPageSize(QSizeF(w, h))
        return copy

    def write_pdf(self, out: Path) -> int:
        """The document as a PDF, page by page with its headers, footers and numbers. Returns the number of pages."""
        copy = self._print_doc()
        w, h = paper_px(self._setup)
        top, right, bottom, left = (m * PX_PER_MM for m in self._setup["margins"])
        pdf = QPdfWriter(str(out))
        size = QPageSize(QPAGE[self._setup["paper"]])
        pdf.setPageSize(size)
        pdf.setPageOrientation(QPageLayout.Landscape if self._setup["landscape"] else QPageLayout.Portrait)
        pdf.setPageMargins(QMarginsF(0, 0, 0, 0))
        pdf.setResolution(96)
        pdf.setTitle(self.title)
        pdf.setCreator("Huginn Writer")
        painter = QPainter(pdf)
        n = max(1, copy.pageCount())
        lay = copy.documentLayout()
        small = QFont("Inter")
        small.setPointSizeF(9)
        for k in range(n):
            if k:
                pdf.newPage()
            painter.save()
            painter.translate(0, -k * h)
            ctx = QAbstractTextDocumentLayout.PaintContext()
            ctx.clip = QRectF(0, k * h, w, h)
            painter.setClipRect(ctx.clip)
            lay.draw(painter, ctx)
            painter.restore()
            painter.setFont(small)
            painter.setPen(QColor("#5F6670"))
            head, foot, num = self._band("header", k + 1, n), self._band("footer", k + 1, n), self.numberFor(k + 1)
            band_top = QRectF(left, max(16.0, top / 2 - 10), w - left - right, 20)
            band_bottom = QRectF(left, h - max(16.0, bottom / 2) - 10, w - left - right, 20)
            if head:
                painter.drawText(band_top, Qt.AlignLeft | Qt.AlignVCenter, head)
            if foot:
                painter.drawText(band_bottom, Qt.AlignLeft | Qt.AlignVCenter, foot)
            if num:
                where = self._setup["numbers"]
                painter.drawText(band_top if where == "top-right" else band_bottom,
                                 (Qt.AlignHCenter if where == "bottom-center" else Qt.AlignRight) | Qt.AlignVCenter, str(k + 1))
        painter.end()
        return n

    @Slot(result="QVariantList")
    def printers(self) -> list:
        """The printers CUPS knows: [{id, name, default}]."""
        if not shutil.which("lpstat"):
            return []
        try:
            names = subprocess.run(["lpstat", "-e"], capture_output=True, text=True, timeout=5).stdout.split()
            default = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        dflt = default.split(":", 1)[1].strip() if ":" in default else ""
        return [{"id": n, "name": n.replace("_", " "), "default": n == dflt} for n in names]

    @Slot(str, int, str, bool, result=str)
    def printTo(self, printer: str, copies: int, pages: str, both_sides: bool) -> str:
        """Send the document to a printer through CUPS. Returns "" or why not."""
        if self._doc is None:
            return "Nothing to print."
        if not shutil.which("lp"):
            return "Printing needs CUPS, which isn't installed."
        pages = re.sub(r"\s+", "", pages or "")
        if pages and not re.fullmatch(r"\d+(-\d+)?(,\d+(-\d+)?)*", pages):
            return "Pages are numbers like 1-3,5."
        tmp = Path(tempfile.mkdtemp(prefix="huginn-print-")) / f"{self.title or 'Document'}.pdf"
        try:
            self.write_pdf(tmp)
            args = ["lp", "-d", printer, "-n", str(max(1, min(99, copies))), "-t", self.title or "Document"]
            if pages:
                args += ["-P", pages]
            if both_sides:
                args += ["-o", "sides=two-sided-long-edge"]
            done = subprocess.run(args + [str(tmp)], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as err:
            return f"It couldn't be printed: {err}"
        finally:
            QTimer.singleShot(60000, lambda: shutil.rmtree(tmp.parent, ignore_errors=True))
        if done.returncode != 0:
            return "The printer said: " + (done.stderr.strip() or done.stdout.strip() or "no")[:160]
        return ""

    # ------------------------------------------------------------------ export
    @Slot(str, result=str)
    def export(self, kind: str) -> str:
        """kind: pdf | docx | odt | md | html | txt. Writes beside the document and returns the new file's path ('' on failure)."""
        if self._doc is None or self._path is None:
            return ""
        self.save()
        try:
            out = fresh_path(self._path.parent, self._path.stem, "." + kind)
            if kind == "pdf":
                self.write_pdf(out)
            elif kind == "odt":
                writer = QTextDocumentWriter(str(out), b"odf")
                if not writer.write(self._print_doc()):
                    raise OSError("the document couldn't be written")
            elif kind == "md":
                out.write_text(self._doc.toMarkdown(), encoding="utf-8")
            elif kind == "txt":
                out.write_text(self._doc.toPlainText(), encoding="utf-8")
            elif kind == "html":
                out.write_text(self._doc.toHtml(), encoding="utf-8")
            elif kind == "docx":
                self._tidy_review()
                docx.document_to_docx(self._doc, self._setup, out, self.title, self._review)
            else:
                return ""
        except (OSError, docx.ConvertError) as err:
            self.failed.emit(f"Couldn't export: {getattr(err, 'strerror', None) or err}")
            return ""
        return str(out)

    @Slot(int, int, str)
    def put_html(self, start: int, end: int, markup: str) -> None:
        """Paste formatted text (from another app) in place of a stretch."""
        if self._doc is not None:
            self._cursor(start, end).insertHtml(markup)
