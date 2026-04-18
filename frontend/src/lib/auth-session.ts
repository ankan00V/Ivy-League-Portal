import { apiUrl } from "@/lib/api";

const ACCESS_TOKEN_KEY = "access_token";

type OnboardingStatus = {
  completed: boolean;
  progress_percent?: number;
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
    const res = await fetch(apiUrl("/api/v1/users/me/onboarding-status"), {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      return "/dashboard";
    }
    const status = (await res.json()) as OnboardingStatus;
    if (!status.completed) {
      return "/onboarding";
    }
    return "/dashboard";
  } catch {
    return "/dashboard";
  }
}
