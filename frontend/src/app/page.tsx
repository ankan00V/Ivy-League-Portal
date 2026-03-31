"use client";
import { useEffect, useRef } from "react";
import Link from "next/link";
import Navbar from "@/components/Navbar";

export default function Home() {
  const mainRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const node = mainRef.current;
    if (!node) {
      return;
    }

    if (window.matchMedia("(pointer: coarse)").matches) {
      return;
    }

    let raf = 0;
    let nextX = 0;
    let nextY = 0;
    let hasPendingFrame = false;

    const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

    const resetPointer = () => {
      node.style.setProperty("--landing-cursor-x", "50%");
      node.style.setProperty("--landing-cursor-y", "50%");
      node.style.setProperty("--landing-pointer-x", "0");
      node.style.setProperty("--landing-pointer-y", "0");
    };

    const applyPointerState = () => {
      raf = 0;
      if (!hasPendingFrame) {
        return;
      }

      const rect = node.getBoundingClientRect();
      if (!rect.width || !rect.height) {
        return;
      }

      const xRatio = clamp((nextX - rect.left) / rect.width, 0, 1);
      const yRatio = clamp((nextY - rect.top) / rect.height, 0, 1);
      const xNormalized = (xRatio * 2 - 1).toFixed(3);
      const yNormalized = (yRatio * 2 - 1).toFixed(3);

      node.style.setProperty("--landing-cursor-x", `${(xRatio * 100).toFixed(2)}%`);
      node.style.setProperty("--landing-cursor-y", `${(yRatio * 100).toFixed(2)}%`);
      node.style.setProperty("--landing-pointer-x", xNormalized);
      node.style.setProperty("--landing-pointer-y", yNormalized);
      hasPendingFrame = false;
    };

    const queuePointerUpdate = () => {
      if (raf) {
        return;
      }
      raf = window.requestAnimationFrame(applyPointerState);
    };

    const onPointerMove = (event: PointerEvent | MouseEvent) => {
      nextX = event.clientX;
      nextY = event.clientY;
      hasPendingFrame = true;
      queuePointerUpdate();
    };

    resetPointer();

    const hasPointerEvents = "PointerEvent" in window;
    if (hasPointerEvents) {
      node.addEventListener("pointermove", onPointerMove as EventListener, { passive: true });
    } else {
      node.addEventListener("mousemove", onPointerMove as EventListener, { passive: true });
    }
    node.addEventListener("pointerleave", resetPointer);

    return () => {
      if (hasPointerEvents) {
        node.removeEventListener("pointermove", onPointerMove as EventListener);
      } else {
        node.removeEventListener("mousemove", onPointerMove as EventListener);
      }
      node.removeEventListener("pointerleave", resetPointer);
      if (raf) {
        window.cancelAnimationFrame(raf);
      }
    };
  }, []);

  return (
    <main ref={mainRef} className="landing-main">
      <div className="landing-bg-layer" aria-hidden>
        <div className="landing-cursor-glow" />
        <div className="landing-grid" />
        <div className="landing-blob landing-blob-one" />
        <div className="landing-blob landing-blob-two" />
        <div className="landing-blob landing-blob-three" />
      </div>

      <Navbar />

      <section className="layout-container" style={{ alignItems: "center", justifyContent: "center", textAlign: "center", paddingTop: "8rem" }}>
        <div style={{ maxWidth: 800, padding: "2rem" }} className="animate-fade-up landing-hero-parallax">
          <div style={{
            display: "inline-block",
            padding: "0.5rem 1rem",
            background: "var(--landing-kicker-bg)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-full)",
            color: "var(--landing-kicker-text)",
            fontSize: "0.85rem",
            fontWeight: 700,
            marginBottom: "2rem",
            letterSpacing: "0.05em",
            textTransform: "uppercase"
          }}>
            AI-Powered Intelligence Network
          </div>

          <h1 style={{ fontSize: "4rem", lineHeight: 1.1, marginBottom: "1.5rem" }}>
            Bridge the Gap to <br />
            <span className="text-gradient">Ivy League Opportunities</span>
          </h1>

          <p style={{ fontSize: "1.2rem", color: "var(--text-secondary)", marginBottom: "3rem", padding: "0 2rem" }}>
            Real-time tracking of hackathons, research internships, and scholarships.
            Rank yourself with the global <strong style={{ color: "var(--landing-strong-text)" }}>InCoScore</strong> and auto-apply with AI.
          </p>

          <div style={{ display: "flex", gap: "1rem", justifyContent: "center" }}>
            <Link href="/register" className="btn-primary" style={{ padding: "1rem 2.5rem", fontSize: "1.1rem" }}>
              Start Your Journey
            </Link>
            <Link href="/dashboard" className="btn-secondary" style={{ padding: "1rem 2.5rem", fontSize: "1.1rem" }}>
              View Dashboard
            </Link>
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section style={{ padding: "6rem 2rem", maxWidth: 1200, margin: "0 auto" }}>
        <h2 style={{ fontSize: "2.5rem", textAlign: "center", marginBottom: "4rem" }}>Intelligent Architecture</h2>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "2rem" }}>
          {/* Card 1 */}
          <div className="glass-panel" style={{ padding: "2rem" }}>
            <div style={{ width: 48, height: 48, borderRadius: 12, background: "rgba(99,102,241,0.2)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: "1.5rem" }}>
              <span style={{ fontSize: "1.5rem" }}>🧠</span>
            </div>
            <h3 style={{ fontSize: "1.25rem", marginBottom: "1rem" }}>AI Classification</h3>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.95rem" }}>Zero-shot NLP models automatically categorize every scraped opportunity into domains like AI, Law, and Biomed.</p>
          </div>

          {/* Card 2 */}
          <div className="glass-panel" style={{ padding: "2rem" }}>
            <div style={{ width: 48, height: 48, borderRadius: 12, background: "rgba(6,182,212,0.2)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: "1.5rem" }}>
              <span style={{ fontSize: "1.5rem" }}>📈</span>
            </div>
            <h3 style={{ fontSize: "1.25rem", marginBottom: "1rem" }}>InCoScore Ranking</h3>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.95rem" }}>Our proprietary Intelligent Competency Score evaluates your parsed resume, achievements, and technical prowess.</p>
          </div>

          {/* Card 3 */}
          <div className="glass-panel" style={{ padding: "2rem" }}>
            <div style={{ width: 48, height: 48, borderRadius: 12, background: "rgba(168,85,247,0.2)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: "1.5rem" }}>
              <span style={{ fontSize: "1.5rem" }}>⚡</span>
            </div>
            <h3 style={{ fontSize: "1.25rem", marginBottom: "1rem" }}>Automated System</h3>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.95rem" }}>One-click smart form submissions and a dedicated application tracking dashboard.</p>
          </div>
        </div>
      </section>
    </main>
  );
}
