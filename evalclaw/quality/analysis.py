"""Post-run model-performance analysis with hypothesis-driven probes."""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Any, Callable

from ..benchmark import build_benchmark_suite_with_qc_loop, build_suite_from_spec_with_qc_loop
from ..diagnostics import error_record, new_debug_dir, redact_secrets, write_json
from ..execution.environment_claw import run_environment_claw
from ..execution.plan import build_execution_plan, exclude_blocked_items
from ..execution.runner import run_eval
from ..models.llm import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    LLMFinalContentMissingError,
    TargetToolModelResponse,
    call_orchestrator_with_tools,
    extract_json,
)
from ..models.roles import role_model_settings
from ..planning.loop import _apply_review, apply_review_to_suite
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
from .analysis_tools import (
    ANALYSER_ARTIFACT_LIST_TOOL,
    ANALYSER_ARTIFACT_TOOL,
    ANALYSER_ITEM_EVIDENCE_TOOL,
    list_run_artifacts,
    read_item_evidence,
    read_run_artifact,
)

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
focused probe. You may specify the task type, task count, and challenge effort
level — per task or for the probe as a whole — according to what your hypothesis
needs. The three effort levels are:

- E1 (simple construction): meaningfully challenging, but below research-level depth.
- E2 (difficult construction): requires a non-obvious insight or a multi-step rigorous argument.
- E3 (maximum construction effort): extremely difficult; demands broad knowledge,
  tedious reasoning, or bold hypotheses, using every technique to raise difficulty.

State these in the goal so the Planner materializes the probe as intended.

Set "done": true only when you have fully identified every model capability
weakness, AND produced a benchmark that covers exactly those weaknesses (so the
model underperforms on it because of genuine inability), AND that benchmark has
already passed one run showing it is itself correct — the model's poor
performance is not caused by flawed, imprecise, or ambiguous tasks. Then leave
"goal" empty. Otherwise set "done": false and give a goal.

QC is not part of the default analysis context. Three read-only tools may be
available: list_run_artifacts discovers saved evidence, read_run_artifact reads a named artifact (read the QC artifact
only when you need to determine whether an observed result was caused by the
task or infrastructure rather than the evaluated model), and read_item_evidence
reads one main-run or probe item's task, QC, full raw response, and judge reasoning.
Use these only when the request payload is not enough.

For agent tasks, the request includes the task prompt and an environment
contract summary. Use the score, error, and judge reasoning as the initial
explanation of failure. If those do not establish whether the model or the
environment caused it, use the read-only tools to inspect the complete
trajectory, evaluator output, and other saved artifacts. Do not infer a
capability weakness from failed setup, evaluator errors, or ambiguous tasks.
The default raw response is a bounded head-and-tail excerpt, so its final
answer and closing actions remain visible; use read_item_evidence for the full
response when intermediate actions matter.

Return pure JSON only:
{
  "analysis": "...",
  "goal": "...",
  "done": false
}

The probe's total task count must not exceed max_probe_tasks. When
remaining_probe_iterations is zero, do not give a goal — set "done": true and state your
conclusion in analysis.
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

The supplied responses may be bounded excerpts. When necessary, use read_item_evidence to inspect
a main-run or probe item, list_run_artifacts to discover saved execution evidence, and
read_run_artifact to inspect it. Do not infer model weakness from invalid tasks, failed setup,
evaluator errors, harness errors, or infrastructure-caused timeouts.

Return pure JSON only:
{
  "analysis": "...",
  "task_designs": [],
  "done": false
}

When requesting probes, their total task_count must not exceed max_probe_tasks. When
remaining_probe_iterations is zero, do not give task_designs — set "done": true and state
your conclusion in analysis.
"""


SIMILAR_TASKS_ABLATION_PROMPT = """\
You are the EvaluationClaw Analyser that maximizes the target model's error rate by creating tasks
similar to existing failed tasks.

Use all target-model results observed so far, including the initial benchmark and every completed
iteration. Identify the tasks on which the target model performed poorly.

Request new tasks that are similar to the failed tasks. Similarity may involve subject matter, task
format, required operations, tool-interaction patterns, or core difficulty. The new tasks should be
distinct, independently valid instances rather than simple copies, paraphrases, or answer-preserving
rewrites of the originals.

Expand the tasks based on observed existing failures. Do not infer a latent capability weakness or
propose tasks based on hypothetical, unobserved failures.

Do not treat benchmark defects, evaluator failures, harness errors, infrastructure-caused timeouts,
or invalid tasks as evidence of poor model capability.

The supplied responses may be bounded excerpts. When necessary, use read_item_evidence to inspect
a main-run or probe item, list_run_artifacts to discover saved execution evidence, and
read_run_artifact to inspect it.

Continue until the budget is exhausted or no useful new tasks can be generated from existing failed
tasks. Then set done=true and request no additional tasks.
"""


def _similar_tasks_analyser_prompt(mode: str) -> str:
    if mode == "task_design":
        output_instruction = """\
Return TaskDesigns for the existing TaskBuilder to materialize. Use only dimension ids listed
in the request. The framework assigns ids, so do not return an id. Each task_designs entry
contains dimension_id plus: task_type, task_count, challenge_effort, content_design,
input_requirements, interaction_requirements, environment_requirements, output_requirements,
scoring_contract, source_plan, construction_requirements, type_specific_requirements, and
metadata. The total task_count must not exceed max_probe_tasks.

Return pure JSON only:
{"analysis": "...", "task_designs": [], "done": false}"""
    else:
        output_instruction = """\
When more tasks are needed, return a focused evaluation goal describing the benchmark to construct.
This goal serves as an instruction for the Planner to create tasks similar to the identified failed
tasks. State the observable properties that should be preserved and those that should vary. The goal
may specify task type, count, and E1/E2/E3 challenge effort. Its total task count must not exceed
max_probe_tasks.

Return pure JSON only:
{"analysis": "...", "goal": "...", "done": false}"""
    return f"{SIMILAR_TASKS_ABLATION_PROMPT}\n{output_instruction}\n"


def _analyser_system_prompt(mode: str, ablation: str = "none") -> str:
    if ablation == "similar_tasks":
        return _similar_tasks_analyser_prompt(mode)
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
Keep the total planned task count within max_probe_tasks, including any requested additions.
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
    validate: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    settings = role_model_settings(config, "analyser")
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}
    ]
    calls_used = 0
    repairs_used = 0
    while True:
        tools = (
            [
                ANALYSER_ARTIFACT_TOOL,
                ANALYSER_ARTIFACT_LIST_TOOL,
                ANALYSER_ITEM_EVIDENCE_TOOL,
            ]
            if artifact_dir is not None and calls_used < _MAX_ARTIFACT_CALLS
            else []
        )
        response = None
        try:
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
                data = extract_json(response.content)
                if not isinstance(data, dict):
                    raise ValueError("Analyser response must be a JSON object.")
                if validate is not None:
                    validate(data)
                return data
        except (ValueError, LLMFinalContentMissingError) as exc:
            if repairs_used >= 1:
                raise
            repairs_used += 1
            if response is not None:
                messages.append(response.assistant_message)
            messages.append({
                "role": "user",
                "content": (
                    f"The response could not be accepted: {exc}. Return the required JSON. "
                    "Preserve your substantive judgment, including any refusal or limitation; "
                    "do not invent evidence or claim success to satisfy the format."
                ),
            })
            continue

        remaining = max(0, _MAX_ARTIFACT_CALLS - calls_used)
        selected = response.tool_calls[:remaining]
        if not selected:
            raise ValueError("Analyser requested tools after its artifact-read budget was exhausted.")
        handlers = {
            ANALYSER_ARTIFACT_TOOL.name: read_run_artifact,
            ANALYSER_ARTIFACT_LIST_TOOL.name: list_run_artifacts,
            ANALYSER_ITEM_EVIDENCE_TOOL.name: read_item_evidence,
        }
        results = [
            handlers[call.name](call, artifact_dir)
            if call.name in handlers
            else ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=f"Unknown analyser tool: {call.name}",
                error="unknown_tool",
            )
            for call in selected
        ]
        results.extend(
            ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content="The artifact-read budget is exhausted.",
                error="tool_budget_exhausted",
            )
            for call in response.tool_calls[len(selected):]
        )
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
    validate: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    return _run_analyser_tool_loop(
        payload,
        config,
        trace_dir=trace_dir,
        artifact_dir=artifact_dir,
        validate=validate,
        system_prompt=_analyser_system_prompt(
            str(getattr(config, "analysis_probe_mode", "goal")),
            config.ablation_analyser,
        ),
    )


_RAW_RESPONSE_LIMIT = 2000


def _truncate(value: str, limit: int = _RAW_RESPONSE_LIMIT) -> str:
    if len(value) <= limit:
        return value
    # Agent traces often put the useful final answer and failure summary at the
    # end. Keep both ends in the default context; the evidence tool exposes the
    # complete response when the analyser needs it.
    head = limit // 2
    tail = limit - head
    omitted = len(value) - limit
    return value[:head] + f"... [truncated {omitted} chars] ..." + value[-tail:]


def _task_context(suite: TaskSuite) -> list[dict[str, Any]]:
    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): "[redacted]"
                if any(token in str(key).lower() for token in ("key", "token", "secret", "password", "credential"))
                else redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    def agent_environment(item: Any) -> dict[str, Any] | None:
        raw = item.metadata.get("agent_env")
        if not isinstance(raw, dict):
            return None
        # Give the analyser the executable contract and file layout, while keeping
        # hidden answers, credentials, and runtime payloads behind the evidence tool.
        safe: dict[str, Any] = {}
        for key in (
            "type", "image", "network", "resource_limits", "test_command",
            "setup_commands", "evaluation", "vm", "browser",
        ):
            value = raw.get(key)
            if value is not None:
                safe[key] = redact(value)
        for key in ("visible_files", "hidden_files", "runtime_files"):
            value = raw.get(key)
            if isinstance(value, dict):
                safe[key + "_paths"] = sorted(str(path) for path in value)
        image_build = raw.get("image_build")
        if isinstance(image_build, dict):
                safe["image_build"] = redact({
                    key: value for key, value in image_build.items()
                    if key in {"image", "dockerfile", "context_dir", "build_args"}
                })
        return safe

    tasks: list[dict[str, Any]] = []
    for item in suite.tasks:
        context = {
                "id": item.id,
                "dimension_id": item.dimension_id,
                "task_type": item.task_type.value,
                "challenge_effort": item.challenge_effort.value,
                "prompt": item.prompt,
                "choices": [choice.model_dump(mode="json") for choice in item.choices],
                "correct_choice_ids": list(item.correct_choice_ids),
                "expected_texts": list(item.expected_texts),
                "reference_answer": item.reference_answer,
                "reference_trajectory": [
                    step.model_dump(mode="json") for step in item.reference_trajectory
                ],
                "rubric": item.rubric,
            }
        environment = agent_environment(item)
        if environment is not None:
            context["agent_environment"] = environment
            context["agent_task_contract"] = {
                "environment_type": environment.get("type", "docker_workspace"),
                "visible_file_paths": environment.get("visible_files_paths", []),
                "evaluation": environment.get("evaluation", {}),
            }
        tasks.append(context)
    return tasks


def _run_context(run: EvalRun) -> dict[str, Any]:
    def priority(result: Any) -> tuple[int, float, str, str]:
        if result.error:
            group = 0
        elif result.score < 1.0:
            group = 1
        else:
            group = 2
        return group, result.score, result.target_id, result.item_id

    return {
        "summaries": [summary.model_dump(mode="json") for summary in run.summaries],
        "results": [
            {
                "item_id": result.item_id,
                "target_id": result.target_id,
                "score": result.score,
                "judge_reasoning": result.judge_reasoning,
                "error": result.error,
                "latency_ms": result.latency_ms,
                "failure_evidence": {
                    "failed": bool(result.error) or result.score < 1.0,
                    "score": result.score,
                    "reason": result.error or result.judge_reasoning,
                },
                "raw_response": _truncate(result.raw_response),
            }
            for result in sorted(run.results, key=priority)
        ],
    }


def _analysis_max_tasks(config: BenchmarkConfig, suite: TaskSuite) -> int:
    """Probe-task cap: explicit config, else half the main run's task count (floored)."""
    configured = config.analysis_max_tasks
    if configured is not None:
        return max(0, int(configured))
    return len(suite.tasks) // 2


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
                    "task_designs": [
                        {
                            "id": design.id,
                            "task_type": design.task_type.value,
                            "task_count": design.task_count,
                            "challenge_effort": design.challenge_effort.value,
                            "content_design": design.content_design,
                        }
                        for blueprint in suite.blueprints
                        if blueprint.dimension_id == dimension.id
                        for design in blueprint.task_designs
                    ],
                }
                for dimension in suite.spec.dimensions
            ],
            "tasks": _task_context(suite),
        },
        "main_run": _run_context(run),
        "verification_history": history,
        "remaining_probe_iterations": max(0, config.analysis_iterations - len(iterations)),
        "max_probe_tasks": _analysis_max_tasks(config, suite),
    }
    if artifact_dir is not None:
        payload["available_artifacts"] = {
            "index_tool": "list_run_artifacts",
            "qc_report": "qc_report.json",
            "target_run": "run.json",
            "construction": "construction.json",
            "main_item_evidence": "runner/<target_id>/<item_id>/",
            "probe_item_evidence": "analysis/iteration-<NN>/runner/<target_id>/<item_id>/",
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

    if not isinstance(data.get("done"), bool):
        raise ValueError("Analyser response requires a boolean done field.")
    done = data["done"]
    if done or remaining_probe_iterations <= 0 or _analysis_max_tasks(config, suite) == 0:
        return analysis, "", True, []

    mode = str(getattr(config, "analysis_probe_mode", "goal"))
    goal = ""
    designs: list[AnalysisProbeDesign] = []

    if mode == "task_design":
        raw_designs = data.get("task_designs", [])
        if not isinstance(raw_designs, list):
            raise ValueError("Analyser task_designs must be a list.")
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
        max_tasks = _analysis_max_tasks(config, suite)
        if total_tasks > max_tasks:
            raise ValueError(
                f"Analyser requested {total_tasks} probe tasks, exceeding analysis_max_tasks={max_tasks}."
            )
    else:
        raw_goal = data.get("goal")
        if not isinstance(raw_goal, str) or not raw_goal.strip():
            raise ValueError("Analyser response requires a non-empty goal when done=false.")
        goal = raw_goal.strip()

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
        "max_probe_tasks": config.analysis_max_tasks,
    }

    def validate(data: dict[str, Any]) -> None:
        if not isinstance(data.get("done"), bool):
            raise ValueError("Analyser review requires a boolean done field.")
        if not data["done"] and config.analysis_max_tasks is not None:
            outcome = _apply_review(probe_suite, data, QcReport(), config)
            if outcome.spec.scale > config.analysis_max_tasks:
                raise ValueError("Probe review would exceed max_probe_tasks; revise within the budget.")

    data = _run_analyser_tool_loop(
        payload,
        config,
        trace_dir=trace_dir,
        artifact_dir=None,
        system_prompt=ANALYSER_REVIEW_SYSTEM_PROMPT,
        validate=validate,
    )
    if not isinstance(data, dict):
        raise ValueError("Analyser review must be a JSON object.")
    if "done" not in data:
        raise ValueError("Analyser review requires a done field.")
    return data


def _probe_review_iterations(config: BenchmarkConfig) -> int:
    if config.ablation_analyser != "none":
        return 0
    return max(0, int(config.analysis_review_max_iterations or 0))


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
    max_tasks = _analysis_max_tasks(config, main_suite)
    config = config.model_copy(update={
        "item_count": None,
        "challenge_effort_distribution": {},
        "analysis_max_tasks": max_tasks,
    })
    if goal:
        _probe_spec, probe_suite, probe_qc = build_benchmark_suite_with_qc_loop(
            goal,
            config,
            log=log,
            trace_dir=trace_dir / "construction" if trace_dir is not None else None,
            max_task_count=max_tasks,
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
    if trace_dir is not None:
        write_json(trace_dir / "probe-suite.json", probe_suite.model_dump(mode="json"))
        write_json(trace_dir / "probe-qc.json", probe_qc.model_dump(mode="json"))
    for review_index in range(_probe_review_iterations(config)):
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
        _review_spec, probe_suite, probe_qc = apply_review_to_suite(
            probe_suite,
            review,
            probe_qc,
            config,
            log=log,
            trace_dir=review_trace,
            max_task_count=max_tasks,
        )
        if trace_dir is not None:
            write_json(trace_dir / "probe-suite.json", probe_suite.model_dump(mode="json"))
            write_json(trace_dir / "probe-qc.json", probe_qc.model_dump(mode="json"))
    execution_plan = build_execution_plan(probe_suite, probe_qc)
    environment_config = config.model_copy(update={"environment_preflight": False})
    run_config, environment_report = run_environment_claw(
        execution_plan.suite.tasks,
        environment_config,
    )
    blocked_ids = set(environment_report.blocked_item_ids)
    if blocked_ids and set(execution_plan.accepted_item_ids) <= blocked_ids:
        raise RuntimeError("\n\n".join(environment_report.blocking_errors))
    probe_qc = exclude_blocked_items(probe_qc, blocked_ids)
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
    try:
        return _run_analysis(suite, run, config, artifact_dir=artifact_dir, root=root, log=log)
    except CancelledError:
        raise
    except Exception as exc:
        error = redact_secrets(f"{type(exc).__name__}: {exc}")
        log(f"  [Analysis] Failed: {error}. Preserving completed results for reporting.")
        report = AnalysisReport(
            strategy="hypothesis_driven" if config.ablation_analyser == "none" else config.ablation_analyser,
            status="failed",
            error=error,
            iterations=_load_iterations(root),
        )
        if root is not None:
            write_json(root / "failure.json", error_record(exc), redact=True)
            write_json(root / "failed-report.json", report.model_dump(mode="json"))
        return report


def _run_analysis(
    suite: TaskSuite,
    run: EvalRun,
    config: BenchmarkConfig,
    *,
    artifact_dir: Path | None,
    root: Path | None,
    log: Callable[[str], None],
) -> AnalysisReport:
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        report_path = root / "report.json"
        if report_path.is_file():
            try:
                report = AnalysisReport.model_validate_json(report_path.read_text(encoding="utf-8"))
                if report.status == "completed":
                    return report
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
            validate=lambda data: _parse_response(
                data, suite, config, iteration=next_iteration, remaining_probe_iterations=remaining
            ),
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
                strategy=(
                    "hypothesis_driven"
                    if config.ablation_analyser == "none"
                    else config.ablation_analyser
                ),
                analysis=analysis,
                iterations=iterations,
            )
            if root is not None:
                write_json(root / "report.json", report.model_dump(mode="json"))
            return report

        iteration_dir = root / f"iteration-{next_iteration:02d}" if root is not None else None
        strategy_label = (
            config.ablation_analyser.replace("_", "-")
            if config.ablation_analyser != "none"
            else "hypothesis-driven"
        )
        if task_designs:
            probe_desc = (
                f"{sum(item.task_design.task_count for item in task_designs)} "
                f"{strategy_label} probe task(s)"
            )
        else:
            probe_desc = f"a {strategy_label} goal probe"
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
