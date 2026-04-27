"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { apiUrl } from "@/lib/api";
import { ADMIN_LOGIN_PATH } from "@/lib/admin-routes";
import { clearAccessToken, getAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";

type AdminOverview = {
  users_total: number;
  active_users: number;
  opportunities_total: number;
  social_posts_total: number;
  social_comments_total: number;
  jobs_dead_count: number;
  generated_at: string;
};

type Opportunity = {
  id: string;
  title: string;
  description: string;
  url: string;
  opportunity_type?: string | null;
  university?: string | null;
  domain?: string | null;
  source?: string | null;
  lifecycle_status: string;
  updated_at: string;
  deadline?: string | null;
};

type AdminJob = {
  id: string;
  job_type: string;
  status: string;
  attempts: number;
  max_attempts: number;
  created_at: string | null;
  updated_at: string | null;
  last_error?: string | null;
};

type AdminPost = {
  id: string;
  user_id: string;
  domain: string;
  content: string;
  likes_count: number;
  created_at: string;
};

type AdminComment = {
  id: string;
  post_id: string;
  user_id: string;
  content: string;
  created_at: string;
};

type AdminUser = {
  id: string;
  email: string;
  full_name?: string | null;
  account_type: string;
  auth_provider: string;
  is_active: boolean;
  is_admin: boolean;
};

type AuditEvent = {
  id: string;
  event_type: string;
  email?: string | null;
  success: boolean;
  reason?: string | null;
  created_at: string;
};

type OpportunityDraft = {
  title: string;
  description: string;
  url: string;
  opportunity_type: string;
  university: string;
  lifecycle_status: string;
};

const emptyOpportunityDraft: OpportunityDraft = {
  title: "",
  description: "",
  url: "",
  opportunity_type: "Opportunity",
  university: "Unknown",
  lifecycle_status: "published",
};

function authHeaders(token: string | null): Record<string, string> {
  if (!token || token === "__cookie_session__") {
    return {};
  }
  return { Authorization: `Bearer ${token}` };
}

export default function AdminOpsPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [jobs, setJobs] = useState<AdminJob[]>([]);
  const [posts, setPosts] = useState<AdminPost[]>([]);
  const [comments, setComments] = useState<AdminComment[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [oppDraft, setOppDraft] = useState<OpportunityDraft>(emptyOpportunityDraft);
  const [editingOpportunityId, setEditingOpportunityId] = useState<string | null>(null);
  const [jobType, setJobType] = useState("scraper.run");
  const [jobPayload, setJobPayload] = useState("{}");

  const sortedOpportunities = useMemo(
    () => [...opportunities].sort((a, b) => (a.updated_at > b.updated_at ? -1 : 1)),
    [opportunities],
  );

  const loadAdminData = useCallback(async () => {
    const token = getAccessToken();
    if (!token) {
      router.replace(ADMIN_LOGIN_PATH);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const headers = authHeaders(token);
      const meRes = await fetch(apiUrl("/api/v1/users/me"), {
        credentials: "include",
        headers,
      });
      const mePayload = await meRes.json().catch(() => ({}));
      if (!meRes.ok || !Boolean(mePayload.is_admin)) {
        clearAccessToken("logout");
        router.replace("/dashboard");
        return;
      }

      const [overviewRes, oppsRes, jobsRes, postsRes, commentsRes, usersRes, auditsRes] = await Promise.all([
        fetch(apiUrl("/api/v1/admin/overview"), { credentials: "include", headers }),
        fetch(apiUrl("/api/v1/admin/opportunities?limit=200"), { credentials: "include", headers }),
        fetch(apiUrl("/api/v1/admin/jobs/recent?limit=60"), { credentials: "include", headers }),
        fetch(apiUrl("/api/v1/admin/social/posts?limit=80"), { credentials: "include", headers }),
        fetch(apiUrl("/api/v1/admin/social/comments?limit=80"), { credentials: "include", headers }),
        fetch(apiUrl("/api/v1/admin/users?limit=120"), { credentials: "include", headers }),
        fetch(apiUrl("/api/v1/admin/audit-events?limit=120"), { credentials: "include", headers }),
      ]);

      const responses = [overviewRes, oppsRes, jobsRes, postsRes, commentsRes, usersRes, auditsRes];
      for (const response of responses) {
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(getApiErrorMessage(payload, "Unable to load admin dashboard data"));
        }
      }

      const [overviewPayload, oppsPayload, jobsPayload, postsPayload, commentsPayload, usersPayload, auditsPayload] =
        await Promise.all([
          overviewRes.json(),
          oppsRes.json(),
          jobsRes.json(),
          postsRes.json(),
          commentsRes.json(),
          usersRes.json(),
          auditsRes.json(),
        ]);

      setOverview(overviewPayload as AdminOverview);
      setOpportunities((oppsPayload as Opportunity[]) || []);
      setJobs((jobsPayload as AdminJob[]) || []);
      setPosts((postsPayload as AdminPost[]) || []);
      setComments((commentsPayload as AdminComment[]) || []);
      setUsers((usersPayload as AdminUser[]) || []);
      setAuditEvents((auditsPayload as AuditEvent[]) || []);
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to load admin data"));
    } finally {
      setLoading(false);
    }
  }, [router]);

  const saveOpportunity = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const token = getAccessToken();
    if (!token) {
      router.replace(ADMIN_LOGIN_PATH);
      return;
    }
    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const headers = {
        "Content-Type": "application/json",
        ...authHeaders(token),
      };
      const method = editingOpportunityId ? "PATCH" : "POST";
      const target = editingOpportunityId
        ? apiUrl(`/api/v1/admin/opportunities/${editingOpportunityId}`)
        : apiUrl("/api/v1/admin/opportunities");
      const response = await fetch(target, {
        method,
        credentials: "include",
        headers,
        body: JSON.stringify(oppDraft),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to save opportunity"));
      }
      setInfo(editingOpportunityId ? "Opportunity updated." : "Opportunity created.");
      setOppDraft(emptyOpportunityDraft);
      setEditingOpportunityId(null);
      await loadAdminData();
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to save opportunity"));
    } finally {
      setLoading(false);
    }
  };

  const startEdit = (row: Opportunity) => {
    setEditingOpportunityId(row.id);
    setOppDraft({
      title: row.title,
      description: row.description,
      url: row.url,
      opportunity_type: row.opportunity_type || "Opportunity",
      university: row.university || "Unknown",
      lifecycle_status: row.lifecycle_status || "published",
    });
  };

  const deleteOpportunity = async (id: string) => {
    const token = getAccessToken();
    if (!token) {
      router.replace(ADMIN_LOGIN_PATH);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/admin/opportunities/${id}`), {
        method: "DELETE",
        credentials: "include",
        headers: authHeaders(token),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to delete opportunity"));
      }
      setInfo("Opportunity deleted.");
      await loadAdminData();
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to delete opportunity"));
    } finally {
      setLoading(false);
    }
  };

  const enqueueJob = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const token = getAccessToken();
    if (!token) {
      router.replace(ADMIN_LOGIN_PATH);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const parsedPayload = JSON.parse(jobPayload || "{}");
      const response = await fetch(apiUrl("/api/v1/admin/jobs/enqueue"), {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(token),
        },
        body: JSON.stringify({
          job_type: jobType.trim(),
          payload: parsedPayload,
          max_attempts: 5,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to enqueue job"));
      }
      setInfo(`Job queued: ${String(payload.job_id || "")}`);
      await loadAdminData();
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to enqueue job"));
    } finally {
      setLoading(false);
    }
  };

  const deleteSocialRow = async (type: "post" | "comment", id: string) => {
    const token = getAccessToken();
    if (!token) {
      router.replace(ADMIN_LOGIN_PATH);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const endpoint =
        type === "post" ? `/api/v1/admin/social/posts/${id}` : `/api/v1/admin/social/comments/${id}`;
      const response = await fetch(apiUrl(endpoint), {
        method: "DELETE",
        credentials: "include",
        headers: authHeaders(token),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, `Unable to delete ${type}`));
      }
      setInfo(`${type === "post" ? "Post" : "Comment"} removed.`);
      await loadAdminData();
    } catch (err) {
      setError(getUnknownErrorMessage(err, `Unable to delete ${type}`));
    } finally {
      setLoading(false);
    }
  };

  const updateUserStatus = async (id: string, isActive: boolean) => {
    const token = getAccessToken();
    if (!token) {
      router.replace(ADMIN_LOGIN_PATH);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/admin/users/${id}/status`), {
        method: "PATCH",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(token),
        },
        body: JSON.stringify({ is_active: isActive }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to update user status"));
      }
      await loadAdminData();
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to update user status"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAdminData();
  }, [loadAdminData]);

  return (
    <main
      style={{
        minHeight: "100vh",
        padding: "1.25rem",
        background:
          "radial-gradient(circle at 18% 12%, rgba(34,197,94,0.08), transparent 30%), radial-gradient(circle at 85% 20%, rgba(59,130,246,0.08), transparent 28%), var(--bg-base)",
      }}
    >
      <section className="card-panel" style={{ padding: "1rem", marginBottom: "0.9rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", flexWrap: "wrap" }}>
          <div>
            <h1 style={{ marginBottom: "0.2rem" }}>Operations Console</h1>
            <p style={{ color: "var(--text-secondary)" }}>
              Privileged controls for opportunities, moderation, background jobs, and governance.
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button type="button" className="btn-secondary" onClick={() => void loadAdminData()} disabled={loading}>
              {loading ? "Refreshing..." : "Refresh"}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                clearAccessToken("logout");
                router.replace("/dashboard");
              }}
            >
              Logout
            </button>
          </div>
        </div>
        {error ? <p style={{ marginTop: "0.6rem", color: "#ef4444", fontWeight: 600 }}>{error}</p> : null}
        {!error && info ? <p style={{ marginTop: "0.6rem", color: "#16a34a", fontWeight: 600 }}>{info}</p> : null}
      </section>

      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0.75rem" }}>
        <article className="card-panel" style={{ padding: "0.9rem" }}>
          <h3>Users</h3>
          <p>{overview?.users_total ?? "-"}</p>
          <small style={{ color: "var(--text-secondary)" }}>Active: {overview?.active_users ?? "-"}</small>
        </article>
        <article className="card-panel" style={{ padding: "0.9rem" }}>
          <h3>Opportunities</h3>
          <p>{overview?.opportunities_total ?? "-"}</p>
        </article>
        <article className="card-panel" style={{ padding: "0.9rem" }}>
          <h3>Posts / Comments</h3>
          <p>
            {overview?.social_posts_total ?? "-"} / {overview?.social_comments_total ?? "-"}
          </p>
        </article>
        <article className="card-panel" style={{ padding: "0.9rem" }}>
          <h3>Dead Jobs</h3>
          <p>{overview?.jobs_dead_count ?? "-"}</p>
        </article>
      </section>

      <section className="card-panel" style={{ padding: "1rem", marginTop: "0.9rem" }}>
        <h2 style={{ marginBottom: "0.6rem" }}>{editingOpportunityId ? "Edit Opportunity" : "Create Opportunity"}</h2>
        <form onSubmit={saveOpportunity} style={{ display: "grid", gap: "0.6rem" }}>
          <input
            placeholder="Title"
            value={oppDraft.title}
            onChange={(event) => setOppDraft((prev) => ({ ...prev, title: event.target.value }))}
            required
          />
          <input
            placeholder="URL"
            value={oppDraft.url}
            onChange={(event) => setOppDraft((prev) => ({ ...prev, url: event.target.value }))}
            required
          />
          <textarea
            placeholder="Description"
            value={oppDraft.description}
            onChange={(event) => setOppDraft((prev) => ({ ...prev, description: event.target.value }))}
            rows={3}
            required
          />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.5rem" }}>
            <input
              placeholder="Type"
              value={oppDraft.opportunity_type}
              onChange={(event) => setOppDraft((prev) => ({ ...prev, opportunity_type: event.target.value }))}
            />
            <input
              placeholder="University/Org"
              value={oppDraft.university}
              onChange={(event) => setOppDraft((prev) => ({ ...prev, university: event.target.value }))}
            />
            <select
              value={oppDraft.lifecycle_status}
              onChange={(event) => setOppDraft((prev) => ({ ...prev, lifecycle_status: event.target.value }))}
            >
              <option value="draft">draft</option>
              <option value="published">published</option>
              <option value="paused">paused</option>
              <option value="closed">closed</option>
            </select>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button type="submit" className="btn-primary" disabled={loading}>
              {editingOpportunityId ? "Update Opportunity" : "Create Opportunity"}
            </button>
            {editingOpportunityId ? (
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  setEditingOpportunityId(null);
                  setOppDraft(emptyOpportunityDraft);
                }}
              >
                Cancel Edit
              </button>
            ) : null}
          </div>
        </form>
      </section>

      <section className="card-panel" style={{ padding: "1rem", marginTop: "0.9rem" }}>
        <h2 style={{ marginBottom: "0.6rem" }}>Opportunities</h2>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th align="left">Title</th>
                <th align="left">Status</th>
                <th align="left">Updated</th>
                <th align="left">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedOpportunities.map((row) => (
                <tr key={row.id} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                  <td style={{ padding: "0.45rem 0.15rem" }}>{row.title}</td>
                  <td>{row.lifecycle_status}</td>
                  <td>{new Date(row.updated_at).toLocaleString()}</td>
                  <td style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", padding: "0.35rem 0.1rem" }}>
                    <button type="button" className="btn-secondary" onClick={() => startEdit(row)} disabled={loading}>
                      Edit
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => void deleteOpportunity(row.id)}
                      disabled={loading}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card-panel" style={{ padding: "1rem", marginTop: "0.9rem" }}>
        <h2 style={{ marginBottom: "0.6rem" }}>Jobs and Queue Control</h2>
        <form onSubmit={enqueueJob} style={{ display: "grid", gap: "0.5rem", marginBottom: "0.8rem" }}>
          <input value={jobType} onChange={(event) => setJobType(event.target.value)} placeholder="job_type" required />
          <textarea
            rows={3}
            value={jobPayload}
            onChange={(event) => setJobPayload(event.target.value)}
            placeholder='{"lookback_days": 30}'
          />
          <button type="submit" className="btn-primary" disabled={loading}>
            Enqueue Job
          </button>
        </form>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th align="left">Type</th>
                <th align="left">Status</th>
                <th align="left">Attempts</th>
                <th align="left">Updated</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                  <td style={{ padding: "0.4rem 0.1rem" }}>{job.job_type}</td>
                  <td>{job.status}</td>
                  <td>
                    {job.attempts}/{job.max_attempts}
                  </td>
                  <td>{job.updated_at ? new Date(job.updated_at).toLocaleString() : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card-panel" style={{ padding: "1rem", marginTop: "0.9rem" }}>
        <h2 style={{ marginBottom: "0.6rem" }}>Content Moderation</h2>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.9rem" }}>
          <div>
            <h3>Posts</h3>
            {posts.map((post) => (
              <article key={post.id} style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: "0.55rem", marginTop: "0.55rem" }}>
                <p style={{ marginBottom: "0.3rem" }}>{post.content}</p>
                <small style={{ color: "var(--text-secondary)" }}>
                  domain={post.domain} user={post.user_id}
                </small>
                <div style={{ marginTop: "0.35rem" }}>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => void deleteSocialRow("post", post.id)}
                    disabled={loading}
                  >
                    Delete Post
                  </button>
                </div>
              </article>
            ))}
          </div>
          <div>
            <h3>Comments</h3>
            {comments.map((comment) => (
              <article
                key={comment.id}
                style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: "0.55rem", marginTop: "0.55rem" }}
              >
                <p style={{ marginBottom: "0.3rem" }}>{comment.content}</p>
                <small style={{ color: "var(--text-secondary)" }}>
                  post={comment.post_id} user={comment.user_id}
                </small>
                <div style={{ marginTop: "0.35rem" }}>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => void deleteSocialRow("comment", comment.id)}
                    disabled={loading}
                  >
                    Delete Comment
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="card-panel" style={{ padding: "1rem", marginTop: "0.9rem" }}>
        <h2 style={{ marginBottom: "0.6rem" }}>User Governance</h2>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th align="left">Email</th>
                <th align="left">Type</th>
                <th align="left">Provider</th>
                <th align="left">State</th>
                <th align="left">Action</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                  <td style={{ padding: "0.4rem 0.1rem" }}>{user.email}</td>
                  <td>{user.account_type}</td>
                  <td>{user.auth_provider}</td>
                  <td>{user.is_active ? "active" : "inactive"}</td>
                  <td style={{ padding: "0.4rem 0.1rem" }}>
                    {user.is_admin ? (
                      <small style={{ color: "var(--text-secondary)" }}>locked</small>
                    ) : (
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => void updateUserStatus(user.id, !user.is_active)}
                        disabled={loading}
                      >
                        {user.is_active ? "Deactivate" : "Activate"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card-panel" style={{ padding: "1rem", marginTop: "0.9rem" }}>
        <h2 style={{ marginBottom: "0.6rem" }}>Audit Stream</h2>
        <div style={{ maxHeight: "320px", overflowY: "auto", display: "grid", gap: "0.45rem" }}>
          {auditEvents.map((eventRow) => (
            <article key={eventRow.id} style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: "0.5rem" }}>
              <p style={{ marginBottom: "0.15rem" }}>
                <strong>{eventRow.event_type}</strong> {eventRow.success ? "ok" : "failed"}
              </p>
              <small style={{ color: "var(--text-secondary)" }}>
                {eventRow.email || "n/a"} · {new Date(eventRow.created_at).toLocaleString()}
              </small>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
