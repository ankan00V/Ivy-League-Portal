import type { CSSProperties } from "react";

type StyleValue = string | number | null | undefined;
type SerializableStyle = Record<string, StyleValue>;

function normalizeStyle(style: CSSProperties | SerializableStyle | null | undefined): SerializableStyle {
  if (!style || typeof style !== "object") {
    return {};
  }
  const normalized: SerializableStyle = {};
  for (const [key, value] of Object.entries(style as SerializableStyle)) {
    if (value === null || value === undefined || value === "") {
      continue;
    }
    normalized[key] = value;
  }
  return normalized;
}

export function vvStyle(style: CSSProperties | SerializableStyle | null | undefined): string | undefined {
  const normalized = normalizeStyle(style);
  if (!Object.keys(normalized).length) {
    return undefined;
  }
  return JSON.stringify(normalized);
}
