# kArena Task Factory Reference

Use inside `karena-shell`. The REPL already has `config`, `db`, task factories, and `Path` available.

## Factories

```python
t = crawl_bugs(config, db)
```

One-shot Syzbot crawl.

```python
t = submit_kcache(config, db)
t = submit_kcache(config, db, status="open")
t = submit_kcache(config, db, n_batch=1, ninstance=5, userspace_image_name="buildroot.raw")
```

One-shot kCache submission. Default status is `"fixed"`.

```python
t = poll_kcache(config, db)
t = poll_kcache(config, db, interval=120)
```

Loop that fills kCache verdicts.

```python
t = build_kenv_images(config, db)
t = build_kenv_images(config, db, status="open")
t = build_kenv_images(config, db, push=True)
t = build_kenv_images(config, db, push=False)
```

Loop that submits kenv-base rows and builds pending images. Default `push=None` auto-detects from `config.dockerPrefix`.

```python
t = populate_developer_patches(config, db)
```

Loop that analyzes developer patches after kenv-base images are built.

```python
t = issue_crash_evals(config, db)
t = issue_crash_evals(config, db, agent_config_id=74)
t = issue_crash_evals(config, db, agent_config_id=74, excl_queue=False)
```

Loop that submits crash-resolution eval jobs. `excl_queue=True` by default.

```python
t = poll_crash_evals(config, db)
t = poll_crash_evals(config, db, interval=60)
```

Loop that polls crash-resolution jobs.

```python
t = issue_llm_judge(db, judge_id=6, workspace_root=Path("workspace"))
t = issue_llm_judge(db, judge_id=6, workspace_root=Path("workspace"), interval=120)
```

Loop that runs LLM judge evaluation. `judge_id` is required.

```python
t = issue_localization(db)
t = issue_localization(db, interval=60)
```

Loop that computes localization IoU.

```python
t = import_from_hf(config, db, "org/live-kbench-bugs")
t = export_to_hf(db, "org/live-kbench-bugs", private=True)
```

One-shot HuggingFace import/export task factories.

## Task Control

```python
t.cancel()
t.done()
asyncio.all_tasks()
```

## Common Combinations

Full evaluation after patch generation:

```python
t_crash_issue = issue_crash_evals(config, db, agent_config_id=74)
t_crash_poll = poll_crash_evals(config, db)
t_judge = issue_llm_judge(db, judge_id=6, workspace_root=Path("workspace"))
t_loc = issue_localization(db)
```

Bootstrap from crawl:

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

After `t_import` completes:

```python
t_kcache = poll_kcache(config, db)
t_build = build_kenv_images(config, db)
t_devpatch = populate_developer_patches(config, db)
```
