import type { Metadata } from "next";
import { redirect } from "next/navigation";

export const metadata: Metadata = {
  title: "Leaderboard",
};

export default function Home() {
  redirect("/leaderboard");
}
