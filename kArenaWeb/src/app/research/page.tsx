import type { Metadata } from "next";
import { ResearchClient } from "@/components/research-client";
import { getDefaultResearchQuery, getResearchOptions } from "@/lib/research-query";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Research",
  description: "Build detailed dataset-scoped kArena evaluation queries and inspect grouped metric results.",
};

export default function ResearchPage() {
  const options = getResearchOptions();
  const defaultQuery = getDefaultResearchQuery();

  return (
    <main>
      <div className="shell wideShell">
        <header className="header">
          <div>
            <p className="eyebrow">Detailed Data View</p>
            <h1>Research</h1>
            <p className="subtitle">
              Build a dataset-scoped query, split results into nested groups, and inspect
              metric availability for configured pass@k and mean@k views.
            </p>
          </div>
        </header>
        <ResearchClient options={options} defaultQuery={defaultQuery} />
      </div>
    </main>
  );
}
