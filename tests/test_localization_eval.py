"""IoU math for LocalizationEval against an in-memory DB."""

from datetime import datetime

from kArena.evaluation.localization_eval import LocalizationEval, filter_source_files
from kArena.models import AgentPatch, DeveloperPatch, Patch


def _agent_patch(patch_id: int, agent_patch_id: int = 1) -> AgentPatch:
    return AgentPatch(
        agentPatchId=agent_patch_id, patchId=patch_id, bugId='bug-1',
        addedTime=datetime(2026, 1, 1), agentConfigId=1, unionId=1,
        baseCommit='parentCommit', status='success', systemMessage='',
        attrs={},
    )


def _dev_patch(patch_id: int, dev_patch_id: int = 1) -> DeveloperPatch:
    return DeveloperPatch(
        devPatchId=dev_patch_id, patchId=patch_id, bugId='bug-1',
        commitId='deadbeef', addedTime=datetime(2026, 1, 1),
        fixedTime=datetime(2026, 1, 2), patchMessage='fix',
        attrs={},
    )


async def _insert_patch(db, files, funcs):
    return await db.insert_patch(Patch(
        patchId=0, patchContent='(unused)', status='success', systemMessage='',
        modifiedFiles=list(files), modifiedFunctions=list(funcs), numModifiedLines=1,
    ))


def test_filter_source_files_drops_non_source():
    kept = filter_source_files({'a.c', 'b.h', 'c.py', 'd.md', 'e.S', 'f.txt'})
    assert kept == {'a.c', 'b.h', 'e.S'}


async def test_localization_partial_file_overlap(db):
    ap_id = await _insert_patch(db, files=['drivers/a.c', 'drivers/b.c', 'Makefile'],
                                funcs=['fa', 'fb'])
    dp_id = await _insert_patch(db, files=['drivers/a.c', 'drivers/c.c'],
                                funcs=['fa', 'fc'])

    ev = LocalizationEval(_agent_patch(ap_id), _dev_patch(dp_id), db)
    res = await ev.run_eval()

    assert res.status == 'success'
    # Makefile is filtered out; drivers/a.c is the only shared source file.
    # Files in the IoU: {a.c, b.c} ∪ {a.c, c.c} = 3; ∩ = 1 → 1/3.
    assert res.fileIntersectionSize == 1
    assert res.fileUnionSize == 3
    assert abs(res.fileEvaluation - (1 / 3)) < 1e-9
    # Functions are not filtered; {fa, fb} vs {fa, fc} → IoU = 1/3.
    assert res.functionIntersectionSize == 1
    assert res.functionUnionSize == 3
    assert abs(res.functionEvaluation - (1 / 3)) < 1e-9


async def test_localization_disjoint_is_zero(db):
    ap_id = await _insert_patch(db, files=['x.c'], funcs=['f1'])
    dp_id = await _insert_patch(db, files=['y.c'], funcs=['f2'])

    res = await LocalizationEval(_agent_patch(ap_id), _dev_patch(dp_id), db).run_eval()
    assert res.fileEvaluation == 0.0
    assert res.functionEvaluation == 0.0
    assert res.fileUnionSize == 2


async def test_localization_invalid_when_agent_patch_errored(db):
    # An errored agent patch (status='error') → short-circuit to 'invalid'.
    bad_id = await db.insert_patch(Patch(
        patchId=0, patchContent='', status='error',
        systemMessage='analysis broke', modifiedFiles=[], modifiedFunctions=[],
        numModifiedLines=0,
    ))
    dp_id = await _insert_patch(db, files=['x.c'], funcs=['f'])

    res = await LocalizationEval(_agent_patch(bad_id), _dev_patch(dp_id), db).run_eval()
    assert res.status == 'invalid'
    assert 'analysis broke' in res.systemMessage
