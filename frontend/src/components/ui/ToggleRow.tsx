import React from "react";

type ToggleRowProps = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: React.ReactNode;
  align?: "start" | "center";
  disabled?: boolean;
  className?: string;
};

export default function ToggleRow({
  checked,
  onChange,
  children,
  align = "center",
  disabled = false,
  className,
}: ToggleRowProps) {
  const classes = ["vv-toggle-row", align === "start" ? "vv-toggle-row-start" : "vv-toggle-row-center", className ?? ""]
    .filter(Boolean)
    .join(" ");

  return (
    <label className={classes}>
      <input
        className="vv-toggle-input"
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{children}</span>
    </label>
  );
}
