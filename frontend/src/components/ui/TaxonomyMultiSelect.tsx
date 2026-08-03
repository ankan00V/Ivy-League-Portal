"use client";

import React from "react";
import type { LucideIcon } from "lucide-react";
import { X } from "lucide-react";

import FormSection from "@/components/ui/FormSection";

export type TaxonomyOption = {
  label: string;
  group: string;
};

type TaxonomyMultiSelectProps = {
  label: string;
  helper?: string;
  /** Comma-separated stored value, e.g. "Bengaluru, Remote". */
  value: string;
  onChange: (value: string) => void;
  options: TaxonomyOption[];
  groups: string[];
  /** Splits the stored string into canonical entries. */
  split: (value: string) => string[];
  /** Joins entries back into the stored string. */
  join: (values: string[]) => string;
  addLabel: string;
  icon: LucideIcon;
  wrapperClassName?: string;
};

/**
 * Add-and-remove picker for a comma-separated taxonomy field.
 *
 * Preferred Roles and Preferred Work Locations are the same control over
 * different vocabularies, so they share one implementation rather than two
 * near-identical blocks in profile/page.tsx. Chips reuse the skill picker's
 * visual language so every multi-value field on the page behaves alike.
 */
export default function TaxonomyMultiSelect({
  label,
  helper,
  value,
  onChange,
  options,
  groups,
  split,
  join,
  addLabel,
  icon: Icon,
  wrapperClassName,
}: TaxonomyMultiSelectProps) {
  const selected = split(value);
  const selectedKeys = new Set(selected.map((item) => item.toLowerCase()));

  // The chip box scrolls once it fills, so the count is what tells a student
  // how many are selected when some have scrolled out of view.
  const helperWithCount =
    selected.length > 0 ? `${selected.length} selected. ${helper ?? ""}`.trim() : helper;

  return (
    <FormSection className={wrapperClassName} label={label} helper={helperWithCount}>
      <div className="skill-picker-input-row">
        <Icon className="skill-picker-icon" size={15} aria-hidden="true" />
        {selected.length === 0 ? (
          <span className="skill-picker-empty">Nothing selected yet</span>
        ) : (
          selected.map((item) => (
            <span key={item} className="profile-tag removable">
              {item}
              <button
                type="button"
                aria-label={`Remove ${item}`}
                onClick={() => onChange(join(selected.filter((entry) => entry !== item)))}
              >
                <X size={12} aria-hidden="true" />
              </button>
            </span>
          ))
        )}
      </div>
      <select
        className="input-base taxonomy-add-select"
        // Always resets to the prompt, so the same option can be re-added after
        // being removed. A controlled select holding the last pick would not fire
        // onChange for that.
        value=""
        aria-label={addLabel}
        onChange={(event) => {
          const next = event.target.value;
          if (!next || selectedKeys.has(next.toLowerCase())) {
            return;
          }
          onChange(join([...selected, next]));
        }}
      >
        <option value="">{addLabel}</option>
        {groups.map((group) => {
          const available = options.filter(
            (option) => option.group === group && !selectedKeys.has(option.label.toLowerCase()),
          );
          if (available.length === 0) {
            return null;
          }
          return (
            <optgroup key={group} label={group}>
              {available.map((option) => (
                <option key={option.label} value={option.label}>
                  {option.label}
                </option>
              ))}
            </optgroup>
          );
        })}
      </select>
    </FormSection>
  );
}
