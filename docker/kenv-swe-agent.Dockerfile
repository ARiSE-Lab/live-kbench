ARG KENV_IMAGE

FROM python:3.13-bookworm AS builder

COPY ./SWE-agent /SWE-agent

RUN pip wheel --no-cache-dir --wheel-dir=/wheels /SWE-agent


FROM ${KENV_IMAGE}

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels \
    sweagent \
    && rm -rf /wheels

COPY ./SWE-agent/kenv-invoker.py /kenv-invoker.py

CMD ["python3", "/kenv-invoker.py"]
