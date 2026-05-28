import { corsJson, corsOptions, timedCorsJson } from "@/lib/cors";
import { evaluateResearchQuery } from "@/lib/research-query";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function OPTIONS(request: Request) {
  return corsOptions(request);
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as unknown;
    return timedCorsJson(request, () => evaluateResearchQuery(body));
  } catch (error) {
    return corsJson(
      request,
      {
        error: error instanceof Error ? error.message : "Invalid research query",
      },
      { status: 400 },
    );
  }
}
