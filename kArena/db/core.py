"""kArenaDB: the composed async SQLite database facade.

Entity-specific query methods live on the mixin classes in sibling modules.
``kArenaDB`` combines them and owns the connection lifecycle + schema init.
"""

import aiosqlite
from typing import Literal

BaseCommit = Literal['parentCommit', 'crashCommit']


def base_commit_for_status(status: Literal['open', 'fixed']) -> BaseCommit:
    return 'parentCommit' if status == 'fixed' else 'crashCommit'

from kArena.db.agent_patches import AgentConfigMixin, AgentPatchMixin
from kArena.db.bugs import BugMixin
from kArena.db.datasets import DatasetMixin
from kArena.db.eval_crash import CrashEvalMixin
from kArena.db.eval_llm_judge import LLMJudgeMixin
from kArena.db.eval_localization import LocalizationEvalMixin
from kArena.db.kcache import KCacheMixin
from kArena.db.kenv_base import KEnvBaseMixin
from kArena.db.patches import PatchMixin
from kArena.db.schema import INDEXES, TABLES


class kArenaDB(
    BugMixin,
    KCacheMixin,
    KEnvBaseMixin,
    PatchMixin,
    AgentPatchMixin,
    AgentConfigMixin,
    CrashEvalMixin,
    LLMJudgeMixin,
    LocalizationEvalMixin,
    DatasetMixin,
):
    """Async database interface for kArena.

    Manages all kArena data including bug reports, patches, evaluations,
    and agent configurations using async SQLite operations.

    Usage:
        async with kArenaDB("karena.db") as db:
            await db.initialize_schema()
            bug = await db.get_bug("bug_id")
    """

    def __init__(self, db_path: str = "workspace/shared/karena.db"):
        """Initialize database connection manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self):
        """Open database connection with Row factory."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row

    async def close(self):
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def initialize_schema(self):
        """Create all database tables and indexes."""
        async with self._conn.cursor() as cur:
            for ddl in TABLES:
                await cur.execute(ddl)
            for ddl in INDEXES:
                await cur.execute(ddl)
            await self._conn.commit()
