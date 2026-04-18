import { NextRequest, NextResponse } from "next/server";

function normalizedTarget(value?: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const withoutTrailing = trimmed.replace(/\/+$/, "");
  // Accept env values that may include /api and normalize to host root.
  return withoutTrailing.replace(/\/api(?:\/v1)?$/i, "");
}

const backendCandidates = Array.from(
  new Set(
    [
      normalizedTarget(process.env.BACKEND_INTERNAL_URL),
      normalizedTarget(process.env.NEXT_PUBLIC_API_BASE_URL),
      "http://127.0.0.1:8000",
      "http://localhost:8000",
    ].filter((value): value is string => Boolean(value)),
  ),
);

const slashSensitiveCollections = new Set([
  "v1/opportunities",
  "v1/applications",
  "v1/chat",
]);

function buildBackendUrl(target: string, request: NextRequest, path: string[]): string {
  const joinedPath = path.join("/");
  const normalizedPath = slashSensitiveCollections.has(joinedPath) ? `${joinedPath}/` : joinedPath;
  const upstream = new URL(`${target}/api/${normalizedPath}`);
  upstream.search = request.nextUrl.search;
  return upstream.toString();
}

function buildRequestHeaders(request: NextRequest): Headers {
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("keep-alive");
  headers.delete("content-length");
  return headers;
}

function buildResponseHeaders(upstreamResponse: Response): Headers {
  const headers = new Headers(upstreamResponse.headers);
  headers.delete("connection");
  headers.delete("keep-alive");
  headers.delete("transfer-encoding");
  // Body is read into memory and re-emitted by NextResponse, so preserve only compatible headers.
  headers.delete("content-encoding");
  headers.delete("content-length");
  return headers;
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const method = request.method.toUpperCase();
  const requestInit: RequestInit = {
    method,
    headers: buildRequestHeaders(request),
    redirect: "manual",
  };

  if (!["GET", "HEAD"].includes(method)) {
    requestInit.body = await request.arrayBuffer();
  }

  const requestOrigin = request.nextUrl.origin;
  const safeCandidates = backendCandidates.filter((target) => {
    try {
      return new URL(target).origin !== requestOrigin;
    } catch {
      return false;
    }
  });

  const fallbackCandidates = safeCandidates.length > 0 ? safeCandidates : ["http://127.0.0.1:8000"];
  const failureDetails: Array<{ upstream: string; reason: string }> = [];

  for (const target of fallbackCandidates) {
    const upstreamUrl = buildBackendUrl(target, request, path);
    try {
      const upstreamResponse = await fetch(upstreamUrl, requestInit);
      // Retry only on gateway-like upstream failures.
      // Do NOT swallow application-level 4xx responses (e.g., OTP validation 404),
      // otherwise the client sees a fake "backend unavailable" message.
      if ([502, 503, 504].includes(upstreamResponse.status)) {
        failureDetails.push({
          upstream: upstreamUrl,
          reason: `upstream responded with ${upstreamResponse.status}`,
        });
        continue;
      }

      const responseHeaders = buildResponseHeaders(upstreamResponse);
      const location = responseHeaders.get("location");

      if (location && location.startsWith(target)) {
        responseHeaders.set("location", location.replace(target, ""));
      }

      const responseBody = await upstreamResponse.arrayBuffer();

      return new NextResponse(responseBody, {
        status: upstreamResponse.status,
        headers: responseHeaders,
      });
    } catch (error) {
      const reason = error instanceof Error ? error.message : "unknown upstream error";
      failureDetails.push({ upstream: upstreamUrl, reason });
    }
  }

  return NextResponse.json(
    {
      detail: "Upstream backend unavailable",
      attempts: failureDetails,
    },
    { status: 503 },
  );
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as OPTIONS, proxy as HEAD };
