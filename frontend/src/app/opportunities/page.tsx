"use client";
import Sidebar from "@/components/Sidebar";
import AskAIPanel from "@/components/AskAIPanel";
import { OpportunityCardsSkeleton } from "@/components/LoadingSkeletons";
import PageHeader from "@/components/ui/PageHeader";
import PillGroup from "@/components/ui/PillGroup";
import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { MapPin, Calendar, Send, Bookmark } from "lucide-react";
import Image from "next/image";
import { Opportunity, useOpportunityFeed } from "@/hooks/useOpportunityFeed";
import { useOpportunityFeedImpressions } from "@/lib/opportunity-feed-tracker";

export default function OpportunitiesPage() {
    const {
        activeTab,
        setActiveTab,
        loading,
        notice,
        applyingId,
        savedOpportunityIds,
        imageFallbackMap,
        domains,
        grouped,
        visibleOpportunities,
        trackerContext,
        handleSave,
        handleApply,
        markImageFallback,
    } = useOpportunityFeed();
    useOpportunityFeedImpressions(visibleOpportunities, trackerContext);

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

    const renderTrustBadge = (opp: Opportunity) => {
        const isVerified = (opp.trust_status || "").toLowerCase() === "verified";
        return (
            <span
                style={{
                    fontSize: "0.72rem",
                    padding: "0.22rem 0.58rem",
                    borderRadius: "999px",
                    background: isVerified ? "#dcfce7" : "#fff7d6",
                    color: "#111111",
                    fontWeight: 900,
                    textTransform: "uppercase",
                    border: `2px solid ${isVerified ? "#86efac" : "#facc15"}`,
                }}
            >
                {isVerified ? "Verified Source" : "Source Check Pending"}
            </span>
        );
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
                        onError={() => markImageFallback(opp.id)}
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
                        {renderTrustBadge(opp)}
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
                                {renderTrustBadge(opp)}
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
                                onError={() => markImageFallback(opp.id)}
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
        <div className="opportunities-page-root">

            <Sidebar />
            <main className="main-content">
                <PageHeader
                    title={<><span>Discover </span><span className="opportunities-highlight-chip">Opportunities</span></>}
                    subtitle="Compete in hackathons, quizzes, workshops, and other non-hiring tracks from top universities and global companies."
                />

                <PillGroup className="opportunities-domain-tabs">
                    {domains.map(domain => (
                        <button
                            key={domain}
                            onClick={() => setActiveTab(domain)}
                            className={`opportunities-domain-tab ${activeTab === domain ? "active" : ""}`}
                        >
                            {domain}
                        </button>
                    ))}
                </PillGroup>

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
                    <OpportunityCardsSkeleton count={6} />
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
            </main>
        </div>
    );
}
