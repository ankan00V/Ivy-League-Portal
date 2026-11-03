// Integration regression: actual Next.js routes + Neon SDK + WebKit cookies.
// Neon and FastAPI are controlled HTTP fixtures, not browser-intercepted routes.
// This does not validate delivery by the live SMTP provider or Google consent.
import assert from 'node:assert/strict';
import { createHmac, randomBytes } from 'node:crypto';
import http from 'node:http';
import https from 'node:https';
import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { webkit } from 'playwright';

const root = fileURLToPath(new URL('../../', import.meta.url));
const bridgeSecret = randomBytes(32).toString('hex');
let verified = false;
let callbackURL;
let bridgeCount = 0;
const user = () => ({ id: 'transport-test', name: 'Transport Test', email: 'transport@example.com', emailVerified: verified });
const session = () => ({ user: user(), session: { id: 'test-session', token: 'fixture-session', userId: 'transport-test', expiresAt: new Date(Date.now() + 3600000).toISOString() } });
const json = (res, data, status = 200) => { res.writeHead(status, { 'content-type': 'application/json' }); res.end(JSON.stringify(data)); };
const servers = [];
let child;
let browser;
async function listen(server) {
  servers.push(server);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return server.address().port;
}

try {
  const fixturePort = await listen(http.createServer(async (req, res) => {
    const path = new URL(req.url, 'http://fixture').pathname;
    const authenticated = (req.headers.cookie || '').includes('__Secure-neon-auth.session_token=fixture-session');
    if (path === '/auth/get-session') return json(res, authenticated ? session() : null);
    if (path === '/auth/sign-up/email') {
      let body = '';
      for await (const chunk of req) body += chunk;
      callbackURL = JSON.parse(body).callbackURL;
      return json(res, { user: user(), token: null });
    }
    if (path === '/auth/verify-email') {
      verified = true;
      res.writeHead(302, { location: callbackURL });
      return res.end();
    }
    if (path === '/auth/sign-in/email') {
      if (!verified) return json(res, { code: 'EMAIL_NOT_VERIFIED', message: 'Verify your email first.' }, 403);
      res.setHeader('set-cookie', '__Secure-neon-auth.session_token=fixture-session; Path=/; HttpOnly; Secure; SameSite=Lax');
      return json(res, { user: user(), token: 'fixture-session' });
    }
    if (path === '/api/v1/auth/neon/exchange') {
      const [payload, signature] = String(req.headers['x-neon-bridge-credential'] || '').split('.');
      if (!payload || signature !== createHmac('sha256', bridgeSecret).update(payload).digest('base64url')) return json(res, {}, 401);
      const claims = JSON.parse(Buffer.from(payload, 'base64url'));
      if (claims.sub !== 'transport-test' || claims.aud !== 'vidyaverse-backend' || claims.exp <= Date.now() / 1000) return json(res, {}, 401);
      bridgeCount++;
      res.setHeader('set-cookie', 'vidyaverse_session=fixture-app-session; Path=/; HttpOnly; Secure; SameSite=Lax');
      return json(res, { access_token: 'fixture-app-token' });
    }
    if (path === '/api/v1/users/me') return json(res, { id: 'test-user', is_admin: false });
    if (path === '/api/v1/users/me/profile') return json(res, { account_type: 'candidate', first_name: 'Transport', last_name: 'Test', country_code: '+91' });
    if (path === '/api/v1/users/me/onboarding-status') return json(res, { completed: false, progress_percent: 8, missing_fields: ['mobile'], recommended_next_step: 'identity' });
    return json(res, {});
  }));
  const portProbe = http.createServer();
  const appPort = await listen(portProbe);
  await new Promise(resolve => portProbe.close(resolve));
  child = spawn(process.execPath, ['.next/standalone/server.js'], {
    cwd: `${root}frontend`,
    env: { ...process.env, NODE_ENV: 'production', HOSTNAME: '127.0.0.1', PORT: String(appPort), LOCAL_HTTPS_ORIGIN: '', NEON_AUTH_BASE_URL: `http://127.0.0.1:${fixturePort}/auth`, NEON_AUTH_COOKIE_SECRET: randomBytes(32).toString('hex'), NEON_AUTH_BRIDGE_SECRET: bridgeSecret, BACKEND_INTERNAL_URL: `http://127.0.0.1:${fixturePort}` },
    stdio: 'ignore',
  });
  let ready = false;
  for (let i = 0; i < 100; i++) {
    if (child.exitCode !== null) throw new Error('Fixture Next.js server exited before becoming ready');
    if (await fetch(`http://127.0.0.1:${appPort}/api/health`).then(r => r.ok).catch(() => false)) { ready = true; break; }
    await delay(100);
  }
  assert(ready, 'Fixture app must start');
  const tlsPort = await listen(https.createServer({
    cert: readFileSync(`${root}.local-runtime/tls/localhost.pem`),
    key: readFileSync(`${root}.local-runtime/tls/localhost-key.pem`),
  }, (req, res) => {
    const upstream = http.request({ hostname: '127.0.0.1', port: appPort, path: req.url, method: req.method, headers: { ...req.headers, 'x-forwarded-proto': 'https' } }, reply => {
      res.writeHead(reply.statusCode, reply.headers);
      reply.pipe(res);
    });
    upstream.on('error', () => { res.writeHead(502); res.end(); });
    req.pipe(upstream);
  }));
  browser = await webkit.launch();
  // Certificate validation is tested separately against the local trust store.
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const origin = `https://127.0.0.1:${tlsPort}`;
  await page.goto(`${origin}/register`);
  await page.getByLabel('Full name').fill('Transport Test');
  await page.getByLabel('Email').fill('transport@example.com');
  await page.getByLabel('Password', { exact: true }).fill('StrongPass1');
  await page.getByLabel('Confirm password').fill('StrongPass1');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await page.waitForURL(/\/verify-email\?email=/);
  assert.equal(new URL(callbackURL).searchParams.get('email'), 'transport@example.com');
  assert.equal(bridgeCount, 0, 'Unverified signup must not create an app session');
  const linkTab = await context.newPage();
  await linkTab.goto(`http://127.0.0.1:${fixturePort}/auth/verify-email`);
  await linkTab.waitForURL(/\/login\?continue=setup/);
  assert.equal(await linkTab.getByLabel('Email').inputValue(), 'transport@example.com');
  await linkTab.getByLabel('Password', { exact: true }).fill('StrongPass1');
  await linkTab.getByRole('button', { name: 'Sign in', exact: true }).click();
  await linkTab.waitForURL(/\/onboarding$/);
  const cookies = await context.cookies();
  assert(cookies.some(c => c.name === '__Secure-neon-auth.session_token' && c.secure && c.httpOnly));
  assert(cookies.some(c => c.name === 'vidyaverse_session' && c.secure && c.httpOnly));
  await linkTab.reload();
  const sessionCheck = await linkTab.evaluate(async () => (await fetch('/api/auth/get-session?disableCookieCache=true')).json());
  assert.equal(sessionCheck.user.emailVerified, true);
  assert(bridgeCount > 0);
  console.log('PASS WebKit HTTPS: signup -> email link in new tab -> sign-in -> real SDK/bridge -> onboarding; HttpOnly cookies survive reload');

  const httpContext = await browser.newContext();
  const httpPage = await httpContext.newPage();
  await httpPage.goto(`http://127.0.0.1:${appPort}/login`);
  const httpStatus = await httpPage.evaluate(async () => {
    await fetch('/api/auth/sign-in/email', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ email: 'transport@example.com', password: 'StrongPass1' }) });
    return (await fetch('/api/auth/bridge', { method: 'POST' })).status;
  });
  assert.equal(httpStatus, 401, 'WebKit must reject the Secure session cookie on HTTP');
  console.log('PASS WebKit HTTP: reproduces missing Secure cookie / bridge 401; HTTPS fixes transport without weakening cookie flags');
} finally {
  await browser?.close();
  if (child && child.exitCode === null) { child.kill('SIGTERM'); await once(child, 'exit'); }
  for (const server of servers) { server.closeAllConnections(); if (server.listening) await new Promise(resolve => server.close(resolve)); }
}
