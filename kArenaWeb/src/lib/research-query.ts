import "server-only";

import { getDatabase } from "./db";
import { getConfig } from "./app-config";
import {
  AGGREGATIONS,
  GROUP_FIELDS,
  METRIC_IDS,
  type DatasetSummary,
  type FilterSpec,
  type GroupField,
  type GroupSpec,
  type MetricCell,
  type MetricId,
  type MetricSpec,
  type RangeBucket,
  type ResearchOptions,
  type ResearchQuery,
  type ResearchQueryResult,
  type ResultNode,
} from "./research-types";

type SqlValue = string | number | boolean | null;

type ResearchRow = {
  bugId: string;
  status: string;
  subsystem: string;
  fixedTime: string | null;
  developerPatchSize: number | null;
  agentPatchId: number | null;
  unionId: number | null;
  agent: string | null;
  agentConfigName: string | null;
  statefulEdit: number | null;
  oracleMode: number | null;
  model: string | null;
  modelConfigName: string | null;
  judgeName: string | null;
  crrEvaluation: string | null;
  llmStatus: string | null;
  yesCount: number | null;
  noCount: number | null;
  fileEvaluation: number | null;
  functionEvaluation: number | null;
  localizationStatus: string | null;
};

const FEATURE_LABELS: Record<GroupField, string> = {
  subsystem: "Subsystem",
  fixedTime: "Fixed time",
  developerPatchSize: "Developer patch size",
  agent: "Agent",
  agentConfigName: "Agent config",
  statefulEdit: "Stateful edit",
  oracleMode: "Oracle mode",
  model: "Model",
  modelConfigName: "Model config",
  judgeName: "Judge",
};

const METRIC_LABELS: Record<MetricId, string> = {
  crr: "CRR",
  epr: "EPR",
  file_iou: "File IoU",
  func_iou: "Func IoU",
};

export function getDatasets(): DatasetSummary[] {
  const rows = getDatabase()
    .prepare(
      `
      SELECT
        d.datasetId,
        d.datasetName,
        d.description,
        d.addedTime,
        count(DISTINCT bdm.bugId) AS bugCount,
        count(DISTINCT CASE WHEN b.status = 'fixed' THEN b.bugId END) AS fixedBugs,
        count(DISTINCT CASE WHEN b.status = 'open' THEN b.bugId END) AS openBugs,
        min(dp.fixedTime) AS earliestFixedTime,
        max(dp.fixedTime) AS latestFixedTime
      FROM bug_datasets d
      LEFT JOIN bug_dataset_members bdm ON bdm.datasetId = d.datasetId
      LEFT JOIN syzbot_bugs b ON b.bugId = bdm.bugId
      LEFT JOIN developer_patches dp ON dp.bugId = b.bugId
      GROUP BY d.datasetId
      ORDER BY d.datasetName ASC
      `,
    )
    .all() as DatasetSummary[];

  return rows.map((row) => ({
    datasetId: row.datasetId,
    datasetName: row.datasetName,
    description: row.description,
    addedTime: row.addedTime,
    bugCount: row.bugCount,
    fixedBugs: row.fixedBugs,
    openBugs: row.openBugs,
    earliestFixedTime: row.earliestFixedTime,
    latestFixedTime: row.latestFixedTime,
  }));
}

export function getResearchOptions(): ResearchOptions {
  const datasets = getDatasets();

  return {
    datasets,
    fieldOptions: {
      subsystem: distinctSubsystems(),
      agent: distinctText("agent_configurations", "agent"),
      agentConfigName: distinctText("agent_configurations", "agentConfigName"),
      statefulEdit: [false, true],
      oracleMode: [false, true],
      model: distinctText("agent_configurations", "model"),
      modelConfigName: distinctText("agent_configurations", "modelConfigName"),
      judgeName: distinctText("llm_judge_configurations", "judgeName"),
    },
    judges: (getDatabase()
      .prepare("SELECT judgeId, judgeName FROM llm_judge_configurations ORDER BY judgeName ASC")
      .all() as Array<{ judgeId: number; judgeName: string }>).map((row) => ({
      judgeId: row.judgeId,
      judgeName: row.judgeName,
    })),
  };
}

export function getDefaultResearchQuery(): ResearchQuery | null {
  const configuredQuery = getConfig().defaultResearchQuery;
  if (configuredQuery) {
    return normalizeResearchQuery(configuredQuery);
  }

  const dataset = getDatasets()[0];
  if (!dataset) {
    return null;
  }

  return {
    datasetId: dataset.datasetId,
    filters: [],
    groups: [
      { field: "subsystem", mode: "value" },
      { field: "modelConfigName", mode: "value" },
      { field: "agentConfigName", mode: "value" },
    ],
    metrics: [
      { id: "crr", aggregation: "pass", k: 1 },
      { id: "epr", aggregation: "pass", k: 1 },
      { id: "file_iou", aggregation: "mean", k: 1 },
      { id: "func_iou", aggregation: "mean", k: 1 },
    ],
  };
}

export function evaluateResearchQuery(input: unknown): ResearchQueryResult {
  const query = normalizeResearchQuery(input);
  const dataset = getDatasets().find((item) => item.datasetId === query.datasetId);
  if (!dataset) {
    throw new Error(`Dataset not found: ${query.datasetId}`);
  }

  const rows = fetchRows(query.datasetId).filter((row) => query.filters.every((filter) => rowPassesFilter(row, filter)));
  const root = buildNode("root", "All matching bugs", undefined, rows, query.groups, query.metrics);

  return {
    query,
    dataset,
    root,
  };
}

export function normalizeResearchQuery(input: unknown): ResearchQuery {
  if (!isObject(input)) {
    throw new Error("Query must be an object");
  }

  const datasetId = Number(input.datasetId);
  if (!Number.isInteger(datasetId) || datasetId <= 0) {
    throw new Error("datasetId must be a positive integer");
  }

  const filters = Array.isArray(input.filters) ? input.filters.map(normalizeFilter) : [];
  const groups = Array.isArray(input.groups) ? input.groups.map(normalizeGroup) : [];
  const metrics = Array.isArray(input.metrics) ? input.metrics.map(normalizeMetric) : [];

  if (metrics.length === 0) {
    throw new Error("At least one metric is required");
  }

  return {
    datasetId,
    filters,
    groups,
    metrics,
  };
}

function fetchRows(datasetId: number) {
  return getDatabase()
    .prepare(
      `
      SELECT
        b.bugId,
        b.status,
        b.subsystem,
        dp.fixedTime,
        dev_patch.numModifiedLines AS developerPatchSize,
        ap.agentPatchId,
        ap.unionId,
        ac.agent,
        ac.agentConfigName,
        ac.statefulEdit,
        ac.oracleMode,
        ac.model,
        ac.modelConfigName,
        ljc.judgeName,
        crr.kGymEvaluation AS crrEvaluation,
        llm.status AS llmStatus,
        llm.yesCount,
        llm.noCount,
        loc.fileEvaluation,
        loc.functionEvaluation,
        loc.status AS localizationStatus
      FROM bug_dataset_members bdm
      INNER JOIN syzbot_bugs b ON b.bugId = bdm.bugId
      LEFT JOIN developer_patches dp ON dp.bugId = b.bugId
      LEFT JOIN patches dev_patch ON dev_patch.patchId = dp.patchId
      LEFT JOIN agent_patches ap ON ap.bugId = b.bugId
      LEFT JOIN agent_configurations ac ON ac.agentConfigId = ap.agentConfigId
      LEFT JOIN patch_crash_resolution_evaluations crr ON crr.agentPatchId = ap.agentPatchId
      LEFT JOIN patch_llm_judge_evaluations llm ON llm.agentPatchId = ap.agentPatchId
      LEFT JOIN llm_judge_configurations ljc ON ljc.judgeId = llm.judgeId
      LEFT JOIN patch_localization_evaluations loc ON loc.agentPatchId = ap.agentPatchId
      WHERE bdm.datasetId = ?
      ORDER BY b.bugId ASC, ap.unionId ASC, ap.agentPatchId ASC, ljc.judgeName ASC
      `,
    )
    .all(datasetId) as ResearchRow[];
}

function buildNode(
  id: string,
  label: string,
  field: GroupField | undefined,
  rows: ResearchRow[],
  groups: GroupSpec[],
  metrics: MetricSpec[],
): ResultNode {
  const [group, ...remainingGroups] = groups;
  const children = group ? groupRows(rows, group).map((child) => buildNode(`${id}/${child.id}`, child.label, group.field, child.rows, remainingGroups, metrics)) : [];

  return {
    id,
    label,
    field,
    bugCount: distinctCount(rows.map((row) => row.bugId)),
    runCount: distinctCount(rows.map((row) => row.agentPatchId).filter((value): value is number => value !== null)),
    metrics: metrics.map((metric) => calculateMetric(rows, metric)),
    children,
  };
}

function groupRows(rows: ResearchRow[], group: GroupSpec) {
  if (group.mode === "range") {
    return (group.ranges ?? [])
      .map((range, index) => ({
        id: `${group.field}:${index}`,
        label: range.label,
        rows: rows.filter((row) => valueInRange(getFieldValue(row, group.field), range)),
      }))
      .filter((item) => item.rows.length > 0);
  }

  const grouped = new Map<string, { label: string; rows: ResearchRow[] }>();
  for (const row of rows) {
    const value = getFieldValue(row, group.field);
    const label = formatFieldValue(group.field, value);
    const key = `${group.field}:${label}`;
    const existing = grouped.get(key);
    if (existing) {
      existing.rows.push(row);
    } else {
      grouped.set(key, { label, rows: [row] });
    }
  }

  return Array.from(grouped.entries())
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => ({ id: key, label: value.label, rows: value.rows }));
}

function calculateMetric(rows: ResearchRow[], metric: MetricSpec): MetricCell {
  const bugRuns = new Map<string, Array<{ agentPatchId: number; unionId: number; score: number | null }>>();

  for (const row of rows) {
    if (row.agentPatchId === null) {
      continue;
    }
    if (metric.id === "epr" && metric.judgeName && row.judgeName !== metric.judgeName) {
      continue;
    }

    const score = metricScore(row, metric.id);
    const runs = bugRuns.get(row.bugId) ?? [];
    if (!runs.some((run) => run.agentPatchId === row.agentPatchId)) {
      runs.push({
        agentPatchId: row.agentPatchId,
        unionId: row.unionId ?? 0,
        score,
      });
      bugRuns.set(row.bugId, runs);
    }
  }

  const bugIds = Array.from(new Set(rows.map((row) => row.bugId))).sort();
  const requiredRuns = bugIds.length * metric.k;
  let availableRuns = 0;
  const bugValues: number[] = [];

  for (const bugId of bugIds) {
    const runs = (bugRuns.get(bugId) ?? [])
      .sort((left, right) => left.unionId - right.unionId || left.agentPatchId - right.agentPatchId)
      .slice(0, metric.k);
    availableRuns += runs.length;

    if (runs.length < metric.k) {
      continue;
    }

    if (metric.aggregation === "pass") {
      bugValues.push(runs.some((run) => (run.score ?? 0) > 0) ? 1 : 0);
    } else {
      bugValues.push(runs.reduce((total, run) => total + (run.score ?? 0), 0) / metric.k);
    }
  }

  return {
    metricKey: `${metric.id}_${metric.aggregation}@${metric.k}${metric.judgeName ? `_${metric.judgeName}` : ""}`,
    label: `${METRIC_LABELS[metric.id]} ${metric.aggregation}@${metric.k}`,
    value: bugValues.length === bugIds.length && bugValues.length > 0 ? mean(bugValues) : null,
    availableRuns,
    requiredRuns,
    bugCount: bugIds.length,
  };
}

function metricScore(row: ResearchRow, metric: MetricId) {
  if (metric === "crr") {
    return row.crrEvaluation === "notReproduced" ? 1 : row.crrEvaluation ? 0 : null;
  }
  if (metric === "epr") {
    if (!row.crrEvaluation || row.yesCount === null || row.noCount === null || row.llmStatus !== "success") {
      return null;
    }
    return row.crrEvaluation === "notReproduced" && row.yesCount > row.noCount ? 1 : 0;
  }
  if (metric === "file_iou") {
    return row.localizationStatus === "success" && row.fileEvaluation !== null ? row.fileEvaluation : null;
  }
  if (metric === "func_iou") {
    return row.localizationStatus === "success" && row.functionEvaluation !== null ? row.functionEvaluation : null;
  }
  return null;
}

function rowPassesFilter(row: ResearchRow, filter: FilterSpec) {
  const value = getFieldValue(row, filter.field);
  if (filter.op === "equals") {
    return normalizeComparable(value) === normalizeComparable(filter.value ?? null);
  }
  if (filter.op === "in") {
    const values = filter.values ?? [];
    return values.map(normalizeComparable).includes(normalizeComparable(value));
  }
  return valueInRange(value, filter);
}

function getFieldValue(row: ResearchRow, field: GroupField): SqlValue {
  if (field === "subsystem") {
    return parseSubsystem(row.subsystem);
  }
  if (field === "statefulEdit" || field === "oracleMode") {
    return row[field] === null ? null : Boolean(row[field]);
  }
  return row[field];
}

function formatFieldValue(field: GroupField, value: SqlValue) {
  if (value === null || value === "") {
    return `No ${FEATURE_LABELS[field]}`;
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  return String(value);
}

function parseSubsystem(rawSubsystem: string | null) {
  if (!rawSubsystem) {
    return null;
  }
  try {
    const parsed = JSON.parse(rawSubsystem) as unknown;
    if (Array.isArray(parsed)) {
      return parsed.map(String).sort().join(", ");
    }
  } catch {
    return rawSubsystem;
  }
  return rawSubsystem;
}

function valueInRange(value: SqlValue, range: Pick<RangeBucket, "min" | "max">) {
  if (value === null) {
    return false;
  }
  const comparable = typeof value === "number" ? value : String(value);
  const min = range.min ?? null;
  const max = range.max ?? null;
  if (min !== null && comparable < min) {
    return false;
  }
  if (max !== null && comparable > max) {
    return false;
  }
  return true;
}

function normalizeFilter(input: unknown): FilterSpec {
  if (!isObject(input) || !isGroupField(input.field) || !["equals", "in", "range"].includes(String(input.op))) {
    throw new Error("Invalid filter");
  }
  if (input.op === "in" && !Array.isArray(input.values)) {
    throw new Error("Filter op 'in' requires values");
  }
  return {
    field: input.field,
    op: input.op as FilterSpec["op"],
    value: input.value as FilterSpec["value"],
    values: Array.isArray(input.values) ? (input.values as FilterSpec["values"]) : undefined,
    min: emptyToNull(input.min) as FilterSpec["min"],
    max: emptyToNull(input.max) as FilterSpec["max"],
  };
}

function normalizeGroup(input: unknown): GroupSpec {
  if (!isObject(input) || !isGroupField(input.field) || !["value", "range"].includes(String(input.mode))) {
    throw new Error("Invalid group");
  }
  const ranges = Array.isArray(input.ranges)
    ? input.ranges.map((range) => {
        if (!isObject(range) || typeof range.label !== "string") {
          throw new Error("Invalid group range");
        }
        return {
          label: range.label,
          min: emptyToNull(range.min) as RangeBucket["min"],
          max: emptyToNull(range.max) as RangeBucket["max"],
        };
      })
    : undefined;

  if (input.mode === "range" && (!ranges || ranges.length === 0)) {
    throw new Error("Range groups require at least one range");
  }

  return {
    field: input.field,
    mode: input.mode as GroupSpec["mode"],
    ranges,
  };
}

function normalizeMetric(input: unknown): MetricSpec {
  if (!isObject(input) || !METRIC_IDS.includes(input.id as MetricId) || !AGGREGATIONS.includes(input.aggregation as MetricSpec["aggregation"])) {
    throw new Error("Invalid metric");
  }
  const k = Number(input.k);
  if (!Number.isInteger(k) || k <= 0) {
    throw new Error("Metric k must be a positive integer");
  }
  return {
    id: input.id as MetricId,
    aggregation: input.aggregation as MetricSpec["aggregation"],
    k,
    judgeName: typeof input.judgeName === "string" && input.judgeName ? input.judgeName : undefined,
  };
}

function isGroupField(value: unknown): value is GroupField {
  return GROUP_FIELDS.includes(value as GroupField);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function emptyToNull(value: unknown) {
  return value === "" ? null : value;
}

function normalizeComparable(value: unknown) {
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return value === null || value === undefined ? "" : String(value);
}

function distinctText(table: string, column: string) {
  return getDatabase()
    .prepare(`SELECT DISTINCT ${column} AS value FROM ${table} WHERE ${column} IS NOT NULL AND ${column} != '' ORDER BY ${column} ASC`)
    .all()
    .map((row) => (row as { value: string }).value);
}

function distinctSubsystems() {
  const rows = getDatabase().prepare("SELECT DISTINCT subsystem FROM syzbot_bugs ORDER BY subsystem ASC").all() as Array<{ subsystem: string }>;
  return Array.from(new Set(rows.map((row) => parseSubsystem(row.subsystem)).filter((value): value is string => typeof value === "string"))).sort();
}

function distinctCount(values: Array<string | number>) {
  return new Set(values).size;
}

function mean(values: number[]) {
  return values.reduce((total, value) => total + value, 0) / values.length;
}
