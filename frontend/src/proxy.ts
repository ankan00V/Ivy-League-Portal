import { NextRequest, NextResponse } from "next/server";

function createNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

function cspValue(nonce: string): string {
  const isProduction = process.env.NODE_ENV === "production";
  const apiOrigin = process.env.NEXT_PUBLIC_API_ORIGIN?.trim();
  const extraConnect = process.env.NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA?.trim();
  const reportUri = process.env.NEXT_PUBLIC_CSP_REPORT_URI?.trim() || "/api/v1/security/csp-report";
  const trustedTypesEnabled = process.env.NEXT_PUBLIC_CSP_ENABLE_TRUSTED_TYPES === "1";
  const connectParts = new Set<string>(["'self'", "https://prod.spline.design"]);
  if (apiOrigin) connectParts.add(apiOrigin);
  if (extraConnect) {
    for (const token of extraConnect.split(/\s+/)) {
      if (token) connectParts.add(token);
    }
  }
  if (!isProduction) {
    for (const token of ["https:", "http:", "ws:", "wss:"]) connectParts.add(token);
  }
  const connectSrc = Array.from(connectParts).join(" ");
  const directives = [
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    "style-src 'self' 'unsafe-inline' https:",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data: https:",
    `connect-src ${connectSrc}`,
    "worker-src 'self' blob:",
    "manifest-src 'self'",
    "form-action 'self'",
    `report-uri ${reportUri}`,
    "report-to csp-endpoint",
  ];
  if (isProduction && trustedTypesEnabled) {
    directives.push("require-trusted-types-for 'script'");
    directives.push("trusted-types default nextjs nextjs#bundler");
  }
  return directives.join("; ");
}

export function proxy(request: NextRequest) {
  const nonce = createNonce();
  const csp = cspValue(nonce);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);

  const response = NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });

  response.headers.set("Content-Security-Policy", csp);
  response.headers.set(
    "Report-To",
    JSON.stringify({
      group: "csp-endpoint",
      max_age: 10886400,
      endpoints: [{ url: process.env.NEXT_PUBLIC_CSP_REPORT_URI?.trim() || "/api/v1/security/csp-report" }],
    }),
  );
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()");
  response.headers.set("X-DNS-Prefetch-Control", "off");
  response.headers.set("Cross-Origin-Opener-Policy", "same-origin");
  response.headers.set("Cross-Origin-Resource-Policy", "same-site");
  response.headers.set("x-nonce", nonce);
  return response;
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)"],
};
