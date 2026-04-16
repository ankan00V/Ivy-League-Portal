"use client";

import React, { useEffect, useMemo, useState } from "react";
import Sidebar from "@/components/Sidebar";
import { apiUrl } from "@/lib/api";
import { motion } from "framer-motion";

type VariantRow = {
  name: string;
  weight: number;
  is_control: boolean;
  impressions: number;
  conversions: number;
  conversion_rate: number;
  ci_low: number;
  ci_high: number;
};

type ComparisonRow = {
  control: string;
  variant: string;
  diff: number | null;
  diff_ci_low: number | null;
  diff_ci_high: number | null;
  lift: number | null;
  z: number | null;
  p_value: number | null;
};

type ExperimentReport = {
  experiment_key: string;
  status: string;
  days: number;
  conversion_types: string[];
  variants: VariantRow[];
  comparisons: ComparisonRow[];
};

function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

function formatP(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 0.0001) return "< 0.0001";
  return value.toFixed(4);
}

export default function ExperimentsPage() {
  const [days, setDays] = useState<number>(30);
  const [reports, setReports] = useState<ExperimentReport[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const sortedReports = useMemo(() => {
    return [...reports].sort((a, b) => a.experiment_key.localeCompare(b.experiment_key));
  }, [reports]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const token = localStorage.getItem("access_token");
        if (!token) {
          setError("Sign in as an admin to view experiment reports.");
          setReports([]);
          return;
        }

        const res = await fetch(apiUrl(`/api/v1/experiments/reports?days=${days}&conversion=click`), {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json().catch(() => null);
        if (!res.ok) {
          const detail = typeof data?.detail === "string" ? data.detail : "Could not load experiment reports.";
          throw new Error(detail);
        }
        setReports(Array.isArray(data) ? (data as ExperimentReport[]) : []);
      } catch (err) {
        const message = err instanceof Error ? err.message : "unknown error";
        setError(message);
        setReports([]);
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, [days]);

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        background: "var(--bg-base)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <Sidebar />

      <main className="main-content" style={{ width: "100%" }}>
        <motion.header
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
            gap: "1rem",
            padding: "1.5rem 0 1rem",
            borderBottom: "2px solid var(--border-subtle)",
            marginBottom: "1.25rem",
          }}
        >
          <div>
            <div style={{ fontFamily: "var(--font-serif)", fontSize: "2rem", fontWeight: 400 }}>
              Experiments
            </div>
            <div style={{ color: "var(--text-muted)", fontWeight: 600 }}>
              Variant performance with confidence intervals and significance tests.
            </div>
          </div>

          <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
            <label style={{ fontWeight: 700, color: "var(--text-muted)", fontSize: "0.85rem" }}>Window</label>
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              style={{
                background: "var(--bg-surface)",
                border: "2px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
                padding: "0.6rem 0.75rem",
                color: "var(--text-primary)",
                fontWeight: 700,
                boxShadow: "var(--shadow-sm)",
              }}
            >
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
              <option value={180}>180 days</option>
            </select>
          </div>
        </motion.header>

        {error ? (
          <div
            style={{
              background: "var(--bg-surface)",
              border: "2px solid var(--border-subtle)",
              borderRadius: "var(--radius-sm)",
              padding: "1.25rem",
              boxShadow: "var(--shadow-sm)",
              fontWeight: 700,
            }}
          >
            {error}
          </div>
        ) : null}

        {loading ? (
          <div style={{ color: "var(--text-muted)", fontWeight: 700 }}>Loading…</div>
        ) : null}

        {!loading && !error && sortedReports.length === 0 ? (
          <div style={{ color: "var(--text-muted)", fontWeight: 700 }}>No experiments found.</div>
        ) : null}

        <div style={{ display: "grid", gap: "1.25rem" }}>
          {sortedReports.map((report) => {
            const control = report.variants.find((v) => v.is_control) ?? report.variants[0];
            return (
              <section
                key={report.experiment_key}
                style={{
                  background: "var(--bg-surface)",
                  border: "2px solid var(--border-subtle)",
                  borderRadius: "var(--radius-sm)",
                  boxShadow: "var(--shadow-sm)",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "1rem",
                    padding: "1.1rem 1.25rem",
                    background: "var(--bg-surface-hover)",
                    borderBottom: "2px solid var(--border-subtle)",
                  }}
                >
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                    <div style={{ fontWeight: 900, letterSpacing: "-0.01em" }}>{report.experiment_key}</div>
                    <div style={{ color: "var(--text-muted)", fontWeight: 700, fontSize: "0.9rem" }}>
                      Status: {report.status} · Conversion: {report.conversion_types.join(", ")}
                    </div>
                  </div>
                  {control ? (
                    <div style={{ textAlign: "right" }}>
                      <div style={{ color: "var(--text-muted)", fontWeight: 800, fontSize: "0.8rem" }}>
                        Control
                      </div>
                      <div style={{ fontWeight: 900 }}>
                        {control.name} · {formatPct(control.conversion_rate)}{" "}
                        <span style={{ color: "var(--text-muted)", fontWeight: 800 }}>
                          ({formatPct(control.ci_low)}–{formatPct(control.ci_high)})
                        </span>
                      </div>
                    </div>
                  ) : null}
                </div>

                <div style={{ padding: "1.25rem" }}>
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 780 }}>
                      <thead>
                        <tr style={{ textAlign: "left", color: "var(--text-muted)", fontWeight: 900 }}>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Variant</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Traffic</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Impressions</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Conversions</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Rate (95% CI)</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Δ vs control (95% CI)</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>p</th>
                        </tr>
                      </thead>
                      <tbody>
                        {report.variants.map((variant) => {
                          const comparison = report.comparisons.find((c) => c.variant === variant.name);
                          const isControl = Boolean(variant.is_control);
                          const diffLabel =
                            comparison && comparison.diff !== null
                              ? `${formatPct(comparison.diff)} (${formatPct(comparison.diff_ci_low)}–${formatPct(
                                  comparison.diff_ci_high,
                                )})`
                              : isControl
                                ? "—"
                                : "—";
                          const pValue = comparison?.p_value ?? null;
                          const significant = pValue !== null && pValue < 0.05;
                          return (
                            <tr key={variant.name} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                              <td style={{ padding: "0.85rem 0.5rem", fontWeight: 900 }}>
                                {variant.name}
                                {isControl ? (
                                  <span
                                    style={{
                                      marginLeft: "0.6rem",
                                      display: "inline-block",
                                      padding: "0.15rem 0.45rem",
                                      borderRadius: 999,
                                      background: "var(--brand-accent)",
                                      border: "1px solid var(--border-subtle)",
                                      color: "#000",
                                      fontWeight: 900,
                                      fontSize: "0.75rem",
                                    }}
                                  >
                                    CONTROL
                                  </span>
                                ) : null}
                              </td>
                              <td style={{ padding: "0.85rem 0.5rem", fontWeight: 800 }}>
                                {Math.round(variant.weight * 100)}%
                              </td>
                              <td style={{ padding: "0.85rem 0.5rem", fontWeight: 800 }}>{variant.impressions}</td>
                              <td style={{ padding: "0.85rem 0.5rem", fontWeight: 800 }}>{variant.conversions}</td>
                              <td style={{ padding: "0.85rem 0.5rem", fontWeight: 900 }}>
                                {formatPct(variant.conversion_rate)}{" "}
                                <span style={{ color: "var(--text-muted)", fontWeight: 800 }}>
                                  ({formatPct(variant.ci_low)}–{formatPct(variant.ci_high)})
                                </span>
                              </td>
                              <td style={{ padding: "0.85rem 0.5rem", fontWeight: 900 }}>{diffLabel}</td>
                              <td style={{ padding: "0.85rem 0.5rem", fontWeight: 900 }}>
                                <span style={{ color: significant ? "var(--brand-primary)" : "var(--text-primary)" }}>
                                  {formatP(pValue)}
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              </section>
            );
          })}
        </div>
      </main>
    </div>
  );
}

