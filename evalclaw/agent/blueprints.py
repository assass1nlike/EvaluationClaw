"""Default agent task blueprint routing rules."""
from __future__ import annotations

import re

from ..types import AgentEnvironmentType, AgentTaskBlueprint, EvalDimension
from .goal_detection import (
    _contains_any,
    _goal_mentions_blender,
    _goal_mentions_browser_gui,
    _goal_mentions_desktop_software,
    _goal_mentions_gui_desktop,
    _goal_mentions_multi_industrial_workflow,
    _goal_mentions_runtime_pipeline,
    _mentions_app_state_workflow,
)


def _default_blueprint_for_dimension(dimension: EvalDimension) -> AgentTaskBlueprint:
    identity = " ".join([dimension.id, dimension.name]).lower()
    full_text = " ".join([dimension.id, dimension.name, dimension.description, dimension.approach]).lower()
    category_text = " ".join(
        [
            dimension.id,
            dimension.name,
            dimension.approach,
            " ".join(dimension.item_requirements),
        ]
    ).lower()
    if _goal_mentions_multi_industrial_workflow(full_text):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_industrial_multi_app_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} industrial multi-app workflow",
            description=f"VM-backed multi-application industrial software workflow tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.gui_desktop,
            expected_task_count=1,
            resource_queries=[
                f"{dimension.name} KiCad FreeCAD Blender workflow",
                f"{dimension.name} CAD EDA mechanical render artifact handoff",
            ],
            source_strategy=(
                "Prefer source-backed industrial workflows and compact generated project briefs. Use the "
                "reproducible open-source stack KiCad + FreeCAD + Blender unless the user supplied a licensed "
                "industrial software stack."
            ),
            tool_requirements=[
                "screenshot",
                "mouse_move",
                "click",
                "drag",
                "scroll",
                "key",
                "type",
                "list_files",
                "read_file",
                "write_file",
                "run_command",
                "evaluate",
            ],
            construction_requirements=[
                "Build a VM-backed desktop_software task with at least two distinct industrial applications; default to KiCad, FreeCAD, and Blender for reproducible open-source coverage.",
                "Define workflow_stages with input artifacts, output artifacts, and the application responsible for each handoff.",
                "Require a final workflow_manifest.json recording application sequence, artifact provenance, units, and checks performed.",
                "Provide hidden evaluator logic or bridge checks for intermediate artifacts, final artifacts, and GUI/tool trajectory.",
                "Reject tasks that can be completed entirely inside one application or by writing a text report.",
            ],
            scoring_strategy=(
                "Bridge-backed artifact evaluation over EDA/CAD/render outputs, workflow manifest provenance, "
                "and trace evidence that multiple industrial applications were used."
            ),
        )
    if any(keyword in category_text for keyword in ("office", "spreadsheet", "document", "presentation", "libreoffice")):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_office_desktop_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} office desktop workflow",
            description=f"VM-backed office application artifact-editing tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.gui_desktop,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} OSWorld office GUI task", f"{dimension.name} desktop artifact evaluator"],
            source_strategy="Use compact staged spreadsheet/document fixtures with hidden artifact checks.",
            tool_requirements=[
                "screenshot",
                "click",
                "drag",
                "key",
                "type",
                "read_file",
                "run_command",
                "evaluate",
            ],
            construction_requirements=[
                "Stage visible office files before the run and require the agent to edit them through the desktop GUI.",
                "Define exact output artifacts and hidden deterministic checks over saved/exported files.",
                "Require trace evidence of office application use.",
            ],
            scoring_strategy="Hidden artifact comparison plus bridge trace evidence.",
        )
    if (
        any(keyword in category_text for keyword in ("image", "photo", "gimp", "vlc", "creative"))
        or re.search(r"\bmedia\b", category_text) is not None
    ):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_creative_desktop_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} creative desktop workflow",
            description=f"VM-backed image/media editing tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.gui_desktop,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} OSWorld GIMP VLC task", f"{dimension.name} desktop media evaluator"],
            source_strategy="Use staged visual/media assets and hidden artifact or preference checks.",
            tool_requirements=[
                "screenshot",
                "click",
                "drag",
                "key",
                "type",
                "run_command",
                "evaluate",
            ],
            construction_requirements=[
                "Provide visible source assets and exact requested image/media/app-state changes.",
                "Score exported artifacts or app configuration deterministically.",
                "Require trace evidence of native application use.",
            ],
            scoring_strategy="Hidden artifact/state checks plus GUI trace evidence.",
        )
    if _mentions_app_state_workflow(category_text):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_app_state_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} application state workflow",
            description=f"VM-backed browser/email/IDE state-management tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.gui_desktop,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} OSWorld application state task"],
            source_strategy="Use local app fixtures and deterministic state evaluators.",
            tool_requirements=[
                "screenshot",
                "click",
                "scroll",
                "key",
                "type",
                "run_command",
                "evaluate",
            ],
            construction_requirements=[
                "Define initial application state and exact expected preference/extension/email-filter outcome.",
                "Score final app state through hidden file/config/command checks.",
            ],
            scoring_strategy="Hidden app-state evaluator plus bridge trajectory requirements.",
        )
    provenance_only = "provenance" in identity or (
        any(keyword in category_text for keyword in ("provenance", "manifest", "workflow manifest"))
        and not any(
            keyword in category_text
            for keyword in (
                "professional_artifact_reconstruction",
                "artifact reconstruction",
                "engineering artifact",
                "domain_data_pipeline_execution",
                "data pipeline",
                "life-science data pipeline",
                "life science data pipeline",
            )
        )
    )
    if provenance_only:
        return AgentTaskBlueprint(
            id=f"{dimension.id}_professional_provenance_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} professional provenance workflow",
            description=f"Docker-backed professional task with provenance and hidden grading for {dimension.name}.",
            environment_type=AgentEnvironmentType.docker_workspace,
            expected_task_count=1,
            resource_queries=[
                f"{dimension.name} ALE provenance hidden grading task",
                f"{dimension.name} professional executable workflow manifest benchmark",
            ],
            source_strategy="Use domain fixtures, output manifests, logs, and hidden reference checks.",
            tool_requirements=["list_files", "read_file", "write_file", "run_command", "run_tests"],
            construction_requirements=[
                "Require structured outputs plus a workflow manifest or provenance report.",
                "Keep hidden references runner-private and score artifact content plus provenance completeness.",
                "Use deterministic checks over files, logs, schemas, or numerical tolerances.",
            ],
            scoring_strategy="Hidden evaluator over structured outputs, logs, and provenance artifacts.",
        )
    if any(keyword in identity for keyword in ("domain_data_pipeline", "data pipeline")) or any(
        keyword in category_text
        for keyword in (
            "domain data pipeline",
            "data pipeline",
            "life-science data pipeline",
            "life science data pipeline",
            "staged life-science data",
            "structured result tables",
        )
    ):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_professional_pipeline_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} professional executable pipeline",
            description=f"Docker-backed professional data/workflow pipeline tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.docker_workspace,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} ALE data pipeline task", f"{dimension.name} hidden reference grader"],
            source_strategy="Use compact domain fixtures, visible docs/configs, and hidden reference outputs.",
            tool_requirements=["list_files", "read_file", "write_file", "run_command", "run_tests"],
            construction_requirements=[
                "Build a docker_workspace task with setup commands and deterministic hidden evaluator.",
                "Require the agent to run commands, inspect outputs, and produce structured artifacts.",
                "Keep hidden references and truth sets runner-private.",
            ],
            scoring_strategy="Hidden evaluator over structured outputs, logs, and numerical/schema tolerances.",
        )
    if any(
        keyword in category_text
        for keyword in (
            "professional artifact",
            "artifact reconstruction",
            "engineering artifact",
            "professional_artifact_reconstruction",
            "executable artifact",
            "visual media",
        )
    ):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_professional_artifact_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} professional artifact workflow",
            description=f"VM-backed professional artifact reconstruction tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.gui_desktop,
            expected_task_count=1,
            resource_queries=[
                f"{dimension.name} Agents Last Exam artifact reconstruction",
                f"{dimension.name} professional desktop artifact grader",
            ],
            source_strategy="Use staged professional references and output contracts with hidden artifact graders.",
            tool_requirements=[
                "screenshot",
                "click",
                "drag",
                "key",
                "type",
                "run_command",
                "read_file",
                "write_file",
                "evaluate",
            ],
            construction_requirements=[
                "Stage visible input assets before the run and keep reference artifacts private.",
                "Require concrete deliverables and artifact_collection metadata.",
                "Define deterministic or calibrated artifact scoring with pass/partial/fail thresholds.",
            ],
            scoring_strategy="Artifact similarity/structure checks with hidden references and provenance scoring.",
        )
    if _goal_mentions_multi_industrial_workflow(full_text):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_industrial_multi_app_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} industrial multi-app workflow",
            description=f"VM-backed multi-application industrial software workflow tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.gui_desktop,
            expected_task_count=1,
            resource_queries=[
                f"{dimension.name} KiCad FreeCAD Blender workflow",
                f"{dimension.name} CAD EDA mechanical render artifact handoff",
            ],
            source_strategy=(
                "Prefer source-backed industrial workflows and compact generated project briefs. Use the "
                "reproducible open-source stack KiCad + FreeCAD + Blender unless the user supplied a licensed "
                "industrial software stack."
            ),
            tool_requirements=[
                "screenshot",
                "mouse_move",
                "click",
                "drag",
                "scroll",
                "key",
                "type",
                "list_files",
                "read_file",
                "write_file",
                "run_command",
                "evaluate",
            ],
            construction_requirements=[
                "Build a VM-backed desktop_software task with at least two distinct industrial applications; default to KiCad, FreeCAD, and Blender for reproducible open-source coverage.",
                "Define workflow_stages with input artifacts, output artifacts, and the application responsible for each handoff.",
                "Require a final workflow_manifest.json recording application sequence, artifact provenance, units, and checks performed.",
                "Provide hidden evaluator logic or bridge checks for intermediate artifacts, final artifacts, and GUI/tool trajectory.",
                "Reject tasks that can be completed entirely inside one application or by writing a text report.",
            ],
            scoring_strategy=(
                "Bridge-backed artifact evaluation over EDA/CAD/render outputs, workflow manifest provenance, "
                "and trace evidence that multiple industrial applications were used."
            ),
        )
    if _goal_mentions_browser_gui(full_text):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_browser_gui_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} browser GUI",
            description=f"Browser-mediated GUI tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.gui_desktop,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} browser GUI benchmark"],
            source_strategy="Use a bridge-backed browser session or local web app bundle.",
            tool_requirements=[
                "screenshot",
                "mouse_move",
                "click",
                "drag",
                "scroll",
                "key",
                "type",
                "list_files",
                "read_file",
                "write_file",
                "run_command",
                "evaluate",
            ],
            construction_requirements=[
                "Define the browser session state and starting page in the task-agent metadata.",
                "Specify the completion oracle as a page-state or artifact check.",
            ],
            scoring_strategy="Bridge-backed evaluation with artifact or page-state scoring.",
        )
    if _goal_mentions_desktop_software(full_text):
        is_blender = _goal_mentions_blender(full_text)
        title_suffix = "Blender task" if is_blender else "desktop software"
        source_query = f"{dimension.name} Blender 3D modeling benchmark" if is_blender else f"{dimension.name} desktop software benchmark"
        construction_requirements = [
            "Define the application, initial document state, and expected output artifacts.",
            "Make the oracle inspectable through saved files, exported artifacts, or bridge evaluation.",
        ]
        if is_blender:
            construction_requirements = [
                "Define a Blender VM session with a clean Blender image/snapshot and desktop bridge.",
                "Provide scene requirements, starter assets or scripts, and expected .blend/render artifacts.",
                "Make the oracle inspect object types, materials, positions, camera/light setup, and rendered PNG validity.",
            ]
        return AgentTaskBlueprint(
            id=f"{dimension.id}_desktop_software_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} {title_suffix}",
            description=f"Desktop application tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.gui_desktop,
            expected_task_count=1,
            resource_queries=[source_query],
            source_strategy="Use a bridge-backed desktop application or local software fixture.",
            tool_requirements=[
                "screenshot",
                "cursor_position",
                "mouse_move",
                "click",
                "type",
                "key",
                "scroll",
                "list_files",
                "read_file",
                "write_file",
                "run_command",
                "evaluate",
            ],
            construction_requirements=construction_requirements,
            scoring_strategy="Bridge-backed artifact scoring with deterministic checks when possible.",
        )
    if _goal_mentions_gui_desktop(full_text):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_gui_desktop_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} GUI desktop",
            description=f"General GUI desktop tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.gui_desktop,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} GUI desktop benchmark"],
            source_strategy="Use a bridge-backed desktop session with realistic UI state.",
            tool_requirements=[
                "screenshot",
                "cursor_position",
                "mouse_move",
                "click",
                "drag",
                "scroll",
                "key",
                "type",
                "hold_key",
                "list_files",
                "read_file",
                "write_file",
                "run_command",
                "evaluate",
            ],
            construction_requirements=[
                "Provide a standardized task-agent session description and evaluation contract.",
                "Keep the task bridge-agnostic so runtime configuration can supply the actual desktop session.",
            ],
            scoring_strategy="Bridge-backed GUI state scoring or artifact evaluation.",
        )
    if _goal_mentions_runtime_pipeline(full_text):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_runtime_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} executable workflow",
            description=f"Docker-backed executable workflow tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.docker_workspace,
            expected_task_count=1,
            resource_queries=[
                f"{dimension.name} benchmark dataset task",
                f"{dimension.name} reproducible workflow fixture",
            ],
            source_strategy=(
                "Use compact source-backed datasets, logs, notebooks, configs, or document packets where possible; "
                "generate only the minimal fixture needed to make the task executable."
            ),
            tool_requirements=["list_files", "read_file", "write_file", "run_command", "run_tests"],
            construction_requirements=[
                "Build a complete docker_workspace task with visible input files, setup commands, and deterministic evaluation.",
                "Include metadata.agent_task_package with visible_inputs, hidden_references, output_contract, execution, evaluation, artifact_collection, trajectory_requirements, and provenance.",
                "Keep hidden truth sets, reference outputs, or evaluator scripts runner-private.",
            ],
            scoring_strategy="Deterministic hidden evaluator over produced files, structured outputs, logs, or numerical tolerances.",
        )
    if any(keyword in identity for keyword in ("code", "repo", "debug", "repair", "test", "python")):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_code_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} code repair",
            description=f"Executable code-repair tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.code_sandbox,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} bug report", f"{dimension.name} failing tests"],
            source_strategy="Use a compact repository or synthetic repair fixture.",
            tool_requirements=["read_file", "write_file", "run_tests"],
            construction_requirements=[
                "Include complete visible files and hidden tests.",
                "Make the failure mode discoverable from the visible state.",
            ],
            scoring_strategy="Deterministic hidden tests with partial credit for meaningful progress.",
        )
    if any(keyword in identity for keyword in ("dialogue", "conversation", "chat", "multi-turn", "multi turn")):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_dialogue_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} dialogue task",
            description=f"Multi-turn agent interaction tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.dialogue,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} dialogue benchmark"],
            source_strategy="Use a scripted dialogue or task-specific user simulator.",
            tool_requirements=[],
            construction_requirements=[
                "Specify the initial user request and follow-up turns clearly.",
                "Define pass/fail/partial scoring for the transcript.",
            ],
            scoring_strategy="Transcript-based judge scoring.",
        )
    if any(keyword in full_text for keyword in ("browser", "web", "search", "research", "api", "tool")):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_tool_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} tool use",
            description=f"Tool-using agent tasks for {dimension.name}.",
            environment_type=AgentEnvironmentType.workspace,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} tool use benchmark"],
            source_strategy="Use structured resources that require the agent to inspect, choose, and act.",
            tool_requirements=["look", "read_file", "write_file", "run_command"],
            construction_requirements=[
                "Make the task stateful and concrete.",
                "Ensure the oracle depends on the final state or command results.",
            ],
            scoring_strategy="Deterministic environment or judge scoring.",
        )
    return AgentTaskBlueprint(
        id=f"{dimension.id}_agent_blueprint",
        dimension_id=dimension.id,
        title=dimension.name,
        description=dimension.description,
        environment_type=AgentEnvironmentType.workspace,
        expected_task_count=1,
        resource_queries=[f"{dimension.name} agent task"],
        source_strategy="Use the simplest executable environment that still reflects the requested capability.",
        tool_requirements=["look", "read_file", "write_file"],
        construction_requirements=[
            "Build one executable agent task for the dimension.",
            "Keep the oracle explicit and deterministic.",
        ],
        scoring_strategy="Deterministic environment or judge scoring.",
    )
