"use client";

import React from "react";

type SkeletonBlockProps = {
  width?: string;
  height?: string;
  borderRadius?: string;
  style?: React.CSSProperties;
};

export function SkeletonBlock({
  width = "100%",
  height = "1rem",
  borderRadius = "6px",
  style,
}: SkeletonBlockProps) {
  return (
    <div
      className="vv-skeleton"
      style={{
        width,
        height,
        borderRadius,
        ...style,
      }}
    />
  );
}

type CenteredPageSkeletonProps = {
  paneHeight?: string;
};

export function CenteredPageSkeleton({ paneHeight = "520px" }: CenteredPageSkeletonProps) {
  return (
    <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "var(--bg-base)", padding: "1.5rem" }}>
      <section className="card-panel" style={{ width: "min(980px, 100%)", minHeight: paneHeight, display: "grid", gap: "1rem" }}>
        <SkeletonBlock width="220px" height="30px" />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
          <SkeletonBlock height="44px" />
          <SkeletonBlock height="44px" />
        </div>
        <SkeletonBlock height="44px" />
        <SkeletonBlock height="44px" />
        <SkeletonBlock height="44px" />
        <SkeletonBlock height="44px" />
        <SkeletonBlock width="180px" height="44px" style={{ marginTop: "auto" }} />
      </section>
    </main>
  );
}

type OpportunityCardsSkeletonProps = {
  count?: number;
};

export function OpportunityCardsSkeleton({ count = 6 }: OpportunityCardsSkeletonProps) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "2rem" }}>
      {Array.from({ length: count }).map((_, idx) => (
        <div key={`opp-skeleton-${idx}`} className="card-panel" style={{ padding: 0, height: "420px", display: "flex", flexDirection: "column" }}>
          <SkeletonBlock height="160px" borderRadius="0" />
          <div style={{ padding: "1.5rem", flex: 1, display: "flex", flexDirection: "column", gap: "0.85rem" }}>
            <SkeletonBlock width="78%" height="24px" />
            <SkeletonBlock width="100%" height="16px" />
            <SkeletonBlock width="62%" height="16px" />
            <SkeletonBlock width="100%" height="38px" borderRadius="999px" style={{ marginTop: "auto" }} />
          </div>
        </div>
      ))}
    </div>
  );
}

type LeaderboardRowsSkeletonProps = {
  rows?: number;
};

export function LeaderboardRowsSkeleton({ rows = 8 }: LeaderboardRowsSkeletonProps) {
  return (
    <>
      {Array.from({ length: rows }).map((_, idx) => (
        <tr key={`leaderboard-skeleton-${idx}`} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
          <td style={{ padding: "0.9rem 1.25rem" }}>
            <SkeletonBlock width="60px" height="16px" />
          </td>
          <td style={{ padding: "0.9rem 1.25rem" }}>
            <SkeletonBlock width="180px" height="16px" />
          </td>
          <td style={{ padding: "0.9rem 1.25rem" }}>
            <SkeletonBlock width="240px" height="16px" />
          </td>
          <td style={{ padding: "0.9rem 1.25rem" }}>
            <SkeletonBlock width="90px" height="28px" />
          </td>
        </tr>
      ))}
    </>
  );
}

export function DashboardPageSkeleton() {
  return (
    <div style={{ minHeight: "100vh", display: "flex", background: "var(--bg-base)" }}>
      <div style={{ width: "var(--sidebar-width)", borderRight: "2px solid var(--border-subtle)", background: "var(--bg-sidebar)", padding: "1.25rem", display: "grid", gap: "1rem" }}>
        <SkeletonBlock width="150px" height="36px" />
        <SkeletonBlock height="48px" />
        <SkeletonBlock height="48px" />
        <SkeletonBlock height="48px" />
        <SkeletonBlock height="48px" />
      </div>
      <main className="main-content" style={{ display: "grid", gap: "1.5rem" }}>
        <section className="card-panel" style={{ padding: "2rem", display: "grid", gap: "0.8rem" }}>
          <SkeletonBlock width="300px" height="42px" />
          <SkeletonBlock width="520px" height="18px" />
        </section>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1.5rem" }}>
          {Array.from({ length: 3 }).map((_, idx) => (
            <section key={`stat-skeleton-${idx}`} className="card-panel" style={{ minHeight: "210px", display: "grid", gap: "0.75rem" }}>
              <SkeletonBlock width="150px" height="16px" />
              <SkeletonBlock width="120px" height="86px" />
              <SkeletonBlock width="180px" height="16px" />
              <SkeletonBlock width="160px" height="14px" />
            </section>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "2rem" }}>
          <section className="card-panel" style={{ display: "grid", gap: "1rem" }}>
            <SkeletonBlock width="220px" height="28px" />
            {Array.from({ length: 3 }).map((_, idx) => (
              <div key={`dash-rec-${idx}`} className="card-panel" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "1rem 1.25rem" }}>
                <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
                  <SkeletonBlock width="48px" height="48px" />
                  <div style={{ display: "grid", gap: "0.5rem" }}>
                    <SkeletonBlock width="220px" height="18px" />
                    <SkeletonBlock width="100px" height="14px" />
                  </div>
                </div>
                <SkeletonBlock width="100px" height="32px" />
              </div>
            ))}
          </section>
          <section className="card-panel" style={{ display: "grid", gap: "1rem" }}>
            <SkeletonBlock width="180px" height="28px" />
            {Array.from({ length: 2 }).map((_, idx) => (
              <div key={`dash-post-${idx}`} style={{ display: "grid", gap: "0.65rem" }}>
                <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
                  <SkeletonBlock width="40px" height="40px" />
                  <div style={{ display: "grid", gap: "0.45rem" }}>
                    <SkeletonBlock width="130px" height="14px" />
                    <SkeletonBlock width="90px" height="12px" />
                  </div>
                </div>
                <SkeletonBlock width="100%" height="14px" />
                <SkeletonBlock width="88%" height="14px" />
              </div>
            ))}
          </section>
        </div>
      </main>
    </div>
  );
}

export function EmployerDashboardSkeleton() {
  return (
    <main style={{ minHeight: "100vh", background: "var(--bg-base)", padding: "1.25rem" }}>
      <div style={{ maxWidth: "1200px", margin: "0 auto", display: "grid", gap: "1rem" }}>
        <section className="card-panel" style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <div style={{ display: "grid", gap: "0.6rem" }}>
            <SkeletonBlock width="150px" height="32px" />
            <SkeletonBlock width="280px" height="34px" />
            <SkeletonBlock width="420px" height="16px" />
          </div>
          <div style={{ display: "flex", gap: "0.6rem" }}>
            <SkeletonBlock width="160px" height="46px" />
            <SkeletonBlock width="120px" height="46px" />
          </div>
        </section>
        <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.75rem" }}>
          {Array.from({ length: 8 }).map((_, idx) => (
            <article key={`employer-stat-${idx}`} className="card-panel" style={{ padding: "0.9rem", display: "grid", gap: "0.55rem" }}>
              <SkeletonBlock width="90px" height="14px" />
              <SkeletonBlock width="72px" height="34px" />
            </article>
          ))}
        </section>
        <section className="card-panel" style={{ display: "grid", gap: "0.8rem" }}>
          <SkeletonBlock width="180px" height="28px" />
          <div style={{ display: "grid", gap: "0.75rem" }}>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "0.75rem" }}>
              <SkeletonBlock height="44px" />
              <SkeletonBlock height="44px" />
            </div>
            <SkeletonBlock height="120px" />
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "0.75rem" }}>
              <SkeletonBlock height="44px" />
              <SkeletonBlock height="44px" />
              <SkeletonBlock height="44px" />
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

export function TableWorkspaceSkeleton() {
  return (
    <main style={{ minHeight: "100vh", background: "var(--bg-base)", padding: "1.25rem" }}>
      <div style={{ maxWidth: "1280px", margin: "0 auto", display: "grid", gap: "1rem" }}>
        <section className="card-panel" style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <div style={{ display: "grid", gap: "0.6rem" }}>
            <SkeletonBlock width="150px" height="32px" />
            <SkeletonBlock width="260px" height="32px" />
            <SkeletonBlock width="420px" height="16px" />
          </div>
          <div style={{ display: "flex", gap: "0.6rem" }}>
            <SkeletonBlock width="180px" height="46px" />
            <SkeletonBlock width="120px" height="46px" />
          </div>
        </section>
        <section className="card-panel" style={{ display: "grid", gap: "0.75rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "0.6rem" }}>
            <SkeletonBlock height="44px" />
            <SkeletonBlock height="44px" />
            <SkeletonBlock height="44px" />
            <SkeletonBlock height="44px" />
            <SkeletonBlock height="44px" />
          </div>
          <SkeletonBlock width="110px" height="42px" style={{ marginLeft: "auto" }} />
          <div style={{ display: "grid", gap: "0.55rem" }}>
            {Array.from({ length: 6 }).map((_, idx) => (
              <div key={`table-row-${idx}`} style={{ display: "grid", gridTemplateColumns: "1.4fr 1.1fr 1.2fr 0.8fr 0.8fr", gap: "0.75rem", alignItems: "center", padding: "0.85rem 0", borderBottom: "1px solid var(--border-subtle)" }}>
                <SkeletonBlock height="16px" />
                <SkeletonBlock height="16px" />
                <SkeletonBlock height="16px" />
                <SkeletonBlock height="16px" />
                <SkeletonBlock height="36px" />
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
