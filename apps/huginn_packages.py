#!/usr/bin/env python3
"""Putting in Ubuntu packages for Huginn's apps: Code's languages (huginn_code.py) and llama.cpp for Huginn AI
(huginn_ai.py), through PackageKit (pkgcli, Ubuntu 26.04) or, without it, apt-get under the system's password prompt.

The drive and a fresh installation carry no package lists (/var/lib/apt/lists: they'd add a lot, and go stale), so
until something fetches them every package looks unknown and an install fails at once. Here they're fetched first
whenever they're missing or more than two days old.

    install(["clangd", "gdb"]) -> ""            or why not, in a sentence
"""
import os
import shutil
import subprocess
import time
from pathlib import Path

LISTS = Path("/var/lib/apt/lists")
STALE = 2 * 86400


def lists_stale(lists: Path = LISTS, now: float = 0.0) -> bool:
    """No package lists, or none fetched in the last two days."""
    try:
        newest = max((p.stat().st_mtime for p in lists.iterdir() if "_Packages" in p.name), default=0.0)
    except OSError:
        newest = 0.0
    return (now or time.time()) - newest > STALE


def _tail(done: subprocess.CompletedProcess) -> str:
    lines = [ln.strip() for ln in (done.stderr or done.stdout or "").splitlines() if ln.strip()]
    return lines[-1][:160] if lines else f"code {done.returncode}"


def install(pkgs: list, timeout: int = 3600, run=subprocess.run, which=shutil.which, stale=None) -> str:
    """Put these packages in, fetching the package lists first if need be. "" when they're in; else why not."""
    if not pkgs:
        return ""
    env = {**os.environ, "LC_ALL": "C.UTF-8", "DEBIAN_FRONTEND": "noninteractive"}
    refresh = lists_stale() if stale is None else stale
    try:
        if which("pkgcli"):
            if refresh:
                done = run(["pkgcli", "refresh"], capture_output=True, text=True, timeout=900, env=env)
                if done.returncode != 0:
                    return f"Couldn't fetch the list of Ubuntu's packages ({_tail(done)}). Is the computer online?"
            done = run(["pkgcli", "install", "-y", *pkgs], capture_output=True, text=True, timeout=timeout, env=env)
        else:
            # one password prompt for both steps
            script = ("apt-get update && " if refresh else "") + 'apt-get install -y "$@"'
            done = run(["pkexec", "env", "DEBIAN_FRONTEND=noninteractive", "sh", "-c", script, "sh", *pkgs],
                       capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return "Putting the packages in took too long and was stopped."
    except OSError as err:
        return f"The packages couldn't be put in ({err})."
    if done.returncode == 0:
        return ""
    if done.returncode in (126, 127) and not which("pkgcli"):
        return "The password prompt was closed, so nothing was put in."
    return f"The packages weren't put in ({_tail(done)})."
