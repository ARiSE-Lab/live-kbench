import type { NextConfig } from "next";
import { readFileSync } from "node:fs";

type ConfigFile = {
  allowedDevOrigins?: unknown;
};

const nextConfig: NextConfig = {
  allowedDevOrigins: readAllowedDevOrigins(),
  output: "standalone",
};

export default nextConfig;

function readAllowedDevOrigins() {
  try {
    const config = JSON.parse(readFileSync("config.json", "utf8")) as ConfigFile;
    if (Array.isArray(config.allowedDevOrigins)) {
      return config.allowedDevOrigins.filter((item): item is string => typeof item === "string");
    }
  } catch {
    return [];
  }
  return [];
}
