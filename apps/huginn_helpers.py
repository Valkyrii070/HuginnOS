#!/usr/bin/env python3
"""Huginn's quiet helpers, in one process: the shortcuts agent (huginn_shortcuts.py), the privacy watcher
(huginn_privacy.py), automatic updates (huginn_updates.py), keeping accounts in step (huginn_accounts.py) and Huginn
sync (huginn_sync.py).

Each is a loop that looks now and then and sleeps between; run as four Pythons, each carried its own interpreter,
GLib and Qt (about 20 MB apiece). Here they share one, each in its own thread, started a little apart as they were
(huginn-session-apps), and one failing never stops the others: it's started again a minute later.

    python3 huginn_helpers.py          all of them (huginn-session-apps starts it)

Each can still run on its own as before (`huginn_privacy.py watch` and so on); the locks they take mean only one copy
of each runs in a session, whichever started it.
"""
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def name_process(name: str) -> None:
    """The name top and Monitor show for this process (its comm), in place of "python3"."""
    try:
        import ctypes
        ctypes.CDLL(None).prctl(15, name.encode()[:15], 0, 0, 0)          # PR_SET_NAME
    except (OSError, AttributeError):
        pass


def shortcuts() -> None:
    import huginn_shortcuts
    huginn_shortcuts.Agent().serve()


def privacy() -> None:
    import huginn_privacy
    huginn_privacy.Watcher().serve()


def updates() -> None:
    import huginn_updates
    huginn_updates.watch()


def accounts() -> None:
    import huginn_accounts
    huginn_accounts.watch()


def sync() -> None:
    import huginn_sync
    huginn_sync.watch()


# (name, what, seconds after the start: as huginn-session-apps spaced them)
JOBS = (("shortcuts", shortcuts, 0), ("privacy", privacy, 2), ("updates", updates, 0), ("accounts", accounts, 10), ("sync", sync, 12))


def keep(name: str, job, wait: float) -> None:
    time.sleep(wait)
    while True:
        started = time.time()
        try:
            job()
            return                                       # it ended by itself (another copy has its lock): leave it
        except Exception:                                # noqa: BLE001  (one helper's trouble isn't the others')
            print(f"huginn-helpers: {name} stopped:", file=sys.stderr)
            traceback.print_exc()
        time.sleep(60 if time.time() - started > 5 else 300)


def main() -> int:
    name_process("huginn-helpers")
    threads = [threading.Thread(target=keep, args=job, name=job[0], daemon=True) for job in JOBS]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
