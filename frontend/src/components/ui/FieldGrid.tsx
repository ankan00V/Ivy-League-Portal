import React from "react";

type FieldGridVariant = "default" | "two" | "leading-compact";

type FieldGridProps = {
  children: React.ReactNode;
  variant?: FieldGridVariant;
  className?: string;
};

export default function FieldGrid({ children, variant = "default", className }: FieldGridProps) {
  const variantClass =
    variant === "two" ? "vv-field-grid-two" : variant === "leading-compact" ? "vv-field-grid-leading-compact" : "";
  const classes = ["vv-field-grid", variantClass, className ?? ""].filter(Boolean).join(" ");

  return <div className={classes}>{children}</div>;
}
