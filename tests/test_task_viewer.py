import json
from pathlib import Path

from evalclaw.pipeline import _persist_package
from evalclaw.reporting.reporter import build_report
from evalclaw.reporting.task_viewer import _task_payload, build_task_viewer_html
from evalclaw.types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    BenchmarkConfig,
    BenchmarkItem,
    BenchmarkPackage,
    BenchmarkSource,
    ChoiceOption,
    EvalDimension,
    EvalReport,
    EvalRun,
    EvalSpec,
    QcReport,
    SourceKind,
    TaskDefinition,
    TaskSuite,
    TaskType,
)


def _package_with_all_task_types() -> BenchmarkPackage:
    dimension = EvalDimension(
        id="core",
        name="Core capability",
        description="Measure the capability.",
        approach="Use representative tasks.",
    )
    spec = EvalSpec(id="task_viewer_eval", objective="Browse generated tasks.", dimensions=[dimension])
    definitions = [
        TaskDefinition(
            id="choice-1",
            dimension_id=dimension.id,
            task_type=TaskType.choice,
            title="Choice task",
            prompt="Choose the correct option.",
            choices=[ChoiceOption(id="a", text="First option")],
            correct_choice_ids=["a"],
        ),
        TaskDefinition(
            id="blank-1",
            dimension_id=dimension.id,
            task_type=TaskType.fill_blank,
            title="Fill task",
            prompt="Complete the expression.",
            expected_texts=["x = 1"],
        ),
        TaskDefinition(
            id="generation-1",
            dimension_id=dimension.id,
            task_type=TaskType.generation,
            title="Generation task",
            prompt="Explain the result.",
            rubric="The explanation is correct.",
        ),
        TaskDefinition(
            id="dialogue-1",
            dimension_id=dimension.id,
            task_type=TaskType.multi_turn,
            title="Dialogue task",
            prompt="Respond over several turns.",
            interaction={"max_turns": 3},
        ),
        TaskDefinition(
            id="agent-1",
            dimension_id=dimension.id,
            task_type=TaskType.agent,
            title="Agent task",
            prompt="Inspect the workspace and finish the task.",
            system_prompt="Act as a careful coding agent.",
            environment=AgentEnvironmentSpec(
                type=AgentEnvironmentType.docker_workspace,
                visible_files={"input.txt": "input"},
                test_command="python tests.py",
            ),
        ),
    ]
    items = [
        BenchmarkItem(
            id=definition.id,
            dimension_id=definition.dimension_id,
            task_type=definition.task_type,
            prompt=definition.prompt,
            choices=definition.choices,
            correct_choice_ids=definition.correct_choice_ids,
            expected_texts=definition.expected_texts,
            rubric=definition.rubric,
            source=BenchmarkSource(kind=SourceKind.self_generated, title=definition.title),
            source_definition=definition,
            metadata=(
                {"agent_env": definition.environment.model_dump(mode="json")}
                if definition.environment is not None
                else {}
            ),
        )
        for definition in definitions
    ]
    suite = TaskSuite(
        spec=spec,
        objective=spec.objective,
        dimensions=[dimension],
        tasks=items,
    )
    run = EvalRun(suite=suite, qc_report=QcReport(passed_item_ids=[item.id for item in items]))
    return BenchmarkPackage(
        goal=spec.objective,
        spec=spec,
        suite=suite,
        qc_report=run.qc_report,
        run=run,
        report=build_report(run),
    )


def test_task_viewer_renders_all_task_types_and_task_fields() -> None:
    html = build_task_viewer_html(_package_with_all_task_types())

    for expected in [
        "Choice task",
        "Fill task",
        "Generation task",
        "Dialogue task",
        "Agent task",
        "First option",
        "Correct choice IDs",
        "x = 1",
        "Act as a careful coding agent.",
        "Execution environment",
        "python tests.py",
    ]:
        assert expected in html
    assert "EvaluationClaw Diagnostic Report" not in html


def test_task_viewer_labels_non_agent_image_assets(tmp_path: Path) -> None:
    image_path = tmp_path / "private" / "scene.png"
    image_path.parent.mkdir()
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    dimension = EvalDimension(
        id="vision", name="Vision", description="Measure vision.", approach="Use images."
    )
    spec = EvalSpec(id="vision_eval", objective="Browse images.", dimensions=[dimension])
    definition = TaskDefinition(
        id="vision-1",
        dimension_id="vision",
        task_type=TaskType.choice,
        title="Image choice",
        prompt=f"Inspect {image_path}.",
        assets=[{"path": str(image_path)}],
        choices=[ChoiceOption(id="a", text=str(image_path))],
        correct_choice_ids=["a"],
    )
    item = BenchmarkItem(
        id=definition.id,
        dimension_id=definition.dimension_id,
        task_type=definition.task_type,
        prompt=definition.prompt,
        assets=definition.assets,
        choices=definition.choices,
        correct_choice_ids=definition.correct_choice_ids,
        source_definition=definition,
    )
    suite = TaskSuite(spec=spec, objective=spec.objective, dimensions=[dimension], tasks=[item])
    package = BenchmarkPackage(
        goal=spec.objective,
        spec=spec,
        suite=suite,
        qc_report=QcReport(passed_item_ids=[item.id]),
        run=EvalRun(suite=suite, qc_report=QcReport(passed_item_ids=[item.id])),
        report=build_report(EvalRun(suite=suite, qc_report=QcReport(passed_item_ids=[item.id]))),
    )

    payload = _task_payload(package)
    html = build_task_viewer_html(package)

    assert payload["tasks"][0]["prompt"] == "Inspect Image 1."
    assert payload["tasks"][0]["choices"][0]["text"] == "Image 1"
    assert "Image 1" in html


def test_persist_package_writes_task_viewer_artifact(tmp_path) -> None:
    package = _package_with_all_task_types()
    _persist_package(package, BenchmarkConfig(), str(tmp_path), log=lambda _message: None)

    task_pages = list(tmp_path.glob("tasks_*.html"))
    assert len(task_pages) == 1
    assert "Task Browser" in task_pages[0].read_text(encoding="utf-8")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["task_viewer"] == str(task_pages[0])
    report_text = next(tmp_path.glob("evalclaw_*.md")).read_text(encoding="utf-8")
    assert "task_viewer_html" in report_text
