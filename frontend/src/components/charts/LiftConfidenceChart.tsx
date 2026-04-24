import React from "react";

type LiftRow = {
  label: string;
  diff: number | null;
  low: number | null;
  high: number | null;
};

type LiftConfidenceChartProps = {
  rows: LiftRow[];
};

export default function LiftConfidenceChart({ rows }: LiftConfidenceChartProps) {
  const normalized = rows
    .filter((row) => row.diff !== null && row.low !== null && row.high !== null)
    .map((row) => ({
      label: row.label,
      diff: Number(row.diff),
      low: Number(row.low),
      high: Number(row.high),
    }));

  if (normalized.length === 0) {
    return <div style={{ color: "var(--text-muted)", fontWeight: 700 }}>No confidence rows available.</div>;
  }

  const min = Math.min(...normalized.map((row) => row.low), 0);
  const max = Math.max(...normalized.map((row) => row.high), 0);
  const range = Math.max(max - min, 1e-6);

  const toPercent = (value: number) => ((value - min) / range) * 100;

  return (
    <div style={{ display: "grid", gap: "0.55rem" }}>
      {normalized.map((row) => {
        const left = toPercent(row.low);
        const width = Math.max(toPercent(row.high) - left, 0.8);
        const point = toPercent(row.diff);
        const positive = row.diff > 0;

        return (
          <div key={row.label} style={{ display: "grid", gridTemplateColumns: "180px minmax(0, 1fr) 70px", gap: "0.6rem", alignItems: "center" }}>
            <div style={{ fontWeight: 800, fontSize: "0.84rem", color: "var(--text-secondary)" }}>{row.label}</div>
            <div style={{ position: "relative", height: "24px", borderRadius: "999px", border: "1px solid var(--border-subtle)", background: "color-mix(in srgb, var(--bg-surface-hover) 85%, white 15%)" }}>
              <div
                style={{
                  position: "absolute",
                  left: `${left}%`,
                  top: "7px",
                  width: `${width}%`,
                  height: "10px",
                  borderRadius: "999px",
                  background: positive ? "#16a34a" : "#ef4444",
                  opacity: 0.65,
                }}
              />
              <div
                style={{
                  position: "absolute",
                  left: `${point}%`,
                  top: "3px",
                  width: "2px",
                  height: "18px",
                  background: "#0f172a",
                }}
              />
              <div
                style={{
                  position: "absolute",
                  left: `${toPercent(0)}%`,
                  top: 0,
                  bottom: 0,
                  width: "1px",
                  background: "color-mix(in srgb, var(--border-subtle) 80%, #000 20%)",
                }}
              />
            </div>
            <div style={{ fontWeight: 900, fontSize: "0.82rem", textAlign: "right", color: positive ? "#166534" : "#991b1b" }}>
              {(row.diff * 100).toFixed(2)}%
            </div>
          </div>
        );
      })}
    </div>
  );
}
