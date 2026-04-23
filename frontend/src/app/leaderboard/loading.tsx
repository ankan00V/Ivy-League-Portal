import { LeaderboardRowsSkeleton } from "@/components/LoadingSkeletons";

export default function LeaderboardLoading() {
  return (
    <main style={{ minHeight: "100vh", background: "var(--bg-base)", padding: "2.5rem" }}>
      <section className="card-panel" style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "1rem 1.25rem", borderBottom: "2px solid var(--border-subtle)" }}>
          <div className="vv-skeleton" style={{ width: "180px", height: "22px", borderRadius: "8px" }} />
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <tbody>
            <LeaderboardRowsSkeleton rows={10} />
          </tbody>
        </table>
      </section>
    </main>
  );
}
