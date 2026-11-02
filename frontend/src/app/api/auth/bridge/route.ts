import { createHmac } from "node:crypto";

import { getNeonAuth } from "@/lib/neon-auth-server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type ManagedUser = {
  id?: string;
  email?: string;
  name?: string | null;
  emailVerified?: boolean;
};

function base64Url(value: string): string {
  return Buffer.from(value, "utf8").toString("base64url");
}

function signedBridgeCredential(user: ManagedUser): string {
  const secret = process.env.NEON_AUTH_BRIDGE_SECRET?.trim();
  if (!secret) {
    throw new Error("NEON_AUTH_BRIDGE_SECRET is not configured.");
  }
  const now = Math.floor(Date.now() / 1000);
  const payload = base64Url(
    JSON.stringify({
      aud: "vidyaverse-backend",
      sub: user.id,
      email: user.email,
      name: user.name || null,
      iat: now,
      exp: now + 60,
    }),
  );
  const signature = createHmac("sha256", secret).update(payload).digest("base64url");
  return `${payload}.${signature}`;
}

export async function POST(request: Request) {
  try {
    const { data, error } = await getNeonAuth().getSession({ query: { disableCookieCache: "true" } });
    if (error) {
      return Response.json({ detail: "We could not check your secure session. Please retry shortly." }, { status: 503 });
    }
    const user = data?.user as ManagedUser | undefined;
    if (!user?.id || !user.email) {
      return Response.json({ detail: "Your sign-in session could not be restored. Please sign in again using the secure HTTPS address." }, { status: 401 });
    }
    if (!user.emailVerified) {
      return Response.json({ detail: "Verify your email before continuing to VidyaVerse." }, { status: 403 });
    }

    const backendUrl = (
      process.env.BACKEND_INTERNAL_URL ||
      process.env.NEXT_PUBLIC_API_BASE_URL ||
      "http://localhost:8000"
    ).replace(/\/+$/, "");

    // The application session is device-bound. The backend must see the same
    // browser fingerprint when it creates this session as it will on later API
    // requests; otherwise its own replay protection revokes a freshly-created
    // session as soon as the dashboard loads.
    const upstreamHeaders = new Headers({
      "Content-Type": "application/json",
      "X-Neon-Bridge-Credential": signedBridgeCredential(user),
    });
    for (const header of ["user-agent", "accept-language", "x-forwarded-for", "cf-connecting-ip"]) {
      const value = request.headers.get(header);
      if (value) upstreamHeaders.set(header, value);
    }
    const upstream = await fetch(`${backendUrl}/api/v1/auth/neon/exchange`, {
      method: "POST",
      headers: upstreamHeaders,
      cache: "no-store",
    });
    const body = await upstream.text();
    const headers = new Headers({
      "Content-Type": upstream.headers.get("content-type") || "application/json",
      "Cache-Control": "no-store",
    });
    // The backend issues its HttpOnly application-session and CSRF cookies on
    // this exchange. This route is the same-origin BFF boundary, so pass every
    // Set-Cookie through rather than returning only the JSON token. Without
    // these headers, client-side navigation appears to work but server-rendered
    // and subsequent protected API calls immediately become unauthorized.
    for (const cookie of upstream.headers.getSetCookie()) {
      headers.append("Set-Cookie", cookie);
    }
    return new Response(body, {
      status: upstream.status,
      headers,
    });
  } catch {
    return Response.json({ detail: "The application service is unavailable. Please retry shortly." }, { status: 503 });
  }
}
