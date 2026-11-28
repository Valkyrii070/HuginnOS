"""Tempo, pro pass five, in its window (the demo): drum notes and chords on a recording, chords of written notes,
the reference in the mastering pane, a film's Picture window following the playhead, with no QML complaints."""
import os, sys, tempfile, subprocess, time
home = tempfile.mkdtemp(prefix="tempo5ui-")
os.environ.update(HOME=home, XDG_CONFIG_HOME=home + "/config", XDG_CACHE_HOME=home + "/cache", XDG_DATA_HOME=home + "/data",
                  QT_QPA_PLATFORM="offscreen", HUGINN_SHOT_DELAY="600000")
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
sys.path.insert(0, SRC + "/apps"); sys.path.insert(0, SRC + "/shell")
from PySide6.QtCore import QTimer, QEventLoop, QObject, qInstallMessageHandler
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
    if "Tempo.qml" in msg or ("qml" in msg.lower() and ("Error" in msg or "TypeError" in msg or "ReferenceError" in msg)):
        said.append(msg)
qInstallMessageHandler(heard)

def settle(ms=150):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

def wait(cond, secs=60):
    end = time.time() + secs
    while time.time() < end and not cond():
        settle(50)
    return cond()

def find(root, name):
    return root.findChild(QObject, name)

def checks(engine):
    root = engine.rootObjects()[0]
    b = engine.rootContext().contextProperty("Backend")
    b._demo = False                                     # (the demo song, but the commands for real)
    audio = next((r for r in b._p["regions"] if r.get("kind") == "audio"), None)
    check("the demo song has a recording", audio is not None)
    b.selectRegion(audio["id"]); root.setProperty("bench", "region"); root.setProperty("benchOpen", True); settle()
    pane = find(root, "insidePane")
    check("a recording: what's in it", pane is not None and pane.property("visible") is True and find(root, "drumNotesBtn").property("visible") is True)
    midi = next(r for r in b._p["regions"] if r.get("kind") == "midi" and r.get("notes") and not b.region(r["id"])["kit"])
    b.selectRegion(midi["id"]); settle()
    b.findChords(midi["id"]); settle(200)
    chords = [c for c in (b._r(midi["id"]).get("chords") or []) if c[1]]
    check("written notes: their chords found", len(chords) >= 1, b._r(midi["id"]).get("chords"))
    flow = find(root, "chordFlow")
    check("…and shown as chips", flow.property("visible") is True and len([k for k in flow.childItems() if k.property("modelData") is not None]) == len(chords))
    check("Play the Chords is offered", find(root, "chordsToTrackBtn").property("visible") is True)
    # the film
    film = os.path.join(home, "boat.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", film], check=True)
    b.setVideo(film)
    check("a film: the Picture window shows", find(root, "pictureWindow").property("visible") is True)
    check("its pictures are read", wait(lambda: b.video.get("ready"), 60))
    b.seek(2.0); settle(200)
    src = find(root, "pictureFrame").property("source")
    check("the picture follows the playhead", str(src.toString() if hasattr(src, "toString") else src).endswith(".jpg"), src)
    root.setProperty("showPicture", False); settle()
    check("it can be hidden", find(root, "pictureWindow").property("visible") is False)
    root.setProperty("sheet", "export"); settle()
    check("Export offers the film with the music", find(root, "filmExport").property("visible") is True)
    root.setProperty("sheet", ""); settle()
    check("the reference box is in the mastering pane", find(root, "referenceBox") is not None and find(root, "referenceBtn") is not None)
    check("no QML complaints", not said, said[:5])
    QGuiApplication.instance().quit()

class Engine(ha.QQmlApplicationEngine):
    def load(self, *a):
        super().load(*a)
        QTimer.singleShot(500, lambda: checks(self))

ha.QQmlApplicationEngine = Engine
sys.argv = ["huginn_app.py", "tempo", "--demo", "--shot", os.path.join(home, "shot.png")]
try:
    ha.main()
except SystemExit:
    pass
print(f"{ok} passed, {bad} failed")
sys.exit(1 if bad or ok < 12 else 0)
