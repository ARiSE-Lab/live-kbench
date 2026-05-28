"""DataPipeline DI seam — all external deps are injectable.

This is the main value of the Phase 2 refactor: constructing a DataPipeline
shouldn't reach out to GCS or the filesystem when every dep is provided.
"""

from unittest.mock import AsyncMock, MagicMock

from kArena.crawler import DataPipeline


def test_datapipeline_accepts_all_injected_deps(karena_config, mock_kgym_client, mock_bucket, db):
    """When every dep is supplied, __init__ must not touch disk or network."""
    mock_crawler = MagicMock()
    mock_populator = MagicMock()

    pipe = DataPipeline(
        config=karena_config,
        db=db,
        client=mock_kgym_client,
        crawler=mock_crawler,
        populator=mock_populator,
        bucket=mock_bucket,
    )

    assert pipe._client is mock_kgym_client
    assert pipe.crawler is mock_crawler
    assert pipe.populator is mock_populator
    assert pipe.bucket is mock_bucket
    assert pipe.db is db


async def test_submit_kcache_builds_short_circuits_when_no_bugs(karena_config, mock_kgym_client, mock_bucket, db):
    """With an empty DB and injected deps, submit_kcache_builds should no-op
    (no bugs needing kCache) and never hit the kGym client."""
    pipe = DataPipeline(
        config=karena_config,
        db=db,
        client=mock_kgym_client,
        crawler=MagicMock(),
        populator=MagicMock(),
        bucket=mock_bucket,
    )

    await pipe.submit_kcache_builds('fixed')

    # No bugs → create_job must never be called.
    mock_kgym_client.create_job.assert_not_called()


async def test_populate_kcache_builds_polls_each_submitted(karena_config, mock_kgym_client, mock_bucket, db):
    """Inserting a pending kCache row should cause populate_kcache_builds
    to consult kGym; we stub the response as 'still running' so no DB update."""
    from datetime import datetime

    from kArena.models import kCache

    # JobId parses its string form as hex — so use a valid hex string.
    await db.insert_kcache(kCache(
        kCacheId=0, bugId='bug-a', baseCommit='parentCommit',
        addedTime=datetime(2026, 1, 1), kGymJobId='deadbeef',
        status='success', systemMessage='Submitted',
    ))

    # Simulate "job still running" — get_job returns None → populate skips it.
    mock_kgym_client.get_job = AsyncMock(return_value=None)

    pipe = DataPipeline(
        config=karena_config,
        db=db,
        client=mock_kgym_client,
        crawler=MagicMock(),
        populator=MagicMock(),
        bucket=mock_bucket,
    )

    await pipe.populate_kcache_builds()

    mock_kgym_client.get_job.assert_awaited_once()
    # Row must still be in "submitted but unpolled" state.
    assert await db.get_submitted_kcache_builds() == [1]
