"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { apiUrl } from "@/lib/api";
import { ADMIN_DASHBOARD_PATH } from "@/lib/admin-routes";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";
import {
  clearPendingAdminChallenge,
  COOKIE_SESSION_SENTINEL,
  getAccessToken,
  getPendingAdminChallenge,
  hasAuthSession,
  setPendingAdminChallenge,
  setAccessToken,
} from "@/lib/auth-session";

type CurrentUser = {
  is_admin?: boolean;
};

export default function AdminAuthPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [challengeToken, setChallengeToken] = useState("");
  const [totpToken, setTotpToken] = useState("");
  const [otpVerified, setOtpVerified] = useState(false);
  const [totpSetupRequired, setTotpSetupRequired] = useState(false);
  const [totpSetupSecret, setTotpSetupSecret] = useState("");
  const [totpSetupIssuer, setTotpSetupIssuer] = useState("");
  const [totpSetupAccountName, setTotpSetupAccountName] = useState("");
  const [otpLoading, setOtpLoading] = useState(false);
  const [totpLoading, setTotpLoading] = useState(false);
  const [resendLoading, setResendLoading] = useState(false);
  const [otpCooldownSeconds, setOtpCooldownSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    const run = async () => {
      const token = getAccessToken();
      if (token || hasAuthSession()) {
        try {
          const headers =
            token && token !== COOKIE_SESSION_SENTINEL ? { Authorization: `Bearer ${token}` } : undefined;
          const meRes = await fetch(apiUrl("/api/v1/users/me"), {
            credentials: "include",
            headers,
          });
          if (meRes.ok) {
            const me = (await meRes.json()) as CurrentUser;
            router.replace(Boolean(me.is_admin) ? ADMIN_DASHBOARD_PATH : "/dashboard");
            return;
          }
        } catch {
          // Fall through to challenge mode.
        }
      }

      const pending = getPendingAdminChallenge();
      if (!pending) {
        setError("Start from the normal login page with your admin email and password.");
        return;
      }

      setEmail(pending.email);
      setChallengeToken(pending.adminChallengeToken);
      setTotpToken(String(pending.adminTotpToken || ""));
      setOtpVerified(Boolean(pending.otpVerified));
      setTotpSetupRequired(Boolean(pending.totpSetupRequired));
      setTotpSetupSecret(String(pending.totpSetupSecret || ""));
      setTotpSetupIssuer(String(pending.totpSetupIssuer || ""));
      setTotpSetupAccountName(String(pending.totpSetupAccountName || ""));
      setOtpCooldownSeconds(Math.max(0, Number(pending.otpCooldownSeconds || 0)));
      if (pending.debugOtp) {
        setOtp(pending.debugOtp);
        setInfo(
          pending.otpVerified
            ? "OTP verified. Enter the current authenticator TOTP to continue."
            : pending.totpSetupRequired
              ? `Password verified. Set up your authenticator, then verify the emailed OTP. Debug OTP: ${pending.debugOtp}`
              : `Password verified. Verify the emailed OTP to continue. Debug OTP: ${pending.debugOtp}`,
        );
        return;
      }
      setInfo(
        pending.otpVerified
          ? "OTP verified. Enter the current authenticator TOTP to continue."
          : pending.totpSetupRequired
            ? "Password verified. Set up your authenticator first, then verify the email OTP."
            : "Password verified. Enter the email OTP to continue.",
      );
    };
    void run();
  }, [router]);

  useEffect(() => {
    if (otpCooldownSeconds <= 0) {
      return;
    }
    const timer = window.setInterval(() => {
      setOtpCooldownSeconds((current) => (current > 0 ? current - 1 : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [otpCooldownSeconds]);

  const handleResendOtp = async () => {
    if (!challengeToken || resendLoading || otpCooldownSeconds > 0 || otpVerified) {
      return;
    }
    setResendLoading(true);
    setError(null);
    setInfo(null);
    try {
      const response = await fetch(apiUrl("/api/v1/auth/admin/resend-otp"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          admin_challenge_token: challengeToken,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to resend OTP"));
      }
      const nextCooldown = Math.max(0, Number(payload.cooldown_seconds || 0));
      const debugOtp = typeof payload.debug_otp === "string" ? payload.debug_otp : null;
      setOtpCooldownSeconds(nextCooldown);
      if (debugOtp) {
        setOtp(debugOtp);
      }
      setPendingAdminChallenge({
        email: email.trim().toLowerCase(),
        adminChallengeToken: challengeToken,
        adminTotpToken: null,
        otpVerified: false,
        otpDelivery: payload.delivery,
        otpCooldownSeconds: nextCooldown,
        otpExpiresInSeconds: Number(payload.expires_in_seconds || 300),
        debugOtp,
        totpSetupRequired,
        totpSetupSecret,
        totpSetupIssuer,
        totpSetupAccountName,
      });
      setInfo(debugOtp ? `${String(payload.message || "OTP resent")} Debug OTP: ${debugOtp}` : String(payload.message || "OTP resent"));
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to resend OTP"));
    } finally {
      setResendLoading(false);
    }
  };

  const onVerifyOtp = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!challengeToken || otpVerified) {
      return;
    }
    setOtpLoading(true);
    setError(null);
    setInfo(null);
    try {
      const response = await fetch(apiUrl("/api/v1/auth/admin/verify-otp"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          otp: otp.trim(),
          admin_challenge_token: challengeToken,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, "OTP verification failed"));
      }
      const nextTotpToken = String(payload.admin_totp_token || "");
      if (!nextTotpToken) {
        throw new Error("Admin TOTP session missing from response");
      }
      setTotpToken(nextTotpToken);
      setOtpVerified(true);
      setPendingAdminChallenge({
        email: email.trim().toLowerCase(),
        adminChallengeToken: challengeToken,
        adminTotpToken: nextTotpToken,
        otpVerified: true,
        otpDelivery: undefined,
        otpCooldownSeconds: 0,
        otpExpiresInSeconds: undefined,
        debugOtp: null,
        totpSetupRequired,
        totpSetupSecret,
        totpSetupIssuer,
        totpSetupAccountName,
      });
      setInfo(String(payload.message || "OTP verified. Enter your authenticator TOTP to continue."));
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to verify OTP"));
    } finally {
      setOtpLoading(false);
    }
  };

  const onVerifyTotp = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!totpToken || !otpVerified) {
      return;
    }
    setTotpLoading(true);
    setError(null);
    setInfo(null);
    try {
      const response = await fetch(apiUrl("/api/v1/auth/admin/verify-totp"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          totp_code: totpCode.trim(),
          admin_totp_token: totpToken,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, "TOTP verification failed"));
      }
      const token = String(payload.access_token || "");
      if (!token) {
        throw new Error("Auth token missing from response");
      }
      clearPendingAdminChallenge();
      setAccessToken(token);
      setInfo("Authentication successful. Redirecting...");
      router.replace(ADMIN_DASHBOARD_PATH);
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to verify TOTP"));
    } finally {
      setTotpLoading(false);
    }
  };

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "1.5rem",
        background:
          "radial-gradient(circle at 15% 20%, rgba(34,197,94,0.12), transparent 34%), radial-gradient(circle at 84% 12%, rgba(59,130,246,0.12), transparent 26%), var(--bg-base)",
      }}
    >
      <section className="card-panel" style={{ width: "min(520px, 100%)", padding: "1.5rem" }}>
        <h1 style={{ marginBottom: "0.5rem" }}>Admin Verification</h1>
        <p style={{ color: "var(--text-secondary)", marginBottom: "1rem" }}>
          {totpSetupRequired
            ? "Set up your authenticator first, then finish admin sign-in with the email OTP and TOTP."
            : "Finish admin sign-in with the email OTP and authenticator TOTP."}
        </p>

        <form onSubmit={otpVerified ? onVerifyTotp : onVerifyOtp} style={{ display: "grid", gap: "0.85rem" }}>
          <label style={{ display: "grid", gap: "0.35rem" }}>
            <span>Email</span>
            <input
              type="email"
              value={email}
              readOnly
              required
              autoComplete="username"
              style={{
                border: "1px solid var(--border-subtle)",
                borderRadius: "0.5rem",
                padding: "0.7rem 0.85rem",
                background: "var(--bg-surface-hover)",
                color: "var(--text-primary)",
              }}
            />
          </label>
          {totpSetupRequired ? (
            <div
              style={{
                display: "grid",
                gap: "0.45rem",
                padding: "0.85rem",
                border: "1px solid rgba(37, 99, 235, 0.28)",
                borderRadius: "0.6rem",
                background: "rgba(37, 99, 235, 0.08)",
              }}
            >
              <strong style={{ color: "var(--text-primary)" }}>Set up your authenticator</strong>
              <p style={{ margin: 0, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                Add this account in Google Authenticator, Authy, 1Password, or another TOTP app. After saving it,
                enter the current 6-digit code below.
              </p>
              <div style={{ display: "grid", gap: "0.2rem" }}>
                <span style={{ color: "var(--text-secondary)", fontSize: "0.92rem" }}>Issuer</span>
                <code style={{ wordBreak: "break-word" }}>{totpSetupIssuer || "Vidyaverse"}</code>
              </div>
              <div style={{ display: "grid", gap: "0.2rem" }}>
                <span style={{ color: "var(--text-secondary)", fontSize: "0.92rem" }}>Account</span>
                <code style={{ wordBreak: "break-word" }}>{totpSetupAccountName || email}</code>
              </div>
              <div style={{ display: "grid", gap: "0.2rem" }}>
                <span style={{ color: "var(--text-secondary)", fontSize: "0.92rem" }}>Setup key</span>
                <code style={{ wordBreak: "break-word" }}>{totpSetupSecret || "Unavailable"}</code>
              </div>
            </div>
          ) : null}
          <label style={{ display: "grid", gap: "0.35rem" }}>
            <span>Email OTP</span>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              value={otp}
              onChange={(event) => setOtp(event.target.value.replace(/\D/g, ""))}
              required
              disabled={otpVerified}
              style={{
                border: "1px solid var(--border-subtle)",
                borderRadius: "0.5rem",
                padding: "0.7rem 0.85rem",
                background: otpVerified ? "var(--bg-surface-hover)" : "var(--bg-panel)",
                color: "var(--text-primary)",
                letterSpacing: "0.2em",
              }}
            />
          </label>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.75rem" }}>
            <span style={{ color: "var(--text-secondary)", fontSize: "0.95rem" }}>
              {otpCooldownSeconds > 0 ? `You can resend OTP in ${otpCooldownSeconds}s.` : "Didn't get the email OTP?"}
            </span>
            <button
              type="button"
              onClick={handleResendOtp}
              disabled={!challengeToken || resendLoading || otpCooldownSeconds > 0 || otpVerified}
              style={{
                border: "1px solid var(--border-subtle)",
                borderRadius: "0.5rem",
                padding: "0.55rem 0.9rem",
                background: otpCooldownSeconds > 0 || otpVerified ? "var(--bg-surface-hover)" : "var(--bg-panel)",
                color: "var(--text-primary)",
                fontWeight: 600,
                cursor: !challengeToken || resendLoading || otpCooldownSeconds > 0 || otpVerified ? "not-allowed" : "pointer",
                opacity: !challengeToken || resendLoading || otpCooldownSeconds > 0 || otpVerified ? 0.65 : 1,
              }}
            >
              {resendLoading ? "Sending..." : "Resend OTP"}
            </button>
          </div>
          <label style={{ display: "grid", gap: "0.35rem" }}>
            <span>TOTP</span>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              value={totpCode}
              onChange={(event) => setTotpCode(event.target.value.replace(/\D/g, ""))}
              required
              disabled={!otpVerified}
              style={{
                border: "1px solid var(--border-subtle)",
                borderRadius: "0.5rem",
                padding: "0.7rem 0.85rem",
                background: otpVerified ? "var(--bg-panel)" : "var(--bg-surface-hover)",
                color: "var(--text-primary)",
                letterSpacing: "0.2em",
              }}
            />
          </label>
          <button
            type="submit"
            className="btn-primary"
            disabled={otpVerified ? totpLoading || !totpToken : otpLoading || !challengeToken}
            style={{ marginTop: "0.35rem" }}
          >
            {otpVerified ? (totpLoading ? "Verifying TOTP..." : "Verify TOTP") : (otpLoading ? "Verifying OTP..." : "Verify OTP")}
          </button>
        </form>

        {error ? (
          <p style={{ marginTop: "0.85rem", color: "#ef4444", fontWeight: 600 }}>{error}</p>
        ) : null}
        {!error && info ? (
          <p style={{ marginTop: "0.85rem", color: "#16a34a", fontWeight: 600 }}>{info}</p>
        ) : null}
      </section>
    </main>
  );
}
