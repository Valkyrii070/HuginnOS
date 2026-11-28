#!/usr/bin/env python3
"""Huginn OS updating itself (apps/huginn_osupdate.py), on a made-up system in a temp folder, with GitHub standing in
as a table of answers. Nothing here touches the real system or the network.
Usage: osupdate_test.py <kit root>"""
import io, json, lzma, os, shutil, subprocess, sys, tarfile, tempfile
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0:
    sys.exit("not as root: this test writes and removes files")
home = Path(tempfile.mkdtemp(prefix="osupdate-"))
os.environ.update(HOME=str(home), HUGINN_OSUPDATE_TEST="1")
sys.path[:0] = [str(KIT / "apps")]
import huginn_osupdate as up

passed = failed = 0
def ok(what, cond, extra=""):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1
        print("FAIL", what, extra)
def problem(fn, *a, **k):
    try:
        fn(*a, **k); return ""
    except up.Problem as why:
        return str(why)
def tree_state(root):
    """Every file under a root with its bytes' hash and mode (the updater's own state folder left out)."""
    out = {}
    for f in sorted(Path(root).rglob("*")):
        rel = str(f.relative_to(root))
        if f.is_file() and not rel.startswith(up.STATE_DIR):
            out[rel] = (up.sha256(f), f.stat().st_mode & 0o777)
    return out

# ------------------------------------------------------------------------------- a small Huginn OS tree, three versions
def make_kit(where: Path, version: int) -> Path:
    for d in ("apps/qml", "apps/help", "apps/data/emoji", "shell/qml", "tokens", "config/package-lists", "config/hooks", "config/overlay/usr/bin", "config/overlay/usr/libexec",
              "config/overlay/etc/xdg", "config/overlay/etc/systemd/system", "config/overlay/usr/share/applications", "config/overlay/etc/udev/rules.d", "compositor/src", "third_party/smithay"):
        (where / d).mkdir(parents=True, exist_ok=True)
    w = lambda rel, text, mode=0o644: ((where / rel).write_text(text), os.chmod(where / rel, mode))     # noqa: E731
    w("apps/huginn_app.py", f"VERSION = {version}\n"); w("apps/huginn_code.py", f"print('code v{version}')\n"); w("apps/qml/Code.qml", f"// v{version}\n")
    w("apps/qml/grain.png", "png"); w("apps/help/code.md", f"# Code {version}\n"); w("apps/data/emoji/list.txt", "smile\n")
    shutil.copy(KIT / "apps/huginn_osupdate.py", where / "apps/huginn_osupdate.py")
    w("shell/huginn_shell.py", f"SHELL = {version}\n"); w("shell/qml/Panel.qml", f"// panel {version}\n"); w("shell/qml/util.js", "var a = 1\n")
    shutil.copy(KIT / "tokens/tokens.json", where / "tokens/tokens.json"); shutil.copy(KIT / "tokens/gen_theme.py", where / "tokens/gen_theme.py")
    w("config/package-lists/10-base.list", "python3   # the language\ngdb\n# a comment\n" + ("podman\n" if version >= 2 else ""))
    w("config/update.conf", "repo: https://github.com/astrid/HuginnOS.git\nbranch: huginn-os\n")
    w("config/overlay/usr/bin/huginn-session", f"#!/bin/sh\necho session {version}\n", 0o755)
    w("config/overlay/usr/libexec/huginn-helper", "#!/bin/sh\necho helper\n", 0o755)
    w("config/overlay/etc/xdg/mimeapps.list", f"[Default Applications]\ntext/plain=huginn-code.desktop\n# v{min(version, 2)}\n")
    w("config/overlay/etc/xdg/kdeglobals", "[KDE]\nSingleClick=false\n")
    w("config/overlay/etc/systemd/system/huginn-thing.service", f"[Service]\nExecStart=/bin/true {version}\n")
    w("config/overlay/usr/share/applications/huginn-code.desktop", "[Desktop Entry]\nName=Code\n")
    w("config/hooks/40-own.sh", "#!/bin/sh\n# On update: run\ntrue\n", 0o755); w("config/hooks/41-boot.sh", "#!/bin/sh\n# only when the image is built\nfalse\n", 0o755)
    w("compositor/src/main.rs", "fn main() {}\n"); w("third_party/smithay/lib.rs", "// smithay\n")
    if version >= 2:
        w("apps/huginn_notebook.py", "NEW = True\n"); w("apps/qml/NotebookView.qml", "// new\n")
        (where / "apps/qml/grain.png").unlink()                     # a file version 2 no longer has
        (where / "config/overlay/usr/libexec/huginn-helper").unlink()
        w("config/overlay/etc/udev/rules.d/60-new.rules", "# rule\n"); w("config/overlay/usr/libexec/huginn-new-helper", "#!/bin/sh\n", 0o755)
        w("config/overlay/usr/share/applications/huginn-code.desktop", "[Desktop Entry]\nName=Code\nKeywords=notebook;\n")
    if version >= 3:
        w("apps/huginn_app.py", "VERSION = 3\nimport os\n")
    return where
def pack(kit: Path, sha: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(kit, arcname=f"HuginnOS-{sha}")
    return buf.getvalue()
kits = {n: make_kit(home / f"kit{n}", n) for n in (1, 2, 3)}
SHA = {1: "1" * 40, 2: "2" * 40, 3: "3" * 40}
DATE = {1: "2026-11-20", 2: "2026-11-27", 3: "2026-11-28"}
web = {"head": 2, "asked": []}
def get(url, timeout=60, cap=0):
    web["asked"].append(url)
    n = web["head"]
    if url == "https://api.github.com/repos/astrid/HuginnOS/commits/huginn-os":
        return json.dumps({"sha": SHA[n], "commit": {"committer": {"date": DATE[n] + "T10:00:00Z"}, "message": f"Version {n}: notebooks\n\nbody"}}).encode()
    if url.startswith("https://api.github.com/repos/astrid/HuginnOS/compare/"):
        return json.dumps({"commits": [{"commit": {"message": "Notebooks in Code\n\nmore"}}, {"commit": {"message": "Fix the start menu"}}]}).encode()
    for k, sha in SHA.items():
        if url == f"https://codeload.github.com/astrid/HuginnOS/tar.gz/{sha}":
            return pack(kits[k], sha)
    raise up.Problem("GitHub answered 404 for the update.")

# ------------------------------------------------------------------------------------------- what a system says it is
root = home / "root"; (root / "etc").mkdir(parents=True); (root / "etc/os-release").write_text('NAME="Huginn OS"\nBUILD_ID=20261120\n')
ok("a system that doesn't say what it is can't be updated, and says to install once", "Install the newest image once" in problem(up.look, root, get))
theme1 = home / "theme1"
made = up.make_theme(kits[1], root, theme1)
ok("the look's files are made from the tree's own tokens", made and len(list((theme1 / "color-schemes").glob("*.colors"))) >= 2 and (theme1 / "qml").is_dir()
   and len(list((theme1 / "qt").glob("*.conf"))) == 8)
p0 = up.plan(kits[1], root, theme1)
up.apply_plan(p0, root, home / "discard")                          # (the image's build, standing in: version 1 put in place)
n_rec = up.record(kits[1], root, SHA[1], DATE[1], theme1)
have = up.source(root)
ok("an image records what it is and what each of its own files was", have == {"repo": "astrid/HuginnOS", "branch": "huginn-os", "commit": SHA[1], "date": DATE[1]} and n_rec == len(p0["want"]) > 20
   and json.loads((root / up.MANIFEST).read_text())["usr/bin/huginn-session"] == up.sha256(root / "usr/bin/huginn-session"), (have, n_rec))
ok("modes are kept: programs can run, the rest can't", (root / "usr/bin/huginn-session").stat().st_mode & 0o777 == 0o755 and (root / "usr/share/huginn-apps/qml/Code.qml").stat().st_mode & 0o777 == 0o644
   and (root / "usr/share/huginn-apps/huginn_code.py").stat().st_mode & 0o777 == 0o755)
ok("the look's settings were written the way the image writes them (the colours added to kdeglobals)", "[Colors:Window]" in (root / "etc/xdg/kdeglobals").read_text() and (root / "etc/xdg/kdeglobals").read_text().startswith("[KDE]")
   and "gtk-theme-name=Huginn" in (root / "etc/gtk-4.0/settings.ini").read_text()
   and "[Colours]" in (root / "etc/xdg/huginn/qt.conf").read_text() and "scheme=dark" in (root / "etc/xdg/huginn/qt.conf").read_text()
   and (root / "usr/share/huginn-os/qt/HuginnAuroraDark.conf").is_file())
for bad, why in (("repo: https://evil.example/x/y.git\nbranch: main\n", "another site"), ("repo: https://github.com/a/b.git\nbranch: ../../x\n", "a branch that climbs"),
                 ("repo: https://github.com/a/b/../../c.git\nbranch: main\n", "a repository that climbs")):
    r2 = home / "bad"; (r2 / "usr/share/huginn-os").mkdir(parents=True, exist_ok=True); (r2 / up.SOURCE).write_text(bad)
    ok(f"a SOURCE naming {why} isn't followed", not (up.source(r2)["repo"] and up.source(r2)["branch"]) and "Install the newest image once" in problem(up.look, r2, get), up.source(r2))

# ------------------------------------------------------------------------------------------------------------ looking
web["head"] = 1
ok("on the branch's newest commit, nothing is waiting", up.look(root, get)["waiting"] is False and up.stage(root, get) == {})
web["head"] = 2
found = up.look(root, get)
ok("a newer commit on the branch is waiting, with what changed", found["waiting"] and found["latest"] == {"sha": SHA[2], "date": DATE[2], "title": "Version 2: notebooks"} and found["news"] == ["Fix the start menu", "Notebooks in Code"], found)
ok("only GitHub's own addresses for that repository were asked", all(u.startswith(("https://api.github.com/repos/astrid/HuginnOS/", "https://codeload.github.com/astrid/HuginnOS/")) for u in web["asked"]))
ok("plain http is refused outright", "HTTPS" in problem(lambda: (os.environ.pop("HUGINN_OSUPDATE_TEST"), up.fetch("http://example.org/x"))) and os.environ.setdefault("HUGINN_OSUPDATE_TEST", "1"))

# ---------------------------------------------------------------------------------------------- what is fetched is checked
evil = io.BytesIO()
with tarfile.open(fileobj=evil, mode="w:gz") as tar:
    def add(name, data=b"x", kind=tarfile.REGTYPE, link=""):
        info = tarfile.TarInfo(name); info.size = len(data) if kind == tarfile.REGTYPE else 0; info.type = kind; info.linkname = link; info.mode = 0o4755
        tar.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    add("top/ok.txt"); add("top/../../escaped.txt"); add("top/sub/../../../escaped2.txt"); add("/abs.txt"); add("top/link", kind=tarfile.SYMTYPE, link="/etc/passwd")
    add("top/dev", kind=tarfile.CHRTYPE); add("top/hard", kind=tarfile.LNKTYPE, link="top/ok.txt"); add("top/run.sh", b"#!/bin/sh\n")
dest = home / "unpacked"; up.unpack(evil.getvalue(), dest)
ok("unpacking keeps only plain files inside the folder: no climbing out, no links, no devices, no setuid", sorted(str(f.relative_to(dest)) for f in dest.rglob("*")) == ["abs.txt", "ok.txt", "run.sh"] and not Path("/abs.txt").exists()
   and not (home / "escaped.txt").exists() and not (home.parent / "escaped2.txt").exists() and (dest / "run.sh").stat().st_mode & 0o7777 == 0o755, sorted(str(f.relative_to(dest)) for f in dest.rglob("*")))
ok("what isn't a packed tree says so", "couldn't be unpacked" in problem(up.unpack, b"not a tarball", home / "x1") and "couldn't be unpacked" in problem(up.unpack, evil.getvalue()[:60], home / "x2"))
broken = make_kit(home / "broken", 2); (broken / "apps/huginn_code.py").write_text("def f(:\n")
ok("a tree whose Python doesn't compile is refused, naming the file", any("apps/huginn_code.py doesn't compile" in b for b in up.check_kit(broken)), up.check_kit(broken))
shutil.rmtree(broken / "shell/qml")
ok("a tree missing a piece is refused, naming the piece", up.check_kit(broken) == ["it has no shell/qml"], up.check_kit(broken))
ok("a sound tree has nothing wrong", up.check_kit(kits[2]) == [])
ok("the packages a tree names", up.listed_packages(kits[2]) == ["gdb", "podman", "python3"])
ok("…and which of them this computer lacks", up.missing_packages(kits[2], lambda argv, t=0, env=None: (1, "gdb installed\npython3 installed\npodman not-installed\ndpkg-query: no packages found matching x\n")) == ["podman"])

# --------------------------------------------------------------------------------------------- staging, then putting in
(root / "etc/xdg/mimeapps.list").write_text("[Default Applications]\ntext/plain=my-own-editor.desktop\n")       # the person changed a settings file
(root / "home/astrid").mkdir(parents=True); (root / "home/astrid/novel.txt").write_text("chapter one")
(root / "usr/share/huginn-apps/__pycache__").mkdir(); (root / "usr/share/huginn-apps/__pycache__/x.pyc").write_text("c")
(root / "usr/share/applications/firefox.desktop").write_text("[Desktop Entry]\nName=Firefox\n")                 # another package's file
before = tree_state(root)
logs = []
staged = up.stage(root, get, log=logs.append)
ok("staging fetches that commit, checks it and leaves it ready, changing nothing yet", staged["sha"] == SHA[2] and Path(staged["kit"]).is_dir() and tree_state(root) == before
   and up.load_state(root)["staged"]["news"] == ["Fix the start menu", "Notebooks in Code"] and any("Fetching" in l for l in logs), staged)
n_asked = len(web["asked"]); again = up.stage(root, get)
ok("staging again doesn't fetch the tree again", again["sha"] == SHA[2] and not any("codeload" in u for u in web["asked"][n_asked:]))
ok("with a version staged, looking says so", up.look(root, get)["staged"] == SHA[2])
done = up.apply(root, log=logs.append)
now = tree_state(root)
ok("applied: this system is now that commit", up.source(root) == {"repo": "astrid/HuginnOS", "branch": "huginn-os", "commit": SHA[2], "date": DATE[2]} and "BUILD_ID=20261127" in (root / "etc/os-release").read_text(), up.source(root))
ok("changed files are the new ones, new files are there", (root / "usr/share/huginn-apps/huginn_code.py").read_text() == "print('code v2')\n" and (root / "usr/share/huginn-apps/huginn_notebook.py").is_file()
   and (root / "usr/share/huginn-apps/qml/NotebookView.qml").is_file() and (root / "usr/bin/huginn-session").read_text().endswith("session 2\n") and (root / "etc/udev/rules.d/60-new.rules").is_file()
   and (root / "usr/libexec/huginn-new-helper").stat().st_mode & 0o777 == 0o755 and "ExecStart=/bin/true 2" in (root / "etc/systemd/system/huginn-thing.service").read_text())
ok("files this version no longer has are gone: an app's picture, a helper", not (root / "usr/share/huginn-apps/qml/grain.png").exists() and not (root / "usr/libexec/huginn-helper").exists() and done["removed"] == 2, done)
ok("a settings file the person changed is left exactly as they made it, and that is said", (root / "etc/xdg/mimeapps.list").read_text() == "[Default Applications]\ntext/plain=my-own-editor.desktop\n" and done["kept"] == ["etc/xdg/mimeapps.list"], done["kept"])
ok("nothing else on the computer was touched: their files, another package's, Python's own caches", now["home/astrid/novel.txt"] == before["home/astrid/novel.txt"] and now["usr/share/applications/firefox.desktop"] == before["usr/share/applications/firefox.desktop"]
   and "usr/share/huginn-apps/__pycache__/x.pyc" in now)
ok("only what differs was written, not everything", 6 <= done["written"] <= 14 < len(p0["want"]) and now["usr/share/huginn-apps/data/emoji/list.txt"] == before["usr/share/huginn-apps/data/emoji/list.txt"], done["written"])
ok("the staged tree is cleared away and nothing is waiting", not (up.state_dir(root) / "staged").exists() and up.look(root, get)["waiting"] is False and "No update is waiting" in problem(up.apply, root))
ok("the compositor is left alone when the update carries no ready-built one, and that is said", "no ready-built compositor" in done["compositor"])

ok("the look's own files are still there after the update", (root / "usr/share/color-schemes/HuginnAuroraDark.colors").is_file() and "usr/share/color-schemes/HuginnAuroraDark.colors" in json.loads((root / up.MANIFEST).read_text()))
held = up.plan(kits[2], root, None)
ok("when the look can't be made from a version's tokens, its files are left as they are (not taken for files the version dropped)", not any(r.startswith("usr/share/color-schemes/") for r in held["remove"])
   and any(k.startswith("usr/share/color-schemes/") for k in held["held"]), held["remove"])

# ------------------------------------------------------------------------------------------------------- going back
kept_state = tree_state(root)
went = up.back(root)
after_back = tree_state(root)
same = {k: v for k, v in after_back.items()} == {k: v for k, v in before.items()}
ok("Go Back puts every file back exactly as it was before the update: bytes and modes, the removed ones returned, the new ones gone", same and went["commit"] == SHA[1],
   {k: (before.get(k), after_back.get(k)) for k in set(before) | set(after_back) if before.get(k) != after_back.get(k)})
ok("the version gone back from is still offered, but isn't taken on its own", up.look(root, get)["waiting"] is True and up.look(root, get)["skipped"] is True and up.stage(root, get) == {}
   and "no earlier version" in problem(up.back, root).lower())
web["head"] = 3
ok("…the next one is taken as usual", up.look(root, get)["waiting"] is True and up.look(root, get)["skipped"] is False)
web["head"] = 2
ok("…and asked for by a person, the one gone back from is taken again", up.stage(root, get, force=True).get("sha") == SHA[2])
up.apply(root)
ok("applied a second time it lands the same", tree_state(root) == kept_state)

# ---------------------------------------------------------------------- settings files: yours only once you change them
(root / "etc/xdg/mimeapps.list").write_text((kits[1] / "config/overlay/etc/xdg/mimeapps.list").read_text())
m = json.loads((root / up.MANIFEST).read_text()); m["etc/xdg/mimeapps.list"] = up.sha256(root / "etc/xdg/mimeapps.list"); (root / up.MANIFEST).write_text(json.dumps(m))
p = up.plan(kits[2], root, None)
ok("a settings file still exactly as Huginn OS put it is brought up to date", "etc/xdg/mimeapps.list" in p["write"] and p["kept"] == [], (list(p["write"]), p["kept"]))
(root / "etc/systemd/system/huginn-thing.service").write_text("[Service]\nExecStart=/bin/false\n")
ok("a system file that isn't a settings file is always put right", "etc/systemd/system/huginn-thing.service" in up.plan(kits[2], root, None)["write"])
(root / "usr/share/huginn-shell/qml/Panel.qml").unlink(); (root / "usr/share/huginn-shell/qml/Panel.qml").mkdir()
ok("where a folder sits in a file's place, it isn't forced", "usr/share/huginn-shell/qml/Panel.qml" not in up.plan(kits[2], root, None)["write"])
(root / "usr/share/huginn-shell/qml/Panel.qml").rmdir()

# ------------------------------------------------------------------------------------------------- the compositor
binary = b"\x7fELF" + os.urandom(4000)
(home / "built").write_bytes(binary)
note = up.make_prebuilt(kits[3], home / "built")
ok("a built compositor is put in the tree, noted as for exactly its sources", note.get("written") and (kits[3] / "prebuilt/huginn-compositor.xz").is_file() and note["sources"] == up.tree_hash(kits[3] / "compositor", kits[3] / "third_party/smithay"))
ok("made again from the same, the tree doesn't change", not up.make_prebuilt(kits[3], home / "built").get("written"))
(root / "usr/bin/huginn-compositor").write_bytes(b"\x7fELFold"); os.chmod(root / "usr/bin/huginn-compositor", 0o755)  # noqa: S103
web["head"] = 3
up.stage(root, get); done3 = up.apply(root)
ok("an update carrying one for its own sources replaces the compositor", done3["compositor"] == "replaced" and (root / "usr/bin/huginn-compositor").read_bytes() == binary and (root / "usr/bin/huginn-compositor").stat().st_mode & 0o777 == 0o755)
ok("…and Go Back brings the old one back", (up.back(root), (root / "usr/bin/huginn-compositor").read_bytes())[1] == b"\x7fELFold")
(kits[3] / "compositor/src/main.rs").write_text("fn main() { changed(); }\n")
ok("a ready-built one for other sources isn't used", up.compositor_ready(kits[3]) == (None, "the compositor's sources changed after its ready-built copy was made"))
up.make_prebuilt(kits[3], home / "built"); (kits[3] / "prebuilt/huginn-compositor.xz").write_bytes(lzma.compress(b"\x7fELF" + b"tampered"))
ok("nor one whose bytes aren't what its note says", up.compositor_ready(kits[3])[0] is None and "isn't the one" in up.compositor_ready(kits[3])[1])
ok("a thing that isn't a program can't be put in a tree as the compositor", "isn't a program" in problem(up.make_prebuilt, kits[3], kits[3] / "apps/huginn_app.py"))

# ------------------------------------------------------------------------------------------------- Huginn's Qt parts
(kits[3] / "qt/theme").mkdir(parents=True); (kits[3] / "qt/theme/theme.cpp").write_text("// theme\n")
built = home / "qt-built"
parts = {}
for part, (name, _rel) in up.QT_PARTS.items():
    data = (b"\x7fELF" + os.urandom(2000)) if name.endswith(".so") else f"module org.huginn.layershell\n# {part}\n".encode()
    (built / name).parent.mkdir(parents=True, exist_ok=True); (built / name).write_bytes(data); parts[part] = data
qnote = up.make_prebuilt_qt(kits[3], built, "6.10.2")
ok("Huginn's Qt parts, built, are put in a tree, noted as for their sources and their Qt", qnote.get("written") and qnote["qt"] == "6.10.2"
   and qnote["sources"] == up.tree_hash(kits[3] / "qt") and all((kits[3] / f"prebuilt/huginn-qt-{k}.xz").is_file() for k in up.QT_PARTS))
ok("…made again from the same, the tree doesn't change", not up.make_prebuilt_qt(kits[3], built, "6.10.2").get("written"))
ok("…not with a Qt version that isn't one", "isn't a Qt version" in problem(up.make_prebuilt_qt, kits[3], built, "six"))
ok("…nor from a folder without them all", "isn't in" in problem(up.make_prebuilt_qt, kits[3], home / "nowhere", "6.10.2"))
(root / "var/lib/dpkg").mkdir(parents=True, exist_ok=True)
dpkg = root / "var/lib/dpkg/status"
dpkg.write_text("Package: libqt6core6t64\nStatus: install ok installed\nVersion: 6.9.1+dfsg-2\n\n")
got, why = up.qt_ready(kits[3], root)
ok("a system with another Qt keeps its own, and says why", got == {} and "for Qt 6.10.2" in why and "6.9.1" in why, why)
dpkg.write_text("Package: libqt6core6t64\nStatus: deinstall ok config-files\nVersion: 6.10.2+dfsg-1\n\nPackage: libqt6core6t64\nStatus: install ok installed\nVersion: 6.10.3+dfsg-1\n\n")
got, why = up.qt_ready(kits[3], root)
styles = {f"var/lib/flatpak/extension/org.kde.KStyle.Huginn/x86_64/{b}/styles/libhuginnstyle.so": parts["style"] for b in ("6.10", "6.11", "6.12")}
ok("one with the same Qt (another patch) gets every part, where Qt looks for it, and the style for App Store apps too",
   got == {**{rel: parts[k] for k, (_n, rel) in up.QT_PARTS.items()}, **styles}, why)
ok("…the style as Flatpak's extension for KDE's runtimes from its Qt on", up.kstyle_paths("6.10.2") == list(styles) and up.kstyle_paths("six") == [])
p_qt = up.plan(kits[3], root, None)
ok("…in the plan", set(p_qt["qt"]) == {rel for _n, rel in up.QT_PARTS.values()} | set(styles))
up.apply_plan(p_qt, root, home / "discard-qt")
ok("…put in place, readable by everyone", (root / up.QT_PARTS["theme"][1]).read_bytes() == parts["theme"]
   and (root / up.QT_PARTS["layershell-qmldir"][1]).stat().st_mode & 0o777 == 0o644)
ok("…and not again when they are already the ones", up.plan(kits[3], root, None)["qt"] == {})
(kits[3] / "qt/theme/theme.cpp").write_text("// changed\n")
ok("ready-built parts for other sources aren't used", up.qt_ready(kits[3], root) == ({}, "the Qt look's sources changed after its ready-built copy was made"))
up.make_prebuilt_qt(kits[3], built, "6.10.2"); (kits[3] / "prebuilt/huginn-qt-style.xz").write_bytes(lzma.compress(b"\x7fELFx"))
ok("…nor ones whose bytes aren't what the note says", up.qt_ready(kits[3], root)[0] == {} and "isn't the one" in up.qt_ready(kits[3], root)[1])
for f in ["huginn-qt.for"] + [f"huginn-qt-{k}.xz" for k in up.QT_PARTS]:
    (kits[3] / "prebuilt" / f).unlink()
shutil.rmtree(kits[3] / "qt")

# ------------------------------------------------------------------------------------------------- the GTK menu module
(kits[3] / "gtk").mkdir(exist_ok=True); (kits[3] / "gtk/menus.c").write_text("/* menus */\n"); (kits[3] / "gtk/build.sh").write_text("# build\n")
module = b"\x7fELF" + os.urandom(3000)
(home / "libhuginn-menus.so").write_bytes(module)
gnote = up.make_prebuilt_gtk(kits[3], home / "libhuginn-menus.so")
ok("the GTK menu module, built, is put in a tree, noted as for its sources", gnote.get("written") and gnote["sources"] == up.gtk_sources(kits[3])
   and (kits[3] / "prebuilt/huginn-gtk-menus.xz").is_file())
ok("…made again from the same, the tree doesn't change", not up.make_prebuilt_gtk(kits[3], home / "libhuginn-menus.so").get("written"))
ok("…not from something that isn't a library", "isn't a built library" in problem(up.make_prebuilt_gtk, kits[3], kits[3] / "gtk/menus.c"))
(kits[3] / "gtk/build.sh").write_text("# build, reworded\n")
got, why = up.gtk_ready(kits[3], root)
ok("an update brings it, where GTK looks for modules (its build script's wording isn't part of it)", got == {up.GTK_MODULE: module} and why == "", why)
p_gtk = up.plan(kits[3], root, None)
ok("…in the plan", set(p_gtk["gtk"]) == {up.GTK_MODULE})
up.apply_plan(p_gtk, root, home / "discard-gtk")
ok("…put in place, readable by everyone", (root / up.GTK_MODULE).read_bytes() == module and (root / up.GTK_MODULE).stat().st_mode & 0o777 == 0o644)
ok("…and not again when it is already the one", up.plan(kits[3], root, None)["gtk"] == {})
(kits[3] / "gtk/menus.c").write_text("/* changed */\n")
ok("a ready-built one for other sources isn't used", up.gtk_ready(kits[3], root) == ({}, "the GTK menu module's sources changed after its ready-built copy was made"))
up.make_prebuilt_gtk(kits[3], home / "libhuginn-menus.so"); (kits[3] / "prebuilt/huginn-gtk-menus.xz").write_bytes(lzma.compress(b"\x7fELFx"))
ok("nor one whose bytes aren't what its note says", up.gtk_ready(kits[3], root) == ({}, "the ready-built GTK menu module isn't the one its note describes"))
ok("…which making it again puts right", up.make_prebuilt_gtk(kits[3], home / "libhuginn-menus.so").get("written") and up.gtk_ready(kits[3], root)[1] == "")
for f in ("huginn-gtk.for", "huginn-gtk-menus.xz"):
    (kits[3] / "prebuilt" / f).unlink()
ok("an update without one says so", up.gtk_ready(kits[3], root) == ({}, "this update carries no ready-built GTK menu module"))
shutil.rmtree(kits[3] / "gtk")

# ----------------------------------------------------------------------------- what a real system is told afterwards
ran = []
runner = lambda argv, timeout=0, env=None: (ran.append(argv), (0, ""))[1]       # noqa: E731
failed_ = up.after(root, ["etc/systemd/system/a.service", "usr/share/applications/x.desktop", "etc/udev/rules.d/60.rules", "usr/share/huginn-apps/a.py"], ["usr/share/icons/hicolor/a.png"], kits[2], runner, real=True)
flat = [" ".join(a) for a in ran]
ok("afterwards: Python is compiled, systemd, udev, the app list and the icons are told, and only the hooks marked for updates run",
   any("compileall" in f for f in flat) and "systemctl daemon-reload" in flat and "udevadm control --reload" in flat and any(f.startswith("update-desktop-database") for f in flat)
   and any("gtk-update-icon-cache" in f for f in flat) and any(f.endswith("40-own.sh") for f in flat) and not any("41-boot.sh" in f for f in flat) and failed_ == [], flat)
ok("the start-up picture and the boot menu are only rebuilt when their files changed", not any("update-initramfs" in f or "update-grub" in f for f in flat)
   and (ran.clear(), up.after(root, ["usr/share/plymouth/themes/x", "etc/grub.d/41_x"], [], None, runner, real=True), [" ".join(a) for a in ran])[2][-2:] == ["update-initramfs -u", "update-grub"])
ok("on a made-up system none of that is run", (ran.clear(), up.after(root, ["etc/systemd/system/a.service"], [], kits[2], runner), ran)[2] == [])
ok("a step that fails is reported, not hidden", len(up.after(root, ["etc/systemd/x"], [], None, lambda argv, t=0, env=None: (1, "boom"), real=True)) == 2)

# ---------------------------------------------------------------------------------------------------- the command itself
env = {**os.environ, "HUGINN_OSUPDATE_ROOT": str(root)}
cmd = lambda *words: subprocess.run([sys.executable, str(KIT / "apps/huginn_osupdate.py"), *words], capture_output=True, text=True, env=env)     # noqa: E731
st = json.loads(cmd("state").stdout)
ok("“state” says what this system is and whether it can go back", st["have"]["commit"] == SHA[2] and st["auto"] is True and st["canGoBack"] is False, st)
ok("automatic staging can be switched off and on", (cmd("auto-off"), json.loads(cmd("state").stdout)["auto"])[1] is False and (cmd("auto-on"), json.loads(cmd("state").stdout)["auto"])[1] is True)
ok("with nothing ready, the start-up step does nothing and isn't an error", cmd("apply-at-start").returncode == 0 and up.source(root)["commit"] == SHA[2])
marker = home / "handed-over"
(kits[3] / "apps/huginn_osupdate.py").write_text((KIT / "apps/huginn_osupdate.py").read_text().replace('def main(argv: list) -> int:', f'def main(argv: list) -> int:\n    open({str(marker)!r}, "w").write(" ".join(argv))', 1))
(kits[3] / "compositor/src/main.rs").write_text("fn main() {}\n"); up.make_prebuilt(kits[3], home / "built")
up.stage(root, get, force=True); up.mark_ready(root)
r = cmd("apply-at-start")
ok("at start-up a ready update is put in place, by the new version's own installer", r.returncode == 0 and up.source(root)["commit"] == SHA[3] and marker.read_text() == "apply-at-start" and "Huginn OS is now 2026-11-28" in r.stdout
   and not (up.state_dir(root) / "ready").exists(), (r.returncode, r.stdout[-300:], r.stderr[-300:]))
ok("“back” from the command", cmd("back").returncode == 0 and up.source(root)["commit"] == SHA[2])
up.stage(root, get, force=True); up.mark_ready(root)
(Path(up.load_state(root)["staged"]["kit"]) / "apps/huginn_app.py").write_text("def broken(:\n")
r = cmd("apply-at-start")
ok("a staged update found unsound at start-up is not applied, says why, and isn't tried at every start-up after", r.returncode == 1 and "isn't sound" in r.stderr and up.source(root)["commit"] == SHA[2]
   and "isn't sound" in up.load_state(root)["problem"] and not (up.state_dir(root) / "ready").exists(), (r.returncode, r.stderr))
live = home / "live"; (live / "cdrom/casper").mkdir(parents=True); (live / "usr/share/huginn-os").mkdir(parents=True); shutil.copy(root / up.SOURCE, live / up.SOURCE)
ok("running from the installation drive, nothing is staged, and why is said", "installation drive" in problem(up.stage, live, get))
ok("an unknown command explains itself", cmd("frobnicate").returncode == 64)
print(f"{passed} passed, {failed} failed")
