import React from "react";

import FormSection from "@/components/ui/FormSection";

type TextareaFieldProps = React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label: React.ReactNode;
  helper?: React.ReactNode;
  helperTone?: "default" | "warning";
  required?: boolean;
  labelSpaced?: boolean;
  wrapperClassName?: string;
};

export default function TextareaField({
  label,
  helper,
  helperTone = "default",
  required = false,
  labelSpaced = false,
  wrapperClassName,
  className,
  id,
  ...textareaProps
}: TextareaFieldProps) {
  const textareaClassName = ["input-base", className ?? ""].filter(Boolean).join(" ");

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
      <textarea id={id} className={textareaClassName} {...textareaProps} />
    </FormSection>
  );
}
