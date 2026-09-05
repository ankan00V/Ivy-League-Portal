"use client";

import React, { useEffect, useState } from "react";

import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";
import TextField from "@/components/ui/TextField";

/**
 * Adds a personal backup address to an account created with a college email.
 *
 * The address is never written to the database from here: sending a code only
 * sends a code, and the account is updated by the verify call alone. So a
 * half-finished attempt leaves nothing behind, and the profile never shows an
 * address the student has not proved they own.
 *
 * Verification is per address, once. A confirmed address stays confirmed until
 * it is changed to a different one, which starts the flow again.
 */
export default function BackupEmailPanel() {
    const [savedEmail, setSavedEmail] = useState<string>("");
    const [verified, setVerified] = useState(false);
    const [input, setInput] = useState("");
    const [otp, setOtp] = useState("");
    const [stage, setStage] = useState<"idle" | "code-sent">("idle");
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loaded, setLoaded] = useState(false);

    useEffect(() => {
        let cancelled = false;

        const load = async () => {
            try {
                const token = getAccessToken();
                if (!token) {
                    return;
                }
                const res = await fetch(apiUrl("/api/v1/users/me"), {
                    headers: { Authorization: `Bearer ${token}` },
                });
                if (res.ok) {
                    const data = (await res.json()) as {
                        secondary_email?: string | null;
                        secondary_email_verified?: boolean;
                    };
                    if (!cancelled) {
                        setSavedEmail(data.secondary_email || "");
                        setVerified(Boolean(data.secondary_email_verified));
                        setInput(data.secondary_email || "");
                    }
                }
            } catch {
                // Non-fatal: the panel still works, it just starts empty.
            } finally {
                if (!cancelled) {
                    setLoaded(true);
                }
            }
        };

        // Deferring the read keeps state updates out of the effect's synchronous
        // phase and gives the cleanup a chance to cancel an unmounted request.
        void Promise.resolve().then(load);
        return () => {
            cancelled = true;
        };
    }, []);

    // Typing a different address invalidates the confirmed one on screen, so the
    // badge never claims an address the student has since edited.
    const trimmed = input.trim().toLowerCase();
    const isUnchanged = Boolean(savedEmail) && trimmed === savedEmail.toLowerCase();
    const showVerified = verified && isUnchanged;

    const request = async () => {
        setBusy(true);
        setError(null);
        setMessage(null);
        try {
            const token = getAccessToken();
            const res = await fetch(apiUrl("/api/v1/auth/secondary-email/send-otp"), {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ email: trimmed }),
            });
            const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
            if (!res.ok) {
                throw new Error(String(payload.detail || "Could not send the code."));
            }
            setStage("code-sent");
            setMessage(String(payload.message || "Verification code sent."));
        } catch (err) {
            setError(err instanceof Error ? err.message : "Could not send the code.");
        } finally {
            setBusy(false);
        }
    };

    const confirm = async () => {
        setBusy(true);
        setError(null);
        setMessage(null);
        try {
            const token = getAccessToken();
            const res = await fetch(apiUrl("/api/v1/auth/secondary-email/verify"), {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ email: trimmed, otp: otp.trim() }),
            });
            const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
            if (!res.ok) {
                const detail = payload.detail;
                throw new Error(
                    typeof detail === "string" ? detail : "That code was not accepted.",
                );
            }
            setSavedEmail(trimmed);
            setVerified(true);
            setStage("idle");
            setOtp("");
            setMessage("Backup email verified. You can sign in with either address.");
        } catch (err) {
            setError(err instanceof Error ? err.message : "That code was not accepted.");
        } finally {
            setBusy(false);
        }
    };

    if (!loaded) {
        return null;
    }

    return (
        <div className="profile-address-card">
            <div className="profile-address-head">
                <h3>Backup Email</h3>
                {showVerified ? (
                    <span className="profile-verified-badge">Verified</span>
                ) : null}
            </div>
            <p className="profile-address-note">
                Add a personal address you will still have after you graduate. You can sign in with
                it as well as your college email. It is saved only after you enter the code we send
                to it.
            </p>

            <div className="profile-field-grid two">
                <TextField
                    wrapperClassName="profile-field"
                    label="Personal email"
                    type="email"
                    value={input}
                    onChange={(event) => {
                        setInput(event.target.value);
                        setStage("idle");
                        setOtp("");
                        setMessage(null);
                        setError(null);
                    }}
                    placeholder="you@example.com"
                />
                {stage === "code-sent" ? (
                    <TextField
                        wrapperClassName="profile-field"
                        label="6-digit code"
                        value={otp}
                        onChange={(event) => setOtp(event.target.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase().slice(0, 6))}
                        placeholder="XXXXXX"
                        inputMode="text"
                    />
                ) : null}
            </div>

            <div className="profile-hobby-input-row">
                {stage === "code-sent" ? (
                    <>
                        <button
                            type="button"
                            className="btn-primary"
                            disabled={busy || otp.trim().length !== 6}
                            onClick={confirm}
                        >
                            {busy ? "Verifying…" : "Verify and save"}
                        </button>
                        <button type="button" className="btn-secondary" disabled={busy} onClick={request}>
                            Resend code
                        </button>
                    </>
                ) : (
                    <button
                        type="button"
                        className="btn-primary"
                        disabled={busy || !trimmed.includes("@") || showVerified}
                        onClick={request}
                    >
                        {busy ? "Sending…" : showVerified ? "Verified" : "Send verification code"}
                    </button>
                )}
            </div>

            {message ? <p className="profile-address-note">{message}</p> : null}
            {error ? (
                <p className="profile-address-note" role="alert" style={{ color: "var(--danger, #c0392b)" }}>
                    {error}
                </p>
            ) : null}
        </div>
    );
}
