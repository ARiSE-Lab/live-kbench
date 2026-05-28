# kEnv: an environment for agents to fix kernel bugs;
# /KBDr - Libraries
# /linux - code repository
# /root/report.txt, ... - kGym resources
# /KBDr/initialize - Run initalization (pulling resources and checking out)
# /KBDr/run_kernel - Run the patch in /root/linux

# kEnv takes the following environment variables / volumes:
# - KENV_COMMIT_FROM: Literal['crash', 'parent']
# - KENV_SYZBOT_BUG_ID: str
# - KENV_STATEFUL_EDIT: bool (false by default)
# - KENV_KGYM_ENDPOINT: str, kGym API URL (optional) for stateful edit
# - kGym storage config file at /KBDr/storageCfg.json
# - kBench json (SyzbotData and kCacheIndex) file at /KBDr/kBench.json
# - kBench evaluation results (kBenchEvaluationResult) file at /KBDr/kEval.json
# Output space:
# /KBDr/output/{patch.txt, traj.json, log.txt};

ARG KENV_BASE_IMAGE

FROM python:3.13-bookworm AS builder

COPY ./kGym/kcore /KBDr/kcore
COPY ./kGym/kclient /KBDr/kclient

# newer litellm has bug with gemini models;
RUN pip wheel --no-cache-dir --wheel-dir=/wheels \
    unidiff litellm!=1.82.7,!=1.82.8 google-cloud-aiplatform boto3 /KBDr/kcore /KBDr/kclient

FROM ${KENV_BASE_IMAGE}

RUN --mount=target=/var/lib/apt/lists,type=cache,sharing=locked \
    --mount=target=/var/cache/apt,type=cache,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt install -y --no-install-recommends build-essential git universal-ctags

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels \
    unidiff litellm!=1.82.7,!=1.82.8 google-cloud-aiplatform boto3 kgym-core kgym-client \
    && rm -rf /wheels

COPY --chmod=755 ./kenv/initialize /KBDr/initialize
COPY --chmod=755 ./kenv/run_kernel /KBDr/run_kernel
COPY --chmod=755 ./kenv/analyze_patch /KBDr/analyze_patch

CMD ["python3", "/KBDr/analyze_patch"]
