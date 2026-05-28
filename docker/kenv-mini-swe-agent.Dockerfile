ARG KENV_IMAGE

FROM python:3.13-bookworm AS builder

COPY ./mini-swe-agent /mini-swe-agent

RUN pip wheel --no-cache-dir --wheel-dir=/wheels /mini-swe-agent


FROM ${KENV_IMAGE}

COPY --from=builder /wheels /wheels
COPY ./mini-swe-agent/kenv-invoker.py /kenv-invoker.py
RUN pip install --no-cache-dir --no-index --find-links=/wheels \
    mini-swe-agent \
    && rm -rf /wheels

ENV MSWEA_CONFIGURED=1

CMD ["python3", "/kenv-invoker.py"]
