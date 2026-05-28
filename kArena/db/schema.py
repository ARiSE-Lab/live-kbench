"""SQL DDL for kArena tables and indexes."""

TABLES: list[str] = [
    # SyzbotBug table
    """
    CREATE TABLE IF NOT EXISTS syzbot_bugs (
        bugId TEXT PRIMARY KEY,
        extid TEXT NOT NULL,
        title TEXT NOT NULL,
        addedTime TEXT NOT NULL,
        reportedTime TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('open', 'fixed')),
        subsystem TEXT NOT NULL,
        syzbotCrashReport TEXT,
        syzbotReproducer TEXT,
        syzkallerCommitId TEXT,
        syzkallerRollbackTag TEXT,
        syzbotData TEXT NOT NULL
    )
    """,
    # kCache table
    """
    CREATE TABLE IF NOT EXISTS kcache (
        kCacheId INTEGER PRIMARY KEY AUTOINCREMENT,
        bugId TEXT NOT NULL,
        baseCommit TEXT NOT NULL CHECK(baseCommit IN ('parentCommit', 'crashCommit')),
        addedTime TEXT NOT NULL,
        kGymJobId TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('success', 'error')),
        systemMessage TEXT NOT NULL,
        storageKey TEXT,
        storageUri TEXT,
        kGymEvaluation TEXT CHECK(kGymEvaluation IN ('notReproduced', 'reproduced', 'compilationError', 'imageError', 'error')),
        kGymEvaluationResult TEXT,
        crashReport TEXT,
        FOREIGN KEY (bugId) REFERENCES syzbot_bugs(bugId) ON DELETE CASCADE,
        UNIQUE(bugId, baseCommit)
    )
    """,
    # Patches table
    """
    CREATE TABLE IF NOT EXISTS patches (
        patchId INTEGER PRIMARY KEY AUTOINCREMENT,
        patchContent TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('success', 'error')),
        systemMessage TEXT NOT NULL,
        modifiedFiles TEXT NOT NULL,
        modifiedFunctions TEXT NOT NULL,
        numModifiedLines INTEGER NOT NULL
    )
    """,
    # AgentPatch table
    """
    CREATE TABLE IF NOT EXISTS agent_patches (
        agentPatchId INTEGER PRIMARY KEY AUTOINCREMENT,
        patchId INTEGER NOT NULL,
        bugId TEXT NOT NULL,
        addedTime TEXT NOT NULL,
        agentConfigId INTEGER NOT NULL,
        unionId INTEGER NOT NULL,
        baseCommit TEXT NOT NULL CHECK(baseCommit IN ('parentCommit', 'crashCommit')),
        status TEXT NOT NULL CHECK(status IN ('success', 'error')),
        systemMessage TEXT NOT NULL,
        trajectoryKey TEXT,
        logKey TEXT,
        attrs TEXT NOT NULL,
        FOREIGN KEY (patchId) REFERENCES patches(patchId) ON DELETE CASCADE,
        FOREIGN KEY (bugId) REFERENCES syzbot_bugs(bugId) ON DELETE CASCADE,
        FOREIGN KEY (agentConfigId) REFERENCES agent_configurations(agentConfigId) ON DELETE CASCADE
    )
    """,
    # DeveloperPatch table
    """
    CREATE TABLE IF NOT EXISTS developer_patches (
        devPatchId INTEGER PRIMARY KEY AUTOINCREMENT,
        patchId INTEGER NOT NULL,
        bugId TEXT NOT NULL,
        commitId TEXT NOT NULL,
        addedTime TEXT NOT NULL,
        fixedTime TEXT NOT NULL,
        patchMessage TEXT NOT NULL,
        attrs TEXT NOT NULL,
        FOREIGN KEY (patchId) REFERENCES patches(patchId) ON DELETE CASCADE,
        FOREIGN KEY (bugId) REFERENCES syzbot_bugs(bugId) ON DELETE CASCADE
    )
    """,
    # AgentConfiguration table
    """
    CREATE TABLE IF NOT EXISTS agent_configurations (
        agentConfigId INTEGER PRIMARY KEY AUTOINCREMENT,
        agent TEXT NOT NULL,
        agentConfigName TEXT NOT NULL,
        model TEXT NOT NULL,
        unionCounter INTEGER NOT NULL,
        statefulEdit INTEGER NOT NULL,
        oracleMode INTEGER NOT NULL,
        modelConfigName TEXT NOT NULL,
        description TEXT NOT NULL,
        attrs TEXT NOT NULL
    )
    """,
    # PatchLocalizationEvaluation table
    """
    CREATE TABLE IF NOT EXISTS patch_localization_evaluations (
        evalId INTEGER PRIMARY KEY AUTOINCREMENT,
        bugId TEXT NOT NULL,
        devPatchId INTEGER NOT NULL,
        agentPatchId INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('success', 'error', 'invalid')),
        systemMessage TEXT NOT NULL,
        fileIntersectionSize INTEGER NOT NULL,
        fileUnionSize INTEGER NOT NULL,
        fileEvaluation REAL NOT NULL,
        functionIntersectionSize INTEGER NOT NULL,
        functionUnionSize INTEGER NOT NULL,
        functionEvaluation REAL NOT NULL,
        FOREIGN KEY (bugId) REFERENCES syzbot_bugs(bugId) ON DELETE CASCADE,
        FOREIGN KEY (devPatchId) REFERENCES developer_patches(devPatchId) ON DELETE CASCADE,
        FOREIGN KEY (agentPatchId) REFERENCES agent_patches(agentPatchId) ON DELETE CASCADE
    )
    """,
    # PatchCrashResolutionEvaluation table
    """
    CREATE TABLE IF NOT EXISTS patch_crash_resolution_evaluations (
        evalId INTEGER PRIMARY KEY AUTOINCREMENT,
        agentPatchId INTEGER NOT NULL,
        kCacheId INTEGER NOT NULL,
        kGymEvalJobId TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('success', 'error')),
        systemMessage TEXT NOT NULL,
        kGymEvaluation TEXT CHECK(kGymEvaluation IN ('notReproduced', 'reproduced', 'compilationError', 'imageError', 'error')),
        kGymEvaluationResult TEXT,
        FOREIGN KEY (agentPatchId) REFERENCES agent_patches(agentPatchId) ON DELETE CASCADE,
        FOREIGN KEY (kCacheId) REFERENCES kcache(kCacheId) ON DELETE CASCADE
    )
    """,
    # LLMJudgeConfiguration table
    """
    CREATE TABLE IF NOT EXISTS llm_judge_configurations (
        judgeId INTEGER PRIMARY KEY AUTOINCREMENT,
        judgeName TEXT NOT NULL UNIQUE,
        prompt TEXT NOT NULL,
        model TEXT NOT NULL,
        modelConfigName TEXT NOT NULL,
        nVotes INTEGER NOT NULL,
        attrs TEXT NOT NULL
    )
    """,
    # PatchLLMJudgeEvaluation table
    """
    CREATE TABLE IF NOT EXISTS patch_llm_judge_evaluations (
        evalId INTEGER PRIMARY KEY AUTOINCREMENT,
        judgeId INTEGER NOT NULL,
        bugId TEXT NOT NULL,
        devPatchId INTEGER NOT NULL,
        agentPatchId INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('success', 'error')),
        systemMessage TEXT NOT NULL,
        yesCount INTEGER,
        noCount INTEGER,
        errorCount INTEGER,
        llmMessages TEXT,
        FOREIGN KEY (judgeId) REFERENCES llm_judge_configurations(judgeId) ON DELETE CASCADE,
        FOREIGN KEY (bugId) REFERENCES syzbot_bugs(bugId) ON DELETE CASCADE,
        FOREIGN KEY (devPatchId) REFERENCES developer_patches(devPatchId) ON DELETE CASCADE,
        FOREIGN KEY (agentPatchId) REFERENCES agent_patches(agentPatchId) ON DELETE CASCADE,
        UNIQUE(judgeId, devPatchId, agentPatchId)
    )
    """,
    # kenv-base image build state (per-bug, per-base-commit).
    # Mirrors the kcache submit-then-poll pattern for docker-build work that
    # happens locally (not via kGym). Crash-resilient: a row exists before
    # the build starts, so we never lose track of in-flight work.
    """
    CREATE TABLE IF NOT EXISTS kenv_base_image (
        kEnvImageId INTEGER PRIMARY KEY AUTOINCREMENT,
        bugId TEXT NOT NULL,
        baseCommit TEXT NOT NULL CHECK(baseCommit IN ('parentCommit', 'crashCommit')),
        addedTime TEXT NOT NULL,
        commitId TEXT NOT NULL,
        gitUrl TEXT NOT NULL,
        mirrorPath TEXT NOT NULL,
        localImageName TEXT NOT NULL,
        remoteImageName TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending', 'building', 'built', 'pushed', 'error')),
        systemMessage TEXT NOT NULL DEFAULT '',
        builtTime TEXT,
        pushedTime TEXT,
        FOREIGN KEY (bugId) REFERENCES syzbot_bugs(bugId) ON DELETE CASCADE,
        UNIQUE(bugId, baseCommit)
    )
    """,
    # BugDataset table
    """
    CREATE TABLE IF NOT EXISTS bug_datasets (
        datasetId   INTEGER PRIMARY KEY AUTOINCREMENT,
        datasetName TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL,
        addedTime   TEXT NOT NULL,
        attrs       TEXT NOT NULL
    )
    """,
    # BugDatasetMembers junction table
    """
    CREATE TABLE IF NOT EXISTS bug_dataset_members (
        datasetId INTEGER NOT NULL,
        bugId     TEXT NOT NULL,
        PRIMARY KEY (datasetId, bugId),
        FOREIGN KEY (datasetId) REFERENCES bug_datasets(datasetId) ON DELETE CASCADE,
        FOREIGN KEY (bugId) REFERENCES syzbot_bugs(bugId) ON DELETE CASCADE
    )
    """,
]

INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_agent_patches_bugId ON agent_patches(bugId)",
    "CREATE INDEX IF NOT EXISTS idx_agent_patches_agentConfigId ON agent_patches(agentConfigId)",
    "CREATE INDEX IF NOT EXISTS idx_syzbot_bugs_status ON syzbot_bugs(status)",
    "CREATE INDEX IF NOT EXISTS idx_kcache_bugId ON kcache(bugId)",
    "CREATE INDEX IF NOT EXISTS idx_llm_judge_evals_judgeId ON patch_llm_judge_evaluations(judgeId)",
    "CREATE INDEX IF NOT EXISTS idx_llm_judge_evals_agentPatchId ON patch_llm_judge_evaluations(agentPatchId)",
    "CREATE INDEX IF NOT EXISTS idx_bug_dataset_members_datasetId ON bug_dataset_members(datasetId)",
    "CREATE INDEX IF NOT EXISTS idx_kenv_base_image_status ON kenv_base_image(status)",
]
