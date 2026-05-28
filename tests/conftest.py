"""Shared fixtures for kArena tests.

Every test uses an in-memory SQLite database with the full kArena schema
so the DB mixins can be exercised without touching the filesystem.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from kArena.db import kArenaDB
from kArena.models import kArenaConfig


@pytest.fixture
async def db():
    """Fresh in-memory kArenaDB with schema initialised."""
    d = kArenaDB(':memory:')
    await d.connect()
    await d.initialize_schema()
    try:
        yield d
    finally:
        await d.close()


@pytest.fixture
def karena_config(tmp_path: Path) -> kArenaConfig:
    """Stub config pointing at a tmp workspace root; no filesystem state."""
    return kArenaConfig(
        kGymEndpoint='http://unused.example/',
        workspaceRoot=tmp_path,
        dockerPrefix='test-registry.example/live-kbench',
        preserveKenvBase=False,
    )


@pytest.fixture
def mock_kgym_client():
    """AsyncMock stub for kGymAsyncClient — all coroutine methods return None by default."""
    return AsyncMock()


@pytest.fixture
def mock_bucket():
    """MagicMock stub for a GCS bucket. Call `.get_blob.return_value...` to set up downloads."""
    return MagicMock()
