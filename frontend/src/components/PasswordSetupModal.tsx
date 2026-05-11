"use client";

import { LockKeyhole } from "lucide-react";
import type { FormEvent } from "react";
import { useMemo, useState } from "react";

import { apiUrl } from "@/lib/api";
import { createAuthenticatedFetchInit } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";
import { evaluatePasswordStrength } from "@/lib/password-strength";
import PasswordStrengthMeter from "@/components/PasswordStrengthMeter";

type PasswordSetupModalProps = {
  open: boolean;
  onComplete: () => void;
};

export default function PasswordSetupModal({ open, onComplete }: PasswordSetupModalProps) {
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const strength = useMemo(() => evaluatePasswordStrength(password), [password]);
  const passwordsMatch = password.length > 0 && password === confirmPassword;

  if (!open) {
    return null;
  }

  const submitPassword = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!strength.acceptable) {
      setError("Use at least 8 characters with uppercase, lowercase, and a number.");
      return;
    }
    if (!passwordsMatch) {
      setError("Password confirmation does not match.");
      return;
    }

    setSaving(true);
    try {
      const response = await fetch(
        apiUrl("/api/v1/auth/password/setup"),
        createAuthenticatedFetchInit({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password, confirm_password: confirmPassword }),
        }),
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to set password"));
      }
      onComplete();
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to set password"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Set account password"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 180,
        background: "rgba(0,0,0,0.55)",
        display: "grid",
        placeItems: "center",
        padding: "1.25rem",
      }}
    >
      <form
        onSubmit={submitPassword}
        className="card-panel"
        style={{
          width: "min(560px, 100%)",
          background: "var(--bg-surface)",
          display: "grid",
          gap: "1rem",
          boxShadow: "var(--shadow-lg)",
        }}
      >
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "flex-start" }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: "50%",
              border: "2px solid var(--border-subtle)",
              background: "var(--brand-primary)",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <LockKeyhole size={20} />
          </div>
          <div>
            <h2 style={{ margin: 0, fontFamily: "var(--font-serif)", fontSize: "2rem" }}>Set your password</h2>
            <p style={{ margin: "0.3rem 0 0", color: "var(--text-secondary)", fontWeight: 600 }}>
              Your account was created before password sign-in was enabled. Set this once to access your dashboard with OTP or password.
            </p>
          </div>
        </div>

        {error && (
          <div style={{ background: "rgba(239,68,68,0.08)", border: "2px solid #ef4444", color: "#b91c1c", borderRadius: "var(--radius-sm)", padding: "0.75rem", fontWeight: 700 }}>
            {error}
          </div>
        )}

        <label style={{ fontWeight: 800 }}>New password</label>
        <input
          type="password"
          className="input-base"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="new-password"
          required
          disabled={saving}
        />
        <PasswordStrengthMeter strength={strength} compact />

        <label style={{ fontWeight: 800 }}>Confirm password</label>
        <input
          type="password"
          className="input-base"
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.target.value)}
          autoComplete="new-password"
          required
          disabled={saving}
          style={{ borderColor: confirmPassword.length === 0 || passwordsMatch ? undefined : "#ef4444" }}
        />

        <button type="submit" className="btn-primary" disabled={saving || !strength.acceptable || !passwordsMatch} style={{ justifyContent: "center" }}>
          {saving ? "Saving password..." : "Set Password & Open Dashboard"}
        </button>
      </form>
    </div>
  );
}
