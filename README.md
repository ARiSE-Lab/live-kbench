# Live-kBench: A Live Kernel Crash Resolution Benchmark for All

<a href="https://arxiv.org/abs/2602.02690"><img src="https://img.shields.io/badge/arxiv-2602.02690-red?style=for-the-badge&logo=arxiv&logoColor=white&labelColor=black" alt="arxiv 2602.02690"></a>
<a href="https://huggingface.co/datasets/live-kbench/live-kbench"><img src="https://img.shields.io/badge/🤗%20Dataset-live--kbench-blue?style=for-the-badge" alt="HuggingFace Dataset"></a>

**[ICML 2026] Outrunning LLM Cutoffs: A Live Kernel Crash Resolution Benchmark for All**

*Chenxi Huang, Alex Mathai, Feiyang Yu, Aleksandr Nogikh, Petros Maniatis, Franjo Ivančić, Eugene Wu, Kostis Kaffes, Junfeng Yang, and Baishakhi Ray*

---

Live-kBench is a continuously-updating evaluation framework for benchmarking AI agents on real Linux kernel crash resolution. It crawls fresh bugs from [Syzbot](https://syzkaller.appspot.com), runs agents in a standardized kernel environment, and evaluates patches through three complementary metrics: crash reproduction, LLM-based equivalence judgment, and localization overlap. Because the benchmark ingests new bugs continuously, it resists data contamination—agents achieve up to **25% higher equivalent patch rates on bugs within their training cutoff**, making pre-/post-cutoff performance a diagnostic for contamination.

## System Overview

The repository is organized into four layers:

```
live-kbench/
├── kArena/          # Orchestration, pipeline, database, evaluation
├── kGym/            # Distributed kernel build & crash reproduction
├── kenv/            # Standardized agent container protocol
├── SWE-agent/       # SWE-agent integration (v1d3cfb7)
├── mini-swe-agent/  # mini-SWE-agent integration (v3c2cd4a)
├── OpenHands/       # OpenHands integration (v0.62.0)
└── dashboard/       # Public results web dashboard
```

---

## Components

### kArena

Orchestration layer that ties together Syzbot crawling, agent execution, and all three evaluation pipelines. It exposes a SQLite-backed async database and an interactive `karena-shell` REPL.

**Database tables:**

| Table | Contents |
|---|---|
| `syzbot_bugs` | Crawled bug metadata (title, commit, reproducer, …) |
| `kcache` | Prebuilt kernel cache entries and build verdicts |
| `patches` + `agent_patches` | Agent-generated patches with metadata |
| `developer_patches` | Ground-truth patches extracted from git |
| `agent_configurations` | Agent and model config records |
| `patch_crash_resolution_evaluations` | kGym crash test results per patch |
| `patch_llm_judge_evaluations` | LLM equivalence judgments per patch |
| `patch_localization_evaluations` | File/function IoU scores |
| `kenv_base_images` | Agent Docker image records |
| `datasets` | Named bug-set snapshots |

**Claude Code skill:**

The `karena-ops` skill is available in [Claude Code](https://claude.ai/code) as a task factory code generator for kArena. It generates shell task factory calls (e.g. `crawl_bugs`, `issue_crash_evals`) for use inside `karena-shell`, tailored to the current database and workspace configuration.

**Interactive shell:**

```bash
# Default workspace path
karena-shell workspace/shared/karena.db

# Or specify explicitly
python3 kArena/shell.py /path/to/karena.db
```

All logging goes to `<db_path>.log`. The shell pre-binds these names:

```python
db        # connected kArenaDB (async)
config    # kArenaConfig (workspaceRoot, kGymEndpoint)

# Task factories – each returns an asyncio.Task, cancel with t.cancel()
t = crawl_bugs(config, db)            # scrape Syzbot
t = submit_kcache(config, db)         # submit prebuilt kernel jobs
t = poll_kcache(config, db)           # poll build results
t = build_kenv_images(config, db)     # build agent Docker images
t = issue_crash_evals(config, db)     # submit crash resolution jobs
t = poll_crash_evals(config, db)      # poll crash results
t = issue_llm_judge(db, judge_id=1, workspace_root=Path("workspace"))
t = issue_localization(db)
```

**Workspace layout:**

```
workspace/shared/
├── karena.db                   # SQLite database
├── karena.log                  # Log output
├── agent-configs/              # Per-agent YAML behavior configs
├── model-configs/              # LLM endpoint configs (per agent)
├── judge-model-configs/        # LLM judge model configs
├── repositories/map.json       # Git URL → local mirror path
└── storageCfg.json             # kGym storage backend config
```

**Environment variables:**

| Variable | Default | Description |
|---|---|---|
| `KGYM_ENDPOINT` | `` | kGym API base URL |
| `HF_TOKEN` | — | HuggingFace token for dataset import/export |

---

### kEnv

A standardized Docker-based container protocol that gives every agent a uniform interface: receive bug data as environment variables and volume mounts, produce a patch as output. Full specification: [`docs/kEnv.md`](docs/kEnv.md).

**Two operating modes:**

- **Stateless** (`KENV_STATEFUL_EDIT=false`): Agent works without runtime feedback and submits a final patch.
- **Stateful** (`KENV_STATEFUL_EDIT=true`): Agent can call `/KBDr/run_kernel` at any point to apply its current diff to a live kernel VM and receive crash/success feedback, enabling iterative debugging. This mode yields a **+29% improvement** in crash resolution rate.

**Container inputs:**

| Environment variable | Required | Description |
|---|---|---|
| `KENV_SYZBOT_BUG_ID` | Yes | Syzbot bug identifier (git commit hash) |
| `KENV_COMMIT_FROM` | Yes | `'parent'` (parent of fix) or `'crash'` (crash commit) |
| `KENV_STATEFUL_EDIT` | No | Enable `/KBDr/run_kernel` feedback tool (default: false) |
| `KENV_KGYM_ENDPOINT` | Conditional | kGym API URL (required for stateful mode) |

| Volume mount | Description |
|---|---|
| `/KBDr/storageCfg.json` | kGym storage credentials |
| `/KBDr/kBench.json` | Bug data and kCache index |
| `/KBDr/kEval.json` | Pre-computed evaluation results |
| `/KBDr/mirror` | Local Linux kernel git mirrors |
| `/KBDr/agent-config` | Agent behavior configuration |
| `/KBDr/model-config` | LLM model and API settings |
| `/KBDr/output` | Output directory (patch, trajectory, logs) |

**Container outputs** (all written to `/KBDr/output/`):

| File | Description |
|---|---|
| `patch.txt` | Unified diff of the agent's fix |
| `traj.json` | Full agent trajectory (actions and observations) |
| `log.txt` | Execution stdout/stderr |

**Execution flow:**

1. `/KBDr/initialize` — clone kernel from local mirror, checkout base commit, write `report.txt` and `reproducer.txt`
2. Agent invoker — construct problem statement from report + reproducer, run agent in `/linux`, extract patch

**Supported agent images:**

```bash
# Build base image
docker build -f docker/kenv.Dockerfile -t kenv:latest .

# Build agent images
docker build -f docker/kenv-swe-agent.Dockerfile       -t kenv-swe-agent:latest .
docker build -f docker/kenv-mini-swe-agent.Dockerfile  -t kenv-mini-swe-agent:latest .
docker build -f docker/kenv-open-hands.Dockerfile      -t kenv-open-hands:latest .
```

**Run a single agent manually:**

```bash
docker run --rm \
  -e KENV_COMMIT_FROM=parent \
  -e KENV_SYZBOT_BUG_ID=c416b595bd3c7332a8b75474a6cc3c854ad85b37 \
  -e KENV_STATEFUL_EDIT=false \
  -v $(pwd)/storageCfg.json:/KBDr/storageCfg.json \
  -v $(pwd)/kBench.json:/KBDr/kBench.json \
  -v $(pwd)/kEval.json:/KBDr/kEval.json \
  -v $(pwd)/kGym/kclient/repositories:/KBDr/mirror \
  -v $(pwd)/workspace/shared/agent-configs/mini-swe-agent-c-unlimited:/KBDr/agent-config \
  -v $(pwd)/workspace/shared/model-configs/mini-swe-agent/gemini-flash:/KBDr/model-config \
  -v $(pwd)/workspace/output:/KBDr/output \
  kenv-mini-swe-agent:latest
```

**Adding a new agent:** create `docker/kenv-{name}.Dockerfile` extending `kenv:latest`, write a `kenv-invoker.py` that initializes via `/KBDr/initialize`, runs the agent in `/linux`, and writes `patch.txt` / `traj.json` / `log.txt` to `/KBDr/output/`. See [`docs/kEnv.md`](docs/kEnv.md) for the full protocol specification.

---

### Dashboard

Coming soon.

---

### Evaluation Pipeline

Three metrics are computed for each agent patch:

**1. Crash Resolution (kGym)**

Submits the patched kernel to kGym, runs the crash reproducer across multiple VM instances, and records whether the crash is suppressed.

```python
t = issue_crash_evals(config, db)   # submit jobs
t = poll_crash_evals(config, db)    # collect results
```

Possible verdicts: `notReproduced`, `reproduced`, `compilationError`, `timeout`.

**2. LLM Judge (Patch Equivalence)**

An LLM compares the agent patch against the developer patch and votes `equivalent` or `discrepant` across `nVotes` independent rounds (default: 5). Majority vote is the final verdict.

```python
t = issue_llm_judge(db, judge_id=1, workspace_root=Path("workspace"))
```

Configure judges via the `llm_judge_configurations` table. Model configs live in `workspace/shared/judge-model-configs/`. The judge prompt receives `{devPatch}`, `{devPatchMessage}`, and `{agentPatch}` and returns JSON with a `"verdict"` field (`"equivalent"` or `"discrepant"`).

**3. Localization (File / Function IoU)**

Computes intersection-over-union between the set of files (and functions) modified by the agent versus the developer. Requires no execution.

```python
t = issue_localization(db)
```

---

### Data Pipeline

The full pipeline from raw Syzbot data to evaluated results:

```
1. crawl_bugs          → syzbot_bugs table
2. submit_kcache        → prebuilt kernel cache (kGym kbuilder)
3. poll_kcache          → kcache verdicts
4. build_kenv_images    → Docker images for each agent
5. AgentPatchProcess    → run agents, store patches
6. issue_crash_evals    → submit patched kernels to kGym
7. poll_crash_evals     → crash resolution verdicts
8. issue_llm_judge      → equivalence votes
9. issue_localization   → file/function IoU
```

---

### HuggingFace Dataset

The benchmark dataset (`kBenchSyz`) is published on the HuggingFace Hub at [live-kbench/live-kbench](https://huggingface.co/datasets/live-kbench/live-kbench) and can be imported/exported via `hf_sync.py`:

```python
from kArena.hf_sync import export_to_hf, import_from_hf

# Export current DB snapshot
await export_to_hf(db, repo_id="live-kbench/live-kbench", split="kb")

# Import into a fresh DB
await import_from_hf(db, repo_id="live-kbench/live-kbench", split="kb")
```

---

### kGymSuite

<a href="https://arxiv.org/abs/2504.20412"><img src="https://img.shields.io/badge/arxiv-2504.20412-red?style=flat-square&logo=arxiv&logoColor=white&labelColor=black" alt="arxiv 2504.20412"></a>

A distributed microservices platform that compiles Linux kernels, applies patches, and reproduces crashes in isolated VMs. Full documentation: [`kGym/README.md`](kGym/README.md) and [`kGym/DEPLOY.md`](kGym/DEPLOY.md).

**Services:**

| Service | Role |
|---|---|
| `kscheduler` | FastAPI job scheduler; manages job lifecycle and worker coordination |
| `kmq` | RabbitMQ message broker for worker communication |
| `kbuilder` | Compiles Linux kernels from a git commit, applies patches, produces VM images |
| `kvmmanager` | Runs crash reproducers in isolated QEMU or GCE VMs via syzkaller |
| `kprebuilder` | Validates patch compilability against cached kernel builds (~2–3 s per patch) |
| `kdashboard` | Next.js monitoring interface |
| `kclient` | Python client library and IPython shell (`kclient` command) |

**Quick start (local):**

```bash
cd kGym
docker compose -f deployment/local/compose.yml --project-directory . build
docker compose -f deployment/local/compose.yml up -d kmq kscheduler kdashboard
docker compose -f deployment/local/compose.yml up -d kbuilder kvmmanager
```

Configuration lives in `deployment/local/config.json` (storage, workers, servers) and `deployment/local/kgym-runner.env` (RabbitMQ credentials). See [`kGym/DEPLOY.md`](kGym/DEPLOY.md) for multi-server GCP deployment.

**Reproducibility note:** 238 of 279 kBenchSyz bugs reproduce on QEMU with `ninstance=5`. GCP VMs match syzbot's original fuzzing environment more closely. See [`kGym/misc/reproducible-bugs-on-qemu.json`](kGym/misc/reproducible-bugs-on-qemu.json).

---

## Installation

Requires Python ≥ 3.13, [uv](https://github.com/astral-sh/uv), and Docker.

```bash
git clone https://github.com/ARiSE-Lab/live-kbench.git
cd live-kbench
uv sync
```

This installs the `karena`, `kgym-client`, and `kgym-core` workspace packages.

## Running the Full Benchmark

```bash
# 1. Start kGym services
cd kGym
docker compose -f deployment/local/compose.yml up -d

# 2. Open the orchestration shell
cd ..
karena-shell workspace/shared/karena.db

# 3. Inside the shell – run the pipeline
t = crawl_bugs(config, db)
await t

t = submit_kcache(config, db, status='fixed')
await t

t = build_kenv_images(config, db)
await t

# (Run agents via AgentPatchProcess or Docker directly, then:)

t = issue_crash_evals(config, db)
t = poll_crash_evals(config, db)   # runs until cancelled
t = issue_llm_judge(db, judge_id=1, workspace_root=Path("workspace"))
t = issue_localization(db)
```

## Key Results

| Metric | Value |
|---|---|
| Bugs in kBenchSyz | 534 curated Linux kernel bugs |
| Reproducible on QEMU (`ninstance=5`) | 238 / 279 |
| Crash resolution rate (first attempt) | 74% |
| Equivalent patch rate | ~20% |
| Improvement with stateful feedback | +29% crash resolution |
| Pre-cutoff vs post-cutoff gap (equiv. patch) | up to +25% |

## Citation

If you use this artifact, please cite:

```bibtex
@misc{huang2026outrunning,
  title         = {Outrunning LLM Cutoffs: A Live Kernel Crash Resolution Benchmark for All},
  author        = {Chenxi Huang and Alex Mathai and Feiyang Yu and Aleksandr Nogikh and
                   Petros Maniatis and Franjo Ivan\v{c}i\'{c} and Eugene Wu and
                   Kostis Kaffes and Junfeng Yang and Baishakhi Ray},
  year          = {2026},
  eprint        = {2602.02690},
  archivePrefix = {arXiv},
  primaryClass  = {cs.SE},
  url           = {https://arxiv.org/abs/2602.02690},
}
```

Related work:

```bibtex
@misc{mathai2025crashfixer,
  title         = {CrashFixer: A crash resolution agent for the Linux kernel},
  author        = {Alex Mathai and Chenxi Huang and Suwei Ma and Jihwan Kim and
                   Hailie Mitchell and Aleksandr Nogikh and Petros Maniatis and
                   Franjo Ivan\v{c}i\'{c} and Junfeng Yang and Baishakhi Ray},
  year          = {2025},
  eprint        = {2504.20412},
  archivePrefix = {arXiv},
  primaryClass  = {cs.SE},
  url           = {https://arxiv.org/abs/2504.20412},
}

@misc{mathai2024kgym,
  title         = {KGym: A Platform and Dataset to Benchmark Large Language Models on Linux Kernel Crash Resolution},
  author        = {Alex Mathai and Chenxi Huang and Petros Maniatis and Aleksandr Nogikh and
                   Franjo Ivan\v{c}i\'{c} and Junfeng Yang and Baishakhi Ray},
  year          = {2024},
  eprint        = {2407.02680},
  archivePrefix = {arXiv},
  primaryClass  = {cs.SE},
  url           = {https://arxiv.org/abs/2407.02680},
}
```

## Contact

Open an issue or email [Chenxi Huang](mailto:chenxi@cs.columbia.edu).
