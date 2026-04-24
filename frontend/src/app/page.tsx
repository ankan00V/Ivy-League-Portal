"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";
import Spline from "@splinetool/react-spline";
import { useCallback, useEffect, useState } from "react";
import { getAccessToken, getAuthStateEventName, hasAuthSession, resolvePostAuthRoute } from "@/lib/auth-session";

export default function Home() {
  const router = useRouter();
  const [isAuthenticated, setIsAuthenticated] = useState(() => hasAuthSession());
  const [dashboardHref, setDashboardHref] = useState("/dashboard");

  const hideSplineBranding = useCallback(() => {
    const brandedAnchors = Array.from(
      document.querySelectorAll<HTMLAnchorElement>('a[href*="spline.design"], a[href*="splinetool"]')
    );

    brandedAnchors.forEach((anchor) => {
      const content = (anchor.textContent || "").toLowerCase();
      const href = (anchor.getAttribute("href") || "").toLowerCase();
      const isSplineBadge = content.includes("built with spline") || href.includes("spline.design");

      if (!isSplineBadge) {
        return;
      }

      const fixedContainer = anchor.closest<HTMLElement>("div[style*='position: fixed']");
      const target = fixedContainer ?? anchor;
      target.style.display = "none";
      target.style.visibility = "hidden";
      target.style.pointerEvents = "none";
      target.style.opacity = "0";
    });
  }, []);

  const handleSplineLoad = useCallback(
    (app: unknown) => {
      const splineApp = app as {
        _renderer?: { pipeline?: { setWatermark?: (texture: unknown) => void } };
      };

      const pipeline = splineApp?._renderer?.pipeline;
      if (pipeline && typeof pipeline.setWatermark === "function") {
        pipeline.setWatermark(null);
      }

      window.setTimeout(hideSplineBranding, 0);
      window.setTimeout(hideSplineBranding, 500);
      window.setTimeout(hideSplineBranding, 1500);
    },
    [hideSplineBranding]
  );

  useEffect(() => {
    hideSplineBranding();

    const observer = new MutationObserver(() => {
      hideSplineBranding();
    });

    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [hideSplineBranding]);

  useEffect(() => {
    let cancelled = false;

    const syncDashboardHref = async () => {
      const token = getAccessToken();
      if (!token && !hasAuthSession()) {
        if (!cancelled) {
          setDashboardHref("/dashboard");
        }
        return;
      }

      const nextRoute = await resolvePostAuthRoute(token || null);
      if (!cancelled) {
        setDashboardHref(nextRoute || "/dashboard");
      }
    };

    const syncAuthState = () => {
      const token = getAccessToken();
      const isAuthed = Boolean(token) || hasAuthSession();
      if (!cancelled) {
        setIsAuthenticated(isAuthed);
      }
      void syncDashboardHref();
    };

    void syncDashboardHref();
    const authStateEventName = getAuthStateEventName();
    window.addEventListener("focus", syncAuthState);
    window.addEventListener("storage", syncAuthState);
    window.addEventListener(authStateEventName, syncAuthState);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", syncAuthState);
      window.removeEventListener("storage", syncAuthState);
      window.removeEventListener(authStateEventName, syncAuthState);
    };
  }, []);

  const handlePrimaryAction = () => {
    router.push(isAuthenticated ? "/profile" : "/register");
  };

  return (
    <main
      style={{
        position: "relative",
        height: "100vh",
        overflow: "hidden",
        background: "var(--bg-base)",
      }}
    >
      <div
        aria-hidden
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 0,
          touchAction: "pan-y",
        }}
      >
        <Spline
          scene="https://prod.spline.design/h-vDP210ADjhpfEB/scene.splinecode"
          onLoad={handleSplineLoad}
        />
      </div>
      <div
        aria-hidden
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 1,
          pointerEvents: "none",
          background:
            "linear-gradient(180deg, color-mix(in srgb, var(--bg-base) 8%, transparent) 0%, color-mix(in srgb, var(--bg-base) 4%, transparent) 48%, color-mix(in srgb, var(--bg-base) 10%, transparent) 100%)",
        }}
      />
      <div style={{ position: "relative", zIndex: 2 }}>
        <Navbar />
      </div>
      <section
        className="layout-container"
        style={{
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          minHeight: "100vh",
          padding: "7.5rem 1.5rem 2rem 1.5rem",
          position: "relative",
          zIndex: 2,
          pointerEvents: "none",
        }}
      >
        <div
          style={{
            maxWidth: 800,
            padding: "1.5rem 2rem",
          }}
          className="animate-fade-up"
        >
          <div style={{
            display: "inline-block",
            padding: "0.55rem 1.1rem",
            background:
              "linear-gradient(120deg, color-mix(in srgb, var(--landing-kicker-bg) 70%, #0b1d39 30%) 0%, color-mix(in srgb, var(--landing-kicker-bg) 84%, #4ec8ff 16%) 52%, color-mix(in srgb, var(--landing-kicker-bg) 70%, #0b1d39 30%) 100%)",
            border: "2px solid color-mix(in srgb, var(--landing-kicker-text) 55%, #ffffff 45%)",
            borderRadius: "var(--radius-full)",
            color: "var(--landing-kicker-text)",
            fontSize: "0.85rem",
            fontWeight: 700,
            marginBottom: "2rem",
            letterSpacing: "0.05em",
            textTransform: "uppercase",
            boxShadow:
              "0 8px 22px color-mix(in srgb, var(--landing-kicker-text) 24%, transparent), inset 0 1px 0 color-mix(in srgb, #ffffff 35%, transparent)",
            textShadow: "0 0 12px color-mix(in srgb, var(--landing-kicker-text) 35%, transparent)",
          }}>
            AI-Powered Intelligence Network
          </div>

          <h1
            style={{
              fontSize: "4rem",
              lineHeight: 1.1,
              marginBottom: "1.5rem",
              color: "color-mix(in srgb, var(--text-primary) 92%, #ffffff 8%)",
              textShadow:
                "0 2px 0 color-mix(in srgb, #000000 55%, transparent), 0 14px 34px color-mix(in srgb, #000000 48%, transparent)",
              WebkitTextStroke: "0.45px color-mix(in srgb, #000000 45%, transparent)",
            }}
          >
            Bridge the Gap to <br />
            <span
              style={{
                background:
                  "linear-gradient(120deg, color-mix(in srgb, var(--brand-primary) 90%, #ffffff 10%) 0%, color-mix(in srgb, var(--brand-primary) 65%, #c08a00 35%) 45%, color-mix(in srgb, var(--brand-primary) 88%, #ffffff 12%) 100%)",
                WebkitBackgroundClip: "text",
                backgroundClip: "text",
                color: "transparent",
                WebkitTextFillColor: "transparent",
                textShadow:
                  "0 0 18px color-mix(in srgb, var(--brand-primary) 36%, transparent), 0 6px 20px color-mix(in srgb, #000000 45%, transparent)",
              }}
            >
              Ivy League Opportunities
            </span>
          </h1>

          <p
            style={{
              fontSize: "1.2rem",
              color: "color-mix(in srgb, var(--text-secondary) 78%, #ffffff 22%)",
              marginBottom: "3rem",
              padding: "0 2rem",
              textShadow: "0 3px 14px color-mix(in srgb, #000000 48%, transparent)",
            }}
          >
            Real-time tracking of hackathons, research internships, and scholarships.
            Rank yourself with the global{" "}
            <strong
              style={{
                color: "color-mix(in srgb, var(--landing-strong-text) 90%, #ffffff 10%)",
                textShadow: "0 2px 12px color-mix(in srgb, #000000 55%, transparent)",
              }}
            >
              InCoScore
            </strong>{" "}
            and auto-apply with AI.
          </p>

          <div style={{ display: "flex", gap: "1rem", justifyContent: "center", pointerEvents: "auto" }}>
            <button
              type="button"
              className="btn-primary"
              onClick={handlePrimaryAction}
              style={{
                padding: "1rem 2.5rem",
                fontSize: "1.1rem",
                background:
                  "linear-gradient(135deg, color-mix(in srgb, var(--brand-primary) 88%, #ffffff 12%) 0%, color-mix(in srgb, var(--brand-primary) 70%, #9a6f00 30%) 100%)",
                boxShadow:
                  "0 12px 28px color-mix(in srgb, var(--brand-primary) 28%, transparent), var(--shadow-sm)",
              }}
            >
              {isAuthenticated ? "Open Profile" : "Start Your Journey"}
            </button>
            <Link
              href={dashboardHref}
              className="btn-secondary"
              style={{
                padding: "1rem 2.5rem",
                fontSize: "1.1rem",
                background:
                  "linear-gradient(135deg, color-mix(in srgb, #0b1022 78%, var(--bg-surface) 22%) 0%, color-mix(in srgb, #18284f 82%, var(--bg-surface) 18%) 100%)",
                border: "2px solid color-mix(in srgb, #ffffff 78%, var(--border-subtle) 22%)",
                color: "color-mix(in srgb, #ffffff 90%, var(--text-primary) 10%)",
                boxShadow:
                  "0 12px 28px color-mix(in srgb, #5a8bff 22%, transparent), var(--shadow-sm)",
              }}
            >
              {isAuthenticated ? "Open Dashboard" : "View Dashboard"}
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}
