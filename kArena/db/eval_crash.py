"""Crash resolution evaluation DB operations."""

from KBDr.kclient import EvaluationResult

from kArena.models import PatchCrashResolutionEvaluation


def _row_to_crash_eval(row) -> PatchCrashResolutionEvaluation:
    return PatchCrashResolutionEvaluation(
        evalId=row['evalId'],
        agentPatchId=row['agentPatchId'],
        kCacheId=row['kCacheId'],
        kGymEvalJobId=row['kGymEvalJobId'],
        status=row['status'],
        systemMessage=row['systemMessage'],
        kGymEvaluation=row['kGymEvaluation'],
        kGymEvaluationResult=EvaluationResult.model_validate_json(row['kGymEvaluationResult']) if row['kGymEvaluationResult'] else None,
    )


class CrashEvalMixin:
    """Crash-resolution evaluation ops on :class:`kArenaDB`."""

    async def insert_crash_resolution_eval(self, eval: PatchCrashResolutionEvaluation) -> int:
        """Insert a new PatchCrashResolutionEvaluation into the database.

        Args:
            eval: PatchCrashResolutionEvaluation object to insert (evalId will be auto-generated)

        Returns:
            The auto-generated evalId
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO patch_crash_resolution_evaluations (
                    agentPatchId, kCacheId, kGymEvalJobId, status, systemMessage,
                    kGymEvaluation, kGymEvaluationResult
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eval.agentPatchId,
                    eval.kCacheId,
                    eval.kGymEvalJobId,
                    eval.status,
                    eval.systemMessage,
                    eval.kGymEvaluation,
                    eval.kGymEvaluationResult.model_dump_json() if eval.kGymEvaluationResult else None,
                ),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_submitted_crash_resolution_evals(self) -> list[int]:
        """Get all evaluation IDs that have been submitted but not yet polled.

        Returns:
            List of evalIds where status='success' and kGymEvaluation IS NULL
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """SELECT evalId FROM patch_crash_resolution_evaluations
                   WHERE status = 'success' AND kGymEvaluation IS NULL"""
            )
            rows = await cur.fetchall()
            return [row['evalId'] for row in rows]

    async def get_crash_resolution_eval(self, eval_id: int) -> PatchCrashResolutionEvaluation:
        """Get a PatchCrashResolutionEvaluation by evalId.

        Args:
            eval_id: The evalId to look up

        Returns:
            PatchCrashResolutionEvaluation object

        Raises:
            ValueError: If evaluation not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM patch_crash_resolution_evaluations WHERE evalId = ?",
                (eval_id,)
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f'Crash resolution evaluation not found: {eval_id}')
            return _row_to_crash_eval(row)

    async def update_crash_resolution_eval(self, eval: PatchCrashResolutionEvaluation) -> None:
        """Update an existing PatchCrashResolutionEvaluation record.

        Args:
            eval: PatchCrashResolutionEvaluation with updated values
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE patch_crash_resolution_evaluations
                SET status = ?, systemMessage = ?, kGymEvaluation = ?, kGymEvaluationResult = ?
                WHERE evalId = ?
                """,
                (
                    eval.status,
                    eval.systemMessage,
                    eval.kGymEvaluation,
                    eval.kGymEvaluationResult.model_dump_json() if eval.kGymEvaluationResult else None,
                    eval.evalId
                )
            )
            await self._conn.commit()

    async def get_crash_evaluations_batch(
        self,
        patch_ids: list[int]
    ) -> dict[int, PatchCrashResolutionEvaluation]:
        """Get crash resolution evaluations for multiple patches.

        Args:
            patch_ids: List of patchIds (from agent_patches table) to fetch evaluations for

        Returns:
            Dictionary mapping patchId to PatchCrashResolutionEvaluation
        """
        if not patch_ids:
            return {}

        async with self._conn.cursor() as cur:
            placeholders = ','.join('?' * len(patch_ids))
            query = f"""
                SELECT pcre.*, ap.patchId
                FROM patch_crash_resolution_evaluations pcre
                INNER JOIN agent_patches ap ON pcre.agentPatchId = ap.agentPatchId
                WHERE ap.patchId IN ({placeholders})
            """
            await cur.execute(query, patch_ids)
            rows = await cur.fetchall()

            return {row['patchId']: _row_to_crash_eval(row) for row in rows}
