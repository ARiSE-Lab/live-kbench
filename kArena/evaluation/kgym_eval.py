"""kGym Evaluation Module

This module provides crash resolution evaluation for agent-generated patches
using the kGym kernel testing infrastructure.

kGymEval implements a two-phase submit-then-poll contract:
- submit_eval(): submits the kGym job and stores a row with kGymEvaluation=NULL
- poll_eval(): polls the job and fills in the verdict when the job is complete

A row with kGymEvaluation IS NULL is the sentinel for "submitted but not yet
polled"; callers must not insert fully-populated rows outside of poll_eval.
"""

from KBDr.kclient import kGymAsyncClient
from kArena.models import PatchCrashResolutionEvaluation
from kArena.db import kArenaDB
from kArena.evaluation.verdict import interpret_kgym_verdict

# 5 kVMManager workers × 5 VMs each = 25 VM runs per patch evaluation.
DEFAULT_N_BATCH: int = 5
DEFAULT_N_INSTANCE: int = 5


class kGymEval:
    """Evaluates agent patches using kGym crash reproduction.

    This class handles the full evaluation workflow:
    - Fetches necessary data (bug, kCache, patch) from the database
    - Constructs a kBench with a single bug and its cached kernel
    - Runs kGym evaluation with the patch applied
    - Returns structured evaluation results

    Attributes:
        agent_patch: The AgentPatch object to evaluate
        db: Database connection for fetching data
        client: kGymAsyncClient for kGym operations
    """

    def __init__(self, agent_patch_id: int | None, db: kArenaDB, client: kGymAsyncClient):
        """Initialize the kGym evaluator.

        Args:
            agent_patch_id: AgentPatch ID (None for polling-only usage)
            db: kArenaDB instance for database operations
            client: kGymAsyncClient instance for kGym operations
        """
        self.agent_patch_id = agent_patch_id
        self.db = db
        self.client = client

    async def _submit_kgym_job(
        self,
        bug_id: str,
        kcache_job_id: str,
        patch_content: str,
        syzkaller_tag: str | None,
        n_batch: int = DEFAULT_N_BATCH
    ) -> str:
        """Submit a kGym evaluation job directly using kGym client.

        Creates a job request with:
        - kBuilderArgument worker (compiles kernel with patch)
        - kVMManagerArgument workers (runs crash reproduction n_batch times)

        Args:
            bug_id: Bug identifier
            kcache_job_id: Job ID of the cached kernel build
            patch_content: Patch content to apply
            syzkaller_tag: Syzkaller rollback tag (optional)
            n_batch: Number of VM instances to run (default: 5)

        Returns:
            JobId string of the submitted job

        Raises:
            Exception: If job submission fails
        """
        from KBDr.kclient_models.kbuilder import kBuilderArgument
        from KBDr.kclient_models.kvmmanager import kVMManagerArgument
        from KBDr.kclient.models import kJobRequest
        from KBDr.kcore import JobId

        # Fetch the kCache from the build job
        cached_job_ctx = await self.client.get_job(JobId(kcache_job_id))
        cached_result = cached_job_ctx.jobWorkers[0].workerResult
        kcache = cached_result.kCache

        # Fetch bug data for userspace image and reproducer info
        bug = await self.db.get_bug(bug_id)
        syzbot_data = bug.syzbotData

        # Create workers
        workers = []

        # Worker 1: kBuilder (compiles kernel with patch)
        workers.append(kBuilderArgument(
            kernelSource=kcache,
            userspaceImage=syzbot_data.userspaceImage,
            patch=patch_content
        ))

        # Workers 2+: kVMManager (runs VM with reproducer)
        image = 0  # Use output from first worker (kBuilder)
        for _ in range(n_batch):
            workers.append(kVMManagerArgument.model_from_syzbot_data(
                syzbot_data=syzbot_data,
                image=image,
                syzkaller_latest_tag=syzkaller_tag,
                ninstance=DEFAULT_N_INSTANCE
            ))

        # Create job request
        req = kJobRequest(
            jobWorkers=workers,
            tags={}
        )

        # Submit job and return job ID
        job_id = await self.client.create_job(req)
        return str(job_id)

    async def submit_eval(self) -> PatchCrashResolutionEvaluation:
        """Submit kGym evaluation job and return evaluation record with jobId.

        Returns:
            PatchCrashResolutionEvaluation with:
                - status='success'
                - kGymEvalJobId populated
                - kGymEvaluation=None (indicates submitted but not yet polled)
                - kGymEvaluationResult=None
        """
        # Fetch bug, kcache, patch
        agent_patch = await self.db.get_agent_patch(self.agent_patch_id)
        bug = await self.db.get_bug(agent_patch.bugId)
        kcache = await self.db.get_latest_kcache(agent_patch.bugId, agent_patch.baseCommit)
        patch = await self.db.get_patch(agent_patch.patchId)

        # Submit job directly
        job_id = await self._submit_kgym_job(
            bug_id=bug.bugId,
            kcache_job_id=str(kcache.kGymJobId),
            patch_content=patch.patchContent,
            syzkaller_tag=bug.syzkallerRollbackTag,
            n_batch=DEFAULT_N_BATCH
        )

        return PatchCrashResolutionEvaluation(
            evalId=0,
            agentPatchId=agent_patch.agentPatchId,
            kCacheId=kcache.kCacheId,
            kGymEvalJobId=job_id,
            status='success',
            systemMessage=f'Job submitted: {job_id}',
            kGymEvaluation=None,  # NULL indicates not yet polled
            kGymEvaluationResult=None
        )

    @staticmethod
    async def poll_eval(eval_id: int, db: 'kArenaDB', client: 'kGymAsyncClient') -> PatchCrashResolutionEvaluation | None:
        """Poll a submitted kGym evaluation job (static method).

        Args:
            eval_id: The evalId of the submitted evaluation record
            db: kArenaDB instance
            client: kGymAsyncClient instance

        Returns:
            PatchCrashResolutionEvaluation with populated results if job is complete,
            None if job is still in progress (Pending/InProgress/Waiting)

        Raises:
            ValueError: If evaluation not found or already polled
        """
        from KBDr.kcore import JobStatus, JobId

        # Fetch the existing evaluation record
        eval_record = await db.get_crash_resolution_eval(eval_id)

        # Check if already polled (kGymEvaluation is not NULL)
        if eval_record.kGymEvaluation is not None:
            raise ValueError(f"Evaluation {eval_id} already polled: kGymEvaluation={eval_record.kGymEvaluation}")

        # Get job status from kGym
        job_ctx = await client.get_job(JobId(eval_record.kGymEvalJobId))

        # If job is not finished, skip polling for now
        if job_ctx.status not in [JobStatus.Finished, JobStatus.Aborted]:
            return None  # Still in progress

        # Job is complete - interpret verdict using shared helper
        verdict = interpret_kgym_verdict(job_ctx, eval_record.kGymEvalJobId)

        return PatchCrashResolutionEvaluation(
            evalId=eval_record.evalId,
            agentPatchId=eval_record.agentPatchId,
            kCacheId=eval_record.kCacheId,
            kGymEvalJobId=eval_record.kGymEvalJobId,
            status='success',
            systemMessage=f'Evaluation completed: {verdict.evaluation}',
            kGymEvaluation=verdict.evaluation,
            kGymEvaluationResult=verdict
        )
