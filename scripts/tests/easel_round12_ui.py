"""Easel, round twelve, in its window (the demo): the Automate menu, recording's badge, the Actions sheet with a kept
action, Merge Photos' chooser (two photos ticked enable Merge), the folder sheet for a batch, and the window waiting
while a folder is worked through; no QML complaints. Shots of the sheets go to $EASEL12_SHOTS when set."""
import os, sys, tempfile
home = tempfile.mkdtemp(prefix="easel12ui-")
os.environ.update(HOME=home, XDG_CONFIG_HOME=home + "/config", XDG_CACHE_HOME=home + "/cache", XDG_DATA_HOME=home + "/data",
                  QT_QPA_PLATFORM="offscreen", HUGINN_SHOT_DELAY="600000")
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
SHOTS = os.environ.get("EASEL12_SHOTS", "")
sys.path.insert(0, SRC + "/apps"); sys.path.insert(0, SRC + "/shell")
from PySide6.QtCore import QTimer, QEventLoop, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication, QImage
import huginn_app as ha

ok = bad = 0
said = []
def check(name, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
        print("ok  ", name)
    else:
        bad += 1
        print("FAIL", name, extra, flush=True)

def heard(kind, ctx, msg):
    if "Easel.qml" in msg or "qml" in msg.lower() and ("Error" in msg or "TypeError" in msg or "ReferenceError" in msg):
        said.append(msg)
qInstallMessageHandler(heard)

def settle(ms=200):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()

def shot(root, name):
    if SHOTS:
        root.grabWindow().save(os.path.join(SHOTS, name))

def visible_text(item, out=None):
    out = [] if out is None else out
    if item.property("visible") is False:
        return out
    t = item.property("text")
    if isinstance(t, str) and t:
        out.append(t)
    for k in item.childItems():
        visible_text(k, out)
    return out

def checks(engine):
    root = engine.rootObjects()[0]
    b = engine.rootContext().contextProperty("Backend")
    root.setProperty("sheet", "")
    root.setProperty("menuOpen", True)
    settle()
    words = visible_text(root.contentItem())
    check("the menu has Automate: Start Recording, Actions…, Merge Photos…", all(w in words for w in ("AUTOMATE", "Start Recording", "Actions…", "Merge Photos…")), [w for w in words if w.isupper()])
    root.setProperty("menuOpen", False)
    b.startRecording()
    settle()
    words = visible_text(root.contentItem())
    check("recording shows its badge, and the menu offers to stop", "Recording an action" in words)
    b.applyFilter("sharpen", 0.3)
    b.imageSize(b.property("docW") // 2, b.property("docH") // 2)
    root.setProperty("sheet", "keepaction")
    settle()
    check("stopping asks for a name", "Keep the recording as an action" in visible_text(root.contentItem()))
    b.stopRecording("Web-ready")
    root.setProperty("sheet", "actions")
    settle()
    words = visible_text(root.contentItem())
    check("the Actions sheet lists it with its steps, Play and On a Folder…", "Web-ready" in words and "Play" in words and "On a Folder…" in words
          and any("2 steps" in w for w in words), [w for w in words if "step" in w])
    shot(root, "easel-actions.png")
    pics = os.path.join(home, "Pictures")
    os.makedirs(pics, exist_ok=True)
    for n in ("a.png", "b.png", "c.png"):
        q = QImage(64, 48, QImage.Format.Format_RGB32); q.fill(0xFF446688); q.save(os.path.join(pics, n))
    root.startBrowse(pics)
    root.open("merge", {"how": "panorama", "picked": [os.path.join(pics, "a.png")]})
    settle()
    words = visible_text(root.contentItem())
    check("Merge Photos: the three ways and the photos in the folder", "Merge photos" in words and "Panorama" in words and "Focus stack" in words and "b.png" in words, words[:30])
    from PySide6.QtCore import QObject
    def merge_btn():
        for w in root.findChildren(QObject):
            if w.property("text") == "Merge" and w.property("visible"):
                return w
    m = merge_btn()
    check("…Merge waits for two photos", m is not None and m.property("enabled") is False)
    root.setProperty("sheetData", {"how": "focus", "picked": [os.path.join(pics, "a.png"), os.path.join(pics, "b.png")]})
    settle()
    words = visible_text(root.contentItem())
    check("…two ticked: Merge can go, and focus stacking is explained", merge_btn().property("enabled") is True and any("sharpest" in w and "2 chosen" in w for w in words))
    shot(root, "easel-merge.png")
    root.open("batch", {"action": 0, "name": "Web-ready"})
    settle()
    words = visible_text(root.contentItem())
    check("a batch: the folder, and where the results go", "Play “Web-ready” on a folder" in words and "Run on This Folder" in words and any("Edited by Easel" in w for w in words))
    root.setProperty("sheet", "")
    b.batch(0, pics)
    settle(30)
    words = visible_text(root.contentItem())
    check("the window waits while the folder is worked through", any(w.startswith("Working through the folder") for w in words) or not b.property("batchState")["on"])
    for _ in range(100):
        if not b.property("batchState")["on"]:
            break
        settle(50)
    check("…and is given back", not b.property("batchState")["on"] and os.path.isfile(os.path.join(pics, "Edited by Easel", "a.png")))
    check("no QML complaints", not said, said[:5])
    QGuiApplication.instance().quit()

class Engine(ha.QQmlApplicationEngine):
    def load(self, *a):
        super().load(*a)
        QTimer.singleShot(600, lambda: checks(self))

ha.QQmlApplicationEngine = Engine
sys.argv = ["huginn_app.py", "easel", "--demo", "--shot", os.path.join(home, "shot.png")]
try:
    ha.main()
except SystemExit:
    pass
print(f"{ok} passed, {bad} failed")
sys.exit(1 if bad or ok < 10 else 0)
