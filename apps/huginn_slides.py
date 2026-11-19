"""Slides' engine: a deck of free-form slides (text boxes, shapes, pictures anywhere, at any size and angle), themes,
layouts with placeholders, transitions and builds, PowerPoint files both ways (huginn_pptx) and vector PDF.

The model and the drawing live in huginn_slides_model; this file is the window's side of it: the slides as the
window shows them (text as HTML, pictures as files in a cache), the changes the window asks for, and undo.
"""
import base64
import copy
import hashlib
import json
import time
from pathlib import Path

from PySide6.QtCore import Property, QByteArray, QMimeData, QStandardPaths, Qt, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QImage, QTextCharFormat, QTextCursor

import huginn_slides_model as sm
from huginn_office import Bridge, FileList, fresh_path, note_recent, write_atomic

MIME = "application/x-huginn-slide-items"


def picture_uri(path: str, max_side: int = 2400) -> tuple:
    """(data URI, width, height) of a picture file; very large pictures are scaled down."""
    from huginn_writer import image_data_uri
    return image_data_uri(path, max_side)


class Slides(FileList):
    NATIVE, OWN, VIA_BRIDGE, MODERN, STEM = (".hslides",), (".pptx",), (".odp", ".ppt"), "pptx", "Untitled Talk"

    def __init__(self, target: Path = None):
        super().__init__(target)
        self._deck = sm.upgrade({"slides": [{"layout": "title"}]})
        self._index = 0
        self._views = {}                      # slide id → (key, the slide as the window shows it)
        self._files = {}                      # picture data → its file in the cache
        self._undo, self._redo = [], []
        self._last = ("", 0.0)
        self._edit_doc = self._edit_quick = None
        self._clip = None
        self._next = 1
        self._cache = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation) or Path.home() / ".cache") / "huginn-slides"
        self._rev, self._made = 0, (-1, [])
        self.changed.connect(self._bump)
        self.changed.connect(self.deckChanged)
        if self._extra:
            self.open(str(self._extra))

    deckChanged = Signal()
    historyChanged = Signal()

    # ------------------------------------------------------------------ what the window reads
    def _bump(self) -> None:
        self._rev += 1

    def _all_views(self) -> list:
        """The slides as the window shows them, remade only for slides that changed."""
        if self._made[0] == self._rev:
            return self._made[1]
        look = self._look()
        look_key = self._look_key(look)
        views = []
        for n, s in enumerate(self._deck["slides"], 1):          # the footer goes by the slide's place, so it's added here
            v = self._view(s, look, look_key)
            foot = sm.footer_of(self._deck, s, n)
            views.append(dict(v, foot=foot) if foot else v)
        live = {s["id"] for s in self._deck["slides"]}
        self._views = {k: v for k, v in self._views.items() if k in live}
        self._made = (self._rev, views)
        return views

    def _look_key(self, look: dict) -> str:
        light = dict(look, frames={k: [dict(it, src=hash(it.get("src", ""))) for it in f["items"]] for k, f in (look.get("frames") or {}).items()})
        if (light.get("bg") or {}).get("picture"):
            light["bg"] = dict(light["bg"], picture=hash(light["bg"]["picture"]))
        return hashlib.sha1(json.dumps([light, self._deck.get("size")], sort_keys=True, default=str).encode()).hexdigest()

    def _look(self) -> dict:
        return sm.look_of(self._deck)

    def _view(self, slide: dict, look: dict, look_key: str) -> dict:
        light = dict(slide, items=[dict(it, src=hash(it["src"])) if "src" in it else it for it in slide.get("items", [])])
        if (slide.get("bg") or {}).get("picture"):
            light["bg"] = dict(slide["bg"], picture=hash(slide["bg"]["picture"]))
        key = hashlib.sha1(json.dumps(light, sort_keys=True, default=str).encode()).hexdigest() + look_key
        got = self._views.get(slide["id"])
        if got and got[0] == key:
            return got[1]
        view = {k: v for k, v in slide.items() if k != "items"}
        view["items"] = []
        view["bg"] = self._bg_view(slide.get("bg") or look["bg"])
        view["steps"] = self._steps(slide)
        seq = []                                    # the builds in the order the clicks bring them: [item id, paragraph or -1]
        for n, it in sorted(enumerate(slide.get("items", [])), key=lambda e: (float((e[1].get("anim") or {}).get("order") or 0), e[0])):
            seq += [[it["id"], k] for k in self._build_steps(it)]
        view["buildSeq"] = seq
        layout = slide.get("layout", "")
        view["items"] = [self._item_view(item, layout, look) for item in slide.get("items", [])]
        frame = (look.get("frames") or {}).get(slide.get("frame") or "") if self._deck.get("look") else None
        view["frameItems"] = [self._item_view(item, layout, look) for item in frame["items"]] if frame else []
        self._views[slide["id"]] = (key, view)
        return view

    def _item_view(self, item: dict, layout: str, look: dict) -> dict:
        v = {k: val for k, val in item.items() if k not in ("src", "paras")}
        if item["kind"] == "picture":
            v["url"] = self._file_for(item.get("src", ""))
        if item["kind"] in ("table", "chart"):
            v["url"] = self._drawn(item, look)
            v.pop("cells", None)
        if item["kind"] in ("text", "shape") and item.get("shape") not in ("line", "arrowline"):
            v["html"] = sm.item_html(item, layout, look) if sm.has_text(item) else ""
            v["empty"] = not sm.has_text(item)
            v["valign"] = item.get("valign") or (sm.role_style(item.get("role", ""), layout)["valign"] if item["kind"] == "text" else "middle")
            if v["empty"] and item.get("role"):
                v["hint"] = sm.item_html(self._hint_item(item), layout, look)
        if item["kind"] == "shape":
            v["fillHex"] = sm.colour(item.get("fill", ""), look)
            v["lineHex"] = sm.colour(item.get("line", ""), look)
            v["path"] = sm.ops_svg(sm.shape_ops(item.get("shape", "rect"), item["w"], item["h"], item.get("flipH"), item.get("flipV")))
            if item.get("shape") == "arrowline":
                v["head"] = sm.ops_svg(sm._poly(sm.arrow_head(item)))
        v["build"] = self._build_steps(item)
        if len(v["build"]) > 1 or (v["build"] and v["build"][0] >= 0):
            steps = []                              # the text as each click of a paragraph build leaves it
            for k in range(len(v["build"]) + 1):
                shown = set(v["build"][:k])
                paras = [dict(p, _hide=(n in v["build"] and n not in shown)) for n, p in enumerate(item.get("paras", []))]
                steps.append(sm.item_html(dict(item, paras=paras), layout, look))
            v["stepHtml"] = steps
        return v

    def _hint_item(self, item: dict) -> dict:
        hint = {"title": "Click to add a title", "subtitle": "Click to add a subtitle"}.get(item.get("role"), "Click to add text")
        it = copy.deepcopy(item)
        it["paras"] = [{"runs": [{"t": hint}], "lvl": 0, "list": item["paras"][0].get("list", "") if item.get("paras") else "", "align": ""}]
        return it

    def _bg_view(self, bg: dict) -> dict:
        bg = dict(bg or {})
        if bg.get("picture"):
            bg["url"] = self._file_for(bg.pop("picture"))
        return bg

    def _drawn(self, item: dict, look: dict) -> str:
        """A table or chart drawn as a picture in the cache (named by what's in it and the design), for the window."""
        key = hashlib.sha1(json.dumps([{k: v for k, v in item.items() if k not in ("x", "y", "anim", "id", "locked")}, look], sort_keys=True,
                                      default=str).encode()).hexdigest()[:20]
        path = self._cache / f"item-{key}.png"
        if not path.exists():
            try:
                self._cache.mkdir(parents=True, exist_ok=True)
                sm.render_item(item, look, 0.6).save(str(path), "PNG")
            except OSError:
                return ""
        return path.as_uri()

    def _file_for(self, src: str) -> str:
        """Pictures reach the window as files in the cache (named by their content), not as long strings."""
        if not src.startswith("data:") or "," not in src:
            return ""
        if src in self._files:
            return self._files[src]
        head, data = src.split(",", 1)
        ext = "jpg" if "jpeg" in head else "png"
        name = hashlib.sha1(data.encode()).hexdigest()[:20] + "." + ext
        path = self._cache / name
        if not path.exists():
            try:
                self._cache.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(data))
            except (OSError, ValueError):
                return ""
        self._files[src] = path.as_uri()
        return self._files[src]

    @staticmethod
    def _build_steps(item: dict) -> list:
        """How many clicks this item's build takes: 1, or one per paragraph with text."""
        anim = item.get("anim") or {}
        if not anim.get("kind"):
            return []
        if anim.get("byPara") and item.get("paras"):
            return [n for n, p in enumerate(item["paras"]) if any(r.get("t") for r in p.get("runs", []))]
        return [-1]

    def _steps(self, slide: dict) -> int:
        return sum(len(self._build_steps(it)) for it in slide.get("items", []))

    slides = Property("QVariantList", lambda self: self._all_views(), notify=deckChanged)
    index = Property(int, lambda self: self._index, notify=deckChanged)
    count = Property(int, lambda self: len(self._deck["slides"]), notify=deckChanged)
    theme = Property(str, lambda self: "" if self._deck.get("look") else self._deck.get("theme", "realm"), notify=deckChanged)
    look = Property("QVariant", lambda self: self._look_view(), notify=deckChanged)
    size = Property(str, lambda self: self._deck.get("size", "16:9"), notify=deckChanged)
    slideW = Property(int, lambda self: sm.slide_w(self._deck.get("size", "16:9")), notify=deckChanged)
    canUndo = Property(bool, lambda self: bool(self._undo), notify=historyChanged)
    canRedo = Property(bool, lambda self: bool(self._redo), notify=historyChanged)
    themes = Property("QVariantList", lambda self: [dict(v, key=k, bg=self._bg_view(v["bg"])) for k, v in sm.THEMES.items()], constant=True)
    layouts = Property("QVariantList", lambda self: [{"key": k, "name": sm.LAYOUT_NAMES[k]} for k in sm.LAYOUTS], constant=True)
    shapes = Property("QVariantList", lambda self: [{"key": k, "name": sm.SHAPE_NAMES[k], "path": sm.ops_svg(sm.shape_ops(k, 28, 20))} for k in sm.SHAPES],
                      constant=True)

    @Property("QVariantList", notify=deckChanged)
    def samples(self):
        """Each layout as an empty slide, for the layout menus."""
        look = self._look()
        look_key = self._look_key(look)
        out = []
        for key in sm.LAYOUTS:
            items = [sm.placeholder_item(role, f"x{n}", tuple(rect), key) for n, (role, *rect) in enumerate(sm.placeholders(key, self._deck["size"]))]
            out.append(dict(self._view({"id": "sample-" + key, "layout": key, "items": items, "bg": None}, look, look_key), key=key, name=sm.LAYOUT_NAMES[key]))
        return out

    def _look_view(self) -> dict:
        look = dict(self._look())
        look["bg"] = self._bg_view(look["bg"])
        return look

    @Slot(result="QVariantList")
    def fonts(self) -> list:
        fams = QFontDatabase.families()
        first = [f for f in ("Inter", "Caladea", "Carlito", "Liberation Sans", "Liberation Serif", "Liberation Mono", "DejaVu Sans") if f in fams]
        return first + [f for f in fams if f not in first and not f.startswith(("Noto Sans Mono", "Noto Color"))][:120]

    @Slot(str, float, float, bool, bool, result=str)
    def shapePath(self, kind: str, w: float, h: float, fh: bool = False, fv: bool = False) -> str:
        return sm.ops_svg(sm.shape_ops(kind, w, h, fh, fv))

    # ------------------------------------------------------------------ files
    def _sid(self) -> str:
        used = {s["id"] for s in self._deck["slides"]}
        while f"s{self._next}" in used:
            self._next += 1
        self._next += 1
        return f"s{self._next - 1}"

    def _iid(self) -> str:
        used = {it["id"] for s in self._deck["slides"] for it in s.get("items", [])}
        while f"i{self._next}" in used:
            self._next += 1
        self._next += 1
        return f"i{self._next - 1}"

    @Slot(str)
    def open(self, path: str) -> None:
        note_recent(path)
        if self._dirty:
            self.save()
        source, target, dropped = Path(path), Path(path), None
        try:
            if source.suffix.lower() in self.FOREIGN:
                import huginn_pptx
                deck, dropped = huginn_pptx.read(self._modern(source))
                target = fresh_path(source.parent, source.stem, ".hslides")
            else:
                data = json.loads(source.read_text(encoding="utf-8"))
                deck = data if data.get("format") == "huginn-slides-2" else sm.upgrade(data)
            deck = self._clean(deck)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as err:
            self.failed.emit(f"Couldn't open “{source.name}”: {getattr(err, 'strerror', None) or err}")
            return
        except Exception as err:                       # noqa: BLE001 (a damaged PowerPoint file can fail anywhere)
            self.failed.emit(f"Couldn't open “{source.name}”: {err}")
            return
        self._deck, self._views = deck, {}
        self._undo, self._redo = [], []
        self.historyChanged.emit()
        self._path, self._dirty, self._index = target, False, 0
        if target != source:
            self.touch()
            self.imported.emit(source.name, dropped or [])
        self.changed.emit()

    def _clean(self, deck: dict) -> dict:
        deck.setdefault("theme", "realm")
        deck.setdefault("size", "16:9")
        deck.setdefault("look", None)
        deck["footer"] = sm.clean_footer(deck.get("footer"))
        slides = [s for s in deck.get("slides", []) if isinstance(s, dict)]
        for s in slides:
            s.setdefault("id", "")
            s.setdefault("layout", "content")
            s.setdefault("items", [])
            s.setdefault("notes", "")
            s.setdefault("bg", None)
            s.setdefault("transition", {"kind": "none", "ms": 500})
            s.setdefault("hidden", False)
            for it in s["items"]:
                it.setdefault("rot", 0)
                it.setdefault("role", "")
                for k in ("x", "y", "w", "h"):
                    it[k] = float(it.get(k, 0))
        seen = set()
        for s in slides:
            if not s["id"] or s["id"] in seen:
                s["id"] = f"s{len(seen) + 1000}"
            seen.add(s["id"])
        deck["slides"] = slides or sm.upgrade({"slides": [{"layout": "title"}]})["slides"]
        deck["format"] = "huginn-slides-2"
        return deck

    @Slot()
    def create(self) -> None:
        if self._dirty:
            self.save()
        try:
            path = fresh_path(self._folder, self.STEM, ".hslides")
            deck = sm.upgrade({"slides": [{"layout": "title"}]})
            path.write_text(json.dumps(deck), encoding="utf-8")
        except OSError as err:
            self.failed.emit(f"Couldn't create a presentation: {err.strerror or err}")
            return
        self.open(str(path))

    @Slot()
    def save(self) -> None:
        if not self._dirty or self._path is None:
            return
        try:
            write_atomic(self._path, json.dumps(self._deck, ensure_ascii=False))
            self._dirty = False
        except OSError as err:
            self.failed.emit(f"Couldn't save: {err.strerror or err}")
        self.changed.emit()

    @Slot(str, result=str)
    def export(self, kind: str) -> str:
        if self._path is None:
            return ""
        self.save()
        try:
            if kind == "pptx":
                import huginn_pptx
                out = fresh_path(self._path.parent, self._path.stem, ".pptx")
                huginn_pptx.write(self._deck, out)
            elif kind == "odp" and Bridge.available():
                import huginn_pptx
                import tempfile
                tmp = Path(tempfile.mkdtemp(prefix="huginn-slides-")) / (self._path.stem + ".pptx")
                huginn_pptx.write(self._deck, tmp)
                made = Bridge.convert(tmp, "odp")
                out = fresh_path(self._path.parent, self._path.stem, ".odp")
                made.replace(out)
            else:
                out = fresh_path(self._path.parent, self._path.stem, ".pdf")
                sm.write_pdf(self._deck, str(out), self._path.stem)
        except OSError as err:
            self.failed.emit(f"Couldn't export: {err.strerror or err}")
            return ""
        return str(out)

    # ------------------------------------------------------------------ undo
    def _keep(self, tag: str = "") -> None:
        """Before a change. A run of the same small change (a drag, typing) is one step."""
        now = time.monotonic()
        if tag and self._last[0] == tag and now - self._last[1] < 1.2:
            self._last = (tag, now)
            return
        self._last = (tag, now)
        self._undo.append((copy.deepcopy(self._deck), self._index))
        del self._undo[:-80]
        self._redo.clear()
        self.historyChanged.emit()

    def _done(self) -> None:
        if self._path is not None:
            self.touch()
        else:
            self.changed.emit()

    @Slot()
    def undo(self) -> None:
        if self._undo:
            self._redo.append((copy.deepcopy(self._deck), self._index))
            self._deck, self._index = self._undo.pop()
            self._index = min(self._index, len(self._deck["slides"]) - 1)
            self._last = ("", 0.0)
            self.historyChanged.emit()
            self._done()

    @Slot()
    def redo(self) -> None:
        if self._redo:
            self._undo.append((copy.deepcopy(self._deck), self._index))
            self._deck, self._index = self._redo.pop()
            self._index = min(self._index, len(self._deck["slides"]) - 1)
            self._last = ("", 0.0)
            self.historyChanged.emit()
            self._done()

    # ------------------------------------------------------------------ slides
    @property
    def _slide(self) -> dict:
        return self._deck["slides"][self._index]

    def _new_slide(self, layout: str) -> dict:
        layout = layout if layout in sm.LAYOUTS else "content"
        items = [sm.placeholder_item(role, self._iid(), tuple(rect), layout) for role, *rect in sm.placeholders(layout, self._deck["size"])]
        return {"id": self._sid(), "layout": layout, "items": items, "notes": "", "bg": None, "transition": {"kind": "none", "ms": 500}, "hidden": False}

    @Slot(int)
    def select(self, index: int) -> None:
        if 0 <= index < len(self._deck["slides"]) and index != self._index:
            self._index = index
            self.deckChanged.emit()

    @Slot(str)
    def add(self, layout: str) -> None:
        if self._path is None:
            return
        self._keep()
        if layout == "":
            layout = "content" if self._slide.get("layout") == "title" else self._slide.get("layout", "content")
        slide = self._new_slide(layout)
        slide["transition"] = dict(self._slide.get("transition") or {"kind": "none", "ms": 500})
        self._deck["slides"].insert(self._index + 1, slide)
        self._index += 1
        self._done()

    @Slot()
    def duplicate(self) -> None:
        if self._path is None:
            return
        self._keep()
        copy_ = copy.deepcopy(self._slide)
        copy_["id"] = self._sid()
        for it in copy_["items"]:
            it["id"] = self._iid()
        self._deck["slides"].insert(self._index + 1, copy_)
        self._index += 1
        self._done()

    @Slot()
    def remove(self) -> None:
        if len(self._deck["slides"]) > 1:
            self._keep()
            del self._deck["slides"][self._index]
            self._index = min(self._index, len(self._deck["slides"]) - 1)
            self._done()

    @Slot(int)
    def move(self, delta: int) -> None:
        self.moveTo(self._index, self._index + delta)

    @Slot(int, int)
    def moveTo(self, src: int, dst: int) -> None:
        s = self._deck["slides"]
        if 0 <= src < len(s) and 0 <= dst < len(s) and src != dst:
            self._keep()
            s.insert(dst, s.pop(src))
            self._index = dst
            self._done()

    @Slot(int, str)
    def setNotes(self, index: int, text: str) -> None:
        if 0 <= index < len(self._deck["slides"]) and self._deck["slides"][index].get("notes", "") != text:
            self._keep(f"notes:{index}")
            self._deck["slides"][index]["notes"] = text
            self._done()

    @Slot(str)
    def setLayout(self, layout: str) -> None:
        """A new layout: placeholders move to their new places; text a layout has no place for stays, as a text box."""
        if layout not in sm.LAYOUTS or self._path is None:
            return
        self._keep()
        slide = self._slide
        places = {role: rect for role, *rect in sm.placeholders(layout, self._deck["size"])}
        kept = []
        have = set()
        for it in slide["items"]:
            role = it.get("role", "")
            if role and role == "subtitle" and "subtitle" not in places and "body" in places and "body" not in have:
                role = it["role"] = "body"
            elif role == "body" and "body" not in places and "subtitle" in places and "subtitle" not in have:
                role = it["role"] = "subtitle"
            if role in places and role not in have:
                it["x"], it["y"], it["w"], it["h"] = places[role]
                st = sm.role_style(role, layout)
                for p in it.get("paras", []):
                    p["list"] = st["list"] if not p.get("list") or not st["list"] else p["list"]
                have.add(role)
                kept.append(it)
            elif role:
                if sm.has_text(it):
                    it["role"] = ""
                    kept.append(it)
            else:
                kept.append(it)
        for role, rect in places.items():
            if role not in have:
                kept.insert(0 if role == "title" else len([k for k in kept if k.get("role")]), sm.placeholder_item(role, self._iid(), tuple(rect), layout))
        slide["items"], slide["layout"] = kept, layout
        for it in kept:
            if it.get("role"):
                it["fit"] = sm.fit_scale(it, layout, self._look())
        self._done()

    @Slot(str)
    def setTheme(self, name: str) -> None:
        if name in sm.THEMES and (name != self._deck.get("theme") or self._deck.get("look")):
            self._keep()
            self._deck["theme"], self._deck["look"] = name, None
            self._refit()
            self._done()

    @Slot(str)
    def setSize(self, size: str) -> None:
        if size in ("16:9", "4:3") and size != self._deck["size"]:
            self._keep()
            k = sm.slide_w(size) / sm.slide_w(self._deck["size"])
            for s in self._deck["slides"]:
                for it in s["items"]:
                    it["x"], it["w"] = round(it["x"] * k, 2), round(it["w"] * k, 2)
            self._deck["size"] = size
            self._refit()
            self._done()

    def _refit(self) -> None:
        look = self._look()
        for s in self._deck["slides"]:
            for it in s["items"]:
                if it.get("role") and it["kind"] == "text":
                    it["fit"] = sm.fit_scale(it, s.get("layout", ""), look)

    @Slot(str)
    def setBackground(self, spec: str) -> None:
        """'' (the theme's), '#RRGGBB', 'from #A to #B', or a picture file's path; for this slide, or all with 'all:'."""
        every = spec.startswith("all:")
        spec = spec[4:] if every else spec
        if spec and not spec.startswith("#") and not spec.startswith("from ") and Path(spec).is_file():
            try:
                bg = {"picture": picture_uri(spec, 3000)[0]}
            except OSError as err:
                self.failed.emit(str(err))
                return
        elif spec.startswith("from "):
            a, _, b = spec[5:].partition(" to ")
            bg = {"from": a.strip(), "to": b.strip() or a.strip(), "angle": 90}
        elif spec.startswith("#"):
            bg = {"color": spec}
        else:
            bg = None
        self._keep()
        for s in (self._deck["slides"] if every else [self._slide]):
            s["bg"] = bg
        self._done()

    @Slot(str, int, bool)
    def setTransition(self, kind: str, ms: int, every: bool) -> None:
        if kind not in ("none", "fade", "push", "wipe", "zoom", "cover"):
            return
        self._keep()
        for s in (self._deck["slides"] if every else [self._slide]):
            s["transition"] = {"kind": kind, "ms": max(100, min(3000, int(ms)))}
        self._done()

    @Slot(int, bool)
    def setHidden(self, index: int, hidden: bool) -> None:
        if 0 <= index < len(self._deck["slides"]):
            self._keep()
            self._deck["slides"][index]["hidden"] = hidden
            self._done()

    # ------------------------------------------------------------------ items
    def _find(self, iid: str) -> dict:
        return next((it for it in self._slide["items"] if it["id"] == iid), None)

    def _ids(self, ids) -> list:
        ids = ids.toVariant() if hasattr(ids, "toVariant") else ids
        return [it for it in self._slide["items"] if it["id"] in set(ids or [])]

    @Slot(str, str, result=str)
    def addItem(self, kind: str, arg: str) -> str:
        """A new text box, shape (arg: which) or picture (arg: the file), in the middle of the slide."""
        if self._path is None:
            return ""
        w = sm.slide_w(self._deck["size"])
        iid = self._iid()
        if kind == "picture":
            try:
                src, pw, ph = picture_uri(arg)
            except OSError as err:
                self.failed.emit(f"Couldn't add the picture: {err}")
                return ""
            k = min(1.0, w * 0.6 / pw, sm.SLIDE_H * 0.6 / ph)
            item = sm.new_item("picture", iid, (w - pw * k) / 2, (sm.SLIDE_H - ph * k) / 2, pw * k, ph * k, src=src)
        elif kind == "shape":
            shape = arg if arg in sm.SHAPES else "rect"
            line = shape in ("line", "arrowline")
            sw, sh = (480, 0.01) if line else (360, 360) if shape in ("ellipse", "star", "heart", "plus", "pentagon", "hexagon", "diamond") else (420, 260)
            item = sm.new_item("shape", iid, (w - sw) / 2, (sm.SLIDE_H - sh) / 2, sw, sh, shape=shape)
            if line:
                item.update({"fill": "", "line": "accent1", "lineW": 6})
        elif kind == "table":
            try:
                rows, cols = (int(x) for x in (arg or "3x3").lower().split("x"))
            except ValueError:
                rows, cols = 3, 3
            tw = min(w - 240, 300 * max(1, min(12, cols)))
            item = sm.new_table(iid, (w - tw) / 2, 0, tw, rows, cols)
            item["y"] = round(max(220.0, (sm.SLIDE_H - item["h"]) / 2), 2)
            if item["header"]:
                item["cells"][0] = [f"Heading {k + 1}" for k in range(len(item["cells"][0]))]
        elif kind == "chart":
            item = sm.new_chart(iid, (w - 1200) / 2, 260, 1200, 700, arg)
        else:
            item = sm.new_item("text", iid, (w - 800) / 2, sm.SLIDE_H / 2 - 40, 800, 80, grow=True)
        self._keep()
        self._slide["items"].append(item)
        self._done()
        return iid

    @Slot("QVariant", str, "QVariant")
    def setItems(self, ids, key: str, value) -> None:
        """One property on the chosen items: fill, line, lineW, shape, valign, rot, anim, flipH, flipV, locked…"""
        items = self._ids(ids)
        value = value.toVariant() if hasattr(value, "toVariant") else value
        if not items or key not in ("fill", "line", "lineW", "shape", "valign", "rot", "anim", "flipH", "flipV", "x", "y", "w", "h", "locked", "grow",
                                    "header", "banded", "accent", "size", "chart", "title", "legend"):
            return
        self._keep(f"set:{key}:{','.join(it['id'] for it in items)}")
        if key == "anim":
            if not value or not value.get("kind"):
                value = None
            else:
                value = {k: v for k, v in value.items() if v is not None}
                if "order" not in value:
                    top = max([float((x.get("anim") or {}).get("order") or 0) for x in self._slide["items"]] + [0])
                    value["order"] = top + 1
                value["ms"] = int(value.get("ms") or 500)
        for it in items:
            if key in ("x", "y", "w", "h", "rot", "lineW"):
                it[key] = round(float(value), 2)
            else:
                it[key] = value
        if key in ("w", "h"):
            self._settle(items)
        self._done()

    @Slot(str, result="QVariantList")
    def gridOf(self, iid: str) -> list:
        """A table's cells or a chart's data, as rows of text (a chart's series along the top, labels down the side)."""
        it = self._find(iid)
        return sm.grid_of(it) if it is not None and it["kind"] in ("table", "chart") else []

    @Slot(str, "QVariant")
    def setGrid(self, iid: str, grid) -> None:
        it = self._find(iid)
        grid = grid.toVariant() if hasattr(grid, "toVariant") else grid
        if it is None or it["kind"] not in ("table", "chart") or not isinstance(grid, list):
            return
        new = sm.with_grid(it, grid)
        if new == it:
            return
        self._keep("grid:" + iid)
        before = len(it.get("cells") or []) if it["kind"] == "table" else 0
        it.clear()
        it.update(new)
        if before and len(it["cells"]) != before:  # a row more or less: the table grows or shrinks with it
            it["h"] = round(it["h"] / before * len(it["cells"]), 2)
        self._done()

    @Slot("QVariant", float, float)
    def moveItems(self, ids, dx: float, dy: float) -> None:
        items = [it for it in self._ids(ids) if not it.get("locked")]
        if items and (dx or dy):
            self._keep("move:" + ",".join(it["id"] for it in items))
            for it in items:
                it["x"], it["y"] = round(it["x"] + dx, 2), round(it["y"] + dy, 2)
            self._done()

    @Slot(str, float, float, float, float)
    def place(self, iid: str, x: float, y: float, w: float, h: float) -> None:
        """Where one item goes after a resize."""
        it = self._find(iid)
        if it is None:
            return
        self._keep("place:" + iid)
        line = it.get("shape") in ("line", "arrowline")
        it["x"], it["y"] = round(x, 2), round(y, 2)
        it["w"], it["h"] = round(max(1.0 if line else 8.0, w), 2), round(max(0.01 if line else 8.0, h), 2)
        self._settle([it])
        self._done()

    @Slot(str, float, float, float, float)
    def placeLine(self, iid: str, x0: float, y0: float, x1: float, y1: float) -> None:
        """A line from one end to the other: its box, and which way it runs across the box."""
        it = self._find(iid)
        if it is None:
            return
        self._keep("place:" + iid)
        it["x"], it["y"] = round(min(x0, x1), 2), round(min(y0, y1), 2)
        it["w"], it["h"] = round(max(0.01, abs(x1 - x0)), 2), round(max(0.01, abs(y1 - y0)), 2)
        it["flipH"], it["flipV"] = x1 < x0, y1 < y0
        self._done()

    def _settle(self, items: list) -> None:
        look, layout = self._look(), self._slide.get("layout", "")
        for it in items:
            if it["kind"] == "text" and it.get("grow"):
                it["h"] = round(max(40.0, sm.text_height(it, layout, look, it["w"] - 2 * sm.INSET_X) + 2 * sm.INSET_Y), 2)
            elif it["kind"] == "text" and it.get("role"):
                it["fit"] = sm.fit_scale(it, layout, look)

    @Slot("QVariant")
    def removeItems(self, ids) -> None:
        items = self._ids(ids)
        if items:
            self._keep()
            gone = {it["id"] for it in items}
            self._slide["items"] = [it for it in self._slide["items"] if it["id"] not in gone]
            sm.tidy_groups(self._slide["items"])
            self._done()

    # ------------------------------------------------------------------ groups
    def _new_group(self) -> str:
        used = {it.get("group") for s in self._deck["slides"] for it in s.get("items", [])}
        n = 1
        while f"g{n}" in used:
            n += 1
        return f"g{n}"

    @Slot("QVariant", result=bool)
    def group(self, ids) -> bool:
        """Ctrl+G: these items (two or more) become one group, in front where the front-most of them was."""
        items = [it for it in self._ids(ids) if not it.get("locked")]
        if len(items) < 2:
            return False
        self._keep()
        gid = self._new_group()
        chosen = {it["id"] for it in items}
        for it in items:
            it["group"] = gid
            if it.get("role"):                      # a placeholder can't be in a group (PowerPoint's rule): it becomes a text box
                it["role"] = ""
        lst = self._slide["items"]
        top = max(k for k, it in enumerate(lst) if it["id"] in chosen)
        members = [it for it in lst if it["id"] in chosen]
        rest = [it for it in lst if it["id"] not in chosen]
        at = sum(1 for it in lst[:top + 1] if it["id"] not in chosen)
        self._slide["items"] = rest[:at] + members + rest[at:]
        sm.tidy_groups(self._slide["items"])
        self._done()
        return True

    @Slot("QVariant", result=bool)
    def ungroup(self, ids) -> bool:
        """Ctrl+Shift+G: the groups these items are in come apart."""
        groups = {it.get("group") for it in self._ids(ids)} - {None, ""}
        if not groups:
            return False
        self._keep()
        for it in self._slide["items"]:
            if it.get("group") in groups:
                it.pop("group", None)
        self._done()
        return True

    @Slot("QVariant")
    def placeItems(self, rects) -> None:
        """Several items' new boxes at once (a group sized): [{id, x, y, w, h}]."""
        rects = rects.toVariant() if hasattr(rects, "toVariant") else rects
        todo = [(self._find(r.get("id", "")), r) for r in rects or [] if isinstance(r, dict)]
        todo = [(it, r) for it, r in todo if it is not None and not it.get("locked")]
        if not todo:
            return
        self._keep("place:" + ",".join(it["id"] for it, _ in todo))
        for it, r in todo:
            line = it.get("shape") in ("line", "arrowline")
            it["x"], it["y"] = round(float(r["x"]), 2), round(float(r["y"]), 2)
            it["w"], it["h"] = round(max(0.01 if line else 4.0, float(r["w"])), 2), round(max(0.01 if line else 4.0, float(r["h"])), 2)
        self._settle([it for it, _ in todo])
        self._done()

    # ------------------------------------------------------------------ the footer: slide numbers, the date, a line of text
    footer = Property("QVariantMap", lambda self: sm.clean_footer(self._deck.get("footer")), notify=deckChanged)

    @Slot(str, "QVariant")
    def setFooter(self, key: str, value) -> None:
        value = value.toVariant() if hasattr(value, "toVariant") else value
        f = sm.clean_footer(self._deck.get("footer"))
        if key not in f or f[key] == value:
            return
        self._keep()
        f[key] = value
        self._deck["footer"] = sm.clean_footer(f)
        self._done()

    @Slot("QVariant", result="QVariantList")
    def duplicateItems(self, ids) -> list:
        items = self._ids(ids)
        if not items:
            return []
        self._keep()
        made, regroup = [], {}
        for it in items:
            c = copy.deepcopy(it)
            c["id"], c["role"] = self._iid(), ""
            c["x"], c["y"] = it["x"] + 40, it["y"] + 40
            if c.get("group"):
                c["group"] = regroup.setdefault(c["group"], self._new_group() + "-" + c["id"])
            self._slide["items"].append(c)
            made.append(c["id"])
        sm.tidy_groups(self._slide["items"])
        self._done()
        return made

    @Slot("QVariant", str)
    def order(self, ids, how: str) -> None:
        items = self._ids(ids)
        if not items:
            return
        self._keep()
        rest = [it for it in self._slide["items"] if it not in items]
        if how == "front":
            self._slide["items"] = rest + items
        elif how == "back":
            self._slide["items"] = items + rest
        else:
            seq = self._slide["items"]
            step = 1 if how == "forward" else -1
            for it in (reversed(items) if step > 0 else items):
                i = seq.index(it)
                j = i + step
                if 0 <= j < len(seq) and seq[j] not in items:
                    seq[i], seq[j] = seq[j], seq[i]
        sm.tidy_groups(self._slide["items"])
        self._done()

    @Slot("QVariant", str)
    def align(self, ids, how: str) -> None:
        """Line the items up with each other, or with the slide when there's one."""
        items = [it for it in self._ids(ids) if not it.get("locked")]
        if not items:
            return
        self._keep()
        sw = sm.slide_w(self._deck["size"])
        box = sm.bounds(items) if len(items) > 1 else None
        left, top = (box.left(), box.top()) if box else (0, 0)
        right, bottom = (box.right(), box.bottom()) if box else (sw, sm.SLIDE_H)
        if how in ("hspread", "vspread") and len(items) > 2:
            horiz = how == "hspread"
            seq = sorted(items, key=lambda it: it["x"] if horiz else it["y"])
            span = (right - left) if horiz else (bottom - top)
            total = sum(it["w"] if horiz else it["h"] for it in seq)
            gap = (span - total) / (len(seq) - 1)
            pos = left if horiz else top
            for it in seq:
                it["x" if horiz else "y"] = round(pos, 2)
                pos += (it["w"] if horiz else it["h"]) + gap
        for it in items:
            if how == "left":
                it["x"] = left
            elif how == "center":
                it["x"] = round((left + right) / 2 - it["w"] / 2, 2)
            elif how == "right":
                it["x"] = round(right - it["w"], 2)
            elif how == "top":
                it["y"] = top
            elif how == "middle":
                it["y"] = round((top + bottom) / 2 - it["h"] / 2, 2)
            elif how == "bottom":
                it["y"] = round(bottom - it["h"], 2)
        self._done()

    @Slot(str, str)
    def replacePicture(self, iid: str, path: str) -> None:
        it = self._find(iid)
        if it is None or it["kind"] != "picture":
            return
        try:
            src, pw, ph = picture_uri(path)
        except OSError as err:
            self.failed.emit(f"Couldn't use the picture: {err}")
            return
        self._keep()
        cx, cy = it["x"] + it["w"] / 2, it["y"] + it["h"] / 2
        it["src"], it["h"] = src, round(it["w"] * ph / pw, 2)
        it["x"], it["y"] = round(cx - it["w"] / 2, 2), round(cy - it["h"] / 2, 2)
        self._done()

    @Slot(str, result=float)
    def aspect(self, iid: str) -> float:
        it = self._find(iid)
        if it is None or it["kind"] != "picture":
            return 0.0
        img = sm.image_of(it.get("src", ""))
        return img.width() / img.height() if not img.isNull() and img.height() else 0.0

    # ------------------------------------------------------------------ copy and paste
    @Slot("QVariant")
    def copyItems(self, ids) -> None:
        items = self._ids(ids)
        if not items:
            return
        self._clip = copy.deepcopy(items)
        data = QMimeData()
        data.setData(MIME, QByteArray(json.dumps(items).encode()))
        data.setText("\n\n".join(sm.text_of(it) for it in items if sm.has_text(it)))
        pic = next((it for it in items if it["kind"] == "picture"), None)
        if pic is not None and len(items) == 1:
            img = sm.image_of(pic.get("src", ""))
            if not img.isNull():
                data.setImageData(img)
        QGuiApplication.clipboard().setMimeData(data)

    @Slot(result="QVariantList")
    def pasteItems(self) -> list:
        """Items copied here (or in another Slides window); else a picture, or text as a new text box."""
        if self._path is None:
            return []
        data = QGuiApplication.clipboard().mimeData()
        items = None
        if data is not None and data.hasFormat(MIME):
            try:
                items = json.loads(bytes(data.data(MIME)).decode())
            except ValueError:
                items = None
        if items is None and data is not None and data.hasImage():
            img = data.imageData()
            if isinstance(img, QImage) and not img.isNull():
                import tempfile
                tmp = Path(tempfile.mkdtemp(prefix="huginn-paste-")) / "picture.png"
                img.save(str(tmp))
                return [self.addItem("picture", str(tmp))]
        if items is None and data is not None and data.hasText() and data.text().strip():
            iid = self.addItem("text", "")
            it = self._find(iid)
            it["paras"] = [{"runs": [{"t": line}] if line else [], "lvl": 0, "list": "", "align": ""} for line in data.text().strip().split("\n")[:200]]
            self._settle([it])
            self._done()
            return [iid]
        if not items:
            return []
        self._keep()
        made, regroup = [], {}
        here = {it["id"]: it for it in self._slide["items"]}
        for it in items:
            c = copy.deepcopy(it)
            same = here.get(it.get("id"))
            c["id"] = self._iid()
            if c.get("group"):
                c["group"] = regroup.setdefault(c["group"], self._new_group() + "-" + c["id"])
            if same is not None and abs(same["x"] - it["x"]) < 1 and abs(same["y"] - it["y"]) < 1:
                c["x"], c["y"] = it["x"] + 40, it["y"] + 40           # pasted on its own slide: a little apart
            if c.get("role") and any(x.get("role") == c["role"] for x in self._slide["items"]):
                c["role"] = ""
            self._slide["items"].append(c)
            made.append(c["id"])
        sm.tidy_groups(self._slide["items"])
        self._done()
        return made

    # ------------------------------------------------------------------ text
    @Slot("QVariant")
    def attachEditor(self, quick_doc) -> None:
        self._edit_quick = quick_doc
        self._edit_doc = quick_doc.textDocument()
        self._edit_doc.setIndentWidth(sm.INDENT)
        self._edit_doc.setDocumentMargin(0)

    @Slot(str)
    def loadEditor(self, iid: str) -> None:
        """The item's text into the editor, built straight in (an empty paragraph keeps its size and colour)."""
        it = self._find(iid)
        if it is None or self._edit_doc is None:
            return
        layout, look = self._slide.get("layout", ""), self._look()
        first = (it.get("paras") or [{}])[0]
        dflt = sm.para_defaults(it, first, layout, look)
        font = QFont(dflt["font"])
        font.setPixelSize(round(dflt["size"] * sm.PT))
        self._edit_doc.setDefaultFont(font)
        sm.build_doc(it, layout, look, self._edit_doc)

    @Slot(str, result=str)
    def editHtml(self, iid: str) -> str:
        it = self._find(iid)
        return sm.item_html(it, self._slide.get("layout", ""), self._look()) if it else ""

    @Slot(str)
    def commitEdit(self, iid: str) -> None:
        """What's in the editor, back into the item (called as the typing pauses, and at the end)."""
        it = self._find(iid)
        if it is None or self._edit_doc is None:
            return
        paras = sm.read_doc(self._edit_doc, it, self._slide.get("layout", ""), self._look())
        if paras == it.get("paras"):
            return
        self._keep("edit:" + iid)
        it["paras"] = paras
        self._settle([it])
        self._done()

    def _blocks(self, start: int, end: int) -> tuple:
        doc = self._edit_doc
        return doc.findBlock(min(start, end)).blockNumber(), doc.findBlock(max(start, end)).blockNumber()

    @Slot(str, int, int, str, result="QVariantList")
    def style(self, iid: str, start: int, end: int, what: str) -> list:
        """Formatting in the editor: bold, italic, underline, strike, size:N, bigger, smaller, font:F, #RRGGBB, clear
        on the selection (or the word); left/center/right/justify, bullet, number, indent, outdent, spacing:N on the
        paragraphs. Returns the selection to put back."""
        it = self._find(iid)
        doc = self._edit_doc
        if it is None or doc is None:
            return [start, end]
        start, end = min(start, end), max(start, end)
        self._apply(it, doc, start, end, what)
        self.commitEdit(iid)
        return [start, end]

    def _apply(self, it: dict, doc, start: int, end: int, what: str) -> None:
        if what in ("left", "center", "right", "justify", "bullet", "number", "indent", "outdent") or what.startswith("spacing:"):
            layout, look = self._slide.get("layout", ""), self._look()
            paras = sm.read_doc(doc, it, layout, look)
            a, b = self._blocks(start, end)
            chosen = paras[a:b + 1]
            if what in ("bullet", "number"):
                on = not all(p.get("list") == what for p in chosen)
                for p in chosen:
                    p["list"] = what if on else ""
            elif what in ("indent", "outdent"):
                for p in chosen:
                    p["lvl"] = max(0, min(8, int(p.get("lvl", 0)) + (1 if what == "indent" else -1)))
            elif what.startswith("spacing:"):
                for p in chosen:
                    p["spacing"] = float(what[8:] or 1)
            else:
                dflt = sm.role_style(it.get("role", ""), layout)["align"] if it["kind"] == "text" else "center"
                for p in chosen:
                    p["align"] = "" if what == dflt else what
            work = dict(it, paras=paras)
            sm.build_doc(work, layout, look, doc)
            return
        cursor = QTextCursor(doc)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        if not cursor.hasSelection():
            word = QTextCursor(cursor)
            word.select(QTextCursor.WordUnderCursor)
            if word.hasSelection() and word.selectionStart() < start < word.selectionEnd():
                cursor = word
        now = cursor.charFormat()
        fmt = QTextCharFormat()
        if what == "bold":
            fmt.setFontWeight(QFont.Normal if now.fontWeight() >= QFont.DemiBold else QFont.Bold)
        elif what == "italic":
            fmt.setFontItalic(not now.fontItalic())
        elif what == "underline":
            fmt.setFontUnderline(not now.fontUnderline())
        elif what == "strike":
            fmt.setFontStrikeOut(not now.fontStrikeOut())
        elif what in ("bigger", "smaller") or what.startswith("size:"):
            pt = (now.font().pixelSize() / sm.PT) if now.font().pixelSize() > 0 else 24
            steps = [10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 44, 48, 54, 60, 66, 72, 80, 88, 96, 120]
            if what == "bigger":
                pt = next((s for s in steps if s > pt + 0.1), pt)
            elif what == "smaller":
                pt = next((s for s in reversed(steps) if s < pt - 0.1), pt)
            else:
                pt = max(4.0, min(400.0, float(what[5:] or 24)))
            fmt.setProperty(QTextCharFormat.FontPixelSize, round(pt * sm.PT))
        elif what.startswith("font:"):
            fmt.setFontFamilies([what[5:]])
        elif what.startswith("#"):
            from PySide6.QtGui import QColor
            fmt.setForeground(QColor(what))
        elif what == "clear":
            layout, look = self._slide.get("layout", ""), self._look()
            blk = doc.findBlock(start)
            lst = blk.textList()
            lvl = (lst.format().indent() - 1) if lst is not None else blk.blockFormat().indent()
            dflt = sm.para_defaults(it, {"lvl": lvl}, layout, look)
            cursor.setCharFormat(sm.char_format({}, dflt))
            return
        else:
            return
        cursor.mergeCharFormat(fmt)

    @Slot("QVariant", str)
    def styleItems(self, ids, what: str) -> None:
        """Formatting on all the text of the chosen items (when they're chosen, not being typed in)."""
        from PySide6.QtGui import QTextDocument
        items = [it for it in self._ids(ids) if it.get("paras") is not None and it.get("shape") not in ("line", "arrowline")]
        if not items:
            return
        self._keep()
        layout, look = self._slide.get("layout", ""), self._look()
        for it in items:
            doc = sm.build_doc(it, layout, look, QTextDocument())
            end = max(0, doc.characterCount() - 1)
            if what in ("bold", "italic", "underline", "strike"):        # on for all if any lacks it
                key = {"bold": "b", "italic": "i", "underline": "u", "strike": "s"}[what]
                on = False
                for p in it.get("paras", []):
                    dflt = sm.para_defaults(it, p, layout, look)
                    on = on or any(not r.get(key, dflt.get(key, False)) for r in p.get("runs", []) if r.get("t"))
                self._apply_all(doc, key, on)
            else:
                self._apply(it, doc, 0, end, what)
            it["paras"] = sm.read_doc(doc, it, layout, look)
            self._settle([it])
        self._done()

    @staticmethod
    def _apply_all(doc, key: str, on: bool) -> None:
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.Document)
        fmt = QTextCharFormat()
        if key == "b":
            fmt.setFontWeight(QFont.Bold if on else QFont.Normal)
        elif key == "i":
            fmt.setFontItalic(on)
        elif key == "u":
            fmt.setFontUnderline(on)
        else:
            fmt.setFontStrikeOut(on)
        cursor.mergeCharFormat(fmt)

    @Slot(str, result="QVariant")
    def itemFormat(self, iid: str) -> dict:
        from PySide6.QtGui import QTextDocument
        it = self._find(iid)
        if it is None or it.get("paras") is None:
            return {}
        saved = self._edit_doc
        self._edit_doc = sm.build_doc(it, self._slide.get("layout", ""), self._look(), QTextDocument())
        try:
            return self.formatAt(iid, 1 if self._edit_doc.characterCount() > 1 else 0)
        finally:
            self._edit_doc = saved

    @Slot(str, int, result="QVariant")
    def formatAt(self, iid: str, pos: int) -> dict:
        """The formatting where the cursor is, for the formatting island."""
        doc = self._edit_doc
        it = self._find(iid)
        if doc is None or it is None:
            return {}
        cursor = QTextCursor(doc)
        cursor.setPosition(max(0, min(pos, doc.characterCount() - 1)))
        cf = cursor.charFormat()
        font = cf.font()
        blk = cursor.block()
        lst = blk.textList()
        al = blk.blockFormat().alignment() & Qt.AlignHorizontal_Mask
        fams = cf.fontFamilies() if isinstance(cf.fontFamilies(), list) else []
        return {"b": font.bold(), "i": font.italic(), "u": font.underline(), "s": font.strikeOut(),
                "size": round(font.pixelSize() / sm.PT) if font.pixelSize() > 0 else 0, "font": fams[0] if fams else font.family(),
                "color": cf.foreground().color().name() if cf.foreground().style() != Qt.NoBrush else "",
                "list": ("number" if lst.format().style() in sm.LIST_STYLES["number"] else "bullet") if lst is not None else "",
                "align": {Qt.AlignHCenter: "center", Qt.AlignRight: "right", Qt.AlignJustify: "justify"}.get(al, "left")}

    @Slot(str, str)
    def setText(self, iid: str, text: str) -> None:
        """Plain text into an item (paragraphs by line), keeping each paragraph's list."""
        it = self._find(iid)
        if it is None:
            return
        self._keep()
        st = sm.role_style(it.get("role", ""), self._slide.get("layout", ""))
        it["paras"] = [{"runs": [{"t": line}] if line else [], "lvl": 0, "list": st["list"], "align": ""} for line in text.split("\n")]
        self._settle([it])
        self._done()

    @Slot(int, result=str)
    def plainText(self, index: int) -> str:
        """A slide's words (titles first), for the outline and for search."""
        if not 0 <= index < len(self._deck["slides"]):
            return ""
        items = sorted(self._deck["slides"][index]["items"], key=lambda it: (it.get("role") != "title", it["y"], it["x"]))
        return "\n".join(sm.text_of(it) for it in items if sm.has_text(it))

    @Slot(int, result=str)
    def titleOf(self, index: int) -> str:
        if not 0 <= index < len(self._deck["slides"]):
            return ""
        t = next((it for it in self._deck["slides"][index]["items"] if it.get("role") == "title" and sm.has_text(it)), None)
        return sm.text_of(t).replace("\n", " ") if t else ""

    @Slot(str, result="QVariantList")
    def findText(self, needle: str) -> list:
        """The slides whose words contain the text."""
        n = needle.casefold()
        return [i for i in range(len(self._deck["slides"])) if n and n in self.plainText(i).casefold()]

    @Slot(str, str, result=int)
    def replaceAll(self, needle: str, repl: str) -> int:
        if not needle:
            return 0
        count = 0
        for s in self._deck["slides"]:
            for it in s["items"]:
                for p in it.get("paras", []):
                    for r in p.get("runs", []):
                        if needle in r.get("t", ""):
                            count += r["t"].count(needle)
        if count:
            self._keep()
            for s in self._deck["slides"]:
                for it in s["items"]:
                    for p in it.get("paras", []):
                        for r in p.get("runs", []):
                            r["t"] = r.get("t", "").replace(needle, repl)
            self._refit()
            self._done()
        return count
