import { corsJson, corsOptions } from "@/lib/cors";
import { getDashboardStats, getRuntimeInfo } from "@/lib/karena";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function OPTIONS(request: Request) {
  return corsOptions(request);
}

export function GET(request: Request) {
  const stats = getDashboardStats();

  return corsJson(request, {
    ok: true,
    databaseMode: "read-only",
    stats,
    runtime: getRuntimeInfo(),
  });
}
