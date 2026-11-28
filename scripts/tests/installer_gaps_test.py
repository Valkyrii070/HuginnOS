"""The installer's two gaps closed: bookmarks brought over from Windows' browsers (Edge, Chrome, Firefox…) into
Huginn's Favorites, read-only; and the disk opened by the TPM and a PIN (systemd-cryptenroll and dracut from the
medium's pool/tpm). No chip here: what the engine runs is checked against a fake one.
Usage: installer_gaps_test.py <kit root>   (never as root)"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if os.geteuid() == 0:
    sys.exit("not as root")
home = Path(tempfile.mkdtemp(prefix="instgaps-"))
os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "config"), XDG_CACHE_HOME=str(home / "cache"), QT_QPA_PLATFORM="offscreen")
sys.path[:0] = [str(KIT / "apps")]
import huginn_first_start as fs  # noqa: E402
import huginn_install_engine as eng  # noqa: E402

ok = bad = 0


def check(name, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
        print("ok  ", name)
    else:
        bad += 1
        print("FAIL", name, extra, flush=True)


# ================================================================================ bookmarks from Windows
c = home / "c"
person = c / "Users/Astrid"
(person).mkdir(parents=True)
(person / "NTUSER.DAT").write_text("x")
edge = person / "AppData/Local/Microsoft/Edge/User Data/Default"
edge.mkdir(parents=True)
(edge / "Bookmarks").write_text(json.dumps({"roots": {
    "bookmark_bar": {"type": "folder", "children": [{"type": "url", "name": "Fjord news", "url": "https://fjord.example/"},
                                                    {"type": "folder", "name": "Work", "children": [{"type": "url", "name": "Tracker", "url": "https://work.example/t"}]},
                                                    {"type": "url", "name": "a script", "url": "javascript:alert(1)"}]},
    "other": {"type": "folder", "children": [{"type": "url", "name": "Recipes", "url": "https://food.example/"}]}}}))
chrome = person / "AppData/Local/Google/Chrome/User Data/Profile 1"
chrome.mkdir(parents=True)
(chrome / "Bookmarks").write_text(json.dumps({"roots": {"bookmark_bar": {"type": "folder", "children": [
    {"type": "url", "name": "Fjord again", "url": "https://fjord.example/"}, {"type": "url", "name": "", "url": "https://untitled.example/"}]}}}))
ff = person / "AppData/Roaming/Mozilla/Firefox/Profiles/abcd.default-release"
ff.mkdir(parents=True)
db = sqlite3.connect(ff / "places.sqlite")
db.executescript("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT); CREATE TABLE moz_bookmarks (id INTEGER PRIMARY KEY, type INT, fk INT, parent INT, position INT, title TEXT);"
                 "INSERT INTO moz_places VALUES (1, 'https://maps.example/'), (2, 'place:sort=8');"
                 "INSERT INTO moz_bookmarks VALUES (10, 2, NULL, 1, 0, 'toolbar'), (11, 1, 1, 10, 0, 'Maps'), (12, 1, 2, 10, 1, 'Recent');")
db.commit()
db.close()
(person / "AppData/Local/Vivaldi/User Data/Default").mkdir(parents=True)
(person / "AppData/Local/Vivaldi/User Data/Default/Bookmarks").write_text("{not json")

marks = fs.windows_bookmarks(person)
urls = [m["url"] for m in marks]
check("Edge, Chrome and Firefox read: web pages only, each once, the bar first",
      urls == ["https://fjord.example/", "https://work.example/t", "https://food.example/", "https://untitled.example/", "https://maps.example/"], urls)
check("…named for their browser, an untitled one by its address", marks[0]["browser"] == "Edge" and marks[3] == {"browser": "Chrome", "title": "https://untitled.example/", "url": "https://untitled.example/"}
      and marks[4]["browser"] == "Firefox")
check("…a broken bookmarks file is passed over", len(marks) == 5)
check("…Firefox's file read where it is, unchanged", (ff / "places.sqlite").stat().st_size > 0 and not (ff / "places.sqlite-wal").exists())
check("nothing found in a person without browsers", fs.windows_bookmarks(c / "Users/Nobody") == [])

survey = eng.windows_survey(c, budget=5)
astrid = next(u for u in survey["users"] if u["name"] == "Astrid")
check("the survey counts them, and says whose browsers", astrid["bookmarks"] == {"count": 5, "browsers": ["Edge", "Chrome", "Firefox"]}, astrid.get("bookmarks"))

# into Huginn's Favorites (its data file), after what's there
dest = home / "h1"
dest.mkdir()
data = dest / fs.BROWSER_DATA
said = fs.bring_bookmarks(person, dest, "", running=lambda: False)
got = json.loads(data.read_text())
check("into Huginn's Favorites when it hasn't been opened yet", [b["url"] for b in got["bookmarks"]] == urls and "5 bookmarks" in said, said)
data.write_text(json.dumps({"bookmarks": [{"title": "Mine", "url": "https://mine.example/"}, {"title": "Fjord", "url": "https://fjord.example/"}],
                            "history": [{"url": "https://mine.example/", "title": "Mine", "time": 1.0}], "stats": {"blocked": 7}}))
said = fs.bring_bookmarks(person, dest, "", running=lambda: False)
got = json.loads(data.read_text())
check("…after the ones already there, none twice, the rest of its data kept",
      [b["url"] for b in got["bookmarks"]][:2] == ["https://mine.example/", "https://fjord.example/"] and len(got["bookmarks"]) == 6
      and got["history"][0]["title"] == "Mine" and got["stats"] == {"blocked": 7} and "4 bookmarks" in said, said)
dest2 = home / "h2"
dest2.mkdir()
said = fs.bring_bookmarks(person, dest2, "", running=lambda: True)
html = (dest2 / "Bookmarks from Windows.html").read_text()
check("with Huginn open: a bookmarks file in the home instead, to import", not (dest2 / fs.BROWSER_DATA).exists() and "NETSCAPE-Bookmark-file-1" in html
      and html.count("<DT><A HREF=") == 5 and "Import" in said, said)
check("…titles made safe", "<script" not in fs.bookmarks_html([{"title": "<script>x</script>", "url": "https://a.example/?q=\"x\""}]))
(home / "h3").mkdir()
check("no bookmarks: says so, writes nothing", fs.bring_bookmarks(c / "Users/Nobody", home / "h3", "", running=lambda: False).startswith("No bookmarks")
      and not any((home / "h3").iterdir()))

# the first start's Windows step brings them (copy, or with Windows used where it is)
root = home / "root"
(root / "home/astrid").mkdir(parents=True)
(root / "run").mkdir()
(root / "run/huginn-windows").symlink_to(c)
said = fs.windows_step("copy", {"uuid": "x", "user": "Astrid", "folders": [], "bookmarks": True}, "astrid", root=root, mount=False)
check("first start, copying: bookmarks alone when no folders were asked for", (root / "home/astrid" / fs.BROWSER_DATA).exists() and said.startswith("5 bookmarks"), said)
(root / "etc").mkdir()
(root / "etc/fstab").write_text("")
(root / "mnt").mkdir()
(root / "mnt/windows").symlink_to(c)
(root / "home/astrid" / fs.BROWSER_DATA).unlink()
said = fs.windows_step("link", {"uuid": "W-1", "user": "Astrid", "bookmarks": True}, "astrid", root=root, mount=False)
check("…and used where it is: read from the mounted Windows", (root / "home/astrid" / fs.BROWSER_DATA).exists() and "bookmarks" in said, said)
t = eng.first_start_tasks({"user": {"name": "astrid"}, "windows": {"user": "Astrid", "folders": [], "how": "copy", "bookmarks": True}}, "W-1")
check("the engine asks the first start for them, even with no folders", t["windows"] and t["windows"]["bookmarks"] is True)
check("…and not when they weren't chosen", eng.first_start_tasks({"user": {"name": "a"}, "windows": {"user": "A", "folders": [], "how": "copy"}}, "W")["windows"] is None)

# ================================================================================ TPM and PIN
plan = {"mode": "erase", "disk": "/dev/sdb", "user": {"name": "astrid", "password": "huginn-test-only"}, "encrypt": True, "passphrase": "huginn-test-only",
        "recoveryKey": eng.recovery_key(), "tpmPin": "2468"}
check("a plan with a PIN is a good plan", eng.check_plan(plan) == [], eng.check_plan(plan))
check("…a PIN without encrypting isn't", eng.check_plan(dict(plan, encrypt=False, passphrase="")) != [])
check("…nor a PIN too short", eng.check_plan(dict(plan, tpmPin="12")) != [])
check("crypttab: the chip first, the password and recovery key still", "tpm2-device=auto" in eng.crypttab("U-1", tpm=True) and "tpm2" not in eng.crypttab("U-1"))
sysfs = home / "sys"
(sysfs / "class/tpm/tpm0").mkdir(parents=True)
(sysfs / "class/tpm/tpm0/tpm_version_major").write_text("1\n")
check("a TPM 1.2 doesn't count", not eng.tpm2_here(sysfs) and not eng.tpm2_here(home / "nosys"))
(sysfs / "class/tpm/tpm0/tpm_version_major").write_text("2\n")
check("a TPM 2.0 does", eng.tpm2_here(sysfs))

# the engine's part, against a fake target and medium (what it runs is recorded, nothing is run)
inst = eng.Engine.__new__(eng.Engine)
inst.p, inst.t, inst.medium = plan, home / "target", home / "medium"
inst.dev = {"root": "/dev/sdb3"}
(inst.t / "tmp").mkdir(parents=True)
(inst.t / "etc").mkdir()
ran, logs = [], []
inst.log = logs.append
inst.uuid = lambda dev: "LUKS-UUID"


def fake_run(cmd, stdin=None, chroot=False, check=True, timeout=0, secrets=None):
    ran.append((cmd, secrets))
    return ""


inst.run = fake_run
real = eng.tpm2_here
eng.tpm2_here = lambda sysfs=None: True
check("no packages on the medium: the password alone", inst.tpm_unlock() is False and not ran)
(inst.medium / "pool/tpm").mkdir(parents=True)
for n in ("dracut_110-1_amd64.deb", "systemd-cryptsetup_259_amd64.deb"):
    (inst.medium / "pool/tpm" / n).write_text("deb")
eng.tpm2_here = lambda sysfs=None: False
check("no chip: the password alone", inst.tpm_unlock() is False and not ran)
eng.tpm2_here = lambda sysfs=None: True
done = inst.tpm_unlock()
cmds = [r[0] for r in ran]
check("with both: dracut and systemd-cryptsetup put in from the medium, offline", cmds[0][:4] == ["apt-get", "install", "-y", "--no-download"]
      and "/tmp/huginn-tpm/dracut_110-1_amd64.deb" in cmds[0] and not (inst.t / "tmp/huginn-tpm").exists(), cmds)
enroll = ran[1]
check("…the PIN sealed to the chip with Secure Boot's state, the password to allow it", enroll[0] == ["systemd-cryptenroll", "--tpm2-device=auto", "--tpm2-pcrs=7", "--tpm2-with-pin=yes", "/dev/sdb3"]
      and enroll[1] == {"PASSWORD": "huginn-test-only", "NEWPIN": "2468"}, enroll)
check("…never in the log", not any("2468" in str(x) or "huginn-test-only" in str(x) for x in logs))
check("…crypttab and dracut told, and it says so", done is True and "tpm2-device=auto" in (inst.t / "etc/crypttab").read_text()
      and "tpm2-tss" in (inst.t / "etc/dracut.conf.d/90-huginn.conf").read_text())
ran.clear()


def refuse(cmd, stdin=None, chroot=False, check=True, timeout=0, secrets=None):
    ran.append(cmd)
    if cmd[0] == "systemd-cryptenroll":
        raise eng.Failed("systemd-cryptenroll failed: no TPM2 device")
    return ""


inst.run = refuse
(inst.t / "etc/crypttab").write_text(eng.crypttab("LUKS-UUID"))
check("the chip refusing: the password alone, crypttab left as it was", inst.tpm_unlock() is False and "tpm2" not in (inst.t / "etc/crypttab").read_text())
eng.tpm2_here = real

print(f"\n{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
