"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import PasswordSetupModal from "@/components/PasswordSetupModal";
import { ADMIN_LOGIN_PATH } from "@/lib/admin-routes";
import { apiUrl } from "@/lib/api";
import {
  clearAccessToken,
  createAuthenticatedFetchInit,
  getAccessToken,
  getAccessTokenExpiry,
  getAuthStateEventName,
  hasAuthSession,
} from "@/lib/auth-session";

// `/dashboard` stays publicly viewable as a product-preview surface.
// Interactive user-specific actions inside it remain sign-in gated.
const PUBLIC_PATHS = new Set(["/", "/dashboard", "/login", "/register", "/auth/callback", ADMIN_LOGIN_PATH]);
const PASSWORD_PROMPT_EXCLUDED_PATHS = new Set(["/login", "/register", "/auth/callback", ADMIN_LOGIN_PATH]);

type CurrentUserSummary = {
  needs_password_setup?: boolean;
};

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.has(pathname);
}

export default function SessionManager() {
  const pathname = usePathname();
  const router = useRouter();
  const expiryTimerRef = useRef<number | null>(null);
  const [passwordSetupRequired, setPasswordSetupRequired] = useState(false);

  const refreshPasswordSetupState = useCallback(async (token: string | null) => {
    if (!token || PASSWORD_PROMPT_EXCLUDED_PATHS.has(pathname)) {
      setPasswordSetupRequired(false);
      return;
    }

    try {
      const response = await fetch(
        apiUrl("/api/v1/users/me"),
        createAuthenticatedFetchInit({}, token),
      );
      if (!response.ok) {
        setPasswordSetupRequired(false);
        return;
      }
      const user = (await response.json()) as CurrentUserSummary;
      setPasswordSetupRequired(Boolean(user.needs_password_setup));
    } catch {
      setPasswordSetupRequired(false);
    }
  }, [pathname]);

  useEffect(() => {
    const stopExpiryTimer = () => {
      if (expiryTimerRef.current !== null) {
        window.clearTimeout(expiryTimerRef.current);
        expiryTimerRef.current = null;
      }
    };

    const redirectIfProtected = () => {
      if (!isPublicPath(pathname)) {
        router.replace("/login");
      }
    };

    const syncSession = () => {
      const token = getAccessToken();
      const hasSession = hasAuthSession();
      const expiresAt = getAccessTokenExpiry();

      stopExpiryTimer();

      if ((!token && !hasSession) || !expiresAt) {
        setPasswordSetupRequired(false);
        redirectIfProtected();
        return;
      }

      const remainingMs = expiresAt - Date.now();
      if (remainingMs <= 0) {
        setPasswordSetupRequired(false);
        clearAccessToken("expired");
        redirectIfProtected();
        return;
      }

      void refreshPasswordSetupState(token);
      expiryTimerRef.current = window.setTimeout(() => {
        setPasswordSetupRequired(false);
        clearAccessToken("expired");
        redirectIfProtected();
      }, remainingMs);
    };

    const authStateEventName = getAuthStateEventName();

    syncSession();
    window.addEventListener("focus", syncSession);
    window.addEventListener("storage", syncSession);
    document.addEventListener("visibilitychange", syncSession);
    window.addEventListener(authStateEventName, syncSession);

    return () => {
      stopExpiryTimer();
      window.removeEventListener("focus", syncSession);
      window.removeEventListener("storage", syncSession);
      document.removeEventListener("visibilitychange", syncSession);
      window.removeEventListener(authStateEventName, syncSession);
    };
  }, [pathname, refreshPasswordSetupState, router]);

  return <PasswordSetupModal open={passwordSetupRequired} onComplete={() => setPasswordSetupRequired(false)} />;
}
