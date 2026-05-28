"use client";

import { useEffect, useMemo, useState } from "react";
import type { DatasetBugPage } from "@/lib/dataset-bugs";
import type { DatasetSummary } from "@/lib/research-types";

const PAGE_SIZE = 25;

export function DatasetsClient({ datasets }: { datasets: DatasetSummary[] }) {
  const defaultDatasetId = datasets.find((dataset) => dataset.datasetName === "lkbench-2512")?.datasetId ?? datasets[0]?.datasetId ?? 0;
  const [datasetId, setDatasetId] = useState(defaultDatasetId);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<DatasetBugPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const pageCount = useMemo(() => Math.max(1, Math.ceil((result?.total ?? 0) / PAGE_SIZE)), [result?.total]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    fetch(`/api/datasets/bugs?datasetId=${datasetId}&page=${page}&pageSize=${PAGE_SIZE}`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = (await response.json()) as DatasetBugPage | { error: string };
        if (!response.ok) {
          throw new Error("error" in payload ? payload.error : "Dataset bug query failed");
        }
        setResult(payload as DatasetBugPage);
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError") {
          return;
        }
        setResult(null);
        setError(caught instanceof Error ? caught.message : "Dataset bug query failed");
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [datasetId, page]);

  return (
    <section className="datasetDashboard">
      <header className="header">
        <div>
          <p className="eyebrow">Live-kBench Datasets</p>
          <h1>Datasets</h1>
          <p className="subtitle">Browse syzbot bugs included in each dataset.</p>
        </div>

        <label className="leaderboardDatasetSelect">
          <span>Dataset</span>
          <select
            value={datasetId}
            onChange={(event) => {
              setLoading(true);
              setDatasetId(Number(event.target.value));
              setPage(1);
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

      <section className="panel datasetBugPanel">
        <div className="panelHeader">
          <h2>Bugs</h2>
          <div className="datasetPager">
            {loading ? <span className="statusPill">Loading</span> : null}
            <span>
              Page {page} of {pageCount}
            </span>
            <button disabled={page <= 1 || loading} onClick={() => setPage((value) => Math.max(1, value - 1))} type="button">
              Previous
            </button>
            <button disabled={page >= pageCount || loading} onClick={() => setPage((value) => value + 1)} type="button">
              Next
            </button>
          </div>
        </div>

        {error ? <p className="errorText notice">{error}</p> : null}

        <div className="datasetBugList">
          {(result?.bugs ?? []).map((bug) => (
            <a className="datasetBugItem" href={`https://syzkaller.appspot.com/bug?id=${bug.bugId}`} key={bug.bugId} rel="noreferrer" target="_blank">
              <strong>{bug.title}</strong>
              <span>
                {bug.status} / {bug.subsystem} / {formatDate(bug.reportedTime)}
              </span>
            </a>
          ))}
          {result && result.bugs.length === 0 ? <p className="notice">No bugs in this dataset.</p> : null}
        </div>
      </section>
    </section>
  );
}

function formatDate(value: string) {
  return value.slice(0, 10);
}
