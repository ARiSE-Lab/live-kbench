from pathlib import Path

from pydantic import BaseModel


class kArenaConfig(BaseModel):
    kGymEndpoint: str
    workspaceRoot: Path
    dockerPrefix: str = 'us-docker.pkg.dev/triangulate-396717/live-kbench'
    preserveKenvBase: bool = False
    googleApplicationCredentials: Path | None = None
    litellmProxyConfigPath: Path | None = None  # path to LiteLLM YAML config; None = disabled
    litellmProxyPort: int = 4000                # port to bind the singleton proxy
