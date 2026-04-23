"use client";
import Sidebar from "@/components/Sidebar";
import { LeaderboardRowsSkeleton } from "@/components/LoadingSkeletons";
import React, { useEffect, useState } from "react";
import { Crown, Medal, Trophy } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";

interface LeaderboardEntry {
    user_id: string;
    full_name?: string | null;
    email: string;
    incoscore: number;
}

export default function LeaderboardPage() {
    const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchLeaderboard = async () => {
            const token = getAccessToken();
            if (!token) {
                setError("Sign in to view the leaderboard.");
                setLoading(false);
                return;
            }
            try {
                const res = await fetch(apiUrl("/api/v1/users/leaderboard?limit=50"), {
                    headers: { Authorization: `Bearer ${token}` },
                });
                const data = await res.json().catch(() => []);
                if (!res.ok) {
                    throw new Error(data?.detail || "Could not load leaderboard.");
                }
                setEntries(Array.isArray(data) ? data : []);
            } catch (err: unknown) {
                setError(err instanceof Error ? err.message : "Could not load leaderboard.");
            } finally {
                setLoading(false);
            }
        };

        void fetchLeaderboard();
    }, []);

    const rankBadge = (index: number) => {
        if (index === 0) return <Crown size={16} />;
        if (index === 1) return <Trophy size={16} />;
        if (index === 2) return <Medal size={16} />;
        return <span style={{ fontSize: "0.85rem", fontWeight: 700 }}>#{index + 1}</span>;
    };

    return (
        <div className="layout-container">
            <Sidebar />
            <main className="main-content">
                <header style={{ marginBottom: "2rem" }}>
                    <h1 style={{ fontSize: "2.75rem", marginBottom: "0.5rem" }}>InCoScore Leaderboard</h1>
                    <p style={{ color: "var(--text-secondary)", fontSize: "1.05rem" }}>
                        Global competency ranking generated from skills, achievements, and academic profile strength.
                    </p>
                </header>

                {error && (
                    <div className="card-panel" style={{ marginBottom: "1rem", background: "var(--bg-surface-hover)" }}>
                        {error}
                    </div>
                )}

                <section className="card-panel" style={{ padding: 0, overflow: "hidden" }}>
                    <div style={{ padding: "1rem 1.25rem", borderBottom: "2px solid var(--border-subtle)", fontWeight: 700 }}>
                        Top Students
                    </div>
                    <div style={{ overflowX: "auto" }}>
                        <table style={{ width: "100%", borderCollapse: "collapse" }}>
                            <thead>
                                <tr style={{ borderBottom: "2px solid var(--border-subtle)" }}>
                                    <th style={{ textAlign: "left", padding: "0.9rem 1.25rem" }}>Rank</th>
                                    <th style={{ textAlign: "left", padding: "0.9rem 1.25rem" }}>Student</th>
                                    <th style={{ textAlign: "left", padding: "0.9rem 1.25rem" }}>Email</th>
                                    <th style={{ textAlign: "left", padding: "0.9rem 1.25rem" }}>InCoScore</th>
                                </tr>
                            </thead>
                            <tbody>
                                {loading && (
                                    <LeaderboardRowsSkeleton rows={8} />
                                )}
                                {!loading && entries.length === 0 && (
                                    <tr>
                                        <td colSpan={4} style={{ padding: "1.25rem" }}>
                                            No leaderboard data yet.
                                        </td>
                                    </tr>
                                )}
                                {!loading &&
                                    entries.map((entry, index) => (
                                        <tr key={entry.user_id} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                                            <td style={{ padding: "0.9rem 1.25rem", fontWeight: 700 }}>
                                                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
                                                    {rankBadge(index)}
                                                </span>
                                            </td>
                                            <td style={{ padding: "0.9rem 1.25rem", fontWeight: 600 }}>
                                                {entry.full_name || "Student"}
                                            </td>
                                            <td style={{ padding: "0.9rem 1.25rem", color: "var(--text-secondary)" }}>
                                                {entry.email}
                                            </td>
                                            <td style={{ padding: "0.9rem 1.25rem" }}>
                                                <span className="btn-secondary" style={{ padding: "0.3rem 0.7rem" }}>
                                                    {entry.incoscore.toFixed(2)}
                                                </span>
                                            </td>
                                        </tr>
                                    ))}
                            </tbody>
                        </table>
                    </div>
                </section>
            </main>
        </div>
    );
}
