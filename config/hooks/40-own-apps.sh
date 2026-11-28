#!/bin/sh
# Huginn's Terminal is the system's terminal: x-terminal-emulator runs it.
# On update: run
set -e
update-alternatives --install /usr/bin/x-terminal-emulator x-terminal-emulator /usr/bin/huginn-terminal 60
update-alternatives --set x-terminal-emulator /usr/bin/huginn-terminal

# Programs Huginn's own apps use behind the scenes (Screen Sharing uses FreeRDP), and KDE Connect's windows and
# Kvantum's manager on a system that had them before Phone's own link and Huginn's own Qt look, stay out of the start
# menu: a copy with NoDisplay in /usr/local/share, which comes first, so the packages' own files are untouched and
# the programs still run.
mkdir -p /usr/local/share/applications
for f in org.kde.kdeconnect.app org.kde.kdeconnect.nonplasma org.kde.kdeconnect.sms sdl-freerdp kvantummanager; do
    src=/usr/share/applications/$f.desktop
    [ -f "$src" ] || continue
    grep -v '^NoDisplay=' "$src" | sed '0,/^\[Desktop Entry\]/s//[Desktop Entry]\nNoDisplay=true/' > /usr/local/share/applications/$f.desktop
done

# Phone's own link (KDE Connect's protocol; kdeconnect itself is in not-wanted.list): started with the session, and
# by D-Bus when Phone asks for it.
test -f /usr/share/huginn-apps/huginn_phoned.py
test -f /usr/share/dbus-1/services/org.huginn.Phone.service
python3 -c "import cryptography.x509"
