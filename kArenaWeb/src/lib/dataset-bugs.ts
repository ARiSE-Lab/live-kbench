import "server-only";

import { getDatabase } from "./db";

export type DatasetBug = {
  bugId: string;
  title: string;
  status: string;
  subsystem: string;
  reportedTime: string;
};

export type DatasetBugPage = {
  datasetId: number;
  page: number;
  pageSize: number;
  total: number;
  bugs: DatasetBug[];
};

export function getDatasetBugPage(datasetId: number, page: number, pageSize: number): DatasetBugPage {
  if (!Number.isInteger(datasetId) || datasetId <= 0) {
    throw new Error("datasetId must be a positive integer");
  }
  if (!Number.isInteger(page) || page <= 0) {
    throw new Error("page must be a positive integer");
  }
  if (!Number.isInteger(pageSize) || pageSize <= 0 || pageSize > 100) {
    throw new Error("pageSize must be an integer between 1 and 100");
  }

  const totalRow = getDatabase()
    .prepare("SELECT count(*) AS total FROM bug_dataset_members WHERE datasetId = ?")
    .get(datasetId) as { total: number };

  const bugs = getDatabase()
    .prepare(
      `
      SELECT b.bugId, b.title, b.status, b.subsystem, b.reportedTime
      FROM bug_dataset_members bdm
      INNER JOIN syzbot_bugs b ON b.bugId = bdm.bugId
      WHERE bdm.datasetId = ?
      ORDER BY b.reportedTime DESC, b.bugId ASC
      LIMIT ? OFFSET ?
      `,
    )
    .all(datasetId, pageSize, (page - 1) * pageSize) as DatasetBug[];

  return {
    datasetId,
    page,
    pageSize,
    total: totalRow.total,
    bugs,
  };
}
