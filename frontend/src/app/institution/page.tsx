"use client";
import Sidebar from "@/components/Sidebar";
import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Building2, AlertTriangle, Loader2, ShieldCheck, Users, TrendingDown, BookOpenCheck } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";

interface CohortGap {
    skill: string;
    students_affected: number;
    weight: number;
}

interface FunnelStage {
    label: string;
    count: number;
    conversion_from_previous: number | null;
}

interface SkillSignal {
    skill: string;
    demand_share: number;
    coverage: number;
    students_assessed: number;
    students_covered: number;
    is_soft: boolean;
    gap: number;
}

interface Cohort {
    institution: string;
    institution_domain: string;
    min_cohort_size: number;
    available: boolean;
    reason?: string | null;
    cohort_size?: number | null;
    matched_by_domain?: number | null;
    matched_by_name?: number | null;
    profiles_complete?: number | null;
    assessments_taken?: number | null;
    average_readiness?: number | null;
    average_incoscore?: number | null;
    applications_total?: number | null;
    students_with_applications?: number | null;
    top_gaps: CohortGap[];
    funnel: FunnelStage[];
    curriculum_signal: SkillSignal[];
    signal_domain?: string | null;
    signal_reason?: string | null;
}

function panelStyle(): React.CSSProperties {
    return {
        border: "2px solid var(--border-subtle)",
        background: "var(--bg-surface)",
        boxShadow: "var(--shadow-sm)",
        borderRadius: "var(--radius-sm)",
    };
}

function labelStyle(): React.CSSProperties {
    return {
        fontWeight: 800,
        color: "var(--text-primary)",
        fontSize: "0.8rem",
        textTransform: "uppercase",
        letterSpacing: "0.05em",
    };
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
    return (
        <div style={{ ...panelStyle(), padding: "1.1rem 1.25rem" }}>
            <div style={labelStyle()}>{label}</div>
            <div style={{ fontSize: "2.25rem", fontWeight: 800, fontFamily: "var(--font-serif)", color: "var(--text-primary)", lineHeight: 1.1, marginTop: "0.35rem" }}>
                {value}
            </div>
            {hint && (
                <div style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: "0.85rem", marginTop: "0.3rem" }}>
                    {hint}
                </div>
            )}
        </div>
    );
}

export default function InstitutionPage() {
    const [cohort, setCohort] = useState<Cohort | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;

        const load = async () => {
            try {
                const token = getAccessToken();
                if (!token) {
                    if (!cancelled) setError("Sign in with an institution account to see this dashboard.");
                    return;
                }
                const res = await fetch(
                    apiUrl("/api/v1/academia/institution/cohort"),
                    createAuthenticatedFetchInit({}, token),
                );
                if (cancelled) return;
                if (res.status === 403) {
                    setError("This dashboard is for institution accounts.");
                    return;
                }
                if (res.status === 400) {
                    setError("Set your institution name on your profile before viewing the cohort.");
                    return;
                }
                if (!res.ok) {
                    setError("Could not load the cohort.");
                    return;
                }
                setCohort((await res.json()) as Cohort);
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Could not load the cohort.");
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        };

        void load();
        return () => {
            cancelled = true;
        };
    }, []);

    const pct = (part?: number | null, whole?: number | null) =>
        part != null && whole ? `${Math.round((part / whole) * 100)}%` : "—";

    return (
        <div style={{ minHeight: "100vh", display: "flex", background: "var(--bg-base)" }}>
            <Sidebar />
            <main className="main-content">
                <header style={{ marginBottom: "2.5rem" }}>
                    <h1
                        style={{
                            fontSize: "3rem",
                            marginBottom: "0.75rem",
                            fontWeight: 400,
                            fontFamily: "var(--font-serif)",
                            color: "var(--text-primary)",
                            lineHeight: 1.1,
                        }}
                    >
                        <span
                            style={{
                                background: "var(--brand-primary)",
                                padding: "0.2rem 0.5rem",
                                border: "2px solid var(--border-subtle)",
                                boxShadow: "var(--shadow-sm)",
                                display: "inline-block",
                                transform: "rotate(-2deg)",
                            }}
                        >
                            Cohort
                        </span>{" "}
                        Dashboard
                    </h1>
                    <p style={{ color: "var(--text-secondary)", fontSize: "1.15rem", maxWidth: "700px", fontWeight: 600 }}>
                        Skill development, internship participation and placement progress across your
                        students — in aggregate only.
                    </p>
                    {cohort && (
                        <div style={{ marginTop: "1rem", display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                            <span style={{ ...panelStyle(), padding: "0.4rem 0.75rem", ...labelStyle() }}>
                                {cohort.institution}
                            </span>
                            {cohort.institution_domain && (
                                <span style={{ ...panelStyle(), padding: "0.4rem 0.75rem", ...labelStyle() }}>
                                    @{cohort.institution_domain}
                                </span>
                            )}
                        </div>
                    )}
                </header>

                {error && (
                    <div style={{ ...panelStyle(), padding: "1rem 1.25rem", marginBottom: "1.5rem", display: "flex", gap: "0.6rem", alignItems: "center" }}>
                        <AlertTriangle size={18} />
                        <span style={{ fontWeight: 700, color: "var(--text-primary)" }}>{error}</span>
                    </div>
                )}

                {loading && (
                    <div style={{ ...panelStyle(), padding: "2rem", display: "flex", gap: "0.6rem", alignItems: "center" }}>
                        <Loader2 size={18} className="animate-spin" />
                        <span style={{ fontWeight: 700 }}>Matching your cohort…</span>
                    </div>
                )}

                {cohort && !cohort.available && (
                    // Deliberately not an empty dashboard. "Too few students to
                    // anonymise" and "your students have done nothing" are opposite
                    // findings and must never render the same way.
                    <motion.div
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        style={{ ...panelStyle(), padding: "1.75rem" }}
                    >
                        <div style={{ ...labelStyle(), display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.6rem" }}>
                            <ShieldCheck size={16} /> Withheld to protect students
                        </div>
                        <p style={{ color: "var(--text-primary)", fontWeight: 700, fontSize: "1.05rem" }}>
                            {cohort.reason}
                        </p>
                        <p style={{ color: "var(--text-secondary)", fontWeight: 600, marginTop: "0.6rem" }}>
                            This is not an empty result. An average across a handful of students
                            identifies those students, so aggregates are only shown once the cohort
                            reaches {cohort.min_cohort_size}.
                        </p>
                    </motion.div>
                )}

                {cohort && cohort.available && (
                    <>
                        <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: "0.85rem", marginBottom: "1.5rem" }}>
                            <Stat
                                label="Students"
                                value={String(cohort.cohort_size ?? "—")}
                                hint={`${cohort.matched_by_domain ?? 0} by email domain · ${cohort.matched_by_name ?? 0} by college name`}
                            />
                            <Stat
                                label="Avg readiness"
                                value={cohort.average_readiness != null ? `${cohort.average_readiness}` : "—"}
                                hint={`${cohort.assessments_taken ?? 0} have taken the assessment`}
                            />
                            <Stat
                                label="Avg InCoScore"
                                value={cohort.average_incoscore != null ? `${cohort.average_incoscore}` : "—"}
                                hint="profile competency score"
                            />
                            <Stat
                                label="Applying"
                                value={pct(cohort.students_with_applications, cohort.cohort_size)}
                                hint={`${cohort.applications_total ?? 0} applications in total`}
                            />
                            <Stat
                                label="Profiles complete"
                                value={pct(cohort.profiles_complete, cohort.cohort_size)}
                                hint="finished onboarding"
                            />
                        </section>

                        <section style={{ ...panelStyle(), padding: "1.5rem" }}>
                            <div style={{ ...labelStyle(), display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.4rem" }}>
                                <Users size={16} /> Where this cohort is weakest
                            </div>
                            <p style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: "0.9rem", marginBottom: "1rem" }}>
                                Ranked by demand in live postings, not by how many students are behind —
                                a gap nobody is hiring for is not a curriculum problem.
                            </p>
                            {cohort.top_gaps.length === 0 && (
                                <p style={{ color: "var(--text-secondary)", fontWeight: 600 }}>
                                    No assessments completed yet, so there are no gaps to rank.
                                </p>
                            )}
                            {cohort.top_gaps.map((gap) => (
                                <div
                                    key={gap.skill}
                                    style={{ ...panelStyle(), padding: "0.65rem 0.9rem", marginBottom: "0.5rem", display: "flex", justifyContent: "space-between", gap: "1rem", background: "var(--bg-base)" }}
                                >
                                    <span style={{ fontWeight: 700, color: "var(--text-primary)" }}>{gap.skill}</span>
                                    <span style={{ color: "var(--text-secondary)", fontWeight: 700 }}>
                                        {gap.students_affected} student{gap.students_affected === 1 ? "" : "s"}
                                    </span>
                                </div>
                            ))}
                        </section>
                    </>
                )}

                {cohort && cohort.available && cohort.funnel.length > 0 && (
                    <section style={{ ...panelStyle(), padding: "1.5rem", marginTop: "1.5rem" }}>
                        <div style={{ ...labelStyle(), display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.4rem" }}>
                            <TrendingDown size={16} /> Where your cohort stops
                        </div>
                        <p style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: "0.9rem", marginBottom: "1.25rem" }}>
                            &ldquo;Placement is low&rdquo; and &ldquo;nobody finishes a profile&rdquo; need different
                            remedies. This says which one you have.
                        </p>
                        {cohort.funnel.map((stage) => {
                            const widest = cohort.funnel[0]?.count || 1;
                            const width = Math.max(4, Math.round((stage.count / widest) * 100));
                            return (
                                <div key={stage.label} style={{ marginBottom: "0.85rem" }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.3rem" }}>
                                        <span style={{ fontWeight: 700, color: "var(--text-primary)" }}>{stage.label}</span>
                                        <span style={{ fontWeight: 700, color: "var(--text-secondary)" }}>
                                            {stage.count}
                                            {stage.conversion_from_previous != null && (
                                                <> · {Math.round(stage.conversion_from_previous * 100)}% of previous</>
                                            )}
                                        </span>
                                    </div>
                                    <div style={{ height: "1.35rem", border: "2px solid var(--border-subtle)", background: "var(--bg-base)", borderRadius: "var(--radius-sm)", overflow: "hidden" }}>
                                        <div style={{ width: `${width}%`, height: "100%", background: "var(--brand-primary)" }} />
                                    </div>
                                </div>
                            );
                        })}
                    </section>
                )}

                {cohort && cohort.available && cohort.curriculum_signal.length === 0 && cohort.signal_reason && (
                    // Shown rather than hidden. An absent section reads as
                    // broken, and "not enough students assessed" is fixed by
                    // asking them to take it - which nobody does if the page
                    // never mentions it.
                    <section style={{ ...panelStyle(), padding: "1.5rem", marginTop: "1.5rem" }}>
                        <div style={{ ...labelStyle(), display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.5rem" }}>
                            <BookOpenCheck size={16} /> Curriculum signal
                        </div>
                        <p style={{ color: "var(--text-primary)", fontWeight: 700 }}>{cohort.signal_reason}</p>
                        <p style={{ color: "var(--text-secondary)", fontWeight: 600, marginTop: "0.6rem", fontSize: "0.9rem" }}>
                            Once enough students have been assessed, this compares what employers are
                            advertising for against what your students can actually evidence.
                        </p>
                    </section>
                )}

                {cohort && cohort.available && cohort.curriculum_signal.length > 0 && (
                    <section style={{ ...panelStyle(), padding: "1.5rem", marginTop: "1.5rem" }}>
                        <div style={{ ...labelStyle(), display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.4rem" }}>
                            <BookOpenCheck size={16} /> Curriculum signal
                        </div>
                        <p style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: "0.9rem", marginBottom: "1.25rem" }}>
                            What employers are advertising for right now, against what your assessed
                            students can evidence. Ranked by the widest gap, not the lowest score —
                            a skill nobody is hiring for is not a curriculum priority.
                        </p>
                        {cohort.curriculum_signal.map((row) => (
                            <div key={row.skill} style={{ marginBottom: "1rem" }}>
                                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.35rem", flexWrap: "wrap", gap: "0.5rem" }}>
                                    <span style={{ fontWeight: 700, color: "var(--text-primary)" }}>
                                        {row.skill}{row.is_soft ? " · soft" : ""}
                                    </span>
                                    <span style={{ fontWeight: 700, color: "var(--text-secondary)", fontSize: "0.88rem" }}>
                                        industry {Math.round(row.demand_share * 1000) / 10}% · your students{" "}
                                        {Math.round(row.coverage * 100)}% ({row.students_covered}/{row.students_assessed})
                                    </span>
                                </div>
                                {/* Two bars on one track: demand above, coverage below, so the
                                    gap between them is the thing the eye lands on. */}
                                <div style={{ border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", overflow: "hidden", background: "var(--bg-base)" }}>
                                    <div style={{ height: "0.7rem", width: `${Math.min(100, row.demand_share * 100 * 6)}%`, background: "var(--text-primary)" }} />
                                    <div style={{ height: "0.7rem", width: `${Math.min(100, row.coverage * 100)}%`, background: "var(--brand-primary)" }} />
                                </div>
                            </div>
                        ))}
                        <p style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: "0.82rem", marginTop: "0.75rem" }}>
                            Dark bar: share of live postings naming the skill. Yellow bar: share of your
                            assessed students who can evidence it. Coverage counts corroborated levels,
                            not self-ratings.
                        </p>
                    </section>
                )}

                <div style={{ marginTop: "2rem", display: "flex", gap: "0.5rem", alignItems: "center", color: "var(--text-secondary)", fontWeight: 600 }}>
                    <Building2 size={16} />
                    <span>
                        Your cohort is derived from your own account&apos;s institution and email domain.
                        No individual student record is shown here.
                    </span>
                </div>
            </main>
        </div>
    );
}
