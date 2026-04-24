import React from "react";

type HeatmapCell = {
  cohortLabel: string;
  dayLabel: string;
  value: number;
};

type CohortHeatmapProps = {
  rows: string[];
  columns: string[];
  cells: HeatmapCell[];
};

function shade(value: number): string {
  const clamped = Math.max(0, Math.min(1, value));
  const intensity = Math.round(28 + clamped * 55);
  return `hsl(196 92% ${intensity}%)`;
}

export default function CohortHeatmap({ rows, columns, cells }: CohortHeatmapProps) {
  const cellMap = new Map(cells.map((cell) => [`${cell.cohortLabel}::${cell.dayLabel}`, cell.value]));

  return (
    <div style={{ overflowX: "auto" }}>
      <div style={{ minWidth: 420, display: "grid", gap: "0.35rem" }}>
        <div style={{ display: "grid", gridTemplateColumns: `150px repeat(${columns.length}, minmax(40px, 1fr))`, gap: "0.35rem" }}>
          <div />
          {columns.map((column) => (
            <div key={column} style={{ fontSize: "0.72rem", fontWeight: 900, color: "var(--text-muted)", textAlign: "center" }}>
              {column}
            </div>
          ))}
        </div>
        {rows.map((row) => (
          <div key={row} style={{ display: "grid", gridTemplateColumns: `150px repeat(${columns.length}, minmax(40px, 1fr))`, gap: "0.35rem", alignItems: "center" }}>
            <div style={{ fontSize: "0.76rem", fontWeight: 800, color: "var(--text-secondary)" }}>{row}</div>
            {columns.map((column) => {
              const value = cellMap.get(`${row}::${column}`) ?? 0;
              return (
                <div
                  key={`${row}-${column}`}
                  title={`${row} · ${column}: ${(value * 100).toFixed(1)}%`}
                  style={{
                    height: "26px",
                    borderRadius: "6px",
                    background: shade(value),
                    border: "1px solid color-mix(in srgb, var(--border-subtle) 65%, transparent)",
                    display: "grid",
                    placeItems: "center",
                    fontSize: "0.68rem",
                    fontWeight: 800,
                    color: value > 0.44 ? "#e0f2fe" : "#082f49",
                  }}
                >
                  {(value * 100).toFixed(0)}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
