import React from "react";

import FormSection from "@/components/ui/FormSection";

type TextFieldProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, "children"> & {
  label: React.ReactNode;
  helper?: React.ReactNode;
  helperTone?: "default" | "warning";
  required?: boolean;
  labelSpaced?: boolean;
  wrapperClassName?: string;
};

export default function TextField({
  label,
  helper,
  helperTone = "default",
  required = false,
  labelSpaced = false,
  wrapperClassName,
  className,
  id,
  ...inputProps
}: TextFieldProps) {
  const inputClassName = ["input-base", className ?? ""].filter(Boolean).join(" ");

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
      <input id={id} className={inputClassName} {...inputProps} />
    </FormSection>
  );
}
