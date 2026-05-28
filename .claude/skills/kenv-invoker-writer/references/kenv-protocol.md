# kEnv Protocol Reference

## Source Files

- Protocol docs: `docs/kEnv.md`
- Base scripts: `kenv/initialize`, `kenv/run_kernel`
- Existing invokers: `SWE-agent/kenv-invoker.py`, `mini-swe-agent/kenv-invoker.py`, `OpenHands/kenv-invoker.py`
- Dockerfiles: `docker/kenv.Dockerfile`, `docker/kenv-*.Dockerfile`

## Required Inputs

Environment:

- `KENV_SYZBOT_BUG_ID`: Syzbot bug identifier.
- `KENV_COMMIT_FROM`: `parent` or `crash`.
- `KENV_STATEFUL_EDIT`: optional boolean; enables `/KBDr/run_kernel`.
- `KENV_KGYM_ENDPOINT`: required when stateful editing is enabled.

Mounts:

- `/KBDr/storageCfg.json`
- `/KBDr/kBench.json`
- `/KBDr/kEval.json`
- `/KBDr/mirror`
- `/KBDr/agent-config`
- `/KBDr/model-config`
- `/KBDr/output`

## Required Flow

1. Run `/KBDr/initialize`.
2. Read `/root/report.txt` and `/root/reproducer.txt`.
3. Construct a task containing the crash report and reproducer.
4. Merge external agent config and model config with invoker-required internal settings.
5. Run the agent in `/linux`.
6. Capture stdout/stderr to `/KBDr/output/log.txt`.
7. Write final patch to `/KBDr/output/patch.txt`.
8. Write trajectory or structured run metadata to `/KBDr/output/traj.json`.

## Output Contract

- `patch.txt`: unified diff for the proposed fix.
- `traj.json`: full trajectory if the agent provides one; otherwise write a JSON object containing command, exit code, timestamps, and artifact paths.
- `log.txt`: combined stdout/stderr from the agent process and invoker diagnostics.

## Existing Patterns

SWE-agent:

- Builds an internal config with local preexisting repo `/linux`.
- Runs `sweagent run --config <agent> --config <model> --config <internal>`.
- Extracts `model_patch` from the SWE-agent `.pred` file.

mini-swe-agent:

- Loads YAML agent config and model config.
- Sets `env.cwd` to `/linux`.
- Runs `mini --yolo --config <internal> --output <traj> --task <task>`.
- Extracts patch with `git add -A && git diff --cached`.

## Dockerfile Pattern

Use the repo's current agent Dockerfile style:

```Dockerfile
FROM kenv:latest

# install/copy agent dependencies
COPY ./<agent-dir>/kenv-invoker.py /kenv-invoker.py
RUN chmod +x /kenv-invoker.py
ENTRYPOINT ["python3", "/kenv-invoker.py"]
```

## Common Failure Modes

- Missing `/KBDr/output` files even when the agent fails; write empty patch plus error metadata when needed.
- Running from the wrong cwd; the Linux repo is `/linux`.
- Treating `/KBDr/run_kernel` as mandatory; it is available only in stateful mode.
- Losing model credentials by overwriting instead of merging `/KBDr/model-config`.
- Producing a patch from untracked files only; stage or include untracked files before diff extraction when using git.
