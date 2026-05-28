"""Bug-related DB operations: SyzbotBug CRUD and selection helpers."""

import json
from datetime import datetime
from typing import Literal

from KBDr.kclient import SyzbotData

from kArena.models import SyzbotBug
from kArena.db.core import base_commit_for_status


def _row_to_bug(row) -> SyzbotBug:
    return SyzbotBug(
        bugId=row['bugId'],
        extid=row['extid'],
        title=row['title'],
        addedTime=datetime.fromisoformat(row['addedTime']),
        reportedTime=datetime.fromisoformat(row['reportedTime']),
        status=row['status'],
        subsystem=json.loads(row['subsystem']),
        syzbotCrashReport=row['syzbotCrashReport'],
        syzbotReproducer=row['syzbotReproducer'],
        syzkallerCommitId=row['syzkallerCommitId'],
        syzkallerRollbackTag=row['syzkallerRollbackTag'],
        syzbotData=SyzbotData.model_validate_json(row['syzbotData']),
    )


class BugMixin:
    """SyzbotBug operations on :class:`kArenaDB`.

    Depends on :attr:`_conn` being set on the combined class.
    """

    async def get_fixed_bugs_ids(self) -> list[tuple[str, str]]:
        """Get bugId and extid for all fixed bugs.

        Returns:
            List of tuples (bugId, extid) for bugs with status='fixed'
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT bugId, extid FROM syzbot_bugs WHERE status = 'fixed'"
            )
            rows = await cur.fetchall()
            return [(row['bugId'], row['extid']) for row in rows]

    async def get_open_bugs_ids(self) -> list[tuple[str, str]]:
        """Get bugId and extid for all open bugs.

        Returns:
            List of tuples (bugId, extid) for bugs with status='open'
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT bugId, extid FROM syzbot_bugs WHERE status = 'open'"
            )
            rows = await cur.fetchall()
            return [(row['bugId'], row['extid']) for row in rows]

    async def get_bugs_needing_kcache(
        self,
        status: Literal['open', 'fixed']
    ) -> list[SyzbotBug]:
        """Get all bugs that don't have kCache for the given status.

        Args:
            status: 'fixed' or 'open' - determines which baseCommit to check
                    'fixed' checks for 'parentCommit' kCache
                    'open' checks for 'crashCommit' kCache

        Returns:
            List of SyzbotBug objects that need kCache
        """
        base_commit = base_commit_for_status(status)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT * FROM syzbot_bugs
                WHERE bugId NOT IN (
                    SELECT bugId FROM kcache WHERE baseCommit = ?
                )
                AND status = ?
                """,
                (base_commit, status)
            )
            rows = await cur.fetchall()

            return [_row_to_bug(row) for row in rows]

    async def insert_syzbot_bug(self, bug: SyzbotBug) -> str:
        """Insert a new SyzbotBug into the database, or update if exists.

        Uses UPSERT logic: if bugId already exists, updates only:
        - status
        - subsystem
        - syzbotCrashReport
        - syzbotData

        Args:
            bug: SyzbotBug object to insert

        Returns:
            The bugId
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO syzbot_bugs (
                    bugId, extid, title, addedTime, reportedTime,
                    status, subsystem, syzbotCrashReport,
                    syzbotReproducer, syzkallerCommitId, syzkallerRollbackTag,
                    syzbotData
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bugId) DO UPDATE SET
                    status = excluded.status,
                    subsystem = excluded.subsystem,
                    syzbotCrashReport = excluded.syzbotCrashReport,
                    syzbotData = excluded.syzbotData
                """,
                (
                    bug.bugId,
                    bug.extid,
                    bug.title,
                    bug.addedTime.isoformat(),
                    bug.reportedTime.isoformat(),
                    bug.status,
                    json.dumps(bug.subsystem),
                    bug.syzbotCrashReport,
                    bug.syzbotReproducer,
                    bug.syzkallerCommitId,
                    bug.syzkallerRollbackTag,
                    bug.syzbotData.model_dump_json(),
                ),
            )
            await self._conn.commit()
            return bug.bugId

    async def get_all_bugs(self) -> list[SyzbotBug]:
        """Return every bug in the database regardless of status."""
        async with self._conn.cursor() as cur:
            await cur.execute("SELECT * FROM syzbot_bugs")
            rows = await cur.fetchall()
            return [_row_to_bug(row) for row in rows]

    async def get_bug(self, bug_id: str) -> SyzbotBug:
        """Get a SyzbotBug by bugId.

        Args:
            bug_id: The bugId to look up

        Returns:
            SyzbotBug object

        Raises:
            ValueError: If bug not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM syzbot_bugs WHERE bugId = ?",
                (bug_id,)
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"Bug not found: {bug_id}")
            return _row_to_bug(row)
