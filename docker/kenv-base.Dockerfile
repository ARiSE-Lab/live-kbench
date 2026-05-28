# Dockerfile for embedding a kernel checkout
# Usage:
#   DOCKER_BUILDKIT=1 docker build -f docker/kenv-base.Dockerfile \
#     --build-arg GIT_URL=https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git \
#     --build-arg MIRROR_PATH=workspace/shared/repositories/abc123.git \
#     --build-arg COMMIT_ID=abc123def456 \
#     --build-arg SYZBOT_BUG_ID=bug_id_here \
#     --build-arg BASE_COMMIT=parentCommit \
#     -t kenv-base-bugid-parent-commit:latest .
#
# Note: MIRROR_PATH should be relative to build context
# Note: BASE_COMMIT should be 'parentCommit' or 'crashCommit'
# Note: Requires BuildKit (DOCKER_BUILDKIT=1)

FROM python:3.13-bookworm

ARG GIT_URL
ARG MIRROR_PATH
ARG COMMIT_ID
ARG SYZBOT_BUG_ID
ARG BASE_COMMIT

# Install git
RUN apt-get update && \
    apt-get install -y git

# Setup kernel checkout with fallback to remote
# Mount mirror without copying it as a layer
RUN --mount=type=bind,source=${MIRROR_PATH},target=/linux-mirror.git \
    git config --global --add safe.directory /linux-mirror.git && \
    mkdir /linux && \
    cd /linux && \
    git init && \
    git remote add origin /linux-mirror.git && \
    (git fetch origin ${COMMIT_ID} || \
     (git remote set-url origin ${GIT_URL} && git fetch origin ${COMMIT_ID})) && \
    git checkout ${COMMIT_ID} && \
    git remote set-url origin ${GIT_URL} && \
    git config --global --add safe.directory /linux

WORKDIR /linux

LABEL git.url="${GIT_URL}"
LABEL git.commit="${COMMIT_ID}"
LABEL syzbot.bug_id="${SYZBOT_BUG_ID}"
LABEL base.commit="${BASE_COMMIT}"
