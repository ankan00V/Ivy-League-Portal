"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import { establishApplicationSession } from "@/lib/neon-auth-bridge";
import { neonAuthClient } from "@/lib/neon-auth-client";
import { resolvePostAuthRoute } from "@/lib/auth-session";
import { getUnknownErrorMessage } from "@/lib/error-utils";
import { verificationCallbackURL } from "@/lib/email-verification";
import { AUTH_FETCH_OPTIONS } from "@/lib/auth-network";

type ManagedUser = { email?: string; emailVerified?: boolean };

const PENDING_EMAIL_KEY = "vidyaverse_pending_verification_email";
const RESEND_COOLDOWN_SECONDS = 60;

function normalizeEmail(value: string | null | undefined): string {
  return String(value || "").trim().toLowerCase();
}

export default function VerifyEmailPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryEmail = normalizeEmail(searchParams.get("email"));
  const returnedFromLink = searchParams.get("returned") === "1";
  const linkError = searchParams.get("error");
  const [pendingEmail, setPendingEmail] = useState(queryEmail);
  const [checking, setChecking] = useState(false);
  const [resending, setResending] = useState(false);
  const [resendAvailableAt, setResendAvailableAt] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [message, setMessage] = useState(
    "We sent a verification link to your inbox. Open it to confirm your email, then continue to sign in and complete your profile.",
  );
  const [error, setError] = useState<string | null>(linkError
    ? "This verification link is invalid or has expired. Request a new link below."
    : null);
  const completionInProgress = useRef(false);

  const email = useMemo(() => queryEmail || pendingEmail, [pendingEmail, queryEmail]);
  const resendSeconds = Math.max(0, Math.ceil((resendAvailableAt - now) / 1000));
  const signInURL = `/login?continue=setup${email ? `&email=${encodeURIComponent(email)}` : ""}`;

  useEffect(() => {
    if (queryEmail) {
      window.sessionStorage.setItem(PENDING_EMAIL_KEY, queryEmail);
      return;
    }
    const remembered = normalizeEmail(window.sessionStorage.getItem(PENDING_EMAIL_KEY));
    if (remembered) {
      // Browser-only storage is read after hydration; the query stays the
      // primary source and this one-time update supports previously sent links.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPendingEmail(remembered);
    }
  }, [queryEmail]);

  useEffect(() => {
    if (resendSeconds <= 0) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [resendSeconds]);

  async function finishVerifiedSession() {
    if (completionInProgress.current) return;
    completionInProgress.current = true;
    setChecking(true);
    setError(null);
    try {
      // The link updates Neon in another tab. Do not reuse a cached
      // emailVerified=false response after the mailbox has been confirmed.
      const result = await neonAuthClient.getSession({ query: { disableCookieCache: true }, fetchOptions: AUTH_FETCH_OPTIONS });
      if (result.error) throw result.error;
      const user = result.data?.user as ManagedUser | undefined;
      const sessionEmail = normalizeEmail(user?.email);
      if (email && sessionEmail && email !== sessionEmail) {
        throw new Error("A different account is signed in in this browser. Sign out of that account before continuing with this email.");
      }
      if (sessionEmail) {
        window.sessionStorage.setItem(PENDING_EMAIL_KEY, sessionEmail);
        setPendingEmail(sessionEmail);
      }
      if (!user) {
        // Email verification does not necessarily create a sign-in session.
        // No session is not evidence that the email is still unverified.
        router.replace(signInURL);
        return;
      }
      if (!user.emailVerified) {
        setMessage("Your email is not verified yet. Open the newest verification link, then select this button again.");
        completionInProgress.current = false;
        return;
      }
      const token = await establishApplicationSession();
      window.sessionStorage.removeItem(PENDING_EMAIL_KEY);
      router.replace(await resolvePostAuthRoute(token));
    } catch (cause) {
      setError(getUnknownErrorMessage(cause, "We could not finish setting up your account. Please try again."));
      completionInProgress.current = false;
    } finally {
      setChecking(false);
    }
  }

  useEffect(() => {
    let active = true;
    if (linkError) return;
    void (async () => {
      try {
        const result = await neonAuthClient.getSession({ query: { disableCookieCache: true }, fetchOptions: AUTH_FETCH_OPTIONS });
        if (active && (returnedFromLink || result.data?.user?.emailVerified)) {
          await finishVerifiedSession();
        }
      } catch {
        // The explicit primary action remains available if the auth service is
        // briefly unavailable while this page first renders.
      }
    })();
    return () => {
      active = false;
    };
  // Run once: finishVerifiedSession intentionally changes UI state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [returnedFromLink, linkError]);

  async function resendVerificationLink() {
    if (!email || resendSeconds > 0) return;
    setResending(true);
    setError(null);
    try {
      const result = await neonAuthClient.sendVerificationEmail({
        email,
        callbackURL: verificationCallbackURL(window.location.origin, email),
        fetchOptions: AUTH_FETCH_OPTIONS,
      });
      if (result.error) throw result.error;
      setResendAvailableAt(Date.now() + RESEND_COOLDOWN_SECONDS * 1_000);
      setNow(Date.now());
      setMessage("A fresh verification link is on its way. Use the newest email, and check spam if you do not see it shortly.");
    } catch (cause) {
      setError(getUnknownErrorMessage(cause, "We could not resend the verification link. Please try again."));
    } finally {
      setResending(false);
    }
  }

  return (
    <main className="auth-page-shell">
      <section className="card-panel auth-shell auth-verify-shell" aria-labelledby="verify-email-heading">
        <section className="auth-right-pane">
          <BrandLogo />
          <div className="auth-form-intro">
            <h1 id="verify-email-heading">Verify your email</h1>
            <p>{message}</p>
            {email ? <p className="auth-verify-email-address">{email}</p> : null}
          </div>
          {error ? <p className="auth-message auth-message-error" role="alert">{error}</p> : null}
          <button type="button" className="auth-primary-button" onClick={() => void finishVerifiedSession()} disabled={checking}>
            {checking ? "Checking verification..." : "I verified my email — continue"}
          </button>
          {email ? <p className="auth-resend-row">
            Didn&apos;t receive the link?{" "}
            <button type="button" className="auth-resend-link" onClick={() => void resendVerificationLink()} disabled={!email || resending || resendSeconds > 0}>
              {resending ? "Sending..." : resendSeconds > 0 ? `Resend in ${resendSeconds}s` : "Resend verification link"}
            </button>
          </p> : <p className="auth-form-helper">To request another link, sign in with the email you used to create your account.</p>}
          <p className="auth-switch-row">
            Already verified? <Link href={signInURL}>Sign in</Link>
            {" · "}<Link href="/register">Use a different email</Link>
          </p>
        </section>
      </section>
    </main>
  );
}
