"""State transitions for the KEnvBaseMixin."""

from datetime import datetime

from kArena.models import kEnvBaseImage, kCache


def _pending_row(bug_id: str = 'bug-z', base_commit='parentCommit') -> kEnvBaseImage:
    return kEnvBaseImage(
        kEnvImageId=0, bugId=bug_id, baseCommit=base_commit,
        addedTime=datetime(2026, 4, 1),
        commitId='cafebabe', gitUrl='https://example/git', mirrorPath='mirror/x.git',
        localImageName=f'kenv-base-{bug_id}-parent-commit:latest',
        remoteImageName=f'reg/kenv-base-{bug_id}-parent-commit:latest',
        status='pending', systemMessage='Submitted',
    )


async def test_insert_and_lookup_kenv_base(db):
    kid = await db.insert_kenv_base(_pending_row())
    assert kid > 0

    row = await db.get_kenv_base('bug-z', 'parentCommit')
    assert row is not None
    assert row.commitId == 'cafebabe'
    assert row.status == 'pending'
    assert row.builtTime is None

    assert await db.get_kenv_base('bug-z', 'crashCommit') is None


async def test_claim_is_exclusive(db):
    kid = await db.insert_kenv_base(_pending_row())

    assert await db.claim_kenv_base_build(kid) is True
    # Second call must fail — row is now 'building'.
    assert await db.claim_kenv_base_build(kid) is False

    row = await db.get_kenv_base_by_id(kid)
    assert row.status == 'building'


async def test_mark_built_pushed_sets_timestamps(db):
    kid = await db.insert_kenv_base(_pending_row())
    await db.claim_kenv_base_build(kid)
    await db.mark_kenv_base_built(kid, pushed=True, message='ok')

    row = await db.get_kenv_base_by_id(kid)
    assert row.status == 'pushed'
    assert row.builtTime is not None
    assert row.pushedTime is not None
    assert row.systemMessage == 'ok'


async def test_mark_built_without_push_sets_only_built_time(db):
    kid = await db.insert_kenv_base(_pending_row())
    await db.claim_kenv_base_build(kid)
    await db.mark_kenv_base_built(kid, pushed=False)

    row = await db.get_kenv_base_by_id(kid)
    assert row.status == 'built'
    assert row.builtTime is not None
    assert row.pushedTime is None


async def test_mark_error_records_message(db):
    kid = await db.insert_kenv_base(_pending_row())
    await db.claim_kenv_base_build(kid)
    await db.mark_kenv_base_error(kid, 'docker build exit 2')

    row = await db.get_kenv_base_by_id(kid)
    assert row.status == 'error'
    assert row.systemMessage == 'docker build exit 2'


async def test_get_pending_includes_building_rows(db):
    k1 = await db.insert_kenv_base(_pending_row(bug_id='b1', base_commit='parentCommit'))
    k2 = await db.insert_kenv_base(_pending_row(bug_id='b2', base_commit='parentCommit'))
    await db.claim_kenv_base_build(k1)
    # k1 is now 'building'; k2 is 'pending'. Both must appear.
    assert set(await db.get_pending_kenv_base_builds()) == {k1, k2}

    await db.mark_kenv_base_built(k1, pushed=False)
    # Only k2 now.
    assert await db.get_pending_kenv_base_builds() == [k2]


async def test_get_bugs_needing_kenv_base_requires_reproduced_kcache(db):
    # Need a bug row because we join on syzbot_bugs.
    async with db._conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO syzbot_bugs
               (bugId, extid, title, addedTime, reportedTime, status, subsystem, syzbotData)
               VALUES ('bug-needs', 'ext', 't',
                       '2026-04-01T00:00:00', '2026-04-01T00:00:00',
                       'fixed', '[]', '{}')"""
        )
        await db._conn.commit()

    # A reproduced kCache for that bug at parentCommit.
    await db.insert_kcache(kCache(
        kCacheId=0, bugId='bug-needs', baseCommit='parentCommit',
        addedTime=datetime(2026, 4, 1), kGymJobId='deadbeef',
        status='success', systemMessage='ok',
        kGymEvaluation='reproduced',
    ))

    assert await db.get_bugs_needing_kenv_base('fixed') == ['bug-needs']

    # Once a kenv_base row exists for it, it disappears from the list.
    await db.insert_kenv_base(_pending_row(bug_id='bug-needs', base_commit='parentCommit'))
    assert await db.get_bugs_needing_kenv_base('fixed') == []


async def test_get_bugs_needing_kenv_base_skips_notreproduced(db):
    async with db._conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO syzbot_bugs
               (bugId, extid, title, addedTime, reportedTime, status, subsystem, syzbotData)
               VALUES ('bug-dud', 'ext', 't',
                       '2026-04-01T00:00:00', '2026-04-01T00:00:00',
                       'fixed', '[]', '{}')"""
        )
        await db._conn.commit()

    await db.insert_kcache(kCache(
        kCacheId=0, bugId='bug-dud', baseCommit='parentCommit',
        addedTime=datetime(2026, 4, 1), kGymJobId='deadbeef',
        status='success', systemMessage='nope',
        kGymEvaluation='notReproduced',
    ))
    # notReproduced must be filtered out.
    assert await db.get_bugs_needing_kenv_base('fixed') == []
