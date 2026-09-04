"use client";
import Sidebar from "@/components/Sidebar";
import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { GraduationCap, AlertTriangle, Loader2, ExternalLink, BookOpenCheck } from "lucide-react";
import BriefingPanel, { type Briefing } from "@/components/BriefingPanel";
import { apiUrl } from "@/lib/api";
import { createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";

interface FacultyOpportunity {
    id: string;
    title: string;
    opportunity_type?: string | null;
    organisation?: string | null;
    url?: string | null;
    location?: string | null;
    deadline?: string | null;
}

interface DemandRow {
    skill: string;
    postings: number;
    share: number;
    is_soft: boolean;
}

interface FacultyFeed {
    briefing?: Briefing | null;
    total: number;
    scanned: number;
    from_faculty_sources: number;
    from_keyword_fallback: number;
    demand_signal: DemandRow[];
    demand_domain?: string | null;
    demand_postings_analysed: number;
    opportunities: FacultyOpportunity[];
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

export default function FacultyPage() {
    const [feed, setFeed] = useState<FacultyFeed | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;

        const load = async () => {
            try {
                const token = getAccessToken();
                if (!token) {
                    if (!cancelled) setError("Sign in with an academician account to see this portal.");
                    return;
                }
                const res = await fetch(
                    apiUrl("/api/v1/academia/faculty/opportunities"),
                    createAuthenticatedFetchInit({}, token),
                );
                if (cancelled) return;
                if (res.status === 403) {
                    setError("This portal is for academician accounts.");
                    return;
                }
                if (!res.ok) {
                    setError("Could not load faculty opportunities.");
                    return;
                }
                setFeed((await res.json()) as FacultyFeed);
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Could not load faculty opportunities.");
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
                            Academician
                        </span>{" "}
                        Portal
                    </h1>
                    <p style={{ color: "var(--text-secondary)", fontSize: "1.15rem", maxWidth: "700px", fontWeight: 600 }}>
                        Faculty development programmes, industrial training, consultancy and
                        collaborative research — filtered out of the same corpus your students see,
                        so you are not handed their internships.
                    </p>
                    {feed && (
                        <div style={{ marginTop: "1rem", display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                            <span style={{ ...panelStyle(), padding: "0.4rem 0.75rem", ...labelStyle() }}>
                                {feed.total} faculty-facing
                            </span>
                            <span style={{ ...panelStyle(), padding: "0.4rem 0.75rem", ...labelStyle() }}>
                                {feed.scanned.toLocaleString()} live postings scanned
                            </span>
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
                        <span style={{ fontWeight: 700 }}>Filtering the corpus…</span>
                    </div>
                )}

                <BriefingPanel briefing={feed?.briefing} />

                {feed && feed.demand_signal.length > 0 && (
                    <section style={{ ...panelStyle(), padding: "1.5rem", marginBottom: "1.5rem" }}>
                        <div style={{ ...labelStyle(), display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.4rem" }}>
                            <BookOpenCheck size={16} /> What industry is asking for
                        </div>
                        <p style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: "0.9rem", marginBottom: "1.25rem" }}>
                            Read from {feed.demand_postings_analysed.toLocaleString()} live postings
                            {feed.demand_domain && feed.demand_domain !== "__all__" ? ` in ${feed.demand_domain}` : " across the market"}.
                            This is what your students are being hired against — the half of curriculum
                            design that usually has no data behind it.
                        </p>
                        <div style={{ display: "grid", gap: "0.6rem" }}>
                            {feed.demand_signal.map((row) => (
                                <div key={row.skill}>
                                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.25rem" }}>
                                        <span style={{ fontWeight: 700, color: "var(--text-primary)" }}>
                                            {row.skill}{row.is_soft ? " · soft" : ""}
                                        </span>
                                        <span style={{ fontWeight: 700, color: "var(--text-secondary)", fontSize: "0.85rem" }}>
                                            {(row.share * 100).toFixed(1)}% · {row.postings} postings
                                        </span>
                                    </div>
                                    <div style={{ height: "0.6rem", border: "2px solid var(--border-subtle)", background: "var(--bg-base)", borderRadius: "var(--radius-sm)", overflow: "hidden" }}>
                                        {/* Scaled against the strongest signal rather than 100%, or
                                            every bar would be a sliver: the top skill sits near 6%. */}
                                        <div style={{ height: "100%", width: `${Math.max(3, (row.share / (feed.demand_signal[0]?.share || row.share)) * 100)}%`, background: "var(--brand-primary)" }} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </section>
                )}

                {feed && (feed.from_faculty_sources > 0 || feed.from_keyword_fallback > 0) && (
                    // Stated rather than hidden: the academician corpus is still
                    // largely salvaged from student-facing sources, and a reader
                    // should know which number they are looking at.
                    <div style={{ ...panelStyle(), padding: "0.85rem 1.1rem", marginBottom: "1.5rem", color: "var(--text-secondary)", fontWeight: 600, fontSize: "0.88rem" }}>
                        {feed.from_faculty_sources} from academician sources · {feed.from_keyword_fallback} recovered
                        from the wider corpus. Academician sources are still being qualified, so the
                        second number is currently the larger one.
                    </div>
                )}

                {feed && feed.opportunities.length === 0 && (
                    // Say which of the two it is. "Nothing matched" and "nothing
                    // exists yet" look identical on screen and mean different things.
                    <div style={{ ...panelStyle(), padding: "1.5rem" }}>
                        <div style={{ ...labelStyle(), marginBottom: "0.5rem" }}>Nothing faculty-facing yet</div>
                        <p style={{ color: "var(--text-secondary)", fontWeight: 600 }}>
                            {feed.scanned.toLocaleString()} live postings were scanned and none were aimed
                            at academicians. Every source currently feeding this corpus targets student
                            roles; faculty-facing sources are still being added.
                        </p>
                    </div>
                )}

                {feed && feed.opportunities.length > 0 && (
                    <section style={{ display: "grid", gap: "0.85rem" }}>
                        {feed.opportunities.map((row, index) => (
                            <motion.article
                                key={row.id}
                                initial={{ opacity: 0, y: 8 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: Math.min(index * 0.03, 0.3) }}
                                style={{ ...panelStyle(), padding: "1.1rem 1.35rem" }}
                            >
                                <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
                                    <div style={{ flex: "1 1 320px" }}>
                                        <div style={{ fontWeight: 800, color: "var(--text-primary)", fontSize: "1.05rem" }}>
                                            {row.title}
                                        </div>
                                        <div style={{ color: "var(--text-secondary)", fontWeight: 600, marginTop: "0.25rem" }}>
                                            {[row.organisation, row.location].filter(Boolean).join(" · ") || "—"}
                                        </div>
                                    </div>
                                    <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", flexWrap: "wrap" }}>
                                        {row.opportunity_type && (
                                            <span style={{ ...panelStyle(), padding: "0.25rem 0.6rem", fontSize: "0.78rem", fontWeight: 800, background: "var(--bg-base)" }}>
                                                {row.opportunity_type}
                                            </span>
                                        )}
                                        {row.url && (
                                            <a
                                                href={row.url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                style={{
                                                    ...panelStyle(),
                                                    padding: "0.25rem 0.6rem",
                                                    fontSize: "0.78rem",
                                                    fontWeight: 800,
                                                    background: "var(--brand-primary)",
                                                    color: "var(--text-primary)",
                                                    textDecoration: "none",
                                                    display: "inline-flex",
                                                    alignItems: "center",
                                                    gap: "0.3rem",
                                                }}
                                            >
                                                Open <ExternalLink size={12} />
                                            </a>
                                        )}
                                    </div>
                                </div>
                            </motion.article>
                        ))}
                    </section>
                )}

                <div style={{ marginTop: "2rem", display: "flex", gap: "0.5rem", alignItems: "center", color: "var(--text-secondary)", fontWeight: 600 }}>
                    <GraduationCap size={16} />
                    <span>FDPs, postdocs, consultancy and academic research only. Student roles are excluded.</span>
                </div>
            </main>
        </div>
    );
}
