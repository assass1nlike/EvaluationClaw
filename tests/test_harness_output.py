"""Bounded capture tests for untrusted harness subprocesses."""

import os
import sys

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
