"use client";
import Sidebar from "@/components/Sidebar";
import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Compass, Target, TrendingUp, AlertTriangle, Loader2, BookOpen } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";

interface Question {
    skill: string;
    is_soft: boolean;
    demand_share: number;
    rationale: string;
}

interface Questionnaire {
    domain: string;
    sourced_from: string;
    postings_analysed: number;
    scale: Record<string, string>;
    questions: Question[];
}

interface GapRow {
    skill: string;
    level: number;
    demand_share: number;
    is_soft: boolean;
    priority: number;
    corroborated: boolean;
}

interface Adjustment {
    skill: string;
    claimed: number;
    recorded: number;
    reason: string;
}

interface Recommendation {
    program_id: string;
    title: string;
    provider: string;
    url?: string | null;
    program_format: string;
    duration_weeks?: number | null;
    is_free: boolean;
    certificate_offered: boolean;
    closes_gaps: string[];
    score: number;
}

interface RecommendationPayload {
    status: "ok" | "no_assessment" | "no_programs" | "no_matching_programs";
    detail: string;
    recommendations: Recommendation[];
}

interface AssessmentResult {
    id?: string | null;
    domain: string;
    readiness_score: number;
    strengths: GapRow[];
    gaps: GapRow[];
    adjustments: Adjustment[];
}

const LEVELS = [0, 1, 2, 3, 4];
const LEVEL_LABELS: Record<number, string> = {
    0: "None",
    1: "Aware",
    2: "Practising",
    3: "Confident",
    4: "Expert",
};

const GLOBAL_DOMAIN = "__all__";

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

export default function SkillsPage() {
    const [questionnaire, setQuestionnaire] = useState<Questionnaire | null>(null);
    const [responses, setResponses] = useState<Record<string, number>>({});
    const [result, setResult] = useState<AssessmentResult | null>(null);
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [programs, setPrograms] = useState<RecommendationPayload | null>(null);

    useEffect(() => {
        // Everything lives inside the effect so nothing calls setState in the
        // effect body, and `cancelled` stops a slow response from writing state
        // into an unmounted component.
        let cancelled = false;

        const load = async () => {
            try {
                const token = getAccessToken();
                if (!token) {
                    if (!cancelled) setError("Sign in to take the skill assessment.");
                    return;
                }
                const init = createAuthenticatedFetchInit({}, token);
                const [qRes, latestRes, programsRes] = await Promise.all([
                    fetch(apiUrl("/api/v1/skills/questionnaire"), init),
                    fetch(apiUrl("/api/v1/skills/assessment/latest"), init),
                    fetch(apiUrl("/api/v1/learning/recommended"), init),
                ]);
                if (!cancelled && programsRes.ok) {
                    setPrograms((await programsRes.json()) as RecommendationPayload);
                }
                if (cancelled) return;

                if (!qRes.ok) {
                    // 503 means the demand job has not run yet. Say so plainly
                    // rather than rendering an empty questionnaire, which would
                    // look identical to having no skills in demand.
                    setError(
                        qRes.status === 503
                            ? "Skill demand is still being computed from live postings. Check back shortly."
                            : "Could not load the assessment.",
                    );
                    return;
                }

                const data: Questionnaire = await qRes.json();
                if (cancelled) return;
                setQuestionnaire(data);

                if (latestRes.ok) {
                    const latest = await latestRes.json();
                    if (!cancelled && latest) setResult(latest as AssessmentResult);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Could not load the assessment.");
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

    const submit = async () => {
        if (!questionnaire) return;
        setSubmitting(true);
        setError(null);
        try {
            const token = getAccessToken();
            if (!token) {
                setError("Sign in to submit your assessment.");
                return;
            }
            // Unanswered skills count as absent rather than being omitted: a
            // skipped question is a gap, and dropping it would quietly inflate
            // the readiness score.
            const payload: Record<string, number> = {};
            for (const question of questionnaire.questions) {
                payload[question.skill] = responses[question.skill] ?? 0;
            }
            const res = await fetch(
                apiUrl("/api/v1/skills/assessment"),
                createAuthenticatedFetchInit(
                    {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ responses: payload }),
                    },
                    token,
                ),
            );
            if (!res.ok) {
                setError("Could not submit the assessment.");
                return;
            }
            setResult((await res.json()) as AssessmentResult);
            // The gaps just changed, so the recommendations built from them are
            // stale. Refetching is cheaper than explaining why they disagree.
            try {
                const rec = await fetch(
                    apiUrl("/api/v1/learning/recommended"),
                    createAuthenticatedFetchInit({}, token),
                );
                if (rec.ok) setPrograms((await rec.json()) as RecommendationPayload);
            } catch {
                // Recommendations are supplementary; the assessment result stands.
            }
            window.scrollTo({ top: 0, behavior: "smooth" });
        } catch (err) {
            setError(err instanceof Error ? err.message : "Could not submit.");
        } finally {
            setSubmitting(false);
        }
    };

    const answered = questionnaire
        ? questionnaire.questions.filter((q) => responses[q.skill] !== undefined).length
        : 0;

    return (
        <div style={{ minHeight: "100vh", display: "flex", background: "var(--bg-base)", position: "relative" }}>
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
                            Skill
                        </span>{" "}
                        Gap Analysis
                    </h1>
                    <p style={{ color: "var(--text-secondary)", fontSize: "1.15rem", maxWidth: "680px", fontWeight: 600 }}>
                        These questions are not a fixed list. They are the skills employers are asking
                        for right now, read from live postings in the corpus.
                    </p>
                    {questionnaire && (
                        <div style={{ marginTop: "1rem", display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                            <span style={{ ...panelStyle(), padding: "0.4rem 0.75rem", ...labelStyle() }}>
                                {questionnaire.postings_analysed.toLocaleString()} live postings analysed
                            </span>
                            <span style={{ ...panelStyle(), padding: "0.4rem 0.75rem", ...labelStyle() }}>
                                {questionnaire.sourced_from === GLOBAL_DOMAIN
                                    ? "across all domains"
                                    : `domain: ${questionnaire.sourced_from}`}
                            </span>
                            {questionnaire.sourced_from === GLOBAL_DOMAIN &&
                                questionnaire.domain !== GLOBAL_DOMAIN && (
                                    // Being explicit beats silently substituting: the student
                                    // would otherwise wonder why they were asked about React.
                                    <span
                                        style={{
                                            ...panelStyle(),
                                            padding: "0.4rem 0.75rem",
                                            ...labelStyle(),
                                            background: "var(--brand-primary)",
                                        }}
                                    >
                                        too few postings in {questionnaire.domain} — using the wider market
                                    </span>
                                )}
                        </div>
                    )}
                </header>

                {error && (
                    <div style={{ ...panelStyle(), padding: "1rem 1.25rem", marginBottom: "1.5rem", display: "flex", gap: "0.6rem", alignItems: "center" }}>
                        <AlertTriangle size={18} style={{ color: "var(--text-primary)" }} />
                        <span style={{ fontWeight: 700, color: "var(--text-primary)" }}>{error}</span>
                    </div>
                )}

                {loading && (
                    <div style={{ ...panelStyle(), padding: "2rem", display: "flex", gap: "0.6rem", alignItems: "center" }}>
                        <Loader2 size={18} className="animate-spin" />
                        <span style={{ fontWeight: 700 }}>Reading the live corpus…</span>
                    </div>
                )}

                <AnimatePresence>
                    {result && (
                        <motion.section
                            initial={{ opacity: 0, y: -12 }}
                            animate={{ opacity: 1, y: 0 }}
                            style={{ ...panelStyle(), padding: "1.75rem", marginBottom: "2rem" }}
                        >
                            <div style={{ display: "flex", alignItems: "baseline", gap: "1rem", flexWrap: "wrap" }}>
                                <span style={labelStyle()}>Readiness</span>
                                <span style={{ fontSize: "3rem", fontWeight: 800, fontFamily: "var(--font-serif)", color: "var(--text-primary)", lineHeight: 1 }}>
                                    {result.readiness_score}
                                    <span style={{ fontSize: "1.25rem" }}>/100</span>
                                </span>
                                <span style={{ color: "var(--text-secondary)", fontWeight: 600 }}>
                                    weighted by how often each skill appears in real postings
                                </span>
                            </div>

                            {result.adjustments.length > 0 && (
                                <div style={{ marginTop: "1.5rem", ...panelStyle(), padding: "1rem 1.25rem", background: "var(--bg-base)" }}>
                                    <div style={{ ...labelStyle(), marginBottom: "0.6rem" }}>
                                        Recorded lower than you rated — {result.adjustments.length}
                                    </div>
                                    <p style={{ color: "var(--text-secondary)", fontWeight: 600, marginBottom: "0.75rem", fontSize: "0.95rem" }}>
                                        A self-rating is a measure of confidence. These are the claims your
                                        profile does not yet back up — adding the evidence will raise them.
                                    </p>
                                    {result.adjustments.map((adjustment) => (
                                        <div key={adjustment.skill} style={{ marginBottom: "0.4rem", color: "var(--text-primary)", fontWeight: 600 }}>
                                            <strong>{adjustment.skill}</strong>: you said{" "}
                                            {LEVEL_LABELS[adjustment.claimed]}, recorded as{" "}
                                            {LEVEL_LABELS[adjustment.recorded]} — {adjustment.reason}
                                        </div>
                                    ))}
                                </div>
                            )}

                            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1.25rem", marginTop: "1.5rem" }}>
                                <div>
                                    <div style={{ ...labelStyle(), display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.75rem" }}>
                                        <TrendingUp size={16} /> Strengths
                                    </div>
                                    {result.strengths.length === 0 && (
                                        <p style={{ color: "var(--text-secondary)", fontWeight: 600 }}>
                                            Nothing corroborated yet.
                                        </p>
                                    )}
                                    {result.strengths.slice(0, 8).map((row) => (
                                        <div key={row.skill} style={{ ...panelStyle(), padding: "0.6rem 0.85rem", marginBottom: "0.5rem", display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
                                            <span style={{ fontWeight: 700, color: "var(--text-primary)" }}>{row.skill}</span>
                                            <span style={{ color: "var(--text-secondary)", fontWeight: 700 }}>
                                                {(row.demand_share * 100).toFixed(1)}% of postings
                                            </span>
                                        </div>
                                    ))}
                                </div>

                                <div>
                                    <div style={{ ...labelStyle(), display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.75rem" }}>
                                        <Target size={16} /> Gaps worth closing first
                                    </div>
                                    <p style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: "0.9rem", marginBottom: "0.75rem" }}>
                                        Ranked by demand, not by how far behind you are.
                                    </p>
                                    {result.gaps.slice(0, 8).map((row) => (
                                        <div key={row.skill} style={{ ...panelStyle(), padding: "0.6rem 0.85rem", marginBottom: "0.5rem" }}>
                                            <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
                                                <span style={{ fontWeight: 700, color: "var(--text-primary)" }}>{row.skill}</span>
                                                <span style={{ color: "var(--text-secondary)", fontWeight: 700 }}>
                                                    {(row.demand_share * 100).toFixed(1)}% of postings
                                                </span>
                                            </div>
                                            <div style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: "0.85rem" }}>
                                                you: {LEVEL_LABELS[row.level]}
                                                {row.is_soft ? " · soft skill" : ""}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </motion.section>
                    )}
                </AnimatePresence>

                {programs && result && (
                    <section style={{ ...panelStyle(), padding: "1.75rem", marginBottom: "2rem" }}>
                        <div style={{ ...labelStyle(), display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.5rem" }}>
                            <BookOpen size={16} /> Programmes that close these gaps
                        </div>
                        <p style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: "0.9rem", marginBottom: "1rem" }}>
                            Ranked by the value of the gaps each one closes, not by how many skills
                            it advertises.
                        </p>

                        {programs.status !== "ok" && (
                            // Each empty case says which it is. "No programmes published yet"
                            // and "none of them match you" are different problems with
                            // different fixes, and one empty list cannot mean both.
                            <p style={{ color: "var(--text-primary)", fontWeight: 700 }}>{programs.detail}</p>
                        )}

                        {programs.recommendations.map((program) => (
                            <div
                                key={program.program_id}
                                style={{ ...panelStyle(), padding: "0.85rem 1.1rem", marginBottom: "0.6rem", background: "var(--bg-base)" }}
                            >
                                <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
                                    <div style={{ flex: "1 1 300px" }}>
                                        <div style={{ fontWeight: 800, color: "var(--text-primary)" }}>{program.title}</div>
                                        <div style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: "0.9rem" }}>
                                            {program.provider} · {program.program_format}
                                            {program.duration_weeks != null ? ` · ${program.duration_weeks} weeks` : ""}
                                            {program.is_free ? " · free" : ""}
                                            {program.certificate_offered ? " · certificate" : ""}
                                        </div>
                                        <div style={{ color: "var(--text-primary)", fontWeight: 700, fontSize: "0.85rem", marginTop: "0.35rem" }}>
                                            Closes: {program.closes_gaps.join(", ")}
                                        </div>
                                    </div>
                                    {program.url && (
                                        <a
                                            href={program.url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            style={{
                                                ...panelStyle(),
                                                padding: "0.3rem 0.7rem",
                                                fontSize: "0.8rem",
                                                fontWeight: 800,
                                                background: "var(--brand-primary)",
                                                color: "var(--text-primary)",
                                                textDecoration: "none",
                                                alignSelf: "flex-start",
                                            }}
                                        >
                                            Open
                                        </a>
                                    )}
                                </div>
                            </div>
                        ))}
                    </section>
                )}

                {questionnaire && (
                    <section style={{ ...panelStyle(), padding: "1.75rem" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", flexWrap: "wrap", marginBottom: "1.5rem" }}>
                            <div style={{ ...labelStyle(), display: "flex", alignItems: "center", gap: "0.4rem" }}>
                                <Compass size={16} /> {result ? "Retake the assessment" : "Rate yourself"}
                            </div>
                            <span style={{ color: "var(--text-secondary)", fontWeight: 700 }}>
                                {answered}/{questionnaire.questions.length} answered
                            </span>
                        </div>

                        {questionnaire.questions.map((question) => (
                            <div key={question.skill} style={{ marginBottom: "1.25rem", paddingBottom: "1.25rem", borderBottom: "2px solid var(--border-subtle)" }}>
                                <div style={{ display: "flex", gap: "0.6rem", alignItems: "baseline", flexWrap: "wrap" }}>
                                    <span style={{ fontWeight: 800, color: "var(--text-primary)", fontSize: "1.05rem" }}>
                                        {question.skill}
                                    </span>
                                    {question.is_soft && (
                                        <span style={{ ...panelStyle(), padding: "0.1rem 0.4rem", fontSize: "0.7rem", fontWeight: 800, textTransform: "uppercase" }}>
                                            soft
                                        </span>
                                    )}
                                    <span style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: "0.85rem" }}>
                                        {question.rationale}
                                    </span>
                                </div>
                                <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
                                    {LEVELS.map((level) => {
                                        const active = responses[question.skill] === level;
                                        return (
                                            <button
                                                key={level}
                                                type="button"
                                                onClick={() =>
                                                    setResponses((prev) => ({ ...prev, [question.skill]: level }))
                                                }
                                                style={{
                                                    ...panelStyle(),
                                                    padding: "0.45rem 0.8rem",
                                                    cursor: "pointer",
                                                    fontWeight: 700,
                                                    fontSize: "0.85rem",
                                                    background: active ? "var(--brand-primary)" : "var(--bg-base)",
                                                    color: "var(--text-primary)",
                                                }}
                                                aria-pressed={active}
                                            >
                                                {LEVEL_LABELS[level]}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        ))}

                        <button
                            type="button"
                            onClick={() => void submit()}
                            disabled={submitting}
                            style={{
                                ...panelStyle(),
                                padding: "0.85rem 1.5rem",
                                cursor: submitting ? "wait" : "pointer",
                                fontWeight: 800,
                                textTransform: "uppercase",
                                letterSpacing: "0.05em",
                                background: "var(--brand-primary)",
                                color: "var(--text-primary)",
                            }}
                        >
                            {submitting ? "Scoring…" : "See my gaps"}
                        </button>
                    </section>
                )}
            </main>
        </div>
    );
}
