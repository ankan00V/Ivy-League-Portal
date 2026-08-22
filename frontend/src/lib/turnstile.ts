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

const TURNSTILE_INLINE_ID = "turnstile-mount";

function ensureTurnstileContainer(): HTMLElement {
  // A page that wants the checkbox visible renders <div id="turnstile-mount" />
  // inside its form; the floating fallback below only exists for pages that do
  // not. Without this the widget was mounted in a fixed corner box and set to
  // "interaction-only", so a user challenged by Cloudflare had nothing to click.
  const inline = document.getElementById(TURNSTILE_INLINE_ID);
  if (inline) {
    return inline;
  }
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
    // A failed script does not emit another error event when a user retries.
    // Keeping it would leave the next call waiting forever, which presents as
    // an inert signup button. Remove the failed node and start a clean load.
    if (existing.dataset.turnstileState === "error") {
      existing.remove();
      return loadTurnstileScript();
    }
    return new Promise((resolve, reject) => {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("Unable to load Turnstile")), { once: true });
    });
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.id = TURNSTILE_SCRIPT_ID;
    script.dataset.turnstileState = "loading";
    window.onTurnstileLoad = () => {
      script.dataset.turnstileState = "loaded";
      resolve();
    };
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=onTurnstileLoad";
    script.async = true;
    script.defer = true;
    script.onerror = () => {
      script.dataset.turnstileState = "error";
      reject(new Error("Unable to load Turnstile"));
    };
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
      // Visible by default: the challenge must be something the user can see
      // and complete, otherwise a failed verification is indistinguishable from
      // a broken page.
      appearance: "always",
      execution: "execute",
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

/**
 * Render a persistent, visible Turnstile widget into the page.
 *
 * getTurnstileToken above solves at submit time and removes the widget again,
 * so a user never sees the challenge - which is fine when Cloudflare stays
 * silent, but leaves a blocked sign-in looking like a broken button. This
 * mounts the managed widget where the form can show it, reports each token as
 * it arrives, and reports expiry so the caller can disable submit until a
 * fresh one is issued.
 *
 * Returns a cleanup function, or null when no site key is configured.
 */
export async function mountTurnstile(
  container: HTMLElement,
  action: string,
  onToken: (token: string | null) => void,
): Promise<(() => void) | null> {
  const siteKey = getSiteKey();
  if (!siteKey) {
    // No key configured: leave the caller free to submit. The backend still
    // decides, and rejects when it is the one enforcing.
    onToken(null);
    return null;
  }

  await loadTurnstileScript();
  const turnstile = window.turnstile;
  if (!turnstile) {
    throw new Error("Turnstile is unavailable. Please refresh and try again.");
  }

  container.replaceChildren();
  const widgetId = turnstile.render(container, {
    sitekey: siteKey,
    action,
    appearance: "always",
    callback: (token: string) => onToken(token),
    // A token is single-use and short-lived; clearing it on expiry or error
    // keeps the form honest rather than submitting something already spent.
    "error-callback": () => onToken(null),
    "expired-callback": () => onToken(null),
  });

  return () => {
    try {
      turnstile.remove(widgetId);
    } catch {
      // Best-effort: the widget may already be gone with the unmounted form.
    }
  };
}
