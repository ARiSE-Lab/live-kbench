import "server-only";

import { readFileSync, statSync } from "node:fs";
import path from "node:path";

export type kArenaWebConfig = {
  databasePath: string;
  workspaceRoot?: string;
  appName?: string;
  baseUrl?: string;
  allowedCorsOrigins?: string[];
  allowedDevOrigins?: string[];
  defaultResearchQuery?: unknown;
  paperUrl?: string;
  githubUrl?: string;
  queryTimeoutMs?: number;
};

let cachedConfig: kArenaWebConfig | undefined;
let cachedConfigMtimeMs: number | undefined;

export function getConfigPath() {
  return path.join(/*turbopackIgnore: true*/ process.cwd(), "config.json");
}

export function getConfig(): kArenaWebConfig {
  const configPath = getConfigPath();
  const configMtimeMs = statSync(configPath).mtimeMs;

  if (cachedConfig && cachedConfigMtimeMs === configMtimeMs) {
    return cachedConfig;
  }

  const rawConfig = JSON.parse(readFileSync(configPath, "utf8")) as Partial<kArenaWebConfig>;

  if (!rawConfig.databasePath || typeof rawConfig.databasePath !== "string") {
    throw new Error(`Missing databasePath in ${configPath}`);
  }

  cachedConfig = {
    databasePath: rawConfig.databasePath,
    workspaceRoot: rawConfig.workspaceRoot,
    appName: rawConfig.appName ?? "kArenaWeb",
    baseUrl: typeof rawConfig.baseUrl === "string" ? rawConfig.baseUrl : undefined,
    allowedCorsOrigins: readStringList(rawConfig.allowedCorsOrigins),
    allowedDevOrigins: readStringList(rawConfig.allowedDevOrigins),
    defaultResearchQuery: rawConfig.defaultResearchQuery,
    paperUrl: typeof rawConfig.paperUrl === "string" ? rawConfig.paperUrl : undefined,
    githubUrl: typeof rawConfig.githubUrl === "string" ? rawConfig.githubUrl : undefined,
    queryTimeoutMs: readPositiveNumber(rawConfig.queryTimeoutMs, 10_000),
  };
  cachedConfigMtimeMs = configMtimeMs;

  return cachedConfig;
}

function readStringList(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function readPositiveNumber(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

export function resolveFromAppRoot(inputPath: string) {
  return path.isAbsolute(inputPath)
    ? inputPath
    : path.resolve(/*turbopackIgnore: true*/ process.cwd(), inputPath);
}

export function getDatabasePath() {
  return resolveFromAppRoot(getConfig().databasePath);
}
