#!/bin/sh
# Huginn's own boot screen and sign-in screen.
set -e
# Plymouth: the Huginn theme is the default (the initramfs is rebuilt at the end of the build, with it inside).
update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth \
    /usr/share/plymouth/themes/huginn/huginn.plymouth 200
update-alternatives --set default.plymouth /usr/share/plymouth/themes/huginn/huginn.plymouth
# The sign-in screen is Huginn's own now (47-sign-in.sh). SDDM's settings and its Huginn theme are still carried, and
# only for systems installed with SDDM: there SDDM is what takes over if the new service can't start. They go once
# the new sign-in has been seen working on real computers.
test -f /usr/share/sddm/themes/huginn/Main.qml
# The live wallpapers the sign-in screen and the desktop share: a compiled scene and a still for each realm.
for realm in aurora bifrost muspelheim niflheim; do
    test -f "/usr/share/huginn-os/live/$realm.frag.qsb"
    test -f "/usr/share/huginn-os/live/stills/$realm.jpg"
done
test -f /usr/share/huginn-os/live/LiveWallpaper.qml
chmod 755 /usr/libexec/huginn-login-look /usr/libexec/huginn-system-settings
# The session: "Huginn OS" (huginn.desktop: Huginn's own compositor). huginn-session-preview is an old name for it.
rm -f /usr/share/wayland-sessions/huginnos-preview.desktop /usr/share/xdg-desktop-portal/huginn-own-portals.conf
chmod 755 /usr/bin/huginn-session /usr/bin/huginn-session-preview /usr/libexec/huginn-session-apps
test -f /usr/share/huginn-shell/huginn_compositor.py
test -f /usr/share/huginn-shell/qml/Compositor.qml
# The desktop portal: Open and Save, screenshots and colours, "Allow …?", Open With, keeping the screen on,
# starting at sign-in and settings are Huginn's own.
test -f /usr/share/xdg-desktop-portal/huginn-portals.conf
test -f /usr/share/xdg-desktop-portal/portals/huginn.portal
test -f /usr/share/xdg-desktop-portal/portals/huginn-settings.portal
test -f /usr/share/huginn-apps/qml/PortalPrompt.qml
test -f /usr/share/huginn-apps/qml/PortalShot.qml
test -f /usr/share/huginn-apps/huginn_portal_more.py
# GTK's backend answers what Huginn's own and xdg-desktop-portal-wlr (screen sharing) don't: printing, email, your
# name and picture. KDE's backend is gone; on a system that had it, its wrapper, the set-aside D-Bus file and the
# systemd drop-in are put back as they were (nothing asks for it any more, so it never starts).
test -f /usr/share/xdg-desktop-portal/portals/gtk.portal
rm -f /usr/libexec/huginn-portal-kde
rm -rf /usr/lib/systemd/user/plasma-xdg-desktop-portal-kde.service.d
svc=/usr/share/dbus-1/services/org.freedesktop.impl.portal.desktop.kde.service
if dpkg-divert --list "$svc" | grep -q .; then
    rm -f "$svc"
    dpkg-divert --local --rename --remove "$svc"
fi
# The installation drive signs in to Huginn's session, not Plasma's (casper would pick Plasma).
chmod 755 /usr/libexec/huginn-live-session
systemctl enable huginn-live-session.service
# casper-md5check (the installation drive checking its own files at each start) wants an md5sum.txt this image
# doesn't carry: it only ever failed, and showed among the failed services in problem reports. Switched off.
ln -sf /dev/null /etc/systemd/system/casper-md5check.service
# A text console (Ctrl+Alt+F3) greets you as Huginn OS, without Ubuntu's news.
printf 'Huginn OS \\n \\l\n\n' > /etc/issue
printf 'Huginn OS\n' > /etc/issue.net
[ -f /etc/default/motd-news ] && sed -i 's/^ENABLED=.*/ENABLED=0/' /etc/default/motd-news
true
