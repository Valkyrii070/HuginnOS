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
# The desktop portal: Open and Save, screenshots and colours, "Allow …?", Open With and settings are Huginn's own.
test -f /usr/share/xdg-desktop-portal/huginn-portals.conf
test -f /usr/share/xdg-desktop-portal/portals/huginn.portal
test -f /usr/share/xdg-desktop-portal/portals/huginn-settings.portal
test -f /usr/share/huginn-apps/qml/PortalPrompt.qml
test -f /usr/share/huginn-apps/qml/PortalShot.qml
# KDE's backend answers what Huginn's own and xdg-desktop-portal-wlr (screen sharing) don't. It is started through a
# small wrapper (it once told it "KDE" in the KWin session, which is gone); its own D-Bus file is set aside
# (dpkg-divert, so package updates keep to the side).
kde_portal=$(dpkg -L xdg-desktop-portal-kde | grep '/libexec/xdg-desktop-portal-kde$' | head -n1)
test -x "$kde_portal"
cat > /usr/libexec/huginn-portal-kde <<EOF2
#!/bin/sh
# KDE's portal backend in Huginn's session: see /usr/share/xdg-desktop-portal/huginn-portals.conf.
exec $kde_portal "\$@"
EOF2
chmod 755 /usr/libexec/huginn-portal-kde
svc=/usr/share/dbus-1/services/org.freedesktop.impl.portal.desktop.kde.service
dpkg-divert --local --rename --divert "$svc.kde-original" --add "$svc"
cat > "$svc" <<'EOF2'
[D-BUS Service]
Name=org.freedesktop.impl.portal.desktop.kde
Exec=/usr/libexec/huginn-portal-kde
SystemdService=plasma-xdg-desktop-portal-kde.service
EOF2
mkdir -p /usr/lib/systemd/user/plasma-xdg-desktop-portal-kde.service.d
cat > /usr/lib/systemd/user/plasma-xdg-desktop-portal-kde.service.d/huginn.conf <<'EOF2'
# Huginn: started by systemd, KDE's portal backend goes through the same wrapper (see /usr/libexec/huginn-portal-kde).
[Service]
ExecStart=
ExecStart=/usr/libexec/huginn-portal-kde
EOF2
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
