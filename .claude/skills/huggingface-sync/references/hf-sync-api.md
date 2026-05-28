# HuggingFace Sync API Reference

## Source Files

- `kArena/hf_sync.py`
- `kArena/ops.py`
- `README.md` HuggingFace Dataset section

## Repository Layout

The HuggingFace dataset repo has two dataset configs:

- `bugs`: one row per `SyzbotBug`; `syzbotData` is serialized JSON.
- `datasets`: one row per `BugDataset`; `bugIds` and `attrs` are serialized JSON strings.

## Export

Direct API:

```python
from kArena.hf_sync import HFBugExporter

exporter = HFBugExporter(db)
await exporter.export("org/live-kbench-bugs", token=None, private=True)
```

Shell task factory:

```python
t_export = export_to_hf(db, "org/live-kbench-bugs", private=True)
```

Behavior:

- Exports all bugs from `db.get_all_bugs()`.
- Exports all dataset definitions from `db.get_all_datasets()`.
- Uses HuggingFace `datasets.Dataset.from_list(...).push_to_hub(...)`.
- `token=None` falls back to the HuggingFace environment behavior, usually `HF_TOKEN`.

## Import

Direct API:

```python
from kArena.hf_sync import HFBugImporter

importer = HFBugImporter(db)
new_bug_ids = await importer.import_bugs("org/live-kbench-bugs")
new_dataset_names = await importer.import_datasets("org/live-kbench-bugs")
```

Shell task factory:

```python
t_import = import_from_hf(config, db, "org/live-kbench-bugs")
```

Behavior:

- Loads `bugs` and `datasets` configs via `datasets.load_dataset(...)`.
- Inserts or updates bugs through existing DB upsert behavior.
- Inserts dataset definitions only when `datasetName` does not already exist locally.
- Does not submit kCache builds.
- Does not build kEnv images.

## Required Decisions

- `hf_repo`: required, in `owner/repo` form.
- `token`: optional for public repos; required for private repos unless `HF_TOKEN` is set.
- `private`: export-only; default to `True` unless the user wants public publishing.

## Post-Import Pipeline

If the user wants imported data to become evaluation-ready:

```python
t_kcache = poll_kcache(config, db)
t_build = build_kenv_images(config, db)
t_devpatch = populate_developer_patches(config, db)
```

Use `submit_kcache(config, db)` as well when no kCache build jobs have been submitted for the imported bugs.
