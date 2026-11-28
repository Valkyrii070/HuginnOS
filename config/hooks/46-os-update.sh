#!/bin/sh
# Huginn OS updates itself (apps/huginn_osupdate.py): the timer that looks for a newer version and gets it ready,
# and the start-up service that puts a ready one in place before the sign-in screen.
# On update: run
set -e
systemctl enable huginn-os-update.timer huginn-os-update-apply.service
