---
name: huggingface-sync
description: Import or export live-kBench kArena bugs and dataset definitions with HuggingFace Hub. Use when Codex is asked to sync, publish, push, pull, import, export, mirror, snapshot, or restore kArena datasets through kArena.hf_sync, HFBugExporter, HFBugImporter, export_to_hf, import_from_hf, or HF_TOKEN.
---

# HuggingFace Sync

## Workflow

First inspect the available API:

```bash
sed -n '1,260p' kArena/hf_sync.py
sed -n '200,280p' kArena/ops.py
```

Use `references/hf-sync-api.md` for row layout, task factory behavior, and examples.

## Decision Rules

- Use `import_from_hf(config, db, repo_id, token=...)` or `export_to_hf(db, repo_id, token=..., private=...)` inside `karena-shell`.
- Use `HFBugImporter` or `HFBugExporter` directly only when writing Python code outside the shell task-factory flow.
- Ask for `hf_repo` if missing; it must look like `owner/repo`.
- Use the `HF_TOKEN` environment fallback when the user does not provide a token.
- For exports, default `private=True` unless the user explicitly asks for a public repo.
- For imports, state that bugs are upserted and dataset definitions are inserted only when the dataset name is new.
- After import, do not imply that kCache or kEnv images were built; suggest the relevant kArena tasks only when the user is bootstrapping a pipeline.

## Shell Examples

```python
t_export = export_to_hf(db, "org/live-kbench-bugs", private=True)
```

```python
t_import = import_from_hf(config, db, "org/live-kbench-bugs")
```

After an import completes and the user wants pipeline readiness:

```python
t_kcache = poll_kcache(config, db)
t_build = build_kenv_images(config, db)
t_devpatch = populate_developer_patches(config, db)
```
