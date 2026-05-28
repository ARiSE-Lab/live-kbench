"""populate_kenv_base_builds — end-to-end against the DB with a fake builder."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from kArena.crawler import DataPipeline
from kArena.kenv_base_builder import KenvBaseBuildError
from kArena.models import kEnvBaseImage


def _pipeline(karena_config, db, mock_kgym_client, mock_bucket) -> DataPipeline:
    return DataPipeline(
        config=karena_config, db=db,
        client=mock_kgym_client, crawler=MagicMock(),
        populator=MagicMock(), bucket=mock_bucket,
    )


def _pending(bug_id: str = 'bug-q') -> kEnvBaseImage:
    return kEnvBaseImage(
        kEnvImageId=0, bugId=bug_id, baseCommit='parentCommit',
        addedTime=datetime(2026, 4, 1), commitId='cafebabe',
        gitUrl='https://example/git', mirrorPath='workspace/shared/repositories/x.git',
        localImageName=f'kenv-base-{bug_id}-parent-commit:latest',
        remoteImageName=f'reg/kenv-base-{bug_id}-parent-commit:latest',
        status='pending', systemMessage='Submitted',
    )


async def test_populate_marks_built_when_push_disabled(karena_config, db, mock_kgym_client, mock_bucket):
    kid = await db.insert_kenv_base(_pending())

    fake_builder = MagicMock()
    fake_builder.build = AsyncMock()
    fake_builder.push = AsyncMock()
    fake_builder.remove_local = AsyncMock()

    pipe = _pipeline(karena_config, db, mock_kgym_client, mock_bucket)
    await pipe.populate_kenv_base_builds(push=False, builder=fake_builder)

    fake_builder.build.assert_awaited_once()
    fake_builder.push.assert_not_awaited()
    fake_builder.remove_local.assert_not_awaited()

    row = await db.get_kenv_base_by_id(kid)
    assert row.status == 'built'
    assert row.builtTime is not None
    assert row.pushedTime is None


async def test_populate_pushes_and_removes_when_push_enabled(karena_config, db, mock_kgym_client, mock_bucket):
    kid = await db.insert_kenv_base(_pending())

    fake_builder = MagicMock()
    fake_builder.build = AsyncMock()
    fake_builder.push = AsyncMock()
    fake_builder.remove_local = AsyncMock()

    pipe = _pipeline(karena_config, db, mock_kgym_client, mock_bucket)
    await pipe.populate_kenv_base_builds(push=True, builder=fake_builder)

    fake_builder.build.assert_awaited_once()
    fake_builder.push.assert_awaited_once()
    fake_builder.remove_local.assert_awaited_once()

    row = await db.get_kenv_base_by_id(kid)
    assert row.status == 'pushed'
    assert row.pushedTime is not None


async def test_populate_marks_error_on_build_failure(karena_config, db, mock_kgym_client, mock_bucket):
    kid = await db.insert_kenv_base(_pending())

    fake_builder = MagicMock()
    fake_builder.build = AsyncMock(side_effect=KenvBaseBuildError('docker build exit 2: oom'))
    fake_builder.push = AsyncMock()
    fake_builder.remove_local = AsyncMock()

    pipe = _pipeline(karena_config, db, mock_kgym_client, mock_bucket)
    await pipe.populate_kenv_base_builds(push=False, builder=fake_builder)

    fake_builder.push.assert_not_awaited()
    row = await db.get_kenv_base_by_id(kid)
    assert row.status == 'error'
    assert 'oom' in row.systemMessage


async def test_populate_is_noop_when_nothing_pending(karena_config, db, mock_kgym_client, mock_bucket):
    fake_builder = MagicMock()
    fake_builder.build = AsyncMock()
    pipe = _pipeline(karena_config, db, mock_kgym_client, mock_bucket)
    await pipe.populate_kenv_base_builds(push=False, builder=fake_builder)
    fake_builder.build.assert_not_awaited()
