#!/usr/bin/env bash
# Installs the Obscura headless browser used by the scraper's render chain.
#
# Obscura is a native binary rather than a Python package, so it cannot come in
# through requirements.txt. Without this step the render provider reports itself
# unconfigured and the chain silently skips to crawlee - which still works, but
# loses the JavaScript-rendered boards Obscura was added to reach.
#
# The archive is pinned by version and verified against a recorded checksum, so
# a tampered or truncated download fails here rather than at scrape time.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${OBSCURA_INSTALL_DIR:-${ROOT_DIR}/backend/bin}"
VERSION="${OBSCURA_VERSION:-v0.1.11}"

case "$(uname -s)" in
  Darwin) OS="macos" ;;
  Linux)  OS="linux" ;;
  *) echo "Unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) ARCH="aarch64" ;;
  x86_64|amd64)  ARCH="x86_64" ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

ASSET="obscura-${ARCH}-${OS}.tar.gz"
URL="https://github.com/h4ckf0r0day/obscura/releases/download/${VERSION}/${ASSET}"

# sha256 per published asset. macOS still ships bash 3.2, which has no
# associative arrays, so this is a plain case statement rather than a map. A new
# VERSION needs its checksums added here; an unknown asset is installed but
# reported, never silently trusted.
expected_checksum() {
  case "$1" in
    "v0.1.11:obscura-aarch64-macos.tar.gz")
      echo "38441f56e3414b5e6a05e51c01c65591608f499dfd01a10072979a152652b1e7" ;;
    *) echo "" ;;
  esac
}

if [[ -x "${TARGET_DIR}/obscura" ]] && "${TARGET_DIR}/obscura" --version 2>/dev/null | grep -q "${VERSION#v}"; then
  echo "Obscura ${VERSION} already installed at ${TARGET_DIR}/obscura"
  exit 0
fi

mkdir -p "${TARGET_DIR}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "Downloading ${ASSET} (${VERSION})..."
curl -fsSL --retry 3 -o "${TMP_DIR}/${ASSET}" "${URL}"

EXPECTED="$(expected_checksum "${VERSION}:${ASSET}")"
ACTUAL="$(shasum -a 256 "${TMP_DIR}/${ASSET}" | awk '{print $1}')"
if [[ -n "${EXPECTED}" ]]; then
  if [[ "${EXPECTED}" != "${ACTUAL}" ]]; then
    echo "Checksum mismatch for ${ASSET}." >&2
    echo "  expected ${EXPECTED}" >&2
    echo "  actual   ${ACTUAL}" >&2
    exit 1
  fi
  echo "Checksum verified."
else
  echo "No recorded checksum for ${VERSION}:${ASSET}; got ${ACTUAL}."
  echo "Add it to scripts/install_obscura.sh to pin this platform."
fi

tar xzf "${TMP_DIR}/${ASSET}" -C "${TMP_DIR}"
install -m 0755 "${TMP_DIR}/obscura" "${TARGET_DIR}/obscura"
[[ -f "${TMP_DIR}/obscura-worker" ]] && install -m 0755 "${TMP_DIR}/obscura-worker" "${TARGET_DIR}/obscura-worker"

echo "Installed: $("${TARGET_DIR}/obscura" --version)"
echo "Set OBSCURA_BINARY_PATH=${TARGET_DIR}/obscura (or put it on PATH)."
