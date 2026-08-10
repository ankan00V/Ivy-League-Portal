import type { Metadata } from "next";
import Link from "next/link";

import styles from "./policy.module.css";

/*
 * This page is written from the code, not from a template.
 *
 * Every claim below was checked against the implementation on 2026-08-05:
 * the profile fields we store (app/models/profile.py), what the resume path does
 * (endpoints/users.py::upload_resume + services/document_redaction.py), where
 * resume text is parsed (services/ai_engine.py::parse_resume — local spaCy, no
 * third-party LLM), what consent gates (services/privacy_consent_service.py), what
 * the warehouse exports (services/warehouse_export_service.py), the telemetry
 * retention window (services/telemetry_privacy.py), and what account deletion
 * actually removes (services/account_deletion_service.py).
 *
 * If any of those change, this page is stale and must change with them. That is a
 * README-freshness obligation under AGENTS.md, not a nice-to-have: a privacy notice
 * that describes behaviour the code no longer has is worse than none.
 *
 * It has not been reviewed by a lawyer. It is an accurate engineering description
 * of what the system does, which is the necessary input to that review.
 */

export const metadata: Metadata = {
  title: "Privacy Policy - VidyaVerse",
  description:
    "What VidyaVerse collects, why, how long it is kept, and how to get it deleted.",
};

const POLICY_VERSION = "2026-08-05";

export default function PrivacyPolicyPage() {
  return (
    <main className={styles.page}>
      <article className={styles.document}>
        <header className={styles.header}>
          <Link href="/" className={styles.back}>
            ← Back to VidyaVerse
          </Link>
          <h1>Privacy Policy</h1>
          <p className={styles.version}>
            Version {POLICY_VERSION}. This version number is recorded against your consent, so
            if we change this policy materially we have to ask you again rather than assume
            your earlier agreement carried over.
          </p>
        </header>

        <section>
          <h2>The short version</h2>
          <ul>
            <li>We collect what we need to match you to opportunities, and we have removed the fields we were collecting and never using.</li>
            <li>Your resume is parsed on our own servers. It is never sent to a third-party AI provider.</li>
            <li>We strip the hidden author and employer metadata out of your resume file before storing it.</li>
            <li>Analytics is optional and off unless you consent. Withdrawing consent does not break your feed.</li>
            <li>You can delete your account and everything attached to it, from your profile page, without emailing anyone.</li>
          </ul>
        </section>

        <section>
          <h2>What we collect</h2>

          <h3>Account</h3>
          <p>
            Your email address, and a password hash if you set a password. If you sign in with
            Google, we receive your email from Google; we do not receive your Google password.
          </p>

          <h3>Profile</h3>
          <p>
            Your name, mobile number, education (course, specialization, institute, graduation
            year), work experience, skills, interests, city/region, preferred roles and
            locations, expected stipend, and availability. These are the inputs to matching.
          </p>
          <p>
            We deliberately <strong>do not</strong> collect your date of birth, gender,
            pronouns, street address, landmark, or pincode. We used to. Nothing in the product
            read them, so they were removed on {POLICY_VERSION} and purged from storage. We ask
            for your city and state because opportunity matching uses location; we do not need
            to know which building you live in.
          </p>

          <h3>Resume</h3>
          <p>
            If you upload one, we store the file and extract text from it to pre-fill your
            profile and to produce the Resume Readiness Review. Two things worth stating
            plainly:
          </p>
          <ul>
            <li>
              <strong>Your resume is not sent to any third-party AI service.</strong> Text
              extraction and parsing run on our own servers using a local NLP model. It is not
              sent to OpenAI, Anthropic, Google, or any other provider.
            </li>
            <li>
              <strong>We strip the file&rsquo;s hidden metadata before storing it.</strong> PDFs
              and Word documents carry an author name, the licensed software owner, and often
              the name of the organisation whose machine last edited the file. If you last
              edited your CV on your current employer&rsquo;s laptop, that file names them. We
              remove that on upload.
            </li>
          </ul>
          <p>
            The Resume Readiness Review is advisory only. It is not a hiring prediction, not an
            eligibility decision, and it does not feed opportunity ranking. We do not keep the
            extracted text or the review output after generating it.
          </p>

          <h3>How you use the product</h3>
          <p>
            Which opportunities we showed you, which you opened, saved, applied to or hid, how
            long you spent, and what you searched for. This is what makes recommendations
            improve rather than stay static.
          </p>
        </section>

        <section>
          <h2>Your choices</h2>

          <h3>Analytics consent</h3>
          <p>
            The privacy consent toggle on your profile controls whether your activity is
            included in our analytics warehouse — the aggregated reporting we use to understand
            how the product performs. It is a real switch:
          </p>
          <ul>
            <li>With consent off, your rows are excluded from every analytics export.</li>
            <li>Your recommendations keep working either way. Ranking your feed needs your profile, and that is the thing you asked us for.</li>
            <li>You can withdraw at any time, and we record when consent was given and when it ended.</li>
          </ul>
          <p>
            Even with consent on, exported analytics identifies you by a one-way pseudonym
            rather than your account ID.
          </p>

          <h3>Deleting your account</h3>
          <p>
            Profile → Danger Zone → Delete account. You will be asked to type a confirmation
            phrase, because it cannot be undone. It removes your profile, your resume file,
            your applications, your saved queries and assistant conversations, your posts and
            comments, and your account.
          </p>
          <p>
            Two things survive deletion, and you should know what they are:
          </p>
          <ul>
            <li>
              <strong>Anonymous measurement rows.</strong> The record that &ldquo;an
              impression happened&rdquo; stays, with your identity replaced by a random value
              that maps to nothing. If we deleted these instead, every past experiment result
              would silently change. What is removed is the link to you.
            </li>
            <li>
              <strong>Security records.</strong> Sign-in attempt logs keep their IP address and
              lock state for abuse defence, with your email and user ID stripped. These expire
              automatically after 90 days. Without this, deleting an account would be a way to
              erase an abuse trail.
            </li>
          </ul>
        </section>

        <section>
          <h2>How long we keep things</h2>
          <ul>
            <li><strong>Profile and resume:</strong> until you delete your account.</li>
            <li><strong>Detailed activity:</strong> linked to you for up to 400 days. After that we replace your ID with a pseudonym and clear what you typed into search, keeping the anonymous measurement.</li>
            <li><strong>Sign-in and security logs:</strong> 90 days, automatically.</li>
            <li><strong>One-time passcodes:</strong> deleted when they expire.</li>
          </ul>
        </section>

        <section>
          <h2>Who else sees your data</h2>
          <p>
            We use third-party services to find and fetch opportunity listings from across the
            web — search and page-rendering providers. <strong>Those requests are about job
            listings, not about you.</strong> Your profile, your resume and your activity are
            not sent to them.
          </p>
          <p>
            Our infrastructure providers (database, cache, analytics warehouse, file storage)
            process data on our behalf under their own terms.
          </p>
          <p>We do not sell your data, and we do not run advertising trackers.</p>
        </section>

        <section>
          <h2>Your rights</h2>
          <p>
            If you are in India, the Digital Personal Data Protection Act, 2023 gives you rights
            over your personal data including access, correction and erasure. If you are in the
            EEA or UK, the GDPR gives you equivalent rights including erasure under Article 17.
          </p>
          <p>
            You can exercise correction by editing your profile and erasure by deleting your
            account — both self-service, no request queue. For anything else, contact us and we
            will respond.
          </p>
        </section>

        <section>
          <h2>Contact</h2>
          <p>
            Questions about this policy, or about data we hold: reach out through the in-product
            assistant or the contact route listed on our repository.
          </p>
          <p className={styles.footnote}>
            This document describes the system as implemented on {POLICY_VERSION}. It has not
            been reviewed by a lawyer, and it is not a substitute for one. See also our{" "}
            <Link href="/terms">Terms of Service</Link>.
          </p>
        </section>
      </article>
    </main>
  );
}
