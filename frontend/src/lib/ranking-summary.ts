export type RankingSummary = {
  account_scope: "candidate" | "employer";
  incoscore: number;
  rank: number;
  total_users: number;
  // Null until the cohort is large enough for a percentile to be meaningful;
  // `band` carries the interpretation until then.
  top_percent: number | null;
  percentile: number | null;
  band?: string | null;
  cohort_ready?: boolean;
  updated_at: string;
};

export function formatTopPercent(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "100";
  }
  if (value <= 1) {
    return "1";
  }
  if (value < 10) {
    return value.toFixed(1).replace(/\.0$/, "");
  }
  return Math.round(value).toString();
}
