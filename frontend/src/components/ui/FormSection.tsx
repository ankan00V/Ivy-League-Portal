import React from "react";

import FieldLabel from "@/components/ui/FieldLabel";

type FormSectionProps = {
  children: React.ReactNode;
  label?: React.ReactNode;
  labelFor?: string;
  required?: boolean;
  labelSpaced?: boolean;
  helper?: React.ReactNode;
  helperTone?: "default" | "warning";
  className?: string;
};

export default function FormSection({
  children,
  label,
  labelFor,
  required = false,
  labelSpaced = false,
  helper,
  helperTone = "default",
  className,
}: FormSectionProps) {
  const classes = ["vv-form-section", className ?? ""].filter(Boolean).join(" ");
  const helperClassName = ["vv-form-helper", helperTone === "warning" ? "warning" : ""].filter(Boolean).join(" ");

  return (
    <div className={classes}>
      {label ? (
        <FieldLabel htmlFor={labelFor} required={required} spaced={labelSpaced}>
          {label}
        </FieldLabel>
      ) : null}
      {children}
      {helper ? <p className={helperClassName}>{helper}</p> : null}
    </div>
  );
}
