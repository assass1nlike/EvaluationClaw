"""Post-run model-performance analysis with hypothesis-driven probes."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from ..benchmark import build_benchmark_suite_with_qc_loop, build_suite_from_spec_with_qc_loop
from ..diagnostics import new_debug_dir, redact_secrets, write_json
from ..execution.environment_claw import run_environment_claw
from ..execution.plan import build_execution_plan
from ..execution.runner import run_eval
from ..models.llm import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    TargetToolModelResponse,
    call_orchestrator_with_tools,
    extract_json,
)
from ..models.roles import role_model_settings
from ..planning.loop import apply_review_to_suite
from ..planning.task_planner import _audit_plan
from ..protocols.tool import ToolResult
from ..protocols.tool_adapters import (
    evalclaw_tool_result_to_anthropic,
    evalclaw_tool_result_to_openai,
    evalclaw_tool_result_to_openai_response_input,
)
from ..types import (
    AnalysisIteration,
    AnalysisProbeDesign,
    AnalysisReport,
    BenchmarkConfig,
    BenchmarkPlan,
    BenchmarkPlanDimension,
    EvalRun,
    QcReport,
    TaskDesign,
    TaskSuite,
)
from .analysis_tools import ANALYSER_ARTIFACT_TOOL, read_run_artifact

_MAX_ARTIFACT_CALLS = 6

ANALYSER_SYSTEM_PROMPT = """\
You are the EvaluationClaw Analyser. Analyse the evaluated model's behaviour
from the completed benchmark run. Use aggregate results and concrete model
responses to identify supported weaknesses and their likely causes. Do not treat
benchmark-design gaps as model weaknesses.

Your "analysis" is a narrative stating: a summary of what the evidence so far
shows; which model-capability weaknesses are still unconfirmed; the hypothesis
you hold about them; and how you plan to experiment to test that hypothesis.

If you still need evidence, write a focused evaluation goal for that experiment.
The framework runs the goal through the full Planner -> Builder -> Runner
pipeline to produce the probe tasks. Probes are experiments, not adversarial
expansion for its own sake. Write the goal so the Planner designs a small,
focused probe.

Set "done": true only when you have fully identified every model capability
weakness, AND produced a benchmark that covers exactly those weaknesses (so the
model underperforms on it because of genuine inability), AND that benchmark has
already passed one run showing it is itself correct — the model's poor
performance is not caused by flawed, imprecise, or ambiguous tasks. Then leave
"goal" empty. Otherwise set "done": false and give a goal.

QC is not part of the default analysis context. A read_run_artifact tool may be
available. Read the named QC artifact only when you need to determine whether
an observed result was caused by the task or infrastructure rather than the
evaluated model.

Return pure JSON only:
{
  "analysis": "...",
  "goal": "...",
  "done": false
}

The probe's total task count must not exceed max_probe_tasks.
"""


ANALYSER_TASK_DESIGN_PROMPT = """\
You are the EvaluationClaw Analyser. Analyse the evaluated model's behaviour
from the completed benchmark run. Use aggregate results and concrete model
responses to identify supported weaknesses and their likely causes. Do not treat
benchmark-design gaps as model weaknesses.

Your "analysis" is a narrative stating: a summary of what the evidence so far
shows; which model-capability weaknesses are still unconfirmed; the hypothesis
you hold about them; and how you plan to experiment to test that hypothesis.

If you still need evidence, design focused probe tasks that test the hypothesis.
Probes are experiments, not adversarial expansion for its own sake. Return
TaskDesigns for the existing TaskBuilder to materialize; do not construct final
task JSON. Use only dimension ids listed in the request. The framework assigns
all TaskDesign and task ids, so do not return an id.

Each task_designs entry contains dimension_id plus these TaskDesign fields:
task_type, task_count, challenge_effort, content_design, input_requirements,
interaction_requirements, environment_requirements, output_requirements,
scoring_contract, source_plan, construction_requirements,
type_specific_requirements, and metadata. content_design must include a concrete
description or purpose. Non-agent task types must use an empty
environment_requirements object. Agent tasks must declare an environment
category. source_plan.strategy is generated, adapted, reused, or
imported_dataset. generated uses no URLs or search queries; the other strategies
require an existing URL.

Set "done": true only when you have fully identified every model capability
weakness, AND produced a benchmark that covers exactly those weaknesses (so the
model underperforms on it because of genuine inability), AND that benchmark has
already passed one run showing it is itself correct — the model's poor
performance is not caused by flawed, imprecise, or ambiguous tasks. Then leave
"task_designs" empty. Otherwise set "done": false and give task_designs.

Return pure JSON only:
{
  "analysis": "...",
  "task_designs": [],
  "done": false
}

When requesting probes, their total task_count must not exceed max_probe_tasks.
"""


def _analyser_system_prompt(mode: str) -> str:
    return ANALYSER_TASK_DESIGN_PROMPT if mode == "task_design" else ANALYSER_SYSTEM_PROMPT


ANALYSER_REVIEW_SYSTEM_PROMPT = """\
You are the EvaluationClaw Analyser reviewing freshly-built probe tasks before they run.
These probe tasks were materialised from your TaskDesigns to test a hypothesis. Inspect
each probe task and judge whether it faithfully and effectively distinguishes the
hypothesis; fix the ones that do not.

Return pure JSON only:
{
  "done": false,
  "update_items": [{"item_id": "...", "dimension_id": "...", "guidance": "Rewrite this task so that ..."}],
  "delete_item_ids": ["..."],
  "needs_more_items": [{"dimension_id": "...", "count": 1, "guidance": "..."}]
}

Use only the item ids and dimension ids listed in the request. done=true means every
probe task is ready to run; then leave the three lists empty. Do not restructure
dimensions — only fix the probe tasks themselves.
"""


def _append_tool_results(
    messages: list[dict[str, Any]],
    response: TargetToolModelResponse,
    results: list[ToolResult],
) -> None:
    messages.append(response.assistant_message)
    if response.adapter == "anthropic":
        messages.append(
            {
                "role": "user",
                "content": [evalclaw_tool_result_to_anthropic(result) for result in results],
            }
        )
        return
    if response.adapter == "openai_responses":
        messages.pop()
        output = response.assistant_message.get("responses_output")
        if isinstance(output, list):
            messages.extend(item for item in output if isinstance(item, dict))
        messages.extend(evalclaw_tool_result_to_openai_response_input(result) for result in results)
        return
    messages.extend(evalclaw_tool_result_to_openai(result) for result in results)


def _run_analyser_tool_loop(
    payload: dict[str, Any],
    config: BenchmarkConfig,
    *,
    trace_dir: Path | None,
    artifact_dir: Path | None,
    system_prompt: str = ANALYSER_SYSTEM_PROMPT,
) -> dict[str, Any]:
    settings = role_model_settings(config, "analyser")
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}
    ]
    calls_used = 0
    while True:
        tools = [ANALYSER_ARTIFACT_TOOL] if artifact_dir is not None and calls_used < _MAX_ARTIFACT_CALLS else []
        response = call_orchestrator_with_tools(
            messages,
            system_prompt=system_prompt,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            tools=tools,
            max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            retry_on_truncation=True,
            expect_json=not tools,
            trace_dir=trace_dir / "llm" if trace_dir is not None else None,
            trace_name="analyser",
        )
        if not response.tool_calls:
            if not response.content.strip():
                raise ValueError("Analyser returned empty final content.")
            return extract_json(response.content)

        remaining = _MAX_ARTIFACT_CALLS - calls_used
        selected = response.tool_calls[:remaining]
        if not selected:
            messages.append(response.assistant_message)
            messages.append(
                {
                    "role": "user",
                    "content": "The artifact-read budget is exhausted. Return the final analysis JSON now.",
                }
            )
            continue
        results = [read_run_artifact(call, artifact_dir) for call in selected]
        calls_used += len(selected)
        _append_tool_results(messages, response, results)
        if calls_used >= _MAX_ARTIFACT_CALLS:
            messages.append(
                {
                    "role": "user",
                    "content": "The artifact-read budget is exhausted. Return the final analysis JSON now.",
                }
            )


def _call_analyser_json(
    payload: dict[str, Any],
    config: BenchmarkConfig,
    *,
    trace_dir: Path | None = None,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    return _run_analyser_tool_loop(
        payload,
        config,
        trace_dir=trace_dir,
        artifact_dir=artifact_dir,
        system_prompt=_analyser_system_prompt(
            str(getattr(config, "analysis_probe_mode", "goal"))
        ),
    )


def _task_context(suite: TaskSuite) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for item in suite.tasks:
        payload = item.model_dump(mode="json")
        if item.source_definition is not None:
            payload["definition"] = item.source_definition.model_dump(mode="json")
        tasks.append(redact_secrets(payload))
    return tasks


def _run_context(run: EvalRun) -> dict[str, Any]:
    return {
        "summaries": [summary.model_dump(mode="json") for summary in run.summaries],
        "results": [result.model_dump(mode="json") for result in run.results],
        "runner_artifacts": redact_secrets(run.runner_artifacts),
    }


def _analysis_payload(
    suite: TaskSuite,
    run: EvalRun,
    iterations: list[AnalysisIteration],
    config: BenchmarkConfig,
    *,
    artifact_dir: Path | None,
) -> dict[str, Any]:
    history = []
    for iteration in iterations:
        history.append(
            {
                "iteration": iteration.iteration,
                "analysis": iteration.analysis,
                "goal": iteration.goal,
                "task_designs": [
                    design.model_dump(mode="json") for design in iteration.task_designs
                ],
                "tasks": _task_context(iteration.suite) if iteration.suite is not None else [],
                "run": _run_context(iteration.run) if iteration.run is not None else {},
            }
        )
    payload: dict[str, Any] = {
        "benchmark": {
            "objective": suite.spec.objective,
            "dimensions": [
                {
                    "id": dimension.id,
                    "name": dimension.name,
                    "measurement_target": dimension.measurement_target,
                    "boundary": dimension.boundary,
                    "approach": dimension.approach,
                }
                for dimension in suite.spec.dimensions
            ],
            "tasks": _task_context(suite),
        },
        "main_run": _run_context(run),
        "verification_history": history,
        "remaining_probe_iterations": max(0, config.analysis_iterations - len(iterations)),
        "max_probe_tasks": max(0, config.analysis_max_tasks),
    }
    if artifact_dir is not None:
        payload["available_artifacts"] = {
            "qc_report": "qc_report.json",
            "target_run": "run.json",
            "construction": "construction.json",
            "analysis": "analysis/",
        }
    return payload


def _parse_response(
    data: dict[str, Any],
    suite: TaskSuite,
    config: BenchmarkConfig,
    *,
    iteration: int,
    remaining_probe_iterations: int,
) -> tuple[str, str, bool, list[AnalysisProbeDesign]]:
    analysis = str(data.get("analysis") or "").strip()
    if not analysis:
        raise ValueError("Analyser response requires a non-empty analysis.")

    done = bool(data.get("done"))
    if done:
        return analysis, "", True, []

    mode = str(getattr(config, "analysis_probe_mode", "goal"))
    goal = ""
    designs: list[AnalysisProbeDesign] = []

    if mode == "task_design":
        raw_designs = data.get("task_designs", [])
        if not isinstance(raw_designs, list):
            raise ValueError("Analyser task_designs must be a list.")
        if raw_designs and remaining_probe_iterations <= 0:
            raise ValueError(
                "Analyser returned TaskDesigns after the probe-iteration budget was exhausted."
            )
        known_dimensions = {dimension.id for dimension in suite.spec.dimensions}
        total_tasks = 0
        for index, raw in enumerate(raw_designs, 1):
            if not isinstance(raw, dict):
                raise ValueError(f"Analyser task_designs entry {index} must be an object.")
            if "id" in raw:
                raise ValueError("Analyser must not assign TaskDesign ids.")
            dimension_id = str(raw.get("dimension_id") or "").strip()
            if dimension_id not in known_dimensions:
                raise ValueError(
                    f"Analyser task_designs entry {index} references unknown dimension {dimension_id!r}."
                )
            design_payload = {key: value for key, value in raw.items() if key != "dimension_id"}
            design = TaskDesign(
                id=f"analysis_{iteration:02d}_design_{index:02d}",
                **design_payload,
            )
            total_tasks += design.task_count
            designs.append(AnalysisProbeDesign(dimension_id=dimension_id, task_design=design))
        max_tasks = max(0, int(config.analysis_max_tasks))
        if total_tasks > max_tasks:
            raise ValueError(
                f"Analyser requested {total_tasks} probe tasks, exceeding analysis_max_tasks={max_tasks}."
            )
    else:
        raw_goal = data.get("goal")
        if not isinstance(raw_goal, str) or not raw_goal.strip():
            raise ValueError("Analyser response requires a non-empty goal when done=false.")
        goal = raw_goal.strip()
        if remaining_probe_iterations <= 0:
            raise ValueError("Analyser returned a goal after the probe-iteration budget was exhausted.")

    if not goal and not designs:
        raise ValueError("Analyser response with done=false must include a goal or task_designs.")

    return analysis, goal, False, designs


def _probe_plan(
    suite: TaskSuite,
    task_designs: list[AnalysisProbeDesign],
    *,
    iteration: int,
) -> BenchmarkPlan:
    by_dimension: dict[str, list[TaskDesign]] = defaultdict(list)
    for probe in task_designs:
        by_dimension[probe.dimension_id].append(probe.task_design)
    source_dimensions = {dimension.id: dimension for dimension in suite.spec.dimensions}
    dimensions = []
    for dimension_id, designs in by_dimension.items():
        dimension = source_dimensions[dimension_id]
        dimensions.append(
            BenchmarkPlanDimension(
                id=dimension.id,
                name=dimension.name,
                measurement_target=dimension.measurement_target,
                boundary=dimension.boundary,
                approach=dimension.approach,
                task_designs=designs,
            )
        )
    plan = BenchmarkPlan(
        id=f"{suite.spec.id}_analysis_{iteration:02d}",
        objective=suite.spec.objective,
        constraints=list(suite.spec.constraints),
        planner_notes="Hypothesis-driven verification tasks designed by the Analyser.",
        dimensions=dimensions,
        subjects=list(suite.spec.subjects),
        scale_budget=suite.spec.scale_budget,
    )
    issues = _audit_plan(plan)
    if issues:
        raise ValueError("Invalid Analyser TaskDesigns: " + " ".join(issues))
    return plan


def _review_probes(
    probe_suite: TaskSuite,
    analysis: str,
    config: BenchmarkConfig,
    *,
    trace_dir: Path | None,
) -> dict[str, Any]:
    """Ask the analyser to review freshly-built probe tasks, returning a review dict."""
    payload = {
        "hypothesis": analysis,
        "tasks": _task_context(probe_suite),
    }
    data = _run_analyser_tool_loop(
        payload,
        config,
        trace_dir=trace_dir,
        artifact_dir=None,
        system_prompt=ANALYSER_REVIEW_SYSTEM_PROMPT,
    )
    if not isinstance(data, dict):
        raise ValueError("Analyser review must be a JSON object.")
    if "done" not in data:
        raise ValueError("Analyser review requires a done field.")
    return data


def _build_and_run_probes(
    main_suite: TaskSuite,
    config: BenchmarkConfig,
    analysis: str,
    goal: str,
    task_designs: list[AnalysisProbeDesign],
    *,
    iteration: int,
    trace_dir: Path | None,
    log: Callable[[str], None],
) -> tuple[TaskSuite, QcReport, EvalRun]:
    if goal:
        probe_suite, probe_qc = build_benchmark_suite_with_qc_loop(
            goal,
            config,
            log=log,
            trace_dir=trace_dir / "construction" if trace_dir is not None else None,
        )
        max_tasks = max(0, int(config.analysis_max_tasks))
        if len(probe_suite.tasks) > max_tasks:
            raise ValueError(
                f"Goal-mode probe produced {len(probe_suite.tasks)} tasks, exceeding "
                f"analysis_max_tasks={max_tasks}."
            )
    else:
        plan = _probe_plan(main_suite, task_designs, iteration=iteration)
        spec = plan.to_eval_spec()
        original_dimensions = {dimension.id: dimension for dimension in main_suite.spec.dimensions}
        spec = spec.model_copy(
            update={
                "dimensions": [
                    dimension.model_copy(
                        update={
                            "description": original_dimensions[dimension.id].description,
                            "weight": original_dimensions[dimension.id].weight,
                            "item_requirements": list(
                                original_dimensions[dimension.id].item_requirements
                            ),
                        }
                    )
                    for dimension in spec.dimensions
                ]
            }
        )
        probe_suite, probe_qc = build_suite_from_spec_with_qc_loop(
            spec,
            plan.builder_jobs,
            config,
            log=log,
            trace_dir=trace_dir / "construction" if trace_dir is not None else None,
        )
        probe_suite.plan = plan
    for review_index in range(
        max(0, int(getattr(config, "analysis_review_max_iterations", 3) or 0))
    ):
        review_trace = (
            trace_dir / f"review-{review_index + 1:02d}" if trace_dir is not None else None
        )
        review = _review_probes(probe_suite, analysis, config, trace_dir=review_trace)
        if review.get("done"):
            if log:
                log(f"  [Analysis] probe review accepted after {review_index + 1} pass(es).")
            break
        if log:
            log(f"  [Analysis] probe review requested changes (pass {review_index + 1}).")
        probe_suite, probe_qc = apply_review_to_suite(
            probe_suite,
            review,
            probe_qc,
            config,
            log=log,
            trace_dir=review_trace,
        )
    execution_plan = build_execution_plan(probe_suite, probe_qc)
    environment_config = config.model_copy(update={"environment_preflight": False})
    run_config, environment_report = run_environment_claw(
        execution_plan.suite.tasks,
        environment_config,
    )
    if environment_report.blocking_errors:
        raise RuntimeError("\n\n".join(environment_report.blocking_errors))
    if trace_dir is not None:
        write_json(trace_dir / "environment.json", environment_report.as_dict())
    probe_run = run_eval(
        probe_suite,
        probe_qc,
        run_config,
        trace_dir=trace_dir / "runner" if trace_dir is not None else None,
    )
    probe_run.runner_artifacts["environment_claw"] = environment_report.as_dict()
    return probe_suite, probe_qc, probe_run


def _load_iterations(root: Path | None) -> list[AnalysisIteration]:
    if root is None or not root.is_dir():
        return []
    iterations: list[AnalysisIteration] = []
    for path in sorted(root.glob("iteration-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            iterations.append(AnalysisIteration.model_validate(payload))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return iterations


def run_analysis(
    suite: TaskSuite,
    run: EvalRun,
    config: BenchmarkConfig,
    *,
    artifact_dir: Path | None = None,
    log: Callable[[str], None] = print,
) -> AnalysisReport:
    """Analyse a completed run and execute only probes needed to resolve hypotheses."""
    if not role_model_settings(config, "analyser").configured:
        raise RuntimeError("Analysis requires a configured Analyser model.")
    if not run.results:
        raise RuntimeError("Analysis requires target-model results from the main benchmark run.")

    root = artifact_dir / "analysis" if artifact_dir is not None else new_debug_dir(config.output_dir, "analysis")
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        report_path = root / "report.json"
        if report_path.is_file():
            try:
                return AnalysisReport.model_validate_json(report_path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError):
                pass
    iterations = _load_iterations(root)

    while True:
        next_iteration = len(iterations) + 1
        remaining = max(0, config.analysis_iterations - len(iterations))
        call_dir = root / f"analyser-{next_iteration:02d}" if root is not None else None
        payload = _analysis_payload(
            suite,
            run,
            iterations,
            config,
            artifact_dir=artifact_dir,
        )
        if call_dir is not None:
            write_json(call_dir / "request.json", payload)
        log(
            f"  [Analysis] Analyser call {next_iteration}; "
            f"remaining probe iterations: {remaining}."
        )
        data = _call_analyser_json(
            payload,
            config,
            trace_dir=call_dir,
            artifact_dir=artifact_dir,
        )
        if call_dir is not None:
            write_json(call_dir / "response.json", data)
        analysis, goal, done, task_designs = _parse_response(
            data,
            suite,
            config,
            iteration=next_iteration,
            remaining_probe_iterations=remaining,
        )
        if done:
            report = AnalysisReport(
                analysis=analysis,
                iterations=iterations,
            )
            if root is not None:
                write_json(root / "report.json", report.model_dump(mode="json"))
            return report

        iteration_dir = root / f"iteration-{next_iteration:02d}" if root is not None else None
        if task_designs:
            probe_desc = (
                f"{sum(item.task_design.task_count for item in task_designs)} "
                "hypothesis-driven probe task(s)"
            )
        else:
            probe_desc = "a goal-driven probe"
        log(f"  [Analysis] Building {probe_desc}.")
        probe_suite, probe_qc, probe_run = _build_and_run_probes(
            suite,
            config,
            analysis,
            goal,
            task_designs,
            iteration=next_iteration,
            trace_dir=iteration_dir,
            log=log,
        )
        completed = AnalysisIteration(
            iteration=next_iteration,
            analysis=analysis,
            goal=goal,
            task_designs=task_designs,
            suite=probe_suite,
            qc_report=probe_qc,
            run=probe_run,
        )
        iterations.append(completed)
        if root is not None:
            write_json(
                root / f"iteration-{next_iteration:02d}.json",
                completed.model_dump(mode="json"),
            )


__all__ = [
    "ANALYSER_SYSTEM_PROMPT",
    "run_analysis",
]
