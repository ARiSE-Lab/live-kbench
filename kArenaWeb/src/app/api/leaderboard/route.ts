import { corsJson, corsOptions, timedCorsJson } from "@/lib/cors";
import { evaluateLeaderboard } from "@/lib/leaderboard-query";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function OPTIONS(request: Request) {
  return corsOptions(request);
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as unknown;
    return timedCorsJson(request, () => evaluateLeaderboard(body));
  } catch (error) {
    return corsJson(
      request,
      {
        error: error instanceof Error ? error.message : "Invalid leaderboard query",
      },
      { status: 400 },
    );
  }
}
