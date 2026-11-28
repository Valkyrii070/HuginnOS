"""Start a message in Mail with files attached (Mail shows it; nothing is sent from here). For the apps whose backends
live in their own modules (Writer, Sheets, Slides): the same hand-over huginn_app.send_by_mail makes."""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent


def send_files(paths, subject: str = "") -> bool:
    parts = ["attach=" + quote(str(p), safe="") for p in paths if os.path.isfile(str(p))]
    if not parts:
        return False
    if subject:
        parts.append("subject=" + quote(subject[:200], safe=""))
    subprocess.Popen([sys.executable, str(HERE / "huginn_app.py"), "mail", "mailto:?" + "&".join(parts)], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True
