"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  GROUP_FIELDS,
  METRIC_IDS,
  type Aggregation,
  type FilterSpec,
  type GroupField,
  type GroupSpec,
  type MetricId,
  type MetricSpec,
  type ResearchOptions,
  type ResearchQuery,
  type ResearchQueryResult,
  type ResultNode,
} from "@/lib/research-types";

type Props = {
  options: ResearchOptions;
  defaultQuery: ResearchQuery | null;
};

const FIELD_LABELS: Record<GroupField, string> = {
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

export function ResearchClient({ options, defaultQuery }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [query, setQuery] = useState<ResearchQuery | null>(defaultQuery);
  const [result, setResult] = useState<ResearchQueryResult | null>(null);
  const [lastRunJson, setLastRunJson] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rangeDrafts, setRangeDrafts] = useState<Record<number, string>>({});
  const [metricKDrafts, setMetricKDrafts] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(false);

  const executeQuery = useCallback(async (nextQuery: ResearchQuery) => {
    const executedJson = JSON.stringify(nextQuery, null, 2);
    setLoading(true);
    setError(null);

    try {
      const response = await fetch("/api/research/query", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(nextQuery),
      });
      const payload = (await response.json()) as ResearchQueryResult | { error: string };
      if (!response.ok) {
        throw new Error("error" in payload ? payload.error : "Research query failed");
      }
      setResult(payload as ResearchQueryResult);
      setLastRunJson(executedJson);
    } catch (caught: unknown) {
      setResult(null);
      setLastRunJson(null);
      setError(caught instanceof Error ? caught.message : "Research query failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const encoded = searchParams.get("q");
    if (!encoded) {
      return;
    }
    try {
      const urlQuery = JSON.parse(decodeURIComponent(encoded)) as ResearchQuery;
      setQuery(urlQuery);
      void executeQuery(urlQuery);
    } catch {
      setError("Syntax error");
    }
  }, [executeQuery, searchParams]);

  const draftJson = useMemo(() => (query ? JSON.stringify(query, null, 2) : ""), [query]);
  const resultJson = useMemo(() => (result ? JSON.stringify(result, null, 2) : ""), [result]);
  const isFresh = result !== null && lastRunJson === draftJson;
  const statusLabel = error ? "Data view error" : isFresh ? "Data view fresh" : "Data view stale";
  const statusClassName = error ? "errorChip" : isFresh ? "freshChip" : "staleChip";

  if (options.datasets.length === 0 || !query) {
    return (
      <section className="panel emptyPanel">
        <h2>No datasets</h2>
        <p>The configured database has no `bug_datasets` rows, so the Research view has no dataset-scoped universe to query.</p>
      </section>
    );
  }

  return (
    <div className="researchGrid">
      <div className="builderColumn">
        <section className="panel actionPanel" aria-label="Data view actions">
          <div className="buttonRow">
            <button type="button" onClick={runQuery} disabled={loading}>
              {loading ? "Running..." : "Run"}
            </button>
            <button type="button" onClick={() => router.replace(`/research?q=${encodeURIComponent(draftJson)}`)}>
              Update URL
            </button>
            <button
              type="button"
              onClick={() => {
                if (defaultQuery) {
                  setQuery(defaultQuery);
                  setRangeDrafts({});
                  setMetricKDrafts({});
                  void executeQuery(defaultQuery);
                }
              }}
            >
              Reset
            </button>
            <span className={statusClassName}>{statusLabel}</span>
          </div>
        </section>

        <section className="panel controlPanel">
          <div className="panelHeader">
            <h2>Query Builder</h2>
          </div>
          <div className="controls">
            <label className="fieldControl">
              <span>Dataset</span>
              <select
                value={query.datasetId}
                onChange={(event) => setQuery({ ...query, datasetId: Number(event.target.value) })}
              >
                {options.datasets.map((dataset) => (
                  <option key={dataset.datasetId} value={dataset.datasetId}>
                    {dataset.datasetName} ({dataset.bugCount} bugs)
                  </option>
                ))}
              </select>
            </label>

          <fieldset className="controlGroup">
            <legend>Filters</legend>
            {query.filters.map((filter, index) => (
              <div className="inlineControls" key={`${filter.field}-${filter.op}-${index}`}>
                <select
                  value={filter.field}
                  onChange={(event) => {
                    const nextField = event.target.value as GroupField;
                    updateFilter(index, isConfigFilterField(nextField) ? { field: nextField, op: "in", values: [] } : { ...filter, field: nextField });
                  }}
                >
                  {GROUP_FIELDS.map((field) => (
                    <option key={field} value={field}>
                      {FIELD_LABELS[field]}
                    </option>
                  ))}
                </select>
                <select
                  value={isConfigFilterField(filter.field) ? "in" : filter.op}
                  onChange={(event) => updateFilter(index, withFilterOp(filter, event.target.value as FilterSpec["op"]))}
                  disabled={isConfigFilterField(filter.field)}
                >
                  <option value="in">In</option>
                  {isConfigFilterField(filter.field) ? null : <option value="equals">Equals</option>}
                  {isConfigFilterField(filter.field) ? null : <option value="range">Range</option>}
                </select>
                <button type="button" onClick={() => setQuery({ ...query, filters: query.filters.filter((_, itemIndex) => itemIndex !== index) })}>
                  Remove
                </button>
                {isConfigFilterField(filter.field) ? (
                  <CheckboxChipFilter
                    options={getFilterOptions(options, filter.field)}
                    selectedValues={getSelectedFilterValues(filter)}
                    onChange={(values) => updateFilter(index, { field: filter.field, op: "in", values })}
                  />
                ) : filter.op === "range" ? (
                  <>
                    <input
                      value={filter.min ?? ""}
                      onChange={(event) => updateFilter(index, { ...filter, min: event.target.value })}
                      placeholder="min"
                    />
                    <input
                      value={filter.max ?? ""}
                      onChange={(event) => updateFilter(index, { ...filter, max: event.target.value })}
                      placeholder="max"
                    />
                  </>
                ) : (
                  <input
                    value={filter.op === "equals" ? String(filter.value ?? "") : (filter.values ?? []).map(String).join(", ")}
                    onChange={(event) => updateFilter(index, updateFilterValue(filter, event.target.value))}
                    placeholder={filterPlaceholder(filter.field)}
                  />
                )}
              </div>
            ))}
            <button type="button" onClick={() => setQuery({ ...query, filters: [...query.filters, { field: "subsystem", op: "in", values: [] }] })}>
              Add filter
            </button>
          </fieldset>

          <fieldset className="controlGroup">
            <legend>Group by</legend>
            {query.groups.map((group, index) => (
              <div className="inlineControls" key={`${group.field}-${index}`}>
                <select
                  value={group.field}
                  onChange={(event) => updateGroup(index, { ...group, field: event.target.value as GroupField })}
                >
                  {GROUP_FIELDS.map((field) => (
                    <option key={field} value={field}>
                      {FIELD_LABELS[field]}
                    </option>
                  ))}
                </select>
                <select
                  value={group.mode}
                  onChange={(event) => updateGroup(index, withMode(group, event.target.value as GroupSpec["mode"]))}
                >
                  <option value="value">Value</option>
                  <option value="range">Range</option>
                </select>
                <button type="button" onClick={() => setQuery({ ...query, groups: query.groups.filter((_, itemIndex) => itemIndex !== index) })}>
                  Remove
                </button>
                {group.mode === "range" ? (
                  <input
                    value={rangeDrafts[index] ?? serializeRanges(group)}
                    onChange={(event) => {
                      setRangeDrafts((drafts) => ({ ...drafts, [index]: event.target.value }));
                      updateGroup(index, { ...group, ranges: parseRanges(event.target.value) });
                    }}
                    placeholder="small::20, medium:21:80, large:81:"
                  />
                ) : null}
              </div>
            ))}
            <button type="button" onClick={() => setQuery({ ...query, groups: [...query.groups, { field: "subsystem", mode: "value" }] })}>
              Add group
            </button>
          </fieldset>

          <fieldset className="controlGroup">
            <legend>Metrics</legend>
            {query.metrics.map((metric, index) => (
              <div className="inlineControls" key={`${metric.id}-${metric.aggregation}-${metric.k}-${index}`}>
                <select
                  value={metric.id}
                  onChange={(event) => updateMetric(index, { ...metric, id: event.target.value as MetricId })}
                >
                  {METRIC_IDS.map((metricId) => (
                    <option key={metricId} value={metricId}>
                      {METRIC_LABELS[metricId]}
                    </option>
                  ))}
                </select>
                <select
                  value={metric.aggregation}
                  onChange={(event) => updateMetric(index, { ...metric, aggregation: event.target.value as Aggregation })}
                >
                  <option value="pass">pass</option>
                  <option value="mean">mean</option>
                </select>
                <input
                  type="text"
                  inputMode="numeric"
                  value={metricKDrafts[index] ?? String(metric.k)}
                  onChange={(event) => {
                    setMetricKDrafts((drafts) => ({ ...drafts, [index]: event.target.value }));
                    updateMetric(index, { ...metric, k: event.target.value as unknown as number });
                  }}
                />
                {metric.id === "epr" && options.judges.length > 0 ? (
                  <select
                    value={metric.judgeName ?? ""}
                    onChange={(event) => updateMetric(index, { ...metric, judgeName: event.target.value || undefined })}
                  >
                    <option value="">Any judge</option>
                    {options.judges.map((judge) => (
                      <option key={judge.judgeId} value={judge.judgeName}>
                        {judge.judgeName}
                      </option>
                    ))}
                  </select>
                ) : null}
                <button type="button" onClick={() => setQuery({ ...query, metrics: query.metrics.filter((_, itemIndex) => itemIndex !== index) })}>
                  Remove
                </button>
              </div>
            ))}
            <button type="button" onClick={() => setQuery({ ...query, metrics: [...query.metrics, { id: "crr", aggregation: "pass", k: 1 }] })}>
              Add metric
            </button>
          </fieldset>
          </div>
        </section>
      </div>

      <div className="resultsColumn">
        <details className="panel jsonPreview">
          <summary>Generated JSON</summary>
          <pre>{draftJson}</pre>
        </details>

        <details className="panel jsonPreview">
          <summary>Result JSON</summary>
          <pre>{resultJson}</pre>
        </details>

        <section className="panel resultsPanel">
          <div className="panelHeader">
            <h2>Results</h2>
          </div>
          {loading ? <p className="notice">Running query...</p> : null}
          {error ? <p className="errorText notice">{error}</p> : null}
          {result ? <ResultTree node={result.root} /> : <p className="notice">Draft a query, then run it to load a data view.</p>}
        </section>
      </div>
    </div>
  );

  async function runQuery() {
    if (!query || loading) {
      return;
    }
    await executeQuery(query);
  }

  function updateGroup(index: number, nextGroup: GroupSpec) {
    setQuery((currentQuery) =>
      currentQuery
        ? {
            ...currentQuery,
            groups: currentQuery.groups.map((group, itemIndex) => (itemIndex === index ? nextGroup : group)),
          }
        : currentQuery,
    );
  }

  function updateFilter(index: number, nextFilter: FilterSpec) {
    setQuery((currentQuery) =>
      currentQuery
        ? {
            ...currentQuery,
            filters: currentQuery.filters.map((filter, itemIndex) => (itemIndex === index ? nextFilter : filter)),
          }
        : currentQuery,
    );
  }

  function updateMetric(index: number, nextMetric: MetricSpec) {
    setQuery((currentQuery) =>
      currentQuery
        ? {
            ...currentQuery,
            metrics: currentQuery.metrics.map((metric, itemIndex) => (itemIndex === index ? nextMetric : metric)),
          }
        : currentQuery,
    );
  }
}

function ResultTree({ node }: { node: ResultNode }) {
  if (node.children.length === 0) {
    return <MetricTable node={node} />;
  }

  return (
    <div className="resultNode">
      <div className="resultNodeHeader">
        <strong>{node.label}</strong>
        <span>{node.bugCount} bugs</span>
        <span>{node.runCount} runs</span>
      </div>
      <div className="tabTree">
        {node.children.map((child) => (
          <details key={child.id} open>
            <summary>
              {child.label} <span>{child.bugCount} bugs</span>
            </summary>
            <ResultTree node={child} />
          </details>
        ))}
      </div>
    </div>
  );
}

function MetricTable({ node }: { node: ResultNode }) {
  return (
    <table className="table compactTable">
      <thead>
        <tr>
          <th>Metric</th>
          <th>Value</th>
          <th>Runs</th>
          <th>Bugs</th>
        </tr>
      </thead>
      <tbody>
        {node.metrics.map((metric) => (
          <tr key={metric.metricKey}>
            <td>{metric.label}</td>
            <td>{formatPercent(metric.value)}</td>
            <td>
              {metric.availableRuns}/{metric.requiredRuns}
            </td>
            <td>{metric.bugCount}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CheckboxChipFilter({
  onChange,
  options,
  selectedValues,
}: {
  onChange: (values: string[]) => void;
  options: Array<string | number | boolean>;
  selectedValues: string[];
}) {
  const selectedSet = new Set(selectedValues);

  return (
    <div className="checkboxChipFilter">
      <details className="checkboxDropdown">
        <summary>{selectedValues.length === 0 ? "Select values" : `${selectedValues.length} selected`}</summary>
        <div className="checkboxDropdownMenu">
          {options.map((option) => {
            const value = String(option);
            return (
              <label key={value}>
                <input
                  checked={selectedSet.has(value)}
                  onChange={(event) => {
                    const nextValues = event.target.checked ? [...selectedValues, value] : selectedValues.filter((item) => item !== value);
                    onChange(nextValues);
                  }}
                  type="checkbox"
                />
                <span>{value}</span>
              </label>
            );
          })}
        </div>
      </details>
      <div className="selectedChips">
        {selectedValues.map((value) => (
          <button key={value} onClick={() => onChange(selectedValues.filter((item) => item !== value))} type="button">
            {value}
          </button>
        ))}
      </div>
    </div>
  );
}

function formatPercent(value: number | null) {
  if (value === null) {
    return "-";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function isConfigFilterField(field: GroupField) {
  return field === "agentConfigName" || field === "modelConfigName";
}

function getFilterOptions(options: ResearchOptions, field: GroupField) {
  return options.fieldOptions[field] ?? [];
}

function getSelectedFilterValues(filter: FilterSpec) {
  if (filter.op === "equals") {
    return filter.value === undefined || filter.value === null ? [] : [String(filter.value)];
  }
  if (filter.op === "in") {
    return (filter.values ?? []).map(String);
  }
  return [];
}

function withMode(group: GroupSpec, mode: GroupSpec["mode"]): GroupSpec {
  if (mode === "range") {
    return {
      ...group,
      mode,
      ranges: group.ranges ?? [],
    };
  }
  return { field: group.field, mode };
}

function withFilterOp(filter: FilterSpec, op: FilterSpec["op"]): FilterSpec {
  if (op === "range") {
    return { field: filter.field, op, min: null, max: null };
  }
  if (op === "equals") {
    return { field: filter.field, op, value: null };
  }
  return { field: filter.field, op, values: [] };
}

function updateFilterValue(filter: FilterSpec, value: string): FilterSpec {
  if (filter.op === "equals") {
    return { ...filter, value };
  }
  if (filter.op === "in") {
    return {
      ...filter,
      values: value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean)
        .map((item) => item),
    };
  }
  return filter;
}

function filterPlaceholder(field: GroupField) {
  if (field === "statefulEdit" || field === "oracleMode") {
    return "true";
  }
  if (field === "developerPatchSize") {
    return "10, 50, 100";
  }
  return "comma-separated values";
}

function parseRanges(value: string) {
  return value
    .split(",")
    .map((chunk) => {
      const [label, min, max] = chunk.split(":");
      return {
        label: label ?? "",
        min: min ?? "",
        max: max ?? "",
      };
    });
}

function serializeRanges(group: GroupSpec) {
  return (group.ranges ?? []).map((range) => `${range.label}:${range.min ?? ""}:${range.max ?? ""}`).join(",");
}
