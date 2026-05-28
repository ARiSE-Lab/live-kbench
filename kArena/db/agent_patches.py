"""AgentPatch + AgentConfiguration DB operations."""

import json
from datetime import datetime
from typing import Literal

from kArena.models import AgentConfiguration, AgentPatch
from kArena.db.core import base_commit_for_status


def _row_to_agent_patch(row) -> AgentPatch:
    return AgentPatch(
        agentPatchId=row['agentPatchId'],
        patchId=row['patchId'],
        bugId=row['bugId'],
        addedTime=datetime.fromisoformat(row['addedTime']),
        agentConfigId=row['agentConfigId'],
        unionId=row['unionId'],
        baseCommit=row['baseCommit'],
        status=row['status'],
        systemMessage=row['systemMessage'],
        dollarCost=row['dollarCost'],
        timeCost=row['timeCost'],
        exitReason=row['exitReason'],
        trajectoryKey=row['trajectoryKey'],
        logKey=row['logKey'],
        attrs=json.loads(row['attrs']),
    )


def _row_to_agent_config(row) -> AgentConfiguration:
    return AgentConfiguration(
        agentConfigId=row['agentConfigId'],
        agent=row['agent'],
        agentConfigName=row['agentConfigName'],
        model=row['model'],
        unionCounter=row['unionCounter'],
        statefulEdit=bool(row['statefulEdit']),
        oracleMode=bool(row['oracleMode']),
        modelConfigName=row['modelConfigName'],
        description=row['description'],
        attrs=json.loads(row['attrs']),
    )


class AgentPatchMixin:
    """AgentPatch operations on :class:`kArenaDB`."""

    async def insert_agent_patch(self, agent_patch: AgentPatch) -> int:
        """Insert a new AgentPatch into the database.

        Args:
            agent_patch: AgentPatch object to insert (agentPatchId will be auto-generated)

        Returns:
            The auto-generated agentPatchId
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO agent_patches (
                    patchId, bugId, addedTime, agentConfigId, unionId,
                    baseCommit, status, systemMessage,
                    dollarCost, timeCost, exitReason,
                    trajectoryKey, logKey, attrs
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_patch.patchId,
                    agent_patch.bugId,
                    agent_patch.addedTime.isoformat(),
                    agent_patch.agentConfigId,
                    agent_patch.unionId,
                    agent_patch.baseCommit,
                    agent_patch.status,
                    agent_patch.systemMessage,
                    agent_patch.dollarCost,
                    agent_patch.timeCost,
                    agent_patch.exitReason,
                    agent_patch.trajectoryKey,
                    agent_patch.logKey,
                    json.dumps(agent_patch.attrs),
                ),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def update_agent_patch_keys(
        self,
        agent_patch_id: int,
        trajectory_key: str,
        log_key: str
    ) -> None:
        """Update trajectoryKey and logKey for an AgentPatch.

        Args:
            agent_patch_id: The agentPatchId to update
            trajectory_key: New trajectoryKey value
            log_key: New logKey value
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE agent_patches
                SET trajectoryKey = ?, logKey = ?
                WHERE agentPatchId = ?
                """,
                (trajectory_key, log_key, agent_patch_id)
            )
            await self._conn.commit()

    async def get_agent_patch(self, agent_patch_id: int) -> AgentPatch:
        """Get an AgentPatch by agentPatchId.

        Args:
            agent_patch_id: The agentPatchId to look up

        Returns:
            AgentPatch object

        Raises:
            ValueError: If agent patch not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM agent_patches WHERE agentPatchId = ?",
                (agent_patch_id,)
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"Agent patch not found: {agent_patch_id}")
            return _row_to_agent_patch(row)

    async def _get_unattempted_bugs(
        self,
        *,
        base_commit: Literal['parentCommit', 'crashCommit'],
        agent_config_id: int,
        independent_runs: int,
        dataset_id: int | None = None,
        fixed_after: datetime | None = None,
        fixed_before: datetime | None = None,
    ) -> list[tuple[str, int]]:
        """Shared core query: bugs with fewer patches than independent_runs.

        Only includes bugs that have a reproduced kCache at base_commit.
        Optional dataset_id restricts to members of that named dataset.
        Optional fixed_after/fixed_before filter on developer_patches.fixedTime.

        Returns:
            List of (bugId, remaining_runs) tuples where
            remaining_runs = independent_runs - current patch count.
        """
        params: dict = {
            'independent_runs': independent_runs,
            'agent_config_id': agent_config_id,
            'base_commit': base_commit,
        }

        dataset_join = ''
        if dataset_id is not None:
            dataset_join = (
                'INNER JOIN bug_dataset_members bdm '
                'ON k.bugId = bdm.bugId AND bdm.datasetId = :dataset_id'
            )
            params['dataset_id'] = dataset_id

        date_filter = ''
        if fixed_after is not None or fixed_before is not None:
            date_filter = 'AND k.bugId IN (SELECT bugId FROM developer_patches WHERE 1=1'
            if fixed_after is not None:
                date_filter += ' AND fixedTime >= :fixed_after'
                params['fixed_after'] = fixed_after.isoformat()
            if fixed_before is not None:
                date_filter += ' AND fixedTime <= :fixed_before'
                params['fixed_before'] = fixed_before.isoformat()
            date_filter += ')'

        query = f"""
            SELECT k.bugId, :independent_runs - COUNT(ap.agentPatchId) AS remaining_runs
            FROM kcache k
            {dataset_join}
            LEFT JOIN agent_patches ap
                ON k.bugId = ap.bugId AND ap.agentConfigId = :agent_config_id
            WHERE k.baseCommit = :base_commit
              AND k.status = 'success'
              AND k.kGymEvaluation = 'reproduced'
              {date_filter}
            GROUP BY k.bugId
            HAVING COUNT(ap.agentPatchId) < :independent_runs
        """
        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()
            return [(row['bugId'], row['remaining_runs']) for row in rows]

    async def get_unattempted_bugs(
        self,
        status: Literal['open', 'fixed'],
        agent_config_id: int,
        independent_runs: int,
        fixed_after: datetime | None = None,
        fixed_before: datetime | None = None,
    ) -> list[tuple[str, int]]:
        """Get bugs with fewer patches than independent_runs for the given agent config.

        Only includes bugs that have a reproduced kCache entry. Delegates to
        _get_unattempted_bugs; base_commit is derived from status.

        Args:
            status: 'open' or 'fixed' (determines baseCommit used for kCache lookup)
            agent_config_id: The agentConfigId to check against
            independent_runs: Target number of patches per bug
            fixed_after: Optional lower bound (inclusive) on developer patch fixedTime
            fixed_before: Optional upper bound (inclusive) on developer patch fixedTime

        Returns:
            List of (bugId, remaining_runs) tuples.
        """
        return await self._get_unattempted_bugs(
            base_commit=base_commit_for_status(status),
            agent_config_id=agent_config_id,
            independent_runs=independent_runs,
            fixed_after=fixed_after,
            fixed_before=fixed_before,
        )

    async def get_yet_evaluated_agent_patches(
        self,
        eval_type: Literal['crashResolution', 'llmJudge', 'localization'],
        agent_config_id: int | None = None
    ) -> list[int]:
        table = {
            'crashResolution': 'patch_crash_resolution_evaluations',
            'llmJudge': 'patch_llm_judge_evaluations',
            'localization': 'patch_localization_evaluations',
        }[eval_type]
        query = f"""
            SELECT agentPatchId FROM agent_patches
            WHERE status == 'success' AND (
                agent_patches.agentPatchId NOT IN (
                    SELECT agentPatchId FROM {table}
                )
            )
        """
        params: list = []
        if agent_config_id is not None:
            query += " AND agentConfigId = ?"
            params.append(agent_config_id)
        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()
            return [row['agentPatchId'] for row in rows]

    async def get_agent_patch_ids_with_error_patch_analysis(self) -> list[int]:
        """Get all AgentPatch IDs where the associated Patch has status='error'.

        Returns:
            List of agentPatchIds where patch analysis failed
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT ap.agentPatchId
                FROM agent_patches ap
                INNER JOIN patches p ON ap.patchId = p.patchId
                WHERE p.status = 'error'
                """
            )
            rows = await cur.fetchall()
            return [row['agentPatchId'] for row in rows]

    async def get_agent_patches_ordered(
        self,
        agent_config_id: int,
        bug_ids: list[str]
    ) -> list[tuple[str, int, datetime]]:
        """Get agent patches ordered by bugId and addedTime.

        Args:
            agent_config_id: The agentConfigId to filter by
            bug_ids: List of bugIds to include

        Returns:
            List of (bugId, patchId, addedTime) tuples ordered by bugId, addedTime ASC
        """
        if not bug_ids:
            return []

        async with self._conn.cursor() as cur:
            placeholders = ','.join('?' * len(bug_ids))
            query = f"""
                SELECT ap.bugId, ap.patchId, ap.addedTime
                FROM agent_patches ap
                WHERE ap.agentConfigId = ? AND ap.bugId IN ({placeholders})
                ORDER BY ap.bugId, ap.addedTime ASC
            """
            await cur.execute(query, [agent_config_id] + bug_ids)
            rows = await cur.fetchall()
            return [
                (row['bugId'], row['patchId'], datetime.fromisoformat(row['addedTime']))
                for row in rows
            ]


class AgentConfigMixin:
    """AgentConfiguration operations on :class:`kArenaDB`."""

    async def insert_agent_configuration(self, config: AgentConfiguration) -> int:
        """Insert a new AgentConfiguration into the database.

        Args:
            config: AgentConfiguration object to insert (agentConfigId will be auto-generated if 0)

        Returns:
            The agentConfigId (auto-generated or existing)
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO agent_configurations (
                    agent, agentConfigName, model, unionCounter, statefulEdit,
                    oracleMode, modelConfigName, description, attrs
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    config.agent,
                    config.agentConfigName,
                    config.model,
                    config.unionCounter,
                    1 if config.statefulEdit else 0,  # Convert bool to int for SQLite
                    1 if config.oracleMode else 0,  # Convert bool to int for SQLite
                    config.modelConfigName,
                    config.description,
                    json.dumps(config.attrs),
                ),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def increment_and_get_union_counter(self, agent_config_id: int) -> int:
        """Increment unionCounter for an agent configuration and return the new value.

        Args:
            agent_config_id: The agentConfigId to increment

        Returns:
            The new unionCounter value after incrementing
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """UPDATE agent_configurations
                   SET unionCounter = unionCounter + 1
                   WHERE agentConfigId = ?
                   RETURNING unionCounter""",
                (agent_config_id,)
            )
            result = await cur.fetchone()
            await self._conn.commit()
            return result[0]

    async def get_agent_configuration(self, agent_config_id: int) -> AgentConfiguration:
        """Get an AgentConfiguration by agentConfigId.

        Args:
            agent_config_id: The agentConfigId to look up

        Returns:
            AgentConfiguration object

        Raises:
            ValueError: If agent configuration not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM agent_configurations WHERE agentConfigId = ?",
                (agent_config_id,)
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"Agent configuration not found: {agent_config_id}")
            return _row_to_agent_config(row)
