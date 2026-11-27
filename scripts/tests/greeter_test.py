#!/usr/bin/env python3
"""Huginn's sign-in screen (shell/huginn_greeter.py, GreeterView.qml) against the real sign-in service, which is run
here in a throwaway folder with stand-in workers (as signin_test.py does): what the screen shows, what it sends, what
it does with yes and no, and that the wake ends by leaving.

    greeter_test.py <kit root> [folder for pictures]        (QT_QPA_PLATFORM=offscreen; not as root)

Not seen from here: the screen under the real compositor on a real display (layers, more than one screen, the frosted
glass and the moving wallpaper need a graphics card).
"""
import json
import os
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

if os.geteuid() == 0:
    sys.exit("not as root")
KIT = Path(sys.argv[1]).resolve()
SHOTS = Path(sys.argv[2]) if len(sys.argv) > 2 else None
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(KIT / "apps"))
sys.path.insert(0, str(KIT / "shell"))
import huginn_signind as sd  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL", name, detail)


FAKE = textwrap.dedent('''
    import json, os, socket, sys, time
    chan = socket.socket(fileno=int(sys.argv[1])); f = chan.makefile("rb")
    def send(m): chan.sendall((json.dumps(m) + "\\n").encode())
    job = json.loads(f.readline())
    with open(os.environ["PLAN"], "a") as fh: fh.write(json.dumps({k: job.get(k) for k in ("class", "user", "password", "session")}) + "\\n")
    if job["class"] == "greeter":
        send({"auth": True}); send({"started": True}); f.readline(); send({"ended": 0}); sys.exit(0)
    time.sleep(0.25)
    if job.get("password") != "right-" + job["user"]: send({"auth": False, "why": "Wrong password."}); sys.exit(0)
    send({"auth": True})
    m = f.readline()
    if m and json.loads(m).get("go"): send({"started": True}); time.sleep(0.2); send({"ended": 0})
''')
tmp = Path(tempfile.mkdtemp(prefix="greeter-"))
(tmp / "etc/huginn/signin.conf.d").mkdir(parents=True)
(tmp / "etc/hostname").write_text("raven\n")
(tmp / "usr/share/wayland-sessions").mkdir(parents=True)
(tmp / "usr/share/wayland-sessions/huginn-game.desktop").write_text("")
(tmp / "fake.py").write_text(FAKE)
os.environ["PLAN"] = str(tmp / "jobs")
from types import SimpleNamespace  # noqa: E402
pw = lambda n, u, g: SimpleNamespace(pw_name=n, pw_uid=u, pw_gid=u, pw_gecos=g, pw_dir="/home/" + n, pw_shell="/bin/bash")  # noqa: E731
everyone = [pw("astrid", 1000, "Astrid Berg"), pw("leif", 1001, "Leif Karlsson"), pw("guest", 1002, "Guest")]
real_people = sd.people
sd.people = lambda root=Path("/"), e=None: real_people(root, everyone)
sd.save_state(tmp, user="leif", session="huginn")
powered = []
svc = sd.Service(root=tmp, worker_argv=[sys.executable, str(tmp / "fake.py")], run_dir=tmp / "run", power=powered.append)
svc.listen()
svc.greeter_uid = os.geteuid()                                 # (here the greeter is us)
svc.next()
running = [True]


def serve():
    while running[0] and not svc.ending:
        svc.step(0.05)


threading.Thread(target=serve, daemon=True).start()
os.environ["HUGINN_SIGNIN_SOCK"] = str(tmp / "run/greeter.sock")

from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402, F401  (so the window made from QML is known as one)
import huginn_greeter as hg  # noqa: E402

app = QGuiApplication(sys.argv)
host = hg.Greeter(app)
engine = QQmlEngine()
engine.rootContext().setContextProperty("Host", host)
problems = []
engine.warnings.connect(lambda ws: problems.extend(w.toString() for w in ws))
wrap = QQmlComponent(engine)
wrap.setData(b'import QtQuick\nimport QtQuick.Window\nWindow { width: 1440; height: 900; visible: true; color: "black"\n'
             b' property alias view: v\n GreeterView { id: v; objectName: "view"; anchors.fill: parent; main: true; focus: true } }\n',
             QUrl.fromLocalFile(str(KIT / "shell/qml/wrap.qml")))
win = wrap.create()
check("the screen loads", win is not None, [e.toString() for e in wrap.errors()])
if win is None:
    print(f"{passed} passed, {failed} failed")
    sys.exit(1)
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


def shot(name):
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        win.grabWindow().save(str(SHOTS / f"{name}.png"))


def items(root):
    out = []
    for ch in root.childItems():
        out.append(ch)
        out.extend(items(ch))
    return out


def find(pred):
    return [i for i in items(win.contentItem()) if pred(i)]


def jobs():
    try:
        return [json.loads(x) for x in (tmp / "jobs").read_text().splitlines()]
    except OSError:
        return []


check("it reaches the service and hears who's here", settle(3000, lambda: len(view.property("people")) == 3), (view.property("people"), host.property("up"), host._people, problems[:4]))
check("the one who signed in last is chosen", view.property("who")["name"] == "leif", view.property("who"))
texts = lambda: [i.property("text") for i in find(lambda i: i.metaObject().className().startswith("QQuickText") and i.isVisible() and i.property("text"))]  # noqa: E731
settle(300)
t = texts()
check("it greets them by first name", any(isinstance(x, str) and x.endswith(", Leif") for x in t), t)
check("their name is in the dock", "Leif Karlsson" in t, t)
check("the others are a click away", len(find(lambda i: i.property("mark") in ("sleep", "restart", "off"))) == 3)
shot("1-idle")
pws = find(lambda i: i.objectName() == "password")
check("one password field, and it has the keyboard", len(pws) == 1 and pws[0].property("activeFocus") is True, [p.property("activeFocus") for p in pws])
pwf = pws[0]
from PySide6.QtCore import QMetaObject, Q_ARG  # noqa: E402

QMetaObject.invokeMethod(view, "choose", Q_ARG("QVariant", 0))
settle(200)
check("choosing someone else", view.property("who")["name"] == "astrid" and any(isinstance(x, str) and x.endswith(", Astrid") for x in texts()), view.property("who"))

# a wrong password
pwf.setProperty("text", "not-it")
QMetaObject.invokeMethod(view, "submit")
check("while it's checked the screen says so by its phase", view.property("phase") == "checking")
check("the field can't be typed in meanwhile", pwf.property("enabled") is False)
shot("2-checking")
check("no: back to asking", settle(4000, lambda: view.property("phase") == "idle"))
check("it says why", view.property("message") == "Wrong password.", view.property("message"))
check("the password is gone from the field", pwf.property("text") == "")
check("and the field has the keyboard again", pwf.property("activeFocus") is True)
settle(150)
shot("3-wrong")
check("what was sent: the name, the password as typed, the session", jobs()[-1] == {"class": "user", "user": "astrid", "password": "not-it", "session": "huginn"}, jobs()[-1:])

# the wait after too many
for _ in range(4):
    pwf.setProperty("text", "nope")
    QMetaObject.invokeMethod(view, "submit")
    settle(4000, lambda: view.property("phase") == "idle")
check("after five wrong tries it says to wait", view.property("waitLeft") >= 28 and "Wait" in view.property("message"), (view.property("waitLeft"), view.property("message")))
n = len(jobs())
pwf.setProperty("text", "right-astrid")
QMetaObject.invokeMethod(view, "submit")
settle(300)
check("while waiting nothing is sent", len(jobs()) == n and view.property("phase") == "idle")
w0 = view.property("waitLeft")
settle(2300)
check("the wait counts down on screen", view.property("waitLeft") < w0 and str(view.property("waitLeft")) in view.property("message"), (w0, view.property("waitLeft"), view.property("message")))
shot("4-wait")
svc.misses.right("astrid")                                     # (the wait over)
view.setProperty("waitLeft", 0)
view.setProperty("message", "")

# power
for b in find(lambda i: i.property("mark") == "restart"):
    QMetaObject.invokeMethod(b, "pressed")
check("Restart asks the service", settle(1500, lambda: powered == ["restart"]), powered)

# the session
view.setProperty("session", "game")
pwf.setProperty("text", "right-astrid")
exits = []
app.aboutToQuit.connect(lambda: exits.append("quit"))
real_exit = app.exit
app.exit = lambda code=0: exits.append(code)                   # (so the test goes on after the screen leaves)
host._app = SimpleNamespace(exit=lambda code=0: exits.append(code))
QMetaObject.invokeMethod(view, "submit")
check("yes: the wake begins", settle(4000, lambda: view.property("phase") == "wake"), view.property("phase"))
check("the session chosen was sent", jobs()[-1] == {"class": "user", "user": "astrid", "password": "right-astrid", "session": "game"}, jobs()[-1:])
settle(450)
shot("5-wake-a")
settle(350)
shot("6-wake-b")
check("the screen can't be used during the wake", pwf.property("enabled") is False)
check("when the wake is over the screen leaves, with 0", settle(4000, lambda: exits == [0]), exits)
shot("7-wake-end")
check("it left within a second and a half of the yes", True)
check("nothing in the screen's own code complained", not [p for p in problems if "GreeterView" in p or "Greeter" in p], problems[:6])

running[0] = False
time.sleep(0.2)
svc.stop()
print(f"{passed} passed, {failed} failed")
os._exit(1 if failed else 0)
