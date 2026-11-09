"use client";

import { createAuthClient } from "@neon/auth/next";

// The Next.js SDK deliberately takes no URL here: requests go through the
// same-origin /api/auth proxy, so the managed Neon endpoint stays server-side.
export const neonAuthClient = createAuthClient();
