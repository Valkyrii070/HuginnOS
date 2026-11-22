"""Code, round four: the parts that don't need a window. Snippets and their tab stops, merge conflicts, the scopes
for sticky scroll and the outline, and quick fixes for Python's commonest problems (an import not used, a name
never imported), for when the language server has none of its own."""
import re
import sys

# name: (what it is, the body). In a body, ${1:text} is the first place to type (with text there to start),
# $2 the second, $0 where the cursor ends; a tab is one step of the file's own indentation.
SNIPPETS = {
    "Python": {
        "def": ("Function", "def ${1:name}(${2}):\n\t${0:pass}"),
        "adef": ("Async function", "async def ${1:name}(${2}):\n\t${0:pass}"),
        "class": ("Class", "class ${1:Name}:\n\tdef __init__(self${2}):\n\t\t${0:pass}"),
        "dataclass": ("Data class", "@dataclass\nclass ${1:Name}:\n\t${2:field}: ${3:int}${0}"),
        "main": ("Run as a program", "def main():\n\t${1:pass}\n\n\nif __name__ == \"__main__\":\n\tmain()${0}"),
        "for": ("Loop over something", "for ${1:item} in ${2:items}:\n\t${0:pass}"),
        "enum": ("Loop with numbers", "for ${1:i}, ${2:item} in enumerate(${3:items}):\n\t${0:pass}"),
        "while": ("While", "while ${1:True}:\n\t${0:pass}"),
        "if": ("If", "if ${1:condition}:\n\t${0:pass}"),
        "with": ("With", "with open(${1:path}) as ${2:f}:\n\t${0:pass}"),
        "try": ("Try … except", "try:\n\t${1:pass}\nexcept ${2:Exception} as ${3:e}:\n\t${0:raise}"),
        "test": ("Test (pytest)", "def test_${1:name}():\n\t${0:assert True}"),
        "prop": ("Property", "@property\ndef ${1:name}(self):\n\treturn self._${1:name}${0}"),
    },
    "JavaScript": {
        "fn": ("Function", "function ${1:name}(${2}) {\n\t${0}\n}"),
        "afn": ("Arrow function", "const ${1:name} = (${2}) => {\n\t${0}\n};"),
        "for": ("Loop over something", "for (const ${1:item} of ${2:items}) {\n\t${0}\n}"),
        "fori": ("Counting loop", "for (let ${1:i} = 0; ${1:i} < ${2:n}; ${1:i}++) {\n\t${0}\n}"),
        "if": ("If", "if (${1:condition}) {\n\t${0}\n}"),
        "log": ("Print", "console.log(${1});${0}"),
        "imp": ("Import", "import { ${2:name} } from \"${1:module}\";${0}"),
        "try": ("Try … catch", "try {\n\t${1}\n} catch (${2:err}) {\n\t${0}\n}"),
        "cls": ("Class", "class ${1:Name} {\n\tconstructor(${2}) {\n\t\t${0}\n\t}\n}"),
    },
    "C": {
        "main": ("A program's start", "int main(int argc, char **argv)\n{\n\t${0}\n\treturn 0;\n}"),
        "for": ("Counting loop", "for (int ${1:i} = 0; ${1:i} < ${2:n}; ${1:i}++) {\n\t${0}\n}"),
        "if": ("If", "if (${1:condition}) {\n\t${0}\n}"),
        "inc": ("Include", "#include <${1:stdio.h}>${0}"),
        "guard": ("Include guard", "#ifndef ${1:NAME_H}\n#define ${1:NAME_H}\n\n${0}\n\n#endif"),
        "struct": ("Structure", "typedef struct {\n\t${2:int field};\n} ${1:Name};${0}"),
        "pf": ("Print", "printf(\"${1:%d}\\n\", ${2});${0}"),
    },
    "Rust": {
        "fn": ("Function", "fn ${1:name}(${2}) {\n\t${0}\n}"),
        "pfn": ("Public function", "pub fn ${1:name}(${2}) -> ${3:()} {\n\t${0}\n}"),
        "test": ("Test", "#[test]\nfn ${1:name}() {\n\t${0}\n}"),
        "impl": ("impl", "impl ${1:Type} {\n\t${0}\n}"),
        "match": ("match", "match ${1:value} {\n\t${2:_} => ${0},\n}"),
        "for": ("Loop over something", "for ${1:item} in ${2:items} {\n\t${0}\n}"),
        "pl": ("Print", "println!(\"${1:{}}\", ${2});${0}"),
    },
    "Go": {
        "func": ("Function", "func ${1:name}(${2}) ${3}{\n\t${0}\n}"),
        "iferr": ("If there's an error", "if err != nil {\n\treturn ${1:err}\n}${0}"),
        "for": ("Loop over something", "for ${1:_}, ${2:item} := range ${3:items} {\n\t${0}\n}"),
        "main": ("A program's start", "func main() {\n\t${0}\n}"),
        "test": ("Test", "func Test${1:Name}(t *testing.T) {\n\t${0}\n}"),
        "pf": ("Print", "fmt.Println(${1})${0}"),
    },
    "Shell": {
        "sh": ("Start of a script", "#!/usr/bin/env bash\nset -euo pipefail\n\n${0}"),
        "if": ("If", "if [[ ${1:condition} ]]; then\n\t${0}\nfi"),
        "for": ("Loop over something", "for ${1:item} in ${2:items}; do\n\t${0}\ndone"),
        "fn": ("Function", "${1:name}() {\n\t${0}\n}"),
    },
    "Markdown": {
        "link": ("Link", "[${1:text}](${2:https://})${0}"),
        "img": ("Picture", "![${1:what it shows}](${2:path})${0}"),
        "code": ("Code block", "```${1:python}\n${0}\n```"),
        "table": ("Table", "| ${1:Heading} | ${2:Heading} |\n|---|---|\n| ${3} | ${0} |"),
        "todo": ("Task", "- [ ] ${0}"),
    },
    "HTML": {
        "html": ("A page", "<!DOCTYPE html>\n<html lang=\"${1:en}\">\n<head>\n\t<meta charset=\"utf-8\">\n\t<title>${2:Title}</title>\n</head>\n<body>\n\t${0}\n</body>\n</html>"),
        "a": ("Link", "<a href=\"${1}\">${0}</a>"),
        "div": ("Box", "<div class=\"${1}\">\n\t${0}\n</div>"),
    },
}
SNIPPETS["TypeScript"] = dict(SNIPPETS["JavaScript"], intf=("Interface", "interface ${1:Name} {\n\t${2:field}: ${3:string};${0}\n}"))
SNIPPETS["C++"] = dict(SNIPPETS["C"], cls=("Class", "class ${1:Name} {\npublic:\n\t${1:Name}();\n\t${0}\n};"),
                       cout=("Print", "std::cout << ${1} << std::endl;${0}"))


def snippet_parse(body: str, unit: str = "    ", indent: str = "") -> dict:
    """A snippet's body -> {text, stops}: the text to put in (tabs as the file's indentation, lines after the first
    at the line's own indent), and where to type, in order: [[start, end], …] with the end ($0) last. A number used
    again (${1:i} three times) is the same stop: those places are listed with it in "same"."""
    out, stops, i, n = [], {}, 0, len(body)
    text_len = 0

    def put(s):
        nonlocal text_len
        out.append(s)
        text_len += len(s)
    while i < n:
        ch = body[i]
        if ch == "\\" and i + 1 < n and body[i + 1] in "$}\\":
            put(body[i + 1])
            i += 2
            continue
        if ch == "\n":
            put("\n" + indent)
            i += 1
            continue
        if ch == "\t":
            put(unit)
            i += 1
            continue
        if ch == "$":
            m = re.match(r"\$(\d+)|\$\{(\d+)(?::((?:[^}\\]|\\.)*))?\}|\$\{(\d+)\|([^|]*)\|\}", body[i:])
            if m:
                num = int(m.group(1) or m.group(2) or m.group(4))
                default = m.group(3) if m.group(2) else (m.group(5).split(",")[0] if m.group(4) else "")
                default = re.sub(r"\\(.)", r"\1", default or "")
                if num in stops and not default:
                    default = stops[num]["text"]
                start = text_len
                put(default)
                stops.setdefault(num, {"text": default, "at": []})["at"].append([start, text_len])
                i += m.end()
                continue
        put(ch)
        i += 1
    order = sorted(k for k in stops if k > 0) + ([0] if 0 in stops else [])
    text = "".join(out)
    if 0 not in stops:
        order.append(0)
        stops[0] = {"text": "", "at": [[len(text), len(text)]]}
    return {"text": text, "stops": [stops[k]["at"][0] for k in order], "same": [stops[k]["at"][1:] for k in order]}


def snippet_items(lang: str, prefix: str) -> list:
    """Completion items for the snippets whose names start like the word being typed."""
    out = []
    for name, (what, body) in (SNIPPETS.get(lang) or {}).items():
        if prefix and name.startswith(prefix):
            out.append({"label": name, "insert": body, "snippet": body, "detail": what, "kind": 15, "sort": "~" + name})
    return out


# ---------------------------------------------------------------- merge conflicts
def conflicts(text: str) -> list:
    """The conflicts Git left in a file: [{start, mid, base, end, ours, theirs}] as line numbers (base when
    merge.conflictStyle is diff3), and what each side said."""
    lines, out, k = text.split("\n"), [], 0
    while k < len(lines):
        if lines[k].startswith("<<<<<<<"):
            start, base, mid, end = k, -1, -1, -1
            j = k + 1
            while j < len(lines):
                if lines[j].startswith("|||||||") and mid < 0:
                    base = j
                elif lines[j].startswith("=======") and mid < 0:
                    mid = j
                elif lines[j].startswith(">>>>>>>") and mid >= 0:
                    end = j
                    break
                elif lines[j].startswith("<<<<<<<"):
                    break
                j += 1
            if mid > 0 and end > 0:
                ours = lines[start + 1:(base if base > 0 else mid)]
                out.append({"start": start, "base": base, "mid": mid, "end": end, "ours": "\n".join(ours), "theirs": "\n".join(lines[mid + 1:end]),
                            "oursName": lines[start][7:].strip() or "ours", "theirsName": lines[end][7:].strip() or "theirs"})
                k = end + 1
                continue
        k += 1
    return out


def resolve_text(text: str, which: str, only: int = -1) -> tuple:
    """The file with its conflicts (all, or number `only`) settled: "ours", "theirs" or "both" (ours, then theirs).
    -> (new text, how many were settled)."""
    lines = text.split("\n")
    found = conflicts(text)
    done = 0
    for n, c in reversed(list(enumerate(found))):
        if only >= 0 and n != only:
            continue
        ours = lines[c["start"] + 1:(c["base"] if c["base"] > 0 else c["mid"])]
        theirs = lines[c["mid"] + 1:c["end"]]
        keep = ours if which == "ours" else theirs if which == "theirs" else ours + theirs
        lines[c["start"]:c["end"] + 1] = keep
        done += 1
    return "\n".join(lines), done


# ---------------------------------------------------------------- scopes: the outline and sticky scroll
def scopes(text: str, symbols: list) -> list:
    """Each symbol with where it ends: the line before the next one that isn't blank or a comment and is no more
    indented than its own first line (a closing brace on its own still belongs to it)."""
    lines = text.split("\n")
    ind = []
    for l in lines:
        s = l.lstrip()
        ind.append(len(l.expandtabs(4)) - len(s.expandtabs(4)) if s else -1)
    out = []
    for sym in symbols:
        k = sym["line"]
        if not 0 <= k < len(lines):
            continue
        base = ind[k] if ind[k] >= 0 else 0
        end = k
        j = k + 1
        while j < len(lines):
            s = lines[j].strip()
            if ind[j] >= 0 and ind[j] <= base and not s.startswith(("#", "//")):
                if s[:1] in ")]}" or s.startswith(("end", "fi", "done", "esac")):
                    end = j
                break
            if ind[j] >= 0:
                end = j
            j += 1
        out.append(dict(sym, end=end, indent=base))
    return out


def enclosing(scoped: list, line: int) -> list:
    """The scopes a line is inside, outermost first (for sticky scroll)."""
    inside = [s for s in scoped if s["line"] < line <= s["end"]]
    inside.sort(key=lambda s: (s["indent"], s["line"]))
    return inside


# ---------------------------------------------------------------- quick fixes for Python
STD = set(getattr(sys, "stdlib_module_names", ())) | {"os", "sys", "re", "json", "math", "time", "datetime", "random", "subprocess", "pathlib", "typing",
                                                    "collections", "itertools", "functools", "shutil", "tempfile", "logging", "argparse", "dataclasses"}
FROM = {"Path": "pathlib", "dataclass": "dataclasses", "field": "dataclasses", "defaultdict": "collections", "Counter": "collections",
        "OrderedDict": "collections", "namedtuple": "collections", "deque": "collections", "partial": "functools", "lru_cache": "functools",
        "wraps": "functools", "reduce": "functools", "datetime": "datetime", "date": "datetime", "timedelta": "datetime", "Optional": "typing",
        "List": "typing", "Dict": "typing", "Any": "typing", "Union": "typing", "Callable": "typing", "Iterable": "typing", "Enum": "enum",
        "ABC": "abc", "abstractmethod": "abc", "contextmanager": "contextlib", "suppress": "contextlib", "sleep": "time", "glob": "glob",
        "pprint": "pprint", "dedent": "textwrap", "deepcopy": "copy", "copy": "copy", "sqrt": "math", "pi": "math", "floor": "math", "ceil": "math"}


def _import_line(lines: list) -> int:
    """Where a new import goes: after the module's docstring, __future__ imports and the imports already there."""
    k, n = 0, len(lines)
    while k < n and (not lines[k].strip() or lines[k].startswith("#!") or lines[k].startswith("# -*-")):
        k += 1
    if k < n and lines[k].lstrip().startswith(('"""', "'''")):
        q = lines[k].lstrip()[:3]
        if lines[k].count(q) >= 2 and len(lines[k].strip()) > 3:
            k += 1
        else:
            k += 1
            while k < n and q not in lines[k]:
                k += 1
            k += 1
    last = -1
    for j in range(k, min(n, k + 400)):
        s = lines[j]
        if re.match(r"(import\s|from\s+\S+\s+import\s)", s):
            last = j
            while last + 1 < n and (lines[last].rstrip().endswith(("(", ",", "\\")) and not lines[last].rstrip().endswith(")")):
                last += 1
        elif s.strip() and not s.startswith("#") and last >= 0:
            break
        elif s.strip() and not s.startswith(("#", "import", "from")) and last < 0:
            break
    return last + 1 if last >= 0 else k


def python_fixes(text: str, problems: list, line: int, modules: set = frozenset()) -> list:
    """Quick fixes for the problems on a line: [{title, edits: [[start line, start col, end line, end col, text]]}].
    "'os' imported but unused": take it out (the whole line, or just that name from a list). "undefined name 'X'":
    import it, when it's a standard module, a common name from one, or a module of the project."""
    lines, out = text.split("\n"), []
    for p in problems:
        if not p["line"] <= line <= p.get("endLine", p["line"]):
            continue
        msg = p.get("message", "")
        m = re.search(r"'([\w.]+)(?: as \w+)?' imported but unused", msg)
        if m and p["line"] < len(lines):
            full = m.group(1)
            row = lines[p["line"]]
            name = full.split(".")[-1] if re.match(r"\s*from\s", row) else full
            fm = re.match(r"(\s*from\s+\S+\s+import\s+)(\(?)(.*?)(\)?)\s*$", row)
            if fm and "," in fm.group(3):
                names = [x.strip() for x in fm.group(3).split(",") if x.strip()]
                keep = [x for x in names if x.split(" as ")[0].strip() != name]
                if len(keep) < len(names):
                    new = fm.group(1) + fm.group(2) + ", ".join(keep) + fm.group(4)
                    out.append({"title": f"Take out the unused import of {name}", "edits": [[p["line"], 0, p["line"], len(row), new]]})
                    continue
            im = re.match(r"(\s*import\s+)(.*)$", row)
            if im and "," in im.group(2):
                names = [x.strip() for x in im.group(2).split(",")]
                keep = [x for x in names if x.split(" as ")[0].strip() != full]
                out.append({"title": f"Take out the unused import of {full}", "edits": [[p["line"], 0, p["line"], len(row), im.group(1) + ", ".join(keep)]]})
                continue
            out.append({"title": f"Take out the unused import of {name}", "edits": [[p["line"], 0, p["line"] + 1, 0, ""]]})
            continue
        m = re.search(r"undefined name '(\w+)'", msg)
        if m:
            name = m.group(1)
            at = _import_line(lines)
            if name in STD or name in modules:
                out.append({"title": f"import {name}", "edits": [[at, 0, at, 0, f"import {name}\n"]]})
            if name in FROM:
                mod = FROM[name]
                existing = next((k for k, l in enumerate(lines) if re.match(rf"from\s+{re.escape(mod)}\s+import\s+[^(]*$", l)), -1)
                if existing >= 0:
                    row = lines[existing]
                    out.append({"title": f"Add {name} to “{row.strip()}”", "edits": [[existing, 0, existing, len(row), row.rstrip() + f", {name}"]]})
                else:
                    out.append({"title": f"from {mod} import {name}", "edits": [[at, 0, at, 0, f"from {mod} import {name}\n"]]})
    seen, unique = set(), []
    for f in out:
        if f["title"] not in seen:
            seen.add(f["title"])
            unique.append(f)
    return unique


def edits_to_offsets(text: str, edits: list) -> list:
    """[[line, col, end line, end col, text]] -> [[start, end, text]] as offsets into text."""
    starts, k = [0], 0
    for l in text.split("\n"):
        k += len(l) + 1
        starts.append(k)
    last = len(text)

    def at(line, col):
        return min(last, starts[min(line, len(starts) - 1)] + col) if line < len(starts) - 1 else last
    return [[at(a, b), at(c, d), t] for a, b, c, d, t in edits]


def u16(text: str, offset: int) -> int:
    """A character offset as Qt counts it (UTF-16: characters past U+FFFF are two)."""
    if text.isascii():
        return offset
    return len(text[:offset].encode("utf-16-le", "surrogatepass")) // 2


def trim_text(text: str, lang: str) -> str:
    """Spaces at the ends of lines taken away (not Markdown's two-space line breaks) and one newline at the end."""
    if not text:
        return text
    if lang == "Markdown":
        lines = [l.rstrip() + "  " if l.endswith("  ") and l.strip() else l.rstrip() for l in text.split("\n")]
    else:
        lines = [l.rstrip() for l in text.split("\n")]
    while len(lines) > 1 and lines[-1] == "" and lines[-2] == "":
        lines.pop()
    out = "\n".join(lines)
    return out if out.endswith("\n") else out + "\n"


# ---------------------------------------------------------------- whole lines at a time
LINE_EDITS = ("up", "down", "copy_up", "copy_down", "delete", "join", "sort", "sort_desc", "unique",
              "upper", "lower", "title", "above", "below", "select")


def from16(text: str, n: int) -> int:
    """A position the editor counts (UTF-16 units) as a position in the Python string."""
    n = max(0, int(n))
    if text.isascii():
        return min(n, len(text))
    return len(text.encode("utf-16-le", "surrogatepass")[:2 * n].decode("utf-16-le", "ignore"))


def line_span(text: str, a: int, b: int) -> tuple:
    """The whole lines a selection touches: (start of the first, end of the last, without its line end).
    A selection that stops at the very start of a line doesn't count that line."""
    a, b = max(0, min(a, b, len(text))), max(0, min(max(a, b), len(text)))
    s = text.rfind("\n", 0, a) + 1
    e = text.find("\n", b - 1 if b > a and text[b - 1] == "\n" else b)
    return s, len(text) if e < 0 else e


def line_edit(text: str, a: int, b: int, how: str):
    """One whole-line command on the selection a..b (or the cursor's line).
    -> (start, end, new, sel_a, sel_b): put `new` where text[start:end] was, then select sel_a..sel_b; None when there's nothing to do."""
    if how not in LINE_EDITS:
        return None
    a, b = max(0, min(a, b, len(text))), max(0, min(max(a, b), len(text)))
    s, e = line_span(text, a, b)
    block = text[s:e]
    if how == "select":
        return (s, s, "", s, min(e + 1, len(text)))
    if how == "up":
        if s == 0:
            return None
        ps = text.rfind("\n", 0, s - 1) + 1
        prev = text[ps:s - 1]
        return (ps, e, block + "\n" + prev, a - len(prev) - 1, b - len(prev) - 1)
    if how == "down":
        if e >= len(text):
            return None
        ne = text.find("\n", e + 1)
        ne = len(text) if ne < 0 else ne
        nxt = text[e + 1:ne]
        return (s, ne, nxt + "\n" + block, a + len(nxt) + 1, min(b + len(nxt) + 1, ne))
    if how == "copy_down":
        return (e, e, "\n" + block, a + len(block) + 1, b + len(block) + 1)
    if how == "copy_up":
        return (e, e, "\n" + block, a, b)
    if how == "delete":
        if e < len(text):
            return (s, e + 1, "", s, s)
        if s > 0:
            ps = text.rfind("\n", 0, s - 1) + 1
            return (s - 1, e, "", ps, ps)
        return (s, e, "", 0, 0) if block else None
    if how in ("above", "below"):
        ind = re.match(r"[ \t]*", block).group(0)
        if how == "above":
            return (s, s, ind + "\n", s + len(ind), s + len(ind))
        return (e, e, "\n" + ind, e + 1 + len(ind), e + 1 + len(ind))
    if how == "join":
        if "\n" not in block:                                 # one line: the next one comes up to it
            if e >= len(text):
                return None
            ne = text.find("\n", e + 1)
            e = len(text) if ne < 0 else ne
            block = text[s:e]
        parts = block.split("\n")
        out, at = parts[0].rstrip(), None
        for part in parts[1:]:
            part = part.strip()
            at = len(out)
            if part:
                out += (" " if out else "") + part
        if out == block:
            return None
        if len(parts) == 2:
            return (s, e, out, s + at, s + at)
        return (s, e, out, s, s + len(out))
    if how in ("sort", "sort_desc", "unique"):
        parts = block.split("\n")
        if len(parts) < 2:
            return None
        if how == "unique":
            seen, now = set(), []
            for part in parts:
                if part not in seen:
                    seen.add(part)
                    now.append(part)
        else:
            now = sorted(parts, key=lambda l: (l.casefold(), l), reverse=how == "sort_desc")
        if now == parts:
            return None
        out = "\n".join(now)
        return (s, e, out, s, s + len(out))
    # upper, lower, title: what's selected, or the cursor's line
    s2, e2 = (a, b) if b > a else (s, e)
    old = text[s2:e2]
    now = old.upper() if how == "upper" else old.lower() if how == "lower" else re.sub(r"[^\W\d_]+(?:['’][^\W\d_]+)*", lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(), old)
    if now == old:
        return None
    return (s2, e2, now, s2, s2 + len(now)) if b > a else (s2, e2, now, min(a, s2 + len(now)), min(a, s2 + len(now)))


# ---------------------------------------------------------------- what changed since the last commit
CHANGES_LIMIT = 20000         # lines: past this the marks come from Git when the file is saved, not as you type


def changes(old: str, new: str) -> list:
    """What differs between the committed text and the one in the editor, as runs of lines in the new one:
    [{"a", "b", "kind": add | mod | del, "old": the committed lines it replaced}]. A "del" sits at line a (b == a)."""
    if old == new:
        return []
    was, now = old.split("\n"), new.split("\n")
    if len(was) > CHANGES_LIMIT or len(now) > CHANGES_LIMIT:
        return []
    import difflib
    head = 0                                                  # (the same start and end are skipped first: typing in a long file stays quick)
    top = min(len(was), len(now))
    while head < top and was[head] == now[head]:
        head += 1
    tail = 0
    while tail < top - head and was[len(was) - 1 - tail] == now[len(now) - 1 - tail]:
        tail += 1
    out = []
    mid_was, mid_now = was[head:len(was) - tail], now[head:len(now) - tail]
    import collections
    seen = collections.Counter(mid_now)
    work = sum(seen[l] for l in mid_was)                      # how many pairs of equal lines there are to weigh up
    if not mid_was or not mid_now or work > 3_000_000:        # one side empty, or thousands of the same line over and over: one change
        return [{"a": head, "b": head + len(mid_now), "kind": "add" if not mid_was else "del" if not mid_now else "mod", "old": mid_was}]
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, mid_was, mid_now, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        out.append({"a": head + j1, "b": head + j2, "kind": "add" if tag == "insert" else "del" if tag == "delete" else "mod",
                    "old": mid_was[i1:i2]})
    return out


def change_marks(found: list, lines: int) -> dict:
    """The gutter's marks from `changes`: {line: add | mod | del}."""
    marks = {}
    for c in found:
        if c["kind"] == "del":
            marks.setdefault(max(0, min(c["a"], lines - 1)), "del")
        else:
            for n in range(c["a"], c["b"]):
                marks[n] = c["kind"]
    return marks


def change_at(found: list, line: int):
    """The change the cursor's line belongs to (a removal belongs to the line it sits on, or the one before)."""
    for c in found:
        if c["a"] <= line < c["b"] or (c["kind"] == "del" and line in (c["a"], c["a"] - 1)):
            return c
    return None


def put_back(new: str, c: dict) -> tuple:
    """Undo one change: -> (start, end, text) to put the committed lines back where the changed ones are."""
    lines = new.split("\n")
    starts = [0]
    for l in lines:
        starts.append(starts[-1] + len(l) + 1)
    total = len(new)
    if c["kind"] == "del":                                    # the lines go back in above line a
        if c["a"] >= len(lines):
            return (total, total, "\n" + "\n".join(c["old"]))
        return (starts[c["a"]], starts[c["a"]], "\n".join(c["old"]) + "\n")
    s = starts[c["a"]]
    e = min(starts[c["b"]], total + 1)
    if c["kind"] == "add":                                 # the added lines go, with one line end
        if e > total:                                         # (they were the last lines: the line end before them goes instead)
            return (max(0, s - 1), total, "")
        return (s, e, "")
    return (s, e - 1, "\n".join(c["old"]))
