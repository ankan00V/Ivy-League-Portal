import { useEffect, useRef } from "react";

import { getAccessToken } from "@/lib/auth-session";
import {
  logOpportunityInteraction,
  logOpportunityInteractionsBatch,
  type OpportunityInteractionInput,
  type OpportunityInteractionType,
} from "@/lib/opportunity-interactions";

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

function buildTrackedPayload(
  opportunity: FeedTrackedOpportunity,
  interactionType: OpportunityInteractionType,
  context: FeedTrackerContext
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
    features: {
      surface: context.surface,
      active_tab: context.activeTab,
    },
  };
}

export async function logTrackedOpportunityEvent(
  opportunity: FeedTrackedOpportunity,
  interactionType: OpportunityInteractionType,
  context: FeedTrackerContext
): Promise<boolean> {
  return logOpportunityInteraction(buildTrackedPayload(opportunity, interactionType, context));
}

export function useOpportunityFeedImpressions(
  opportunities: FeedTrackedOpportunity[],
  context: FeedTrackerContext
): void {
  const lastBatchRef = useRef<string>("");

  useEffect(() => {
    const token = getAccessToken();
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
    /* One request for the whole page, not one per card.
       This fired Promise.allSettled over every visible listing, so a feed
       showing 797 cards opened 797 simultaneous POSTs - and did it again on
       every filter change, because narrowing the list changes the signature.
       The feed rate limit is 100/min, so the page spent its time collecting
       429s while the browser queued hundreds of connections. The batch
       endpoint already existed on both sides; it just was not being used. */
    void logOpportunityInteractionsBatch(
      opportunities.map((opportunity, idx) =>
        buildTrackedPayload(
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
