"use client";

import { useCallback, useEffect, useRef, type RefObject } from "react";

import {
  logOpportunityInteractionsBatch,
  type OpportunityInteractionInput,
  type OpportunityInteractionType,
} from "@/lib/opportunity-interactions";

const FLUSH_INTERVAL_MS = 5_000;

export interface TrackableOpportunity {
  id: string;
  ranking_mode?: string | null;
  experiment_key?: string | null;
  experiment_variant?: string | null;
  rank_position?: number | null;
  match_score?: number | null;
  model_version_id?: string | null;
  query?: string | null;
}

export interface TrackingContext {
  surface: string;
  activeTab?: string | null;
  coldStart?: boolean;
}

export interface TrackInteractionOptions {
  dwellTimeMs?: number | null;
  scrollDepth?: number | null;
  features?: Record<string, unknown> | null;
}

function sessionId(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const key = "vidyaverse_interaction_session_id";
  const existing = window.sessionStorage.getItem(key);
  if (existing) {
    return existing;
  }
  const value =
    typeof window.crypto?.randomUUID === "function"
      ? window.crypto.randomUUID()
      : `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  window.sessionStorage.setItem(key, value);
  return value;
}

function toInput(
  opportunity: TrackableOpportunity,
  interactionType: OpportunityInteractionType,
  context: TrackingContext,
  options?: TrackInteractionOptions,
): OpportunityInteractionInput {
  return {
    opportunityId: opportunity.id,
    interactionType,
    rankingMode: opportunity.ranking_mode || "baseline",
    experimentKey: opportunity.experiment_key || "ranking_mode",
    experimentVariant: opportunity.experiment_variant || opportunity.ranking_mode || "baseline",
    rankPosition: opportunity.rank_position ?? null,
    matchScore: opportunity.match_score ?? null,
    query: opportunity.query ?? null,
    modelVersionId: opportunity.model_version_id ?? null,
    dwellTimeMs: options?.dwellTimeMs ?? null,
    scrollDepth: options?.scrollDepth ?? null,
    sessionId: sessionId(),
    coldStart: Boolean(context.coldStart),
    features: {
      surface: context.surface,
      active_tab: context.activeTab || null,
      ...(options?.features || {}),
    },
  };
}

export function useTrackInteraction(context: TrackingContext) {
  const queueRef = useRef<OpportunityInteractionInput[]>([]);

  const flush = useCallback(async () => {
    const batch = queueRef.current.splice(0);
    if (batch.length === 0) {
      return;
    }
    const ok = await logOpportunityInteractionsBatch(batch);
    if (!ok) {
      queueRef.current = [...batch, ...queueRef.current].slice(0, 250);
    }
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => {
      void flush();
    }, FLUSH_INTERVAL_MS);
    const onPageHide = () => {
      void flush();
    };
    window.addEventListener("pagehide", onPageHide);
    document.addEventListener("visibilitychange", onPageHide);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("pagehide", onPageHide);
      document.removeEventListener("visibilitychange", onPageHide);
      void flush();
    };
  }, [flush]);

  return useCallback(
    (
      opportunity: TrackableOpportunity,
      interactionType: OpportunityInteractionType,
      options?: TrackInteractionOptions,
    ) => {
      queueRef.current.push(toInput(opportunity, interactionType, context, options));
      if (queueRef.current.length >= 25) {
        void flush();
      }
    },
    [context, flush],
  );
}

export function useTrackDwell(
  opportunity: TrackableOpportunity,
  context: TrackingContext,
  options: { minDwellMs?: number } = {},
) {
  const track = useTrackInteraction(context);
  const startedAtRef = useRef<number | null>(null);
  const minDwellMs = options.minDwellMs ?? 1_000;

  const beginDwell = useCallback(() => {
    startedAtRef.current = performance.now();
  }, []);

  const endDwell = useCallback(() => {
    if (startedAtRef.current === null) {
      return;
    }
    const dwellTimeMs = Math.max(0, Math.round(performance.now() - startedAtRef.current));
    startedAtRef.current = null;
    if (dwellTimeMs >= minDwellMs) {
      track(opportunity, "expand", { dwellTimeMs });
    }
  }, [minDwellMs, opportunity, track]);

  useEffect(() => endDwell, [endDwell]);

  return { beginDwell, endDwell };
}

export function useTrackScroll(
  containerRef: RefObject<HTMLElement | null>,
  opportunity: TrackableOpportunity,
  context: TrackingContext,
  options: { minScrollDepth?: number } = {},
) {
  const track = useTrackInteraction(context);
  const maxDepthRef = useRef(0);
  const minScrollDepth = options.minScrollDepth ?? 50;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const updateDepth = () => {
      const scrollable = Math.max(1, container.scrollHeight - container.clientHeight);
      const depth = Math.min(100, Math.max(0, (container.scrollTop / scrollable) * 100));
      maxDepthRef.current = Math.max(maxDepthRef.current, depth);
    };
    container.addEventListener("scroll", updateDepth, { passive: true });
    updateDepth();
    return () => {
      container.removeEventListener("scroll", updateDepth);
      if (maxDepthRef.current >= minScrollDepth) {
        track(opportunity, "expand", { scrollDepth: Math.round(maxDepthRef.current) });
      }
    };
  }, [containerRef, minScrollDepth, opportunity, track]);
}
