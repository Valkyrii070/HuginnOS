#!/bin/sh
# The system's font cache, brought up to date after every font is in (the Japanese, Chinese and Korean ones are big).
# Flatpak apps read it too (/run/host/fonts-cache), so their first start doesn't read every font to make their own.
fc-cache -s >/dev/null 2>&1 || true
