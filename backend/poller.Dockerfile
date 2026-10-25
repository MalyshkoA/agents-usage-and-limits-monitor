# Server-side limits poller: Codex CLI + Claude Code / Agent SDK + the Python bridge client.
# Claude Code needs Node 22+, so the image starts from Node and adds Python.
FROM node:22-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NPM_CONFIG_UPDATE_NOTIFIER=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pinned CLIs: `codex` (app-server + device login) and `claude` (setup-token login).
# Codex ships its native binary as an aliased optional dependency, which a global
# npm install can skip; install the one for this architecture explicitly.
ARG CODEX_VERSION=0.161.0
RUN arch="$(dpkg --print-architecture | sed 's/amd64/x64/')" \
    && npm install -g --no-audit --no-fund \
        "@openai/codex@${CODEX_VERSION}" \
        "@openai/codex-linux-${arch}@npm:@openai/codex@${CODEX_VERSION}-linux-${arch}" \
        @anthropic-ai/claude-code@2.1.292 \
    && codex --version && claude --version \
    && npm cache clean --force

WORKDIR /opt/claude_usage
COPY claude_usage/package.json claude_usage/collect.mjs ./
RUN npm install --omit=dev --no-audit --no-fund && npm cache clean --force

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir .

# Sessions and state live in the /data volume; HOME and CODEX_HOME point there
# so the read-only root filesystem never needs writes.
RUN mkdir -p /data/home /data/codex && chown -R node:node /data
ENV PATH=/opt/venv/bin:$PATH \
    HOME=/data/home \
    CODEX_HOME=/data/codex \
    QWB_POLLER_DATA_DIR=/data

USER node
CMD ["quota-watch-poller", "run"]
