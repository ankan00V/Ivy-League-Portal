# Frontend

This is the Next.js frontend for VidyaVerse.

## Main Screens

- `/` landing page with Spline hero
- `/register` OTP signup
- `/login` OTP signin
- `/dashboard` profile summary, recommendations, activity
- `/opportunities` primary opportunity feed with Ask AI
- `/internships-jobs` alternate route into the opportunity feed
- `/applications` application status table
- `/leaderboard` InCoScore rankings
- `/social` social feed and comments
- `/experiments` admin reporting surface

## Development

Install dependencies and start the dev server:

```bash
npm install
npm run dev -- --hostname 0.0.0.0
```

Default local URL: [http://localhost:3000](http://localhost:3000)

## API Behavior

The frontend uses `src/lib/api.ts` plus `src/app/api/[...path]/route.ts` to decide how to reach the backend.

### Default mode
- Leave `NEXT_PUBLIC_API_BASE_URL` unset.
- Browser requests go through the frontend proxy at `/api/...`.
- The proxy falls back to `http://127.0.0.1:8000` and `http://localhost:8000`.

### Explicit backend mode
- Set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`
- Optionally set `BACKEND_INTERNAL_URL=http://localhost:8000`

This proxy setup is especially useful when the frontend is served via `https://web.test` through `slim` while the backend still runs locally on plain HTTP.

## Auth Session Mode

- Backend now issues an HttpOnly session cookie on successful OTP/password/OAuth login.
- Frontend no longer persists bearer tokens in `localStorage`; auth state uses cookie session + non-sensitive session marker.
- Existing bearer header logic remains backward-compatible during migration, but session cookie is the primary auth mechanism.
- Frontend responses now include nonce-based strict `script-src` CSP + enforced Trusted Types security headers from `src/proxy.ts`.

## Preferred Local Hosting

Once the backend is running on port `8000`, map local domains with:

```bash
slim start web --port 3000
slim start api --port 8000
```

That gives:
- `https://web.test`
- `https://api.test`

## Notes

- `allowedDevOrigins` in `next.config.ts` already includes `web.test`.
- Opportunity surfaces now enforce tracking metadata for interaction logs:
  - `ranking_mode`, `experiment_key`, `experiment_variant`, `rank_position`
  - Ask AI shortlist cards and citation clicks are logged with `experiment_key=ask_ai_rag`.
- The opportunity pages expect a live backend for recommendations, interactions, social content, and Ask AI.
- If the backend is unavailable, the UI falls back where possible and surfaces retry notices on the opportunities feed.

## E2E Checks

Playwright tests validate interaction payload contracts across feed and Ask AI surfaces.

```bash
npm install
npx playwright install chromium
npm run e2e
```

Integrated live-backend smoke (no mocked API routes):

```bash
PLAYWRIGHT_LIVE_BACKEND=1 npm run e2e -- --grep "Live backend smoke"
```

Integrated staging auth + protected-flow checks (no mocked API routes):

```bash
PLAYWRIGHT_STAGING_URL=https://your-staging-web-domain.com \
PLAYWRIGHT_INTEGRATED_AUTH=1 \
npm run e2e:staging
```

Required seeded staging role checks use:
- `PLAYWRIGHT_STAGING_ADMIN_EMAIL`
- `PLAYWRIGHT_STAGING_ADMIN_PASSWORD`
- `PLAYWRIGHT_STAGING_EMPLOYER_EMAIL`
- `PLAYWRIGHT_STAGING_EMPLOYER_PASSWORD`
