# kenv-openhands requires Python 3.12+ for OpenHands
# Uses LocalRuntime (no Docker sandbox needed)

ARG KENV_IMAGE

FROM ${KENV_IMAGE}

RUN pip install -U "google-cloud-aiplatform>=1.38"

# Install system dependencies
# tmux is required by OpenHands LocalRuntime
RUN apt update && apt install -y \
    tmux \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package installer)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install OpenHands
COPY ./OpenHands /openhands
WORKDIR /openhands

# Install OpenHands dependencies and package using uv
# This is much faster than poetry and more reliable
RUN uv pip install --system --no-cache -e .

# Copy kenv-invoker
WORKDIR /
COPY ./OpenHands/kenv-invoker.py /kenv-invoker.py
RUN chmod +x /kenv-invoker.py

CMD ["python3", "/kenv-invoker.py"]
