import { OpportunityCardsSkeleton } from "@/components/LoadingSkeletons";

export default function OpportunitiesLoading() {
  return (
    <main style={{ minHeight: "100vh", background: "var(--bg-base)", padding: "2.5rem" }}>
      <div style={{ display: "grid", gap: "1.5rem" }}>
        <div className="card-panel" style={{ display: "grid", gap: "0.75rem" }}>
          <div className="vv-skeleton" style={{ width: "320px", height: "42px", borderRadius: "8px" }} />
          <div className="vv-skeleton" style={{ width: "520px", height: "18px", borderRadius: "8px" }} />
        </div>
        <OpportunityCardsSkeleton count={6} />
      </div>
    </main>
  );
}
