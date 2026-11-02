#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
command -v mkcert >/dev/null || { echo 'Install mkcert first (macOS: brew install mkcert).'; exit 1; }
command -v docker >/dev/null || { echo 'Docker is required.'; exit 1; }

# Install the local CA separately with `mkcert -install`; macOS may ask for
# administrator approval. Never commit the CA or these private keys.
mkdir -p .local-runtime/tls
if [[ ! -f .local-runtime/tls/localhost.pem || ! -f .local-runtime/tls/localhost-key.pem ]]; then
  mkcert -cert-file .local-runtime/tls/localhost.pem -key-file .local-runtime/tls/localhost-key.pem localhost 127.0.0.1 ::1
  chmod 600 .local-runtime/tls/localhost-key.pem
fi
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.https.yml up -d --build frontend backend local-https
echo 'Open https://localhost:3443. If the certificate is not trusted, run mkcert -install and approve the macOS prompt.'
