#!/bin/sh
# Builds Huginn's GTK menu module (menus.c) as libhuginn-menus.so, into the folder given (else next to this file).
# Needs a C compiler, pkg-config and GTK 3's headers (libgtk-3-dev). scripts/build.sh runs it inside the image.
set -e
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-$here}
# shellcheck disable=SC2046  # (pkg-config's words are meant to split)
${CC:-cc} -O2 -g0 -Wall -Wextra -Wno-unused-parameter -shared -fPIC -fvisibility=hidden -Wl,-z,relro,-z,now,-s \
    -o "$out/libhuginn-menus.so" "$here/menus.c" $(pkg-config --cflags --libs gtk+-3.0)
