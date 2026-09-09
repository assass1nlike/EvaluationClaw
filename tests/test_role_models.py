from __future__ import annotations

import json

import pytest

from evalclaw.construction.suite import build_task_suite
from evalclaw.execution import runner as execution_runner
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.models.roles import resolve_task_model, role_model_settings
from evalclaw.planning import planner
from evalclaw.quality import analysis, llm_checks
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    EvalDimension,
    EvalSpec,
    TargetModelConfig,
    TaskSuite,
    TaskType,
)
from tests.blueprint_factory import make_blueprint
from tests.config_helpers import patch_task_builder_model


def _config_for(role: str) -> BenchmarkConfig:
    return BenchmarkConfig(
        **{
            f"{role}_model": f"{role}-model",
            f"{role}_provider": "openai_compatible",
            f"{role}_api_key": f"{role}-key",
            f"{role}_base_url": f"https://{role}.example",
        },
        use_llm_qc=True,
    )


def _assert_role_call(captured: dict, role: str) -> None:
    assert captured["model"] == f"{role}-model"
    assert captured["provider"] == "openai_compatible"
    assert captured["api_key"] == f"{role}-key"
    assert captured["base_url"] == f"https://{role}.example"


def _suite() -> TaskSuite:
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
    return TaskSuite(
        spec=spec,
        objective=spec.objective,
        tasks=[
            BenchmarkItem(
                id="analysis_1",
                dimension_id=dimension.id,
                task_type=TaskType.generation,
                prompt="Analyze the evidence and justify the conclusion.",
                rubric="Score correctness and justification.",
            )
        ],
    )


@pytest.mark.parametrize("role", ["planner", "task_builder", "qc", "research", "analyser"])
def test_role_settings_use_role_fields(role: str) -> None:
    settings = role_model_settings(_config_for(role), role)  # type: ignore[arg-type]

    assert settings.configured is True
    _assert_role_call(settings.call_kwargs(), role)


def test_unset_role_fields_remain_none() -> None:
    config = BenchmarkConfig(planner_model="planner-model")

    assert role_model_settings(config, "planner").call_kwargs() == {
        "model": "planner-model",
        "provider": None,
        "api_key": None,
        "base_url": None,
    }


def test_role_reasoning_effort_is_forwarded() -> None:
    settings = role_model_settings(
        BenchmarkConfig(
            task_builder_model="gpt-5.6-sol",
            task_builder_api_key="key",
            task_builder_reasoning_effort="high",
        ),
        "task_builder",
    )

    assert settings.call_kwargs()["reasoning_effort"] == "high"


def test_role_key_is_sufficient() -> None:
    settings = role_model_settings(
        BenchmarkConfig(
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
    suite = _suite()
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

    patch_task_builder_model(monkeypatch, fake_call_llm)

    with pytest.raises(RuntimeError, match="stop after capture"):
        build_task_suite(
            suite.spec,
            [blueprint],
            _config_for("task_builder").model_copy(
                update={
                    "task_builder_max_workers": 1,
                    "task_builder_repair_attempts": 0,
                    "use_web_research": False,
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

    llm_checks._llm_qc(_suite(), _config_for("qc"))
    _assert_role_call(captured, "qc")


def test_judge_uses_selected_judge_model(monkeypatch) -> None:
    captured: dict = {}

    def fake_call_llm(*args, **kwargs):
        captured.update(kwargs)
        return '{"score_raw":5,"score_normalized":1.0,"reasoning":"correct"}'

    monkeypatch.setattr(execution_runner, "call_llm", fake_call_llm)

    config = BenchmarkConfig(
        task_models=[
            TargetModelConfig(provider="openai_compatible", model="judge-model", api_key="judge-key")
        ]
    )
    assert execution_runner._call_judge_json({"item": "x"}, config, config.task_models[0]) is not None
    assert captured["model"] == "judge-model"
    assert captured["provider"] == "openai_compatible"
    assert captured["api_key"] == "judge-key"


def test_resolve_task_model_uses_per_task_selection() -> None:
    models = [
        TargetModelConfig(provider="openai_compatible", model="task-a", api_key="k"),
        TargetModelConfig(provider="openai_compatible", model="task-b", api_key="k"),
    ]
    config = BenchmarkConfig(task_models=models)
    item = BenchmarkItem(
        id="i",
        dimension_id="d",
        task_type=TaskType.generation,
        prompt="p",
        metadata={"task_model_id": "task-b"},
    )

    assert resolve_task_model(config, item).model == "task-b"
    assert resolve_task_model(config).model == "task-a"
    assert resolve_task_model(BenchmarkConfig(), item) is None


def test_analysis_uses_analyser_role(monkeypatch) -> None:
    captured: dict = {}

    def fake_call_llm(*args, **kwargs):
        captured.update(kwargs)
        return TargetToolModelResponse(
            adapter="litellm",
            content=json.dumps(
                {"analysis": "Supported conclusion.", "recommendations": [], "task_designs": []}
            ),
            tool_calls=[],
            assistant_message={"role": "assistant", "content": ""},
            raw_response={},
        )

    monkeypatch.setattr(analysis, "call_orchestrator_with_tools", fake_call_llm)

    assert analysis._run_analyser_tool_loop(
        {}, _config_for("analyser"), trace_dir=None, artifact_dir=None
    )["analysis"] == "Supported conclusion."
    _assert_role_call(captured, "analyser")
