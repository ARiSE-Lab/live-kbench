"""Router Manager for LLM Judge Evaluation

This module provides a singleton RouterManager that maintains a global registry
of LiteLLM Router instances, ensuring each model config corresponds to only one
router instance across all evaluations.
"""

import asyncio
import litellm
from pathlib import Path


class RouterManager:
    """Static router manager for LLM judge evaluations.

    Maintains a global cache of Router instances keyed by model config name.
    Ensures each config file is loaded only once and shared across all evaluations.

    Usage:
        router = await RouterManager.get_router('gemini-3-pro-preview', workspace_root)
    """

    # Class variables for global state
    _routers: dict[str, litellm.Router] = {}
    _lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    async def get_router(
        cls,
        model_config_name: str,
        workspace_root: Path
    ) -> litellm.Router:
        """Get or create a Router for the given model config.

        If the router for this config already exists, returns the cached instance.
        Otherwise, loads the config file and creates a new Router.

        Args:
            model_config_name: Name of the model config file (without extension)
            workspace_root: Path to workspace root directory

        Returns:
            litellm.Router instance for this config

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config file is malformed
        """
        async with cls._lock:
            # Return cached router if exists
            if model_config_name in cls._routers:
                return cls._routers[model_config_name]

            # Load config and create new router
            config_path = workspace_root / "shared" / "judge-model-configs" / model_config_name

            if not config_path.exists():
                raise FileNotFoundError(f"Router config not found: {config_path}")

            config = cls._load_config(config_path)

            # Create router with all config parameters
            router = litellm.Router(**config)

            # Cache and return
            cls._routers[model_config_name] = router
            return router

    @staticmethod
    def _load_config(config_path: Path) -> dict:
        """Load YAML config file.

        Args:
            config_path: Path to YAML config file

        Returns:
            Parsed config dictionary

        Raises:
            ValueError: If YAML parsing fails
        """
        import yaml

        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            raise ValueError(f"Failed to load config {config_path}: {str(e)}")

    @classmethod
    def clear_cache(cls) -> None:
        """Clear all cached routers.

        Useful for testing or when config files are updated.
        """
        cls._routers.clear()

    @classmethod
    def get_cache_info(cls) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Dict with cache info: {'cached_configs': count, 'config_names': [...]}
        """
        return {
            'cached_configs': len(cls._routers),
            'config_names': list(cls._routers.keys())
        }
