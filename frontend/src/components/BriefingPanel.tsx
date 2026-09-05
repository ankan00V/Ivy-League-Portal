"use client";

import React from "react";
import { Sparkles, ShieldCheck, Info } from "lucide-react";

/** What the backend returns alongside the numbers on the same page. */
export interface Briefing {
    headline: string;
    paragraphs: string[];
    actions: string[];
    /**
     * Which of three paths produced this. Rendered, not hidden — a reader
     * deciding how much weight to give a paragraph is entitled to know whether
     * a model wrote it, a template wrote it, or the platform declined to say
     * anything because there was not enough data.
     */
    source: "llm" | "deterministic" | "refused" | string;
    refusal?: string | null;
}

const PROVENANCE: Record<string, { label: string; detail: string }> = {
    llm: {
        label: "AI reading",
        detail:
            "Written by a model over the measured rows on this page. Every number it used was checked against those rows before this was shown to you.",
    },
    deterministic: {
        label: "Computed",
        detail:
            "Assembled directly from the measured rows. The model was unavailable or its answer failed the number check, so this says less rather than risking a figure nobody measured.",
    },
    refused: {
        label: "Not enough data",
        detail:
            "There is not enough evidence yet to say anything useful, and a confident paragraph over thin data would be worse than this notice.",
    },
};

/**
 * The reading of the numbers, above the numbers.
 *
 * Every dashboard here ends in a table, and a table is where the reader's work
 * starts rather than where it ends. The arithmetic was the easy half: deciding
 * which two of eleven gaps to act on, or what to put to an academic council, is
 * the part this panel does.
 */
export default function BriefingPanel({
    briefing,
    tone = "default",
}: {
    briefing: Briefing | null | undefined;
    tone?: "default" | "quiet";
}) {
    if (!briefing) return null;

    const provenance = PROVENANCE[briefing.source] || PROVENANCE.deterministic;
    const refused = briefing.source === "refused";

    return (
        <section
            style={{
                border: `2px solid ${refused ? "var(--border-subtle)" : "var(--text-primary)"}`,
                background: refused ? "var(--bg-surface)" : "var(--bg-surface)",
                boxShadow: refused ? "var(--shadow-sm)" : "var(--shadow-md)",
                borderRadius: "var(--radius-sm)",
                padding: "1.4rem 1.5rem",
                marginBottom: tone === "quiet" ? "1.25rem" : "1.5rem",
            }}
        >
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "0.75rem",
                    marginBottom: "0.75rem",
                    flexWrap: "wrap",
                }}
            >
                <div
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.45rem",
                        fontWeight: 800,
                        fontSize: "0.8rem",
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                        color: "var(--text-primary)",
                    }}
                >
                    {refused ? <Info size={16} /> : <Sparkles size={16} />}
                    What this means
                </div>
                <span
                    title={provenance.detail}
                    style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "0.3rem",
                        border: "2px solid var(--border-subtle)",
                        borderRadius: "var(--radius-sm)",
                        padding: "0.15rem 0.5rem",
                        fontSize: "0.72rem",
                        fontWeight: 800,
                        textTransform: "uppercase",
                        letterSpacing: "0.04em",
                        color: "var(--text-secondary)",
                        cursor: "help",
                        whiteSpace: "nowrap",
                    }}
                >
                    <ShieldCheck size={13} /> {provenance.label}
                </span>
            </div>

            <p
                style={{
                    fontWeight: 800,
                    fontSize: "1.05rem",
                    lineHeight: 1.4,
                    color: "var(--text-primary)",
                    margin: 0,
                }}
            >
                {briefing.headline}
            </p>

            {briefing.paragraphs.map((paragraph, index) => (
                <p
                    key={index}
                    style={{
                        marginTop: "0.75rem",
                        marginBottom: 0,
                        color: "var(--text-secondary)",
                        fontWeight: 600,
                        fontSize: "0.92rem",
                        lineHeight: 1.6,
                    }}
                >
                    {paragraph}
                </p>
            ))}

            {briefing.actions.length > 0 && (
                <ul
                    style={{
                        marginTop: "1rem",
                        marginBottom: 0,
                        paddingLeft: 0,
                        listStyle: "none",
                        display: "flex",
                        flexDirection: "column",
                        gap: "0.45rem",
                    }}
                >
                    {briefing.actions.map((action, index) => (
                        <li
                            key={index}
                            style={{
                                display: "flex",
                                gap: "0.55rem",
                                alignItems: "flex-start",
                                color: "var(--text-primary)",
                                fontWeight: 700,
                                fontSize: "0.9rem",
                                lineHeight: 1.5,
                            }}
                        >
                            <span
                                aria-hidden
                                style={{
                                    flexShrink: 0,
                                    marginTop: "0.35rem",
                                    width: "0.45rem",
                                    height: "0.45rem",
                                    background: "var(--brand-primary)",
                                    borderRadius: "50%",
                                }}
                            />
                            {action}
                        </li>
                    ))}
                </ul>
            )}

            {/* The provenance line is spelled out under a refusal rather than
                left in a tooltip, because a reader who sees an empty-looking
                panel needs to know it is a deliberate answer and not a fault. */}
            {refused && briefing.refusal && (
                <p
                    style={{
                        marginTop: "0.85rem",
                        marginBottom: 0,
                        color: "var(--text-secondary)",
                        fontWeight: 600,
                        fontSize: "0.82rem",
                    }}
                >
                    {briefing.refusal}
                </p>
            )}
        </section>
    );
}
