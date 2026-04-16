"use client";
import Link from "next/link";
import { useState, useEffect } from "react";
import BrandLogo from "@/components/BrandLogo";

export default function Navbar() {
    const [scrolled, setScrolled] = useState(false);

    useEffect(() => {
        const handleScroll = () => setScrolled(window.scrollY > 20);
        window.addEventListener("scroll", handleScroll);
        return () => window.removeEventListener("scroll", handleScroll);
    }, []);

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
            <div style={{ maxWidth: 1200, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <BrandLogo size="sm" />
                <div style={{ display: "flex", gap: "2rem", alignItems: "center" }}>
                    <Link href="#features" style={{ fontSize: "0.95rem", color: "var(--text-secondary)" }}>Features</Link>
                    <Link href="#incoscore" style={{ fontSize: "0.95rem", color: "var(--text-secondary)" }}>InCoScore</Link>
                    <Link href="/login" style={{ fontSize: "0.95rem", fontWeight: 500, color: "var(--text-primary)" }}>Sign In</Link>
                    <Link href="/register" className="btn-primary">Get Early Access</Link>
                </div>
            </div>
        </nav>
    );
}
