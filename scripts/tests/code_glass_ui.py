"""Code in glass panels (the demo): the rail of tools with the panel beside it, the panel put away by its own tool
while the rail stays, the code's pane moving to fill the room, the status line as islands along the bottom, the
terminal fitting between the code and those islands, zen hiding all of it, the glass itself (see-through panes, Run as
the one filled button, the name island in the same glass) and no QML complaints; then again with Reduce Transparency
on, where all of it is solid and the light is off. Shots go to $CODE_GLASS_SHOTS."""
import json, os, subprocess, sys, tempfile
home = tempfile.mkdtemp(prefix="codeglass-")
SOLID = len(sys.argv) > 2 and sys.argv[2] == "solid"
if SOLID:
    os.makedirs(home + "/config/huginn-shell")
    with open(home + "/config/huginn-shell/settings.json", "w") as f:
        json.dump({"reduceTransparency": "true"}, f)
os.environ.update(HOME=home, XDG_CONFIG_HOME=home + "/config", XDG_CACHE_HOME=home + "/cache", XDG_DATA_HOME=home + "/data",
                  QT_QPA_PLATFORM="offscreen", HUGINN_SHOT_DELAY="600000")
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
SHOTS = os.environ.get("CODE_GLASS_SHOTS", "")
sys.path.insert(0, SRC + "/apps"); sys.path.insert(0, SRC + "/shell")
from PySide6.QtCore import QTimer, QEventLoop, QMetaObject, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
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
    if "qml" in msg.lower() and ("Error" in msg or "TypeError" in msg or "ReferenceError" in msg or "Unable to assign" in msg or "binding loop" in msg.lower()):
        said.append(msg)
qInstallMessageHandler(heard)


def settle(ms=200):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def shot(root, name):
    if SHOTS:
        root.grabWindow().save(os.path.join(SHOTS, name))


def find(item, name):
    if item.objectName() == name:
        return item
    for k in item.childItems():
        hit = find(k, name)
        if hit is not None:
            return hit
    return None


def box(item):
    """Where an item is, in the window: (left, top, right, bottom)."""
    p = item.mapToItem(None, 0, 0)
    return (round(p.x()), round(p.y()), round(p.x() + item.width()), round(p.y() + item.height()))


def texts(item, out=None):
    out = [] if out is None else out
    t = item.property("text")
    if isinstance(t, str) and t:
        out.append(t)
    for k in item.childItems():
        texts(k, out)
    return out


def shown(item):
    return item is not None and item.isVisible() and item.width() > 0


def solid_checks(engine):
    root = engine.rootObjects()[0]
    top = root.contentItem()
    settle(400)
    slab, panel, rail = find(top, "slab"), find(top, "sidePanel"), find(top, "rail")
    check("Reduce Transparency: the code's pane is solid", slab.property("color").alphaF() == 1 and root.property("slabFill").alphaF() == 1)
    check("…the panels and the rail too", panel.property("color").alphaF() == 1 and rail.property("color").alphaF() == 1)
    check("…and there's no light behind them", root.property("glowPeak") == 0)
    root.setProperty("term", True)
    settle(300)
    check("…the terminal as well", find(top, "termBox").property("color").alphaF() == 1)
    shot(root, "code-glass-solid.png")
    check("no QML complaints (solid)", not said, said[:5])
    QGuiApplication.instance().quit()


def checks(engine):
    root = engine.rootObjects()[0]
    top = root.contentItem()
    W, H = round(root.width()), round(root.height())
    settle(400)
    rail, panel, slab, status = (find(top, n) for n in ("rail", "sidePanel", "slab", "statusBar"))
    check("the rail, the panel, the code's pane and the status line are there", all(x is not None for x in (rail, panel, slab, status)))
    tools = [find(top, "rail-" + t) for t in ("files", "search", "git", "problems", "tests", "outline")]
    check("six tools in the rail, one under the other", all(shown(t) for t in tools) and len({box(t)[0] for t in tools}) == 1
          and all(box(tools[i])[1] < box(tools[i + 1])[1] for i in range(5)), [box(t) for t in tools if t])
    check("the tool showing is lit (Files)", tools[0].property("on") is True and not any(t.property("on") for t in tools[1:]))
    r, p, s, st = box(rail), box(panel), box(slab), box(status)
    check("the panel sits beside the rail, the code beside the panel", p[0] == r[2] + 8 and s[0] == p[2] + 12, (r, p, s))
    check("the status islands run the window's width at the bottom", st[0] == 12 and st[2] == W - 12 and st[3] == H - 12, (st, W, H))
    check("…and the panels end above them", r[3] == st[1] - 12 and p[3] == st[1] - 12 and s[3] == st[1] - 12, (r, p, s, st))
    pills = {n: find(top, n) for n in ("branchPill", "problemsPill", "cursorPill", "wrapPill", "langPill")}
    check("pills for the branch, the problems, the cursor, wrapping and the language", all(shown(x) for x in pills.values()), [n for n, x in pills.items() if not shown(x)])
    check("the cursor's pill says where it is", any(t.startswith("Ln 1, Col 1") for t in texts(pills["cursorPill"])), texts(pills["cursorPill"]))
    check("the branch's pill names it", any(t.startswith("main") for t in texts(pills["branchPill"])), texts(pills["branchPill"]))
    check("left pills at the left, right pills at the right", box(pills["branchPill"])[0] == 12 and box(pills["langPill"])[2] == W - 12, (box(pills["branchPill"]), box(pills["langPill"])))
    # the glass
    check("the code's pane is see-through glass", root.property("slabFill").alphaF() < 1 and slab.property("color").alphaF() < 1)
    check("the panels are glass too", panel.property("color").alphaF() < 0.5 and rail.property("color").alphaF() < 0.5)
    check("what covers code (sticky lines) is the glass's look, solid", root.property("slab").alphaF() == 1)
    check("the light is turned up for Code", abs(root.property("glowBoost") - 1.3) < 1e-6)
    run = find(top, "runButton")
    check("Run is the one filled button", run.property("primary") is True and run.property("lit") is True)
    tabs = find(top, "tabsBar")
    check("the open files start where the code does", round(tabs.mapToItem(None, 0, 0).x()) == s[0], (box(tabs), s))
    tools_island = find(top, "toolsIsland")
    check("the top islands are the same glass", tools_island.property("color") == root.property("glass"))
    shot(root, "code-glass.png")

    # the panel put away by its own tool; the rail stays and the code takes the room
    QMetaObject.invokeMethod(tools[0], "clicked")
    settle()
    s2 = box(slab)
    check("a click on the lit tool puts the panel away", root.property("side") is False and not panel.isVisible())
    check("…the rail stays", shown(rail) and not any(t.property("on") for t in tools))
    check("…and the code moves up beside it", s2[0] == r[2] + 12 and s2[2] == W - 12, (s2, r))
    shot(root, "code-glass-nopanel.png")
    QMetaObject.invokeMethod(tools[2], "clicked")
    settle()
    check("another tool brings the panel back with its own page", root.property("side") is True and root.property("panel") == "git" and tools[2].property("on") is True)
    check("the code steps back over", box(slab)[0] == p[2] + 12)
    QMetaObject.invokeMethod(tools[0], "clicked")
    settle()

    # the terminal between the code and the status islands
    root.setProperty("term", True)
    settle(300)
    term = find(top, "termBox")
    t, s3, st = box(term), box(slab), box(status)
    check("the terminal comes up under the code", shown(term) and t[1] == s3[3] + 10 and t[0] == s3[0] and t[2] == s3[2], (t, s3))
    check("…and stops above the status islands", t[3] == st[1] - 12, (t, st))
    check("the terminal is glass as well", term.property("color").alphaF() < 1)
    shot(root, "code-glass-terminal.png")
    root.setProperty("term", False)
    settle()

    # zen: only the code
    QMetaObject.invokeMethod(root, "toggleZen")
    settle(300)
    z = box(slab)
    check("zen hides the rail, the panel and the status islands", not rail.isVisible() and not panel.isVisible() and not status.isVisible())
    check("…and the code fills the window", z[0] == 12 and z[2] == W - 12 and z[3] == H - 12, z)
    QMetaObject.invokeMethod(root, "toggleZen")
    settle(300)
    check("leaving zen brings it all back", shown(rail) and panel.isVisible() and status.isVisible() and box(slab) == s, (box(slab), s))

    check("no QML complaints", not said, said[:5])
    QGuiApplication.instance().quit()


class Engine(ha.QQmlApplicationEngine):
    def load(self, *a):
        super().load(*a)
        QTimer.singleShot(900, lambda: (solid_checks if SOLID else checks)(self))


ha.QQmlApplicationEngine = Engine
sys.argv = ["huginn_app.py", "code", "--demo", "--dark", "--shot", os.path.join(home, "shot.png")]
try:
    ha.main()
except SystemExit:
    pass
if SOLID:
    print(f"{ok} passed, {bad} failed")
    sys.exit(1 if bad else 0)
again = subprocess.run([sys.executable, __file__, SRC, "solid"], capture_output=True, text=True)
for line in again.stdout.splitlines():
    if line.startswith(("ok  ", "FAIL")):
        print(line)
        ok, bad = (ok + 1, bad) if line.startswith("ok") else (ok, bad + 1)
if again.returncode not in (0, 1):
    bad += 1
    print("FAIL the solid run ended badly", again.stderr[-400:])
print(f"{ok} passed, {bad} failed")
sys.exit(1 if bad or ok < 30 else 0)
