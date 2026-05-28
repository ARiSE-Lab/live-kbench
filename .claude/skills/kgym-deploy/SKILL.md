---
name: kgym-deploy
description: Deploy, upgrade, shut down, or troubleshoot kGymSuite for live-kBench in local Docker Compose or GCP/remote multi-server environments. Use when Codex is asked to deploy kGym, start local kGym services, configure deployment/local or deployment/gcp, run kgym.py new-deploy/upgrade/down/config-artifact-reg, prepare kGym storage, or verify scheduler/dashboard/worker services.
---

# kGym Deploy

## Workflow

First determine the target environment from the user request:

- Local development: use Docker Compose with `kGym/deployment/local/compose.yml`.
- GCP or remote multi-server: use `kGym/kgym.py` and a copied deployment directory under `kGym/deployment/<name>`.

Read `references/deployment.md` for concrete commands, config fields, and verification checks.

## Local Deployment

- Work from `kGym/`.
- Ensure userspace images exist in the local storage bucket before expecting VM jobs to run.
- Build with `DEPLOYMENT=local docker compose -f deployment/local/compose.yml --project-directory . build`.
- Start core services before workers: `kmq`, `kscheduler`, `kdashboard`, then `kbuilder`, `kvmmanager`, and optionally `kprebuilder`.
- Verify with `docker compose ps`, scheduler docs at `http://localhost:8000/docs`, and dashboard at `http://localhost:3000`.

## GCP or Remote Deployment

- Create a deployment directory from `deployment/gcp`, then update `config.json`, `kgym-runner.env`, and image tags in `compose.yml`.
- Confirm GCP prerequisites before running commands: Compute VMs, Artifact Registry, GCS bucket, IAM permissions, and authenticated `gcloud`.
- Build and push images before `kgym.py upgrade` or first remote bring-up.
- Run `python kgym.py <deployment> new-deploy`, then `python kgym.py <deployment> config-artifact-reg <artifact-registry-host>`.
- Upload `buildroot.raw` and `bullseye.raw` to the configured GCS bucket under `userspace-images/`.

## Safety

- Do not run `down`, remove volumes, or overwrite deployment configs unless the user asked for that action.
- Do not invent project IDs, bucket names, deployment names, hostnames, or registry hosts.
- For troubleshooting, inspect service logs and config before recommending rebuilds.
