"""Pace request starts across local worker processes."""

import fcntl
from pathlib import Path
import time


def wait_for_slot(path, rpm):
    if rpm <= 0:
        raise ValueError("RPM must be positive")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        previous = float(handle.read() or "0")
        delay = previous + 60.0 / rpm - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        started = time.monotonic()
        handle.seek(0)
        handle.truncate()
        handle.write(str(started))
        handle.flush()
        return started
