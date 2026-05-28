import type { Metadata } from "next";
import { LeaderboardClient } from "@/components/leaderboard-client";
import { getDatasets } from "@/lib/research-query";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Leaderboard",
  description: "Compare Live-kBench agent and model configurations over fixed syzbot bug time ranges.",
};

export default function LeaderboardPage() {
  const datasets = getDatasets();

  return (
    <main>
      <div className="shell wideShell">
        <LeaderboardClient datasets={datasets} />
      </div>
    </main>
  );
}
