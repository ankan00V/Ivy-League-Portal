"use client";

import { useEffect } from "react";

const STYLE_ATTR = "data-vv-style";
const CLASS_PREFIX = "vv-style-";
const cache = new Map<string, string>();

const unitlessProperties = new Set([
  "animationIterationCount",
  "aspectRatio",
  "borderImageOutset",
  "borderImageSlice",
  "borderImageWidth",
  "boxFlex",
  "boxFlexGroup",
  "boxOrdinalGroup",
  "columnCount",
  "columns",
  "flex",
  "flexGrow",
  "flexPositive",
  "flexShrink",
  "flexNegative",
  "flexOrder",
  "gridArea",
  "gridColumn",
  "gridColumnEnd",
  "gridColumnStart",
  "gridRow",
  "gridRowEnd",
  "gridRowStart",
  "fontWeight",
  "lineClamp",
  "lineHeight",
  "opacity",
  "order",
  "orphans",
  "scale",
  "tabSize",
  "widows",
  "zIndex",
  "zoom",
]);

function hash(input: string): string {
  let value = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    value ^= input.charCodeAt(index);
    value = Math.imul(value, 16777619);
  }
  return (value >>> 0).toString(36);
}

function kebabCase(property: string): string {
  if (property.startsWith("--")) {
    return property;
  }
  return property.replace(/[A-Z]/g, (match) => `-${match.toLowerCase()}`);
}

function cssValue(property: string, value: unknown): string | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  if (typeof value === "number") {
    return unitlessProperties.has(property) || property.startsWith("--") ? String(value) : `${value}px`;
  }
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  if (/url\s*\(|expression\s*\(|@import/i.test(trimmed)) {
    return null;
  }
  return trimmed.replace(/[{};]/g, "");
}

function toCssRule(className: string, payload: string): string | null {
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(payload) as Record<string, unknown>;
  } catch {
    return null;
  }
  const declarations = Object.entries(parsed)
    .map(([property, value]) => {
      if (!/^--?[a-zA-Z_][a-zA-Z0-9_-]*$/.test(property)) {
        return null;
      }
      const normalizedValue = cssValue(property, value);
      if (normalizedValue === null) {
        return null;
      }
      return `${kebabCase(property)}:${normalizedValue}`;
    })
    .filter(Boolean)
    .join(";");
  return declarations ? `.${className}{${declarations}}` : null;
}

function ensureStyleElement(nonce: string): HTMLStyleElement {
  const existing = document.querySelector<HTMLStyleElement>("style[data-vv-style-runtime]");
  if (existing) {
    return existing;
  }
  const styleElement = document.createElement("style");
  styleElement.setAttribute("data-vv-style-runtime", "true");
  if (nonce) {
    styleElement.nonce = nonce;
  }
  document.head.appendChild(styleElement);
  return styleElement;
}

function applyStyles(root: ParentNode, styleElement: HTMLStyleElement): void {
  const nodes = root instanceof Element && root.hasAttribute(STYLE_ATTR)
    ? [root, ...Array.from(root.querySelectorAll<HTMLElement>(`[${STYLE_ATTR}]`))]
    : Array.from(root.querySelectorAll<HTMLElement>(`[${STYLE_ATTR}]`));
  const newRules: string[] = [];

  for (const node of nodes) {
    const payload = node.getAttribute(STYLE_ATTR);
    if (!payload) {
      continue;
    }
    let className = cache.get(payload);
    if (!className) {
      className = `${CLASS_PREFIX}${hash(payload)}`;
      cache.set(payload, className);
      const rule = toCssRule(className, payload);
      if (rule) {
        newRules.push(rule);
      }
    }
    node.classList.add(className);
    node.removeAttribute(STYLE_ATTR);
  }

  if (newRules.length) {
    styleElement.appendChild(document.createTextNode(newRules.join("\n")));
  }
}

export default function NonceStyleRuntime({ nonce }: { nonce: string }) {
  useEffect(() => {
    const styleElement = ensureStyleElement(nonce);
    applyStyles(document, styleElement);
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of Array.from(mutation.addedNodes)) {
          if (node instanceof Element) {
            applyStyles(node, styleElement);
          }
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [nonce]);

  return null;
}
