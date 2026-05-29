"""BugDataset DB operations."""

import json
from datetime import datetime
from typing import Literal

from kArena.models import BugDataset


class DatasetMixin:
    """Named bug-dataset ops on :class:`kArenaDB`."""

    async def get_dataset_bugs(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> list[str]:
        """Get bugIds for Live-kBench dataset.

        Returns bugIds where:
        - developer_patches.fixedTime is within [start_time, end_time]
        - kcache exists with kGymEvaluation = 'reproduced'

        Args:
            start_time: Start of time range (inclusive)
            end_time: End of time range (inclusive)

        Returns:
            List of bugIds matching the criteria
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT DISTINCT sb.bugId
                FROM syzbot_bugs sb
                INNER JOIN developer_patches dp ON sb.bugId = dp.bugId
                INNER JOIN kcache kc ON sb.bugId = kc.bugId
                WHERE dp.fixedTime BETWEEN ? AND ?
                  AND kc.kGymEvaluation = 'reproduced'
                """,
                (start_time.isoformat(), end_time.isoformat())
            )
            rows = await cur.fetchall()
            return [row['bugId'] for row in rows]

    async def create_dataset(
        self,
        name: str,
        description: str,
        bug_ids: list[str],
        attrs: dict[str, str] = {},
    ) -> BugDataset:
        """Create a named dataset of bugs.

        Args:
            name: Unique dataset name
            description: Human-readable description
            bug_ids: List of bugIds to include in the dataset
            attrs: Arbitrary key-value attributes

        Returns:
            BugDataset with the assigned datasetId
        """
        added_time = datetime.utcnow()
        async with self._conn.cursor() as cur:
            await cur.execute(
                'INSERT INTO bug_datasets (datasetName, description, addedTime, attrs) VALUES (?, ?, ?, ?)',
                (name, description, added_time.isoformat(), json.dumps(attrs))
            )
            dataset_id = cur.lastrowid
            if bug_ids:
                await cur.executemany(
                    'INSERT INTO bug_dataset_members (datasetId, bugId) VALUES (?, ?)',
                    [(dataset_id, bug_id) for bug_id in bug_ids]
                )
            await self._conn.commit()
        return BugDataset(
            datasetId=dataset_id,
            datasetName=name,
            description=description,
            addedTime=added_time,
            bugIds=list(bug_ids),
            attrs=attrs,
        )

    async def get_dataset(self, dataset_id: int) -> BugDataset | None:
        """Get a named bug dataset by ID.

        Args:
            dataset_id: The datasetId to fetch

        Returns:
            BugDataset if found, None otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                'SELECT datasetId, datasetName, description, addedTime, attrs FROM bug_datasets WHERE datasetId = ?',
                (dataset_id,)
            )
            row = await cur.fetchone()
            if row is None:
                return None
            await cur.execute(
                'SELECT bugId FROM bug_dataset_members WHERE datasetId = ?',
                (dataset_id,)
            )
            member_rows = await cur.fetchall()
        return BugDataset(
            datasetId=row['datasetId'],
            datasetName=row['datasetName'],
            description=row['description'],
            addedTime=datetime.fromisoformat(row['addedTime']),
            bugIds=[r['bugId'] for r in member_rows],
            attrs=json.loads(row['attrs']),
        )

    async def get_all_datasets(self) -> list[BugDataset]:
        """Return every named dataset in the database."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                'SELECT datasetId, datasetName, description, addedTime, attrs FROM bug_datasets'
            )
            rows = await cur.fetchall()
            datasets = []
            for row in rows:
                await cur.execute(
                    'SELECT bugId FROM bug_dataset_members WHERE datasetId = ?',
                    (row['datasetId'],)
                )
                member_rows = await cur.fetchall()
                datasets.append(BugDataset(
                    datasetId=row['datasetId'],
                    datasetName=row['datasetName'],
                    description=row['description'],
                    addedTime=datetime.fromisoformat(row['addedTime']),
                    bugIds=[r['bugId'] for r in member_rows],
                    attrs=json.loads(row['attrs']),
                ))
            return datasets

    async def update_dataset(
        self,
        dataset_id: int,
        description: str,
        added_time: datetime,
        bug_ids: list[str],
        attrs: dict[str, str],
    ) -> None:
        """Overwrite an existing dataset's metadata and member bugs."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                'UPDATE bug_datasets SET description = ?, addedTime = ?, attrs = ? WHERE datasetId = ?',
                (description, added_time.isoformat(), json.dumps(attrs), dataset_id)
            )
            await cur.execute(
                'DELETE FROM bug_dataset_members WHERE datasetId = ?',
                (dataset_id,)
            )
            if bug_ids:
                await cur.executemany(
                    'INSERT INTO bug_dataset_members (datasetId, bugId) VALUES (?, ?)',
                    [(dataset_id, bug_id) for bug_id in bug_ids]
                )
            await self._conn.commit()

    async def get_dataset_by_name(self, name: str) -> BugDataset | None:
        """Look up a dataset by its unique name; returns None if not found."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                'SELECT datasetId, datasetName, description, addedTime, attrs FROM bug_datasets WHERE datasetName = ?',
                (name,)
            )
            row = await cur.fetchone()
            if row is None:
                return None
            await cur.execute(
                'SELECT bugId FROM bug_dataset_members WHERE datasetId = ?',
                (row['datasetId'],)
            )
            member_rows = await cur.fetchall()
        return BugDataset(
            datasetId=row['datasetId'],
            datasetName=row['datasetName'],
            description=row['description'],
            addedTime=datetime.fromisoformat(row['addedTime']),
            bugIds=[r['bugId'] for r in member_rows],
            attrs=json.loads(row['attrs']),
        )

    async def get_unattempted_bugs_for_dataset(
        self,
        dataset_id: int,
        agent_config_id: int,
        independent_runs: int,
        base_commit: Literal['parentCommit', 'crashCommit'] = 'parentCommit',
        fixed_after: datetime | None = None,
        fixed_before: datetime | None = None,
    ) -> list[tuple[str, int]]:
        """Get dataset bugs with fewer patches than independent_runs for the given agent config.

        Only includes bugs that have a reproduced kCache entry. Delegates to
        _get_unattempted_bugs. fixed_after/fixed_before filter on fixedTime.

        Args:
            dataset_id: The datasetId to filter bugs by
            agent_config_id: The agentConfigId to check against
            independent_runs: Target number of patches per bug
            base_commit: Which kernel base commit to require a reproduced kCache for
            fixed_after: Optional lower bound (inclusive) on developer patch fixedTime
            fixed_before: Optional upper bound (inclusive) on developer patch fixedTime

        Returns:
            List of (bugId, remaining_runs) tuples.
        """
        return await self._get_unattempted_bugs(
            base_commit=base_commit,
            agent_config_id=agent_config_id,
            independent_runs=independent_runs,
            dataset_id=dataset_id,
            fixed_after=fixed_after,
            fixed_before=fixed_before,
        )
