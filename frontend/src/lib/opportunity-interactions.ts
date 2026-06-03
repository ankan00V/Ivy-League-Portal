import { apiUrl } from "@/lib/api";
import { createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";

export type OpportunityInteractionType =
  | "impression"
  | "view"
  | "click"
  | "expand"
  | "apply"
  | "apply_start"
  | "apply_complete"
  | "save"
  | "share"
  | "skip"
  | "dismiss";
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
  dwellTimeMs?: number | null;
  scrollDepth?: number | null;
  sessionId?: string | null;
  coldStart?: boolean;
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

function normalizeRankPosition(value?: number | null): number {
  const parsed = Number(value);
  if (Number.isFinite(parsed) && parsed > 0) {
    return Math.floor(parsed);
  }
  return 1;
}

function buildInteractionPayload(input: OpportunityInteractionInput): Record<string, unknown> | null {
  if (!isMongoObjectId(input.opportunityId)) {
    return null;
  }

  const rankingMode = normalizeRankingMode(input.rankingMode);
  const experimentKey = (input.experimentKey || "ranking_mode").trim() || "ranking_mode";
  const experimentVariant = (input.experimentVariant || rankingMode).trim() || rankingMode;
  return {
    opportunity_id: input.opportunityId,
    interaction_type: input.interactionType,
    ranking_mode: rankingMode,
    experiment_key: experimentKey,
    experiment_variant: experimentVariant,
    rank_position: normalizeRankPosition(input.rankPosition),
    match_score: input.matchScore ?? null,
    query: input.query ?? null,
    model_version_id: input.modelVersionId ?? null,
    features: input.features ?? undefined,
    dwell_time_ms: input.dwellTimeMs ?? null,
    scroll_depth: input.scrollDepth ?? null,
    session_id: input.sessionId ?? null,
    cold_start: Boolean(input.coldStart),
  };
}

export async function logOpportunityInteraction(input: OpportunityInteractionInput): Promise<boolean> {
  if (typeof window === "undefined") {
    return false;
  }

  const token = getAccessToken();
  if (!token) {
    return false;
  }

  const payload = buildInteractionPayload(input);
  if (!payload) {
    return false;
  }

  try {
    const res = await fetch(
      apiUrl("/api/v1/opportunities/interactions"),
      createAuthenticatedFetchInit(
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
          keepalive: true,
        },
        token,
      ),
    );

    return res.ok;
  } catch {
    return false;
  }
}

export async function logOpportunityInteractionsBatch(inputs: OpportunityInteractionInput[]): Promise<boolean> {
  if (typeof window === "undefined" || inputs.length === 0) {
    return false;
  }

  const token = getAccessToken();
  if (!token) {
    return false;
  }

  const events = inputs
    .map((input) => buildInteractionPayload(input))
    .filter((item): item is Record<string, unknown> => Boolean(item));
  if (events.length === 0) {
    return false;
  }

  try {
    const res = await fetch(
      apiUrl("/api/v1/opportunities/interactions/batch"),
      createAuthenticatedFetchInit(
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ events }),
          keepalive: true,
        },
        token,
      ),
    );

    return res.ok;
  } catch {
    return false;
  }
}
