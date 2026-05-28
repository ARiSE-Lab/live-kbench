"""LLMJudgeEval router-injection seam.

Verifies that passing ``router=`` to the constructor bypasses the
``RouterManager`` singleton entirely — useful for tests.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

from kArena.evaluation.llm_judge_eval import LLMJudgeEval
from kArena.models import AgentPatch, DeveloperPatch, LLMJudgeConfiguration, Patch


def _judge(n_votes: int = 1) -> LLMJudgeConfiguration:
    return LLMJudgeConfiguration(
        judgeId=1, judgeName='test-judge',
        prompt='dev:\n{devPatch}\nmsg:\n{devPatchMessage}\nagent:\n{agentPatch}',
        model='test-model', modelConfigName='test-config',
        nVotes=n_votes, attrs={},
    )


def _equivalent_response_text() -> str:
    return """
<reasoning>The patches are equivalent.</reasoning>
<evaluation>
<developerPatchAnalysis>dev does X</developerPatchAnalysis>
<studentPatchAnalysis>agent does X</studentPatchAnalysis>
<verdict>equivalent</verdict>
</evaluation>
"""


def _build_completion_response(text: str):
    """Shape an object matching ``router.acompletion`` return (OpenAI-ish)."""
    msg = type('M', (), {'content': text})()
    choice = type('C', (), {'message': msg})()
    return type('R', (), {'choices': [choice]})()


async def test_injected_router_bypasses_router_manager(db, tmp_path):
    ap_id = await db.insert_patch(Patch(
        patchId=0, patchContent='agent diff\n', status='success', systemMessage='',
        modifiedFiles=['a.c'], modifiedFunctions=['f'], numModifiedLines=1,
    ))
    dp_id = await db.insert_patch(Patch(
        patchId=0, patchContent='dev diff\n', status='success', systemMessage='',
        modifiedFiles=['a.c'], modifiedFunctions=['f'], numModifiedLines=1,
    ))
    agent_patch = AgentPatch(
        agentPatchId=1, patchId=ap_id, bugId='bug-1', addedTime=datetime(2026, 1, 1),
        agentConfigId=1, unionId=1, baseCommit='parentCommit',
        status='success', systemMessage='', attrs={},
    )
    dev_patch = DeveloperPatch(
        devPatchId=1, patchId=dp_id, bugId='bug-1', commitId='d',
        addedTime=datetime(2026, 1, 1), fixedTime=datetime(2026, 1, 2),
        patchMessage='fix', attrs={},
    )

    router = AsyncMock()
    router.acompletion = AsyncMock(
        return_value=_build_completion_response(_equivalent_response_text())
    )

    ev = LLMJudgeEval(
        judge_config=_judge(n_votes=1),
        agent_patch=agent_patch, dev_patch=dev_patch, db=db,
        workspace_root=tmp_path, router=router,
    )

    # RouterManager.get_router MUST NOT be called when a router is injected.
    with patch('kArena.evaluation.llm_judge_eval.RouterManager.get_router',
               side_effect=AssertionError('should not be called')):
        res = await ev.run_eval()

    router.acompletion.assert_awaited_once()
    assert res.status == 'success'
    assert res.yesCount == 1
    assert res.noCount == 0
    assert res.errorCount == 0
