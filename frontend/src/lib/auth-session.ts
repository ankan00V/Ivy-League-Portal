import { apiUrl } from "@/lib/api";

// Kept for backward cleanup compatibility only. Tokens are no longer persisted.
export const ACCESS_TOKEN_KEY = "access_token";
export const ACCESS_TOKEN_EXPIRES_AT_KEY = "access_token_expires_at";
export const AUTH_SESSION_PRESENT_KEY = "auth_session_present";
export const COOKIE_SESSION_SENTINEL = "__cookie_session__";
export const AUTH_STATE_EVENT = "auth-state-changed";
export const ACCESS_TOKEN_LIFETIME_MS = 24 * 60 * 60 * 1000;

let volatileAccessToken: string | null = null;

type AuthStateReason = "login" | "logout" | "expired";

type OnboardingStatus = {
  account_type?: "candidate" | "employer";
  onboarding_completed?: boolean;
  onboarding_prompt_seen?: boolean;
};

function dispatchAuthState(reason: AuthStateReason): void {
  window.dispatchEvent(new CustomEvent(AUTH_STATE_EVENT, { detail: { reason } }));
}

function removeStoredAuth(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(ACCESS_TOKEN_EXPIRES_AT_KEY);
  localStorage.removeItem(AUTH_SESSION_PRESENT_KEY);
}

function clearStoredAuth(reason: AuthStateReason): void {
  removeStoredAuth();
  volatileAccessToken = null;
  dispatchAuthState(reason);
}

function markAuthSessionPresentInternal(): void {
  localStorage.setItem(AUTH_SESSION_PRESENT_KEY, "1");
  localStorage.setItem(
    ACCESS_TOKEN_EXPIRES_AT_KEY,
    String(Date.now() + ACCESS_TOKEN_LIFETIME_MS),
  );
  localStorage.removeItem(ACCESS_TOKEN_KEY);
}

export function getAccessTokenExpiry(): number | null {
  if (typeof window === "undefined") {
    return null;
  }
  const rawExpiry = localStorage.getItem(ACCESS_TOKEN_EXPIRES_AT_KEY);
  const expiresAt = Number(rawExpiry);
  return Number.isFinite(expiresAt) && expiresAt > 0 ? expiresAt : null;
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  if (volatileAccessToken) {
    return volatileAccessToken;
  }

  const marker = localStorage.getItem(AUTH_SESSION_PRESENT_KEY);
  const expiresAt = getAccessTokenExpiry();
  if (marker !== "1" || !expiresAt || expiresAt <= Date.now()) {
    removeStoredAuth();
    return null;
  }
  return COOKIE_SESSION_SENTINEL;
}

export function hasAuthSession(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const token = getAccessToken();
  return Boolean(token);
}

export function setAccessToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }
  const normalizedToken = token && token !== COOKIE_SESSION_SENTINEL ? token : null;
  volatileAccessToken = normalizedToken;
  markAuthSessionPresentInternal();
  dispatchAuthState("login");
}

export function markAuthSessionPresent(): void {
  if (typeof window === "undefined") {
    return;
  }
  markAuthSessionPresentInternal();
  dispatchAuthState("login");
}

export function clearAccessToken(reason: AuthStateReason = "logout"): void {
  if (typeof window === "undefined") {
    return;
  }
  volatileAccessToken = null;
  void fetch(apiUrl("/api/v1/auth/logout"), {
    method: "POST",
    credentials: "include",
  }).catch(() => {
    // Best-effort cookie invalidation.
  });
  clearStoredAuth(reason);
}

export function getAuthStateEventName(): string {
  return AUTH_STATE_EVENT;
}

export async function resolvePostAuthRoute(token?: string | null): Promise<string> {
  const normalizedToken = token && token !== COOKIE_SESSION_SENTINEL ? token : null;
  const headers = normalizedToken ? { Authorization: `Bearer ${normalizedToken}` } : undefined;
  try {
    const res = await fetch(apiUrl("/api/v1/users/me/profile"), {
      credentials: "include",
      headers,
    });
    if (!res.ok) {
      return "/dashboard";
    }
    markAuthSessionPresentInternal();
    const status = (await res.json()) as OnboardingStatus;
    const accountType = String(status.account_type || "candidate").toLowerCase();
    const onboardingCompleted = Boolean(status.onboarding_completed);
    const onboardingPromptSeen = Boolean(status.onboarding_prompt_seen);
    if (!onboardingCompleted) {
      if (!onboardingPromptSeen) {
        try {
          await fetch(apiUrl("/api/v1/users/me/onboarding/mark-seen"), {
            method: "POST",
            credentials: "include",
            headers,
          });
        } catch {
          // Non-blocking best effort.
        }
        return "/onboarding";
      }
      return accountType === "employer" ? "/employer/dashboard" : "/dashboard";
    }
    return accountType === "employer" ? "/employer/dashboard" : "/dashboard";
  } catch {
    return "/dashboard";
  }
}
