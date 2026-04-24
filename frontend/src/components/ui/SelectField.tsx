import React from "react";

import FormSection from "@/components/ui/FormSection";

type SelectFieldProps = React.SelectHTMLAttributes<HTMLSelectElement> & {
  label: React.ReactNode;
  helper?: React.ReactNode;
  helperTone?: "default" | "warning";
  required?: boolean;
  labelSpaced?: boolean;
  wrapperClassName?: string;
  children: React.ReactNode;
};

export default function SelectField({
  label,
  helper,
  helperTone = "default",
  required = false,
  labelSpaced = false,
  wrapperClassName,
  className,
  id,
  children,
  ...selectProps
}: SelectFieldProps) {
  const selectClassName = ["input-base", className ?? ""].filter(Boolean).join(" ");

  return (
    <FormSection
      label={label}
      labelFor={id}
      helper={helper}
      helperTone={helperTone}
      required={required}
      labelSpaced={labelSpaced}
      className={wrapperClassName}
    >
      <select id={id} className={selectClassName} {...selectProps}>
        {children}
      </select>
    </FormSection>
  );
}
