"use client";

import React, { useMemo, useRef, useState } from "react";
import { X } from "lucide-react";

import FormSection from "@/components/ui/FormSection";

type SkillOption = {
  id: string;
  name: string;
  category: string;
  subcategory: string;
  aliases: string[];
  search_keywords: string[];
};

type SkillAutocompleteInputProps = {
  label: React.ReactNode;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
  wrapperClassName?: string;
};

const SKILLS_INDEX_URL = "/data/skills-taxonomy/skills_autocomplete.json";

function normalizeKey(value: string): string {
  return value.toLocaleLowerCase("en-IN").replace(/[^a-z0-9+#.]+/g, " ").trim();
}

function splitCommaValues(value: string): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  value
    .split(",")
    .map((item) => item.trim())
    .forEach((item) => {
      const key = normalizeKey(item);
      if (!item || seen.has(key)) {
        return;
      }
      seen.add(key);
      output.push(item);
    });
  return output;
}

function joinSkills(values: string[]): string {
  return values.map((item) => item.trim()).filter(Boolean).join(", ");
}

export default function SkillAutocompleteInput({
  label,
  value,
  onChange,
  placeholder,
  required = false,
  wrapperClassName,
}: SkillAutocompleteInputProps) {
  const [options, setOptions] = useState<SkillOption[]>([]);
  const [query, setQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const loadedRef = useRef(false);

  const selectedSkills = useMemo(() => splitCommaValues(value), [value]);
  const selectedKeys = useMemo(() => new Set(selectedSkills.map(normalizeKey)), [selectedSkills]);

  const loadOptions = async () => {
    if (loadedRef.current || isLoading) {
      return;
    }
    setIsLoading(true);
    setLoadError(false);
    try {
      const response = await fetch(SKILLS_INDEX_URL, { cache: "force-cache" });
      if (!response.ok) {
        throw new Error(`Failed to load skills index: ${response.status}`);
      }
      const payload = (await response.json()) as SkillOption[];
      setOptions(payload);
      loadedRef.current = true;
    } catch {
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  };

  const suggestions = useMemo(() => {
    const normalizedQuery = normalizeKey(query);
    if (!normalizedQuery || normalizedQuery.length < 2) {
      return [];
    }
    const exact: SkillOption[] = [];
    const prefix: SkillOption[] = [];
    const contains: SkillOption[] = [];
    for (const option of options) {
      const nameKey = normalizeKey(option.name);
      if (selectedKeys.has(nameKey)) {
        continue;
      }
      const searchable = [option.name, ...option.aliases, ...option.search_keywords].map(normalizeKey);
      if (searchable.some((item) => item === normalizedQuery)) {
        exact.push(option);
      } else if (searchable.some((item) => item.startsWith(normalizedQuery))) {
        prefix.push(option);
      } else if (searchable.some((item) => item.includes(normalizedQuery))) {
        contains.push(option);
      }
      if (exact.length + prefix.length + contains.length >= 18) {
        break;
      }
    }
    return [...exact, ...prefix, ...contains].slice(0, 8);
  }, [options, query, selectedKeys]);

  const addSkill = (name: string) => {
    const cleanName = name.trim();
    if (!cleanName || selectedKeys.has(normalizeKey(cleanName))) {
      setQuery("");
      return;
    }
    onChange(joinSkills([...selectedSkills, cleanName]));
    setQuery("");
    setIsOpen(false);
  };

  const removeSkill = (name: string) => {
    const keyToRemove = normalizeKey(name);
    onChange(joinSkills(selectedSkills.filter((skill) => normalizeKey(skill) !== keyToRemove)));
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && suggestions[0]) {
      event.preventDefault();
      addSkill(suggestions[0].name);
    }
    if ((event.key === "," || event.key === "Tab") && suggestions[0]) {
      event.preventDefault();
      addSkill(suggestions[0].name);
    }
    if (event.key === "Backspace" && !query && selectedSkills.length > 0) {
      event.preventDefault();
      removeSkill(selectedSkills[selectedSkills.length - 1]);
    }
  };

  const helper = loadError
    ? "Skill suggestions are unavailable right now."
    : isLoading
      ? "Loading skill suggestions."
      : undefined;

  return (
    <FormSection label={label} required={required} helper={helper} helperTone={loadError ? "warning" : "default"} className={wrapperClassName}>
      <div
        className="skill-picker"
        onFocus={() => {
          setIsOpen(true);
          void loadOptions();
        }}
      >
        <div className="skill-picker-input-row">
          {selectedSkills.map((skill) => (
            <span key={skill} className="profile-tag removable">
              {skill}
              <button type="button" aria-label={`Remove ${skill}`} onClick={() => removeSkill(skill)}>
                <X size={12} aria-hidden="true" />
              </button>
            </span>
          ))}
          <input
            className="skill-picker-input"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setIsOpen(true);
            }}
            onKeyDown={handleKeyDown}
            onFocus={() => {
              setIsOpen(true);
              void loadOptions();
            }}
            placeholder={selectedSkills.length > 0 ? "Add another skill" : placeholder}
          />
        </div>
        {isOpen && suggestions.length > 0 ? (
          <div className="skill-picker-menu" role="listbox">
            {suggestions.map((option) => (
              <button
                key={option.id}
                type="button"
                role="option"
                aria-selected="false"
                className="skill-picker-option"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => addSkill(option.name)}
              >
                <span>{option.name}</span>
                <small>
                  {option.category} · {option.subcategory}
                </small>
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </FormSection>
  );
}
