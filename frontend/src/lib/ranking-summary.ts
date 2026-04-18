export type RankingSummary = {
  account_scope: "candidate" | "employer";
  incoscore: number;
  rank: number;
  total_users: number;
  top_percent: number;
  percentile: number;
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
