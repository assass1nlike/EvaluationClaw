"""Bounded output capture with a deadline that also covers inherited pipes."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time


def run_bounded(
    command,
    *,
    timeout,
    env,
    stdin=subprocess.DEVNULL,
    failure_markers=(),
    output_limit=8 * 1024 * 1024,
):
    process = subprocess.Popen(
        command,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    buffers = {name: [bytearray(), bytearray(), 0] for name in ("stdout", "stderr")}
    markers = {marker: marker.encode() for marker in failure_markers}
    carry_size = max((len(value) - 1 for value in markers.values()), default=0)
    carries = {name: b"" for name in buffers}
    found = set()
    half = max(1, output_limit // 2)
    deadline = time.monotonic() + timeout
    timed_out = False
    try:
        with selectors.DefaultSelector() as selector:
            for name in buffers:
                selector.register(getattr(process, name), selectors.EVENT_READ, name)
            while selector.get_map() or process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, 64 * 1024)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    name = key.data
                    searchable = carries[name] + chunk
                    found.update(marker for marker, value in markers.items() if value in searchable)
                    carries[name] = searchable[-carry_size:] if carry_size else b""
                    head, tail, total = buffers[name]
                    buffers[name][2] = total + len(chunk)
                    size = max(0, half - len(head))
                    head.extend(chunk[:size])
                    tail.extend(chunk[size:])
                    del tail[:-half]
    finally:
        if process.poll() is None or timed_out:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
        process.stdout.close()
        process.stderr.close()
    outputs = {}
    for name, (head, tail, total) in buffers.items():
        separator = b"\n[output truncated]\n" if total > output_limit else b""
        outputs[name] = (bytes(head) + separator + bytes(tail)).decode("utf-8", errors="replace")
    for marker in sorted(found):
        if not any(marker in value for value in outputs.values()):
            outputs["stderr"] += f"\n[detected failure marker] {marker}"
    if timed_out:
        raise subprocess.TimeoutExpired(
            command, timeout, output=outputs["stdout"], stderr=outputs["stderr"]
        )
    return subprocess.CompletedProcess(command, process.returncode, **outputs)
