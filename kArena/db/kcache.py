"""kCache DB operations: insert + poll/update + lookups."""

from datetime import datetime
from typing import Literal

from KBDr.kclient import EvaluationResult

from kArena.models import kCache


def _row_to_kcache(row) -> kCache:
    return kCache(
        kCacheId=row['kCacheId'],
        bugId=row['bugId'],
        baseCommit=row['baseCommit'],
        addedTime=datetime.fromisoformat(row['addedTime']),
        kGymJobId=row['kGymJobId'],
        status=row['status'],
        systemMessage=row['systemMessage'],
        storageKey=row['storageKey'],
        storageUri=row['storageUri'],
        kGymEvaluation=row['kGymEvaluation'],
        kGymEvaluationResult=EvaluationResult.model_validate_json(row['kGymEvaluationResult']) if row['kGymEvaluationResult'] else None,
        crashReport=row['crashReport'],
    )


class KCacheMixin:
    """kCache operations on :class:`kArenaDB`."""

    async def insert_kcache(self, kcache: kCache) -> int:
        """Insert a new kCache into the database.

        Args:
            kcache: kCache object to insert (kCacheId will be auto-generated)

        Returns:
            The auto-generated kCacheId
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO kcache (
                    bugId, baseCommit, addedTime, kGymJobId,
                    status, systemMessage, storageKey, storageUri,
                    kGymEvaluation, kGymEvaluationResult, crashReport
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kcache.bugId,
                    kcache.baseCommit,
                    kcache.addedTime.isoformat(),
                    kcache.kGymJobId,
                    kcache.status,
                    kcache.systemMessage,
                    kcache.storageKey,
                    kcache.storageUri,
                    kcache.kGymEvaluation,
                    kcache.kGymEvaluationResult.model_dump_json() if kcache.kGymEvaluationResult else None,
                    kcache.crashReport,
                ),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_latest_kcache(self, bug_id: str, base_commit: Literal['parentCommit', 'crashCommit']) -> kCache:
        """Get the latest kCache for a bug and baseCommit.

        If multiple kCache entries exist, returns the one with the latest addedTime.

        Args:
            bug_id: The bugId to look up
            base_commit: The baseCommit type ('parentCommit' or 'crashCommit')

        Returns:
            kCache object

        Raises:
            ValueError: If kCache not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT * FROM kcache
                WHERE bugId = ? AND baseCommit = ? AND status = 'success'
                ORDER BY addedTime DESC
                LIMIT 1
                """,
                (bug_id, base_commit)
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"kCache not found for bug {bug_id} with baseCommit {base_commit}")
            return _row_to_kcache(row)

    async def get_kcache_by_id(self, kcache_id: int) -> kCache:
        """Get a kCache by its primary key."""
        async with self._conn.cursor() as cur:
            await cur.execute("SELECT * FROM kcache WHERE kCacheId = ?", (kcache_id,))
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"kCache not found: {kcache_id}")
            return _row_to_kcache(row)

    async def get_submitted_kcache_builds(self) -> list[int]:
        """Return kCacheIds whose build job was submitted but not yet polled.

        A row in this state has status='success', kGymJobId set, and
        kGymEvaluation IS NULL (the poll sentinel).
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """SELECT kCacheId FROM kcache
                   WHERE status = 'success' AND kGymEvaluation IS NULL"""
            )
            rows = await cur.fetchall()
            return [row['kCacheId'] for row in rows]

    async def update_kcache_poll_result(self, kcache: kCache) -> None:
        """Fill in the poll-time fields of a kCache row.

        Updates status, systemMessage, storageKey, storageUri, kGymEvaluation,
        kGymEvaluationResult, and crashReport by kCacheId.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE kcache
                SET status = ?, systemMessage = ?,
                    storageKey = ?, storageUri = ?,
                    kGymEvaluation = ?, kGymEvaluationResult = ?,
                    crashReport = ?
                WHERE kCacheId = ?
                """,
                (
                    kcache.status,
                    kcache.systemMessage,
                    kcache.storageKey,
                    kcache.storageUri,
                    kcache.kGymEvaluation,
                    kcache.kGymEvaluationResult.model_dump_json() if kcache.kGymEvaluationResult else None,
                    kcache.crashReport,
                    kcache.kCacheId,
                )
            )
            await self._conn.commit()
