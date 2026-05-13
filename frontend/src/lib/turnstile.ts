"use client";

declare global {
  interface Window {
    turnstile?: {
      render: (
        container: string | HTMLElement,
        options: {
          sitekey: string;
          action?: string;
          execution?: "render" | "execute";
          appearance?: "always" | "execute" | "interaction-only";
          callback?: (token: string) => void;
          "error-callback"?: () => void;
          "expired-callback"?: () => void;
        },
      ) => string;
      execute: (widgetIdOrContainer: string | HTMLElement) => void;
      remove: (widgetId: string) => void;
      reset: (widgetId: string) => void;
    };
    onTurnstileLoad?: () => void;
  }
}

const TURNSTILE_SCRIPT_ID = "cloudflare-turnstile";
const TURNSTILE_CONTAINER_ID = "turnstile-verification-container";

function getSiteKey(): string {
  return (process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || "").trim();
}

function ensureTurnstileContainer(): HTMLElement {
  let container = document.getElementById(TURNSTILE_CONTAINER_ID);
  if (!container) {
    container = document.createElement("div");
    container.id = TURNSTILE_CONTAINER_ID;
    container.style.position = "fixed";
    container.style.right = "1rem";
    container.style.bottom = "1rem";
    container.style.zIndex = "2147483647";
    document.body.appendChild(container);
  }
  return container;
}

function loadTurnstileScript(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.resolve();
  }

  if (window.turnstile) {
    return Promise.resolve();
  }

  const existing = document.getElementById(TURNSTILE_SCRIPT_ID) as HTMLScriptElement | null;
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("Unable to load Turnstile")), { once: true });
    });
  }

  return new Promise((resolve, reject) => {
    window.onTurnstileLoad = () => resolve();
    const script = document.createElement("script");
    script.id = TURNSTILE_SCRIPT_ID;
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=onTurnstileLoad";
    script.async = true;
    script.defer = true;
    script.onerror = () => reject(new Error("Unable to load Turnstile"));
    document.head.appendChild(script);
  });
}

export async function getTurnstileToken(action: string): Promise<string | null> {
  const siteKey = getSiteKey();
  if (!siteKey) {
    return null;
  }

  await loadTurnstileScript();
  const turnstile = window.turnstile;
  if (!turnstile) {
    throw new Error("Turnstile is unavailable. Please refresh and try again.");
  }

  const container = ensureTurnstileContainer();
  container.replaceChildren();

  return new Promise((resolve, reject) => {
    let widgetId = "";
    const cleanup = () => {
      if (widgetId) {
        try {
          turnstile.remove(widgetId);
        } catch {
          // Widget cleanup is best-effort after token resolution.
        }
      }
    };

    widgetId = turnstile.render(container, {
      sitekey: siteKey,
      action,
      execution: "execute",
      appearance: "interaction-only",
      callback: (token: string) => {
        cleanup();
        resolve(token);
      },
      "error-callback": () => {
        cleanup();
        reject(new Error("Turnstile verification failed. Please try again."));
      },
      "expired-callback": () => {
        cleanup();
        reject(new Error("Turnstile verification expired. Please try again."));
      },
    });
    turnstile.execute(widgetId);
  });
}
