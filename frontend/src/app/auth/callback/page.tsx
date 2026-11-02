"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import React, { Suspense, useEffect, useMemo, useState } from "react";

import { resolvePostAuthRoute, setAccessToken } from "@/lib/auth-session";
import { establishApplicationSession } from "@/lib/neon-auth-bridge";
import { neonAuthClient } from "@/lib/neon-auth-client";

function OAuthCallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const token = useMemo(() => searchParams.get("access_token") || "", [searchParams]);
  const callbackError = useMemo(() => searchParams.get("error") || "", [searchParams]);
  const message = useMemo(() => searchParams.get("message") || "", [searchParams]);
  const requestedNext = useMemo(() => searchParams.get("next") || "", [searchParams]);
  const [completionError, setCompletionError] = useState("");
  const error = useMemo(() => {
    if (callbackError) {
      return message || callbackError || "OAuth sign-in failed.";
    }
    return completionError || null;
  }, [callbackError, completionError, message]);
  const status = error ? "Unable to complete sign-in." : "Completing sign-in...";

  useEffect(() => {
    if (error) {
      return;
    }

    let cancelled = false;
    const run = async () => {
      if (token) {
        setAccessToken(token);
        const nextRoute = await resolvePostAuthRoute(
          token,
          requestedNext && requestedNext.startsWith("/") && requestedNext !== "/auth/callback"
            ? requestedNext
            : null,
        );
        if (!cancelled) {
          router.replace(nextRoute);
        }
        return;
      }
      const { data, error: sessionError } = await neonAuthClient.getSession();
      if (sessionError || !data?.user) {
        throw new Error("Google sign-in did not create a session. Please try again.");
      }
      if (!data.user.emailVerified) {
        if (!cancelled) router.replace(`/verify-email?email=${encodeURIComponent(data.user.email || "")}`);
        return;
      }
      const appToken = await establishApplicationSession();
      const nextRoute = await resolvePostAuthRoute(
        appToken,
        requestedNext && requestedNext.startsWith("/") && requestedNext !== "/auth/callback"
          ? requestedNext
          : null,
      );
      if (!cancelled) {
        router.replace(nextRoute);
      }
    };
    void run().catch((cause) => {
      if (!cancelled) {
        setCompletionError(cause instanceof Error ? cause.message : "Unable to complete Google sign-in.");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [error, requestedNext, router, token]);

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "var(--bg-base)",
        padding: "2rem",
      }}
    >
      <section className="card-panel" style={{ width: "100%", maxWidth: "560px", padding: "2rem" }}>
        <h1 style={{ marginBottom: "0.75rem", fontSize: "1.75rem" }}>OAuth Callback</h1>
        <p style={{ color: "var(--text-secondary)", marginBottom: "1.5rem" }}>{status}</p>
        {error ? (
          <div
            style={{
              border: "2px solid #ef4444",
              borderRadius: "var(--radius-sm)",
              padding: "0.875rem",
              background: "rgba(239, 68, 68, 0.08)",
              color: "#ef4444",
              marginBottom: "1rem",
            }}
          >
            {error}
          </div>
        ) : (
          <p style={{ color: "var(--text-secondary)" }}>Please wait while we secure your session.</p>
        )}
        <Link href="/login" style={{ color: "var(--brand-primary)", fontWeight: 700 }}>
          Go back to login
        </Link>
      </section>
    </main>
  );
}

function CallbackLoadingFallback() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "var(--bg-base)",
        padding: "2rem",
      }}
    >
      <section className="card-panel" style={{ width: "100%", maxWidth: "560px", padding: "2rem" }}>
        <h1 style={{ marginBottom: "0.75rem", fontSize: "1.75rem" }}>OAuth Callback</h1>
        <p style={{ color: "var(--text-secondary)", marginBottom: "1.5rem" }}>Completing sign-in...</p>
      </section>
    </main>
  );
}

export default function OAuthCallbackPage() {
  return (
    <Suspense fallback={<CallbackLoadingFallback />}>
      <OAuthCallbackInner />
    </Suspense>
  );
}
