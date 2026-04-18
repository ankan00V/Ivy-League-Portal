export type ProfileSignalDetail = {
  key: string;
  label: string;
  description: string;
};

export type ProfileStrengthSummary = {
  account_scope: "candidate" | "employer";
  strength_percent: number;
  completed_signals: number;
  total_signals: number;
  missing_signals: string[];
  missing_signal_details?: ProfileSignalDetail[];
  recommendation: string;
  updated_at: string;
};

export function clampPercent(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(value)));
}
