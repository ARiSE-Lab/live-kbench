"""Patch + DeveloperPatch DB operations."""

import json
from datetime import datetime
from typing import Literal

from kArena.models import DeveloperPatch, Patch


def _row_to_patch(row) -> Patch:
    return Patch(
        patchId=row['patchId'],
        patchContent=row['patchContent'],
        status=row['status'],
        systemMessage=row['systemMessage'],
        modifiedFiles=json.loads(row['modifiedFiles']),
        modifiedFunctions=json.loads(row['modifiedFunctions']),
        numModifiedLines=row['numModifiedLines'],
    )


def _row_to_developer_patch(row) -> DeveloperPatch:
    return DeveloperPatch(
        devPatchId=row['devPatchId'],
        patchId=row['patchId'],
        bugId=row['bugId'],
        commitId=row['commitId'],
        addedTime=datetime.fromisoformat(row['addedTime']),
        fixedTime=datetime.fromisoformat(row['fixedTime']),
        patchMessage=row['patchMessage'],
        attrs=json.loads(row['attrs']),
    )


class PatchMixin:
    """Generic :class:`Patch` and :class:`DeveloperPatch` operations."""

    async def insert_patch(self, patch: Patch) -> int:
        """Insert a new Patch into the database.

        Args:
            patch: Patch object to insert (patchId will be auto-generated)

        Returns:
            The auto-generated patchId
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO patches (
                    patchContent, status, systemMessage,
                    modifiedFiles, modifiedFunctions, numModifiedLines
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    patch.patchContent,
                    patch.status,
                    patch.systemMessage,
                    json.dumps(patch.modifiedFiles),
                    json.dumps(patch.modifiedFunctions),
                    patch.numModifiedLines,
                ),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_patch(self, patch_id: int) -> Patch:
        """Get a Patch by patchId.

        Args:
            patch_id: The patchId to look up

        Returns:
            Patch object

        Raises:
            ValueError: If patch not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM patches WHERE patchId = ?",
                (patch_id,)
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"Patch not found: {patch_id}")
            return _row_to_patch(row)

    async def get_all_patch_ids(self) -> list[int]:
        """Get all patch IDs from the database.

        Returns:
            List of all patchIds
        """
        async with self._conn.cursor() as cur:
            await cur.execute("SELECT patchId FROM patches")
            rows = await cur.fetchall()
            return [row['patchId'] for row in rows]

    async def update_patch_content(
        self,
        patch_id: int,
        new_content: str
    ) -> None:
        """Update only the patchContent field for a patch.

        Args:
            patch_id: The patchId to update
            new_content: New patch content
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "UPDATE patches SET patchContent = ? WHERE patchId = ?",
                (new_content, patch_id)
            )
            await self._conn.commit()

    async def update_patch_analysis(
        self,
        patch_id: int,
        status: Literal['success', 'error'],
        system_message: str,
        modified_files: list[str],
        modified_functions: list[str],
        num_modified_lines: int
    ) -> None:
        """Update patch analysis results.

        Args:
            patch_id: The patchId to update
            status: Analysis status
            system_message: System message from analysis
            modified_files: List of modified file paths
            modified_functions: List of modified function names
            num_modified_lines: Number of modified lines
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE patches
                SET status = ?, systemMessage = ?, modifiedFiles = ?,
                    modifiedFunctions = ?, numModifiedLines = ?
                WHERE patchId = ?
                """,
                (
                    status,
                    system_message,
                    json.dumps(modified_files),
                    json.dumps(modified_functions),
                    num_modified_lines,
                    patch_id
                )
            )
            await self._conn.commit()

    async def insert_developer_patch(self, dev_patch: DeveloperPatch) -> int:
        """Insert a new DeveloperPatch into the database.

        Args:
            dev_patch: DeveloperPatch object to insert (devPatchId will be auto-generated)

        Returns:
            The auto-generated devPatchId
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO developer_patches (
                    patchId, bugId, commitId, addedTime, fixedTime, patchMessage, attrs
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dev_patch.patchId,
                    dev_patch.bugId,
                    dev_patch.commitId,
                    dev_patch.addedTime.isoformat(),
                    dev_patch.fixedTime.isoformat(),
                    dev_patch.patchMessage,
                    json.dumps(dev_patch.attrs),
                ),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_developer_patch(self, dev_patch_id: int) -> DeveloperPatch:
        """Get a DeveloperPatch by devPatchId.

        Args:
            dev_patch_id: The devPatchId to look up

        Returns:
            DeveloperPatch object

        Raises:
            ValueError: If developer patch not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM developer_patches WHERE devPatchId = ?",
                (dev_patch_id,)
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"Developer patch not found: {dev_patch_id}")
            return _row_to_developer_patch(row)

    async def get_bugs_needing_developer_patches(self) -> list[str]:
        """Return bugIds of fixed bugs whose kenv-base is built but have no DeveloperPatch yet."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT DISTINCT sb.bugId
                FROM syzbot_bugs sb
                INNER JOIN kenv_base_image ki
                    ON ki.bugId = sb.bugId AND ki.baseCommit = 'parentCommit'
                WHERE sb.status = 'fixed'
                  AND ki.status IN ('built', 'pushed')
                  AND NOT EXISTS (
                      SELECT 1 FROM developer_patches dp WHERE dp.bugId = sb.bugId
                  )
                """
            )
            rows = await cur.fetchall()
            return [row['bugId'] for row in rows]

    async def get_developer_patch_by_bug_id(self, bug_id: str) -> DeveloperPatch | None:
        """Get a DeveloperPatch by bugId.

        Args:
            bug_id: The bugId to look up

        Returns:
            DeveloperPatch object, or None if not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                'SELECT * FROM developer_patches WHERE bugId = ?',
                (bug_id,)
            )
            row = await cur.fetchone()
            if not row:
                return None
            return _row_to_developer_patch(row)
