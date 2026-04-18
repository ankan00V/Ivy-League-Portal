"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useMemo, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import { apiUrl } from "@/lib/api";
import { setAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";

type RegisterStep = "details" | "otp";
type AccountType = "candidate" | "employer";

type OAuthProviderStatus = {
  google: boolean;
  linkedin: boolean;
  microsoft: boolean;
};

const REGISTER_VISUALS = {
  candidate: {
    heading: "Sign up as candidate",
    image:
      "https://images.unsplash.com/photo-1600880292203-757bb62b4baf?auto=format&fit=crop&w=1200&q=80",
  },
  employer: {
    heading: "Sign up as employer",
    image:
      "https://images.unsplash.com/photo-1557804506-669a67965ba0?auto=format&fit=crop&w=1200&q=80",
  },
};

export default function RegisterPage() {
  const router = useRouter();
  const defaultOtpCooldownSeconds = 60;
  const [accountType, setAccountType] = useState<AccountType>("candidate");
  const [step, setStep] = useState<RegisterStep>("details");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [otpCooldownSeconds, setOtpCooldownSeconds] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [providers, setProviders] = useState<OAuthProviderStatus>({ google: false, linkedin: false, microsoft: false });

  const visual = useMemo(() => REGISTER_VISUALS[accountType], [accountType]);

  React.useEffect(() => {
    const run = async () => {
      try {
        const res = await fetch(apiUrl("/api/v1/auth/oauth/providers"));
        if (!res.ok) {
          return;
        }
        const payload = (await res.json()) as OAuthProviderStatus;
        setProviders(payload);
      } catch {
        // Ignore local discovery errors.
      }
    };
    void run();
  }, []);

  React.useEffect(() => {
    if (otpCooldownSeconds <= 0) {
      return;
    }
    const timer = window.setInterval(() => {
      setOtpCooldownSeconds((current) => (current > 0 ? current - 1 : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [otpCooldownSeconds]);

  const fullName = useMemo(() => `${firstName} ${lastName}`.trim(), [firstName, lastName]);

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
    if (otpCooldownSeconds > 0) {
      throw new Error(`Please wait ${otpCooldownSeconds}s before requesting another OTP.`);
    }

    setLoading(true);
    resetMessages();

    try {
      const res = await fetch(apiUrl("/api/v1/auth/send-otp"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, purpose: "signup", account_type: accountType }),
      });
      const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        const detail = getApiErrorMessage(payload, "");
        if (res.status === 429) {
          const remaining = resolveCooldownSeconds(res, payload);
          setOtpCooldownSeconds(remaining);
          throw new Error(`Please wait ${remaining}s before requesting another OTP.`);
        }
        throw new Error(detail || "Failed to send OTP");
      }

      const cooldown = resolveCooldownSeconds(res, payload);
      setOtpCooldownSeconds(cooldown);
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

  const handleVerifySignup = async (event: React.FormEvent) => {
    event.preventDefault();
    setLoading(true);
    resetMessages();

    try {
      const res = await fetch(apiUrl("/api/v1/auth/verify-otp"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          otp,
          purpose: "signup",
          full_name: fullName,
          account_type: accountType,
        }),
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
      router.push("/onboarding");
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to verify OTP"));
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
          "radial-gradient(circle at 20% 20%, rgba(251,191,36,0.11), transparent 28%), radial-gradient(circle at 80% 10%, rgba(59,130,246,0.08), transparent 24%), var(--bg-base)",
      }}
    >
      <section
        className="card-panel auth-shell"
        style={{
          width: "min(1100px, 100%)",
          minHeight: "740px",
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
          <div style={{ borderRadius: "var(--radius-md)", overflow: "hidden", border: "2px solid rgba(0,0,0,0.12)", background: "#fff" }}>
            <img src={visual.image} alt="Signup visual" style={{ width: "100%", height: "420px", objectFit: "cover", display: "block" }} />
          </div>
          <div>
            <h2 style={{ fontSize: "2rem", marginBottom: "0.4rem", color: "#111" }}>{visual.heading}</h2>
            <p style={{ color: "rgba(0,0,0,0.78)", fontWeight: 600 }}>
              Verify with OTP and complete a guided profile setup to unlock personalized recommendations.
            </p>
          </div>
        </aside>

        <div className="auth-right-pane" style={{ padding: "2rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
          <h1 style={{ fontSize: "2.2rem", marginBottom: "0.35rem" }}>Create your account</h1>

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
            <button type="button" className={accountType === "candidate" ? "btn-primary" : "btn-secondary"} style={{ borderRadius: "999px", width: "100%" }} onClick={() => setAccountType("candidate")}>
              Candidate
            </button>
            <button type="button" className={accountType === "employer" ? "btn-primary" : "btn-secondary"} style={{ borderRadius: "999px", width: "100%" }} onClick={() => setAccountType("employer")}>
              Employer
            </button>
          </div>
          {accountType === "employer" && (
            <p style={{ color: "var(--text-secondary)", fontWeight: 700 }}>
              Employer sign-up requires a corporate email domain.
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

          {step === "details" && (
            <>
              <div style={{ display: "grid", gap: "0.6rem" }}>
                <button type="button" className="btn-secondary" onClick={() => void startGoogleOAuth()} disabled={loading || !providers.google} style={{ width: "100%", justifyContent: "center" }}>
                  Continue with Google
                </button>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", color: "var(--text-secondary)" }}>
                <div style={{ height: "1px", background: "var(--border-subtle)", flex: 1 }} />
                <span>OR</span>
                <div style={{ height: "1px", background: "var(--border-subtle)", flex: 1 }} />
              </div>
            </>
          )}

          {step === "details" ? (
            <form onSubmit={handleSendOtp} style={{ display: "grid", gap: "0.85rem" }}>
              <label style={{ fontWeight: 700 }}>First Name</label>
              <input type="text" className="input-base" value={firstName} onChange={(event) => setFirstName(event.target.value)} placeholder="Bob" required disabled={loading} />

              <label style={{ fontWeight: 700 }}>Last Name</label>
              <input type="text" className="input-base" value={lastName} onChange={(event) => setLastName(event.target.value)} placeholder="Builder" disabled={loading} />

              <label style={{ fontWeight: 700 }}>Email</label>
              <input
                type="email"
                className="input-base"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder={accountType === "employer" ? "name@company.com" : "student@college.edu"}
                required
                disabled={loading}
              />

              <button
                type="submit"
                className="btn-primary"
                disabled={loading || otpCooldownSeconds > 0}
                style={{ width: "100%", justifyContent: "center", marginTop: "0.25rem" }}
              >
                {loading ? "Please wait..." : (otpCooldownSeconds > 0 ? `Send OTP (${otpCooldownSeconds}s)` : "Send OTP")}
              </button>
            </form>
          ) : (
            <form onSubmit={handleVerifySignup} style={{ display: "grid", gap: "0.85rem" }}>
              <label style={{ fontWeight: 700 }}>Email</label>
              <input type="email" className="input-base" value={email} disabled />

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

              <button type="submit" className="btn-primary" disabled={loading} style={{ width: "100%", justifyContent: "center", marginTop: "0.25rem" }}>
                {loading ? "Verifying..." : "Verify OTP & Continue"}
              </button>

              <button type="button" style={{ border: "none", background: "none", color: "var(--brand-primary)", fontWeight: 700, cursor: "pointer" }} onClick={() => setStep("details")}>
                Edit details
              </button>
            </form>
          )}

          <div style={{ color: "var(--text-secondary)", fontWeight: 600 }}>
            Already have an account?{" "}
            <Link href="/login" style={{ color: "var(--brand-primary)", fontWeight: 800 }}>
              Sign in
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}
