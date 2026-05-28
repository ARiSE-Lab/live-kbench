import modelMap from "./model-map.json";

export type ModelFamily = keyof typeof modelMap | "unknown-vendor";

export type ModelIconName = "claude" | "gemini" | "default";

export const MODEL_ICON_SIZE = 24;

export type ModelMetadata = {
  family: ModelFamily;
  icon: ModelIconName;
  iconPath: string | null;
  iconSize: number;
};

const DEFAULT_MODEL_METADATA: ModelMetadata = {
  family: "unknown-vendor",
  icon: "default",
  iconPath: null,
  iconSize: MODEL_ICON_SIZE,
};

const MODEL_FAMILY_ICONS: Record<keyof typeof modelMap, ModelIconName> = {
  claude: "claude",
  gemini: "gemini",
};

const MODEL_ICON_PATHS: Record<ModelIconName, string | null> = {
  claude: "/model-icons/claude.jpg",
  gemini: "/model-icons/gemini.svg",
  default: null,
};

export function getModelMetadata(modelName: string): ModelMetadata {
  for (const [family, models] of Object.entries(modelMap) as Array<[keyof typeof modelMap, string[]]>) {
    if (models.includes(modelName)) {
      return {
        family,
        icon: MODEL_FAMILY_ICONS[family],
        iconPath: MODEL_ICON_PATHS[MODEL_FAMILY_ICONS[family]],
        iconSize: MODEL_ICON_SIZE,
      };
    }
  }

  return DEFAULT_MODEL_METADATA;
}

export function getModelFamily(modelName: string): ModelFamily {
  return getModelMetadata(modelName).family;
}

export function getModelIcon(modelName: string): ModelIconName {
  return getModelMetadata(modelName).icon;
}

export function getModelIconPath(modelName: string): string | null {
  return getModelMetadata(modelName).iconPath;
}
