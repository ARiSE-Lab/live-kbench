"""Evaluation Process Module

This module provides functions for populating evaluation results in the kArena database.
It handles batch evaluation of agent patches using kGym's crash resolution testing,
LLM judge patch equivalence evaluation, and localization metrics.

Main functions:
- populate_crash_resolution_evaluations(): Evaluates all unevaluated agent patches
- populate_llm_judge_evaluations(): Runs LLM judge on agent vs developer patches
- populate_localization_evaluations(): Computes file/function IoU metrics
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiolimiter import AsyncLimiter
from KBDr.kclient import kGymAsyncClient
from kArena.models import kArenaConfig
from kArena.db import kArenaDB
from kArena.evaluation.kgym_eval import kGymEval
from kArena.evaluation.llm_judge_eval import LLMJudgeEval
from kArena.evaluation.localization_eval import LocalizationEval

logger = logging.getLogger(__name__)


async def _run_concurrent(
    items: list,
    per_item: Callable[[Any], Awaitable[None]],
    max_concurrent: int,
    item_label: str,
) -> None:
    """Run per_item(item) for each item with bounded concurrency.

    per_item owns its own error handling and logging; this helper only
    provides the semaphore + TaskGroup + empty-list short-circuit.
    """
    if not items:
        logger.info(f'No {item_label} to process')
        return
    logger.info(f'Processing {len(items)} {item_label}')
    sem = asyncio.Semaphore(max_concurrent)

    async def _guarded(item):
        async with sem:
            await per_item(item)

    async with asyncio.TaskGroup() as tg:
        for item in items:
            tg.create_task(_guarded(item))


async def submit_crash_resolution_evaluations(
    db: kArenaDB,
    config: kArenaConfig,
    max_concurrent: int = 16,
    excl_queue: bool = True,
    agent_config_id: int | None = None
) -> None:
    """Submit crash resolution evaluation jobs for all unevaluated agent patches.

    This function:
    1. Retrieves all agent patch ids that haven't been submitted for evaluation
    2. Creates kGymEval instances and submits jobs
    3. Stores records with status='success' and kGymEvalJobId (kGymEvaluation=NULL)

    Args:
        db: kArenaDB instance for database operations
        config: kArenaConfig containing kGym endpoint configuration
        max_concurrent: Maximum number of concurrent submissions (default: 16)
        agent_config_id: If set, only submit patches from this agentConfigId
    """
    logger.info('Starting crash resolution evaluation submission')

    unevaluated_agent_patch_ids = await db.get_yet_evaluated_agent_patches('crashResolution', agent_config_id=agent_config_id)
    client = kGymAsyncClient(config.kGymEndpoint, excl_queue='benchmark' if excl_queue else None)

    async def submit_single(agent_patch_id: int) -> None:
        try:
            logger.info(f'Submitting evaluation for agent patch id {agent_patch_id}')
            evaluator = kGymEval(agent_patch_id=agent_patch_id, db=db, client=client)
            eval_result = await evaluator.submit_eval()
            eval_id = await db.insert_crash_resolution_eval(eval_result)
            if eval_result.status == 'success' and eval_result.kGymEvaluation is None:
                logger.info(
                    f'Agent patch id {agent_patch_id} submitted successfully '
                    f'(evalId={eval_id}, jobId={eval_result.kGymEvalJobId})'
                )
            else:
                logger.warning(
                    f'Agent patch id {agent_patch_id} submission failed '
                    f'(evalId={eval_id}): {eval_result.systemMessage}'
                )
        except ValueError as e:
            logger.error(f'Skipping agent patch id {agent_patch_id}: {str(e)}')
        except Exception as e:
            logger.error(f'Unexpected error submitting agent patch id {agent_patch_id}: {str(e)}', exc_info=True)

    await _run_concurrent(unevaluated_agent_patch_ids, submit_single, max_concurrent, 'agent patches to submit')
    logger.info(f'Crash resolution evaluation submission completed for {len(unevaluated_agent_patch_ids)} agent patches')


async def populate_crash_resolution_evaluations(
    db: kArenaDB,
    config: kArenaConfig,
    max_concurrent: int = 16
) -> None:
    """Poll submitted crash resolution evaluations and populate results.

    This function:
    1. Retrieves all evaluation records with status='success' and kGymEvaluation IS NULL
    2. Polls kGym for job status
    3. Updates records with results when jobs are complete
    4. Skips jobs that are still in progress (Pending/InProgress/Waiting)

    Args:
        db: kArenaDB instance for database operations
        config: kArenaConfig containing kGym endpoint configuration
        max_concurrent: Maximum number of concurrent polls (default: 16)
    """
    logger.info('Starting crash resolution evaluation polling')

    submitted_eval_ids = await db.get_submitted_crash_resolution_evals()
    client = kGymAsyncClient(config.kGymEndpoint, excl_queue='benchmark')

    completed_count = 0
    in_progress_count = 0
    error_count = 0

    async def poll_single(eval_id: int) -> None:
        nonlocal completed_count, in_progress_count, error_count
        try:
            logger.info(f'Polling evaluation id {eval_id}')
            eval_result = await kGymEval.poll_eval(eval_id, db, client)
            if eval_result is None:
                in_progress_count += 1
                logger.info(f'Evaluation id {eval_id} still in progress')
                return
            await db.update_crash_resolution_eval(eval_result)
            if eval_result.status == 'success':
                completed_count += 1
                logger.info(
                    f'Evaluation id {eval_id} completed successfully '
                    f'(kGymEvaluation={eval_result.kGymEvaluation})'
                )
            else:
                error_count += 1
                logger.warning(f'Evaluation id {eval_id} completed with errors: {eval_result.systemMessage}')
        except ValueError as e:
            logger.error(f'Skipping evaluation id {eval_id}: {str(e)}')
        except Exception as e:
            logger.error(f'Unexpected error polling evaluation id {eval_id}: {str(e)}', exc_info=True)

    await _run_concurrent(submitted_eval_ids, poll_single, max_concurrent, 'submitted evaluations')
    logger.info(
        f'Crash resolution evaluation polling completed: '
        f'{completed_count} completed, {in_progress_count} still in progress, {error_count} errors'
    )


async def populate_llm_judge_evaluations(
    db: kArenaDB,
    judge_id: int,
    workspace_root: Path,
    max_concurrent: int = 10
) -> None:
    """Populate LLM judge evaluations for all unevaluated agent patches.

    This function:
    1. Retrieves the judge configuration from the database
    2. Finds all (agentPatchId, devPatchId) pairs that haven't been evaluated
    3. Creates LLMJudgeEval instances for each pair
    4. Runs evaluations with controlled concurrency (to avoid rate limits)
    5. Stores results in the patch_llm_judge_evaluations table

    Args:
        db: kArenaDB instance for database operations
        judge_id: The judgeId to use for evaluation
        workspace_root: Path to workspace root (for finding model configs)
        max_concurrent: Maximum number of concurrent LLM calls (default: 10)

    Example:
        >>> async with kArenaDB("karena.db") as db:
        >>>     await populate_llm_judge_evaluations(db, judge_id=1, workspace_root=Path("workspace"))
    """
    logger.info(f"Starting LLM judge evaluation population (judgeId={judge_id})")

    try:
        judge_config = await db.get_llm_judge_config(judge_id)
        logger.info(
            f"Using judge: {judge_config.judgeName} "
            f"(model={judge_config.model}, nVotes={judge_config.nVotes})"
        )
    except ValueError as e:
        logger.error(f"Judge configuration not found: {e}")
        return

    unevaluated_pairs = await db.get_yet_evaluated_llm_judge_patches(judge_id)

    async def evaluate_pair(pair: tuple[int, int]) -> None:
        agent_patch_id, dev_patch_id = pair
        try:
            logger.info(f"Evaluating pair: agentPatchId={agent_patch_id}, devPatchId={dev_patch_id}")
            agent_patch = await db.get_agent_patch(agent_patch_id)
            dev_patch = await db.get_developer_patch(dev_patch_id)
            evaluator = LLMJudgeEval(
                judge_config=judge_config,
                agent_patch=agent_patch,
                dev_patch=dev_patch,
                db=db,
                workspace_root=workspace_root
            )
            eval_result = await evaluator.run_eval()
            eval_id = await db.insert_llm_judge_eval(eval_result)
            if eval_result.status == 'success':
                logger.info(
                    f"Pair evaluated successfully (evalId={eval_id}): "
                    f"{eval_result.yesCount} yes, {eval_result.noCount} no, "
                    f"{eval_result.errorCount} errors"
                )
            else:
                logger.warning(f"Pair evaluation failed (evalId={eval_id}): {eval_result.systemMessage}")
        except ValueError as e:
            logger.error(f"Skipping pair (agentPatchId={agent_patch_id}, devPatchId={dev_patch_id}): {str(e)}")
        except Exception as e:
            logger.error(
                f"Unexpected error evaluating pair "
                f"(agentPatchId={agent_patch_id}, devPatchId={dev_patch_id}): {str(e)}",
                exc_info=True
            )

    await _run_concurrent(unevaluated_pairs, evaluate_pair, max_concurrent, 'patch pairs')
    logger.info(f"LLM judge evaluation completed for {len(unevaluated_pairs)} patch pairs")


async def populate_localization_evaluations(
    db: kArenaDB,
    max_concurrent: int = 16
) -> None:
    """Populate localization evaluations for all unevaluated successful agent patches.

    This function:
    1. Retrieves all agent patch ids with status='success' that haven't been evaluated
    2. For each agent patch, finds the corresponding developer patch (fixed bugs only)
    3. Runs LocalizationEval to compute file-level and function-level IoU metrics
    4. Stores results in the patch_localization_evaluations table

    Args:
        db: kArenaDB instance for database operations
        max_concurrent: Maximum number of concurrent evaluations (default: 16)

    Example:
        >>> db = kArenaDB("karena.db")
        >>> await db.connect()
        >>> await populate_localization_evaluations(db)
    """
    logger.info('Starting localization evaluation population')

    unevaluated_agent_patch_ids = await db.get_yet_evaluated_agent_patches('localization')

    evaluated_count = 0
    skipped_count = 0
    error_count = 0

    async def evaluate_single(agent_patch_id: int) -> None:
        nonlocal evaluated_count, skipped_count, error_count
        try:
            agent_patch = await db.get_agent_patch(agent_patch_id)
            dev_patch = await db.get_developer_patch_by_bug_id(agent_patch.bugId)
            if dev_patch is None:
                skipped_count += 1
                logger.debug(f'Skipping agent patch {agent_patch_id}: no developer patch (open bug)')
                return
            evaluator = LocalizationEval(agent_patch=agent_patch, dev_patch=dev_patch, db=db)
            eval_result = await evaluator.run_eval()
            eval_id = await db.insert_localization_eval(eval_result)
            if eval_result.status == 'success':
                evaluated_count += 1
                logger.info(
                    f'Agent patch {agent_patch_id} evaluated (evalId={eval_id}): '
                    f'file IoU={eval_result.fileEvaluation:.3f}, '
                    f'function IoU={eval_result.functionEvaluation:.3f}'
                )
            else:
                error_count += 1
                logger.warning(
                    f'Agent patch {agent_patch_id} evaluation failed (evalId={eval_id}): '
                    f'{eval_result.systemMessage}'
                )
        except ValueError as e:
            error_count += 1
            logger.error(f'Skipping agent patch {agent_patch_id}: {str(e)}')
        except Exception as e:
            error_count += 1
            logger.error(f'Unexpected error evaluating agent patch {agent_patch_id}: {str(e)}', exc_info=True)

    await _run_concurrent(unevaluated_agent_patch_ids, evaluate_single, max_concurrent, 'agent patches')
    logger.info(
        f'Localization evaluation completed: '
        f'{evaluated_count} evaluated, {skipped_count} skipped (open bugs), {error_count} errors'
    )
