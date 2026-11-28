"""Clips, pro round six, in its window (the demo): the Words tab, cutting the ums from it, the one-colour controls,
an adjustment layer's tabs, smooth slow motion's switch and the chapters line, with no QML complaints."""
import os, sys, tempfile
home = tempfile.mkdtemp(prefix="clips7ui-")
os.environ.update(HOME=home, XDG_CONFIG_HOME=home + "/config", XDG_CACHE_HOME=home + "/cache", XDG_DATA_HOME=home + "/data",
                  QT_QPA_PLATFORM="offscreen", HUGINN_SHOT_DELAY="600000")
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
sys.path.insert(0, SRC + "/apps"); sys.path.insert(0, SRC + "/shell")
from PySide6.QtCore import QTimer, QEventLoop, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
import huginn_app as ha

ok = bad = 0
said = []
def check(name, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
    else:
        bad += 1
        print("FAIL", name, extra, flush=True)

def heard(kind, ctx, msg):
    if "Clips.qml" in msg or "qml" in msg.lower() and ("Error" in msg or "TypeError" in msg or "ReferenceError" in msg):
        said.append(msg)
qInstallMessageHandler(heard)

def settle(ms=150):
    app = QGuiApplication.instance()
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()

def find(root, name):
    from PySide6.QtCore import QObject
    return root.findChild(QObject, name)

def kids(item):
    return [k for k in item.childItems() if k.property("modelData") is not None]

def checks(engine):
    root = engine.rootObjects()[0]
    b = engine.rootContext().contextProperty("Backend")
    talk = next(c for c in b._p["clips"] if c.get("kind") == "media" and next((m for m in b._p["media"] if m["id"] == c["media"]), {}).get("audio")
                and next((m for m in b._p["media"] if m["id"] == c["media"]), {}).get("kind") == "video")
    b._picked = [talk["id"]]; b.pickChanged.emit(); settle()
    tabs = [t[0] for t in find(root, "inspector").property("tabs").toVariant()] if hasattr(find(root, "inspector").property("tabs"), "toVariant") else [t[0] for t in find(root, "inspector").property("tabs")]
    check("footage with sound has a Words tab", "words" in tabs, tabs)
    root.setProperty("tab", "words"); settle()
    listen = find(root, "listenBtn")
    check("not listened to yet: the button to write it down", listen.property("visible") is True)
    b.listenWords(talk["id"]); settle(250)
    check("the words are shown", find(root, "wordFlow").property("visible") is True and len(kids(find(root, "wordFlow"))) == len(b.wordsOf(talk["id"])) > 10,
          (len(kids(find(root, "wordFlow"))), len(b.wordsOf(talk["id"]))))
    fillers = sum(1 for w in b.wordsOf(talk["id"]) if w["filler"])
    check("the ums are counted on the button", find(root, "cutFillersBtn").property("text") == f"Cut the Ums ({fillers})" and fillers >= 2, find(root, "cutFillersBtn").property("text"))
    first = kids(find(root, "wordFlow"))[0]
    check("a word is a word", first.property("modelData")["w"] == "So")
    before = sum(1 for c in b._p["clips"] if c.get("media") == talk["media"])
    length = b._get_clip()["length"]
    b.cutFillers(talk["id"]); settle(250)
    pieces = [c for c in b._p["clips"] if c.get("media") == talk["media"]]
    check("cut: the clip is in pieces, shorter", len(pieces) >= before + fillers - 1 and sum(c["out"] - c["in"] for c in pieces if c["track"] == talk["track"]) < length + 50, (len(pieces), before, fillers))
    b._picked = [next(c for c in b._p["clips"] if c.get("media") == talk["media"])["id"]]; b.pickChanged.emit(); settle()
    check("no ums left in any piece", all(not w["filler"] for c in pieces for w in b.wordsOf(c["id"])) and any(b.wordsOf(c["id"]) for c in pieces))
    # one colour
    root.setProperty("tab", "colour"); settle()
    box = find(root, "rangeBox")
    check("the one-colour switch is there", find(root, "rangeToggle") is not None and box.property("visible") is True)
    b.set(b._picked[0], "colour.range.on", True); settle()
    check("turned on, its controls show", sum(1 for k in box.childItems() if k.property("visible")) >= 6, sum(1 for k in box.childItems() if k.property("visible")))
    # smooth slow motion
    root.setProperty("tab", "speed"); settle()
    check("the smooth slow motion switch is there for footage", find(root, "smoothRow").property("visible") is True)
    # an adjustment layer
    aid = b.addAdjustment(-1); settle()
    tabs = find(root, "inspector").property("tabs")
    tabs = [t[0] for t in (tabs.toVariant() if hasattr(tabs, "toVariant") else tabs)]
    check("an adjustment layer has Colour and Effects", tabs == ["colour", "effects"], tabs)
    check("it shows as an adjustment on the timeline", b._face(b._c(aid))["mediaKind"] == "adjust" and b._face(b._c(aid))["name"] == "Adjustment")
    root.setProperty("tab", "effects"); settle()
    check("no steadying on an adjustment layer", find(root, "steadyKnob").property("visible") is False)
    # chapters
    b.seek(2.0); b.addMarker("One"); b.seek(9.0); b.addMarker("Two"); settle()
    root.setProperty("sheet", {"kind": "export", "preset": "h264"}); settle()
    check("the export card offers the chapters", find(root, "chaptersRow") is not None and find(root, "chaptersRow").property("visible") is True)
    check("no QML complaints", not said, said[:5])
    QGuiApplication.instance().quit()

class Engine(ha.QQmlApplicationEngine):
    def load(self, *a):
        super().load(*a)
        QTimer.singleShot(400, lambda: checks(self))

ha.QQmlApplicationEngine = Engine
sys.argv = ["huginn_app.py", "clips", "--demo", "--shot", os.path.join(home, "shot.png")]
try:
    ha.main()
except SystemExit:
    pass
print(f"{ok} passed, {bad} failed")
sys.exit(1 if bad or ok < 15 else 0)
