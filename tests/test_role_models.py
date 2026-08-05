from __future__ import annotations

import json

import pytest

from evalclaw.construction.suite import build_task_suite
from evalclaw.execution import runner as execution_runner
from evalclaw.models.roles import role_model_settings
from evalclaw.planning import planner
from evalclaw.quality import improver, llm_checks
from evalclaw.research import deep_research
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    EvalDimension,
    EvalSpec,
    TaskType,
)
from tests.blueprint_factory import make_blueprint


def _config_for(role: str) -> BenchmarkConfig:
    return BenchmarkConfig(
        orchestrator_model="default-model",
        orchestrator_provider="anthropic",
        orchestrator_api_key="default-key",
        orchestrator_base_url="https://default.example",
        **{
            f"{role}_model": f"{role}-model",
            f"{role}_provider": "openai_compatible",
            f"{role}_api_key": f"{role}-key",
            f"{role}_base_url": f"https://{role}.example",
        },
    )


def _assert_role_call(captured: dict, role: str) -> None:
    assert captured["model"] == f"{role}-model"
    assert captured["provider"] == "openai_compatible"
    assert captured["api_key"] == f"{role}-key"
    assert captured["base_url"] == f"https://{role}.example"


def _dataset() -> BenchmarkDataset:
    dimension = EvalDimension(
        id="analysis",
        name="Analysis",
        description="Evaluate analysis.",
        approach="Use one direct task.",
        task_types=[TaskType.generation],
        target_item_count=1,
    )
    spec = EvalSpec(
        objective="Evaluate analysis.",
        dimensions=[dimension],
        task_types=[TaskType.generation],
        scale=1,
    )
    return BenchmarkDataset(
        spec=spec,
        items=[
            BenchmarkItem(
                id="analysis_1",
                dimension_id=dimension.id,
                task_type=TaskType.generation,
                prompt="Analyze the evidence and justify the conclusion.",
                rubric="Score correctness and justification.",
            )
        ],
    )


@pytest.mark.parametrize("role", ["planner", "task_builder", "qc", "judge", "research", "loop3"])
def test_role_settings_override_orchestrator(role: str) -> None:
    settings = role_model_settings(_config_for(role), role)  # type: ignore[arg-type]

    assert settings.configured is True
    _assert_role_call(settings.call_kwargs(), role)


def test_role_settings_fall_back_field_wise() -> None:
    config = BenchmarkConfig(
        orchestrator_model="default-model",
        orchestrator_provider="anthropic",
        orchestrator_api_key="default-key",
        orchestrator_base_url="https://default.example",
        planner_model="planner-model",
    )

    assert role_model_settings(config, "planner").call_kwargs() == {
        "model": "planner-model",
        "provider": "anthropic",
        "api_key": "default-key",
        "base_url": "https://default.example",
    }


def test_role_key_is_sufficient_without_orchestrator_key() -> None:
    settings = role_model_settings(
        BenchmarkConfig(
            orchestrator_api_key=None,
            qc_model="qc-model",
            qc_api_key="qc-key",
        ),
        "qc",
    )

    assert settings.configured is True
    assert settings.model == "qc-model"
    assert settings.api_key == "qc-key"


def test_planner_uses_planner_role(monkeypatch) -> None:
    captured: dict = {}

    def fake_call_llm(*args, **kwargs):
        captured.update(kwargs)
        return '{"english_goal":"Evaluate analysis"}'

    monkeypatch.setattr(planner, "call_llm", fake_call_llm)

    assert planner.translate_goal_to_english("评估分析能力", _config_for("planner")) == "Evaluate analysis"
    _assert_role_call(captured, "planner")


def test_task_builder_uses_task_builder_role(monkeypatch) -> None:
    captured: dict = {}
    dataset = _dataset()
    blueprint = make_blueprint(
        "analysis_blueprint",
        "analysis",
        "Analysis task",
        task_type=TaskType.generation,
        content="One analysis task.",
    )

    def fake_call_llm(*args, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop after capture")

    monkeypatch.setattr("evalclaw.construction.suite.call_llm", fake_call_llm)

    with pytest.raises(RuntimeError, match="stop after capture"):
        build_task_suite(
            dataset.spec,
            [blueprint],
            _config_for("task_builder").model_copy(
                update={
                    "task_builder_max_workers": 1,
                    "task_builder_repair_attempts": 0,
                    "use_web_research": False,
                    "use_hf_discovery": False,
                }
            ),
        )
    _assert_role_call(captured, "task_builder")


def test_qc_uses_qc_role(monkeypatch) -> None:
    captured: dict = {}

    def fake_call_llm(*args, **kwargs):
        captured.update(kwargs)
        return '{"issues":[]}'

    monkeypatch.setattr(llm_checks, "call_llm", fake_call_llm)

    llm_checks._llm_qc(_dataset(), _config_for("qc"))
    _assert_role_call(captured, "qc")


def test_judge_uses_judge_role(monkeypatch) -> None:
    captured: dict = {}

    def fake_call_llm(*args, **kwargs):
        captured.update(kwargs)
        return '{"score_raw":5,"score_normalized":1.0,"reasoning":"correct"}'

    monkeypatch.setattr(execution_runner, "call_llm", fake_call_llm)

    assert execution_runner._call_judge_json({"item": "x"}, _config_for("judge")) is not None
    _assert_role_call(captured, "judge")


def test_research_uses_research_role(monkeypatch) -> None:
    captured: dict = {}

    def fake_call_llm(*args, **kwargs):
        captured.update(kwargs)
        return '{"findings":["grounded"]}'

    monkeypatch.setattr(deep_research, "call_llm", fake_call_llm)

    assert deep_research._call_orchestrator_json(
        _config_for("research"),
        "system",
        {"goal": "goal"},
    ) == {"findings": ["grounded"]}
    _assert_role_call(captured, "research")


def test_low_effort_research_caps_structured_output_budget(monkeypatch) -> None:
    captured: dict = {}

    def fake_call_llm(*args, **kwargs):
        captured.update(kwargs)
        return '{"findings":["grounded"]}'

    monkeypatch.setenv("EVALCLAW_REASONING_EFFORT", "low")
    monkeypatch.setattr(deep_research, "call_llm", fake_call_llm)

    deep_research._call_orchestrator_json(
        _config_for("research"),
        "system",
        {"goal": "goal"},
        max_tokens=8192,
    )

    assert captured["max_tokens"] == 2048


def test_loop3_uses_loop3_role(monkeypatch) -> None:
    captured: dict = {}

    def fake_call_llm(*args, **kwargs):
        captured.update(kwargs)
        return json.dumps({"actions": []})

    monkeypatch.setattr(improver, "call_llm", fake_call_llm)

    assert improver._call_loop3_llm_json({}, _config_for("loop3")) == {"actions": []}
    _assert_role_call(captured, "loop3")
