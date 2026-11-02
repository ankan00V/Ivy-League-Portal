"use client";

import { setAccessToken } from "@/lib/auth-session";
import { fetchWithTimeout } from "@/lib/auth-network";

type BridgeResponse = {
  access_token?: string;
  token_type?: string;
};

/**
 * Exchanges the authenticated Neon session for the application's existing
 * protected-API session. The browser never receives the bridge credential:
 * the Next route reads the HttpOnly Neon cookie and signs the internal request.
 */
export async function establishApplicationSession(): Promise<string> {
  const response = await fetchWithTimeout("/api/auth/bridge", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });
  const payload = (await response.json().catch(() => ({}))) as BridgeResponse & { detail?: string };
  if (!response.ok) {
    throw new Error(payload.detail || "Your account was created, but the application session could not be established.");
  }

  const token = String(payload.access_token || "").trim();
  if (!token) {
    throw new Error("The application session response did not contain an access token.");
  }
  setAccessToken(token);
  return token;
}
