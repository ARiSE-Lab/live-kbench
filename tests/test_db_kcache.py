"""kCache submit-then-poll state transitions on kArenaDB.

Note: SQLite foreign keys are off by default (no ``PRAGMA foreign_keys = ON``
in ``initialize_schema``), so we can insert kCache rows without a bug row.
"""

from datetime import datetime

from kArena.models import kCache


def _pending_kcache(bug_id: str = 'bug-x', job_id: str = 'job-1') -> kCache:
    return kCache(
        kCacheId=0,
        bugId=bug_id,
        baseCommit='parentCommit',
        addedTime=datetime(2026, 1, 1, 12, 0, 0),
        kGymJobId=job_id,
        status='success',
        systemMessage='Submitted',
    )


async def test_submit_then_poll_marks_row_ready(db):
    kc_id = await db.insert_kcache(_pending_kcache())

    pending = await db.get_submitted_kcache_builds()
    assert pending == [kc_id]

    kc = await db.get_kcache_by_id(kc_id)
    # Poll sentinel is "kGymEvaluation IS NULL"
    assert kc.kGymEvaluation is None
    assert kc.status == 'success'

    # Fill in the poll result.
    kc.status = 'success'
    kc.systemMessage = 'kCache ready: reproduced'
    kc.kGymEvaluation = 'reproduced'
    kc.storageKey = 'gs://bucket/key'
    kc.storageUri = 'gs://bucket/path'
    kc.crashReport = 'kernel BUG at foo.c:42'
    await db.update_kcache_poll_result(kc)

    # Now it should no longer appear in the submitted-but-unpolled list.
    assert await db.get_submitted_kcache_builds() == []

    refetched = await db.get_kcache_by_id(kc_id)
    assert refetched.kGymEvaluation == 'reproduced'
    assert refetched.storageKey == 'gs://bucket/key'
    assert refetched.crashReport == 'kernel BUG at foo.c:42'


async def test_failed_submit_is_not_polled(db):
    # An "error" row represents a submit that failed before reaching kGym.
    row = _pending_kcache()
    row.status = 'error'
    row.systemMessage = 'Submit failed: network down'
    row.kGymJobId = ''
    await db.insert_kcache(row)

    # Only status='success' AND kGymEvaluation IS NULL rows should be returned.
    assert await db.get_submitted_kcache_builds() == []


async def test_get_latest_kcache_returns_most_recent(db):
    a = _pending_kcache(bug_id='bug-y', job_id='j-old')
    a.addedTime = datetime(2026, 1, 1, 0, 0, 0)
    b = _pending_kcache(bug_id='bug-y', job_id='j-new')
    b.addedTime = datetime(2026, 1, 2, 0, 0, 0)
    # Populate verdicts so get_latest_kcache (status='success') is satisfied
    a.kGymEvaluation = 'notReproduced'
    b.kGymEvaluation = 'reproduced'
    # UNIQUE(bugId, baseCommit) forbids two rows for the same bug+commit,
    # so give them different baseCommits.
    a.baseCommit = 'parentCommit'
    b.baseCommit = 'crashCommit'
    await db.insert_kcache(a)
    await db.insert_kcache(b)

    latest_parent = await db.get_latest_kcache('bug-y', 'parentCommit')
    latest_crash = await db.get_latest_kcache('bug-y', 'crashCommit')
    assert latest_parent.kGymJobId == 'j-old'
    assert latest_crash.kGymJobId == 'j-new'
