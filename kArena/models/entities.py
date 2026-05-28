from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from KBDr.kclient import EvaluationResult, SyzbotData


class SyzbotBug(BaseModel):
    bugId: str
    extid: str
    title: str
    addedTime: datetime
    reportedTime: datetime
    status: Literal['open', 'fixed']
    subsystem: list[str]
    syzbotCrashReport: str
    syzbotReproducer: str
    syzkallerCommitId: str
    syzkallerRollbackTag: str
    syzbotData: SyzbotData


class kCache(BaseModel):
    kCacheId: int
    bugId: str
    baseCommit: Literal['parentCommit', 'crashCommit']
    addedTime: datetime
    kGymJobId: str

    status: Literal['success', 'error']
    systemMessage: str

    storageKey: str | None = None
    storageUri: str | None = None

    kGymEvaluation: Literal['notReproduced', 'reproduced', 'compilationError', 'imageError', 'error'] | None = None
    kGymEvaluationResult: EvaluationResult | None = None
    crashReport: str | None = None


class Patch(BaseModel):
    patchId: int
    patchContent: str

    status: Literal['success', 'error']
    systemMessage: str

    modifiedFiles: list[str]
    modifiedFunctions: list[str]
    numModifiedLines: int


class AgentPatch(BaseModel):
    # main key;
    agentPatchId: int
    patchId: int
    bugId: str
    addedTime: datetime
    agentConfigId: int
    unionId: int
    baseCommit: Literal['parentCommit', 'crashCommit']

    status: Literal['success', 'error']
    systemMessage: str

    dollarCost: float | None = None
    timeCost: int | None = None
    exitReason: Literal['normal', 'costLimitExceeded', 'timeLimitExceeded'] | None = None

    trajectoryKey: str | None = None
    logKey: str | None = None

    attrs: dict[str, str]


class DeveloperPatch(BaseModel):
    devPatchId: int
    patchId: int
    bugId: str
    commitId: str
    addedTime: datetime
    fixedTime: datetime
    patchMessage: str
    attrs: dict[str, str]


class AgentConfiguration(BaseModel):
    agentConfigId: int
    # 'mini-swe-agent', 'openhands', 'swe-agent'
    agent: str
    # 'mini-swe-agent-cost-10', ...
    agentConfigName: str
    model: str
    modelConfigName: str
    # how many times to deal with high temp;
    unionCounter: int
    statefulEdit: bool
    oracleMode: bool
    description: str
    attrs: dict[str, str]


class PatchLocalizationEvaluation(BaseModel):
    evalId: int
    bugId: str
    devPatchId: int
    agentPatchId: int

    status: Literal['success', 'error', 'invalid']
    systemMessage: str

    # File-level metrics
    fileIntersectionSize: int
    fileUnionSize: int
    fileEvaluation: float

    # Function-level metrics
    functionIntersectionSize: int
    functionUnionSize: int
    functionEvaluation: float


class PatchCrashResolutionEvaluation(BaseModel):
    evalId: int
    agentPatchId: int
    kCacheId: int
    kGymEvalJobId: str

    status: Literal['success', 'error']
    systemMessage: str

    kGymEvaluation: Literal['notReproduced', 'reproduced', 'compilationError', 'imageError', 'error'] | None = None
    kGymEvaluationResult: EvaluationResult | None = None


class LLMJudgeConfiguration(BaseModel):
    judgeId: int
    judgeName: str
    prompt: str
    model: str
    modelConfigName: str
    nVotes: int
    attrs: dict[str, str] = {}


class PatchLLMJudgeEvaluation(BaseModel):
    evalId: int
    judgeId: int
    bugId: str
    devPatchId: int
    agentPatchId: int

    status: Literal['success', 'error']
    systemMessage: str

    # Aggregated counts (nullable - None if evaluation failed)
    yesCount: int | None = None
    noCount: int | None = None
    errorCount: int | None = None

    # LLM conversation trajectories (nullable - None if evaluation failed)
    # Each inner list contains the message history for that vote
    # Vote outcome can be extracted from the assistant's response
    # Messages can contain tool_calls (list) or content (str), so values are Any
    llmMessages: list[list[dict]] | None = None


class BugDataset(BaseModel):
    datasetId: int
    datasetName: str
    description: str
    addedTime: datetime
    bugIds: list[str]
    attrs: dict[str, str]


class kEnvBaseImage(BaseModel):
    kEnvImageId: int
    bugId: str
    baseCommit: Literal['parentCommit', 'crashCommit']
    addedTime: datetime

    # Build inputs — captured at submit time so retries are deterministic.
    commitId: str
    gitUrl: str
    mirrorPath: str

    # Image tags (redundant with bugId/baseCommit but convenient).
    localImageName: str
    remoteImageName: str

    status: Literal['pending', 'building', 'built', 'pushed', 'error']
    systemMessage: str = ''
    builtTime: datetime | None = None
    pushedTime: datetime | None = None
