import React from "react";

type FieldLabelProps = {
  children: React.ReactNode;
  htmlFor?: string;
  required?: boolean;
  spaced?: boolean;
  className?: string;
};

export default function FieldLabel({ children, htmlFor, required = false, spaced = false, className }: FieldLabelProps) {
  const classes = ["vv-field-label", spaced ? "vv-field-label-spaced" : "", className ?? ""]
    .filter(Boolean)
    .join(" ");

  return (
    <label className={classes} htmlFor={htmlFor}>
      {children}
      {required ? <span aria-hidden="true"> *</span> : null}
    </label>
  );
}
