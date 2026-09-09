from __future__ import annotations

import json

import pytest

from evalclaw.planning.task_planner import (
    _audit_plan,
    _explicit_total_task_count,
    _valid_effort_distribution,
    plan_benchmark,
)
from evalclaw.types import BenchmarkConfig, BenchmarkPlan, ChallengeEffort, TaskType
from tests.config_helpers import dummy_config_kwargs


def _plan(
    *,
    task_count: int = 1,
    task_type: TaskType = TaskType.generation,
    environment_category: str = "",
    followup_mode: str = "adaptive",
    source_strategy: str = "generated",
    suggested_urls: list[str] | None = None,
    search_queries: list[str] | None = None,
) -> BenchmarkPlan:
    environment = (
        {"category": environment_category, "purpose": "Run the interaction."}
        if environment_category
        else {}
    )
    return BenchmarkPlan.model_validate(
        {
            "id": "test_plan",
            "objective": "Test the requested capability.",
            "dimensions": [
                {
                    "id": "capability",
                    "name": "Capability",
                    "measurement_target": "The requested capability.",
                    "boundary": "Exclude unrelated capabilities.",
                    "approach": "Measure it directly.",
                    "task_designs": [
                        {
                            "id": "tasks",
                            "task_type": task_type.value,
                            "task_count": task_count,
                            "content_design": {"description": "Concrete test cases."},
                            "interaction_requirements": (
                                {"followup_mode": followup_mode}
                                if task_type == TaskType.multi_turn and followup_mode
                                else {}
                            ),
                            "environment_requirements": environment,
                            "source_plan": {
                                "strategy": source_strategy,
                                "suggested_urls": suggested_urls or [],
                                "search_queries": search_queries or [],
                            },
                        }
                    ],
                }
            ],
        }
    )


def test_explicit_total_task_count_is_conservative() -> None:
    assert _explicit_total_task_count("Create exactly 50 scenario dialogue questions.") == 50
    assert _explicit_total_task_count("Create a total of exactly 20 crystallography questions.") == 20
    assert _explicit_total_task_count("总共出 20 道题，覆盖两种题型。") == 20
    assert _explicit_total_task_count("Create exactly 10 questions in each of 5 domains.") is None


def test_llm_planning_without_a_configured_model_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="does not substitute a local plan"):
        plan_benchmark("Create one benchmark task.", BenchmarkConfig())


def test_plan_audit_enforces_explicit_total() -> None:
    issues = _audit_plan(_plan(task_count=51), expected_task_count=50)

    assert any("requested exactly 50" in issue and "contains 51" in issue for issue in issues)


def test_plan_audit_keeps_multi_turn_out_of_environment_routes() -> None:
    wrong_route = _audit_plan(
        _plan(task_type=TaskType.multi_turn, environment_category="docker_workspace")
    )
    correct_route = _audit_plan(_plan(task_type=TaskType.multi_turn))

    assert any("only valid for agent tasks" in issue for issue in wrong_route)
    assert correct_route == []


def test_plan_audit_requires_multi_turn_followup_mode() -> None:
    issues = _audit_plan(
        _plan(
            task_type=TaskType.multi_turn,
            followup_mode="",
        )
    )

    assert any("followup_mode" in issue for issue in issues)


def test_plan_audit_rejects_environment_for_static_task() -> None:
    issues = _audit_plan(
        _plan(task_type=TaskType.fill_blank, environment_category="docker_workspace")
    )

    assert any("only valid for agent tasks" in issue for issue in issues)


@pytest.mark.parametrize(
    "strategy",
    ["generated", "adapted", "reused", "imported_dataset"],
)
def test_plan_audit_accepts_source_strategies(strategy: str) -> None:
    urls = [] if strategy == "generated" else ["https://example.com/source"]

    assert _audit_plan(_plan(source_strategy=strategy, suggested_urls=urls)) == []


@pytest.mark.parametrize(
    "strategy",
    ["", "self_contained", "source_backed", "mixed", "unsupported"],
)
def test_plan_audit_rejects_unknown_source_strategy(strategy: str) -> None:
    issues = _audit_plan(_plan(source_strategy=strategy))

    assert any("source_plan.strategy must be" in issue for issue in issues)


@pytest.mark.parametrize(
    ("suggested_urls", "search_queries"),
    [(["https://example.com/source"], []), ([], ["source query"])],
)
def test_plan_audit_rejects_sources_for_generated_strategy(
    suggested_urls: list[str],
    search_queries: list[str],
) -> None:
    issues = _audit_plan(
        _plan(
            source_strategy="generated",
            suggested_urls=suggested_urls,
            search_queries=search_queries,
        )
    )

    assert any("requires empty suggested_urls and search_queries" in issue for issue in issues)


@pytest.mark.parametrize("strategy", ["adapted", "reused", "imported_dataset"])
def test_plan_audit_requires_url_for_external_source_strategy(strategy: str) -> None:
    issues = _audit_plan(_plan(source_strategy=strategy))

    assert any("requires at least one suggested URL" in issue for issue in issues)


def test_planner_repairs_wrong_explicit_total(monkeypatch) -> None:
    responses = [_plan(task_count=51), _plan(task_count=50)]
    payloads: list[str] = []

    def fake_tool_loop(user_content, system, config, settings, **kwargs):
        payloads.append(user_content)
        return json.dumps(responses[len(payloads) - 1].model_dump(mode="json"))

    monkeypatch.setattr("evalclaw.planning.task_planner._run_planner_tool_loop", fake_tool_loop)

    plan = plan_benchmark(
        "Create exactly 50 evaluation questions.",
        BenchmarkConfig(**dummy_config_kwargs(), max_planner_iterations=2),
    )

    assert sum(design.task_count for dim in plan.dimensions for design in dim.task_designs) == 50
    assert len(payloads) == 2
    assert "explicitly requested exactly 50 tasks" in payloads[1]


def test_planner_debug_saves_each_raw_attempt(monkeypatch, tmp_path) -> None:
    responses = [_plan(task_count=2), _plan(task_count=1)]
    raw_responses = [
        json.dumps(response.model_dump(mode="json")) for response in responses
    ]

    def fake_tool_loop(user_content, system, config, settings, **kwargs):
        return raw_responses.pop(0)

    monkeypatch.setattr("evalclaw.planning.task_planner._run_planner_tool_loop", fake_tool_loop)

    plan_benchmark(
        "Create exactly 1 benchmark task.",
        BenchmarkConfig(
            **dummy_config_kwargs(),
            max_planner_iterations=2,
            planner_debug_dir=str(tmp_path / "planner-debug"),
        ),
    )

    response_paths = sorted(tmp_path.glob("planner-debug/**/*.response.txt"))
    diagnostic_paths = sorted(tmp_path.glob("planner-debug/**/*.diagnostics.json"))
    assert len(response_paths) == 2
    assert len(diagnostic_paths) == 2
    assert json.loads(response_paths[0].read_text(encoding="utf-8"))["dimensions"][
        0
    ]["task_designs"][0]["task_count"] == 2
    assert json.loads(response_paths[1].read_text(encoding="utf-8"))["dimensions"][
        0
    ]["task_designs"][0]["task_count"] == 1
    assert [
        json.loads(path.read_text(encoding="utf-8"))["status"]
        for path in diagnostic_paths
    ] == ["deterministic_audit_failed", "accepted"]


def test_planner_repairs_removed_dimension_fields(monkeypatch) -> None:
    valid_plan = _plan().model_dump(mode="json")
    stale_plan = json.loads(json.dumps(valid_plan))
    stale_dimension = stale_plan["dimensions"][0]
    stale_dimension["content_requirements"] = ["Cover the requested content."]
    stale_dimension["exclusions"] = ["Exclude unrelated content."]
    responses = [stale_plan, valid_plan]
    payloads: list[str] = []

    def fake_tool_loop(user_content, system, config, settings, **kwargs):
        payloads.append(user_content)
        return json.dumps(responses[len(payloads) - 1])

    monkeypatch.setattr("evalclaw.planning.task_planner._run_planner_tool_loop", fake_tool_loop)

    plan = plan_benchmark(
        "Create exactly one benchmark task.",
        BenchmarkConfig(**dummy_config_kwargs(), max_planner_iterations=2),
    )

    assert len(payloads) == 2
    assert "content_requirements" in payloads[1]
    assert "exclusions" in payloads[1]
    assert plan.dimensions[0].measurement_target == "The requested capability."
    assert plan.dimensions[0].boundary == "Exclude unrelated capabilities."


def test_plan_maps_merged_dimension_fields_without_item_requirements() -> None:
    plan = _plan()

    dimension = plan.to_eval_spec().dimensions[0]

    assert dimension.measurement_target == plan.dimensions[0].measurement_target
    assert dimension.boundary == plan.dimensions[0].boundary
    assert dimension.item_requirements == []


def _multi_design_plan(
    *,
    counts_and_efforts: list[tuple[int, ChallengeEffort]],
) -> BenchmarkPlan:
    return BenchmarkPlan.model_validate(
        {
            "id": "test_plan",
            "objective": "Test the requested capability.",
            "dimensions": [
                {
                    "id": "capability",
                    "name": "Capability",
                    "measurement_target": "The requested capability.",
                    "boundary": "Exclude unrelated capabilities.",
                    "approach": "Measure it directly.",
                    "task_designs": [
                        {
                            "id": f"design-{index}",
                            "task_type": TaskType.generation.value,
                            "task_count": task_count,
                            "challenge_effort": effort.value,
                            "content_design": {"description": "Concrete test cases."},
                            "source_plan": {"strategy": "generated"},
                        }
                        for index, (task_count, effort) in enumerate(counts_and_efforts)
                    ],
                }
            ],
        }
    )


def test_valid_effort_distribution_normalizes_and_validates() -> None:
    assert _valid_effort_distribution({"E1": 0.2, "E2": 0.3, "E3": 0.5}) == {
        ChallengeEffort.E1: 0.2,
        ChallengeEffort.E2: 0.3,
        ChallengeEffort.E3: 0.5,
    }
    assert _valid_effort_distribution({}) == {}
    assert _valid_effort_distribution({"E1": 0.2, "E3": 0.3}) == {}  # sum != 1
    assert _valid_effort_distribution({"E1": -0.2, "E2": 0.7, "E3": 0.5}) == {}
    assert _valid_effort_distribution({"E1": 0.2, "E2": 0.3, "E3": 0.5, "E9": 1.0}) == {
        ChallengeEffort.E1: 0.2,
        ChallengeEffort.E2: 0.3,
        ChallengeEffort.E3: 0.5,
    }  # unknown keys ignored


def test_valid_effort_distribution_accepts_case_insensitive_keys() -> None:
    assert _valid_effort_distribution({"e1": 0.5, "e2": 0.5}) == {
        ChallengeEffort.E1: 0.5,
        ChallengeEffort.E2: 0.5,
    }


def test_plan_audit_accepts_matching_effort_distribution() -> None:
    plan = _multi_design_plan(
        counts_and_efforts=[
            (2, ChallengeEffort.E1),
            (3, ChallengeEffort.E2),
            (5, ChallengeEffort.E3),
        ]
    )
    issues = _audit_plan(
        plan,
        expected_effort_distribution={
            ChallengeEffort.E1: 0.2,
            ChallengeEffort.E2: 0.3,
            ChallengeEffort.E3: 0.5,
        },
    )
    assert issues == []


def test_plan_audit_rejects_mismatched_effort_distribution() -> None:
    plan = _multi_design_plan(
        counts_and_efforts=[
            (10, ChallengeEffort.E3),
        ]
    )
    issues = _audit_plan(
        plan,
        expected_effort_distribution={
            ChallengeEffort.E1: 0.2,
            ChallengeEffort.E2: 0.3,
            ChallengeEffort.E3: 0.5,
        },
    )
    assert any("challenge_effort must match the required distribution" in issue for issue in issues)
    assert any("E1: planned 0 tasks, expected ~2" in issue for issue in issues)


def test_effort_distribution_is_passed_to_planner_constraints(monkeypatch) -> None:
    responses = [_multi_design_plan(counts_and_efforts=[(1, ChallengeEffort.E3)]).model_dump(mode="json")]
    payloads: list[str] = []

    def fake_tool_loop(user_content, system, config, settings, **kwargs):
        payloads.append(user_content)
        return json.dumps(responses[len(payloads) - 1])

    monkeypatch.setattr("evalclaw.planning.task_planner._run_planner_tool_loop", fake_tool_loop)

    plan_benchmark(
        "Create one benchmark task.",
        BenchmarkConfig(
            **dummy_config_kwargs(),
            challenge_effort_distribution={"E1": 0.2, "E2": 0.3, "E3": 0.5},
            max_planner_iterations=1,
        ),
    )

    assert "challenge_effort_distribution" in payloads[0]
    assert '"E1": 0.2' in payloads[0]
    assert '"E3": 0.5' in payloads[0]
    assert "The framework requires the total task count" in payloads[0]
