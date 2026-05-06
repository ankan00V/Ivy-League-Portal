"use client";
import Sidebar from "@/components/Sidebar";
import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Copyleft as Clock, Bookmark, Play, CheckCircle, Activity } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";

interface ApplicationRow {
    id: string;
    opportunity_title: string;
    opportunity_domain: string;
    opportunity_type: string;
    status: string;
    automation_mode?: string | null;
    created_at: string;
}

export default function ApplicationsPage() {
    const [applications, setApplications] = useState<ApplicationRow[]>([]);

    useEffect(() => {
        let cancelled = false;
        const fetchApps = async () => {
            try {
                const token = getAccessToken();
                if (!token) {
                    if (!cancelled) {
                        setApplications([]);
                    }
                    return;
                }
                const res = await fetch(
                    apiUrl("/api/v1/applications/"),
                    createAuthenticatedFetchInit({}, token),
                );
                if (res.ok) {
                    const data = await res.json();
                    if (!cancelled) {
                        setApplications(Array.isArray(data) ? data : []);
                    }
                }
            } catch (err) {
                const message = err instanceof Error ? err.message : "unknown error";
                console.warn(`[Applications] Fetch failed: ${message}`);
            }
        };

        void fetchApps();
        const interval = window.setInterval(() => {
            void fetchApps();
        }, 15000);
        const handleRefresh = () => {
            void fetchApps();
        };
        window.addEventListener("focus", handleRefresh);
        document.addEventListener("visibilitychange", handleRefresh);

        return () => {
            cancelled = true;
            window.clearInterval(interval);
            window.removeEventListener("focus", handleRefresh);
            document.removeEventListener("visibilitychange", handleRefresh);
        };
    }, []);

    const getStatusStyle = (status: string) => {
        if (status === "In Progress") return { bg: "var(--brand-primary)", color: "#000000" };
        if (status === "Applied") return { bg: "var(--brand-accent)", color: "#000000" };
        if (status === "Registered") return { bg: "var(--accent-purple)", color: "#000000" };
        return { bg: "var(--text-primary)", color: "var(--bg-base)" };
    };

    return (
        <div style={{ minHeight: '100vh', display: 'flex', background: 'var(--bg-base)', position: 'relative' }}>

            <Sidebar />
            <main className="main-content">
                <header style={{ marginBottom: '3rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
                    <div>
                        <h1 style={{ fontSize: '3rem', marginBottom: '0.75rem', fontWeight: 400, fontFamily: 'var(--font-serif)', color: 'var(--text-primary)', lineHeight: 1.1 }}>
                            <span style={{ background: 'var(--brand-primary)', padding: '0.2rem 0.5rem', border: '2px solid var(--border-subtle)', boxShadow: 'var(--shadow-sm)', display: 'inline-block', transform: 'rotate(-2deg)' }}>Applications</span> Hub
                        </h1>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '1.25rem', maxWidth: '600px', fontWeight: 600 }}>
                            Track your real-time application status across hackathons, quizzes, and job portals.
                        </p>
                    </div>
                </header>

                <div className="card-panel" style={{ padding: '0' }}>
                    <div style={{ padding: '1.5rem', borderBottom: '2px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Activity size={18} className="animate-pulse" style={{ color: 'var(--text-primary)' }} />
                        <span style={{ fontWeight: 800, color: 'var(--text-primary)', fontSize: '0.95rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Live Syncing Enabled</span>
                    </div>

                    <div style={{ overflowX: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                            <thead>
                                <tr style={{ background: 'var(--bg-surface)', borderBottom: '2px solid var(--border-subtle)' }}>
                                    <th style={{ padding: '1.25rem 1.5rem', fontWeight: 800, color: 'var(--text-primary)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Opportunity</th>
                                    <th style={{ padding: '1.25rem 1.5rem', fontWeight: 800, color: 'var(--text-primary)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Organization</th>
                                    <th style={{ padding: '1.25rem 1.5rem', fontWeight: 800, color: 'var(--text-primary)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Type</th>
                                    <th style={{ padding: '1.25rem 1.5rem', fontWeight: 800, color: 'var(--text-primary)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Automation</th>
                                    <th style={{ padding: '1.25rem 1.5rem', fontWeight: 800, color: 'var(--text-primary)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Last Updated</th>
                                    <th style={{ padding: '1.25rem 1.5rem', fontWeight: 800, color: 'var(--text-primary)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                <AnimatePresence mode="popLayout">
                                    {applications.map((app, idx) => (
                                        <motion.tr
                                            key={app.id}
                                            initial={{ opacity: 0, x: -20 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            exit={{ opacity: 0, x: 20 }}
                                            transition={{ type: "spring", stiffness: 400, damping: 25, delay: idx * 0.05 }}
                                            style={{ borderBottom: '2px solid var(--border-subtle)' }}
                                            whileHover={{ backgroundColor: 'var(--bg-surface-hover)', transition: { duration: 0 } }}
                                        >
                                            <td style={{ padding: '1.25rem 1.5rem', fontWeight: 700, color: 'var(--text-primary)' }}>{app.opportunity_title}</td>
                                            <td style={{ padding: '1.25rem 1.5rem', color: 'var(--text-primary)', fontWeight: 500 }}>{app.opportunity_domain}</td>
                                            <td style={{ padding: '1.25rem 1.5rem' }}>
                                                <span style={{ padding: '0.25rem 0.6rem', background: 'var(--text-primary)', border: '2px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', fontWeight: 700, color: 'var(--bg-base)' }}>
                                                    {app.opportunity_type}
                                                </span>
                                            </td>
                                            <td style={{ padding: '1.25rem 1.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
                                                {app.automation_mode || "N/A"}
                                            </td>
                                            <td style={{ padding: '1.25rem 1.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>{new Date(app.created_at).toLocaleDateString()}</td>
                                            <td style={{ padding: '1.25rem 1.5rem' }}>
                                                <span style={{
                                                    padding: '0.35rem 0.75rem',
                                                    borderRadius: 'var(--radius-sm)',
                                                    fontSize: '0.8rem',
                                                    fontWeight: 800,
                                                    background: getStatusStyle(app.status).bg,
                                                    color: getStatusStyle(app.status).color,
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                    gap: '0.35rem',
                                                    border: '2px solid var(--border-subtle)',
                                                    boxShadow: 'var(--shadow-sm)'
                                                }}>
                                                    {app.status === 'In Progress' && <Play size={12} />}
                                                    {app.status === 'Applied' && <CheckCircle size={12} />}
                                                    {app.status === 'Registered' && <Bookmark size={12} />}
                                                    {app.status}
                                                </span>
                                            </td>
                                        </motion.tr>
                                    ))}
                                </AnimatePresence>
                            </tbody>
                        </table>
                        {applications.length === 0 && (
                            <motion.div
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                                style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}
                            >
                                <Clock size={32} style={{ opacity: 0.5 }} />
                                No active applications synced yet.
                            </motion.div>
                        )}
                    </div>
                </div>

                {/* Re-use pulse animation */}
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
