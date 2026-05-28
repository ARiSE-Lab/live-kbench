---
name: karena-deploy
description: Generate ready-to-paste kArena shell task factory snippets for live-kBench operations. Use when Codex is asked to start, deploy, run, poll, bootstrap, sync, or manage kArena workflows in karena-shell, including crawl_bugs, submit_kcache, poll_kcache, build_kenv_images, crash evals, LLM judge evals, localization, developer patch population, and HuggingFace import/export tasks.
---

# kArena Deploy

## Workflow

Generate code for the `karena-shell` ptpython REPL. The shell already provides `config`, `db`, `Path`, and the task factories; do not output imports or setup boilerplate.

Read `references/task-factories.md` when a request mentions a specific operation, pipeline, or missing parameter.

## Output Rules

- Output only the minimal ready-to-paste Python snippet unless the user asks for explanation.
- Assign tasks to descriptive variables when starting more than one operation.
- Use `await t` only for one-shot operations when the user asks to wait for completion.
- For polling loops, return task assignments and mention cancellation only if useful: `t.cancel()`.
- Ask only for required missing values that cannot be inferred, especially `judge_id` for LLM judge and `agent_config_id` when the user wants one specific agent configuration.
- Default `status` to `"fixed"` unless the user says open bugs.
- Default `interval` to the factory default unless the user gives a frequency.
- Default `workspace_root` to `Path("workspace")`.

## Common Snippets

Full evaluation after patches exist:

```python
t_crash_issue = issue_crash_evals(config, db, agent_config_id=74)
t_crash_poll = poll_crash_evals(config, db)
t_judge = issue_llm_judge(db, judge_id=6, workspace_root=Path("workspace"))
t_loc = issue_localization(db)
```

Bootstrap from Syzbot:

```python
t_crawl = crawl_bugs(config, db)
t_submit = submit_kcache(config, db)
t_kcache = poll_kcache(config, db)
t_build = build_kenv_images(config, db)
t_devpatch = populate_developer_patches(config, db)
```

Bootstrap from HuggingFace:

```python
t_import = import_from_hf(config, db, "org/live-kbench-bugs")
```
