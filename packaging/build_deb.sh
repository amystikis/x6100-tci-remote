#!/usr/bin/env bash
# Build a .deb that installs the app into the system Python (no virtualenv).
# Runtime deps come from apt: python3-websockets, python3-numpy and PySide6 (Qt for Python).
# Package names for PySide6 differ between distros; adjust DEPENDS below if apt can't find them.
# (Not every distro ships PySide6 as a deb: then use `pipx install .` instead - see README.)
set -euo pipefail
cd "$(dirname "$0")/.."
VER=$(python3 -c "import re;print(re.search(r'version = \"([^\"]+)\"', open('pyproject.toml').read()).group(1))")
PKG=x6100-tci-remote
ROOT=build/deb/${PKG}_${VER}
DEPENDS="python3 (>= 3.10), python3-websockets, python3-numpy, python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets"
RECOMMENDS="python3-pyside6.qtmultimedia, libxcb-cursor0"

rm -rf "$ROOT" && mkdir -p "$ROOT"/{DEBIAN,usr/bin,usr/lib/python3/dist-packages,usr/share/applications,usr/share/icons/hicolor/scalable/apps,usr/share/doc/$PKG}
cp -r src/x6100_remote "$ROOT/usr/lib/python3/dist-packages/"
find "$ROOT" -name __pycache__ -type d -prune -exec rm -rf {} +
find "$ROOT" -type d -exec chmod 755 {} + && find "$ROOT" -type f -exec chmod 644 {} +
cat > "$ROOT/usr/bin/x6100-tci-remote" <<'WRAP'
#!/bin/sh
exec python3 -m x6100_remote "$@"
WRAP
chmod 755 "$ROOT/usr/bin/x6100-tci-remote"
install -m 644 LICENSE "$ROOT/usr/share/doc/$PKG/copyright"
install -m 644 README.md CHANGELOG.md "$ROOT/usr/share/doc/$PKG/"
gzip -9n "$ROOT/usr/share/doc/$PKG/CHANGELOG.md"
cp packaging/x6100-tci-remote.desktop "$ROOT/usr/share/applications/"
cp packaging/x6100-tci-remote.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/"
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
