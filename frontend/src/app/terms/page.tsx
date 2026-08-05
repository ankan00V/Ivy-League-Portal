import type { Metadata } from "next";
import Link from "next/link";

import styles from "../privacy/policy.module.css";

/*
 * Like the privacy policy, this describes the product as built rather than
 * restating a generic template. The claims about what the ranking does and does
 * not decide, and about the advisory-only resume review, are checked against
 * README section 6 and services/resume_review_service.py.
 *
 * Not reviewed by a lawyer.
 */

export const metadata: Metadata = {
  title: "Terms of Service - VidyaVerse",
  description: "The rules for using VidyaVerse, and what we do and do not promise.",
};

const TERMS_VERSION = "2026-08-05";

export default function TermsPage() {
  return (
    <main className={styles.page}>
      <article className={styles.document}>
        <header className={styles.header}>
          <Link href="/" className={styles.back}>
            ← Back to VidyaVerse
          </Link>
          <h1>Terms of Service</h1>
          <p className={styles.version}>Version {TERMS_VERSION}</p>
        </header>

        <section>
          <h2>What VidyaVerse is</h2>
          <p>
            VidyaVerse is a discovery tool. We collect internship and early-career
            opportunity listings from across the web, filter and rank them against your
            profile, and show you the ones we think fit. That is the whole service.
          </p>
        </section>

        <section>
          <h2>What we do not do</h2>
          <p>Worth being explicit, because discovery products are often assumed to do more:</p>
          <ul>
            <li>
              <strong>We are not the employer</strong> and we are not a recruitment agency. We
              do not decide who gets hired, we do not forward your profile to employers on our
              own initiative, and we have no influence over any hiring decision.
            </li>
            <li>
              <strong>We do not guarantee that a listing is accurate, current, or genuine.</strong>{" "}
              Listings come from third-party sources. We score them for quality and retire ones
              that look closed, but a posting can be stale, mis-described, or withdrawn without
              us knowing. Verify anything important with the employer directly, and never pay a
              fee to apply for a job.
            </li>
            <li>
              <strong>The Resume Readiness Review is advisory.</strong> It is a deterministic
              readability and completeness check. It is not a hiring prediction, not an
              eligibility ruling, and it does not affect how opportunities are ranked for you.
            </li>
            <li>
              <strong>Eligibility notes are guidance, not decisions.</strong> Where we show that
              a listing may not match your degree or graduation year, that is our reading of the
              posting, not the employer&rsquo;s ruling on your application.
            </li>
          </ul>
        </section>

        <section>
          <h2>Your account</h2>
          <ul>
            <li>You need to be old enough to consent to data processing where you live. If you are a minor, use the product with a parent or guardian.</li>
            <li>Keep your account to yourself. You are responsible for what happens under your login.</li>
            <li>Give us accurate profile information. Matching is only as good as what it matches against.</li>
            <li>Employer accounts require a corporate email address and are subject to review.</li>
          </ul>
        </section>

        <section>
          <h2>Acceptable use</h2>
          <p>Do not:</p>
          <ul>
            <li>Scrape, bulk-download, or resell listings or other users&rsquo; information.</li>
            <li>Post fraudulent opportunities, or use an employer account to harvest candidate profiles.</li>
            <li>Attempt to break, overload, or work around the platform&rsquo;s security or rate limits.</li>
            <li>Upload anything you do not have the right to share, including a resume that is not yours.</li>
          </ul>
          <p>
            We may suspend or remove accounts that do these things. Repeated failed sign-in
            attempts trigger an automatic temporary lock.
          </p>
        </section>

        <section>
          <h2>Your content</h2>
          <p>
            Your profile, your resume and anything you post stay yours. You give us permission
            to store and process them for the purpose of running the service — matching you to
            opportunities and showing you your own data back. Nothing more. Delete your account
            and that permission ends along with the data; see the{" "}
            <Link href="/privacy">Privacy Policy</Link> for exactly what deletion removes.
          </p>
        </section>

        <section>
          <h2>Availability</h2>
          <p>
            The service is provided as-is. We do not promise uninterrupted availability, and we
            may change or remove features. Where a change materially affects how we handle your
            data, we will update the Privacy Policy and its version number, which means we ask
            for your consent again rather than assuming it.
          </p>
        </section>

        <section>
          <h2>Ending things</h2>
          <p>
            You can delete your account at any time from your profile page, without contacting
            anyone. We may close accounts that breach these terms.
          </p>
          <p className={styles.footnote}>
            These terms describe the service as built on {TERMS_VERSION}. They have not been
            reviewed by a lawyer. See also our <Link href="/privacy">Privacy Policy</Link>.
          </p>
        </section>
      </article>
    </main>
  );
}
