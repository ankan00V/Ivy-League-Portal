"use client";
import Sidebar from "@/components/Sidebar";
import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { MessageSquare, Heart, Share2, Paperclip, Trophy, Hash } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";

interface SocialPost {
    id: string;
    domain: string;
    content: string;
    likes_count: number;
    created_at: string;
}

interface SocialComment {
    id: string;
    post_id: string;
    user_id: string;
    content: string;
    created_at: string;
}

export default function SocialPage() {
    const [activeGroup, setActiveGroup] = useState("Global");
    const groups = ["Global", "AI Researchers", "Ivy League Law", "MedTech Innovators"];
    const [newPostContent, setNewPostContent] = useState("");
    const [posting, setPosting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const [posts, setPosts] = useState<SocialPost[]>([]);
    const [commentsByPost, setCommentsByPost] = useState<Record<string, SocialComment[]>>({});
    const [commentDraftByPost, setCommentDraftByPost] = useState<Record<string, string>>({});
    const [commentPanelOpen, setCommentPanelOpen] = useState<Record<string, boolean>>({});
    const [commentLoadingByPost, setCommentLoadingByPost] = useState<Record<string, boolean>>({});

    const mapGroupToDomain = (group: string) => {
        if (group === "AI Researchers") return "AI and Machine Learning";
        if (group === "Ivy League Law") return "Law";
        if (group === "MedTech Innovators") return "Biomedical and Healthcare";
        return "General";
    };

    useEffect(() => {
        let cancelled = false;
        const fetchPosts = async () => {
            try {
                const token = getAccessToken();
                const query = activeGroup === "Global" ? "" : `?domain=${encodeURIComponent(mapGroupToDomain(activeGroup))}`;
                const res = await fetch(apiUrl(`/api/v1/social/posts${query}`), {
                    headers: token ? { Authorization: `Bearer ${token}` } : {},
                });
                if (res.ok) {
                    const data = await res.json();
                    if (!cancelled) {
                        setPosts(Array.isArray(data) ? data : []);
                    }
                }
            } catch (err) {
                const message = err instanceof Error ? err.message : "unknown error";
                console.warn(`[Social] Fetch posts failed: ${message}`);
            }
        };

        void fetchPosts();
        const interval = window.setInterval(() => {
            void fetchPosts();
        }, 15000);
        const handleRefresh = () => {
            void fetchPosts();
        };
        window.addEventListener("focus", handleRefresh);
        document.addEventListener("visibilitychange", handleRefresh);

        return () => {
            cancelled = true;
            window.clearInterval(interval);
            window.removeEventListener("focus", handleRefresh);
            document.removeEventListener("visibilitychange", handleRefresh);
        };
    }, [activeGroup]);

    const handleCreatePost = async () => {
        if (!newPostContent.trim()) {
            return;
        }
        const token = getAccessToken();
        if (!token) {
            setError("Sign in to create a post.");
            return;
        }

        setPosting(true);
        setError(null);
        try {
            const res = await fetch(apiUrl("/api/v1/social/posts"), {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({
                    domain: mapGroupToDomain(activeGroup),
                    content: newPostContent.trim(),
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || "Could not create post.");
            }
            setPosts((prev) => [data, ...prev]);
            setNewPostContent("");
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : "Could not create post.");
        } finally {
            setPosting(false);
        }
    };

    const handleLike = async (id: string) => {
        const token = getAccessToken();
        if (!token) {
            setError("Sign in to like posts.");
            return;
        }

        try {
            const res = await fetch(apiUrl(`/api/v1/social/posts/${id}/like`), {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${token}`,
                },
            });
            if (!res.ok) {
                return;
            }
            setPosts((prev) =>
                prev.map((post) =>
                    post.id === id ? { ...post, likes_count: (post.likes_count || 0) + 1 } : post
                )
            );
        } catch (err) {
            const message = err instanceof Error ? err.message : "unknown error";
            console.warn(`[Social] Like failed: ${message}`);
        }
    };

    const fetchCommentsForPost = async (postId: string) => {
        setCommentLoadingByPost((prev) => ({ ...prev, [postId]: true }));
        try {
            const token = getAccessToken();
            const res = await fetch(apiUrl(`/api/v1/social/posts/${postId}/comments`), {
                headers: token ? { Authorization: `Bearer ${token}` } : {},
            });
            const data = await res.json().catch(() => []);
            if (res.ok && Array.isArray(data)) {
                setCommentsByPost((prev) => ({ ...prev, [postId]: data }));
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : "unknown error";
            console.warn(`[Social] Fetch comments failed: ${message}`);
        } finally {
            setCommentLoadingByPost((prev) => ({ ...prev, [postId]: false }));
        }
    };

    const toggleComments = (postId: string) => {
        const isOpen = !!commentPanelOpen[postId];
        if (!isOpen && !commentsByPost[postId]) {
            void fetchCommentsForPost(postId);
        }
        setCommentPanelOpen((prev) => ({ ...prev, [postId]: !isOpen }));
    };

    const handleCreateComment = async (postId: string) => {
        const token = getAccessToken();
        if (!token) {
            setError("Sign in to add comments.");
            return;
        }

        const commentText = (commentDraftByPost[postId] || "").trim();
        if (!commentText) {
            return;
        }

        try {
            const res = await fetch(apiUrl(`/api/v1/social/posts/${postId}/comments`), {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({ content: commentText }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || "Could not add comment.");
            }

            setCommentsByPost((prev) => {
                const current = prev[postId] || [];
                return { ...prev, [postId]: [data, ...current] };
            });
            setCommentDraftByPost((prev) => ({ ...prev, [postId]: "" }));
            setCommentPanelOpen((prev) => ({ ...prev, [postId]: true }));
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : "Could not add comment.");
        }
    };

    return (
        <div className="layout-container">
            <Sidebar />
            <main className="main-content">
                <header style={{ marginBottom: '3rem' }}>
                    <h1 style={{ fontSize: '2.5rem', marginBottom: '0.5rem' }}>Academic Social Network</h1>
                    <p style={{ color: 'var(--text-secondary)' }}>Connect with peers, join domain-specific groups, and collaborate.</p>
                </header>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: '2rem' }}>
                    {/* Feed */}
                    <div>
                        {/* Create Post */}
                        <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '2rem' }}>
                            {error && (
                                <div style={{ marginBottom: "0.75rem", color: "#ef4444", fontWeight: 600 }}>{error}</div>
                            )}
                            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                                <div style={{ width: 40, height: 40, borderRadius: '50%', background: 'var(--brand-primary)', flexShrink: 0 }} />
                                <textarea
                                    className="input-base"
                                    placeholder="Share a research update, ask for feedback, or post a milestone..."
                                    style={{ minHeight: '80px', resize: 'none' }}
                                    value={newPostContent}
                                    onChange={(e) => setNewPostContent(e.target.value)}
                                />
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div style={{ display: 'flex', gap: '1rem' }}>
                                    <button style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                        <Paperclip size={16} /> Attach Paper
                                    </button>
                                    <button style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                        <Trophy size={16} /> Add Achievement
                                    </button>
                                </div>
                                <button
                                    className="btn-primary"
                                    style={{ padding: '0.5rem 1.5rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}
                                    disabled={posting}
                                    onClick={() => void handleCreatePost()}
                                >
                                    <MessageSquare size={16} /> {posting ? "Posting..." : "Post"}
                                </button>
                            </div>
                        </div>

                        {/* Posts List */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                            <AnimatePresence mode="popLayout">
                                {posts.length > 0 ? posts.map((post, idx) => (
                                    <motion.div
                                        key={post.id || idx}
                                        layout
                                        initial={{ opacity: 0, scale: 0.95, y: 40 }}
                                        animate={{ opacity: 1, scale: 1, y: 0 }}
                                        exit={{ opacity: 0, scale: 0.95, y: -20 }}
                                        transition={{ type: "spring", stiffness: 350, damping: 25, delay: idx * 0.1 }}
                                        className="glass-panel"
                                        style={{ padding: '1.5rem' }}
                                    >
                                        <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                                            <div style={{ width: 44, height: 44, borderRadius: '50%', background: 'linear-gradient(135deg, var(--brand-primary), var(--accent-purple))', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold' }}>
                                                V
                                            </div>
                                            <div>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                    <h4 style={{ fontSize: '1.05rem', fontWeight: 600 }}>System / Member</h4>
                                                    <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>• {new Date(post.created_at).toLocaleDateString()}</span>
                                                </div>
                                                <div style={{ fontSize: '0.85rem', color: 'var(--accent-cyan)' }}>{post.domain}</div>
                                            </div>
                                        </div>
                                        <p style={{ fontSize: '0.95rem', lineHeight: 1.6, marginBottom: '1.5rem' }}>{post.content}</p>
                                        <div style={{ display: 'flex', gap: '1.5rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '1rem' }}>
                                            <button
                                                style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.4rem', transition: 'color 0.2s' }}
                                                onClick={() => void handleLike(post.id)}
                                                onMouseEnter={(e) => e.currentTarget.style.color = 'var(--accent-pink)'}
                                                onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-secondary)'}
                                            >
                                                <Heart size={16} /> {post.likes_count || 0} Likes
                                            </button>
                                            <button
                                                style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.4rem', transition: 'color 0.2s' }}
                                                onClick={() => toggleComments(post.id)}
                                                onMouseEnter={(e) => e.currentTarget.style.color = 'var(--brand-primary)'}
                                                onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-secondary)'}
                                            >
                                                <MessageSquare size={16} /> {(commentsByPost[post.id] || []).length} Comments
                                            </button>
                                            <button style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.4rem', transition: 'color 0.2s' }} onMouseEnter={(e) => e.currentTarget.style.color = 'var(--brand-primary)'} onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-secondary)'}>
                                                <Share2 size={16} /> Share
                                            </button>
                                        </div>
                                        {commentPanelOpen[post.id] && (
                                            <div style={{ marginTop: "1rem", borderTop: "1px solid var(--border-subtle)", paddingTop: "0.9rem" }}>
                                                {commentLoadingByPost[post.id] && (
                                                    <div style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginBottom: "0.6rem" }}>
                                                        Loading comments...
                                                    </div>
                                                )}
                                                {!commentLoadingByPost[post.id] && (commentsByPost[post.id] || []).length === 0 && (
                                                    <div style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginBottom: "0.6rem" }}>
                                                        No comments yet.
                                                    </div>
                                                )}
                                                <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", marginBottom: "0.7rem" }}>
                                                    {(commentsByPost[post.id] || []).map((comment) => (
                                                        <div key={comment.id} style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.55rem 0.7rem" }}>
                                                            <div style={{ fontSize: "0.92rem" }}>{comment.content}</div>
                                                            <div style={{ marginTop: "0.25rem", fontSize: "0.75rem", color: "var(--text-muted)" }}>
                                                                {new Date(comment.created_at).toLocaleString()}
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                                <div style={{ display: "flex", gap: "0.5rem" }}>
                                                    <input
                                                        className="input-base"
                                                        style={{ padding: "0.6rem 0.75rem", fontSize: "0.9rem" }}
                                                        placeholder="Add a comment..."
                                                        value={commentDraftByPost[post.id] || ""}
                                                        onChange={(event) =>
                                                            setCommentDraftByPost((prev) => ({
                                                                ...prev,
                                                                [post.id]: event.target.value,
                                                            }))
                                                        }
                                                    />
                                                    <button
                                                        className="btn-primary"
                                                        style={{ padding: "0.6rem 0.9rem", fontSize: "0.85rem" }}
                                                        onClick={() => void handleCreateComment(post.id)}
                                                    >
                                                        Post
                                                    </button>
                                                </div>
                                            </div>
                                        )}
                                    </motion.div>
                                )) : (
                                    <motion.div
                                        initial={{ opacity: 0 }}
                                        animate={{ opacity: 1 }}
                                        style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}
                                    >
                                        No posts available yet. Wait for the scraper or add one!
                                    </motion.div>
                                )}
                            </AnimatePresence>
                        </div>
                    </div>

                    {/* Right Sidebar */}
                    <div style={{ position: 'sticky', top: '2rem', height: 'fit-content' }}>
                        <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '1.5rem' }}>
                            <h3 style={{ fontSize: '1.1rem', marginBottom: '1rem' }}>Your Groups</h3>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                {groups.map(group => (
                                    <button
                                        key={group}
                                        style={{
                                            textAlign: 'left',
                                            padding: '0.75rem',
                                            borderRadius: 'var(--radius-sm)',
                                            background: activeGroup === group ? 'var(--bg-surface-hover)' : 'transparent',
                                            color: activeGroup === group ? 'white' : 'var(--text-secondary)',
                                            fontWeight: activeGroup === group ? 500 : 400,
                                            borderLeft: activeGroup === group ? '2px solid var(--brand-primary)' : '2px solid transparent',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.5rem',
                                            transition: 'all 0.2s ease'
                                        }}
                                        onClick={() => setActiveGroup(group)}
                                    >
                                        <Hash size={14} style={{ color: activeGroup === group ? 'var(--brand-primary)' : 'inherit' }} /> {group}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div className="glass-panel" style={{ padding: '1.5rem' }}>
                            <h3 style={{ fontSize: '1.1rem', marginBottom: '1rem' }}>Trending Topics</h3>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                                {['#NeurIPS2026', '#YCombinator', '#HarvardHack', '#QuantumComputing'].map(tag => (
                                    <span key={tag} style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: '100px', color: 'var(--accent-cyan)', cursor: 'pointer' }}>
                                        {tag}
                                    </span>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    );
}
