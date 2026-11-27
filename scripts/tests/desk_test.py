import sys, os, tempfile, json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
KIT = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/huginn-os"
sys.path[:0] = [KIT + "/shell", KIT + "/apps"]
tmp = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tmp + "/c"; os.environ["HOME"] = tmp
from pathlib import Path
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
import huginn_stacks as st, huginn_shell as sh
ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("ok  ", name)
    else: fail += 1; print("FAIL", name, extra)
desk = Path(tmp) / "Desktop"; desk.mkdir(); (desk / "b.txt").write_text("x"); (desk / "A folder").mkdir(); (desk / ".hidden").write_text("x")
(Path(tmp) / "Downloads").mkdir(); (Path(tmp) / "elsewhere.txt").write_text("y")
st.desktop_folder = lambda: desk
s = st.Stacks(False)
check("the desktop's files, folders first, hidden ones left out", [i["name"] for i in s.desktop] == ["A folder", "b.txt"], [i["name"] for i in s.desktop])
s.placeOnDesktop("b.txt", 2, 3)
check("a place is kept", json.loads(st.DESK_PLACES.read_text()) == {"b.txt": [2, 3]})
s.placeOnDesktop("A folder", 2, 3)
check("dropped on a taken cell: the other gives way", s.desktopPlaces == {"A folder": [2, 3]}, s.desktopPlaces)
s.placeOnDesktop("b.txt", 0, 0); s.placeOnDesktop("A folder", 0, 0)
check("two placed ones swap", s.desktopPlaces == {"A folder": [0, 0], "b.txt": [2, 3]}, s.desktopPlaces)
s.dropOnDesktop(["file://" + str(Path(tmp) / "elsewhere.txt")], 1, 1)
check("a file dropped in moves to the Desktop folder, at that cell", (desk / "elsewhere.txt").exists() and not (Path(tmp) / "elsewhere.txt").exists() and s.desktopPlaces.get("elsewhere.txt") == [1, 1])
check("New Folder, then New Folder 2", s.newDesktopFolder() == "New Folder" and s.newDesktopFolder() == "New Folder 2" and (desk / "New Folder 2").is_dir())
(desk / "b.txt").unlink(); s.refresh()
check("a file that left the desktop frees its place", "b.txt" not in s.desktopPlaces and "b.txt" not in [i["name"] for i in s.desktop])
tokens, settings, theme = sh.make_theme(False, False, "", True)
for k, v, want in [("widgetPlaces", '{"clock":{"s":"DP-1","x":0.4,"y":0.3}}', True), ("widgetPlaces", '{"clock":{"s":"DP-1","x":1.4,"y":0.3}}', False),
                   ("widgetPlaces", '{"nope":{"s":"DP-1","x":0.4,"y":0.3}}', False), ("widgetPlaces", "not json", False), ("widgetPlaces", "", True),
                   ("quickTiles", "dnd,mute,shot", True), ("quickTiles", "dnd,dnd", False), ("quickTiles", "dnd,rocket", False), ("quickTiles", "", True),
                   ("barStyle", "islands", True), ("barStyle", "tabs", False), ("liveAt", "dock", True), ("liveAt", "left", False),
                   ("dockEverywhere", "true", True), ("desktopFiles", "maybe", False)]:
    check(f"{k}={v!r} {'taken' if want else 'refused'}", settings._allowed(k, v) == want)
settings.set("widgetPlaces", '{"clock":{"s":"DP-1","x":0.4,"y":0.3}}')
check("widget places as a map", settings.widgetPlaces == {"clock": {"s": "DP-1", "x": 0.4, "y": 0.3}} and settings.quickTiles == ["dnd", "night", "dark", "captions"])
# the desktop on the screen yet? (it starts behind the sign-in screen, on a terminal of its own)
import time
from PySide6.QtCore import QCoreApplication
act = Path(tmp) / "active"; act.write_text("tty1\n")
def spin(sec, until):
    end = time.monotonic() + sec
    while time.monotonic() < end and not until():
        QCoreApplication.processEvents(); time.sleep(0.01)
    return until()
o = sh.OnScreen("2", str(act), every=10); seen = []; o.changed.connect(lambda: seen.append(1))
check("on another terminal: not on the screen yet", not o.property("shown"))
spin(0.1, lambda: False)
check("…and still not while that's in front", not o.property("shown") and not seen)
act.write_text("tty2\n")
check("its own terminal comes to the front: on the screen, once", spin(1, lambda: o.property("shown")) and seen == [1])
check("no terminal (nested, previews): on the screen from the start", sh.OnScreen("").property("shown"))
check("can't tell: never waited for", sh.OnScreen("3", str(Path(tmp) / "nowhere")).property("shown"))
act.write_text("tty4\n")
check("already in front at the start", sh.OnScreen("4", str(act)).property("shown"))
print(f"\n{ok} passed, {fail} failed"); sys.exit(1 if fail else 0)
