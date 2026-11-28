#!/bin/sh
# Programs that work behind Huginn's own apps stay out of the start menu and Search: KDE Connect's windows (on a
# system that had it before Phone's own link), FreeRDP (behind Screen Sharing and Machines), Calf and setBfree (Tempo's instruments and effects) and Kvantum's
# manager (on a system from before Huginn's own Qt look). Each gets a copy in /usr/local/share/applications, which comes before
# /usr/share's, with NoDisplay=true: they still run, open files and start as before, and package updates don't undo it.
# On update: run
set -e
mkdir -p /usr/local/share/applications
for id in org.kde.kdeconnect.app org.kde.kdeconnect.nonplasma org.kde.kdeconnect.sms sdl-freerdp calf setbfree kvantummanager; do
    src="/usr/share/applications/$id.desktop"
    [ -f "$src" ] || continue
    awk 'BEGIN { done = 0 }
         /^\[/ { if (inside && !done) { print "NoDisplay=true"; done = 1 } inside = ($0 == "[Desktop Entry]") }
         inside && /^NoDisplay=/ { next }
         { print }
         END { if (inside && !done) print "NoDisplay=true" }' "$src" > "/usr/local/share/applications/$id.desktop"
done
