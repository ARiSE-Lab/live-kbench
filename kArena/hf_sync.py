"""HuggingFace import/export for kArena bugs and dataset definitions.

HF repo layout (two dataset configs):
  bugs     — one row per SyzbotBug, `syzbotData` column is SyzbotData JSON
  datasets — one row per BugDataset, `bugIds`/`attrs` columns are JSON strings

Usage (export, run by maintainer):
    exporter = HFBugExporter(db)
    await exporter.export("org/live-kbench-bugs", token="hf_xxx")

Usage (import, run by operator):
    importer = HFBugImporter(db)
    new_ids = await importer.import_bugs("org/live-kbench-bugs")
    new_ds  = await importer.import_datasets("org/live-kbench-bugs")
"""

import json
import logging
from datetime import datetime

from KBDr.kclient import SyzbotData

from kArena.db import kArenaDB
from kArena.models import SyzbotBug

logger = logging.getLogger(__name__)


class HFBugExporter:
    """Exports kArena DB bugs and dataset definitions to a HuggingFace Dataset repo."""

    def __init__(self, db: kArenaDB) -> None:
        self.db = db

    async def export(
        self,
        hf_repo: str,
        token: str | None = None,
        *,
        private: bool = False,
    ) -> None:
        """Push all bugs and all dataset definitions to HuggingFace Hub.

        Args:
            hf_repo: HF repository name, e.g. ``"org/live-kbench-bugs"``.
            token: HuggingFace API token (falls back to ``HF_TOKEN`` env var).
            private: Whether to create/keep the repository private.
        """
        from datasets import Dataset

        bugs = await self.db.get_all_bugs()
        logger.info(f"[HFBugExporter] exporting {len(bugs)} bugs to {hf_repo}")

        bug_rows = [
            {
                'bugId': b.bugId,
                'extid': b.extid,
                'title': b.title,
                'addedTime': b.addedTime.isoformat(),
                'reportedTime': b.reportedTime.isoformat(),
                'status': b.status,
                'subsystem': json.dumps(b.subsystem),
                'syzbotCrashReport': b.syzbotCrashReport,
                'syzbotReproducer': b.syzbotReproducer,
                'syzkallerCommitId': b.syzkallerCommitId,
                'syzkallerRollbackTag': b.syzkallerRollbackTag,
                'syzbotData': b.syzbotData.model_dump_json(),
            }
            for b in bugs
        ]
        Dataset.from_list(bug_rows).push_to_hub(
            hf_repo, config_name='bugs', token=token, private=private
        )
        logger.info(f"[HFBugExporter] pushed {len(bug_rows)} bugs")

        datasets = await self.db.get_all_datasets()
        logger.info(f"[HFBugExporter] exporting {len(datasets)} dataset definitions")

        ds_rows = [
            {
                'datasetName': d.datasetName,
                'description': d.description,
                'addedTime': d.addedTime.isoformat(),
                'bugIds': json.dumps(d.bugIds),
                'attrs': json.dumps(d.attrs),
            }
            for d in datasets
        ]
        Dataset.from_list(ds_rows).push_to_hub(
            hf_repo, config_name='datasets', token=token, private=private
        )
        logger.info(f"[HFBugExporter] pushed {len(ds_rows)} dataset definitions")


class HFBugImporter:
    """Imports bugs and dataset definitions from a HuggingFace Dataset repo into kArena DB."""

    def __init__(self, db: kArenaDB) -> None:
        self.db = db

    async def import_bugs(
        self,
        hf_repo: str,
        token: str | None = None,
    ) -> list[str]:
        """Load bugs from HF and insert any that are not already in the DB.

        Uses the existing UPSERT logic in ``db.insert_syzbot_bug`` (no duplicates
        are created). Returns the list of bugIds that were newly inserted.

        Args:
            hf_repo: HF repository name.
            token: HuggingFace API token.

        Returns:
            List of newly-inserted bugIds.
        """
        from datasets import load_dataset

        existing_fixed = {bid for bid, _ in await self.db.get_fixed_bugs_ids()}
        existing_open = {bid for bid, _ in await self.db.get_open_bugs_ids()}
        existing = existing_fixed | existing_open

        logger.info(f"[HFBugImporter] loading bugs from {hf_repo} ({len(existing)} already in DB)")
        hf_ds = load_dataset(hf_repo, 'bugs', split='train', token=token)

        new_ids: list[str] = []
        for row in hf_ds:
            bug = SyzbotBug(
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
            await self.db.insert_syzbot_bug(bug)
            if bug.bugId not in existing:
                new_ids.append(bug.bugId)

        logger.info(f"[HFBugImporter] inserted {len(new_ids)} new bugs")
        return new_ids

    async def import_datasets(
        self,
        hf_repo: str,
        token: str | None = None,
    ) -> list[str]:
        """Load dataset definitions from HF and insert any not already present locally.

        Deduplication is by ``datasetName``: if a dataset with the same name exists
        in the local DB it is left untouched.

        Args:
            hf_repo: HF repository name.
            token: HuggingFace API token.

        Returns:
            List of newly-inserted dataset names.
        """
        from datasets import load_dataset

        logger.info(f"[HFBugImporter] loading dataset definitions from {hf_repo}")
        hf_ds = load_dataset(hf_repo, 'datasets', split='train', token=token)

        new_names: list[str] = []
        for row in hf_ds:
            name = row['datasetName']
            existing = await self.db.get_dataset_by_name(name)
            if existing is not None:
                await self.db.update_dataset(
                    dataset_id=existing.datasetId,
                    description=row['description'],
                    added_time=datetime.fromisoformat(row['addedTime']),
                    bug_ids=json.loads(row['bugIds']),
                    attrs=json.loads(row['attrs']),
                )
            else:
                await self.db.create_dataset(
                    name=name,
                    description=row['description'],
                    bug_ids=json.loads(row['bugIds']),
                    attrs=json.loads(row['attrs']),
                )
                new_names.append(name)

        logger.info(f"[HFBugImporter] inserted {len(new_names)} new dataset definitions")
        return new_names
