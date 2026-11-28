"""Clips and Tempo in glass panels, in their windows (the demos): the panels are the app's own glass, the dense part
(Clips' timeline, Tempo's arrangement) a deeper pane, the picture in Clips still on black; the tools that sat inside
the timeline and the arrangement now float as islands over them, at the window's edges, clear of each other and of
the panel under them, with what's inside the panel moved up into the room they left; Tempo's transport keeps clear of
the toolbar; and no QML complaints. Usage: glass_islands_ui.py /src [clips|tempo] (both when neither is named).
Shots go to $GLASS_SHOTS when set."""
import os, subprocess, sys, tempfile
SRC = sys.argv[1] if len(sys.argv) > 1 else "/src"
APP = sys.argv[2] if len(sys.argv) > 2 else ""
if not APP:                                    # each app in its own process, one after the other
    total_ok = total_bad = 0
    for app in ("clips", "tempo"):
        r = subprocess.run([sys.executable, __file__, SRC, app], capture_output=True, text=True, timeout=300)
        for line in r.stdout.splitlines():
            if line.startswith(("ok  ", "FAIL")):
                print(app + ": " + line)
                total_ok, total_bad = (total_ok + 1, total_bad) if line.startswith("ok") else (total_ok, total_bad + 1)
        if r.returncode not in (0, 1):
            total_bad += 1
            print(f"FAIL {app} ended badly", r.stderr[-400:])
    print(f"{total_ok} passed, {total_bad} failed")
    sys.exit(1 if total_bad or total_ok < 30 else 0)

home = tempfile.mkdtemp(prefix="glassui-")
os.environ.update(HOME=home, XDG_CONFIG_HOME=home + "/config", XDG_CACHE_HOME=home + "/cache", XDG_DATA_HOME=home + "/data",
                  QT_QPA_PLATFORM="offscreen", HUGINN_SHOT_DELAY="600000")
SHOTS = os.environ.get("GLASS_SHOTS", "")
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
    p = item.mapToItem(None, 0, 0)
    return (round(p.x()), round(p.y()), round(p.x() + item.width()), round(p.y() + item.height()))


def shown(item):
    return item is not None and item.isVisible() and item.width() > 0 and item.opacity() > 0


def apart(a, b):
    """Two boxes that don't overlap."""
    return a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def alpha(item):
    return item.property("color").alphaF()


def common(root, top, main_island):
    check("the name island is the app's glass", root.property("islandColor") == root.property("glass"))
    check("the top island is too", shown(main_island) and main_island.property("color") == root.property("glass"))
    check("glass is see-through, the deeper pane less so", 0 < root.property("glass").alphaF() < 0.6 and root.property("glass").alphaF() < root.property("deepGlass").alphaF() < 1)


def clips(root, backend):
    top = root.contentItem()
    W, H = round(root.width()), round(root.height())
    lib, insp, tl, tools, zoom = (find(top, n) for n in ("library", "inspector", "timeline", "timelineTools", "zoomIsland"))
    common(root, top, find(top, "mainIsland"))
    check("the library and the inspector are glass", alpha(lib) < 0.6 and alpha(insp) < 0.6)
    check("the timeline is the deeper pane", tl.property("color") == root.property("deepGlass"))
    screen = find(top, "viewer").childItems()[0]
    check("the picture stays on black", screen.property("color").name() == "#000000" and alpha(screen) == 1)
    islands = [find(top, n) for n in ("toolIsland", "editIsland", "trackIsland", "panelIsland")]
    check("four islands of tools, in a row", all(shown(i) for i in islands) and all(box(islands[k])[2] < box(islands[k + 1])[0] for k in range(3)), [box(i) for i in islands])
    t, z, l = box(tools), box(zoom), box(tl)
    check("…over the timeline, 12 apart", t[3] + 12 == l[1] and z[3] + 12 == l[1] and t[0] == 12, (t, z, l))
    check("the zoom island sits at the right edge, clear of the tools", z[2] == W - 12 and apart(t, z), (t, z, W))
    ruler = find(top, "lanes")
    check("the lanes moved up into the room the tools left", box(ruler)[1] == l[1] + 38, (box(ruler), l))
    check("the timeline still reaches the bottom", l[3] == H - 12)
    check("the tools are glass islands", all(i.property("color") == root.property("glass") for i in islands + [zoom]))
    shot(root, "clips-glass.png")
    # the tools still work
    blade = [k for k in islands[0].childItems()[-1].childItems() if k.property("text") == "Blade"][0]
    QMetaObject.invokeMethod(blade, "clicked")
    settle()
    check("Blade, from its island", root.property("tool") == "blade")
    QMetaObject.invokeMethod(find(top, "mixerBtn"), "clicked")
    settle()
    mix = find(top, "mixer")
    check("Mixer, from its island: the mixer is glass too", root.property("mixer") is True and shown(mix) and alpha(mix) < 0.6)
    QMetaObject.invokeMethod(find(top, "mixerBtn"), "clicked")
    root.setProperty("tool", "select")
    # narrow: the zoom island gives way rather than running into the tools
    root.setWidth(1100)
    settle(300)
    t, z = box(tools), box(zoom)
    check("at the narrowest window the zoom island still clears the tools", apart(t, z) and z[2] == 1100 - 12, (t, z))
    shot(root, "clips-glass-narrow.png")
    root.setWidth(W)
    settle()


def tempo(root, backend):
    top = root.contentItem()
    arrange, bench, tools, actions, transport = (find(top, n) for n in ("arrange", "bench", "arrangeTools", "arrangeActions", "transport"))
    check("a song is open", shown(arrange))
    check("the arrangement is the deeper pane, the bench glass", arrange.property("color") == root.property("deepGlass") and alpha(bench) < 0.6)
    check("the transport is the app's glass", transport.property("color") == root.property("glass"))
    a, t, c = box(arrange), box(tools), box(actions)
    check("the arrangement's tools float over it, 12 apart", t[3] + 12 == a[1] and c[3] + 12 == a[1] and t[0] == a[0], (t, c, a))
    check("…its actions and zoom at its right edge, clear of the tools", c[2] == a[2] and apart(t, c), (t, c, a))
    check("the ruler and lanes moved up into the room the tools left", box(find(top, "ruler"))[1] == a[1] + 30 and box(find(top, "lanes"))[1] == a[1] + 62, (box(find(top, "ruler")), box(find(top, "lanes")), a))
    zoom = find(top, "zoomIsland")
    check("the zoom island is the rightmost", box(zoom)[2] == a[2])
    region = find(top, "regionIsland")
    check("a picked region's actions show beside it", shown(region) and box(region)[2] < box(zoom)[0])
    title_end, tool_start = root.property("titleEnd"), root.property("toolStart")
    tr = box(transport)
    check("the transport keeps clear of the name island and the toolbar", tr[0] >= title_end + 11 and tr[2] <= tool_start - 11, (tr, title_end, tool_start))
    shot(root, "tempo-glass.png")
    # a section picked: its actions take the region's place
    sections = backend.property("sections") or []
    check("the demo song has sections", len(sections) > 0)
    root.setProperty("selSection", sections[0]["id"] if sections else "")
    settle()
    sec = find(top, "sectionActions")
    if sections:
        check("a picked section's actions show instead, clear of the tools", shown(sec) and not shown(region) and apart(box(sec), box(tools)), (box(sec), box(tools)))
        root.setProperty("selSection", "")
        settle()
    # the drawer: the arrangement narrows and the islands follow it
    root.setProperty("drawer", "loops")
    settle(500)
    a2, c2, d = box(arrange), box(actions), box(find(top, "drawer"))
    check("with the loops open, the zoom island follows the arrangement's edge", c2[2] == a2[2] and a2[2] < d[0], (c2, a2, d))
    check("…and the loops drawer is glass", alpha(find(top, "drawer")) < 0.6)
    shot(root, "tempo-glass-drawer.png")
    root.setProperty("drawer", "")
    settle(400)
    # the bench put away
    root.setProperty("benchOpen", False)
    settle(300)
    check("with the bench put away, the arrangement reaches the bottom", box(arrange)[3] == round(root.height()) - 12)
    root.setProperty("benchOpen", True)
    settle()


def checks(engine):
    root = engine.rootObjects()[0]
    settle(600)
    (clips if APP == "clips" else tempo)(root, engine.rootContext().contextProperty("Backend"))
    check("no QML complaints", not said, said[:5])
    QGuiApplication.instance().quit()


class Engine(ha.QQmlApplicationEngine):
    def load(self, *a):
        super().load(*a)
        QTimer.singleShot(1200, lambda: checks(self))


ha.QQmlApplicationEngine = Engine
sys.argv = ["huginn_app.py", APP, "--demo", "--dark", "--shot", os.path.join(home, "shot.png")]
try:
    ha.main()
except SystemExit:
    pass
print(f"{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
