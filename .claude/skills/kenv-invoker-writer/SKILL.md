---
name: kenv-invoker-writer
description: Write or update live-kBench kEnv agent integrations. Use when Codex needs to create a kenv-invoker.py, adapt an agent to the kEnv protocol, add a docker/kenv-*.Dockerfile, debug kEnv container inputs or outputs, or ensure an agent writes patch.txt, traj.json, and log.txt for live-kBench evaluation.
---

# kEnv Invoker Writer

## Workflow

First inspect the repo state before editing:

```bash
rg -n "kenv-invoker|KENV_|/KBDr|patch.txt|traj.json|log.txt" .
sed -n '1,260p' docs/kEnv.md
```

Use `references/kenv-protocol.md` for the protocol contract and existing examples.

## Implementation Rules

- Create or update the agent invoker at `<agent-dir>/kenv-invoker.py`.
- Create or update `docker/kenv-<agent-name>.Dockerfile` only when the agent image does not already exist.
- Extend `kenv:latest` or the repo's current kEnv base image pattern.
- Treat `/KBDr/agent-config` as the agent behavior config and `/KBDr/model-config` as the model/API config.
- Run `/KBDr/initialize` before invoking the agent.
- Run the agent against the preexisting Linux checkout at `/linux`.
- Build the task text from `/root/report.txt` and `/root/reproducer.txt`.
- Preserve `KENV_STATEFUL_EDIT=true` support by letting the agent call `/KBDr/run_kernel`; do not hide or delete that tool.
- Always write these outputs under `/KBDr/output/`: `patch.txt`, `traj.json`, and `log.txt`.
- Derive `patch.txt` from the agent's native prediction artifact when available; otherwise use `git diff` from `/linux`.

## Checks

After editing, run the smallest relevant validation:

```bash
python3 -m py_compile <agent-dir>/kenv-invoker.py
docker build -f docker/kenv-<agent-name>.Dockerfile -t kenv-<agent-name>:latest .
```

For a container smoke test, mount the required kEnv inputs listed in the reference and confirm `/KBDr/output/patch.txt`, `/KBDr/output/traj.json`, and `/KBDr/output/log.txt` exist after the run.
