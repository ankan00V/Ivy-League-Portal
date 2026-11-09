"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import PasswordStrengthMeter from "@/components/PasswordStrengthMeter";
import { AUTH_FETCH_OPTIONS } from "@/lib/auth-network";
import { neonAuthClient } from "@/lib/neon-auth-client";
import { evaluatePasswordStrength } from "@/lib/password-strength";

type Step = "email" | "code" | "password" | "complete";
const RESEND_WAIT_MS = 60_000;

function errorCode(cause: unknown): string {
  if (!cause || typeof cause !== "object") return "";
  const record = cause as Record<string, unknown>;
  const nestedError = record.error && typeof record.error === "object"
    ? record.error as Record<string, unknown>
    : null;
  const nestedBody = record.body && typeof record.body === "object"
    ? record.body as Record<string, unknown>
    : null;
  return String(nestedError?.code || nestedBody?.code || record.code || "").trim().toUpperCase();
}

function errorStatus(cause: unknown): number | null {
  if (!cause || typeof cause !== "object") return null;
  const record = cause as Record<string, unknown>;
  const nestedError = record.error && typeof record.error === "object"
    ? record.error as Record<string, unknown>
    : null;
  const value = Number(record.status ?? nestedError?.status);
  return Number.isFinite(value) ? value : null;
}

function recoveryMessage(cause: unknown): string {
  const code = errorCode(cause);
  if (code === "OTP_EXPIRED") return "This code has expired. Request a new code below.";
  if (code === "TOO_MANY_ATTEMPTS") return "Too many incorrect attempts. Request a new code below.";
  if (code === "INVALID_OTP" || code === "OTP_NOT_FOUND" || code === "USER_NOT_FOUND") {
    return "This code is invalid or has expired. Check the code or request a new one.";
  }
  if (code === "TOO_MANY_REQUESTS" || errorStatus(cause) === 429) {
    return "Too many requests. Wait a minute before trying again.";
  }
  if (code === "PASSWORD_TOO_SHORT" || code === "PASSWORD_TOO_LONG") {
    return "Choose a password between 8 and 128 characters.";
  }
  // Do not expose account-existence details or provider internals.
  return "We could not complete the request. Check your connection and try again. If you just submitted a new password, try signing in with it before requesting another code.";
}

export default function PasswordResetFlow() {
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [resendAt, setResendAt] = useState(0);
  const [remaining, setRemaining] = useState(0);
  const pending = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const strength = evaluatePasswordStrength(password);

  useEffect(() => {
    if (!resendAt) return;
    const update = () => setRemaining(Math.max(0, Math.ceil((resendAt - Date.now()) / 1000)));
    const interval = window.setInterval(update, 1000);
    window.addEventListener("focus", update);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", update);
    };
  }, [resendAt]);

  useEffect(() => { heading.current?.focus(); }, [step]);

  function beginRequest() {
    if (pending.current) return false;
    pending.current = true;
    setLoading(true);
    setError(null);
    return true;
  }

  function finishRequest() {
    pending.current = false;
    setLoading(false);
  }

  async function sendCode() {
    if (Date.now() < resendAt || !beginRequest()) return;
    // A UI cooldown is only convenience; Neon's server enforces rate limits.
    setResendAt(Date.now() + RESEND_WAIT_MS);
    setRemaining(RESEND_WAIT_MS / 1000);
    const normalizedEmail = email.trim().toLowerCase();
    try {
      const result = await neonAuthClient.emailOtp.requestPasswordReset({
        email: normalizedEmail, fetchOptions: AUTH_FETCH_OPTIONS,
      });
      if (result.error) throw result.error;
      if (!result.data?.success) throw new Error("Reset code was not accepted");
      setEmail(normalizedEmail);
      setOtp("");
      setPassword("");
      setConfirmation("");
      setNotice("If an account exists for that address, a reset code is on its way. Check your inbox and spam folder. Use the latest code you receive.");
      setStep("code");
    } catch (cause) {
      setError(recoveryMessage(cause));
    } finally { finishRequest(); }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (step === "email") {
      if ((event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") === "enter-code") {
        setEmail(email.trim().toLowerCase());
        setError(null);
        setStep("code");
      } else { await sendCode(); }
      return;
    }
    if (step !== "code" && step !== "password") return;
    if (!/^\d{6}$/.test(otp)) { setError("Enter the six-digit code from your email."); return; }
    if (step === "password") {
      if (!strength.acceptable || password.length > 128) {
        setError("Use 8–128 characters with uppercase, lowercase, and a number."); return;
      }
      if (password !== confirmation) { setError("Password confirmation does not match."); return; }
    }
    if (!beginRequest()) return;
    try {
      if (step === "code") {
        const result = await neonAuthClient.emailOtp.checkVerificationOtp({
          email, otp, type: "forget-password", fetchOptions: AUTH_FETCH_OPTIONS,
        });
        if (result.error) throw result.error;
        if (!result.data?.success) throw new Error("Code was not verified");
        setNotice("");
        setStep("password");
      } else {
        // The server revalidates and consumes the OTP here. Reaching the
        // password screen is never authorization to change a password.
        const result = await neonAuthClient.emailOtp.resetPassword({
          email, otp, password, fetchOptions: AUTH_FETCH_OPTIONS,
        });
        if (result.error) throw result.error;
        if (!result.data?.success) throw new Error("Password was not reset");
        setOtp("");
        setPassword("");
        setConfirmation("");
        setNotice("");
        setStep("complete");
      }
    } catch (cause) {
      if (["OTP_EXPIRED", "INVALID_OTP", "OTP_NOT_FOUND", "TOO_MANY_ATTEMPTS", "USER_NOT_FOUND"].includes(errorCode(cause))) {
        setOtp("");
        setPassword("");
        setConfirmation("");
        setStep("code");
      }
      setError(recoveryMessage(cause));
    } finally { finishRequest(); }
  }

  function changeEmail() {
    setStep("email");
    setOtp("");
    setPassword("");
    setConfirmation("");
    setNotice("");
    setError(null);
  }

  const title = step === "code" ? "Enter your reset code" : step === "password" ? "Choose a new password" : step === "complete" ? "Password reset" : "Reset your password";

  return (
    <main className="auth-page-shell">
      <section className="card-panel auth-shell auth-verify-shell" aria-labelledby="password-reset-heading">
        <section className="auth-right-pane">
          <BrandLogo />
          <div className="auth-form-intro">
            <h1 id="password-reset-heading" tabIndex={-1} ref={heading}>{title}</h1>
            <p>{step === "email" ? "Enter your account email. We’ll send a one-time code to reset your password, not a link." : step === "code" ? `Enter the six-digit code sent to ${email}.` : step === "password" ? "Choose a password you do not reuse elsewhere. Your code will be checked again when you save." : "Your password has been reset. You can sign in now."}</p>
          </div>
          {notice ? <p className="auth-message" role="status">{notice}</p> : null}
          {step !== "complete" ? (
            <form onSubmit={submit} className="auth-form-stack" aria-busy={loading}>
              {step === "email" ? <label>Email<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} disabled={loading} required /></label> : null}
              {step === "code" ? <>
                <label>Reset code<input type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={otp} onChange={(event) => setOtp(event.target.value.replace(/\D/g, "").slice(0, 6))} disabled={loading} required aria-describedby="reset-code-help" /></label>
                <p id="reset-code-help">Codes expire. If yours no longer works, request a new one below.</p>
              </> : null}
              {step === "password" ? <>
                <label>New password<input type="password" autoComplete="new-password" maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} disabled={loading} required /></label>
                <PasswordStrengthMeter strength={strength} compact />
                <label>Confirm new password<input type="password" autoComplete="new-password" maxLength={128} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} disabled={loading} required /></label>
              </> : null}
              {error ? <p className="auth-message auth-message-error" role="alert">{error}</p> : null}
              <button type="submit" className="auth-primary-button" disabled={loading || (step === "email" && remaining > 0)}>
                {loading ? "Please wait..." : step === "email" ? remaining > 0 ? `Try again in ${remaining}s` : "Send reset code" : step === "code" ? "Verify code" : "Reset password"}
              </button>
              {step === "email" ? <p className="auth-resend-row"><button type="submit" value="enter-code" className="auth-resend-link" style={{ color: "var(--text-primary)" }} disabled={loading}>I already have a reset code</button></p> : null}
              {step !== "email" ? <>
                <p className="auth-resend-row">Didn’t receive a code? <button type="button" className="auth-resend-link" style={{ color: "var(--text-primary)" }} onClick={() => void sendCode()} disabled={loading || remaining > 0}>{remaining > 0 ? `Resend code in ${remaining}s` : "Resend code"}</button></p>
                <p className="auth-switch-row"><button type="button" className="auth-resend-link" style={{ color: "var(--text-primary)" }} onClick={changeEmail} disabled={loading}>Use a different email</button></p>
              </> : null}
            </form>
          ) : null}
          <p className="auth-switch-row"><Link href="/login">{step === "complete" ? "Go to sign in" : "Back to sign in"}</Link></p>
        </section>
      </section>
    </main>
  );
}
