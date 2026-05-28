"""Shared kGym job verdict interpretation.

Turns a finished/aborted kJobContext into an EvaluationResult with the verdict
enum filled in. Used by both crash-resolution evaluation (applied patch) and
kCache build polling (no patch, baseline kernel).
"""

from KBDr.kclient import EvaluationResult
from KBDr.kcore import JobStatus


def interpret_kgym_verdict(job_ctx, job_id: str) -> EvaluationResult:
    """Interpret a finished kGym job context into an EvaluationResult.

    Expects the job to have a kBuilder worker at index 0 and one or more
    kVMManager workers after it. Returns verdicts:
    - 'compilationError' / 'error' for builder failures
    - 'imageError' when the built image is unusable on every VM
    - 'reproduced' / 'notReproduced' based on VM crash results

    Args:
        job_ctx: kJobContext returned by client.get_job(...)
        job_id: The job id (stored on the result for traceability)
    """
    er = EvaluationResult(
        jobId=job_id,
        jobContext=job_ctx,
        status=job_ctx.status,
        evaluation='error'
    )

    if job_ctx.status != JobStatus.Finished:
        if (
            job_ctx.jobWorkers[0].workerResult and
            job_ctx.jobWorkers[0].workerResult.jobException and
            job_ctx.jobWorkers[0].workerResult.jobException.code and
            job_ctx.jobWorkers[0].workerResult.jobException.code in (
                'kbuilder.KernelBuildError',
                'kbuilder.PatchApplicationError'
            )
        ):
            er.evaluation = 'compilationError'
        return er

    results = [
        w.workerResult for w in job_ctx.jobWorkers if w.workerType == 'kvmmanager'
    ]

    er.image = 'error'
    for result in results:
        if result.imageAbility == 'normal':
            er.image = 'normal'
        elif result.imageAbility == 'warning' and er.image != 'normal':
            er.image = 'warning'

    if er.image == 'error':
        er.evaluation = 'imageError'
        return er

    er.evaluation = 'notReproduced'
    er.resources = None
    for result in results:
        if result.crashes is None:
            continue
        for crash in result.crashes:
            if crash.crashType == 'special':
                continue
            er.evaluation = 'reproduced'
            er.title = crash.title
            er.resources = crash.incidents[0]
            return er

    return er
