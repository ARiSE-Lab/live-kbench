export const BUG_FIELDS = ["subsystem", "fixedTime", "developerPatchSize"] as const;
export const AGENT_FIELDS = ["agent", "agentConfigName", "statefulEdit", "oracleMode"] as const;
export const MODEL_FIELDS = ["model", "modelConfigName"] as const;
export const JUDGE_FIELDS = ["judgeName"] as const;
export const GROUP_FIELDS = [...BUG_FIELDS, ...AGENT_FIELDS, ...MODEL_FIELDS, ...JUDGE_FIELDS] as const;
export const METRIC_IDS = ["crr", "epr", "file_iou", "func_iou"] as const;
export const AGGREGATIONS = ["pass", "mean"] as const;

export type GroupField = (typeof GROUP_FIELDS)[number];
export type MetricId = (typeof METRIC_IDS)[number];
export type Aggregation = (typeof AGGREGATIONS)[number];

export type RangeBucket = {
  label: string;
  min?: string | number | null;
  max?: string | number | null;
};

export type FilterSpec = {
  field: GroupField;
  op: "equals" | "in" | "range";
  value?: string | number | boolean | null;
  values?: Array<string | number | boolean | null>;
  min?: string | number | null;
  max?: string | number | null;
};

export type GroupSpec = {
  field: GroupField;
  mode: "value" | "range";
  ranges?: RangeBucket[];
};

export type MetricSpec = {
  id: MetricId;
  aggregation: Aggregation;
  k: number;
  judgeName?: string;
};

export type ResearchQuery = {
  datasetId: number;
  filters: FilterSpec[];
  groups: GroupSpec[];
  metrics: MetricSpec[];
};

export type DatasetSummary = {
  datasetId: number;
  datasetName: string;
  description: string;
  addedTime: string;
  bugCount: number;
  fixedBugs: number;
  openBugs: number;
  earliestFixedTime: string | null;
  latestFixedTime: string | null;
};

export type ResearchOptions = {
  datasets: DatasetSummary[];
  fieldOptions: Partial<Record<GroupField, Array<string | number | boolean>>>;
  judges: Array<{ judgeId: number; judgeName: string }>;
};

export type MetricCell = {
  metricKey: string;
  label: string;
  value: number | null;
  availableRuns: number;
  requiredRuns: number;
  bugCount: number;
};

export type ResultNode = {
  id: string;
  label: string;
  field?: GroupField;
  bugCount: number;
  runCount: number;
  metrics: MetricCell[];
  children: ResultNode[];
};

export type ResearchQueryResult = {
  query: ResearchQuery;
  dataset: DatasetSummary;
  root: ResultNode;
};
