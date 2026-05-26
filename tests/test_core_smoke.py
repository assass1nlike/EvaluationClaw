from evalclaw.hf_discovery import _expanded_queries
from evalclaw.generator import _parse_items
from evalclaw.hf_ingest import item_from_hf_record
from evalclaw.reporter import build_report
from evalclaw.sandbox import build_code_harness, run_python_sandbox
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkSource,
    Difficulty,
    EvalDimension,
    EvalRun,
    EvalSpec,
    QcReport,
    SourceKind,
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
