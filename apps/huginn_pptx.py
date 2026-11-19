"""PowerPoint files for Slides, both ways.

write(deck, path): a .pptx with a master and one layout per Slides layout (and per design frame read from another
file), the theme's colours and fonts, every item where it is on the slide (text with its runs, bullets and levels,
shapes as PowerPoint's preset shapes, pictures), backgrounds, speaker notes, transitions, builds and hidden slides.

read(path) → (deck, dropped): the slides with their items placed as PowerPoint places them: placeholders that take
their place and text styles from the layout and master, theme colours and fonts, groups flattened, tables as cells,
pictures (cropped), backgrounds, the master's and layout's own shapes (logos, bands) kept as the deck's frames,
notes, transitions and entrance builds. What doesn't come across is listed.
"""
import base64
import colorsys
import posixpath
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import huginn_slides_model as sm

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
P14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
NS = f'xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"'


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def a_(tag):
    return q(A, tag)


def p_(tag):
    return q(P, tag)


# ============================================================================================== writing
PRESETS = {"rect": "rect", "rounded": "roundRect", "ellipse": "ellipse", "triangle": "triangle", "rtriangle": "rtTriangle",
           "diamond": "diamond", "pentagon": "pentagon", "hexagon": "hexagon", "star": "star5", "arrow": "rightArrow",
           "larrow": "leftArrow", "chevron": "chevron", "callout": "wedgeRectCallout", "heart": "heart", "plus": "plus",
           "line": "line", "arrowline": "line"}
LAYOUT_TYPES = {"title": ("title", "Title Slide"), "content": ("obj", "Title and Content"), "section": ("secHead", "Section Header"),
                "two": ("twoObj", "Two Content"), "titleonly": ("titleOnly", "Title Only"), "blank": ("blank", "Blank")}
BULLETS = ("•", "◦", "▪")
NUMBERS = ("arabicPeriod", "alphaLcPeriod", "romanLcPeriod")
TRANSITIONS = {"fade": "<p:fade/>", "push": '<p:push dir="l"/>', "wipe": '<p:wipe dir="r"/>', "zoom": "<p:zoom/>", "cover": '<p:cover dir="l"/>'}
PRESET_IDS = {"appear": 1, "fade": 10, "rise": 2, "zoom": 53}


def emu(v: float) -> int:
    return int(round(float(v) * sm.EMU))


def hexval(c: str) -> str:
    return (c or "#000000").lstrip("#").upper()[:6]


def fill_xml(value: str, look: dict) -> str:
    if not value:
        return "<a:noFill/>"
    if value.startswith("accent") and value[6:].isdigit() and 1 <= int(value[6:]) <= 6:
        return f'<a:solidFill><a:schemeClr val="{value}"/></a:solidFill>'
    return f'<a:solidFill><a:srgbClr val="{hexval(sm.colour(value, look))}"/></a:solidFill>'


def bg_xml(bg: dict, rel_for) -> str:
    if not bg:
        return ""
    if bg.get("picture"):
        rid = rel_for(bg["picture"])
        fill = f'<a:blipFill dpi="0" rotWithShape="1"><a:blip r:embed="{rid}"/><a:srcRect/><a:stretch><a:fillRect/></a:stretch></a:blipFill>'
    elif bg.get("from"):
        ang = 0 if int(bg.get("angle", 0)) % 180 == 0 else 5400000
        fill = (f'<a:gradFill rotWithShape="1"><a:gsLst><a:gs pos="0"><a:srgbClr val="{hexval(bg["from"])}"/></a:gs>'
                f'<a:gs pos="100000"><a:srgbClr val="{hexval(bg.get("to") or bg["from"])}"/></a:gs></a:gsLst><a:lin ang="{ang}" scaled="0"/></a:gradFill>')
    else:
        fill = f'<a:solidFill><a:srgbClr val="{hexval(bg.get("color", "#FFFFFF"))}"/></a:solidFill>'
    return f"<p:bg><p:bgPr>{fill}<a:effectLst/></p:bgPr></p:bg>"


def para_xml(item: dict, para: dict, n: int, layout: str, look: dict) -> str:
    dflt = sm.para_defaults(item, para, layout, look)
    lvl = max(0, min(8, int(para.get("lvl", 0))))
    kind = para.get("list") or ""
    algn = {"left": "l", "center": "ctr", "right": "r", "justify": "just"}[para.get("align") or dflt["align"]]
    attrs = f' algn="{algn}"'
    if kind:
        attrs += f' marL="{emu((lvl + 1) * sm.INDENT)}" indent="{-emu(sm.INDENT)}"'
    elif lvl:
        attrs += f' marL="{emu(lvl * sm.INDENT)}" indent="0"'
    else:
        attrs += ' marL="0" indent="0"'
    if lvl:
        attrs = f' lvl="{lvl}"' + attrs
    inner = ""
    spacing = float(para.get("spacing", 0) or 0) or (0.95 if item.get("role") == "title" else 0)
    if spacing:
        inner += f'<a:lnSpc><a:spcPct val="{int(spacing * 100000)}"/></a:lnSpc>'
    if n and item.get("role") in ("body", "body2") and kind:
        inner += f'<a:spcBef><a:spcPts val="{int(dflt["size"] * 0.35 * 100)}"/></a:spcBef>'
    else:
        inner += '<a:spcBef><a:spcPts val="0"/></a:spcBef>'
    if kind == "bullet":
        inner += f'<a:buFont typeface="Arial"/><a:buChar char="{BULLETS[lvl % 3]}"/>'
    elif kind == "number":
        inner += f'<a:buFont typeface="+mj-lt"/><a:buAutoNum type="{NUMBERS[lvl % 3]}"/>'
    else:
        inner += "<a:buNone/>"
    runs = ""
    for run in para.get("runs", []):
        text = run.get("t", "")
        if not text:
            continue
        for k, piece in enumerate(text.split("\n")):
            if k:
                runs += f"<a:br>{rpr_xml(run, dflt)}</a:br>"
            if piece:
                runs += f'<a:r>{rpr_xml(run, dflt)}<a:t>{escape(piece)}</a:t></a:r>'
    end = rpr_xml({}, dflt, "a:endParaRPr")
    return f"<a:p><a:pPr{attrs}>{inner}</a:pPr>{runs}{end}</a:p>"


def rpr_xml(run: dict, dflt: dict, tag: str = "a:rPr") -> str:
    size = float(run.get("size") or dflt["size"])
    attrs = f' lang="en-US" sz="{int(round(size * 100))}" b="{1 if run.get("b", dflt["b"]) else 0}" i="{1 if run.get("i") else 0}"'
    if run.get("u"):
        attrs += ' u="sng"'
    if run.get("s"):
        attrs += ' strike="sngStrike"'
    font = escape(run.get("font") or dflt["font"], {'"': "&quot;"})
    return (f'<{tag}{attrs} dirty="0"><a:solidFill><a:srgbClr val="{hexval(run.get("color") or dflt["color"])}"/></a:solidFill>'
            f'<a:latin typeface="{font}"/><a:cs typeface="{font}"/></{tag}>')


def body_xml(item: dict, layout: str, look: dict) -> str:
    valign = item.get("valign") or sm.role_style(item.get("role", ""), layout)["valign"]
    anchor = {"top": "t", "middle": "ctr", "bottom": "b"}.get(valign, "t")
    if item.get("role"):
        fit = float(item.get("fit", 1) or 1)
        auto = f'<a:normAutofit fontScale="{int(fit * 100000)}"/>' if fit < 0.999 else "<a:normAutofit/>"
    elif item.get("grow"):
        auto = "<a:spAutoFit/>"
    else:
        auto = "<a:noAutofit/>"
    paras = "".join(para_xml(item, p, n, layout, look) for n, p in enumerate(item.get("paras") or [{"runs": []}]))
    return (f'<p:txBody><a:bodyPr wrap="square" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="0" anchor="{anchor}">{auto}</a:bodyPr>'
            f"<a:lstStyle/>{paras}</p:txBody>")


def xfrm_xml(item: dict, tag: str = "a:xfrm") -> str:
    attrs = ""
    if item.get("rot"):
        attrs += f' rot="{int(round(float(item["rot"]) * 60000)) % 21600000}"'
    if item.get("flipH"):
        attrs += ' flipH="1"'
    if item.get("flipV"):
        attrs += ' flipV="1"'
    return f'<{tag}{attrs}><a:off x="{emu(item["x"])}" y="{emu(item["y"])}"/><a:ext cx="{emu(max(item["w"], 0))}" cy="{emu(max(item["h"], 0))}"/></{tag}>'


PH = {"title": ('type="title"', "Title"), "subtitle": ('type="subTitle" idx="1"', "Subtitle"), "body": ('idx="1"', "Content Placeholder"),
      "body2": ('idx="2"', "Content Placeholder")}


def ph_attr(role: str, layout: str) -> str:
    if role == "title" and layout == "title":
        return 'type="ctrTitle"'
    if role == "body" and layout == "section":
        return 'type="body" idx="1"'
    if role in ("body", "body2") and layout == "two":
        return f'sz="half" idx="{1 if role == "body" else 2}"'
    return PH[role][0]


def item_xml(item: dict, sid: int, layout: str, look: dict, rel_for, placeholders: bool = True) -> str:
    name = escape(item.get("name") or {"picture": "Picture", "shape": sm.SHAPE_NAMES.get(item.get("shape", "rect"), "Shape")}.get(item["kind"], "TextBox"), {'"': "&quot;"})
    if item["kind"] == "picture":
        rid = rel_for(item.get("src", ""))
        return (f'<p:pic><p:nvPicPr><p:cNvPr id="{sid}" name="{name} {sid}" descr="{escape(item.get("alt", ""), {chr(34): "&quot;"})}"/>'
                f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
                f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
                f'<p:spPr>{xfrm_xml(item)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')
    role = item.get("role", "") if placeholders else ""
    if role:
        nv = f'<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph {ph_attr(role, layout)}/></p:nvPr>'
        name = PH[role][1]
    elif item["kind"] == "text":
        nv = '<p:cNvSpPr txBox="1"/><p:nvPr/>'
    else:
        nv = "<p:cNvSpPr/><p:nvPr/>"
    if item["kind"] == "shape":
        shape = item.get("shape", "rect")
        geom = f'<a:prstGeom prst="{PRESETS.get(shape, "rect")}"><a:avLst/></a:prstGeom>'
        if shape in ("line", "arrowline"):
            colour_ = item.get("line") or item.get("fill") or "accent1"
            tail = '<a:tailEnd type="triangle"/>' if shape == "arrowline" else ""
            sppr = f'{geom}<a:noFill/><a:ln w="{emu(item.get("lineW") or 3)}" cap="rnd">{fill_xml(colour_, look)}{tail}</a:ln>'
        else:
            line = (f'<a:ln w="{emu(item.get("lineW") or 2)}">{fill_xml(item["line"], look)}</a:ln>' if item.get("line") and item.get("lineW")
                    else "<a:ln><a:noFill/></a:ln>")
            sppr = f"{geom}{fill_xml(item.get('fill', ''), look)}{line}"
    else:
        sppr = '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/>'
    text = body_xml(item, layout, look) if item["kind"] == "text" or (item["kind"] == "shape" and item.get("shape") not in ("line", "arrowline")) else ""
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{name} {sid}"/>{nv}</p:nvSpPr>'
            f"<p:spPr>{xfrm_xml(item)}{sppr}</p:spPr>{text}</p:sp>")


TREE = ('<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/>'
        '<a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>')


def timing_xml(slide: dict, ids: dict) -> str:
    """Builds as PowerPoint's entrance effects, one click each (by paragraph where asked)."""
    builds = []
    for item in slide.get("items", []):
        anim = item.get("anim") or {}
        if not anim.get("kind") or item["id"] not in ids:
            continue
        paras = [n for n, p in enumerate(item.get("paras", [])) if any(r.get("t") for r in p.get("runs", []))]
        targets = paras if anim.get("byPara") and paras and item["kind"] != "picture" else [None]
        builds.append((float(anim.get("order") or 0), item, anim, targets))
    if not builds:
        return ""
    builds.sort(key=lambda b: b[0])
    counter = [2]

    def nid():
        counter[0] += 1
        return counter[0]

    clicks, bld = [], []
    for _, item, anim, targets in builds:
        spid = ids[item["id"]]
        kind = anim.get("kind") if anim.get("kind") in PRESET_IDS else "fade"
        for t in targets:
            tgt = f'<p:spTgt spid="{spid}">' + (f'<p:txEl><p:pRg st="{t}" end="{t}"/></p:txEl>' if t is not None else "") + "</p:spTgt>"
            dur = int(anim.get("ms", 500))
            effects = (f'<p:set><p:cBhvr><p:cTn id="{nid()}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
                       f'<p:tgtEl>{tgt}</p:tgtEl><p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>'
                       '<p:to><p:strVal val="visible"/></p:to></p:set>')
            if kind == "fade":
                effects += f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{nid()}" dur="{dur}"/><p:tgtEl>{tgt}</p:tgtEl></p:cBhvr></p:animEffect>'
            elif kind == "rise":
                for attr, start in (("ppt_x", "#ppt_x"), ("ppt_y", "#ppt_y+0.1")):
                    effects += (f'<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="{nid()}" dur="{dur}" fill="hold"/>'
                                f'<p:tgtEl>{tgt}</p:tgtEl><p:attrNameLst><p:attrName>{attr}</p:attrName></p:attrNameLst></p:cBhvr>'
                                f'<p:tavLst><p:tav tm="0"><p:val><p:strVal val="{start}"/></p:val></p:tav><p:tav tm="100000"><p:val>'
                                f'<p:strVal val="#{attr}"/></p:val></p:tav></p:tavLst></p:anim>')
                effects += f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{nid()}" dur="{dur}"/><p:tgtEl>{tgt}</p:tgtEl></p:cBhvr></p:animEffect>'
            elif kind == "zoom":
                for attr in ("ppt_w", "ppt_h"):
                    effects += (f'<p:anim calcmode="lin" valueType="num"><p:cBhvr><p:cTn id="{nid()}" dur="{dur}" fill="hold"/>'
                                f'<p:tgtEl>{tgt}</p:tgtEl><p:attrNameLst><p:attrName>{attr}</p:attrName></p:attrNameLst></p:cBhvr>'
                                f'<p:tavLst><p:tav tm="0"><p:val><p:fltVal val="0"/></p:val></p:tav><p:tav tm="100000"><p:val>'
                                f'<p:strVal val="#{attr}"/></p:val></p:tav></p:tavLst></p:anim>')
                effects += f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{nid()}" dur="{dur}"/><p:tgtEl>{tgt}</p:tgtEl></p:cBhvr></p:animEffect>'
            outer, inner, eff = nid(), nid(), nid()
            sub = {"appear": 0, "fade": 0, "rise": 4, "zoom": 16}[kind]
            clicks.append(f'<p:par><p:cTn id="{outer}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst><p:childTnLst>'
                          f'<p:par><p:cTn id="{inner}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
                          f'<p:par><p:cTn id="{eff}" presetID="{PRESET_IDS[kind]}" presetClass="entr" presetSubtype="{sub}" fill="hold"'
                          f'{" grpId=" + chr(34) + "0" + chr(34) if item["kind"] != "picture" else ""} nodeType="clickEffect">'
                          f'<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>{effects}</p:childTnLst></p:cTn></p:par>'
                          "</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>")
        if item["kind"] != "picture":
            bld.append(f'<p:bldP spid="{spid}" grpId="0"' + (' build="p"' if targets != [None] else (' animBg="1"' if item["kind"] == "shape" else "")) + "/>")
    return ('<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
            '<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
            + "".join(clicks) +
            '</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
            '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
            '</p:childTnLst></p:cTn></p:par></p:tnLst>' + (f'<p:bldLst>{"".join(bld)}</p:bldLst>' if bld else "") + "</p:timing>")


def theme_xml(look: dict, name: str = "Huginn") -> str:
    acc = (look["accents"] * 2)[:6]
    bg = look["bg"]
    back = bg.get("color") or bg.get("from") or "#FFFFFF"
    fill3 = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3
    line3 = '<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>' * 3
    head, body = escape(look["head"], {'"': "&quot;"}), escape(look["body"], {'"': "&quot;"})
    return (f'{HEAD}<a:theme xmlns:a="{A}" name="{escape(name)}"><a:themeElements><a:clrScheme name="{escape(name)}">'
            f'<a:dk1><a:srgbClr val="{hexval(look["text"])}"/></a:dk1><a:lt1><a:srgbClr val="{hexval(back)}"/></a:lt1>'
            f'<a:dk2><a:srgbClr val="{hexval(look["title"])}"/></a:dk2><a:lt2><a:srgbClr val="{hexval(bg.get("to") or back)}"/></a:lt2>'
            + "".join(f'<a:accent{i + 1}><a:srgbClr val="{hexval(c)}"/></a:accent{i + 1}>' for i, c in enumerate(acc))
            + f'<a:hlink><a:srgbClr val="{hexval(acc[0])}"/></a:hlink><a:folHlink><a:srgbClr val="{hexval(acc[1])}"/></a:folHlink></a:clrScheme>'
            f'<a:fontScheme name="{escape(name)}"><a:majorFont><a:latin typeface="{head}"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
            f'<a:minorFont><a:latin typeface="{body}"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
            f'<a:fmtScheme name="{escape(name)}"><a:fillStyleLst>{fill3}</a:fillStyleLst><a:lnStyleLst>{line3}</a:lnStyleLst>'
            '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
            f'<a:bgFillStyleLst>{fill3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>')


def lvl_styles(look: dict, role: str, layout: str) -> str:
    out = ""
    st = sm.role_style(role, layout)
    for lvl in range(9):
        size = sm.para_size(st["size"], lvl, role)
        font = "+mj-lt" if st["font"] == "head" else "+mn-lt"
        colour_ = look["title"] if st["color"] == "title" else look["text"]
        algn = {"left": "l", "center": "ctr", "right": "r"}[st["align"]]
        if st["list"]:
            bu = f'<a:buFont typeface="Arial"/><a:buChar char="{BULLETS[lvl % 3]}"/>'
            ind = f' marL="{emu((lvl + 1) * sm.INDENT)}" indent="{-emu(sm.INDENT)}"'
        else:
            bu, ind = "<a:buNone/>", f' marL="{emu(lvl * sm.INDENT)}" indent="0"'
        out += (f'<a:lvl{lvl + 1}pPr{ind} algn="{algn}"><a:spcBef><a:spcPts val="0"/></a:spcBef>{bu}'
                f'<a:defRPr sz="{int(size * 100)}" b="{1 if st["b"] else 0}"><a:solidFill><a:srgbClr val="{hexval(colour_)}"/></a:solidFill>'
                f'<a:latin typeface="{font}"/><a:cs typeface="{font}"/></a:defRPr></a:lvl{lvl + 1}pPr>')
    return out


def write(deck: dict, path) -> None:
    look = sm.look_of(deck)
    W = sm.slide_w(deck.get("size", "16:9"))
    files, ct, media = {}, [], {}
    frames = (look.get("frames") or {}) if deck.get("look") else {}

    def media_for(src: str, rels: list) -> str:
        """A picture into ppt/media (once) and a relationship to it from the part being written."""
        if not src.startswith("data:") or "," not in src:
            return ""
        if src not in media:
            head, data = src.split(",", 1)
            ext = "jpeg" if "jpeg" in head or "jpg" in head else "png"
            name = f"image{len(media) + 1}.{ext}"
            files[f"ppt/media/{name}"] = base64.b64decode(data)
            media[src] = name
        rid = f"rId{len(rels) + 1}"
        rels.append(f'<Relationship Id="{rid}" Type="{R}/image" Target="../media/{media[src]}"/>')
        return rid

    # -- the layouts: one per Slides layout in use, and one more per design frame it's used with
    used = []
    for s in deck["slides"]:
        key = (s.get("layout", "content") if s.get("layout") in sm.LAYOUTS else "content", s.get("frame") if s.get("frame") in frames else "")
        if key not in used:
            used.append(key)
    if not used:
        used = [("content", "")]
    layout_files = {}
    for n, (lay, frame) in enumerate(used, 1):
        rels = [f'<Relationship Id="rId1" Type="{R}/slideMaster" Target="../slideMasters/slideMaster1.xml"/>']
        kind, name = LAYOUT_TYPES[lay]
        shapes, sid = "", 2
        for item in (frames.get(frame, {}).get("items", []) if frame else []):
            shapes += item_xml(dict(item, role=""), sid, lay, look, lambda src: media_for(src, rels), placeholders=False)
            sid += 1
        if not frame and look.get("deco") and lay in ("content", "two", "titleonly"):
            t = next(r for r in sm.placeholders(lay, deck.get("size", "16:9")) if r[0] == "title")
            bar = {"id": "deco", "kind": "shape", "shape": "rounded", "x": t[1] + sm.INSET_X, "y": t[2] + t[4] + 4, "w": 112, "h": 8, "fill": "accent1",
                   "name": "Huginn accent", "paras": []}
            shapes += item_xml(bar, sid, lay, look, None, placeholders=False)
            sid += 1
        for role, x, y, w, h in sm.placeholders(lay, deck.get("size", "16:9")):
            ph = sm.placeholder_item(role, f"ph{sid}", (x, y, w, h), lay)
            st = sm.role_style(role, lay)
            anchor = {"top": "t", "middle": "ctr", "bottom": "b"}[st["valign"]]
            shapes += (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{PH[role][1]} {sid}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
                       f'<p:nvPr><p:ph {ph_attr(role, lay)}/></p:nvPr></p:nvSpPr><p:spPr>{xfrm_xml(ph)}</p:spPr>'
                       f'<p:txBody><a:bodyPr anchor="{anchor}"><a:normAutofit/></a:bodyPr><a:lstStyle>{lvl_styles(look, role, lay)}</a:lstStyle>'
                       f'<a:p><a:r><a:rPr lang="en-US"/><a:t>{"Click to edit the title" if role == "title" else "Click to edit the text"}</a:t></a:r></a:p></p:txBody></p:sp>')
            sid += 1
        show = ' showMasterSp="0"' if frame else ""
        files[f"ppt/slideLayouts/slideLayout{n}.xml"] = (f'{HEAD}<p:sldLayout {NS} type="{kind}" preserve="1"{show}><p:cSld name="{name}">{TREE}{shapes}'
                                                         "</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>")
        files[f"ppt/slideLayouts/_rels/slideLayout{n}.xml.rels"] = f'{HEAD}<Relationships xmlns="{PKG}">{"".join(rels)}</Relationships>'
        ct.append(f'<Override PartName="/ppt/slideLayouts/slideLayout{n}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>')
        layout_files[(lay, frame)] = n

    # -- the master
    mrels = [f'<Relationship Id="rId{n}" Type="{R}/slideLayout" Target="../slideLayouts/slideLayout{n}.xml"/>' for n in range(1, len(used) + 1)]
    mrels.append(f'<Relationship Id="rId{len(used) + 1}" Type="{R}/theme" Target="../theme/theme1.xml"/>')
    deco = ""
    if look.get("deco") == "orb":
        orb = {"x": W * 0.68, "y": -sm.SLIDE_H * 0.45, "w": W * 0.5, "h": W * 0.5}
        deco = (f'<p:sp><p:nvSpPr><p:cNvPr id="9" name="Huginn orb"/><p:cNvSpPr/><p:nvPr userDrawn="1"/></p:nvSpPr><p:spPr>{xfrm_xml(orb)}'
                f'<a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="{hexval(look["accents"][0])}"><a:alpha val="10000"/>'
                "</a:srgbClr></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr></p:sp>")
    mbg = bg_xml(look["bg"], lambda src: media_for(src, mrels))
    title_rect, body_rect = sm.placeholders("content", deck.get("size", "16:9"))[:2]
    tph = sm.placeholder_item("title", "t", tuple(title_rect[1:]), "content")
    bph = sm.placeholder_item("body", "b", tuple(body_rect[1:]), "content")
    master_tree = (f'{TREE}{deco}<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
                   f'<p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:spPr>{xfrm_xml(tph)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
                   '<p:txBody><a:bodyPr anchor="ctr"><a:normAutofit/></a:bodyPr><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/><a:t>Title</a:t></a:r></a:p></p:txBody></p:sp>'
                   f'<p:sp><p:nvSpPr><p:cNvPr id="3" name="Text Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
                   f'<p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr>{xfrm_xml(bph)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
                   '<p:txBody><a:bodyPr><a:normAutofit/></a:bodyPr><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/><a:t>Text</a:t></a:r></a:p></p:txBody></p:sp></p:spTree>')
    other = "".join(f'<a:lvl{i}pPr marL="{emu((i - 1) * sm.INDENT)}" algn="l"><a:defRPr sz="2400"><a:solidFill><a:srgbClr val="{hexval(look["text"])}"/>'
                    f'</a:solidFill><a:latin typeface="+mn-lt"/></a:defRPr></a:lvl{i}pPr>' for i in range(1, 10))
    files["ppt/slideMasters/slideMaster1.xml"] = (
        f'{HEAD}<p:sldMaster {NS}><p:cSld>{mbg}{master_tree}</p:cSld>'
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
        'accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:sldLayoutIdLst>'
        + "".join(f'<p:sldLayoutId id="{2147483649 + n}" r:id="rId{n + 1}"/>' for n in range(len(used)))
        + f'</p:sldLayoutIdLst><p:txStyles><p:titleStyle>{lvl_styles(look, "title", "content")}</p:titleStyle>'
        f'<p:bodyStyle>{lvl_styles(look, "body", "content")}</p:bodyStyle><p:otherStyle>{other}</p:otherStyle></p:txStyles></p:sldMaster>')
    files["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = f'{HEAD}<Relationships xmlns="{PKG}">{"".join(mrels)}</Relationships>'
    files["ppt/theme/theme1.xml"] = theme_xml(look)

    # -- the slides
    slide_ids, pres_rels, notes_any = [], [], False
    for n, slide in enumerate(deck["slides"], 1):
        lay = slide.get("layout", "content") if slide.get("layout") in sm.LAYOUTS else "content"
        frame = slide.get("frame") if slide.get("frame") in frames else ""
        rels = [f'<Relationship Id="rId1" Type="{R}/slideLayout" Target="../slideLayouts/slideLayout{layout_files[(lay, frame)]}.xml"/>']
        ids, shapes, sid = {}, "", 2
        roles = set()
        for item in slide.get("items", []):
            role_ok = item.get("role") and item["role"] in [r[0] for r in sm.placeholders(lay)] and item["role"] not in roles
            roles.add(item.get("role"))
            ids[item["id"]] = sid
            shapes += item_xml(item if role_ok else dict(item, role=""), sid, lay, look, lambda src: media_for(src, rels))
            sid += 1
        bg = bg_xml(slide["bg"], lambda src: media_for(src, rels)) if slide.get("bg") else ""
        trans = slide.get("transition") or {}
        tr = ""
        if trans.get("kind") in TRANSITIONS:
            ms = int(trans.get("ms", 500))
            spd = "fast" if ms < 600 else "med" if ms < 900 else "slow"
            tr = (f'<mc:AlternateContent xmlns:mc="{MC}"><mc:Choice xmlns:p14="{P14}" Requires="p14"><p:transition spd="{spd}" p14:dur="{ms}">'
                  f'{TRANSITIONS[trans["kind"]]}</p:transition></mc:Choice><mc:Fallback><p:transition spd="{spd}">{TRANSITIONS[trans["kind"]]}'
                  "</p:transition></mc:Fallback></mc:AlternateContent>")
        hidden = ' show="0"' if slide.get("hidden") else ""
        files[f"ppt/slides/slide{n}.xml"] = (f'{HEAD}<p:sld {NS}{hidden}><p:cSld>{bg}{TREE}{shapes}</p:spTree></p:cSld>'
                                             f"<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>{tr}{timing_xml(slide, ids)}</p:sld>")
        if slide.get("notes", "").strip():
            notes_any = True
            rels.append(f'<Relationship Id="rId{len(rels) + 1}" Type="{R}/notesSlide" Target="../notesSlides/notesSlide{n}.xml"/>')
            paras = "".join(f'<a:p><a:r><a:rPr lang="en-US" dirty="0"/><a:t>{escape(line)}</a:t></a:r></a:p>' if line else "<a:p/>"
                            for line in slide["notes"].split("\n"))
            files[f"ppt/notesSlides/notesSlide{n}.xml"] = (
                f'{HEAD}<p:notes {NS}><p:cSld>{TREE}<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1" '
                'noRot="1" noChangeAspect="1"/></p:cNvSpPr><p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr><p:spPr/></p:sp>'
                '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" idx="1"/>'
                f'</p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{paras}</p:txBody></p:sp></p:spTree></p:cSld>'
                "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>")
            files[f"ppt/notesSlides/_rels/notesSlide{n}.xml.rels"] = (
                f'{HEAD}<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/notesMaster" Target="../notesMasters/notesMaster1.xml"/>'
                f'<Relationship Id="rId2" Type="{R}/slide" Target="../slides/slide{n}.xml"/></Relationships>')
            ct.append(f'<Override PartName="/ppt/notesSlides/notesSlide{n}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>')
        files[f"ppt/slides/_rels/slide{n}.xml.rels"] = f'{HEAD}<Relationships xmlns="{PKG}">{"".join(rels)}</Relationships>'
        ct.append(f'<Override PartName="/ppt/slides/slide{n}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
        slide_ids.append(f'<p:sldId id="{255 + n}" r:id="rId{n + 1}"/>')
        pres_rels.append(f'<Relationship Id="rId{n + 1}" Type="{R}/slide" Target="slides/slide{n}.xml"/>')

    k = len(deck["slides"]) + 2
    pres_rels.append(f'<Relationship Id="rId{k}" Type="{R}/theme" Target="theme/theme1.xml"/>')
    pres_rels.append(f'<Relationship Id="rId{k + 1}" Type="{R}/presProps" Target="presProps.xml"/>')
    pres_rels.append(f'<Relationship Id="rId{k + 2}" Type="{R}/viewProps" Target="viewProps.xml"/>')
    pres_rels.append(f'<Relationship Id="rId{k + 3}" Type="{R}/tableStyles" Target="tableStyles.xml"/>')
    notes_master = ""
    if notes_any:
        pres_rels.append(f'<Relationship Id="rId{k + 4}" Type="{R}/notesMaster" Target="notesMasters/notesMaster1.xml"/>')
        notes_master = f'<p:notesMasterIdLst><p:notesMasterId r:id="rId{k + 4}"/></p:notesMasterIdLst>'
        files["ppt/notesMasters/notesMaster1.xml"] = (
            f'{HEAD}<p:notesMaster {NS}><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>{TREE}'
            '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
            '<p:nvPr><p:ph type="sldImg" idx="2"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="381000" y="685800"/><a:ext cx="6096000" cy="3429000"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln w="12700"><a:solidFill><a:prstClr val="black"/></a:solidFill></a:ln></p:spPr></p:sp>'
            '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" sz="quarter" idx="3"/>'
            '</p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="685800" y="4343400"/><a:ext cx="5486400" cy="4114800"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            '</p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/><a:t>Notes</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>'
            '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
            'accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:notesStyle><a:lvl1pPr marL="0" algn="l"><a:defRPr sz="1200">'
            '<a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/></a:defRPr></a:lvl1pPr></p:notesStyle></p:notesMaster>')
        files["ppt/notesMasters/_rels/notesMaster1.xml.rels"] = (f'{HEAD}<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/theme" '
                                                                'Target="../theme/theme2.xml"/></Relationships>')
        files["ppt/theme/theme2.xml"] = theme_xml(sm.THEMES["paper"], "Notes")
        ct.append('<Override PartName="/ppt/notesMasters/notesMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"/>')
        ct.append('<Override PartName="/ppt/theme/theme2.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>')
    kind = "screen4x3" if deck.get("size") == "4:3" else "custom"
    files["ppt/presentation.xml"] = (f'{HEAD}<p:presentation {NS} saveSubsetFonts="1"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/>'
                                     f'</p:sldMasterIdLst>{notes_master}<p:sldIdLst>{"".join(slide_ids)}</p:sldIdLst>'
                                     f'<p:sldSz cx="{emu(W)}" cy="{emu(sm.SLIDE_H)}"{" type=" + chr(34) + kind + chr(34) if kind != "custom" else ""}/>'
                                     '<p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    files["ppt/_rels/presentation.xml.rels"] = (f'{HEAD}<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/slideMaster" '
                                                f'Target="slideMasters/slideMaster1.xml"/>{"".join(pres_rels)}</Relationships>')
    files["ppt/presProps.xml"] = f'{HEAD}<p:presentationPr {NS}/>'
    files["ppt/viewProps.xml"] = (f'{HEAD}<p:viewPr {NS}><p:normalViewPr><p:restoredLeft sz="15620"/><p:restoredTop sz="94660"/></p:normalViewPr>'
                                  '<p:gridSpacing cx="76200" cy="76200"/></p:viewPr>')
    files["ppt/tableStyles.xml"] = f'{HEAD}<a:tblStyleLst xmlns:a="{A}" def="{{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}}"/>'
    files["docProps/app.xml"] = (f'{HEAD}<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
                                 f'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>Huginn Slides</Application>'
                                 f'<Slides>{len(deck["slides"])}</Slides></Properties>')
    files["docProps/core.xml"] = (f'{HEAD}<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                                  'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title></dc:title></cp:coreProperties>')
    content_types = (f'{HEAD}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
                     '<Default Extension="jpeg" ContentType="image/jpeg"/>'
                     '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
                     '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
                     '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
                     '<Override PartName="/ppt/presProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"/>'
                     '<Override PartName="/ppt/viewProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"/>'
                     '<Override PartName="/ppt/tableStyles.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"/>'
                     '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                     '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
                     + "".join(ct) + "</Types>")
    root_rels = (f'{HEAD}<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/officeDocument" Target="ppt/presentation.xml"/>'
                 '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                 f'<Relationship Id="rId3" Type="{R}/extended-properties" Target="docProps/app.xml"/></Relationships>')
    tmp = str(path) + ".saving"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        for name, data in files.items():
            z.writestr(name, data if isinstance(data, bytes) else data.encode("utf-8"))
    import os
    os.replace(tmp, path)


# ============================================================================================== reading
class Read:
    """One PowerPoint file being read: parts, relationships, masters and layouts, the theme."""

    def __init__(self, path):
        self.z = zipfile.ZipFile(path)
        self.names = set(self.z.namelist())
        self.cache = {}
        self.dropped = {}

    def part(self, name: str):
        if name not in self.cache:
            try:
                self.cache[name] = ET.fromstring(self.z.read(name)) if name in self.names else None
            except ET.ParseError:
                self.cache[name] = None
        return self.cache[name]

    def rels(self, part: str) -> dict:
        folder, base = posixpath.split(part)
        root = self.part(posixpath.join(folder, "_rels", base + ".rels"))
        out = {}
        for rel in (root if root is not None else []):
            target = rel.get("Target", "")
            if rel.get("TargetMode") == "External":
                continue
            full = posixpath.normpath(posixpath.join(folder, target)) if not target.startswith("/") else target.lstrip("/")
            out[rel.get("Id")] = (full, rel.get("Type", "").rsplit("/", 1)[-1])
        return out

    def target(self, part: str, kind: str) -> str:
        return next((t for t, k in self.rels(part).values() if k == kind), "")

    def drop(self, what: str, n: int = 1) -> None:
        self.dropped[what] = self.dropped.get(what, 0) + n


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _apply_mods(hexc: str, node) -> str:
    """lumMod / lumOff / tint / shade on a colour, as PowerPoint's theme variations use them."""
    r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4))
    for m in node:
        tag, val = m.tag.split("}")[-1], _int(m.get("val"), 100000) / 100000
        if tag in ("lumMod", "lumOff"):
            h, light, s = colorsys.rgb_to_hls(r, g, b)
            light = light * val if tag == "lumMod" else min(1.0, light + val)
            r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, light)), s)
        elif tag == "tint":
            r, g, b = (c + (1 - c) * (1 - val) for c in (r, g, b))
        elif tag == "shade":
            r, g, b = (c * val for c in (r, g, b))
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in (r, g, b))


class Theme:
    def __init__(self, root, clr_map: dict):
        self.colours, self.major, self.minor = {}, "Calibri Light", "Calibri"
        self.map = clr_map or {}
        if root is None:
            return
        scheme = root.find(f".//{a_('clrScheme')}")
        for node in (scheme if scheme is not None else []):
            name = node.tag.split("}")[-1]
            c = node[0] if len(node) else None
            if c is None:
                continue
            val = c.get("val") if c.tag == a_("srgbClr") else c.get("lastClr") or ("000000" if c.get("val") == "windowText" else "FFFFFF")
            self.colours[name] = (val or "000000").upper()
        maj, mnr = root.find(f".//{a_('majorFont')}/{a_('latin')}"), root.find(f".//{a_('minorFont')}/{a_('latin')}")
        self.major = maj.get("typeface") if maj is not None and maj.get("typeface") else self.major
        self.minor = mnr.get("typeface") if mnr is not None and mnr.get("typeface") else self.minor

    def scheme(self, name: str) -> str:
        name = self.map.get(name, name)
        return self.colours.get(name, "000000")

    def colour(self, node, accent_names: bool = False) -> str:
        """A colour element (srgbClr, schemeClr, sysClr, prstClr) → '#RRGGBB' (or 'accentN' when asked and it is one, plain)."""
        if node is None:
            return ""
        tag = node.tag.split("}")[-1]
        if tag == "srgbClr":
            base = (node.get("val") or "000000").upper()
        elif tag == "schemeClr":
            val = node.get("val", "")
            if accent_names and val.startswith("accent") and len(node) == 0:
                return val
            base = self.scheme(val)
        elif tag == "sysClr":
            base = (node.get("lastClr") or "000000").upper()
        elif tag == "prstClr":
            base = {"black": "000000", "white": "FFFFFF", "red": "FF0000", "green": "008000", "blue": "0000FF"}.get(node.get("val"), "000000")
        elif tag == "scrgbClr":
            base = "".join(f"{round(_int(node.get(k)) / 100000 * 255):02X}" for k in ("r", "g", "b"))
        else:
            return ""
        return _apply_mods(base, node) if len(node) else "#" + base

    def fill(self, holder, accent_names: bool = False):
        """The fill inside an spPr/bgPr-like element: '#…'/'accentN', '' for none, None when it doesn't say."""
        if holder is None:
            return None
        if holder.find(a_("noFill")) is not None:
            return ""
        solid = holder.find(a_("solidFill"))
        if solid is not None and len(solid):
            return self.colour(solid[0], accent_names)
        grad = holder.find(a_("gradFill"))
        if grad is not None:
            stops = grad.findall(f"{a_('gsLst')}/{a_('gs')}")
            if stops and len(stops[0]):
                return self.colour(stops[0][0], accent_names)
        return None

    def font(self, face: str) -> str:
        if face.startswith("+mj"):
            return self.major
        if face.startswith("+mn"):
            return self.minor
        return face


class Master:
    """A slide master or layout: its placeholders (by idx and type), text styles and background."""

    def __init__(self, rd: Read, part: str, theme: Theme, parent=None):
        self.part, self.parent, self.theme = part, parent, theme
        root = rd.part(part)
        self.root = root
        self.ph = {}
        self.decor = []
        self.show_master = root is None or root.get("showMasterSp", "1") not in ("0", "false")
        tree = root.find(f"{p_('cSld')}/{p_('spTree')}") if root is not None else None
        for sp in (tree if tree is not None else []):
            ph = sp.find(f".//{p_('nvPr')}/{p_('ph')}")
            if ph is not None:
                kind = ph.get("type", "body" if ph.get("idx") else "obj")
                self.ph.setdefault(("idx", ph.get("idx")), sp) if ph.get("idx") else None
                self.ph.setdefault(("type", kind), sp)
            elif sp.tag in (p_("sp"), p_("pic"), p_("grpSp"), p_("cxnSp")):
                self.decor.append(sp)
        self.styles = {}
        tx = root.find(p_("txStyles")) if root is not None else None
        if tx is not None:
            for name in ("titleStyle", "bodyStyle", "otherStyle"):
                el = tx.find(p_(name))
                if el is not None:
                    self.styles[name] = el
        bg = root.find(f"{p_('cSld')}/{p_('bg')}") if root is not None else None
        self.bg = bg

    def find(self, kind: str, idx):
        """The placeholder a slide's placeholder takes after: by idx first, then by type."""
        if idx is not None and ("idx", idx) in self.ph:
            sp = self.ph[("idx", idx)]
            got = sp.find(f".//{p_('nvPr')}/{p_('ph')}")
            if got is not None and _same_kind(got.get("type", "body" if got.get("idx") else "obj"), kind):
                return sp
        for k in _kinds(kind):
            if ("type", k) in self.ph:
                return self.ph[("type", k)]
        if idx is not None and ("idx", idx) in self.ph:
            return self.ph[("idx", idx)]
        return None


def _kinds(kind: str) -> list:
    if kind in ("title", "ctrTitle"):
        return [kind, "title", "ctrTitle"]
    if kind in ("body", "obj", "subTitle"):
        return [kind, "body", "obj", "subTitle"]
    return [kind]


def _same_kind(a: str, b: str) -> bool:
    return a == b or (a in ("body", "obj", "subTitle") and b in ("body", "obj", "subTitle")) or (a in ("title", "ctrTitle") and b in ("title", "ctrTitle"))


def _xfrm(sp):
    x = sp.find(f"{p_('spPr')}/{a_('xfrm')}")
    if x is None:
        x = sp.find(f"{p_('grpSpPr')}/{a_('xfrm')}")
    if x is None:
        x = sp.find(f"{p_('xfrm')}")
    return x


def _lvl_props(el, lvl: int, theme: Theme, into: dict) -> None:
    """Merge one lstStyle-like element's level (lvlNpPr) into the running properties."""
    if el is None:
        return
    node = el.find(a_(f"lvl{lvl + 1}pPr"))
    if node is None and lvl == 0:
        node = el.find(a_("defPPr"))
    if node is not None:
        _ppr_props(node, theme, into)


def _ppr_props(node, theme: Theme, into: dict) -> None:
    if node.get("algn"):
        into["align"] = {"l": "left", "ctr": "center", "r": "right", "just": "justify", "dist": "justify"}.get(node.get("algn"), "left")
    if node.find(a_("buNone")) is not None:
        into["list"] = ""
    elif node.find(a_("buChar")) is not None:
        into["list"] = "bullet"
    elif node.find(a_("buAutoNum")) is not None:
        into["list"] = "number"
    ln = node.find(f"{a_('lnSpc')}/{a_('spcPct')}")
    if ln is not None:
        into["spacing"] = _int(ln.get("val"), 100000) / 100000
    d = node.find(a_("defRPr"))
    if d is not None:
        _rpr_props(d, theme, into)


def _rpr_props(node, theme: Theme, into: dict) -> None:
    if node.get("sz"):
        into["size"] = _int(node.get("sz"), 1800) / 100
    for attr, key in (("b", "b"), ("i", "i")):
        if node.get(attr) is not None:
            into[key] = node.get(attr) in ("1", "true")
    if node.get("u") is not None:
        into["u"] = node.get("u") not in ("none", "")
    if node.get("strike") is not None:
        into["s"] = node.get("strike") not in ("noStrike", "")
    fill = theme.fill(node)
    if fill:
        into["color"] = fill
    latin = node.find(a_("latin"))
    if latin is not None and latin.get("typeface"):
        into["font"] = theme.font(latin.get("typeface"))


def read(path) -> tuple:
    """(deck, dropped) from a .pptx."""
    rd = Read(path)
    pres = rd.part("ppt/presentation.xml")
    if pres is None:
        raise ValueError("this doesn't look like a PowerPoint presentation")
    size_el = pres.find(p_("sldSz"))
    cx, cy = (_int(size_el.get("cx"), 12192000), _int(size_el.get("cy"), 6858000)) if size_el is not None else (12192000, 6858000)
    size = "4:3" if abs(cx / cy - 4 / 3) < 0.05 else "16:9"
    W = sm.slide_w(size)
    sx, sy = W / cx, sm.SLIDE_H / cy                 # slide units per EMU, each way
    rels = rd.rels("ppt/presentation.xml")
    order = [rels[s.get(q(R, "id"))][0] for s in pres.iter(p_("sldId")) if s.get(q(R, "id")) in rels]
    masters, themes = {}, {}

    def master_of(part: str):
        if part not in masters:
            mroot = rd.part(part)
            cmap = {}
            cm = mroot.find(p_("clrMap")) if mroot is not None else None
            if cm is not None:
                cmap = dict(cm.attrib)
            tpart = rd.target(part, "theme")
            if tpart not in themes:
                themes[tpart] = rd.part(tpart)
            masters[part] = Master(rd, part, Theme(themes[tpart], cmap))
        return masters[part]

    layouts = {}

    def layout_of(part: str):
        if part not in layouts:
            mpart = rd.target(part, "slideMaster")
            m = master_of(mpart)
            layouts[part] = Master(rd, part, m.theme, m)
        return layouts[part]

    slides, first_theme = [], None
    deck_bg = None
    counter = [0]

    def nid():
        counter[0] += 1
        return f"i{counter[0]}"

    def pic_src(part: str, blip, crop=None) -> str:
        rid = blip.get(q(R, "embed")) if blip is not None else None
        target = rd.rels(part).get(rid, ("", ""))[0] if rid else ""
        if not target or target not in rd.names:
            return ""
        data = rd.z.read(target)
        ext = target.rsplit(".", 1)[-1].lower()
        if ext not in ("png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp"):
            rd.drop("pictures in a format Slides can't show (" + ext.upper() + ")")
            return ""
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QImage
        img = QImage()
        if not img.loadFromData(data):
            return ""
        if crop is not None and any(_int(crop.get(k)) for k in ("l", "t", "r", "b")):
            l_, t_, r_, b_ = (_int(crop.get(k)) / 100000 for k in ("l", "t", "r", "b"))
            img = img.copy(round(img.width() * l_), round(img.height() * t_), max(1, round(img.width() * (1 - l_ - r_))),
                           max(1, round(img.height() * (1 - t_ - b_))))
        elif ext in ("png", "jpg", "jpeg") and img.width() <= 3000 and img.height() <= 3000:
            return f"data:image/{'jpeg' if ext in ('jpg', 'jpeg') else 'png'};base64," + base64.b64encode(data).decode()
        if max(img.width(), img.height()) > 3000:
            from PySide6.QtCore import Qt
            img = img.scaled(3000, 3000, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        kind = "png" if img.hasAlphaChannel() else "jpeg"
        img.save(buf, kind.upper(), 90)
        return f"data:image/{kind};base64," + base64.b64encode(bytes(ba)).decode()

    def bg_of(bg_el, part: str, theme: Theme):
        if bg_el is None:
            return None
        pr = bg_el.find(p_("bgPr"))
        if pr is not None:
            blip = pr.find(f"{a_('blipFill')}/{a_('blip')}")
            if blip is not None:
                src = pic_src(part, blip)
                return {"picture": src} if src else None
            grad = pr.find(a_("gradFill"))
            if grad is not None:
                stops = [s for s in grad.findall(f"{a_('gsLst')}/{a_('gs')}") if len(s)]
                if stops:
                    lin = grad.find(a_("lin"))
                    ang = _int(lin.get("ang")) / 60000 if lin is not None else 90
                    return {"from": theme.colour(stops[0][0]), "to": theme.colour(stops[-1][0]), "angle": 0 if round(ang) % 180 == 0 else 90}
            c = theme.fill(pr)
            return {"color": c} if c else None
        ref = bg_el.find(p_("bgRef"))
        if ref is not None and len(ref):
            return {"color": theme.colour(ref[0])}
        return None

    def items_from(tree, part: str, theme: Theme, chain_for, layout_key: str, offset=None, locked=False) -> list:
        """The items in a shape tree; chain_for(sp) gives the placeholder chain (or None)."""
        out = []
        body_seen = 0
        for sp in (tree if tree is not None else []):
            tag = sp.tag.split("}")[-1]
            if tag == "grpSp":
                gx = sp.find(f"{p_('grpSpPr')}/{a_('xfrm')}")
                sub = None
                if gx is not None:
                    off, ext, choff, chext = gx.find(a_("off")), gx.find(a_("ext")), gx.find(a_("chOff")), gx.find(a_("chExt"))
                    if None not in (off, ext, choff, chext):
                        kx = _int(ext.get("cx")) / max(1, _int(chext.get("cx"))) if _int(chext.get("cx")) else 1
                        ky = _int(ext.get("cy")) / max(1, _int(chext.get("cy"))) if _int(chext.get("cy")) else 1
                        sub = (_int(off.get("x")) - _int(choff.get("x")) * kx, _int(off.get("y")) - _int(choff.get("y")) * ky, kx, ky)
                        if offset:
                            ox, oy, okx, oky = offset
                            sub = (ox + sub[0] * okx, oy + sub[1] * oky, sub[2] * okx, sub[3] * oky)
                    if _int(gx.get("rot")):
                        rd.drop("rotation of grouped shapes")
                out += items_from(sp, part, theme, chain_for, layout_key, sub or offset, locked)
                continue
            if tag not in ("sp", "pic", "cxnSp", "graphicFrame"):
                continue
            ph = sp.find(f".//{p_('nvPr')}/{p_('ph')}")
            kind_ph = ph.get("type", "body" if ph.get("idx") else "obj") if ph is not None else None
            if kind_ph in ("dt", "ftr", "sldNum", "hdr"):
                if any(t.text for t in sp.iter(a_("t"))) and not locked:
                    rd.drop("footers, dates and slide numbers")
                continue
            chain = chain_for(kind_ph, ph.get("idx") if ph is not None else None) if ph is not None else []
            xf = _xfrm(sp)
            for c in chain:
                if xf is not None and xf.find(a_("off")) is not None:
                    break
                xf = _xfrm(c)
            if xf is None or xf.find(a_("off")) is None:
                continue
            off, ext = xf.find(a_("off")), xf.find(a_("ext"))
            x, y = _int(off.get("x")), _int(off.get("y"))
            w, h = (_int(ext.get("cx")), _int(ext.get("cy"))) if ext is not None else (0, 0)
            if offset:
                ox, oy, kx, ky = offset
                x, y, w, h = ox + x * kx, oy + y * ky, w * kx, h * ky
            base = {"id": nid(), "x": round(x * sx, 2), "y": round(y * sy, 2), "w": round(w * sx, 2), "h": round(h * sy, 2),
                    "rot": round(_int(xf.get("rot")) / 60000, 2) % 360, "role": ""}
            if xf.get("flipH") in ("1", "true"):
                base["flipH"] = True
            if xf.get("flipV") in ("1", "true"):
                base["flipV"] = True
            if locked:
                base["locked"] = True
            cnv = sp.find(f".//{p_('cNvPr')}")
            if cnv is not None and not locked:
                base["_spid"] = cnv.get("id")
            if tag == "graphicFrame":
                tbl = sp.find(f".//{a_('tbl')}")
                if tbl is not None:
                    out += table_items(tbl, base, theme, layout_key)
                else:
                    rd.drop("charts and diagrams")
                continue
            if tag == "pic":
                blip = sp.find(f"{p_('blipFill')}/{a_('blip')}")
                src = pic_src(part, blip, sp.find(f"{p_('blipFill')}/{a_('srcRect')}"))
                if src:
                    out.append(dict(base, kind="picture", src=src, alt=(cnv.get("descr", "") if cnv is not None else "")))
                elif blip is not None and blip.get(q(R, "link")):
                    rd.drop("linked pictures")
                continue
            # a shape or a text box
            sppr = sp.find(p_("spPr"))
            geom = sppr.find(a_("prstGeom")) if sppr is not None else None
            prst = geom.get("prst", "rect") if geom is not None else ("rect" if sppr is None or sppr.find(a_("custGeom")) is None else "custom")
            if prst == "custom":
                rd.drop("freeform shapes (drawn as rectangles)")
            inv = {v: k for k, v in PRESETS.items() if k not in ("arrowline",)}
            inv.update({"roundRect": "rounded", "snipRect": "rect", "round2SameRect": "rounded", "flowChartProcess": "rect", "flowChartAlternateProcess": "rounded",
                        "flowChartDecision": "diamond", "flowChartConnector": "ellipse", "straightConnector1": "line", "bentConnector3": "line",
                        "wedgeRoundRectCallout": "callout", "wedgeEllipseCallout": "callout", "homePlate": "chevron", "star4": "star", "star6": "star",
                        "upArrow": "arrow", "downArrow": "arrow", "triangle": "triangle", "frame": "rect", "can": "rect", "cube": "rect", "octagon": "hexagon"})
            shape = inv.get(prst)
            if shape is None:
                shape = "rect"
                if prst not in ("rect", "custom"):
                    rd.drop("shapes Slides doesn't have (drawn as rectangles)")
            style = sp.find(p_("style"))
            fill = theme.fill(sppr, True) if sppr is not None else None
            if fill is None and style is not None:
                ref = style.find(a_("fillRef"))
                fill = theme.colour(ref[0], True) if ref is not None and len(ref) and _int(ref.get("idx")) > 0 else None
            ln_el = sppr.find(a_("ln")) if sppr is not None else None
            line = theme.fill(ln_el, True) if ln_el is not None else None
            if line is None and style is not None:
                ref = style.find(a_("lnRef"))
                line = theme.colour(ref[0], True) if ref is not None and len(ref) and _int(ref.get("idx")) > 0 else None
            line_w = _int(ln_el.get("w"), 12700) * sy if ln_el is not None and ln_el.get("w") else (12700 * sy if line else 0)
            txb = sp.find(p_("txBody"))
            is_line = tag == "cxnSp" or shape == "line"
            role = ""
            if kind_ph in ("title", "ctrTitle"):
                role = "title"
            elif kind_ph == "subTitle":
                role = "subtitle"
            elif kind_ph in ("body", "obj") and kind_ph is not None:
                role = "body" if body_seen == 0 else "body2"
                body_seen += 1
            elif kind_ph is not None and kind_ph not in ("pic",):
                role = ""
            visual = bool(fill) or (bool(line) and line_w > 0) or is_line
            if is_line:
                tail = ln_el.find(a_("tailEnd")) if ln_el is not None else None
                head = ln_el.find(a_("headEnd")) if ln_el is not None else None
                arrow = any(e is not None and e.get("type", "none") != "none" for e in (tail, head))
                item = dict(base, kind="shape", shape="arrowline" if arrow else "line", fill="", line=line or fill or "accent1", lineW=round(max(1.0, line_w), 2))
                if head is not None and head.get("type", "none") != "none" and (tail is None or tail.get("type", "none") == "none"):
                    item["flipH"], item["flipV"] = not item.get("flipH", False), not item.get("flipV", False)
                out.append(item)
                continue
            if role or not visual:
                item = dict(base, kind="text", role=role)
                if not role:
                    bp = txb.find(a_("bodyPr")) if txb is not None else None
                    item["grow"] = bp is not None and bp.find(a_("spAutoFit")) is not None
            else:
                item = dict(base, kind="shape", shape=shape, fill=fill or "", line=line or "", lineW=round(line_w, 2) if line else 0)
            if txb is not None:
                paras, anchor = text_of_body(txb, chain, kind_ph, theme, layout_key, item, style)
                item["paras"] = paras
                if anchor:
                    item["valign"] = anchor
            else:
                item["paras"] = [{"runs": [], "lvl": 0, "list": "", "align": ""}]
            if item["kind"] == "text" and not role and not sm.has_text(item):
                continue                       # an empty text box
            item.setdefault("valign", "")
            item["fit"] = 1.0
            out.append(item)
        return out

    def table_items(tbl, base: dict, theme: Theme, layout_key: str) -> list:
        """A table as its cells: a rectangle with text for each, where it is."""
        cols = [_int(g.get("w")) * sx for g in tbl.findall(f"{a_('tblGrid')}/{a_('gridCol')}")]
        out, y = [], base["y"]
        rows = tbl.findall(a_("tr"))
        total_h = sum(_int(r.get("h")) for r in rows) * sy or base["h"]
        k = max(1.0, base["h"] / total_h) if total_h else 1.0
        for r_i, tr in enumerate(rows):
            h = _int(tr.get("h")) * sy * k
            x = base["x"]
            for c_i, tc in enumerate(tr.findall(a_("tc"))):
                w = cols[c_i] if c_i < len(cols) else 100
                span = _int(tc.get("gridSpan"), 1)
                w = sum(cols[c_i:c_i + span]) if span > 1 else w
                if tc.get("hMerge") in ("1", "true") or tc.get("vMerge") in ("1", "true"):
                    x += cols[c_i] if c_i < len(cols) else 100
                    continue
                tcpr = tc.find(a_("tcPr"))
                fill = theme.fill(tcpr, True) if tcpr is not None else None
                heading = fill is None and r_i == 0 and tbl.find(f"{a_('tblPr')}") is not None and tbl.find(a_("tblPr")).get("firstRow") in ("1", "true")
                if heading:
                    fill = "accent1"                    # the usual table style: a coloured heading row in white
                cell = {"id": nid(), "kind": "shape", "shape": "rect", "x": round(x, 2), "y": round(y, 2), "w": round(w, 2),
                        "h": round(h * _int(tc.get("rowSpan"), 1), 2), "rot": 0, "role": "", "fill": fill or "", "line": "#BFBFBF", "lineW": 1.5, "valign": "middle"}
                txb = tc.find(a_("txBody"))
                paras, _ = text_of_body(txb, [], None, theme, layout_key, cell, None, "#FFFFFF" if heading else "") if txb is not None else ([{"runs": []}], "")
                for p in paras:
                    if not p.get("align"):
                        p["align"] = "left"
                cell["paras"] = paras
                cell["fit"] = 1.0
                out.append(cell)
                x += cols[c_i] if c_i < len(cols) else 100
            y += h
        rd.drop("tables (as separate cells)")
        return out

    def text_of_body(txb, chain, kind_ph, theme: Theme, layout_key: str, item: dict, style, colour_over: str = "") -> tuple:
        """The paragraphs of a txBody, every property resolved through the placeholder chain and the master's styles."""
        master = current["master"]
        style_name = "titleStyle" if kind_ph in ("title", "ctrTitle") else "bodyStyle" if kind_ph is not None else "otherStyle"
        lists = [master.styles.get(style_name)] if master is not None and kind_ph is not None else []
        for c in reversed(chain):
            lists.append(c.find(f"{p_('txBody')}/{a_('lstStyle')}"))
        lists.append(txb.find(a_("lstStyle")))
        anchor = ""
        for c in list(reversed(chain)) + [None]:
            bp = (c.find(f"{p_('txBody')}/{a_('bodyPr')}") if c is not None else txb.find(a_("bodyPr")))
            if bp is not None and bp.get("anchor"):
                anchor = {"t": "top", "ctr": "middle", "b": "bottom"}.get(bp.get("anchor"), "top")
        if item["kind"] == "shape" and not anchor:
            anchor = "middle"
        font_ref = style.find(a_("fontRef")) if style is not None else None
        ref_colour = colour_over or (theme.colour(font_ref[0]) if font_ref is not None and len(font_ref) else "")
        paras = []
        for p in txb.findall(a_("p")):
            ppr = p.find(a_("pPr"))
            lvl = _int(ppr.get("lvl")) if ppr is not None else 0
            props = {"size": 18.0, "b": False, "i": False, "u": False, "s": False, "color": ref_colour or theme.scheme("tx1") and "#" + theme.scheme("tx1"),
                     "font": theme.minor if kind_ph not in ("title", "ctrTitle") else theme.major, "align": "left", "list": "", "spacing": 0}
            if master is not None and kind_ph is None:
                _lvl_props(current["deflist"], lvl, theme, props)
            for el in lists:
                _lvl_props(el, lvl, theme, props)
            if ref_colour:                      # a shape's own style colours its text, over the presentation's defaults
                props["color"] = ref_colour
            if ppr is not None:
                _ppr_props(ppr, theme, props)
            para = {"runs": [], "lvl": lvl, "list": props["list"], "align": ""}
            dflt = sm.para_defaults(item, para, layout_key, current["look"])
            if props["align"] != dflt["align"]:
                para["align"] = props["align"]
            if props.get("spacing") and abs(props["spacing"] - (0.95 if item.get("role") == "title" else 1.0)) > 0.02:
                para["spacing"] = round(props["spacing"], 2)
            for node in p:
                tag = node.tag.split("}")[-1]
                if tag in ("r", "fld", "br"):
                    rp = dict(props)
                    rpr = node.find(a_("rPr"))
                    if rpr is not None:
                        _rpr_props(rpr, theme, rp)
                    text = "\n" if tag == "br" else "".join(t.text or "" for t in node.findall(a_("t")))
                    if not text:
                        continue
                    run = {"t": text}
                    for key in ("b", "i", "u", "s"):
                        if bool(rp[key]) != bool(dflt[key]):
                            run[key] = bool(rp[key])
                    if abs(float(rp["size"]) - float(dflt["size"])) > 0.26:
                        run["size"] = rp["size"]
                    if rp["font"] and rp["font"] != dflt["font"]:
                        run["font"] = rp["font"]
                    if rp["color"] and rp["color"].upper() != dflt["color"].upper():
                        run["color"] = rp["color"].upper()
                    last = para["runs"][-1] if para["runs"] else None
                    if last is not None and {k: v for k, v in last.items() if k != "t"} == {k: v for k, v in run.items() if k != "t"}:
                        last["t"] += text
                    else:
                        para["runs"].append(run)
            paras.append(para)
        return paras or [{"runs": [], "lvl": 0, "list": "", "align": ""}], anchor

    current = {"master": None, "look": None, "deflist": None}
    deflist = pres.find(p_("defaultTextStyle"))
    current["deflist"] = deflist
    LAYOUT_KEYS = {"title": "title", "secHead": "section", "twoObj": "two", "twoTxTwoObj": "two", "twoColTx": "two", "titleOnly": "titleonly",
                   "blank": "blank", "obj": "content", "tx": "content", "txAndObj": "content", "objAndTx": "content", "picTx": "content"}
    for n, part in enumerate(order[:800]):
        root = rd.part(part)
        if root is None:
            continue
        lpart = rd.target(part, "slideLayout")
        lay = layout_of(lpart) if lpart else None
        master = lay.parent if lay is not None else None
        theme = (master or lay).theme if (master or lay) else Theme(None, {})
        ovr = root.find(f"{p_('clrMapOvr')}/{a_('overrideClrMapping')}")
        if ovr is not None:
            theme = Theme(None, dict(ovr.attrib))
            theme.colours, theme.major, theme.minor = (master.theme.colours, master.theme.major, master.theme.minor) if master else ({}, "Calibri Light", "Calibri")
        if first_theme is None:
            first_theme = theme
            look = {"name": "From the file", "title": "#" + theme.scheme("tx1"), "text": "#" + theme.scheme("tx1"),
                    "accents": ["#" + theme.colours.get(f"accent{i}", "4472C4") for i in range(1, 7)], "head": theme.major, "body": theme.minor,
                    "deco": "", "bg": {"color": "#" + theme.scheme("bg1")}, "frames": {}}
            if master is not None:
                ts = master.styles.get("titleStyle")
                props = {"color": ""}
                _lvl_props(ts, 0, theme, props)
                if props.get("color"):
                    look["title"] = props["color"]
                bs = master.styles.get("bodyStyle")
                props = {"color": ""}
                _lvl_props(bs, 0, theme, props)
                if props.get("color"):
                    look["text"] = props["color"]
                deck_bg = bg_of(master.bg, master.part, theme)
                if deck_bg:
                    look["bg"] = deck_bg
            current["look"] = look
        lay_type = lay.root.get("type", "obj") if lay is not None and lay.root is not None else "obj"
        key = LAYOUT_KEYS.get(lay_type, "content")
        current["master"] = master

        def chain_for(kind, idx, lay=lay, master=master):
            chain = []
            got = lay.find(kind, idx) if lay is not None else None
            if got is not None:
                chain.append(got)
            mk = "title" if kind in ("title", "ctrTitle") else "body"
            got = master.find(mk, None) if master is not None else None
            if got is not None:
                chain.append(got)
            return chain

        tree = root.find(f"{p_('cSld')}/{p_('spTree')}")
        items = items_from(tree, part, theme, chain_for, key)
        # the design behind: the master's and the layout's own shapes, kept once per layout as a frame
        frame = ""
        if lay is not None:
            fid = lpart.rsplit("/", 1)[-1].replace(".xml", "")
            if fid not in current["look"]["frames"]:
                deco = []
                show_master = lay.show_master and root.get("showMasterSp", "1") not in ("0", "false")
                if master is not None and show_master:
                    deco += items_from(master.decor, master.part, theme, lambda k, i: [], key, locked=True)
                deco += items_from(lay.decor, lay.part, theme, lambda k, i: [], key, locked=True)
                current["look"]["frames"][fid] = {"items": deco}
            if current["look"]["frames"][fid]["items"]:
                frame = fid
        bg = bg_of(root.find(f"{p_('cSld')}/{p_('bg')}"), part, theme)
        if bg is None and lay is not None:
            bg = bg_of(lay.bg, lay.part, theme)
        if bg == current["look"]["bg"]:
            bg = None
        notes = ""
        npart = rd.target(part, "notesSlide")
        nroot = rd.part(npart) if npart else None
        for sp in (nroot.iter(p_("sp")) if nroot is not None else []):
            ph = sp.find(f".//{p_('nvPr')}/{p_('ph')}")
            if ph is not None and ph.get("type") == "body":
                notes = "\n".join("".join(t.text or "" for t in par.iter(a_("t"))) for par in sp.iter(a_("p"))).strip()
        trans = {"kind": "none", "ms": 500}
        tr = root.find(f".//{p_('transition')}")
        if tr is not None:
            kinds = [c.tag.split("}")[-1] for c in tr]
            kind = next((k for k in kinds), "")
            mapped = {"fade": "fade", "dissolve": "fade", "push": "push", "pull": "push", "wipe": "wipe", "split": "wipe", "strips": "wipe",
                      "zoom": "zoom", "newsflash": "zoom", "cover": "cover", "cut": "none"}.get(kind, "fade" if kind else "none")
            dur = tr.get(q(P14, "dur"))
            ms = _int(dur, 0) or {"fast": 500, "med": 750, "slow": 1000}.get(tr.get("spd", "med"), 750)
            trans = {"kind": mapped, "ms": ms}
            if mapped not in ("none", kind) and kind not in ("dissolve", "pull", "split", "strips", "newsflash"):
                rd.drop("transitions Slides doesn't have (shown as fades)")
        builds = read_timing(root, tree, items)
        if builds:
            rd.drop("builds other than entrances", builds)
        for it in items:
            it.pop("_spid", None)
        slides.append({"id": f"s{n + 1}", "layout": key, "items": items, "notes": notes, "bg": bg, "transition": trans,
                       "hidden": root.get("show", "1") in ("0", "false"), "frame": frame})
    if not slides:
        raise ValueError("the presentation has no slides")
    look = current["look"]
    if not any(f["items"] for f in look["frames"].values()):
        look["frames"] = {}
    deck = {"format": "huginn-slides-2", "theme": "paper", "look": look, "size": size, "slides": slides}
    for s in slides:
        for it in s["items"]:
            if it.get("role") and it["kind"] == "text":
                it["fit"] = sm.fit_scale(it, s["layout"], sm.look_of(deck))
            elif it["kind"] == "text" and it.get("grow"):
                need = sm.text_height(it, s["layout"], sm.look_of(deck), it["w"] - 2 * sm.INSET_X) + 2 * sm.INSET_Y
                it["h"] = round(max(it["h"], need), 2)
    dropped = []
    for what, count in rd.dropped.items():
        dropped.append(what if count == 1 or what.startswith(("footers", "tables", "rotation")) else f"{what} ({count})")
    return deck, dropped


def read_timing(root, tree, items: list) -> int:
    """Entrance effects become builds; returns how many other effects there were (emphasis, exits, paths)."""
    timing = root.find(p_("timing"))
    if timing is None:
        return 0
    by_spid = {it["_spid"]: it for it in items if it.get("_spid")}
    other, order = 0, 0
    for ctn in timing.iter(p_("cTn")):
        if ctn.get("nodeType") not in ("clickEffect", "withEffect", "afterEffect"):
            continue
        cls = ctn.get("presetClass", "")
        tgt = ctn.find(f".//{p_('spTgt')}")
        if tgt is None:
            continue
        if cls != "entr":
            other += 1
            continue
        item = by_spid.get(tgt.get("spid"))
        if item is None:
            continue
        preset = _int(ctn.get("presetID"))
        kind = {1: "appear", 10: "fade", 2: "rise", 42: "rise", 47: "rise", 53: "zoom", 21: "zoom", 23: "zoom"}.get(preset, "fade")
        by_para = ctn.find(f".//{p_('pRg')}") is not None
        if item.get("anim"):
            continue
        order += 1
        item["anim"] = {"kind": kind, "byPara": by_para, "order": order, "ms": 500}
    return other
