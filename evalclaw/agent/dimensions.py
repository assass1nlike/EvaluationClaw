"""Agent benchmark dimension parsing and local fallback dimensions."""
from __future__ import annotations

from typing import Any

from ..core.scaling import scale_budget_target_items
from ..generation.generator import _safe_task_type as _item_safe_task_type
from ..types import (
    ChallengeEffort,
    EvalDimension,
    EvalSpec,
    ScaleBudget,
    TaskType,
    safe_challenge_effort,
)
from .common import _safe_optional_int, _safe_scale_budget, _slug
from .goal_detection import (
    _goal_mentions_ale_style,
    _goal_mentions_desktop_software,
    _goal_mentions_gui_desktop,
    _goal_mentions_multi_industrial_workflow,
    _goal_mentions_osworld_style,
    _goal_mentions_professional_engineering_artifact,
    _goal_mentions_professional_executable_benchmark,
    _goal_mentions_professional_life_science_analysis,
    _goal_mentions_runtime_pipeline,
)


def _parse_dimensions(data: list[dict[str, Any]] | dict[str, Any], goal: str, scale_budget: ScaleBudget) -> EvalSpec:
    if isinstance(data, dict):
        spec_data = data.get("spec", data)
        dims = spec_data.get("dimensions", []) if isinstance(spec_data.get("dimensions"), list) else []
        task_types = spec_data.get("task_types", ["agent_interaction"])
        objective = str(spec_data.get("objective") or goal)
        scale = int(spec_data.get("scale") or scale_budget_target_items(scale_budget))
        critique = spec_data.get("critique") if isinstance(spec_data.get("critique"), dict) else {}
        dimensions: list[EvalDimension] = []
        for idx, raw in enumerate(dims, 1):
            if not isinstance(raw, dict):
                continue
            dim_id = str(raw.get("id") or f"dimension_{idx}")
            challenge_effort = safe_challenge_effort(
                raw.get("challenge_effort")
                or raw.get("target_challenge_effort")
                or raw.get("task_builder_effort")
            )
            dimensions.append(
                EvalDimension(
                    id=dim_id,
                    name=str(raw.get("name") or dim_id),
                    description=str(raw.get("description") or ""),
                    approach=str(raw.get("approach") or ""),
                    weight=float(raw.get("weight", 1.0) or 1.0),
                    challenge_effort=challenge_effort,
                    needs_research=bool(raw.get("needs_research", False)),
                    research_queries=[str(q) for q in raw.get("research_queries", []) if q],
                    target_item_count=_safe_optional_int(raw.get("target_item_count")),
                    target_source_backed_count=max(0, _safe_optional_int(raw.get("target_source_backed_count")) or 0),
                    target_generated_count=_safe_optional_int(raw.get("target_generated_count")),
                    task_types=[_item_safe_task_type(x, TaskType.agent_interaction) for x in raw.get("task_types", [])]
                    if isinstance(raw.get("task_types"), list)
                    else [TaskType.agent_interaction],
                    item_requirements=[str(x) for x in raw.get("item_requirements", []) if x],
                )
            )
        return EvalSpec(
            id=str(spec_data.get("id") or _slug(goal)),
            objective=objective,
            subjects=[str(x) for x in spec_data.get("subjects", ["user_supplied_targets"])],
            task_types=[_item_safe_task_type(x, TaskType.agent_interaction) for x in task_types],
            dimensions=dimensions,
            scale_budget=_safe_scale_budget(spec_data.get("scale_budget"), scale_budget),
            scale=scale,
            metrics=[],
            constraints=[str(x) for x in spec_data.get("constraints", [])],
            planner_notes=str(spec_data.get("planner_notes", "")),
        )
    raise TypeError("Expected dict agent benchmark planner output.")

def _fallback_dimensions(goal: str) -> list[EvalDimension]:
    full_text = goal.lower()
    if _goal_mentions_osworld_style(full_text):
        return [
            EvalDimension(
                id="office_artifact_editing",
                name="Office artifact editing",
                description=(
                    "Measure whether the agent can operate desktop office applications such as spreadsheets, "
                    f"documents, and presentations, then save artifacts for deterministic comparison: {goal}"
                ),
                approach=(
                    "Use VM-backed LibreOffice/office-style tasks with staged files, exact expected values or "
                    "format changes, and hidden artifact checks."
                ),
                challenge_effort=ChallengeEffort.E4,
                needs_research=True,
                research_queries=[
                    "OSWorld LibreOffice Calc Writer Impress task evaluator examples",
                    "desktop GUI agent spreadsheet document artifact benchmark",
                ],
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Construct a GUI desktop task with staged office files and exact output artifact requirements.",
                    "Require GUI interaction with a spreadsheet/document/presentation application, not a text-only answer.",
                    "Include hidden deterministic artifact checks for saved/exported files.",
                ],
            ),
            EvalDimension(
                id="creative_media_desktop_editing",
                name="Creative and media desktop editing",
                description=(
                    "Measure whether the agent can use native image/media applications such as GIMP or VLC to "
                    f"change application state or exported media artifacts: {goal}"
                ),
                approach=(
                    "Use VM-backed image/media tasks with visible source assets, requested edits/settings, and "
                    "hidden checks over exported files or app preferences."
                ),
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Construct a desktop image/media editing task with concrete visible assets.",
                    "Score saved output artifacts or app configuration through deterministic checks.",
                    "Require trace evidence of GUI tool use through the desktop bridge.",
                ],
            ),
            EvalDimension(
                id="browser_email_ide_state_management",
                name="Browser, email, and IDE state management",
                description=(
                    "Measure whether the agent can navigate desktop/browser/email/IDE state, install or change "
                    f"settings, and leave the system in the requested state: {goal}"
                ),
                approach=(
                    "Use VM-backed browser, Thunderbird, VS Code, or settings tasks with local fixtures and state "
                    "or command-line evaluators."
                ),
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Define initial application state and exact target preference/extension/page state.",
                    "Use hidden checks over browser/app config, IDE extension state, or email-filter preferences.",
                    "Avoid repeating the same browser ticket-editing fixture across dimensions.",
                ],
            ),
        ]
    if _goal_mentions_ale_style(full_text):
        return [
            EvalDimension(
                id="professional_artifact_reconstruction",
                name="Professional artifact reconstruction",
                description=(
                    "Measure whether the agent can reconstruct or transform professional artifacts in a real "
                    f"desktop/VM workflow, with visible inputs and hidden reference outputs: {goal}"
                ),
                approach=(
                    "Use VM-backed engineering, visual-media, or design tasks with staged references, required "
                    "deliverables, and deterministic or calibrated artifact graders."
                ),
                challenge_effort=ChallengeEffort.E4,
                needs_research=True,
                research_queries=[
                    "Agents Last Exam visual media engineering artifact reconstruction task",
                    "professional agent benchmark hidden reference artifact grader",
                ],
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Create a long-horizon professional task with visible input files and runner-private references.",
                    "Require concrete deliverables such as scene/model/report/exported artifacts.",
                    "Define artifact_collection, trajectory requirements, and pass/partial/fail thresholds.",
                ],
            ),
            EvalDimension(
                id="domain_data_pipeline_execution",
                name="Domain data pipeline execution",
                description=(
                    "Measure whether the agent can run a domain pipeline in Docker/VM, inspect inputs and logs, "
                    f"repair parameters or code, and produce structured outputs: {goal}"
                ),
                approach=(
                    "Use Docker-backed scientific, financial, security, or health data workflows with compact "
                    "fixtures and hidden reference checks."
                ),
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Construct a docker_workspace task with visible data/config/docs and a hidden evaluator.",
                    "The agent must run commands, inspect failures or outputs, and produce structured artifacts.",
                    "Keep hidden truth sets and evaluator scripts private until grading.",
                ],
            ),
            EvalDimension(
                id="professional_provenance_and_hidden_grading",
                name="Professional provenance and hidden grading",
                description=(
                    "Measure whether the agent can document workflow provenance while matching hidden reference "
                    f"criteria in economically valuable professional tasks: {goal}"
                ),
                approach=(
                    "Require output manifests, logs, and artifacts that the grader can compare against hidden "
                    "reference data, numerical tolerances, or schema rules."
                ),
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Require a machine-readable workflow manifest or report with artifact provenance.",
                    "Use hidden reference files, schema/numerical checks, and trajectory evidence.",
                    "Prefer domain-specific executable work over generic workspace puzzles.",
                ],
            ),
        ]
    if _goal_mentions_professional_life_science_analysis(full_text):
        return [
            EvalDimension(
                id="domain_data_pipeline_execution",
                name="Life-science data pipeline execution",
                description=(
                    "Measure whether the agent can inspect staged life-science data tables and metadata, follow "
                    f"an analysis contract, and produce structured result tables: {goal}"
                ),
                approach=(
                    "Use Docker-backed data-analysis tasks with compact biological fixtures, visible contracts, "
                    "runner-private reference outputs, and deterministic checks."
                ),
                challenge_effort=ChallengeEffort.E4,
                needs_research=True,
                research_queries=[
                    "life science agent benchmark structured data analysis hidden reference outputs",
                    "bioinformatics workflow benchmark deterministic grading provenance",
                ],
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Construct a docker_workspace task with visible data tables, metadata, analysis contract, and output contract.",
                    "Require structured output tables and a workflow_manifest.json provenance record.",
                    "Keep hidden reference outputs and evaluator scripts runner-private.",
                    "Prefer domain-specific life-science analysis over generic aggregation puzzles.",
                ],
            ),
            EvalDimension(
                id="professional_provenance_and_hidden_grading",
                name="Life-science provenance and hidden grading",
                description=(
                    "Measure whether the agent documents analysis provenance while matching private reference "
                    f"criteria for a professional life-science task: {goal}"
                ),
                approach=(
                    "Require reproducible manifests, input/output declarations, and hidden schema/numerical checks."
                ),
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Require a machine-readable workflow manifest or provenance report.",
                    "Use hidden reference files, schema checks, and deterministic scoring.",
                    "Avoid tasks that can be solved as a prose explanation only.",
                ],
            ),
        ]
    if _goal_mentions_professional_engineering_artifact(full_text):
        return [
            EvalDimension(
                id="professional_artifact_reconstruction",
                name="Engineering artifact reconstruction",
                description=(
                    "Measure whether the agent can inspect engineering assets and structured metadata, recover "
                    f"relationships and constraints, and produce a complete executable artifact: {goal}"
                ),
                approach=(
                    "Use VM-backed or desktop-tool-backed engineering artifact tasks with visible manifests, "
                    "required deliverables, validation reports, and hidden semantic checks."
                ),
                challenge_effort=ChallengeEffort.E4,
                needs_research=True,
                research_queries=[
                    "engineering agent benchmark artifact reconstruction structured metadata hidden checks",
                    "robotics CAD URDF executable artifact benchmark deterministic evaluation",
                ],
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Construct a professional engineering artifact task with visible assets and structured metadata.",
                    "Require an executable output artifact plus validation evidence and provenance.",
                    "Use runner-private semantic or kinematic checks rather than text-only judging.",
                    "Prefer reconstructing relationships/constraints over generic drawing or scene creation.",
                ],
            ),
            EvalDimension(
                id="professional_provenance_and_hidden_grading",
                name="Engineering provenance and hidden grading",
                description=(
                    "Measure whether the agent can document engineering decisions and satisfy runner-private "
                    f"validation criteria: {goal}"
                ),
                approach=(
                    "Require structured validation evidence, provenance records, and hidden artifact/metadata checks."
                ),
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Require a workflow manifest or validation report tied to the produced engineering artifact.",
                    "Use hidden evaluator files, semantic checks, and trajectory evidence.",
                    "Avoid generic code or workspace tasks when engineering assets are requested.",
                ],
            ),
        ]
    if _goal_mentions_professional_executable_benchmark(full_text):
        return [
            EvalDimension(
                id="professional_artifact_reconstruction",
                name="Professional artifact construction",
                description=(
                    "Measure whether the agent can inspect domain assets, constraints, and metadata, then produce "
                    f"a checkable professional artifact: {goal}"
                ),
                approach=(
                    "Use executable VM/Docker tasks with visible inputs, concrete deliverables, hidden references, "
                    "and artifact/provenance scoring."
                ),
                challenge_effort=ChallengeEffort.E4,
                needs_research=True,
                research_queries=[
                    "professional agent benchmark executable artifact hidden deterministic checks",
                    "long horizon professional workflow benchmark provenance artifact collection",
                ],
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Create a professional task with visible input files and runner-private references.",
                    "Require concrete deliverables, validation evidence, artifact collection, and provenance.",
                    "Define pass/partial/fail thresholds using deterministic or calibrated checks.",
                ],
            ),
            EvalDimension(
                id="domain_data_pipeline_execution",
                name="Domain pipeline execution",
                description=(
                    "Measure whether the agent can run a domain workflow, inspect inputs and logs, produce "
                    f"structured outputs, and satisfy hidden checks: {goal}"
                ),
                approach=(
                    "Use Docker-backed fixtures with visible docs/configs, private reference outputs, and reproducible tests."
                ),
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Construct a docker_workspace task with visible data/config/docs and a hidden evaluator.",
                    "Require structured outputs plus a workflow manifest or provenance report.",
                    "Keep hidden reference data and evaluator scripts runner-private.",
                ],
            ),
            EvalDimension(
                id="professional_provenance_and_hidden_grading",
                name="Professional provenance and hidden grading",
                description=(
                    "Measure whether the agent can document workflow provenance while matching private evaluation "
                    f"criteria in a professional task: {goal}"
                ),
                approach=(
                    "Require output manifests, logs, artifacts, and hidden schema/numerical/artifact checks."
                ),
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Require a machine-readable workflow manifest or report with artifact provenance.",
                    "Use hidden reference files, schema/numerical checks, and trajectory evidence.",
                    "Prefer domain-specific executable work over generic workspace puzzles.",
                ],
            ),
        ]
    if _goal_mentions_multi_industrial_workflow(full_text):
        return [
            EvalDimension(
                id="cross_application_artifact_handoff",
                name="Cross-application artifact handoff",
                description=(
                    "Measure whether the agent can pass engineering artifacts across multiple industrial "
                    f"applications without losing units, geometry, constraints, or provenance for: {goal}"
                ),
                approach=(
                    "Use VM-backed workflows where one application produces an intermediate artifact that must be "
                    "opened, checked, and transformed by another application."
                ),
                challenge_effort=ChallengeEffort.E4,
                needs_research=True,
                research_queries=[
                    "KiCad FreeCAD Blender PCB enclosure workflow",
                    "CAD EDA render multi application engineering workflow benchmark",
                ],
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Construct a VM-backed desktop_software task requiring at least two named industrial applications.",
                    "The task must include explicit handoff artifacts, expected file paths, and provenance checks.",
                    "Do not accept a single-application or text-only task for this dimension.",
                ],
            ),
            EvalDimension(
                id="engineering_constraint_reconciliation",
                name="Engineering constraint reconciliation",
                description=(
                    "Measure whether the agent can reconcile PCB, mechanical, manufacturing, and visual review "
                    f"constraints across different tools for: {goal}"
                ),
                approach=(
                    "Provide compact design briefs and hidden reference constraints; score final artifacts and a "
                    "workflow manifest against clearance, placement, units, and review requirements."
                ),
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Include design constraints that require cross-checking between EDA/CAD/rendering stages.",
                    "Require a structured workflow manifest recording which application produced each artifact.",
                    "Use hidden evaluator files or bridge checks for pass/partial/fail scoring.",
                ],
            ),
            EvalDimension(
                id="end_to_end_industrial_workflow_execution",
                name="End-to-end industrial workflow execution",
                description=(
                    "Measure whether the agent can plan, execute, recover from tool friction, and finish a "
                    f"multi-software industrial workflow for: {goal}"
                ),
                approach=(
                    "Require launch/use of multiple desktop applications, artifact export/import, final review "
                    "outputs, and deterministic bridge or artifact evaluation."
                ),
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "The environment must declare VM/session/software requirements for the full application stack.",
                    "The task must produce concrete intermediate and final artifacts, not only a report.",
                    "The trajectory requirements must make shortcut-only completion auditable.",
                ],
            ),
        ]
    if _goal_mentions_gui_desktop(full_text) or _goal_mentions_desktop_software(full_text):
        return [
            EvalDimension(
                id="desktop_state_grounding",
                name="Desktop state grounding",
                description=f"Measure whether the agent can inspect and understand GUI/software state for: {goal}",
                approach="Use VM/bridge-backed desktop tasks with screenshots, files, assets, and explicit session state.",
                challenge_effort=ChallengeEffort.E4,
                needs_research=True,
                research_queries=[f"{goal} desktop agent benchmark task", f"{goal} reference artifact evaluation"],
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Construct a GUI or desktop-software task with metadata.task_agent and metadata.agent_task_package.",
                    "The task must include visible inputs, VM/session requirements, expected artifacts, hidden references, and bridge evaluation.",
                ],
            ),
            EvalDimension(
                id="artifact_workflow_execution",
                name="Artifact workflow execution",
                description=f"Measure whether the agent can complete a professional software workflow and produce artifacts for: {goal}",
                approach="Require multi-step GUI/tool use, saved files, exported artifacts, and deterministic artifact checks.",
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Require the target to produce concrete files or GUI state, not only a textual summary.",
                    "Use metadata.agent_task_package.output_contract and artifact_collection to name all outputs and logs.",
                ],
            ),
            EvalDimension(
                id="hidden_reference_alignment",
                name="Hidden-reference alignment",
                description=(
                    "Measure whether produced artifacts match runner-private reference criteria without exposing "
                    f"the oracle for: {goal}"
                ),
                approach="Use hidden references, evaluator scripts, artifact metrics, and trace checks.",
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Keep reference artifacts and evaluator internals runner-private.",
                    "Define pass/partial/fail criteria and trajectory requirements in metadata.agent_task_package.",
                ],
            ),
        ]
    if _goal_mentions_runtime_pipeline(full_text):
        return [
            EvalDimension(
                id="resource_grounded_pipeline_setup",
                name="Resource-grounded pipeline setup",
                description=f"Measure whether the agent can inspect domain resources, configs, data, and docs for: {goal}",
                approach="Use Docker-backed tasks with compact source-backed files and realistic setup commands.",
                challenge_effort=ChallengeEffort.E4,
                needs_research=True,
                research_queries=[f"{goal} benchmark dataset", f"{goal} reproducible workflow"],
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Build a docker_workspace task with visible files, setup commands, and metadata.agent_task_package.",
                    "Use source-backed or realistic compact fixtures rather than pure prose prompts.",
                ],
            ),
            EvalDimension(
                id="iterative_execution_and_recovery",
                name="Iterative execution and recovery",
                description=(
                    "Measure whether the agent can run commands, diagnose failures, revise files, and complete "
                    f"the workflow for: {goal}"
                ),
                approach="Require command execution, log inspection, edits or parameter choices, and reruns.",
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "The task must require at least one executable run/test/evaluation step.",
                    "Scoring should reward correct recovery from realistic command, data, or configuration failures.",
                ],
            ),
            EvalDimension(
                id="structured_output_oracle",
                name="Structured output oracle",
                description=(
                    "Measure whether final outputs match hidden truth sets, numerical tolerances, or schema checks "
                    f"for: {goal}"
                ),
                approach="Use hidden evaluator files or tests over produced JSON/CSV/reports/artifacts.",
                challenge_effort=ChallengeEffort.E4,
                task_types=[TaskType.agent_interaction],
                item_requirements=[
                    "Define output_contract, hidden_references, evaluation checks, and artifact_collection.",
                    "Keep hidden truth sets runner-private and make all visible inputs self-contained.",
                ],
            ),
        ]
    return [
        EvalDimension(
            id="agent_tool_use",
            name="Tool use and action selection",
            description=f"Measure whether the agent can use tools correctly for: {goal}",
            approach="Create realistic action-observation tasks with clear tool affordances.",
            challenge_effort=ChallengeEffort.E3,
            task_types=[TaskType.agent_interaction],
            item_requirements=[
                "Test valid tool use, state tracking, and recovery from invalid actions.",
                "Prefer executable environments over static prompts.",
            ],
        ),
        EvalDimension(
            id="agent_recovery",
            name="Recovery and iteration",
            description="Measure whether the agent can inspect failures and revise its strategy.",
            approach="Use environments where the first attempt often fails and revision is required.",
            challenge_effort=ChallengeEffort.E3,
            task_types=[TaskType.agent_interaction],
            item_requirements=[
                "Require the agent to inspect feedback and adapt.",
                "Make hidden tests or environment feedback part of the oracle.",
            ],
        ),
        EvalDimension(
            id="agent_resource_grounding",
            name="Grounding in resources",
            description="Measure whether the agent can exploit real resources or structured task context.",
            approach="Use docs, repositories, or issue-like materials as the basis for tasks.",
            challenge_effort=ChallengeEffort.E3,
            needs_research=True,
            task_types=[TaskType.agent_interaction, TaskType.multi_turn],
            item_requirements=[
                "Build tasks from supplied resources rather than synthetic trivia.",
                "Keep the oracle tied to the provided materials.",
            ],
        ),
    ]
