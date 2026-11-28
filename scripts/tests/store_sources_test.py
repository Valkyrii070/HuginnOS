#!/usr/bin/env python3
"""The App Store's two sources (apps/huginn_debapps.py, Store in apps/huginn_app.py): Ubuntu's own packages of the apps
it lists from Flathub, found in Ubuntu's AppStream catalogue, chosen by default for Qt apps, installed, opened and
removed through PackageKit; Flathub's as before. Against made-up catalogues and stand-ins for flatpak, pkgcli and
apt-cache (they only write down what they were asked); with Ubuntu's real catalogue too where this computer has it.

    store_sources_test.py <kit root>        (not as root)
"""
import gzip
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

if os.geteuid() == 0:
    sys.exit("not as root")
KIT = Path(sys.argv[1]).resolve()
home = Path(tempfile.mkdtemp(prefix="storesrc-"))
os.environ.update(HOME=str(home), XDG_DATA_HOME=str(home / ".local/share"), XDG_CONFIG_HOME=str(home / ".config"), QT_QPA_PLATFORM="offscreen")
sys.path.insert(0, str(KIT / "apps"))
import huginn_debapps as d  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"ok   {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


# ------------------------------------------------------------------------------------------------ Ubuntu's catalogue
lists = home / "lists"
lists.mkdir()
DEP11 = """---
File: DEP-11
Version: '1.0'
Origin: ubuntu-resolute-universe
---
Type: desktop-application
ID: org.kde.krita.desktop
Package: krita
Name:
  C: Krita
  de: Krita
Summary:
  C: Digital painting
Launchable:
  desktop-id:
  - org.kde.krita.desktop
---
Type: desktop-application
ID: org.videolan.vlc
Package: vlc
Name:
  C: VLC
Launchable:
  desktop-id:
  - vlc.desktop
Provides:
  mediatypes:
  - video/mp4
---
Type: desktop-application
ID: gimp.desktop
Package: gimp
Name:
  C: GNU Image Manipulation Program
Provides:
  ids:
  - org.gimp.GIMP
---
Type: desktop-application
ID: org.mozilla.firefox
Package: firefox
Name:
  C: Firefox
---
Type: font
ID: org.example.font
Package: fonts-example
---
Type: desktop-application
ID: org.example.Bad
Package: Bad Name; rm -rf /
"""
dep11 = lists / "archive.ubuntu.com_ubuntu_dists_resolute_universe_dep11_Components-amd64.yml.gz"
with gzip.open(dep11, "wt") as fh:
    fh.write(DEP11)
cat = d.catalogue(lists, "amd64")
check("an app by its id, with or without .desktop, in any case", d.match(cat, ["org.kde.Krita"]) == {"package": "krita", "desktop": "org.kde.krita.desktop", "name": "Krita"})
check("…by its launcher's name", d.match(cat, ["org.videolan.VLC"])["package"] == "vlc" and d.match(cat, ["vlc.desktop"])["desktop"] == "vlc.desktop")
check("…by an id it says it provides", d.match(cat, ["org.gimp.GIMP"])["package"] == "gimp")
check("…the first of an app's ids that Ubuntu has", d.match(cat, ["org.example.Nope", "org.videolan.vlc"])["package"] == "vlc")
check("Ubuntu's packages that only install a Snap aren't offered", d.match(cat, ["org.mozilla.firefox"]) is None)
check("…nor fonts, nor a package name that isn't one", d.match(cat, ["org.example.font"]) is None and d.match(cat, ["org.example.Bad"]) is None)
check("…nor another architecture's catalogue", d.catalogue(lists, "arm64") == {})
check("no catalogue: nothing, and very old", d.catalogue(home / "none", "amd64") == {} and d.lists_age(home / "none") > 1e9 and d.lists_age(lists) < 60)
status = home / "status"
status.write_text("Package: gimp\nStatus: install ok installed\nVersion: 3.0.6-1\n\nPackage: vlc\nStatus: deinstall ok config-files\n\nPackage: krita-data\nStatus: install ok installed\n")
check("what dpkg says is installed (and not what's only left configured)", d.installed(status) == {"gimp", "krita-data"})
check("PackageKit installs and removes", d.command("install", "krita", which=lambda n: "/usr/bin/pkgcli") == ["pkgcli", "install", "-y", "krita"]
      and d.command("remove", "krita", which=lambda n: "/usr/bin/pkgcli") == ["pkgcli", "remove", "-y", "krita"])
check("…fetching the lists first when they're old", d.command("install", "krita", refresh=True, which=lambda n: "/usr/bin/pkgcli") == ["sh", "-c", "pkgcli refresh && pkgcli install -y krita"])
check("…apt under the password prompt without PackageKit", d.command("install", "krita", refresh=True, which=lambda n: None)
      == ["pkexec", "env", "DEBIAN_FRONTEND=noninteractive", "sh", "-c", 'apt-get update && apt-get install -y "$1"', "sh", "krita"])
check("…and nothing for a name that isn't a package's, or another verb", d.command("install", "krita; rm -rf ~") == [] and d.command("purge", "krita") == [])


class Done:
    def __init__(self, out):
        self.stdout, self.returncode = out, 0


check("the version and size apt would install", d.details("krita", run=lambda *a, **k: Done("Package: krita\nVersion: 1:5.2.9+dfsg-2ubuntu1\nSize: 41520034\n"))
      == {"version": "5.2.9", "size": "41.5 MB"})
check("…not asked for a name that isn't a package's", d.details("-o Dir=/x") == {})
apps_dir = home / "applications"
apps_dir.mkdir()
(apps_dir / "org.kde.krita.desktop").write_text("[Desktop Entry]\nName=Krita\nExec=krita\n")
check("an installed app's launcher", d.launcher("org.kde.krita.desktop", [str(apps_dir)]) == str(apps_dir / "org.kde.krita.desktop")
      and d.launcher("../../etc/passwd", [str(apps_dir)]) == "" and d.launcher("vlc.desktop", [str(apps_dir)]) == "")

# ------------------------------------------------------------------------------------------------ the store, with both
flathub = home / ".local/share/flatpak/appstream/flathub" / os.uname().machine / "active"
flathub.mkdir(parents=True)
APPSTREAM = """<?xml version="1.0"?><components version="0.8" origin="flathub">
<component type="desktop-application"><id>org.kde.krita</id><name>Krita</name><summary>Paint</summary>
  <bundle type="flatpak" runtime="org.kde.Platform/x86_64/6.9" sdk="org.kde.Sdk/x86_64/6.9">app/org.kde.krita/x86_64/stable</bundle>
  <launchable type="desktop-id">org.kde.krita.desktop</launchable><categories><category>Graphics</category></categories></component>
<component type="desktop-application"><id>org.gimp.GIMP</id><name>GIMP</name><summary>Photos</summary>
  <bundle type="flatpak" runtime="org.gnome.Platform/x86_64/48">app/org.gimp.GIMP/x86_64/stable</bundle></component>
<component type="desktop-application"><id>org.example.Only</id><name>Only</name><summary>Only on Flathub</summary>
  <bundle type="flatpak" runtime="org.kde.Platform/x86_64/6.9">app/org.example.Only/x86_64/stable</bundle></component>
<component type="desktop-application"><id>org.mozilla.firefox</id><name>Firefox</name><summary>Web</summary>
  <bundle type="flatpak" runtime="org.freedesktop.Platform/x86_64/24.08">app/org.mozilla.firefox/x86_64/stable</bundle></component>
</components>"""
with gzip.open(flathub / "appstream.xml.gz", "wt") as fh:
    fh.write(APPSTREAM)
bin_dir = home / "bin"
bin_dir.mkdir()
log = home / "asked.log"
for name, body in (("flatpak", 'case "$1" in remotes) echo flathub;; list) echo org.example.Old;; remote-ls) printf "org.kde.krita\\t120 MB\\n";; '
                                '*) echo "flatpak $*" >> LOG; echo "Installing… 100%";; esac'),
                   ("pkgcli", 'echo "pkgcli $*" >> LOG; echo "Resolving"; [ "$3" = broken ] && exit 1; exit 0'),
                   ("apt-cache", 'printf "Package: %s\\nVersion: 5.2.9-1\\nSize: 2048000\\n" "$4"'),
                   ("gio", 'echo "gio $*" >> LOG')):
    f = bin_dir / name
    f.write_text("#!/bin/sh\n" + body.replace("LOG", str(log)) + "\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
d.LISTS, d.STATUS, d.LAUNCHERS = lists, status, (str(apps_dir),)

from PySide6.QtCore import QCoreApplication  # noqa: E402
app = QCoreApplication([])
import huginn_app  # noqa: E402


def settle(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


store = huginn_app.Store(False)
check("the catalogue is read", settle(lambda: store._ready and len(store._apps) == 4))
a = store._apps
check("a Qt app Ubuntu has: both offered, Ubuntu's first", a["org.kde.krita"]["deb"] == "krita" and a["org.kde.krita"]["qt"] and a["org.kde.krita"]["prefer"] == "deb"
      and a["org.kde.krita"]["debDesktop"] == "org.kde.krita.desktop", a["org.kde.krita"])
check("a GTK app Ubuntu has: both offered, Flathub's first; already in from Ubuntu", a["org.gimp.GIMP"]["deb"] == "gimp" and a["org.gimp.GIMP"]["prefer"] == "flathub"
      and a["org.gimp.GIMP"]["installed"] and a["org.gimp.GIMP"]["from"] == "deb" and not a["org.gimp.GIMP"]["flatInstalled"], a["org.gimp.GIMP"])
check("an app only on Flathub: Flathub's, even a Qt one", a["org.example.Only"]["deb"] == "" and a["org.example.Only"]["prefer"] == "flathub")
check("an app whose Ubuntu package is only a Snap: Flathub's", a["org.mozilla.firefox"]["deb"] == "")
store.show("org.kde.krita")
check("an app's page asks apt which version Ubuntu's is", settle(lambda: a["org.kde.krita"].get("debVersion") == "5.2.9") and a["org.kde.krita"]["debSize"] == "2.0 MB")
store.install("org.kde.krita")
check("Get on a Qt app puts in Ubuntu's package, through PackageKit", settle(lambda: not store._busy and a["org.kde.krita"]["debInstalled"])
      and "pkgcli install -y krita" in log.read_text() and a["org.kde.krita"]["from"] == "deb", log.read_text())
store.launch("org.kde.krita")
check("…and Open starts it from its launcher", settle(lambda: f"gio launch {apps_dir / 'org.kde.krita.desktop'}" in log.read_text()), log.read_text())
store.installFrom("org.example.Only", "deb")
check("asking Ubuntu for an app it hasn't: Flathub's", settle(lambda: not store._busy and a["org.example.Only"]["flatInstalled"])
      and "flatpak install -y --noninteractive flathub org.example.Only" in log.read_text())
store.installFrom("org.gimp.GIMP", "flathub")
store.removeFrom("org.kde.krita", "deb")
check("one at a time: the second waits its turn", store._busy == "org.gimp.GIMP" and [q[0] for q in store._queue] == ["org.kde.krita"])
check("…then both are done", settle(lambda: not store._busy and not store._queue and "pkgcli remove -y krita" in log.read_text()
                                     and not a["org.kde.krita"]["debInstalled"]) and a["org.gimp.GIMP"]["flatInstalled"] and not a["org.kde.krita"]["debInstalled"]
      and not a["org.kde.krita"]["installed"] and "pkgcli remove -y krita" in log.read_text(), (store._busy, store._queue, a["org.gimp.GIMP"], a["org.kde.krita"], log.read_text()))
check("with both in, it's still installed when one goes, and says which is left",
      (store.remove("org.gimp.GIMP"), settle(lambda: not store._busy))[1] and a["org.gimp.GIMP"]["installed"] and a["org.gimp.GIMP"]["from"] == "flathub"
      and "pkgcli remove -y gimp" in log.read_text())
before = log.read_text()
store.installFrom("org.example.NotListed", "deb")
store.installFrom("--version", "flathub")
check("nothing the store didn't list is handed on", settle(lambda: not store._busy, 1) and log.read_text() == before, (store._busy, log.read_text()[len(before):]))
a["org.kde.krita"]["deb"] = "broken"
errors = []
store.failed.connect(errors.append)
store.installFrom("org.kde.krita", "deb")
check("a package that won't go in says so", settle(lambda: bool(errors)) and "Couldn't install Krita" in errors[0], errors)

# ------------------------------------------------------------------------------------------------ Ubuntu's real catalogue
real = Path("/var/lib/apt/lists")
if list(real.glob("*_dep11_Components-*.yml.gz")):
    cat = d.catalogue(real)
    found = {i: (d.match(cat, [i]) or {}).get("package") for i in ("org.videolan.VLC", "org.keepassxc.KeePassXC", "org.kde.kate", "org.kde.krita", "com.obsproject.Studio")}
    check("Ubuntu's real catalogue: well-known Flathub apps found", all(found.values()), json.dumps(found))
    check("…and Firefox and Thunderbird left to Flathub", d.match(cat, ["org.mozilla.firefox", "firefox.desktop"]) is None
          and d.match(cat, ["org.mozilla.Thunderbird", "thunderbird.desktop"]) is None)
else:
    print("skip Ubuntu's real catalogue: not on this computer (needs the appstream package and fetched lists)")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
