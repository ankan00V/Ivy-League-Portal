import Link from "next/link";

import styles from "./AppRecovery.module.css";
import BrandLogo from "@/components/BrandLogo";

export default function NotFound() {
  return (
    <main className={styles.shell}>
      <section className={styles.card} aria-labelledby="not-found-title">
        <BrandLogo size="md" />
        <p className={styles.eyebrow}>404 - Page not found</p>
        <h1 id="not-found-title" className={styles.title}>This route is not in the Verse.</h1>
        <p className={styles.message}>
          The page may have moved, or the link may be outdated. Continue with the live opportunity feed instead.
        </p>
        <div className={styles.actions}>
          <Link className="btn-primary" href="/opportunities">Browse opportunities</Link>
          <Link className="btn-secondary" href="/">Return home</Link>
        </div>
      </section>
    </main>
  );
}
