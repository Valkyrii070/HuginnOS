"""Fuzz Code's backend: awkward files and random commands, with what's on disk checked. Usage: code_fuzz.py /src [steps] [seed]"""
import os as _os, sys as _sys
if _os.geteuid() == 0:        # it renames, removes and replaces at random: never as root, where a slip reaches the whole system
    _sys.exit("code_fuzz.py: run this as an ordinary user (it refuses to run as root).")
import os, random, subprocess, sys, tempfile, time, traceback
home = tempfile.mkdtemp(prefix="codefuzz-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/d", XDG_CONFIG_HOME=home + "/c", XDG_CACHE_HOME=home + "/k", QT_QPA_PLATFORM="offscreen",
                  GIT_AUTHOR_NAME="Ada", GIT_AUTHOR_EMAIL="ada@x.invalid", GIT_COMMITTER_NAME="Ada", GIT_COMMITTER_EMAIL="ada@x.invalid")
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 1
sys.path.insert(0, SRC + "/apps"); sys.path.insert(0, SRC + "/shell")
from pathlib import Path
from PySide6.QtCore import QEventLoop
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
import huginn_code as hc

random.seed(SEED)
problems, log = {}, []


def problem(kind, detail):
    import re
    key = kind + " :: " + re.sub(r"\d+", "N", detail.strip().splitlines()[-1])[:150]
    if key not in problems:
        problems[key] = {"n": 0, "detail": detail[-1400:], "trail": list(log[-5:])}
    problems[key]["n"] += 1


def spin(ms=5):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents(QEventLoop.AllEvents, 5)


P = Path(home) / "proj"
(P / "src" / "deep" / "er").mkdir(parents=True)
(P / "docs").mkdir()
ASTRAL = "😀𝒳🐦‍⬛"
FILES = {
    "src/main.py": "import os\nimport sys\n\n\nclass Shop:\n    def __init__(self, name):\n        self.name = name\n\n    def total(self, items):\n        return sum(i.price for i in items)\n\n\ndef main():\n    s = Shop('a')\n    print(s.total([]))\n\n\nif __name__ == '__main__':\n    main()\n",
    "src/util.js": "export function add(a, b) {\n  return a + b;\n}\n\nconst x = { a: [1, 2, (3)] };\n",
    "src/deep/er/lib.rs": "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n",
    "docs/notes.md": "# Notes\n\nSome *text* with  \ntwo-space breaks.\n\n## More\n\n- one\n- two\n",
    "crlf.txt": "one\r\ntwo\r\nthree\r\n",
    "mixed.txt": "one\r\ntwo\nthree\rfour\n",
    "bom.txt": "﻿with a bom\nsecond\n",
    "astral.txt": f"faces {ASTRAL} and more {ASTRAL}\nline two {ASTRAL}\n",
    "noeol.txt": "no newline at the end",
    "empty.txt": "",
    "tabs.c": "int main(void) {\n\tint a = 1;\n\tif (a) {\n\t\treturn a;\n\t}\n\treturn 0;\n}\n",
    "conflict.py": "a = 1\n<<<<<<< HEAD\nb = 2\n=======\nb = 3\n>>>>>>> other\nc = 4\n",
    "odd name ü €.txt": "odd\n",
    ".hidden": "dot\n",
}
for rel, text in FILES.items():
    (P / rel).parent.mkdir(parents=True, exist_ok=True)
    (P / rel).write_bytes(text.encode("utf-8"))
(P / ".editorconfig").write_bytes(random.choice([b"root = true\n[*]\nindent_style = tab\ntrim_trailing_whitespace = false\ninsert_final_newline = false\n",
    b"[*.{py,txt}]\nindent_size = 3\nend_of_line = crlf\n[**]\ntab_width = 99999999999999999999\n", b"\xff\xfe[[[{{{,,\n=\n[" + b"*" * 300 + b"]\nindent_size = -1\n", b"[" + b"{a," * 120 + b"]\nx=y\n"]))
(P / "latin1.txt").write_bytes("caf\xe9 na\xefve \xa3\n".encode("latin-1"))
(P / "utf16.txt").write_bytes("﻿wide text\nline two\n".encode("utf-16-le"))
(P / "binary.bin").write_bytes(bytes(range(256)) * 20)
(P / "long.txt").write_bytes(("x" * 400000 + "\n").encode() + b"end\n")
(P / "many.txt").write_bytes(("line of text here\n" * 120000).encode())
(P / "big.log").write_bytes(b"y" * (9 * 1024 * 1024))
(P / "badutf.txt").write_bytes(b"ok \xff\xfe\xfa broken \xc3\x28 utf\n")
(P / "ro.txt").write_text("read only\n"); os.chmod(P / "ro.txt", 0o444)
os.symlink(P / "src" / "main.py", P / "link.py")
os.symlink(P, P / "src" / "loop")
os.symlink(P / "nowhere", P / "dangling")
os.mkfifo(P / "pipe")
subprocess.run(["git", "-C", str(P), "init", "-q", "-b", "main"]); subprocess.run(["git", "-C", str(P), "add", "-A"], capture_output=True)
subprocess.run(["git", "-C", str(P), "commit", "-qm", "start"], capture_output=True)
OUTSIDE = str(Path(home) / "outside.txt")
Path(OUTSIDE).write_text("not in the project\n")
ORIGINAL = {str(p): p.read_bytes() for p in P.rglob("*") if p.is_file() and not p.is_symlink() and ".git" not in p.parts and p.name != "pipe" and "loop" not in p.parts}

c = hc.Code(False, str(P))
said = []
c.said.connect(lambda m, w: said.append(m))
spin(300)


def docs():
    return c._docs


def ri():
    return random.choice(list(range(len(docs()))) + [-1, 99]) if random.random() < 0.9 else random.randrange(-3, 120)


def rpath():
    pool = [str(P / r) for r in FILES] + [str(P / n) for n in ("latin1.txt", "utf16.txt", "binary.bin", "long.txt", "many.txt", "big.log", "badutf.txt", "ro.txt", "link.py",
                                                                "dangling", "pipe", "src", "src/loop", "nope.txt", "", "src/loop/src/loop/src/main.py")] + [OUTSIDE, "/proc/self/mem", "/dev/zero", "relative.txt"]
    made = [str(p) for p in P.rglob("made*")][:20]
    return random.choice(pool + made)


WORDS = ["Shop", "total", "add", "self", "a", "", " ", "x" * 300, "(", "[a-", "\\", ".*", "^$", "(?P<n>", ASTRAL, "\n", "import", "é", "\t", "<<<<<<<"]


def mutate(text):
    if len(text) > 300000:
        return text[:1000] + random.choice(WORDS) + text[1000:] if random.random() < 0.5 else text[:500]
    k = random.random()
    at = random.randrange(0, len(text) + 1)
    if k < 0.35:
        return text[:at] + random.choice(WORDS + ["\n    ", "def f():\n    pass\n", "{", "}", '"', "'''"]) + text[at:]
    if k < 0.6:
        b = min(len(text), at + random.randrange(0, 40))
        return text[:at] + text[b:]
    if k < 0.7:
        return ""
    if k < 0.8:
        return text + "\n" * random.randrange(0, 4)
    if k < 0.9:
        return text.replace("\n", "\r\n", random.randrange(0, 3))
    return text[::-1][:5000]


def lc(i):
    if not 0 <= i < len(docs()):
        return random.randrange(-2, 50), random.randrange(-2, 50)
    lines = docs()[i].text.split("\n")
    line = random.choice([random.randrange(0, len(lines)), -1, len(lines) + 5, 0])
    col = random.choice([0, random.randrange(0, 200), -1, len(lines[line]) if 0 <= line < len(lines) else 3])
    return line, col


def op_edit():
    i = ri()
    return ("edit", i, mutate(docs()[i].text) if 0 <= i < len(docs()) else "x")


def op_multi():
    i = ri()
    n = len(docs()[i].text) if 0 <= i < len(docs()) else 10
    edits = [[random.randrange(-5, n + 20), random.randrange(-5, n + 20), random.choice(WORDS)] for _ in range(random.randrange(0, 5))]
    return ("multiEdit", i, edits, random.random() < 0.3)


OPS = [
    (10, lambda: ("openFile", rpath(), True, random.choice([-1, 0, 5, 10 ** 7]), random.choice([0, 3, -1, 10 ** 6]))),
    (12, op_edit),
    (6, lambda: ("save", ri(), random.random() < 0.3)),
    (2, lambda: ("saveAll",)),
    (4, lambda: ("close", ri(), random.random() < 0.6)),
    (3, lambda: ("select", ri())),
    (2, lambda: ("move", ri(), ri())),
    (2, lambda: ("reload", ri())),
    (2, lambda: ("newUntitled",)),
    (1, lambda: ("newFileIn", random.choice(["Python", "Rust", "nope", ""]))),
    (3, lambda: ("create", random.choice([str(P), str(P / "src"), str(P / "nope"), "/proc", ""]), random.choice(["made.txt", "made dir", "made/a/b.py", "../made_out.txt", "", ".", "..", "a\x00b", "x" * 300, "made.md"]), random.random() < 0.3)),
    (3, lambda: ("rename", rpath(), random.choice(["made2.txt", "", "../up.txt", "src", "a/b", "main.py", "made 3 ü.py"]))),
    (2, lambda: ("remove", rpath())),
    (2, lambda: ("toggle", rpath())),
    (2, lambda: ("browse", rpath())),
    (3, lambda: ("quickOpen", random.choice(WORDS + ["main", "src/", ">save", ":12", "@tot", ":x", "@"]))),
    (3, lambda: ("search", random.choice(WORDS), random.random() < 0.5, random.random() < 0.5, random.random() < 0.3)),
    (3, lambda: ("replaceAll", random.choice(WORDS), random.choice(["", "Z", "\\1", "$1", "\\g<9>", ASTRAL]), random.random() < 0.5, random.random() < 0.5, random.random() < 0.3)),
    (2, lambda: ("symbols", ri())),
    (2, lambda: ("outline", ri())),
    (2, lambda: ("crumbsAt", ri(), random.randrange(-3, 300))),
    (2, lambda: ("stickyAt", ri(), random.randrange(-3, 300))),
    (2, lambda: ("marksOf", ri())),
    (1, lambda: ("problemsOf", ri())),
    (3, lambda: (lambda i: ("wordAt", i, *lc(i)))(ri())),
    (2, lambda: (lambda i: ("references", i, *lc(i)))(ri())),
    (2, lambda: (lambda i: ("renameSymbol", i, *lc(i), random.choice(["newName", "", "a b", ASTRAL, "class"])))(ri())),
    (2, lambda: (lambda i: ("complete", i, *lc(i)))(ri())),
    (2, lambda: (lambda i: ("definition", i, *lc(i)))(ri())),
    (2, lambda: (lambda i: ("hover", i, *lc(i)))(ri())),
    (2, lambda: (lambda i: ("signatureAt", i, *lc(i)))(ri())),
    (2, lambda: (lambda i: ("quickFixes", i, *lc(i)))(ri())),
    (1, lambda: ("applyFix", random.randrange(-1, 5))),
    (4, op_multi),
    (2, lambda: ("expandSnippet", ri(), random.choice(["for ${1:i} in ${2:xs}:\n\t$0", "$", "${", "${1", "${1:${2:x}}", "$1$1$1", "\\$1 }", ""]), random.choice(["", "    ", "\t"]))),
    (2, lambda: ("conflictsOf", ri())),
    (2, lambda: ("resolveConflict", ri(), random.randrange(-2, 4), random.choice(["ours", "theirs", "both", "nope"]))),
    (1, lambda: ("markResolved", random.choice(["conflict.py", "nope", "../x", ""]))),
    (2, lambda: ("format", ri())),
    (2, lambda: ("blame", ri())),
    (1, lambda: ("history", random.choice(["", "src/main.py", "nope", "../.."]))),
    (1, lambda: ("commitInfo", random.choice(["HEAD", "nope", "", "--help", "-n1"]))),
    (1, lambda: ("commitRows", random.choice(["HEAD", "nope", "--all"]), random.choice(["", "src/main.py"]))),
    (2, lambda: ("refreshGit",)),
    (2, lambda: ("diff", random.choice(["src/main.py", "crlf.txt", "nope", "", "binary.bin", "../x", "-p"]), random.random() < 0.5)),
    (2, lambda: ("stage", random.choice(["src/main.py", "crlf.txt", "nope", "", "made.txt", "--all", "../x"]))),
    (1, lambda: ("unstage", random.choice(["src/main.py", "nope", ""]))),
    (1, lambda: ("stageAll",)),
    (1, lambda: ("discard", random.choice(["crlf.txt", "nope", "", "made.txt", "docs/notes.md"]))),
    (1, lambda: ("commit", random.choice(["A change", "", "x" * 5000, "-m evil", "multi\nline"]))),
    (1, lambda: ("branches",)),
    (1, lambda: ("newBranch", random.choice(["feature", "", "a b", "-D", "main", "x/y", "ü"]))),
    (1, lambda: ("switchBranch", random.choice(["feature", "main", "nope", "", "-"]))),
    (1, lambda: ("deleteBranch", random.choice(["feature", "main", "nope", ""]))),
    (2, lambda: ("toggleBreakpoint", ri(), random.randrange(-3, 400))),
    (1, lambda: ("breakpointsOf", ri())),
    (1, lambda: ("setOption", random.choice(["formatOnSave", "trimOnSave", "guides", "occurrences", "nope", ""]), random.random() < 0.5)),
    (2, lambda: ("reopenClosed",)),
    (2, lambda: ("placeOf", random.randint(-2, 12))),
    (2, lambda: ("setPlace", random.randint(-2, 12), random.choice([0, 5, -1, 10 ** 9, 400])),),
    (1, lambda: ("fileThere", random.choice(["", "/", "\0", str(P / "latin1.txt"), "x" * 5000]))),
    (1, lambda: ("setSize", random.choice([13, 0, -5, 500]))),
    (1, lambda: ("setWrap", random.random() < 0.5)),
    (1, lambda: ("setMinimap", random.random() < 0.5)),
    (1, lambda: ("relOf", ri())),
    (1, lambda: ("openRel", random.choice(["src/main.py", "nope", "../../etc/passwd", ""]), random.choice([-1, 3, 10 ** 6]), 0)),
    (1, lambda: ("textOf", ri())),
    (1, lambda: ("openFolder", random.choice([str(P), str(P / "src"), str(P / "nope"), "/proc/self", str(P / "src" / "main.py"), ""]), random.random() < 0.5)),
    (1, lambda: ("setRun", random.choice(["", "python3 main.py", "x" * 2000]))),
    (1, lambda: ("runCommand",)),
    (1, lambda: ("copyPath", rpath())),
]
BAG = [f for w, f in OPS for _ in range(w)]


def expected_bytes(d):
    text = d.text.replace("\n", "\r\n") if d.crlf else d.text
    try:
        return (d.wide or (b"\xef\xbb\xbf" if d.bom else b"")) + text.encode(d.encoding)
    except Exception:
        return None


def check_state(op):
    cur = c.current
    if not (-1 <= cur < max(1, len(docs())) or (cur == -1 and not docs())):
        problem("the current tab isn't one of the tabs", f"{op[0]}: current {cur} of {len(docs())}")
    if docs() and not 0 <= cur < len(docs()):
        problem("tabs are open but none is current", f"{op[0]}: current {cur} of {len(docs())}")
    paths = [d.path for d in docs() if d.path]
    if len(paths) != len(set(paths)):
        problem("the same file is open in two tabs", f"{op[0]}")
    try:
        tabs = c.tabs
        if len(tabs) != len(docs()):
            problem("the tab strip and the documents disagree", f"{op[0]}: {len(tabs)} vs {len(docs())}")
    except Exception:
        problem(f"listing the tabs after {op[0]}", traceback.format_exc())
    for d in docs():
        if not isinstance(d.text, str):
            problem("a tab whose text isn't text", f"{op[0]}: {type(d.text).__name__}")
        if "\r" in d.text and not d.binary and d.path not in CR_SEEN:
            CR_SEEN.add(d.path)
            problem("a carriage return left inside an open document", f"{op[0]}: {os.path.basename(d.path)}")


CR_SEEN = set()
t0 = time.time()
saves = untouched = 0
for n in range(STEPS):
    op = random.choice(BAG)()
    log.append(repr(op)[:150])
    open(home + "/now.txt", "w").write(f"{n} {op!r}"[:400])
    t1 = time.time()
    try:
        got = getattr(c, op[0])(*op[1:])
    except Exception:
        problem(f"{op[0]} raised", traceback.format_exc())
        got = None
    if time.time() - t1 > 1.5:
        problem(f"{op[0]} took long", f"{time.time() - t1:.1f}s: {op!r}"[:300])
    spin(3)
    try:
        check_state(op)
    except Exception:
        problem(f"checking after {op[0]}", traceback.format_exc())
    # a save that says it worked leaves on disk exactly what the tab holds, in the file's own encoding and line endings
    if op[0] == "save" and got == "" and 0 <= op[1] < len(docs()):
        d = docs()[op[1]]
        if d.path and os.path.isfile(d.path) and not d.binary:
            want = expected_bytes(d)
            have = Path(d.path).read_bytes()
            saves += 1
            if want is not None and have != want and not c.options["trimOnSave"] and not c.options["formatOnSave"] and not getattr(d, "mixed", False):
                problem("what was saved isn't what the tab holds", f"{d.path}: {len(have)} bytes on disk, {len(want)} expected")
            if d.dirty and not c.options["formatOnSave"]:
                problem("still marked unsaved after a save that worked", d.path)
    if n % 150 == 0:
        # a file opened and saved without a change keeps every byte (tidying off for this check)
        opts = {k: c.options[k] for k in ("trimOnSave", "formatOnSave")}
        for k in opts:
            c.setOption(k, False)
        for name in ("crlf.txt", "bom.txt", "latin1.txt", "astral.txt", "noeol.txt", "tabs.c", "mixed.txt", "badutf.txt", "empty.txt"):
            p = str(P / name)
            if not os.path.isfile(p) or any(d.path == p for d in docs()):
                continue
            raw = Path(p).read_bytes()
            try:
                c.openFile(p)
                i = next((k for k, d in enumerate(docs()) if d.path == p), -1)
                if i >= 0 and not docs()[i].read_only:
                    r = c.save(i, True)
                    after = Path(p).read_bytes()
                    untouched += 1
                    if r == "" and after != raw:
                        problem("opening and saving a file changed it", f"{name}: {raw[:40]!r} became {after[:40]!r}")
                if i >= 0:
                    c.close(i, True)
            except Exception:
                problem(f"open and save {name}", traceback.format_exc())
        for k, v in opts.items():
            c.setOption(k, bool(v))
    if n % 300 == 0:
        print(f"step {n}: {len(docs())} tabs, {len(problems)} kinds of problem, {time.time() - t0:.0f}s", flush=True)

if not os.path.isfile(OUTSIDE) and not any(op.startswith("('remove'") or op.startswith("('rename'") for op in []):
    problem("a file outside the project was renamed or removed", OUTSIDE)
outside = [p for p in (Path(home) / "made_out.txt", Path(home) / "up.txt", P.parent / "x") if p.exists()]
if outside:
    problem("something was written outside the project", str(outside))
for p, raw in ORIGINAL.items():
    name = os.path.basename(p)
    if name in ("binary.bin", "big.log") and os.path.isfile(p) and Path(p).read_bytes() != raw:
        problem("a file Code can't edit was changed", name)
print(f"\n{STEPS} steps, seed {SEED}: {saves} saves checked, {untouched} untouched round trips, {sum(v['n'] for v in problems.values())} problems of {len(problems)} kinds")
for k, v in sorted(problems.items(), key=lambda kv: -kv[1]["n"]):
    print(f"\n=== x{v['n']}  {k}")
    print("   ", v["detail"].strip().replace("\n", "\n    ")[-900:])
    print("    last steps:", " ; ".join(t[:120] for t in v["trail"][-3:]))
os._exit(0)
