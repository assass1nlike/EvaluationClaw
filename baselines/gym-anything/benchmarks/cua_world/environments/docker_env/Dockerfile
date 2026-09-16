FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb x11-apps x11-utils xdotool fluxbox pulseaudio ffmpeg xterm x11vnc \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Copy helper scripts
COPY scripts/start_app.sh /workspace/start_app.sh
COPY scripts/reset_env.sh /workspace/reset_env.sh
RUN chmod +x /workspace/*.sh

# Default workdir contains scripts; runtime will docker exec into this container
