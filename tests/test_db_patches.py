"""Round-trip tests for the PatchMixin methods on kArenaDB."""

from kArena.models import Patch


async def test_insert_and_get_patch(db):
    patch = Patch(
        patchId=0,
        patchContent='diff --git a/foo b/foo\n',
        status='success',
        systemMessage='',
        modifiedFiles=['foo.c', 'bar.h'],
        modifiedFunctions=['do_thing', 'other_thing'],
        numModifiedLines=3,
    )
    new_id = await db.insert_patch(patch)
    assert new_id > 0

    fetched = await db.get_patch(new_id)
    assert fetched.patchId == new_id
    assert fetched.patchContent == patch.patchContent
    assert fetched.status == 'success'
    assert fetched.modifiedFiles == ['foo.c', 'bar.h']
    assert fetched.modifiedFunctions == ['do_thing', 'other_thing']
    assert fetched.numModifiedLines == 3


async def test_update_patch_analysis_overwrites_fields(db):
    patch = Patch(
        patchId=0, patchContent='raw', status='error', systemMessage='pending analysis',
        modifiedFiles=[], modifiedFunctions=[], numModifiedLines=0,
    )
    patch_id = await db.insert_patch(patch)

    await db.update_patch_analysis(
        patch_id=patch_id,
        status='success',
        system_message='analysed',
        modified_files=['a.c'],
        modified_functions=['f'],
        num_modified_lines=5,
    )

    updated = await db.get_patch(patch_id)
    assert updated.status == 'success'
    assert updated.systemMessage == 'analysed'
    assert updated.modifiedFiles == ['a.c']
    assert updated.modifiedFunctions == ['f']
    assert updated.numModifiedLines == 5
    # patchContent must survive analysis updates
    assert updated.patchContent == 'raw'


async def test_get_all_patch_ids_returns_inserted_ids(db):
    ids = set()
    for i in range(3):
        ids.add(await db.insert_patch(Patch(
            patchId=0, patchContent=f'p{i}', status='success', systemMessage='',
            modifiedFiles=[], modifiedFunctions=[], numModifiedLines=0,
        )))
    assert set(await db.get_all_patch_ids()) == ids
