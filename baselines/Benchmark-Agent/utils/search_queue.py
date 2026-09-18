"""Cross-process request slots and a clock excluding infrastructure waits."""

import fcntl
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class SearchInfrastructureError(BaseException):
    """Stop execution without returning an infrastructure failure to a planner."""


_clock_lock = threading.Lock()
_waiters = 0
_wait_started = 0.0
_wait_total = 0.0


@contextmanager
def infrastructure_wait():
    global _waiters, _wait_started, _wait_total
    with _clock_lock:
        if _waiters == 0:
            _wait_started = time.monotonic()
        _waiters += 1
    try:
        yield
    finally:
        with _clock_lock:
            _waiters -= 1
            if _waiters == 0:
                _wait_total += time.monotonic() - _wait_started


def progress_clock():
    with _clock_lock:
        now = time.monotonic()
        return now - _wait_total - (now - _wait_started if _waiters else 0)


@contextmanager
def search_slot(directory, capacity):
    """flock releases a slot even when its owner process is killed."""
    if type(capacity) is not int or capacity < 1:
        raise SearchInfrastructureError("Invalid search concurrency capacity")
    directory = Path(directory)
    if not directory.is_absolute():
        directory = Path(__file__).resolve().parents[1] / directory
    slot = None
    request_id = uuid4().hex
    started = time.monotonic()

    def event(kind, slot_index):
        row = {"event": kind, "id": request_id, "pid": os.getpid(), "slot": slot_index,
               "time_ns": time.monotonic_ns(), "wait_seconds": waited}
        with (directory / "events.jsonl").open("a") as log:
            fcntl.flock(log, fcntl.LOCK_EX)
            log.write(json.dumps(row) + "\n")

    try:
        directory.mkdir(parents=True, exist_ok=True)
        with infrastructure_wait(), (directory / "admission.lock").open("a") as admission:
            fcntl.flock(admission, fcntl.LOCK_EX)
            while slot is None:
                for index in range(capacity):
                    candidate = (directory / f"slot_{index}.lock").open("a")
                    try:
                        fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        candidate.close()
                    else:
                        slot = candidate
                        break
                if slot is None:
                    time.sleep(0.05)
        waited = time.monotonic() - started
        event("acquired", index)
        try:
            yield waited
        finally:
            event("released", index)
    except OSError as exc:
        raise SearchInfrastructureError(f"Search queue I/O failed: {type(exc).__name__}") from exc
    finally:
        if slot is not None:
            slot.close()
