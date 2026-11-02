"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import PasswordStrengthMeter from "@/components/PasswordStrengthMeter";
import { verificationCallbackURL } from "@/lib/email-verification";
import { neonAuthClient } from "@/lib/neon-auth-client";
import { getUnknownErrorMessage } from "@/lib/error-utils";
import { evaluatePasswordStrength } from "@/lib/password-strength";

function readableAuthError(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = String(error.message || "").trim();
    if (message) return message;
  }
  return getUnknownErrorMessage(error, fallback);
}

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const passwordStrength = useMemo(() => evaluatePasswordStrength(password), [password]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!name.trim()) {
      setError("Enter your name to create your profile.");
      return;
    }
    if (!passwordStrength.acceptable) {
      setError("Use at least 8 characters with uppercase, lowercase, and a number.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Password confirmation does not match.");
      return;
    }

    setLoading(true);
    try {
      const normalizedEmail = email.trim().toLowerCase();
      const result = await neonAuthClient.signUp.email({
        name: name.trim(),
        email: normalizedEmail,
        password,
        callbackURL: verificationCallbackURL(window.location.origin, normalizedEmail),
      });
      if (result.error) throw result.error;
      // Keep a tab-local fallback for older links. New callbacks also carry the
      // address as a prefill hint because mail clients often open a new tab.
      window.sessionStorage.setItem("vidyaverse_pending_verification_email", normalizedEmail);
      // Neon Auth now requires a verification link at sign-up. Do not bridge a
      // pending identity into the application before the mailbox is proven.
      router.replace(`/verify-email?email=${encodeURIComponent(normalizedEmail)}`);
    } catch (cause) {
      setError(readableAuthError(cause, "We could not create your account. Please try again."));
    } finally {
      setLoading(false);
    }
  }

  async function continueWithGoogle() {
    setLoading(true);
    setError(null);
    try {
      const result = await neonAuthClient.signIn.social({
        provider: "google",
        callbackURL: `${window.location.origin}/auth/callback?next=/onboarding`,
      });
      if (result.error) throw result.error;
    } catch (cause) {
      setError(readableAuthError(cause, "Google sign-up could not be started. Please try again."));
      setLoading(false);
    }
  }

  return (
    <main className="auth-page-shell">
      <section className="card-panel auth-shell" aria-labelledby="register-heading">
        <aside className="auth-left-pane">
          <BrandLogo />
          <div className="auth-image-frame">
            <Image src="/auth/signup-candidate.jpg" alt="Student preparing for a new opportunity" fill priority sizes="(max-width: 900px) 0px, 50vw" style={{ objectFit: "cover" }} />
          </div>
          <div>
            <h1 id="register-heading">Build your opportunity edge.</h1>
            <p>One secure account for internships, competitions, and the work that moves your career forward.</p>
          </div>
        </aside>

        <section className="auth-right-pane">
          <div className="auth-form-intro">
            <h2>Create your account</h2>
            <p>Use the email you check most—Gmail and college email addresses both work. We&apos;ll send a verification link before creating your VidyaVerse session.</p>
          </div>
          <button type="button" className="auth-oauth-button" onClick={() => void continueWithGoogle()} disabled={loading}>
            <span aria-hidden="true" className="auth-google-mark">G</span>
            Continue with Google
          </button>
          <p className="auth-divider" aria-hidden="true"><span />or<span /></p>
          <form onSubmit={handleSubmit} className="auth-form-stack">
            <label>Full name<input autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} disabled={loading} required /></label>
            <label>Email<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} disabled={loading} required /></label>
            <label>Password<input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={loading} required /></label>
            <PasswordStrengthMeter strength={passwordStrength} compact />
            <label>Confirm password<input type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} disabled={loading} required /></label>
            <p className="auth-form-helper">By continuing, you agree to the <Link href="/terms">Terms</Link> and <Link href="/privacy">Privacy Policy</Link>.</p>
            {error ? <p className="auth-message auth-message-error" role="alert">{error}</p> : null}
            <button type="submit" className="auth-primary-button" disabled={loading}>{loading ? "Creating account..." : "Create account"}</button>
          </form>
          <p className="auth-switch-row">Already have an account? <Link href="/login">Sign in</Link></p>
        </section>
      </section>
    </main>
  );
}
