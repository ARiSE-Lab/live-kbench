"use client";

import { type CSSProperties, useEffect, useMemo, useState } from "react";
import Image from "next/image";
import type { LeaderboardEntry, LeaderboardMetricCell, LeaderboardResult } from "@/lib/leaderboard-query";
import type { DatasetSummary } from "@/lib/research-types";

type SortDirection = "asc" | "desc";
type SortKey = keyof LeaderboardEntry["metrics"];

const METRIC_ORDER: SortKey[] = [
  "crr_pass",
  "crr_mean",
  "epr_pass",
  "epr_mean",
  "file_iou_pass",
  "file_iou_mean",
  "func_iou_pass",
  "func_iou_mean",
];

const METRIC_HEADERS: Record<SortKey, string> = {
  crr_pass: "CRR pass",
  crr_mean: "CRR mean",
  epr_pass: "EPR pass",
  epr_mean: "EPR mean",
  file_iou_pass: "File IoU pass",
  file_iou_mean: "File IoU mean",
  func_iou_pass: "Func IoU pass",
  func_iou_mean: "Func IoU mean",
};

const MONTHS = buildMonths("2024-01", currentMonth());
const K_OPTIONS = Array.from({ length: 10 }, (_, index) => index + 1);

export function LeaderboardClient({ datasets }: { datasets: DatasetSummary[] }) {
  const defaultDatasetId = datasets.find((dataset) => dataset.datasetName === "lkbench-2512")?.datasetId ?? datasets[0]?.datasetId ?? 0;
  const [datasetId, setDatasetId] = useState(defaultDatasetId);
  const [startIndex, setStartIndex] = useState(0);
  const [endIndex, setEndIndex] = useState(MONTHS.length - 1);
  const [k, setK] = useState(1);
  const [sortKey, setSortKey] = useState<SortKey>("crr_pass");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [result, setResult] = useState<LeaderboardResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const startMonth = MONTHS[Math.min(startIndex, endIndex)];
  const endMonth = MONTHS[Math.max(startIndex, endIndex)];
  const startPercent = (startIndex / Math.max(MONTHS.length - 1, 1)) * 100;
  const endPercent = (endIndex / Math.max(MONTHS.length - 1, 1)) * 100;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    fetch("/api/leaderboard", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ datasetId, startMonth, endMonth, k }),
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = (await response.json()) as LeaderboardResult | { error: string };
        if (!response.ok) {
          throw new Error("error" in payload ? payload.error : "Leaderboard query failed");
        }
        setResult(payload as LeaderboardResult);
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError") {
          return;
        }
        setResult(null);
        setError(caught instanceof Error ? caught.message : "Leaderboard query failed");
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [datasetId, startMonth, endMonth, k]);

  const sortedRows = useMemo(() => {
    const rows = [...(result?.rows ?? [])];
    rows.sort((left, right) => {
      const leftValue = left.metrics[sortKey].value;
      const rightValue = right.metrics[sortKey].value;
      if (leftValue === null && rightValue === null) {
        return left.agentConfigName.localeCompare(right.agentConfigName);
      }
      if (leftValue === null) {
        return 1;
      }
      if (rightValue === null) {
        return -1;
      }
      const diff = leftValue - rightValue;
      return sortDirection === "asc" ? diff : -diff;
    });
    return rows;
  }, [result?.rows, sortDirection, sortKey]);

  return (
    <section className="leaderboardSurface">
      <header className="header">
        <div>
          <p className="eyebrow">Live-kBench Leaderboard</p>
          <h1>Leaderboard</h1>
          <p className="subtitle">Compare agent configurations over a fixed-time window with pass@k and mean@k metrics.</p>
        </div>

        <label className="leaderboardDatasetSelect">
          <span>Dataset</span>
          <select
            value={datasetId}
            onChange={(event) => {
              setLoading(true);
              setDatasetId(Number(event.target.value));
            }}
          >
            {datasets.map((dataset) => (
              <option key={dataset.datasetId} value={dataset.datasetId}>
                {dataset.datasetName}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="panel leaderboardControls">
        <div>
          <p className="controlLabel">Fixed time range</p>
          <div className="monthRangeLabels">
            <strong>{startMonth}</strong>
            <span>to</span>
            <strong>{endMonth}</strong>
          </div>
          <div
            className="dualRange"
            style={
              {
                "--range-start": `${startPercent}%`,
                "--range-end": `${endPercent}%`,
              } as CSSProperties
            }
          >
            <div className="dualRangeTrack">
              <span />
            </div>
            <input
              aria-label="Start month"
              max={MONTHS.length - 1}
              min={0}
              onChange={(event) => {
                setLoading(true);
                setStartIndex(Math.min(Number(event.target.value), endIndex));
              }}
              type="range"
              value={startIndex}
            />
            <input
              aria-label="End month"
              max={MONTHS.length - 1}
              min={0}
              onChange={(event) => {
                setLoading(true);
                setEndIndex(Math.max(Number(event.target.value), startIndex));
              }}
              type="range"
              value={endIndex}
            />
          </div>
          <div className="rangeEndpoints">
            <span>{MONTHS[0]}</span>
            <span>{MONTHS[MONTHS.length - 1]}</span>
          </div>
        </div>

        <label className="leaderboardSelect">
          <span>k</span>
          <select
            value={k}
            onChange={(event) => {
              setLoading(true);
              setK(Number(event.target.value));
            }}
          >
            {K_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="panel leaderboardPanel">
        <div className="panelHeader">
          <h2>{result ? `${result.datasetName} leaderboard` : "Leaderboard"}</h2>
          <div className="leaderboardHeaderMeta">
            <div className="leaderboardLegend" aria-label="Agent config tag legend">
              <span>
                <strong>CRF</strong>: crash resolution feedback
              </span>
              <span>
                <strong>Oracle</strong>: perfect localization hint
              </span>
              <span>
                <strong>-</strong>: fewer than k runs for at least one selected bug
              </span>
            </div>
            {loading ? <span className="statusPill">Loading</span> : null}
          </div>
        </div>
        {error ? <p className="errorText notice">{error}</p> : null}
        <div className="tableScroller">
          <table className="table leaderboardTable">
            <thead>
              <tr>
                <th>Agent config</th>
                <th>Model</th>
                <th>
                  <span className="stackedHeader">
                    <span>Bugs with</span>
                    <span>k runs</span>
                  </span>
                </th>
                {METRIC_ORDER.map((metricKey) => (
                  <th key={metricKey}>
                    <button className="sortHeader" type="button" onClick={() => toggleSort(metricKey)}>
                      {METRIC_HEADERS[metricKey].split(" ").map((part) => (
                        <span key={part}>{part}</span>
                      ))}
                      <span className="sortDirection">{sortKey === metricKey ? (sortDirection === "asc" ? "up" : "down") : ""}</span>
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((row) => (
                <tr key={row.agentConfigId}>
                  <td>
                    <div className="leaderboardIdentity">
                      <IconSlot path={row.agentIconPath} label={row.agent} fallback={row.agent.slice(0, 1).toUpperCase()} />
                      <div>
                        <strong>
                          {row.agent}
                          <ConfigTags row={row} />
                        </strong>
                        <span>{row.agentConfigName}</span>
                      </div>
                    </div>
                  </td>
                  <td>
                    <div className="leaderboardIdentity">
                      <IconSlot path={row.modelIconPath} label={row.modelFamily} fallback="?" />
                      <div>
                        <strong>{row.model}</strong>
                        <span>{row.modelConfigName}</span>
                      </div>
                    </div>
                  </td>
                  <td>
                    {row.bugsWithKRuns}/{row.bugCount}
                  </td>
                  {METRIC_ORDER.map((metricKey) => (
                    <td key={metricKey}>{formatMetric(row.metrics[metricKey])}</td>
                  ))}
                </tr>
              ))}
              {sortedRows.length === 0 ? (
                <tr>
                  <td colSpan={11}>No leaderboard rows for this range.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );

  function toggleSort(nextSortKey: SortKey) {
    if (nextSortKey === sortKey) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortKey(nextSortKey);
      setSortDirection("desc");
    }
  }
}

function ConfigTags({ row }: { row: LeaderboardEntry }) {
  if (!row.statefulEdit && !row.oracleMode) {
    return null;
  }

  return (
    <span className="configTagList">
      {row.statefulEdit ? <span className="configTag">CRF</span> : null}
      {row.oracleMode ? <span className="configTag oracleTag">Oracle</span> : null}
    </span>
  );
}

function IconSlot({ path, label, fallback }: { path: string | null; label: string; fallback: string }) {
  return (
    <span className="modelIconSlot" title={label}>
      {path ? <Image alt="" className="modelIcon" height={24} src={path} width={24} /> : <span className="iconFallback">{fallback}</span>}
    </span>
  );
}

function formatMetric(metric: LeaderboardMetricCell) {
  if (metric.value === null) {
    return "-";
  }
  return `${(metric.value * 100).toFixed(1)}%`;
}

function buildMonths(start: string, end: string) {
  const months: string[] = [];
  const [startYear, startMonth] = start.split("-").map(Number);
  const [endYear, endMonth] = end.split("-").map(Number);
  let year = startYear;
  let month = startMonth;
  while (year < endYear || (year === endYear && month <= endMonth)) {
    months.push(`${year}-${String(month).padStart(2, "0")}`);
    month += 1;
    if (month > 12) {
      year += 1;
      month = 1;
    }
  }
  return months;
}

function currentMonth() {
  return new Date().toISOString().slice(0, 7);
}
