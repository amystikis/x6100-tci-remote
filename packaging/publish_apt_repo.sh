#!/usr/bin/env bash
# Rebuild the apt repository under a gh-pages checkout's apt/ directory with the newly built .deb as its only
# package (there's one package, so the repo always just points at the latest version) and sign it with the
# repo's GPG key (release.yml's apt-repo job imports it from the APT_SIGNING_KEY secret before calling this).
set -euo pipefail
GHPAGES_APT_DIR="$1"
DEB_FILE="$2"

mkdir -p "$GHPAGES_APT_DIR"
find "$GHPAGES_APT_DIR" -maxdepth 1 -name '*.deb' -delete
cp "$DEB_FILE" "$GHPAGES_APT_DIR/"

cd "$GHPAGES_APT_DIR"
dpkg-scanpackages . /dev/null > Packages
gzip -9kf Packages

CONF=$(mktemp)
cat > "$CONF" <<EOF
APT::FTPArchive::Release::Origin "x6100-tci-remote";
APT::FTPArchive::Release::Label "x6100-tci-remote";
APT::FTPArchive::Release::Suite "stable";
APT::FTPArchive::Release::Codename "stable";
APT::FTPArchive::Release::Architectures "all";
APT::FTPArchive::Release::Components "main";
APT::FTPArchive::Release::Description "x6100-tci-remote apt repository";
EOF
apt-ftparchive -c "$CONF" release . > Release
rm -f "$CONF"

KEYID=$(gpg --list-secret-keys --with-colons | awk -F: '/^sec/{print $5; exit}')
gpg --batch --yes --pinentry-mode loopback --passphrase '' --default-key "$KEYID" --digest-algo SHA256 -abs -o Release.gpg Release
gpg --batch --yes --pinentry-mode loopback --passphrase '' --default-key "$KEYID" --digest-algo SHA256 --clearsign -o InRelease Release
