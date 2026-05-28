"""LLM Judge Evaluation Module

This module provides LLM-based patch equivalence evaluation for comparing
agent-generated patches to ground truth developer patches.

The LLMJudgeEval class evaluates patches by:
1. Fetching judge configuration, agent patch, and developer patch from the database
2. Loading the LiteLLM router configuration from the specified config file
3. Running multiple voting rounds (nVotes) with the LLM
4. Collecting structured text responses with verdict (equivalent/discrepant)
5. Aggregating results and returning evaluation with vote counts
"""

import logging
import re
import litellm
from pathlib import Path
from typing import Literal
from unidiff import PatchSet
from kArena.models import (
    AgentPatch,
    DeveloperPatch,
    LLMJudgeConfiguration,
    PatchLLMJudgeEvaluation,
)
from kArena.db import kArenaDB
from kArena.evaluation.router_manager import RouterManager
from kArena.evaluation.source_filters import SOURCE_EXTENSIONS

logger = logging.getLogger(__name__)


def filter_patch_files(patch_content: str) -> str:
    """Filter patch to keep only C/C++ source and assembly files, excluding binary files.

    Uses unidiff to parse the patch and recompose it with only source files.
    This removes:
    - Binary file changes
    - Documentation, build files, and other non-code files

    Args:
        patch_content: The raw patch content as a string

    Returns:
        Filtered patch containing only source file changes.
        Returns original patch if parsing fails or patch is empty.
    """
    if not patch_content or not patch_content.strip():
        return patch_content

    try:
        patchset = PatchSet(patch_content)

        # Filter to keep only non-binary source files
        filtered_files = []
        for patch_file in patchset:
            # Skip binary files
            if patch_file.is_binary_file:
                continue

            # Get the file path (prefer target path, fall back to source)
            file_path = patch_file.path
            if file_path and any(file_path.endswith(ext) for ext in SOURCE_EXTENSIONS):
                filtered_files.append(patch_file)

        # If no files were filtered out, return original
        if len(filtered_files) == len(patchset):
            return patch_content

        # If all files were filtered out, return empty string
        if not filtered_files:
            return ''

        # Recompose the patch from filtered files
        filtered_patch = ''.join(str(f) for f in filtered_files)

        num_filtered = len(patchset) - len(filtered_files)
        logger.debug(f'Filtered {num_filtered} non-source/binary files from patch')

        return filtered_patch

    except Exception as e:
        logger.warning(f'Failed to parse patch for filtering: {e}')
        return patch_content


class LLMJudgeEval:
    """Evaluates agent patches using LLM-based judgment.

    This class handles the full LLM judge evaluation workflow:
    - Loads judge configuration and model router
    - Fetches necessary data (agent patch, developer patch, patch contents)
    - Formats prompt with template substitution and format instructions
    - Runs multiple voting rounds with structured text output
    - Aggregates votes and returns evaluation results

    Attributes:
        judge_config: The LLMJudgeConfiguration for this evaluation
        agent_patch: The AgentPatch object to evaluate
        dev_patch: The DeveloperPatch object (ground truth)
        db: Database connection for fetching data
        workspace_root: Path to workspace root for finding config files
    """

    # Format instructions appended to the prompt
    FORMAT_INSTRUCTIONS = """

After your analysis, provide your response in the following format:

<reasoning>
[Provide extensive reasoning here. Analyze both patches in detail, compare their approaches, consider edge cases, and explain your thought process thoroughly before making a decision.]
</reasoning>

<evaluation>
<developerPatchAnalysis>
[Your detailed analysis of what the approved/developer patch does]
</developerPatchAnalysis>
<studentPatchAnalysis>
[Your detailed analysis of what the student/agent patch does]
</studentPatchAnalysis>
<verdict>
[Either "equivalent" or "discrepant"]
</verdict>
</evaluation>

Important:
- The verdict must be exactly "equivalent" or "discrepant" (lowercase, without quotes in the actual output)
- Use the <reasoning> section to think through your analysis thoroughly
- Provide detailed technical analysis in the XML fields
- All content must be properly formatted within the XML tags
"""

    def __init__(
        self,
        judge_config: LLMJudgeConfiguration,
        agent_patch: AgentPatch,
        dev_patch: DeveloperPatch,
        db: kArenaDB,
        workspace_root: Path,
        *,
        router: litellm.Router | None = None,
    ):
        """Initialize the LLM judge evaluator.

        Args:
            judge_config: LLMJudgeConfiguration with prompt template and model settings
            agent_patch: AgentPatch object to evaluate
            dev_patch: DeveloperPatch object (ground truth)
            db: kArenaDB instance for database operations
            workspace_root: Path to workspace root directory
            router: Optional pre-built LiteLLM router. When provided, skips the
                RouterManager singleton lookup — useful for tests.
        """
        self.judge_config = judge_config
        self.agent_patch = agent_patch
        self.dev_patch = dev_patch
        self.db = db
        self.workspace_root = workspace_root
        self._router_override = router

    def _error_result(self, system_message: str) -> PatchLLMJudgeEvaluation:
        return PatchLLMJudgeEvaluation(
            evalId=0,
            judgeId=self.judge_config.judgeId,
            bugId=self.agent_patch.bugId,
            devPatchId=self.dev_patch.devPatchId,
            agentPatchId=self.agent_patch.agentPatchId,
            status='error',
            systemMessage=system_message,
            yesCount=None,
            noCount=None,
            errorCount=None,
            llmMessages=None,
        )

    def _format_prompt(
        self,
        dev_patch_content: str,
        dev_patch_message: str,
        agent_patch_content: str
    ) -> str:
        """Format the prompt template with actual patch data and append format instructions.

        Patches are filtered to include only source files (C/C++, assembly) and
        exclude binary files before being included in the prompt.

        Args:
            dev_patch_content: Content of the developer's patch
            dev_patch_message: Developer's commit message
            agent_patch_content: Content of the agent's patch

        Returns:
            Formatted prompt string with format instructions appended
        """
        # Filter patches to only include source files, exclude binary files
        filtered_dev_patch = filter_patch_files(dev_patch_content)
        filtered_agent_patch = filter_patch_files(agent_patch_content)

        base_prompt = self.judge_config.prompt.format(
            devPatch=filtered_dev_patch,
            devPatchMessage=dev_patch_message,
            agentPatch=filtered_agent_patch
        )
        return base_prompt + self.FORMAT_INSTRUCTIONS

    def _parse_verdict(self, response_text: str) -> tuple[str, dict[str, str]]:
        """Parse the XML response to extract verdict and analysis.

        Args:
            response_text: The LLM's text response

        Returns:
            Tuple of (verdict, parsed_data)
            - verdict: 'equivalent', 'discrepant', or 'parse_error'
            - parsed_data: Dict with 'reasoning', 'developerPatchAnalysis',
                          'studentPatchAnalysis', 'verdict', and 'error' (if parse failed)
        """
        parsed = {}

        # Extract reasoning section
        reasoning_match = re.search(r'<reasoning>(.*?)</reasoning>', response_text, re.DOTALL)
        if reasoning_match:
            parsed['reasoning'] = reasoning_match.group(1).strip()

        # Extract evaluation section
        eval_match = re.search(r'<evaluation>(.*?)</evaluation>', response_text, re.DOTALL)
        if not eval_match:
            return ('parse_error', {
                'error': 'No <evaluation> section found in response',
                'raw_response': response_text
            })

        eval_content = eval_match.group(1)

        # Extract developerPatchAnalysis
        dev_analysis_match = re.search(
            r'<developerPatchAnalysis>(.*?)</developerPatchAnalysis>',
            eval_content,
            re.DOTALL
        )
        if dev_analysis_match:
            parsed['developerPatchAnalysis'] = dev_analysis_match.group(1).strip()

        # Extract studentPatchAnalysis
        student_analysis_match = re.search(
            r'<studentPatchAnalysis>(.*?)</studentPatchAnalysis>',
            eval_content,
            re.DOTALL
        )
        if student_analysis_match:
            parsed['studentPatchAnalysis'] = student_analysis_match.group(1).strip()

        # Extract verdict
        verdict_match = re.search(r'<verdict>(.*?)</verdict>', eval_content, re.DOTALL)
        if not verdict_match:
            return ('parse_error', {
                **parsed,
                'error': 'No <verdict> tag found in evaluation section',
                'raw_response': response_text
            })

        verdict_text = verdict_match.group(1).strip().lower()

        if verdict_text == 'equivalent':
            parsed['verdict'] = 'equivalent'
            return ('equivalent', parsed)
        elif verdict_text == 'discrepant':
            parsed['verdict'] = 'discrepant'
            return ('discrepant', parsed)
        else:
            return ('parse_error', {
                **parsed,
                'error': f'Invalid verdict value: {verdict_text}',
                'raw_response': response_text
            })

    async def _run_single_vote(
        self,
        router: litellm.Router,
        prompt: str,
        vote_id: int
    ) -> tuple[Literal['yes', 'no', 'error'], list[dict[str, str]]]:
        """Run a single voting round with the LLM.

        Args:
            router: LiteLLM router instance
            prompt: Formatted prompt to send to LLM
            vote_id: Vote number (for logging)

        Returns:
            Tuple of (vote_result, message_history)
            - vote_result: 'yes' if equivalent, 'no' if discrepant, 'error' if failed
            - message_history: List of message dicts in OpenAI format
        """
        logger.info(f"Starting vote {vote_id} for LLM judge evaluation")

        messages = [
            {"role": "system", "content": "You are a kernel expert."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await router.acompletion(
                model=self.judge_config.model,
                messages=messages
            )

            # Extract the assistant's response
            assistant_message = response.choices[0].message
            response_text = assistant_message.content or ""

            # Add assistant message to history
            messages.append({
                "role": "assistant",
                "content": response_text
            })

            if not response_text:
                logger.warning(f"Vote {vote_id}: Empty response from LLM")
                messages.append({
                    "error": "Empty response from LLM"
                })
                return ('error', messages)

            # Parse the structured response
            verdict, parsed_data = self._parse_verdict(response_text)

            if verdict == 'parse_error':
                logger.warning(f"Vote {vote_id}: Failed to parse response - {parsed_data.get('error')}")
                messages.append({
                    "error": parsed_data.get('error', 'Unknown parse error'),
                    "parsed_data": parsed_data
                })
                return ('error', messages)

            # Add parsed data to message history for reference
            messages.append({
                "parsed_data": parsed_data
            })

            if verdict == 'equivalent':
                logger.info(f"Vote {vote_id}: Verdict is 'equivalent'")
                return ('yes', messages)
            elif verdict == 'discrepant':
                logger.info(f"Vote {vote_id}: Verdict is 'discrepant'")
                return ('no', messages)
            else:
                logger.error(f"Vote {vote_id}: Unexpected verdict value: {verdict}")
                messages.append({
                    "error": f"Unexpected verdict: {verdict}"
                })
                return ('error', messages)

        except Exception as e:
            # LLM API error (timeout, rate limit, etc.)
            logger.error(f"Vote {vote_id}: LLM API error - {str(e)}")
            messages.append({
                "error": f"LLM API error: {str(e)}"
            })
            return ('error', messages)

    async def run_eval_with_content(
        self,
        dev_patch_content: str,
        dev_patch_message: str,
        agent_patch_content: str,
        bug_id: str = '',
        dev_patch_id: int = 0,
        agent_patch_id: int = 0,
    ) -> PatchLLMJudgeEvaluation:
        """Run LLM judge evaluation with provided patch content.

        This method bypasses database lookups and works directly with patch content.
        Useful for testing and standalone evaluation scenarios.

        Args:
            dev_patch_content: Developer patch content
            dev_patch_message: Developer patch commit message
            agent_patch_content: Agent patch content
            bug_id: bugId for the returned record (default: '')
            dev_patch_id: devPatchId for the returned record (default: 0)
            agent_patch_id: agentPatchId for the returned record (default: 0)

        Returns:
            PatchLLMJudgeEvaluation with caller-supplied or placeholder IDs
        """
        try:
            if self._router_override is not None:
                router = self._router_override
            else:
                router = await RouterManager.get_router(
                    self.judge_config.modelConfigName,
                    self.workspace_root
                )
        except Exception as e:
            return self._error_result(f'Failed to get router: {str(e)}')

        # Format prompt
        prompt = self._format_prompt(
            dev_patch_content=dev_patch_content,
            dev_patch_message=dev_patch_message,
            agent_patch_content=agent_patch_content
        )

        # Run voting rounds
        all_messages = []
        yes_count = 0
        no_count = 0
        error_count = 0

        for vote_id in range(1, self.judge_config.nVotes + 1):
            vote_result, messages = await self._run_single_vote(
                router, prompt, vote_id
            )
            all_messages.append(messages)

            if vote_result == 'yes':
                yes_count += 1
            elif vote_result == 'no':
                no_count += 1
            else:  # error
                error_count += 1

        # Determine overall status
        if error_count == self.judge_config.nVotes:
            status = 'error'
            system_message = f'All {self.judge_config.nVotes} votes failed'
        else:
            status = 'success'
            system_message = (
                f'Completed {self.judge_config.nVotes} votes: '
                f'{yes_count} yes, {no_count} no, {error_count} errors'
            )

        return PatchLLMJudgeEvaluation(
            evalId=0,
            judgeId=self.judge_config.judgeId,
            bugId=bug_id,
            devPatchId=dev_patch_id,
            agentPatchId=agent_patch_id,
            status=status,
            systemMessage=system_message,
            yesCount=yes_count,
            noCount=no_count,
            errorCount=error_count,
            llmMessages=all_messages,
        )

    async def run_eval(self) -> PatchLLMJudgeEvaluation:
        """Run LLM judge evaluation for the agent patch.

        This method:
        1. Fetches patch data from the database
        2. Delegates to run_eval_with_content for actual evaluation
        3. Returns PatchLLMJudgeEvaluation with all metadata

        Returns:
            PatchLLMJudgeEvaluation with full metadata from database entities

        Raises:
            ValueError: If patch not found in database
        """
        try:
            agent_patch_data = await self.db.get_patch(self.agent_patch.patchId)
            dev_patch_data = await self.db.get_patch(self.dev_patch.patchId)
            return await self.run_eval_with_content(
                dev_patch_content=dev_patch_data.patchContent,
                dev_patch_message=self.dev_patch.patchMessage,
                agent_patch_content=agent_patch_data.patchContent,
                bug_id=self.agent_patch.bugId,
                dev_patch_id=self.dev_patch.devPatchId,
                agent_patch_id=self.agent_patch.agentPatchId,
            )
        except ValueError as e:
            return self._error_result(f'Database error: {str(e)}')
        except Exception as e:
            return self._error_result(f'Evaluation error: {str(e)}')
