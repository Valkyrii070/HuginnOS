"""The installer's dock path: its steps and what each keeps (Ready?, Extras with media formats from Ubuntu or built
here, Apps, From Windows, Safety with a recovery key, help seeing and typing), the plan they make, what the engine
writes for the first start, Windows surveyed read-only, the first-start runner (dry, and against a fake root), and the
window itself (demo): the dock's islands, going round them, installing.
Usage: installer_dock_test.py <kit root>   (never as root)"""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0:
    sys.exit("not as root")
home = tempfile.mkdtemp(prefix="instdock-")
os.environ.update(HOME=home, XDG_CONFIG_HOME=home + "/config", XDG_CACHE_HOME=home + "/cache", XDG_DATA_HOME=home + "/data",
                  QT_QPA_PLATFORM="offscreen", HUGINN_SHOT_DELAY="600000")
sys.path[:0] = [str(KIT / "apps"), str(KIT / "shell")]
import huginn_install_engine as eng
import huginn_first_start as fs

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
    else:
        bad += 1
        print("FAIL", name, extra, flush=True)

# ================================================================================ the engine's new parts
key = eng.recovery_key()
check("a recovery key: eight words from the list", len(key.split("-")) == 8 and all(w in eng.RECOVERY_WORDS for w in key.split("-")) and key != eng.recovery_key())
plan = {"mode": "erase", "disk": "/dev/sdb", "user": {"name": "astrid", "password": "huginn-test-only"}, "encrypt": True, "passphrase": "huginn-test-only",
        "recoveryKey": key, "extras": {"codecs": "build", "msfonts": True, "scripts": True, "printers": True, "nvidia": True},
        "apps": {"gamedev": True, "flathub": True, "fromWindows": ["discord", "obs", "nonsense"]},
        "windows": {"part": "/dev/nvme0n1p3", "user": "Astrid", "folders": ["documents", "pictures", "bogus"], "how": "copy"}}
check("a plan with the new parts is a good plan", eng.check_plan(plan) == [], eng.check_plan(plan))
check("a made-up recovery key isn't taken", eng.check_plan(dict(plan, recoveryKey="1234")) != [])
check("a way to add media formats that isn't one isn't taken", eng.check_plan(dict(plan, extras={"codecs": "steal"})) != [])
check("bringing things from a Windows that's being erased is refused",
      eng.check_plan(dict(plan, disk="/dev/nvme0n1")) != [] and eng.check_plan(dict(plan, mode="shrink", disk="/dev/nvme0n1", shrinkPart="/dev/nvme0n1p3", keepBytes=10)) == [])
t = eng.first_start_tasks(plan, "ABCD-1234")
check("first start: Microsoft's fonts with their licence, fonts for every script, printers, game tools",
      "ttf-mscorefonts-installer" in t["packages"] and eng.MSFONTS_EULA in t["debconf"] and "fonts-noto-cjk" in t["packages"]
      and "printer-driver-all" in t["packages"] and "git-lfs" in t["packages"], t["packages"])
check("…media formats to build (not downloaded)", t["build"] == ["codecs"] and not set(eng.CODEC_PACKAGES) & set(t["packages"]))
check("…apps from Flathub: Godot and the Windows apps that are real", t["flatpaks"] == ["org.godotengine.Godot", "com.discordapp.Discord", "com.obsproject.Studio"], t["flatpaks"])
check("…NVIDIA's driver, and Windows by its UUID with only real folders", t["drivers"] and t["windows"] == {"uuid": "ABCD-1234", "user": "Astrid", "how": "copy", "folders": ["documents", "pictures"], "bookmarks": False})
t2 = eng.first_start_tasks({"user": {"name": "a"}, "extras": {"codecs": "download"}})
check("downloaded formats are Ubuntu's packages", set(eng.CODEC_PACKAGES) <= set(t2["packages"]) and not t2["build"] and t2["windows"] is None)
check("nothing chosen, nothing to do", eng.first_start_tasks({"user": {"name": "a"}}) == {"owner": "a", "packages": [], "debconf": [], "flatpaks": [], "flathub": True,
                                                                                       "build": [], "drivers": False, "windows": None})

# Windows, surveyed: a made-up C: drive
c = Path(home) / "c"
for rel, size in (("Users/Astrid/NTUSER.DAT", 10), ("Users/Astrid/Documents/letter.docx", 1000), ("Users/Astrid/Documents/Taxes/2025.pdf", 2000),
                  ("Users/Astrid/Pictures/fjord.jpg", 5000), ("Users/Public/Documents/shared.txt", 5), ("Users/Default/NTUSER.DAT", 5),
                  ("Users/Erik/NTUSER.DAT", 5), ("Users/Erik/Music/song.mp3", 300),
                  ("Program Files/obs-studio/bin/obs64.exe", 1), ("Program Files/VideoLAN/VLC/vlc.exe", 1),
                  ("Users/Astrid/AppData/Local/Discord/Update.exe", 1),
                  ("ProgramData/Microsoft/Windows/Start Menu/Programs/Spotify.lnk", 1), ("ProgramData/Microsoft/Windows/Start Menu/Programs/Notepad.lnk", 1)):
    f = c / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x" * size)
(c / "hiberfil.sys").write_bytes(b"HIBR" + b"\0" * 60)
sv = eng.windows_survey(c)
check("its people (not Public or Default)", [u["name"] for u in sv["users"]] == ["Astrid", "Erik"], sv["users"])
a = sv["users"][0]["folders"]
check("their folders: files and bytes, sub-folders counted", a["documents"] == {"files": 2, "bytes": 3000} and a["pictures"]["files"] == 1 and a["music"]["files"] == 0)
check("apps with Linux versions, from Program Files, AppData and the Start menu", sv["apps"] == ["discord", "obs", "spotify", "vlc"], sv["apps"])
check("Fast Startup is seen from the hibernation file", sv["fastStartup"] is True)
(c / "hiberfil.sys").write_bytes(b"\0" * 64)
check("…and not when Windows shut down fully", eng.windows_survey(c)["fastStartup"] is False)
check("an empty partition: no one", eng.windows_survey(Path(home) / "nowhere")["users"] == [])

# ================================================================================ the first start
steps = fs.plan_steps(t)
keys = [k for k, _w, _c in steps]
check("the first start's work, in order", keys[:2] == ["update", "debconf"] and "apt-fonts" in keys and "apt-printers" in keys and "apt-tools" in keys
      and "drivers" in keys and "build-codecs" in keys and keys.index("flathub") < keys.index("flatpak-org.godotengine.Godot") and keys[-1] == "windows", keys)
build = next(c_ for k, _w, c_ in steps if k == "build-codecs")
check("building the formats: their build tools, FFmpeg's source, every format turned on", "libfdk-aac-dev" in build[0] and fs.FFMPEG in build[2]
      and "--enable-nonfree" in build[4][2] and "--enable-libfdk-aac" in build[4][2])
dry = subprocess.run([sys.executable, str(KIT / "apps/huginn_first_start.py"), "--dry-run", "/dev/stdin"], input=json.dumps(t), capture_output=True, text=True)
check("a dry run says what it would do and does nothing", dry.returncode == 0 and "Bringing your things from Windows" in dry.stdout and "apt-get install" in dry.stdout, dry.stderr[-300:])
check("no internet needed only to bring things from Windows", not fs.needs_internet(fs.plan_steps({"windows": {"uuid": "x", "user": "A", "folders": [], "how": "copy"}}))
      and fs.needs_internet(steps))
check("Flathub turned off when asked", ["flatpak", "remote-modify", "--disable", "flathub"] in [c_ for k, _w, cs in fs.plan_steps({"flathub": False}) for c_ in cs])
# bringing the files over, against a made-up root: the "mounted" Windows is the fake C: drive
root = Path(home) / "root"
(root / "home/astrid/Documents").mkdir(parents=True)
(root / "home/astrid/Documents/letter.docx").write_text("mine already")
(root / "run").mkdir(parents=True)
(root / "run/huginn-windows").symlink_to(c)
said = fs.windows_step("copy", {"uuid": "x", "user": "Astrid", "folders": ["documents", "pictures"]}, "astrid", root=root, mount=False)
check("copied over: the folders asked for, sub-folders too", (root / "home/astrid/Documents/Taxes/2025.pdf").stat().st_size == 2000 and (root / "home/astrid/Pictures/fjord.jpg").exists(), said)
check("…nothing already there overwritten", (root / "home/astrid/Documents/letter.docx").read_text() == "mine already" and said == "2 files brought over from Windows", said)
check("…and nothing that wasn't asked for", not (root / "home/astrid/Music").exists())
(root / "etc").mkdir()
(root / "etc/fstab").write_text("UUID=r / btrfs defaults 0 0\n")
fs.windows_step("link", {"uuid": "W-1", "user": "Astrid"}, "astrid", root=root, mount=False)
fstab = (root / "etc/fstab").read_text()
check("used where they are: Windows mounted read-only by itself, a Windows folder in the home", "UUID=W-1 /mnt/windows ntfs3 ro,nofail" in fstab
      and os.readlink(root / "home/astrid/Windows") == "/mnt/windows/Users/Astrid")
fs.windows_step("link", {"uuid": "W-1", "user": "Astrid"}, "astrid", root=root, mount=False)
check("…once, however often it runs", (root / "etc/fstab").read_text().count("UUID=W-1") == 1)
# the runner: offline waits; each task once; a failing one gives up after three
fs.STATE = Path(home) / "state"; fs.STATE.mkdir()
fs.TASKS, fs.STATUS = fs.STATE / "first-start.json", fs.STATE / "first-start.status.json"
fs.TASKS.write_text(json.dumps(t2))
real_online = fs.online
fs.online = lambda: False
check("offline: it waits (and says so), to be started again", fs.run_all(t2, runner=None) == fs.OFFLINE and fs.read_status()["now"] == "Waiting for the internet")
fs.online = lambda: True
ran = []
class R:
    def __init__(self, code): self.returncode, self.stderr, self.stdout = code, "E: broken", ""
def runner(cmd, **kw):
    ran.append(cmd)
    return R(1 if "libavcodec-extra" in cmd else 0)
code = fs.run_all(t2, runner)
st = fs.read_status()
check("online: what works is done, what fails is said", code == fs.OFFLINE and "update" in st["done"] and st["failed"].get("apt-formats") == 1
      and any("broken" in n for n in st["notes"]), st)
codes = [fs.run_all(t2, runner) for _ in range(2)]
check("a task that fails three times is left, and the rest finishes", fs.read_status()["failed"]["apt-formats"] == 3 and codes == [fs.OFFLINE, 0]
      and not fs.TASKS.exists() and fs.TASKS.with_suffix(".done").exists(), codes)
check("done tasks aren't done again", sum(1 for c_ in ran if "update" in c_) == 1, [c_ for c_ in ran if "update" in c_])
fs.online = real_online
check("the first-start service: after the network, again and again while offline", "After=network-online.target" in (KIT / "config/overlay/etc/systemd/system/huginn-first-start.service").read_text()
      and "RestartSec=10min" in (KIT / "config/overlay/etc/systemd/system/huginn-first-start.service").read_text() and os.access(KIT / "config/overlay/usr/libexec/huginn-first-start", os.X_OK))

# ================================================================================ the window
from PySide6.QtCore import QTimer, QEventLoop, QObject, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
import huginn_app as ha
heard = []
qInstallMessageHandler(lambda kind, ctx, msg: heard.append(msg) if ("Installer.qml" in msg or "TypeError" in msg or "ReferenceError" in msg) else None)

def settle(ms=150):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

def wait(cond, secs=20):
    end = time.time() + secs
    while time.time() < end and not cond():
        settle(50)
    return cond()

def items(item):
    for k in item.childItems():
        yield k
        yield from items(k)

def checks(engine):
    try:
        run_checks(engine)
    finally:
        QGuiApplication.instance().quit()

def run_checks(engine):
    root = engine.rootObjects()[0]
    b = engine.rootContext().contextProperty("Backend")
    def find(n):
        got = root.findChild(QObject, n)
        return got if got is not None else next((k for k in items(root.contentItem()) if k.objectName() == n), None)
    ids = [s["id"] for s in b.steps]
    check("ten steps and the orb", ids == ["welcome", "keyboard", "check", "disk", "extras", "apps", "windows", "you", "time", "safety", "ready"])
    check("an island for each in the dock", all(find("island-" + i) is not None for i in ids[:-1]) and find("orb") is not None)
    check("the language is the one raised", find("island-welcome").property("here") is True)
    b.next(); b.next(); settle()
    check("Ready?: looked over, Windows surveyed meanwhile", b.step == 2 and len(b.check) >= 4 and wait(lambda: b.windows["state"] == "ok"))
    check("…the dock keeps each answer", next(a for a in b.answers if a["id"] == "keyboard")["answer"] == "US" and next(a for a in b.answers if a["id"] == "welcome")["done"])
    b.setMode("shrink"); settle(800)
    b.goTo(ids.index("windows")); settle()
    check("From Windows is there when Windows stays (beside it)", b.step == ids.index("windows") and b.windows["here"] and b.windows["user"] == "Astrid")
    b.setMode("erase"); settle()
    check("…and set aside when Windows is erased", next(a for a in b.answers if a["id"] == "windows")["off"] is True)
    b.goTo(ids.index("disk")); b.setMode("shrink"); settle(800)
    b.next(); settle()
    b.setExtra("codecs", "build"); b.setExtra("scripts", True); b.setExtra("codecs", "steal")
    check("Extras: formats to be built, fonts for every script", b.extras["codecs"] == "build" and b.extras["scripts"] and find("codecs-build").property("on"))
    b.next(); settle()
    b.setApp("gamedev", True); b.setApp("windowsApp", "obs"); b.setApp("windowsApp", "nonsense")
    check("Apps: game tools, and an app found in Windows", b.apps["gamedev"] and [a["key"] for a in b.apps["windowsApps"] if a["on"]] == ["obs"]
          and find("windowsApps").property("visible"))
    b.next(); settle()
    b.setBring("folder", "videos"); b.setBring("how", "link"); b.setBring("how", "nowhere")
    check("From Windows: a folder left out, used where they are", not next(f for f in b.windows["folders"] if f["key"] == "videos")["on"] and b.windows["how"] == "link")
    b.next(); settle()
    for k, v in (("realName", "Astrid Berg"), ("password", "huginn-test-only"), ("again", "huginn-test-only")):
        b.setYou(k, v)
    b.next(); b.next(); settle()
    check("Safety", b.steps[b.step]["id"] == "safety")
    b.setEncrypt(True, "short")
    check("an encryption password too short is stopped", "8 characters" in b.problem)
    b.setEncrypt(True, "huginn-test-only")
    words = list(b.safety["recoveryWords"])
    check("encrypted: a recovery key to write down, on screen", len(words) == 8 and find("recoveryKey").property("visible"))
    b.newRecoveryKey()
    check("…new words when asked", list(b.safety["recoveryWords"]) != words)
    b.setSafety("firewall", False)
    b.setAccess("bigger", True); b.setAccess("motion", True); b.setAccess("nope", True)
    check("help seeing and typing: the window grows", abs(find("card").property("scale") - 1.16) < 1e-6)
    b.next(); settle()
    p = b._plan()
    check("the plan: what each step chose", p["extras"]["codecs"] == "build" and p["apps"]["fromWindows"] == ["obs"] and p["windows"]["how"] == "link"
          and "videos" not in p["windows"]["folders"] and p["recoveryKey"] == "-".join(b.safety["recoveryWords"]) and p["safety"]["firewall"] is False
          and p["access"] == {"reader": False, "bigger": True, "motion": True, "osk": False} and eng.check_plan(p) == [], eng.check_plan(p))
    rows = {r["label"]: r["value"] for r in b.summary}
    check("the last look says it all", "built on this computer" in rows.get("Extras", "") and "OBS Studio" in rows.get("Apps", "") and "read-only" in rows.get("From Windows", "")
          and "recovery key" in rows.get("Encryption", ""), rows)
    check("…and what comes after the first start", "come after the first start" in b.later)
    check("the orb is lit on the last look", b.steps[b.step]["id"] == "ready" and find("orb").property("here"))
    b.install()
    check("installing: the steps of it, done and to do", b.state == "installing" and wait(lambda: any(x["state"] == "done" for x in b.phases), 10) and find("runCard").property("visible"))
    check("…to the end", wait(lambda: b.state == "done", 30) and all(x["state"] == "done" for x in b.phases))
    check("no QML complaints", not heard, heard[:4])

class Engine(ha.QQmlApplicationEngine):
    def load(self, *a):
        super().load(*a)
        QTimer.singleShot(600, lambda: checks(self))

ha.QQmlApplicationEngine = Engine
sys.argv = ["huginn_app.py", "installer", "--demo", "--shot", os.path.join(home, "shot.png")]
try:
    ha.main()
except SystemExit:
    pass
print(f"{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
