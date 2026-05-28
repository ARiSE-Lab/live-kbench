"""Localization evaluation DB operations."""

from kArena.models import PatchLocalizationEvaluation


def _row_to_localization_eval(row) -> PatchLocalizationEvaluation:
    return PatchLocalizationEvaluation(
        evalId=row['evalId'],
        bugId=row['bugId'],
        devPatchId=row['devPatchId'],
        agentPatchId=row['agentPatchId'],
        status=row['status'],
        systemMessage=row['systemMessage'],
        fileIntersectionSize=row['fileIntersectionSize'],
        fileUnionSize=row['fileUnionSize'],
        fileEvaluation=row['fileEvaluation'],
        functionIntersectionSize=row['functionIntersectionSize'],
        functionUnionSize=row['functionUnionSize'],
        functionEvaluation=row['functionEvaluation'],
    )


class LocalizationEvalMixin:
    """File/function IoU evaluation ops on :class:`kArenaDB`."""

    async def insert_localization_eval(self, eval: PatchLocalizationEvaluation) -> int:
        """Insert a new PatchLocalizationEvaluation into the database.

        Args:
            eval: PatchLocalizationEvaluation object to insert (evalId will be auto-generated)

        Returns:
            The auto-generated evalId
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO patch_localization_evaluations (
                    bugId, devPatchId, agentPatchId, status, systemMessage,
                    fileIntersectionSize, fileUnionSize, fileEvaluation,
                    functionIntersectionSize, functionUnionSize, functionEvaluation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eval.bugId,
                    eval.devPatchId,
                    eval.agentPatchId,
                    eval.status,
                    eval.systemMessage,
                    eval.fileIntersectionSize,
                    eval.fileUnionSize,
                    eval.fileEvaluation,
                    eval.functionIntersectionSize,
                    eval.functionUnionSize,
                    eval.functionEvaluation,
                ),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_localization_eval(self, eval_id: int) -> PatchLocalizationEvaluation:
        """Get a PatchLocalizationEvaluation by evalId.

        Args:
            eval_id: The evalId to look up

        Returns:
            PatchLocalizationEvaluation object

        Raises:
            ValueError: If evaluation not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM patch_localization_evaluations WHERE evalId = ?",
                (eval_id,)
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"Localization evaluation not found: {eval_id}")
            return _row_to_localization_eval(row)

    async def get_localization_evaluations_batch(
        self,
        patch_ids: list[int]
    ) -> dict[int, PatchLocalizationEvaluation]:
        """Get localization evaluations for multiple patches.

        Args:
            patch_ids: List of patchIds (from agent_patches table) to fetch evaluations for

        Returns:
            Dictionary mapping patchId to PatchLocalizationEvaluation
        """
        if not patch_ids:
            return {}

        async with self._conn.cursor() as cur:
            placeholders = ','.join('?' * len(patch_ids))
            query = f"""
                SELECT ple.*, ap.patchId
                FROM patch_localization_evaluations ple
                INNER JOIN agent_patches ap ON ple.agentPatchId = ap.agentPatchId
                WHERE ap.patchId IN ({placeholders})
            """
            await cur.execute(query, patch_ids)
            rows = await cur.fetchall()

            return {row['patchId']: _row_to_localization_eval(row) for row in rows}
