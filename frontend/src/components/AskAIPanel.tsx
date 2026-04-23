"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Bot, ExternalLink, Loader2, MessageSquareQuote, Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";

import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";
import { isMongoObjectId, logOpportunityInteraction } from "@/lib/opportunity-interactions";

interface Citation {
  opportunity_id: string;
  url: string;
  title?: string | null;
  source?: string | null;
}

interface AskAIResponse {
  request_id: string;
  query: string;
  insights: {
    summary: string;
    recommended_action: string;
    deadline_urgency: string;
    citations: Citation[];
    top_opportunities: Array<{
      opportunity_id: string;
      title: string;
      why_fit: string;
      urgency: "low" | "medium" | "high";
      match_score: number;
      citations: Citation[];
    }>;
  };
}

interface AskAIPanelProps {
  surface: string;
  suggestedQueries: string[];
}

export default function AskAIPanel({ surface, suggestedQueries }: AskAIPanelProps) {
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<AskAIResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);
  const [feedbackNotice, setFeedbackNotice] = useState<string | null>(null);
  const lastImpressionBatchRef = useRef<string>("");

  const logAskAIInteraction = useCallback(async (
    item: AskAIResponse["insights"]["top_opportunities"][number],
    interactionType: "impression" | "click",
    rankPosition: number,
    requestId: string,
    resolvedQuery: string,
    metadata?: Record<string, unknown>
  ): Promise<void> => {
    if (!isMongoObjectId(item.opportunity_id)) {
      return;
    }
    await logOpportunityInteraction({
      opportunityId: item.opportunity_id,
      interactionType,
      rankingMode: "semantic",
      experimentKey: "ask_ai_rag",
      experimentVariant: "semantic",
      rankPosition,
      matchScore: item.match_score,
      query: resolvedQuery,
      features: {
        surface,
        ask_ai_request_id: requestId,
        ask_ai_urgency: item.urgency,
        ...metadata,
      },
    });
  }, [surface]);

  const runAskAI = async (nextQuery?: string) => {
    const resolvedQuery = (nextQuery ?? query).trim();
    if (!resolvedQuery || loading) {
      return;
    }

    const token = getAccessToken();
    if (!token) {
      setNotice("Sign in to use Ask AI.");
      return;
    }

    setLoading(true);
    setNotice(null);
    setFeedback(null);
    setFeedbackNotice(null);
    try {
      const res = await fetch(apiUrl("/api/v1/opportunities/ask-ai"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query: resolvedQuery, top_k: 8 }),
      });
      const data = (await res.json().catch(() => null)) as AskAIResponse | { detail?: string } | null;
      if (!res.ok || !data || !("request_id" in data)) {
        const detail = data && "detail" in data && typeof data.detail === "string" ? data.detail : "Ask AI failed.";
        throw new Error(detail);
      }
      setQuery(resolvedQuery);
      setResponse(data);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Ask AI failed.");
    } finally {
      setLoading(false);
    }
  };

  const submitFeedback = async (value: "up" | "down") => {
    if (!response || feedback) {
      return;
    }

    const token = getAccessToken();
    if (!token) {
      setFeedbackNotice("Sign in to send feedback.");
      return;
    }

    try {
      const res = await fetch(apiUrl("/api/v1/opportunities/ask-ai/feedback"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          request_id: response.request_id,
          query: response.query,
          feedback: value,
          response_summary: response.insights.summary,
          citations: response.insights.citations,
          surface,
          metadata: {
            recommended_action: response.insights.recommended_action,
            deadline_urgency: response.insights.deadline_urgency,
            citation_count: response.insights.citations.length,
          },
        }),
      });
      if (!res.ok) {
        throw new Error("Could not save feedback.");
      }
      setFeedback(value);
      setFeedbackNotice(value === "up" ? "Helpful answer logged." : "Feedback logged for improvement.");
    } catch (error) {
      setFeedbackNotice(error instanceof Error ? error.message : "Could not save feedback.");
    }
  };

  useEffect(() => {
    const token = getAccessToken();
    if (!token || !response || response.insights.top_opportunities.length === 0) {
      return;
    }
    const batchSignature = `${response.request_id}:${response.insights.top_opportunities
      .map((item, idx) => `${item.opportunity_id}:${idx + 1}`)
      .join("|")}`;
    if (batchSignature === lastImpressionBatchRef.current) {
      return;
    }
    lastImpressionBatchRef.current = batchSignature;

    void Promise.allSettled(
      response.insights.top_opportunities.map((item, idx) =>
        logAskAIInteraction(item, "impression", idx + 1, response.request_id, response.query, {
          origin: "ask_ai_top_opportunity",
        })
      )
    );
  }, [logAskAIInteraction, response]);

  return (
    <section
      className="card-panel"
      style={{
        marginBottom: "2rem",
        display: "grid",
        gap: "1.1rem",
        background:
          "linear-gradient(135deg, color-mix(in srgb, var(--brand-primary) 10%, transparent), var(--bg-surface) 60%)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "start", flexWrap: "wrap" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: "0.45rem", marginBottom: "0.7rem", fontSize: "0.78rem", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", padding: "0.35rem 0.65rem", borderRadius: "999px", border: "2px solid var(--border-subtle)", background: "#ffffff", color: "#000000" }}>
            <Sparkles size={14} />
            Ask AI
          </div>
          <h2 style={{ margin: 0, fontSize: "1.7rem", fontWeight: 900, color: "var(--text-primary)" }}>
            Ask for a grounded shortlist
          </h2>
          <p style={{ margin: "0.5rem 0 0", color: "var(--text-secondary)", fontWeight: 600, maxWidth: "720px" }}>
            Query the ranking stack directly, inspect citations, and send feedback on whether the answer actually helped.
          </p>
        </div>
        <div style={{ minWidth: "220px", padding: "0.85rem 1rem", border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-md)", background: "var(--bg-base)", boxShadow: "var(--shadow-sm)" }}>
          <div style={{ fontSize: "0.76rem", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-secondary)", marginBottom: "0.35rem" }}>
            Product Loop
          </div>
          <div style={{ fontWeight: 700, lineHeight: 1.45 }}>
            Query
            {" -> "}
            cited answer
            {" -> "}
            user feedback
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gap: "0.85rem" }}>
        <label htmlFor={`${surface}-ask-ai`} style={{ fontSize: "0.82rem", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-secondary)" }}>
          What should the retriever solve?
        </label>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: "0.8rem" }}>
          <input
            id={`${surface}-ask-ai`}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Example: research internships in NLP with recent deadlines and strong fit for Python + evaluation"
            style={{
              width: "100%",
              borderRadius: "var(--radius-md)",
              border: "2px solid var(--border-subtle)",
              padding: "0.95rem 1rem",
              background: "var(--bg-base)",
              color: "var(--text-primary)",
              fontSize: "0.98rem",
              fontWeight: 600,
            }}
          />
          <button
            className="btn-primary"
            onClick={() => void runAskAI()}
            disabled={loading || query.trim().length < 2}
            style={{ minWidth: "140px", display: "inline-flex", alignItems: "center", justifyContent: "center", gap: "0.45rem", border: "2px solid #000000" }}
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Bot size={16} />}
            {loading ? "Thinking..." : "Ask AI"}
          </button>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem" }}>
          {suggestedQueries.map((suggestion) => (
            <button
              key={suggestion}
              className="btn-secondary"
              onClick={() => void runAskAI(suggestion)}
              disabled={loading}
              style={{ border: "2px solid var(--border-subtle)", fontSize: "0.88rem", padding: "0.55rem 0.85rem" }}
            >
              {suggestion}
            </button>
          ))}
        </div>
        {notice && (
          <div style={{ color: "#8a1f1f", fontWeight: 700 }}>
            {notice}
          </div>
        )}
      </div>

      {response && (
        <div style={{ display: "grid", gap: "1rem" }}>
          <div style={{ padding: "1rem 1.1rem", borderRadius: "var(--radius-md)", border: "2px solid var(--border-subtle)", background: "var(--bg-base)", boxShadow: "var(--shadow-sm)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "start", flexWrap: "wrap", marginBottom: "0.75rem" }}>
              <div>
                <div style={{ fontSize: "0.78rem", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-secondary)", marginBottom: "0.25rem" }}>
                  Summary
                </div>
                <div style={{ fontSize: "1.05rem", fontWeight: 700, lineHeight: 1.55, color: "var(--text-primary)" }}>
                  {response.insights.summary}
                </div>
              </div>
              <div style={{ minWidth: "210px", display: "grid", gap: "0.45rem" }}>
                <div style={{ fontSize: "0.78rem", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-secondary)" }}>
                  Request ID
                </div>
                <code style={{ fontSize: "0.82rem", fontWeight: 700 }}>{response.request_id}</code>
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0.85rem" }}>
              <div style={{ padding: "0.85rem 0.95rem", borderRadius: "var(--radius-md)", border: "2px solid var(--border-subtle)", background: "var(--bg-surface)" }}>
                <div style={{ fontSize: "0.78rem", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-secondary)", marginBottom: "0.35rem" }}>
                  Recommended Action
                </div>
                <div style={{ fontWeight: 700 }}>{response.insights.recommended_action}</div>
              </div>
              <div style={{ padding: "0.85rem 0.95rem", borderRadius: "var(--radius-md)", border: "2px solid var(--border-subtle)", background: "var(--bg-surface)" }}>
                <div style={{ fontSize: "0.78rem", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-secondary)", marginBottom: "0.35rem" }}>
                  Deadline Signal
                </div>
                <div style={{ fontWeight: 700 }}>{response.insights.deadline_urgency}</div>
              </div>
            </div>
          </div>

          <div style={{ display: "grid", gap: "0.85rem" }}>
            {response.insights.top_opportunities.map((item, index) => (
              <article key={item.opportunity_id} className="card-panel" style={{ display: "grid", gap: "0.8rem", background: "var(--bg-base)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "start", flexWrap: "wrap" }}>
                  <div>
                    <div style={{ fontSize: "0.78rem", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-secondary)", marginBottom: "0.35rem" }}>
                      Top Match
                    </div>
                    <h3 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 900 }}>{item.title}</h3>
                  </div>
                  <div style={{ display: "flex", gap: "0.55rem", flexWrap: "wrap" }}>
                    <span style={{ padding: "0.35rem 0.6rem", borderRadius: "999px", border: "2px solid var(--border-subtle)", background: "#ffffff", color: "#000000", fontWeight: 900 }}>
                      {Math.round(item.match_score)} / 100
                    </span>
                    <span style={{ padding: "0.35rem 0.6rem", borderRadius: "999px", border: "2px solid var(--border-subtle)", background: "var(--bg-surface)", fontWeight: 800 }}>
                      {item.urgency} urgency
                    </span>
                  </div>
                </div>
                <p style={{ margin: 0, color: "var(--text-secondary)", fontWeight: 600, lineHeight: 1.55 }}>
                  {item.why_fit}
                </p>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem" }}>
                  {item.citations.map((citation) => (
                    <a
                      key={`${item.opportunity_id}-${citation.url}`}
                      href={citation.url}
                      target="_blank"
                      rel="noreferrer"
                      className="btn-secondary"
                      onClick={() =>
                        void logAskAIInteraction(item, "click", index + 1, response.request_id, response.query, {
                          origin: "ask_ai_citation",
                          citation_url: citation.url,
                          citation_title: citation.title || citation.source || null,
                        })
                      }
                      style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", border: "2px solid var(--border-subtle)", padding: "0.55rem 0.85rem", fontSize: "0.88rem" }}
                    >
                      <MessageSquareQuote size={14} />
                      {citation.title || citation.source || "Citation"}
                      <ExternalLink size={14} />
                    </a>
                  ))}
                </div>
              </article>
            ))}
          </div>

          <div className="card-panel" style={{ display: "grid", gap: "0.8rem", background: "var(--bg-base)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
              <div>
                <div style={{ fontSize: "0.78rem", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-secondary)", marginBottom: "0.3rem" }}>
                  Feedback
                </div>
                <div style={{ fontWeight: 700 }}>
                  Was this answer actually useful?
                </div>
              </div>
              <div style={{ display: "flex", gap: "0.6rem" }}>
                <button
                  className="btn-secondary"
                  onClick={() => void submitFeedback("up")}
                  disabled={Boolean(feedback)}
                  style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", border: "2px solid var(--border-subtle)" }}
                >
                  <ThumbsUp size={14} />
                  Helpful
                </button>
                <button
                  className="btn-secondary"
                  onClick={() => void submitFeedback("down")}
                  disabled={Boolean(feedback)}
                  style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", border: "2px solid var(--border-subtle)" }}
                >
                  <ThumbsDown size={14} />
                  Missed
                </button>
              </div>
            </div>
            {feedbackNotice && <div style={{ color: "var(--text-secondary)", fontWeight: 700 }}>{feedbackNotice}</div>}
          </div>
        </div>
      )}
    </section>
  );
}
