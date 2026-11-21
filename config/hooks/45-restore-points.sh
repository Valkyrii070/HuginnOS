#!/bin/sh
# Restore points (huginn-snapshot): the helper, GRUB's list of them, the initramfs piece that goes back from the
# start-up menu, and the service that finishes it. They only act on an installed system on btrfs.
# And Huginn sync's command (huginn-sync; the session's helpers run it).
set -e
chmod 755 /usr/libexec/huginn-snapshot /usr/libexec/huginn-sync /usr/libexec/huginn-dictate /etc/grub.d/41_huginn_snapshots \
          /usr/share/initramfs-tools/scripts/local-premount/huginn-undo /usr/share/initramfs-tools/hooks/huginn-undo
systemctl enable huginn-undo-finish.service huginn-file-versions.timer
