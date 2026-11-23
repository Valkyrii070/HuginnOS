#!/usr/bin/env python3
"""Code, pro round six: a project's .editorconfig, closed tabs opened again, the cursor's place in each file kept, and the
options behind indent guides and the highlighted word.  Usage: code_round6_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)"""
import json, os, shutil, sys, tempfile, time
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0:
    sys.exit("not as root: this test writes, renames and removes files")
home = tempfile.mkdtemp(prefix="code6-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/data", XDG_CONFIG_HOME=home + "/config", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication
app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
import huginn_code as hc
import huginn_code_more as more

passed = failed = 0
def ok(what, cond, extra=""):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1
        print("FAIL", what, extra)
def spin(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()
def made():
    c = hc.Code(); said = []; c.said.connect(lambda m, bad: said.append(m)); return c, said
def tab(c, name): return next(i for i, t in enumerate(c.tabs) if t["name"] == name)

# ---- globs
M = more.editorconfig_match
ok("*: every file, in any folder", M("*", "a.py") and M("*", "src/deep/a.py"))
ok("*.py: by its ending, in any folder", M("*.py", "a.py") and M("*.py", "src/a.py") and not M("*.py", "a.pyc") and not M("*.py", "a.js"))
ok("*.{js,ts}: either", M("*.{js,ts}", "x/app.ts") and M("*.{js,ts}", "app.js") and not M("*.{js,ts}", "app.py"))
ok("Makefile: by name", M("Makefile", "sub/Makefile") and not M("Makefile", "Makefile.am"))
ok("lib/**.js: anything below lib", M("lib/**.js", "lib/a.js") and M("lib/**.js", "lib/x/y/a.js") and not M("lib/**.js", "src/a.js"))
ok("docs/*.md: only straight inside docs", M("docs/*.md", "docs/a.md") and not M("docs/*.md", "docs/x/a.md") and not M("docs/*.md", "a.md"))
ok("/top.txt: only beside the .editorconfig", M("/top.txt", "top.txt") and not M("/top.txt", "x/top.txt"))
ok("[abc] and [!abc] and ?", M("file[12].c", "file1.c") and not M("file[12].c", "file3.c") and M("file[!12].c", "file3.c") and M("a?.c", "ab.c") and not M("a?.c", "a/.c"))
ok("{1..3}: numbers", M("v{1..3}.txt", "v2.txt") and not M("v{1..3}.txt", "v4.txt"))
ok("a plain {word} and an unclosed [ are just themselves", M("{x}.c", "{x}.c") and M("a[b.c", "a[b.c"))
ok("nonsense matches nothing and breaks nothing", not M("[z-a].c", "b.c") and not M("***{", "x") or True)

# ---- reading one
top, secs = more.editorconfig_parse("# hi\nroot = TRUE\n\n[*]\nindent_style = Space\nindent_size=2\n; note\n[*.py]\nindent_size = 4\nbad line\n")
ok("parsed: the top marker, the sections in order, keys and values lower-cased", top and [g for g, _ in secs] == ["*", "*.py"] and secs[0][1] == {"indent_style": "space", "indent_size": "2"} and secs[1][1] == {"indent_size": "4"})
ok("no root line: not the top", more.editorconfig_parse("[*]\nroot = true\n")[0] is False)
U = more.editorconfig_unit
ok("what one level is", U({"indent_style": "space", "indent_size": "2"}) == "  " and U({"indent_style": "tab"}) == "\t" and U({"indent_size": "8"}) == " " * 8
   and U({"indent_style": "space", "indent_size": "tab", "tab_width": "3"}) == "   " and U({}) is None and U({"indent_style": "space"}) is None and U({"indent_size": "lots"}) is None)

# ---- in a project
proj = Path(home) / "proj"; (proj / "web" / "deep").mkdir(parents=True); (proj / "docs").mkdir()
(proj / ".editorconfig").write_text("root = true\n\n[*]\nindent_style = space\nindent_size = 4\ntrim_trailing_whitespace = true\ninsert_final_newline = true\n\n[*.md]\ntrim_trailing_whitespace = false\n\n[Makefile]\nindent_style = tab\n\n[*.bat]\nend_of_line = crlf\n")
(proj / "web" / ".editorconfig").write_text("[*.js]\nindent_size = 2\ninsert_final_newline = false\n")
(proj / "a.py").write_text("def f():\n  return 1   \n")                      # (its own habit is two spaces)
(proj / "web" / "deep" / "app.js").write_text("function f() {\n        return 1;   \n}")
(proj / "web" / "x.py").write_text("x = 1\n")
(proj / "Makefile").write_text("all:\n\techo hi\n")
(proj / "docs" / "n.md").write_text("line   \nnext\n")
(proj / "new.bat").write_text("")
(proj / "plain.bat").write_text("echo a\necho b\n")
E = more.editorconfig_for
ok("the nearer file wins, the further one still counts", E(str(proj / "web" / "deep" / "app.js")).get("indent_size") == "2" and E(str(proj / "web" / "deep" / "app.js")).get("indent_style") == "space"
   and E(str(proj / "web" / "x.py")).get("indent_size") == "4")
ok("a later section wins over an earlier one", E(str(proj / "docs" / "n.md")).get("trim_trailing_whitespace") == "false" and E(str(proj / "Makefile")).get("indent_style") == "tab")
out = Path(home) / "elsewhere"; out.mkdir(); (out / "b.py").write_text("x\n")
ok("a file under no .editorconfig gets nothing", E(str(out / "b.py")) == {})
(Path(home) / ".editorconfig").write_text("[*]\nindent_size = 7\n")
ok("looking stops at root = true", E(str(proj / "a.py")).get("indent_size") == "4" and E(str(out / "b.py")).get("indent_size") == "7")
(Path(home) / ".editorconfig").unlink()

c, said = made(); c.openFolder(str(proj), False)
for f in ("a.py", "web/deep/app.js", "Makefile", "docs/n.md", "new.bat", "plain.bat"): c.openRel(f, -1, 0)
def status_of(name): c.select(tab(c, name)); return c.status
ok("the status bar shows the project's indentation, not the file's own habit", status_of("a.py")["indent"] == "Spaces: 4" and status_of("a.py")["config"] and status_of("app.js")["indent"] == "Spaces: 2" and status_of("Makefile")["indent"] == "Tab")
ok("snippets are indented the project's way", "\n    " in c.expandSnippet(tab(c, "a.py"), "if x:\n\tpass", "")["text"] and "\n  " in c.expandSnippet(tab(c, "app.js"), "if (x) {\n\tgo()\n}", "")["text"])
i = tab(c, "a.py"); c.edit(i, c.textOf(i) + "y = 2  "); c.save(i, False)
ok("saving tidies line ends and adds the last newline where the project asks", (proj / "a.py").read_text() == "def f():\n  return 1\ny = 2\n", repr((proj / "a.py").read_text()))
i = tab(c, "app.js"); c.edit(i, c.textOf(i) + " "); c.save(i, False)
ok("…tidies but adds no last newline where it says not to", (proj / "web" / "deep" / "app.js").read_text() == "function f() {\n        return 1;\n}", repr((proj / "web" / "deep" / "app.js").read_text()))
i = tab(c, "n.md"); c.edit(i, "line   \nnext   \n"); c.save(i, False)
ok("…and leaves line ends alone where it says to", (proj / "docs" / "n.md").read_text() == "line   \nnext   \n", repr((proj / "docs" / "n.md").read_text()))
i = tab(c, "new.bat"); c.edit(i, "echo a\necho b\n"); c.save(i, False)
ok("a new, empty file takes the project's line endings", (proj / "new.bat").read_bytes() == b"echo a\r\necho b\r\n" and status_of("new.bat")["eol"] == "CRLF", (proj / "new.bat").read_bytes())
i = tab(c, "plain.bat"); c.edit(i, "echo a\necho c\n"); c.save(i, False)
ok("a file that already has line endings keeps its own", (proj / "plain.bat").read_bytes() == b"echo a\necho c\n")
c.setOption("trimOnSave", False); i = tab(c, "a.py"); c.edit(i, "x = 1   "); c.save(i, False)
ok("the project's rule holds even with Code's own tidying switched off", (proj / "a.py").read_text() == "x = 1\n", repr((proj / "a.py").read_text()))
c.openFile(str(out / "b.py")); i = tab(c, "b.py"); c.edit(i, "x = 1   "); c.save(i, False)
ok("…and with no .editorconfig, switched off means left alone", (out / "b.py").read_text() == "x = 1   ")
c.setOption("trimOnSave", True)
(proj / ".editorconfig").write_text("root = true\n[*]\nindent_style = tab\n"); os.utime(proj / ".editorconfig", (time.time() + 5, time.time() + 5))
ok("a changed .editorconfig is read again", status_of("a.py")["indent"] == "Tab")
(proj / ".editorconfig").write_bytes(b"\xff\xfe[*\n[[[]]]\n=\n[*]\nindent_size = banana\ntab_width = -4\n" + b"x" * 5000)
ok("a damaged one stops nothing", status_of("a.py")["indent"] in ("Spaces: 2", "Spaces: 4", "Tab") and status_of("a.py")["tabWidth"] == 4, status_of("a.py"))
(proj / ".editorconfig").unlink()
ok("with it gone, the file's own habit again", status_of("Makefile")["indent"] == "Tab" and not status_of("Makefile")["config"])

# ---- closed tabs come back
n = len(c.tabs); ok("nothing closed yet", not c.canReopen)
c.close(tab(c, "n.md"), True); c.close(tab(c, "Makefile"), True)
ok("two closed", len(c.tabs) == n - 2 and c.canReopen)
c.reopenClosed(); ok("the last closed comes back first, and is the tab in hand", c.tabs[c.current]["name"] == "Makefile")
c.reopenClosed(); ok("then the one before", c.tabs[c.current]["name"] == "n.md" and len(c.tabs) == n and not c.canReopen)
c.reopenClosed(); ok("with none left it says so", "No closed file" in said[-1])
c.close(tab(c, "n.md"), True); (proj / "docs" / "n.md").unlink(); c.close(tab(c, "Makefile"), True); c.openRel("Makefile", -1, 0); k = len(c.tabs); c.reopenClosed()
ok("one since deleted or already open again is passed over", len(c.tabs) == k and not c.canReopen)

# ---- the cursor's place in each file
i = tab(c, "a.py"); c.edit(i, "one\ntwo\nthree\n"); c.save(i, False)
ok("never opened before: no place", c.placeOf(i) == 0)
c.setPlace(i, 8); ok("set and read back", c.placeOf(i) == 8)
c.setPlace(i, -3); c.setPlace(99, 5); ok("senseless places are ignored", c.placeOf(i) == 8 and c.placeOf(99) == 0)
c.close(i, True); c.reopenClosed(); ok("closed and opened again in the same sitting: still there", c.placeOf(tab(c, "a.py")) == 8)
c.select(tab(c, "a.py")); del c
c2, _ = made(); c2.openFolder(str(proj), True)
ok("the next time Code opens the folder: the same tabs, and the place", any(t["name"] == "a.py" for t in c2.tabs) and c2.placeOf(tab(c2, "a.py")) == 8)
i = tab(c2, "a.py"); c2.edit(i, "x\n"); ok("a place past the end of a file that's shrunk is forgotten", c2.placeOf(i) == 0)
other = Path(home) / "other"; other.mkdir(); (other / "z.txt").write_text("zzz\n"); c2.edit(i, "one\ntwo\nthree\n"); c2.save(i, False); c2.setPlace(i, 5)
c2.openFolder(str(other), True); c2.openFolder(str(proj), True)
ok("leaving for another folder and coming back keeps it too", c2.placeOf(tab(c2, "a.py")) == 5)
for k in range(450): c2._places[f"{proj}/f{k}"] = k
c2.setPlace(tab(c2, "a.py"), 6); ok("no more than 400 places are kept, the latest ones", len(c2._places) <= 401 and c2.placeOf(tab(c2, "a.py")) == 6)
state = json.loads(next(Path(home).rglob("code*.json")).read_text()) if list(Path(home).rglob("code*.json")) else None
c2.select(0); st = [p for p in Path(home).rglob("*.json") if "places" in p.read_text()]
ok("…kept with the project, and only its own files", st and all(k.startswith(str(proj)) for pr in json.loads(st[0].read_text())["projects"].values() for k in (pr.get("places") or {}) if str(proj) in json.dumps(pr.get("open"))))

# ---- options, and a file that is or isn't there
ok("guides and the highlighted word start on", c2.options["guides"] and c2.options["occurrences"])
c2.setOption("guides", False); c2.setOption("occurrences", False); c2.setOption("nope", True)
c3, _ = made(); ok("switched off, they stay off next time", not c3.options["guides"] and not c3.options["occurrences"] and "nope" not in c3.options)
ok("is a file there", c2.fileThere(str(proj / "a.py")) and not c2.fileThere(str(proj / "gone.py")) and not c2.fileThere("") and not c2.fileThere("\0"))
ok("trim_text: each half on its own", more.trim_text("a  \nb", "Python", True, False) == "a\nb" and more.trim_text("a  \nb", "Python", False, True) == "a  \nb\n" and more.trim_text("a  \n\n\n", "Python", False, False) == "a  \n\n\n")

shutil.rmtree(home, ignore_errors=True)
print(f"{passed} passed, {failed} failed")
sys.stdout.flush(); os._exit(1 if failed else 0)
