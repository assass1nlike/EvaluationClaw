FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    docker.io docker-compose-v2 git curl ca-certificates openssh-client iproute2 procps \
    jq file unzip xz-utils sudo python3 && rm -rf /var/lib/apt/lists/*
RUN groupadd -g 1015 experiment && groupadd -g 109 kvm && \
    useradd -m -u 1015 -g 1015 -G docker,kvm -d /home/zangyihe -s /bin/bash experiment && \
    printf 'experiment ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/experiment
COPY entrypoint.sh /usr/local/bin/seed-entrypoint
ENTRYPOINT ["/usr/local/bin/seed-entrypoint"]
