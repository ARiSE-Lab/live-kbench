import "server-only";

import { getConfig, getConfigPath, getDatabasePath, resolveFromAppRoot } from "./app-config";
import { getDatabase } from "./db";

export type DashboardStats = {
  bugs: number;
  openBugs: number;
  fixedBugs: number;
  agentPatches: number;
  developerPatches: number;
  kcacheEntries: number;
  agentConfigurations: number;
  datasets: number;
};

export type RecentBug = {
  bugId: string;
  extid: string;
  title: string;
  status: "open" | "fixed";
  subsystem: string;
  reportedTime: string;
};

function count(table: string, where = "") {
  const row = getDatabase()
    .prepare(`SELECT count(*) AS count FROM ${table} ${where}`)
    .get() as { count: number };

  return row.count;
}

export function getDashboardStats(): DashboardStats {
  return {
    bugs: count("syzbot_bugs"),
    openBugs: count("syzbot_bugs", "WHERE status = 'open'"),
    fixedBugs: count("syzbot_bugs", "WHERE status = 'fixed'"),
    agentPatches: count("agent_patches"),
    developerPatches: count("developer_patches"),
    kcacheEntries: count("kcache"),
    agentConfigurations: count("agent_configurations"),
    datasets: count("bug_datasets"),
  };
}

export function getRecentBugs(limit = 10): RecentBug[] {
  const rows = getDatabase()
    .prepare(
      `SELECT bugId, extid, title, status, subsystem, reportedTime
       FROM syzbot_bugs
       ORDER BY reportedTime DESC
       LIMIT ?`,
    )
    .all(limit) as Array<Omit<RecentBug, "subsystem"> & { subsystem: string }>;

  return rows.map((row) => ({
    ...row,
    subsystem: parseSubsystem(row.subsystem),
  }));
}

export function getRuntimeInfo() {
  const config = getConfig();

  return {
    appName: config.appName ?? "kArenaWeb",
    configPath: getConfigPath(),
    databasePath: getDatabasePath(),
    workspaceRoot: config.workspaceRoot ? resolveFromAppRoot(config.workspaceRoot) : undefined,
  };
}

function parseSubsystem(rawSubsystem: string) {
  try {
    const parsed = JSON.parse(rawSubsystem) as unknown;
    if (Array.isArray(parsed)) {
      return parsed.join(", ");
    }
  } catch {
    return rawSubsystem;
  }

  return rawSubsystem;
}
