"""LLM-judge evaluation DB operations."""

import json

from kArena.models import LLMJudgeConfiguration, PatchLLMJudgeEvaluation


def _row_to_llm_judge_eval(row) -> PatchLLMJudgeEvaluation:
    return PatchLLMJudgeEvaluation(
        evalId=row['evalId'],
        judgeId=row['judgeId'],
        bugId=row['bugId'],
        devPatchId=row['devPatchId'],
        agentPatchId=row['agentPatchId'],
        status=row['status'],
        systemMessage=row['systemMessage'],
        yesCount=row['yesCount'],
        noCount=row['noCount'],
        errorCount=row['errorCount'],
        llmMessages=json.loads(row['llmMessages']) if row['llmMessages'] else None,
    )


class LLMJudgeMixin:
    """LLM-judge config + evaluation ops on :class:`kArenaDB`."""

    async def insert_llm_judge_config(self, config: LLMJudgeConfiguration) -> int:
        """Insert a new LLMJudgeConfiguration into the database.

        Args:
            config: LLMJudgeConfiguration object to insert (judgeId will be auto-generated)

        Returns:
            The auto-generated judgeId
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO llm_judge_configurations (
                    judgeName, prompt, model, modelConfigName, nVotes, attrs
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    config.judgeName,
                    config.prompt,
                    config.model,
                    config.modelConfigName,
                    config.nVotes,
                    json.dumps(config.attrs),
                ),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_llm_judge_config(self, judge_id: int) -> LLMJudgeConfiguration:
        """Get an LLMJudgeConfiguration by judgeId.

        Args:
            judge_id: The judgeId to look up

        Returns:
            LLMJudgeConfiguration object

        Raises:
            ValueError: If judge configuration not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM llm_judge_configurations WHERE judgeId = ?",
                (judge_id,)
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"LLM judge configuration not found: {judge_id}")

            return LLMJudgeConfiguration(
                judgeId=row['judgeId'],
                judgeName=row['judgeName'],
                prompt=row['prompt'],
                model=row['model'],
                modelConfigName=row['modelConfigName'],
                nVotes=row['nVotes'],
                attrs=json.loads(row['attrs'])
            )

    async def insert_llm_judge_eval(self, eval: PatchLLMJudgeEvaluation) -> int:
        """Insert a new PatchLLMJudgeEvaluation into the database.

        Args:
            eval: PatchLLMJudgeEvaluation object to insert (evalId will be auto-generated)

        Returns:
            The auto-generated evalId
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO patch_llm_judge_evaluations (
                    judgeId, bugId, devPatchId, agentPatchId, status, systemMessage,
                    yesCount, noCount, errorCount, llmMessages
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eval.judgeId,
                    eval.bugId,
                    eval.devPatchId,
                    eval.agentPatchId,
                    eval.status,
                    eval.systemMessage,
                    eval.yesCount,
                    eval.noCount,
                    eval.errorCount,
                    json.dumps(eval.llmMessages) if eval.llmMessages else None,
                ),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_yet_evaluated_llm_judge_patches(
        self,
        judge_id: int
    ) -> list[tuple[int, int]]:
        """Get all (agentPatchId, devPatchId) pairs that need LLM judge evaluation.

        Returns agent patches that:
        1. Have status='success'
        2. Have a corresponding developer patch (fixed bugs)
        3. Have NOT been evaluated by this judge yet

        Args:
            judge_id: The judgeId to check against

        Returns:
            List of (agentPatchId, devPatchId) tuples
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT ap.agentPatchId, dp.devPatchId
                FROM agent_patches ap
                INNER JOIN developer_patches dp ON ap.bugId = dp.bugId
                WHERE ap.status = 'success'
                AND NOT EXISTS (
                    SELECT 1 FROM patch_llm_judge_evaluations e
                    WHERE e.judgeId = ?
                    AND e.agentPatchId = ap.agentPatchId
                    AND e.devPatchId = dp.devPatchId
                )
                """,
                (judge_id,)
            )
            rows = await cur.fetchall()
            return [(row['agentPatchId'], row['devPatchId']) for row in rows]

    async def get_llm_judge_eval(self, eval_id: int) -> PatchLLMJudgeEvaluation:
        """Get a PatchLLMJudgeEvaluation by evalId.

        Args:
            eval_id: The evalId to look up

        Returns:
            PatchLLMJudgeEvaluation object

        Raises:
            ValueError: If evaluation not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM patch_llm_judge_evaluations WHERE evalId = ?",
                (eval_id,)
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"LLM judge evaluation not found: {eval_id}")
            return _row_to_llm_judge_eval(row)

    async def get_llm_judge_evaluations_batch(
        self,
        patch_ids: list[int],
        judge_id: int
    ) -> dict[int, PatchLLMJudgeEvaluation]:
        """Get LLM judge evaluations for multiple patches.

        Args:
            patch_ids: List of patchIds (from agent_patches table) to fetch evaluations for
            judge_id: The judgeId to filter by

        Returns:
            Dictionary mapping patchId to PatchLLMJudgeEvaluation
        """
        if not patch_ids:
            return {}

        async with self._conn.cursor() as cur:
            placeholders = ','.join('?' * len(patch_ids))
            query = f"""
                SELECT plje.*, ap.patchId
                FROM patch_llm_judge_evaluations plje
                INNER JOIN agent_patches ap ON plje.agentPatchId = ap.agentPatchId
                WHERE ap.patchId IN ({placeholders}) AND plje.judgeId = ?
            """
            await cur.execute(query, patch_ids + [judge_id])
            rows = await cur.fetchall()

            return {row['patchId']: _row_to_llm_judge_eval(row) for row in rows}
