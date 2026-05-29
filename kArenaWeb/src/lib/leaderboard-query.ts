import "server-only";

import { getDatabase } from "./db";
import { getAgentMetadata } from "./agent-metadata";
import { getModelMetadata } from "./model-metadata";

type LeaderboardMetricId =
  | "crr_pass"
  | "crr_mean"
  | "epr_pass"
  | "epr_mean"
  | "file_iou_pass"
  | "file_iou_mean"
  | "func_iou_pass"
  | "func_iou_mean";

type LeaderboardRow = {
  agentConfigId: number;
  agent: string;
  agentConfigName: string;
  model: string;
  modelConfigName: string;
  statefulEdit: number;
  oracleMode: number;
  bugId: string;
  agentPatchId: number | null;
  unionId: number | null;
  crrEvaluation: string | null;
  llmStatus: string | null;
  yesCount: number | null;
  noCount: number | null;
  fileEvaluation: number | null;
  functionEvaluation: number | null;
  localizationStatus: string | null;
};

type LeaderboardDataset = {
  datasetId: number;
  datasetName: string;
};

type RunScore = {
  agentPatchId: number;
  unionId: number;
  scores: Record<"crr" | "epr" | "file_iou" | "func_iou", number>;
};

export type LeaderboardMetricCell = {
  key: LeaderboardMetricId;
  label: string;
  value: number | null;
  availableRuns: number;
  requiredRuns: number;
};

export type LeaderboardEntry = {
  agentConfigId: number;
  agent: string;
  agentConfigName: string;
  model: string;
  modelConfigName: string;
  statefulEdit: boolean;
  oracleMode: boolean;
  agentIconPath: string | null;
  agentIconSize: number;
  modelFamily: string;
  modelIconPath: string | null;
  modelIconSize: number;
  bugCount: number;
  bugsWithKRuns: number;
  runCount: number;
  metrics: Record<LeaderboardMetricId, LeaderboardMetricCell>;
};

export type LeaderboardResult = {
  datasetId: number;
  datasetName: string;
  startMonth: string;
  endMonth: string;
  fixedTimeStart: string;
  fixedTimeEnd: string;
  k: number;
  bugCount: number;
  rows: LeaderboardEntry[];
};

const METRIC_LABELS: Record<LeaderboardMetricId, string> = {
  crr_pass: "CRR pass",
  crr_mean: "CRR mean",
  epr_pass: "EPR pass",
  epr_mean: "EPR mean",
  file_iou_pass: "File IoU pass",
  file_iou_mean: "File IoU mean",
  func_iou_pass: "Func IoU pass",
  func_iou_mean: "Func IoU mean",
};

type LeaderboardCacheGlobal = typeof globalThis & {
  __kArenaLeaderboardCache?: Map<string, LeaderboardResult>;
};

const leaderboardCacheGlobal = globalThis as LeaderboardCacheGlobal;
const leaderboardCache = leaderboardCacheGlobal.__kArenaLeaderboardCache ?? new Map<string, LeaderboardResult>();
leaderboardCacheGlobal.__kArenaLeaderboardCache = leaderboardCache;

export function evaluateLeaderboard(input: unknown): LeaderboardResult {
  if (!isObject(input)) {
    throw new Error("Leaderboard query must be an object");
  }

  const startMonth = typeof input.startMonth === "string" ? input.startMonth : "2024-01";
  const endMonth = typeof input.endMonth === "string" ? input.endMonth : currentMonth();
  const k = Number(input.k);
  if (!Number.isInteger(k) || k <= 0) {
    throw new Error("k must be a positive integer");
  }

  const dataset = resolveDataset(input.datasetId);
  const fixedTimeStart = `${startMonth}-01`;
  const fixedTimeEnd = `${endMonth}-${lastDayOfMonth(endMonth)}`;
  const cacheKey = getCacheKey(dataset.datasetId, startMonth, endMonth, k);
  const cachedResult = leaderboardCache.get(cacheKey);
  if (cachedResult) {
    return cachedResult;
  }
  const selectedBugIds = fetchSelectedBugIds(dataset.datasetId, fixedTimeStart, fixedTimeEnd);

  const result = {
    datasetId: dataset.datasetId,
    datasetName: dataset.datasetName,
    startMonth,
    endMonth,
    fixedTimeStart,
    fixedTimeEnd,
    k,
    bugCount: selectedBugIds.length,
    rows: buildEntries(fetchLeaderboardRows(dataset.datasetId, fixedTimeStart, fixedTimeEnd), selectedBugIds, k),
  };
  leaderboardCache.set(cacheKey, result);

  return result;
}

function resolveDataset(inputDatasetId: unknown): LeaderboardDataset {
  if (inputDatasetId === undefined || inputDatasetId === null || inputDatasetId === "") {
    return getDefaultDataset();
  }

  const datasetId = Number(inputDatasetId);
  if (!Number.isInteger(datasetId) || datasetId <= 0) {
    throw new Error("datasetId must be a positive integer");
  }

  const row = getDatabase()
    .prepare(
      `
      SELECT datasetId, datasetName
      FROM bug_datasets
      WHERE datasetId = ?
      `,
    )
    .get(datasetId) as { datasetId: number; datasetName: string } | undefined;

  if (!row) {
    throw new Error(`Dataset not found: ${datasetId}`);
  }

  return {
    datasetId: row.datasetId,
    datasetName: row.datasetName,
  };
}

function getDefaultDataset(): LeaderboardDataset {
  const row = getDatabase()
    .prepare(
      `
      SELECT datasetId, datasetName
      FROM bug_datasets
      ORDER BY CASE WHEN datasetName = 'lkbench-2512' THEN 0 ELSE 1 END, datasetId ASC
      LIMIT 1
      `,
    )
    .get() as { datasetId: number; datasetName: string } | undefined;

  if (!row) {
    throw new Error("No dataset available for leaderboard");
  }

  return {
    datasetId: row.datasetId,
    datasetName: row.datasetName,
  };
}

function fetchSelectedBugIds(datasetId: number, fixedTimeStart: string, fixedTimeEnd: string) {
  const rows = getDatabase()
    .prepare(
      `
      SELECT DISTINCT bdm.bugId
      FROM bug_dataset_members bdm
      INNER JOIN developer_patches dp ON dp.bugId = bdm.bugId
      WHERE bdm.datasetId = ?
        AND dp.fixedTime >= ?
        AND dp.fixedTime <= ?
      ORDER BY bdm.bugId
      `,
    )
    .all(datasetId, fixedTimeStart, fixedTimeEnd) as Array<{ bugId: string }>;

  return rows.map((row) => row.bugId);
}

function fetchLeaderboardRows(datasetId: number, fixedTimeStart: string, fixedTimeEnd: string) {
  return getDatabase()
    .prepare(
      `
      WITH selected_bugs AS (
        SELECT DISTINCT bdm.bugId
        FROM bug_dataset_members bdm
        INNER JOIN developer_patches dp ON dp.bugId = bdm.bugId
        WHERE bdm.datasetId = ?
          AND dp.fixedTime >= ?
          AND dp.fixedTime <= ?
      )
      SELECT
        ac.agentConfigId,
        ac.agent,
        ac.agentConfigName,
        ac.model,
        ac.modelConfigName,
        ac.statefulEdit,
        ac.oracleMode,
        sb.bugId,
        ap.agentPatchId,
        ap.unionId,
        crr.kGymEvaluation AS crrEvaluation,
        llm.status AS llmStatus,
        llm.yesCount,
        llm.noCount,
        loc.fileEvaluation,
        loc.functionEvaluation,
        loc.status AS localizationStatus
      FROM agent_configurations ac
      CROSS JOIN selected_bugs sb
      LEFT JOIN agent_patches ap
        ON ap.agentConfigId = ac.agentConfigId
        AND ap.bugId = sb.bugId
      LEFT JOIN patch_crash_resolution_evaluations crr ON crr.agentPatchId = ap.agentPatchId
      LEFT JOIN patch_llm_judge_evaluations llm ON llm.agentPatchId = ap.agentPatchId
      LEFT JOIN patch_localization_evaluations loc ON loc.agentPatchId = ap.agentPatchId
      `,
    )
    .all(datasetId, fixedTimeStart, fixedTimeEnd) as LeaderboardRow[];
}

function buildEntries(rows: LeaderboardRow[], selectedBugIds: string[], k: number) {
  const byConfig = new Map<number, LeaderboardRow[]>();
  for (const row of rows) {
    const configRows = byConfig.get(row.agentConfigId) ?? [];
    configRows.push(row);
    byConfig.set(row.agentConfigId, configRows);
  }

  return Array.from(byConfig.values()).map((configRows) => {
    const first = configRows[0];
    const agentMetadata = getAgentMetadata(first.agent);
    const modelMetadata = getModelMetadata(first.model);
    const runCount = new Set(configRows.map((row) => row.agentPatchId).filter((value): value is number => value !== null)).size;
    const runsByBug = buildRunsByBug(configRows);
    const metrics = calculateMetrics(selectedBugIds, runsByBug, k);

    return {
      agentConfigId: first.agentConfigId,
      agent: first.agent,
      agentConfigName: first.agentConfigName,
      model: first.model,
      modelConfigName: first.modelConfigName,
      statefulEdit: Boolean(first.statefulEdit),
      oracleMode: Boolean(first.oracleMode),
      agentIconPath: agentMetadata.iconPath,
      agentIconSize: agentMetadata.iconSize,
      modelFamily: modelMetadata.family,
      modelIconPath: modelMetadata.iconPath,
      modelIconSize: modelMetadata.iconSize,
      bugCount: selectedBugIds.length,
      bugsWithKRuns: countBugsWithKRuns(selectedBugIds, runsByBug, k),
      runCount,
      metrics,
    };
  });
}

function buildRunsByBug(rows: LeaderboardRow[]) {
  const runsByBug = new Map<string, RunScore[]>();
  for (const row of rows) {
    if (row.agentPatchId === null) {
      continue;
    }

    const runs = runsByBug.get(row.bugId) ?? [];
    if (!runs.some((run) => run.agentPatchId === row.agentPatchId)) {
      runs.push({
        agentPatchId: row.agentPatchId,
        unionId: row.unionId ?? 0,
        scores: {
          crr: row.crrEvaluation === "notReproduced" ? 1 : 0,
          epr: row.crrEvaluation === "notReproduced" && row.llmStatus === "success" && row.yesCount !== null && row.noCount !== null && row.yesCount > row.noCount ? 1 : 0,
          file_iou: row.localizationStatus === "success" && row.fileEvaluation !== null ? row.fileEvaluation : 0,
          func_iou: row.localizationStatus === "success" && row.functionEvaluation !== null ? row.functionEvaluation : 0,
        },
      });
      runsByBug.set(row.bugId, runs);
    }
  }
  return runsByBug;
}

function calculateMetrics(bugIds: string[], runsByBug: Map<string, RunScore[]>, k: number) {
  return {
    crr_pass: calculateCell("crr_pass", "crr", "pass", bugIds, runsByBug, k),
    crr_mean: calculateCell("crr_mean", "crr", "mean", bugIds, runsByBug, k),
    epr_pass: calculateCell("epr_pass", "epr", "pass", bugIds, runsByBug, k),
    epr_mean: calculateCell("epr_mean", "epr", "mean", bugIds, runsByBug, k),
    file_iou_pass: calculateCell("file_iou_pass", "file_iou", "pass", bugIds, runsByBug, k),
    file_iou_mean: calculateCell("file_iou_mean", "file_iou", "mean", bugIds, runsByBug, k),
    func_iou_pass: calculateCell("func_iou_pass", "func_iou", "pass", bugIds, runsByBug, k),
    func_iou_mean: calculateCell("func_iou_mean", "func_iou", "mean", bugIds, runsByBug, k),
  };
}

function countBugsWithKRuns(bugIds: string[], runsByBug: Map<string, RunScore[]>, k: number) {
  return bugIds.filter((bugId) => (runsByBug.get(bugId) ?? []).length >= k).length;
}

function calculateCell(
  key: LeaderboardMetricId,
  scoreKey: keyof RunScore["scores"],
  aggregation: "pass" | "mean",
  bugIds: string[],
  runsByBug: Map<string, RunScore[]>,
  k: number,
): LeaderboardMetricCell {
  const requiredRuns = bugIds.length * k;
  let availableRuns = 0;
  const bugValues: number[] = [];

  for (const bugId of bugIds) {
    const runs = (runsByBug.get(bugId) ?? [])
      .sort((left, right) => left.unionId - right.unionId || left.agentPatchId - right.agentPatchId)
      .slice(0, k);
    availableRuns += runs.length;

    if (runs.length < k) {
      continue;
    }

    if (aggregation === "pass") {
      bugValues.push(runs.some((run) => run.scores[scoreKey] > 0) ? 1 : 0);
    } else {
      bugValues.push(runs.reduce((total, run) => total + run.scores[scoreKey], 0) / k);
    }
  }

  return {
    key,
    label: `${METRIC_LABELS[key]}@${k}`,
    value: bugValues.length === bugIds.length && bugValues.length > 0 ? mean(bugValues) : null,
    availableRuns,
    requiredRuns,
  };
}

function currentMonth() {
  return new Date().toISOString().slice(0, 7);
}

function lastDayOfMonth(month: string) {
  const [year, monthIndex] = month.split("-").map(Number);
  return String(new Date(year, monthIndex, 0).getDate()).padStart(2, "0");
}

function getCacheKey(datasetId: number, startMonth: string, endMonth: string, k: number) {
  return JSON.stringify({ datasetId, startMonth, endMonth, k });
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function mean(values: number[]) {
  return values.reduce((total, value) => total + value, 0) / values.length;
}
