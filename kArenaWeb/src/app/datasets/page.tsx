import type { Metadata } from "next";
import { DatasetsClient } from "@/components/datasets-client";
import { getDatasets } from "@/lib/research-query";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Datasets",
  description: "Browse Live-kBench datasets and their syzbot bug entries.",
};

export default function DatasetsPage() {
  const datasets = getDatasets();

  return (
    <main>
      <div className="shell wideShell">
        <DatasetsClient datasets={datasets} />
      </div>
    </main>
  );
}
