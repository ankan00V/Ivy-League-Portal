const rawBase = process.env.NEXT_PUBLIC_API_BASE_URL || "";

export const API_BASE_URL = rawBase.replace(/\/+$/, "");

function shouldForceProxy(baseUrl: string): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  try {
    const base = new URL(baseUrl);
    const current = new URL(window.location.origin);
    const localHosts = new Set(["localhost", "127.0.0.1", "0.0.0.0", "web.test", "api.test"]);
    const isLocalBackend = localHosts.has(base.hostname);
    const isMixedProtocol = current.protocol === "https:" && base.protocol !== "https:";
    const isCrossOriginLocal = isLocalBackend && base.origin !== current.origin;
    return isMixedProtocol || isCrossOriginLocal;
  } catch {
    return false;
  }
}

export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (!API_BASE_URL || shouldForceProxy(API_BASE_URL)) {
    return normalizedPath;
  }
  return `${API_BASE_URL}${normalizedPath}`;
}
