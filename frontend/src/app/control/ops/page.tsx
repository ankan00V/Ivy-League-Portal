"use client";

import { type CSSProperties, type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  Archive,
  Bot,
  BriefcaseBusiness,
  EyeOff,
  FileClock,
  LogOut,
  Pencil,
  RefreshCw,
  Shield,
  Trash2,
  Trophy,
  Users2,
} from "lucide-react";

import PageHeader from "@/components/ui/PageHeader";
import PillGroup from "@/components/ui/PillGroup";
import MetricCard from "@/components/ui/MetricCard";
import { apiUrl } from "@/lib/api";
import { ADMIN_LOGIN_PATH } from "@/lib/admin-routes";
import { clearAccessToken, getAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";

type AdminOverview = {
  users_total: number;
  active_users: number;
  opportunities_total: number;
  active_opportunities_total: number;
  expired_opportunities_total: number;
  inactive_opportunities_total: number;
  social_posts_total: number;
  social_comments_total: number;
  jobs_dead_count: number;
  generated_at: string;
};

type OpportunityPortal = "career" | "competitive" | "other";
type OpportunityLifecycle = "draft" | "published" | "paused" | "closed";

type Opportunity = {
  id: string;
  title: string;
  description: string;
  url: string;
  opportunity_type?: string | null;
  portal_category: OpportunityPortal;
  university?: string | null;
  domain?: string | null;
  source?: string | null;
  location?: string | null;
  eligibility?: string | null;
  ppo_available?: string | null;
  lifecycle_status: OpportunityLifecycle;
  duration_start?: string | null;
  duration_end?: string | null;
  deadline?: string | null;
  is_expired: boolean;
  visible_on_student_portal: boolean;
  updated_at: string;
  created_at: string;
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

type AdminSection =
  | "overview"
  | "create"
  | "active"
  | "expired"
  | "inactive"
  | "automation"
  | "community"
  | "users"
  | "audit";

type OpportunityDraft = {
  title: string;
  description: string;
  url: string;
  opportunity_type: string;
  university: string;
  domain: string;
  ppo_available: string;
  duration_start: string;
  duration_end: string;
  deadline: string;
  lifecycle_status: OpportunityLifecycle;
};

const emptyOpportunityDraft: OpportunityDraft = {
  title: "",
  description: "",
  url: "",
  opportunity_type: "job",
  university: "Unknown",
  domain: "",
  ppo_available: "undefined",
  duration_start: "",
  duration_end: "",
  deadline: "",
  lifecycle_status: "published",
};

const sectionMeta: Array<{
  key: AdminSection;
  label: string;
  icon: typeof BriefcaseBusiness;
  description: string;
}> = [
  { key: "overview", label: "Overview", icon: Activity, description: "Live posture and routing counts" },
  { key: "create", label: "Create", icon: BriefcaseBusiness, description: "Publish and edit opportunities" },
  { key: "active", label: "Live", icon: Shield, description: "Visible on student portals now" },
  { key: "expired", label: "Expired", icon: FileClock, description: "Past deadline, editable for resurfacing" },
  { key: "inactive", label: "Inactive", icon: EyeOff, description: "Draft, paused, or manually closed" },
  { key: "automation", label: "Jobs", icon: Bot, description: "Queue and background operations" },
  { key: "community", label: "Community", icon: Trophy, description: "Posts and comments moderation" },
  { key: "users", label: "Users", icon: Users2, description: "Access and account controls" },
  { key: "audit", label: "Audit", icon: Archive, description: "Authentication and admin trail" },
];

function authHeaders(token: string | null): Record<string, string> {
  if (!token || token === "__cookie_session__") {
    return {};
  }
  return { Authorization: `Bearer ${token}` };
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function toDateInput(value?: string | null): string {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}`;
}

function toDateTimeInput(value?: string | null): string {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

function toIsoDate(value: string): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

function toIsoDateTime(value: string): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

function formatDateTime(value?: string | null): string {
  if (!value) {
    return "Not set";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Not set";
  }
  return parsed.toLocaleString();
}

function formatMonthRange(start?: string | null, end?: string | null): string {
  if (!start || !end) {
    return "Not set";
  }
  const startValue = new Date(start);
  const endValue = new Date(end);
  if (Number.isNaN(startValue.getTime()) || Number.isNaN(endValue.getTime())) {
    return "Not set";
  }
  const formatter = new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" });
  return `${formatter.format(startValue)} - ${formatter.format(endValue)}`;
}

function formatMonthSummary(value: string): string {
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return "Select a date";
  }
  return new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" }).format(parsed);
}

function portalLabel(portal: OpportunityPortal): string {
  if (portal === "career") {
    return "Go Portal";
  }
  if (portal === "competitive") {
    return "Opportunities Page";
  }
  return "Other";
}

function panelStyle(background = "var(--bg-surface)"): CSSProperties {
  return {
    border: "2px solid var(--border-subtle)",
    borderRadius: "var(--radius-md)",
    background,
    boxShadow: "var(--shadow-sm)",
  };
}

function actionButtonStyle(
  tone: "edit" | "publish" | "mute" | "delete" | "neutral",
): CSSProperties {
  const tones: Record<string, CSSProperties> = {
    edit: {
      background: "var(--brand-primary)",
      color: "#000000",
    },
    publish: {
      background: "var(--brand-accent)",
      color: "#000000",
    },
    mute: {
      background: "color-mix(in srgb, var(--accent-cyan) 26%, var(--bg-surface))",
      color: "var(--text-primary)",
    },
    delete: {
      background: "color-mix(in srgb, #ef4444 22%, var(--bg-surface))",
      color: "var(--text-primary)",
    },
    neutral: {
      background: "var(--bg-surface)",
      color: "var(--text-primary)",
    },
  };

  return {
    border: "2px solid var(--border-subtle)",
    borderRadius: "var(--radius-sm)",
    padding: "0.58rem 0.82rem",
    fontWeight: 800,
    fontSize: "0.86rem",
    boxShadow: "var(--shadow-sm)",
    ...tones[tone],
  };
}

function SectionShell({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section style={{ ...panelStyle(), padding: "1.15rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", marginBottom: "0.95rem" }}>
        <div style={{ minWidth: 0 }}>
          <h2 style={{ marginBottom: "0.2rem", fontSize: "1.4rem" }}>{title}</h2>
          {subtitle ? <p style={{ color: "var(--text-secondary)" }}>{subtitle}</p> : null}
        </div>
        {actions ? <div style={{ display: "flex", gap: "0.55rem", flexWrap: "wrap" }}>{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

function OpportunityTable({
  title,
  subtitle,
  rows,
  loading,
  onEdit,
  onLifecycleChange,
  onDelete,
}: {
  title: string;
  subtitle: string;
  rows: Opportunity[];
  loading: boolean;
  onEdit: (row: Opportunity) => void;
  onLifecycleChange: (id: string, lifecycle: OpportunityLifecycle) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div style={{ display: "grid", gap: "0.65rem" }}>
      <div>
        <h3 style={{ fontSize: "1.1rem", marginBottom: "0.15rem" }}>{title}</h3>
        <p style={{ color: "var(--text-secondary)", fontSize: "0.94rem" }}>{subtitle}</p>
      </div>
      <div style={{ overflowX: "auto", ...panelStyle("var(--bg-base)") }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: "940px" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid var(--border-subtle)" }}>
              <th align="left" style={{ padding: "0.8rem 0.9rem", fontSize: "0.78rem", textTransform: "uppercase" }}>Title</th>
              <th align="left" style={{ padding: "0.8rem 0.9rem", fontSize: "0.78rem", textTransform: "uppercase" }}>Type</th>
              <th align="left" style={{ padding: "0.8rem 0.9rem", fontSize: "0.78rem", textTransform: "uppercase" }}>Duration</th>
              <th align="left" style={{ padding: "0.8rem 0.9rem", fontSize: "0.78rem", textTransform: "uppercase" }}>Deadline</th>
              <th align="left" style={{ padding: "0.8rem 0.9rem", fontSize: "0.78rem", textTransform: "uppercase" }}>Portal</th>
              <th align="left" style={{ padding: "0.8rem 0.9rem", fontSize: "0.78rem", textTransform: "uppercase" }}>Status</th>
              <th align="left" style={{ padding: "0.8rem 0.9rem", fontSize: "0.78rem", textTransform: "uppercase" }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ padding: "1rem 0.9rem", color: "var(--text-secondary)" }}>
                  No rows here.
                </td>
              </tr>
            ) : null}
            {rows.map((row) => (
              <tr key={row.id} style={{ borderTop: "1px solid color-mix(in srgb, var(--border-subtle) 30%, transparent)" }}>
                <td style={{ padding: "0.9rem" }}>
                  <div style={{ display: "grid", gap: "0.2rem" }}>
                    <strong style={{ color: "var(--text-primary)" }}>{row.title}</strong>
                    <span style={{ color: "var(--text-secondary)", fontSize: "0.88rem" }}>
                      {row.university || "Unknown"}{row.domain ? ` · ${row.domain}` : ""}
                    </span>
                    {String(row.opportunity_type || "").toLowerCase() === "internship" ? (
                      <span style={{ color: "var(--text-secondary)", fontSize: "0.82rem" }}>
                        PPO: {row.ppo_available || "undefined"}
                      </span>
                    ) : null}
                  </div>
                </td>
                <td style={{ padding: "0.9rem", fontWeight: 700 }}>{row.opportunity_type || "Opportunity"}</td>
                <td style={{ padding: "0.9rem" }}>{formatMonthRange(row.duration_start, row.duration_end)}</td>
                <td style={{ padding: "0.9rem" }}>{formatDateTime(row.deadline)}</td>
                <td style={{ padding: "0.9rem" }}>
                  <span
                    style={{
                      display: "inline-flex",
                      padding: "0.22rem 0.55rem",
                      borderRadius: "999px",
                      border: "2px solid var(--border-subtle)",
                      background: row.portal_category === "career" ? "var(--brand-primary)" : "var(--brand-accent)",
                      color: "#000000",
                      fontWeight: 900,
                      fontSize: "0.75rem",
                    }}
                  >
                    {portalLabel(row.portal_category)}
                  </span>
                </td>
                <td style={{ padding: "0.9rem" }}>
                  <div style={{ display: "grid", gap: "0.2rem" }}>
                    <span style={{ fontWeight: 800, color: "var(--text-primary)" }}>{row.lifecycle_status}</span>
                    <span style={{ color: row.visible_on_student_portal ? "#15803d" : "var(--text-secondary)", fontSize: "0.84rem" }}>
                      {row.visible_on_student_portal ? "Visible to students" : row.is_expired ? "Expired" : "Hidden from students"}
                    </span>
                  </div>
                </td>
                <td style={{ padding: "0.9rem" }}>
                  <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                    <button type="button" style={actionButtonStyle("edit")} onClick={() => onEdit(row)} disabled={loading}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
                        <Pencil size={14} /> Edit
                      </span>
                    </button>
                    {row.lifecycle_status !== "published" ? (
                      <button type="button" style={actionButtonStyle("publish")} onClick={() => onLifecycleChange(row.id, "published")} disabled={loading}>
                        Publish
                      </button>
                    ) : (
                      <button type="button" style={actionButtonStyle("mute")} onClick={() => onLifecycleChange(row.id, "paused")} disabled={loading}>
                        Unpublish
                      </button>
                    )}
                    <button type="button" style={actionButtonStyle("delete")} onClick={() => onDelete(row.id)} disabled={loading}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
                        <Trash2 size={14} /> Delete
                      </span>
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function AdminOpsPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<AdminSection>("overview");
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
    () => [...opportunities].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()),
    [opportunities],
  );

  const activeOpportunities = useMemo(
    () => sortedOpportunities.filter((row) => row.visible_on_student_portal),
    [sortedOpportunities],
  );
  const expiredOpportunities = useMemo(
    () => sortedOpportunities.filter((row) => row.is_expired),
    [sortedOpportunities],
  );
  const inactiveOpportunities = useMemo(
    () => sortedOpportunities.filter((row) => !row.is_expired && row.lifecycle_status !== "published"),
    [sortedOpportunities],
  );

  const splitByPortal = useCallback((rows: Opportunity[]) => {
    return {
      career: rows.filter((row) => row.portal_category === "career"),
      competitive: rows.filter((row) => row.portal_category !== "career"),
    };
  }, []);

  const activeGrouped = useMemo(() => splitByPortal(activeOpportunities), [activeOpportunities, splitByPortal]);
  const expiredGrouped = useMemo(() => splitByPortal(expiredOpportunities), [expiredOpportunities, splitByPortal]);

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
      const meRes = await fetch(apiUrl("/api/v1/users/me"), { credentials: "include", headers });
      const mePayload = await meRes.json().catch(() => ({}));
      if (!meRes.ok || !Boolean(mePayload.is_admin)) {
        clearAccessToken("logout");
        router.replace("/dashboard");
        return;
      }

      const [overviewRes, oppsRes, jobsRes, postsRes, commentsRes, usersRes, auditsRes] = await Promise.all([
        fetch(apiUrl("/api/v1/admin/overview"), { credentials: "include", headers }),
        fetch(apiUrl("/api/v1/admin/opportunities?limit=240"), { credentials: "include", headers }),
        fetch(apiUrl("/api/v1/admin/jobs/recent?limit=60"), { credentials: "include", headers }),
        fetch(apiUrl("/api/v1/admin/social/posts?limit=80"), { credentials: "include", headers }),
        fetch(apiUrl("/api/v1/admin/social/comments?limit=80"), { credentials: "include", headers }),
        fetch(apiUrl("/api/v1/admin/users?limit=120"), { credentials: "include", headers }),
        fetch(apiUrl("/api/v1/admin/audit-events?limit=120"), { credentials: "include", headers }),
      ]);

      for (const response of [overviewRes, oppsRes, jobsRes, postsRes, commentsRes, usersRes, auditsRes]) {
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

  useEffect(() => {
    void loadAdminData();
  }, [loadAdminData]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      void loadAdminData();
    }, 15000);
    const onFocus = () => {
      void loadAdminData();
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void loadAdminData();
      }
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [loadAdminData]);

  const resetOpportunityDraft = () => {
    setOppDraft(emptyOpportunityDraft);
    setEditingOpportunityId(null);
  };

  const saveOpportunity = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const token = getAccessToken();
    if (!token) {
      router.replace(ADMIN_LOGIN_PATH);
      return;
    }

    const durationStart = toIsoDate(oppDraft.duration_start);
    const durationEnd = toIsoDate(oppDraft.duration_end);
    const deadline = toIsoDateTime(oppDraft.deadline);
    if (!durationStart || !durationEnd || !deadline) {
      setError("Duration start, duration end, and application deadline are required.");
      return;
    }

    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const response = await fetch(
        editingOpportunityId ? apiUrl(`/api/v1/admin/opportunities/${editingOpportunityId}`) : apiUrl("/api/v1/admin/opportunities"),
        {
          method: editingOpportunityId ? "PATCH" : "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            ...authHeaders(token),
          },
          body: JSON.stringify({
            title: oppDraft.title.trim(),
            description: oppDraft.description.trim(),
            url: oppDraft.url.trim(),
            opportunity_type: oppDraft.opportunity_type,
            university: oppDraft.university.trim() || "Unknown",
            domain: oppDraft.domain.trim() || null,
            ppo_available: oppDraft.opportunity_type === "internship" ? oppDraft.ppo_available : null,
            duration_start: durationStart,
            duration_end: durationEnd,
            deadline,
            lifecycle_status: oppDraft.lifecycle_status,
          }),
        },
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to save opportunity"));
      }
      setInfo(editingOpportunityId ? "Opportunity updated." : "Opportunity created.");
      resetOpportunityDraft();
      setActiveSection("active");
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
      opportunity_type: (row.opportunity_type || "Job").toLowerCase(),
      university: row.university || "Unknown",
      domain: row.domain || "",
      ppo_available: row.ppo_available || "undefined",
      duration_start: toDateInput(row.duration_start),
      duration_end: toDateInput(row.duration_end),
      deadline: toDateTimeInput(row.deadline),
      lifecycle_status: row.lifecycle_status,
    });
    setActiveSection("create");
    setInfo(`Editing "${row.title}". Update the deadline to resurface expired opportunities.`);
  };

  const changeLifecycleStatus = async (id: string, lifecycleStatus: OpportunityLifecycle) => {
    const token = getAccessToken();
    if (!token) {
      router.replace(ADMIN_LOGIN_PATH);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/admin/opportunities/${id}`), {
        method: "PATCH",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(token),
        },
        body: JSON.stringify({ lifecycle_status: lifecycleStatus }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to update opportunity status"));
      }
      setInfo(`Opportunity marked ${lifecycleStatus}.`);
      await loadAdminData();
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to update opportunity status"));
    } finally {
      setLoading(false);
    }
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
      setInfo("Opportunity permanently deleted.");
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
      const endpoint = type === "post" ? `/api/v1/admin/social/posts/${id}` : `/api/v1/admin/social/comments/${id}`;
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
      setInfo(`User ${isActive ? "activated" : "deactivated"}.`);
      await loadAdminData();
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to update user status"));
    } finally {
      setLoading(false);
    }
  };

  const currentSectionMeta = sectionMeta.find((item) => item.key === activeSection);

  return (
    <main
      style={{
        minHeight: "100vh",
        padding: "1.4rem",
        background:
          "radial-gradient(circle at 12% 16%, color-mix(in srgb, var(--brand-primary) 18%, transparent), transparent 32%), radial-gradient(circle at 88% 10%, color-mix(in srgb, var(--brand-accent) 16%, transparent), transparent 24%), var(--bg-base)",
      }}
    >
      <PageHeader
        title="Operations Console"
        subtitle="A cleaner admin workspace for publishing, routing, expiry control, moderation, and platform jobs."
        kicker="Admin"
        status={
          <>
            <span style={{ ...panelStyle("var(--bg-surface)"), padding: "0.35rem 0.65rem", fontWeight: 800 }}>
              {overview ? `Updated ${new Date(overview.generated_at).toLocaleTimeString()}` : "Loading snapshot"}
            </span>
            {currentSectionMeta ? (
              <span style={{ ...panelStyle("var(--bg-surface-hover)"), padding: "0.35rem 0.65rem", fontWeight: 800 }}>
                {currentSectionMeta.label}: {currentSectionMeta.description}
              </span>
            ) : null}
          </>
        }
        actions={
          <>
            <button type="button" style={actionButtonStyle("neutral")} onClick={() => void loadAdminData()} disabled={loading}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: "0.45rem" }}>
                <RefreshCw size={15} /> {loading ? "Refreshing..." : "Refresh"}
              </span>
            </button>
            <button
              type="button"
              style={actionButtonStyle("mute")}
              onClick={() => {
                clearAccessToken("logout");
                router.replace("/dashboard");
              }}
            >
              <span style={{ display: "inline-flex", alignItems: "center", gap: "0.45rem" }}>
                <LogOut size={15} /> Logout
              </span>
            </button>
          </>
        }
      />

      {error ? <p style={{ marginTop: "0.65rem", color: "#dc2626", fontWeight: 700 }}>{error}</p> : null}
      {!error && info ? <p style={{ marginTop: "0.65rem", color: "#15803d", fontWeight: 700 }}>{info}</p> : null}

      <section style={{ marginTop: "1rem", marginBottom: "1rem" }}>
        <PillGroup>
          {sectionMeta.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setActiveSection(key)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.45rem",
                padding: "0.72rem 0.95rem",
                borderRadius: "999px",
                border: "2px solid var(--border-subtle)",
                background: activeSection === key ? "var(--brand-primary)" : "var(--bg-surface)",
                color: activeSection === key ? "#000000" : "var(--text-primary)",
                boxShadow: "var(--shadow-sm)",
                fontWeight: 800,
              }}
            >
              <Icon size={15} />
              {label}
            </button>
          ))}
        </PillGroup>
      </section>

      {activeSection === "overview" ? (
        <section style={{ display: "grid", gap: "1rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.8rem" }}>
            <MetricCard label="Students / Employers" value={overview?.users_total ?? "-"} hint={`Active: ${overview?.active_users ?? "-"}`} />
            <MetricCard label="Live Opportunities" value={overview?.active_opportunities_total ?? "-"} hint="Visible on student portals" tone="primary" />
            <MetricCard label="Expired Opportunities" value={overview?.expired_opportunities_total ?? "-"} hint="Past deadline, edit to resurface" />
            <MetricCard label="Inactive Opportunities" value={overview?.inactive_opportunities_total ?? "-"} hint="Draft, paused, or closed" />
            <MetricCard label="Dead Background Jobs" value={overview?.jobs_dead_count ?? "-"} hint="Needs admin intervention" tone="accent" />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "0.8rem" }}>
            <button type="button" style={{ ...panelStyle(), padding: "1rem", textAlign: "left" }} onClick={() => setActiveSection("create")}>
              <h3 style={{ fontSize: "1.12rem" }}>Publish a new opportunity</h3>
              <p style={{ color: "var(--text-secondary)" }}>
                Admin-created Hiring Challenges, Internships, and Jobs route into Go Portal. Competitive items route into Opportunities Page.
              </p>
            </button>
            <button type="button" style={{ ...panelStyle(), padding: "1rem", textAlign: "left" }} onClick={() => setActiveSection("expired")}>
              <h3 style={{ fontSize: "1.12rem" }}>Resurface expired listings</h3>
              <p style={{ color: "var(--text-secondary)" }}>
                Expired items are already hidden from students. Extend the deadline and republish them from the expired tab.
              </p>
            </button>
            <button type="button" style={{ ...panelStyle(), padding: "1rem", textAlign: "left" }} onClick={() => setActiveSection("automation")}>
              <h3 style={{ fontSize: "1.12rem" }}>Queue operational jobs</h3>
              <p style={{ color: "var(--text-secondary)" }}>
                Scraper refresh, analytics work, and incident follow-up stay isolated from publishing controls.
              </p>
            </button>
          </div>
        </section>
      ) : null}

      {activeSection === "create" ? (
        <SectionShell
          title={editingOpportunityId ? "Edit Opportunity" : "Create Opportunity"}
          subtitle="Title, URL, JD, type, duration range, and application close time are required for admin-managed listings."
          actions={
            editingOpportunityId ? (
              <button type="button" style={actionButtonStyle("neutral")} onClick={resetOpportunityDraft}>
                Cancel Edit
              </button>
            ) : undefined
          }
        >
          <form onSubmit={saveOpportunity} style={{ display: "grid", gap: "0.9rem" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "0.8rem" }}>
              <label style={{ display: "grid", gap: "0.35rem" }}>
                <span style={{ fontWeight: 700 }}>Title</span>
                <input value={oppDraft.title} onChange={(event) => setOppDraft((prev) => ({ ...prev, title: event.target.value }))} required />
              </label>
              <label style={{ display: "grid", gap: "0.35rem" }}>
                <span style={{ fontWeight: 700 }}>Application URL</span>
                <input value={oppDraft.url} onChange={(event) => setOppDraft((prev) => ({ ...prev, url: event.target.value }))} required />
              </label>
            </div>

            <label style={{ display: "grid", gap: "0.35rem" }}>
              <span style={{ fontWeight: 700 }}>JD / Details</span>
              <textarea
                rows={5}
                value={oppDraft.description}
                onChange={(event) => setOppDraft((prev) => ({ ...prev, description: event.target.value }))}
                required
              />
            </label>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "0.8rem" }}>
              <label style={{ display: "grid", gap: "0.35rem" }}>
                <span style={{ fontWeight: 700 }}>Opportunity Type</span>
                <select
                  value={oppDraft.opportunity_type}
                  onChange={(event) =>
                    setOppDraft((prev) => ({
                      ...prev,
                      opportunity_type: event.target.value,
                      ppo_available: event.target.value === "internship" ? prev.ppo_available : "undefined",
                    }))
                  }
                >
                  <optgroup label="Career">
                    <option value="hiring challenge">Hiring Challenge</option>
                    <option value="internship">Internship</option>
                    <option value="job">Job</option>
                  </optgroup>
                  <optgroup label="Competitive">
                    <option value="competition">Competition</option>
                    <option value="hackathon">Hackathon</option>
                  </optgroup>
                </select>
              </label>
              <label style={{ display: "grid", gap: "0.35rem" }}>
                <span style={{ fontWeight: 700 }}>Organization / University</span>
                <input value={oppDraft.university} onChange={(event) => setOppDraft((prev) => ({ ...prev, university: event.target.value }))} />
              </label>
              <label style={{ display: "grid", gap: "0.35rem" }}>
                <span style={{ fontWeight: 700 }}>Domain</span>
                <input value={oppDraft.domain} onChange={(event) => setOppDraft((prev) => ({ ...prev, domain: event.target.value }))} />
              </label>
            </div>

            {oppDraft.opportunity_type === "internship" ? (
              <label style={{ display: "grid", gap: "0.35rem", maxWidth: "320px" }}>
                <span style={{ fontWeight: 700 }}>PPO Available</span>
                <select
                  value={oppDraft.ppo_available}
                  onChange={(event) => setOppDraft((prev) => ({ ...prev, ppo_available: event.target.value }))}
                >
                  <option value="yes">Yes</option>
                  <option value="no">No</option>
                  <option value="undefined">Undefined</option>
                </select>
              </label>
            ) : null}

            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "0.8rem" }}>
              <label style={{ display: "grid", gap: "0.35rem" }}>
                <span style={{ fontWeight: 700 }}>Duration Start</span>
                <input type="date" value={oppDraft.duration_start} onChange={(event) => setOppDraft((prev) => ({ ...prev, duration_start: event.target.value }))} required />
                <small style={{ color: "var(--text-secondary)" }}>
                  {oppDraft.duration_start ? `Month / Year: ${formatMonthSummary(oppDraft.duration_start)}` : "Select a calendar date. The month/year is derived automatically."}
                </small>
              </label>
              <label style={{ display: "grid", gap: "0.35rem" }}>
                <span style={{ fontWeight: 700 }}>Duration End</span>
                <input type="date" value={oppDraft.duration_end} onChange={(event) => setOppDraft((prev) => ({ ...prev, duration_end: event.target.value }))} required />
                <small style={{ color: "var(--text-secondary)" }}>
                  {oppDraft.duration_end ? `Month / Year: ${formatMonthSummary(oppDraft.duration_end)}` : "Select a calendar date. The month/year is derived automatically."}
                </small>
              </label>
              <label style={{ display: "grid", gap: "0.35rem" }}>
                <span style={{ fontWeight: 700 }}>Last Date & Time to Apply</span>
                <input type="datetime-local" value={oppDraft.deadline} onChange={(event) => setOppDraft((prev) => ({ ...prev, deadline: event.target.value }))} required />
              </label>
            </div>

            <div style={{ ...panelStyle("var(--bg-base)"), padding: "0.85rem", display: "grid", gap: "0.35rem" }}>
              <strong style={{ color: "var(--text-primary)" }}>Automatic routing</strong>
              <p style={{ color: "var(--text-secondary)" }}>
                Hiring Challenges, Internships, and Jobs appear in Go Portal. Competitions and Hackathons appear on the Opportunities page.
                Once the deadline passes, the listing disappears from student surfaces automatically and moves to the Expired tab here.
              </p>
            </div>

            <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
              <button type="submit" style={actionButtonStyle("publish")} disabled={loading}>
                {editingOpportunityId ? "Save Opportunity" : "Create Opportunity"}
              </button>
              <button type="button" style={actionButtonStyle("neutral")} onClick={() => setActiveSection("active")}>
                View Live Listings
              </button>
            </div>
          </form>
        </SectionShell>
      ) : null}

      {activeSection === "active" ? (
        <section style={{ display: "grid", gap: "1rem" }}>
          <SectionShell title="Live Listings" subtitle="These are currently visible to students. Use separate tables for the two candidate-facing portals.">
            <div style={{ display: "grid", gap: "1rem" }}>
              <OpportunityTable
                title="Go Portal"
                subtitle="Hiring Challenges, Internships, and Jobs."
                rows={activeGrouped.career}
                loading={loading}
                onEdit={startEdit}
                onLifecycleChange={(id, lifecycle) => void changeLifecycleStatus(id, lifecycle)}
                onDelete={(id) => void deleteOpportunity(id)}
              />
              <OpportunityTable
                title="Opportunities Page"
                subtitle="Competitions, Hackathons, and other competitive opportunities."
                rows={activeGrouped.competitive}
                loading={loading}
                onEdit={startEdit}
                onLifecycleChange={(id, lifecycle) => void changeLifecycleStatus(id, lifecycle)}
                onDelete={(id) => void deleteOpportunity(id)}
              />
            </div>
          </SectionShell>
        </section>
      ) : null}

      {activeSection === "expired" ? (
        <SectionShell title="Expired Listings" subtitle="These are already hidden from student portals because the deadline has passed. Edit the deadline and republish to resurface them.">
          <div style={{ display: "grid", gap: "1rem" }}>
            <OpportunityTable
              title="Expired Go Portal listings"
              subtitle="Career opportunities that need a new deadline before going back live."
              rows={expiredGrouped.career}
              loading={loading}
              onEdit={startEdit}
              onLifecycleChange={(id, lifecycle) => void changeLifecycleStatus(id, lifecycle)}
              onDelete={(id) => void deleteOpportunity(id)}
            />
            <OpportunityTable
              title="Expired Opportunities Page listings"
              subtitle="Competitive items that can be rescheduled or removed."
              rows={expiredGrouped.competitive}
              loading={loading}
              onEdit={startEdit}
              onLifecycleChange={(id, lifecycle) => void changeLifecycleStatus(id, lifecycle)}
              onDelete={(id) => void deleteOpportunity(id)}
            />
          </div>
        </SectionShell>
      ) : null}

      {activeSection === "inactive" ? (
        <SectionShell title="Inactive Listings" subtitle="Draft, paused, or manually closed rows stay here until you publish them again.">
          <OpportunityTable
            title="Inactive opportunities"
            subtitle="Use Publish to send them back to the correct student portal."
            rows={inactiveOpportunities}
            loading={loading}
            onEdit={startEdit}
            onLifecycleChange={(id, lifecycle) => void changeLifecycleStatus(id, lifecycle)}
            onDelete={(id) => void deleteOpportunity(id)}
          />
        </SectionShell>
      ) : null}

      {activeSection === "automation" ? (
        <SectionShell title="Background Jobs" subtitle="Operational jobs stay in their own tab so publishing and maintenance are separated.">
          <form onSubmit={enqueueJob} style={{ display: "grid", gap: "0.7rem", marginBottom: "1rem" }}>
            <label style={{ display: "grid", gap: "0.35rem" }}>
              <span style={{ fontWeight: 700 }}>Job Type</span>
              <input value={jobType} onChange={(event) => setJobType(event.target.value)} required />
            </label>
            <label style={{ display: "grid", gap: "0.35rem" }}>
              <span style={{ fontWeight: 700 }}>Payload JSON</span>
              <textarea rows={4} value={jobPayload} onChange={(event) => setJobPayload(event.target.value)} />
            </label>
            <button type="submit" style={actionButtonStyle("publish")} disabled={loading}>
              Queue Job
            </button>
          </form>

          <div style={{ overflowX: "auto", ...panelStyle("var(--bg-base)") }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "2px solid var(--border-subtle)" }}>
                  <th align="left" style={{ padding: "0.8rem 0.9rem" }}>Type</th>
                  <th align="left" style={{ padding: "0.8rem 0.9rem" }}>Status</th>
                  <th align="left" style={{ padding: "0.8rem 0.9rem" }}>Attempts</th>
                  <th align="left" style={{ padding: "0.8rem 0.9rem" }}>Updated</th>
                  <th align="left" style={{ padding: "0.8rem 0.9rem" }}>Error</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id} style={{ borderTop: "1px solid color-mix(in srgb, var(--border-subtle) 30%, transparent)" }}>
                    <td style={{ padding: "0.85rem 0.9rem", fontWeight: 700 }}>{job.job_type}</td>
                    <td style={{ padding: "0.85rem 0.9rem" }}>{job.status}</td>
                    <td style={{ padding: "0.85rem 0.9rem" }}>{job.attempts}/{job.max_attempts}</td>
                    <td style={{ padding: "0.85rem 0.9rem" }}>{job.updated_at ? new Date(job.updated_at).toLocaleString() : "-"}</td>
                    <td style={{ padding: "0.85rem 0.9rem", color: "var(--text-secondary)" }}>{job.last_error || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionShell>
      ) : null}

      {activeSection === "community" ? (
        <SectionShell title="Community Moderation" subtitle="Posts and comments are separate from opportunity operations and use destructive controls only where needed.">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "1rem" }}>
            <div style={{ display: "grid", gap: "0.8rem" }}>
              <h3 style={{ fontSize: "1.1rem" }}>Posts</h3>
              {posts.map((post) => (
                <article key={post.id} style={{ ...panelStyle(), padding: "0.9rem", display: "grid", gap: "0.45rem" }}>
                  <p style={{ color: "var(--text-primary)", fontWeight: 600 }}>{post.content}</p>
                  <small style={{ color: "var(--text-secondary)" }}>domain={post.domain} · user={post.user_id}</small>
                  <button type="button" style={actionButtonStyle("delete")} onClick={() => void deleteSocialRow("post", post.id)} disabled={loading}>
                    Delete Post
                  </button>
                </article>
              ))}
            </div>
            <div style={{ display: "grid", gap: "0.8rem" }}>
              <h3 style={{ fontSize: "1.1rem" }}>Comments</h3>
              {comments.map((comment) => (
                <article key={comment.id} style={{ ...panelStyle(), padding: "0.9rem", display: "grid", gap: "0.45rem" }}>
                  <p style={{ color: "var(--text-primary)", fontWeight: 600 }}>{comment.content}</p>
                  <small style={{ color: "var(--text-secondary)" }}>post={comment.post_id} · user={comment.user_id}</small>
                  <button type="button" style={actionButtonStyle("delete")} onClick={() => void deleteSocialRow("comment", comment.id)} disabled={loading}>
                    Delete Comment
                  </button>
                </article>
              ))}
            </div>
          </div>
        </SectionShell>
      ) : null}

      {activeSection === "users" ? (
        <SectionShell title="Users" subtitle="Account control stays separate from content publishing.">
          <div style={{ overflowX: "auto", ...panelStyle("var(--bg-base)") }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "2px solid var(--border-subtle)" }}>
                  <th align="left" style={{ padding: "0.8rem 0.9rem" }}>Name</th>
                  <th align="left" style={{ padding: "0.8rem 0.9rem" }}>Email</th>
                  <th align="left" style={{ padding: "0.8rem 0.9rem" }}>Account</th>
                  <th align="left" style={{ padding: "0.8rem 0.9rem" }}>Provider</th>
                  <th align="left" style={{ padding: "0.8rem 0.9rem" }}>Status</th>
                  <th align="left" style={{ padding: "0.8rem 0.9rem" }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id} style={{ borderTop: "1px solid color-mix(in srgb, var(--border-subtle) 30%, transparent)" }}>
                    <td style={{ padding: "0.85rem 0.9rem" }}>{user.full_name || "Unknown"}</td>
                    <td style={{ padding: "0.85rem 0.9rem" }}>{user.email}</td>
                    <td style={{ padding: "0.85rem 0.9rem" }}>{user.account_type}</td>
                    <td style={{ padding: "0.85rem 0.9rem" }}>{user.auth_provider}</td>
                    <td style={{ padding: "0.85rem 0.9rem" }}>{user.is_active ? "Active" : "Inactive"}</td>
                    <td style={{ padding: "0.85rem 0.9rem" }}>
                      <button
                        type="button"
                        style={actionButtonStyle(user.is_active ? "mute" : "publish")}
                        onClick={() => void updateUserStatus(user.id, !user.is_active)}
                        disabled={loading || user.is_admin}
                      >
                        {user.is_active ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionShell>
      ) : null}

      {activeSection === "audit" ? (
        <SectionShell title="Audit Trail" subtitle="Recent admin and auth events stay searchable in a dedicated tab instead of cluttering the console.">
          <div style={{ display: "grid", gap: "0.75rem" }}>
            {auditEvents.map((event) => (
              <article key={event.id} style={{ ...panelStyle(), padding: "0.9rem", display: "grid", gap: "0.35rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", flexWrap: "wrap" }}>
                  <strong style={{ color: "var(--text-primary)" }}>{event.event_type}</strong>
                  <span style={{ color: event.success ? "#15803d" : "#b91c1c", fontWeight: 800 }}>
                    {event.success ? "success" : "failure"}
                  </span>
                </div>
                <div style={{ color: "var(--text-secondary)" }}>{event.email || "system"}</div>
                {event.reason ? <div style={{ color: "var(--text-secondary)", fontSize: "0.92rem" }}>{event.reason}</div> : null}
                <small style={{ color: "var(--text-secondary)" }}>{new Date(event.created_at).toLocaleString()}</small>
              </article>
            ))}
          </div>
        </SectionShell>
      ) : null}
    </main>
  );
}
