"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import BrandLogo from "@/components/BrandLogo";
import { clearAccessToken, getAuthStateEventName, hasAuthSession } from "@/lib/auth-session";

export default function Navbar() {
    const [scrolled, setScrolled] = useState(false);
    const [isAuthenticated, setIsAuthenticated] = useState(() => hasAuthSession());
    const router = useRouter();

    useEffect(() => {
        const handleScroll = () => setScrolled(window.scrollY > 20);
        window.addEventListener("scroll", handleScroll);
        return () => window.removeEventListener("scroll", handleScroll);
    }, []);

    const syncAuthState = useCallback(() => {
        setIsAuthenticated(hasAuthSession());
    }, []);

    useEffect(() => {
        const authStateEventName = getAuthStateEventName();
        window.addEventListener("focus", syncAuthState);
        window.addEventListener("storage", syncAuthState);
        window.addEventListener(authStateEventName, syncAuthState);
        return () => {
            window.removeEventListener("focus", syncAuthState);
            window.removeEventListener("storage", syncAuthState);
            window.removeEventListener(authStateEventName, syncAuthState);
        };
    }, [syncAuthState]);

    const handleLogout = () => {
        clearAccessToken();
        setIsAuthenticated(false);
        router.push("/");
    };

    return (
        <nav
            style={{
                position: "fixed",
                top: 0,
                left: 0,
                right: 0,
                zIndex: 50,
                transition: "all 0.3s ease",
                background: scrolled ? "rgba(10, 10, 11, 0.8)" : "transparent",
                backdropFilter: scrolled ? "blur(12px)" : "none",
                borderBottom: scrolled ? "1px solid var(--border-subtle)" : "1px solid transparent",
                padding: scrolled ? "1rem 2rem" : "1.5rem 2rem",
            }}
        >
            <div style={{ maxWidth: 1200, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem" }}>
                <BrandLogo size="sm" />
                <div style={{ display: "flex", gap: "2rem", alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
                    <Link href="#features" style={{ fontSize: "0.95rem", color: "var(--text-secondary)" }}>Features</Link>
                    <Link href="#incoscore" style={{ fontSize: "0.95rem", color: "var(--text-secondary)" }}>InCoScore</Link>
                    {isAuthenticated ? (
                        <>
                            <Link href="/profile" style={{ fontSize: "0.95rem", fontWeight: 700, color: "var(--text-primary)" }}>
                                Profile
                            </Link>
                            <button
                                type="button"
                                className="btn-secondary"
                                onClick={handleLogout}
                                style={{ padding: "0.75rem 1.15rem" }}
                            >
                                Logout
                            </button>
                        </>
                    ) : (
                        <>
                            <Link href="/login" style={{ fontSize: "0.95rem", fontWeight: 500, color: "var(--text-primary)" }}>Sign In</Link>
                            <Link href="/register" className="btn-primary">Get Early Access</Link>
                        </>
                    )}
                </div>
            </div>
        </nav>
    );
}
