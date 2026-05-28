# kGym Deployment Reference

## Source Files

- Deployment guide: `kGym/DEPLOY.md`
- CLI: `kGym/kgym.py`
- Local template: `kGym/deployment/local/`
- GCP template: `kGym/deployment/gcp/`

## Local Deployment

Work from `kGym/`.

Prepare local storage:

```bash
mkdir -p deployment/local/bucket/userspace-images
mkdir -p deployment/local/bucket/jobs
cp buildroot.raw deployment/local/bucket/userspace-images/
cp bullseye.raw deployment/local/bucket/userspace-images/
```

Build:

```bash
DEPLOYMENT=local docker compose -f deployment/local/compose.yml --project-directory . build
```

Start:

```bash
DEPLOYMENT=local docker compose -f deployment/local/compose.yml up -d kmq kscheduler kdashboard
DEPLOYMENT=local docker compose -f deployment/local/compose.yml up -d kbuilder kvmmanager kprebuilder
```

Verify:

```bash
DEPLOYMENT=local docker compose -f deployment/local/compose.yml ps
DEPLOYMENT=local docker compose -f deployment/local/compose.yml logs -f kscheduler
```

Endpoints:

- Scheduler API: `http://localhost:8000/docs`
- Dashboard: `http://localhost:3000`

Stop:

```bash
DEPLOYMENT=local docker compose -f deployment/local/compose.yml down
```

## GCP or Remote Deployment

Create a deployment:

```bash
cd kGym/deployment
cp -r gcp <deployment>
```

Configure `deployment/<deployment>/config.json`:

- `deploymentName`: deployment name.
- `allowedOrigins`: dashboard/API origins.
- `storage.providerType`: `gcs`.
- `storage.providerConfig.bucketName`: GCS bucket.
- `dbPath`: scheduler DB path on main server.
- `kGymAPIEndpoint`: public API URL if available.
- `servers`: logical names to SSH user and hostname.
- `mainServer`: server running core services.
- `services`: service placement.

Configure `deployment/<deployment>/kgym-runner.env`:

```bash
KGYM_CONN_URL=amqp://kbdr:<password>@<main-host>:5672/?heartbeat=60
```

Update `deployment/<deployment>/compose.yml` image tags to the target Artifact Registry.

Build and push:

```bash
DEPLOYMENT=<deployment> docker compose -f deployment/<deployment>/compose.yml --project-directory . build
gcloud auth configure-docker <artifact-registry-host>
DEPLOYMENT=<deployment> docker compose -f deployment/<deployment>/compose.yml push
```

Deploy:

```bash
python kgym.py <deployment> new-deploy
python kgym.py <deployment> config-artifact-reg <artifact-registry-host>
python kgym.py <deployment> upgrade
```

Upload userspace images:

```bash
gsutil cp buildroot.raw gs://<bucket>/userspace-images/
gsutil cp bullseye.raw gs://<bucket>/userspace-images/
```

Verify on the main server:

```bash
docker ps
docker logs kgym-scheduler
curl http://localhost:8000/docs
```

## Common Operations

Upgrade:

```bash
DEPLOYMENT=<deployment> docker compose -f deployment/<deployment>/compose.yml --project-directory . build
DEPLOYMENT=<deployment> docker compose -f deployment/<deployment>/compose.yml push
python kgym.py <deployment> upgrade
```

Remote shutdown:

```bash
python kgym.py <deployment> down
```

Local logs:

```bash
DEPLOYMENT=local docker compose -f deployment/local/compose.yml logs -f
DEPLOYMENT=local docker compose -f deployment/local/compose.yml logs --tail=100 kvmmanager
```

Scale local workers:

```bash
DEPLOYMENT=local docker compose -f deployment/local/compose.yml up -d --scale kvmmanager=10
```

## Troubleshooting

- Services fail to start: check Docker daemon and `docker compose config`.
- Workers idle: verify `KGYM_CONN_URL`, `kmq`, and worker logs.
- kbuilder fails: check privileged mode, `/dev`, disk space, and job logs.
- QEMU/KVM fails: verify `/dev/kvm`, CPU virtualization, and container device mapping.
- GCS fails: verify VM service account has storage permissions.
- Local storage fails: verify `/mnt/bucket` ownership inside the container mapping.
