"""AgentPatchProcess: Orchestrates agent patch generation and analysis.

This module handles the full pipeline for generating patches from agents:
- Runs agents on bugs using AgentInvoker
- Analyzes patches using PatchAnalyzer
- Stores results in database and filesystem
- Controls concurrency with semaphores
"""

import asyncio
import contextlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Literal

from kArena.models import AgentConfiguration, SyzbotBug, AgentPatch, Patch, kArenaConfig
from kArena.agent_invoker import AgentInvoker, AgentResult, LiteLLMProxyManager
from kArena.patch_analyzer import PatchAnalyzer, PatchAnalysis, patch_from_analysis
from kArena.db import kArenaDB
from kArena.kenv_image_manager import KenvImageManager

logger = logging.getLogger(__name__)


class AgentPatchProcess:
    """Orchestrates the full agent patch generation pipeline.

    For each bug, this class:
    1. Retrieves kCache with evaluation results
    2. Runs AgentInvoker to generate a patch
    3. If successful, runs PatchAnalyzer to analyze the patch
    4. Stores Patch and AgentPatch in database
    5. Saves trajectory and log files to filesystem

    Concurrency is controlled via semaphore since both AgentInvoker and
    PatchAnalyzer use Docker containers.
    """

    def __init__(
        self,
        config: kArenaConfig,
        db: kArenaDB,
        agent_config: AgentConfiguration,
        bug_ids: list[str | tuple[str, int]],
        bug_type: Literal['open', 'fixed'],
        n_instance: int = 5,
        semaphore: asyncio.Semaphore | None = None
    ):
        """Initialize AgentPatchProcess.

        Args:
            config: kArena configuration with workspace root and endpoints
            db: Database connection
            agent_config: Agent configuration to use
            bug_ids: List of bug IDs to process. Each entry is either a plain bug ID
                string (runs n_instance times) or a (bugId, remaining_runs) tuple
                (runs exactly remaining_runs times).
            bug_type: Type of bugs being processed ('open' or 'fixed')
            n_instance: Default number of runs per bug when bug_ids contains plain strings
            semaphore: Semaphore to control concurrency (default: 16)
        """
        self.config = config
        self.db = db
        self.agent_config = agent_config
        self.bug_type = bug_type
        self.n_instance = n_instance
        self.semaphore = semaphore if semaphore is not None else asyncio.Semaphore(16)
        self.workspace_root = Path(config.workspaceRoot)
        self._bug_runs: dict[str, int] = {
            (b if isinstance(b, str) else b[0]): (n_instance if isinstance(b, str) else b[1])
            for b in bug_ids
        }
        self.bug_ids: list[str] = list(self._bug_runs.keys())

    async def process_bugs(self) -> list[AgentPatch]:
        """Process all bugs and generate patches.

        Creates tasks for each bug and runs them concurrently using TaskGroup.
        For each bug, n_instance runs are executed sequentially.
        Increments unionCounter to get a new group ID for this batch.
        All patches in this batch are labeled with the same unionId.

        Returns:
            List of AgentPatch objects (n_instance per bug, all with same unionId)
        """
        # Step 1: Increment counter and get new group ID for this batch
        union_id = await self.db.increment_and_get_union_counter(
            self.agent_config.agentConfigId
        )
        logger.info(f"Starting batch with unionId={union_id}, n_instance={self.n_instance}")

        agent_patches = []

        proxy_ctx = (
            LiteLLMProxyManager(self.config)
            if self.config.litellmProxyConfigPath is not None
            else contextlib.nullcontext()
        )

        # Step 2: Process each bug with n_instance runs sequentially per bug
        async with proxy_ctx:
            async with asyncio.TaskGroup() as tg:
                tasks = []
                for bug_id in self.bug_ids:
                    task = tg.create_task(self.process_bug_instances(bug_id, union_id, self._bug_runs[bug_id]))
                    tasks.append(task)
                    logger.debug(f"Created task for {bug_id} with {self._bug_runs[bug_id]} sequential instances")

        # Collect results from completed tasks
        for task in tasks:
            try:
                patches = task.result()
                agent_patches.extend(patches)
            except Exception as e:
                logger.error(f"Error processing bug: {e}", exc_info=True)

        return agent_patches

    async def process_bug_instances(
        self,
        bug_id: str,
        union_id: int,
        n_runs: int,
    ) -> list[AgentPatch]:
        """Process all instances of a single bug sequentially.

        Args:
            bug_id: Bug ID to process
            union_id: Union ID for this batch
            n_runs: Number of times to run the agent for this bug

        Returns:
            List of AgentPatch objects (one per instance)
        """
        # Determine base_commit from bug_type
        base_commit: Literal['parentCommit', 'crashCommit'] = (
            'parentCommit' if self.bug_type == 'fixed' else 'crashCommit'
        )

        # Create image manager for this bug
        image_manager = KenvImageManager(self.config, base_commit)

        patches = []
        async with self.semaphore:
            # Step 1-3: Ensure agent image exists (pulls base, builds kenv, builds agent)
            await image_manager.ensure_agent_image(bug_id, self.agent_config.agent)
            # Step 4: Process other instances
            for instance_idx in range(n_runs):
                logger.info(f"[{bug_id}] Processing instance {instance_idx + 1}/{n_runs}")
                try:
                    patch = await self.process_single_bug(bug_id, union_id)
                    patches.append(patch)
                except Exception as e:
                    logger.error(f"[{bug_id}] Error processing instance {instance_idx}: {e}", exc_info=True)

        # Step 5: Cleanup images outside of semaphore
        await image_manager.cleanup_images(bug_id, [self.agent_config.agent])

        return patches

    async def process_single_bug(
        self,
        bug_id: str,
        union_id: int
    ) -> AgentPatch:
        """Process a single bug to generate and analyze a patch.

        Fetches the bug from database and determines base_commit from bug status:
        - 'fixed' bugs use 'parentCommit' (parent of fix commit)
        - 'open' bugs use 'crashCommit' (commit where crash occurred)

        Args:
            bug_id: Bug ID to process
            union_id: Union ID for this attempt (for multiple runs)

        Returns:
            AgentPatch object with results
        """
        logger.info(f"Processing bug {bug_id} (unionId={union_id})")

        # Step 1: Get bug from database and determine base_commit
        bug = await self.db.get_bug(bug_id)
        base_commit: Literal['parentCommit', 'crashCommit'] = (
            'parentCommit' if bug.status == 'fixed' else 'crashCommit'
        )
        logger.debug(f"[{bug_id}] Status: {bug.status}, base_commit: {base_commit}")

        # Step 2: Get kCache for the bug
        kcache = await self.db.get_latest_kcache(bug_id, base_commit)

        # Step 3: Run AgentInvoker
        logger.info(f"[{bug_id}] Running AgentInvoker...")
        invoker = AgentInvoker(
            config=self.config,
            bug=bug.syzbotData,  # Pass SyzbotData, not SyzbotBug
            agent_config=self.agent_config,
            base_commit=base_commit,
            stateful_edit=self.agent_config.statefulEdit,
            kcache=kcache
        )
        agent_result: AgentResult = await invoker.run_agent(timeout=6 * 60 * 60 if self.agent_config.statefulEdit else 2 * 60 * 60)

        # Step 4: Handle result and create Patch
        if agent_result.status == 'error':
            logger.warning(f"[{bug_id}] Agent failed: {agent_result.systemMessage}")
            patch = Patch(
                patchId=0,
                patchContent=agent_result.patch or "",
                status='error',
                systemMessage=agent_result.systemMessage,
                modifiedFiles=[],
                modifiedFunctions=[],
                numModifiedLines=0,
            )
        else:
            logger.info(f"[{bug_id}] Running PatchAnalyzer...")
            analyzer = PatchAnalyzer(
                config=self.config,
                bug=bug.syzbotData,
                base_commit=base_commit,
                patch=agent_result.patch
            )
            patch_analysis: PatchAnalysis = await analyzer.run_agent()
            logger.info(f"[{bug_id}] Patch analysis complete: {patch_analysis.status}")
            patch = patch_from_analysis(patch_analysis)

        # Step 5: Insert Patch to database
        patch_id = await self.db.insert_patch(patch)
        logger.debug(f"[{bug_id}] Inserted patch (patchId={patch_id})")

        # Step 6: Insert AgentPatch with NULL keys to get ID
        agent_patch = AgentPatch(
            agentPatchId=0,  # auto-generated
            patchId=patch_id,
            bugId=bug_id,
            addedTime=datetime.now(),
            agentConfigId=self.agent_config.agentConfigId,
            unionId=union_id,
            baseCommit=base_commit,
            status=agent_result.status,
            systemMessage=agent_result.systemMessage,
            dollarCost=agent_result.dollarCost,
            timeCost=agent_result.timeCost,
            exitReason=agent_result.exitReason,
            trajectoryKey=None,
            logKey=None,
            attrs={}
        )
        agent_patch_id = await self.db.insert_agent_patch(agent_patch)
        logger.debug(f"[{bug_id}] Inserted agent patch (agentPatchId={agent_patch_id})")

        # Step 7: Save files using the ID
        patch_dir = self.workspace_root / "agent-patches" / str(agent_patch_id)
        patch_dir.mkdir(parents=True, exist_ok=True)

        if agent_result.trajectory:
            (patch_dir / "traj.json").write_bytes(agent_result.trajectory)
            logger.debug(f"[{bug_id}] Saved trajectory")

        if agent_result.log:
            (patch_dir / "log.txt").write_bytes(agent_result.log)
            logger.debug(f"[{bug_id}] Saved log")

        # Step 8: Update database with file paths
        trajectory_key = f"agent-patches/{agent_patch_id}/traj.json"
        log_key = f"agent-patches/{agent_patch_id}/log.txt"
        await self.db.update_agent_patch_keys(agent_patch_id, trajectory_key, log_key)

        # Update local object
        agent_patch.agentPatchId = agent_patch_id
        agent_patch.trajectoryKey = trajectory_key
        agent_patch.logKey = log_key

        logger.info(f"[{bug_id}] Completed processing (agentPatchId={agent_patch_id})")
        return agent_patch
