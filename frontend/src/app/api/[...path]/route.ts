import { NextRequest, NextResponse } from "next/server";

const backendTarget = (process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

const slashSensitiveCollections = new Set([
  "v1/opportunities",
  "v1/applications",
  "v1/chat",
]);

function buildBackendUrl(request: NextRequest, path: string[]): string {
  const joinedPath = path.join("/");
  const normalizedPath = slashSensitiveCollections.has(joinedPath) ? `${joinedPath}/` : joinedPath;
  const upstream = new URL(`${backendTarget}/api/${normalizedPath}`);
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
  return headers;
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const upstreamUrl = buildBackendUrl(request, path);
  const method = request.method.toUpperCase();
  const requestInit: RequestInit = {
    method,
    headers: buildRequestHeaders(request),
    redirect: "manual",
  };

  if (!["GET", "HEAD"].includes(method)) {
    requestInit.body = await request.arrayBuffer();
  }

  const upstreamResponse = await fetch(upstreamUrl, requestInit);
  const responseHeaders = buildResponseHeaders(upstreamResponse);
  const location = responseHeaders.get("location");

  if (location && location.startsWith(backendTarget)) {
    responseHeaders.set("location", location.replace(backendTarget, ""));
  }

  const responseBody = await upstreamResponse.arrayBuffer();

  return new NextResponse(responseBody, {
    status: upstreamResponse.status,
    headers: responseHeaders,
  });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as OPTIONS, proxy as HEAD };
