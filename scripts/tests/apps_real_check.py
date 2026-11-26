#!/usr/bin/env python3
"""Every app opened the way a person first meets it: not its demo, but for real, in an empty home folder. Each draws a
picture of itself and stops. Reports how long each took to its first picture, and everything each one said.

    apps_real_check.py <kit root> <out folder> [app …]      (QT_QPA_PLATFORM=offscreen; not as root)
"""
import os, re, subprocess, sys, time
from pathlib import Path

KIT = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2])
if os.geteuid() == 0:
    sys.exit("not as root: the apps run for real here")
sys.path.insert(0, str(KIT / "apps"))
src = (KIT / "apps/huginn_app.py").read_text(encoding="utf-8")
block = src[src.index("\nAPPS = {"):]
keys = sorted(set(re.findall(r'"([a-z]+)": \("', block[:block.index("}\n")])))
apps = sys.argv[3:] or keys
QUIET = re.compile(r"libEGL|MESA|dri2|ZINK|pdev|propagateSizeHints|XDG_RUNTIME_DIR.*not set|Qt.*offscreen.*plugin does not support|^\s*$|fontconfig|Fontconfig")
home = OUT / "home"
(OUT / "shots").mkdir(parents=True, exist_ok=True)
(OUT / "run").mkdir(exist_ok=True); os.chmod(OUT / "run", 0o700)
rows = []
for key in apps:
    shot = OUT / "shots" / f"{key}.png"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=str(home / key), XDG_RUNTIME_DIR=str(OUT / "run"), PYTHONDONTWRITEBYTECODE="1")
    for v in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "DISPLAY"):
        env.pop(v, None)
    (home / key).mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, str(KIT / "apps/huginn_app.py"), key, "--shot", str(shot)], capture_output=True, text=True, timeout=90, env=env, cwd=str(KIT / "apps"))
        out, code = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out, code = ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) + "\n(timed out after 90 s)", -1
    took = time.time() - t0
    said = [l for l in out.splitlines() if not QUIET.search(l)]
    good = code == 0 and shot.exists() and shot.stat().st_size > 2000
    rows.append((key, took, code, good, said))
    print(f"{'ok  ' if good and not said else 'SAID' if good else 'FAIL'} {key:14} {took:5.1f}s exit {code}{'' if shot.exists() else ', no picture'}", flush=True)
    for l in said[:12]:
        print("       ", l[:260], flush=True)
slow = sorted(rows, key=lambda r: -r[1])[:8]
print("\nslowest:", ", ".join(f"{k} {t:.1f}s" for k, t, *_ in slow))
print(f"{sum(1 for r in rows if r[3] and not r[4])} quiet and fine, {sum(1 for r in rows if r[3] and r[4])} said something, {sum(1 for r in rows if not r[3])} failed, of {len(rows)}")
