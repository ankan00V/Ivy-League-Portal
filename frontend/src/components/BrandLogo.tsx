"use client";

import Link from "next/link";

type LogoSize = "sm" | "md" | "lg";

const SIZE_MAP: Record<LogoSize, { fontSize: string; padding: string; gap: string; versePadding: string }> = {
    sm: { fontSize: "1.45rem", padding: "0.45rem 0.6rem", gap: "0.22rem", versePadding: "0 0.28rem" },
    md: { fontSize: "1.75rem", padding: "0.5rem 0.68rem", gap: "0.22rem", versePadding: "0 0.3rem" },
    lg: { fontSize: "2.1rem", padding: "0.55rem 0.7rem", gap: "0.2rem", versePadding: "0 0.3rem" },
};

export default function BrandLogo({
    href = "/",
    size = "sm",
}: {
    href?: string;
    size?: LogoSize;
}) {
    const sizing = SIZE_MAP[size];

    return (
        <Link
            href={href}
            style={{
                display: "inline-flex",
                alignItems: "baseline",
                gap: sizing.gap,
                padding: sizing.padding,
                border: "2px solid color-mix(in srgb, #ffffff 92%, transparent 8%)",
                borderRadius: "var(--radius-sm)",
                background:
                    "linear-gradient(135deg, color-mix(in srgb, #090c17 92%, #000000 8%) 0%, color-mix(in srgb, #131c3a 88%, #000000 12%) 100%)",
                boxShadow: "0 10px 24px color-mix(in srgb, #000000 38%, transparent)",
                lineHeight: 1,
            }}
        >
            <span
                style={{
                    fontSize: sizing.fontSize,
                    fontWeight: 400,
                    fontFamily: "var(--font-serif)",
                    letterSpacing: "-0.03em",
                    color: "color-mix(in srgb, #ffffff 96%, #d6e3ff 4%)",
                    textShadow: "0 0 10px color-mix(in srgb, #ffffff 14%, transparent)",
                }}
            >
                Vidya
            </span>
            <span
                style={{
                    fontSize: sizing.fontSize,
                    fontWeight: 400,
                    fontFamily: "var(--font-serif)",
                    letterSpacing: "-0.03em",
                    color: "#000000",
                    background:
                        "linear-gradient(135deg, color-mix(in srgb, var(--brand-accent) 88%, #9cffd0 12%) 0%, color-mix(in srgb, var(--brand-accent) 76%, #47c57f 24%) 100%)",
                    border: "2px solid color-mix(in srgb, #ffffff 88%, transparent 12%)",
                    borderRadius: "var(--radius-sm)",
                    padding: sizing.versePadding,
                    boxShadow: "0 8px 20px color-mix(in srgb, var(--brand-accent) 22%, transparent)",
                    transform: "rotate(-2deg)",
                }}
            >
                Verse
            </span>
        </Link>
    );
}
