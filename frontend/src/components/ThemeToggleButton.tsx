"use client";

import { useMemo, useSyncExternalStore } from "react";
import { usePathname } from "next/navigation";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/context/ThemeContext";

const SIDEBAR_ROUTES = [
    "/dashboard",
    "/opportunities",
    "/internships-jobs",
    "/applications",
    "/social",
    "/leaderboard",
    "/experiments",
];

export default function ThemeToggleButton() {
    const pathname = usePathname();
    const { theme, toggleTheme } = useTheme();
    const isHydrated = useSyncExternalStore(
        () => () => { },
        () => true,
        () => false
    );

    const hasSidebar = useMemo(
        () =>
            SIDEBAR_ROUTES.some(
                (route) => pathname === route || pathname.startsWith(`${route}/`)
            ),
        [pathname]
    );

    if (hasSidebar || pathname === "/") {
        return null;
    }

    return (
        <button
            type="button"
            onClick={toggleTheme}
            aria-label={
                !isHydrated
                    ? "Toggle theme"
                    : theme === "dark"
                        ? "Switch to light mode"
                        : "Switch to dark mode"
            }
            title={
                !isHydrated
                    ? "Toggle theme"
                    : theme === "dark"
                        ? "Switch to light mode"
                        : "Switch to dark mode"
            }
            style={{
                position: "fixed",
                top: "1rem",
                right: "1rem",
                zIndex: 70,
                display: "inline-flex",
                alignItems: "center",
                gap: "0.5rem",
                padding: "0.6rem 0.9rem",
                background: "var(--bg-surface)",
                color: "var(--text-primary)",
                border: "2px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
                boxShadow: "var(--shadow-sm)",
                fontWeight: 700,
                fontSize: "0.85rem",
                lineHeight: 1,
                transition: "var(--bounce-transition)",
            }}
            onMouseEnter={(e) => {
                e.currentTarget.style.transform = "translate(-2px, -2px)";
                e.currentTarget.style.boxShadow = "var(--shadow-md)";
                e.currentTarget.style.background = "var(--bg-surface-hover)";
            }}
            onMouseLeave={(e) => {
                e.currentTarget.style.transform = "none";
                e.currentTarget.style.boxShadow = "var(--shadow-sm)";
                e.currentTarget.style.background = "var(--bg-surface)";
            }}
            onMouseDown={(e) => {
                e.currentTarget.style.transform = "translate(2px, 2px)";
                e.currentTarget.style.boxShadow = "none";
            }}
            onMouseUp={(e) => {
                e.currentTarget.style.transform = "translate(-2px, -2px)";
                e.currentTarget.style.boxShadow = "var(--shadow-md)";
            }}
        >
            {!isHydrated ? (
                <>
                    <Sun size={16} />
                    Theme
                </>
            ) : theme === "dark" ? (
                <>
                    <Sun size={16} />
                    Light
                </>
            ) : (
                <>
                    <Moon size={16} />
                    Dark
                </>
            )}
        </button>
    );
}
