import { corsJson, corsOptions, timedCorsJson } from "@/lib/cors";
import { getDatasetBugPage } from "@/lib/dataset-bugs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function OPTIONS(request: Request) {
  return corsOptions(request);
}

export function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const datasetId = Number(url.searchParams.get("datasetId"));
    const page = Number(url.searchParams.get("page") ?? "1");
    const pageSize = Number(url.searchParams.get("pageSize") ?? "25");

    return timedCorsJson(request, () => getDatasetBugPage(datasetId, page, pageSize));
  } catch (error) {
    return corsJson(
      request,
      {
        error: error instanceof Error ? error.message : "Invalid dataset bug query",
      },
      { status: 400 },
    );
  }
}
