"""Emmet abbreviations for Code: `ul>li.item$*3` and Tab becomes the markup; `m10-20` in a stylesheet becomes
`margin: 10px 20px;`. Written from Emmet's published syntax (docs.emmet.io); none of its code is used.

    expand(abbreviation)           HTML, as a snippet (${1}, ${2} … where to type, ${0} last), or None
    expand_css(abbreviation)       a CSS declaration, or None
    abbreviation_before(text, kind)  the abbreviation that ends a line of text ("" when what's there isn't one)

HTML:   tag  #id  .class  [attr=value other]  {text}  >child  +sibling  ^climb  *times  (group)  $ numbering
        a missing tag name is div (li in a list, td in a row, option in a select, span inside inline tags);
        ! is a page's skeleton; a:mail, link:css, script:src, input:email, btn and their like are known.
"""
import re

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
INLINE = {"a", "abbr", "b", "button", "cite", "code", "em", "i", "img", "input", "kbd", "label", "mark", "option", "q", "s", "small", "span", "strong", "sub", "sup",
          "time", "u", "var", "td", "th", "li", "title", "h1", "h2", "h3", "h4", "h5", "h6", "p", "dt", "dd", "legend", "caption", "summary", "figcaption", "textarea", "select"}
TAGS = VOID | INLINE | {"html", "head", "body", "div", "main", "header", "footer", "nav", "section", "article", "aside", "ul", "ol", "dl", "table", "thead", "tbody", "tfoot",
                        "tr", "form", "fieldset", "figure", "picture", "video", "audio", "canvas", "svg", "iframe", "script", "style", "template", "details", "dialog",
                        "blockquote", "pre", "address", "menu", "slot", "noscript", "object", "map", "progress", "meter", "output", "datalist", "optgroup", "colgroup"}
CHILD_OF = {"ul": "li", "ol": "li", "menu": "li", "table": "tr", "tbody": "tr", "thead": "tr", "tfoot": "tr", "tr": "td", "select": "option", "optgroup": "option",
            "datalist": "option", "colgroup": "col", "map": "area", "dl": "dt", "em": "span", "strong": "span", "a": "span", "span": "span", "b": "span", "i": "span",
            "label": "span", "p": "span", "h1": "span", "h2": "span", "h3": "span", "audio": "source", "video": "source", "picture": "source"}
DEFAULT_ATTRS = {"a": [("href", "")], "img": [("src", ""), ("alt", "")], "link": [("rel", "stylesheet"), ("href", "")], "script": [], "form": [("action", "")],
                 "input": [("type", "text")], "label": [("for", "")], "iframe": [("src", ""), ("frameborder", "0")], "select": [("name", ""), ("id", "")],
                 "textarea": [("name", ""), ("id", ""), ("cols", "30"), ("rows", "10")], "option": [("value", "")], "meta": [], "source": [("src", "")],
                 "video": [("src", "")], "audio": [("src", "")], "area": [("shape", ""), ("coords", ""), ("href", ""), ("alt", "")], "base": [("href", "")],
                 "abbr": [("title", "")], "object": [("data", ""), ("type", "")], "param": [("name", ""), ("value", "")], "map": [("name", "")], "html": [("lang", "en")]}
ALIASES = {
    "a:link": ("a", [("href", "http://")]), "a:mail": ("a", [("href", "mailto:")]), "a:tel": ("a", [("href", "tel:+")]), "a:blank": ("a", [("href", "http://"), ("target", "_blank"), ("rel", "noopener noreferrer")]),
    "link:css": ("link", [("rel", "stylesheet"), ("href", "style.css")]), "link:favicon": ("link", [("rel", "shortcut icon"), ("type", "image/x-icon"), ("href", "favicon.ico")]),
    "script:src": ("script", [("src", "")]), "meta:utf": ("meta", [("http-equiv", "Content-Type"), ("content", "text/html;charset=UTF-8")]),
    "meta:vp": ("meta", [("name", "viewport"), ("content", "width=device-width, initial-scale=1.0")]), "meta:desc": ("meta", [("name", "description"), ("content", "")]),
    "btn": ("button", []), "btn:s": ("button", [("type", "submit")]), "btn:r": ("button", [("type", "reset")]), "btn:b": ("button", [("type", "button")]),
    "bq": ("blockquote", []), "fig": ("figure", []), "figc": ("figcaption", []), "pic": ("picture", []), "ifr": ("iframe", []), "emb": ("embed", []), "obj": ("object", []),
    "cap": ("caption", []), "colg": ("colgroup", []), "fst": ("fieldset", []), "optg": ("optgroup", []), "tarea": ("textarea", []), "leg": ("legend", []), "sect": ("section", []),
    "art": ("article", []), "hdr": ("header", []), "ftr": ("footer", []), "adr": ("address", []), "dlg": ("dialog", []), "str": ("strong", []), "prog": ("progress", []),
    "src": ("source", []), "tem": ("template", []), "datal": ("datalist", []), "out": ("output", []), "det": ("details", []), "sum": ("summary", []), "mn": ("main", []),
}
for _kind in ("text", "email", "password", "number", "checkbox", "radio", "file", "hidden", "search", "url", "tel", "date", "time", "color", "range", "submit", "button", "reset"):
    ALIASES[f"input:{_kind}"] = ("input", [("type", _kind)] + ([] if _kind in ("submit", "button", "reset") else [("name", ""), ("id", "")]))
ALIASES["input:t"], ALIASES["input:p"], ALIASES["input:c"], ALIASES["input:r"], ALIASES["input:h"], ALIASES["input:s"] = (ALIASES["input:text"], ALIASES["input:password"],
                                                                                                                  ALIASES["input:checkbox"], ALIASES["input:radio"], ALIASES["input:hidden"], ALIASES["input:submit"])
SKELETON = ('<!DOCTYPE html>\n<html lang="${1:en}">\n<head>\n\t<meta charset="UTF-8">\n\t<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            "\t<title>${2:Document}</title>\n</head>\n<body>\n\t${0}\n</body>\n</html>")
LIMIT = 2000           # elements an abbreviation may make (li*100000 is a slip, not a wish)


class Node:
    def __init__(self, name=""):
        self.name, self.id, self.classes, self.attrs, self.text, self.count, self.children, self.group = name, "", [], [], None, 1, [], False


class Bad(ValueError):
    pass


_NAME = re.compile(r"[A-Za-z$@!][A-Za-z0-9:$@_-]*")
_WORD = re.compile(r"[A-Za-z0-9_$@-]+")


def _parse(s: str) -> Node:
    """An abbreviation as a tree (a nameless group at its root)."""
    pos = 0

    def element() -> Node:
        nonlocal pos
        if pos < len(s) and s[pos] == "(":
            pos += 1
            node = sequence()
            node.group = True
            if pos >= len(s) or s[pos] != ")":
                raise Bad("unclosed (")
            pos += 1
        else:
            node = Node()
            m = _NAME.match(s, pos)
            if m:
                node.name, pos = m.group(0), m.end()
            had = bool(m)
            while pos < len(s) and s[pos] in "#.[{":
                had = True
                ch = s[pos]
                if ch in "#.":
                    m = _WORD.match(s, pos + 1)
                    if not m:
                        raise Bad("nothing after " + ch)
                    if ch == "#":
                        node.id = m.group(0)
                    else:
                        node.classes.append(m.group(0))
                    pos = m.end()
                elif ch == "[":
                    end = s.find("]", pos)
                    if end < 0:
                        raise Bad("unclosed [")
                    for am in re.finditer(r"""([A-Za-z_:@$][\w:.$-]*)(?:=(?:"([^"]*)"|'([^']*)'|([^\s"']+)))?""", s[pos + 1:end]):
                        value = next((g for g in am.groups()[1:] if g is not None), "")
                        node.attrs.append((am.group(1), value))
                    pos = end + 1
                else:
                    end = s.find("}", pos)
                    if end < 0:
                        raise Bad("unclosed {")
                    node.text, pos = s[pos + 1:end], end + 1
            if not had:
                raise Bad("nothing here")
        m = re.compile(r"\*(\d*)").match(s, pos)
        if m:
            node.count, pos = max(1, min(LIMIT, int(m.group(1) or 1))), m.end()
        return node

    def sequence() -> Node:
        """Elements joined by > + ^ until a ) or the end, as children of a group."""
        nonlocal pos
        root = Node()
        root.group = True
        path = [root]                                     # where the next sibling goes: path[-1]'s children
        while True:
            node = element()
            path[-1].children.append(node)
            if pos >= len(s) or s[pos] == ")":
                return root
            op = s[pos]
            if op == ">":
                pos += 1
                path.append(node)
            elif op == "+":
                pos += 1
            elif op == "^":
                while pos < len(s) and s[pos] == "^":
                    pos += 1
                    if len(path) > 1:
                        path.pop()
            else:
                raise Bad("unexpected " + op)

    tree = sequence()
    if pos != len(s):
        raise Bad("unexpected " + s[pos])
    return tree


def _number(text: str, n: int) -> str:
    """$ is the element's number in its run, $$ padded to two digits, and so on; $@3 starts counting at 3."""
    def fill(m):
        start = int(m.group(2)) if m.group(2) else 1
        return str(n - 1 + start).zfill(len(m.group(1)))
    return re.sub(r"(\$+)(?:@(\d+))?", fill, text) if "$" in text else text


class _Out:
    def __init__(self):
        self.stop, self.made = 0, 0

    def next(self) -> str:
        self.stop += 1
        return "${%d}" % self.stop


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("$", "\\$").replace("}", "\\}")


def _render(node: Node, parent: str, n: int, out: _Out, depth: int) -> list:
    """The lines a node makes (tabs for indentation; Code turns them into the file's own)."""
    lines = []
    if node.group:
        for k in range(1, node.count + 1):
            for child in node.children:
                for j in range(1, (child.count if not child.group else 1) + 1):
                    lines += _render(child, parent, j if child.count > 1 or child.group else (k if node.count > 1 else n), out, depth)
        return lines
    out.made += 1
    if out.made > LIMIT:
        raise Bad("too many elements")
    name = _number(node.name, n) if node.name else ""
    attrs = []
    if name in ALIASES:
        name, attrs = ALIASES[name][0], list(ALIASES[name][1])
    elif not name:
        name = CHILD_OF.get(parent, "div")
    if not attrs:
        attrs = list(DEFAULT_ATTRS.get(name, []))
    given = {k: v for k, v in node.attrs}
    merged = [(k, given.pop(k)) if k in given else (k, v) for k, v in attrs] + list(given.items())
    if node.id:
        merged = [(k, v) for k, v in merged if k != "id"]
        merged.insert(0, ("id", node.id))
    if node.classes:
        merged = [(k, v) for k, v in merged if k != "class"]
        merged.insert(1 if node.id else 0, ("class", " ".join(node.classes)))
    parts = [name]
    for k, v in merged:
        v = _number(v, n)
        parts.append(f'{_number(k, n)}="{_escape(v) if v else out.next()}"')
    open_tag = "<" + " ".join(parts) + ">"
    pad = "\t" * depth
    if name in VOID:
        return [pad + open_tag]
    text = _escape(_number(node.text, n)) if node.text is not None else ""
    inner = []
    for child in node.children:
        for j in range(1, (child.count if not child.group else 1) + 1):
            inner += _render(child, name, j if child.count > 1 else n, out, depth + 1)       # (one child takes its parent's number)
    close = f"</{name}>"
    if not inner:
        return [pad + open_tag + (text or out.next()) + close]
    if len(inner) == 1 and name in INLINE and not text and "\n" not in inner[0]:
        return [pad + open_tag + inner[0].strip() + close]
    return [pad + open_tag + text] + inner + [pad + close]


def expand(abbr: str):
    """An HTML abbreviation as a snippet, or None when it isn't one that can be read."""
    abbr = abbr.strip()
    if not abbr or len(abbr) > 400:
        return None
    if abbr in ("!", "html:5", "doc"):
        return SKELETON
    try:
        tree = _parse(abbr)
        out = _Out()
        lines = _render(tree, "", 1, out, 0)
    except (Bad, RecursionError):
        return None
    if not lines:
        return None
    body = "\n".join(lines)
    last = "${%d}" % out.stop
    if out.stop and body.count(last) == 1 and body.rstrip().endswith((last + "</" + body.rstrip().rsplit("</", 1)[-1],)) and len(lines) == 1:
        return body.replace(last, "${0}")                  # one element: finish inside it
    return body + "${0}"


# ------------------------------------------------------------------------------------------------------------- CSS
CSS_PROPS = {"m": "margin", "mt": "margin-top", "mr": "margin-right", "mb": "margin-bottom", "ml": "margin-left", "p": "padding", "pt": "padding-top", "pr": "padding-right",
             "pb": "padding-bottom", "pl": "padding-left", "w": "width", "h": "height", "maw": "max-width", "mah": "max-height", "miw": "min-width", "mih": "min-height",
             "fz": "font-size", "fw": "font-weight", "lh": "line-height", "t": "top", "r": "right", "b": "bottom", "l": "left", "z": "z-index", "op": "opacity",
             "bd": "border", "bdrs": "border-radius", "bdw": "border-width", "g": "gap", "fl": "float", "fx": "flex", "fxg": "flex-grow", "fxs": "flex-shrink", "ord": "order",
             "bg": "background", "bgc": "background-color", "c": "color", "ff": "font-family", "ti": "text-indent", "ls": "letter-spacing", "ol": "outline", "tr": "transform",
             "trs": "transition", "bxsh": "box-shadow", "cnt": "content", "cur": "cursor", "ov": "overflow", "va": "vertical-align", "ws": "white-space"}
CSS_WORDS = {"df": "display: flex;", "dn": "display: none;", "db": "display: block;", "di": "display: inline;", "dib": "display: inline-block;", "dg": "display: grid;",
             "dif": "display: inline-flex;", "posa": "position: absolute;", "posr": "position: relative;", "posf": "position: fixed;", "poss": "position: sticky;",
             "tac": "text-align: center;", "tal": "text-align: left;", "tar": "text-align: right;", "taj": "text-align: justify;", "fwb": "font-weight: bold;",
             "fwn": "font-weight: normal;", "fsi": "font-style: italic;", "tdn": "text-decoration: none;", "tdu": "text-decoration: underline;", "ttu": "text-transform: uppercase;",
             "ovh": "overflow: hidden;", "ova": "overflow: auto;", "ovs": "overflow: scroll;", "curp": "cursor: pointer;", "fll": "float: left;", "flr": "float: right;",
             "jcc": "justify-content: center;", "jcsb": "justify-content: space-between;", "jcsa": "justify-content: space-around;", "jcfs": "justify-content: flex-start;",
             "jcfe": "justify-content: flex-end;", "aic": "align-items: center;", "aifs": "align-items: flex-start;", "aife": "align-items: flex-end;", "ais": "align-items: stretch;",
             "fxdc": "flex-direction: column;", "fxdr": "flex-direction: row;", "fxww": "flex-wrap: wrap;", "bxzbb": "box-sizing: border-box;", "wsnw": "white-space: nowrap;",
             "vam": "vertical-align: middle;", "bdn": "border: none;", "mauto": "margin: auto;", "m0a": "margin: 0 auto;", "wfull": "width: 100%;", "hfull": "height: 100%;",
             "!": "!important"}
UNITLESS = {"z-index", "opacity", "font-weight", "line-height", "flex", "flex-grow", "flex-shrink", "order"}
_CSS = re.compile(r"([a-z]+)(-?\d*\.?\d+(?:[a-z%]*)(?:-+-?\d*\.?\d+[a-z%]*)*|a)?(!)?$")
_UNIT = {"": "px", "p": "%", "e": "em", "r": "rem", "x": "ex", "vw": "vw", "vh": "vh", "px": "px", "em": "em", "rem": "rem", "%": "%", "fr": "fr", "s": "s", "ms": "ms", "deg": "deg", "pt": "pt"}


def expand_css(abbr: str):
    """`m10` -> `margin: 10px;`, `p10-20` -> `padding: 10px 20px;`, `w100p` -> `width: 100%;`, `df` -> `display: flex;`,
    `c` -> `color: ${1};`. None when it isn't a CSS abbreviation Code knows."""
    abbr = abbr.strip().lower()
    if abbr in CSS_WORDS and abbr != "!":
        return CSS_WORDS[abbr] + "${0}"
    m = _CSS.match(abbr)
    if not m or m.group(1) not in CSS_PROPS:
        return None
    prop, values, bang = CSS_PROPS[m.group(1)], m.group(2), " !important" if m.group(3) else ""
    if values is None:
        return f"{prop}: ${{1}}{bang};${{0}}"
    if values == "a":
        return f"{prop}: auto{bang};${{0}}"
    out = []
    for part in re.findall(r"(?:^|-)(-?\d*\.?\d+)([a-z%]*)", values):
        number, unit = part
        if unit not in _UNIT:
            return None
        zero = float(number) == 0
        out.append(number + ("" if zero or (prop in UNITLESS and not unit) else _UNIT[unit]))
    return f"{prop}: {' '.join(out)}{bang};${{0}}" if out else None


# -------------------------------------------------------------------------------------- is what was typed one of them?
def abbreviation_before(before: str, kind: str = "html") -> str:
    """The abbreviation at the end of a line of text (what's left of the cursor), or "": so that Tab after an
    ordinary word, or inside a tag or a sentence, stays a Tab."""
    if kind == "css":
        m = re.search(r"(?:^|[\s;{])([a-z!]+[\d.a-z%-]*!?)$", before)
        token = m.group(1) if m else ""
        return token if token and expand_css(token) and ":" not in before.split(";")[-1].split("{")[-1] else ""
    # back from the cursor to a space or a tag's end, minding spaces inside [..] and {..}
    i, depth = len(before), 0
    while i > 0:
        ch = before[i - 1]
        if ch in "]}":
            depth += 1
        elif ch in "[{":
            depth -= 1
            if depth < 0:
                break
        elif depth == 0 and (ch.isspace() or (ch == ">" and (i < 2 or not _is_child_op(before, i - 1)))):
            break
        i -= 1
    token = before[i:]
    if not token or token[0] in ">+^*" or before[:i].rstrip().endswith(("<", "</", "=")) or before[:i].count("<") > before[:i].count(">"):
        return ""
    if token in ("!", "html:5", "doc"):
        return token
    try:
        tree = _parse(token)
    except Bad:
        return ""
    if not re.search(r"[.#>+*\[{(]", token):                 # a bare word: only a real tag (or an alias), not any word of prose
        return token if token in TAGS or token in ALIASES else ""
    first = tree.children[0] if tree.children else None
    if first is not None and not first.group and first.name and re.fullmatch(r"\d.*", first.name):
        return ""
    return token


def _is_child_op(text: str, at: int) -> bool:
    """Is the > at `at` Emmet's child sign (part of an abbreviation) and not the end of a tag?"""
    return text.rfind("<", 0, at) <= text.rfind(">", 0, at)          # (no tag is open to the left of it)
