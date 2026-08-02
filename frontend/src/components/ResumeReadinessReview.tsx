"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, RefreshCw, Sparkles } from "lucide-react";

import { apiUrl } from "@/lib/api";
import { createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage } from "@/lib/error-utils";

type ResumeReviewCategory = {
  key: string;
  label: string;
  score: number;
  maximum: number;
  evidence: string[];
};

type ResumeReview = {
  version: string;
  resume_filename: string;
  score: number;
  summary: string;
  categories: ResumeReviewCategory[];
  strengths: string[];
  weaknesses: string[];
  recommendations: string[];
  advisory: string;
};

type ResumeReadinessReviewProps = {
  resumeFilename: string;
};

function scoreColor(score: number): string {
  if (score >= 75) return "#15803d";
  if (score >= 50) return "#a16207";
  return "#b91c1c";
}

export default function ResumeReadinessReview({ resumeFilename }: ResumeReadinessReviewProps) {
  const [review, setReview] = useState<ResumeReview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadReview = useCallback(async () => {
    const token = getAccessToken();
    if (!token) {
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        apiUrl("/api/v1/users/me/resume/review"),
        createAuthenticatedFetchInit({}, token),
      );
      const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to review this resume."));
      }
      setReview(payload as ResumeReview);
    } catch (requestError) {
      setReview(null);
      setError(requestError instanceof Error ? requestError.message : "Unable to review this resume.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void loadReview();
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [resumeFilename, loadReview]);

  return (
    <section
      aria-live="polite"
      style={{
        marginTop: "1rem",
        padding: "1rem",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        background: "var(--bg-surface-hover)",
        display: "grid",
        gap: "0.9rem",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "flex-start", flexWrap: "wrap" }}>
        <div>
          <h3 style={{ margin: 0, display: "flex", alignItems: "center", gap: "0.45rem" }}>
            <Sparkles size={18} /> Resume Readiness Review
          </h3>
          <p style={{ margin: "0.35rem 0 0", color: "var(--text-secondary)" }}>
            Clear, explainable feedback inspired by modern resume-review workflows.
          </p>
        </div>
        <button type="button" className="btn-secondary" onClick={() => void loadReview()} disabled={loading}>
          <RefreshCw size={15} /> {loading ? "Reviewing..." : "Refresh review"}
        </button>
      </div>

      {loading && !review ? <p style={{ margin: 0 }}>Reviewing your uploaded resume...</p> : null}
      {error ? (
        <div style={{ color: "#b91c1c", display: "flex", gap: "0.45rem", alignItems: "flex-start" }}>
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      ) : null}

      {review ? (
        <>
          <div style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
            <strong style={{ fontSize: "2rem", lineHeight: 1, color: scoreColor(review.score) }}>{review.score}/100</strong>
            <p style={{ margin: 0, color: "var(--text-secondary)", maxWidth: "58rem" }}>{review.summary}</p>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.75rem" }}>
            {review.categories.map((category) => {
              const percent = Math.round((category.score / category.maximum) * 100);
              return (
                <article key={category.key} style={{ border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.75rem", background: "var(--bg-surface)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
                    <strong>{category.label}</strong>
                    <span>{category.score}/{category.maximum}</span>
                  </div>
                  <progress value={category.score} max={category.maximum} aria-label={`${category.label}: ${percent}%`} style={{ width: "100%", margin: "0.55rem 0" }} />
                  <ul style={{ margin: 0, paddingLeft: "1.1rem", color: "var(--text-secondary)", fontSize: "0.9rem" }}>
                    {category.evidence.slice(0, 2).map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </article>
              );
            })}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: "0.9rem" }}>
            <div>
              <strong style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}><CheckCircle2 size={17} color="#15803d" /> Strengths</strong>
              <ul style={{ margin: "0.45rem 0 0", paddingLeft: "1.1rem" }}>{review.strengths.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
            <div>
              <strong style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}><AlertTriangle size={17} color="#a16207" /> Weak spots and improvements</strong>
              <ul style={{ margin: "0.45rem 0 0", paddingLeft: "1.1rem" }}>{review.weaknesses.map((item) => <li key={item}>{item}</li>)}</ul>
              <ul style={{ margin: "0.45rem 0 0", paddingLeft: "1.1rem" }}>{review.recommendations.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          </div>

          <p style={{ margin: 0, color: "var(--text-secondary)", fontSize: "0.86rem" }}>{review.advisory}</p>
        </>
      ) : null}
    </section>
  );
}
