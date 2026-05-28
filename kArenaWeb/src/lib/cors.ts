import "server-only";

import { NextResponse } from "next/server";
import { getConfig } from "./app-config";

const ALLOWED_METHODS = "GET, POST, OPTIONS";
const ALLOWED_HEADERS = "content-type";

export function corsJson(request: Request, body: unknown, init?: ResponseInit) {
  const response = NextResponse.json(body, init);
  applyCorsHeaders(request, response);
  return response;
}

export function corsOptions(request: Request) {
  const response = new NextResponse(null, { status: 204 });
  applyCorsHeaders(request, response);
  return response;
}

export function timedCorsJson(request: Request, execute: () => unknown) {
  const timeoutMs = getConfig().queryTimeoutMs ?? 10_000;
  const startedAt = performance.now();
  const body = execute();
  const elapsedMs = performance.now() - startedAt;

  if (elapsedMs > timeoutMs) {
    return corsJson(
      request,
      {
        error: `SQL query timed out after ${timeoutMs}ms`,
      },
      { status: 504 },
    );
  }

  return corsJson(request, body);
}

function applyCorsHeaders(request: Request, response: NextResponse) {
  const origin = request.headers.get("origin");
  const allowedOrigin = getAllowedOrigin(origin);
  if (!allowedOrigin) {
    return;
  }

  response.headers.set("Access-Control-Allow-Origin", allowedOrigin);
  response.headers.set("Access-Control-Allow-Methods", ALLOWED_METHODS);
  response.headers.set("Access-Control-Allow-Headers", ALLOWED_HEADERS);
  response.headers.set("Access-Control-Max-Age", "86400");
  response.headers.set("Vary", "Origin");
}

function getAllowedOrigin(origin: string | null) {
  if (!origin) {
    return null;
  }

  const allowedOrigins = getConfiguredOrigins();
  if (allowedOrigins.includes("*")) {
    return "*";
  }

  return allowedOrigins.includes(origin) ? origin : null;
}

function getConfiguredOrigins() {
  const config = getConfig();
  const origins = [...(config.allowedCorsOrigins ?? [])];
  if (config.baseUrl) {
    origins.push(readOrigin(config.baseUrl));
  }
  return origins.filter(Boolean);
}

function readOrigin(value: string) {
  try {
    return new URL(value).origin;
  } catch {
    return "";
  }
}
