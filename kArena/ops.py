"""Task factories for the karena-shell REPL.

Each function returns an asyncio.Task that can be awaited or cancelled.
Polling loops run indefinitely, logging errors and sleeping between rounds.

Typical usage in karena-shell:
    t = crawl_bugs(config, db)
    t = submit_kcache(config, db)
    t = poll_kcache(config, db)
    t = build_kenv_images(config, db)
    t = issue_crash_evals(config, db)
    t = poll_crash_evals(config, db)
    t = issue_llm_judge(db, judge_id=1, workspace_root=Path("workspace"))
    t = issue_localization(db)
    t.cancel()
"""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from kArena.crawler import DataPipeline
from kArena.db import kArenaDB
from kArena.eval_process import (
    populate_crash_resolution_evaluations,
    populate_llm_judge_evaluations,
    populate_localization_evaluations,
    submit_crash_resolution_evaluations,
)
from kArena.models import kArenaConfig

logger = logging.getLogger(__name__)


def crawl_bugs(
    config: kArenaConfig,
    db: kArenaDB,
) -> asyncio.Task:
    """One-shot: scrape Syzbot and insert/update bugs in the DB."""
    pipeline = DataPipeline(config, db)

    async def _run() -> None:
        logger.info("[crawl_bugs] starting")
        await pipeline.crawl()
        logger.info("[crawl_bugs] done")

    return asyncio.create_task(_run(), name="crawl_bugs")


def submit_kcache(
    config: kArenaConfig,
    db: kArenaDB,
    status: Literal['open', 'fixed'] = 'fixed',
    **kwargs,
) -> asyncio.Task:
    """One-shot: submit kCache build jobs for bugs that don't have one yet."""
    pipeline = DataPipeline(config, db)

    async def _run() -> None:
        logger.info(f"[submit_kcache] starting (status={status})")
        await pipeline.submit_kcache_builds(status, **kwargs)
        logger.info("[submit_kcache] done")

    return asyncio.create_task(_run(), name="submit_kcache")


def poll_kcache(
    config: kArenaConfig,
    db: kArenaDB,
    interval: int = 300,
) -> asyncio.Task:
    """Loop: poll submitted kCache build jobs and fill in verdicts."""
    pipeline = DataPipeline(config, db)

    async def _run() -> None:
        while True:
            try:
                logger.info("[poll_kcache] polling submitted kCache builds")
                await pipeline.populate_kcache_builds()
            except Exception:
                logger.exception("[poll_kcache] error")
            await asyncio.sleep(interval)

    return asyncio.create_task(_run(), name="poll_kcache")


def build_kenv_images(
    config: kArenaConfig,
    db: kArenaDB,
    status: Literal['open', 'fixed'] = 'fixed',
    interval: int = 300,
    push: bool | None = None,
) -> asyncio.Task:
    """Loop: submit new kenv-base DB rows then build (and optionally push) pending images."""
    pipeline = DataPipeline(config, db)

    async def _run() -> None:
        while True:
            try:
                logger.info(f"[build_kenv_images] tick (status={status})")
                await pipeline.submit_kenv_base_builds(status)
                await pipeline.populate_kenv_base_builds(push=push)
            except Exception:
                logger.exception("[build_kenv_images] error")
            await asyncio.sleep(interval)

    return asyncio.create_task(_run(), name="build_kenv_images")


def populate_developer_patches(
    config: kArenaConfig,
    db: kArenaDB,
    interval: int = 300,
) -> asyncio.Task:
    """Loop: analyze developer patches for fixed bugs whose kenv-base is built."""
    pipeline = DataPipeline(config, db)

    async def _run() -> None:
        while True:
            try:
                logger.info("[populate_developer_patches] tick")
                await pipeline.populate_developer_patches()
            except Exception:
                logger.exception("[populate_developer_patches] error")
            await asyncio.sleep(interval)

    return asyncio.create_task(_run(), name="populate_developer_patches")


def issue_crash_evals(
    config: kArenaConfig,
    db: kArenaDB,
    interval: int = 300,
    agent_config_id: int | None = None,
    excl_queue: bool = True,
) -> asyncio.Task:
    """Loop: submit crash-resolution eval jobs for unevaluated patches."""
    async def _run() -> None:
        while True:
            try:
                logger.info("[issue_crash_evals] submitting new evaluations")
                await submit_crash_resolution_evaluations(
                    db, config,
                    agent_config_id=agent_config_id,
                    excl_queue=excl_queue,
                )
            except Exception:
                logger.exception("[issue_crash_evals] error")
            await asyncio.sleep(interval)

    return asyncio.create_task(_run(), name="issue_crash_evals")


def poll_crash_evals(
    config: kArenaConfig,
    db: kArenaDB,
    interval: int = 300,
) -> asyncio.Task:
    """Loop: poll submitted crash-resolution jobs and fill in results."""
    async def _run() -> None:
        while True:
            try:
                logger.info("[poll_crash_evals] polling submitted evaluations")
                await populate_crash_resolution_evaluations(db, config)
            except Exception:
                logger.exception("[poll_crash_evals] error")
            await asyncio.sleep(interval)

    return asyncio.create_task(_run(), name="poll_crash_evals")


def issue_llm_judge(
    db: kArenaDB,
    judge_id: int,
    workspace_root: Path,
    interval: int = 300,
) -> asyncio.Task:
    """Loop: run LLM judge evaluations for unevaluated agent/dev patch pairs."""
    async def _run() -> None:
        while True:
            try:
                logger.info(f"[issue_llm_judge] running judge_id={judge_id}")
                await populate_llm_judge_evaluations(db, judge_id, workspace_root)
            except Exception:
                logger.exception("[issue_llm_judge] error")
            await asyncio.sleep(interval)

    return asyncio.create_task(_run(), name="issue_llm_judge")


def issue_localization(
    db: kArenaDB,
    interval: int = 300,
) -> asyncio.Task:
    """Loop: compute file/function IoU localization scores for unevaluated patches."""
    async def _run() -> None:
        while True:
            try:
                logger.info("[issue_localization] running localization evaluations")
                await populate_localization_evaluations(db)
            except Exception:
                logger.exception("[issue_localization] error")
            await asyncio.sleep(interval)

    return asyncio.create_task(_run(), name="issue_localization")


def export_to_hf(
    db: kArenaDB,
    hf_repo: str,
    token: str | None = None,
    *,
    private: bool = True,
) -> asyncio.Task:
    """One-shot: export all bugs and dataset definitions to HF Hub."""
    from kArena.hf_sync import HFBugExporter

    async def _run() -> None:
        logger.info(f"[export_to_hf] starting → {hf_repo}")
        exporter = HFBugExporter(db)
        await exporter.export(hf_repo, token=token, private=private)
        logger.info("[export_to_hf] done")

    return asyncio.create_task(_run(), name="export_to_hf")


def import_from_hf(
    config: kArenaConfig,
    db: kArenaDB,
    hf_repo: str,
    token: str | None = None,
) -> asyncio.Task:
    """One-shot: import bugs and dataset definitions from HF Hub into the DB.

    No kCache builds or kEnv image builds are triggered. Run ``poll_kcache``
    and ``build_kenv_images`` separately after this completes.
    """
    pipeline = DataPipeline(config, db)

    async def _run() -> None:
        logger.info(f"[import_from_hf] starting from {hf_repo}")
        await pipeline.import_from_hf(hf_repo, token=token)
        logger.info("[import_from_hf] done")

    return asyncio.create_task(_run(), name="import_from_hf")
