import { apiUrl } from "@/lib/api";

export type OpportunityInteractionType = "impression" | "view" | "click" | "apply" | "save";
export type RankingMode = "baseline" | "semantic" | "ml" | "ab";

export interface OpportunityInteractionInput {
  opportunityId: string;
  interactionType: OpportunityInteractionType;
  rankingMode?: string | null;
  experimentKey?: string | null;
  experimentVariant?: string | null;
  rankPosition?: number | null;
  matchScore?: number | null;
  query?: string | null;
  modelVersionId?: string | null;
  features?: Record<string, unknown> | null;
}

const VALID_RANKING_MODES = new Set<RankingMode>(["baseline", "semantic", "ml", "ab"]);
const OBJECT_ID_PATTERN = /^[a-f\d]{24}$/i;

function normalizeRankingMode(value?: string | null): RankingMode {
  const normalized = (value || "").toLowerCase().trim();
  if (VALID_RANKING_MODES.has(normalized as RankingMode)) {
    return normalized as RankingMode;
  }
  return "baseline";
}

export function isMongoObjectId(value?: string | null): boolean {
  return Boolean(value && OBJECT_ID_PATTERN.test(value));
}

export async function logOpportunityInteraction(input: OpportunityInteractionInput): Promise<boolean> {
  if (typeof window === "undefined") {
    return false;
  }

  const token = localStorage.getItem("access_token");
  if (!token) {
    return false;
  }

  if (!isMongoObjectId(input.opportunityId)) {
    return false;
  }

  const rankingMode = normalizeRankingMode(input.rankingMode);
  const payload = {
    opportunity_id: input.opportunityId,
    interaction_type: input.interactionType,
    ranking_mode: rankingMode,
    experiment_key: input.experimentKey || "ranking_mode",
    experiment_variant: input.experimentVariant || rankingMode,
    rank_position: input.rankPosition ?? null,
    match_score: input.matchScore ?? null,
    query: input.query ?? null,
    model_version_id: input.modelVersionId ?? null,
    features: input.features ?? undefined,
  };

  try {
    const res = await fetch(apiUrl("/api/v1/opportunities/interactions"), {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      credentials: "include",
      keepalive: true,
    });

    return res.ok;
  } catch {
    return false;
  }
}
