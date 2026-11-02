"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import { neonAuthClient } from "@/lib/neon-auth-client";
import { getUnknownErrorMessage } from "@/lib/error-utils";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const result = await neonAuthClient.requestPasswordReset({
        email: email.trim().toLowerCase(),
        redirectTo: `${window.location.origin}/reset-password`,
      });
      if (result.error) throw result.error;
      // Keep this response non-enumerable: Neon returns the same success shape
      // whether or not an account exists for the address.
      setSent(true);
    } catch (cause) {
      setError(getUnknownErrorMessage(cause, "We could not request a reset link. Please try again."));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-page-shell">
      <section className="card-panel auth-shell auth-verify-shell" aria-labelledby="forgot-password-heading">
        <section className="auth-right-pane">
          <BrandLogo />
          <div className="auth-form-intro">
            <h1 id="forgot-password-heading">Reset your password</h1>
            <p>Enter the email address on your VidyaVerse account. We&apos;ll send a secure reset link.</p>
          </div>
          {sent ? (
            <p className="auth-message" role="status">
              If an account exists for that address, a password-reset link is on its way. Check your inbox and spam folder.
            </p>
          ) : (
            <form onSubmit={handleSubmit} className="auth-form-stack">
              <label>Email<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} disabled={loading} required /></label>
              {error ? <p className="auth-message auth-message-error" role="alert">{error}</p> : null}
              <button type="submit" className="auth-primary-button" disabled={loading}>{loading ? "Sending reset link..." : "Send reset link"}</button>
            </form>
          )}
          <p className="auth-switch-row"><Link href="/login">Back to sign in</Link></p>
        </section>
      </section>
    </main>
  );
}
