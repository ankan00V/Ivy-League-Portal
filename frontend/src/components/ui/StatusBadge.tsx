import React from "react";

type StatusBadgeTone = "live" | "simulated" | "no_data" | "info" | "success" | "warning";

type StatusBadgeProps = {
  tone: StatusBadgeTone;
  label: string;
  title?: string;
};

const toneStyles: Record<StatusBadgeTone, React.CSSProperties> = {
  live: {
    background: "color-mix(in srgb, #16a34a 78%, white 22%)",
    color: "#052e16",
    borderColor: "color-mix(in srgb, #15803d 70%, #052e16 30%)",
  },
  simulated: {
    background: "color-mix(in srgb, #f59e0b 78%, white 22%)",
    color: "#451a03",
    borderColor: "color-mix(in srgb, #b45309 70%, #451a03 30%)",
  },
  no_data: {
    background: "color-mix(in srgb, #9ca3af 80%, white 20%)",
    color: "#111827",
    borderColor: "color-mix(in srgb, #4b5563 75%, #111827 25%)",
  },
  info: {
    background: "color-mix(in srgb, #38bdf8 78%, white 22%)",
    color: "#082f49",
    borderColor: "color-mix(in srgb, #0369a1 70%, #082f49 30%)",
  },
  success: {
    background: "color-mix(in srgb, #4ade80 80%, white 20%)",
    color: "#14532d",
    borderColor: "color-mix(in srgb, #16a34a 70%, #14532d 30%)",
  },
  warning: {
    background: "color-mix(in srgb, #fbbf24 82%, white 18%)",
    color: "#422006",
    borderColor: "color-mix(in srgb, #d97706 70%, #422006 30%)",
  },
};

export default function StatusBadge({ tone, label, title }: StatusBadgeProps) {
  return (
    <span
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "0.22rem 0.62rem",
        borderRadius: "999px",
        border: "2px solid transparent",
        fontSize: "0.72rem",
        letterSpacing: "0.05em",
        fontWeight: 900,
        textTransform: "uppercase",
        whiteSpace: "nowrap",
        ...toneStyles[tone],
      }}
    >
      {label}
    </span>
  );
}
