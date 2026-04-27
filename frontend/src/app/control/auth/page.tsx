"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { apiUrl } from "@/lib/api";
import { ADMIN_DASHBOARD_PATH } from "@/lib/admin-routes";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";
import { COOKIE_SESSION_SENTINEL, getAccessToken, hasAuthSession, setAccessToken } from "@/lib/auth-session";

type CurrentUser = {
  is_admin?: boolean;
};

export default function AdminAuthPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    const run = async () => {
      const token = getAccessToken();
      if (!token && !hasAuthSession()) {
        return;
      }
      try {
        const headers =
          token && token !== COOKIE_SESSION_SENTINEL ? { Authorization: `Bearer ${token}` } : undefined;
        const meRes = await fetch(apiUrl("/api/v1/users/me"), {
          credentials: "include",
          headers,
        });
        if (!meRes.ok) {
          return;
        }
        const me = (await meRes.json()) as CurrentUser;
        if (Boolean(me.is_admin)) {
          router.replace(ADMIN_DASHBOARD_PATH);
          return;
        }
        router.replace("/dashboard");
      } catch {
        // Keep user on page and allow auth retry.
      }
    };
    void run();
  }, [router]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const response = await fetch(apiUrl("/api/v1/auth/admin/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          password,
          totp_code: totpCode.trim(),
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, "Admin authentication failed"));
      }
      const token = String(payload.access_token || "");
      if (!token) {
        throw new Error("Auth token missing from response");
      }
      setAccessToken(token);
      setInfo("Authentication successful. Redirecting...");
      router.replace(ADMIN_DASHBOARD_PATH);
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to authenticate admin session"));
    } finally {
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
          "radial-gradient(circle at 15% 20%, rgba(34,197,94,0.12), transparent 34%), radial-gradient(circle at 84% 12%, rgba(59,130,246,0.12), transparent 26%), var(--bg-base)",
      }}
    >
      <section className="card-panel" style={{ width: "min(520px, 100%)", padding: "1.5rem" }}>
        <h1 style={{ marginBottom: "0.5rem" }}>Secure Access</h1>
        <p style={{ color: "var(--text-secondary)", marginBottom: "1rem" }}>
          Enter credentials and TOTP code to continue.
        </p>

        <form onSubmit={onSubmit} style={{ display: "grid", gap: "0.85rem" }}>
          <label style={{ display: "grid", gap: "0.35rem" }}>
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              autoComplete="username"
              style={{
                border: "1px solid var(--border-subtle)",
                borderRadius: "0.5rem",
                padding: "0.7rem 0.85rem",
                background: "var(--bg-panel)",
                color: "var(--text-primary)",
              }}
            />
          </label>
          <label style={{ display: "grid", gap: "0.35rem" }}>
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              autoComplete="current-password"
              style={{
                border: "1px solid var(--border-subtle)",
                borderRadius: "0.5rem",
                padding: "0.7rem 0.85rem",
                background: "var(--bg-panel)",
                color: "var(--text-primary)",
              }}
            />
          </label>
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
              style={{
                border: "1px solid var(--border-subtle)",
                borderRadius: "0.5rem",
                padding: "0.7rem 0.85rem",
                background: "var(--bg-panel)",
                color: "var(--text-primary)",
                letterSpacing: "0.2em",
              }}
            />
          </label>
          <button type="submit" className="btn-primary" disabled={loading} style={{ marginTop: "0.35rem" }}>
            {loading ? "Authenticating..." : "Continue"}
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
