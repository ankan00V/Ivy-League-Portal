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
  pipeline_state: "applied" | "shortlisted" | "rejected" | "interview";
  pipeline_notes?: string | null;
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
  shortlisted_applications: number;
  rejected_applications: number;
  interview_applications: number;
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
  lifecycle_status: "draft" | "published" | "paused" | "closed";
  applications_count: number;
};

type RecruiterAuditLog = {
  id: string;
  action: string;
  entity_type: string;
  entity_id?: string | null;
  opportunity_id?: string | null;
  application_id?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
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

type EditOpportunityPayload = {
  id: string;
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
  const [auditLogs, setAuditLogs] = useState<RecruiterAuditLog[]>([]);
  const [lifecycleUpdatingId, setLifecycleUpdatingId] = useState<string | null>(null);
  const [pipelineUpdatingId, setPipelineUpdatingId] = useState<string | null>(null);
  const [pipelineDrafts, setPipelineDrafts] = useState<Record<string, EmployerApplication["pipeline_state"]>>({});
  const [editingOpportunity, setEditingOpportunity] = useState<EditOpportunityPayload | null>(null);
  const [editSaving, setEditSaving] = useState(false);
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

    const [profileRes, summaryRes, opportunitiesRes, auditLogsRes] = await Promise.all([
      fetch(apiUrl("/api/v1/users/me/profile"), { headers: authHeader }),
      fetch(apiUrl("/api/v1/employer/dashboard/summary"), { headers: authHeader }),
      fetch(apiUrl("/api/v1/employer/opportunities"), { headers: authHeader }),
      fetch(apiUrl("/api/v1/employer/audit-logs?limit=25"), { headers: authHeader }),
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
      setPipelineDrafts(
        summaryPayload.recent_applications.reduce<Record<string, EmployerApplication["pipeline_state"]>>((acc, row) => {
          acc[row.application_id] = row.pipeline_state || "applied";
          return acc;
        }, {}),
      );
    }

    if (opportunitiesRes.ok) {
      const opportunitiesPayload = (await opportunitiesRes.json()) as EmployerOpportunity[];
      setOpportunities(opportunitiesPayload);
    }

    if (auditLogsRes.ok) {
      const logsPayload = (await auditLogsRes.json()) as RecruiterAuditLog[];
      setAuditLogs(logsPayload);
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

  const updateEditForm = <K extends keyof EditOpportunityPayload>(field: K, value: EditOpportunityPayload[K]) => {
    setEditingOpportunity((prev) => {
      if (!prev) {
        return prev;
      }
      return { ...prev, [field]: value };
    });
  };

  const openEditDrawer = (opportunity: EmployerOpportunity) => {
    setEditingOpportunity({
      id: opportunity.id,
      title: opportunity.title,
      description: opportunity.description,
      application_url: opportunity.application_url,
      opportunity_type: opportunity.opportunity_type || "",
      domain: opportunity.domain || "",
      location: opportunity.location || "",
      eligibility: opportunity.eligibility || "",
      deadline: stableDate(opportunity.deadline),
    });
  };

  const updateLifecycle = useCallback(
    async (opportunityId: string, status: EmployerOpportunity["lifecycle_status"]) => {
      if (!authHeader) {
        router.replace("/login");
        return;
      }
      setLifecycleUpdatingId(opportunityId);
      setError(null);
      setSuccess(null);
      try {
        const res = await fetch(apiUrl(`/api/v1/employer/opportunities/${opportunityId}/lifecycle`), {
          method: "POST",
          headers: {
            ...authHeader,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ status }),
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(getApiErrorMessage(body, "Unable to update lifecycle"));
        }
        setSuccess(`Lifecycle updated to ${status}.`);
        await refresh();
      } catch (err) {
        setError(getUnknownErrorMessage(err, "Unable to update lifecycle"));
      } finally {
        setLifecycleUpdatingId(null);
      }
    },
    [authHeader, refresh, router],
  );

  const updatePipelineState = useCallback(
    async (applicationId: string) => {
      if (!authHeader) {
        router.replace("/login");
        return;
      }
      const nextState = pipelineDrafts[applicationId] || "applied";
      setPipelineUpdatingId(applicationId);
      setError(null);
      setSuccess(null);
      try {
        const res = await fetch(apiUrl(`/api/v1/employer/applications/${applicationId}/pipeline`), {
          method: "PATCH",
          headers: {
            ...authHeader,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ pipeline_state: nextState }),
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(getApiErrorMessage(body, "Unable to update pipeline state"));
        }
        setSuccess(`Application moved to ${nextState}.`);
        await refresh();
      } catch (err) {
        setError(getUnknownErrorMessage(err, "Unable to update pipeline state"));
      } finally {
        setPipelineUpdatingId(null);
      }
    },
    [authHeader, pipelineDrafts, refresh, router],
  );

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

  const handleSaveEdit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!authHeader) {
      router.replace("/login");
      return;
    }
    if (!editingOpportunity) {
      return;
    }

    const targetId = editingOpportunity.id;
    const previous = opportunities.find((item) => item.id === targetId);
    if (!previous) {
      setError("Opportunity could not be found for editing.");
      setEditingOpportunity(null);
      return;
    }

    const optimistic: EmployerOpportunity = {
      ...previous,
      title: editingOpportunity.title.trim(),
      description: editingOpportunity.description.trim(),
      application_url: editingOpportunity.application_url.trim(),
      opportunity_type: editingOpportunity.opportunity_type.trim() || previous.opportunity_type,
      domain: editingOpportunity.domain.trim() || null,
      location: editingOpportunity.location.trim() || null,
      eligibility: editingOpportunity.eligibility.trim() || null,
      deadline: editingOpportunity.deadline ? new Date(`${editingOpportunity.deadline}T23:59:59`).toISOString() : null,
    };

    setEditSaving(true);
    setError(null);
    setSuccess(null);
    setOpportunities((rows) => rows.map((row) => (row.id === targetId ? optimistic : row)));

    try {
      const payload = {
        title: optimistic.title,
        description: optimistic.description,
        application_url: optimistic.application_url,
        opportunity_type: optimistic.opportunity_type || undefined,
        domain: optimistic.domain || undefined,
        location: optimistic.location || undefined,
        eligibility: optimistic.eligibility || undefined,
        deadline: optimistic.deadline ? new Date(optimistic.deadline).toISOString() : undefined,
      };
      const res = await fetch(apiUrl(`/api/v1/employer/opportunities/${targetId}`), {
        method: "PATCH",
        headers: {
          ...authHeader,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(getApiErrorMessage(body, "Unable to update opportunity"));
      }
      const updated = body as EmployerOpportunity;
      setOpportunities((rows) => rows.map((row) => (row.id === targetId ? updated : row)));
      setEditingOpportunity(null);
      setSuccess("Opportunity updated.");
      await refresh();
    } catch (err) {
      setOpportunities((rows) => rows.map((row) => (row.id === targetId ? previous : row)));
      setError(getUnknownErrorMessage(err, "Unable to update opportunity"));
    } finally {
      setEditSaving(false);
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
            <Link href="/employer/applications" className="btn-secondary">Manage Applications</Link>
            <Link href="/profile" className="btn-secondary">View Profile</Link>
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
            { label: "Shortlisted", value: summary?.shortlisted_applications ?? 0 },
            { label: "Interview", value: summary?.interview_applications ?? 0 },
            { label: "Rejected", value: summary?.rejected_applications ?? 0 },
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
                    <th style={{ padding: "0.55rem" }}>Lifecycle</th>
                    <th style={{ padding: "0.55rem" }}>Deadline</th>
                    <th style={{ padding: "0.55rem" }}>Applications</th>
                    <th style={{ padding: "0.55rem" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {opportunities.map((item) => (
                    <tr key={item.id} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                      <td style={{ padding: "0.55rem", fontWeight: 700 }}>{item.title}</td>
                      <td style={{ padding: "0.55rem" }}>{item.opportunity_type || "-"}</td>
                      <td style={{ padding: "0.55rem" }}>{item.domain || "-"}</td>
                      <td style={{ padding: "0.55rem", fontWeight: 700 }}>{item.lifecycle_status}</td>
                      <td style={{ padding: "0.55rem" }}>{stableDate(item.deadline)}</td>
                      <td style={{ padding: "0.55rem" }}>{item.applications_count}</td>
                      <td style={{ padding: "0.55rem" }}>
                        <div style={{ display: "flex", gap: "0.45rem", alignItems: "center" }}>
                          <select
                            className="input-base"
                            value={item.lifecycle_status}
                            onChange={(event) => {
                              void updateLifecycle(item.id, event.target.value as EmployerOpportunity["lifecycle_status"]);
                            }}
                            disabled={lifecycleUpdatingId === item.id || item.lifecycle_status === "closed"}
                            style={{ minWidth: "124px" }}
                          >
                            <option value="draft">draft</option>
                            <option value="published">published</option>
                            <option value="paused">paused</option>
                            <option value="closed">closed</option>
                          </select>
                          <a
                            href={item.application_url}
                            target="_blank"
                            rel="noreferrer"
                            className="btn-secondary"
                            style={{ textDecoration: "none", whiteSpace: "nowrap" }}
                          >
                            Open
                          </a>
                          <button
                            type="button"
                            className="btn-secondary"
                            onClick={() => openEditDrawer(item)}
                            style={{ whiteSpace: "nowrap" }}
                          >
                            Edit
                          </button>
                        </div>
                      </td>
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
                    <th style={{ padding: "0.55rem" }}>Pipeline</th>
                    <th style={{ padding: "0.55rem" }}>Created</th>
                    <th style={{ padding: "0.55rem" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.recent_applications.map((row) => (
                    <tr key={row.application_id} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                      <td style={{ padding: "0.55rem", fontWeight: 700 }}>{row.opportunity_title}</td>
                      <td style={{ padding: "0.55rem" }}>{row.applicant_name || "-"}</td>
                      <td style={{ padding: "0.55rem" }}>{row.applicant_email || "-"}</td>
                      <td style={{ padding: "0.55rem" }}>{row.status}</td>
                      <td style={{ padding: "0.55rem" }}>
                        <select
                          className="input-base"
                          value={pipelineDrafts[row.application_id] || row.pipeline_state || "applied"}
                          onChange={(event) => {
                            const value = event.target.value as EmployerApplication["pipeline_state"];
                            setPipelineDrafts((prev) => ({ ...prev, [row.application_id]: value }));
                          }}
                          disabled={pipelineUpdatingId === row.application_id}
                          style={{ minWidth: "124px" }}
                        >
                          <option value="applied">applied</option>
                          <option value="shortlisted">shortlisted</option>
                          <option value="interview">interview</option>
                          <option value="rejected">rejected</option>
                        </select>
                      </td>
                      <td style={{ padding: "0.55rem" }}>{stableDate(row.created_at)}</td>
                      <td style={{ padding: "0.55rem" }}>
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => {
                            void updatePipelineState(row.application_id);
                          }}
                          disabled={pipelineUpdatingId === row.application_id}
                          style={{ whiteSpace: "nowrap" }}
                        >
                          {pipelineUpdatingId === row.application_id ? "Saving..." : "Save Stage"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="card-panel" style={{ display: "grid", gap: "0.75rem" }}>
          <h2 style={{ fontSize: "1.4rem" }}>Recruiter Audit Trail</h2>
          {auditLogs.length === 0 ? (
            <p style={{ color: "var(--text-secondary)", fontWeight: 600 }}>No audit events yet.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "2px solid var(--border-subtle)" }}>
                    <th style={{ padding: "0.55rem" }}>Time</th>
                    <th style={{ padding: "0.55rem" }}>Action</th>
                    <th style={{ padding: "0.55rem" }}>Entity</th>
                    <th style={{ padding: "0.55rem" }}>Reference</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map((row) => (
                    <tr key={row.id} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                      <td style={{ padding: "0.55rem" }}>{stableDate(row.created_at)}</td>
                      <td style={{ padding: "0.55rem", fontWeight: 700 }}>{row.action}</td>
                      <td style={{ padding: "0.55rem" }}>{row.entity_type}</td>
                      <td style={{ padding: "0.55rem" }}>
                        {row.application_id || row.opportunity_id || row.entity_id || "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {editingOpportunity && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.25)",
            display: "flex",
            justifyContent: "flex-end",
            zIndex: 60,
          }}
          onClick={() => {
            if (!editSaving) {
              setEditingOpportunity(null);
            }
          }}
        >
          <aside
            className="card-panel"
            style={{
              width: "min(520px, 100%)",
              height: "100%",
              borderRadius: 0,
              borderLeft: "2px solid var(--border-subtle)",
              overflowY: "auto",
              padding: "1rem",
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <h2 style={{ fontSize: "1.4rem", marginBottom: "0.75rem" }}>Edit Opportunity</h2>
            <form onSubmit={handleSaveEdit} style={{ display: "grid", gap: "0.65rem" }}>
              <label style={{ fontWeight: 700 }}>Title</label>
              <input
                className="input-base"
                value={editingOpportunity.title}
                onChange={(event) => updateEditForm("title", event.target.value)}
                required
              />
              <label style={{ fontWeight: 700 }}>Description</label>
              <textarea
                className="input-base"
                rows={5}
                value={editingOpportunity.description}
                onChange={(event) => updateEditForm("description", event.target.value)}
                required
              />
              <label style={{ fontWeight: 700 }}>Application URL</label>
              <input
                className="input-base"
                value={editingOpportunity.application_url}
                onChange={(event) => updateEditForm("application_url", event.target.value)}
                required
              />
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.6rem" }}>
                <div>
                  <label style={{ fontWeight: 700 }}>Type</label>
                  <input
                    className="input-base"
                    value={editingOpportunity.opportunity_type}
                    onChange={(event) => updateEditForm("opportunity_type", event.target.value)}
                  />
                </div>
                <div>
                  <label style={{ fontWeight: 700 }}>Domain</label>
                  <input
                    className="input-base"
                    value={editingOpportunity.domain}
                    onChange={(event) => updateEditForm("domain", event.target.value)}
                  />
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.6rem" }}>
                <div>
                  <label style={{ fontWeight: 700 }}>Location</label>
                  <input
                    className="input-base"
                    value={editingOpportunity.location}
                    onChange={(event) => updateEditForm("location", event.target.value)}
                  />
                </div>
                <div>
                  <label style={{ fontWeight: 700 }}>Deadline</label>
                  <input
                    type="date"
                    className="input-base"
                    value={editingOpportunity.deadline}
                    onChange={(event) => updateEditForm("deadline", event.target.value)}
                  />
                </div>
              </div>
              <label style={{ fontWeight: 700 }}>Eligibility</label>
              <input
                className="input-base"
                value={editingOpportunity.eligibility}
                onChange={(event) => updateEditForm("eligibility", event.target.value)}
              />
              <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", marginTop: "0.5rem" }}>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setEditingOpportunity(null)}
                  disabled={editSaving}
                >
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={editSaving}>
                  {editSaving ? "Saving..." : "Save Changes"}
                </button>
              </div>
            </form>
          </aside>
        </div>
      )}
    </main>
  );
}
