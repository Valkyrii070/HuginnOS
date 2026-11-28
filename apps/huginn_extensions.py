"""Extensions for Code.

Visual Studio Code's extensions are of two parts. One is data: colour themes, snippets, which file endings are which
language, key bindings. The other is a program that runs inside VS Code's own extension host and calls VS Code's own
API; that part cannot run anywhere but in VS Code (or a fork of it), and Code is neither.

So Code takes the data part of a .vsix package and says plainly when a package also has a program part it leaves
behind. From a .vsix only package.json and the files its "contributes" names are unpacked: no program is written to
disk, nothing in the package is ever run.

Code's own extensions are the same shape (a folder or a .vsix with a package.json), and may also add commands, which
VS Code's cannot do without a program:

    "contributes": { "huginnCommands": [ { "title": "Bake the Lightmaps", "run": "make bake FILE=${file}" } ] }

Such a command is a line for the terminal, shown in the command palette, and is run only when you pick it.

Open VSX (open-vsx.org) is the open registry of VS Code extensions; search() and fetch() ask it. Microsoft's own
marketplace allows only Microsoft's products, so Code does not use it.

Pure helpers, no Qt.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import huginn_vscode as vsc

DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "huginn" / "code-extensions"
REGISTRY = "https://open-vsx.org"
MAX_FILE = 8 * 1024 * 1024            # one unpacked data file
MAX_ALL = 64 * 1024 * 1024            # everything unpacked from one package
MAX_PACKAGE = 200 * 1024 * 1024       # a package fetched from the registry
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\.[a-z0-9][a-z0-9._-]{0,99}$")
_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def _safe(rel: str) -> str:
    """A path inside a package, cleaned ("" when it would leave the package)."""
    rel = str(rel).replace("\\", "/").lstrip("./")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    return "" if not parts or any(p == ".." for p in parts) or len(rel) > 300 else "/".join(parts)


def ext_id(manifest: dict) -> str:
    """publisher.name, in small letters ("" when the manifest doesn't name both properly)."""
    got = f"{str(manifest.get('publisher') or 'local').lower()}.{str(manifest.get('name') or '').lower()}"
    return got if _ID.match(got) else ""


def _wanted(manifest: dict) -> list:
    """The data files a manifest's contributes names."""
    con = manifest.get("contributes") if isinstance(manifest.get("contributes"), dict) else {}
    out = []
    for key in ("themes", "snippets"):
        for row in con.get(key) if isinstance(con.get(key), list) else []:
            if isinstance(row, dict) and isinstance(row.get("path"), str):
                out.append(_safe(row["path"]))
    for extra in ("icon",):
        if isinstance(manifest.get(extra), str) and manifest[extra].lower().endswith((".png", ".svg")):
            out.append(_safe(manifest[extra]))
    return [w for w in dict.fromkeys(out) if w]


def describe(manifest: dict, have=None) -> dict:
    """What a package holds: what Code takes and what it leaves. With `have` (the data files that are really there),
    a theme or snippet file the manifest names but the package doesn't hold isn't counted."""
    con = manifest.get("contributes") if isinstance(manifest.get("contributes"), dict) else {}
    there = lambda key, r: have is None or key not in ("themes", "snippets") or _safe(r.get("path") or "") in have     # noqa: E731
    count = lambda key: len([r for r in con.get(key) if isinstance(r, dict) and there(key, r)]) if isinstance(con.get(key), list) else 0     # noqa: E731
    takes, n = [], {k: count(k) for k in ("themes", "snippets", "languages", "keybindings", "grammars", "debuggers")}
    n["huginnCommands"] = len([r for r in con.get("huginnCommands") if isinstance(r, dict) and str(r.get("title") or "").strip() and str(r.get("run") or "").strip()]) \
        if isinstance(con.get("huginnCommands"), list) else 0
    for key, one, many in (("themes", "colour theme", "colour themes"), ("snippets", "snippet file", "snippet files"), ("languages", "file type", "file types"),
                           ("keybindings", "key binding", "key bindings"), ("huginnCommands", "command", "commands")):
        if n[key]:
            takes.append(f"{n[key]} {one if n[key] == 1 else many}")
    leaves = []
    if manifest.get("main") or manifest.get("browser"):
        leaves.append("its program (that part runs only inside VS Code)")
    if n["grammars"]:
        leaves.append("its syntax colouring (Code colours the languages it knows itself)")
    if n["debuggers"]:
        leaves.append("its debugger (Code debugs with debugpy and GDB)")
    return {"takes": ", ".join(takes), "leaves": ", ".join(leaves), "useful": bool(takes)}


def _read_manifest(text) -> dict:
    try:
        data = json.loads(vsc.strip_jsonc(text if isinstance(text, str) else text.decode("utf-8", "replace")))
    except (ValueError, AttributeError):
        return {}
    return data if isinstance(data, dict) else {}


def install(path, folder=None) -> dict:
    """Install a .vsix package, or a folder holding a package.json. Returns what was installed ({id, name, …}), or
    raises ValueError saying why not. Installing again replaces what was there."""
    path, folder = Path(str(path).replace("file://", "").strip()).expanduser(), Path(folder or DIR)
    files = {}
    if path.is_dir():
        manifest = _read_manifest((path / "package.json").read_text(encoding="utf-8", errors="replace")) if (path / "package.json").is_file() else {}
        for rel in _wanted(manifest):
            src = (path / rel).resolve()
            if src.is_file() and str(src).startswith(str(path.resolve()) + os.sep) and src.stat().st_size <= MAX_FILE:
                files[rel] = src.read_bytes()
    elif path.is_file():
        try:
            with zipfile.ZipFile(path) as z:
                names = {i.filename: i for i in z.infolist() if not i.is_dir()}
                top = "extension/" if "extension/package.json" in names else ""
                if top + "package.json" not in names or names[top + "package.json"].file_size > MAX_FILE:
                    raise ValueError("That file isn't an extension package (it has no package.json inside).")
                manifest = _read_manifest(z.read(names[top + "package.json"]))
                for rel in _wanted(manifest):
                    info = names.get(top + rel)
                    if info is not None and info.file_size <= MAX_FILE and sum(len(b) for b in files.values()) + info.file_size <= MAX_ALL:
                        files[rel] = z.read(info)
        except (zipfile.BadZipFile, OSError, KeyError, RuntimeError) as err:
            raise ValueError("That file isn't an extension package (a .vsix is a zip file with a package.json inside).") from err
    else:
        raise ValueError("That file isn't there.")
    ident = ext_id(manifest)
    if not ident:
        raise ValueError("That package doesn't say who made it and what it is called, so it can't be installed.")
    what = describe(manifest, set(files))
    if not what["useful"]:
        raise ValueError(f"“{str(manifest.get('displayName') or manifest.get('name'))[:60]}” is only a program for VS Code's own extension host: it has no themes, snippets, file types or key bindings Code could use"
                         + (f" ({what['leaves']})." if what["leaves"] else "."))
    dest = folder / ident
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    keep = {k: manifest[k] for k in ("name", "publisher", "displayName", "description", "version", "icon", "contributes", "main", "browser", "license") if k in manifest}
    (dest / "package.json").write_text(json.dumps(keep, indent=1), encoding="utf-8")
    for rel, blob in files.items():
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(blob)
    return dict(_row(ident, keep, dest), new=True)


def _row(ident: str, manifest: dict, where: Path) -> dict:
    try:
        have = {str(f.relative_to(where)) for f in where.rglob("*") if f.is_file()}
    except OSError:
        have = set()
    what = describe(manifest, have)
    return {"id": ident, "name": str(manifest.get("displayName") or manifest.get("name") or ident)[:80], "version": str(manifest.get("version") or "")[:30],
            "publisher": str(manifest.get("publisher") or "")[:60], "about": str(manifest.get("description") or "")[:240], "takes": what["takes"], "leaves": what["leaves"],
            "folder": str(where)}


def _off(folder: Path) -> set:
    try:
        got = json.loads((folder / "off.json").read_text(encoding="utf-8"))
        return {str(x) for x in got} if isinstance(got, list) else set()
    except (OSError, ValueError):
        return set()


def set_on(ident: str, on: bool, folder=None) -> None:
    folder = Path(folder or DIR)
    off = _off(folder)
    (off.discard if on else off.add)(ident)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "off.json").write_text(json.dumps(sorted(off)), encoding="utf-8")


def remove(ident: str, folder=None) -> bool:
    """Take an extension away. Only a folder of that exact name inside the extensions folder is ever removed."""
    folder = Path(folder or DIR)
    if not _ID.match(ident or ""):
        return False
    dest = folder / ident
    if dest.is_symlink() or not dest.is_dir() or dest.resolve().parent != folder.resolve():
        return False
    shutil.rmtree(dest)
    set_on(ident, True, folder)
    return True


def installed(folder=None) -> list:
    folder, out = Path(folder or DIR), []
    off = _off(folder)
    try:
        dirs = sorted(d for d in folder.iterdir() if d.is_dir() and _ID.match(d.name))
    except OSError:
        return out
    for d in dirs:
        try:
            manifest = _read_manifest((d / "package.json").read_text(encoding="utf-8"))
        except OSError:
            continue
        if manifest:
            out.append(dict(_row(d.name, manifest, d), on=d.name not in off, manifest=manifest))
    return out


def gather(langs: dict, folder=None, commands: dict = None) -> dict:
    """Everything the switched-on extensions add: {themes: [{ext, label, path, dark}], snippets: {language: {prefix:
    (description, body)}}, types: [(glob, language)], keys: {command: sequence}, commands: [{ext, title, run}]}."""
    out = {"themes": [], "snippets": {}, "types": [], "keys": {}, "commands": []}
    for row in installed(folder):
        if not row["on"]:
            continue
        base, con = Path(row["folder"]), row["manifest"].get("contributes") if isinstance(row["manifest"].get("contributes"), dict) else {}
        rows = lambda key: [r for r in con.get(key) if isinstance(r, dict)] if isinstance(con.get(key), list) else []     # noqa: E731
        for t in rows("themes"):
            rel = _safe(t.get("path") or "")
            if rel and (base / rel).is_file():
                out["themes"].append({"ext": row["id"], "label": str(t.get("label") or t.get("id") or Path(rel).stem)[:80], "path": str(base / rel),
                                      "dark": str(t.get("uiTheme") or "vs-dark") != "vs" and "light" not in str(t.get("uiTheme") or "")})
        for s in rows("snippets"):
            rel, lang = _safe(s.get("path") or ""), vsc.language_name(str(s.get("language") or ""), langs)
            if rel and (base / rel).is_file() and (lang or not s.get("language")):
                for name, found in vsc.snippets(vsc.load_jsonc(base / rel), langs, lang).items():
                    out["snippets"].setdefault(name, {}).update(found)
        for l in rows("languages"):
            names = [str(l.get("id") or "")] + [str(a) for a in (l.get("aliases") if isinstance(l.get("aliases"), list) else [])]
            lang = next((n for n in (vsc.language_name(x, langs) for x in names) if n), "")
            if not lang:
                continue                                           # a language Code doesn't know: nothing would colour it
            for end in l.get("extensions") if isinstance(l.get("extensions"), list) else []:
                if isinstance(end, str) and re.fullmatch(r"\.[A-Za-z0-9._+-]{1,24}", end) and end.lower() not in langs[lang][0]:
                    out["types"].append(("*" + end, lang))
            for name in l.get("filenames") if isinstance(l.get("filenames"), list) else []:
                if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9._+-]{1,60}", name) and name not in langs[lang][0]:
                    out["types"].append((name, lang))
        out["keys"].update(vsc.keybindings(rows("keybindings")))
        for cmd in rows("huginnCommands"):
            if isinstance(cmd.get("title"), str) and isinstance(cmd.get("run"), str) and cmd["title"].strip() and cmd["run"].strip():
                out["commands"].append({"ext": row["id"], "from": row["name"], "title": cmd["title"].strip()[:100], "run": cmd["run"].strip()[:2000]})
    return out


# ------------------------------------------------------------------------------------------------------------ Open VSX
def _registry() -> str:
    base = os.environ.get("HUGINN_OPENVSX") or REGISTRY
    return base.rstrip("/")


def _allowed(url: str) -> bool:
    """Only the registry itself (https), or the stand-in a test names."""
    got, base = urllib.parse.urlsplit(url), urllib.parse.urlsplit(_registry())
    if (got.scheme, got.netloc) == (base.scheme, base.netloc):
        return True
    return got.scheme == "https" and (got.hostname or "").endswith(("open-vsx.org", "openvsx.org", "eclipsecontent.org"))


def _get(url: str, cap: int, timeout: int = 30) -> bytes:
    if not _allowed(url):
        raise ValueError("That address isn't the Open VSX registry.")
    req = urllib.request.Request(url, headers={"User-Agent": "HuginnCode/1 (extensions)", "Accept": "application/json, */*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 (checked above)
            if not _allowed(r.geturl()):
                raise ValueError("The registry sent Code somewhere else, which it doesn't follow.")
            blob = r.read(cap + 1)
    except OSError as err:
        raise ValueError(f"The Open VSX registry couldn't be reached ({getattr(err, 'reason', err)}).") from err
    if len(blob) > cap:
        raise ValueError("That is larger than Code will fetch.")
    return blob


def search(query: str, size: int = 30) -> list:
    """Extensions in the registry matching some words: [{namespace, name, title, about, version, downloads}]."""
    url = f"{_registry()}/api/-/search?" + urllib.parse.urlencode({"query": query.strip()[:100], "size": max(1, min(50, size)), "sortBy": "relevance" if query.strip() else "downloadCount"})
    try:
        data = json.loads(_get(url, 4 * 1024 * 1024))
    except ValueError as err:
        if "registry" in str(err) or "larger" in str(err):
            raise
        raise ValueError("The registry's answer couldn't be read.") from err
    out = []
    for row in data.get("extensions") if isinstance(data, dict) and isinstance(data.get("extensions"), list) else []:
        if isinstance(row, dict) and _PART.match(str(row.get("namespace") or "")) and _PART.match(str(row.get("name") or "")):
            out.append({"namespace": row["namespace"], "name": row["name"], "title": str(row.get("displayName") or row["name"])[:80], "about": str(row.get("description") or "")[:240],
                        "version": str(row.get("version") or "")[:30], "downloads": int(row.get("downloadCount") or 0) if str(row.get("downloadCount") or "0").isdigit() else 0})
    return out


def fetch(namespace: str, name: str, folder=None, scratch=None) -> dict:
    """Fetch an extension's package from the registry and install its data part. Returns install()'s row."""
    if not (_PART.match(namespace or "") and _PART.match(name or "")):
        raise ValueError("That isn't an extension's name.")
    try:
        meta = json.loads(_get(f"{_registry()}/api/{namespace}/{name}", 4 * 1024 * 1024))
    except ValueError as err:
        if "registry" in str(err):
            raise
        raise ValueError("The registry's answer couldn't be read.") from err
    url = (meta.get("files") or {}).get("download") if isinstance(meta, dict) and isinstance(meta.get("files"), dict) else ""
    if not isinstance(url, str) or not url:
        raise ValueError("The registry has no package for that extension.")
    scratch = Path(scratch or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huginn" / "code-extensions")
    scratch.mkdir(parents=True, exist_ok=True)
    part = scratch / f"{namespace}.{name}.vsix"
    try:
        part.write_bytes(_get(url, MAX_PACKAGE, timeout=120))
        return install(part, folder)
    finally:
        part.unlink(missing_ok=True)
