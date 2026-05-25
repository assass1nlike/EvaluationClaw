from evalclaw.sandbox import build_code_harness, run_python_sandbox
from evalclaw.types import BenchmarkConfig, EvalDimension, TargetModelConfig


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
