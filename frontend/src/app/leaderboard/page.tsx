"use client";
import Sidebar from "@/components/Sidebar";
import { LeaderboardRowsSkeleton } from "@/components/LoadingSkeletons";
import React, { useEffect, useState } from "react";
import { Crown, Medal, Trophy } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";

interface LeaderboardEntry {
    rank: number;
    user_id: string;
    full_name?: string | null;
    handle: string;
    incoscore: number;
}

export default function LeaderboardPage() {
    const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [searchQuery, setSearchQuery] = useState("");
    const [searchResults, setSearchResults] = useState<LeaderboardEntry[]>([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const [searchError, setSearchError] = useState<string | null>(null);

    useEffect(() => {
        const fetchLeaderboard = async () => {
            const token = getAccessToken();
            if (!token) {
                setError("Sign in to view the leaderboard.");
                setLoading(false);
                return;
            }
            try {
                const res = await fetch(apiUrl("/api/v1/users/leaderboard?limit=10"), {
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

    useEffect(() => {
        const token = getAccessToken();
        const query = searchQuery.trim();

        if (!query) {
            setSearchResults([]);
            setSearchError(null);
            setSearchLoading(false);
            return;
        }

        if (!token) {
            setSearchResults([]);
            setSearchError("Sign in to search your rank.");
            return;
        }

        const controller = new AbortController();
        const timer = window.setTimeout(async () => {
            setSearchLoading(true);
            setSearchError(null);
            try {
                const res = await fetch(apiUrl(`/api/v1/users/leaderboard?limit=10&search=${encodeURIComponent(query)}`), {
                    headers: { Authorization: `Bearer ${token}` },
                    signal: controller.signal,
                });
                const data = await res.json().catch(() => []);
                if (!res.ok) {
                    throw new Error(data?.detail || "Could not search leaderboard.");
                }
                setSearchResults(Array.isArray(data) ? data : []);
            } catch (err: unknown) {
                if (err instanceof DOMException && err.name === "AbortError") {
                    return;
                }
                setSearchResults([]);
                setSearchError(err instanceof Error ? err.message : "Could not search leaderboard.");
            } finally {
                setSearchLoading(false);
            }
        }, 250);

        return () => {
            controller.abort();
            window.clearTimeout(timer);
        };
    }, [searchQuery]);

    const rankBadge = (rank: number) => {
        if (rank === 1) return <Crown size={16} />;
        if (rank === 2) return <Trophy size={16} />;
        if (rank === 3) return <Medal size={16} />;
        return <span style={{ fontSize: "0.85rem", fontWeight: 700 }}>#{rank}</span>;
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

                <section className="card-panel" style={{ marginBottom: "1rem" }}>
                    <div style={{ display: "grid", gap: "0.5rem" }}>
                        <label htmlFor="leaderboard-search" style={{ fontWeight: 700 }}>
                            Find your rank by name or username
                        </label>
                        <input
                            id="leaderboard-search"
                            type="search"
                            value={searchQuery}
                            onChange={(event) => setSearchQuery(event.target.value)}
                            placeholder="Search name or @handle"
                            style={{
                                border: "2px solid var(--border-subtle)",
                                background: "var(--bg-surface)",
                                color: "var(--text-primary)",
                                padding: "0.7rem 0.85rem",
                                borderRadius: "10px",
                                fontSize: "0.95rem",
                            }}
                        />
                    </div>

                    {searchQuery.trim() && (
                        <div style={{ marginTop: "1rem" }}>
                            {searchLoading && <p style={{ margin: 0 }}>Searching ranks...</p>}
                            {!searchLoading && searchError && <p style={{ margin: 0 }}>{searchError}</p>}
                            {!searchLoading && !searchError && searchResults.length === 0 && (
                                <p style={{ margin: 0 }}>No matching student found.</p>
                            )}
                            {!searchLoading && !searchError && searchResults.length > 0 && (
                                <div style={{ overflowX: "auto" }}>
                                    <table style={{ width: "100%", borderCollapse: "collapse" }}>
                                        <thead>
                                            <tr style={{ borderBottom: "2px solid var(--border-subtle)" }}>
                                                <th style={{ textAlign: "left", padding: "0.75rem 0.35rem" }}>Rank</th>
                                                <th style={{ textAlign: "left", padding: "0.75rem 0.35rem" }}>Student</th>
                                                <th style={{ textAlign: "left", padding: "0.75rem 0.35rem" }}>Handle</th>
                                                <th style={{ textAlign: "left", padding: "0.75rem 0.35rem" }}>InCoScore</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {searchResults.map((entry) => (
                                                <tr key={`search-${entry.user_id}`} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                                                    <td style={{ padding: "0.75rem 0.35rem", fontWeight: 700 }}>
                                                        #{entry.rank}
                                                    </td>
                                                    <td style={{ padding: "0.75rem 0.35rem", fontWeight: 600 }}>
                                                        {entry.full_name || "Student"}
                                                    </td>
                                                    <td style={{ padding: "0.75rem 0.35rem", color: "var(--text-secondary)" }}>
                                                        @{entry.handle}
                                                    </td>
                                                    <td style={{ padding: "0.75rem 0.35rem" }}>
                                                        <span className="btn-secondary" style={{ padding: "0.25rem 0.65rem" }}>
                                                            {entry.incoscore.toFixed(2)}
                                                        </span>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </div>
                    )}
                </section>

                <section className="card-panel" style={{ padding: 0, overflow: "hidden" }}>
                    <div style={{ padding: "1rem 1.25rem", borderBottom: "2px solid var(--border-subtle)", fontWeight: 700 }}>
                        Top 10 Students
                    </div>
                    <div style={{ overflowX: "auto" }}>
                        <table style={{ width: "100%", borderCollapse: "collapse" }}>
                            <thead>
                                <tr style={{ borderBottom: "2px solid var(--border-subtle)" }}>
                                    <th style={{ textAlign: "left", padding: "0.9rem 1.25rem" }}>Rank</th>
                                    <th style={{ textAlign: "left", padding: "0.9rem 1.25rem" }}>Student</th>
                                    <th style={{ textAlign: "left", padding: "0.9rem 1.25rem" }}>Handle</th>
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
                                    entries.map((entry) => (
                                        <tr key={entry.user_id} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                                            <td style={{ padding: "0.9rem 1.25rem", fontWeight: 700 }}>
                                                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
                                                    {rankBadge(entry.rank)}
                                                </span>
                                            </td>
                                            <td style={{ padding: "0.9rem 1.25rem", fontWeight: 600 }}>
                                                {entry.full_name || "Student"}
                                            </td>
                                            <td style={{ padding: "0.9rem 1.25rem", color: "var(--text-secondary)" }}>
                                                @{entry.handle}
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
