import React from "react";

type SectionCardProps = {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  aside?: React.ReactNode;
  children: React.ReactNode;
  status?: React.ReactNode;
  style?: React.CSSProperties;
};

export default function SectionCard({ title, subtitle, aside, children, status, style }: SectionCardProps) {
  return (
    <section className="vv-section-card" style={style}>
      <div className="vv-section-head">
        <div style={{ minWidth: 0 }}>
          <h2 className="vv-section-title">{title}</h2>
          {subtitle ? <p className="vv-section-subtitle">{subtitle}</p> : null}
          {status ? <div style={{ marginTop: "0.45rem", display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>{status}</div> : null}
        </div>
        {aside ? <div>{aside}</div> : null}
      </div>
      <div>{children}</div>
    </section>
  );
}
