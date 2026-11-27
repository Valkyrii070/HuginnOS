#!/usr/bin/env python3
"""Code's extensions against real, published VS Code extensions (their sources, as their makers keep them on GitHub),
each packed the way vsce packs a .vsix. code_round9_test.py uses made-up ones.
Usage: code_extensions_real_check.py <kit root> <a folder holding the extensions' folders>
With no such folder there is nothing to check, and it says so."""
import json, os, sys, tempfile, zipfile
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
SRC = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/nonexistent")
if os.geteuid() == 0:
    sys.exit("not as root: this test writes and removes files")
home = tempfile.mkdtemp(prefix="code-ext-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/data", XDG_CONFIG_HOME=home + "/config", XDG_CACHE_HOME=home + "/cache", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtGui import QGuiApplication
app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
import huginn_code as code
import huginn_code_more as more
import huginn_extensions as hx
import huginn_vscode as vsc

found = sorted(d for d in SRC.iterdir() if (d / "package.json").is_file()) if SRC.is_dir() else []
if not found:
    print("(no real extensions here: nothing checked)"); sys.exit(0)
passed = failed = 0
def ok(what, cond, extra=""):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1
        print("FAIL", what, extra)
def pack(folder: Path) -> str:
    """A .vsix as vsce makes one: the extension's files under extension/, and a manifest beside them."""
    target = Path(home) / (folder.name + ".vsix")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>"); z.writestr("extension.vsixmanifest", "<PackageManifest/>")
        for f in sorted(folder.rglob("*")):
            if f.is_file() and ".git" not in f.relative_to(folder).parts:
                z.write(f, "extension/" + str(f.relative_to(folder)))
    return str(target)
hexish = lambda v: isinstance(v, str) and v.startswith("#") and len(v) in (4, 7, 9)      # noqa: E731

c = code.Code(); c._demo = False
for folder in found:
    manifest = json.loads(vsc.strip_jsonc((folder / "package.json").read_text(encoding="utf-8", errors="replace")))
    con = manifest.get("contributes") or {}
    declared_themes = [t for t in con.get("themes", []) if (folder / t["path"]).is_file()]
    declared_snips = [s_ for s_ in con.get("snippets", []) if (folder / s_["path"]).is_file()]
    said = c.installExtension(pack(folder))
    ident = hx.ext_id(manifest)
    if not declared_themes and not declared_snips and not con.get("languages") and not con.get("keybindings"):
        ok(f"{folder.name}: its sources hold none of the data its manifest names (its themes are built when it is published), and Code says there is nothing in it to use",
           "only a program" in said or "no themes" in said, said)
        continue
    ok(f"{folder.name}: its .vsix installs", said.startswith("Installed") and any(e["id"] == ident for e in c.extensions), said)
    want = (f"{len(declared_themes)} colour theme" if declared_themes else "") or f"{len(declared_snips)} snippet file"
    ok(f"{folder.name}: what it says it took is what the package really held ({want}…)", want in said, said)
    there = hx.DIR / ident
    kept = sorted(str(f.relative_to(there)) for f in there.rglob("*") if f.is_file())
    ok(f"{folder.name}: only its package.json and data files are unpacked ({len(kept)} of {sum(1 for f in folder.rglob('*') if f.is_file() and '.git' not in f.parts)} files)",
       kept and all(k == "package.json" or k.endswith((".json", ".code-snippets", ".png", ".svg", ".tmTheme")) for k in kept) and not any(k.endswith((".js", ".ts", ".sh")) for k in kept), kept[:12])
    mine = [t for t in c.extensionThemes if t["ext"] == ident]
    ok(f"{folder.name}: every theme whose file it ships is offered ({len(mine)})", len(mine) == len(declared_themes), ([t["label"] for t in mine], [t.get("label") for t in declared_themes]))
    for t in mine:
        why = c.useExtensionTheme(ident, t["label"])
        th = c.theme
        ok(f"{folder.name}: “{t['label']}” goes on: a background, a text colour, and colours for key words, strings and comments",
           why == "" and th.get("name") == t["label"] and hexish(th.get("paper")) and hexish(th.get("ink")) and all(hexish(th.get(k)) for k in ("key", "string", "comment")) and th["paper"].lower() != th["ink"].lower(),
           (why, {k: th.get(k) for k in ("name", "dark", "paper", "ink", "key", "string", "comment")}))
        lum = lambda h: sum(int(h[i:i + 2], 16) * w for i, w in ((1, 0.299), (3, 0.587), (5, 0.114))) if len(h) >= 7 else 128      # noqa: E731
        ok(f"{folder.name}: “{t['label']}” is known as {'dark' if th.get('dark') else 'light'}, which is what its background is", (lum(th["paper"]) < 128) == bool(th.get("dark")), (th.get("paper"), th.get("dark")))
    if declared_snips:
        langs = {vsc.language_name(s_.get("language", ""), code.LANGS) for s_ in declared_snips} - {""}
        got = {lang: len(more.EXTRA_SNIPPETS.get(lang, {})) for lang in langs}
        ok(f"{folder.name}: its snippets are offered in the languages Code has ({got})", langs and all(n > 5 for n in got.values()), got)
        lang = sorted(langs)[0]
        body = next(iter(more.EXTRA_SNIPPETS[lang].values()))
        ok(f"{folder.name}: a snippet is a description and a body with its tab stops", isinstance(body, tuple) and len(body) == 2 and isinstance(body[1], str) and body[1].strip(), body)
    c.removeExtension(ident)
    ok(f"{folder.name}: removed cleanly", not there.exists() and not any(e["id"] == ident for e in c.extensions) and c.theme == {})
print(f"{passed} passed, {failed} failed")
