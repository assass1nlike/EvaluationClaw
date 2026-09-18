from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from evalclaw.types import (
    BenchmarkItem,
    EvalDimension,
    EvalSpec,
    QcReport,
    TaskSuite,
    TaskType,
)
from evalclaw_harness.api import build, validate
from evalclaw_harness.cli import app
from evalclaw_harness.models import HarnessConfig, HarnessRequest


def _request() -> HarnessRequest:
    return HarnessRequest.model_validate(
        {
            "id": "external-request",
            "objective": "Evaluate evidence extraction.",
            "dimensions": [
                {
                    "id": "extract",
                    "name": "Extraction",
                    "measurement_target": "Extract a supplied fact.",
                    "boundary": "Use only supplied evidence.",
                    "approach": "Use deterministic fill-blank tasks.",
                    "task_designs": [
                        {
                            "id": "extract_fact",
                            "task_type": "fill_blank",
                            "task_count": 1,
                            "challenge_effort": "E1",
                            "content_design": {"description": "Extract one explicit fact."},
                        }
                    ],
                }
            ],
        }
    )


def _config(**updates: object) -> HarnessConfig:
    raw = {
        "task_builder": {
            "model": "builder-model",
            "provider": "openai_compatible",
            "api_key": "sk-test-secret",
            "base_url": "https://models.example/v1",
        },
        "environment_preflight": False,
    }
    raw.update(updates)
    return HarnessConfig.model_validate(raw)


def _suite() -> TaskSuite:
    dimension = EvalDimension(
        id="extract",
        name="Extraction",
        description="Extract facts.",
        approach="Use deterministic tasks.",
        task_types=[TaskType.fill_blank],
        target_item_count=1,
    )
    spec = EvalSpec(
        id="external-request",
        objective="Evaluate evidence extraction.",
        dimensions=[dimension],
        scale=1,
    )
    return TaskSuite(
        id="external-suite",
        objective=spec.objective,
        spec=spec,
        dimensions=[dimension],
        tasks=[
            BenchmarkItem(
                id="fact-1",
                dimension_id="extract",
                task_type=TaskType.fill_blank,
                prompt="According to the supplied record, what is the project code?",
                expected_texts=["ALPHA-7"],
            )
        ],
    )


def test_request_derives_existing_plan_contract() -> None:
    request = _request()
    plan = request.to_plan()

    assert plan.to_eval_spec().scale == 1
    assert plan.builder_jobs[0].id == "extract__extract_fact"
    assert plan.builder_jobs[0].task_design_ids == ["extract_fact"]


@pytest.mark.parametrize(
    "path,value,message",
    [
        (("dimensions", 1, "id"), "extract", "Dimension ids must be unique"),
        (
            ("dimensions", 1, "task_designs", 0, "id"),
            "extract_fact",
            "TaskDesign ids must be globally unique",
        ),
    ],
)
def test_request_rejects_duplicate_ids(path, value, message) -> None:
    raw = _request().model_dump(mode="json")
    raw["dimensions"].append(json.loads(json.dumps(raw["dimensions"][0])))
    if path[2:3] == ("task_designs",):
        raw["dimensions"][1]["id"] = "extract-second"
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValueError, match=message):
        HarnessRequest.model_validate(raw)


def test_config_maps_only_harness_roles_and_resolves_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HARNESS_BUILDER_KEY", "resolved-secret")
    config = HarnessConfig.model_validate(
        {
            "task_builder": {
                "model": "builder-model",
                "api_key_env": "HARNESS_BUILDER_KEY",
            }
        }
    ).to_benchmark_config(output_dir=str(tmp_path))

    assert config.task_builder_api_key == "resolved-secret"
    assert config.planner_model is None
    assert config.analyser_model is None
    assert config.run_targets is False


def test_build_uses_preplanned_entrypoint_and_redacts_config(monkeypatch, tmp_path) -> None:
    request = _request()
    suite = _suite()
    calls = []

    def fake_build(spec, builder_jobs, config, **kwargs):
        calls.append((spec, builder_jobs, config, kwargs))
        return suite, QcReport(passed_item_ids=["fact-1"], summary="passed")

    monkeypatch.setattr("evalclaw_harness.api.build_suite_from_spec_with_qc_loop", fake_build)
    result = build(request, _config(), tmp_path, log=lambda _: None)

    assert result.status == "ready"
    assert len(calls) == 1
    assert calls[0][0].objective == request.objective
    assert calls[0][1][0].task_design_ids == ["extract_fact"]
    saved = (tmp_path / "config.json").read_text(encoding="utf-8")
    assert "sk-test-secret" not in saved
    assert "[REDACTED]" in saved
    assert (tmp_path / "result.json").is_file()


def test_validate_runs_static_qc_and_writes_artifacts(tmp_path) -> None:
    result = validate(_suite(), _config(), tmp_path)

    assert result.status == "ready"
    assert result.qc_report.passed_item_ids == ["fact-1"]
    assert (tmp_path / "suite.json").is_file()
    assert (tmp_path / "qc-report.json").is_file()


def test_validate_preflights_agent_environment(monkeypatch, tmp_path) -> None:
    suite = _suite()
    suite.tasks = [
        BenchmarkItem(
            id="agent-1",
            dimension_id="extract",
            task_type=TaskType.agent,
            prompt="Inspect the workspace and report whether its setup is executable.",
            rubric="Award full credit for the correct report.",
            metadata={
                "agent_env": {
                    "type": "docker_workspace",
                    "image": "python:3.11-slim",
                    "test_command": "true",
                }
            },
        )
    ]
    calls = []

    class Outcome:
        def as_dict(self):
            return {"ok": True}

    class Environment:
        def preflight(self):
            calls.append("preflight")
            return Outcome()

        def cleanup(self):
            calls.append("cleanup")

    monkeypatch.setattr("evalclaw_harness.api.build_agent_environment", lambda *args: Environment())
    result = validate(suite, _config(environment_preflight=True), tmp_path)

    assert result.status == "incomplete"
    assert calls == ["preflight", "cleanup"]
    assert not any("environment preflight failed" in issue.message for issue in result.qc_report.issues)
    assert (tmp_path / "traces" / "environment-preflight" / "agent-1" / "result.json").is_file()


def test_cli_validate_emits_machine_readable_result(tmp_path) -> None:
    suite_path = tmp_path / "input-suite.json"
    config_path = tmp_path / "input-config.json"
    output_dir = tmp_path / "run"
    suite_path.write_text(_suite().model_dump_json(indent=2), encoding="utf-8")
    config_path.write_text(_config().model_dump_json(indent=2), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "validate",
            "--suite",
            str(suite_path),
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ready"
    assert payload["result"] == str((output_dir / "result.json").resolve())


def test_failure_is_persisted(monkeypatch, tmp_path) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("builder failed with sk-private")

    monkeypatch.setattr("evalclaw_harness.api.build_suite_from_spec_with_qc_loop", fail)
    with pytest.raises(RuntimeError, match="builder failed"):
        build(_request(), _config(), tmp_path, log=lambda _: None)

    failure = (tmp_path / "failure.json").read_text(encoding="utf-8")
    assert "sk-private" not in failure
    assert "[REDACTED]" in failure
