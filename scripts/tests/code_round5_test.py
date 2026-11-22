#!/usr/bin/env python3
"""Code, pro round five: whole-line commands, change marks that follow typing with put-back, unsaved work kept through
a quit, and the hardening the fuzz asked for.  Usage: code_round5_test.py <kit root>   (QT_QPA_PLATFORM=offscreen)"""
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
home = tempfile.mkdtemp(prefix="code5-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/data", XDG_CONFIG_HOME=home + "/config", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
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
def ap(t, r): return t[:r[0]] + r[2] + t[r[1]:]
def made(**kw):
    c = next(v for k, v in vars(hc).items() if isinstance(v, type) and hasattr(v, "lineEdit"))
    return c(**kw) if kw else c()

# ---- whole lines
t = "one\n  two\nthree\nfour"
ok("move up", ap(t, more.line_edit(t, 5, 5, "up")) == "  two\none\nthree\nfour")
ok("move down", ap(t, more.line_edit(t, 5, 5, "down")) == "one\nthree\n  two\nfour")
ok("first line can't go up", more.line_edit(t, 1, 1, "up") is None)
ok("last line can't go down", more.line_edit(t, len(t), len(t), "down") is None)
r = more.line_edit(t, 5, 12, "down")
ok("a block moves down, still selected", ap(t, r) == "one\nfour\n  two\nthree" and (r[3], r[4]) == (10, 17), r)
ok("selection ending at a line start leaves that line", ap(t, more.line_edit(t, 0, 4, "down")) == "  two\none\nthree\nfour")
ok("copy down", ap(t, more.line_edit(t, 5, 5, "copy_down")) == "one\n  two\n  two\nthree\nfour")
r = more.line_edit(t, 6, 6, "copy_up")
ok("copy up keeps the cursor on the first copy", ap(t, r) == "one\n  two\n  two\nthree\nfour" and r[3] == 6)
ok("delete a line", ap(t, more.line_edit(t, 5, 5, "delete")) == "one\nthree\nfour")
ok("delete the last line", ap(t, more.line_edit(t, len(t), len(t), "delete")) == "one\n  two\nthree")
ok("delete the only line", ap("x", more.line_edit("x", 0, 0, "delete")) == "" and more.line_edit("", 0, 0, "delete") is None)
r = more.line_edit(t, 0, 0, "join")
ok("join with the next line", ap(t, r) == "one two\nthree\nfour" and r[3] == 3, r)
ok("join a selection", ap(t, more.line_edit(t, 0, len(t), "join")) == "one two three four")
ok("join with an empty line adds no space", ap("a\n\nb", more.line_edit("a\n\nb", 0, 0, "join")) == "a\nb")
ok("sort", ap(t, more.line_edit(t, 0, len(t), "sort")) == "  two\nfour\none\nthree")
ok("sort z to a", ap("b\na\nc", more.line_edit("b\na\nc", 0, 5, "sort_desc")) == "c\nb\na")
ok("sort ignores case", ap("b\nA\nc", more.line_edit("b\nA\nc", 0, 5, "sort")) == "A\nb\nc")
ok("sorted already: nothing to do", more.line_edit("a\nb", 0, 3, "sort") is None)
ok("repeated lines go", ap("a\nb\na\nb\nc", more.line_edit("a\nb\na\nb\nc", 0, 9, "unique")) == "a\nb\nc")
ok("upper case the selection", ap(t, more.line_edit(t, 0, 3, "upper")) == "ONE\n  two\nthree\nfour")
ok("upper case the line with nothing selected", ap(t, more.line_edit(t, 6, 6, "upper")) == "one\n  TWO\nthree\nfour")
ok("lower case", ap("ABC", more.line_edit("ABC", 0, 3, "lower")) == "abc")
ok("title case", ap("the old man's SEA", more.line_edit("the old man's SEA", 0, 17, "title")) == "The Old Man's Sea")
ok("upper case that grows (ß)", ap("straße", more.line_edit("straße", 0, 6, "upper")) == "STRASSE")
r = more.line_edit(t, 6, 6, "below")
ok("new line below keeps the indent", ap(t, r) == "one\n  two\n  \nthree\nfour" and r[3] == 12, r)
r = more.line_edit(t, 6, 6, "above")
ok("new line above keeps the indent", ap(t, r) == "one\n  \n  two\nthree\nfour" and r[3] == 6, r)
r = more.line_edit(t, 6, 6, "select")
ok("select the line", (r[3], r[4]) == (4, 10) and r[2] == "")
ok("an unknown command does nothing", more.line_edit(t, 0, 0, "explode") is None)
ok("positions past the end are safe", more.line_edit(t, 999, 9999, "up") is not None and more.line_edit("", 5, 9, "sort") is None)
ok("editor positions: plain", more.from16("abc", 2) == 2 and more.u16("abc", 2) == 2)
ok("editor positions: past an emoji", more.from16("a😀b", 3) == 2 and more.u16("a😀b", 2) == 3)
ok("editor positions: inside an emoji", more.from16("a😀b", 2) in (1, 2))

# ---- what changed
old = "a\nb\nc\nd\ne"
ok("nothing changed", more.changes(old, old) == [])
c = more.changes(old, "a\nb\nX\nd\ne")
ok("a changed line", len(c) == 1 and (c[0]["a"], c[0]["b"], c[0]["kind"], c[0]["old"]) == (2, 3, "mod", ["c"]), c)
c = more.changes(old, "a\nb\nnew\nc\nd\ne")
ok("an added line", len(c) == 1 and (c[0]["a"], c[0]["b"], c[0]["kind"]) == (2, 3, "add"), c)
c = more.changes(old, "a\nb\nd\ne")
ok("a removed line", len(c) == 1 and (c[0]["a"], c[0]["b"], c[0]["kind"], c[0]["old"]) == (2, 2, "del", ["c"]), c)
ok("marks", more.change_marks(more.changes(old, "a\nQ\nc\nd\ne\nf"), 6) == {1: "mod", 5: "add"})
ok("a removal at the end is marked on the last line", more.change_marks(more.changes(old, "a\nb\nc\nd"), 4) == {3: "del"})
for new in ("a\nb\nX\nd\ne", "a\nb\nnew\nc\nd\ne", "a\nb\nd\ne", "a\nb\nc\nd", "b\nc\nd\ne", "a\nb\nc\nd\ne\nf\ng", "", "x", "a\nb\nc\nd\ne\n"):
    cur, n = new, 0
    while more.changes(old, cur) and n < 20:
        cur, n = ap(cur, more.put_back(cur, more.changes(old, cur)[0])), n + 1
    ok(f"put back {new!r}", cur == old, cur)
ok("the change on a line", more.change_at(more.changes(old, "a\nb\nX\nd\ne"), 2)["kind"] == "mod" and more.change_at(more.changes(old, "a\nb\nX\nd\ne"), 3) is None)
ok("a removal belongs to its line", more.change_at(more.changes(old, "a\nb\nd\ne"), 2)["kind"] == "del")
big_old = "\n".join(f"line {n}" for n in range(15000))
big_new = big_old.replace("line 7000\n", "line seven thousand\n").replace("line 12000\n", "")
t0 = time.time(); c = more.changes(big_old, big_new); took = time.time() - t0
ok("15 000 lines compared quickly", len(c) == 2 and took < 1.5, f"{len(c)} in {took:.2f}s")
t0 = time.time(); c = more.changes("same\n" * 9000, "same\n" * 4000 + "other\n" + "same\n" * 4000 + "x"); took = time.time() - t0
ok("thousands of the same line don't stall it", took < 1.5 and len(c) >= 1, f"{len(c)} in {took:.2f}s")
ok("past the limit: left to Git", more.changes("\n" * 30000, "x" + "\n" * 30000) == [])

# ---- in the app
proj = Path(home) / "proj"; proj.mkdir()
def git(*a): return subprocess.run(["git", "-C", str(proj), *a], capture_output=True, text=True, env=dict(os.environ, GIT_AUTHOR_NAME="Astrid Berg", GIT_AUTHOR_EMAIL="astrid@example.org", GIT_COMMITTER_NAME="Astrid Berg", GIT_COMMITTER_EMAIL="astrid@example.org"))
(proj / "a.py").write_text("one = 1\ntwo = 2\nthree = 3\nfour = 4\n")
(proj / "crlf.txt").write_bytes(b"x\r\ny\r\nz\r\n")
(proj / "mixed.txt").write_bytes(b"one\r\ntwo\nthree\rfour\n")
(proj / "wide.txt").write_bytes(b"\xff\xfe" + "héllo\nwörld\n".encode("utf-16-le"))
(proj / "bad.bin.txt").write_bytes(b"caf\xe9 \xff\xfe\n")
git("init", "-q"); git("add", "-A"); git("commit", "-qm", "first")
(Path(home) / "outside.txt").write_text("keep me\n")
c = made()
said = []
c.said.connect(lambda m, bad: said.append(m))
c.openFolder(str(proj)); spin(200)
def idx(name): return next(i for i, d in enumerate(c._docs) if d.path.endswith("/" + name))
c.openFile(str(proj / "a.py")); spin(100)
i = idx("a.py"); d = c._docs[i]
ok("committed text is known", d.head == "one = 1\ntwo = 2\nthree = 3\nfour = 4\n" and d.marks == {})
c.edit(i, "one = 1\ntwo = 22\nthree = 3\nnew = 0\nfour = 4\n")
ok("marks wait for the pause", d.marks == {})
spin(900)
ok("marks follow typing, unsaved", c.marksOf(i) == {"1": "mod", "3": "add"}, c.marksOf(i))
ok("next change", c.changeNear(i, 0, 1) == 1 and c.changeNear(i, 1, 1) == 3)
ok("next change goes round", c.changeNear(i, 3, 1) == 1 and c.changeNear(i, 4, 1) == 1)
ok("previous change", c.changeNear(i, 4, -1) == 3 and c.changeNear(i, 1, -1) == 3)
r = c.putBack(i, 1)
ok("put a changed line back", r and d.text[:r["at"]] + r["text"] + d.text[r["end"]:] == "one = 1\ntwo = 2\nthree = 3\nnew = 0\nfour = 4\n", r)
c.edit(i, d.text[:r["at"]] + r["text"] + d.text[r["end"]:])
r = c.putBack(i, 3)
c.edit(i, d.text[:r["at"]] + r["text"] + d.text[r["end"]:]); spin(800)
ok("all put back: clean, no marks", not d.dirty and c.marksOf(i) == {}, (d.text, c.marksOf(i)))
ok("an unchanged line has nothing to put back", c.putBack(i, 0) == {} and c.changeNear(i, 0, 1) == -1)
r = c.lineEdit(i, 9, 9, "up")
ok("line command through the app", r and r["text"] == "two = 2\none = 1" and (r["at"], r["end"]) == (0, 15), r)
ok("line command on a bad tab", c.lineEdit(99, 0, 0, "up") == {} and c.lineEdit(i, 0, 0, "nope") == {})
c.edit(i, "😀 = 1\ntwo = 2\n")
r = c.lineEdit(i, 9, 9, "up")     # the editor counts the emoji as two
ok("line command past an emoji, in the editor's positions", r and r["text"] == "two = 2\n😀 = 1" and (r["at"], r["end"], r["a"]) == (0, 14, 2), r)
c.edit(i, "one = 1\ntwo = 2\nthree = 3\nfour = 4\n")

# ---- unsaved work, kept
c.edit(i, "one = 1\nunsaved work\n")
spin(2400)
stash = hc.UNSAVED / c._stash_file(d.path).name
ok("unsaved work is put by", stash.is_file() and json.loads(stash.read_text())["text"] == "one = 1\nunsaved work\n")
ok("only you can read it", (stash.stat().st_mode & 0o077) == 0 and (hc.UNSAVED.stat().st_mode & 0o077) == 0)
ok("the file on disk is untouched", (proj / "a.py").read_text() == "one = 1\ntwo = 2\nthree = 3\nfour = 4\n")
c._stash_now()
c2 = made(); said2 = []; c2.said.connect(lambda m, bad: said2.append(m)); spin(1800)
j = next((k for k, x in enumerate(c2._docs) if x.path.endswith("/a.py")), -1)
ok("a new start brings it back, unsaved", j >= 0 and c2._docs[j].text == "one = 1\nunsaved work\n" and c2._docs[j].dirty, [x.path for x in c2._docs])
ok("and says so", any("Brought back" in m and "a.py" in m for m in said2), said2)
ok("saving it works and lets the copy go", c2.save(j, False) == "" and (proj / "a.py").read_text() == "one = 1\nunsaved work\n")
c2._stash_now()
ok("no copy once saved", not stash.exists())
d.text = d.saved = c._docs[i].text; c.reload(i)
# changed on disk meanwhile
c2.edit(j, "one = 1\nmine\n"); c2._stash_now()
time.sleep(0.02); (proj / "a.py").write_text("someone else's\n")
c3 = made(); said3 = []; c3.said.connect(lambda m, bad: said3.append(m)); spin(1800)
k = next(n for n, x in enumerate(c3._docs) if x.path.endswith("/a.py"))
ok("brought back over a file that changed: says so", c3._docs[k].text == "one = 1\nmine\n" and any("changed on disk" in m for m in said3), said3)
ok("and saving asks first", c3.save(k, False) == "changed" and (proj / "a.py").read_text() == "someone else's\n")
ok("closing without saving lets the copy go", c3.close(k, True) == "" and not stash.exists())
hc.UNSAVED.mkdir(parents=True, exist_ok=True)
(hc.UNSAVED / "junk.json").write_text("{not json")
(hc.UNSAVED / "odd.json").write_text(json.dumps({"path": str(Path(home) / "outside.txt"), "text": 5}))
old_one = hc.UNSAVED / "old.json"; old_one.write_text(json.dumps({"path": str(proj / "crlf.txt"), "text": "ancient"})); os.utime(old_one, (time.time() - 40 * 86400,) * 2)
c4 = made(); spin(300)
ok("junk in the folder is harmless", (Path(home) / "outside.txt").read_text() == "keep me\n" and not any(x.dirty for x in c4._docs))
ok("work put by over a month ago is let go", not old_one.exists())
for f in hc.UNSAVED.glob("*.json"): f.unlink()

# ---- hardening
i = idx("a.py") if any(x.path.endswith("/a.py") for x in c._docs) else -1
c.openFile(str(proj / "mixed.txt")); m = idx("mixed.txt")
ok("mixed line endings: no carriage returns in the editor", "\r" not in c._docs[m].text and c._docs[m].text == "one\ntwo\nthree\nfour\n")
ok("mixed line endings: an untouched save changes nothing", c.save(m, False) == "" and (proj / "mixed.txt").read_bytes() == b"one\r\ntwo\nthree\rfour\n")
c.openFile(str(proj / "crlf.txt")); n = idx("crlf.txt")
c.edit(n, "x\ny\nz\nmore\n"); c._state["trimOnSave"] = False
ok("CRLF kept on save", c.save(n, False) == "" and (proj / "crlf.txt").read_bytes() == b"x\r\ny\r\nz\r\nmore\r\n")
c.edit(n, "pasted\r\nwith\rreturns\n")
ok("carriage returns never get into a document", c._docs[n].text == "pasted\nwith\nreturns\n")
c.openFile(str(proj / "wide.txt")); w = idx("wide.txt")
ok("UTF-16 opens as text", c._docs[w].text == "héllo\nwörld\n" and not c._docs[w].binary)
c.edit(w, "héllo\nwörld\nmore\n")
ok("UTF-16 saves as UTF-16", c.save(w, False) == "" and (proj / "wide.txt").read_bytes() == b"\xff\xfe" + "héllo\nwörld\nmore\n".encode("utf-16-le"))
fifo = proj / "pipe"; os.mkfifo(fifo)
t0 = time.time(); c.openFile(str(fifo)); spin(50)
ok("a pipe doesn't hang Code", time.time() - t0 < 2)
ok("rename: outside the project is refused", "outside" in c.rename(str(Path(home) / "outside.txt"), "gone.txt") and (Path(home) / "outside.txt").exists())
ok("remove: outside the project is refused", "outside" in c.remove(str(Path(home) / "outside.txt")) and (Path(home) / "outside.txt").exists())
ok("remove: not the project itself, not /", c.remove(str(proj)) != "" and c.remove("/") != "" and proj.is_dir())
ok("remove: something that isn't there", c.remove(str(proj / "nope.txt")) != "")
ok("rename: a name too long", c.rename(str(proj / "crlf.txt"), "x" * 300) != "" and (proj / "crlf.txt").exists())
ok("rename inside the project still works", c.rename(str(proj / "bad.bin.txt"), "bad.txt") == "" and (proj / "bad.txt").exists())
(proj / "huge.txt").write_text("x" * 400000 + "\n" + "x " * 200000 + "\nf(" + "a, " * 100000)
c.openFile(str(proj / "huge.txt")); h = idx("huge.txt")
t0 = time.time(); c.references(h, 0, 399999); c.references(h, 1, 10); c.signatureAt(h, 2, 300000); spin(50)
ok("a huge line doesn't freeze find-every-use or the signature hint", time.time() - t0 < 4, f"{time.time() - t0:.1f}s")
(proj / "huge.txt").unlink(); c.close(h, True)
(proj / "caf\udce9.txt".encode("utf-8", "surrogateescape").decode("latin-1")).write_text("odd name\n")
try:
    c.refreshGit(); c.stageAll(); c.refreshGit(); fine = True
except Exception as e:
    fine = repr(e)
ok("Git output that isn't UTF-8 doesn't break anything", fine is True, fine)
(proj / "s1.txt").write_text("alpha beta\n"); (proj / "s2.txt").write_bytes(b"alpha\r\ngamma\r\n")
c._files_cache = None
c.search("alpha", True, False, False); spin(1500)
before = len(said)
ok("replace with a group the pattern lacks: said, nothing changed", c.replaceAll("(alpha)", r"\2", True, True, False) == 0 and len(said) > before and (proj / "s1.txt").read_text() == "alpha beta\n", said[-1:])
c.search("alpha", True, False, False); spin(1500)
got = c.replaceAll("alpha", "omega", True, False, False)
ok("replace everywhere keeps each file's line endings", got >= 2 and (proj / "s2.txt").read_bytes() == b"omega\r\ngamma\r\n" and (proj / "s1.txt").read_text() == "omega beta\n", got)

shutil.rmtree(home, ignore_errors=True)
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
