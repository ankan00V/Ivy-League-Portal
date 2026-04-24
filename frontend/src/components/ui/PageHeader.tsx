import React from "react";

type PageHeaderProps = {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  kicker?: React.ReactNode;
  actions?: React.ReactNode;
  status?: React.ReactNode;
  compact?: boolean;
};

export default function PageHeader({ title, subtitle, kicker, actions, status, compact = false }: PageHeaderProps) {
  return (
    <header
      className="vv-page-header"
      style={{
        paddingTop: compact ? "0.8rem" : "1.2rem",
        paddingBottom: compact ? "0.8rem" : "1rem",
      }}
    >
      <div style={{ display: "grid", gap: "0.4rem", minWidth: 0 }}>
        {kicker ? <div className="vv-page-kicker">{kicker}</div> : null}
        <h1 className="vv-page-title">{title}</h1>
        {subtitle ? <p className="vv-page-subtitle">{subtitle}</p> : null}
        {status ? <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>{status}</div> : null}
      </div>
      {actions ? <div className="vv-page-actions">{actions}</div> : null}
    </header>
  );
}
