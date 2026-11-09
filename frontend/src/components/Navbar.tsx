"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import BrandLogo from "@/components/BrandLogo";
import { clearAccessToken, getAuthStateEventName, hasAuthSession } from "@/lib/auth-session";
import styles from "./Navbar.module.css";

export default function Navbar() {
    const [scrolled, setScrolled] = useState(false);
    const [isAuthenticated, setIsAuthenticated] = useState(false);
    const [hasMounted, setHasMounted] = useState(false);
    const router = useRouter();

    // Initialize auth state on mount to prevent hydration mismatch
    // This is intentional - we need to sync client state after mount
    /* eslint-disable */
    useEffect(() => {
        setHasMounted(true);
        setIsAuthenticated(hasAuthSession());
    }, []);
    /* eslint-enable */

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
            className={styles.nav}
            data-scrolled={scrolled}
        >
            <div className={styles.inner}>
                <div className={styles.brand}>
                    <BrandLogo size="lg" />
                </div>
                <div className={styles.links} suppressHydrationWarning>
                    <Link className={styles.discoveryLink} href="#features">Features</Link>
                    <Link className={styles.discoveryLink} href="#incoscore">InCoScore</Link>
                    {!hasMounted ? (
                        // Show unauthenticated state during SSR to match server render
                        <>
                            <Link className={styles.authLink} href="/login">Sign In</Link>
                            <Link href="/register" className={`${styles.earlyAccess} btn-primary`}>Get Early Access</Link>
                        </>
                    ) : isAuthenticated ? (
                        <>
                            <Link className={`${styles.authLink} ${styles.profileLink}`} href="/profile">
                                Profile
                            </Link>
                            <button
                                type="button"
                                className={`${styles.logout} btn-secondary`}
                                onClick={handleLogout}
                            >
                                Logout
                            </button>
                        </>
                    ) : (
                        <>
                            <Link className={styles.authLink} href="/login">Sign In</Link>
                            <Link href="/register" className={`${styles.earlyAccess} btn-primary`}>Get Early Access</Link>
                        </>
                    )}
                </div>
            </div>
        </nav>
    );
}
