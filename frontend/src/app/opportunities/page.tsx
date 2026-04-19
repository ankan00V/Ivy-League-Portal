"use client";
import Sidebar from "@/components/Sidebar";
import AskAIPanel from "@/components/AskAIPanel";
import React, { startTransition, useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { MapPin, Calendar, Send, Bookmark } from "lucide-react";
import Image from "next/image";
import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";
import { logTrackedOpportunityEvent, useOpportunityFeedImpressions } from "@/lib/opportunity-feed-tracker";

interface Opportunity {
    id: string;
    title: string;
    description: string;
    url: string;
    opportunity_type: string;
    university: string;
    domain: string;
    source?: string;
    created_at?: string;
    updated_at?: string;
    last_seen_at?: string;
    deadline?: string;
    ranking_mode?: string;
    experiment_key?: string;
    experiment_variant?: string;
    rank_position?: number;
    match_score?: number;
    model_version_id?: string;
}

const FEED_REFRESH_MS = 60 * 1000;
const FEED_RETRY_MS = 10 * 1000;
const COMPETITIVE_KEYWORDS = [
    "hackathon",
    "competition",
    "challenge",
    "quiz",
    "conference",
    "workshop",
    "bootcamp",
    "webinar",
    "buildathon",
    "ctf",
];
const CAREER_KEYWORDS = ["internship", "intern", "job", "hiring", "developer", "engineer", "lead"];

const buildOpportunitiesSignature = (items: Opportunity[]): string =>
    items
        .map(
            (item) =>
                `${item.id}:${item.created_at || ""}:${item.updated_at || ""}:${item.last_seen_at || ""}:${
                    item.deadline || ""
                }:${item.title}:${item.source || ""}`
        )
        .join("|");

export default function OpportunitiesPage() {
    const [activeTab, setActiveTab] = useState("All");
    const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
    const [loading, setLoading] = useState(true);
    const [notice, setNotice] = useState<string | null>(null);
    const [applyingId, setApplyingId] = useState<string | null>(null);
    const [savedOpportunityIds, setSavedOpportunityIds] = useState<Record<string, boolean>>({});
    const [imageFallbackMap, setImageFallbackMap] = useState<Record<string, boolean>>({});
    const opportunitiesSignatureRef = useRef<string>("");
    const scraperTriggerAttemptedRef = useRef(false);

    const domains = useMemo(() => {
        const apiDomains = Array.from(new Set(opportunities.map(o => o.domain))).filter(Boolean);
        return ["All", ...apiDomains];
    }, [opportunities]);

    const triggerLiveRefresh = useEffectEvent(async () => {
        const token = getAccessToken();
        if (!token) {
            return;
        }
        try {
            await fetch(apiUrl("/api/v1/opportunities/trigger-scraper"), {
                method: "POST",
                credentials: "include",
                headers: { Authorization: `Bearer ${token}` },
            });
        } catch (error) {
            const message = error instanceof Error ? error.message : "unknown error";
            console.warn(`[Opportunities] Trigger scraper failed: ${message}`);
        }
    });

    const fetchOpportunities = useEffectEvent(async () => {
        try {
            const token = getAccessToken();
            if (token) {
                const personalizedRes = await fetch(
                    apiUrl("/api/v1/opportunities/recommended/me?limit=100&ranking_mode=ab"),
                    {
                        headers: { Authorization: `Bearer ${token}` },
                    }
                );
                if (personalizedRes.ok) {
                    const rawData: Opportunity[] = await personalizedRes.json();
                    const data: Opportunity[] = rawData.map((item, idx) => ({
                        ...item,
                        ranking_mode: item.ranking_mode || "baseline",
                        experiment_key: item.experiment_key || "ranking_mode",
                        experiment_variant: item.experiment_variant || item.ranking_mode || "baseline",
                        rank_position: item.rank_position ?? idx + 1,
                    }));
                    const nextSignature = buildOpportunitiesSignature(data);
                    if (nextSignature !== opportunitiesSignatureRef.current) {
                        opportunitiesSignatureRef.current = nextSignature;
                        startTransition(() => {
                            setOpportunities(data);
                        });
                    }
                    scraperTriggerAttemptedRef.current = false;
                    setNotice(null);
                    return;
                }
            }

            const res = await fetch(apiUrl("/api/v1/opportunities/"), { credentials: "include" });
            if (res.ok) {
                const rawData: Opportunity[] = await res.json();
                const data: Opportunity[] = rawData.map((item, idx) => ({
                    ...item,
                    ranking_mode: item.ranking_mode || "baseline",
                    experiment_key: item.experiment_key || "ranking_mode",
                    experiment_variant: item.experiment_variant || item.ranking_mode || "baseline",
                    rank_position: item.rank_position ?? idx + 1,
                }));
                const nextSignature = buildOpportunitiesSignature(data);
                if (nextSignature !== opportunitiesSignatureRef.current) {
                    opportunitiesSignatureRef.current = nextSignature;
                    startTransition(() => {
                        setOpportunities(data);
                    });
                }
                if (data.length === 0) {
                    setNotice("Refreshing live opportunities...");
                    if (!scraperTriggerAttemptedRef.current) {
                        scraperTriggerAttemptedRef.current = true;
                        void triggerLiveRefresh();
                    }
                } else {
                    scraperTriggerAttemptedRef.current = false;
                    setNotice((current) =>
                        current === "Refreshing live opportunities..." ||
                        current === "Live opportunities are temporarily unavailable. Retrying..." ||
                        current === "Backend API is unavailable. Retrying..." ? null : current
                    );
                }
                return;
            }

            const errorPayload = await res.json().catch(() => null);
            const errorDetail =
                typeof errorPayload?.detail === "string" ? errorPayload.detail : "";
            const nextNotice = errorDetail.includes("Upstream backend unavailable")
                ? "Backend API is unavailable. Retrying..."
                : "Live opportunities are temporarily unavailable. Retrying...";
            setNotice(nextNotice);
            if (!scraperTriggerAttemptedRef.current) {
                scraperTriggerAttemptedRef.current = true;
                void triggerLiveRefresh();
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : "unknown error";
            console.warn(`[Opportunities] Fetch failed: ${message}`);
            setNotice("Backend API is unavailable. Retrying...");
            if (!scraperTriggerAttemptedRef.current) {
                scraperTriggerAttemptedRef.current = true;
                void triggerLiveRefresh();
            }
        } finally {
            setLoading(false);
        }
    });

    const logOpportunityEvent = useCallback(
        async (opportunity: Opportunity, interactionType: "impression" | "click" | "save" | "apply") => {
            await logTrackedOpportunityEvent(opportunity, interactionType, {
                surface: "opportunities_page",
                activeTab,
            });
        },
        [activeTab]
    );

    useEffect(() => {
        void fetchOpportunities();
        void triggerLiveRefresh();
    }, []);

    useEffect(() => {
        const refreshMs = opportunities.length > 0 ? FEED_REFRESH_MS : FEED_RETRY_MS;
        const interval = window.setInterval(() => {
            void fetchOpportunities();
        }, refreshMs);
        return () => window.clearInterval(interval);
    }, [opportunities.length]);

    const filtered = useMemo(() => {
        const source = activeTab === "All"
            ? opportunities
            : opportunities.filter((o) => o.domain === activeTab);
        const getSortTimestamp = (opportunity: Opportunity) =>
            new Date(opportunity.last_seen_at || opportunity.updated_at || opportunity.created_at || 0).getTime();
        return [...source].sort(
            (a, b) => getSortTimestamp(b) - getSortTimestamp(a)
        );
    }, [activeTab, opportunities]);

    const grouped = useMemo(() => {
        const matchesKeyword = (value: string, keywords: string[]) =>
            keywords.some((keyword) => value.includes(keyword));

        const groups: Record<"competitive" | "career" | "other", Opportunity[]> = {
            competitive: [],
            career: [],
            other: [],
        };

        for (let idx = 0; idx < filtered.length; idx += 1) {
            const opportunity: Opportunity = {
                ...filtered[idx],
                rank_position: filtered[idx].rank_position ?? idx + 1,
            };
            const typeValue = (opportunity.opportunity_type || "").toLowerCase().trim();
            const titleValue = (opportunity.title || "").toLowerCase().trim();
            const descriptionValue = (opportunity.description || "").toLowerCase().trim();
            const haystack = `${typeValue} ${titleValue} ${descriptionValue}`;

            if (matchesKeyword(haystack, CAREER_KEYWORDS)) {
                groups.career.push(opportunity);
                continue;
            }

            if (matchesKeyword(haystack, COMPETITIVE_KEYWORDS)) {
                groups.competitive.push(opportunity);
                continue;
            }

            groups.other.push(opportunity);
        }

        return groups;
    }, [filtered]);

    const visibleOpportunities = useMemo(
        () => [...grouped.competitive, ...grouped.other],
        [grouped]
    );
    const trackerContext = useMemo(
        () => ({ surface: "opportunities_page", activeTab }),
        [activeTab]
    );
    useOpportunityFeedImpressions(visibleOpportunities, trackerContext);

    const handleSave = async (opportunity: Opportunity) => {
        setSavedOpportunityIds((current) => ({ ...current, [opportunity.id]: true }));
        await logOpportunityEvent(opportunity, "save");
    };

    const handleApply = async (opportunity: Opportunity) => {
        const token = getAccessToken();
        if (!token) {
            setNotice("Sign in to use one-click application.");
            return;
        }

        try {
            await logOpportunityEvent(opportunity, "click");
        } catch {
            // Best effort. Application flow should continue even if click telemetry fails.
        }

        setApplyingId(opportunity.id);
        setNotice(null);
        try {
            const query = new URLSearchParams({
                ranking_mode: opportunity.ranking_mode || "baseline",
                experiment_key: opportunity.experiment_key || "ranking_mode",
                experiment_variant: opportunity.experiment_variant || opportunity.ranking_mode || "baseline",
                rank_position: String(opportunity.rank_position ?? 1),
            });
            if (typeof opportunity.match_score === "number") {
                query.set("match_score", String(opportunity.match_score));
            }
            if (opportunity.model_version_id) {
                query.set("model_version_id", opportunity.model_version_id);
            }
            const res = await fetch(apiUrl(`/api/v1/applications/${opportunity.id}?${query.toString()}`), {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${token}`,
                },
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || "Application failed");
            }
            setNotice("Saved to your Applications. Redirecting...");
            if (typeof window !== "undefined") {
                if (opportunity.url) {
                    window.location.assign(opportunity.url);
                    return;
                }
                setNotice("Saved to your Applications.");
                return;
            }
        } catch (error: unknown) {
            setNotice(error instanceof Error ? error.message : "Could not submit application.");
        } finally {
            setApplyingId(null);
        }
    };

    const TYPE_IMAGE_MAP: Record<string, string> = {
        hackathon: "https://images.unsplash.com/photo-1523240795612-9a054b0db644?auto=format&fit=crop&w=1400&q=80",
        hackathons: "https://images.unsplash.com/photo-1523240795612-9a054b0db644?auto=format&fit=crop&w=1400&q=80",
        conference: "https://images.unsplash.com/photo-1517048676732-d65bc937f952?auto=format&fit=crop&w=1400&q=80",
        conferences: "https://images.unsplash.com/photo-1517048676732-d65bc937f952?auto=format&fit=crop&w=1400&q=80",
        quiz: "https://images.unsplash.com/photo-1434030216411-0b793f4b4173?auto=format&fit=crop&w=1400&q=80",
        quizzes: "https://images.unsplash.com/photo-1434030216411-0b793f4b4173?auto=format&fit=crop&w=1400&q=80",
        challenge: "https://images.unsplash.com/photo-1552664730-d307ca884978?auto=format&fit=crop&w=1400&q=80",
        competition: "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=1400&q=80",
        workshop: "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?auto=format&fit=crop&w=1400&q=80",
        internship: "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?auto=format&fit=crop&w=1400&q=80",
        hiring: "https://images.unsplash.com/photo-1520607162513-77705c0f0d4a?auto=format&fit=crop&w=1400&q=80",
    };

    const DOMAIN_IMAGE_MAP: Record<string, string> = {
        "ai and machine learning": "https://images.unsplash.com/photo-1532619675605-1ede6c2ed2b0?auto=format&fit=crop&w=1400&q=80",
        engineering: "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?auto=format&fit=crop&w=1400&q=80",
        finance: "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?auto=format&fit=crop&w=1400&q=80",
        "data science": "https://images.unsplash.com/photo-1516321497487-e288fb19713f?auto=format&fit=crop&w=1400&q=80",
        law: "https://images.unsplash.com/photo-1589829545856-d10d557cf95f?auto=format&fit=crop&w=1400&q=80",
        biomedical: "https://images.unsplash.com/photo-1579154204601-01588f351e67?auto=format&fit=crop&w=1400&q=80",
        healthcare: "https://images.unsplash.com/photo-1579154204601-01588f351e67?auto=format&fit=crop&w=1400&q=80",
    };

    const FALLBACK_IMAGE =
        "https://images.unsplash.com/photo-1503676260728-1c00da094a0b?auto=format&fit=crop&w=1400&q=80";

    const normalize = (value?: string) => (value || "").toLowerCase().trim();

    const findMappedImage = (value: string, map: Record<string, string>) => {
        for (const [keyword, image] of Object.entries(map)) {
            if (value.includes(keyword)) {
                return image;
            }
        }
        return null;
    };

    const getCompetitionImage = (opp: Opportunity) => {
        const typeValue = normalize(opp.opportunity_type);
        const domainValue = normalize(opp.domain);
        const titleValue = normalize(opp.title);

        return (
            findMappedImage(typeValue, TYPE_IMAGE_MAP) ||
            findMappedImage(domainValue, DOMAIN_IMAGE_MAP) ||
            findMappedImage(titleValue, TYPE_IMAGE_MAP) ||
            FALLBACK_IMAGE
        );
    };

    const formatSourceLabel = (source?: string) => {
        const normalized = (source || "source").replace(/_/g, " ").trim();
        return normalized
            .split(" ")
            .filter(Boolean)
            .map((chunk) => chunk.charAt(0).toUpperCase() + chunk.slice(1))
            .join(" ");
    };

    const renderCompetitiveCard = (opp: Opportunity, idx: number) => {
        const imageUrl = imageFallbackMap[opp.id] ? FALLBACK_IMAGE : getCompetitionImage(opp);
        return (
            <motion.article
                key={opp.id || idx}
                initial={{ opacity: 0, scale: 0.96, y: 24 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.96, y: 12 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
                className="card-panel"
                style={{
                    padding: 0,
                    display: "grid",
                    gridTemplateColumns: "minmax(150px, 190px) minmax(0, 1fr)",
                    minHeight: "240px",
                    overflow: "hidden",
                    background:
                        "linear-gradient(135deg, color-mix(in srgb, var(--brand-accent) 22%, transparent), var(--bg-surface) 55%)",
                }}
                whileHover={{ y: -5, boxShadow: "var(--shadow-md)", borderColor: "var(--brand-primary)" }}
            >
                <div
                    style={{
                        position: "relative",
                        minHeight: "100%",
                        borderRight: "2px solid var(--border-subtle)",
                        background: "#111111",
                    }}
                >
                    <Image
                        src={imageUrl}
                        alt={`${opp.opportunity_type || "Opportunity"} banner`}
                        fill
                        sizes="(max-width: 768px) 100vw, 190px"
                        onError={() => {
                            if (!imageFallbackMap[opp.id]) {
                                setImageFallbackMap((prev) => ({ ...prev, [opp.id]: true }));
                            }
                        }}
                        style={{ objectFit: "cover" }}
                    />
                    <div
                        style={{
                            position: "absolute",
                            inset: 0,
                            background: "linear-gradient(180deg, rgba(0,0,0,0.08) 0%, rgba(0,0,0,0.56) 100%)",
                        }}
                    />
                    <div
                        style={{
                            position: "absolute",
                            left: "1rem",
                            bottom: "1rem",
                            display: "flex",
                            flexDirection: "column",
                            gap: "0.5rem",
                        }}
                    >
                        <span
                            style={{
                                display: "inline-flex",
                                alignItems: "center",
                                width: "fit-content",
                                background: "var(--brand-primary)",
                                color: "#000000",
                                padding: "0.35rem 0.7rem",
                                borderRadius: "var(--radius-sm)",
                                border: "2px solid #000000",
                                fontSize: "0.75rem",
                                fontWeight: 900,
                                textTransform: "uppercase",
                                letterSpacing: "0.08em",
                            }}
                        >
                            Event Track
                        </span>
                        <span style={{ color: "#ffffff", fontWeight: 700, fontSize: "0.85rem" }}>
                            {opp.deadline
                                ? `Closes ${new Date(opp.deadline).toLocaleDateString(undefined, {
                                      month: "short",
                                      day: "numeric",
                                  })}`
                                : "Rolling basis"}
                        </span>
                    </div>
                </div>
                <div style={{ padding: "1.5rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem" }}>
                        <span
                            style={{
                                fontSize: "0.75rem",
                                padding: "0.25rem 0.6rem",
                                borderRadius: "999px",
                                background: "#ffffff",
                                color: "#000000",
                                fontWeight: 900,
                                textTransform: "uppercase",
                                border: "2px solid var(--border-subtle)",
                            }}
                        >
                            {opp.opportunity_type || "Opportunity"}
                        </span>
                        <span
                            style={{
                                fontSize: "0.75rem",
                                padding: "0.25rem 0.6rem",
                                borderRadius: "999px",
                                background: "color-mix(in srgb, var(--brand-accent) 80%, white 20%)",
                                color: "#000000",
                                fontWeight: 800,
                                textTransform: "uppercase",
                                border: "2px solid var(--border-subtle)",
                            }}
                        >
                            {formatSourceLabel(opp.source)}
                        </span>
                    </div>

                    <div>
                        <h2
                            style={{
                                fontSize: "1.4rem",
                                marginBottom: "0.55rem",
                                color: "var(--text-primary)",
                                lineHeight: 1.2,
                                fontWeight: 900,
                            }}
                        >
                            {opp.title}
                        </h2>
                        <p
                            style={{
                                color: "var(--text-secondary)",
                                fontSize: "0.95rem",
                                display: "-webkit-box",
                                WebkitLineClamp: 3,
                                WebkitBoxOrient: "vertical",
                                overflow: "hidden",
                                fontWeight: 500,
                            }}
                        >
                            {opp.description}
                        </p>
                    </div>

                    <div
                        style={{
                            marginTop: "auto",
                            display: "flex",
                            justifyContent: "space-between",
                            gap: "1rem",
                            alignItems: "end",
                            borderTop: "2px solid var(--border-subtle)",
                            paddingTop: "1rem",
                        }}
                    >
                        <div style={{ display: "grid", gap: "0.45rem" }}>
                            <span style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.9rem", fontWeight: 700 }}>
                                <MapPin size={14} /> {opp.university || "Global"}
                            </span>
                            <span style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.9rem", color: "var(--text-secondary)", fontWeight: 700 }}>
                                <Calendar size={14} />
                                {opp.deadline
                                    ? new Date(opp.deadline).toLocaleDateString(undefined, {
                                          month: "short",
                                          day: "numeric",
                                          year: "numeric",
                                      })
                                    : "Rolling Basis"}
                            </span>
                        </div>
                        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", justifyContent: "end" }}>
                            <button
                                className="btn-primary"
                                style={{ padding: "0.7rem 1.1rem", fontSize: "0.9rem", display: "flex", alignItems: "center", gap: "0.4rem", border: "2px solid #000000" }}
                                onClick={() => void handleApply(opp)}
                                disabled={applyingId === opp.id}
                            >
                                <Send size={14} />
                                {applyingId === opp.id ? "Joining..." : "Join"}
                            </button>
                            <button
                                className="btn-secondary"
                                style={{ padding: "0.7rem 0.95rem", fontSize: "0.9rem", display: "flex", alignItems: "center", gap: "0.3rem", border: "2px solid var(--border-subtle)" }}
                                onClick={() => void handleSave(opp)}
                                disabled={Boolean(savedOpportunityIds[opp.id])}
                            >
                                <Bookmark size={14} />
                                {savedOpportunityIds[opp.id] ? "Saved" : "Save"}
                            </button>
                        </div>
                    </div>
                </div>
            </motion.article>
        );
    };

    const renderCareerCard = (opp: Opportunity, idx: number) => {
        const imageUrl = imageFallbackMap[opp.id] ? FALLBACK_IMAGE : getCompetitionImage(opp);
        return (
            <motion.article
                key={opp.id || idx}
                initial={{ opacity: 0, scale: 0.98, y: 24 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.98, y: 12 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
                className="card-panel"
                style={{ padding: 0, display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}
                whileHover={{ y: -5, boxShadow: "var(--shadow-md)", borderColor: "var(--brand-primary)" }}
            >
                <div
                    style={{
                        height: "10px",
                        background:
                            "linear-gradient(90deg, color-mix(in srgb, var(--brand-primary) 88%, white 12%), color-mix(in srgb, var(--brand-accent) 88%, white 12%))",
                        borderBottom: "2px solid var(--border-subtle)",
                    }}
                />
                <div style={{ padding: "1.4rem", display: "flex", flexDirection: "column", gap: "1rem", height: "100%" }}>
                    <div style={{ display: "flex", alignItems: "start", justifyContent: "space-between", gap: "1rem" }}>
                        <div style={{ minWidth: 0 }}>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.8rem" }}>
                                <span
                                    style={{
                                        fontSize: "0.72rem",
                                        padding: "0.22rem 0.58rem",
                                        borderRadius: "999px",
                                        background: "var(--bg-surface-hover)",
                                        color: "var(--text-primary)",
                                        fontWeight: 900,
                                        textTransform: "uppercase",
                                        border: "2px solid var(--border-subtle)",
                                    }}
                                >
                                    Career Track
                                </span>
                                <span
                                    style={{
                                        fontSize: "0.72rem",
                                        padding: "0.22rem 0.58rem",
                                        borderRadius: "999px",
                                        background: "#ffffff",
                                        color: "#000000",
                                        fontWeight: 900,
                                        textTransform: "uppercase",
                                        border: "2px solid var(--border-subtle)",
                                    }}
                                >
                                    {opp.opportunity_type || "Opportunity"}
                                </span>
                            </div>
                            <h2
                                style={{
                                    fontSize: "1.18rem",
                                    marginBottom: "0.45rem",
                                    color: "var(--text-primary)",
                                    lineHeight: 1.25,
                                    fontWeight: 850,
                                }}
                            >
                                {opp.title}
                            </h2>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.8rem", color: "var(--text-secondary)", fontWeight: 700, fontSize: "0.88rem" }}>
                                <span style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
                                    <MapPin size={14} /> {opp.university || "Global"}
                                </span>
                                <span>{formatSourceLabel(opp.source)}</span>
                            </div>
                        </div>
                        <div
                            style={{
                                width: "64px",
                                height: "64px",
                                position: "relative",
                                borderRadius: "16px",
                                overflow: "hidden",
                                flexShrink: 0,
                                border: "2px solid var(--border-subtle)",
                                boxShadow: "var(--shadow-sm)",
                                background: "#111111",
                            }}
                        >
                            <Image
                                src={imageUrl}
                                alt={`${opp.opportunity_type || "Opportunity"} preview`}
                                fill
                                sizes="64px"
                                onError={() => {
                                    if (!imageFallbackMap[opp.id]) {
                                        setImageFallbackMap((prev) => ({ ...prev, [opp.id]: true }));
                                    }
                                }}
                                style={{ objectFit: "cover" }}
                            />
                        </div>
                    </div>

                    <div
                        style={{
                            display: "grid",
                            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                            gap: "0.8rem",
                            background: "var(--bg-surface-hover)",
                            border: "2px solid var(--border-subtle)",
                            borderRadius: "var(--radius-md)",
                            padding: "0.9rem",
                        }}
                    >
                        <div>
                            <div style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 900, color: "var(--text-secondary)", marginBottom: "0.35rem" }}>
                                Domain
                            </div>
                            <div style={{ fontWeight: 800, color: "var(--text-primary)" }}>{opp.domain || "General"}</div>
                        </div>
                        <div>
                            <div style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 900, color: "var(--text-secondary)", marginBottom: "0.35rem" }}>
                                Deadline
                            </div>
                            <div style={{ fontWeight: 800, color: "var(--text-primary)" }}>
                                {opp.deadline
                                    ? new Date(opp.deadline).toLocaleDateString(undefined, {
                                          month: "short",
                                          day: "numeric",
                                          year: "numeric",
                                      })
                                    : "Rolling Basis"}
                            </div>
                        </div>
                    </div>

                    <p
                        style={{
                            color: "var(--text-secondary)",
                            fontSize: "0.95rem",
                            marginBottom: "0.25rem",
                            flex: 1,
                            display: "-webkit-box",
                            WebkitLineClamp: 4,
                            WebkitBoxOrient: "vertical",
                            overflow: "hidden",
                            fontWeight: 500,
                        }}
                    >
                        {opp.description}
                    </p>

                    <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", marginTop: "auto" }}>
                        <button
                            className="btn-primary"
                            style={{ padding: "0.7rem 1rem", fontSize: "0.9rem", display: "flex", alignItems: "center", gap: "0.4rem", border: "2px solid #000000" }}
                            onClick={() => void handleApply(opp)}
                            disabled={applyingId === opp.id}
                        >
                            <Send size={14} />
                            {applyingId === opp.id ? "Applying..." : "Apply"}
                        </button>
                        <button
                            className="btn-secondary"
                            style={{ padding: "0.7rem 0.95rem", fontSize: "0.9rem", display: "flex", alignItems: "center", gap: "0.3rem", border: "2px solid var(--border-subtle)" }}
                            onClick={() => void handleSave(opp)}
                            disabled={Boolean(savedOpportunityIds[opp.id])}
                        >
                            <Bookmark size={14} />
                            {savedOpportunityIds[opp.id] ? "Saved" : "Save"}
                        </button>
                    </div>
                </div>
            </motion.article>
        );
    };

    const renderSection = (
        title: string,
        subtitle: string,
        items: Opportunity[],
        variant: "competitive" | "career" | "other"
    ) => {
        if (!items.length) {
            return null;
        }

        return (
            <section style={{ marginBottom: "3rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "end", gap: "1rem", marginBottom: "1.25rem", flexWrap: "wrap" }}>
                    <div>
                        <h2 style={{ fontSize: "1.7rem", fontWeight: 900, color: "var(--text-primary)", marginBottom: "0.35rem" }}>
                            {title}
                        </h2>
                        <p style={{ color: "var(--text-secondary)", fontSize: "0.98rem", fontWeight: 600 }}>
                            {subtitle}
                        </p>
                    </div>
                    <div
                        style={{
                            padding: "0.5rem 0.8rem",
                            border: "2px solid var(--border-subtle)",
                            borderRadius: "999px",
                            background: variant === "competitive" ? "var(--brand-accent)" : "var(--bg-surface)",
                            color: "#000000",
                            fontWeight: 900,
                            boxShadow: "var(--shadow-sm)",
                        }}
                    >
                        {items.length} live
                    </div>
                </div>
                <div
                    style={{
                        display: "grid",
                        gridTemplateColumns:
                            variant === "competitive" ? "1fr" : "repeat(auto-fill, minmax(320px, 1fr))",
                        gap: "1.5rem",
                    }}
                >
                    <AnimatePresence mode="popLayout" initial={false}>
                        {items.map((opp, idx) =>
                            variant === "competitive" ? renderCompetitiveCard(opp, idx) : renderCareerCard(opp, idx)
                        )}
                    </AnimatePresence>
                </div>
            </section>
        );
    };

    return (
        <div style={{ minHeight: '100vh', display: 'flex', background: 'var(--bg-base)', position: 'relative' }}>

            <Sidebar />
            <main className="main-content">
                <header style={{ marginBottom: '3rem' }}>
                    <h1 style={{ fontSize: '3rem', marginBottom: '0.75rem', fontWeight: 400, fontFamily: 'var(--font-serif)', color: 'var(--text-primary)', lineHeight: 1.1 }}>
                        Discover <span style={{ background: 'var(--brand-accent)', padding: '0.2rem 0.5rem', border: '2px solid var(--border-subtle)', boxShadow: 'var(--shadow-sm)', display: 'inline-block', transform: 'rotate(-2deg)' }}>Opportunities</span>
                    </h1>
                    <p style={{ color: 'var(--text-secondary)', fontSize: '1.25rem', maxWidth: '600px', fontWeight: 600 }}>
                        Compete in hackathons, quizzes, workshops, and other non-hiring tracks from top universities and global companies.
                    </p>
                </header>

                {/* Brutalist Navigation Filters */}
                <div style={{
                    display: 'flex',
                    gap: '1rem',
                    marginBottom: '2.5rem',
                    overflowX: 'auto',
                    paddingBottom: '1rem',
                    /* Hide scrollbar for cleaner look */
                    scrollbarWidth: 'none',
                    msOverflowStyle: 'none'
                }}>
                    {domains.map(domain => (
                        <button
                            key={domain}
                            onClick={() => setActiveTab(domain)}
                            style={{
                                padding: '0.75rem 1.75rem',
                                borderRadius: 'var(--radius-sm)',
                                fontWeight: 700,
                                fontSize: '1rem',
                                whiteSpace: 'nowrap',
                                transition: 'var(--bounce-transition)',
                                background: activeTab === domain ? 'var(--brand-primary)' : 'var(--bg-surface)',
                                color: activeTab === domain ? '#000000' : 'var(--text-primary)',
                                border: '2px solid var(--border-subtle)',
                                boxShadow: activeTab === domain ? 'var(--shadow-sm)' : 'var(--shadow-md)',
                                transform: activeTab === domain ? 'translate(2px, 2px)' : 'none'
                            }}
                        >
                            {domain}
                        </button>
                    ))}
                </div>

                <AskAIPanel
                    surface="opportunities_page"
                    suggestedQueries={[
                        "hackathons for web3 and smart contracts with deadlines soon",
                        "research fellowships in AI evaluation or NLP with citations",
                        "product and analytics competitions worth shortlisting this week",
                    ]}
                />

                {/* Interactive Grid Layout */}
                {notice && (
                    <div className="card-panel" style={{ marginBottom: "1.5rem", background: "var(--bg-surface-hover)" }}>
                        <strong>{notice}</strong>
                    </div>
                )}
                {loading ? (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '2rem' }}>
                        {Array.from({ length: 6 }).map((_, idx) => (
                            <div key={`skel-${idx}`} className="card-panel" style={{ padding: 0, height: '420px', display: 'flex', flexDirection: 'column' }}>
                                <div style={{ height: '160px', background: 'var(--bg-surface-hover)', animation: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite' }} />
                                <div style={{ padding: '1.5rem', flex: 1, display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                    <div style={{ height: '24px', background: 'var(--bg-surface-hover)', borderRadius: '4px', width: '80%', animation: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite' }} />
                                    <div style={{ height: '16px', background: 'var(--bg-surface-hover)', borderRadius: '4px', width: '100%', animation: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite' }} />
                                    <div style={{ height: '16px', background: 'var(--bg-surface-hover)', borderRadius: '4px', width: '60%', animation: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite' }} />
                                    <div style={{ marginTop: 'auto', height: '40px', background: 'var(--bg-surface-hover)', borderRadius: '24px', width: '100%', animation: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite' }} />
                                </div>
                            </div>
                        ))}
                    </div>
                ) : (
                    <>
                        {renderSection(
                            "Challenges & Competitions",
                            "Hackathons, quizzes, buildathons, workshops, and other event-driven opportunities.",
                            grouped.competitive,
                            "competitive"
                        )}
                        {renderSection(
                            "Other Opportunities",
                            "Everything that does not clearly fit the event or hiring tracks.",
                            grouped.other,
                            "other"
                        )}
                        {!visibleOpportunities.length && (
                            <div className="card-panel" style={{ padding: "1.5rem" }}>
                                <strong>No non-hiring opportunities match this filter right now.</strong>
                            </div>
                        )}
                    </>
                )}

                {/* CSS for Skeleton Pulse since we didn't add it to globals.css */}
                <style dangerouslySetInnerHTML={{
                    __html: `
                    @keyframes pulse {
                        0%, 100% { opacity: 1; }
                        50% { opacity: .5; }
                    }
                `}} />
            </main>
        </div>
    );
}
