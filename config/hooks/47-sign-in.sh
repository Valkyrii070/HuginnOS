#!/bin/sh
# Huginn's own sign-in: the service that checks passwords and starts sessions (apps/huginn_signind.py), and the
# screen it shows (shell/huginn_greeter.py). SDDM is not in the image.
# On update: run
set -e
chmod 755 /usr/libexec/huginn-signind /usr/libexec/huginn-signin-fallback /usr/libexec/huginn-greeter-session /usr/libexec/huginn-login-look
test -f /usr/share/huginn-apps/huginn_signind.py
test -f /usr/share/huginn-apps/huginn_pam.py
test -f /usr/share/huginn-shell/huginn_greeter.py
test -f /usr/share/huginn-shell/qml/Greeter.qml
test -f /usr/share/huginn-shell/qml/GreeterView.qml
for f in huginn-signin huginn-signin-greeter huginn-signin-autologin; do test -f "/etc/pam.d/$f"; chmod 644 "/etc/pam.d/$f"; done
test -f /etc/systemd/system/huginn-signin.service
test -f /etc/systemd/system/graphical.target.d/huginn-signin.conf
# the account the sign-in screen is drawn as, and where the service keeps who signed in last
systemd-sysusers /usr/lib/sysusers.d/huginn-signin.conf
systemd-tmpfiles --create /usr/lib/tmpfiles.d/huginn-signin.conf
getent passwd huginn-greeter >/dev/null
mkdir -p /etc/huginn/signin.conf.d

# A system that signed in through SDDM until now keeps what was chosen there: who signs in by itself, and the realm
# the sign-in screen wears.
old=/etc/sddm.conf.d/20-autologin.conf; new=/etc/huginn/signin.conf.d/20-autologin.conf
if [ -f "$old" ] && [ ! -f "$new" ]; then
    who=$(sed -n 's/^[[:space:]]*User[[:space:]]*=[[:space:]]*//p' "$old" | head -n 1)
    if printf %s "$who" | grep -Eq '^[a-z_][a-z0-9_-]{0,31}$'; then
        printf '[Autologin]\n# Carried over from SDDM.\nUser=%s\nSession=huginn\nRelogin=false\n' "$who" > "$new"
        chmod 644 "$new"
    fi
fi
old=/usr/share/sddm/themes/huginn/theme.conf.user; new=/etc/huginn/signin.conf.d/10-look.conf
if [ -f "$old" ] && [ ! -f "$new" ]; then
    realm=$(sed -n 's/^realm=//p' "$old" | head -n 1)
    case "$realm" in
        aurora|bifrost|muspelheim|niflheim) printf '[Look]\n# Carried over from SDDM.\nRealm=%s\n' "$realm" > "$new"; chmod 644 "$new" ;;
    esac
fi

if [ ! -e /usr/lib/systemd/system/sddm.service ]; then
    # no SDDM here (a new image): this service is the system's display manager by name too
    ln -sfn /etc/systemd/system/huginn-signin.service /etc/systemd/system/display-manager.service
elif [ -d /run/systemd/system ] && ! systemctl is-active --quiet sddm.service; then
    # an update going in as the computer starts, on a system that had SDDM: SDDM now stands aside
    # (sddm.service.d/huginn-signin.conf), and this start was planned before the new service existed, so it's asked
    # for here. It waits for the update to finish (After=huginn-os-update-apply.service).
    systemctl --no-block start huginn-signin.service || true
fi
