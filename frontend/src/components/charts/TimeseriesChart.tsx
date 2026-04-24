import React, { useMemo } from "react";

type TimeseriesPoint = {
  label: string;
  value: number;
};

type TimeseriesChartProps = {
  points: TimeseriesPoint[];
  color?: string;
  height?: number;
  valueFormatter?: (value: number) => string;
};

export default function TimeseriesChart({
  points,
  color = "var(--accent-cyan)",
  height = 168,
  valueFormatter,
}: TimeseriesChartProps) {
  const prepared = useMemo(() => {
    if (points.length === 0) {
      return { path: "", area: "", min: 0, max: 0, latest: null as number | null };
    }
    const values = points.map((point) => point.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = Math.max(max - min, 1e-6);
    const width = 100;

    const toCoord = (value: number, index: number) => {
      const x = points.length === 1 ? width / 2 : (index / (points.length - 1)) * width;
      const y = 100 - ((value - min) / range) * 82 - 9;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    };

    const line = points.map((point, index) => toCoord(point.value, index)).join(" ");
    const area = `${line} ${width},100 0,100`;

    return { path: line, area, min, max, latest: values.at(-1) ?? null };
  }, [points]);

  return (
    <div style={{ display: "grid", gap: "0.45rem" }}>
      <div style={{ width: "100%", height }}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: "100%", height: "100%" }}>
          <defs>
            <linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.36" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <rect x="0" y="0" width="100" height="100" fill="transparent" />
          {[20, 40, 60, 80].map((y) => (
            <line key={y} x1="0" y1={y} x2="100" y2={y} stroke="color-mix(in srgb, var(--border-subtle) 42%, transparent)" strokeWidth="0.4" />
          ))}
          {prepared.area ? <polygon points={prepared.area} fill="url(#trend-fill)" /> : null}
          {prepared.path ? (
            <polyline
              points={prepared.path}
              fill="none"
              stroke={color}
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ) : null}
        </svg>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", color: "var(--text-muted)", fontWeight: 700, fontSize: "0.8rem" }}>
        <span>{points[0]?.label ?? "-"}</span>
        <span>
          {prepared.latest !== null
            ? valueFormatter
              ? valueFormatter(prepared.latest)
              : prepared.latest.toFixed(3)
            : "No data"}
        </span>
        <span>{points.at(-1)?.label ?? "-"}</span>
      </div>
    </div>
  );
}
