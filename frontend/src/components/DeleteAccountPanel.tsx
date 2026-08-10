"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { apiUrl } from "@/lib/api";
import { clearAccessToken, createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";

/**
 * Self-service account deletion.
 *
 * Before this existed there was no way out of VidyaVerse: a student could hand over
 * their mobile number, college and resume and had no path to get any of it back.
 *
 * The typed confirmation is not friction for its own sake — deletion is
 * irreversible, and a single mis-click on a page full of save buttons should not be
 * able to trigger it. The phrase must match what the backend expects exactly
 * (`ACCOUNT_DELETION_CONFIRMATION` in endpoints/users.py).
 *
 * What is removed and what survives as anonymous measurement is spelled out here
 * rather than hidden behind a link, because "delete" that quietly leaves rows behind
 * is the kind of thing this whole change set exists to stop.
 */

const CONFIRMATION_PHRASE = "DELETE MY ACCOUNT";

export default function DeleteAccountPanel() {
  const router = useRouter();
  const [expanded, setExpanded] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canDelete = confirmation.trim().toUpperCase() === CONFIRMATION_PHRASE && !deleting;

  const handleDelete = async () => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }

    setDeleting(true);
    setError(null);
    try {
      const res = await fetch(
        apiUrl("/api/v1/users/me"),
        createAuthenticatedFetchInit(
          {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ confirmation: confirmation.trim() }),
          },
          token,
        ),
      );

      if (!res.ok) {
        const payload = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(payload.detail || "Unable to delete your account. Please try again.");
      }

      // The session is already revoked server-side; clear the client copy so the
      // app cannot briefly render as a signed-in user whose account is gone.
      clearAccessToken("logout");
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete your account.");
      setDeleting(false);
    }
  };

  return (
    <section className="profile-danger-zone">
      <div className="profile-danger-head">
        <AlertTriangle size={18} aria-hidden />
        <h3>Delete account</h3>
      </div>

      {!expanded ? (
        <>
          <p>
            Permanently delete your account and everything attached to it. This cannot be
            undone.
          </p>
          <button
            type="button"
            className="profile-danger-button"
            onClick={() => setExpanded(true)}
          >
            Delete my account
          </button>
        </>
      ) : (
        <>
          <p>
            <strong>This removes:</strong> your profile, your uploaded resume, your
            applications, your saved queries and assistant conversations, your posts and
            comments, and your login.
          </p>
          <p>
            <strong>This keeps, with your identity removed:</strong> anonymous records that an
            impression or click happened — deleting those would retroactively change past
            experiment results — and sign-in security logs, which keep their IP address for
            abuse defence and expire on their own after 90 days. Neither can be traced back to
            you afterwards.
          </p>

          <label className="profile-danger-label" htmlFor="delete-confirmation">
            Type <code>{CONFIRMATION_PHRASE}</code> to confirm
          </label>
          <input
            id="delete-confirmation"
            className="input-base"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            placeholder={CONFIRMATION_PHRASE}
            autoComplete="off"
            disabled={deleting}
          />

          {error ? <p className="profile-danger-error">{error}</p> : null}

          <div className="profile-danger-actions">
            <button
              type="button"
              className="profile-danger-button"
              onClick={handleDelete}
              disabled={!canDelete}
            >
              {deleting ? "Deleting…" : "Permanently delete"}
            </button>
            <button
              type="button"
              className="profile-danger-cancel"
              onClick={() => {
                setExpanded(false);
                setConfirmation("");
                setError(null);
              }}
              disabled={deleting}
            >
              Cancel
            </button>
          </div>
        </>
      )}
    </section>
  );
}
