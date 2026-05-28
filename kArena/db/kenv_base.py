"""kenv-base image build-state DB operations.

Mirrors the kcache submit-then-poll shape for docker-build work that happens
locally (not via kGym). State machine: ``pending → building → (built | pushed
| error)``. Claiming a row via :meth:`claim_kenv_base_build` is a CAS-style
update that prevents two workers from picking up the same row.
"""

from datetime import datetime
from typing import Literal

from kArena.models import kEnvBaseImage
from kArena.db.core import base_commit_for_status


class KEnvBaseMixin:
    """kenv-base image lifecycle ops on :class:`kArenaDB`."""

    async def insert_kenv_base(self, row: kEnvBaseImage) -> int:
        """Insert a new kenv_base_image row. Raises on UNIQUE(bugId, baseCommit)."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO kenv_base_image (
                    bugId, baseCommit, addedTime, commitId, gitUrl, mirrorPath,
                    localImageName, remoteImageName, status, systemMessage,
                    builtTime, pushedTime
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.bugId,
                    row.baseCommit,
                    row.addedTime.isoformat(),
                    row.commitId,
                    row.gitUrl,
                    row.mirrorPath,
                    row.localImageName,
                    row.remoteImageName,
                    row.status,
                    row.systemMessage,
                    row.builtTime.isoformat() if row.builtTime else None,
                    row.pushedTime.isoformat() if row.pushedTime else None,
                ),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_kenv_base(
        self,
        bug_id: str,
        base_commit: Literal['parentCommit', 'crashCommit'],
    ) -> kEnvBaseImage | None:
        """Return the kenv_base_image row for a (bugId, baseCommit) pair, or None."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                'SELECT * FROM kenv_base_image WHERE bugId = ? AND baseCommit = ?',
                (bug_id, base_commit),
            )
            row = await cur.fetchone()
            if not row:
                return None
            return _row_to_model(row)

    async def get_kenv_base_by_id(self, kenv_image_id: int) -> kEnvBaseImage:
        """Return the kenv_base_image row by primary key. Raises if missing."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                'SELECT * FROM kenv_base_image WHERE kEnvImageId = ?',
                (kenv_image_id,),
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f'kenv_base_image not found: {kenv_image_id}')
            return _row_to_model(row)

    async def get_pending_kenv_base_builds(self) -> list[int]:
        """Return kEnvImageIds still needing work (``pending`` or ``building``).

        ``building`` is included so that a crash mid-build doesn't strand the
        row — the next ``populate`` pass re-claims and retries.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """SELECT kEnvImageId FROM kenv_base_image
                   WHERE status IN ('pending', 'building')"""
            )
            rows = await cur.fetchall()
            return [row['kEnvImageId'] for row in rows]

    async def claim_kenv_base_build(self, kenv_image_id: int) -> bool:
        """CAS-style claim: move ``pending`` to ``building``. Returns True iff
        this call won the claim. A concurrent worker that tries to claim the
        same row will get False.

        Rows already in ``building`` are NOT re-claimed by this call (caller
        must decide whether to retry them — typically after a timeout).
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """UPDATE kenv_base_image
                   SET status = 'building'
                   WHERE kEnvImageId = ? AND status = 'pending'""",
                (kenv_image_id,),
            )
            claimed = cur.rowcount > 0
            await self._conn.commit()
            return claimed

    async def mark_kenv_base_built(
        self,
        kenv_image_id: int,
        *,
        pushed: bool,
        message: str = '',
    ) -> None:
        """Terminal success: row transitions to ``built`` or ``pushed``."""
        now = datetime.now()
        if pushed:
            await self._set_kenv_base_state(
                kenv_image_id,
                status='pushed',
                system_message=message or 'built and pushed',
                built_time=now,
                pushed_time=now,
            )
        else:
            await self._set_kenv_base_state(
                kenv_image_id,
                status='built',
                system_message=message or 'built (not pushed)',
                built_time=now,
                pushed_time=None,
            )

    async def mark_kenv_base_error(self, kenv_image_id: int, message: str) -> None:
        """Terminal failure: row transitions to ``error`` with a message."""
        await self._set_kenv_base_state(
            kenv_image_id,
            status='error',
            system_message=message,
            built_time=None,
            pushed_time=None,
        )

    async def _set_kenv_base_state(
        self,
        kenv_image_id: int,
        *,
        status: str,
        system_message: str,
        built_time: datetime | None,
        pushed_time: datetime | None,
    ) -> None:
        async with self._conn.cursor() as cur:
            await cur.execute(
                """UPDATE kenv_base_image
                   SET status = ?, systemMessage = ?,
                       builtTime = COALESCE(?, builtTime),
                       pushedTime = COALESCE(?, pushedTime)
                   WHERE kEnvImageId = ?""",
                (
                    status,
                    system_message,
                    built_time.isoformat() if built_time else None,
                    pushed_time.isoformat() if pushed_time else None,
                    kenv_image_id,
                ),
            )
            await self._conn.commit()

    async def get_bugs_needing_kenv_base(
        self,
        status: Literal['open', 'fixed'],
    ) -> list[str]:
        """Return bugIds whose kCache has ``kGymEvaluation='reproduced'`` at
        the matching baseCommit AND which have no kenv_base_image row yet.

        Gating on reproduced kCaches avoids spending build resources on bugs
        whose kernel won't build or whose reproducer doesn't fire.
        """
        base_commit = base_commit_for_status(status)
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT DISTINCT kc.bugId
                FROM kcache kc
                INNER JOIN syzbot_bugs sb ON kc.bugId = sb.bugId
                WHERE sb.status = ?
                  AND kc.baseCommit = ?
                  AND kc.status = 'success'
                  AND kc.kGymEvaluation = 'reproduced'
                  AND NOT EXISTS (
                      SELECT 1 FROM kenv_base_image ki
                      WHERE ki.bugId = kc.bugId AND ki.baseCommit = ?
                  )
                """,
                (status, base_commit, base_commit),
            )
            rows = await cur.fetchall()
            return [row['bugId'] for row in rows]


def _row_to_model(row) -> kEnvBaseImage:
    return kEnvBaseImage(
        kEnvImageId=row['kEnvImageId'],
        bugId=row['bugId'],
        baseCommit=row['baseCommit'],
        addedTime=datetime.fromisoformat(row['addedTime']),
        commitId=row['commitId'],
        gitUrl=row['gitUrl'],
        mirrorPath=row['mirrorPath'],
        localImageName=row['localImageName'],
        remoteImageName=row['remoteImageName'],
        status=row['status'],
        systemMessage=row['systemMessage'],
        builtTime=datetime.fromisoformat(row['builtTime']) if row['builtTime'] else None,
        pushedTime=datetime.fromisoformat(row['pushedTime']) if row['pushedTime'] else None,
    )
