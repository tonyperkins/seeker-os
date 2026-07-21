import type { NextRequest } from "next/server";

const BACKEND =
  process.env.SERVER_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

const PROXY_TIMEOUT_MS = 300_000;

async function proxy(req: NextRequest) {
  const path = req.nextUrl.pathname;
  const search = req.nextUrl.search;
  const url = `${BACKEND}${path}${search}`;

  const isStream = path.includes("/stream");

  const init: RequestInit = {
    method: req.method,
    headers: {
      "Content-Type": req.headers.get("Content-Type") || "application/json",
      "X-SeekerOS-Origin": req.nextUrl.origin,
    },
  };

  if (isStream) {
    init.signal = AbortSignal.timeout(PROXY_TIMEOUT_MS);
  }

  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }

  try {
    const upstream = await fetch(url, init);
    const contentType = upstream.headers.get("Content-Type") || "application/json";
    const headers = new Headers({
      "Content-Type": contentType,
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
    });
    // OAuth callbacks return a 303 from the backend. Preserve its Location
    // header so a public /api proxy completes the browser redirect to Inbound.
    const location = upstream.headers.get("Location");
    if (location) headers.set("Location", location);
    return new Response(upstream.body, {
      status: upstream.status,
      headers,
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Proxy error";
    return new Response(JSON.stringify({ detail: msg }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
