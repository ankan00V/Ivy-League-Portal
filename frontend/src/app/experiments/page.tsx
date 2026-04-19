"use client";

import React, { useEffect, useMemo, useState } from "react";
import Sidebar from "@/components/Sidebar";
import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";
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
  power?: {
    eligible: boolean;
    alpha: number;
    target_power: number;
    observed_power: number | null;
    mde_absolute: number | null;
    is_underpowered: boolean | null;
    reason?: string | null;
  } | null;
};

type ExperimentReport = {
  experiment_key: string;
  status: string;
  days: number;
  traffic_type?: "all" | "real" | "simulated";
  conversion_types: string[];
  variants: VariantRow[];
  comparisons: ComparisonRow[];
  diagnostics?: {
    srm?: {
      eligible: boolean;
      chi_square: number | null;
      p_value: number | null;
      df?: number;
      alert: boolean;
      total_impressions?: number;
      reason?: string | null;
    };
  };
};

type SideBySideBundle = {
  label: "real" | "simulated";
  experiment_key: string;
  status: "ok" | "missing";
  reports: Record<string, ExperimentReport>;
};

type SideBySideReport = {
  days: number;
  conversion_types: string[];
  real: SideBySideBundle;
  simulated: SideBySideBundle;
};

type DailyAggregate = {
  date: string;
  metric_type: string;
  ranking_mode: string;
  experiment_key: string;
  experiment_variant: string;
  measures: Record<string, number>;
};

type FunnelAggregate = {
  date: string;
  experiment_key: string;
  ranking_mode: string;
  experiment_variant: string;
  impressions: number;
  clicks: number;
  saves: number;
  applies: number;
  ctr: number;
  save_rate: number;
  apply_rate: number;
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

function formatLift(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const pct = value * 100;
  const prefix = pct > 0 ? "+" : "";
  return `${prefix}${pct.toFixed(1)}%`;
}

function formatNum(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(digits);
}

function reportSummary(report?: ExperimentReport) {
  if (!report) return null;
  const control = report.variants.find((variant) => variant.is_control) ?? report.variants[0];
  const best = [...report.variants].sort((a, b) => b.conversion_rate - a.conversion_rate)[0];
  const totalImpressions = report.variants.reduce((sum, variant) => sum + variant.impressions, 0);
  const totalConversions = report.variants.reduce((sum, variant) => sum + variant.conversions, 0);
  const bestLift =
    control && best && best.name !== control.name && control.conversion_rate > 0
      ? (best.conversion_rate - control.conversion_rate) / control.conversion_rate
      : null;
  return {
    control,
    best,
    totalImpressions,
    totalConversions,
    bestLift,
  };
}

export default function ExperimentsPage() {
  const [days, setDays] = useState<number>(30);
  const [reports, setReports] = useState<ExperimentReport[]>([]);
  const [sideBySide, setSideBySide] = useState<SideBySideReport | null>(null);
  const [dailyAggregates, setDailyAggregates] = useState<DailyAggregate[]>([]);
  const [funnelAggregates, setFunnelAggregates] = useState<FunnelAggregate[]>([]);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const sortedReports = useMemo(() => {
    return [...reports].sort((a, b) => a.experiment_key.localeCompare(b.experiment_key));
  }, [reports]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError(null);
      setAnalyticsError(null);
      try {
        const token = getAccessToken();
        if (!token) {
          setError("Sign in as an admin to view experiment reports.");
          setReports([]);
          setSideBySide(null);
          setDailyAggregates([]);
          setFunnelAggregates([]);
          return;
        }

        const [reportsRes, sideBySideRes] = await Promise.all([
          fetch(apiUrl(`/api/v1/experiments/reports?days=${days}&conversion=click`), {
            headers: { Authorization: `Bearer ${token}` },
          }),
          fetch(apiUrl(`/api/v1/experiments/reports/side-by-side?days=${days}&conversion=click,apply,save`), {
            headers: { Authorization: `Bearer ${token}` },
          }),
        ]);

        const reportsData = await reportsRes.json().catch(() => null);
        if (!reportsRes.ok) {
          const detail =
            typeof reportsData?.detail === "string" ? reportsData.detail : "Could not load experiment reports.";
          throw new Error(detail);
        }

        const sideBySideData = await sideBySideRes.json().catch(() => null);
        if (!sideBySideRes.ok) {
          const detail =
            typeof sideBySideData?.detail === "string"
              ? sideBySideData.detail
              : "Could not load side-by-side experiment reports.";
          throw new Error(detail);
        }

        setReports(Array.isArray(reportsData) ? (reportsData as ExperimentReport[]) : []);
        setSideBySide((sideBySideData as SideBySideReport) ?? null);

        const [dailyRes, funnelRes] = await Promise.all([
          fetch(apiUrl(`/api/v1/analytics/warehouse/daily?limit=50&traffic_type=real`), {
            headers: { Authorization: `Bearer ${token}` },
          }),
          fetch(apiUrl(`/api/v1/analytics/warehouse/funnels?limit=50&traffic_type=real`), {
            headers: { Authorization: `Bearer ${token}` },
          }),
        ]);

        if (dailyRes.ok) {
          const dailyData = await dailyRes.json().catch(() => []);
          setDailyAggregates(Array.isArray(dailyData) ? (dailyData as DailyAggregate[]) : []);
        } else {
          setDailyAggregates([]);
        }

        if (funnelRes.ok) {
          const funnelData = await funnelRes.json().catch(() => []);
          setFunnelAggregates(Array.isArray(funnelData) ? (funnelData as FunnelAggregate[]) : []);
        } else {
          setFunnelAggregates([]);
        }

        if (!dailyRes.ok || !funnelRes.ok) {
          setAnalyticsError("Warehouse analytics are admin-only or not initialized yet.");
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : "unknown error";
        setError(message);
        setReports([]);
        setSideBySide(null);
        setDailyAggregates([]);
        setFunnelAggregates([]);
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

        {!loading && !error && sideBySide ? (
          <section
            style={{
              background: "var(--bg-surface)",
              border: "2px solid var(--border-subtle)",
              borderRadius: "var(--radius-sm)",
              boxShadow: "var(--shadow-sm)",
              padding: "1.1rem 1.25rem",
              marginBottom: "1.25rem",
            }}
          >
            <div style={{ marginBottom: "0.8rem" }}>
              <div style={{ fontWeight: 900, letterSpacing: "-0.01em" }}>Simulated vs Real Reports</div>
              <div style={{ color: "var(--text-muted)", fontWeight: 700, fontSize: "0.9rem" }}>
                Side-by-side view for isolated experiment keys: simulated `ranking_mode_persona_sim` and real
                `ranking_mode`.
              </div>
            </div>

            <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
              {[sideBySide.simulated, sideBySide.real].map((bundle) => (
                <div
                  key={bundle.label}
                  style={{
                    background: "var(--bg-surface-hover)",
                    border: "2px solid var(--border-subtle)",
                    borderRadius: "var(--radius-sm)",
                    padding: "0.9rem",
                  }}
                >
                  <div style={{ marginBottom: "0.75rem" }}>
                    <div style={{ fontWeight: 900, textTransform: "capitalize" }}>{bundle.label}</div>
                    <div style={{ color: "var(--text-muted)", fontWeight: 700, fontSize: "0.85rem" }}>
                      key: {bundle.experiment_key}
                    </div>
                  </div>

                  {bundle.status !== "ok" ? (
                    <div style={{ color: "var(--text-muted)", fontWeight: 700 }}>No report data available.</div>
                  ) : (
                    <div style={{ display: "grid", gap: "0.6rem" }}>
                      {sideBySide.conversion_types.map((conversionType) => {
                        const summary = reportSummary(bundle.reports[conversionType]);
                        if (!summary) return null;
                        return (
                          <div
                            key={`${bundle.label}-${conversionType}`}
                            style={{
                              border: "1px solid var(--border-subtle)",
                              borderRadius: "var(--radius-sm)",
                              padding: "0.6rem 0.7rem",
                              background: "var(--bg-surface)",
                            }}
                          >
                            <div style={{ fontWeight: 900, textTransform: "uppercase", fontSize: "0.78rem" }}>
                              {conversionType}
                            </div>
                            <div style={{ color: "var(--text-muted)", fontWeight: 700, fontSize: "0.84rem" }}>
                              {summary.totalConversions} / {summary.totalImpressions} conversions
                            </div>
                            <div style={{ fontWeight: 800, fontSize: "0.9rem", marginTop: "0.25rem" }}>
                              Control {summary.control.name}: {formatPct(summary.control.conversion_rate)} · Best{" "}
                              {summary.best.name}: {formatPct(summary.best.conversion_rate)} ({formatLift(summary.bestLift)})
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {!loading && !error ? (
          <section
            style={{
              background: "var(--bg-surface)",
              border: "2px solid var(--border-subtle)",
              borderRadius: "var(--radius-sm)",
              boxShadow: "var(--shadow-sm)",
              padding: "1.1rem 1.25rem",
              marginBottom: "1.25rem",
            }}
          >
            <div style={{ marginBottom: "0.8rem" }}>
              <div style={{ fontWeight: 900, letterSpacing: "-0.01em" }}>Analytics Warehouse Snapshot</div>
              <div style={{ color: "var(--text-muted)", fontWeight: 700, fontSize: "0.9rem" }}>
                Daily aggregates and conversion funnels for real traffic.
              </div>
              {analyticsError ? (
                <div style={{ color: "#b45309", fontWeight: 700, marginTop: "0.35rem" }}>{analyticsError}</div>
              ) : null}
            </div>

            <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
              <div
                style={{
                  background: "var(--bg-surface-hover)",
                  border: "2px solid var(--border-subtle)",
                  borderRadius: "var(--radius-sm)",
                  padding: "0.9rem",
                }}
              >
                <div style={{ fontWeight: 900, marginBottom: "0.6rem" }}>Daily Metrics (latest)</div>
                {dailyAggregates.length === 0 ? (
                  <div style={{ color: "var(--text-muted)", fontWeight: 700 }}>No daily aggregates yet.</div>
                ) : (
                  <div style={{ display: "grid", gap: "0.45rem" }}>
                    {dailyAggregates.slice(0, 8).map((row, idx) => (
                      <div
                        key={`${row.date}-${row.metric_type}-${row.ranking_mode}-${idx}`}
                        style={{
                          border: "1px solid var(--border-subtle)",
                          borderRadius: "var(--radius-sm)",
                          padding: "0.55rem 0.65rem",
                          background: "var(--bg-surface)",
                        }}
                      >
                        <div style={{ fontWeight: 800, fontSize: "0.88rem" }}>
                          {row.date} · {row.metric_type} · {row.ranking_mode}
                        </div>
                        <div style={{ color: "var(--text-muted)", fontWeight: 700, fontSize: "0.82rem" }}>
                          exp {row.experiment_key}:{row.experiment_variant}
                        </div>
                        <div style={{ fontWeight: 700, fontSize: "0.84rem", marginTop: "0.2rem" }}>
                          ctr {formatPct(row.measures?.ctr)} · apply {formatPct(row.measures?.apply_rate)} · saves{" "}
                          {formatPct(row.measures?.save_rate)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div
                style={{
                  background: "var(--bg-surface-hover)",
                  border: "2px solid var(--border-subtle)",
                  borderRadius: "var(--radius-sm)",
                  padding: "0.9rem",
                }}
              >
                <div style={{ fontWeight: 900, marginBottom: "0.6rem" }}>Funnel Metrics (latest)</div>
                {funnelAggregates.length === 0 ? (
                  <div style={{ color: "var(--text-muted)", fontWeight: 700 }}>No funnel aggregates yet.</div>
                ) : (
                  <div style={{ display: "grid", gap: "0.45rem" }}>
                    {funnelAggregates.slice(0, 8).map((row, idx) => (
                      <div
                        key={`${row.date}-${row.experiment_key}-${row.ranking_mode}-${idx}`}
                        style={{
                          border: "1px solid var(--border-subtle)",
                          borderRadius: "var(--radius-sm)",
                          padding: "0.55rem 0.65rem",
                          background: "var(--bg-surface)",
                        }}
                      >
                        <div style={{ fontWeight: 800, fontSize: "0.88rem" }}>
                          {row.date} · {row.ranking_mode} · {row.experiment_variant}
                        </div>
                        <div style={{ color: "var(--text-muted)", fontWeight: 700, fontSize: "0.82rem" }}>
                          imp {row.impressions} · click {row.clicks} · save {row.saves} · apply {row.applies}
                        </div>
                        <div style={{ fontWeight: 700, fontSize: "0.84rem", marginTop: "0.2rem" }}>
                          ctr {formatPct(row.ctr)} · save {formatPct(row.save_rate)} · apply {formatPct(row.apply_rate)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>
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

                {report.diagnostics?.srm ? (
                  <div
                    style={{
                      padding: "0.8rem 1.25rem",
                      borderBottom: "2px solid var(--border-subtle)",
                      background: report.diagnostics.srm.alert
                        ? "color-mix(in srgb, #fef08a 30%, var(--bg-surface-hover))"
                        : "var(--bg-surface-hover)",
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "0.9rem",
                      fontWeight: 700,
                      fontSize: "0.88rem",
                    }}
                  >
                    <span>
                      SRM: {report.diagnostics.srm.alert ? "alert" : "ok"}
                    </span>
                    <span>p={formatP(report.diagnostics.srm.p_value)}</span>
                    <span>chi2={formatNum(report.diagnostics.srm.chi_square, 4)}</span>
                    <span>df={report.diagnostics.srm.df ?? "—"}</span>
                    <span>impressions={report.diagnostics.srm.total_impressions ?? 0}</span>
                  </div>
                ) : null}

                <div style={{ padding: "1.25rem" }}>
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 980 }}>
                      <thead>
                        <tr style={{ textAlign: "left", color: "var(--text-muted)", fontWeight: 900 }}>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Variant</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Traffic</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Impressions</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Conversions</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Rate (95% CI)</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Δ vs control (95% CI)</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>p</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>Power</th>
                          <th style={{ padding: "0.6rem 0.5rem" }}>MDE (abs)</th>
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
                          const power = comparison?.power;
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
                              <td style={{ padding: "0.85rem 0.5rem", fontWeight: 900 }}>
                                {power?.eligible
                                  ? `${formatPct(power.observed_power)}${power.is_underpowered ? " (low)" : ""}`
                                  : "—"}
                              </td>
                              <td style={{ padding: "0.85rem 0.5rem", fontWeight: 900 }}>
                                {power?.eligible ? formatPct(power.mde_absolute) : "—"}
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
