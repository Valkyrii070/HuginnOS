#!/usr/bin/env python3
"""Easel, round twelve: actions (recorded, played again, run over a folder) and photos merged into one (a panorama,
exposures blended, a focus stack).  Usage: easel_round12_test.py <kit root>   (QT_QPA_PLATFORM=offscreen; not as root)"""
import json, os, sys, tempfile, time
from pathlib import Path
KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0:
    sys.exit("not as root")
home = tempfile.mkdtemp(prefix="easel12-")
os.environ.update(HOME=home, XDG_DATA_HOME=home + "/d", XDG_CONFIG_HOME=home + "/c", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtCore import QCoreApplication
app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
import numpy as np
import cv2
import huginn_easel as ez, huginn_easel_ui as eu, huginn_easel_more as more

passed = failed = 0
def ok(what, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok  ", what)
    else:
        failed += 1
        print("FAIL", what, extra)
def fresh(w=320, h=240, bg="#FFFFFF"):
    e = eu.Easel(False, ""); e.newDoc(w, h, bg); msgs = []
    e.said.connect(lambda m, bad: msgs.append((m, bad))); return e, msgs
rng = np.random.default_rng(12)

# ---------------------------------------------------------------- a scene to photograph: shapes and texture
def scene(w=1500, h=520):
    img = np.full((h, w, 3), 90, np.uint8)
    for _ in range(260):
        c = tuple(int(x) for x in rng.integers(0, 255, 3)); x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        if rng.random() < 0.5:
            cv2.rectangle(img, (x, y), (x + int(rng.integers(8, 60)), y + int(rng.integers(8, 60))), c, -1)
        else:
            cv2.circle(img, (x, y), int(rng.integers(5, 30)), c, -1)
    img = cv2.add(img, rng.integers(0, 25, img.shape, dtype=np.uint8))
    return img
def rgba(bgr):
    out = np.empty(bgr.shape[:2] + (4,), np.uint8); out[..., :3] = bgr[..., ::-1]; out[..., 3] = 255; return out
def sharpness(rgba_, box):
    x0, x1 = box; g = cv2.cvtColor(np.ascontiguousarray(rgba_[:, x0:x1, 2::-1]), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())

world = scene()
shots = [rgba(world[:, x:x + 640]) for x in (0, 430, 860)]
pano = more.merge_photos("panorama", shots)
ok("panorama: three overlapping shots joined wider than any one", pano.shape[1] > 900 and pano.shape[0] >= 400 and pano.shape[2] == 4, pano.shape)
ok("…what no shot covered is clear, the rest solid", (pano[..., 3] == 255).mean() > 0.6)
try:
    more.merge_photos("panorama", [rgba(scene(600, 400)), rgba(scene(600, 400))])
    ok("unrelated photos aren't joined into nonsense", False)
except ValueError as err:
    ok("unrelated photos aren't joined into nonsense (it says why)", "overlap" in str(err) or "lined up" in str(err) or "joined" in str(err), str(err))

base = world[:, :700].astype(np.float32)
dark = rgba(np.clip(base * 0.35, 0, 255).astype(np.uint8))
bright = rgba(np.clip(base * 2.2, 0, 255).astype(np.uint8))
fused = more.merge_photos("exposures", [dark, bright])
clipped = lambda a: float((a[..., :3] >= 254).mean())
ok("exposures: brighter than the dark shot, fewer blown highlights than the bright one",
   fused[..., :3].mean() > dark[..., :3].mean() + 10 and clipped(fused) < clipped(bright) * 0.7, (fused[..., :3].mean(), dark[..., :3].mean(), clipped(fused), clipped(bright)))
ok("…the same size, solid", fused.shape == dark.shape and (fused[..., 3] == 255).all())

sharp = world[:, :700]
blur = cv2.GaussianBlur(sharp, (0, 0), 4)
near = sharp.copy(); near[:, 350:] = blur[:, 350:]                 # focused on the left
far = sharp.copy(); far[:, :350] = blur[:, :350]                   # focused on the right
stack = more.merge_photos("focus", [rgba(near), rgba(far)])
orig = rgba(sharp)
ok("focus stack: both halves sharp", sharpness(stack, (20, 330)) > 0.75 * sharpness(orig, (20, 330)) and sharpness(stack, (370, 680)) > 0.75 * sharpness(orig, (370, 680)),
   (sharpness(stack, (20, 330)), sharpness(orig, (20, 330)), sharpness(stack, (370, 680)), sharpness(orig, (370, 680))))
ok("…sharper than either photo alone", sharpness(stack, (0, 700)) > max(sharpness(rgba(near), (0, 700)), sharpness(rgba(far), (0, 700))))
shifted = np.roll(far, 6, axis=1)
stack2 = more.merge_photos("focus", [rgba(near), rgba(shifted)])
ok("…a hand-held shot a little off is lined up first", sharpness(stack2, (370, 680)) > 0.6 * sharpness(orig, (370, 680)))
for bad, why in ((["panorama", shots[:1]], "one photo"), (["cubism", shots], "a way that isn't one"), (["focus", shots * 9], "too many")):
    try:
        more.merge_photos(*bad); ok(f"refused: {why}", False)
    except ValueError:
        ok(f"refused: {why}", True)

# through the window's backend: files on disk, a new picture made
d = Path(home) / "shots"; d.mkdir()
for i, s in enumerate(shots):
    cv2.imwrite(str(d / f"shot{i}.jpg"), cv2.cvtColor(s[..., :3], cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])
e, msgs = fresh()
e.mergePhotos("panorama", [str(d / f"shot{i}.jpg") for i in range(3)])
ok("Merge Photos: a new picture, the panorama on its layer", e.doc.w > 900 and e.doc.layers[0]["name"] == "Panorama" and "3 photos" in msgs[-1][0], (e.doc.w, msgs[-1:]))
e.mergePhotos("panorama", [str(d / "shot0.jpg"), str(d / "missing.jpg")])
ok("…a photo that can't be read says so, the picture stays", msgs[-1][1] and "missing.jpg" in msgs[-1][0] and e.doc.w > 900)
ok("…the three ways listed", [m["id"] for m in e.merges] == ["panorama", "exposures", "focus"])

# ---------------------------------------------------------------- actions
e, msgs = fresh(400, 300)
ok("not recording at first", e.recording is False)
e.startRecording()
ok("recording", e.recording is True)
e.applyFilter("sharpen", 0.3)
e.imageSize(200, 150)                 # in proportion
e.transformCanvas("cw")
e.addAdjustment("colour"); e.setAdjust("saturation", 0.1); e.setAdjust("saturation", 0.25); e.setAdjust("saturation", 0.4)
e.setLayer(e.doc.layer()["id"], "opacity", 0.8)
e.press(10, 10, 1, 0); e.release(20, 20, 0)                        # (a stroke: nothing to play again)
e.stopRecording("Web-ready")
acts = e.actions
ok("kept as an action with its steps, a slider's run as one", e.recording is False and len(acts) == 1 and acts[0]["name"] == "Web-ready" and acts[0]["count"] == 6, acts)
ok("…described in words", acts[0]["steps"][0] == "Filter: sharpen" and acts[0]["steps"][1] == "Image size: 200 wide, in proportion", acts[0]["steps"])
kept = json.loads((Path(home) / "d/huginn/easel-actions.json").read_text())
ok("…and kept on disk", kept[0]["name"] == "Web-ready" and kept[0]["steps"][4] == ["setAdjust", ["saturation", 0.4]], kept)
e.startRecording(); e.stopRecording("Nothing")
ok("recording nothing keeps nothing, and says so", len(e.actions) == 1 and msgs[-1][1])

e2, msgs2 = fresh(800, 400)
e2.playAction(0)
ok("played on another picture: resized in its own proportion and turned", (e2.doc.w, e2.doc.h) == (100, 200), (e2.doc.w, e2.doc.h))
ok("…with the adjustment and the layer change", e2.doc.layer()["kind"] == "adjust" and abs(e2.doc.layer()["opacity"] - 0.8) < 1e-6 and "Played" in msgs2[-1][0])
n_undo = len(e2._undo)
e2.undo()
ok("…each step its own in History", len(e2._undo) == n_undo - 1)
e3, _ = fresh(); e3.playAction(7); e3.deleteAction(9)
ok("an action that isn't there: nothing happens", len(e3.actions) == 1)

# odd files of actions are made safe
(Path(home) / "d/huginn/easel-actions.json").write_text(json.dumps([{"name": "ok", "steps": [["filter", ["blur", 0.2]], ["rm -rf", []], ["filter", [{"x": 1}]], ["flatten", []]]},
                                                                    {"name": "", "steps": [["trim", []]]}, "junk", {"name": "inf", "steps": [["feather", [float("inf")]]]}]).replace("Infinity", "1e999"))
e4, _ = fresh()
ok("a damaged actions file: only sound steps of named actions", [a["name"] for a in e4.actions] == ["ok"] and e4.actions[0]["count"] == 2, e4.actions)

# batch: every picture in a folder, the originals untouched
folder = Path(home) / "batch"; folder.mkdir()
for i, (w, h) in enumerate(((600, 400), (300, 300), (500, 800))):
    q = QImage(w, h, QImage.Format.Format_RGB32); q.fill(0xFF336699 + i); q.save(str(folder / f"p{i}.{'png' if i != 1 else 'jpg'}"))
(folder / "notes.txt").write_text("not a picture")
(folder / "broken.png").write_bytes(b"\x89PNG not really")
e.startRecording(); e.imageSize(e.doc.w // 2, e.doc.h // 2); e.applyFilter("blur", 0.2); e.stopRecording("Half")
idx = [a["name"] for a in e.actions].index("Half")
before_doc = e.doc
e.batch(idx, str(folder))
ok("a folder's run starts, the window told", e.batchState["on"] and e.batchState["of"] == 4)
end = time.time() + 60
while e.batchState["on"] and time.time() < end:
    QCoreApplication.processEvents(); time.sleep(0.01)
out = folder / "Edited by Easel"
sizes = {p.name: QImage(str(p)).size().toTuple() for p in sorted(out.iterdir())} if out.is_dir() else {}
ok("every picture done: the recorded width, each in its own proportion, in its own format", sizes == {"p0.png": (75, 50), "p1.jpg": (75, 75), "p2.png": (75, 120)}, sizes)
ok("…the broken one said, the rest went on", "broken.png" in msgs[-1][0] and msgs[-1][1], msgs[-1:])
ok("…the originals untouched, the open picture given back", QImage(str(folder / "p0.png")).size().toTuple() == (600, 400) and e.doc is before_doc)
e.batch(idx, str(Path(home) / "nowhere")); e.batch(99, str(folder))
ok("a folder that isn't there, or an action that isn't: nothing starts", not e.batchState["on"])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
