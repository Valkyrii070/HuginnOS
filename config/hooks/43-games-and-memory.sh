#!/bin/sh
# Game Mode, and using less memory.
set -e
# Game Mode (huginn-session --game): the session, Steam's helpers
chmod 755 /usr/libexec/huginn-desktop-session /usr/libexec/huginn-game-session /usr/libexec/huginn-steamos/*
# Ubuntu's fluidsynth turns on its user service for everyone: a MIDI synthesiser that holds its sound font in memory
# (about 160 MB) from sign-in on, for nothing. Tempo runs fluidsynth itself when it makes sound from MIDI.
systemctl --global disable fluidsynth.service 2>/dev/null || true
rm -f /etc/systemd/user/default.target.wants/fluidsynth.service
# earlyoom (settings in /etc/default/earlyoom); zram comes up by itself from /etc/systemd/zram-generator.conf
systemctl enable earlyoom.service
