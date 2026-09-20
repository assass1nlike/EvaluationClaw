"""Port leases held until a QEMU instance stops, including its boot window."""

import fcntl
import os
from pathlib import Path
import random
import socket
import tempfile


class PortLeases:
    def __init__(self):
        self.directory = Path(os.environ.get(
            "GYM_ANYTHING_QEMU_PORT_LOCK_DIR",
            str(Path(tempfile.gettempdir()) / f"gym-anything-ports-{os.getuid()}"),
        ))
        self._files = []

    def reserve(self, start):
        self.directory.mkdir(parents=True, exist_ok=True)
        offset = random.randint(0, 200)
        for i in range(300):
            port = start + offset + i
            if port > 65535:
                port = start + i % 300
            lease = (self.directory / str(port)).open("a")
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Do not use SO_REUSEADDR: QEMU cannot bind TIME_WAIT ports.
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.bind(("0.0.0.0", port))
            except (BlockingIOError, OSError):
                lease.close()
                continue
            self._files.append(lease)
            return port
        raise RuntimeError("No free QEMU port")

    def close(self):
        for lease in self._files:
            lease.close()
        self._files.clear()
        # Keep lock files: unlinking would allow two locks on different inodes.
