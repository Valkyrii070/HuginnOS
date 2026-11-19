"""Excel workbooks (.xlsx) in and out for Huginn Sheets, with Python's standard library.

Out: every sheet with its formulas (and their results, so other apps show them before working anything out), text,
numbers, dates and true/false; bold, italic, underline, strike, colours, fills, alignment, wrapping, font and size;
number formats; column widths and row heights; frozen panes; the filter; and charts (column, bar, line, area and pie,
drawn by Excel from the cells, with their numbers kept in the file too).

Lists to pick from and other limits on what cells take (dataValidations), and notes on cells (comments, with the
VML drawing Excel needs to show them), both ways.

In: the same, plus shared formulas (worked out for each cell), and a plain-language list of what didn't come across.
"""
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import huginn_sheet_engine as se

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
MAX_PART = 96 * 1024 * 1024
NEWER = {"XLOOKUP", "XMATCH", "IFS", "SWITCH", "TEXTJOIN", "CONCAT", "MAXIFS", "MINIFS", "IFNA", "UNIQUE", "SORT", "FILTER", "STDEV.S", "STDEV.P",
         "VAR.S", "VAR.P", "MODE.SNGL", "PERCENTILE.INC", "QUARTILE.INC", "RANK.EQ", "CEILING.MATH", "FLOOR.MATH", "DAYS", "ISOWEEKNUM",
         "UNICHAR", "UNICODE", "NUMBERVALUE", "XOR"}
BUILTIN_FMT = {0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%", 11: "0.00E+00", 12: "General", 14: "short-date",
               15: "d mmm yyyy", 16: "d mmm yyyy", 17: "d mmm yyyy", 18: "h:mm AM/PM", 19: "h:mm AM/PM", 20: "hh:mm", 21: "hh:mm:ss",
               22: "yyyy-mm-dd hh:mm", 37: "#,##0", 38: "#,##0", 39: "#,##0.00", 40: "#,##0.00", 45: "hh:mm", 46: "hh:mm:ss", 47: "hh:mm:ss", 49: "@"}
OUT_FMT = {"General": 0, "0": 1, "0.00": 2, "#,##0": 3, "#,##0.00": 4, "0%": 9, "0.00%": 10, "0.00E+00": 11, "short-date": 14, "hh:mm": 20,
           "hh:mm:ss": 21, "@": 49}
CHART_KINDS = {"column": ("barChart", "col"), "bar": ("barChart", "bar"), "line": ("lineChart", ""), "area": ("areaChart", ""), "pie": ("pieChart", "")}


class ConvertError(Exception):
    pass


def _q(tag, ns=S):
    return f"{{{ns}}}{tag}"


def _attr(v) -> str:
    return escape(str(v), {'"': "&quot;"})


# ================================================================================================ writing
def _excel_code(code: str) -> str:
    """Our format code as Excel writes it (currency symbols in quotes)."""
    return re.sub(r"([$€£¥])", r'"\1"', code) if any(ch in code for ch in "$€£¥") else code


def _style_key(f: dict):
    return (bool(f.get("b")), bool(f.get("i")), bool(f.get("u")), bool(f.get("s")), f.get("color", ""), f.get("size", ""), f.get("font", ""),
            f.get("fill", ""), f.get("align", ""), bool(f.get("wrap")), f.get("num", "General"))


class _Styles:
    def __init__(self):
        self.fonts = [("", "", "", "", "", "", "")]            # b i u s color size font
        self.fills = ["", "gray125"]
        self.numfmts = {}                                      # code -> id (164+)
        self.xfs = [None]
        self.index = {}
        self.dxfs = []                                         # (fill, color, bold): conditional formatting's looks

    def xf(self, f: dict) -> int:
        if not f:
            return 0
        key = _style_key(f)
        if key in self.index:
            return self.index[key]
        b, i, u, s, color, size, font, fill, align, wrap, num = key
        fk = (b, i, u, s, color, size, font)
        if fk not in self.fonts:
            self.fonts.append(fk)
        fill_id = 0
        if fill:
            if fill not in self.fills:
                self.fills.append(fill)
            fill_id = self.fills.index(fill)
        if num in OUT_FMT:
            num_id = OUT_FMT[num]
        else:
            code = {"yyyy-mm-dd": "yyyy\\-mm\\-dd", "d mmm yyyy": "d\\ mmm\\ yyyy", "yyyy-mm-dd hh:mm": "yyyy\\-mm\\-dd\\ hh:mm"}.get(num) or _excel_code(num)
            if code not in self.numfmts:
                self.numfmts[code] = 164 + len(self.numfmts)
            num_id = self.numfmts[code]
        self.xfs.append((self.fonts.index(fk), fill_id, num_id, align, wrap))
        self.index[key] = len(self.xfs) - 1
        return self.index[key]

    def dxf(self, look: dict) -> int:
        key = (look.get("fill", ""), look.get("color", ""), bool(look.get("b")))
        if key not in self.dxfs:
            self.dxfs.append(key)
        return self.dxfs.index(key)

    def xml(self) -> str:
        nf = "".join(f'<numFmt numFmtId="{i}" formatCode="{_attr(code)}"/>' for code, i in self.numfmts.items())
        fonts = []
        for b, i, u, s, color, size, font in self.fonts:
            fonts.append("<font>" + ("<b/>" if b else "") + ("<i/>" if i else "") + ("<strike/>" if s else "") + ('<u/>' if u else "")
                         + f'<sz val="{size or 11}"/>' + (f'<color rgb="FF{color.lstrip("#").upper()}"/>' if color else '<color theme="1"/>')
                         + f'<name val="{_attr(font or "Calibri")}"/><family val="2"/></font>')
        fills = ['<fill><patternFill patternType="none"/></fill>', '<fill><patternFill patternType="gray125"/></fill>']
        for fl in self.fills[2:]:
            fills.append(f'<fill><patternFill patternType="solid"><fgColor rgb="FF{fl.lstrip("#").upper()}"/><bgColor indexed="64"/></patternFill></fill>')
        xfs = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>']
        for font_id, fill_id, num_id, align, wrap in self.xfs[1:]:
            al = ""
            if align or wrap:
                al = "<alignment" + (f' horizontal="{align}"' if align else "") + (' wrapText="1"' if wrap else "") + "/>"
            xfs.append(f'<xf numFmtId="{num_id}" fontId="{font_id}" fillId="{fill_id}" borderId="0" xfId="0"'
                       + (' applyNumberFormat="1"' if num_id else "") + (' applyFont="1"' if font_id else "") + (' applyFill="1"' if fill_id else "")
                       + (' applyAlignment="1">' + al + "</xf>" if al else "/>"))
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="{S}">'
                + (f'<numFmts count="{len(self.numfmts)}">{nf}</numFmts>' if nf else "")
                + f'<fonts count="{len(fonts)}">{"".join(fonts)}</fonts><fills count="{len(fills)}">{"".join(fills)}</fills>'
                + '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                + f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
                + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                + (f'<dxfs count="{len(self.dxfs)}">' + "".join(
                    "<dxf>" + ("<font>" + ("<b/>" if b else "") + (f'<color rgb="FF{color.lstrip("#").upper()}"/>' if color else "") + "</font>" if b or color else "")
                    + (f'<fill><patternFill><bgColor rgb="FF{fill.lstrip("#").upper()}"/></patternFill></fill>' if fill else "") + "</dxf>"
                    for fill, color, b in self.dxfs) + "</dxfs>" if self.dxfs else "")
                + '</styleSheet>')


CF_OPS = {"gt": "greaterThan", "ge": "greaterThanOrEqual", "lt": "lessThan", "le": "lessThanOrEqual", "eq": "equal", "ne": "notEqual", "between": "between"}


def _cf_value(text: str) -> str:
    """A rule's value as a formula Excel reads: a number as it is, anything else as text in quotes."""
    v, _ = se.literal(text)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return se.general(float(v))
    return '"' + str(text).replace('"', '""') + '"'


def _cf_xml(rules: list, styles) -> str:
    """Sheets' highlight rules (huginn_sheet_rules) as Excel's conditionalFormatting, in their order."""
    import huginn_sheet_rules as hr
    out = []
    for k, rule in enumerate(rules):
        r0, c0, r1, c1 = rule["range"]
        ref = se.ref_name(r0, c0) + (f":{se.ref_name(r1, c1)}" if (r1, c1) != (r0, c0) else "")
        first = se.ref_name(r0, c0)
        kind, pri = rule["kind"], k + 1
        dxf = f' dxfId="{styles.dxf(hr.look_of(rule))}"' if kind not in ("scale", "bar") else ""
        if kind in CF_OPS:
            body = "".join(f"<formula>{escape(_cf_value(rule.get(x, '')))}</formula>" for x in (("a", "b") if kind == "between" else ("a",)))
            cf = f'<cfRule type="cellIs"{dxf} priority="{pri}" operator="{CF_OPS[kind]}">{body}</cfRule>'
        elif kind == "text":
            t = rule.get("a", "")
            cf = (f'<cfRule type="containsText"{dxf} priority="{pri}" operator="containsText" text="{_attr(t)}">'
                  f'<formula>{escape(f"NOT(ISERROR(SEARCH({_cf_value(t)},{first})))")}</formula></cfRule>')
        elif kind == "starts":
            t = rule.get("a", "")
            cf = (f'<cfRule type="beginsWith"{dxf} priority="{pri}" operator="beginsWith" text="{_attr(t)}">'
                  f'<formula>{escape(f"LEFT({first},LEN({_cf_value(t)}))={_cf_value(t)}")}</formula></cfRule>')
        elif kind in ("dup", "unique"):
            cf = f'<cfRule type="{"duplicateValues" if kind == "dup" else "uniqueValues"}"{dxf} priority="{pri}"/>'
        elif kind in ("top", "bottom"):
            cf = f'<cfRule type="top10"{dxf} priority="{pri}" rank="{rule.get("n", 10)}"{" bottom=\"1\"" if kind == "bottom" else ""}/>'
        elif kind in ("above", "below"):
            cf = f'<cfRule type="aboveAverage"{dxf} priority="{pri}"{" aboveAverage=\"0\"" if kind == "below" else ""}/>'
        elif kind in ("blank", "notblank"):
            cf = (f'<cfRule type="{"containsBlanks" if kind == "blank" else "notContainsBlanks"}"{dxf} priority="{pri}">'
                  f'<formula>{escape(f"LEN(TRIM({first})){"=" if kind == "blank" else ">"}0")}</formula></cfRule>')
        elif kind == "error":
            cf = f'<cfRule type="containsErrors"{dxf} priority="{pri}"><formula>ISERROR({first})</formula></cfRule>'
        elif kind == "scale":
            stops = [rule["low"]] + ([rule["mid"]] if rule.get("mid") else []) + [rule["high"]]
            cfvo = '<cfvo type="min"/>' + ('<cfvo type="percentile" val="50"/>' if rule.get("mid") else "") + '<cfvo type="max"/>'
            cf = f'<cfRule type="colorScale" priority="{pri}"><colorScale>{cfvo}' + "".join(f'<color rgb="FF{c.lstrip("#")}"/>' for c in stops) + "</colorScale></cfRule>"
        elif kind == "bar":
            cf = f'<cfRule type="dataBar" priority="{pri}"><dataBar><cfvo type="min"/><cfvo type="max"/><color rgb="FF{rule["color"].lstrip("#")}"/></dataBar></cfRule>'
        else:
            continue
        out.append(f'<conditionalFormatting sqref="{ref}">{cf}</conditionalFormatting>')
    return "".join(out)


def _read_dxfs(root) -> list:
    """Excel's looks for conditional formatting: [{fill, ink, bold}]."""
    out = []
    dx = root.find(_q("dxfs")) if root is not None else None
    for d in (dx if dx is not None else []):
        look = {}
        font = d.find(_q("font"))
        if font is not None:
            if font.find(_q("b")) is not None and font.find(_q("b")).get("val", "1") not in ("0", "false"):
                look["bold"] = True
            col = font.find(_q("color"))
            if col is not None and re.fullmatch(r"[0-9A-Fa-f]{8}", col.get("rgb", "")):
                look["ink"] = "#" + col.get("rgb")[2:].upper()
        bg = d.find(f"{_q('fill')}/{_q('patternFill')}/{_q('bgColor')}")
        if bg is None:
            bg = d.find(f"{_q('fill')}/{_q('patternFill')}/{_q('fgColor')}")
        if bg is not None and re.fullmatch(r"[0-9A-Fa-f]{8}", bg.get("rgb", "")):
            look["fill"] = "#" + bg.get("rgb")[2:].upper()
        out.append(look)
    return out


def _read_cf(root, dxfs: list) -> tuple:
    """Excel's conditional formatting as Sheets' rules, in priority order; and how many couldn't come across."""
    import huginn_sheet_rules as hr
    back = {v: k for k, v in CF_OPS.items()}
    found, skipped = [], 0
    for cfe in root.iter(_q("conditionalFormatting")):
        spans = []
        for part in (cfe.get("sqref") or "").split():
            a, _, b = part.partition(":")
            p, q = se.parse_cell(a), se.parse_cell(b or a)
            if p and q:
                spans.append([p[0], p[1], q[0], q[1]])
        for rule in cfe.findall(_q("cfRule")):
            t, op = rule.get("type", ""), rule.get("operator", "")
            formulas = [(f.text or "").strip() for f in rule.findall(_q("formula"))]

            def value(text):
                text = text or ""
                return text[1:-1].replace('""', '"') if len(text) >= 2 and text[0] == text[-1] == '"' else text
            want = {}
            if t == "cellIs" and op in back:
                want = {"kind": back[op], "a": value(formulas[0] if formulas else ""), "b": value(formulas[1] if len(formulas) > 1 else "")}
                if want["kind"] == "between" and not want["b"]:
                    want = {}
            elif t == "containsText" or (t == "beginsWith"):
                want = {"kind": "text" if t == "containsText" else "starts", "a": rule.get("text", "")}
            elif t in ("duplicateValues", "uniqueValues"):
                want = {"kind": "dup" if t == "duplicateValues" else "unique"}
            elif t == "top10" and rule.get("percent") not in ("1", "true"):
                want = {"kind": "bottom" if rule.get("bottom") in ("1", "true") else "top", "n": int(rule.get("rank", "10") or 10)}
            elif t == "aboveAverage" and rule.get("equalAverage") not in ("1", "true") and not rule.get("stdDev"):
                want = {"kind": "below" if rule.get("aboveAverage") in ("0", "false") else "above"}
            elif t in ("containsBlanks", "notContainsBlanks", "containsErrors"):
                want = {"kind": {"containsBlanks": "blank", "notContainsBlanks": "notblank", "containsErrors": "error"}[t]}
            elif t == "colorScale":
                cols = [c.get("rgb", "") for c in rule.iter(_q("color"))]
                cols = ["#" + c[2:].upper() for c in cols if re.fullmatch(r"[0-9A-Fa-f]{8}", c)]
                if len(cols) in (2, 3):
                    want = {"kind": "scale", "low": cols[0], "high": cols[-1], **({"mid": cols[1]} if len(cols) == 3 else {})}
            elif t == "dataBar":
                col = next((c.get("rgb", "") for c in rule.iter(_q("color"))), "")
                want = {"kind": "bar", "color": "#" + col[2:].upper() if re.fullmatch(r"[0-9A-Fa-f]{8}", col) else "#638EC6"}
            if not want or not spans:
                skipped += 1
                continue
            dxf_id = rule.get("dxfId")
            look = dxfs[int(dxf_id)] if dxf_id and dxf_id.isdigit() and int(dxf_id) < len(dxfs) else {}
            pri = int(rule.get("priority", "999") or 999)
            for span in spans:
                made = hr.clean_rule({"id": "", "range": span, **want, **look})
                if made:
                    found.append((pri, made))
    found.sort(key=lambda x: x[0])
    rules = []
    for k, (_, r) in enumerate(found):
        r["id"] = f"c{k + 1}"
        rules.append(r)
    return rules, skipped


def _dv_xml(checks: list, day_first: bool) -> str:
    """Sheets' checks (huginn_sheet_checks) as Excel's dataValidations."""
    out = []
    for x in checks:
        r0, c0, r1, c1 = x["range"]
        ref = se.ref_name(r0, c0) + ("" if (r0, c0) == (r1, c1) else ":" + se.ref_name(r1, c1))
        stop = ' errorStyle="stop"' if x["stop"] else ' errorStyle="warning"'
        say = f' error="{_attr(x["say"])}"' if x.get("say") else ""
        if x["kind"] == "list":
            if x["source"]:
                f1 = escape(x["source"] if x["source"].startswith(("$", "'")) or "!" in x["source"] else re.sub(r"([A-Za-z]+)(\d+)", r"$\1$\2", x["source"]))
            else:
                f1 = escape('"' + ",".join(i.replace('"', '""') for i in x["items"]) + '"')
            out.append(f'<dataValidation type="list" allowBlank="1" showInputMessage="1" showErrorMessage="1"{stop}{say} sqref="{ref}"><formula1>{f1}</formula1></dataValidation>')
            continue
        kind = {"length": "textLength"}.get(x["kind"], x["kind"])

        def value(t):
            v, _ = se.literal(t, day_first)
            return se.general(float(v)) if isinstance(v, (int, float)) and not isinstance(v, bool) else '"' + t.replace('"', '""') + '"'
        f = f"<formula1>{escape(value(x['a']))}</formula1>" if x["a"] else ""
        if x["op"] in ("between", "notBetween"):
            f += f"<formula2>{escape(value(x['b']))}</formula2>" if x["b"] else ""
        op = f' operator="{x["op"]}"' if x["op"] != "between" else ""
        out.append(f'<dataValidation type="{kind}"{op} allowBlank="1" showInputMessage="1" showErrorMessage="1"{stop}{say} sqref="{ref}">{f}</dataValidation>')
    return f'<dataValidations count="{len(out)}">' + "".join(out) + "</dataValidations>" if out else ""


def _read_dv(root, day_first: bool) -> tuple:
    """Excel's dataValidations as Sheets' checks, and how many couldn't come across (custom formulas)."""
    import huginn_sheet_checks as hc
    out, skipped = [], 0
    for k, dv in enumerate(root.iter(_q("dataValidation"))):
        kind = {"textLength": "length"}.get(dv.get("type", ""), dv.get("type", ""))
        if kind not in hc.KINDS:
            skipped += 1
            continue
        f1 = (dv.findtext(_q("formula1")) or "").strip()
        f2 = (dv.findtext(_q("formula2")) or "").strip()
        if not f1:            # (newer Excel keeps some in x14 extensions: the formula sits in xm:f)
            f1 = next((e.text or "" for e in dv.iter() if e.tag.endswith("}f")), "").strip()

        def plain(t):
            if t.startswith('"') and t.endswith('"'):
                return t[1:-1].replace('""', '"')
            if kind == "date" and re.fullmatch(r"-?\d+(\.\d+)?", t):
                return se.to_date(float(t)).strftime("%Y-%m-%d")
            return t
        items, source = [], ""
        if kind == "list":
            if f1.startswith('"'):
                items = [i.strip() for i in plain(f1).split(",") if i.strip()]
            elif re.fullmatch(r"(('[^']+'|[\w.]+)!)?\$?[A-Za-z]{1,3}\$?\d+(:\$?[A-Za-z]{1,3}\$?\d+)?", f1):
                source = f1.replace("$", "")
            else:
                skipped += 1               # a named range or a formula
                continue
        for ref in (dv.get("sqref") or "").split():
            a, _, b = ref.partition(":")
            p, q = se.parse_cell(a), se.parse_cell(b or a)
            if not p or not q:
                continue
            chk = hc.clean_check({"id": f"v{k + 1}" + ("" if len(out) == 0 else chr(97 + len(out) % 26)), "range": [p[0], p[1], q[0], q[1]], "kind": kind,
                                  "items": items, "source": source, "op": dv.get("operator") or "between", "a": plain(f1) if kind != "list" else "",
                                  "b": plain(f2) if kind != "list" else "", "stop": dv.get("errorStyle", "stop") == "stop", "say": dv.get("error") or ""})
            if chk:
                out.append(chk)
    return out, skipped


def _comments_parts(notes: dict, n: int) -> tuple:
    """(comments xml, vml drawing) for a sheet's notes: Excel shows notes through the VML shapes."""
    authors = sorted({x.get("by") or "Huginn Sheets" for x in notes.values()})
    rows, shapes = [], []
    for k, ((r, c), x) in enumerate(sorted(notes.items())):
        who = x.get("by") or "Huginn Sheets"
        rows.append(f'<comment ref="{se.ref_name(r, c)}" authorId="{authors.index(who)}"><text><r><rPr><b/><sz val="9"/></rPr><t xml:space="preserve">{escape(who)}:</t></r>'
                    f'<r><rPr><sz val="9"/></rPr><t xml:space="preserve">\n{escape(x["text"])}</t></r></text></comment>')
        shapes.append(f'<v:shape id="_x0000_s{1025 + k}" type="#_x0000_t202" style="position:absolute;margin-left:59.25pt;margin-top:1.5pt;width:108pt;height:59.25pt;z-index:{k + 1};visibility:hidden" '
                      f'fillcolor="#ffffe1" o:insetmode="auto"><v:fill color2="#ffffe1"/><v:shadow on="t" color="black" obscured="t"/><v:path o:connecttype="none"/>'
                      f'<v:textbox style="mso-direction-alt:auto"><div style="text-align:left"></div></v:textbox><x:ClientData ObjectType="Note"><x:MoveWithCells/><x:SizeWithCells/>'
                      f'<x:Anchor>{c + 1}, 15, {r}, 2, {c + 3}, 15, {r + 4}, 4</x:Anchor><x:AutoFill>False</x:AutoFill><x:Row>{r}</x:Row><x:Column>{c}</x:Column></x:ClientData></v:shape>')
    comments = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><comments xmlns="{S}"><authors>' + "".join(f"<author>{escape(a)}</author>" for a in authors)
                + "</authors><commentList>" + "".join(rows) + "</commentList></comments>")
    vml = ('<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel">'
           f'<o:shapelayout v:ext="edit"><o:idmap v:ext="edit" data="{n}"/></o:shapelayout>'
           '<v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202" path="m,l,21600r21600,l21600,xe"><v:stroke joinstyle="miter"/>'
           '<v:path gradientshapeok="t" o:connecttype="rect"/></v:shapetype>' + "".join(shapes) + "</xml>")
    return comments, vml


def _read_comments(root) -> dict:
    """Excel's comments on cells as Sheets' notes (the author's name, which Excel also puts at the start, left out)."""
    if root is None:
        return {}
    authors = [a.text or "" for a in root.iter(_q("author"))]
    out = {}
    for cm in root.iter(_q("comment")):
        p = se.parse_cell(cm.get("ref") or "")
        if not p:
            continue
        text = "".join(t.text or "" for t in cm.iter(_q("t")))
        try:
            who = authors[int(cm.get("authorId", "0"))]
        except (ValueError, IndexError):
            who = ""
        if who and text.startswith(who + ":"):
            text = text[len(who) + 1:]
        text = text.strip()
        if text:
            out[p] = {"text": text, "by": who.split(":")[0].strip(), "when": 0}
    return out


def _formula_out(src: str) -> str:
    body = src[1:]
    try:
        toks = se.tokens(body)
    except se.Err:
        return body
    out, last = [], 0
    for kind, val, a, b in toks:
        if kind == "func" and val.upper() in NEWER:
            out.append(body[last:a] + "_xlfn." + val.upper())
            last = b
    out.append(body[last:])
    return "".join(out)


def _px_to_width(px: float) -> float:
    return round(max(0.0, (px - 5) / 7), 2)


def _anchor(sheet: dict, x: float, y: float):
    """The cell a point (in pixels from the sheet's top left) is in, with the offset inside it (EMU)."""
    col, acc = 0, 0.0
    while True:
        w = float(sheet["widths"].get(col, 100))
        if acc + w > x or col > 16000:
            break
        acc += w
        col += 1
    row, accy = 0, 0.0
    while True:
        h = float(sheet["heights"].get(row, 26))
        if accy + h > y or row > 1000000:
            break
        accy += h
        row += 1
    return col, int((x - acc) * 9525), row, int((y - accy) * 9525)


def _chart_xml(book, s: int, ch: dict, sheet_name: str) -> str:
    from huginn_sheets import chart_series, parse_span
    data = chart_series(book, s, ch)
    r0, c0, r1, c1 = parse_span(ch["range"])
    tag, direction = CHART_KINDS.get(ch.get("kind"), CHART_KINDS["column"])
    qs = se.quote_sheet(sheet_name)
    vals = [[book.value(s, r, c) for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]
    isnum = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)     # noqa: E731
    head_row = any(isinstance(v, str) for v in vals[0][1:] or vals[0]) and len(vals) > 1
    head_col = all(not isnum(row[0]) for row in vals[1 if head_row else 0:]) and len(vals[0]) > 1
    rs = r0 + (1 if head_row else 0)
    first = c0 + (1 if head_col else 0)
    sers = []
    for k, serie in enumerate(data.get("series", [])):
        col = first + k
        name = f'<c:tx><c:strRef><c:f>{qs}!${se.col_name(col)}${r0 + 1}</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>{escape(serie["name"])}</c:v></c:pt></c:strCache></c:strRef></c:tx>' if head_row else ""
        cat = ""
        if head_col:
            pts = "".join(f'<c:pt idx="{i}"><c:v>{escape(lab)}</c:v></c:pt>' for i, lab in enumerate(data["labels"]))
            cat = f'<c:cat><c:strRef><c:f>{qs}!${se.col_name(c0)}${rs + 1}:${se.col_name(c0)}${r1 + 1}</c:f><c:strCache><c:ptCount val="{len(data["labels"])}"/>{pts}</c:strCache></c:strRef></c:cat>'
        pts = "".join(f'<c:pt idx="{i}"><c:v>{v!r}</c:v></c:pt>' for i, v in enumerate(serie["values"]))
        val = f'<c:val><c:numRef><c:f>{qs}!${se.col_name(col)}${rs + 1}:${se.col_name(col)}${r1 + 1}</c:f><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="{len(serie["values"])}"/>{pts}</c:numCache></c:numRef></c:val>'
        colour = serie["colour"].lstrip("#")
        sppr = (f'<c:spPr><a:solidFill><a:srgbClr val="{colour}"/></a:solidFill></c:spPr>' if tag != "lineChart"
                else f'<c:spPr><a:ln w="28575"><a:solidFill><a:srgbClr val="{colour}"/></a:solidFill></a:ln></c:spPr><c:marker><c:symbol val="none"/></c:marker>')
        if tag == "pieChart":
            sppr = ""
        sers.append(f'<c:ser><c:idx val="{k}"/><c:order val="{k}"/>{name}{sppr}{cat}{val}' + ('<c:smooth val="0"/>' if tag == "lineChart" else "") + "</c:ser>")
        if tag == "pieChart":
            break
    axes = '<c:axId val="1001"/><c:axId val="1002"/>' if tag != "pieChart" else ""
    head = (f'<c:barDir val="{direction}"/><c:grouping val="clustered"/>' if tag == "barChart" else '<c:grouping val="standard"/>' if tag in ("lineChart", "areaChart") else "")
    body = f'<c:{tag}>{head}<c:varyColors val="{1 if tag == "pieChart" else 0}"/>{"".join(sers)}' + ('<c:gapWidth val="80"/>' if tag == "barChart" else "") + f"{axes}</c:{tag}>"
    if tag != "pieChart":
        body += ('<c:catAx><c:axId val="1001"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="' + ("l" if direction == "bar" else "b")
                 + '"/><c:numFmt formatCode="General" sourceLinked="1"/><c:tickLblPos val="nextTo"/><c:crossAx val="1002"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/></c:catAx>'
                 '<c:valAx><c:axId val="1002"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="' + ("b" if direction == "bar" else "l")
                 + '"/><c:majorGridlines/><c:numFmt formatCode="General" sourceLinked="1"/><c:tickLblPos val="nextTo"/><c:crossAx val="1001"/><c:crosses val="autoZero"/><c:crossBetween val="between"/></c:valAx>')
    title = data.get("title") or ""
    title_xml = (f'<c:title><c:tx><c:rich><a:bodyPr/><a:p><a:r><a:t>{escape(title)}</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title><c:autoTitleDeleted val="0"/>'
                 if title else '<c:autoTitleDeleted val="1"/>')
    legend = '<c:legend><c:legendPos val="b"/><c:overlay val="0"/></c:legend>' if ch.get("legend", True) else ""
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><c:chartSpace xmlns:c="{C}" xmlns:a="{A}" xmlns:r="{R}"><c:chart>'
            f'{title_xml}<c:plotArea><c:layout/>{body}</c:plotArea>{legend}<c:plotVisOnly val="1"/></c:chart></c:chartSpace>')


def write(book, path, shown=None) -> None:
    """Write a huginn_sheet_engine.Book (with Sheets' sheet dicts) as .xlsx."""
    styles = _Styles()
    strings, string_index = [], {}
    parts, sheets_xml = {}, []
    chart_n = 0
    content_overrides = []
    for s, sh in enumerate(book.sheets):
        name = sh["name"]
        rows = {}
        for (r, c) in set(sh["raw"]) | set(sh["fmt"]):
            rows.setdefault(r, []).append(c)
        out_rows = []
        for r in sorted(rows):
            cells = []
            for c in sorted(rows[r]):
                raw = sh["raw"].get((r, c), "")
                f = sh["fmt"].get((r, c)) or {}
                st = styles.xf(f)
                sattr = f' s="{st}"' if st else ""
                ref = se.ref_name(r, c)
                if not raw:
                    cells.append(f'<c r="{ref}"{sattr}/>')
                    continue
                v = book.value(s, r, c)
                if raw.startswith("=") and len(raw) > 1:
                    fx = f"<f>{escape(_formula_out(raw))}</f>"
                    if isinstance(v, se.Err):
                        cells.append(f'<c r="{ref}"{sattr} t="e">{fx}<v>{escape(v.code)}</v></c>')
                    elif isinstance(v, bool):
                        cells.append(f'<c r="{ref}"{sattr} t="b">{fx}<v>{int(v)}</v></c>')
                    elif isinstance(v, (int, float)):
                        cells.append(f'<c r="{ref}"{sattr}>{fx}<v>{float(v)!r}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}"{sattr} t="str">{fx}<v>{escape(str(v) if v is not se.BLANK else "")}</v></c>')
                    continue
                if isinstance(v, bool):
                    cells.append(f'<c r="{ref}"{sattr} t="b"><v>{int(v)}</v></c>')
                elif isinstance(v, (int, float)):
                    if not st and not f.get("num"):
                        _, guess = se.literal(raw, book.day_first)
                        if guess:
                            st = styles.xf({"num": guess})
                            sattr = f' s="{st}"'
                    cells.append(f'<c r="{ref}"{sattr}><v>{float(v)!r}</v></c>')
                elif isinstance(v, se.Err):
                    cells.append(f'<c r="{ref}"{sattr} t="e"><v>{escape(v.code)}</v></c>')
                else:
                    text = raw[1:] if raw.startswith("'") else raw
                    if text not in string_index:
                        string_index[text] = len(strings)
                        strings.append(text)
                    cells.append(f'<c r="{ref}"{sattr} t="s"><v>{string_index[text]}</v></c>')
            h = sh["heights"].get(r)
            hattr = f' ht="{float(h) * 72 / 96:.2f}" customHeight="1"' if h else ""
            out_rows.append(f'<row r="{r + 1}"{hattr}>{"".join(cells)}</row>')
        for r, h in sorted(sh["heights"].items()):
            if r not in rows:
                out_rows.append(f'<row r="{int(r) + 1}" ht="{float(h) * 72 / 96:.2f}" customHeight="1"/>')
        out_rows.sort(key=lambda x: int(re.match(r'<row r="(\d+)"', x).group(1)))
        cols = "".join(f'<col min="{int(c) + 1}" max="{int(c) + 1}" width="{_px_to_width(float(w))}" customWidth="1"/>' for c, w in sorted(sh["widths"].items()))
        fr, fc = sh.get("freeze") or [0, 0]
        pane = ""
        if fr or fc:
            top_left = se.ref_name(fr, fc)
            which = "bottomRight" if fr and fc else ("bottomLeft" if fr else "topRight")
            pane = (f'<pane{f" xSplit=\"{fc}\"" if fc else ""}{f" ySplit=\"{fr}\"" if fr else ""} topLeftCell="{top_left}" activePane="{which}" state="frozen"/>'
                    f'<selection pane="{which}" activeCell="{top_left}" sqref="{top_left}"/>')
        ur, uc = book.used(s)
        dim = f"A1:{se.ref_name(max(0, ur), max(0, uc))}"
        extra = ""
        flt = sh.get("filter")
        if flt:
            r0, c0, r1, c1 = flt["range"]
            extra += f'<autoFilter ref="{se.ref_name(r0, c0)}:{se.ref_name(r1, c1)}"/>'
        if sh.get("merges"):
            extra += f'<mergeCells count="{len(sh["merges"])}">' + "".join(f'<mergeCell ref="{_attr(m)}"/>' for m in sh["merges"]) + "</mergeCells>"
        if sh.get("rules"):
            extra += _cf_xml(sh["rules"], styles)
        if sh.get("checks"):
            extra += _dv_xml(sh["checks"], book.day_first)
        rels = []
        if sh.get("charts"):
            anchors = []
            drels = []
            for k, ch in enumerate(sh["charts"]):
                chart_n += 1
                parts[f"xl/charts/chart{chart_n}.xml"] = _chart_xml(book, s, ch, name)
                content_overrides.append(f'<Override PartName="/xl/charts/chart{chart_n}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>')
                drels.append(f'<Relationship Id="rId{k + 1}" Type="{REL}/chart" Target="../charts/chart{chart_n}.xml"/>')
                c0_, cx0, r0_, cy0 = _anchor(sh, float(ch.get("x", 0)), float(ch.get("y", 0)))
                c1_, cx1, r1_, cy1 = _anchor(sh, float(ch.get("x", 0)) + float(ch.get("w", 480)), float(ch.get("y", 0)) + float(ch.get("h", 300)))
                anchors.append(f'<xdr:twoCellAnchor><xdr:from><xdr:col>{c0_}</xdr:col><xdr:colOff>{cx0}</xdr:colOff><xdr:row>{r0_}</xdr:row><xdr:rowOff>{cy0}</xdr:rowOff></xdr:from>'
                               f'<xdr:to><xdr:col>{c1_}</xdr:col><xdr:colOff>{cx1}</xdr:colOff><xdr:row>{r1_}</xdr:row><xdr:rowOff>{cy1}</xdr:rowOff></xdr:to>'
                               f'<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="{k + 2}" name="Chart {k + 1}"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>'
                               f'<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm><a:graphic><a:graphicData uri="{C}"><c:chart xmlns:c="{C}" r:id="rId{k + 1}"/></a:graphicData></a:graphic>'
                               f'</xdr:graphicFrame><xdr:clientData/></xdr:twoCellAnchor>')
            parts[f"xl/drawings/drawing{s + 1}.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><xdr:wsDr xmlns:xdr="{XDR}" xmlns:a="{A}" xmlns:r="{R}">'
                                                         + "".join(anchors) + "</xdr:wsDr>")
            parts[f"xl/drawings/_rels/drawing{s + 1}.xml.rels"] = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG}">{"".join(drels)}</Relationships>'
            content_overrides.append(f'<Override PartName="/xl/drawings/drawing{s + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>')
            rels.append(f'<Relationship Id="rId1" Type="{REL}/drawing" Target="../drawings/drawing{s + 1}.xml"/>')
            extra += '<drawing r:id="rId1"/>'
        if sh.get("notes"):
            comments, vml = _comments_parts(sh["notes"], s + 1)
            parts[f"xl/comments{s + 1}.xml"] = comments
            parts[f"xl/drawings/vmlDrawing{s + 1}.vml"] = vml
            content_overrides.append(f'<Override PartName="/xl/comments{s + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"/>')
            rels.append(f'<Relationship Id="rId2" Type="{REL}/comments" Target="../comments{s + 1}.xml"/>')
            rels.append(f'<Relationship Id="rId3" Type="{REL}/vmlDrawing" Target="../drawings/vmlDrawing{s + 1}.vml"/>')
            extra += '<legacyDrawing r:id="rId3"/>'
        selected = ' tabSelected="1"' if s == 0 else ""
        parts[f"xl/worksheets/sheet{s + 1}.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{S}" xmlns:r="{R}"><dimension ref="{dim}"/>'
            f'<sheetViews><sheetView workbookViewId="0"{selected}>{pane}</sheetView></sheetViews><sheetFormatPr defaultRowHeight="19.5" customHeight="1"/>'
            + (f"<cols>{cols}</cols>" if cols else "") + f'<sheetData>{"".join(out_rows)}</sheetData>{extra}</worksheet>')
        if rels:
            parts[f"xl/worksheets/_rels/sheet{s + 1}.xml.rels"] = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG}">{"".join(rels)}</Relationships>'
        sheets_xml.append(f'<sheet name="{_attr(name)}" sheetId="{s + 1}" r:id="rId{s + 1}"/>')
    n = len(book.sheets)
    defined = ""
    flt_names = [(i, sh["filter"]["range"]) for i, sh in enumerate(book.sheets) if sh.get("filter")]
    if flt_names:
        defined = "<definedNames>" + "".join(
            f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">{escape(se.quote_sheet(book.sheets[i]["name"]))}!${se.col_name(rg[1])}${rg[0] + 1}:${se.col_name(rg[3])}${rg[2] + 1}</definedName>'
            for i, rg in flt_names) + "</definedNames>"
    parts["xl/workbook.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{S}" xmlns:r="{R}"><bookViews><workbookView/></bookViews>'
                                f'<sheets>{"".join(sheets_xml)}</sheets>{defined}<calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>')
    wrels = [f'<Relationship Id="rId{i + 1}" Type="{REL}/worksheet" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(n)]
    wrels.append(f'<Relationship Id="rId{n + 1}" Type="{REL}/styles" Target="styles.xml"/>')
    wrels.append(f'<Relationship Id="rId{n + 2}" Type="{REL}/sharedStrings" Target="sharedStrings.xml"/>')
    parts["xl/_rels/workbook.xml.rels"] = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG}">{"".join(wrels)}</Relationships>'
    parts["xl/styles.xml"] = styles.xml()
    sst = "".join(f'<si><t xml:space="preserve">{escape(t)}</t></si>' for t in strings)
    parts["xl/sharedStrings.xml"] = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst xmlns="{S}" count="{len(strings)}" uniqueCount="{len(strings)}">{sst}</sst>'
    overrides = ['<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
                 '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
                 '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>']
    overrides += [f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(n)]
    parts["[Content_Types].xml"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                                    '<Default Extension="vml" ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/>'
                                    + "".join(overrides + content_overrides) + "</Types>")
    parts["_rels/.rels"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG}">'
                            f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    tmp = str(path) + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text)
    import os
    os.replace(tmp, path)


# ================================================================================================ reading
def _part(z, name):
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


def _rels(z, part):
    folder, _, name = part.rpartition("/")
    root = _part(z, f"{folder}/_rels/{name}.rels" if folder else f"_rels/{name}.rels")
    out = {}
    for rel in root if root is not None else []:
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            continue
        pieces = (target.lstrip("/") if target.startswith("/") else f"{folder}/{target}").split("/")
        stack = []
        for piece in pieces:
            if piece == "..":
                if stack:
                    stack.pop()
            elif piece not in ("", "."):
                stack.append(piece)
        out[rel.get("Id")] = ("/".join(stack), rel.get("Type", ""))
    return out


def _our_format(code: str) -> str:
    """An Excel number format as one of ours (near enough)."""
    if not code or code == "General":
        return ""
    plain = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', lambda m: m.group(0)[1:-1] if m.group(0).startswith('"') else m.group(0)[1:] if m.group(0).startswith("\\") else "", code.split(";")[0])
    low = plain.lower()
    if any(x in low for x in ("yy", "dd", "mmm")) or re.search(r"\bd\b|m/d|d/m", low):
        if re.search(r"h", low):
            return "yyyy-mm-dd hh:mm"
        if "yyyy-mm-dd" in low:
            return "yyyy-mm-dd"
        if "mmm" in low:
            return "d mmm yyyy"
        return "short-date"
    if "h" in low and ":" in low:
        return "h:mm AM/PM" if "am" in low else ("hh:mm:ss" if low.count(":") >= 2 else "hh:mm")
    if "e+" in low:
        return "0.00E+00"
    if plain.strip() == "@":
        return "@"
    places = len(re.search(r"\.(0+)", plain).group(1)) if re.search(r"\.(0+)", plain) else 0
    if "%" in plain:
        return "0%" if places == 0 else "0." + "0" * places + "%"
    sym = next((ch for ch in plain if ch in "$€£¥"), "")
    comma = "," in plain
    base = ("#,##0" if comma or sym else "0") + ("." + "0" * places if places else "")
    return (sym + base) if sym else base


def _day_first() -> bool:
    try:
        from PySide6.QtCore import QLocale
        return QLocale.system().dateFormat(QLocale.ShortFormat).lower().startswith("d")
    except Exception:                                       # noqa: BLE001
        return False


def read(path) -> tuple:
    """(sheets as Sheets keeps them, dropped notes)."""
    from huginn_sheets import blank_sheet
    if not zipfile.is_zipfile(path):
        raise ConvertError("This isn't a readable Excel file.")
    dropped = []
    with zipfile.ZipFile(path) as z:
        wb = _part(z, "xl/workbook.xml")
        if wb is None:
            raise ConvertError("This doesn't look like an Excel workbook.")
        wrels = _rels(z, "xl/workbook.xml")
        sst = []
        rel_sst = next((t for t, k in wrels.values() if k.endswith("/sharedStrings")), "xl/sharedStrings.xml")
        sroot = _part(z, rel_sst)
        if sroot is not None:
            for si in sroot.findall(_q("si")):
                phonetic = {id(t) for ph in si.iter(_q("rPh")) for t in ph.iter(_q("t"))}      # (reading aids, not the text)
                sst.append("".join(t.text or "" for t in si.iter(_q("t")) if id(t) not in phonetic))
        styles = _part(z, next((t for t, k in wrels.values() if k.endswith("/styles")), "xl/styles.xml"))
        fmts = _read_styles(styles)
        dxfs = _read_dxfs(styles)
        sheets = []
        names = set(z.namelist())
        unknown = set()
        lost = {"cf": 0, "dv": 0, "comments": 0, "pictures": 0, "pivots": 0, "merges": 0}
        for el in wb.iter(_q("sheet")):
            rid = el.get(_q("id", R))
            target = wrels.get(rid, ("", ""))[0]
            root = _part(z, target)
            if root is None:
                continue
            sh = blank_sheet((el.get("name") or f"Sheet {len(sheets) + 1}")[:31])
            _read_sheet(z, target, root, sh, sst, fmts, unknown, lost, names, dxfs, _day_first())
            sheets.append(sh)
        if len(sheets) > 64:
            dropped.append(f"{len(sheets) - 64} sheets past the first 64")
            sheets = sheets[:64]
    if unknown:
        dropped.append("formulas using " + ", ".join(sorted(unknown)[:6]) + (" and others" if len(unknown) > 6 else "") + " (they show #NAME? for now)")
    for key, words in (("cf", "some conditional formatting (icon sets and rules by formula)"), ("dv", "some limits on what cells take (by formula or a named list)"), ("comments", "comments"),
                       ("pictures", "pictures and shapes"), ("pivots", "pivot tables (their last results are kept as values)"),
                       ("merges", "merged cells (shown as separate cells; they're merged again in Excel files Sheets makes)")):
        if lost[key]:
            dropped.append(words)
    return sheets, dropped


def _read_styles(root) -> list:
    """cellXfs as Sheets' formats."""
    if root is None:
        return []
    custom = {int(n.get("numFmtId")): n.get("formatCode", "") for n in root.iter(_q("numFmt"))}
    fonts = []
    fe = root.find(_q("fonts"))
    for f in (fe if fe is not None else []):
        d = {}
        if f.find(_q("b")) is not None and f.find(_q("b")).get("val", "1") not in ("0", "false"):
            d["b"] = True
        if f.find(_q("i")) is not None and f.find(_q("i")).get("val", "1") not in ("0", "false"):
            d["i"] = True
        if f.find(_q("u")) is not None and f.find(_q("u")).get("val", "single") != "none":
            d["u"] = True
        if f.find(_q("strike")) is not None and f.find(_q("strike")).get("val", "1") not in ("0", "false"):
            d["s"] = True
        col = f.find(_q("color"))
        if col is not None and re.fullmatch(r"[0-9A-Fa-f]{8}", col.get("rgb", "")) and col.get("rgb").upper()[2:] != "000000":
            d["color"] = "#" + col.get("rgb")[2:].upper()
        sz = f.find(_q("sz"))
        if sz is not None and sz.get("val") and abs(float(sz.get("val")) - 11) > 0.01:
            d["size"] = float(sz.get("val"))
        nm = f.find(_q("name"))
        if nm is not None and nm.get("val") not in (None, "Calibri", "Aptos Narrow", "Aptos"):
            d["font"] = nm.get("val")
        fonts.append(d)
    fills = []
    fl = root.find(_q("fills"))
    for f in (fl if fl is not None else []):
        pf = f.find(_q("patternFill"))
        fg = pf.find(_q("fgColor")) if pf is not None else None
        if pf is not None and pf.get("patternType") == "solid" and fg is not None and re.fullmatch(r"[0-9A-Fa-f]{8}", fg.get("rgb", "")):
            fills.append("#" + fg.get("rgb")[2:].upper())
        else:
            fills.append("")
    out = []
    xfs = root.find(_q("cellXfs"))
    for xf in (xfs if xfs is not None else []):
        d = {}
        fid = int(xf.get("fontId", "0") or 0)
        if fid < len(fonts):
            d.update(fonts[fid])
        fl_id = int(xf.get("fillId", "0") or 0)
        if fl_id < len(fills) and fills[fl_id]:
            d["fill"] = fills[fl_id]
        nid = int(xf.get("numFmtId", "0") or 0)
        code = custom.get(nid) if nid in custom else BUILTIN_FMT.get(nid, "General")
        ours = _our_format(code) if nid in custom else ("" if code == "General" else code)
        if ours:
            d["num"] = ours
        al = xf.find(_q("alignment"))
        if al is not None:
            if al.get("horizontal") in ("left", "center", "right"):
                d["align"] = al.get("horizontal")
            if al.get("wrapText") in ("1", "true"):
                d["wrap"] = True
        out.append(d)
    return out


def _formula_in(text: str) -> str:
    return "=" + re.sub(r"_xlfn\.|_xlws\.", "", text, flags=re.I)


def _read_sheet(z, target, root, sh, sst, fmts, unknown, lost, names, dxfs=(), day_first=False):
    shared = {}                       # si -> (row, col, formula text)
    for c in root.iter(_q("c")):
        ref = c.get("r")
        pos = se.parse_cell(ref) if ref else None
        if pos is None:
            continue
        r, col = pos
        s = int(c.get("s", "0") or 0)
        if 0 < s < len(fmts) and fmts[s]:
            sh["fmt"][(r, col)] = dict(fmts[s])
        f = c.find(_q("f"))
        t = c.get("t", "n")
        v = c.find(_q("v"))
        text = None
        if f is not None:
            ftext = f.text or ""
            if f.get("t") == "shared":
                si = f.get("si")
                if ftext:
                    shared[si] = (r, col, ftext)
                elif si in shared:
                    r0, c0, base = shared[si]
                    ftext = se.shift_formula("=" + base, r - r0, col - c0)[1:]
            if ftext:
                text = _formula_in(ftext)
                for name in re.findall(r"([A-Za-z_][\w.]*)\s*\(", ftext):
                    up = re.sub(r"^_XLFN\.|^_XLWS\.", "", name.upper())
                    if up not in se.NAMES:
                        unknown.add(up)
        if text is None:
            if t == "s" and v is not None and (v.text or "").isdigit():
                k = int(v.text)
                text = sst[k] if k < len(sst) else ""
                if text and (se.literal(text)[1] or text.upper() in ("TRUE", "FALSE")) and not text.startswith("="):
                    text = "'" + text                 # text that looks like a number stays text
                elif text.startswith("="):
                    text = "'" + text
            elif t == "inlineStr":
                text = "".join(x.text or "" for x in c.iter(_q("t")))
            elif t == "b" and v is not None:
                text = "TRUE" if v.text == "1" else "FALSE"
            elif t == "e" and v is not None:
                text = v.text or ""
            elif t == "str" and v is not None:
                text = v.text or ""
            elif v is not None and v.text:
                try:
                    num = float(v.text)
                    text = se.general(num) if abs(num) < 1e15 else repr(num)
                except ValueError:
                    text = v.text
        if text:
            sh["raw"][(r, col)] = text
    for col in root.iter(_q("col")):
        try:
            lo, hi, w = int(col.get("min")), int(col.get("max")), float(col.get("width", "0") or 0)
        except (TypeError, ValueError):
            continue
        if col.get("customWidth") in ("1", "true") or w:
            for k in range(lo - 1, min(hi, lo + 300)):
                sh["widths"][k] = round(w * 7 + 5)
    for row in root.iter(_q("row")):
        if row.get("customHeight") in ("1", "true") and row.get("ht") and row.get("r"):
            sh["heights"][int(row.get("r")) - 1] = round(float(row.get("ht")) * 96 / 72)
    pane = root.find(f"{_q('sheetViews')}/{_q('sheetView')}/{_q('pane')}")
    if pane is not None and pane.get("state") in ("frozen", "frozenSplit"):
        sh["freeze"] = [int(float(pane.get("ySplit", "0") or 0)), int(float(pane.get("xSplit", "0") or 0))]
    af = root.find(_q("autoFilter"))
    if af is not None and af.get("ref") and ":" in af.get("ref"):
        a, b = af.get("ref").split(":")
        p, q = se.parse_cell(a), se.parse_cell(b)
        if p and q:
            sh["filter"] = {"range": [p[0], p[1], q[0], q[1]], "hide": {}}
    merges = [m.get("ref") for m in root.iter(_q("mergeCell")) if m.get("ref")]
    if merges:
        sh["merges"] = merges
        lost["merges"] += 1
    sh["rules"], skipped = _read_cf(root, list(dxfs))
    lost["cf"] += skipped
    sh["checks"], skipped = _read_dv(root, day_first)
    lost["dv"] += skipped
    rels = _rels(z, target)
    for rid, (part, kind) in rels.items():
        if kind.endswith("/comments"):
            sh["notes"].update(_read_comments(_part(z, part)))
        elif kind.endswith("/pivotTable"):
            lost["pivots"] += 1
        elif kind.endswith("/drawing"):
            _read_drawing(z, part, sh, lost)


def _read_drawing(z, part, sh, lost):
    root = _part(z, part)
    if root is None:
        return
    rels = _rels(z, part)
    for anchor in list(root):
        frame = anchor.find(_q("graphicFrame", XDR))
        if frame is None:
            lost["pictures"] += 1
            continue
        chart_el = next((e for e in frame.iter(_q("chart", C))), None)
        if chart_el is None:
            lost["pictures"] += 1
            continue
        target = rels.get(chart_el.get(_q("id", R)), ("", ""))[0]
        chart = _part(z, target)
        if chart is None:
            continue
        got = _chart_from(chart)
        if not got:
            lost["pictures"] += 1
            continue
        frm, to = anchor.find(_q("from", XDR)), anchor.find(_q("to", XDR))

        def point(el):
            if el is None:
                return 0.0, 0.0
            col = int(el.find(_q("col", XDR)).text or 0)
            row = int(el.find(_q("row", XDR)).text or 0)
            x = sum(float(sh["widths"].get(k, 100)) for k in range(col)) + int(el.find(_q("colOff", XDR)).text or 0) / 9525
            y = sum(float(sh["heights"].get(k, 26)) for k in range(row)) + int(el.find(_q("rowOff", XDR)).text or 0) / 9525
            return x, y
        x0, y0 = point(frm)
        x1, y1 = point(to) if to is not None else (x0 + 480, y0 + 300)
        kind, span, title = got
        sh["charts"].append({"id": f"chart{len(sh['charts']) + 1}", "kind": kind, "range": span, "title": title,
                             "x": round(x0), "y": round(y0), "w": max(160, round(x1 - x0)), "h": max(120, round(y1 - y0)), "legend": True})


def _chart_from(root):
    """(kind, range, title) of a chart part, when its data is one block of the sheet it's on."""
    plot = next((e for e in root.iter(_q("plotArea", C))), None)
    if plot is None:
        return None
    kind = None
    for tag, ours in (("barChart", None), ("bar3DChart", None), ("lineChart", "line"), ("line3DChart", "line"), ("pieChart", "pie"), ("pie3DChart", "pie"),
                      ("doughnutChart", "pie"), ("areaChart", "area"), ("area3DChart", "area")):
        el = plot.find(_q(tag, C))
        if el is not None:
            if ours is None:
                bd = el.find(_q("barDir", C))
                ours = "bar" if bd is not None and bd.get("val") == "bar" else "column"
            kind = ours
            break
    if kind is None:
        return None
    refs = [f.text for f in plot.iter(_q("f", C)) if f.text]
    cells = []
    for ref in refs:
        sheet, part = se.split_ref(ref.replace("$", ""))
        for piece in part.split(":"):
            p = se.parse_cell(piece)
            if p:
                cells.append(p)
    if not cells:
        return None
    r0, c0 = min(p[0] for p in cells), min(p[1] for p in cells)
    r1, c1 = max(p[0] for p in cells), max(p[1] for p in cells)
    title = "".join(t.text or "" for t in root.iter(_q("t", A)) if t.text) if root.find(f"{_q('chart', C)}/{_q('title', C)}") is not None else ""
    return kind, f"{se.ref_name(r0, c0)}:{se.ref_name(r1, c1)}", title[:120]
