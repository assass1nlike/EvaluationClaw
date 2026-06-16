import json
import subprocess
from pathlib import Path

from evalclaw.execution.docker import docker_status, resolve_docker_executable
from evalclaw.execution.swebench import (
    SweBenchHarnessConfig,
    SweBenchPrediction,
    build_run_evaluation_command,
    is_swebench_item,
    normalize_json_list,
    normalize_swebench_instance,
    prepare_proxy_base_image,
    run_swebench_harness,
    validate_swebench_environment_for_items,
    write_predictions_jsonl,
)
from evalclaw.pipeline import _validate_swebench_preflight_with_retry
from evalclaw.runner import run_eval
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    EvalSpec,
    QcReport,
    SourceKind,
    TargetModelConfig,
    TaskType,
)


def test_normalize_swebench_lists_from_string_or_list() -> None:
    assert normalize_json_list('["a", "b"]') == ["a", "b"]
    assert normalize_json_list(["c", 1]) == ["c", "1"]
    row = {
        "instance_id": "repo__repo-1",
        "FAIL_TO_PASS": '["tests/test_fix.py::test_new"]',
        "PASS_TO_PASS": ["tests/test_old.py::test_existing"],
    }

    normalized = normalize_swebench_instance(row)

    assert normalized["FAIL_TO_PASS"] == ["tests/test_fix.py::test_new"]
    assert normalized["PASS_TO_PASS"] == ["tests/test_old.py::test_existing"]


def test_write_predictions_jsonl(tmp_path) -> None:
    path = write_predictions_jsonl(
        [
            SweBenchPrediction(
                instance_id="pallets__flask-4045",
                model_name_or_path="mock-model",
                model_patch="diff --git a/a.py b/a.py\n",
            )
        ],
        tmp_path / "predictions.jsonl",
    )

    payload = json.loads(path.read_text(encoding="utf-8").strip())
    assert payload["instance_id"] == "pallets__flask-4045"
    assert payload["model_name_or_path"] == "mock-model"
    assert payload["model_patch"].startswith("diff --git")


def test_build_swebench_run_command() -> None:
    command = build_run_evaluation_command(
        SweBenchHarnessConfig(
            predictions_path="gold",
            output_dir="out",
            dataset_name="princeton-nlp/SWE-bench_Lite",
            split="test",
            max_workers=2,
            run_id="smoke",
            instance_ids=["pallets__flask-4045"],
            cache_level="env",
            force_rebuild=True,
            timeout=900,
            python_executable="python",
        )
    )

    assert command[:3] == ["python", "-m", "swebench.harness.run_evaluation"]
    assert "--predictions_path" in command
    assert "gold" in command
    assert "--instance_ids" in command
    assert "pallets__flask-4045" in command
    assert "--timeout" in command
    assert "900" in command
    assert "--force_rebuild" in command
    assert "True" in command


def test_docker_status_reports_missing_executable(monkeypatch) -> None:
    monkeypatch.setattr("evalclaw.execution.docker._windows_docker_cli_candidates", lambda: [])
    monkeypatch.setattr("evalclaw.execution.docker.shutil.which", lambda executable: None)

    status = docker_status(executable="missing-docker")

    assert not status.available
    assert "not found" in status.error


def test_resolve_docker_executable_uses_windows_default_path(monkeypatch, tmp_path) -> None:
    docker = tmp_path / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"
    docker.parent.mkdir(parents=True)
    docker.write_text("", encoding="utf-8")

    monkeypatch.setattr("evalclaw.execution.docker.shutil.which", lambda executable: None)
    monkeypatch.setattr("evalclaw.execution.docker._windows_docker_cli_candidates", lambda: [docker])

    assert resolve_docker_executable("docker") == str(docker)


def test_run_swebench_harness_invokes_subprocess_without_preflight(monkeypatch, tmp_path) -> None:
    calls: list[tuple[list[str], dict]] = []
    docker = tmp_path / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"
    docker.parent.mkdir(parents=True)
    docker.write_text("", encoding="utf-8")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("evalclaw.execution.swebench.subprocess.run", fake_run)
    monkeypatch.setattr("evalclaw.execution.docker.shutil.which", lambda executable: None)
    monkeypatch.setattr(
        "evalclaw.execution.docker._windows_docker_cli_candidates",
        lambda: [docker],
    )
    config = SweBenchHarnessConfig(
        predictions_path="gold",
        output_dir=tmp_path,
        run_id="unit",
        instance_ids=["pallets__flask-4045"],
        python_executable="python",
    )

    result = run_swebench_harness(config, check_docker=False, check_harness=False)

    assert result.returncode == 0
    assert result.stdout == "ok"
    assert calls
    command, kwargs = calls[0]
    assert command[:3] == ["python", "-m", "swebench.harness.run_evaluation"]
    assert str(docker.parent) in kwargs["env"]["PATH"]


def test_run_swebench_harness_uses_wsl_when_requested(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("evalclaw.execution.swebench.subprocess.run", fake_run)
    monkeypatch.setattr(
        "evalclaw.execution.swebench._windows_path_to_wsl",
        lambda path: f"/mnt/d/mock/{Path(path).name}",
    )
    config = SweBenchHarnessConfig(
        predictions_path="gold",
        output_dir=tmp_path,
        run_id="unit",
        python_executable=".venv-swebench-wsl/bin/python",
        use_wsl=True,
        wsl_distro="Ubuntu-24.04",
    )

    result = run_swebench_harness(config, check_docker=False, check_harness=False)

    assert result.returncode == 0
    assert calls
    command = calls[0]
    assert command[:5] == ["wsl.exe", "-d", "Ubuntu-24.04", "--", "bash"]
    script = command[-1]
    assert "DOCKER_HOST=" in script
    assert "/mnt/d/mock/python -m swebench.harness.run_evaluation" in script


def test_prepare_proxy_base_image_builds_wrapper(monkeypatch) -> None:
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")
        dockerfile = Path(command[-1]) / "Dockerfile"
        assert dockerfile.read_text(encoding="utf-8").startswith("FROM sweb.base.py.x86_64:latest")
        assert "host.docker.internal:7891" in dockerfile.read_text(encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="built", stderr="")

    monkeypatch.setattr("evalclaw.execution.swebench.resolve_docker_executable", lambda executable: "docker")
    monkeypatch.setattr("evalclaw.execution.swebench.subprocess.run", fake_run)

    result = prepare_proxy_base_image(proxy_url="http://host.docker.internal:7891")

    assert result.returncode == 0
    assert result.stdout == "built"
    assert calls[0][0][:3] == ["docker", "image", "inspect"]
    assert calls[1][0][:3] == ["docker", "build", "-t"]


def test_swebench_item_detection_uses_metadata_tags_or_source() -> None:
    base = {
        "id": "item",
        "dimension_id": "code_repair",
        "task_type": TaskType.open_generation,
        "prompt": "Fix the bug.",
    }

    assert is_swebench_item(BenchmarkItem(**base, metadata={"swebench": {"instance_id": "repo__repo-1"}}))
    assert is_swebench_item(BenchmarkItem(**base, tags=["swe-bench"]))
    assert is_swebench_item(
        BenchmarkItem(
            **base,
            source={"kind": SourceKind.imported, "uri": "swebench:repo__repo-1"},
        )
    )
    assert not is_swebench_item(BenchmarkItem(**base))


def test_swebench_preflight_skips_when_no_swebench_items(monkeypatch) -> None:
    item = BenchmarkItem(
        id="ordinary",
        dimension_id="code_repair",
        task_type=TaskType.open_generation,
        prompt="Fix the bug.",
    )

    monkeypatch.setattr(
        "evalclaw.execution.swebench.docker_status",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Docker should not be checked")),
    )

    validate_swebench_environment_for_items([item], BenchmarkConfig())


def test_swebench_preflight_reports_actionable_missing_environment(monkeypatch) -> None:
    item = BenchmarkItem(
        id="swe_item",
        dimension_id="code_repair",
        task_type=TaskType.open_generation,
        prompt="Fix the SWE-bench issue.",
        metadata={"swebench": {"instance_id": "pallets__flask-4045"}},
    )

    monkeypatch.setattr(
        "evalclaw.execution.swebench.docker_status",
        lambda **kwargs: type("Status", (), {"available": False, "error": "daemon unavailable"})(),
    )

    def fake_harness(*args, **kwargs):
        raise RuntimeError("swebench import failed")

    monkeypatch.setattr("evalclaw.execution.swebench.ensure_swebench_harness_available", fake_harness)

    try:
        validate_swebench_environment_for_items(
            [item],
            BenchmarkConfig(targets=[TargetModelConfig(provider="mock", model="mock-model")]),
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected SWE-bench preflight failure")

    assert "SWE-bench runtime is not ready" in message
    assert "swe_item" in message
    assert "daemon unavailable" in message
    assert "pip install swebench datasets -i https://pypi.tuna.tsinghua.edu.cn/simple" in message


def test_pipeline_swebench_preflight_retries_after_manual_setup(monkeypatch) -> None:
    item = BenchmarkItem(
        id="swe_item",
        dimension_id="code_repair",
        task_type=TaskType.open_generation,
        prompt="Fix the SWE-bench issue.",
        metadata={"swebench": {"instance_id": "pallets__flask-4045"}},
    )
    calls = {"count": 0}

    def fake_validate(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("missing Docker")

    monkeypatch.setattr("evalclaw.pipeline.validate_swebench_environment_for_items", fake_validate)

    result = _validate_swebench_preflight_with_retry(
        [item],
        BenchmarkConfig(),
        log=lambda _: None,
        ask_user=lambda _: "",
        interactive=True,
    )

    assert result.run_targets
    assert calls["count"] == 2


def test_pipeline_swebench_preflight_can_skip_target_run(monkeypatch) -> None:
    item = BenchmarkItem(
        id="swe_item",
        dimension_id="code_repair",
        task_type=TaskType.open_generation,
        prompt="Fix the SWE-bench issue.",
        metadata={"swebench": {"instance_id": "pallets__flask-4045"}},
    )

    def fake_validate(*args, **kwargs):
        raise RuntimeError("missing Docker")

    monkeypatch.setattr("evalclaw.pipeline.validate_swebench_environment_for_items", fake_validate)

    result = _validate_swebench_preflight_with_retry(
        [item],
        BenchmarkConfig(),
        log=lambda _: None,
        ask_user=lambda _: "skip",
        interactive=True,
    )

    assert not result.run_targets


def test_runner_executes_swebench_item_through_harness(monkeypatch, tmp_path) -> None:
    item = BenchmarkItem(
        id="swe_item",
        dimension_id="code_repair",
        task_type=TaskType.open_generation,
        prompt="Fix the SWE-bench issue.",
        metadata={"swebench": {"instance_id": "pallets__flask-4045", "output_dir": str(tmp_path)}},
    )
    dataset = BenchmarkDataset(spec=EvalSpec(objective="Evaluate SWE-bench."), items=[item])
    qc = QcReport(passed_item_ids=[item.id])
    config = BenchmarkConfig(
        targets=[TargetModelConfig(provider="mock", model="mock-model")],
        run_targets=True,
    )
    calls: dict[str, object] = {}

    monkeypatch.setattr("evalclaw.execution.runner._target_has_credentials", lambda *args, **kwargs: (True, "MOCK_API_KEY"))
    monkeypatch.setattr(
        "evalclaw.execution.runner.validate_swebench_environment_for_items",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "evalclaw.execution.runner.call_target_model",
        lambda *args, **kwargs: "diff --git a/app.py b/app.py\n",
    )

    def fake_harness(run_config):
        calls["predictions_path"] = run_config.predictions_path
        report_path = Path(run_config.output_dir) / f"{Path(run_config.predictions_path).stem}.{run_config.run_id}.json"
        report_path.write_text(
            json.dumps({"resolved_ids": ["pallets__flask-4045"], "unresolved_ids": [], "error_ids": []}),
            encoding="utf-8",
        )
        return type("HarnessResult", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("evalclaw.execution.runner.run_swebench_harness", fake_harness)

    run = run_eval(dataset, qc, config)

    assert run.results[0].score == 1.0
    assert "SWE-bench resolved" in (run.results[0].judge_reasoning or "")
    predictions_payload = json.loads(Path(calls["predictions_path"]).read_text(encoding="utf-8"))
    assert predictions_payload["model_patch"].startswith("diff --git")
