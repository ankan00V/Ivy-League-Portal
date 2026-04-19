import { apiUrl } from "@/lib/api";

export const ACCESS_TOKEN_KEY = "access_token";
export const ACCESS_TOKEN_EXPIRES_AT_KEY = "access_token_expires_at";
export const AUTH_STATE_EVENT = "auth-state-changed";
export const ACCESS_TOKEN_LIFETIME_MS = 24 * 60 * 60 * 1000;

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
}

function clearStoredAuth(reason: AuthStateReason): void {
  removeStoredAuth();
  dispatchAuthState(reason);
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
  const token = localStorage.getItem(ACCESS_TOKEN_KEY);
  if (!token) {
    localStorage.removeItem(ACCESS_TOKEN_EXPIRES_AT_KEY);
    return null;
  }
  const expiresAt = getAccessTokenExpiry();
  if (!expiresAt) {
    // Backward compatibility for sessions created before expiry tracking existed.
    localStorage.setItem(
      ACCESS_TOKEN_EXPIRES_AT_KEY,
      String(Date.now() + ACCESS_TOKEN_LIFETIME_MS),
    );
    return token;
  }
  if (expiresAt <= Date.now()) {
    removeStoredAuth();
    return null;
  }
  return token;
}

export function setAccessToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }
  localStorage.setItem(ACCESS_TOKEN_KEY, token);
  localStorage.setItem(
    ACCESS_TOKEN_EXPIRES_AT_KEY,
    String(Date.now() + ACCESS_TOKEN_LIFETIME_MS),
  );
  dispatchAuthState("login");
}

export function clearAccessToken(reason: AuthStateReason = "logout"): void {
  if (typeof window === "undefined") {
    return;
  }
  clearStoredAuth(reason);
}

export function getAuthStateEventName(): string {
  return AUTH_STATE_EVENT;
}

export async function resolvePostAuthRoute(token: string): Promise<string> {
  try {
    const res = await fetch(apiUrl("/api/v1/users/me/profile"), {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      return "/dashboard";
    }
    const status = (await res.json()) as OnboardingStatus;
    const accountType = String(status.account_type || "candidate").toLowerCase();
    const onboardingCompleted = Boolean(status.onboarding_completed);
    const onboardingPromptSeen = Boolean(status.onboarding_prompt_seen);
    if (!onboardingCompleted) {
      if (!onboardingPromptSeen) {
        try {
          await fetch(apiUrl("/api/v1/users/me/onboarding/mark-seen"), {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
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
