import "server-only";

import { DatabaseSync } from "node:sqlite";
import { existsSync } from "node:fs";
import { getDatabasePath } from "./app-config";

type GlobalWithDatabase = typeof globalThis & {
  __kArenaDatabase?: DatabaseSync;
  __kArenaDatabasePath?: string;
};

const globalWithDatabase = globalThis as GlobalWithDatabase;

export function getDatabase() {
  const databasePath = getDatabasePath();

  if (!existsSync(databasePath)) {
    throw new Error(`Configured kArena database does not exist: ${databasePath}`);
  }

  if (
    globalWithDatabase.__kArenaDatabase &&
    globalWithDatabase.__kArenaDatabasePath === databasePath
  ) {
    return globalWithDatabase.__kArenaDatabase;
  }

  globalWithDatabase.__kArenaDatabase?.close();
  const database = new DatabaseSync(databasePath, { readOnly: true });
  database.exec("PRAGMA query_only = ON");

  globalWithDatabase.__kArenaDatabase = database;
  globalWithDatabase.__kArenaDatabasePath = databasePath;

  return database;
}
