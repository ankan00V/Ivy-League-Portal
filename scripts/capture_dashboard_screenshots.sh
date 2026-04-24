#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${REPO_ROOT}/docs/portfolio/screenshots"
BASE_URL="${BASE_URL:-https://web.test}"

mkdir -p "${OUTPUT_DIR}"

if ! command -v node >/dev/null 2>&1; then
  echo "node is required" >&2
  exit 1
fi

echo "[screenshots] base url: ${BASE_URL}"
echo "[screenshots] output dir: ${OUTPUT_DIR}"

cd "${REPO_ROOT}"

node <<'EOF'
const fs = require('fs');
const path = require('path');

const root = process.cwd();
const outputDir = path.join(root, 'docs', 'portfolio', 'screenshots');
const baseUrl = process.env.BASE_URL || 'https://web.test';
const authToken = process.env.AUTH_TOKEN || '';

const candidates = [
  { name: '01_home.png', path: '/' },
  { name: '02_recommended_feed.png', path: '/opportunities' },
  { name: '03_ask_ai.png', path: '/opportunities' },
  { name: '04_employer_dashboard.png', path: '/employer' },
  { name: '05_experiment_analytics.png', path: '/admin/experiments' },
  { name: '06_auth_audit.png', path: '/admin/auth-audit' },
];

async function main() {
  const { chromium } = require(path.join(root, 'frontend', 'node_modules', 'playwright'));
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1720, height: 980 } });
  const page = await context.newPage();

  if (authToken) {
    await page.addInitScript((token) => {
      try {
        const now = Date.now();
        localStorage.setItem('auth_session_present', '1');
        localStorage.setItem('access_token_expires_at', String(now + 24 * 60 * 60 * 1000));
        const originalFetch = window.fetch.bind(window);
        window.fetch = (input, init = {}) => {
          const headers = new Headers(init.headers || {});
          const currentAuth = headers.get('Authorization');
          if (!currentAuth || currentAuth.includes('__cookie_session__')) {
            headers.set('Authorization', `Bearer ${token}`);
          }
          return originalFetch(input, { ...init, headers });
        };
      } catch (_) {}
    }, authToken);
  }

  for (const entry of candidates) {
    const url = new URL(entry.path, baseUrl).toString();
    try {
      await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
      await page.screenshot({ path: path.join(outputDir, entry.name), fullPage: true });
      console.log(`[ok] ${entry.name} <- ${url}`);
    } catch (err) {
      console.log(`[skip] ${entry.name} <- ${url} (${err.message})`);
    }
  }

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
EOF

echo "[screenshots] done"
