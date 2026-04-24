import React from "react";

type PillGroupProps = {
  children: React.ReactNode;
  className?: string;
};

export default function PillGroup({ children, className }: PillGroupProps) {
  const classes = ["vv-pill-group", className ?? ""].filter(Boolean).join(" ");
  return <div className={classes}>{children}</div>;
}
