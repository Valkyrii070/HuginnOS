"""Huginn's little sounds: the alert sound (an app's bell, a question that needs an answer), a notification's sound
and the click the volume keys make (Settings › Sound). Kept in ~/.config/huginn/sound.json:

    {"alert": "bell", "alertVolume": 0.7, "volumeFeedback": true}

    play(kind)        "alert" (or "bell"), "message" (a notification), "volume" (the volume keys' click); played
                      through PipeWire (pw-play) in the background, at the alert volume
    settings()        the file, with the defaults filled in
    ALERTS            the alert sounds to choose from: (id, label, file)
"""
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
FILE = CONFIG / "huginn" / "sound.json"
SOUNDS = (Path("/usr/share/sounds/freedesktop/stereo"), Path("/usr/share/sounds/ocean/stereo"))
ALERTS = [("bell", "Bell", "bell.oga"), ("chime", "Chime", "complete.oga"), ("soft", "Soft", "dialog-information.oga"),
          ("knock", "Knock", "window-attention.oga"), ("question", "Question", "window-question.oga"),
          ("warning", "Warning", "dialog-warning.oga"), ("none", "None", "")]
DEFAULTS = {"alert": "bell", "alertVolume": 0.7, "volumeFeedback": True}
FILES = {"message": "message-new-instant.oga", "volume": "audio-volume-change.oga", "alarm": "alarm-clock-elapsed.oga"}


def settings() -> dict:
    out = dict(DEFAULTS)
    try:
        saved = json.loads(FILE.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            out.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return out


def save(change: dict) -> dict:
    now = settings()
    now.update({k: v for k, v in change.items() if k in DEFAULTS})
    FILE.parent.mkdir(parents=True, exist_ok=True)
    part = FILE.with_name(f".sound.json.{os.getpid()}.part")
    part.write_text(json.dumps(now, indent=1), encoding="utf-8")
    os.replace(part, FILE)
    return now


def find(name: str) -> str:
    for folder in SOUNDS:
        if name and (folder / name).is_file():
            return str(folder / name)
    return ""


def file_for(kind: str, prefs: dict = None) -> str:
    prefs = prefs or settings()
    if kind in ("alert", "bell"):
        name = next((f for i, _l, f in ALERTS if i == prefs.get("alert")), "bell.oga")
        return find(name)
    if kind.startswith("alert:"):                       # one to try out in Settings
        return find(next((f for i, _l, f in ALERTS if i == kind[6:]), ""))
    if kind == "alarm":                                 # (an alarm rings whatever alert sound is chosen, None too)
        return find(FILES["alarm"]) or find("bell.oga") or find("complete.oga")
    return find(FILES.get(kind, ""))


def play(kind: str, volume: float = None) -> bool:
    """Play one of the sounds; False when there's nothing to play (no sound chosen, or no PipeWire)."""
    prefs = settings()
    path = file_for(kind, prefs)
    player = shutil.which("pw-play") or shutil.which("paplay")
    if not path or not player:
        return False
    level = max(0.0, min(1.0, float(prefs.get("alertVolume", 0.7) if volume is None else volume)))
    argv = [player, f"--volume={level:.2f}", path] if player.endswith("pw-play") else [player, f"--volume={int(level * 65536)}", path]
    run(argv)
    return True


def run(argv: list) -> None:
    """Play in the background, and wait for the player there (so a long-running shell or daemon collects no zombies)."""
    def work():
        try:
            subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
    threading.Thread(target=work, daemon=True).start()
