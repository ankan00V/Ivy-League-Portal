"use client";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";

import {
  clearAccessToken,
  getAccessToken,
  getAccessTokenExpiry,
  getAuthStateEventName,
  hasAuthSession,
} from "@/lib/auth-session";

const PUBLIC_PATHS = new Set(["/", "/login", "/register", "/auth/callback"]);

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.has(pathname);
}

export default function SessionManager() {
  const pathname = usePathname();
  const router = useRouter();
  const expiryTimerRef = useRef<number | null>(null);

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
        redirectIfProtected();
        return;
      }

      const remainingMs = expiresAt - Date.now();
      if (remainingMs <= 0) {
        clearAccessToken("expired");
        redirectIfProtected();
        return;
      }

      expiryTimerRef.current = window.setTimeout(() => {
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
  }, [pathname, router]);

  return null;
}
