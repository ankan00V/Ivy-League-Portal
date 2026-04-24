"use client";

import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";
import { logTrackedOpportunityEvent } from "@/lib/opportunity-feed-tracker";
import { startTransition, useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";

export interface Opportunity {
  id: string;
  title: string;
  description: string;
  url: string;
  opportunity_type: string;
  university: string;
  domain: string;
  source?: string;
  created_at?: string;
  updated_at?: string;
  last_seen_at?: string;
  deadline?: string;
  ranking_mode?: string;
  experiment_key?: string;
  experiment_variant?: string;
  rank_position?: number;
  match_score?: number;
  model_version_id?: string;
}

type OpportunityGroupKey = "competitive" | "career" | "other";
type OpportunityGroups = Record<OpportunityGroupKey, Opportunity[]>;
type OpportunityInteraction = "impression" | "click" | "save" | "apply";

const FEED_REFRESH_MS = 60 * 1000;
const FEED_RETRY_MS = 10 * 1000;
const COMPETITIVE_KEYWORDS = [
  "hackathon",
  "competition",
  "challenge",
  "quiz",
  "conference",
  "workshop",
  "bootcamp",
  "webinar",
  "buildathon",
  "ctf",
];
const CAREER_KEYWORDS = ["internship", "intern", "job", "hiring", "developer", "engineer", "lead"];

const buildOpportunitiesSignature = (items: Opportunity[]): string =>
  items
    .map(
      (item) =>
        `${item.id}:${item.created_at || ""}:${item.updated_at || ""}:${item.last_seen_at || ""}:${item.deadline || ""}:${item.title}:${item.source || ""}`,
    )
    .join("|");

const enrichOpportunity = (item: Opportunity, index: number): Opportunity => ({
  ...item,
  ranking_mode: item.ranking_mode || "baseline",
  experiment_key: item.experiment_key || "ranking_mode",
  experiment_variant: item.experiment_variant || item.ranking_mode || "baseline",
  rank_position: item.rank_position ?? index + 1,
});

export function useOpportunityFeed() {
  const [activeTab, setActiveTab] = useState("All");
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [savedOpportunityIds, setSavedOpportunityIds] = useState<Record<string, boolean>>({});
  const [imageFallbackMap, setImageFallbackMap] = useState<Record<string, boolean>>({});
  const opportunitiesSignatureRef = useRef<string>("");
  const scraperTriggerAttemptedRef = useRef(false);

  const domains = useMemo(() => {
    const apiDomains = Array.from(new Set(opportunities.map((item) => item.domain))).filter(Boolean);
    return ["All", ...apiDomains];
  }, [opportunities]);

  const triggerLiveRefresh = useEffectEvent(async () => {
    const token = getAccessToken();
    if (!token) {
      return;
    }
    try {
      await fetch(apiUrl("/api/v1/opportunities/trigger-scraper"), {
        method: "POST",
        credentials: "include",
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "unknown error";
      console.warn(`[Opportunities] Trigger scraper failed: ${message}`);
    }
  });

  const fetchOpportunities = useEffectEvent(async () => {
    try {
      const token = getAccessToken();
      if (token) {
        const personalizedRes = await fetch(
          apiUrl("/api/v1/opportunities/recommended/me?limit=100&ranking_mode=ab"),
          {
            headers: { Authorization: `Bearer ${token}` },
          },
        );
        if (personalizedRes.ok) {
          const rawData = (await personalizedRes.json()) as Opportunity[];
          const data = rawData.map((item, idx) => enrichOpportunity(item, idx));
          const nextSignature = buildOpportunitiesSignature(data);
          if (nextSignature !== opportunitiesSignatureRef.current) {
            opportunitiesSignatureRef.current = nextSignature;
            startTransition(() => {
              setOpportunities(data);
            });
          }
          scraperTriggerAttemptedRef.current = false;
          setNotice(null);
          return;
        }
      }

      const res = await fetch(apiUrl("/api/v1/opportunities/"), { credentials: "include" });
      if (res.ok) {
        const rawData = (await res.json()) as Opportunity[];
        const data = rawData.map((item, idx) => enrichOpportunity(item, idx));
        const nextSignature = buildOpportunitiesSignature(data);
        if (nextSignature !== opportunitiesSignatureRef.current) {
          opportunitiesSignatureRef.current = nextSignature;
          startTransition(() => {
            setOpportunities(data);
          });
        }
        if (data.length === 0) {
          setNotice("Refreshing live opportunities...");
          if (!scraperTriggerAttemptedRef.current) {
            scraperTriggerAttemptedRef.current = true;
            void triggerLiveRefresh();
          }
        } else {
          scraperTriggerAttemptedRef.current = false;
          setNotice((current) =>
            current === "Refreshing live opportunities..." ||
            current === "Live opportunities are temporarily unavailable. Retrying..." ||
            current === "Backend API is unavailable. Retrying..."
              ? null
              : current,
          );
        }
        return;
      }

      const errorPayload = await res.json().catch(() => null);
      const errorDetail = typeof errorPayload?.detail === "string" ? errorPayload.detail : "";
      const nextNotice = errorDetail.includes("Upstream backend unavailable")
        ? "Backend API is unavailable. Retrying..."
        : "Live opportunities are temporarily unavailable. Retrying...";
      setNotice(nextNotice);
      if (!scraperTriggerAttemptedRef.current) {
        scraperTriggerAttemptedRef.current = true;
        void triggerLiveRefresh();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "unknown error";
      console.warn(`[Opportunities] Fetch failed: ${message}`);
      setNotice("Backend API is unavailable. Retrying...");
      if (!scraperTriggerAttemptedRef.current) {
        scraperTriggerAttemptedRef.current = true;
        void triggerLiveRefresh();
      }
    } finally {
      setLoading(false);
    }
  });

  const logOpportunityEvent = useCallback(
    async (opportunity: Opportunity, interactionType: OpportunityInteraction) => {
      await logTrackedOpportunityEvent(opportunity, interactionType, {
        surface: "opportunities_page",
        activeTab,
      });
    },
    [activeTab],
  );

  useEffect(() => {
    void fetchOpportunities();
    void triggerLiveRefresh();
  }, []);

  useEffect(() => {
    const refreshMs = opportunities.length > 0 ? FEED_REFRESH_MS : FEED_RETRY_MS;
    const interval = window.setInterval(() => {
      void fetchOpportunities();
    }, refreshMs);
    return () => window.clearInterval(interval);
  }, [opportunities.length]);

  const selectOpportunitiesForTab = useCallback(
    (tab: string): Opportunity[] => (tab === "All" ? opportunities : opportunities.filter((item) => item.domain === tab)),
    [opportunities],
  );

  const selectOpportunityById = useCallback(
    (id: string): Opportunity | null => opportunities.find((item) => item.id === id) || null,
    [opportunities],
  );

  const filtered = useMemo(() => {
    const source = selectOpportunitiesForTab(activeTab);
    const getSortTimestamp = (opportunity: Opportunity) =>
      new Date(opportunity.last_seen_at || opportunity.updated_at || opportunity.created_at || 0).getTime();
    return [...source].sort((a, b) => getSortTimestamp(b) - getSortTimestamp(a));
  }, [activeTab, selectOpportunitiesForTab]);

  const grouped = useMemo<OpportunityGroups>(() => {
    const matchesKeyword = (value: string, keywords: string[]) => keywords.some((keyword) => value.includes(keyword));

    const groups: OpportunityGroups = {
      competitive: [],
      career: [],
      other: [],
    };

    for (let idx = 0; idx < filtered.length; idx += 1) {
      const opportunity = enrichOpportunity(filtered[idx], idx);
      const typeValue = (opportunity.opportunity_type || "").toLowerCase().trim();
      const titleValue = (opportunity.title || "").toLowerCase().trim();
      const descriptionValue = (opportunity.description || "").toLowerCase().trim();
      const haystack = `${typeValue} ${titleValue} ${descriptionValue}`;

      if (matchesKeyword(haystack, CAREER_KEYWORDS)) {
        groups.career.push(opportunity);
        continue;
      }
      if (matchesKeyword(haystack, COMPETITIVE_KEYWORDS)) {
        groups.competitive.push(opportunity);
        continue;
      }
      groups.other.push(opportunity);
    }

    return groups;
  }, [filtered]);

  const visibleOpportunities = useMemo(() => [...grouped.competitive, ...grouped.other], [grouped]);
  const trackerContext = useMemo(() => ({ surface: "opportunities_page", activeTab }), [activeTab]);

  const optimisticallySaveOpportunity = useCallback((opportunityId: string) => {
    let previousSavedState = false;
    setSavedOpportunityIds((current) => {
      previousSavedState = Boolean(current[opportunityId]);
      return { ...current, [opportunityId]: true };
    });
    return () => {
      setSavedOpportunityIds((current) => {
        if (previousSavedState) {
          return { ...current, [opportunityId]: true };
        }
        const next = { ...current };
        delete next[opportunityId];
        return next;
      });
    };
  }, []);

  const handleSave = useCallback(
    async (opportunity: Opportunity) => {
      const rollback = optimisticallySaveOpportunity(opportunity.id);
      try {
        await logOpportunityEvent(opportunity, "save");
      } catch {
        rollback();
      }
    },
    [logOpportunityEvent, optimisticallySaveOpportunity],
  );

  const handleApply = useCallback(
    async (opportunity: Opportunity) => {
      const token = getAccessToken();
      if (!token) {
        setNotice("Sign in to use one-click application.");
        return;
      }

      try {
        await logOpportunityEvent(opportunity, "click");
      } catch {
        // Best effort. Application flow should continue even if click telemetry fails.
      }

      setApplyingId(opportunity.id);
      setNotice(null);
      try {
        const query = new URLSearchParams({
          ranking_mode: opportunity.ranking_mode || "baseline",
          experiment_key: opportunity.experiment_key || "ranking_mode",
          experiment_variant: opportunity.experiment_variant || opportunity.ranking_mode || "baseline",
          rank_position: String(opportunity.rank_position ?? 1),
        });
        if (typeof opportunity.match_score === "number") {
          query.set("match_score", String(opportunity.match_score));
        }
        if (opportunity.model_version_id) {
          query.set("model_version_id", opportunity.model_version_id);
        }
        const res = await fetch(apiUrl(`/api/v1/applications/${opportunity.id}?${query.toString()}`), {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });
        const data = (await res.json().catch(() => ({}))) as { detail?: string };
        if (!res.ok) {
          throw new Error(data.detail || "Application failed");
        }
        setNotice("Saved to your Applications. Redirecting...");
        if (typeof window !== "undefined") {
          if (opportunity.url) {
            window.location.assign(opportunity.url);
            return;
          }
          setNotice("Saved to your Applications.");
        }
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "Could not submit application.");
      } finally {
        setApplyingId(null);
      }
    },
    [logOpportunityEvent],
  );

  const markImageFallback = useCallback((opportunityId: string) => {
    setImageFallbackMap((current) => {
      if (current[opportunityId]) {
        return current;
      }
      return { ...current, [opportunityId]: true };
    });
  }, []);

  return {
    activeTab,
    setActiveTab,
    opportunities,
    loading,
    notice,
    applyingId,
    savedOpportunityIds,
    imageFallbackMap,
    domains,
    grouped,
    visibleOpportunities,
    trackerContext,
    selectOpportunitiesForTab,
    selectOpportunityById,
    handleSave,
    handleApply,
    markImageFallback,
  };
}
