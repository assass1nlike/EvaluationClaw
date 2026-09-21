"""Space HTTP request starts across processes sharing a local lock file."""

import fcntl
from pathlib import Path
import time


def wait_for_slot(path, rpm=50):
    if rpm <= 0:
        raise ValueError("RPM must be positive")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        previous = float(handle.read() or "0")
        # A small margin keeps a rolling 60-second window below the ceiling.
        delay = previous + 60 / rpm + 0.01 - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        started = time.monotonic()
        handle.seek(0)
        handle.truncate()
        handle.write(str(started))
        handle.flush()
        return started
