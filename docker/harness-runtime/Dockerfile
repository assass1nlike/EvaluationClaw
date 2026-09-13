FROM node:24-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip ca-certificates git build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g \
    @openai/codex@0.154.0 \
    @anthropic-ai/claude-code@2.1.270 \
    openclaw@2026.9.4
COPY scripts/demo_harness.py /usr/local/bin/evalclaw-demo-harness.py
WORKDIR /workspace
