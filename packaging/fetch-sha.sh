#!/usr/bin/env bash
# Stamp the real tag-tarball sha256 into the Homebrew formula and PKGBUILD.
# Usage: ./fetch-sha.sh 1.3.0   (after `gh release create v1.3.0`)
set -euo pipefail
ver="${1:?usage: fetch-sha.sh VERSION}"
url="https://github.com/Sleepy-Studio/UsageSniffer/archive/refs/tags/v${ver}.tar.gz"
sha=$(curl -sL "$url" | sha256sum | cut -d' ' -f1)
dir=$(dirname "$0")
sed -i "s/sha256 \".*\"/sha256 \"${sha}\"/" "$dir/homebrew/usagesniffer.rb"
sed -i "s/sha256sums=('.*')/sha256sums=('${sha}')/" "$dir/aur/PKGBUILD"
sed -i "s/^pkgver=.*/pkgver=${ver}/" "$dir/aur/PKGBUILD"
echo "stamped $sha for v$ver"
