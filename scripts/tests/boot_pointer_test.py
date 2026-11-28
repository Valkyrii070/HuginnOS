"""The installer's boot pointer (the small file GRUB reads to find its menu): its text, where it is written, and that
a pointer on another disk naming a system that is gone is pointed at the new one while a live one is left alone.
The disks are pretended (lsblk, blkid and mount are stand-ins), so this needs no root and touches no disk.
    python3 boot_pointer_test.py <kit root>"""
import shutil, sys, tempfile
from pathlib import Path
from types import SimpleNamespace
ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
sys.path.insert(0, ROOT + "/apps")
import huginn_install_engine as e                                    # noqa: E402
ok = fail = 0


def check(what, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("FAIL", what, extra)


NEW, GONE, LIVE = "aaaa-new", "bbbb-gone", "cccc-live"
text = e.pointer_text(NEW, "/@/boot/grub")
check("looks for the disk by its id first", text.startswith(f"search.fs_uuid {NEW} root\n"))
check("then by the menu file itself", "search --no-floppy --file --set=root /@/boot/grub/grub.cfg" in text)
check("and opens the menu", text.rstrip().endswith("configfile $prefix/grub.cfg") and "set prefix=($root)'/@/boot/grub'" in text)
check("reads back the id it names", e.pointer_target(text) == NEW and e.pointer_target("echo hi\n") == "")

esp = Path(tempfile.mkdtemp(prefix="ptr-"))
(esp / "ubuntu").mkdir()
(esp / "ubuntu/grub.cfg").write_text(f"search.fs_uuid {GONE} root\nconfigfile x\n")       # what grub-install left
made = e.grub_pointers(esp, NEW, "/@/boot/grub")
check("written where the signed GRUB looks", made == [str(esp / "ubuntu/grub.cfg")] and (esp / "ubuntu/grub.cfg").read_text() == text, made)
(esp / "BOOT").mkdir()
check("and in the fallback place when GRUB is there too", len(e.grub_pointers(esp, NEW, "/@/boot/grub")) == 2 and (esp / "BOOT/grub.cfg").read_text() == text)
shutil.rmtree(esp)

# three other partitions: a stale pointer, a live one (another Linux still installed), and Windows' with none
disks = {"/dev/sdb1": f"search.fs_uuid {GONE} root hd1,gpt2\nset prefix=($root)'/boot/grub'\nconfigfile $prefix/grub.cfg\n",
         "/dev/sdc1": f"search.fs_uuid {LIVE} root\nset prefix=($root)'/boot/grub'\nconfigfile $prefix/grub.cfg\n",
         "/dev/sdd1": None}
mounted, after = {}, {}


def run(cmd, **kw):
    out = ""
    if cmd[0] == "lsblk":
        out = "\n".join([f"/dev/sda1 vfat {e.ESP_TYPE}", "/dev/sda2 btrfs 0fc63daf-8483-4772-8e79-3d69d8477de4", f"/dev/sdb1 vfat {e.ESP_TYPE.upper()}",
                         f"/dev/sdc1 vfat {e.ESP_TYPE}", f"/dev/sdd1 vfat {e.ESP_TYPE}", "/dev/sde1 vfat ebd0a0a2-b9e5-4433-87c0-68b6b72699c7", "/dev/sdf"]) + "\n"
    elif cmd[0] == "blkid":
        out = f"{NEW}\n{LIVE}\n1234-ABCD\n"
    elif cmd[0] == "mount":
        dev, where = cmd[-2], Path(cmd[-1])
        mounted[where] = dev
        if disks.get(dev) is not None:
            (where / "EFI/ubuntu").mkdir(parents=True)
            (where / "EFI/ubuntu/grub.cfg").write_text(disks[dev])
    elif cmd[0] == "umount":
        where = Path(cmd[-1])
        after[mounted[where]] = {f.name: f.read_text() for f in where.rglob("*") if f.is_file()}
        shutil.rmtree(where)
        where.mkdir()
    return SimpleNamespace(returncode=0, stdout=out, stderr="")


said = []
changed = e.stale_pointers("/dev/sda1", NEW, "/@/boot/grub", said.append, run)
check("only the stale one is changed", changed == ["/dev/sdb1"], changed)
check("it points at the new system now", after["/dev/sdb1"].get("grub.cfg") == text)
check("the old file is kept beside it", after["/dev/sdb1"].get("grub.cfg.before-huginn") == disks["/dev/sdb1"])
check("a pointer to a system that is still there is left alone", after["/dev/sdc1"] == {"grub.cfg": disks["/dev/sdc1"]})
check("a partition with no pointer gets none", after["/dev/sdd1"] == {})
check("the installer's own partition and ones that aren't EFI are not opened", set(mounted.values()) == {"/dev/sdb1", "/dev/sdc1", "/dev/sdd1"}, mounted)
check("it is in the log", len(said) == 1 and "/dev/sdb1" in said[0] and GONE in said[0], said)
print(f"{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
