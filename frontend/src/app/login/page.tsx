"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import { establishApplicationSession } from "@/lib/neon-auth-bridge";
import { neonAuthClient } from "@/lib/neon-auth-client";
import { resolvePostAuthRoute } from "@/lib/auth-session";
import { getUnknownErrorMessage } from "@/lib/error-utils";
import { AUTH_FETCH_OPTIONS } from "@/lib/auth-network";

function safeNext(value: string | null): string {
  const candidate = String(value || "").trim();
  return candidate.startsWith("/") && !candidate.startsWith("//") && !/[\\\u0000-\u001f]/.test(candidate) ? candidate : "/dashboard";
}

function readableAuthError(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = String(error.message || "").trim();
    if (message) return message;
  }
  return getUnknownErrorMessage(error, fallback);
}

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState(() => String(searchParams.get("email") || "").trim().toLowerCase());
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [canRetrySession, setCanRetrySession] = useState(false);
  const requestedNext = searchParams.get("next");
  const destination = safeNext(requestedNext);

  async function resolveDestination(token: string): Promise<string> {
    return resolvePostAuthRoute(
      token,
      requestedNext && safeNext(requestedNext) !== "/dashboard" ? destination : null,
    );
  }

  async function continueExistingSession() {
    setCheckingSession(true);
    setError(null);
    try {
      const { data, error: sessionError } = await neonAuthClient.getSession({ query: { disableCookieCache: true }, fetchOptions: AUTH_FETCH_OPTIONS });
      if (sessionError || !data?.user) {
        setCanRetrySession(false);
        throw new Error("Your secure sign-in session has expired. Please sign in again.");
      }
      if (!data.user.emailVerified) {
        router.replace(`/verify-email?email=${encodeURIComponent(data.user.email || "")}`);
        return;
      }
      setCanRetrySession(true);
      const token = await establishApplicationSession();
      router.replace(await resolveDestination(token));
    } catch (cause) {
      setError(readableAuthError(cause, "We could not finish preparing your account. Please retry."));
    } finally {
      setCheckingSession(false);
    }
  }

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const { data, error: sessionError } = await neonAuthClient.getSession({ query: { disableCookieCache: true }, fetchOptions: AUTH_FETCH_OPTIONS });
        if (sessionError) throw sessionError;
        if (active && data?.user) {
          if (!data.user.emailVerified) {
            router.replace(`/verify-email?email=${encodeURIComponent(data.user.email || "")}`);
            return;
          }
          setCanRetrySession(true);
          const token = await establishApplicationSession();
          const next = await resolveDestination(token);
          if (active) router.replace(next);
          return;
        }
      } catch (cause) {
        if (active) {
          setError(readableAuthError(cause, "We could not restore your secure session. Please retry."));
        }
      } finally {
        if (active) setCheckingSession(false);
      }
    })();
    return () => { active = false; };
  // `continueExistingSession` intentionally is not a dependency: making this
  // effect depend on its state updates retried a bridge on every render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [destination, requestedNext, router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setCanRetrySession(false);
    try {
      const result = await neonAuthClient.signIn.email({ email: email.trim().toLowerCase(), password, fetchOptions: AUTH_FETCH_OPTIONS });
      if (result.error?.code === "EMAIL_NOT_VERIFIED") {
        router.replace(`/verify-email?email=${encodeURIComponent(email.trim().toLowerCase())}`);
        return;
      }
      if (result.error) throw result.error;
      if (!result.data?.user?.emailVerified) {
        router.replace(`/verify-email?email=${encodeURIComponent(email.trim().toLowerCase())}`);
        return;
      }
      // Authentication succeeded even if the profile/database service fails.
      // Keep a retry action that does not submit the password again.
      setCanRetrySession(true);
      setPassword("");
      const token = await establishApplicationSession();
      router.replace(await resolveDestination(token));
    } catch (cause) {
      setError(readableAuthError(cause, "Unable to sign in. Check your email and password, then try again."));
    } finally {
      setLoading(false);
    }
  }

  async function continueWithGoogle() {
    setLoading(true);
    setError(null);
    setCanRetrySession(false);
    try {
      const result = await neonAuthClient.signIn.social({
        provider: "google",
        fetchOptions: AUTH_FETCH_OPTIONS,
        callbackURL: `${window.location.origin}/auth/callback${requestedNext ? `?next=${encodeURIComponent(destination)}` : ""}`,
      });
      if (result.error) throw result.error;
    } catch (cause) {
      setError(readableAuthError(cause, "Google sign-in could not be started. Please try again."));
      setLoading(false);
    }
  }

  return (
    <main className="auth-page-shell">
      <section className="card-panel auth-shell" aria-labelledby="login-heading">
        <aside className="auth-left-pane">
          <BrandLogo />
          <div className="auth-image-frame">
            <Image src="/auth/login-candidate.jpg" alt="Student boarding a flight toward a new opportunity" fill priority sizes="(max-width: 900px) 0px, 50vw" style={{ objectFit: "cover" }} />
          </div>
          <div>
            <h1 id="login-heading">Compete, learn, and get hired.</h1>
            <p>Sign in once, then keep your applications, saved opportunities, and progress in one place.</p>
          </div>
        </aside>
        <section className="auth-right-pane">
          <div className="auth-form-intro"><h2>Welcome back</h2><p>Sign in with the email and password you created for VidyaVerse.</p></div>
          {searchParams.get("continue") === "setup" ? (
            <p className="auth-message" role="status">Sign in to continue your account setup. If you just opened the verification link, use the password you chose at sign-up.</p>
          ) : null}
          {checkingSession ? <p className="auth-message" role="status">Checking your secure session…</p> : (
            <>
              {error ? (
                <div className="auth-message auth-message-error" role="alert">
                  <p>{error}</p>
                  {canRetrySession ? (
                    <button type="button" className="auth-text-action" onClick={() => void continueExistingSession()} disabled={loading}>
                      Retry secure sign-in
                    </button>
                  ) : null}
                </div>
              ) : null}
              <button type="button" className="auth-oauth-button" onClick={() => void continueWithGoogle()} disabled={loading}>
                <span aria-hidden="true" className="auth-google-mark">G</span>
                Continue with Google
              </button>
              <p className="auth-divider" aria-hidden="true"><span />or<span /></p>
              <form onSubmit={handleSubmit} className="auth-form-stack">
                <label>Email<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} disabled={loading} required /></label>
                <label>
                  Password
                  <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={loading} required />
                </label>
                <Link className="auth-inline-link" href="/forgot-password">Forgot your password?</Link>
                <button type="submit" className="auth-primary-button" disabled={loading}>{loading ? "Signing in..." : "Sign in"}</button>
              </form>
            </>
          )}
          <p className="auth-switch-row">New here? <Link href="/register">Create an account</Link></p>
        </section>
      </section>
    </main>
  );
}
