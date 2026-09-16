"""Bounded capture tests for untrusted harness subprocesses."""

import os
import subprocess
import sys
import time

import pytest

from evalclaw.runners import harness as harness_module


def test_harness_output_capture_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(harness_module, "_OUTPUT_LIMIT_BYTES", 64)

    result = harness_module._run_bounded(
        [sys.executable, "-c", "import sys; print('o' * 200); print('e' * 200, file=sys.stderr)"],
        timeout=10,
        env=os.environ.copy(),
    )

    assert result.returncode == 0
    assert "[output truncated]" in result.stdout
    assert "[output truncated]" in result.stderr
    assert len(result.stdout) < 100
    assert len(result.stderr) < 100


def test_failure_marker_survives_output_truncation(monkeypatch) -> None:
    monkeypatch.setattr(harness_module, "_OUTPUT_LIMIT_BYTES", 64)

    result = harness_module._run_bounded(
        [sys.executable, "-c", "print('a' * 100 + 'FAIL-MARKER' + 'b' * 100)"],
        timeout=10,
        env=os.environ.copy(),
        failure_markers=("FAIL-MARKER",),
    )

    assert "FAIL-MARKER" in result.stderr


def test_timeout_preserves_bounded_output(monkeypatch) -> None:
    monkeypatch.setattr(harness_module, "_OUTPUT_LIMIT_BYTES", 64)

    with pytest.raises(subprocess.TimeoutExpired) as caught:
        harness_module._run_bounded(
            [
                sys.executable,
                "-c",
                "import sys,time; print('o' * 200, flush=True); "
                "print('e' * 200, file=sys.stderr, flush=True); time.sleep(10)",
            ],
            timeout=1,
            env=os.environ.copy(),
        )

    assert "[output truncated]" in caught.value.stdout
    assert "[output truncated]" in caught.value.stderr


def test_deadline_covers_pipes_inherited_by_detached_child(tmp_path):
    started = time.monotonic()
    pid_path = tmp_path / "child.pid"
    try:
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            harness_module._run_bounded(
                [sys.executable, "-c",
                 "import subprocess,sys,pathlib; "
                 "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True); "
                 f"pathlib.Path({str(pid_path)!r}).write_text(str(p.pid)); "
                 "print('parent finished',flush=True)"],
                timeout=1, env=os.environ.copy(),
            )
        assert time.monotonic() - started < 4
        assert "parent finished" in caught.value.stdout
    finally:
        if pid_path.exists():
            os.kill(int(pid_path.read_text()), 9)
