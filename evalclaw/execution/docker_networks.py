"""Allocate small isolated subnets from an explicitly configured local pool."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import subprocess
from pathlib import Path


def inspect_networks(docker_args, ids):
    if not ids:
        return []
    result = subprocess.run([*docker_args, "network", "inspect", *ids],
                            capture_output=True, text=True, timeout=30)
    networks = json.loads(result.stdout or "[]")
    if result.returncode:
        # Concurrent cleanup can remove networks after listing. Ignore only
        # IDs proved absent; permission/daemon errors on live IDs still fail.
        live = subprocess.check_output([*docker_args, "network", "ls", "-q", "--no-trunc"],
                                       text=True, timeout=30).split()
        inspected = {n["Id"] for n in networks}
        missing_live = [cid for cid in live if cid not in inspected
                        and any(cid.startswith(requested) for requested in ids)]
        if missing_live:
            result.check_returncode()
    return networks


def create_network(docker_args, args, pool, **kwargs):
    import fcntl

    network_pool = ipaddress.IPv4Network(pool)
    if network_pool.prefixlen > 27:
        raise ValueError("Docker network pool must contain at least one /27 subnet.")
    key = hashlib.sha256(str(network_pool).encode()).hexdigest()[:16]
    lock_path = Path("/tmp") / f"evalclaw-network-{os.getuid()}-{key}.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ids = subprocess.check_output([*docker_args, "network", "ls", "-q"], text=True, timeout=30).split()
        networks = inspect_networks(docker_args, ids)
        occupied = [ipaddress.ip_network(c["Subnet"])
                    for n in networks for c in n.get("IPAM", {}).get("Config") or []
                    if c.get("Subnet") and ":" not in c["Subnet"]]
        routes = json.loads(subprocess.check_output(["ip", "-j", "-4", "route", "show"], text=True, timeout=30))
        occupied.extend(ipaddress.ip_network(r["dst"], strict=False) for r in routes
                        if r.get("dst") and r["dst"] != "default")
        subnet = next((s for s in network_pool.subnets(new_prefix=27)
                       if not any(s.overlaps(n) for n in occupied)), None)
        if subnet is None:
            raise RuntimeError(f"No unused /27 subnet in configured Docker pool {network_pool}.")
        return subprocess.run([*docker_args, *args[:2], "--subnet", str(subnet), *args[2:]], **kwargs)
