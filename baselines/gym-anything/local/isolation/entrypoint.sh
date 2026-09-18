#!/bin/bash
set -euo pipefail
dockerd --host=unix:///var/run/docker.sock --storage-driver=overlay2 > /tmp/dockerd.log 2>&1 &
for i in {1..120}; do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 1
done
docker info >/dev/null
docker network create gym-anything-local >/dev/null
if [[ -f /opt/desktop.tar ]]; then docker load -i /opt/desktop.tar; fi
chmod 666 /dev/kvm
install -d -o 1015 -g 1015 /data1/zangyihe/EvaluationClaw/baselines/gym-anything/local/q/1
exec runuser -u experiment --preserve-environment -- "$@"
