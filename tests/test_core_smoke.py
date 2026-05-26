import json

from evalclaw.agent_envs import build_agent_environment
from evalclaw.hf_discovery import _expanded_queries
from evalclaw.generator import _parse_items
from evalclaw.hf_ingest import item_from_hf_record
from evalclaw.planner import plan_eval_spec
from evalclaw.qc import run_qc_gate
from evalclaw.reporter import build_report
from evalclaw.runner import run_question
from evalclaw.sandbox import build_code_harness, run_python_sandbox
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    BenchmarkSource,
    Difficulty,
    EvalDimension,
    EvalRun,
    EvalSpec,
    QcReport,
    ScaleBudget,
    SourceKind,
    TaskType,
    TargetModelConfig,
)


def test_sandbox_runs_in_temp_directory() -> None:
    exit_code, stdout, stderr = run_python_sandbox('assert 1 + 1 == 2\nprint("ok")')

    assert exit_code == 0
    assert stdout.strip() == "ok"
    assert stderr == ""


def test_core_models_fill_defaults() -> None:
    target = TargetModelConfig(provider="deepseek", model="deepseek-v4-flash")
    config = BenchmarkConfig(targets=[target])
    dimension = EvalDimension(
        id="format_following",
        name="Format following",
        description="Checks whether responses follow a requested schema.",
        approach="Use constrained prompts and exact validation.",
    )

    assert target.id == "deepseek-v4-flash"
    assert config.targets[0].provider == "deepseek"
    assert dimension.weight == 1.0


def test_planner_fallback_preserves_scale_budget() -> None:
    config = BenchmarkConfig(
        targets=[TargetModelConfig(provider="mock", model="mock-agent")],
        scale_budget=ScaleBudget.high,
    )

    spec = plan_eval_spec("Evaluate iterative code agents", config)

    assert spec.scale_budget == ScaleBudget.high
    assert spec.scale == 60
    assert all(dimension.target_difficulty == Difficulty.L4 for dimension in spec.dimensions)


def test_code_harness_injects_model_output_as_json_string() -> None:
    harness = build_code_harness("assert {model_output} == 'answer'", "answer")

    assert harness == "assert \"answer\" == 'answer'"


def test_generator_treats_self_generated_source_markers_as_self_generated() -> None:
    dimension = EvalDimension(
        id="math",
        name="Math",
        description="Math reasoning",
        approach="Open proof",
    )
    spec = EvalSpec(objective="Evaluate math reasoning", dimensions=[dimension])

    items, _ = _parse_items(
        {
            "items": [
                {
                    "task_type": "open_generation",
                    "prompt": "Prove that the sum of two even integers is even.",
                    "rubric": "Score for a valid proof.",
                    "source_uri": "https://self_generated",
                    "source_title": "self_generated",
                }
            ]
        },
        spec=spec,
        dimension=dimension,
        requested_count=1,
    )

    assert items[0].source.kind == SourceKind.self_generated
    assert items[0].source.uri == ""


def test_hf_record_ingestion_preserves_provenance() -> None:
    dimension = EvalDimension(
        id="number_theory",
        name="Number theory",
        description="Proof tasks",
        approach="Use rigorous proof",
    )
    source = BenchmarkSource(
        kind=SourceKind.hf_dataset,
        uri="hf://datasets/example/math",
        title="example/math",
    )

    item = item_from_hf_record(
        {
            "problem": "Prove that there are infinitely many primes.",
            "solution": "Assume finitely many primes p1,...,pk. Then p1...pk+1 has a prime divisor not on the list.",
        },
        source=source,
        dimension=dimension,
        difficulty=Difficulty.L4,
        config_name="main",
        split="train",
        row_index=7,
    )

    assert item is not None
    assert item.source.kind == SourceKind.hf_dataset
    assert item.source.uri == "hf://datasets/example/math#split=train&config=main&row=7"
    assert item.metadata["hf_dataset_id"] == "example/math"
    assert item.metadata["hf_config"] == "main"


def test_report_shows_source_coverage() -> None:
    dimension = EvalDimension(
        id="number_theory",
        name="Number theory",
        description="Proof tasks",
        approach="Use rigorous proof",
    )
    spec = EvalSpec(objective="Evaluate math reasoning", dimensions=[dimension])
    item = item_from_hf_record(
        {
            "problem": "Prove that there are infinitely many primes.",
            "solution": "Assume finitely many primes p1,...,pk. Then p1...pk+1 has a prime divisor not on the list.",
        },
        source=BenchmarkSource(
            kind=SourceKind.hf_dataset,
            uri="hf://datasets/example/math",
            title="example/math",
        ),
        dimension=dimension,
        difficulty=Difficulty.L4,
        split="train",
        row_index=1,
    )
    assert item is not None
    dataset = BenchmarkDataset(spec=spec, items=[item], sources=[item.source])
    qc = QcReport(passed_item_ids=[item.id])
    report = build_report(EvalRun(dataset=dataset, qc_report=qc))

    assert "Source-backed items: 1/1" in report.markdown
    assert "item_source:hf_dataset" in report.markdown


def test_static_qc_checks_target_difficulty_coverage() -> None:
    dimension = EvalDimension(
        id="expert_reasoning",
        name="Expert reasoning",
        description="Difficult expert tasks",
        approach="Use high-difficulty prompts",
        target_difficulty=Difficulty.L5,
    )
    spec = EvalSpec(
        objective="Evaluate expert reasoning",
        dimensions=[dimension],
        scale_budget=ScaleBudget.high,
        task_types=[TaskType.open_generation],
    )
    item = BenchmarkItem(
        id="low_difficulty_item",
        dimension_id=dimension.id,
        task_type=TaskType.open_generation,
        prompt="Explain a simple concept clearly.",
        rubric="Score correctness and clarity.",
        difficulty=Difficulty.L3,
    )

    qc = run_qc_gate(BenchmarkDataset(spec=spec, items=[item]), BenchmarkConfig())

    assert any(issue.category.value == "difficulty" for issue in qc.issues)
    assert any("High-budget dimension" in issue.message for issue in qc.issues)


def test_hf_discovery_expands_math_queries() -> None:
    dimension = EvalDimension(
        id="number_theory",
        name="数论",
        description="高难数学证明题",
        approach="Use rigorous proof",
        research_queries=["challenging number theory proof problems with counterexample"],
    )

    queries = _expanded_queries(dimension)

    assert "challenging number theory proof problems with counterexample" in queries
    assert "math reasoning" in queries
    assert "olympiad math" in queries


def test_hf_discovery_expands_known_benchmark_queries() -> None:
    dimension = EvalDimension(
        id="graduate_science_reasoning",
        name="Graduate science reasoning",
        description="Expert biology chemistry and physics reasoning",
        approach="Use published benchmarks",
    )

    queries = _expanded_queries(dimension)

    assert "gpqa" in queries
    assert "mmlu pro" in queries


def test_workspace_agent_environment_scores_goal_completion() -> None:
    item = BenchmarkItem(
        id="agent_item",
        dimension_id="agent",
        task_type=TaskType.agent_interaction,
        prompt="Put the blue notebook in the outgoing bin.",
        rubric="Use deterministic environment scoring.",
        metadata={
            "agent_env": {
                "type": "workspace",
                "start_room": "office",
                "rooms": {"office": ["blue_notebook"], "mailroom": []},
                "goal": {"outgoing_bin": ["blue_notebook"]},
                "max_steps": 4,
            }
        },
    )
    env = build_agent_environment(item)

    env.step({"action": "take", "args": {"item": "blue_notebook"}})
    env.step({"action": "move", "args": {"room": "mailroom"}})
    env.step({"action": "place", "args": {"item": "blue_notebook"}})

    assert env.score() == 1.0
    assert env.state()["outgoing_bin"] == ["blue_notebook"]


def test_agent_interaction_runner_uses_action_observation_loop(monkeypatch) -> None:
    responses = iter(
        [
            '{"action":"take","args":{"item":"blue_notebook"}}',
            '{"action":"move","args":{"room":"mailroom"}}',
            '{"action":"place","args":{"item":"blue_notebook"}}',
        ]
    )

    def fake_call_target_model(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr("evalclaw.runner.call_target_model", fake_call_target_model)
    item = BenchmarkItem(
        id="agent_item",
        dimension_id="agent",
        task_type=TaskType.agent_interaction,
        prompt="Put the blue notebook in the outgoing bin.",
        rubric="Use deterministic environment scoring.",
        metadata={
            "agent_env": {
                "type": "workspace",
                "start_room": "office",
                "rooms": {"office": ["blue_notebook"], "mailroom": []},
                "goal": {"outgoing_bin": ["blue_notebook"]},
                "max_steps": 5,
            }
        },
    )
    config = BenchmarkConfig(targets=[TargetModelConfig(provider="mock", model="mock-agent")])

    result = run_question(item, config)
    trace = json.loads(result.raw_response)

    assert result.score == 1.0
    assert len(trace["trace"]) == 3
    assert trace["final_state"]["outgoing_bin"] == ["blue_notebook"]


def test_code_sandbox_agent_can_revise_after_test_failure(monkeypatch) -> None:
    responses = iter(
        [
            json.dumps(
                {
                    "action": "write_file",
                    "args": {
                        "path": "solution.py",
                        "content": "def max_pair_sum(nums):\n    return max(nums)\n",
                    },
                }
            ),
            '{"action":"run_tests","args":{}}',
            json.dumps(
                {
                    "action": "write_file",
                    "args": {
                        "path": "solution.py",
                        "content": "def max_pair_sum(nums):\n    nums = sorted(nums)\n    return nums[-1] + nums[-2]\n",
                    },
                }
            ),
            '{"action":"run_tests","args":{}}',
        ]
    )

    def fake_call_target_model(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr("evalclaw.runner.call_target_model", fake_call_target_model)
    item = BenchmarkItem(
        id="code_agent_item",
        dimension_id="code_agent",
        task_type=TaskType.agent_interaction,
        prompt="Implement max_pair_sum(nums) and run tests until they pass.",
        rubric="Use deterministic hidden-test scoring.",
        metadata={
            "agent_env": {
                "type": "code_sandbox",
                "visible_files": {"solution.py": "def max_pair_sum(nums):\n    pass\n"},
                "hidden_files": {
                    "tests.py": (
                        "from solution import max_pair_sum\n\n"
                        "assert max_pair_sum([1, 2, 3, 4]) == 7\n"
                        "assert max_pair_sum([-5, -2, -3]) == -5\n"
                    )
                },
                "test_command": "python3 tests.py",
                "max_steps": 6,
            }
        },
    )
    config = BenchmarkConfig(targets=[TargetModelConfig(provider="mock", model="mock-agent")])

    result = run_question(item, config)
    trace = json.loads(result.raw_response)

    assert result.score == 1.0
    assert len(trace["trace"]) == 4
    assert trace["trace"][1]["score_after_step"] == 0.25
    assert trace["trace"][3]["score_after_step"] == 1.0
    assert trace["final_state"]["last_test"]["passed"] is True
