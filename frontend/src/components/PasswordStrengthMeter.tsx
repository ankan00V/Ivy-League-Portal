"use client";

import { CheckCircle2, Circle } from "lucide-react";

import type { PasswordStrength } from "@/lib/password-strength";

type PasswordStrengthMeterProps = {
  strength: PasswordStrength;
  compact?: boolean;
};

export default function PasswordStrengthMeter({ strength, compact = false }: PasswordStrengthMeterProps) {
  return (
    <div
      aria-live="polite"
      style={{
        display: "grid",
        gap: compact ? "0.45rem" : "0.6rem",
        border: "2px solid var(--border-subtle)",
        borderRadius: "var(--radius-sm)",
        padding: compact ? "0.65rem" : "0.85rem",
        background: "var(--bg-surface-hover)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.75rem" }}>
        <span style={{ fontWeight: 800 }}>Password strength</span>
        <span style={{ color: strength.color, fontWeight: 900 }}>{strength.label}</span>
      </div>
      <div
        aria-hidden="true"
        style={{
          height: 8,
          borderRadius: 999,
          background: "rgba(0,0,0,0.12)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${strength.percent}%`,
            height: "100%",
            background: strength.color,
            transition: "width 160ms ease, background 160ms ease",
          }}
        />
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: compact ? "1fr" : "repeat(auto-fit, minmax(150px, 1fr))",
          gap: "0.35rem 0.75rem",
          fontSize: "0.86rem",
          fontWeight: 700,
          color: "var(--text-secondary)",
        }}
      >
        {strength.requirements.map((item) => (
          <span key={item.key} style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
            {item.met ? <CheckCircle2 size={15} color="#16a34a" /> : <Circle size={15} />}
            {item.label}
          </span>
        ))}
      </div>
    </div>
  );
}
