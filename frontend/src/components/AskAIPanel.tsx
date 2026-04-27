"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  BookmarkPlus,
  ExternalLink,
  GitCompare,
  Loader2,
  MessageSquareQuote,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  TimerReset,
} from "lucide-react";

import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";
import { isMongoObjectId, logOpportunityInteraction } from "@/lib/opportunity-interactions";
import StatusBadge from "@/components/ui/StatusBadge";
import SectionCard from "@/components/ui/SectionCard";

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

type StoredTopOpportunity = {
  opportunity_id: string;
  title: string;
  match_score: number;
};

type AskAIHistoryEntry = {
  request_id: string;
  query: string;
  created_at: string;
  top_opportunities: StoredTopOpportunity[];
};

type AskAIHistoryApiEntry = {
  request_id: string;
  query: string;
  created_at: string;
  top_opportunities?: Array<{
    opportunity_id?: string;
    title?: string;
    match_score?: number;
  }>;
};

type AskAISavedQueryApiEntry = {
  query: string;
  surface: string;
  last_used_at: string;
};

type TimelineTone = "info" | "success" | "warning";

type AskAITimelineEvent = {
  id: string;
  timestamp: string;
  label: string;
  detail: string;
  tone: TimelineTone;
};

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

function safeParse<T>(raw: string | null, fallback: T): T {
  if (!raw) {
    return fallback;
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function toHistoryEntry(response: AskAIResponse): AskAIHistoryEntry {
  return {
    request_id: response.request_id,
    query: response.query,
    created_at: new Date().toISOString(),
    top_opportunities: response.insights.top_opportunities.map((item) => ({
      opportunity_id: item.opportunity_id,
      title: item.title,
      match_score: item.match_score,
    })),
  };
}

function toHistoryEntryFromApi(entry: AskAIHistoryApiEntry): AskAIHistoryEntry {
  return {
    request_id: entry.request_id,
    query: entry.query,
    created_at: entry.created_at,
    top_opportunities: (entry.top_opportunities || [])
      .map((item) => ({
        opportunity_id: String(item.opportunity_id || ""),
        title: String(item.title || ""),
        match_score: typeof item.match_score === "number" ? item.match_score : 0,
      }))
      .filter((item) => item.opportunity_id.length > 0),
  };
}

export default function AskAIPanel({ surface, suggestedQueries }: AskAIPanelProps) {
  const askAiTimeoutMs = 30000;
  const storagePrefix = `vidyaverse.ask_ai.${surface}`;
  const savedQueriesStorageKey = `${storagePrefix}.saved_queries`;
  const historyStorageKey = `${storagePrefix}.history`;

  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<AskAIResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);
  const [feedbackNotice, setFeedbackNotice] = useState<string | null>(null);
  const [savedQueries, setSavedQueries] = useState<string[]>([]);
  const [history, setHistory] = useState<AskAIHistoryEntry[]>([]);
  const [compareBaseline, setCompareBaseline] = useState<AskAIHistoryEntry | null>(null);
  const [timelineEvents, setTimelineEvents] = useState<AskAITimelineEvent[]>([]);

  const lastImpressionBatchRef = useRef<string>("");

  const quickQuerySuggestions = useMemo(
    () => uniqueStrings([...savedQueries.slice(0, 6), ...suggestedQueries]).slice(0, 8),
    [savedQueries, suggestedQueries],
  );

  const appendTimeline = useCallback((label: string, detail: string, tone: TimelineTone = "info") => {
    setTimelineEvents((current) => [
      {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        timestamp: new Date().toISOString(),
        label,
        detail,
        tone,
      },
      ...current,
    ].slice(0, 12));
  }, []);

  const persistSavedQuery = useCallback(async (nextQuery: string) => {
    const token = getAccessToken();
    if (!token || nextQuery.trim().length < 2) {
      return;
    }
    try {
      await fetch(apiUrl("/api/v1/opportunities/ask-ai/saved-queries"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query: nextQuery.trim(),
          surface,
        }),
      });
    } catch {
      // Best effort. Local cache still preserves UX.
    }
  }, [surface]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    setSavedQueries(safeParse<string[]>(window.localStorage.getItem(savedQueriesStorageKey), []));
    setHistory(safeParse<AskAIHistoryEntry[]>(window.localStorage.getItem(historyStorageKey), []));
  }, [historyStorageKey, savedQueriesStorageKey]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(savedQueriesStorageKey, JSON.stringify(savedQueries.slice(0, 12)));
  }, [savedQueries, savedQueriesStorageKey]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(historyStorageKey, JSON.stringify(history.slice(0, 40)));
  }, [history, historyStorageKey]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      return;
    }
    let cancelled = false;

    const loadServerState = async () => {
      try {
        const [savedRes, historyRes] = await Promise.all([
          fetch(apiUrl(`/api/v1/opportunities/ask-ai/saved-queries?surface=${encodeURIComponent(surface)}&limit=12`), {
            headers: { Authorization: `Bearer ${token}` },
          }),
          fetch(apiUrl(`/api/v1/opportunities/ask-ai/history?surface=${encodeURIComponent(surface)}&limit=40`), {
            headers: { Authorization: `Bearer ${token}` },
          }),
        ]);

        if (!cancelled && savedRes.ok) {
          const savedPayload = (await savedRes.json().catch(() => [])) as AskAISavedQueryApiEntry[];
          const nextSavedQueries = uniqueStrings(savedPayload.map((item) => String(item.query || "")));
          if (nextSavedQueries.length > 0) {
            setSavedQueries(nextSavedQueries.slice(0, 12));
          }
        }

        if (!cancelled && historyRes.ok) {
          const historyPayload = (await historyRes.json().catch(() => [])) as AskAIHistoryApiEntry[];
          const nextHistory = historyPayload
            .map((entry) => toHistoryEntryFromApi(entry))
            .filter((entry) => entry.request_id.trim().length > 0);
          if (nextHistory.length > 0) {
            setHistory(nextHistory.slice(0, 40));
          }
        }
      } catch {
        // Local storage fallback remains available.
      }
    };

    void loadServerState();
    return () => {
      cancelled = true;
    };
  }, [surface]);

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
    appendTimeline("Query submitted", resolvedQuery, "info");

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), askAiTimeoutMs);
    try {
      const res = await fetch(apiUrl("/api/v1/opportunities/ask-ai"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        signal: controller.signal,
        body: JSON.stringify({ query: resolvedQuery, top_k: 8 }),
      });
      const data = (await res.json().catch(() => null)) as AskAIResponse | { detail?: string } | null;
      if (!res.ok || !data || !("request_id" in data)) {
        const detail = data && "detail" in data && typeof data.detail === "string" ? data.detail : "Ask AI failed.";
        throw new Error(detail);
      }
      setQuery(resolvedQuery);
      setResponse(data);
      setSavedQueries((current) => uniqueStrings([resolvedQuery, ...current]).slice(0, 12));
      setHistory((current) => [toHistoryEntry(data), ...current.filter((entry) => entry.request_id !== data.request_id)].slice(0, 40));
      void persistSavedQuery(resolvedQuery);
      appendTimeline(
        "Retriever response",
        `${data.insights.top_opportunities.length} shortlisted opportunities with ${data.insights.citations.length} citations.`,
        "success",
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        setNotice("Ask AI timed out. Please try again.");
        appendTimeline("Timeout", "Ask AI request exceeded 30 seconds.", "warning");
      } else {
        const detail = error instanceof Error ? error.message : "Ask AI failed.";
        setNotice(detail);
        appendTimeline("Request failed", detail, "warning");
      }
    } finally {
      window.clearTimeout(timeoutId);
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

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 15000);
    try {
      const res = await fetch(apiUrl("/api/v1/opportunities/ask-ai/feedback"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        signal: controller.signal,
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
      appendTimeline(
        value === "up" ? "Positive feedback" : "Corrective feedback",
        value === "up" ? "User marked response as helpful." : "User marked response as missed.",
        value === "up" ? "success" : "warning",
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        setFeedbackNotice("Feedback request timed out.");
      } else {
        setFeedbackNotice(error instanceof Error ? error.message : "Could not save feedback.");
      }
    } finally {
      window.clearTimeout(timeoutId);
    }
  };

  const saveCurrentQuery = () => {
    const normalized = query.trim();
    if (!normalized) {
      return;
    }
    setSavedQueries((current) => uniqueStrings([normalized, ...current]).slice(0, 12));
    void persistSavedQuery(normalized);
    appendTimeline("Saved query", normalized, "info");
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

  const compareSummary = useMemo(() => {
    if (!response || !compareBaseline) {
      return null;
    }

    const currentMap = new Map(
      response.insights.top_opportunities.map((item) => [item.opportunity_id, item.title]),
    );
    const baselineMap = new Map(
      compareBaseline.top_opportunities.map((item) => [item.opportunity_id, item.title]),
    );

    const retained = Array.from(currentMap.keys()).filter((id) => baselineMap.has(id));
    const added = Array.from(currentMap.keys()).filter((id) => !baselineMap.has(id));
    const dropped = Array.from(baselineMap.keys()).filter((id) => !currentMap.has(id));

    return {
      retained: retained.map((id) => currentMap.get(id) || id),
      added: added.map((id) => currentMap.get(id) || id),
      dropped: dropped.map((id) => baselineMap.get(id) || id),
    };
  }, [compareBaseline, response]);

  const dayAgoDiff = useMemo(() => {
    if (!response) {
      return null;
    }

    const now = Date.now();
    const oneDayMs = 24 * 60 * 60 * 1000;
    const previous = history.find((entry) => {
      if (entry.request_id === response.request_id) {
        return false;
      }
      const createdAt = new Date(entry.created_at).getTime();
      return Number.isFinite(createdAt) && now - createdAt >= oneDayMs;
    });

    if (!previous) {
      return null;
    }

    const currentIds = new Set(response.insights.top_opportunities.map((item) => item.opportunity_id));
    const previousIds = new Set(previous.top_opportunities.map((item) => item.opportunity_id));

    const newRows = response.insights.top_opportunities
      .filter((item) => !previousIds.has(item.opportunity_id))
      .map((item) => item.title);
    const removedRows = previous.top_opportunities
      .filter((item) => !currentIds.has(item.opportunity_id))
      .map((item) => item.title);

    return {
      baselineDate: previous.created_at,
      newRows,
      removedRows,
    };
  }, [history, response]);

  const badgeTone = (tone: TimelineTone): "info" | "success" | "warning" => {
    return tone;
  };

  return (
    <SectionCard
      title="Ask for a grounded shortlist"
      subtitle="Query the ranking stack directly, inspect citations, compare shortlist drift, and capture user feedback."
      aside={
        <div style={{ minWidth: "220px", padding: "0.85rem 1rem", border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-md)", background: "var(--bg-base)", boxShadow: "var(--shadow-sm)" }}>
          <div style={{ fontSize: "0.76rem", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-secondary)", marginBottom: "0.35rem" }}>
            Product Loop
          </div>
          <div style={{ fontWeight: 700, lineHeight: 1.45 }}>
            Query
            {" -> "}
            cited answer
            {" -> "}
            feedback
          </div>
        </div>
      }
      status={<StatusBadge tone="live" label="Copilot" />}
      style={{ marginBottom: "2rem" }}
    >
      <div style={{ display: "grid", gap: "0.85rem" }}>
        <label htmlFor={`${surface}-ask-ai`} style={{ fontSize: "0.82rem", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-secondary)" }}>
          What should the retriever solve?
        </label>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto", gap: "0.8rem" }}>
          <input
            id={`${surface}-ask-ai`}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void runAskAI();
              }
            }}
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
            type="button"
            className="btn-secondary"
            onClick={saveCurrentQuery}
            disabled={query.trim().length < 2}
            style={{ minWidth: "120px", display: "inline-flex", alignItems: "center", justifyContent: "center", gap: "0.35rem", border: "2px solid var(--border-subtle)" }}
          >
            <BookmarkPlus size={15} />
            Save
          </button>
          <button
            type="button"
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
          {quickQuerySuggestions.map((suggestion, index) => (
            <button
              key={`${suggestion}-${index}`}
              type="button"
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
        <div style={{ display: "grid", gap: "1rem", marginTop: "1rem" }}>
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
              <div style={{ minWidth: "220px", display: "grid", gap: "0.45rem" }}>
                <div style={{ fontSize: "0.78rem", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-secondary)" }}>
                  Request ID
                </div>
                <code style={{ fontSize: "0.82rem", fontWeight: 700 }}>{response.request_id}</code>
                <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => {
                      setCompareBaseline(toHistoryEntry(response));
                      appendTimeline("Baseline set", "Current shortlist saved for compare mode.", "info");
                    }}
                    style={{ border: "2px solid var(--border-subtle)", fontSize: "0.82rem", padding: "0.42rem 0.62rem" }}
                  >
                    <GitCompare size={14} /> Set Baseline
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => {
                      setCompareBaseline(null);
                      appendTimeline("Compare reset", "Cleared compare baseline.", "info");
                    }}
                    style={{ border: "2px solid var(--border-subtle)", fontSize: "0.82rem", padding: "0.42rem 0.62rem" }}
                  >
                    <TimerReset size={14} /> Reset
                  </button>
                </div>
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

          {compareBaseline && compareSummary ? (
            <div className="card-panel" style={{ display: "grid", gap: "0.7rem", background: "var(--bg-base)" }}>
              <div style={{ fontWeight: 900 }}>Compare Two Shortlists</div>
              <div style={{ color: "var(--text-muted)", fontWeight: 700, fontSize: "0.86rem" }}>
                Baseline: {new Date(compareBaseline.created_at).toLocaleString()} · Query: {compareBaseline.query}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: "0.7rem" }}>
                <div style={{ border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.7rem" }}>
                  <div style={{ fontWeight: 900, marginBottom: "0.35rem" }}>Retained ({compareSummary.retained.length})</div>
                  <div style={{ color: "var(--text-secondary)", fontWeight: 700, fontSize: "0.85rem" }}>
                    {compareSummary.retained.slice(0, 4).join(" · ") || "None"}
                  </div>
                </div>
                <div style={{ border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.7rem" }}>
                  <div style={{ fontWeight: 900, marginBottom: "0.35rem" }}>New ({compareSummary.added.length})</div>
                  <div style={{ color: "var(--text-secondary)", fontWeight: 700, fontSize: "0.85rem" }}>
                    {compareSummary.added.slice(0, 4).join(" · ") || "None"}
                  </div>
                </div>
                <div style={{ border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.7rem" }}>
                  <div style={{ fontWeight: 900, marginBottom: "0.35rem" }}>Dropped ({compareSummary.dropped.length})</div>
                  <div style={{ color: "var(--text-secondary)", fontWeight: 700, fontSize: "0.85rem" }}>
                    {compareSummary.dropped.slice(0, 4).join(" · ") || "None"}
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {dayAgoDiff ? (
            <div className="card-panel" style={{ display: "grid", gap: "0.65rem", background: "var(--bg-base)" }}>
              <div style={{ fontWeight: 900 }}>Why this changed since yesterday</div>
              <div style={{ color: "var(--text-muted)", fontWeight: 700, fontSize: "0.86rem" }}>
                Compared against snapshot from {new Date(dayAgoDiff.baselineDate).toLocaleString()}.
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0.7rem" }}>
                <div style={{ border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.7rem" }}>
                  <div style={{ fontWeight: 800, marginBottom: "0.25rem" }}>New recommendations</div>
                  <div style={{ color: "var(--text-secondary)", fontWeight: 700, fontSize: "0.85rem" }}>
                    {dayAgoDiff.newRows.slice(0, 5).join(" · ") || "No changes"}
                  </div>
                </div>
                <div style={{ border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.7rem" }}>
                  <div style={{ fontWeight: 800, marginBottom: "0.25rem" }}>Removed recommendations</div>
                  <div style={{ color: "var(--text-secondary)", fontWeight: 700, fontSize: "0.85rem" }}>
                    {dayAgoDiff.removedRows.slice(0, 5).join(" · ") || "No removals"}
                  </div>
                </div>
              </div>
            </div>
          ) : null}

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
                  type="button"
                  className="btn-secondary"
                  onClick={() => void submitFeedback("up")}
                  disabled={Boolean(feedback)}
                  style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", border: "2px solid var(--border-subtle)" }}
                >
                  <ThumbsUp size={14} />
                  Helpful
                </button>
                <button
                  type="button"
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

          <div className="card-panel" style={{ display: "grid", gap: "0.6rem", background: "var(--bg-base)" }}>
            <div style={{ display: "inline-flex", alignItems: "center", gap: "0.45rem", fontWeight: 900 }}>
              <Sparkles size={14} /> Reasoning Timeline
            </div>
            {timelineEvents.length === 0 ? (
              <div style={{ color: "var(--text-muted)", fontWeight: 700 }}>Timeline will appear after the first query.</div>
            ) : (
              <div style={{ display: "grid", gap: "0.45rem" }}>
                {timelineEvents.map((event) => (
                  <div
                    key={event.id}
                    style={{
                      border: "2px solid var(--border-subtle)",
                      borderRadius: "var(--radius-sm)",
                      padding: "0.55rem 0.7rem",
                      background: "var(--bg-surface)",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "flex-start",
                      gap: "0.6rem",
                      flexWrap: "wrap",
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 900 }}>{event.label}</div>
                      <div style={{ color: "var(--text-secondary)", fontWeight: 700, fontSize: "0.84rem" }}>{event.detail}</div>
                    </div>
                    <div style={{ display: "grid", justifyItems: "end", gap: "0.25rem" }}>
                      <StatusBadge tone={badgeTone(event.tone)} label={event.tone} />
                      <span style={{ color: "var(--text-muted)", fontSize: "0.76rem", fontWeight: 700 }}>
                        {new Date(event.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </SectionCard>
  );
}
