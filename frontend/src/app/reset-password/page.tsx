"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import PasswordStrengthMeter from "@/components/PasswordStrengthMeter";
import { neonAuthClient } from "@/lib/neon-auth-client";
import { getUnknownErrorMessage } from "@/lib/error-utils";
import { evaluatePasswordStrength } from "@/lib/password-strength";
import { AUTH_FETCH_OPTIONS } from "@/lib/auth-network";

export default function ResetPasswordPage() {
  const searchParams = useSearchParams();
  const token = String(searchParams.get("token") || "").trim();
  const invalidLink = !token || Boolean(searchParams.get("error"));
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [complete, setComplete] = useState(false);
  const strength = useMemo(() => evaluatePasswordStrength(password), [password]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!token) {
      setError("This reset link is missing or expired. Request a new one below.");
      return;
    }
    if (!strength.acceptable) {
      setError("Use at least 8 characters with uppercase, lowercase, and a number.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Password confirmation does not match.");
      return;
    }

    setLoading(true);
    try {
      const result = await neonAuthClient.resetPassword({ token, newPassword: password, fetchOptions: AUTH_FETCH_OPTIONS });
      if (result.error) throw result.error;
      setComplete(true);
      setPassword("");
      setConfirmPassword("");
    } catch (cause) {
      setError(getUnknownErrorMessage(cause, "This reset link is invalid or has expired. Request a new one."));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-page-shell">
      <section className="card-panel auth-shell auth-verify-shell" aria-labelledby="reset-password-heading">
        <section className="auth-right-pane">
          <BrandLogo />
          <div className="auth-form-intro">
            <h1 id="reset-password-heading">Choose a new password</h1>
            <p>Your reset link is single-use. Choose a password you do not reuse elsewhere.</p>
          </div>
          {complete ? (
            <p className="auth-message" role="status">Your password has been reset. You can sign in now.</p>
          ) : invalidLink ? (
            <p className="auth-message auth-message-error" role="alert">This reset link is missing or expired. Request a new one below.</p>
          ) : (
            <form onSubmit={handleSubmit} className="auth-form-stack">
              <label>New password<input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={loading} required /></label>
              <PasswordStrengthMeter strength={strength} compact />
              <label>Confirm new password<input type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} disabled={loading} required /></label>
              {error ? <p className="auth-message auth-message-error" role="alert">{error}</p> : null}
              <button type="submit" className="auth-primary-button" disabled={loading}>{loading ? "Resetting password..." : "Reset password"}</button>
            </form>
          )}
          <p className="auth-switch-row">
            {complete ? <Link href="/login">Go to sign in</Link> : <Link href="/forgot-password">Request a new reset link</Link>}
          </p>
        </section>
      </section>
    </main>
  );
}
