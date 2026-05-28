import agentMap from "./agent-map.json";

export type AgentIconName = keyof typeof agentMap | "default";

export const AGENT_ICON_SIZE = 24;

export type AgentMetadata = {
  icon: AgentIconName;
  iconPath: string | null;
  iconSize: number;
};

const DEFAULT_AGENT_METADATA: AgentMetadata = {
  icon: "default",
  iconPath: null,
  iconSize: AGENT_ICON_SIZE,
};

export function getAgentMetadata(agentName: string): AgentMetadata {
  if (agentName in agentMap) {
    return {
      icon: agentName as keyof typeof agentMap,
      iconPath: agentMap[agentName as keyof typeof agentMap],
      iconSize: AGENT_ICON_SIZE,
    };
  }

  return DEFAULT_AGENT_METADATA;
}
