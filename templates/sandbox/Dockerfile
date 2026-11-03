# One image for both sandbox containers: the agent (Claude Code + our MCP server) and the egress proxy.
# Nothing from the kit is copied in: the kit is mounted read-only at /opt/rak at run time, so the image never holds
# a stale policy, and the agent cannot change the one it runs under.
FROM node:22-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.316
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-yaml git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force \
 && claude --version \
 && git config --system safe.directory /work

# The agent runs as an unprivileged user whose home is a fresh tmpfs on every run (compose.yaml).
RUN useradd --create-home --uid 10001 --shell /bin/bash runner \
 && mkdir /pipe && chown 10002:10001 /pipe && chmod 0750 /pipe \
 && mkdir -p /work && chown 10001:10001 /work
# /pipe: the audit FIFO's folder (audit_collector.py). /work: owned by the agent, so a fresh per-run volume mounted
# there (copy mode) starts writable.
USER runner
ENV HOME=/home/runner \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    DISABLE_AUTOUPDATER=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
