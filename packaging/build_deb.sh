#!/usr/bin/env bash
# Build a .deb that installs the app into the system Python.
# apt provides python3 and the Qt/xcb system libraries. PySide6 is not packaged under one stable name on
# Debian/Ubuntu and the distro websockets is older than the version this app needs (>= 13), so the postinst script
# installs the Python dependencies from PyPI into /opt/x6100-tci-remote/venv (needs internet once).
set -euo pipefail
cd "$(dirname "$0")/.."
VER=$(python3 -c "import re;print(re.search(r'version = \"([^\"]+)\"', open('pyproject.toml').read()).group(1))")
PKG=x6100-tci-remote
ROOT=build/deb/${PKG}_${VER}
DEPENDS="python3 (>= 3.10), python3-venv, libegl1, libgl1, libfontconfig1, libdbus-1-3, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-shape0, libxcb-xinerama0"
RECOMMENDS="libpulse-mainloop-glib0"

rm -rf "$ROOT" && mkdir -p "$ROOT"/{DEBIAN,usr/bin,usr/lib/python3/dist-packages,usr/share/applications,usr/share/icons/hicolor/scalable/apps,usr/share/doc/$PKG}
cp -r src/x6100_remote "$ROOT/usr/lib/python3/dist-packages/"
find "$ROOT" -name __pycache__ -type d -prune -exec rm -rf {} +
find "$ROOT" -type d -exec chmod 755 {} + && find "$ROOT" -type f -exec chmod 644 {} +
cat > "$ROOT/usr/bin/x6100-tci-remote" <<'WRAP'
#!/bin/sh
PY=python3
[ -x /opt/x6100-tci-remote/venv/bin/python ] && PY=/opt/x6100-tci-remote/venv/bin/python
exec "$PY" -m x6100_remote "$@"
WRAP
chmod 755 "$ROOT/usr/bin/x6100-tci-remote"
install -m 644 LICENSE "$ROOT/usr/share/doc/$PKG/copyright"
install -m 644 README.md CHANGELOG.md "$ROOT/usr/share/doc/$PKG/"
gzip -9n "$ROOT/usr/share/doc/$PKG/CHANGELOG.md"
cp packaging/x6100-tci-remote.desktop "$ROOT/usr/share/applications/"
cp packaging/x6100-tci-remote.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/"
install -m 755 packaging/postinst "$ROOT/DEBIAN/postinst"
install -m 755 packaging/postrm "$ROOT/DEBIAN/postrm"
cat > "$ROOT/DEBIAN/control" <<CTRL
Package: $PKG
Version: $VER
Section: hamradio
Priority: optional
Architecture: all
Depends: $DEPENDS
Recommends: $RECOMMENDS
Maintainer: x6100-tci-remote contributors <noreply@example.invalid>
Description: Remote controller for the Xiegu X6100 (OpenX6X00) over TCI
 A desktop app for the Xiegu X6100 running the OpenX6X00 firmware. It talks to the
 radio's TCI WebSocket server to tune, change mode and filter, listen to the receiver
 audio and (optionally, guarded) transmit, and to the radio's panel server for the
 spectrum and waterfall, band plan, DX spots, status, CW decoder text, a CW tuner
 indicator, the radio's key buttons (after pairing) and an OS-hotkey PTT command.
CTRL
dpkg-deb --build --root-owner-group "$ROOT" "build/${PKG}_${VER}_all.deb"
echo "built build/${PKG}_${VER}_all.deb"
