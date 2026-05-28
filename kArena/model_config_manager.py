import asyncio
from contextlib import asynccontextmanager
from pathlib import Path


class ModelConfigManager:
    """Singleton manager for model config directory distribution across vLLM replicas.

    Discovers replica configs named `{modelConfigName}.0`, `.1`, `.2`, … and
    routes each request to the replica with the fewest active users (least-refcount).
    Falls back to the plain `{modelConfigName}` directory when no replicas exist.

    Usage:
        async with ModelConfigManager.get_model_config('qwen-3.5-27b', 'mphase', workspace_root) as path:
            # path is held until the block exits; refcount decremented automatically
    """

    _replica_lists: dict[str, list[Path]] = {}
    _refcounts: dict[str, list[int]] = {}  # parallel to _replica_lists per key
    _lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    @asynccontextmanager
    async def get_model_config(
        cls,
        model_config_name: str,
        agent: str,
        workspace_root: Path,
    ):
        """Async context manager that yields the least-loaded replica path.

        Increments the selected replica's refcount on entry and decrements it
        on exit (even if an exception is raised).

        Args:
            model_config_name: Base config name (e.g. 'qwen-3.5-27b')
            agent: Agent name subdirectory (e.g. 'mphase', 'mini-swe-agent')
            workspace_root: Workspace root Path

        Yields:
            Path to the selected model config directory

        Raises:
            FileNotFoundError: If no config (plain or replicated) exists
        """
        key = f'{agent}/{model_config_name}'
        async with cls._lock:
            if key not in cls._replica_lists:
                base_dir = workspace_root / 'shared' / 'model-configs' / agent
                replicas = cls._discover_replicas(base_dir, model_config_name)
                cls._replica_lists[key] = replicas
                cls._refcounts[key] = [0] * len(replicas)

            counts = cls._refcounts[key]
            idx = counts.index(min(counts))
            counts[idx] += 1

        path = cls._replica_lists[key][idx]
        try:
            yield path
        finally:
            async with cls._lock:
                cls._refcounts[key][idx] -= 1

    @classmethod
    def _discover_replicas(cls, base_dir: Path, model_config_name: str) -> list[Path]:
        replicas: list[Path] = []
        i = 0
        while True:
            candidate = base_dir / f'{model_config_name}.{i}'
            if candidate.exists():
                replicas.append(candidate)
                i += 1
            else:
                break

        if replicas:
            return replicas

        plain = base_dir / model_config_name
        if plain.exists():
            return [plain]

        raise FileNotFoundError(
            f'No model config found for {model_config_name!r} in {base_dir}'
        )

    @classmethod
    def clear_cache(cls) -> None:
        cls._replica_lists.clear()
        cls._refcounts.clear()

    @classmethod
    def get_cache_info(cls) -> dict:
        return {
            'cached_configs': len(cls._replica_lists),
            'config_names': list(cls._replica_lists.keys()),
            'replica_counts': {k: len(v) for k, v in cls._replica_lists.items()},
            'refcounts': {k: list(v) for k, v in cls._refcounts.items()},
        }
