# Base image for agent-harness tasks: Node + the openclaw agent CLI.
#
# openclaw requires Node >=24.16.0 <25, or >=26.1.0. The harness launches it
# inside the task container as `openclaw agent exec ...`, so a harness-enabled
# task image should be built FROM this image (or layer this CLI onto it).
FROM node:24-slim

RUN npm install -g --allow-scripts=openclaw,@google/genai,koffi,tree-sitter-bash,protobufjs openclaw@2026.9.3

# DeepSeek provider (OpenAI-compatible) so `deepseek/<model>` resolves.
RUN openclaw plugins install @openclaw/deepseek-provider

# Register the current `deepseek-flash` model (the plugin catalog still carries
# the old `deepseek-v4-flash` name) and pin the provider base URL.
RUN printf '%s\n' \
    '{"models":{"providers":{"deepseek":{"baseUrl":"https://api.deepseek.com","models":[{"id":"deepseek-flash","name":"deepseek-flash"}]}}}}' \
    | openclaw config patch --stdin
