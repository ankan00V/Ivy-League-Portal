"use client";

import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import React, { useEffect, useMemo, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import { apiUrl } from "@/lib/api";
import { getAccessToken, hasAuthSession, resolvePostAuthRoute, setAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";

type AuthStep = "email" | "otp" | "password";
type AccountType = "candidate" | "employer";

type OAuthProviderStatus = {
  google: boolean;
  linkedin: boolean;
  microsoft: boolean;
};

const LOGIN_VISUALS = {
  candidate: {
    title: "Compete, learn, and get hired.",
    subtitle: "OTP-first secure sign-in plus OAuth options for faster access.",
    image:
      "https://images.unsplash.com/photo-1529074963764-98f45c47344b?auto=format&fit=crop&w=1200&q=80",
  },
  employer: {
    title: "Hire top campus talent faster.",
    subtitle: "Access recruiter workflows with secure authentication.",
    image:
      "https://images.unsplash.com/photo-1552664730-d307ca884978?auto=format&fit=crop&w=1200&q=80",
  },
};

export default function LoginPage() {
  const router = useRouter();
  const defaultOtpCooldownSeconds = 60;
  const [accountType, setAccountType] = useState<AccountType>("candidate");
  const [step, setStep] = useState<AuthStep>("email");
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [password, setPassword] = useState("");
  const [otpCooldownSeconds, setOtpCooldownSeconds] = useState(0);
  const [otpCooldownKey, setOtpCooldownKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [providers, setProviders] = useState<OAuthProviderStatus>({
    google: false,
    linkedin: false,
    microsoft: false,
  });

  const visual = useMemo(() => LOGIN_VISUALS[accountType], [accountType]);
  const normalizedEmail = useMemo(() => email.trim().toLowerCase(), [email]);
  const currentOtpKey = useMemo(() => `${accountType}:${normalizedEmail}`, [accountType, normalizedEmail]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token && !hasAuthSession()) {
      return;
    }
    void resolvePostAuthRoute(token || null).then((nextRoute) => router.replace(nextRoute));
  }, [router]);

  useEffect(() => {
    const run = async () => {
      try {
        const res = await fetch(apiUrl("/api/v1/auth/oauth/providers"));
        if (!res.ok) {
          return;
        }
        const payload = (await res.json()) as OAuthProviderStatus;
        setProviders(payload);
      } catch {
        // Ignore provider discovery issues in local fallback mode.
      }
    };
    void run();
  }, []);

  useEffect(() => {
    if (otpCooldownSeconds <= 0) {
      return;
    }
    const timer = window.setInterval(() => {
      setOtpCooldownSeconds((current) => (current > 0 ? current - 1 : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [otpCooldownSeconds]);

  useEffect(() => {
    if (step !== "email") {
      return;
    }
    if (!otpCooldownKey || otpCooldownKey === currentOtpKey) {
      return;
    }
    setOtpCooldownSeconds(0);
    setOtpCooldownKey(null);
  }, [currentOtpKey, otpCooldownKey, step]);

  const resetMessages = () => {
    setError(null);
    setInfo(null);
  };

  const resolveCooldownSeconds = (response: Response, payload: Record<string, unknown>) => {
    const fromBody = Number(payload.cooldown_seconds);
    if (Number.isFinite(fromBody) && fromBody > 0) {
      return Math.floor(fromBody);
    }
    const retryAfter = Number(response.headers.get("retry-after"));
    if (Number.isFinite(retryAfter) && retryAfter > 0) {
      return Math.floor(retryAfter);
    }
    const detail = String(payload.detail || "");
    const matched = detail.match(/(\d+)/);
    if (matched) {
      return Math.max(1, Number(matched[1]));
    }
    return defaultOtpCooldownSeconds;
  };

  const requestOtp = async () => {
    if (otpCooldownSeconds > 0 && otpCooldownKey === currentOtpKey) {
      throw new Error(`Please wait ${otpCooldownSeconds}s before requesting another OTP.`);
    }

    setLoading(true);
    resetMessages();

    try {
      const res = await fetch(apiUrl("/api/v1/auth/send-otp"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: normalizedEmail, purpose: "signin", account_type: accountType }),
      });
      const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        const detail = getApiErrorMessage(payload, "");
        if (res.status === 429) {
          const remaining = resolveCooldownSeconds(res, payload);
          setOtpCooldownSeconds(remaining);
          setOtpCooldownKey(currentOtpKey);
          setStep("otp");
          setInfo(`OTP already sent. Check inbox/spam and retry in ${remaining}s.`);
          return;
        }
        throw new Error(detail || "Failed to send OTP");
      }

      const cooldown = resolveCooldownSeconds(res, payload);
      setOtpCooldownSeconds(cooldown);
      setOtpCooldownKey(currentOtpKey);
      if (typeof payload.debug_otp === "string" && payload.debug_otp.length === 6) {
        setOtp(payload.debug_otp);
        setInfo(`Debug OTP: ${payload.debug_otp} (local fallback)`);
      } else {
        setInfo("OTP sent to your email. It expires in 5 minutes.");
        setOtp("");
      }
      setStep("otp");
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to send OTP"));
    } finally {
      setLoading(false);
    }
  };

  const handleSendOtp = async (event: React.FormEvent) => {
    event.preventDefault();
    await requestOtp();
  };

  const handleVerifyOtp = async (event: React.FormEvent) => {
    event.preventDefault();
    setLoading(true);
    resetMessages();

    try {
      const res = await fetch(apiUrl("/api/v1/auth/verify-otp"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, otp, purpose: "signin", account_type: accountType }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "OTP verification failed"));
      }
      const token = String(payload.access_token || "");
      if (!token) {
        throw new Error("Auth token missing from response");
      }
      setAccessToken(token);
      const nextRoute = await resolvePostAuthRoute(token);
      router.push(nextRoute);
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to verify OTP"));
    } finally {
      setLoading(false);
    }
  };

  const handlePasswordLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    setLoading(true);
    resetMessages();

    try {
      const body = new URLSearchParams();
      body.set("username", email);
      body.set("password", password);

      const res = await fetch(apiUrl("/api/v1/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Invalid email/password"));
      }
      const token = String(payload.access_token || "");
      if (!token) {
        throw new Error("Auth token missing from response");
      }
      setAccessToken(token);
      const nextRoute = await resolvePostAuthRoute(token);
      router.push(nextRoute);
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to login"));
    } finally {
      setLoading(false);
    }
  };

  const startGoogleOAuth = async () => {
    setLoading(true);
    resetMessages();

    try {
      const params = new URLSearchParams({
        account_type: accountType,
        next: "/auth/callback",
        frontend_origin: window.location.origin,
      });
      const res = await fetch(apiUrl(`/api/v1/auth/oauth/google/start?${params.toString()}`));
      const payload = await res.json().catch(() => ({}));
      if (!res.ok || !payload.redirect_url) {
        throw new Error(getApiErrorMessage(payload, "Google OAuth is unavailable. Configure Google OAuth env vars."));
      }
      window.location.href = String(payload.redirect_url);
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to start Google OAuth"));
      setLoading(false);
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
          "radial-gradient(circle at 20% 20%, rgba(59,130,246,0.08), transparent 30%), radial-gradient(circle at 80% 10%, rgba(34,197,94,0.08), transparent 24%), var(--bg-base)",
      }}
    >
      <section
        className="card-panel auth-shell"
        style={{
          width: "min(1100px, 100%)",
          minHeight: "720px",
          overflow: "hidden",
          padding: 0,
        }}
      >
        <aside
          className="auth-left-pane"
          style={{
            background: "#f7c948",
            padding: "1.25rem",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            borderRight: "2px solid var(--border-subtle)",
          }}
        >
          <BrandLogo size="md" />
          <div
            style={{
              borderRadius: "var(--radius-md)",
              overflow: "hidden",
              border: "2px solid rgba(0,0,0,0.12)",
              background: "#fff",
              position: "relative",
              height: "420px",
            }}
          >
            <Image
              src={visual.image}
              alt="Auth visual"
              fill
              sizes="(max-width: 1100px) 100vw, 50vw"
              style={{ objectFit: "cover", display: "block" }}
            />
          </div>
          <div>
            <h2 style={{ fontSize: "2rem", marginBottom: "0.5rem", color: "#111" }}>{visual.title}</h2>
            <p style={{ color: "rgba(0,0,0,0.78)", fontWeight: 600 }}>{visual.subtitle}</p>
          </div>
        </aside>

        <div className="auth-right-pane" style={{ padding: "2rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div>
            <h1 style={{ fontSize: "2.2rem", marginBottom: "0.35rem" }}>Secure Sign In</h1>
            <p style={{ color: "var(--text-secondary)" }}>OTP-first login with OAuth options and profile-aware onboarding.</p>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "0.5rem",
              background: "var(--bg-surface-hover)",
              padding: "0.3rem",
              borderRadius: "999px",
              border: "2px solid var(--border-subtle)",
              maxWidth: "360px",
            }}
          >
            <button
              type="button"
              className={accountType === "candidate" ? "btn-primary" : "btn-secondary"}
              style={{ borderRadius: "999px", width: "100%" }}
              disabled={loading || step === "otp"}
              onClick={() => setAccountType("candidate")}
            >
              Candidate
            </button>
            <button
              type="button"
              className={accountType === "employer" ? "btn-primary" : "btn-secondary"}
              style={{ borderRadius: "999px", width: "100%" }}
              disabled={loading || step === "otp"}
              onClick={() => setAccountType("employer")}
            >
              Employer
            </button>
          </div>
          {accountType === "employer" && (
            <p style={{ color: "var(--text-secondary)", fontWeight: 700 }}>
              Employer sign-in requires a corporate email domain.
            </p>
          )}

          {error && (
            <div style={{ background: "rgba(239,68,68,0.08)", border: "2px solid #ef4444", color: "#b91c1c", borderRadius: "var(--radius-sm)", padding: "0.75rem" }}>
              {error}
            </div>
          )}
          {info && (
            <div style={{ background: "rgba(34,197,94,0.08)", border: "2px solid #22c55e", color: "#15803d", borderRadius: "var(--radius-sm)", padding: "0.75rem" }}>
              {info}
            </div>
          )}

          <div style={{ display: "grid", gap: "0.6rem" }}>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void startGoogleOAuth()}
              disabled={loading || !providers.google}
              title={providers.google ? "Continue with Google" : "Google OAuth is not configured yet"}
              style={{ width: "100%", justifyContent: "center" }}
            >
              Continue with Google
            </button>
            <button type="button" className="btn-secondary" disabled title="LinkedIn OAuth coming next" style={{ width: "100%", justifyContent: "center" }}>
              Continue with LinkedIn
            </button>
            <button type="button" className="btn-secondary" disabled title="Microsoft OAuth coming next" style={{ width: "100%", justifyContent: "center" }}>
              Continue with Microsoft
            </button>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", color: "var(--text-secondary)" }}>
            <div style={{ height: "1px", background: "var(--border-subtle)", flex: 1 }} />
            <span>OR</span>
            <div style={{ height: "1px", background: "var(--border-subtle)", flex: 1 }} />
          </div>

          {(step === "email" || step === "otp") && (
            <form onSubmit={step === "email" ? handleSendOtp : handleVerifyOtp} style={{ display: "grid", gap: "0.85rem" }}>
              <label style={{ fontWeight: 700 }}>Email</label>
              <input
                type="email"
                className="input-base"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder={accountType === "employer" ? "name@company.com" : "Enter Email"}
                required
                disabled={loading || step === "otp"}
              />

              {step === "otp" && (
                <>
                  <label style={{ fontWeight: 700 }}>OTP</label>
                  <input
                    type="text"
                    className="input-base"
                    value={otp}
                    onChange={(event) => setOtp(event.target.value)}
                    placeholder="123456"
                    maxLength={6}
                    minLength={6}
                    required
                    disabled={loading}
                    style={{ letterSpacing: "0.25em", textAlign: "center", fontWeight: 800 }}
                  />
                  <button
                    type="button"
                    className="btn-secondary"
                    disabled={loading || otpCooldownSeconds > 0}
                    onClick={() => void requestOtp()}
                    style={{ width: "100%", justifyContent: "center" }}
                  >
                    {otpCooldownSeconds > 0 ? `Resend OTP in ${otpCooldownSeconds}s` : "Resend OTP"}
                  </button>
                </>
              )}

              <button
                type="submit"
                className="btn-primary"
                disabled={loading || (step === "email" && otpCooldownSeconds > 0)}
                style={{ width: "100%", justifyContent: "center", marginTop: "0.25rem" }}
              >
                {loading
                  ? "Please wait..."
                  : step === "email"
                    ? (otpCooldownSeconds > 0 ? `Continue with OTP (${otpCooldownSeconds}s)` : "Continue with OTP")
                    : "Verify OTP & Sign In"}
              </button>
            </form>
          )}

          {step === "password" && (
            <form onSubmit={handlePasswordLogin} style={{ display: "grid", gap: "0.85rem" }}>
              <label style={{ fontWeight: 700 }}>Email</label>
              <input
                type="email"
                className="input-base"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder={accountType === "employer" ? "name@company.com" : "Enter Email"}
                required
                disabled={loading}
              />
              <label style={{ fontWeight: 700 }}>Password</label>
              <input
                type="password"
                className="input-base"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Enter password"
                required
                disabled={loading}
              />
              <button type="submit" className="btn-primary" disabled={loading} style={{ width: "100%", justifyContent: "center", marginTop: "0.25rem" }}>
                {loading ? "Signing in..." : "Sign In with Password"}
              </button>
            </form>
          )}

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.75rem" }}>
            <button
              type="button"
              style={{ border: "none", background: "none", color: "var(--brand-primary)", fontWeight: 700, cursor: "pointer" }}
              onClick={() => {
                resetMessages();
                if (step === "otp") {
                  setStep("email");
                  return;
                }
                setStep(step === "password" ? "email" : "password");
              }}
            >
              {step === "password" ? "Login via OTP" : "Login via Password"}
            </button>

            <div style={{ color: "var(--text-secondary)", fontWeight: 600 }}>
              New here?{" "}
              <Link href="/register" style={{ color: "var(--brand-primary)", fontWeight: 800 }}>
                Create account
              </Link>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
