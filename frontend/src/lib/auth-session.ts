import { apiUrl } from "@/lib/api";

const ACCESS_TOKEN_KEY = "access_token";

type OnboardingStatus = {
  account_type?: "candidate" | "employer";
  onboarding_completed?: boolean;
};

export function getAccessToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function setAccessToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }
  localStorage.setItem(ACCESS_TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  if (typeof window === "undefined") {
    return;
  }
  localStorage.removeItem(ACCESS_TOKEN_KEY);
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
    if (!onboardingCompleted) {
      return "/onboarding";
    }
    return accountType === "employer" ? "/employer/dashboard" : "/dashboard";
  } catch {
    return "/dashboard";
  }
}
