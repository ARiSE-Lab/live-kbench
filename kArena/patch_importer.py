"""Patch Importer: Import agent patches from JSON into kArena database.

This module provides functionality to import agent patches from an external
JSON interface, optionally creating crash resolution evaluation records.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from kArena.models import (
    kArenaConfig,
    Patch,
    AgentPatch,
    PatchCrashResolutionEvaluation,
    kCache,
    SyzbotBug,
)
from kArena.db import kArenaDB
from kArena.agent_invoker import filter_binary_files_from_patch
from kArena.patch_analyzer import PatchAnalyzer, PatchAnalysis, patch_from_analysis
from kArena.kenv_image_manager import KenvImageManager

logger = logging.getLogger(__name__)


class ImportPatchResult(BaseModel):
    id: int  # order of patches for this bugId
    patchContent: str
    dollarCost: float | None = None
    timeCost: int | None = None
    exitReason: Literal['normal', 'costLimitExceeded', 'timeLimitExceeded'] | None = 'normal'
    trajectoryPath: str | None = None
    logPath: str | None = None
    attrs: dict[str, str] = {}
    crashResolved: bool | None = None  # only used if crashResolutionEvaluated=true


class PatchImportData(BaseModel):
    agentConfigId: int
    baseCommit: Literal['parentCommit', 'crashCommit']
    crashResolutionEvaluated: bool = False
    results: dict[str, list[ImportPatchResult]]  # bugId -> list of patches


class ImportResult(BaseModel):
    total_patches: int
    successful_patches: int
    failed_patches: int
    errors: list[str]
    agent_patch_ids: list[int]


class ImportValidationError(Exception):
    """Raised when import validation fails."""
    pass


class PatchImporter:
    """Import agent patches from JSON interface into kArena database."""

    def __init__(
        self,
        config: kArenaConfig,
        db: kArenaDB,
        import_data: PatchImportData,
        semaphore: asyncio.Semaphore | None = None
    ):
        self.config = config
        self.db = db
        self.import_data = import_data
        self.semaphore = semaphore or asyncio.Semaphore(32)

        # Cached data populated during validation
        self._bug_cache: dict[str, SyzbotBug] = {}
        self._kcache_cache: dict[str, kCache] = {}

    async def _validate(self) -> None:
        """Validate import data before processing.

        Raises:
            ImportValidationError: If validation fails
        """
        errors: list[str] = []

        # Verify agentConfigId exists
        try:
            await self.db.get_agent_configuration(self.import_data.agentConfigId)
        except ValueError:
            errors.append(f'Agent configuration not found: {self.import_data.agentConfigId}')

        # Validate each bug
        for bug_id in self.import_data.results.keys():
            # Verify bug exists
            try:
                bug = await self.db.get_bug(bug_id)
                self._bug_cache[bug_id] = bug
            except ValueError:
                errors.append(f'Bug not found: {bug_id}')
                continue

            # Verify kCache exists
            try:
                kcache = await self.db.get_latest_kcache(bug_id, self.import_data.baseCommit)
                self._kcache_cache[bug_id] = kcache
            except ValueError:
                errors.append(f'kCache not found for bug {bug_id} with baseCommit {self.import_data.baseCommit}')

        if errors:
            raise ImportValidationError('\n'.join(errors))

    async def _analyze_patch(
        self,
        bug_id: str,
        patch_content: str
    ) -> PatchAnalysis:
        """Run PatchAnalyzer on a patch.

        Args:
            bug_id: The bug ID
            patch_content: The patch content to analyze

        Returns:
            PatchAnalysis result
        """
        bug = self._bug_cache[bug_id]
        analyzer = PatchAnalyzer(
            config=self.config,
            bug=bug.syzbotData,
            base_commit=self.import_data.baseCommit,
            patch=patch_content
        )
        result = await analyzer.run_agent(timeout=300)  # 5 min timeout per patch
        if result is None:
            return PatchAnalysis(
                patchContent=patch_content,
                status='error',
                systemMessage='PatchAnalyzer returned None'
            )
        return result

    async def _import_single_patch(
        self,
        bug_id: str,
        patch_data: ImportPatchResult,
        union_id: int,
        added_time: datetime
    ) -> tuple[int | None, str | None]:
        """Import a single patch.

        Returns:
            Tuple of (agent_patch_id, error_message)
            If successful, error_message is None
            If failed, agent_patch_id is None
        """
        try:
            # Filter binary files from patch
            filtered_content = filter_binary_files_from_patch(patch_data.patchContent)

            # Analyze patch
            async with self.semaphore:
                analysis = await self._analyze_patch(bug_id, filtered_content)

            patch_id = await self.db.insert_patch(patch_from_analysis(analysis))

            # Create AgentPatch record
            agent_patch = AgentPatch(
                agentPatchId=0,  # auto-generated
                patchId=patch_id,
                bugId=bug_id,
                addedTime=added_time,
                agentConfigId=self.import_data.agentConfigId,
                unionId=union_id,
                baseCommit=self.import_data.baseCommit,
                status='success',
                systemMessage='Imported patch',
                dollarCost=patch_data.dollarCost,
                timeCost=patch_data.timeCost,
                exitReason=patch_data.exitReason,
                trajectoryKey=patch_data.trajectoryPath,
                logKey=patch_data.logPath,
                attrs=patch_data.attrs
            )
            agent_patch_id = await self.db.insert_agent_patch(agent_patch)

            # Create crash resolution evaluation if requested
            if self.import_data.crashResolutionEvaluated and patch_data.crashResolved is not None:
                kcache = self._kcache_cache[bug_id]
                eval_record = PatchCrashResolutionEvaluation(
                    evalId=0,  # auto-generated
                    agentPatchId=agent_patch_id,
                    kCacheId=kcache.kCacheId,
                    kGymEvalJobId='imported',
                    status='success',
                    systemMessage='Imported evaluation result',
                    kGymEvaluation='notReproduced' if patch_data.crashResolved else 'reproduced',
                    kGymEvaluationResult=None
                )
                await self.db.insert_crash_resolution_eval(eval_record)

            return agent_patch_id, None

        except Exception as e:
            error_msg = f'Failed to import patch for bug {bug_id} (id={patch_data.id}): {e}'
            logger.error(error_msg)
            return None, error_msg

    async def _import_bug_patches(
        self,
        bug_id: str,
        patches: list[ImportPatchResult],
        union_id: int,
        start_time: datetime,
        patch_index_offset: int
    ) -> tuple[list[int], list[str]]:
        """Import all patches for a single bug.

        Ensures kenv image exists before processing patches, then cleans up.

        Args:
            bug_id: Bug ID
            patches: List of patches to import for this bug
            union_id: Union ID for this batch
            start_time: Start time for calculating addedTime
            patch_index_offset: Offset for calculating addedTime

        Returns:
            Tuple of (successful_agent_patch_ids, error_messages)
        """
        image_manager = KenvImageManager(self.config, self.import_data.baseCommit)
        agent_patch_ids: list[int] = []
        errors: list[str] = []

        try:
            # Ensure kenv image exists for this bug
            async with self.semaphore:
                await image_manager.ensure_kenv_image(bug_id)

            # Sort patches by id for consistent ordering
            sorted_patches = sorted(patches, key=lambda x: x.id)

            # Import each patch
            for idx, patch_data in enumerate(sorted_patches):
                added_time = start_time + timedelta(seconds=patch_index_offset + idx)
                agent_patch_id, error = await self._import_single_patch(
                    bug_id, patch_data, union_id, added_time
                )
                if agent_patch_id is not None:
                    agent_patch_ids.append(agent_patch_id)
                else:
                    if error:
                        errors.append(error)

        except Exception as e:
            error_msg = f'Failed to setup/process bug {bug_id}: {e}'
            logger.error(error_msg)
            errors.append(error_msg)
        finally:
            # Cleanup images
            await image_manager.cleanup_images(bug_id)

        return agent_patch_ids, errors

    async def import_patches(self) -> ImportResult:
        """Import all patches from the import data.

        Returns:
            ImportResult with counts and any errors
        """
        # Validate first
        await self._validate()

        # Get new unionId
        union_id = await self.db.increment_and_get_union_counter(self.import_data.agentConfigId)

        # Set start time
        start_time = datetime.now()

        # Count total patches and pre-calculate offsets per bug
        total = sum(len(patches) for patches in self.import_data.results.values())

        # Build list of (bug_id, patches, offset) for parallel processing
        bug_tasks: list[tuple[str, list[ImportPatchResult], int]] = []
        patch_index_offset = 0
        for bug_id in sorted(self.import_data.results.keys()):
            patches = self.import_data.results[bug_id]
            bug_tasks.append((bug_id, patches, patch_index_offset))
            patch_index_offset += len(patches)

        # Process all bugs in parallel using TaskGroup
        all_agent_patch_ids: list[int] = []
        all_errors: list[str] = []
        tasks: list[asyncio.Task[tuple[list[int], list[str]]]] = []

        async with asyncio.TaskGroup() as tg:
            for bug_id, patches, offset in bug_tasks:
                logger.info(f'[{bug_id}] Scheduling import of {len(patches)} patches')
                task = tg.create_task(
                    self._import_bug_patches(bug_id, patches, union_id, start_time, offset)
                )
                tasks.append(task)

        # Collect results from all tasks
        for task in tasks:
            agent_patch_ids, errors = task.result()
            all_agent_patch_ids.extend(agent_patch_ids)
            all_errors.extend(errors)

        successful = len(all_agent_patch_ids)
        failed = total - successful

        logger.info(f'Import complete: {successful}/{total} patches imported successfully')
        if all_errors:
            for error in all_errors:
                logger.warning(f'  Error: {error}')

        return ImportResult(
            total_patches=total,
            successful_patches=successful,
            failed_patches=failed,
            errors=all_errors,
            agent_patch_ids=all_agent_patch_ids
        )
