import asyncio, json, logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from KBDr.kclient import (
    SyzbotCrawler, SyzbotData, SyzbotPopulator, SyzbotDataset,
    kBuilderArgument, kGymAsyncClient, kVMManagerArgument,
)
from KBDr.kclient.models import kJobRequest
from KBDr.kcore import JobId, JobStatus
from kArena.models import SyzbotBug, kArenaConfig, Patch, DeveloperPatch, kCache, kEnvBaseImage
from kArena.db import kArenaDB
from kArena.kenv_base_builder import KenvBaseBuildError, KenvBaseBuilder
from kArena.kenv_image_manager import get_docker_base_commit, KenvImageManager
from kArena.patch_analyzer import PatchAnalyzer
from kArena.evaluation.verdict import interpret_kgym_verdict

from google.cloud.storage import Client

logger = logging.getLogger(__name__)

class DataPipeline:

    def __init__(
        self,
        config: kArenaConfig,
        db: kArenaDB,
        max_reported_days: int = 365,
        *,
        client: kGymAsyncClient | None = None,
        crawler: SyzbotCrawler | None = None,
        populator: SyzbotPopulator | None = None,
        bucket=None,
    ):
        self.config = config
        self.db: kArenaDB = db
        self._client = client if client is not None else kGymAsyncClient(self.config.kGymEndpoint)
        self.crawler = crawler if crawler is not None else SyzbotCrawler(max_reported_days=max_reported_days)
        self.populator = populator if populator is not None else SyzbotPopulator(
            json.loads((self.config.workspaceRoot / 'shared' / 'repositories' / 'map.json').read_text())
        )
        self.bucket = bucket if bucket is not None else Client().bucket(
            json.loads((self.config.workspaceRoot / 'shared' / 'storageCfg.json').read_text())['providerConfig']['bucketName']
        )

        self.sem = asyncio.Semaphore(16)

    async def crawl(self) -> None:
        logger.info("Starting DataPipeline crawl")
        reported, subsystems_d, fixed_extids, open_extids = await self._scrape_tables()
        newly_fixed_list, newly_open_list = await self._discover_new_extids(fixed_extids, open_extids)
        bugs, bug_id2extid = await self._fetch_bug_details(newly_fixed_list, newly_open_list)
        await self._populate_and_insert(bugs, bug_id2extid, reported, subsystems_d)

    async def _scrape_tables(
        self,
    ) -> tuple[dict[str, int], dict[str, list[str]], set[str], set[str]]:
        """Crawl Syzbot fixed and open tables.

        Returns:
            (reported_days_by_extid, subsystems_by_extid, fixed_extids, open_extids)
        """
        fixed_extids: set[str] = set()
        open_extids: set[str] = set()
        reported: dict[str, int] = {}
        subsystems_d: dict[str, list[str]] = {}

        logger.info("Crawling Syzbot fixed bugs table")
        tbl = await self.crawler.crawl_fixed_table()
        for extid, reported_days, subsystems in tbl:
            fixed_extids.add(extid)
            reported[extid] = reported_days
            subsystems_d[extid] = subsystems
        logger.info(f"Found {len(fixed_extids)} fixed bugs in Syzbot")

        logger.info("Crawling Syzbot open bugs table")
        tbl = await self.crawler.crawl_open_table()
        for extid, reported_days, subsystems in tbl:
            open_extids.add(extid)
            reported[extid] = reported_days
            subsystems_d[extid] = subsystems
        logger.info(f"Found {len(open_extids)} open bugs in Syzbot")

        return reported, subsystems_d, fixed_extids, open_extids

    async def _discover_new_extids(
        self,
        fixed_extids: set[str],
        open_extids: set[str],
    ) -> tuple[list[str], list[str]]:
        """Diff scraped extids against the database.

        Returns:
            (newly_fixed_list, newly_open_list) — lists to preserve insertion order.
        """
        logger.info("Checking for new bugs against database")
        _fixed = await self.db.get_fixed_bugs_ids()
        _open = await self.db.get_open_bugs_ids()
        existing_fixed = {x[1] for x in _fixed}
        existing_open = {x[1] for x in _open}

        newly_fixed_list = list(fixed_extids - existing_fixed)
        newly_open_list = list(open_extids - existing_open)

        logger.info(
            f"Discovered {len(newly_fixed_list)} newly fixed bugs, "
            f"{len(newly_open_list)} newly open bugs"
        )
        logger.info(f"Existing in DB: {len(existing_fixed)} fixed, {len(existing_open)} open")
        return newly_fixed_list, newly_open_list

    async def _fetch_bug_details(
        self,
        newly_fixed_list: list[str],
        newly_open_list: list[str],
    ) -> tuple[list[SyzbotData], dict[str, str]]:
        """Fetch per-extid detail pages in parallel.

        Returns:
            (successful_bugs, bug_id_to_extid) — fixed bugs first, then open.
        """
        logger.info(
            f"Fetching detailed information for {len(newly_fixed_list)} fixed "
            f"and {len(newly_open_list)} open bugs"
        )
        newly_fixed_raw = await asyncio.gather(
            *[self.crawler.crawl_extid('fixed', e) for e in newly_fixed_list],
            return_exceptions=True,
        )
        newly_open_raw = await asyncio.gather(
            *[self.crawler.crawl_extid('open', e) for e in newly_open_list],
            return_exceptions=True,
        )

        bug_id2extid: dict[str, str] = {}
        fixed_exceptions = 0
        open_exceptions = 0

        for extid, dt in zip(newly_fixed_list, newly_fixed_raw):
            if isinstance(dt, SyzbotData):
                bug_id2extid[dt.bugId] = extid
            else:
                fixed_exceptions += 1
                logger.warning(f"Failed to fetch fixed bug {extid}: {dt}")

        for extid, dt in zip(newly_open_list, newly_open_raw):
            if isinstance(dt, SyzbotData):
                bug_id2extid[dt.bugId] = extid
            else:
                open_exceptions += 1
                logger.warning(f"Failed to fetch open bug {extid}: {dt}")

        newly_fixed = [dt for dt in newly_fixed_raw if isinstance(dt, SyzbotData)]
        newly_open = [dt for dt in newly_open_raw if isinstance(dt, SyzbotData)]

        logger.info(
            f"Successfully fetched {len(newly_fixed)} fixed bugs "
            f"({fixed_exceptions} failed) and {len(newly_open)} open bugs "
            f"({open_exceptions} failed)"
        )
        return newly_fixed + newly_open, bug_id2extid

    @staticmethod
    def _has_usable_reproducer(bug: SyzbotData) -> bool:
        """Return True if the bug has a usable syz reproducer on x86_64.

        Requires: at least one crash with a syz reproducer, an x86_64 kernel
        config, and (for fixed bugs) a known parentOfFixCommit.
        """
        return (
            bool(bug.crashes) and
            bug.crashes[0].syzReproducer is not None and
            bug.crashes[0].kernelConfig.find('Linux/x86_64') != -1 and
            (bug.status != 'fixed' or bug.parentOfFixCommit is not None)
        )

    async def _populate_and_insert(
        self,
        bugs: list[SyzbotData],
        bug_id2extid: dict[str, str],
        reported: dict[str, int],
        subsystems_d: dict[str, list[str]],
    ) -> None:
        """Populate bugs with repo metadata, filter, then insert into the DB."""
        logger.info(f"Populating {len(bugs)} bugs with repository information")
        populated = (await self.populator.populate_batch(SyzbotDataset(root=bugs))).root

        before_filter = len(populated)
        populated = [b for b in populated if self._has_usable_reproducer(b)]
        filtered_out = before_filter - len(populated)

        logger.info(
            f"Filtered bugs: {len(populated)} have reproducers, "
            f"{filtered_out} filtered out (no reproducer)"
        )
        if not populated:
            logger.warning("No bugs with reproducers found, pipeline will complete with no new data")
            return

        logger.info(f"Inserting {len(populated)} bugs into database")
        async with asyncio.TaskGroup() as tg:
            for bug in populated:
                extid = bug_id2extid[bug.bugId]
                bug.subsystems = subsystems_d[extid]
                tg.create_task(self.insert_syzbot_bug(bug, extid, reported[extid]))
        logger.info("Database insertion completed")

    async def submit_kcache_builds(
        self,
        status: Literal['open', 'fixed'],
        userspace_image_name: str = 'buildroot.raw',
        n_batch: int = 1,
        ninstance: int = 5,
        syzkaller_latest_tag: str = 'master',
    ) -> None:
        """Submit kCache build jobs (one per bug) without waiting for completion.

        Each job combines a from-scratch kBuilder (no patch) with n_batch
        kVMManager workers that re-run the reproducer on the built kernel. The
        kCache row is inserted immediately with status='success',
        kGymEvaluation=NULL, kGymJobId=<submitted job>; `populate_kcache_builds`
        later polls and fills in the verdict.
        """
        commit_from: Literal['parent', 'crash'] = 'parent' if status == 'fixed' else 'crash'
        base_commit: Literal['parentCommit', 'crashCommit'] = (
            'parentCommit' if status == 'fixed' else 'crashCommit'
        )

        bugs = await self.db.get_bugs_needing_kcache(status)
        if not bugs:
            logger.info(f'No {status} bugs need kCache for {base_commit}')
            return

        logger.info(f'Submitting kCache builds for {len(bugs)} {status} bugs')

        async def submit_one(bug: SyzbotBug) -> None:
            async with self.sem:
                await self._submit_single_kcache_build(
                    bug=bug,
                    commit_from=commit_from,
                    base_commit=base_commit,
                    userspace_image_name=userspace_image_name,
                    n_batch=n_batch,
                    ninstance=ninstance,
                    syzkaller_latest_tag=syzkaller_latest_tag,
                )

        async with asyncio.TaskGroup() as tg:
            for bug in bugs:
                tg.create_task(submit_one(bug))

        logger.info(f'kCache submission completed for {status} bugs')

    async def _submit_single_kcache_build(
        self,
        bug: SyzbotBug,
        commit_from: Literal['parent', 'crash'],
        base_commit: Literal['parentCommit', 'crashCommit'],
        userspace_image_name: str,
        n_batch: int,
        ninstance: int,
        syzkaller_latest_tag: str,
    ) -> None:
        syzbot_data = bug.syzbotData
        try:
            builder = kBuilderArgument.model_from_syzbot_data(
                syzbot_data=syzbot_data,
                userspace_image_name=userspace_image_name,
                commit_from=commit_from,
            )
            vms = [
                kVMManagerArgument.model_from_syzbot_data(
                    syzbot_data=syzbot_data,
                    image=0,
                    syzkaller_latest_tag=syzkaller_latest_tag,
                    ninstance=ninstance,
                )
                for _ in range(n_batch)
            ]
            req = kJobRequest(
                jobWorkers=[builder, *vms],
                tags={
                    'bugId': bug.bugId,
                    'baseCommit': base_commit,
                    'phase': 'kcache',
                },
            )
            job_id = await self._client.create_job(req)
        except Exception as e:
            logger.error(f'[{bug.bugId}] kCache submit failed: {e}', exc_info=True)
            await self.db.insert_kcache(kCache(
                kCacheId=0,
                bugId=bug.bugId,
                baseCommit=base_commit,
                addedTime=datetime.now(),
                kGymJobId='',
                status='error',
                systemMessage=f'Submit failed: {e}',
            ))
            return

        await self.db.insert_kcache(kCache(
            kCacheId=0,
            bugId=bug.bugId,
            baseCommit=base_commit,
            addedTime=datetime.now(),
            kGymJobId=str(job_id),
            status='success',
            systemMessage='Submitted',
        ))
        logger.info(f'[{bug.bugId}] submitted kCache job {job_id}')

    async def populate_kcache_builds(self, max_concurrent: int = 16) -> None:
        """Poll submitted kCache build jobs and fill in their verdicts.

        Picks up rows where status='success' AND kGymEvaluation IS NULL, polls
        kGym, and on completion updates storageKey/Uri, kGymEvaluation,
        kGymEvaluationResult, and (for reproduced crashes) the downloaded
        crashReport. Jobs still in progress are skipped and retried next call.
        """
        pending_ids = await self.db.get_submitted_kcache_builds()
        if not pending_ids:
            logger.info('No submitted kCache builds to poll')
            return

        logger.info(f'Polling {len(pending_ids)} submitted kCache builds')
        sem = asyncio.Semaphore(max_concurrent)

        completed = 0
        in_progress = 0
        failed = 0

        async def poll_one(kcache_id: int) -> None:
            nonlocal completed, in_progress, failed
            async with sem:
                try:
                    done = await self._poll_single_kcache_build(kcache_id)
                    if done is None:
                        in_progress += 1
                    elif done:
                        completed += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    logger.error(f'Error polling kCache {kcache_id}: {e}', exc_info=True)

        async with asyncio.TaskGroup() as tg:
            for kcache_id in pending_ids:
                tg.create_task(poll_one(kcache_id))

        logger.info(
            f'kCache polling done: {completed} completed, '
            f'{in_progress} still in progress, {failed} errored'
        )

    async def _poll_single_kcache_build(self, kcache_id: int) -> bool | None:
        """Poll one submitted kCache build.

        Returns True on successful fill-in, False on terminal failure, None if
        the job is still running.
        """
        kcache = await self.db.get_kcache_by_id(kcache_id)
        if not kcache.kGymJobId:
            # submit had already failed; nothing to poll
            return False

        job_ctx = await self._client.get_job(JobId(kcache.kGymJobId))
        if job_ctx is None or job_ctx.status not in (JobStatus.Finished, JobStatus.Aborted):
            return None

        verdict = interpret_kgym_verdict(job_ctx, kcache.kGymJobId)

        storage_key = None
        storage_uri = None
        if job_ctx.jobWorkers:
            builder_result = job_ctx.jobWorkers[0].workerResult
            if builder_result is not None and getattr(builder_result, 'kCache', None):
                storage_key = builder_result.kCache.key
                storage_uri = builder_result.kCache.storageUri

        crash_report = None
        if verdict.evaluation == 'reproduced' and verdict.resources and verdict.resources.report:
            report = verdict.resources.report
            try:
                blob_bytes = await asyncio.to_thread(
                    self.bucket.get_blob(report.key).download_as_bytes
                )
                crash_report = blob_bytes.decode(encoding='utf-8', errors='replace')
            except Exception as e:
                logger.warning(f'[{kcache.bugId}] failed to download crash report: {e}')

        # Any verdict where the build itself failed is terminal 'error'.
        build_failed = verdict.evaluation == 'compilationError' or storage_key is None
        kcache.status = 'error' if build_failed else 'success'
        kcache.systemMessage = (
            f'kCache build failed: {verdict.evaluation}'
            if build_failed else
            f'kCache ready: {verdict.evaluation}'
        )
        kcache.storageKey = storage_key
        kcache.storageUri = storage_uri
        kcache.kGymEvaluation = verdict.evaluation
        kcache.kGymEvaluationResult = verdict
        kcache.crashReport = crash_report

        await self.db.update_kcache_poll_result(kcache)
        logger.info(
            f'[{kcache.bugId}] kCache polled: {verdict.evaluation} '
            f'(kCacheId={kcache.kCacheId})'
        )
        return not build_failed

    async def submit_kenv_base_builds(
        self,
        status: Literal['open', 'fixed'],
    ) -> None:
        """Insert pending kenv_base_image rows for bugs whose kCache reproduces
        but which have no kenv_base_image row yet.

        Gated on ``kGymEvaluation='reproduced'`` at the matching baseCommit so
        we don't spend build resources on bugs the kernel can't build.
        """
        base_commit: Literal['parentCommit', 'crashCommit'] = (
            'parentCommit' if status == 'fixed' else 'crashCommit'
        )
        docker_base = get_docker_base_commit(base_commit)
        bug_ids = await self.db.get_bugs_needing_kenv_base(status)
        if not bug_ids:
            logger.info(f'No {status} bugs need a kenv-base image')
            return

        logger.info(f'Submitting kenv-base rows for {len(bug_ids)} {status} bugs')
        inserted = 0
        skipped = 0
        for bug_id in bug_ids:
            bug = await self.db.get_bug(bug_id)
            commit_id, git_url = self._resolve_base_commit_source(bug, status)
            if commit_id is None or git_url is None:
                skipped += 1
                logger.warning(
                    f'[{bug_id}] missing commit/git_url for {base_commit}; skipping'
                )
                continue
            mirror_path = self.populator.repository_map.get(git_url)
            if mirror_path is None:
                skipped += 1
                logger.warning(
                    f'[{bug_id}] no mirror configured for {git_url}; skipping'
                )
                continue

            row = kEnvBaseImage(
                kEnvImageId=0,
                bugId=bug_id,
                baseCommit=base_commit,
                addedTime=datetime.now(),
                commitId=commit_id,
                gitUrl=git_url,
                mirrorPath=mirror_path,
                localImageName=f'kenv-base-{bug_id}-{docker_base}:latest',
                remoteImageName=f'{self.config.dockerPrefix}/kenv-base-{bug_id}-{docker_base}:latest',
                status='pending',
                systemMessage='Submitted',
            )
            await self.db.insert_kenv_base(row)
            inserted += 1

        logger.info(
            f'kenv-base submission done: {inserted} inserted, {skipped} skipped'
        )

    async def populate_kenv_base_builds(
        self,
        *,
        push: bool | None = None,
        max_concurrent: int = 2,
        builder: KenvBaseBuilder | None = None,
    ) -> None:
        """Pick up pending rows, build the image locally, optionally push,
        remove the local copy, and write terminal state back to the DB.

        ``push=None`` (the default) auto-decides: push when ``config.dockerPrefix``
        is non-empty. Pass ``push=False`` for dry runs; pass ``builder`` to inject
        a fake in tests.
        """
        if builder is None:
            builder = KenvBaseBuilder(self.config)

        should_push = push if push is not None else bool(self.config.dockerPrefix)

        pending_ids = await self.db.get_pending_kenv_base_builds()
        if not pending_ids:
            logger.info('No pending kenv-base builds')
            return

        logger.info(f'Driving {len(pending_ids)} pending kenv-base builds (push={should_push})')
        sem = asyncio.Semaphore(max_concurrent)

        async def drive_one(kenv_image_id: int) -> None:
            async with sem:
                if not await self.db.claim_kenv_base_build(kenv_image_id):
                    # Lost the claim (already 'building' from a prior crashed run,
                    # or another worker got it). Don't touch it.
                    logger.info(f'kenv-base {kenv_image_id} not claimable; skipping')
                    return
                row = await self.db.get_kenv_base_by_id(kenv_image_id)
                try:
                    await builder.build(row)
                    if should_push:
                        await builder.push(row)
                        await builder.remove_local(row.localImageName, row.remoteImageName)
                    await self.db.mark_kenv_base_built(
                        kenv_image_id, pushed=should_push,
                        message='built and pushed' if should_push else 'built (local only)',
                    )
                    logger.info(f'[{row.bugId}] kenv-base {"pushed" if should_push else "built"}')
                except KenvBaseBuildError as e:
                    logger.error(f'[{row.bugId}] kenv-base build failed: {e}')
                    await self.db.mark_kenv_base_error(kenv_image_id, str(e))
                except Exception as e:
                    logger.exception(f'[{row.bugId}] unexpected kenv-base build error')
                    await self.db.mark_kenv_base_error(
                        kenv_image_id, f'unexpected: {type(e).__name__}: {e}'
                    )

        async with asyncio.TaskGroup() as tg:
            for kenv_image_id in pending_ids:
                tg.create_task(drive_one(kenv_image_id))

        logger.info('kenv-base populate done')

    def _resolve_base_commit_source(
        self,
        bug: SyzbotBug,
        status: Literal['open', 'fixed'],
    ) -> tuple[str | None, str | None]:
        """Return (commitId, gitUrl) for the image's base commit, or (None, None)
        if the required fields are missing on the SyzbotData.
        """
        data = bug.syzbotData
        if status == 'fixed':
            commit_id = data.parentOfFixCommit
        else:
            commit_id = None
            if data.crashes:
                commit_id = data.crashes[0].kernelSourceCommit or None
        git_url: str | None = None
        if data.crashes and data.crashes[0].kernelSourceGit:
            git_url = data.crashes[0].kernelSourceGit
        return commit_id, git_url

    async def insert_syzbot_bug(
        self,
        bug: SyzbotData,
        extid: str,
        reported_days: int
    ):
        """Insert a Syzbot bug into the database.

        Patch analysis is deferred to populate_developer_patches(), which runs
        after kenv-base is built.

        Args:
            bug: SyzbotData containing bug information
            extid: External ID from Syzbot
            reported_days: Days ago when the bug was reported
        """
        status = bug.status
        reported_time = datetime.now() - timedelta(days=reported_days)

        # Insert SyzbotBug
        logger.debug(f"Inserting SyzbotBug {bug.bugId} (status: {status}) into database")
        syzbot_bug = SyzbotBug(
            bugId=bug.bugId,
            extid=extid,
            title=bug.title,
            addedTime=datetime.now(),
            reportedTime=reported_time,
            status=status,
            subsystem=bug.subsystems or [],
            syzbotCrashReport=bug.rawCrashReport or '',
            syzbotReproducer=bug.crashes[0].syzReproducer if bug.crashes and bug.crashes[0].syzReproducer else '',
            syzkallerCommitId=bug.crashes[0].syzkallerCommit if bug.crashes else '',
            syzkallerRollbackTag='master',  # Will be populated later if needed
            syzbotData=bug
        )
        await self.db.insert_syzbot_bug(syzbot_bug)

    async def import_from_hf(
        self,
        hf_repo: str,
        token: str | None = None,
    ) -> None:
        """Import bugs and dataset definitions from a HuggingFace Dataset repo.

        Bugs already present in the DB (by bugId) are updated via UPSERT.
        Dataset definitions are inserted only if no local dataset with the same
        name exists. No kCache builds or kEnv image builds are triggered.

        Args:
            hf_repo: HF repository name, e.g. ``"org/live-kbench-bugs"``.
            token: HuggingFace API token (falls back to ``HF_TOKEN`` env var).
        """
        from kArena.hf_sync import HFBugImporter
        importer = HFBugImporter(self.db)
        new_bug_ids = await importer.import_bugs(hf_repo, token)
        new_ds_names = await importer.import_datasets(hf_repo, token)
        logger.info(
            f"[import_from_hf] done — {len(new_bug_ids)} new bugs, "
            f"{len(new_ds_names)} new dataset definitions"
        )

    async def populate_developer_patches(self) -> None:
        """Analyze and insert developer patches for fixed bugs whose kenv-base is built.

        Prerequisites per bug:
        - kenv_base_image.status IN ('built', 'pushed') at parentCommit
        - No existing developer_patches row

        For each qualifying bug:
        1. Skips if syzbotData.patch is empty
        2. Calls ensure_kenv_image() — pulls kenv-base from registry if needed, builds kenv
        3. Runs PatchAnalyzer against the developer's patch
        4. On success: inserts Patch + DeveloperPatch rows
        5. Always: prunes the kenv image via cleanup_images()
        """
        bug_ids = await self.db.get_bugs_needing_developer_patches()
        if not bug_ids:
            logger.info("[populate_developer_patches] nothing to do")
            return

        logger.info(f"[populate_developer_patches] {len(bug_ids)} bugs to process")

        async def _process_one(bug_id: str) -> None:
            bug_row = await self.db.get_bug(bug_id)
            bug = bug_row.syzbotData

            if not bug.patch:
                logger.debug(f"[{bug_id}] no patch in syzbotData, skipping")
                return

            image_mgr = KenvImageManager(self.config, 'parentCommit')
            try:
                async with self.sem:
                    await image_mgr.ensure_kenv_image(bug_id)

                    analyzer = PatchAnalyzer(
                        config=self.config,
                        bug=bug,
                        base_commit='parentCommit',
                        patch=bug.patch,
                    )
                    analysis = await analyzer.run_agent()

                if analysis and analysis.status == 'success':
                    patch = Patch(
                        patchId=0,
                        patchContent=analysis.patchContent,
                        status=analysis.status,
                        systemMessage=analysis.systemMessage,
                        modifiedFiles=analysis.modifiedFiles or [],
                        modifiedFunctions=analysis.modifiedFunctions or [],
                        numModifiedLines=analysis.numModifiedLines,
                    )
                    patch_id = await self.db.insert_patch(patch)
                    dev_patch = DeveloperPatch(
                        devPatchId=0,
                        patchId=patch_id,
                        bugId=bug_id,
                        commitId=bug.fixCommits[0].hashValue if bug.fixCommits and bug.fixCommits[0].hashValue else '',
                        addedTime=datetime.now(),
                        fixedTime=bug.patchCommitDate or datetime.now(),
                        patchMessage=bug.patchMessage,
                        attrs={},
                    )
                    await self.db.insert_developer_patch(dev_patch)
                    logger.info(f"[{bug_id}] developer patch inserted ({analysis.numModifiedLines} lines)")
                else:
                    logger.error(f"[{bug_id}] patch analysis failed: {analysis.systemMessage if analysis else 'no result'}")
            finally:
                await image_mgr.cleanup_images(bug_id)

        tasks = [asyncio.create_task(_process_one(bug_id)) for bug_id in bug_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for bug_id, result in zip(bug_ids, results):
            if isinstance(result, Exception):
                logger.error(f"[{bug_id}] populate_developer_patches error: {result}")

