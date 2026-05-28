from datetime import datetime

from pydantic import BaseModel


class PassKCrashResolutionQuery(BaseModel):
    startTime: datetime
    endTime: datetime
    agentConfigId: int
    k: int


class PassKLLMJudgeQuery(BaseModel):
    startTime: datetime
    endTime: datetime
    agentConfigId: int
    judgeId: int
    k: int


class PassKLocalizationQuery(BaseModel):
    startTime: datetime
    endTime: datetime
    agentConfigId: int
    k: int


class PassKCrashResolutionResult(BaseModel):
    solvedBugs: list[str]
    unsolvedBugs: list[str]
    resolutionRate: float
    totalBugs: int


class PassKLLMJudgeResult(BaseModel):
    solvedBugs: list[str]
    unsolvedBugs: list[str]
    equivalentRate: float
    totalBugs: int


class PassKLocalizationResult(BaseModel):
    bugIoUs: dict[str, float]  # bugId -> averaged IoU
    statistics: dict[str, float]  # mean, variance, median, min, max
    totalBugs: int


class BugDifficultyQuery(BaseModel):
    startTime: datetime
    endTime: datetime
    agentConfigId: int | None = None  # Optional: filter by specific agent config


class BugDifficultyData(BaseModel):
    difficulty: float  # notReproduced / total
    notReproducedCount: int
    totalPatchCount: int


class BugDifficultyResult(BaseModel):
    bugDifficulties: dict[str, BugDifficultyData]  # bugId -> difficulty data
    statistics: dict[str, float]  # mean, variance, median, min, max of difficulty values
    totalBugs: int


class AverageDollarCostQuery(BaseModel):
    startTime: datetime
    endTime: datetime
    agentConfigId: int


class AverageDollarCostResult(BaseModel):
    bugAverageCosts: dict[str, float]  # bugId -> average dollarCost for that bug
    statistics: dict[str, float]  # mean, variance, median, min, max, std of bug averages
    totalBugs: int
