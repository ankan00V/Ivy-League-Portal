"use client";
import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";
import DotMatrixHandsBackground from "@/components/DotMatrixHandsBackground";
import { useEffect, useState } from "react";
import { getAccessToken, getAuthStateEventName, hasAuthSession } from "@/lib/auth-session";
import styles from "./page.module.css";

export default function Home() {
  const router = useRouter();
  const [isAuthenticated, setIsAuthenticated] = useState(() => hasAuthSession());

  useEffect(() => {
    let cancelled = false;

    const syncAuthState = () => {
      const token = getAccessToken();
      const isAuthed = Boolean(token) || hasAuthSession();
      if (!cancelled) {
        setIsAuthenticated(isAuthed);
      }
    };

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
        <DotMatrixHandsBackground />
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
      <section className={styles.hero}>
        <div className={styles.copyStage}>
          <div className={styles.kicker}>
            AI-Powered Intelligence Network
          </div>

          <h1 className={styles.heading}>
            Bridge the Gap to <br />
            <span className={styles.headingAccent}>
              Ivy League Opportunities
            </span>
          </h1>

          <p className={styles.description}>
            Continuously refreshed internships, hackathons, competitions and workshops.
            Rank yourself with the global{" "}
            <strong className={styles.descriptionStrong}>
              InCoScore
            </strong>{" "}
            and take each application to its source in one click.
          </p>

          <div className={styles.actions}>
            <button
              type="button"
              className={`${styles.primaryAction} btn-primary`}
              onClick={handlePrimaryAction}
            >
              {isAuthenticated ? "Open Profile" : "Start Your Journey"}
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}
