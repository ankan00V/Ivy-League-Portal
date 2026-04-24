"use client";

import React, { useEffect, useMemo, useState } from "react";
import Sidebar from "@/components/Sidebar";
import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";
import { motion } from "framer-motion";
import PageHeader from "@/components/ui/PageHeader";
import SectionCard from "@/components/ui/SectionCard";
import StatusBadge from "@/components/ui/StatusBadge";
import DataTable from "@/components/ui/DataTable";
import TimeseriesChart from "@/components/charts/TimeseriesChart";
import CohortHeatmap from "@/components/charts/CohortHeatmap";
import LiftConfidenceChart from "@/components/charts/LiftConfidenceChart";

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
  measures?: Record<string, number>;
  metrics?: Record<string, number>;
};

type FunnelAggregate = {
  date: string;
  experiment_key: string;
  ranking_mode: string;
  experiment_variant: string;
  impressions?: number;
  clicks?: number;
  saves?: number;
  applies?: number;
  ctr?: number;
  save_rate?: number;
  apply_rate?: number;
  stage_counts?: Record<string, number>;
  rates?: Record<string, number>;
};

type CohortAggregate = {
  cohort_date: string;
  days_since_cohort: number;
  users_in_cohort: number;
  active_users: number;
  applying_users: number;
  retention_rate: number;
  apply_rate: number;
};

type FeatureStoreRow = {
  row_key: string;
  date: string;
  user_id?: string | null;
  opportunity_id?: string | null;
  ranking_mode?: string | null;
  experiment_key?: string | null;
  experiment_variant?: string | null;
  rank_position?: number | null;
  match_score?: number | null;
  features?: Record<string, unknown>;
  labels?: Record<string, unknown>;
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

function readMeasure(row: DailyAggregate, key: string): number | undefined {
  return row.measures?.[key] ?? row.metrics?.[key];
}

function readStageCount(row: FunnelAggregate, key: "impression" | "click" | "save" | "apply"): number {
  const map = row.stage_counts || {};
  if (key === "impression") {
    return Number(row.impressions ?? map.impression ?? 0);
  }
  if (key === "click") {
    return Number(row.clicks ?? map.click ?? 0);
  }
  if (key === "save") {
    return Number(row.saves ?? map.save ?? 0);
  }
  return Number(row.applies ?? map.apply ?? 0);
}

function readRate(row: FunnelAggregate, key: "ctr" | "save_rate" | "apply_rate"): number {
  const map = row.rates || {};
  if (key === "ctr") {
    return Number(row.ctr ?? map.click_from_impression ?? 0);
  }
  if (key === "save_rate") {
    return Number(row.save_rate ?? map.save_from_click ?? 0);
  }
  return Number(row.apply_rate ?? map.apply_from_click ?? 0);
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
  const [analyticsTrafficType, setAnalyticsTrafficType] = useState<"real" | "simulated">("real");
  const [reports, setReports] = useState<ExperimentReport[]>([]);
  const [sideBySide, setSideBySide] = useState<SideBySideReport | null>(null);
  const [dailyAggregates, setDailyAggregates] = useState<DailyAggregate[]>([]);
  const [funnelAggregates, setFunnelAggregates] = useState<FunnelAggregate[]>([]);
  const [cohortAggregates, setCohortAggregates] = useState<CohortAggregate[]>([]);
  const [featureRows, setFeatureRows] = useState<FeatureStoreRow[]>([]);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const sortedReports = useMemo(() => {
    return [...reports].sort((a, b) => a.experiment_key.localeCompare(b.experiment_key));
  }, [reports]);

  const retentionByDay = useMemo(() => {
    const grouped: Record<number, CohortAggregate[]> = {};
    for (const row of cohortAggregates) {
      if (!grouped[row.days_since_cohort]) {
        grouped[row.days_since_cohort] = [];
      }
      grouped[row.days_since_cohort].push(row);
    }
    return [0, 1, 3, 7, 14, 30].map((day) => {
      const rows = grouped[day] || [];
      if (rows.length === 0) {
        return { day, retention_rate: null as number | null, apply_rate: null as number | null };
      }
      const retention = rows.reduce((sum, row) => sum + Number(row.retention_rate || 0), 0) / rows.length;
      const applyRate = rows.reduce((sum, row) => sum + Number(row.apply_rate || 0), 0) / rows.length;
      return { day, retention_rate: retention, apply_rate: applyRate };
    });
  }, [cohortAggregates]);

  const featureQuality = useMemo(() => {
    const totalRows = featureRows.length;
    if (totalRows === 0) {
      return {
        totalRows,
        scoredCoverage: 0,
        labeledCoverage: 0,
        avgFeatureCount: 0,
        missingRankPosition: 0,
        rankingModes: [] as string[],
      };
    }
    let scoredRows = 0;
    let labeledRows = 0;
    let featureCountTotal = 0;
    let missingRank = 0;
    const modeSet = new Set<string>();

    for (const row of featureRows) {
      if (typeof row.match_score === "number") {
        scoredRows += 1;
      }
      const labels = row.labels || {};
      if (Object.keys(labels).length > 0) {
        labeledRows += 1;
      }
      if (!row.rank_position || row.rank_position <= 0) {
        missingRank += 1;
      }
      const features = row.features || {};
      featureCountTotal += Object.keys(features).length;
      if (row.ranking_mode) {
        modeSet.add(row.ranking_mode);
      }
    }
    return {
      totalRows,
      scoredCoverage: scoredRows / totalRows,
      labeledCoverage: labeledRows / totalRows,
      avgFeatureCount: featureCountTotal / totalRows,
      missingRankPosition: missingRank,
      rankingModes: [...modeSet].sort(),
    };
  }, [featureRows]);

  const dailyCtrSeries = useMemo(
    () =>
      dailyAggregates
        .slice(0, 14)
        .reverse()
        .map((row) => ({
          label: row.date.slice(5),
          value: Number(readMeasure(row, "ctr") ?? 0),
        })),
    [dailyAggregates],
  );

  const funnelApplySeries = useMemo(
    () =>
      funnelAggregates
        .slice(0, 14)
        .reverse()
        .map((row) => ({
          label: row.date.slice(5),
          value: Number(readRate(row, "apply_rate") ?? 0),
        })),
    [funnelAggregates],
  );

  const featureCoverageSeries = useMemo(() => {
    const grouped = new Map<string, { total: number; withMatch: number }>();
    for (const row of featureRows) {
      const date = (row.date || "").slice(0, 10);
      if (!date) continue;
      const entry = grouped.get(date) ?? { total: 0, withMatch: 0 };
      entry.total += 1;
      if (typeof row.match_score === "number") {
        entry.withMatch += 1;
      }
      grouped.set(date, entry);
    }
    return Array.from(grouped.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .slice(-14)
      .map(([date, item]) => ({
        label: date.slice(5),
        value: item.total > 0 ? item.withMatch / item.total : 0,
      }));
  }, [featureRows]);

  const cohortHeatmapData = useMemo(() => {
    const dayBuckets = [0, 1, 3, 7, 14, 30];
    const cohortLabels = Array.from(new Set(cohortAggregates.map((row) => row.cohort_date)))
      .sort((a, b) => b.localeCompare(a))
      .slice(0, 6)
      .reverse();

    const cells = cohortLabels.flatMap((cohortLabel) =>
      dayBuckets.map((day) => {
        const rows = cohortAggregates.filter(
          (row) => row.cohort_date === cohortLabel && row.days_since_cohort === day,
        );
        const avgRetention =
          rows.length > 0
            ? rows.reduce((sum, row) => sum + Number(row.retention_rate || 0), 0) / rows.length
            : 0;
        return {
          cohortLabel,
          dayLabel: `D${day}`,
          value: avgRetention,
        };
      }),
    );

    return {
      rows: cohortLabels,
      columns: dayBuckets.map((day) => `D${day}`),
      cells,
    };
  }, [cohortAggregates]);

  const liftRows = useMemo(
    () =>
      sortedReports
        .flatMap((report) =>
          report.comparisons
            .filter((comparison) => comparison.variant !== comparison.control)
            .map((comparison) => ({
              label: `${report.experiment_key}:${comparison.variant}`,
              diff: comparison.diff,
              low: comparison.diff_ci_low,
              high: comparison.diff_ci_high,
            })),
        )
        .slice(0, 8),
    [sortedReports],
  );

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
          setCohortAggregates([]);
          setFeatureRows([]);
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

        const [dailyRes, funnelRes, cohortRes, featureRes] = await Promise.all([
          fetch(apiUrl(`/api/v1/analytics/warehouse/daily?limit=50&traffic_type=${analyticsTrafficType}`), {
            headers: { Authorization: `Bearer ${token}` },
          }),
          fetch(apiUrl(`/api/v1/analytics/warehouse/funnels?limit=50&traffic_type=${analyticsTrafficType}`), {
            headers: { Authorization: `Bearer ${token}` },
          }),
          fetch(
            apiUrl(`/api/v1/analytics/warehouse/cohorts?limit=120&max_days_since_cohort=30&traffic_type=${analyticsTrafficType}`),
            {
              headers: { Authorization: `Bearer ${token}` },
            },
          ),
          fetch(apiUrl(`/api/v1/analytics/feature-store/rows?limit=120&traffic_type=${analyticsTrafficType}`), {
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

        if (cohortRes.ok) {
          const cohortData = await cohortRes.json().catch(() => []);
          setCohortAggregates(Array.isArray(cohortData) ? (cohortData as CohortAggregate[]) : []);
        } else {
          setCohortAggregates([]);
        }

        if (featureRes.ok) {
          const featureData = await featureRes.json().catch(() => []);
          setFeatureRows(Array.isArray(featureData) ? (featureData as FeatureStoreRow[]) : []);
        } else {
          setFeatureRows([]);
        }

        if (!dailyRes.ok || !funnelRes.ok || !cohortRes.ok || !featureRes.ok) {
          setAnalyticsError("Warehouse analytics are admin-only or not initialized yet.");
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : "unknown error";
        setError(message);
        setReports([]);
        setSideBySide(null);
        setDailyAggregates([]);
        setFunnelAggregates([]);
        setCohortAggregates([]);
        setFeatureRows([]);
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, [days, analyticsTrafficType]);

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
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <PageHeader
            title="Experiments"
            subtitle="Variant performance with confidence intervals, power checks, and warehouse diagnostics."
            status={
              <>
                <StatusBadge tone={analyticsTrafficType === "real" ? "live" : "simulated"} label={analyticsTrafficType} />
                <StatusBadge tone="info" label={`${days}d window`} />
              </>
            }
            actions={
              <>
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
                <label style={{ fontWeight: 700, color: "var(--text-muted)", fontSize: "0.85rem" }}>Traffic</label>
                <select
                  value={analyticsTrafficType}
                  onChange={(e) => setAnalyticsTrafficType(e.target.value as "real" | "simulated")}
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
                  <option value="real">real</option>
                  <option value="simulated">simulated</option>
                </select>
              </>
            }
          />
        </motion.div>

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
          <SectionCard
            title="Visual Diagnostics"
            subtitle="Time-series and confidence visuals for faster interpretation across funnel, cohorts, and model-feature quality."
            status={<StatusBadge tone="info" label="Charts" />}
          >
            <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
              <div style={{ border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.8rem", background: "var(--bg-surface-hover)" }}>
                <div style={{ fontWeight: 900, marginBottom: "0.45rem" }}>Daily CTR Trend</div>
                <TimeseriesChart points={dailyCtrSeries} color="var(--accent-cyan)" valueFormatter={(value) => formatPct(value)} />
              </div>
              <div style={{ border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.8rem", background: "var(--bg-surface-hover)" }}>
                <div style={{ fontWeight: 900, marginBottom: "0.45rem" }}>Funnel Apply-Rate Trend</div>
                <TimeseriesChart points={funnelApplySeries} color="var(--brand-accent)" valueFormatter={(value) => formatPct(value)} />
              </div>
              <div style={{ border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.8rem", background: "var(--bg-surface-hover)" }}>
                <div style={{ fontWeight: 900, marginBottom: "0.45rem" }}>Feature Coverage Trend</div>
                <TimeseriesChart points={featureCoverageSeries} color="var(--brand-primary)" valueFormatter={(value) => formatPct(value)} />
              </div>
              <div style={{ border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.8rem", background: "var(--bg-surface-hover)" }}>
                <div style={{ fontWeight: 900, marginBottom: "0.45rem" }}>Lift Confidence</div>
                <LiftConfidenceChart rows={liftRows} />
              </div>
            </div>
            <div style={{ marginTop: "1rem", border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.8rem", background: "var(--bg-surface-hover)" }}>
              <div style={{ fontWeight: 900, marginBottom: "0.45rem" }}>Cohort Retention Heatmap</div>
              {cohortHeatmapData.rows.length === 0 ? (
                <div style={{ color: "var(--text-muted)", fontWeight: 700 }}>No cohort rows yet.</div>
              ) : (
                <CohortHeatmap rows={cohortHeatmapData.rows} columns={cohortHeatmapData.columns} cells={cohortHeatmapData.cells} />
              )}
            </div>
          </SectionCard>
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
                Daily aggregates and conversion funnels for {analyticsTrafficType} traffic.
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
                          ctr {formatPct(readMeasure(row, "ctr"))} · apply {formatPct(readMeasure(row, "apply_rate"))} · saves{" "}
                          {formatPct(readMeasure(row, "save_rate"))}
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
                          imp {readStageCount(row, "impression")} · click {readStageCount(row, "click")} · save {readStageCount(row, "save")} · apply {readStageCount(row, "apply")}
                        </div>
                        <div style={{ fontWeight: 700, fontSize: "0.84rem", marginTop: "0.2rem" }}>
                          ctr {formatPct(readRate(row, "ctr"))} · save {formatPct(readRate(row, "save_rate"))} · apply {formatPct(readRate(row, "apply_rate"))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
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
              <div style={{ fontWeight: 900, letterSpacing: "-0.01em" }}>Cohorts + Feature Store Quality</div>
              <div style={{ color: "var(--text-muted)", fontWeight: 700, fontSize: "0.9rem" }}>
                Retention behavior by cohort day and feature-store health for ranking model training.
              </div>
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
                <div style={{ fontWeight: 900, marginBottom: "0.6rem" }}>Retention by Cohort Day</div>
                {cohortAggregates.length === 0 ? (
                  <div style={{ color: "var(--text-muted)", fontWeight: 700 }}>No cohort rows yet.</div>
                ) : (
                  <div style={{ display: "grid", gap: "0.45rem" }}>
                    {retentionByDay.map((row) => (
                      <div
                        key={`retention-${row.day}`}
                        style={{
                          border: "1px solid var(--border-subtle)",
                          borderRadius: "var(--radius-sm)",
                          padding: "0.55rem 0.65rem",
                          background: "var(--bg-surface)",
                          display: "flex",
                          justifyContent: "space-between",
                          gap: "0.7rem",
                        }}
                      >
                        <div style={{ fontWeight: 800 }}>Day {row.day}</div>
                        <div style={{ color: "var(--text-muted)", fontWeight: 700 }}>
                          retention {formatPct(row.retention_rate)} · apply {formatPct(row.apply_rate)}
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
                <div style={{ fontWeight: 900, marginBottom: "0.6rem" }}>Feature Store Quality Cards</div>
                {featureRows.length === 0 ? (
                  <div style={{ color: "var(--text-muted)", fontWeight: 700 }}>No feature-store rows yet.</div>
                ) : (
                  <div style={{ display: "grid", gap: "0.45rem" }}>
                    {[
                      { label: "Rows", value: String(featureQuality.totalRows) },
                      { label: "Match Score Coverage", value: formatPct(featureQuality.scoredCoverage) },
                      { label: "Label Coverage", value: formatPct(featureQuality.labeledCoverage) },
                      { label: "Avg Feature Count", value: formatNum(featureQuality.avgFeatureCount, 1) },
                      { label: "Missing Rank Position", value: String(featureQuality.missingRankPosition) },
                      {
                        label: "Ranking Modes",
                        value: featureQuality.rankingModes.length > 0 ? featureQuality.rankingModes.join(", ") : "none",
                      },
                    ].map((card) => (
                      <div
                        key={card.label}
                        style={{
                          border: "1px solid var(--border-subtle)",
                          borderRadius: "var(--radius-sm)",
                          padding: "0.55rem 0.65rem",
                          background: "var(--bg-surface)",
                          display: "flex",
                          justifyContent: "space-between",
                          gap: "0.7rem",
                        }}
                      >
                        <div style={{ fontWeight: 800 }}>{card.label}</div>
                        <div style={{ color: "var(--text-muted)", fontWeight: 700, textAlign: "right" }}>{card.value}</div>
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
                  <DataTable minWidth={980}>
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
                  </DataTable>
                </div>
              </section>
            );
          })}
        </div>
      </main>
    </div>
  );
}
