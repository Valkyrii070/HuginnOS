#!/usr/bin/env bash
# Huginn OS ISO build: debootstrap -> chroot customise -> squashfs -> hybrid BIOS/UEFI ISO.
#
#   sudo scripts/build.sh                 full build
#   sudo scripts/build.sh --from rootfs   reuse the bootstrap tarball, rebuild from package install onward
#   sudo scripts/build.sh --from customise  reuse the installed chroot: apply the overlay and hooks again, then repack
#   sudo scripts/build.sh --from image    reuse the finished chroot, only repack squashfs + ISO
#   sudo scripts/build.sh --check         only validate the package lists against the archive
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../config/build.conf
source "$ROOT/config/build.conf"
# Local changes that stay out of the repository (a nearer mirror, faster compression for test builds…).
if [[ -f "$ROOT/config/build.local.conf" ]]; then
    # shellcheck source=/dev/null
    source "$ROOT/config/build.local.conf"
fi

WORK="${WORK:-$ROOT/work}"
OUT="${OUT:-$ROOT/out}"
CHROOT="$WORK/chroot"
IMAGE="$WORK/image"
BOOTSTRAP_TAR="$WORK/bootstrap-$SUITE-${SNAPSHOT:-live}.tar"
FROM="bootstrap"
CHECK_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) FROM="$2"; shift 2 ;;
        --check) CHECK_ONLY=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo $0" >&2; exit 1; }

# One timestamp for every file the build creates, so two builds of the same commit match.
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct 2>/dev/null || date +%s)}"
export SOURCE_DATE_EPOCH
BUILD_ID="$(date -u -d "@$SOURCE_DATE_EPOCH" +%Y%m%d)"
ISO="$OUT/$DISTRO_ID-$DISTRO_VERSION-$BUILD_ID-$ARCH.iso"

if [[ -n "${SNAPSHOT:-}" ]]; then
    APT_MIRROR="$SNAPSHOT_MIRROR/$SNAPSHOT"
else
    APT_MIRROR="$MIRROR"
fi

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mwarning: %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31merror: %s\033[0m\n' "$*" >&2; exit 1; }

umount_chroot() {
    local m
    for m in tmp/hc/crates tmp/hc/target dev/pts dev proc sys run; do
        mountpoint -q "$CHROOT/$m" && umount -l "$CHROOT/$m"
    done
    return 0
}
trap umount_chroot EXIT

mount_chroot() {
    mount --bind /dev "$CHROOT/dev"
    mount -t devpts devpts "$CHROOT/dev/pts"
    mount -t proc proc "$CHROOT/proc"
    mount -t sysfs sysfs "$CHROOT/sys"
    mount -t tmpfs tmpfs "$CHROOT/run"
}

in_chroot() {
    chroot "$CHROOT" /usr/bin/env -i \
        HOME=/root TERM="${TERM:-linux}" PATH=/usr/sbin:/usr/bin:/sbin:/bin \
        DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 \
        SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH" "$@"
}

package_list() {
    # All packages from config/package-lists/*.list, comments and blanks stripped.
    cat "$ROOT"/config/package-lists/*.list | sed 's/#.*//' | awk 'NF {print $1}' | sort -u
}

stage_bootstrap() {
    log "Bootstrap $SUITE ($ARCH) from $APT_MIRROR"
    rm -rf "$CHROOT"
    mkdir -p "$CHROOT"
    debootstrap --arch="$ARCH" --variant=minbase --components="$COMPONENTS" \
        --include=ca-certificates,gpgv "$SUITE" "$CHROOT" "$APT_MIRROR"
    tar -C "$CHROOT" -cf "$BOOTSTRAP_TAR" .
}

stage_restore_bootstrap() {
    [[ -f "$BOOTSTRAP_TAR" ]] || { echo "No bootstrap tarball; run a full build first." >&2; exit 1; }
    log "Restore bootstrap tarball"
    umount_chroot
    rm -rf "$CHROOT"
    mkdir -p "$CHROOT"
    tar -C "$CHROOT" -xf "$BOOTSTRAP_TAR"
}

stage_configure_apt() {
    log "Configure apt"
    local pockets="$SUITE $SUITE-updates $SUITE-security"
    cat > "$CHROOT/etc/apt/sources.list.d/ubuntu.sources" <<SRC
Types: deb
URIs: $APT_MIRROR
Suites: $pockets
Components: ${COMPONENTS//,/ }
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
SRC
    rm -f "$CHROOT/etc/apt/sources.list"
    # Lean installs: no recommends, no snapd pulled back in by a dependency.
    cat > "$CHROOT/etc/apt/apt.conf.d/90huginn" <<'APT'
APT::Install-Recommends "false";
APT::Install-Suggests "false";
Acquire::Check-Valid-Until "false";
APT
    # Building behind an HTTPS proxy (build.local.conf: APT_PROXY, APT_CA): for the build only, removed in cleanup.
    rm -f "$CHROOT/etc/apt/apt.conf.d/89huginn-build-proxy" "$CHROOT/usr/local/share/huginn-build-ca.crt"
    if [[ -n "${APT_PROXY:-}" ]]; then
        echo "Acquire::https::Proxy \"$APT_PROXY\";" > "$CHROOT/etc/apt/apt.conf.d/89huginn-build-proxy"
        if [[ -n "${APT_CA:-}" ]]; then
            install -D -m 644 "$APT_CA" "$CHROOT/usr/local/share/huginn-build-ca.crt"
            echo 'Acquire::https::CaInfo "/usr/local/share/huginn-build-ca.crt";' >> "$CHROOT/etc/apt/apt.conf.d/89huginn-build-proxy"
        fi
    fi
    cat > "$CHROOT/etc/apt/preferences.d/no-snapd" <<'PIN'
Package: snapd
Pin: release *
Pin-Priority: -10
PIN
    in_chroot apt-get update
}

stage_check_packages() {
    log "Validate package lists against the archive"
    local missing=() pkg
    while read -r pkg; do
        if ! in_chroot apt-cache show "$pkg" >/dev/null 2>&1; then
            missing+=("$pkg")
        fi
    done < <(package_list)
    if (( ${#missing[@]} )); then
        printf 'Not found in %s: %s\n' "$SUITE" "${missing[*]}" >&2
        echo "Fix config/package-lists/*.list (apt-cache search inside the chroot helps)." >&2
        exit 1
    fi
    echo "All $(package_list | wc -l) packages resolve."
}

stage_install() {
    log "Install packages"
    # Stop services from starting inside the chroot.
    printf '#!/bin/sh\nexit 101\n' > "$CHROOT/usr/sbin/policy-rc.d"
    chmod +x "$CHROOT/usr/sbin/policy-rc.d"
    in_chroot apt-get -y dist-upgrade
    local pkgs
    mapfile -t pkgs < <(package_list)
    in_chroot apt-get -y install "${pkgs[@]}"

    purge_unwanted "${pkgs[@]}"
}

# Apps Huginn has its own of (and KWin and Plasma's workspace) stay out, even if a dependency brings one in. Also run
# by stage_customise, so a chroot built before something joined config/not-wanted.list loses it too.
purge_unwanted() {
    local pkgs=("$@")
    local unwanted=() p
    while read -r p; do
        in_chroot dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' && unwanted+=("$p")
    done < <(sed 's/#.*//' "$ROOT/config/not-wanted.list" | awk 'NF {print $1}')
    if (( ${#unwanted[@]} )); then
        warn "pulled in by a dependency, taking out: ${unwanted[*]}"
        in_chroot apt-get -y purge "${unwanted[@]}"
        for p in "${pkgs[@]}"; do
            in_chroot dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' \
                || die "taking out ${unwanted[*]} also took out $p: fix config/not-wanted.list or the package lists"
        done
    fi
    # What the lists name stays for good, even once nothing else depends on it (apt autoremove leaves it alone),
    # and something newly listed comes in (a chroot built before it joined a list).
    local missing=()
    for p in "${pkgs[@]}"; do
        in_chroot dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' || missing+=("$p")
    done
    if (( ${#missing[@]} )); then
        in_chroot apt-get -y install "${missing[@]}"
    fi
    in_chroot apt-mark manual "${pkgs[@]}" >/dev/null
    # Zero KDE: anything of KDE's still in the image (a dependency that changed) is said loudly and listed in the
    # work folder, so it's seen at once rather than found later
    local kde kde_names='^(kde|plasma|kwin|breeze|kf6|libkf6|libkf5|kio|kscreen|sddm|kded|kwallet|baloo|milou|kglobalacc|kactivit|libplasma|libkworkspace|libksysguard|libnotificationmanager|libklipper|libkglobalacceld|libkdecorations|libkwaylandclient|knighttime|qml6-module-org-kde|layer-shell-qt|liblayershellqt|qt6-style-kvantum|xdg-desktop-portal-kde|pinentry-qt)'
    # (kept on purpose: KDE's Qt image-format plugins, so Photos, Easel and the rest read HEIC, AVIF, JPEG XL and
    # more; they're plugins for Qt's own image reading, and need KDE's small archive library)
    local kde_kept='^(kimageformat-plugins|libkf5archive5|libkf5archive-data)$'
    kde="$(in_chroot dpkg-query -W -f='${Package}\n' 2>/dev/null | grep -E "$kde_names" | grep -v -E "$kde_kept" || true)"
    if [[ -n "$kde" ]]; then
        # A chroot from before KDE left keeps its libraries marked as asked for; nothing listed needs them now, so
        # they're marked as dependencies and apt takes away the ones nothing depends on (what a fresh build has)
        # shellcheck disable=SC2086
        in_chroot apt-mark auto $kde >/dev/null
        in_chroot apt-get -y autoremove --purge > "$WORK/kde-autoremove.log" 2>&1 || warn "taking out KDE's leftovers failed (see $WORK/kde-autoremove.log)"
        kde="$(in_chroot dpkg-query -W -f='${Package}\n' 2>/dev/null | grep -E "$kde_names" | grep -v -E "$kde_kept" || true)"
    fi
    if [[ -n "$kde" ]]; then
        printf '%s\n' "$kde" > "$WORK/kde-left.txt"
        warn "KDE in the image ($(wc -l <<< "$kde") packages, listed in $WORK/kde-left.txt): add them to config/not-wanted.list or find what brings them"
    else
        rm -f "$WORK/kde-left.txt"
    fi
    purge_old_kernels
}

# Only the newest kernel. A dist-upgrade brings a new one in beside the one before (its image, modules, headers and
# initramfs, about 450 MB in all) and nothing boots the old: the drive and the installed system start from /boot/vmlinuz,
# the newest.
purge_old_kernels() {
    local newest base old
    newest=$(in_chroot sh -c 'ls /lib/modules' | sort -V | tail -n 1)
    base=${newest%-generic}
    [ -n "$base" ] || return 0
    mapfile -t old < <(in_chroot dpkg-query -W -f='${db:Status-Abbrev} ${Package}\n' 'linux-*' 2>/dev/null \
        | awk '$1 == "ii" {print $2}' | grep -E -- '-[0-9]+\.[0-9]+\.[0-9]+-[0-9]+' | grep -vE -- "-${base//./\\.}(-|$)")
    if (( ${#old[@]} )); then
        log "Taking out older kernels (keeping $newest): ${old[*]}"
        in_chroot apt-get -y purge "${old[@]}"
    fi
}

# Dictation's speech engine (Super+H, apps/huginn_dictate.py): whisper.cpp's whisper-cli (MIT, vendor/whisper.cpp at a
# tagged release), built here for any processor with AVX2, with its own ggml linked in: one 3 MB program that needs
# only the C++ runtime. Its build tools come and go again. The speech models are downloaded when they're chosen.
build_whisper() {
    local src="$ROOT/vendor/whisper.cpp" tag="v1.9.5"
    if [ ! -f "$src/CMakeLists.txt" ] && command -v git >/dev/null 2>&1; then
        git clone -q --depth 1 --branch "$tag" https://github.com/ggml-org/whisper.cpp "$src" || rm -rf "$src"
    fi
    [ -f "$src/CMakeLists.txt" ] || { warn "no vendor/whisper.cpp: no dictation"; return 0; }
    rm -rf "$CHROOT/tmp/wh"; mkdir -p "$CHROOT/tmp/wh"
    cp -r "$src/." "$CHROOT/tmp/wh/"; rm -rf "$CHROOT/tmp/wh/.git" "$CHROOT/tmp/wh/models/"*.bin "$CHROOT/tmp/wh/samples"
    in_chroot sh -c "dpkg-query -W -f='\${Package}\n' | sort > /tmp/wh-before.txt"
    if in_chroot env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends cmake g++ make > "$WORK/wh-deps.log" 2>&1 \
       && in_chroot sh -c "cd /tmp/wh && cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF \
              -DWHISPER_BUILD_SERVER=OFF -DWHISPER_SDL2=OFF -DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON \
              -DGGML_OPENMP=OFF && cmake --build build -j$(nproc) --target whisper-cli" > "$WORK/wh-build.log" 2>&1; then
        install -D -m 755 "$CHROOT/tmp/wh/build/bin/whisper-cli" "$CHROOT/usr/libexec/huginn/whisper-cli"
        install -D -m 644 "$src/LICENSE" "$CHROOT/usr/share/doc/huginn-whisper/LICENSE"
    else
        warn "whisper.cpp didn't build (see $WORK/wh-build.log): no dictation"
        tail -15 "$WORK/wh-build.log" "$WORK/wh-deps.log" 2>/dev/null || true
    fi
    in_chroot sh -c "dpkg-query -W -f='\${Package}\n' | sort > /tmp/wh-after.txt; comm -13 /tmp/wh-before.txt /tmp/wh-after.txt > /tmp/wh-new.txt"
    in_chroot sh -c 'grep -E -- "-dev\$|^(cmake|cmake-data|g\+\+|g\+\+-[0-9]+|make|cpp|cpp-[0-9]+|gcc|gcc-[0-9]+)\$" /tmp/wh-new.txt | xargs -r env DEBIAN_FRONTEND=noninteractive apt-get purge -y' > "$WORK/wh-purge.log" 2>&1 || true
    in_chroot env DEBIAN_FRONTEND=noninteractive apt-get autoremove -y --purge >> "$WORK/wh-purge.log" 2>&1 || true
    rm -rf "$CHROOT/tmp/wh" "$CHROOT"/tmp/wh-*.txt
}

build_qt() {
    # Huginn's own Qt parts (qt/): the platform theme (colours, fonts, icons, Open and Save through the portal, menu
    # bars in the top bar) and the widget style that Qt apps other than Huginn's load, and the layer-shell module the
    # shell's windows are made with (org.huginn.layershell). Built against the image's Qt; the compiler and the
    # headers are taken out again afterwards. The shell needs the layer-shell module: without it there's no image.
    local src="$ROOT/qt" plugins=/usr/lib/x86_64-linux-gnu/qt6/plugins qml=/usr/lib/x86_64-linux-gnu/qt6/qml
    [ -f "$src/CMakeLists.txt" ] || return 0
    rm -rf "$CHROOT/tmp/hq"; mkdir -p "$CHROOT/tmp/hq/src"
    cp -r "$src/." "$CHROOT/tmp/hq/src/"
    in_chroot sh -c "dpkg-query -W -f='\${Package}\n' | sort > /tmp/hq-before.txt"
    if in_chroot env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends cmake g++ make pkg-config qt6-base-dev qt6-base-private-dev qt6-declarative-dev libwayland-dev wayland-protocols > "$WORK/qt-deps.log" 2>&1 \
       && in_chroot sh -c "cd /tmp/hq && cmake -S src -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j$(nproc)" > "$WORK/qt-build.log" 2>&1; then
        install -D -m 644 "$CHROOT/tmp/hq/build/libhuginntheme.so" "$CHROOT$plugins/platformthemes/libhuginntheme.so"
        install -D -m 644 "$CHROOT/tmp/hq/build/libhuginnstyle.so" "$CHROOT$plugins/styles/libhuginnstyle.so"
        install -d "$CHROOT$qml/org/huginn/layershell"
        install -m 644 "$CHROOT/tmp/hq/build/org/huginn/layershell/"{qmldir,libhuginnlayershell.so,huginnlayershell.qmltypes} "$CHROOT$qml/org/huginn/layershell/"
        # App Store Qt apps (KDE's Flatpak runtime) find the style as an extension Flatpak doesn't manage
        # (org.kde.KStyle.Huginn), for the runtimes from the Qt it was built with on (a plugin loads in a newer Qt, not
        # an older one); kdeglobals tells them to use it (huginn_look.py). apps/huginn_osupdate.py keeps it the same.
        local qtv minor b
        qtv=$(in_chroot dpkg-query -W -f='${Version}' libqt6core6t64 2>/dev/null | sed 's/^[0-9]*://; s/[^0-9.].*//')
        minor=$(echo "$qtv" | cut -d. -f2)
        case "$minor" in ''|*[!0-9]*) minor="" ;; esac
        for b in ${minor:+0 1 2}; do
            install -D -m 644 "$CHROOT/tmp/hq/build/libhuginnstyle.so" \
                "$CHROOT/var/lib/flatpak/extension/org.kde.KStyle.Huginn/x86_64/6.$((minor + b))/styles/libhuginnstyle.so"
        done
        # (kept for whoever makes the ready-built copy updates carry: apps/huginn_osupdate.py prebuilt-qt)
        rm -rf "$WORK/qt-built"; mkdir -p "$WORK/qt-built"
        cp -r "$CHROOT/tmp/hq/build/"libhuginn*.so "$CHROOT/tmp/hq/build/org" "$WORK/qt-built/"
        in_chroot dpkg-query -W -f='${Version}' libqt6core6t64 2>/dev/null | sed 's/^[0-9]*://; s/[^0-9.].*//' > "$WORK/qt-built/qt-version"
    else
        tail -15 "$WORK/qt-build.log" "$WORK/qt-deps.log" 2>/dev/null || true
    fi
    in_chroot sh -c "dpkg-query -W -f='\${Package}\n' | sort > /tmp/hq-after.txt; comm -13 /tmp/hq-before.txt /tmp/hq-after.txt > /tmp/hq-new.txt"
    in_chroot sh -c 'grep -E -- "-dev\$|-dev-tools\$|^(cmake|cmake-data|g\+\+|g\+\+-[0-9]+|make|cpp|cpp-[0-9]+|gcc|gcc-[0-9]+|qmake6|qmake6-bin|pkg-config|pkgconf|pkgconf-bin|libwayland-bin|wayland-protocols|qt6-qmlls-plugins|qt6-qmllint-plugins)\$" /tmp/hq-new.txt | xargs -r env DEBIAN_FRONTEND=noninteractive apt-get purge -y' > "$WORK/qt-purge.log" 2>&1 || true
    in_chroot env DEBIAN_FRONTEND=noninteractive apt-get autoremove -y --purge >> "$WORK/qt-purge.log" 2>&1 || true
    rm -rf "$CHROOT/tmp/hq" "$CHROOT"/tmp/hq-*.txt
    [ -f "$CHROOT$qml/org/huginn/layershell/qmldir" ] || die "Huginn's Qt parts didn't build (see $WORK/qt-build.log): the shell's windows need its layer-shell module"
}

build_gtk_menus() {
    # Old GTK 3 apps' menu bars in the top bar (gtk/menus.c): a GTK module every GTK 3 app in the session loads
    # (huginn-desktop-session sets GTK_MODULES when it's there). Built against the image's GTK; the compiler and the
    # headers are taken out again afterwards.
    local src="$ROOT/gtk" modules=/usr/lib/x86_64-linux-gnu/gtk-3.0/modules
    [ -f "$src/menus.c" ] || return 0
    rm -rf "$CHROOT/tmp/hg"; mkdir -p "$CHROOT/tmp/hg"
    cp "$src/menus.c" "$src/build.sh" "$CHROOT/tmp/hg/"
    in_chroot sh -c "dpkg-query -W -f='\${Package}\n' | sort > /tmp/hg-before.txt"
    if in_chroot env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gcc libc6-dev pkg-config libgtk-3-dev > "$WORK/gtk-deps.log" 2>&1 \
       && in_chroot sh /tmp/hg/build.sh /tmp/hg > "$WORK/gtk-build.log" 2>&1; then
        install -D -m 644 "$CHROOT/tmp/hg/libhuginn-menus.so" "$CHROOT$modules/libhuginn-menus.so"
        # (kept for whoever makes the ready-built copy updates carry: apps/huginn_osupdate.py prebuilt-gtk)
        rm -rf "$WORK/gtk-built"; mkdir -p "$WORK/gtk-built"
        cp "$CHROOT/tmp/hg/libhuginn-menus.so" "$WORK/gtk-built/"
    else
        warn "the GTK menu module didn't build (see $WORK/gtk-build.log): old GTK 3 apps keep their menu bars in their windows"
        tail -15 "$WORK/gtk-build.log" "$WORK/gtk-deps.log" 2>/dev/null || true
    fi
    in_chroot sh -c "dpkg-query -W -f='\${Package}\n' | sort > /tmp/hg-after.txt; comm -13 /tmp/hg-before.txt /tmp/hg-after.txt > /tmp/hg-new.txt"
    in_chroot sh -c 'grep -E -- "-dev\$|-dev-bin\$|^(gcc|gcc-[0-9]+|cpp|cpp-[0-9]+|pkg-config|pkgconf|pkgconf-bin|libwayland-bin|wayland-protocols|gir1.2-.*-dev)\$" /tmp/hg-new.txt | xargs -r env DEBIAN_FRONTEND=noninteractive apt-get purge -y' > "$WORK/gtk-purge.log" 2>&1 || true
    in_chroot env DEBIAN_FRONTEND=noninteractive apt-get autoremove -y --purge >> "$WORK/gtk-purge.log" 2>&1 || true
    rm -rf "$CHROOT/tmp/hg" "$CHROOT"/tmp/hg-*.txt
}

build_compositor() {
    # Huginn's own compositor (compositor/, Rust, built on Smithay): the "own compositor" session at the sign-in screen.
    # Rust and the headers are put in the image only while it builds, then taken out again, as for rounded corners.
    local src="$ROOT/compositor" crates="$WORK/cargo-home" target="$WORK/compositor-target"
    [ -f "$src/Cargo.toml" ] || return 0
    local deps="rustc cargo pkg-config libudev-dev libinput-dev libgbm-dev libseat-dev libxkbcommon-dev libegl-dev libgles-dev libdrm-dev libpixman-1-dev libdisplay-info-dev libwayland-dev"
    # and for screen sharing's portal backend, built from third_party/ (see below)
    deps="$deps gcc meson ninja-build libpipewire-0.3-dev libinih-dev libsystemd-dev wayland-protocols"
    in_chroot sh -c "dpkg-query -W -f='\${Package}\n' | sort > /tmp/hc-before.txt"
    if ! in_chroot env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $deps > "$WORK/comp-deps.log" 2>&1; then
        warn "Rust or the compositor's headers didn't install (see $WORK/comp-deps.log): no \"own compositor\" session"
        tail -15 "$WORK/comp-deps.log" || true
    else
        # The crates (the libraries it's built from, Cargo.lock pins them) are fetched here on the build computer
        # when it has cargo, and kept in the work folder between builds; the build inside the image then runs offline.
        mkdir -p "$crates" "$target" "$CHROOT/tmp/hc/src" "$CHROOT/tmp/hc/crates" "$CHROOT/tmp/hc/target"
        local where=chroot
        if command -v cargo >/dev/null 2>&1 \
           && CARGO_HOME="$crates" cargo fetch --locked --manifest-path "$src/Cargo.toml" > "$WORK/comp-fetch.log" 2>&1; then
            where=host
        fi
        rsync -a --delete "$src/" "$CHROOT/tmp/hc/src/"
        # Smithay, vendored with Huginn's patch (Cargo.toml: path = "../third_party/smithay")
        mkdir -p "$CHROOT/tmp/hc/third_party"
        rsync -a --delete "$ROOT/third_party/smithay/" "$CHROOT/tmp/hc/third_party/smithay/"
        mount --bind "$crates" "$CHROOT/tmp/hc/crates"
        mount --bind "$target" "$CHROOT/tmp/hc/target"
        local offline="--offline"
        if [ "$where" = chroot ]; then                   # no cargo here: the image fetches them itself
            offline=""
        fi
        if in_chroot sh -c "cd /tmp/hc/src && CARGO_HOME=/tmp/hc/crates CARGO_TARGET_DIR=/tmp/hc/target cargo build --release --locked $offline" \
               > "$WORK/comp-build.log" 2>&1; then
            install -m 755 "$target/release/huginn-compositor" "$CHROOT/usr/bin/huginn-compositor"
            install -D -m 644 "$src/LICENSE-Smithay.txt" "$CHROOT/usr/share/doc/huginn-compositor/LICENSE-Smithay.txt"
            # keep what it links against; everything else the build brought in goes again
            in_chroot sh -c 'ldd /usr/bin/huginn-compositor | awk "/=> \//{print \$3}" | xargs -r dpkg -S 2>/dev/null | cut -d: -f1 | sort -u | xargs -r apt-mark manual >/dev/null'
        else
            warn "Huginn's compositor didn't build (see $WORK/comp-build.log): no \"own compositor\" session"
            tail -25 "$WORK/comp-build.log" || true
        fi
        umount "$CHROOT/tmp/hc/crates" "$CHROOT/tmp/hc/target"
        # Screen sharing: xdg-desktop-portal-wlr 0.9.0 (third_party/, MIT), newer than Ubuntu's 0.8.1, whose frames
        # could outlive their buffers and drop the stream; Ubuntu's binary is diverted, its package stays for the rest.
        local xdpw="$ROOT/third_party/xdg-desktop-portal-wlr"
        if [ -f "$xdpw/meson.build" ] && [ -x "$CHROOT/usr/libexec/xdg-desktop-portal-wlr" ]; then
            rsync -a --delete "$xdpw/" "$CHROOT/tmp/hc/xdpw/"
            if in_chroot sh -c "cd /tmp/hc/xdpw && meson setup build --prefix=/usr -Dman-pages=disabled -Dsystemd=disabled && ninja -C build" \
                   > "$WORK/xdpw-build.log" 2>&1; then
                in_chroot dpkg-divert --local --rename --divert /usr/libexec/xdg-desktop-portal-wlr.ubuntu --add /usr/libexec/xdg-desktop-portal-wlr >/dev/null
                install -m 755 "$CHROOT/tmp/hc/xdpw/build/xdg-desktop-portal-wlr" "$CHROOT/usr/libexec/xdg-desktop-portal-wlr"
                install -D -m 644 "$xdpw/LICENSE" "$CHROOT/usr/share/doc/huginn-xdg-desktop-portal-wlr/LICENSE"
            else
                warn "xdg-desktop-portal-wlr didn't build (see $WORK/xdpw-build.log): Ubuntu's stays"
                tail -15 "$WORK/xdpw-build.log" || true
            fi
        fi
    fi
    in_chroot sh -c "dpkg-query -W -f='\${Package}\n' | sort > /tmp/hc-after.txt; comm -13 /tmp/hc-before.txt /tmp/hc-after.txt > /tmp/hc-new.txt"
    in_chroot sh -c 'grep -E -- "-dev\$|^(rustc|rustc-[0-9.]+|cargo|cargo-[0-9.]+|libstd-rust-[0-9.]+(-dev)?|gcc|gcc-[0-9]+|cpp|cpp-[0-9]+|pkg-config|pkgconf|pkgconf-bin|libwayland-bin|libc-dev-bin|meson|ninja-build|wayland-protocols)\$" /tmp/hc-new.txt | xargs -r env DEBIAN_FRONTEND=noninteractive apt-get purge -y' > "$WORK/comp-purge.log" 2>&1 || true
    in_chroot env DEBIAN_FRONTEND=noninteractive apt-get autoremove -y --purge >> "$WORK/comp-purge.log" 2>&1 || true
    rm -rf "$CHROOT/tmp/hc" "$CHROOT"/tmp/hc-*.txt
    # Without it there's no desktop at all.
    [ -x "$CHROOT/usr/bin/huginn-compositor" ] || die "Huginn's compositor didn't build: it's the only session there is (see $WORK/comp-build.log)"
    # Left by earlier builds (with --from customise): the session's old file name, and xwayland-satellite, which the
    # Python preview compositor needed and this one doesn't (XWayland is built in).
    rm -rf "$CHROOT/usr/share/wayland-sessions/huginn-preview.desktop" "$CHROOT/usr/libexec/huginn/xwayland-satellite" \
           "$CHROOT/usr/share/doc/huginn-xwayland-satellite"
}

stage_customise() {
    log "Apply overlay, theme and system defaults"
    local listed
    mapfile -t listed < <(package_list)
    purge_unwanted "${listed[@]}"
    rsync -a --chown=root:root "$ROOT/config/overlay/" "$CHROOT/"

    # Theme files generated from the design tokens.
    local theme="$WORK/theme"
    rm -rf "$theme"
    python3 "$ROOT/tokens/gen_theme.py" "$ROOT/tokens/tokens.json" "$theme"
    install -d "$CHROOT/usr/share/color-schemes" "$CHROOT/usr/share/huginn-os/gtk" "$CHROOT/usr/share/huginn-os/qt" \
               "$CHROOT/usr/lib/x86_64-linux-gnu/qt6/qml/org/huginn/tokens"
    install -m 644 "$theme"/color-schemes/*.colors "$CHROOT/usr/share/color-schemes/"
    install -m 644 "$theme"/gtk/*.css "$CHROOT/usr/share/huginn-os/gtk/"
    install -m 644 "$theme"/qt/*.conf "$CHROOT/usr/share/huginn-os/qt/"
    install -m 644 "$theme"/qml/* "$CHROOT/usr/lib/x86_64-linux-gnu/qt6/qml/org/huginn/tokens/"
    # Everyone else's apps start in Huginn's look (the shell then follows each user's realm: apps/huginn_look.py):
    # Qt apps in Huginn's own Qt look and the Aurora colours (and App Store apps built on KDE's libraries in those
    # colours), GTK apps in Huginn's GTK theme with them.
    sed -n '/^\[Colors:/,$p' "$theme/color-schemes/HuginnAuroraDark.colors" | sed '/^\[General\]/,$d' >> "$CHROOT/etc/xdg/kdeglobals"
    rm -rf "$CHROOT/etc/xdg/Kvantum"
    install -d "$CHROOT/etc/xdg/huginn" "$CHROOT/etc/gtk-3.0" "$CHROOT/etc/gtk-4.0"
    { python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import huginn_osupdate as u; print(u.QT_DEFAULT, end="")' "$ROOT/apps"
      sed -n '/^\[Colours\]/,$p' "$theme/qt/HuginnAuroraDark.conf"; } > "$CHROOT/etc/xdg/huginn/qt.conf"
    for v in 3.0 4.0; do
        printf '[Settings]\ngtk-theme-name=Huginn\ngtk-icon-theme-name=Huginn\ngtk-cursor-theme-name=Huginn\ngtk-application-prefer-dark-theme=true\ngtk-font-name=Inter Variable 10\n' > "$CHROOT/etc/gtk-$v/settings.ini"
    done
    # Huginn's own pointers (pointers/make_pointers.py), drawn into Huginn's icon theme as Adwaita keeps its own, the
    # other names as links; and X11's default pointer theme (/usr/share/icons/default) made Huginn's
    cp "$ROOT/pointers/make_pointers.py" "$CHROOT/tmp/make_pointers.py"
    # (every realm's: Aurora's are "Huginn", the others Huginn-Bifrost, … and the look swaps to the realm's own; and each
    # again with a plain outline and no glow, Huginn-Plain, Huginn-Bifrost-Plain, …)
    if in_chroot env QT_QPA_PLATFORM=offscreen python3 /tmp/make_pointers.py --realms /usr/share/icons --links > "$WORK/pointers.log" 2>&1; then
        in_chroot update-alternatives --install /usr/share/icons/default/index.theme x-cursor-theme /usr/share/icons/Huginn/cursor.theme 100 >> "$WORK/pointers.log" 2>&1 || true
        in_chroot update-alternatives --set x-cursor-theme /usr/share/icons/Huginn/cursor.theme >> "$WORK/pointers.log" 2>&1 || true
    else
        die "Huginn's pointers couldn't be drawn (see $WORK/pointers.log)"
    fi
    rm -f "$CHROOT/tmp/make_pointers.py"

    # Huginn Shell and the tokens it reads.
    install -d "$CHROOT/usr/share/huginn-shell/qml"
    install -m 755 "$ROOT"/shell/*.py "$CHROOT/usr/share/huginn-shell/"
    install -m 644 "$ROOT"/shell/qml/*.qml "$ROOT"/shell/qml/*.js "$CHROOT/usr/share/huginn-shell/qml/"
    install -D -m 644 "$ROOT/shell/layershell-fallback/org/huginn/layershell/qmldir" \
        "$CHROOT/usr/share/huginn-shell/layershell-fallback/org/huginn/layershell/qmldir"   # (only for systems without the real one)
    install -m 644 "$ROOT/tokens/tokens.json" "$CHROOT/usr/share/huginn-os/tokens.json"
    install -d "$CHROOT/usr/share/huginn-apps/qml"
    install -m 755 "$ROOT"/apps/*.py "$CHROOT/usr/share/huginn-apps/"
    install -m 644 "$ROOT"/apps/qml/*.qml "$ROOT"/apps/qml/*.png "$CHROOT/usr/share/huginn-apps/qml/"
    # Help's guides, and data the apps carry (Characters' emoji list, with its licence).
    install -d "$CHROOT/usr/share/huginn-apps/help" "$CHROOT/usr/share/huginn-apps/data"
    install -m 644 "$ROOT"/apps/help/*.md "$CHROOT/usr/share/huginn-apps/help/"
    cp -r --no-preserve=ownership "$ROOT"/apps/data/. "$CHROOT/usr/share/huginn-apps/data/"   # Characters' emoji list, Clips' wipe patterns
    # Compiled once here: users can't write next to these files, so otherwise every start compiles them again (the
    # shell and the apps are large Python files; on a slow computer that alone takes seconds at every sign-in).
    in_chroot python3 -m compileall -q /usr/share/huginn-apps /usr/share/huginn-shell
    # Which version this system is, and what each of its own files was when it was put there: a later update
    # (apps/huginn_osupdate.py) starts from the first and tells your changes from its own by the second.
    # HUGINN_COMMIT is the commit of this tree (the build tree need not be a git checkout).
    local commit="${HUGINN_COMMIT:-$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)}"
    python3 "$ROOT/apps/huginn_osupdate.py" record "$ROOT" "$CHROOT" "$commit" "$(date -u -d "@$SOURCE_DATE_EPOCH" +%Y-%m-%d)" "$theme" >/dev/null \
        || warn "This system's version couldn't be recorded: it won't update itself until an image that records it is installed"
    [ -n "$commit" ] || warn "HUGINN_COMMIT isn't set and this tree isn't a git checkout: the system's first update will bring everything again"

    build_compositor
    build_qt
    build_gtk_menus
    build_whisper
    # KWin is gone (config/not-wanted.list): its rounded-corners effect and the screenshot helper it authorised
    # (huginn-grab) go with it; Huginn's compositor rounds corners and takes the pictures itself.
    rm -rf "$CHROOT/usr/libexec/huginn/huginn-grab" "$CHROOT/usr/share/applications/huginn-grab.desktop" \
           "$CHROOT/usr/share/doc/huginn-rounded-corners"
    find "$CHROOT/usr/lib" -path '*kwin*' -iname '*shapecorners*' -exec rm -rf {} + 2>/dev/null || true

    # Huginn, the browser, from vendor/huginn (see vendor/huginn/SOURCE for the version).
    # Its launcher and menu entry come from the overlay; the per-user installer is left out.
    # Without vendor/huginn, the browser's own repository (BROWSER_REPO, Valkyrii070/Huginn) is fetched into it, as
    # scripts/update-huginn.sh would. (An older checkout of this kit as the browser repository's os/ folder used
    # the repository around it.)
    local browser="$ROOT/vendor/huginn"
    if [ ! -f "$browser/safari_browser.py" ] && [ -f "$ROOT/../safari_browser.py" ]; then
        browser="$(cd "$ROOT/.." && pwd)"
        install -m 644 "$browser/docs/huginn-icon.png" "$WORK/huginn-icon.png"
    fi
    if [ ! -f "$browser/safari_browser.py" ] && command -v git > /dev/null; then
        log "Fetching Huginn, the browser (${BROWSER_REPO:-https://github.com/Valkyrii070/Huginn})"
        rm -rf "$WORK/huginn-src"
        if git clone -q --depth 1 "${BROWSER_REPO:-https://github.com/Valkyrii070/Huginn}" "$WORK/huginn-src"; then
            "$ROOT/scripts/update-huginn.sh" "$WORK/huginn-src" > /dev/null
        fi
    fi
    [ -f "$browser/safari_browser.py" ] || die "no browser: run scripts/update-huginn.sh /path/to/Huginn (a checkout of the browser's repository)"
    rm -rf "$CHROOT/usr/share/huginn"
    install -d "$CHROOT/usr/share/huginn"
    rsync -a --chown=root:root --chmod=D755,F644 --exclude=installer --exclude='Install Huginn*' \
        --exclude='.git*' --exclude=huginn-icon.png --exclude=/os --exclude=/docs --exclude='*.bat' --exclude='*.ps1' \
        --exclude='*.command' --exclude='*_test.py' --exclude=/python --exclude=__pycache__ --exclude=test_out \
        "$browser/" "$CHROOT/usr/share/huginn/"
    # (the overlay keeps a few things of the system's own in that folder, the sign-in widgets among them: put back)
    if [ -d "$ROOT/config/overlay/usr/share/huginn" ]; then
        rsync -a --chown=root:root "$ROOT/config/overlay/usr/share/huginn/" "$CHROOT/usr/share/huginn/"
    fi
    in_chroot python3 -m compileall -q /usr/share/huginn/safari_browser.py
    # Icons: Huginn draws its own at every size; if that fails here, the 256 px picture is used.
    if in_chroot env QT_QPA_PLATFORM=offscreen HOME=/tmp python3 /usr/share/huginn/safari_browser.py --export-icon /tmp/huginn-icons \
            && [ -f "$CHROOT/tmp/huginn-icons/huginn-256.png" ]; then
        local size
        for size in 16 32 48 64 128 256 512; do
            [ -f "$CHROOT/tmp/huginn-icons/huginn-$size.png" ] || continue
            install -D -m 644 "$CHROOT/tmp/huginn-icons/huginn-$size.png" \
                "$CHROOT/usr/share/icons/hicolor/${size}x${size}/apps/huginn.png"
        done
    else
        warn "Huginn could not draw its icons here; using the 256 px picture"
        local icon="$browser/huginn-icon.png"
        [ -f "$icon" ] || icon="$WORK/huginn-icon.png"
        install -D -m 644 "$icon" "$CHROOT/usr/share/icons/hicolor/256x256/apps/huginn.png"
    fi
    rm -rf "$CHROOT/tmp/huginn-icons"
    in_chroot gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    # Every other app's icon on Huginn's glass tile (apps/huginn_iconwrap.py; the shell does the same for each
    # user's apps installed later), then the Huginn theme's cache.
    in_chroot env QT_QPA_PLATFORM=offscreen HOME=/tmp python3 /usr/share/huginn-apps/huginn_iconwrap.py --system --quiet \
        || warn "Other apps' icons could not be put on Huginn's glass here; the shell will do it at sign-in"
    in_chroot gtk-update-icon-cache -q -t -f /usr/share/icons/Huginn || true
    in_chroot update-mime-database /usr/share/mime || true            # Easel's .easel files
    in_chroot python3 -c "import PySide6.QtWebEngineWidgets, cryptography" \
        || die "Huginn's browser engine (Qt WebEngine) is not importable in the image"

    # Identity.
    echo "$LIVE_HOSTNAME" > "$CHROOT/etc/hostname"
    cat > "$CHROOT/etc/os-release" <<REL
NAME="$DISTRO_NAME"
PRETTY_NAME="$DISTRO_NAME $DISTRO_VERSION"
ID=$DISTRO_ID
ID_LIKE="ubuntu debian"
VERSION_ID="$DISTRO_VERSION"
VERSION_CODENAME=$SUITE
UBUNTU_CODENAME=$SUITE
BUILD_ID=$BUILD_ID
REL
    cat > "$CHROOT/etc/casper.conf" <<CASPER
export USERNAME="$LIVE_USER"
export USERFULLNAME="$DISTRO_NAME"
export HOST="$LIVE_HOSTNAME"
export BUILD_SYSTEM="Ubuntu"
export FLAVOUR="$DISTRO_NAME"
CASPER
    in_chroot locale-gen en_US.UTF-8
    in_chroot update-locale LANG=en_US.UTF-8
    in_chroot systemctl enable NetworkManager ufw            # (the sign-in service: config/hooks/47-sign-in.sh)
    in_chroot systemctl set-default graphical.target

    # Optional hooks: config/hooks/*.sh run inside the chroot, in name order.
    if compgen -G "$ROOT/config/hooks/*.sh" >/dev/null; then
        install -d "$CHROOT/tmp/hooks"
        install -m 755 "$ROOT"/config/hooks/*.sh "$CHROOT/tmp/hooks/"
        local hook
        for hook in "$CHROOT"/tmp/hooks/*.sh; do
            log "Hook $(basename "$hook")"
            in_chroot "/tmp/hooks/$(basename "$hook")"
        done
    fi

    # The installer puts GRUB's own package for the computer's firmware (UEFI or BIOS) on the installed system, so
    # GRUB keeps itself up to date there. The live system has both GRUBs' files but neither package (they conflict),
    # so the two packages ride on the ISO, in pool/ (stage_image moves them there).
    install -d "$CHROOT/var/cache/huginn-pool"
    in_chroot sh -c 'cd /var/cache/huginn-pool && apt-get download grub-efi-amd64 grub-pc'
    # Unlocking with the TPM and a PIN (the installer's Encrypt choice): systemd-cryptenroll and dracut, whose
    # start-up asks for the PIN, in place of initramfs-tools (which can't). The live system keeps initramfs-tools
    # (casper needs it), so these ride on the ISO too, in pool/tpm, with what they need that the image hasn't.
    install -d "$CHROOT/var/cache/huginn-pool/tpm/partial"
    if ! in_chroot apt-get install -y --download-only -o Dir::Cache::Archives=/var/cache/huginn-pool/tpm \
            dracut systemd-cryptsetup tpm2-tools > "$WORK/tpm-pool.log" 2>&1; then
        log "(the TPM unlock's packages couldn't be fetched, see $WORK/tpm-pool.log: the installer won't offer it)"
    fi
    rm -rf "$CHROOT/var/cache/huginn-pool/tpm/partial" "$CHROOT/var/cache/huginn-pool/tpm/lock"
}

stage_cleanup() {
    log "Clean chroot"
    in_chroot apt-get -y autoremove --purge
    in_chroot apt-get clean
    in_chroot update-initramfs -u -k all
    rm -f "$CHROOT/usr/sbin/policy-rc.d" "$CHROOT/etc/apt/apt.conf.d/89huginn-build-proxy" "$CHROOT/usr/local/share/huginn-build-ca.crt"
    rm -rf "$CHROOT"/tmp/* "$CHROOT"/var/lib/apt/lists/* "$CHROOT"/var/cache/apt/*.bin \
           "$CHROOT"/var/log/*.log "$CHROOT"/var/log/apt/* "$CHROOT/root/.bash_history"
    : > "$CHROOT/etc/machine-id"
    # (empty folders left under /home by testing in the chroot; /home itself stays)
    [ -d "$CHROOT/home" ] && find "$CHROOT/home" -mindepth 1 -depth -type d -empty -delete
    umount_chroot
}

stage_image() {
    log "Assemble ISO tree"
    rm -rf "$IMAGE"
    mkdir -p "$IMAGE"/{casper,boot/grub,.disk,pool}
    # The installer's GRUB packages: fetched into the chroot by stage_customise, kept in $WORK/pool so that
    # --from image can repack again and again.
    mkdir -p "$WORK/pool/tpm"
    if compgen -G "$CHROOT/var/cache/huginn-pool/*.deb" >/dev/null; then
        rm -f "$WORK"/pool/*.deb
        mv "$CHROOT"/var/cache/huginn-pool/*.deb "$WORK/pool/"
    fi
    if compgen -G "$CHROOT/var/cache/huginn-pool/tpm/*.deb" >/dev/null; then
        rm -f "$WORK"/pool/tpm/*.deb
        mv "$CHROOT"/var/cache/huginn-pool/tpm/*.deb "$WORK/pool/tpm/"
    fi
    rmdir "$CHROOT/var/cache/huginn-pool/tpm" "$CHROOT/var/cache/huginn-pool" 2>/dev/null || true
    compgen -G "$WORK/pool/*.deb" >/dev/null || die "no GRUB packages for the installer: run with --from customise"
    cp "$WORK"/pool/*.deb "$IMAGE/pool/"
    if compgen -G "$WORK/pool/tpm/*.deb" >/dev/null; then                 # (TPM and PIN unlocking, when they came)
        mkdir -p "$IMAGE/pool/tpm"
        cp "$WORK"/pool/tpm/*.deb "$IMAGE/pool/tpm/"
    fi

    local kernel initrd
    kernel="$(find "$CHROOT/boot" -maxdepth 1 -name 'vmlinuz-*' | sort -V | tail -1)"
    initrd="$(find "$CHROOT/boot" -maxdepth 1 -name 'initrd.img-*' | sort -V | tail -1)"
    [[ -n "$kernel" && -n "$initrd" ]] || { echo "Kernel or initrd missing in chroot." >&2; exit 1; }
    cp "$kernel" "$IMAGE/casper/vmlinuz"
    cp "$initrd" "$IMAGE/casper/initrd"

    chroot "$CHROOT" dpkg-query -W --showformat='${Package} ${Version}\n' > "$IMAGE/casper/filesystem.manifest"
    cp "$IMAGE/casper/filesystem.manifest" "$OUT/$(basename "$ISO" .iso).manifest"

    local comp_opts=(-comp "$SQUASHFS_COMP")
    [[ "$SQUASHFS_COMP" == "zstd" ]] && comp_opts+=(-Xcompression-level "$SQUASHFS_LEVEL")
    # Timestamps come from the exported SOURCE_DATE_EPOCH; mksquashfs refuses that plus -mkfs-time/-all-time.
    mksquashfs "$CHROOT" "$IMAGE/casper/filesystem.squashfs" -noappend -all-root \
        -e boot/vmlinuz-* -e boot/initrd.img-* "${comp_opts[@]}"
    du -sx --block-size=1 "$CHROOT" | cut -f1 > "$IMAGE/casper/filesystem.size"

    echo "$DISTRO_NAME $DISTRO_VERSION \"$SUITE\" - $ARCH ($BUILD_ID)" > "$IMAGE/.disk/info"
    cat > "$IMAGE/boot/grub/grub.cfg" <<GRUB
set default=0
set timeout=3
insmod all_video
set gfxpayload=keep

menuentry "$DISTRO_NAME (live)" {
    linux /casper/vmlinuz boot=casper quiet splash ---
    initrd /casper/initrd
}
menuentry "$DISTRO_NAME (safe graphics)" {
    linux /casper/vmlinuz boot=casper nomodeset ---
    initrd /casper/initrd
}
menuentry "$DISTRO_NAME (verbose boot)" {
    linux /casper/vmlinuz boot=casper ---
    initrd /casper/initrd
}
GRUB
    find "$IMAGE" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +
}

stage_iso() {
    log "Build ISO"
    mkdir -p "$OUT"
    # grub-mkrescue writes a hybrid image that boots on BIOS and UEFI (not Secure Boot; see README).
    grub-mkrescue -o "$ISO" "$IMAGE" -- \
        -volid "$(echo "${DISTRO_ID}_${DISTRO_VERSION}" | tr '[:lower:].-' '[:upper:]__' | cut -c1-32)" \
        -volume_date all_file_dates "=$SOURCE_DATE_EPOCH"
    (cd "$OUT" && sha256sum "$(basename "$ISO")" > "$(basename "$ISO").sha256")
    log "Done: $ISO ($(du -h "$ISO" | cut -f1))"
}

mkdir -p "$WORK" "$OUT"

case "$FROM" in
    bootstrap) stage_bootstrap ;;
    rootfs)    stage_restore_bootstrap ;;
    customise|image) [[ -d "$CHROOT/usr" ]] || die "no chroot in $CHROOT: run a full build first" ;;
    *) echo "--from takes bootstrap, rootfs, customise or image" >&2; exit 2 ;;
esac

if [[ "$FROM" == "customise" ]]; then
    mount_chroot
    stage_configure_apt                 # the package lists were cleaned away at the end of the last build
    stage_install                       # quick when nothing changed; picks up packages added to the lists since
    stage_customise
    stage_cleanup
elif [[ "$FROM" != "image" ]]; then
    mount_chroot
    stage_configure_apt
    stage_check_packages
    (( CHECK_ONLY )) && exit 0
    stage_install
    stage_customise
    stage_cleanup
fi
stage_image
stage_iso
