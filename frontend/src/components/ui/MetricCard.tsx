import React from "react";

type MetricCardTone = "default" | "primary" | "accent";

type MetricCardProps = {
  label: React.ReactNode;
  value: React.ReactNode;
  hint?: React.ReactNode;
  detail?: React.ReactNode;
  tone?: MetricCardTone;
  onClick?: () => void;
  role?: string;
  tabIndex?: number;
  onKeyDown?: (event: React.KeyboardEvent<HTMLDivElement>) => void;
};

const toneStyle: Record<MetricCardTone, React.CSSProperties> = {
  default: { background: "var(--bg-surface)", color: "var(--text-primary)" },
  primary: { background: "var(--brand-primary)", color: "#000000" },
  accent: { background: "var(--brand-accent)", color: "#000000" },
};

export default function MetricCard({
  label,
  value,
  hint,
  detail,
  tone = "default",
  onClick,
  role,
  tabIndex,
  onKeyDown,
}: MetricCardProps) {
  return (
    <div
      className="vv-metric-card"
      style={{ cursor: onClick ? "pointer" : "default", ...toneStyle[tone] }}
      onClick={onClick}
      role={role}
      tabIndex={tabIndex}
      onKeyDown={onKeyDown}
    >
      <div className="vv-metric-label">{label}</div>
      <div className="vv-metric-value">{value}</div>
      {hint ? <div className="vv-metric-hint">{hint}</div> : null}
      {detail ? <div className="vv-metric-detail">{detail}</div> : null}
    </div>
  );
}
