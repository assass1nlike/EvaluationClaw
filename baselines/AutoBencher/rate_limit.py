"""Shared request slots and a rolling-window limit across local processes."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import time
import uuid


class RateLimit:
    def __init__(self, path, limit, window=60):
        self.path, self.limit, self.window = path, limit, window
        path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def reservation(self):
        identity = uuid.uuid4().hex
        while True:
            with self.path.open('a+') as state:
                fcntl.flock(state, fcntl.LOCK_EX)
                state.seek(0)
                rows = json.loads(state.read() or '[]')
                # Read timestamps written by the earlier limiter as well.
                rows = [r if isinstance(r, dict) else {'id': str(r), 'time': r} for r in rows]
                now = time.time()
                for row in rows:
                    if row['time'] is None and not Path(f"/proc/{row['pid']}").exists():
                        row['time'] = now
                rows = [r for r in rows if r['time'] is None or r['time'] > now - self.window]
                available = len(rows) < self.limit
                if available:
                    rows.append({'id': identity, 'time': None, 'pid': os.getpid()})
                state.seek(0)
                state.truncate()
                state.write(json.dumps(rows))
                state.flush()
                if available:
                    break
            time.sleep(0.1)
        sent = None

        def mark_sent():
            nonlocal sent
            if sent is not None:
                return sent
            with self.path.open('r+') as state:
                fcntl.flock(state, fcntl.LOCK_EX)
                rows = json.load(state)
                sent = time.time()
                for row in rows:
                    if row['id'] == identity:
                        row['time'] = sent
                state.seek(0)
                state.truncate()
                state.write(json.dumps(rows))
                state.flush()
            return sent

        try:
            yield mark_sent
        finally:
            # Errors before sending headers still count as an attempt.
            mark_sent()

    def acquire(self):
        with self.reservation() as mark_sent:
            return mark_sent()


class SharedSlots:
    def __init__(self, directory, limit):
        self.directory, self.limit = directory, limit
        directory.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def slot(self):
        acquired = None
        while acquired is None:
            for index in range(self.limit):
                handle = (self.directory / str(index)).open('a')
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = handle
                    break
                except BlockingIOError:
                    handle.close()
            if acquired is None:
                time.sleep(0.1)
        try:
            yield
        finally:
            acquired.close()
