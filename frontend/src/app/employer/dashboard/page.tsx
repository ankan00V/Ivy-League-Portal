"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useCallback, useEffect, useMemo, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import { apiUrl } from "@/lib/api";
import { clearAccessToken, getAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";

type ProfileMe = {
  account_type?: string;
  first_name?: string;
  company_name?: string;
};

type EmployerApplication = {
  application_id: string;
  opportunity_id: string;
  opportunity_title: string;
  applicant_name?: string | null;
  applicant_email?: string | null;
  status: string;
  submitted_at?: string | null;
  created_at: string;
};

type EmployerSummary = {
  company_name?: string | null;
  opportunities_posted: number;
  active_opportunities: number;
  total_applications: number;
  submitted_applications: number;
  pending_applications: number;
  auto_filled_applications: number;
  recent_applications: EmployerApplication[];
};

type EmployerOpportunity = {
  id: string;
  title: string;
  description: string;
  opportunity_type?: string | null;
  domain?: string | null;
  location?: string | null;
  eligibility?: string | null;
  application_url: string;
  deadline?: string | null;
  applications_count: number;
};

type CreateOpportunityPayload = {
  title: string;
  description: string;
  application_url: string;
  opportunity_type: string;
  domain: string;
  location: string;
  eligibility: string;
  deadline: string;
};

function stableDate(value?: string | null): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export default function EmployerDashboardPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [profile, setProfile] = useState<ProfileMe | null>(null);
  const [summary, setSummary] = useState<EmployerSummary | null>(null);
  const [opportunities, setOpportunities] = useState<EmployerOpportunity[]>([]);
  const [form, setForm] = useState<CreateOpportunityPayload>({
    title: "",
    description: "",
    application_url: "",
    opportunity_type: "Internship",
    domain: "",
    location: "",
    eligibility: "",
    deadline: "",
  });

  const authHeader = useMemo(() => {
    const token = getAccessToken();
    if (!token) {
      return null;
    }
    return { Authorization: `Bearer ${token}` };
  }, []);

  const refresh = useCallback(async () => {
    if (!authHeader) {
      router.replace("/login");
      return;
    }

    const [profileRes, summaryRes, opportunitiesRes] = await Promise.all([
      fetch(apiUrl("/api/v1/users/me/profile"), { headers: authHeader }),
      fetch(apiUrl("/api/v1/employer/dashboard/summary"), { headers: authHeader }),
      fetch(apiUrl("/api/v1/employer/opportunities"), { headers: authHeader }),
    ]);

    if (!profileRes.ok) {
      throw new Error("Unable to load your profile");
    }

    const profilePayload = (await profileRes.json()) as ProfileMe;
    if (String(profilePayload.account_type || "candidate").toLowerCase() !== "employer") {
      router.replace("/dashboard");
      return;
    }
    setProfile(profilePayload);

    if (summaryRes.ok) {
      const summaryPayload = (await summaryRes.json()) as EmployerSummary;
      setSummary(summaryPayload);
    }

    if (opportunitiesRes.ok) {
      const opportunitiesPayload = (await opportunitiesRes.json()) as EmployerOpportunity[];
      setOpportunities(opportunitiesPayload);
    }
  }, [authHeader, router]);

  useEffect(() => {
    const run = async () => {
      try {
        await refresh();
      } catch (err) {
        setError(getUnknownErrorMessage(err, "Unable to load employer dashboard"));
      } finally {
        setLoading(false);
      }
    };
    void run();
  }, [refresh]);

  const updateForm = <K extends keyof CreateOpportunityPayload>(field: K, value: CreateOpportunityPayload[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!authHeader) {
      router.replace("/login");
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const payload = {
        title: form.title.trim(),
        description: form.description.trim(),
        application_url: form.application_url.trim(),
        opportunity_type: form.opportunity_type.trim(),
        domain: form.domain.trim() || undefined,
        location: form.location.trim() || undefined,
        eligibility: form.eligibility.trim() || undefined,
        deadline: form.deadline ? new Date(`${form.deadline}T23:59:59`).toISOString() : undefined,
      };

      const res = await fetch(apiUrl("/api/v1/employer/opportunities"), {
        method: "POST",
        headers: {
          ...authHeader,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(getApiErrorMessage(body, "Unable to create opportunity"));
      }

      setForm({
        title: "",
        description: "",
        application_url: "",
        opportunity_type: "Internship",
        domain: "",
        location: "",
        eligibility: "",
        deadline: "",
      });
      setSuccess("Opportunity published successfully.");
      await refresh();
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to create opportunity"));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "var(--bg-base)" }}>
        <p style={{ color: "var(--text-secondary)", fontWeight: 700 }}>Loading employer dashboard...</p>
      </main>
    );
  }

  return (
    <main style={{ minHeight: "100vh", background: "var(--bg-base)", padding: "1.25rem" }}>
      <div style={{ maxWidth: "1200px", margin: "0 auto", display: "grid", gap: "1rem" }}>
        <section className="card-panel" style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <div>
            <BrandLogo size="sm" />
            <h1 style={{ marginTop: "0.6rem", marginBottom: "0.25rem", fontSize: "2rem" }}>Employer Command Center</h1>
            <p style={{ color: "var(--text-secondary)", fontWeight: 600 }}>
              {profile?.first_name ? `Welcome ${profile.first_name}.` : "Welcome."} Manage postings and monitor applications in real-time.
            </p>
            <p style={{ color: "var(--text-secondary)", marginTop: "0.35rem" }}>
              Organization: <strong>{summary?.company_name || profile?.company_name || "Employer Organization"}</strong>
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
            <Link href="/onboarding" className="btn-secondary">Update Profile</Link>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                clearAccessToken();
                router.replace("/login");
              }}
            >
              Logout
            </button>
          </div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.75rem" }}>
          {[
            { label: "Posted", value: summary?.opportunities_posted ?? 0 },
            { label: "Active", value: summary?.active_opportunities ?? 0 },
            { label: "Applications", value: summary?.total_applications ?? 0 },
            { label: "Submitted", value: summary?.submitted_applications ?? 0 },
            { label: "Pending", value: summary?.pending_applications ?? 0 },
            { label: "Auto-filled", value: summary?.auto_filled_applications ?? 0 },
          ].map((item) => (
            <article key={item.label} className="card-panel" style={{ padding: "0.9rem" }}>
              <p style={{ color: "var(--text-secondary)", fontWeight: 700 }}>{item.label}</p>
              <p style={{ fontSize: "1.65rem", fontWeight: 900 }}>{item.value}</p>
            </article>
          ))}
        </section>

        <section className="card-panel" style={{ display: "grid", gap: "0.8rem" }}>
          <h2 style={{ fontSize: "1.4rem" }}>Post Opportunity</h2>
          {error && <div style={{ border: "2px solid #ef4444", color: "#b91c1c", borderRadius: "10px", padding: "0.7rem", background: "rgba(239,68,68,0.08)" }}>{error}</div>}
          {success && <div style={{ border: "2px solid #22c55e", color: "#15803d", borderRadius: "10px", padding: "0.7rem", background: "rgba(34,197,94,0.08)" }}>{success}</div>}

          <form onSubmit={handleCreate} style={{ display: "grid", gap: "0.75rem" }}>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "0.75rem" }}>
              <input className="input-base" placeholder="Opportunity title" value={form.title} onChange={(e) => updateForm("title", e.target.value)} required />
              <input className="input-base" placeholder="Type (Internship / Job / Hackathon)" value={form.opportunity_type} onChange={(e) => updateForm("opportunity_type", e.target.value)} required />
            </div>
            <textarea
              className="input-base"
              placeholder="Description"
              rows={4}
              value={form.description}
              onChange={(e) => updateForm("description", e.target.value)}
              required
            />
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "0.75rem" }}>
              <input className="input-base" placeholder="Application URL" value={form.application_url} onChange={(e) => updateForm("application_url", e.target.value)} required />
              <input className="input-base" placeholder="Domain" value={form.domain} onChange={(e) => updateForm("domain", e.target.value)} />
              <input className="input-base" placeholder="Location" value={form.location} onChange={(e) => updateForm("location", e.target.value)} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "0.75rem" }}>
              <input className="input-base" placeholder="Eligibility criteria" value={form.eligibility} onChange={(e) => updateForm("eligibility", e.target.value)} />
              <input className="input-base" type="date" value={form.deadline} onChange={(e) => updateForm("deadline", e.target.value)} />
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button className="btn-primary" type="submit" disabled={saving}>{saving ? "Publishing..." : "Publish Opportunity"}</button>
            </div>
          </form>
        </section>

        <section className="card-panel" style={{ display: "grid", gap: "0.75rem" }}>
          <h2 style={{ fontSize: "1.4rem" }}>Your Posted Opportunities</h2>
          {opportunities.length === 0 ? (
            <p style={{ color: "var(--text-secondary)", fontWeight: 600 }}>No employer opportunities posted yet.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "2px solid var(--border-subtle)" }}>
                    <th style={{ padding: "0.55rem" }}>Title</th>
                    <th style={{ padding: "0.55rem" }}>Type</th>
                    <th style={{ padding: "0.55rem" }}>Domain</th>
                    <th style={{ padding: "0.55rem" }}>Deadline</th>
                    <th style={{ padding: "0.55rem" }}>Applications</th>
                  </tr>
                </thead>
                <tbody>
                  {opportunities.map((item) => (
                    <tr key={item.id} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                      <td style={{ padding: "0.55rem", fontWeight: 700 }}>{item.title}</td>
                      <td style={{ padding: "0.55rem" }}>{item.opportunity_type || "-"}</td>
                      <td style={{ padding: "0.55rem" }}>{item.domain || "-"}</td>
                      <td style={{ padding: "0.55rem" }}>{stableDate(item.deadline)}</td>
                      <td style={{ padding: "0.55rem" }}>{item.applications_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="card-panel" style={{ display: "grid", gap: "0.75rem" }}>
          <h2 style={{ fontSize: "1.4rem" }}>Recent Applications</h2>
          {!summary || summary.recent_applications.length === 0 ? (
            <p style={{ color: "var(--text-secondary)", fontWeight: 600 }}>No applications yet.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "2px solid var(--border-subtle)" }}>
                    <th style={{ padding: "0.55rem" }}>Opportunity</th>
                    <th style={{ padding: "0.55rem" }}>Applicant</th>
                    <th style={{ padding: "0.55rem" }}>Email</th>
                    <th style={{ padding: "0.55rem" }}>Status</th>
                    <th style={{ padding: "0.55rem" }}>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.recent_applications.map((row) => (
                    <tr key={row.application_id} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                      <td style={{ padding: "0.55rem", fontWeight: 700 }}>{row.opportunity_title}</td>
                      <td style={{ padding: "0.55rem" }}>{row.applicant_name || "-"}</td>
                      <td style={{ padding: "0.55rem" }}>{row.applicant_email || "-"}</td>
                      <td style={{ padding: "0.55rem" }}>{row.status}</td>
                      <td style={{ padding: "0.55rem" }}>{stableDate(row.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
