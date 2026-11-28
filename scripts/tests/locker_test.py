#!/usr/bin/env python3
"""Huginn's lock screen (shell/huginn_locker.py with GreeterView.qml): the sign-in screen's design, you alone, Sleep
only, your widgets under the same rule, a wait after five wrong passwords, and leaving with 0 after the wake.
PAM is a stand-in here (huginn_pam.check); signin_real_check.py checks the real one.

    locker_test.py <kit root> [folder for pictures]        (QT_QPA_PLATFORM=offscreen; not as root)
"""
import os
import sys
import tempfile
import time
from pathlib import Path

if os.geteuid() == 0:
    sys.exit("not as root")
KIT = Path(sys.argv[1]).resolve()
SHOTS = Path(sys.argv[2]) if len(sys.argv) > 2 else None
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
home = Path(tempfile.mkdtemp(prefix="locker-"))
os.environ["HOME"] = str(home)
sys.path.insert(0, str(KIT / "apps"))
sys.path.insert(0, str(KIT / "shell"))
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL", name, detail)


import huginn_signin_widgets as sw  # noqa: E402
sw.write_layout(home, [{"kind": "weather", "size": "small", "before": True}, {"kind": "today", "size": "wide", "before": False}])
sw.write_snapshot(home, {"weather": {"place": "Reykjavík", "temp": "4°", "words": "Clear", "high": "9°", "at": int(time.time())},
                         "today": {"events": [{"title": "Secret meeting", "date": time.strftime("%Y-%m-%d"), "time": "23:59"}]}})
import huginn_pam  # noqa: E402
tries = []


def fake_check(user, password, service="huginn-lock"):
    tries.append((user, password))
    time.sleep(0.2)
    return (password == "right", "" if password == "right" else "Wrong password.")


huginn_pam.check = fake_check
from PySide6.QtCore import QEventLoop, QMetaObject, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402, F401
import huginn_locker as hl  # noqa: E402

app = QGuiApplication(sys.argv)
host = hl.Locker(app)
exits = []
host._app = type("A", (), {"exit": staticmethod(lambda code=0: exits.append(code))})()
engine = QQmlEngine()
engine.rootContext().setContextProperty("Host", host)
problems = []
engine.warnings.connect(lambda ws: problems.extend(w.toString() for w in ws))
wrap = QQmlComponent(engine)
wrap.setData(b'import QtQuick\nimport QtQuick.Window\nWindow { width: 1440; height: 900; visible: true; color: "black"\n'
             b' GreeterView { objectName: "view"; anchors.fill: parent; main: true; focus: true } }\n', QUrl.fromLocalFile(str(KIT / "shell/qml/wrap.qml")))
win = wrap.create()
check("the lock screen loads", win is not None, [e.toString() for e in wrap.errors()])
view = win.findChild(object, "view")


def settle(ms=200, until=None):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        loop = QEventLoop()
        QTimer.singleShot(30, loop.quit)
        loop.exec()
        if until and until():
            return True
    return until() if until else True


def items(root):
    out = []
    for ch in root.childItems():
        out.append(ch)
        out.extend(items(ch))
    return out


def find(pred):
    return [i for i in items(win.contentItem()) if pred(i)]


def texts():
    return [i.property("text") for i in find(lambda i: i.metaObject().className().startswith("QQuickText") and i.isVisible() and isinstance(i.property("text"), str))]


def shot(name):
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        win.grabWindow().save(str(SHOTS / f"{name}.png"))


settle(600)
me = view.property("who")
check("you, and only you", len(view.property("people")) == 1 and me and me["name"] == os.environ.get("USER", me["name"]), view.property("people"))
check("it's the lock screen", view.property("locking") is True)
power = [i.property("mark") for i in find(lambda i: i.property("mark") in ("sleep", "restart", "off") and i.isVisible())]
check("Sleep, and nothing that would close your work", power == ["sleep"], power)
t = texts()
check("your widgets: the weather you allowed", "4° and clear" in t, t)
check("the private one shows its name and a lock, nothing of it", "Private while locked" in t and not any("Secret meeting" in x for x in t), t)
check("no session to choose", "Desktop" not in t and "Game Mode" not in t)
shot("lock-1")
pw = find(lambda i: i.objectName() == "password")[0]
for n in range(4):
    pw.setProperty("text", f"wrong{n}")
    QMetaObject.invokeMethod(view, "submit")
    settle(3000, lambda: view.property("phase") == "idle")
check("a wrong password says so", view.property("message") == "Wrong password.", view.property("message"))
pw.setProperty("text", "wrong4")
QMetaObject.invokeMethod(view, "submit")
settle(3000, lambda: view.property("phase") == "idle")
check("the fifth makes you wait", view.property("waitLeft") >= 28 and "Wait" in view.property("message"), (view.property("waitLeft"), view.property("message")))
n = len(tries)
pw.setProperty("text", "right")
QMetaObject.invokeMethod(view, "submit")
settle(400)
check("while waiting, nothing is checked", len(tries) == n)
host._misses.right(host._me["login"])
view.setProperty("waitLeft", 0)
QMetaObject.invokeMethod(view, "submit")
check("the right password: the wake", settle(3000, lambda: view.property("phase") == "wake"))
settle(500)
shot("lock-2-wake")
check("and then it leaves with 0, which unlocks", settle(4000, lambda: exits[:1] == [0]), exits)
check("PAM was asked as you", all(u == host._me["login"] for u, _ in tries))
check("nothing in the screen's own code complained", not [p for p in problems if "Greeter" in p or "Locker" in p], problems[:5])
print(f"{passed} passed, {failed} failed")
os._exit(1 if failed else 0)
