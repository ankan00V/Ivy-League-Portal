"use client";

import Link from "next/link";
import { useEffect } from "react";

import styles from "./AppRecovery.module.css";
import BrandLogo from "@/components/BrandLogo";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("VidyaVerse route error", error);
  }, [error]);

  return (
    <main className={styles.shell}>
      <section className={styles.card} aria-labelledby="recovery-title">
        <BrandLogo size="md" />
        <p className={styles.eyebrow}>Temporary interruption</p>
        <h1 id="recovery-title" className={styles.title}>This page needs another try.</h1>
        <p className={styles.message}>
          Your account is safe. Retry the page, or return to the dashboard while VidyaVerse reconnects.
        </p>
        <div className={styles.actions}>
          <button type="button" className="btn-primary" onClick={reset}>Try again</button>
          <Link className="btn-secondary" href="/dashboard">Open dashboard</Link>
        </div>
      </section>
    </main>
  );
}
