"""Backup kept in a folder of the home: the folder's own files are still backed up, earlier backups are not copied
into later ones, and going back is only from a listed backup and only from inside it.
    python3 backup_inside_test.py <kit root>"""
import os, shutil, sys, tempfile, time
from pathlib import Path
ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
if os.geteuid() == 0:
    sys.exit("not as root: this writes and removes files")
home = Path(tempfile.mkdtemp(prefix="bktest-"))
os.environ.update(HOME=str(home), QT_QPA_PLATFORM="offscreen")
sys.path[:0] = [ROOT + "/apps", ROOT + "/shell"]
import huginn_more as m                                              # noqa: E402
ok = fail = 0


def check(what, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("FAIL", what, extra)


for d in ("Music", "Documents"):
    (home / d).mkdir()
(home / "Music/a.mp3").write_bytes(b"x" * 1000)
(home / "Documents/n.txt").write_text("hi")
results = []
for _ in range(3):
    results.append(m.run_backup(home, str(home / "Music")))
    time.sleep(1.1)
check("three backups finish", all(r["ok"] for r in results), [r["error"] for r in results])
check("each holds the two files and no more", [r["files"] for r in results] == [2, 2, 2], [r["files"] for r in results])
snaps = sorted(p for p in (home / "Music/Huginn Backups").glob("*/*") if p.is_dir())
check("three kept", len(snaps) == 3, snaps)
check("the chosen folder's own files are in the backup", all((s / "Music/a.mp3").is_file() for s in snaps))
check("no backup inside a backup", not any((s / "Music/Huginn Backups").exists() for s in snaps))
deepest = max(len(p.parts) for p in home.rglob("*")) - len(home.parts)
check("nothing nests", deepest <= 6, deepest)
check("a place that steps out of a backup is refused", m.Backup._within("../../x") == "" and m.Backup._within("/a//b/./c") == "a/b/c")
print(f"{ok} passed, {fail} failed")
shutil.rmtree(home, ignore_errors=True)
sys.exit(1 if fail else 0)
