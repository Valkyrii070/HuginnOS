"""Word documents (.docx) in and out for Huginn Writer, with Python's standard library and Qt's text document.

Out: a QTextDocument is walked paragraph by paragraph and table by table and written as WordprocessingML: styles
(Title, Heading 1-3, Quote, Code), runs (font, size, bold, italic, underline, strike, raised and lowered, colour,
shading), links, pictures (inline, embedded), lists with levels (bullets, numbers, checklists), tables (with merged
cells and a shaded header row), page breaks, line spacing and indents, and the page itself (size, orientation,
margins, header, footer, page numbers as fields).

In: the same things the other way, into HTML Qt reads, plus a plain-language list of what didn't come across.
"""
import base64
import html
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QFont, QTextBlockFormat, QTextCharFormat, QTextDocument, QTextFormat, QTextListFormat

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_PART = 64 * 1024 * 1024
TWIP_PX = 15          # 1 px (1/96 in) is 15 twips (1/1440 in)
EMU_PX = 9525         # and 9525 EMU
PAPERS_MM = {"letter": (215.9, 279.4), "a4": (210.0, 297.0), "legal": (215.9, 355.6), "a5": (148.0, 210.0)}
HIGHLIGHT = {"yellow": "FFFF00", "green": "00FF00", "cyan": "00FFFF", "magenta": "FF00FF", "blue": "0000FF", "red": "FF0000",
             "darkBlue": "000080", "darkCyan": "008080", "darkGreen": "008000", "darkMagenta": "800080", "darkRed": "800000",
             "darkYellow": "808000", "darkGray": "808080", "lightGray": "C0C0C0", "black": "000000", "white": "FFFFFF"}


class ConvertError(Exception):
    pass


def _q(tag: str, ns: str = W) -> str:
    return f"{{{ns}}}{tag}"


def _attr(s: str) -> str:
    return escape(s, {'"': "&quot;"})


# ================================================================================================ writing
STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="%(W)s">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="%(font)s" w:hAnsi="%(font)s" w:eastAsia="%(font)s" w:cs="%(font)s"/><w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="%(lang)s"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:before="90" w:after="150"/></w:pPr><w:rPr><w:b/><w:sz w:val="52"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="270" w:after="90"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="210" w:after="60"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="180" w:after="60"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:ind w:left="540" w:right="540"/></w:pPr><w:rPr><w:i/><w:color w:val="4B5563"/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="HuginnCode"><w:name w:val="Code"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:shd w:val="clear" w:color="auto" w:fill="F1F3F5"/><w:spacing w:before="30" w:after="30" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:rFonts w:ascii="JetBrains Mono" w:hAnsi="JetBrains Mono" w:cs="JetBrains Mono"/><w:sz w:val="20"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="40"/><w:contextualSpacing/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Header"><w:name w:val="header"/><w:basedOn w:val="Normal"/><w:rPr><w:color w:val="5F6670"/><w:sz w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/><w:rPr><w:color w:val="5F6670"/><w:sz w:val="18"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:rPr><w:color w:val="2361AE"/><w:u w:val="single"/></w:rPr></w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:tblPr><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:basedOn w:val="TableNormal"/><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="9AA0A6"/><w:left w:val="single" w:sz="4" w:space="0" w:color="9AA0A6"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="9AA0A6"/><w:right w:val="single" w:sz="4" w:space="0" w:color="9AA0A6"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="9AA0A6"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="9AA0A6"/></w:tblBorders></w:tblPr></w:style>
</w:styles>"""

BULLET_GLYPHS = ("•", "◦", "▪")
NUMBER_KINDS = (("decimal", "%{n}."), ("lowerLetter", "%{n}."), ("lowerRoman", "%{n}."))


def _numbering_xml(numbered_lists: int) -> str:
    lv_b = "".join(f'<w:lvl w:ilvl="{i}"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="{BULLET_GLYPHS[i % 3]}"/><w:lvlJc w:val="left"/>'
                   f'<w:pPr><w:ind w:left="{360 * (i + 1) + 360}" w:hanging="360"/></w:pPr></w:lvl>' for i in range(9))
    lv_n = "".join(f'<w:lvl w:ilvl="{i}"><w:start w:val="1"/><w:numFmt w:val="{NUMBER_KINDS[i % 3][0]}"/><w:lvlText w:val="%{i + 1}."/><w:lvlJc w:val="left"/>'
                   f'<w:pPr><w:ind w:left="{360 * (i + 1) + 360}" w:hanging="360"/></w:pPr></w:lvl>' for i in range(9))
    nums = '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
    for k in range(numbered_lists):                 # each numbered list starts again from 1
        nums += f'<w:num w:numId="{k + 2}"><w:abstractNumId w:val="1"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>'
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering xmlns:w="{W}">'
            f'<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>{lv_b}</w:abstractNum>'
            f'<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="hybridMultilevel"/>{lv_n}</w:abstractNum>{nums}</w:numbering>')


class _Out:
    """What the writer collects on the way: pictures, links, numbered lists."""

    def __init__(self, doc: QTextDocument):
        self.doc = doc
        self.rels = []                 # (id, type, target, external)
        self.media = {}                # name -> bytes
        self.lists = {}                # QTextList key -> numId
        self.next_num = 2
        self.pic = 0

    def rel(self, kind: str, target: str, external: bool = False) -> str:
        rid = f"rId{len(self.rels) + 10}"
        self.rels.append((rid, kind, target, external))
        return rid


def _run_props(cf: QTextCharFormat, default_family: str) -> str:
    out = []
    fams = cf.fontFamilies() if cf.hasProperty(QTextFormat.FontFamilies) else []
    fam = str(fams[0]) if fams else ""
    if fam and fam != default_family:
        out.append(f'<w:rFonts w:ascii="{_attr(fam)}" w:hAnsi="{_attr(fam)}" w:cs="{_attr(fam)}"/>')
    if cf.hasProperty(QTextFormat.FontWeight) and cf.fontWeight() >= QFont.DemiBold:
        out.append("<w:b/>")
    if cf.fontItalic():
        out.append("<w:i/>")
    if cf.fontStrikeOut():
        out.append("<w:strike/>")
    if cf.foreground().style() != Qt.NoBrush:
        c = cf.foreground().color().name()[1:].upper()
        if c != "15181C":
            out.append(f'<w:color w:val="{c}"/>')
    if cf.fontPointSize() and abs(cf.fontPointSize() - 11) > 0.01:
        out.append(f'<w:sz w:val="{int(round(cf.fontPointSize() * 2))}"/><w:szCs w:val="{int(round(cf.fontPointSize() * 2))}"/>')
    if cf.fontUnderline() and not cf.isAnchor():
        out.append('<w:u w:val="single"/>')
    bg = cf.background()
    if bg.style() != Qt.NoBrush and bg.color().alpha() > 0:
        out.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{bg.color().name()[1:].upper()}"/>')
    va = cf.verticalAlignment()
    if va == QTextCharFormat.AlignSuperScript:
        out.append('<w:vertAlign w:val="superscript"/>')
    elif va == QTextCharFormat.AlignSubScript:
        out.append('<w:vertAlign w:val="subscript"/>')
    if cf.isAnchor():
        out.insert(0, '<w:rStyle w:val="Hyperlink"/>')
    return f"<w:rPr>{''.join(out)}</w:rPr>" if out else ""


def _text_runs(text: str, rpr: str) -> str:
    out = []
    for k, piece in enumerate(re.split(r"(\t| |\n)", text)):
        if piece == "\t":
            out.append(f"<w:r>{rpr}<w:tab/></w:r>")
        elif piece in (" ", "\n"):
            out.append(f"<w:r>{rpr}<w:br/></w:r>")
        elif piece:
            out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(piece)}</w:t></w:r>')
    return "".join(out)


def _picture(o: _Out, name: str, w: float, h: float) -> str:
    data, ext = None, "png"
    if name.startswith("data:"):
        m = re.match(r"data:image/([a-z+]+);base64,(.*)", name, re.S)
        if m:
            ext = {"jpeg": "jpeg", "jpg": "jpeg", "png": "png", "gif": "gif"}.get(m.group(1), "png")
            data = base64.b64decode(m.group(2))
    else:
        path = QUrl(name).toLocalFile() if name.startswith("file:") else name
        try:
            data = Path(path).read_bytes()
            ext = "jpeg" if data[:3] == b"\xff\xd8\xff" else "gif" if data[:3] == b"GIF" else "png"
        except OSError:
            data = None
    if not data:
        return ""
    if not (w and h):
        img = o.doc.resource(QTextDocument.ImageResource, QUrl(name))
        w, h = (img.width(), img.height()) if img is not None and hasattr(img, "width") else (200, 150)
    o.pic += 1
    fname = f"image{o.pic}.{ext}"
    o.media[fname] = data
    rid = o.rel(f"{REL}/image", f"media/{fname}")
    cx, cy = int(w * EMU_PX), int(h * EMU_PX)
    return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{o.pic}" name="Picture {o.pic}"/><wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            f'<a:graphic><a:graphicData uri="{PIC}"><pic:pic><pic:nvPicPr><pic:cNvPr id="{o.pic}" name="{fname}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            f'</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')


def _paragraph(o: _Out, block, default_family: str, in_cell: bool = False) -> str:
    bf = block.blockFormat()
    ppr = []
    level = bf.headingLevel()
    lst = block.textList()
    check = bf.marker() != QTextBlockFormat.MarkerType.NoMarker
    style = {1: "Title", 2: "Heading1", 3: "Heading2", 4: "Heading3"}.get(level)
    if not style and bf.leftMargin() == 36 and bf.rightMargin() == 36:
        style = "Quote"
    first = block.begin()
    if not style and bf.background().style() != Qt.NoBrush and not first.atEnd() and first.fragment().charFormat().fontFixedPitch():
        style = "HuginnCode"
    if not style and lst is not None:
        style = "ListParagraph"
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if bf.pageBreakPolicy() & QTextFormat.PageBreak_AlwaysBefore:
        ppr.append("<w:pageBreakBefore/>")
    if lst is not None and not check:
        lf = lst.format()
        numbered = lf.style() in (QTextListFormat.ListDecimal, QTextListFormat.ListLowerAlpha, QTextListFormat.ListUpperAlpha,
                                  QTextListFormat.ListLowerRoman, QTextListFormat.ListUpperRoman)
        if numbered:
            key = lst.item(0).position() if lst.count() else 0
            if key not in o.lists:
                o.lists[key] = o.next_num
                o.next_num += 1
            num = o.lists[key]
        else:
            num = 1
        ppr.append(f'<w:numPr><w:ilvl w:val="{max(0, min(8, lf.indent() - 1))}"/><w:numId w:val="{num}"/></w:numPr>')
    sp = []
    if bf.hasProperty(QTextFormat.BlockTopMargin) and not style:
        sp.append(f'w:before="{int(bf.topMargin() * TWIP_PX)}"')
    if bf.hasProperty(QTextFormat.BlockBottomMargin) and not style:
        sp.append(f'w:after="{int(bf.bottomMargin() * TWIP_PX)}"')
    if bf.lineHeightType() == 1 and bf.lineHeight():
        sp.append(f'w:line="{int(round(240 * bf.lineHeight() / 100))}" w:lineRule="auto"')
    if sp:
        ppr.append(f"<w:spacing {' '.join(sp)}/>")
    if style not in ("Quote",) and lst is None and (bf.leftMargin() or bf.indent() or bf.textIndent() or bf.rightMargin()):
        left = bf.leftMargin() + bf.indent() * 40
        ind = f'w:left="{int(left * TWIP_PX)}"'
        if bf.rightMargin():
            ind += f' w:right="{int(bf.rightMargin() * TWIP_PX)}"'
        if bf.textIndent():
            ind += f' w:firstLine="{int(bf.textIndent() * TWIP_PX)}"' if bf.textIndent() > 0 else f' w:hanging="{int(-bf.textIndent() * TWIP_PX)}"'
        ppr.append(f"<w:ind {ind}/>")
    al = bf.alignment()
    jc = "center" if al & Qt.AlignHCenter else "right" if al & Qt.AlignRight else "both" if al & Qt.AlignJustify else ""
    if jc:
        ppr.append(f'<w:jc w:val="{jc}"/>')
    runs = []
    if check:
        runs.append(_text_runs("☒ " if bf.marker() == QTextBlockFormat.MarkerType.Checked else "☐ ", ""))
        if lst is not None:
            ppr.append(f'<w:ind w:left="{360 * lst.format().indent() + 360}"/>')
    it = block.begin()
    link_open, link_xml = None, []
    while not it.atEnd():
        frag = it.fragment()
        it += 1
        if not frag.isValid():
            continue
        cf = frag.charFormat()
        if cf.isImageFormat():
            imf = cf.toImageFormat()
            for _ in frag.text():
                runs.append(_picture(o, imf.name(), imf.width(), imf.height()))
            continue
        rpr = _run_props(cf, default_family)
        piece = _text_runs(frag.text(), rpr)
        href = cf.anchorHref() if cf.isAnchor() else ""
        if href:
            if link_open != href:
                if link_open is not None:
                    runs.append("".join(link_xml) + "</w:hyperlink>")
                rid = o.rel(f"{REL}/hyperlink", href, external=True)
                link_open, link_xml = href, [f'<w:hyperlink r:id="{rid}">']
            link_xml.append(piece)
            continue
        if link_open is not None:
            runs.append("".join(link_xml) + "</w:hyperlink>")
            link_open, link_xml = None, []
        runs.append(piece)
    if link_open is not None:
        runs.append("".join(link_xml) + "</w:hyperlink>")
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{''.join(runs)}</w:p>"


def _frame_body(o: _Out, frame, default_family: str, content_px: float) -> str:
    out = []
    it = frame.begin()
    while not it.atEnd():
        child = it.currentFrame()
        if child is not None:
            table = _as_table(o.doc, child)
            out.append(_table(o, table, default_family, content_px) if table is not None else _frame_body(o, child, default_family, content_px))
        else:
            block = it.currentBlock()
            if block.isValid():
                out.append(_paragraph(o, block, default_family))
        it += 1
    return "".join(out)


def _as_table(doc, frame):
    from PySide6.QtGui import QTextCursor
    c = QTextCursor(doc)
    c.setPosition(frame.firstPosition())
    t = c.currentTable()
    return t if t is not None and t.firstPosition() == frame.firstPosition() else None


def _table(o: _Out, t, default_family: str, content_px: float) -> str:
    rows, cols = t.rows(), t.columns()
    widths = []
    cons = t.format().columnWidthConstraints()
    total = int(content_px * TWIP_PX)
    for k in range(cols):
        share = cons[k].rawValue() / 100 if k < len(cons) and cons[k].type() == cons[k].Type.PercentageLength else 1 / cols
        widths.append(max(200, int(total * share)))
    out = [f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="5000" w:type="pct"/><w:tblLook w:val="04A0" w:firstRow="1"/></w:tblPr>'
           f'<w:tblGrid>{"".join(f"<w:gridCol w:w=\"{w}\"/>" for w in widths)}</w:tblGrid>']
    for r in range(rows):
        out.append("<w:tr>")
        c = 0
        while c < cols:
            cell = t.cellAt(r, c)
            span = max(1, cell.columnSpan())
            tcpr = [f'<w:tcW w:w="{sum(widths[c:c + span])}" w:type="dxa"/>']
            if span > 1:
                tcpr.append(f'<w:gridSpan w:val="{span}"/>')
            if cell.rowSpan() > 1 or cell.row() != r:
                tcpr.append('<w:vMerge w:val="restart"/>' if cell.row() == r else "<w:vMerge/>")
            bg = cell.format().background()
            if bg.style() != Qt.NoBrush:
                tcpr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{bg.color().name()[1:].upper()}"/>')
            body = ""
            if cell.row() == r:
                it = cell.begin()
                while not it.atEnd():
                    child = it.currentFrame()
                    if child is not None:
                        inner = _as_table(o.doc, child)
                        body += _table(o, inner, default_family, content_px * sum(widths[c:c + span]) / max(1, total)) if inner else ""
                    elif it.currentBlock().isValid():
                        body += _paragraph(o, it.currentBlock(), default_family, in_cell=True)
                    it += 1
            out.append(f"<w:tc><w:tcPr>{''.join(tcpr)}</w:tcPr>{body or '<w:p/>'}</w:tc>")
            c += span
        out.append("</w:tr>")
    out.append("</w:tbl><w:p/>")      # Word wants a paragraph after a table
    return "".join(out)


def _band_xml(kind: str, text: str, number: str, title: str) -> str:
    """A header or footer part: its text (fields as Word fields) and the page number where it goes."""
    tag = "hdr" if kind == "header" else "ftr"
    style = "Header" if kind == "header" else "Footer"
    paras = []

    def with_fields(t: str, jc: str = "") -> str:
        runs = []
        for piece in re.split(r"(\{page\}|\{pages\}|\{title\}|\{date\})", t):
            if piece == "{page}":
                runs.append('<w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>')
            elif piece == "{pages}":
                runs.append('<w:fldSimple w:instr=" NUMPAGES "><w:r><w:t>1</w:t></w:r></w:fldSimple>')
            elif piece == "{date}":
                runs.append('<w:fldSimple w:instr=" DATE \\@ &quot;d MMMM yyyy&quot; "><w:r><w:t>date</w:t></w:r></w:fldSimple>')
            elif piece == "{title}":
                runs.append(f'<w:r><w:t xml:space="preserve">{escape(title)}</w:t></w:r>')
            elif piece:
                runs.append(f'<w:r><w:t xml:space="preserve">{escape(piece)}</w:t></w:r>')
        return f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{f"<w:jc w:val=\"{jc}\"/>" if jc else ""}</w:pPr>{"".join(runs)}</w:p>'
    if text:
        paras.append(with_fields(text))
    if number:
        paras.append(with_fields("{page}", "center" if number == "bottom-center" else "right"))
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:{tag} xmlns:w="{W}" xmlns:r="{R}">'
            f'{"".join(paras) or f"<w:p><w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr></w:p>"}</w:{tag}>')


def document_to_docx(doc: QTextDocument, setup: dict, path, title: str = "") -> None:
    """Write a QTextDocument and Writer's page setup as a .docx."""
    o = _Out(doc)
    family = doc.defaultFont().family() or "Inter"
    w_mm, h_mm = PAPERS_MM.get(setup.get("paper"), PAPERS_MM["a4"])
    if setup.get("landscape"):
        w_mm, h_mm = h_mm, w_mm
    tw = lambda mm: int(round(mm / 25.4 * 1440))        # noqa: E731
    top, right, bottom, left = setup.get("margins", [25.4] * 4)
    content_px = (w_mm - left - right) / 25.4 * 96
    body = _frame_body(o, doc.rootFrame(), family, content_px)
    parts = {}
    sect = []
    numbers = setup.get("numbers", "none")
    head_text, foot_text = setup.get("header", ""), setup.get("footer", "")
    if head_text or numbers == "top-right":
        parts["word/header1.xml"] = _band_xml("header", head_text, "top-right" if numbers == "top-right" else "", title)
        sect.append(f'<w:headerReference w:type="default" r:id="{o.rel(f"{REL}/header", "header1.xml")}"/>')
    if foot_text or numbers.startswith("bottom"):
        parts["word/footer1.xml"] = _band_xml("footer", foot_text, numbers if numbers.startswith("bottom") else "", title)
        sect.append(f'<w:footerReference w:type="default" r:id="{o.rel(f"{REL}/footer", "footer1.xml")}"/>')
    orient = ' w:orient="landscape"' if setup.get("landscape") else ""
    sect.append(f'<w:pgSz w:w="{tw(w_mm)}" w:h="{tw(h_mm)}"{orient}/>')
    sect.append(f'<w:pgMar w:top="{tw(top)}" w:right="{tw(right)}" w:bottom="{tw(bottom)}" w:left="{tw(left)}" w:header="{tw(max(5, top / 2))}" '
                f'w:footer="{tw(max(5, bottom / 2))}" w:gutter="0"/>')
    if not setup.get("firstPage", True) and sect[:1] and "Reference" in sect[0]:
        sect.append("<w:titlePg/>")
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:wp="{WP}" xmlns:a="{A}" xmlns:pic="{PIC}">'
                f'<w:body>{body}<w:sectPr>{"".join(sect)}</w:sectPr></w:body></w:document>')
    lang = "en-US"
    try:
        from PySide6.QtCore import QLocale
        lang = QLocale.system().name().replace("_", "-") or "en-US"
    except Exception:                                       # noqa: BLE001
        pass
    parts["word/document.xml"] = document
    parts["word/styles.xml"] = STYLES_XML % {"W": W, "font": _attr(family), "lang": _attr(lang)}
    parts["word/numbering.xml"] = _numbering_xml(o.next_num - 2)
    rels = [f'<Relationship Id="rId1" Type="{REL}/styles" Target="styles.xml"/>', f'<Relationship Id="rId2" Type="{REL}/numbering" Target="numbering.xml"/>']
    for rid, kind, target, external in o.rels:
        rels.append(f'<Relationship Id="{rid}" Type="{kind}" Target="{_attr(target)}"{" TargetMode=\"External\"" if external else ""}/>')
    parts["word/_rels/document.xml.rels"] = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG}">{"".join(rels)}</Relationships>'
    for name, data in o.media.items():
        parts[f"word/media/{name}"] = data
    overrides = ['<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>',
                 '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>',
                 '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>',
                 '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>']
    if "word/header1.xml" in parts:
        overrides.append('<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>')
    if "word/footer1.xml" in parts:
        overrides.append('<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>')
    parts["[Content_Types].xml"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                                    '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
                                    '<Default Extension="jpeg" ContentType="image/jpeg"/><Default Extension="gif" ContentType="image/gif"/>'
                                    + "".join(overrides) + "</Types>")
    parts["_rels/.rels"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG}">'
                            f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="word/document.xml"/>'
                            f'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>')
    parts["docProps/core.xml"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                                  'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + escape(title) + '</dc:title><dc:creator>Huginn Writer</dc:creator></cp:coreProperties>')
    tmp = Path(str(path) + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED if name.startswith("word/media/") else zipfile.ZIP_DEFLATED
            z.writestr(info, data if isinstance(data, bytes) else data.encode("utf-8"))
    tmp.replace(path)


# ================================================================================================ reading
def _part(z: zipfile.ZipFile, name: str):
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_PART:
        raise ConvertError("The file is too large to open safely.")
    data = z.read(info)
    if b"<!DOCTYPE" in data[:4096] or b"<!ENTITY" in data[:4096]:
        raise ConvertError("The file contains constructs that aren't allowed in office documents.")
    return ET.fromstring(data)


def _rels(z: zipfile.ZipFile, part: str) -> dict:
    folder, _, name = part.rpartition("/")
    root = _part(z, f"{folder}/_rels/{name}.rels" if folder else f"_rels/{name}.rels")
    out = {}
    for rel in root if root is not None else []:
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            out[rel.get("Id")] = (target, rel.get("Type", ""), True)
            continue
        pieces = (target.lstrip("/") if target.startswith("/") else f"{folder}/{target}").split("/")
        stack = []
        for piece in pieces:
            if piece == "..":
                if stack:
                    stack.pop()
            elif piece not in ("", "."):
                stack.append(piece)
        out[rel.get("Id")] = ("/".join(stack), rel.get("Type", ""), False)
    return out


def _val(el, tag: str, attr: str = "val"):
    x = el.find(_q(tag)) if el is not None else None
    return None if x is None else x.get(_q(attr))


def _on(el, tag: str) -> bool:
    x = el.find(_q(tag)) if el is not None else None
    return x is not None and x.get(_q("val"), "true") not in ("0", "false", "none")


def _plural(n: int, one: str, many: str = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def docx_to_html(path) -> tuple:
    """(html, setup, dropped): the document as HTML Qt reads (pictures inside), Writer's page setup, and a list of
    what didn't come across, in plain words."""
    with zipfile.ZipFile(path) if zipfile.is_zipfile(path) else _bad() as z:
        doc = _part(z, "word/document.xml")
        if doc is None:
            raise ConvertError("This doesn't look like a Word document.")
        styles = _part(z, "word/styles.xml")
        numbering = _part(z, "word/numbering.xml")
        rels = _rels(z, "word/document.xml")
        names = set(z.namelist())

        def media(target: str) -> str:
            if target not in names or z.getinfo(target).file_size > 40 * 1024 * 1024:
                return ""
            data = z.read(target)
            kind = "jpeg" if data[:3] == b"\xff\xd8\xff" else "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "gif" if data[:3] == b"GIF" else ""
            if not kind:
                return ""
            return f"data:image/{kind};base64," + base64.b64encode(data).decode()

        reader = _Reader(doc, styles, numbering, rels, media)
        body = doc.find(_q("body"))
        if body is None:
            raise ConvertError("The Word document has no text body.")
        markup = reader.body(body)
        setup, extra = reader.setup(body, z, names)
    return "<html><head><meta charset=\"utf-8\"/></head><body>" + markup + "</body></html>", setup, reader.dropped(doc, names) + extra


def _bad():
    raise ConvertError("This isn't a readable Word file.")


class _Reader:
    def __init__(self, doc, styles, numbering, rels, media):
        self.doc, self.rels, self.media = doc, rels, media
        self.style_kind = {}            # styleId -> title | h1 | h2 | h3 | quote | code | list
        self.style_rpr = {}             # styleId -> its run properties (font, size, bold...)
        self.style_based = {}
        self.pictures = self.anchored = 0
        self.after = 8                 # px after a paragraph when it doesn't say (Word's default, from the styles below)
        if styles is not None:
            dflt = styles.find(f"{_q('docDefaults')}/{_q('pPrDefault')}/{_q('pPr')}/{_q('spacing')}")
            normal = next((st for st in styles.findall(_q("style")) if st.get(_q("default")) == "1" and st.get(_q("type")) == "paragraph"), None)
            nsp = normal.find(f"{_q('pPr')}/{_q('spacing')}") if normal is not None else None
            for sp in (dflt, nsp):
                if sp is not None and (sp.get(_q("after")) or "").isdigit():
                    self.after = round(int(sp.get(_q("after"))) / TWIP_PX)
            for st in styles.findall(_q("style")):
                sid = st.get(_q("styleId")) or ""
                name = (_val(st, "name") or sid).lower().replace(" ", "")
                kind = ""
                if name == "title":
                    kind = "title"
                elif re.fullmatch(r"heading([1-9])", name):
                    kind = "h" + str(min(3, int(name[-1])))
                elif "quote" in name:
                    kind = "quote"
                elif "code" in name or name in ("htmlpreformatted", "plaintext", "macrotext"):
                    kind = "code"
                lvl = st.find(f"{_q('pPr')}/{_q('outlineLvl')}")
                if not kind and lvl is not None and (lvl.get(_q("val")) or "").isdigit() and int(lvl.get(_q("val"))) < 3:
                    kind = "h" + str(int(lvl.get(_q("val"))) + 1)
                self.style_kind[sid] = kind
                self.style_rpr[sid] = st.find(_q("rPr"))
                self.style_based[sid] = _val(st, "basedOn") or ""
        # numId -> {level: numbered?}
        self.num = {}
        if numbering is not None:
            abstract = {}
            for an in numbering.findall(_q("abstractNum")):
                levels = {}
                for lvl in an.findall(_q("lvl")):
                    fmt = _val(lvl, "numFmt") or "bullet"
                    levels[int(lvl.get(_q("ilvl"), "0"))] = (fmt != "bullet" and fmt != "none", fmt)
                abstract[an.get(_q("abstractNumId"))] = levels
            for n in numbering.findall(_q("num")):
                self.num[n.get(_q("numId"))] = abstract.get(_val(n, "abstractNumId"), {})

    def kind_of(self, sid: str) -> str:
        seen = 0
        while sid and seen < 10:
            k = self.style_kind.get(sid, "")
            if k:
                return k
            sid = self.style_based.get(sid, "")
            seen += 1
        return ""

    # ---- runs
    def run_css(self, rpr) -> tuple:
        css, wrap = [], []
        if rpr is None:
            return css, wrap
        fonts = rpr.find(_q("rFonts"))
        if fonts is not None:
            fam = fonts.get(_q("ascii")) or fonts.get(_q("hAnsi"))
            if fam:
                css.append(f"font-family:'{_attr(fam)}'")
        sz = _val(rpr, "sz")
        if sz and sz.isdigit():
            css.append(f"font-size:{int(sz) / 2:g}pt")
        col = _val(rpr, "color")
        if col and re.fullmatch(r"[0-9A-Fa-f]{6}", col):
            css.append(f"color:#{col}")
        hl = _val(rpr, "highlight")
        if hl in HIGHLIGHT:
            css.append(f"background-color:#{HIGHLIGHT[hl]}")
        shd = rpr.find(_q("shd"))
        if shd is not None and re.fullmatch(r"[0-9A-Fa-f]{6}", shd.get(_q("fill"), "")):
            css.append(f"background-color:#{shd.get(_q('fill'))}")
        if _on(rpr, "b"):
            css.append("font-weight:700")
        if _on(rpr, "i"):
            css.append("font-style:italic")
        deco = []
        u = _val(rpr, "u")
        if u and u != "none":
            deco.append("underline")
        if _on(rpr, "strike") or _on(rpr, "dstrike"):
            deco.append("line-through")
        if deco:
            css.append("text-decoration:" + " ".join(deco))
        va = _val(rpr, "vertAlign")
        if va in ("superscript", "subscript"):
            css.append("vertical-align:" + ("super" if va == "superscript" else "sub"))
        if _on(rpr, "caps"):
            wrap.append("caps")
        return css, wrap

    def runs(self, par) -> str:
        out = []
        for child in par:
            tag = child.tag
            if tag == _q("r"):
                out.append(self.run(child))
            elif tag == _q("hyperlink"):
                rid = child.get(_q("id", R))
                inner = "".join(self.run(r) for r in child.iter(_q("r")))
                target = self.rels.get(rid, ("", "", False))
                if target[2] and re.match(r"^(https?|mailto|ftp):", target[0]):
                    out.append(f'<a href="{_attr(target[0])}">{inner}</a>')
                else:
                    out.append(inner)
            elif tag in (_q("ins"), _q("smartTag"), _q("sdt"), _q("customXml"), _q("fldSimple")):
                content = child.find(_q("sdtContent")) if tag == _q("sdt") else child
                if content is not None:
                    out.append(self.runs(content))
        return "".join(out)

    def run(self, run) -> str:
        rpr = run.find(_q("rPr"))
        style_rpr = self.style_rpr.get(_val(rpr, "rStyle") or "") if rpr is not None else None
        css, wrap = self.run_css(style_rpr)
        css2, wrap2 = self.run_css(rpr)
        css += css2
        text = []
        for child in run:
            if child.tag == _q("t"):
                piece = html.escape(child.text or "")
                text.append(piece.upper() if "caps" in wrap + wrap2 else piece)
            elif child.tag == _q("tab"):
                text.append('<span style="white-space:pre">\t</span>')
            elif child.tag in (_q("br"), _q("cr")):
                if child.get(_q("type")) == "page":
                    text.append("\x0c")             # a page break inside a paragraph: split there (see body)
                else:
                    text.append("<br/>")
            elif child.tag == _q("drawing") or child.tag == _q("pict"):
                text.append(self.picture(child))
            elif child.tag == _q("sym"):
                text.append(html.escape(chr(int(child.get(_q("char"), "20"), 16)) if re.fullmatch(r"[0-9A-Fa-f]{1,4}", child.get(_q("char"), "")) else ""))
            elif child.tag == _q("noBreakHyphen"):
                text.append("‑")
        piece = "".join(text)
        if not piece:
            return ""
        return f'<span style="{";".join(css)}">{piece}</span>' if css else piece

    def picture(self, el) -> str:
        blip = next((b for b in el.iter(_q("blip", A))), None)
        if blip is None:
            return ""
        rid = blip.get(_q("embed", R))
        target = self.rels.get(rid, ("", "", True))
        if target[2]:
            return ""
        uri = self.media(target[0])
        if not uri:
            return ""
        self.pictures += 1
        if any(True for _ in el.iter(_q("anchor", WP))):
            self.anchored += 1
        ext = next((e for e in el.iter(_q("extent", WP))), None)
        size = ""
        if ext is not None and (ext.get("cx") or "").isdigit() and (ext.get("cy") or "").isdigit():
            size = f' width="{int(ext.get("cx")) / EMU_PX:.0f}" height="{int(ext.get("cy")) / EMU_PX:.0f}"'
        return f'<img src="{uri}"{size}/>'

    # ---- paragraphs
    def paragraph(self, par) -> tuple:
        """(list info or None, opening tag, inner html, closing tag, page break before?)"""
        ppr = par.find(_q("pPr"))
        sid = _val(ppr, "pStyle") or ""
        kind = self.kind_of(sid)
        css = []
        jc = _val(ppr, "jc")
        if jc in ("center", "right", "end", "both", "distribute"):
            css.append("text-align:" + {"center": "center", "right": "right", "end": "right", "both": "justify", "distribute": "justify"}[jc])
        sp = ppr.find(_q("spacing")) if ppr is not None else None
        numpr = ppr.find(_q("numPr")) if ppr is not None else None
        if kind not in ("title", "h1", "h2", "h3"):
            if sp is None or sp.get(_q("after")) is None:
                css.append(f"margin-bottom:{self.after if numpr is None else 2}px")
            if sp is None or sp.get(_q("before")) is None:
                css.append("margin-top:0px")
        if sp is not None:
            for a, prop in (("before", "margin-top"), ("after", "margin-bottom")):
                v = sp.get(_q(a))
                if v and v.lstrip("-").isdigit():
                    css.append(f"{prop}:{max(0, int(v)) / TWIP_PX:.0f}px")
            line, rule = sp.get(_q("line")), sp.get(_q("lineRule"), "auto")
            if line and line.isdigit() and rule == "auto" and abs(int(line) - 240) > 6 and kind not in ("title", "h1", "h2", "h3"):
                css.append(f"line-height:{int(line) / 240 * 100:.0f}%")
        ind = ppr.find(_q("ind")) if ppr is not None else None
        list_info = None
        if numpr is not None:
            nid, lvl = _val(numpr, "numId"), _val(numpr, "ilvl") or "0"
            if nid and nid != "0" and nid in self.num:
                lv = int(lvl) if lvl.isdigit() else 0
                numbered, fmt = self.num[nid].get(lv, (False, "bullet"))
                list_info = (nid, lv, numbered, fmt)
        if ind is not None and list_info is None and kind != "quote":
            left = ind.get(_q("left")) or ind.get(_q("start"))
            if left and left.lstrip("-").isdigit() and int(left) > 0:
                css.append(f"margin-left:{int(left) / TWIP_PX:.0f}px")
            first = ind.get(_q("firstLine"))
            if first and first.isdigit():
                css.append(f"text-indent:{int(first) / TWIP_PX:.0f}px")
        shd = ppr.find(_q("shd")) if ppr is not None else None
        if shd is not None and re.fullmatch(r"[0-9A-Fa-f]{6}", shd.get(_q("fill"), "")) and shd.get(_q("fill")).upper() != "FFFFFF":
            css.append(f"background-color:#{shd.get(_q('fill'))}")
        brk = _on(ppr, "pageBreakBefore")
        inner = self.runs(par)
        check = None
        plain = re.sub(r"<[^>]+>", "", inner)
        if plain[:2] in ("☐ ", "☒ ", "☑ "):     # a checklist item (Writer writes them so)
            check = plain[0] != "☐"
            inner = re.sub("(☐|☒|☑) ", "", inner, count=1)
        style = f' style="{";".join(css)}"' if css else ""
        if kind == "title":
            return list_info, f"<h1{style}>", inner, "</h1>", brk, check
        if kind in ("h1", "h2", "h3"):
            n = int(kind[1]) + 1
            return list_info, f"<h{n}{style}>", inner, f"</h{n}>", brk, check
        if kind == "quote":
            return list_info, f'<p style="margin-left:36px;margin-right:36px;font-style:italic;color:#4B5563{";" + ";".join(css) if css else ""}">', inner, "</p>", brk, check
        if kind == "code":
            return list_info, f'<pre style="background-color:{"#F1F3F5"}{";" + ";".join(css) if css else ""}">', inner, "</pre>", brk, check
        return list_info, f"<p{style}>", inner or "", "</p>", brk, check

    def body(self, body) -> str:
        out = []
        stack = []                 # open lists: (numId, level, tag)

        def close_to(level: int):
            while stack and stack[-1][1] >= level:
                out.append(f"</{stack.pop()[2]}>")

        for child in body:
            if child.tag == _q("p"):
                info, opening, inner, closing, brk, check = self.paragraph(child)
                pieces = inner.split("\x0c")
                for k, piece in enumerate(pieces):
                    page_break = brk if k == 0 else True
                    if info is None and check is None:
                        close_to(0)
                        tag = opening
                        if page_break:
                            tag = re.sub(r"^<(\w+)", r'<\1 style="page-break-before:always"', tag) if "style=" not in tag else tag.replace('style="', 'style="page-break-before:always;', 1)
                        out.append(f"{tag}{piece or ('<br/>' if opening.startswith('<p') else '')}{closing}")
                        continue
                    if info is None:                  # a checklist item without a Word list
                        info = ("check", 0, False, "bullet")
                    nid, lvl, numbered, fmt = info
                    tag = "ol" if numbered else "ul"
                    # close lists deeper than this item, or at its level but another list
                    while stack and (stack[-1][1] > lvl or (stack[-1][1] == lvl and (stack[-1][0] != nid or stack[-1][2] != tag))):
                        out.append(f"</{stack.pop()[2]}>")
                    # and open lists down to its level (one step at a time, inside the list above)
                    while not stack or stack[-1][1] < lvl:
                        depth = stack[-1][1] + 1 if stack else lvl
                        kind = ({"lowerLetter": "lower-alpha", "upperLetter": "upper-alpha", "lowerRoman": "lower-roman",
                                 "upperRoman": "upper-roman"}.get(fmt, "decimal") if numbered else ("disc", "circle", "square")[depth % 3])
                        out.append(f'<{tag} style="list-style-type:{kind}">')
                        stack.append((nid, depth, tag))
                    mark = "" if check is None else (' class="checked"' if check else ' class="unchecked"')
                    out.append(f"<li{mark}>{piece}</li>")
            elif child.tag == _q("tbl"):
                close_to(0)
                out.append(self.table(child))
            elif child.tag == _q("sdt"):
                content = child.find(_q("sdtContent"))
                if content is not None:
                    close_to(0)
                    out.append(self.body(content))
        close_to(0)
        return "".join(out)

    def table(self, tbl) -> str:
        grid = [int(g.get(_q("w"), "0") or 0) for g in tbl.findall(f"{_q('tblGrid')}/{_q('gridCol')}")]
        total = sum(grid) or 1
        rows = tbl.findall(_q("tr"))
        # work out the merged cells: rowspan from vMerge restart/continue
        layout = []
        for row in rows:
            cells, col = [], 0
            for tc in row.findall(_q("tc")):
                tcpr = tc.find(_q("tcPr"))
                span = int(_val(tcpr, "gridSpan") or 1) if (_val(tcpr, "gridSpan") or "1").isdigit() else 1
                vm = tcpr.find(_q("vMerge")) if tcpr is not None else None
                state = None if vm is None else (vm.get(_q("val")) or "continue")
                cells.append({"tc": tc, "col": col, "span": span, "vm": state, "rows": 1})
                col += span
            layout.append(cells)
        for r, cells in enumerate(layout):
            for cell in cells:
                if cell["vm"] == "restart":
                    rr = r + 1
                    while rr < len(layout):
                        below = next((c for c in layout[rr] if c["col"] == cell["col"]), None)
                        if below is None or below["vm"] != "continue":
                            break
                        cell["rows"] += 1
                        rr += 1
        borders = tbl.find(f"{_q('tblPr')}/{_q('tblBorders')}")
        styled = _val(tbl.find(_q("tblPr")), "tblStyle")
        bordered = borders is not None or (styled or "").lower() not in ("", "tablenormal")
        out = [f'<table border="{1 if bordered else 0}" cellspacing="0" cellpadding="6" width="100%" style="border-collapse:collapse;border-color:#9AA0A6">']
        for cells in layout:
            out.append("<tr>")
            for cell in cells:
                if cell["vm"] == "continue":
                    continue
                tcpr = cell["tc"].find(_q("tcPr"))
                attrs = ""
                if cell["span"] > 1:
                    attrs += f' colspan="{cell["span"]}"'
                if cell["rows"] > 1:
                    attrs += f' rowspan="{cell["rows"]}"'
                if grid:
                    attrs += f' width="{100 * sum(grid[cell["col"]:cell["col"] + cell["span"]]) / total:.0f}%"'
                shd = tcpr.find(_q("shd")) if tcpr is not None else None
                if shd is not None and re.fullmatch(r"[0-9A-Fa-f]{6}", shd.get(_q("fill"), "")):
                    attrs += f' bgcolor="#{shd.get(_q("fill"))}"'
                out.append(f"<td{attrs}>{self.body(cell['tc'])}</td>")
            out.append("</tr>")
        out.append("</table>")
        return "".join(out)

    # ---- the page and what didn't come across
    def setup(self, body, z, names) -> tuple:
        setup = {"paper": "a4", "landscape": False, "margins": [25.4] * 4, "header": "", "footer": "", "numbers": "none", "firstPage": True}
        extra = []
        sects = list(body.iter(_q("sectPr")))
        sect = body.find(_q("sectPr")) or (sects[-1] if sects else None)
        if len(sects) > 1:
            extra.append(f"{len(sects)} sections (the whole document takes the last one's page setup)")
        if sect is None:
            return setup, extra
        pg = sect.find(_q("pgSz"))
        if pg is not None and (pg.get(_q("w")) or "").isdigit() and (pg.get(_q("h")) or "").isdigit():
            w, h = int(pg.get(_q("w"))) / 1440 * 25.4, int(pg.get(_q("h"))) / 1440 * 25.4
            landscape = w > h
            a, b = (h, w) if landscape else (w, h)
            best = min(PAPERS_MM, key=lambda k: abs(PAPERS_MM[k][0] - a) + abs(PAPERS_MM[k][1] - b))
            if abs(PAPERS_MM[best][0] - a) + abs(PAPERS_MM[best][1] - b) > 8:
                extra.append(f"its paper size ({a:.0f} × {b:.0f} mm; {best.upper() if best.startswith('a') else best.title()} is used)")
            setup["paper"], setup["landscape"] = best, landscape
        mar = sect.find(_q("pgMar"))
        if mar is not None:
            vals = []
            for k in ("top", "right", "bottom", "left"):
                v = mar.get(_q(k)) or "1440"
                vals.append(abs(int(v)) / 1440 * 25.4 if v.lstrip("-").isdigit() else 25.4)
            setup["margins"] = [round(max(5.0, min(80.0, v)), 2) for v in vals]
        setup["firstPage"] = sect.find(_q("titlePg")) is None
        cols = sect.find(_q("cols"))
        if cols is not None and (cols.get(_q("num")) or "1").isdigit() and int(cols.get(_q("num")) or 1) > 1:
            extra.append("text in columns (shown as one column)")
        for kind in ("header", "footer"):
            ref = next((r for r in sect.findall(_q(f"{kind}Reference")) if r.get(_q("type")) in (None, "default")), None)
            if ref is None:
                continue
            target = self.rels.get(ref.get(_q("id", R)), ("", "", True))
            part = _part(z, target[0]) if not target[2] else None
            if part is None:
                continue
            text, number = _band_text(part)
            setup[kind] = text
            if number:
                setup["numbers"] = ("top-right" if kind == "header" else number)
        return setup, extra

    def dropped(self, doc, names) -> list:
        count = lambda tag, ns=W: sum(1 for _ in doc.iter(_q(tag, ns)))      # noqa: E731
        out = []
        if count("ins") or count("del"):
            out.append("tracked changes (shown as if all were accepted)")
        if count("commentReference"):
            out.append(_plural(count("commentReference"), "comment"))
        if count("footnoteReference") or count("endnoteReference"):
            out.append("footnotes and endnotes")
        if any(el.tag.endswith("}oMath") for el in doc.iter()):
            out.append("equations")
        shapes = sum(1 for el in doc.iter() if el.tag.endswith("}wsp") or el.tag.endswith("}txbx"))
        if shapes:
            out.append(_plural(shapes, "shape or text box", "shapes and text boxes"))
        charts = sum(1 for el in doc.iter() if el.tag.endswith("}chart") or el.tag.endswith("}relIds"))
        if charts:
            out.append(_plural(charts, "chart or diagram", "charts and diagrams"))
        if self.anchored:
            out.append(_plural(self.anchored, "picture placed beside the text", "pictures placed beside the text") + " (kept in line with it)")
        return out


def _band_text(part) -> tuple:
    """A header or footer part as Writer's text (fields as {page}, {pages}, {date}), and where a lone page number sits."""
    paras = []
    number = ""
    for p in part.iter(_q("p")):
        bits, in_field, instr = [], False, ""
        shown = {id(t) for f in p.iter(_q("fldSimple")) for t in f.iter(_q("t"))}     # what a simple field shows
        for el in p.iter():
            if id(el) in shown:
                continue
            if el.tag == _q("fldSimple"):
                code = (el.get(_q("instr")) or "").strip().split(" ")[0].upper()
                bits.append({"PAGE": "{page}", "NUMPAGES": "{pages}", "DATE": "{date}", "TIME": "{date}"}.get(code, ""))
            elif el.tag == _q("fldChar"):
                t = el.get(_q("fldCharType"))
                if t == "begin":
                    in_field, instr = True, ""
                elif t == "separate":
                    code = instr.strip().split(" ")[0].upper() if instr.strip() else ""
                    bits.append({"PAGE": "{page}", "NUMPAGES": "{pages}", "DATE": "{date}"}.get(code, ""))
                elif t == "end":
                    in_field = False
            elif el.tag == _q("instrText"):
                instr += el.text or ""
            elif el.tag == _q("t") and not in_field:
                bits.append(el.text or "")
            elif el.tag == _q("tab"):
                bits.append("  ")
        text = "".join(bits).strip()
        if not text:
            continue
        jc = _val(p.find(_q("pPr")), "jc")
        if text == "{page}" or re.fullmatch(r"(Page\s*)?\{page\}(\s*(of|/)\s*\{pages\})?", text):
            number = "bottom-right" if jc in ("right", "end") else "bottom-center"
            if text != "{page}":
                paras.append(text)
                number = ""
            continue
        paras.append(text)
    return "  ".join(paras)[:300], number
