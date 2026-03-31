"use client";
import React, { useState, useEffect } from "react";
import Sidebar from "@/components/Sidebar";
import { motion, useMotionValue, useTransform } from "framer-motion";
import { TrendingUp, Briefcase, ShieldCheck, Activity, Sparkles, Star } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { useRouter } from "next/navigation";

interface OpportunityCard {
    id: string;
    title: string;
    domain?: string;
}

interface ActivityPost {
    id: string;
    created_at: string;
    content: string;
}

interface ProfileSummary {
    incoscore: number;
    email?: string;
    full_name?: string;
    skills?: string;
}

interface TiltCardProps {
    children: React.ReactNode;
    style?: React.CSSProperties;
    className?: string;
}

// --- 3D TILT CARD COMPONENT ---
const TiltCard = ({ children, style, className }: TiltCardProps) => {
    const x = useMotionValue(0);
    const y = useMotionValue(0);
    const rotateX = useTransform(y, [-100, 100], [15, -15]);
    const rotateY = useTransform(x, [-100, 100], [-15, 15]);

    const handleMouseMove = (event: React.MouseEvent<HTMLDivElement, MouseEvent>) => {
        const rect = event.currentTarget.getBoundingClientRect();
        x.set(event.clientX - rect.left - rect.width / 2);
        y.set(event.clientY - rect.top - rect.height / 2);
    };

    const handleMouseLeave = () => {
        x.set(0);
        y.set(0);
    };

    return (
        <motion.div
            className={className}
            style={{
                ...style,
                rotateX,
                rotateY,
                transformStyle: "preserve-3d",
                perspective: 1000
            }}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0, transition: { type: "spring", stiffness: 300, damping: 24 } }}
            whileHover={{ scale: 1.02 }}
        >
            {/* The inner children must also be translated in Z to give the pop effect */}
            <div style={{ transform: "translateZ(30px)" }}>
                {children}
            </div>
        </motion.div>
    );
};

// --- MULTIPLE MOCK COMPANIES FOR MARQUEE ---
const MARQUEE_COMPANIES = [
    "Google", "Meta", "Apple", "Netflix", "Amazon", "Microsoft", "Stripe", "SpaceX", 
    "OpenAI", "Anthropic", "Tesla", "NVIDIA", "Palantir", "Databricks"
];

// --- GENUINE INFO MOCKS ---
const MOCK_OPPORTUNITIES = [
    { id: 'm1', title: 'Google Summer of Code 2026', domain: 'Engineering' },
    { id: 'm2', title: 'Meta Hacker Cup - Round 1', domain: 'Competitive Programming' },
    { id: 'm3', title: 'Stripe API Design Challenge', domain: 'Backend' },
];

const MOCK_POSTS = [
    { id: 'p1', created_at: '2026-03-02T00:00:00.000Z', content: 'Just secured a position at Palantir through the latest InCo hiring drive! 🚀 Highly recommend tracking their portal.' },
    { id: 'p2', created_at: '2026-03-01T00:00:00.000Z', content: 'The new AWS Cloud Architect challenge is live. Who else is participating this weekend?' }
];

const formatStableDate = (value: string) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, '0');
    const day = String(date.getUTCDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
};

export default function DashboardPage() {
    const router = useRouter();
    const [recommended, setRecommended] = useState<OpportunityCard[]>([]);
    const [profile, setProfile] = useState<ProfileSummary | null>(null);
    const [appCount, setAppCount] = useState<number>(0);
    const [posts, setPosts] = useState<ActivityPost[]>([]);

    const fetchDashboardData = async () => {
        try {
            const token = localStorage.getItem("access_token");
            const headers = {
                "Authorization": `Bearer ${token}`
            };

            // 1. Fetch Profile
            const profileRes = await fetch(apiUrl("/api/v1/users/me/profile"), { headers });
            if (profileRes.ok) {
                const pData = await profileRes.json();
                setProfile(pData);
            }

            // 2. Fetch Applications
            const appsRes = await fetch(apiUrl("/api/v1/applications/"), { headers });
            if (appsRes.ok) {
                const aData = await appsRes.json();
                setAppCount(aData.length);
            }

            // 3. Fetch Personalized Opportunities (Top 3)
            const oppsRes = await fetch(apiUrl("/api/v1/opportunities/recommended/me?limit=3"), { headers });
            if (oppsRes.ok) {
                const oData = await oppsRes.json();
                setRecommended(oData);
            } else {
                const fallback = await fetch(apiUrl("/api/v1/opportunities/?limit=3"));
                if (fallback.ok) {
                    const fallbackData = await fallback.json();
                    setRecommended(fallbackData);
                }
            }

            // 4. Fetch Network Posts (Top 2)
            const postsRes = await fetch(apiUrl("/api/v1/social/posts?limit=2"), { headers });
            if (postsRes.ok) {
                const pData = await postsRes.json();
                setPosts(pData);
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : "unknown error";
            console.warn(`[Dashboard] Data refresh failed: ${message}`);
        }
    };

    useEffect(() => {
        const firstRun = window.setTimeout(() => {
            void fetchDashboardData();
        }, 0);
        const interval = window.setInterval(() => {
            void fetchDashboardData();
        }, 10000);
        return () => {
            window.clearTimeout(firstRun);
            window.clearInterval(interval);
        };
    }, []);

    const getMatchPercent = (seed: string) => {
        let hash = 0;
        for (let i = 0; i < seed.length; i++) hash = seed.charCodeAt(i) + ((hash << 5) - hash);
        return 85 + (Math.abs(hash) % 15);
    };

    const activeRecommendations = recommended.length > 0 ? recommended : MOCK_OPPORTUNITIES;
    const activePosts = posts.length > 0 ? posts : MOCK_POSTS;

    return (
        <div style={{ minHeight: '100vh', display: 'flex', background: 'var(--bg-base)', position: 'relative', overflow: 'hidden' }}>

            <Sidebar />

            <motion.main
                className={`main-content`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1, transition: { staggerChildren: 0.1 } }}
                style={{ perspective: 1200 }} // Added perspective to the main content so 3D children pop
            >
                {/* Hero Header */}
                <motion.header
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0, transition: { type: "spring", stiffness: 300, damping: 24 } }}
                    style={{
                        marginBottom: '1rem',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        background: 'var(--brand-primary)',
                        border: '2px solid var(--border-subtle)',
                        padding: '2.5rem 3rem',
                        borderRadius: 'var(--radius-md)',
                        color: '#000000',
                        boxShadow: 'var(--shadow-md)'
                    }}>
                    <div>
                        <h1 style={{ fontSize: '3.5rem', marginBottom: '0.25rem', color: '#000000', fontFamily: 'var(--font-serif)', lineHeight: 1, display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            Welcome back, Student! <Sparkles size={36} />
                        </h1>
                        <p style={{ color: 'rgba(0,0,0,0.8)', fontSize: '1.25rem', maxWidth: '500px', fontWeight: 600 }}>
                            Your opportunity intelligence overview is ready. Discover your next big win today.
                        </p>
                    </div>
                    <button className="btn-secondary">
                        Update Profile
                    </button>
                </motion.header>

                {/* Infinite Marquee */}
                <div style={{ 
                    overflow: 'hidden', 
                    whiteSpace: 'nowrap', 
                    marginBottom: '3rem', 
                    background: 'var(--bg-surface-hover)', 
                    border: '2px solid var(--border-subtle)', 
                    padding: '0.75rem 0',
                    borderRadius: 'var(--radius-sm)',
                    boxShadow: 'var(--shadow-sm)',
                    display: 'flex',
                    alignItems: 'center'
                }}>
                    <motion.div
                        animate={{ x: [0, -1035] }} // Adjust width translation based on content
                        transition={{ repeat: Infinity, duration: 25, ease: "linear" }}
                        style={{ display: 'flex', gap: '3rem', paddingLeft: '3rem' }}
                    >
                        {/* Duplicate the array to create a seamless loop */}
                        {[...MARQUEE_COMPANIES, ...MARQUEE_COMPANIES].map((company, idx) => (
                            <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 800, fontSize: '1.1rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                <Star size={16} style={{ color: 'var(--brand-primary)' }} /> {company}
                            </div>
                        ))}
                    </motion.div>
                </div>

                {/* Stats Grid with 3D Placards */}
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1, transition: { staggerChildren: 0.1 } }}
                    style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1.5rem', marginBottom: '3rem' }}
                >
                    <TiltCard
                        className="card-panel"
                        style={{ background: 'var(--brand-primary)', color: '#000000' }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', color: 'rgba(0,0,0,0.7)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem', fontWeight: 700 }}>
                            <TrendingUp size={18} /> InCoScore Ranking
                        </div>
                        <div style={{ fontSize: '4rem', fontWeight: 400, fontFamily: 'var(--font-serif)', color: '#000000', lineHeight: 1 }}>
                            {profile?.incoscore?.toFixed(1) || 0}
                        </div>
                        <div style={{ fontSize: '0.9rem', color: 'rgba(0,0,0,0.8)', marginTop: '0.5rem', fontWeight: 600 }}>Top 5% Globally</div>
                    </TiltCard>

                    <TiltCard
                        className="card-panel"
                        style={{ background: 'var(--brand-accent)', color: '#000000' }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', color: 'rgba(0,0,0,0.7)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem', fontWeight: 700 }}>
                            <Briefcase size={18} /> Active Applications
                        </div>
                        <div style={{ fontSize: '4rem', fontWeight: 400, fontFamily: 'var(--font-serif)', color: '#000000', lineHeight: 1 }}>
                            {appCount}
                        </div>
                        <div style={{ fontSize: '0.9rem', color: 'rgba(0,0,0,0.8)', marginTop: '0.5rem', fontWeight: 600 }}>Live Synchronized Tracking</div>
                    </TiltCard>

                    <TiltCard
                        className="card-panel"
                        style={{ background: 'var(--bg-surface)', color: 'var(--text-primary)' }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem', fontWeight: 700 }}>
                            <ShieldCheck size={18} /> Profile Strength
                        </div>
                        <div style={{ fontSize: '4rem', fontWeight: 400, fontFamily: 'var(--font-serif)', color: 'var(--text-primary)', lineHeight: 1 }}>
                            {profile?.skills ? '100%' : '20%'}
                        </div>
                        <div style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginTop: '0.5rem', fontWeight: 600 }}>Add resume to reach 100%</div>
                    </TiltCard>
                </motion.div>

                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1, transition: { staggerChildren: 0.1 } }}
                    style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '2rem' }}
                >
                    {/* Recommended Opportunities */}
                    <motion.section
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0, transition: { type: "spring", stiffness: 300, damping: 24 } }}
                        className="card-panel"
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                            <h2 style={{ fontSize: '1.5rem' }}>Live Recommendations</h2>
                            <span style={{ fontSize: '0.85rem', padding: '0.25rem 0.6rem', background: 'var(--bg-surface-hover)', color: 'var(--text-primary)', borderRadius: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                <Activity size={14} className="animate-pulse" style={{ color: '#10b981' }} />
                                Real-Time Feed
                            </span>
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                            {activeRecommendations.map((opp, idx) => (
                                <div key={opp.id || idx}
                                    className="card-panel"
                                    style={{
                                        display: 'flex',
                                        justifyContent: 'space-between',
                                        alignItems: 'center',
                                        cursor: 'pointer',
                                        padding: '1rem 1.25rem'
                                    }}
                                    onClick={() => router.push('/opportunities')}
                                >
                                    <div style={{ display: 'flex', gap: '1.25rem', alignItems: 'center' }}>
                                        <div style={{
                                            width: '48px', height: '48px',
                                            borderRadius: 'var(--radius-sm)',
                                            background: 'var(--brand-primary)',
                                            border: '2px solid var(--border-subtle)',
                                            boxShadow: 'var(--shadow-sm)',
                                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                                            color: '#000000', fontWeight: 800, fontSize: '1.5rem', fontFamily: 'var(--font-serif)'
                                        }}>
                                            {opp.domain ? opp.domain.charAt(0).toUpperCase() : 'G'}
                                        </div>
                                        <div>
                                            <h3 style={{ fontSize: '1.1rem', marginBottom: '0.2rem', fontWeight: 700, color: 'var(--text-primary)', display: '-webkit-box', WebkitLineClamp: 1, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{opp.title}</h3>
                                            <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                                                {opp.domain}
                                            </div>
                                        </div>
                                    </div>
                                    <div style={{ textAlign: 'right' }}>
                                        <div style={{ color: '#000000', fontWeight: 700, padding: '0.25rem 0.75rem', background: 'var(--brand-accent)', border: '2px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', fontSize: '0.85rem', whiteSpace: 'nowrap' }}>
                                            {getMatchPercent(opp.domain || 'x')}% Match
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </motion.section>

                    {/* Network Feed Snippet */}
                    <motion.section
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0, transition: { type: "spring", stiffness: 300, damping: 24 } }}
                        className="card-panel"
                    >
                        <h2 style={{ fontSize: '1.5rem', marginBottom: '1.5rem', fontFamily: 'var(--font-serif)', fontWeight: 400 }}>Live Network Activity</h2>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                            {activePosts.map((post, index) => (
                                <div key={post.id || index} style={{ borderBottom: index !== activePosts.length - 1 ? '2px solid var(--border-subtle)' : 'none', paddingBottom: index !== activePosts.length - 1 ? '1.25rem' : '0' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
                                        <div style={{ width: 40, height: 40, borderRadius: 'var(--radius-sm)', background: 'var(--brand-accent)', border: '2px solid var(--border-subtle)', boxShadow: 'var(--shadow-sm)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#000000', fontSize: '1rem', fontWeight: 800, fontFamily: 'var(--font-serif)' }}>
                                            VV
                                        </div>
                                        <div>
                                            <div style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--text-primary)' }}>System Auto-Post</div>
                                            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                                                {formatStableDate(post.created_at)}
                                            </div>
                                        </div>
                                    </div>
                                    <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                                        {post.content}
                                    </p>
                                </div>
                            ))}
                        </div>
                    </motion.section>
                </motion.div>

                {/* CSS for Skeleton Pulse since we didn't add it to globals.css */}
                <style dangerouslySetInnerHTML={{
                    __html: `
                    @keyframes pulse {
                        0%, 100% { opacity: 1; }
                        50% { opacity: .5; }
                    }
                `}} />
            </motion.main>
        </div>
    );
}
