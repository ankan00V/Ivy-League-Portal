import { useEffect, useRef } from "react";

import { logOpportunityInteraction, type OpportunityInteractionInput, type OpportunityInteractionType } from "@/lib/opportunity-interactions";

export interface FeedTrackedOpportunity {
  id: string;
  ranking_mode?: string;
  experiment_key?: string;
  experiment_variant?: string;
  rank_position?: number;
  match_score?: number;
  model_version_id?: string;
  query?: string | null;
}

export interface FeedTrackerContext {
  surface: string;
  activeTab: string;
}

export async function logTrackedOpportunityEvent(
  opportunity: FeedTrackedOpportunity,
  interactionType: OpportunityInteractionType,
  context: FeedTrackerContext
): Promise<boolean> {
  const payload: OpportunityInteractionInput = {
    opportunityId: opportunity.id,
    interactionType,
    rankingMode: opportunity.ranking_mode || "baseline",
    experimentKey: opportunity.experiment_key || "ranking_mode",
    experimentVariant: opportunity.experiment_variant || opportunity.ranking_mode || "baseline",
    rankPosition: opportunity.rank_position ?? null,
    matchScore: opportunity.match_score ?? null,
    query: opportunity.query ?? null,
    modelVersionId: opportunity.model_version_id ?? null,
    features: {
      surface: context.surface,
      active_tab: context.activeTab,
    },
  };
  return logOpportunityInteraction(payload);
}

export function useOpportunityFeedImpressions(
  opportunities: FeedTrackedOpportunity[],
  context: FeedTrackerContext
): void {
  const lastBatchRef = useRef<string>("");

  useEffect(() => {
    const token = typeof window === "undefined" ? null : localStorage.getItem("access_token");
    if (!token || opportunities.length === 0) {
      return;
    }

    const batchSignature = `${context.surface}:${context.activeTab}:${opportunities
      .map((item) => `${item.id}:${item.rank_position ?? ""}:${item.ranking_mode || "baseline"}`)
      .join("|")}`;
    if (batchSignature === lastBatchRef.current) {
      return;
    }

    lastBatchRef.current = batchSignature;
    void Promise.allSettled(
      opportunities.map((opportunity, idx) =>
        logTrackedOpportunityEvent(
          {
            ...opportunity,
            rank_position: opportunity.rank_position ?? idx + 1,
          },
          "impression",
          context
        )
      )
    );
  }, [context, opportunities]);
}
