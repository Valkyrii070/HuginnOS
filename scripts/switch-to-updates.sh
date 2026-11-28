#!/bin/sh
# For a Huginn OS installed before it could update itself: bring it to the newest version once, by hand, and from
# then on it keeps itself up to date (Settings › Software Update › Huginn OS). On the installed system, in Terminal:
#
#     curl -fsSL https://raw.githubusercontent.com/Valkyrii070/HuginnOS/huginn-os/scripts/switch-to-updates.sh | sudo sh
#
# It fetches the updater from the same branch, tells this system which branch it follows, and runs the same two steps
# Software Update runs: stage (fetch, check, install the Ubuntu packages the new version needs) and apply. Everything
# it replaces is kept: `sudo /usr/libexec/huginn-os-update back` undoes it. Your files and settings aren't touched.
set -e
REPO="${HUGINN_REPO:-Valkyrii070/HuginnOS}"
BRANCH="${HUGINN_BRANCH:-huginn-os}"
[ "$(id -u)" = 0 ] || { echo "Run it with sudo (see the line at the top of this file)."; exit 1; }
[ -d /usr/share/huginn-apps ] || { echo "This doesn't look like Huginn OS: nothing was changed."; exit 1; }
if [ -d /cdrom/casper ] || [ -d /rofs ]; then echo "This is the live system from the installation drive: install Huginn OS first."; exit 1; fi
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "Fetching the updater…"
curl -fsSL "https://raw.githubusercontent.com/$REPO/$BRANCH/apps/huginn_osupdate.py" -o "$tmp/huginn_osupdate.py"
python3 -m py_compile "$tmp/huginn_osupdate.py"
if ! grep -q '^repo: *https://github.com/' /usr/share/huginn-os/SOURCE 2>/dev/null; then
    mkdir -p /usr/share/huginn-os
    printf 'repo: https://github.com/%s.git\nbranch: %s\ncommit: \ndate: \n' "$REPO" "$BRANCH" > /usr/share/huginn-os/SOURCE
fi
python3 "$tmp/huginn_osupdate.py" stage
python3 "$tmp/huginn_osupdate.py" apply
echo
echo "Done. Restart the computer: the new desktop and apps are used from then on, and later versions arrive by themselves."
