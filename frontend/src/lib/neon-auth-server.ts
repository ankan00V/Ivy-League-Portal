import "server-only";

import { createNeonAuth } from "@neon/auth/next/server";

/**
 * Build the managed-auth server adapter only when a request reaches an auth
 * route. This keeps `next build` deterministic in CI images, where runtime
 * secrets are intentionally not baked into the frontend layer.
 */
export function getNeonAuth() {
  const baseUrl = process.env.NEON_AUTH_BASE_URL?.trim();
  const cookieSecret = process.env.NEON_AUTH_COOKIE_SECRET?.trim();

  if (!baseUrl || !cookieSecret) {
    throw new Error("Neon Auth is not configured. Set NEON_AUTH_BASE_URL and NEON_AUTH_COOKIE_SECRET.");
  }

  return createNeonAuth({
    baseUrl,
    cookies: {
      secret: cookieSecret,
      sessionDataTtl: 300,
    },
  });
}
