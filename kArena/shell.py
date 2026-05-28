#!/usr/bin/env python3
"""
Launch ptpython --asyncio with kArena fully imported and a live DB connection.

Usage:
    python3 karena-shell.py workspace/shared/karena.db
    python3 karena-shell.py /absolute/path/to/some.db

All logging output is redirected to <db_path>.log (next to the DB file).
The following names are pre-bound in the REPL namespace:
    db          — connected kArenaDB instance
    config      — kArenaConfig (workspaceRoot=workspace/, kGymEndpoint from env KGYM_ENDPOINT)
    Path        — pathlib.Path
    asyncio     — asyncio module
    + every public name from kArena.*
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# ── redirect all logging to a file beside the DB ──────────────────────────────

def _setup_logging(db_path: Path) -> None:
    log_path = db_path.with_suffix(".log")
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path)],
    )
    # keep the root logger from printing to stderr
    logging.getLogger().handlers = [h for h in logging.getLogger().handlers
                                     if not isinstance(h, logging.StreamHandler)
                                     or h.stream not in (sys.stdout, sys.stderr)]
    logging.getLogger("litellm").setLevel(logging.WARNING)
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    print(f"[karena-shell] logging → {log_path}")


# ── build the namespace that ptpython will expose ─────────────────────────────

async def _build_namespace(db_path: Path) -> dict:
    # kArena imports
    from kArena.db import kArenaDB
    from kArena.models import (
        kArenaConfig,
        SyzbotBug, kCache, Patch, AgentPatch, DeveloperPatch,
        AgentConfiguration, PatchLocalizationEvaluation,
        PatchCrashResolutionEvaluation, LLMJudgeConfiguration,
        PatchLLMJudgeEvaluation, BugDataset, kEnvBaseImage,
        PassKCrashResolutionQuery, PassKLLMJudgeQuery, PassKLocalizationQuery,
        PassKCrashResolutionResult, PassKLLMJudgeResult, PassKLocalizationResult,
        BugDifficultyQuery, BugDifficultyData, BugDifficultyResult,
        AverageDollarCostQuery, AverageDollarCostResult,
    )
    from kArena.agent_patch_process import AgentPatchProcess
    from kArena.eval_process import (
        submit_crash_resolution_evaluations,
        populate_crash_resolution_evaluations,
        populate_llm_judge_evaluations,
        populate_localization_evaluations,
    )
    from kArena.crawler import DataPipeline
    from kArena.patch_analyzer import PatchAnalyzer, PatchAnalysis
    from kArena.patch_importer import PatchImporter
    from kArena.kenv_image_manager import KenvImageManager
    from kArena.model_config_manager import ModelConfigManager
    from kArena.evaluation.router_manager import RouterManager
    from kArena.db.core import base_commit_for_status
    from kArena.ops import (
        crawl_bugs, submit_kcache, poll_kcache, build_kenv_images,
        issue_crash_evals, poll_crash_evals,
        issue_llm_judge, issue_localization,
        import_from_hf, export_to_hf,
    )
    from kArena.hf_sync import HFBugExporter

    workspace = Path("workspace")
    kgym_endpoint = os.environ.get("KGYM_ENDPOINT", "")
    config = kArenaConfig(kGymEndpoint=kgym_endpoint, workspaceRoot=workspace)

    db = kArenaDB(str(db_path))
    await db.connect()
    await db.initialize_schema()
    print(f"[karena-shell] connected to {db_path}")

    return dict(
        # core
        db=db, config=config,
        # stdlib helpers
        Path=Path, asyncio=asyncio,
        # models — entities
        kArenaConfig=kArenaConfig,
        SyzbotBug=SyzbotBug, kCache=kCache, Patch=Patch,
        AgentPatch=AgentPatch, DeveloperPatch=DeveloperPatch,
        AgentConfiguration=AgentConfiguration,
        PatchLocalizationEvaluation=PatchLocalizationEvaluation,
        PatchCrashResolutionEvaluation=PatchCrashResolutionEvaluation,
        LLMJudgeConfiguration=LLMJudgeConfiguration,
        PatchLLMJudgeEvaluation=PatchLLMJudgeEvaluation,
        BugDataset=BugDataset, kEnvBaseImage=kEnvBaseImage,
        # models — queries
        PassKCrashResolutionQuery=PassKCrashResolutionQuery,
        PassKLLMJudgeQuery=PassKLLMJudgeQuery,
        PassKLocalizationQuery=PassKLocalizationQuery,
        PassKCrashResolutionResult=PassKCrashResolutionResult,
        PassKLLMJudgeResult=PassKLLMJudgeResult,
        PassKLocalizationResult=PassKLocalizationResult,
        BugDifficultyQuery=BugDifficultyQuery,
        BugDifficultyData=BugDifficultyData,
        BugDifficultyResult=BugDifficultyResult,
        AverageDollarCostQuery=AverageDollarCostQuery,
        AverageDollarCostResult=AverageDollarCostResult,
        # orchestration
        AgentPatchProcess=AgentPatchProcess,
        DataPipeline=DataPipeline,
        PatchAnalyzer=PatchAnalyzer, PatchAnalysis=PatchAnalysis,
        PatchImporter=PatchImporter,
        KenvImageManager=KenvImageManager,
        ModelConfigManager=ModelConfigManager,
        RouterManager=RouterManager,
        # eval functions
        submit_crash_resolution_evaluations=submit_crash_resolution_evaluations,
        populate_crash_resolution_evaluations=populate_crash_resolution_evaluations,
        populate_llm_judge_evaluations=populate_llm_judge_evaluations,
        populate_localization_evaluations=populate_localization_evaluations,
        # db helpers
        base_commit_for_status=base_commit_for_status,
        kArenaDB=kArenaDB,
        # ops task factories
        crawl_bugs=crawl_bugs,
        submit_kcache=submit_kcache,
        poll_kcache=poll_kcache,
        build_kenv_images=build_kenv_images,
        issue_crash_evals=issue_crash_evals,
        poll_crash_evals=poll_crash_evals,
        issue_llm_judge=issue_llm_judge,
        issue_localization=issue_localization,
        import_from_hf=import_from_hf,
        export_to_hf=export_to_hf,
        HFBugExporter=HFBugExporter,
    )


# ── configure ptpython ────────────────────────────────────────────────────────

def _configure_ptpython(repl) -> None:
    repl.vi_mode = False
    repl.prompt_style = "ipython"
    repl.enable_history_search = True
    repl.enable_auto_suggest = True
    repl.show_docstring = True


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="kArena interactive shell")
    parser.add_argument(
        "db",
        nargs="?",
        default="workspace/shared/karena.db",
        help="Path to the kArena SQLite database file (default: workspace/shared/karena.db)",
    )
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    _setup_logging(db_path)

    # build the namespace synchronously via a one-shot event loop, then hand
    # the already-connected db into ptpython's own asyncio loop.
    loop = asyncio.new_event_loop()
    namespace = loop.run_until_complete(_build_namespace(db_path))
    loop.close()

    try:
        from ptpython.repl import embed
    except ImportError:
        sys.exit("ptpython is not installed — run: pip install ptpython")

    history_path = (db_path.parent / "karena.history").resolve()
    print("[karena-shell] entering REPL  (db, config, and all kArena names are available)")
    print(f"[karena-shell] history → {history_path}")
    coro = embed(
        globals=namespace,
        locals=namespace,
        configure=_configure_ptpython,
        return_asyncio_coroutine=True,
        title="kArena shell",
        history_filename=str(history_path),
    )

    repl_loop = asyncio.new_event_loop()
    repl_loop.run_until_complete(coro)
    repl_loop.run_until_complete(namespace["db"].close())
    repl_loop.close()
    print("[karena-shell] DB closed, bye.")


if __name__ == "__main__":
    main()
