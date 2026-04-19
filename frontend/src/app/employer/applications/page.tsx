"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useCallback, useEffect, useMemo, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import { apiUrl } from "@/lib/api";
import { clearAccessToken, getAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";

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
  pipeline_updated_at?: string | null;
};

type EmployerApplicationsResponse = {
  total: number;
  rows: EmployerApplication[];
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

export default function EmployerApplicationsPage() {
  const router = useRouter();
  const [rows, setRows] = useState<EmployerApplication[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [pipelineFilter, setPipelineFilter] = useState<string>("all");
  const [pipelineDrafts, setPipelineDrafts] = useState<Record<string, EmployerApplication["pipeline_state"]>>({});
  const [pipelineUpdatingId, setPipelineUpdatingId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const hasFilters = useMemo(() => search.trim().length > 0 || pipelineFilter !== "all", [pipelineFilter, search]);

  const fetchRows = useCallback(
    async (mode: "initial" | "refresh" = "refresh") => {
      const token = getAccessToken();
      if (!token) {
        router.replace("/login");
        return;
      }
      if (mode === "initial") {
        setLoading(true);
      } else {
        setRefreshing(true);
      }

      try {
        const query = new URLSearchParams();
        query.set("limit", "500");
        if (search.trim()) {
          query.set("search", search.trim());
        }
        if (pipelineFilter !== "all") {
          query.set("pipeline_state", pipelineFilter);
        }

        const res = await fetch(apiUrl(`/api/v1/employer/applications?${query.toString()}`), {
          headers: { Authorization: `Bearer ${token}` },
        });
        const payload = (await res.json().catch(() => ({}))) as EmployerApplicationsResponse | Record<string, unknown>;
        if (!res.ok) {
          throw new Error(getApiErrorMessage(payload, "Unable to load applications"));
        }

        const typed = payload as EmployerApplicationsResponse;
        setRows(Array.isArray(typed.rows) ? typed.rows : []);
        setTotal(Number(typed.total || 0));
        setPipelineDrafts(
          (typed.rows || []).reduce<Record<string, EmployerApplication["pipeline_state"]>>((acc, row) => {
            acc[row.application_id] = row.pipeline_state || "applied";
            return acc;
          }, {}),
        );
      } catch (err) {
        setError(getUnknownErrorMessage(err, "Unable to load employer applications"));
      } finally {
        if (mode === "initial") {
          setLoading(false);
        } else {
          setRefreshing(false);
        }
      }
    },
    [pipelineFilter, router, search],
  );

  useEffect(() => {
    void fetchRows("initial");
  }, [fetchRows]);

  const applySearch = () => {
    setError(null);
    setSuccess(null);
    setSearch(searchInput.trim());
  };

  const clearFilters = () => {
    setSearchInput("");
    setSearch("");
    setPipelineFilter("all");
    setError(null);
    setSuccess(null);
  };

  const updatePipelineState = async (applicationId: string) => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    const targetState = pipelineDrafts[applicationId] || "applied";
    const previous = rows.find((row) => row.application_id === applicationId);
    if (!previous) {
      return;
    }

    setPipelineUpdatingId(applicationId);
    setError(null);
    setSuccess(null);

    setRows((current) =>
      current.map((row) =>
        row.application_id === applicationId
          ? {
              ...row,
              pipeline_state: targetState,
              pipeline_updated_at: new Date().toISOString(),
            }
          : row,
      ),
    );

    try {
      const res = await fetch(apiUrl(`/api/v1/employer/applications/${applicationId}/pipeline`), {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ pipeline_state: targetState }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to update pipeline state"));
      }
      const updated = payload as EmployerApplication;
      setRows((current) => current.map((row) => (row.application_id === applicationId ? updated : row)));
      setSuccess(`Application moved to ${targetState}.`);
      await fetchRows("refresh");
    } catch (err) {
      setRows((current) => current.map((row) => (row.application_id === applicationId ? previous : row)));
      setError(getUnknownErrorMessage(err, "Unable to update pipeline state"));
    } finally {
      setPipelineUpdatingId(null);
    }
  };

  const exportCsv = async () => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setExporting(true);
    setError(null);
    try {
      const query = new URLSearchParams();
      if (search.trim()) {
        query.set("search", search.trim());
      }
      if (pipelineFilter !== "all") {
        query.set("pipeline_state", pipelineFilter);
      }
      const res = await fetch(apiUrl(`/api/v1/employer/applications/export.csv?${query.toString()}`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        throw new Error(getApiErrorMessage(payload, "Unable to export CSV"));
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "employer_applications.csv";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setSuccess("CSV export downloaded.");
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to export applications"));
    } finally {
      setExporting(false);
    }
  };

  if (loading) {
    return (
      <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "var(--bg-base)" }}>
        <p style={{ color: "var(--text-secondary)", fontWeight: 700 }}>Loading applications workspace...</p>
      </main>
    );
  }

  return (
    <main style={{ minHeight: "100vh", background: "var(--bg-base)", padding: "1.25rem" }}>
      <div style={{ maxWidth: "1280px", margin: "0 auto", display: "grid", gap: "1rem" }}>
        <section className="card-panel" style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <div>
            <BrandLogo size="sm" />
            <h1 style={{ marginTop: "0.6rem", marginBottom: "0.25rem", fontSize: "2rem" }}>Employer Applications</h1>
            <p style={{ color: "var(--text-secondary)", fontWeight: 600 }}>
              Filter, triage, and move candidates through the pipeline in real-time.
            </p>
            <p style={{ color: "var(--text-secondary)", marginTop: "0.35rem" }}>
              Total records: <strong>{total}</strong>
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
            <Link href="/employer/dashboard" className="btn-secondary">
              Back to Dashboard
            </Link>
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

        <section className="card-panel" style={{ display: "grid", gap: "0.75rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "0.6rem", alignItems: "end" }}>
            <div>
              <label style={{ fontWeight: 700 }}>Search</label>
              <input
                className="input-base"
                placeholder="Applicant, email, opportunity, status"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
              />
            </div>
            <div>
              <label style={{ fontWeight: 700 }}>Pipeline Stage</label>
              <select className="input-base" value={pipelineFilter} onChange={(event) => setPipelineFilter(event.target.value)}>
                <option value="all">all</option>
                <option value="applied">applied</option>
                <option value="shortlisted">shortlisted</option>
                <option value="interview">interview</option>
                <option value="rejected">rejected</option>
              </select>
            </div>
            <button type="button" className="btn-primary" onClick={applySearch}>
              Apply Filters
            </button>
            <button type="button" className="btn-secondary" onClick={clearFilters} disabled={!hasFilters}>
              Reset
            </button>
            <button type="button" className="btn-secondary" onClick={exportCsv} disabled={exporting}>
              {exporting ? "Exporting..." : "Export CSV"}
            </button>
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <button type="button" className="btn-secondary" onClick={() => void fetchRows("refresh")} disabled={refreshing}>
              {refreshing ? "Refreshing..." : "Refresh"}
            </button>
          </div>

          {error && (
            <div
              style={{
                border: "2px solid #ef4444",
                color: "#b91c1c",
                borderRadius: "10px",
                padding: "0.7rem",
                background: "rgba(239,68,68,0.08)",
              }}
            >
              {error}
            </div>
          )}
          {success && (
            <div
              style={{
                border: "2px solid #22c55e",
                color: "#15803d",
                borderRadius: "10px",
                padding: "0.7rem",
                background: "rgba(34,197,94,0.08)",
              }}
            >
              {success}
            </div>
          )}

          {rows.length === 0 ? (
            <p style={{ color: "var(--text-secondary)", fontWeight: 600 }}>No applications found for the current filters.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", minWidth: "1100px" }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "2px solid var(--border-subtle)" }}>
                    <th style={{ padding: "0.55rem" }}>Opportunity</th>
                    <th style={{ padding: "0.55rem" }}>Applicant</th>
                    <th style={{ padding: "0.55rem" }}>Email</th>
                    <th style={{ padding: "0.55rem" }}>Status</th>
                    <th style={{ padding: "0.55rem" }}>Pipeline</th>
                    <th style={{ padding: "0.55rem" }}>Submitted</th>
                    <th style={{ padding: "0.55rem" }}>Updated</th>
                    <th style={{ padding: "0.55rem" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
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
                            setPipelineDrafts((current) => ({ ...current, [row.application_id]: value }));
                          }}
                          disabled={pipelineUpdatingId === row.application_id}
                          style={{ minWidth: "140px" }}
                        >
                          <option value="applied">applied</option>
                          <option value="shortlisted">shortlisted</option>
                          <option value="interview">interview</option>
                          <option value="rejected">rejected</option>
                        </select>
                      </td>
                      <td style={{ padding: "0.55rem" }}>{stableDate(row.submitted_at || row.created_at)}</td>
                      <td style={{ padding: "0.55rem" }}>{stableDate(row.pipeline_updated_at || row.created_at)}</td>
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
      </div>
    </main>
  );
}
