"""Pace HTTP requests across all threads of one evaluation process."""

from datetime import datetime, timezone
import json
import threading
import time


class RequestPacer:
    def __init__(self, rpm, log_path=None):
        if rpm <= 0:
            raise ValueError("rpm must be positive")
        self.interval = 60 / rpm + 0.01
        self.next_start = 0.0
        self.lock = threading.Lock()
        self.log_path = log_path

    def __call__(self, request):
        # HTTP hooks also cover retries. Waiting never holds an in-flight request.
        with self.lock:
            while (delay := self.next_start - time.monotonic()) > 0:
                time.sleep(delay)
            started = time.monotonic()
            self.next_start = started + self.interval
            if self.log_path is not None:
                with self.log_path.open("a") as handle:
                    handle.write(json.dumps({"time_utc": datetime.now(timezone.utc).isoformat(),
                                             "monotonic": started}) + "\n")
