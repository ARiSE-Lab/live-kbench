"""Patch Localization Evaluation Module

This module provides patch localization evaluation for agent-generated patches
by comparing modified files and functions with ground truth developer patches.

The LocalizationEval class evaluates patches by:
1. Fetching agent patch and developer patch data from the database
2. Extracting modified files and functions from both patches
3. Computing intersection over union (IoU) metrics at file and function levels
4. Returning evaluation results with both file-level and function-level metrics
"""

from typing import Literal

from kArena.models import AgentPatch, DeveloperPatch, PatchLocalizationEvaluation
from kArena.db import kArenaDB
from kArena.evaluation.source_filters import SOURCE_EXTENSIONS


def filter_source_files(files: set[str]) -> set[str]:
    """Filter files to keep only C/C++ source and assembly files."""
    return {f for f in files if any(f.endswith(ext) for ext in SOURCE_EXTENSIONS)}


class LocalizationEval:
    """Evaluates agent patches using localization metrics (IoU).

    This class computes the similarity between agent-generated patches and
    ground truth developer patches by analyzing modified files and functions.
    It calculates Intersection over Union (IoU) at both file and function levels.

    Attributes:
        agent_patch: The AgentPatch object to evaluate
        dev_patch: The DeveloperPatch object (ground truth)
        db: Database connection for fetching patch data
    """

    def __init__(self, agent_patch: AgentPatch, dev_patch: DeveloperPatch, db: kArenaDB):
        """Initialize the localization evaluator.

        Args:
            agent_patch: AgentPatch object containing agent patch metadata
            dev_patch: DeveloperPatch object containing ground truth patch metadata
            db: kArenaDB instance for database operations
        """
        self.agent_patch = agent_patch
        self.dev_patch = dev_patch
        self.db = db

    def _empty_result(
        self,
        status: Literal['error', 'invalid'],
        system_message: str,
    ) -> PatchLocalizationEvaluation:
        return PatchLocalizationEvaluation(
            evalId=0,
            bugId=self.agent_patch.bugId,
            devPatchId=self.dev_patch.devPatchId,
            agentPatchId=self.agent_patch.agentPatchId,
            status=status,
            systemMessage=system_message,
            fileIntersectionSize=0,
            fileUnionSize=0,
            fileEvaluation=0.0,
            functionIntersectionSize=0,
            functionUnionSize=0,
            functionEvaluation=0.0,
        )

    async def run_eval(self) -> PatchLocalizationEvaluation:
        """Run localization evaluation for the agent patch.

        This method:
        1. Fetches agent and developer patch data from the database
        2. Validates that both patches were successfully analyzed
        3. Computes IoU metrics for both files and functions
        4. Returns structured evaluation results

        Returns:
            PatchLocalizationEvaluation with:
                - evalId: 0 (placeholder, to be set by caller if inserting to DB)
                - bugId: From the agent_patch
                - devPatchId: From the dev_patch
                - agentPatchId: From the agent_patch
                - status: 'success', 'error', or 'invalid'
                - systemMessage: Human-readable message for logging
                - File-level metrics: intersection size, union size, IoU
                - Function-level metrics: intersection size, union size, IoU

        Raises:
            ValueError: If patch not found in database
            Exception: If evaluation fails
        """
        try:
            # Step 1: Fetch patch data from database
            agent_patch_data = await self.db.get_patch(self.agent_patch.patchId)
            dev_patch_data = await self.db.get_patch(self.dev_patch.patchId)

            # Step 2: Validate patch analysis status
            if agent_patch_data.status != 'success':
                return self._empty_result('invalid', f'Agent patch analysis failed: {agent_patch_data.systemMessage}')

            if dev_patch_data.status != 'success':
                return self._empty_result('invalid', f'Developer patch analysis failed: {dev_patch_data.systemMessage}')

            # Step 3: Compute file-level IoU
            agent_files = filter_source_files(set(agent_patch_data.modifiedFiles or []))
            dev_files = filter_source_files(set(dev_patch_data.modifiedFiles or []))

            file_intersection = agent_files & dev_files
            file_union = agent_files | dev_files

            file_intersection_size = len(file_intersection)
            file_union_size = len(file_union)
            file_iou = file_intersection_size / file_union_size if file_union_size > 0 else 0.0

            # Step 4: Compute function-level IoU
            agent_functions = set(agent_patch_data.modifiedFunctions or [])
            dev_functions = set(dev_patch_data.modifiedFunctions or [])

            function_intersection = agent_functions & dev_functions
            function_union = agent_functions | dev_functions

            function_intersection_size = len(function_intersection)
            function_union_size = len(function_union)
            function_iou = function_intersection_size / function_union_size if function_union_size > 0 else 0.0

            # Step 5: Return evaluation results
            return PatchLocalizationEvaluation(
                evalId=0,
                bugId=self.agent_patch.bugId,
                devPatchId=self.dev_patch.devPatchId,
                agentPatchId=self.agent_patch.agentPatchId,
                status='success',
                systemMessage='Localization evaluation completed successfully',
                fileIntersectionSize=file_intersection_size,
                fileUnionSize=file_union_size,
                fileEvaluation=file_iou,
                functionIntersectionSize=function_intersection_size,
                functionUnionSize=function_union_size,
                functionEvaluation=function_iou
            )

        except ValueError as e:
            return self._empty_result('error', f'Database error: {str(e)}')
        except Exception as e:
            return self._empty_result('error', f'Evaluation error: {str(e)}')
