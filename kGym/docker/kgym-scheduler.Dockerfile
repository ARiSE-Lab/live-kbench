FROM python:3.11-bookworm AS kscheduler-base

RUN apt update && apt install -y build-essential

RUN pip install debugpy

COPY ./kcore /KBDr/kcore
COPY ./kclient /KBDr/kclient
COPY ./kscheduler /KBDr/kscheduler
WORKDIR /KBDr/kcore
RUN pip install .
WORKDIR /KBDr/kclient
RUN pip install .
WORKDIR /KBDr/kscheduler
RUN pip install .
WORKDIR /root

ENV KSCHEDULER_DB_STR=/root/scheduler-db/scheduler.db
ENV KSCHEDULER_CONFIG=/root/config.json

# Target: release
FROM kscheduler-base AS release
ENTRYPOINT ["/usr/local/bin/python3", "-m", "KBDr.kscheduler"]

# Target: debug
FROM kscheduler-base AS debug
ENTRYPOINT ["/usr/local/bin/python3", "-Xfrozen_modules=off", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--wait-for-client", "-m", "KBDr.kscheduler"]
