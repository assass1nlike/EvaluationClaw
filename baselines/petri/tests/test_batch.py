import json
from pathlib import Path
import subprocess
import threading

import pytest

import run_batch
from petri.scorers.prompts import DIMENSIONS


@pytest.mark.parametrize("profile,prefill", [("deepseek", "no-prefill"), ("qwen", "prefill"),
                                            ("qwen-target", "prefill"), ("sol-target", "no-prefill")])
def test_batch_runs_four_parallel_requirements_and_retains_failed_epochs(tmp_path, monkeypatch, profile, prefill):
    barrier = threading.Barrier(4)
    calls = []

    def execute(command, *, cwd, env, stdout, stderr):
        seed = int(command[command.index("--seed") + 1])
        output = Path(command[command.index("--output-dir") + 1])
        requirement = int(output.parent.name.split("-")[-1])
        assert Path(command[1]) == batch / "source" / "run.py"
        assert env["PYTHONHASHSEED"] == str(seed)
        assert env["PYTHONPATH"] == str(batch / "source" / "upstream" / "src")
        assert command[command.index("--prefill-mode") + 1] == prefill
        assert command[command.index("--scoring") + 1] == "both"
        if profile == "qwen-target":
            assert command[command.index("--target") + 1] == "qwen/qwen3.8-27b"
            assert command[command.index("--auditor") + 1] == "deepseek/deepseek-flash"
            assert command[command.index("--judge") + 1] == "deepseek/deepseek-flash"
            assert command[command.index("--target-base-url") + 1] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        if profile == "sol-target":
            assert command[command.index("--target") + 1] == "sol/gpt-5.6-sol"
            assert command[command.index("--sol-rpm") + 1] == "50"
            assert Path(command[command.index("--sol-rate-limit-file") + 1]).is_absolute()
        if seed == 42:
            barrier.wait(timeout=10)
        calls.append((requirement, seed))
        output.mkdir()
        if requirement == 7 and seed == 42:
            return subprocess.CompletedProcess(command, 1)
        score = None if requirement == 8 and seed == 42 else seed - 34
        tool_errors = [{"function": "send_message", "type": "unknown", "message": "Pending tool calls"}] if seed == 42 else []
        (output / "summary.json").write_text(json.dumps({
            "status": "completed_with_tool_errors" if tool_errors else "success",
            "assessment_status": "insufficient_evidence" if score is None else "scored",
            "scores": {"performance": score},
            "native_reference": {"scores": {name: seed - 40 for name in DIMENSIONS}},
            "tool_errors": tool_errors, "judge_errors": {},
        }))
        return subprocess.CompletedProcess(command, int(bool(tool_errors)))

    batch = tmp_path / "batch"
    monkeypatch.setattr(run_batch, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_batch.subprocess, "check_output", lambda *args, **kwargs: "test-commit\n")
    monkeypatch.setattr(run_batch.subprocess, "run", execute)
    monkeypatch.setattr("sys.argv", ["run_batch.py", "--epochs", "2", "--seed", "42",
                                    "--profile", profile,
                                    "--output-dir", str(batch)])
    assert run_batch.main() == 1
    assert sorted(calls) == [(req, seed) for req in (7, 8, 9, 13) for seed in (42, 43)]
    assert all([seed for req, seed in calls if req == requirement] == [42, 43]
               for requirement in (7, 8, 9, 13))
    summary = json.loads((batch / "summary.json").read_text())
    assert summary["7"]["epochs"][0]["status"] == "run_failed"
    assert summary["7"]["performance"] == {"n": 1, "mean": 9, "stderr": None}
    assert summary["8"]["performance"]["n"] == 1
    for req in ("9", "13"):
        assert summary[req]["performance"] == {"n": 2, "mean": 8.5, "stderr": pytest.approx(0.5)}
        assert summary[req]["epochs"][0]["tool_errors"]
    assert all(metric == {"n": 2, "mean": 2.5, "stderr": pytest.approx(0.5)}
               for metric in summary["8"]["native_reference"].values())
    assert all(value["finished_epochs"] == 2 for value in summary.values())
    assert json.loads((batch / "config.json").read_text())["seeds"] == [42, 43]
    assert (batch / "source" / "sha256.json").is_file()
    assert not list((batch / "source").rglob(".env"))


def test_five_slots_refill_without_waiting_for_slow_epochs(tmp_path, monkeypatch):
    batch = tmp_path / "batch"
    directory = batch / "requirement-07"
    directory.mkdir(parents=True)
    saved = {"epoch": 1, "seed": 42, "exit_code": 0, "status": "success",
             "score": 9, "native_scores": {}, "output": "requirement-07/epoch-01"}
    run_batch.write_json(directory / "summary.json", run_batch.summarize([saved], 7))
    barrier = threading.Barrier(5)
    replacement_started = threading.Event()
    lock = threading.Lock()
    active = 0
    peak = 0
    calls = []

    def epoch_run(batch, requirement, epoch, seed, options):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append((epoch, seed))
        try:
            if epoch <= 6:
                barrier.wait(timeout=10)
                if epoch != 2:
                    assert replacement_started.wait(timeout=10)
            else:
                replacement_started.set()
            return {**saved, "epoch": epoch, "seed": seed}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(run_batch, "run_epoch", epoch_run)
    summary = run_batch.run_requirement(batch, 7, list(range(42, 49)), [], 5)
    assert peak == 5
    assert sorted(calls) == [(epoch, epoch + 41) for epoch in range(2, 8)]
    assert summary["epochs"][0] == saved
    assert [record["epoch"] for record in summary["epochs"]] == list(range(1, 8))


def test_resume_preserves_snapshot_and_archives_interrupted_attempt(tmp_path, monkeypatch):
    import hashlib

    batch = tmp_path / "batch"
    source = batch / "source"
    source.mkdir(parents=True)
    (source / "run.py").write_text("fixed original runner")
    digest = hashlib.sha256((source / "run.py").read_bytes()).hexdigest()
    run_batch.write_json(source / "sha256.json", {"run.py": digest})
    run_batch.write_json(batch / "config.json", {"pid": 999999999,
        "profile": "qwen-target", "seeds": [42, 43], "options": run_batch.QWEN_TARGET_OPTIONS,
        "epochs_per_requirement": 2})
    for req in run_batch.REQUIREMENTS:
        directory = batch / f"requirement-{req:02d}"
        (directory / "epoch-01").mkdir(parents=True)
        (directory / "epoch-01" / "result.txt").write_text("completed result")
        (directory / "epoch-02").mkdir()
        (directory / "epoch-02" / "partial.txt").write_text("interrupted trace")
        (directory / "epoch-02.console.log").write_text("interrupted console")
        run_batch.write_json(directory / "summary.json", run_batch.summarize([
            {"epoch": 1, "seed": 42, "exit_code": 0, "score": 9, "native_scores": {}}
        ], 2))

    calls = []
    def epoch_run(batch, requirement, epoch, seed, options):
        assert epoch == 2 and seed == 43
        assert options == run_batch.QWEN_TARGET_OPTIONS
        assert not (batch / f"requirement-{requirement:02d}" / "epoch-02").exists()
        calls.append(requirement)
        return {"epoch": epoch, "seed": seed, "exit_code": 0, "status": "success",
                "score": 10, "native_scores": {}}

    monkeypatch.setattr(run_batch, "run_epoch", epoch_run)
    monkeypatch.setattr(run_batch, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", ["run_batch.py", "--resume", str(batch), "--epoch-concurrency", "5"])
    assert run_batch.main() == 0
    assert sorted(calls) == list(run_batch.REQUIREMENTS)
    assert (source / "run.py").read_text() == "fixed original runner"
    for req in run_batch.REQUIREMENTS:
        assert (batch / f"requirement-{req:02d}/epoch-01/result.txt").read_text() == "completed result"
        archived = list((batch / "interrupted").glob(f"*/requirement-{req:02d}/epoch-02/partial.txt"))
        assert len(archived) == 1 and archived[0].read_text() == "interrupted trace"
    config = json.loads((batch / "config.json").read_text())
    assert config["epoch_concurrency"] == 5 and config["profile"] == "qwen-target"
