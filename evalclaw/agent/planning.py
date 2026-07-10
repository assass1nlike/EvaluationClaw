"""Agent benchmark dimension and blueprint planning."""
from __future__ import annotations

import json
import re
from typing import Any

from ..generator import _safe_difficulty as _item_safe_difficulty
from ..generator import _safe_task_type as _item_safe_task_type
from ..llm import call_llm, extract_json
from ..prompts.agent_benchmark import AGENT_BENCHMARK_PLANNER_PROMPT
from ..protocols.agent_task_package import (
    AGENT_TASK_PACKAGE_GENERATION_GUIDANCE,
    AGENT_TASK_PACKAGE_SCHEMA,
)
from ..protocols.task_agent import TASK_AGENT_GENERATION_GUIDANCE, TASK_AGENT_SCHEMA
from ..scaling import scale_budget_target_workload
from ..types import (
    AgentEnvironmentType,
    AgentTaskBlueprint,
    AgentTaskFamily,
    BenchmarkConfig,
    Difficulty,
    EvalDimension,
    EvalSpec,
    Message,
    ScaleBudget,
    TaskType,
)
from .common import (
    _safe_environment_type,
    _safe_optional_int,
    _safe_scale_budget,
    _safe_task_family,
    _slug,
)


def _parse_dimensions(data: list[dict[str, Any]] | dict[str, Any], goal: str, scale_budget: ScaleBudget) -> EvalSpec:
    if isinstance(data, dict):
        spec_data = data.get("spec", data)
        dims = spec_data.get("dimensions", []) if isinstance(spec_data.get("dimensions"), list) else []
        task_types = spec_data.get("task_types", ["agent_interaction"])
        objective = str(spec_data.get("objective") or goal)
        scale = int(spec_data.get("scale") or scale_budget_target_workload(scale_budget))
        critique = spec_data.get("critique") if isinstance(spec_data.get("critique"), dict) else {}
        dimensions: list[EvalDimension] = []
        for idx, raw in enumerate(dims, 1):
            if not isinstance(raw, dict):
                continue
            dim_id = str(raw.get("id") or f"dimension_{idx}")
            dimensions.append(
                EvalDimension(
                    id=dim_id,
                    name=str(raw.get("name") or dim_id),
                    description=str(raw.get("description") or ""),
                    approach=str(raw.get("approach") or ""),
                    weight=float(raw.get("weight", 1.0) or 1.0),
                    target_difficulty=_item_safe_difficulty(raw.get("target_difficulty"), Difficulty.L4),
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


def _goal_mentions_code(goal: str) -> bool:
    text = goal.lower()
    return any(keyword in text for keyword in ("code", "repo", "repository", "debug", "repair", "test", "python", "program"))


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _mentioned_industrial_apps(full_text: str) -> list[str]:
    app_keywords = (
        ("kicad", "KiCad"),
        ("freecad", "FreeCAD"),
        ("blender", "Blender"),
        ("autocad", "AutoCAD"),
        ("solidworks", "SolidWorks"),
        ("fusion 360", "Fusion 360"),
        ("inventor", "Inventor"),
        ("catia", "CATIA"),
        ("nx", "NX"),
        ("rhino", "Rhino"),
        ("revit", "Revit"),
        ("ltspice", "LTspice"),
        ("ansys", "Ansys"),
        ("moldex3d", "Moldex3D"),
        ("powermill", "PowerMill"),
    )
    found: list[str] = []
    for needle, label in app_keywords:
        if needle in full_text:
            found.append(label)
    return list(dict.fromkeys(found))


def _goal_mentions_multi_industrial_workflow(full_text: str) -> bool:
    normalized_text = re.sub(r"[-_/]+", " ", full_text)
    search_text = f"{full_text} {normalized_text}"
    multi_markers = (
        "multi software",
        "multi-software",
        "multi industrial",
        "multi industrial software",
        "multiple software",
        "multiple industrial",
        "cross-application",
        "cross application",
        "cross-tool",
        "toolchain",
        "interoperability",
        "handoff",
        "workflow",
        "pipeline",
        "\u591a\u8f6f\u4ef6",
        "\u591a\u4e2a\u8f6f\u4ef6",
        "\u534f\u540c",
        "\u5171\u540c\u53c2\u4e0e",
        "\u5de5\u4f5c\u6d41",
    )
    industrial_markers = (
        "industrial software",
        "engineering software",
        "cad",
        "eda",
        "cae",
        "cam",
        "pcb",
        "mechanical",
        "manufacturing",
        "enclosure",
        "render",
        "3d model",
        "kicad",
        "freecad",
        "blender",
        "autocad",
        "solidworks",
        "\u5de5\u4e1a\u8f6f\u4ef6",
        "\u5de5\u4e1a",
        "\u5de5\u7a0b",
        "\u673a\u68b0",
        "\u5236\u9020",
        "\u7535\u8def\u677f",
        "\u5e38\u7528\u5de5\u4e1a\u8f6f\u4ef6",
    )
    mentioned_apps = _mentioned_industrial_apps(search_text)
    return (
        len(mentioned_apps) >= 2
        or (_contains_any(search_text, multi_markers) and _contains_any(search_text, industrial_markers))
    )


def _goal_mentions_osworld_style(full_text: str) -> bool:
    normalized_text = re.sub(r"[-_/]+", " ", full_text)
    search_text = f"{full_text} {normalized_text}"
    explicit_markers = (
        "osworld",
        "os world",
        "computer-control",
        "computer control",
        "general computer",
        "desktop gui applications",
        "desktop application benchmark",
        "desktop software benchmark",
        "desktop software operation",
        "everyday desktop software",
        "local desktop applications",
        "desktop applications",
        "gui applications",
        "desktop app",
        "desktop apps",
        "real desktop gui",
    )
    app_markers = (
        "spreadsheet",
        "document",
        "browser",
        "image editor",
        "photo editor",
        "media player",
        "email client",
        "ide",
        "vs code",
        "vscode",
        "libreoffice",
        "gimp",
        "vlc",
        "thunderbird",
    )
    broad_desktop_benchmark = (
        _goal_mentions_gui_desktop(search_text)
        and _contains_any(search_text, ("benchmark", "evaluation", "evaluate", "test whether", "measure whether"))
        and _contains_any(search_text, ("save", "saved", "output file", "artifact", "state change", "hidden check"))
    )
    return (
        _contains_any(search_text, explicit_markers)
        or broad_desktop_benchmark
        or (_goal_mentions_gui_desktop(search_text) and sum(1 for marker in app_markers if marker in search_text) >= 3)
    )


def _goal_mentions_ale_style(full_text: str) -> bool:
    normalized_text = re.sub(r"[-_/]+", " ", full_text)
    search_text = f"{full_text} {normalized_text}"
    ale_markers = (
        "ale-style",
        "ale style",
        "agents last exam",
        "agent's last exam",
        "agents' last exam",
        "economically valuable",
        "professional work",
        "professional workflow",
        "long-horizon professional",
        "hidden reference",
        "hidden references",
        "artifact grader",
        "deterministic grader",
    )
    domain_markers = (
        "engineering",
        "life sciences",
        "bioinformatics",
        "finance",
        "health",
        "visual media",
        "computing",
        "vm",
        "docker",
        "sandbox",
    )
    return _contains_any(search_text, ale_markers) and _contains_any(search_text, domain_markers)


def _goal_mentions_professional_executable_benchmark(full_text: str) -> bool:
    normalized_text = re.sub(r"[-_/]+", " ", full_text)
    search_text = f"{full_text} {normalized_text}"
    professional_markers = (
        "professional",
        "engineering",
        "life science",
        "life sciences",
        "scientific",
        "domain",
        "workflow",
    )
    benchmark_markers = (
        "benchmark",
        "evaluation",
        "evaluate",
        "test whether",
        "measure whether",
        "agent benchmark",
    )
    executable_markers = (
        "isolated environment",
        "private deterministic checks",
        "hidden reference",
        "hidden reference outputs",
        "deterministic checks",
        "structured result",
        "structured output",
        "output contract",
        "validation evidence",
        "provenance",
        "executable artifact",
        "staged data",
        "staged data tables",
        "structured metadata",
        "private checks",
    )
    return (
        _contains_any(search_text, professional_markers)
        and _contains_any(search_text, benchmark_markers)
        and _contains_any(search_text, executable_markers)
    )


def _goal_mentions_professional_life_science_analysis(full_text: str) -> bool:
    normalized_text = re.sub(r"[-_/]+", " ", full_text)
    search_text = f"{full_text} {normalized_text}"
    return _contains_any(search_text, ("life science", "life sciences", "biomedical", "biology", "omics")) and _contains_any(
        search_text,
        (
            "data analysis",
            "data tables",
            "metadata",
            "analysis contract",
            "structured result",
            "result tables",
            "hidden reference outputs",
            "private deterministic checks",
        ),
    )


def _goal_mentions_professional_engineering_artifact(full_text: str) -> bool:
    normalized_text = re.sub(r"[-_/]+", " ", full_text)
    search_text = f"{full_text} {normalized_text}"
    return _contains_any(search_text, ("engineering", "mechanical", "robot", "robotics", "design asset")) and _contains_any(
        search_text,
        (
            "assets",
            "structured metadata",
            "relationships",
            "constraints",
            "executable artifact",
            "validation evidence",
            "private deterministic checks",
            "isolated environment",
        ),
    )


def _mentions_app_state_workflow(text: str) -> bool:
    return _contains_any(
        text,
        ("browser", "email", "mail", "thunderbird", "vscode", "vs code", "extension", "state management"),
    ) or re.search(r"\bide\b", text) is not None


def _goal_mentions_gui_desktop(full_text: str) -> bool:
    gui_keywords = (
        "gui",
        "desktop",
        "cua",
        "computer use",
        "mouse",
        "keyboard",
        "cursor",
        "screenshot",
        "click",
        "drag",
        "scroll",
        "window",
        "ui interaction",
        "graphical interface",
        "remote desktop",
        "vnc",
        "rdp",
        "\u56fe\u5f62\u754c\u9762",
        "\u684c\u9762",
        "\u8f6f\u4ef6\u64cd\u4f5c",
    )
    return _contains_any(full_text, gui_keywords)


def _goal_mentions_browser_gui(full_text: str) -> bool:
    browser_keywords = (
        "browser gui",
        "browser automation",
        "browser ui",
        "web app",
        "website ui",
        "browser-based",
        "browser based",
        "page interaction",
        "click through",
    )
    return _contains_any(full_text, browser_keywords) or ("browser" in full_text and any(
        keyword in full_text for keyword in ("click", "scroll", "screenshot", "form", "page", "ui")
    ))


def _goal_mentions_desktop_software(full_text: str) -> bool:
    software_keywords = (
        "blender",
        "freecad",
        "kicad",
        "autocad",
        "solidworks",
        "fusion 360",
        "inventor",
        "catia",
        "ansys",
        "3d modeling",
        "3d model",
        "3d scene",
        "render",
        "mesh",
        "material",
        "animation",
        "cad",
        "bim",
        "cae",
        "cam",
        "rhino",
        "moldex3d",
        "powermill",
        "ltspice",
        "unreal",
        "davinci",
        "after effects",
        "video compositing",
        "chroma key",
        "spreadsheet",
        "excel",
        "word processor",
        "document editor",
        "presentation",
        "slides",
        "pdf viewer",
        "file manager",
        "photo editor",
        "image editor",
        "desktop software",
        "desktop app",
        "native app",
        "application window",
        "industrial software",
        "engineering software",
        "\u5de5\u4e1a\u8f6f\u4ef6",
        "\u5de5\u7a0b\u8f6f\u4ef6",
        "\u5efa\u6a21\u8f6f\u4ef6",
        "\u7535\u8def\u677f",
        "\u673a\u68b0\u8bbe\u8ba1",
    )
    return _contains_any(full_text, software_keywords)


def _goal_mentions_blender(full_text: str) -> bool:
    blender_keywords = (
        "blender",
        "3d modeling",
        "3d model",
        "3d scene",
        "mesh",
        "material",
        "rendered image",
        "render image",
        "cycles render",
        "eevee",
    )
    return _contains_any(full_text, blender_keywords)


def _goal_mentions_runtime_pipeline(full_text: str) -> bool:
    runtime_keywords = (
        "scientific computing",
        "simulation",
        "numerical",
        "pipeline",
        "dataset",
        "notebook",
        "zarr",
        "netcdf",
        "climate",
        "genomics",
        "variant calling",
        "bioinformatics",
        "clinical",
        "cell tracking",
        "financial statement",
        "sec filing",
        "10-k",
        "kubernetes",
        "k8s",
        "sre",
        "root cause",
        "incident",
        "pcap",
        "wireshark",
        "ghidra",
        "malware",
        "cloud cost",
        "chemistry",
        "materials",
        "phonon",
        "vqe",
    )
    return _contains_any(full_text, runtime_keywords)


def _runtime_task_family(full_text: str) -> AgentTaskFamily:
    diagnostic_keywords = ("kubernetes", "k8s", "sre", "root cause", "incident", "pcap", "wireshark", "ghidra", "malware")
    if _contains_any(full_text, diagnostic_keywords):
        return AgentTaskFamily.shell_debugging
    return AgentTaskFamily.data_analysis


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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
                target_difficulty=Difficulty.L5,
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
            target_difficulty=Difficulty.L4,
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
            target_difficulty=Difficulty.L4,
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
            target_difficulty=Difficulty.L4,
            needs_research=True,
            task_types=[TaskType.agent_interaction, TaskType.multi_turn],
            item_requirements=[
                "Build tasks from supplied resources rather than synthetic trivia.",
                "Keep the oracle tied to the provided materials.",
            ],
        ),
    ]


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
            task_family=AgentTaskFamily.desktop_software,
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
            task_family=AgentTaskFamily.desktop_software,
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
            task_family=AgentTaskFamily.desktop_software,
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
            task_family=AgentTaskFamily.gui_desktop,
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
            task_family=AgentTaskFamily.data_analysis,
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
            task_family=AgentTaskFamily.data_analysis,
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
            task_family=AgentTaskFamily.desktop_software,
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
            task_family=AgentTaskFamily.desktop_software,
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
            task_family=AgentTaskFamily.browser_gui,
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
            task_family=AgentTaskFamily.desktop_software,
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
            task_family=AgentTaskFamily.gui_desktop,
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
    if any(keyword in identity for keyword in ("code", "repo", "debug", "repair", "test", "python")):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_code_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} code repair",
            description=f"Executable code-repair tasks for {dimension.name}.",
            task_family=AgentTaskFamily.code_repair,
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
            task_family=AgentTaskFamily.multi_turn_delegation,
            environment_type=AgentEnvironmentType.dialogue,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} dialogue benchmark"],
            source_strategy="Use a scripted dialogue or task-specific user simulator.",
            tool_requirements=["multi-turn conversation"],
            construction_requirements=[
                "Specify the initial user request and follow-up turns clearly.",
                "Define pass/fail/partial scoring for the transcript.",
            ],
            scoring_strategy="Transcript-based judge scoring.",
        )
    if _goal_mentions_runtime_pipeline(full_text):
        task_family = _runtime_task_family(full_text)
        return AgentTaskBlueprint(
            id=f"{dimension.id}_{task_family.value}_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} executable workflow",
            description=f"Docker-backed executable workflow tasks for {dimension.name}.",
            task_family=task_family,
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
    if any(keyword in full_text for keyword in ("browser", "web", "search", "research", "api", "tool")):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_tool_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} tool use",
            description=f"Tool-using agent tasks for {dimension.name}.",
            task_family=AgentTaskFamily.api_tool_use,
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
        task_family=AgentTaskFamily.custom,
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


def plan_agent_benchmark(goal: str, config: BenchmarkConfig) -> tuple[EvalSpec, list[AgentTaskBlueprint]]:
    scale_budget = _safe_scale_budget(config.scale_budget)
    builder_mode = str(config.agent_task_builder or "llm").lower()
    strict_llm = builder_mode == "llm"
    if config.orchestrator_api_key:
        payload = {
            "goal": goal,
            "scale_budget": scale_budget.value,
            "scale_budget_workload": scale_budget_target_workload(scale_budget),
            "reference_model": config.reference_model.model_dump(mode="json") if config.reference_model else None,
            "benchmark_mode": config.benchmark_mode.value,
            "task_agent_schema": TASK_AGENT_SCHEMA,
            "task_agent_generation_guidance": TASK_AGENT_GENERATION_GUIDANCE,
            "agent_task_package_schema": AGENT_TASK_PACKAGE_SCHEMA,
            "agent_task_package_generation_guidance": AGENT_TASK_PACKAGE_GENERATION_GUIDANCE,
        }
        try:
            raw = call_llm(
                [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))],
                system=AGENT_BENCHMARK_PLANNER_PROMPT,
                model=config.orchestrator_model,
                api_key=config.orchestrator_api_key,
                base_url=config.orchestrator_base_url,
                backend=config.llm_backend,
                max_tokens=8192,
            )
            parsed = extract_json(raw)
        except Exception as exc:
            if strict_llm:
                raise RuntimeError(
                    "Agent benchmark planner LLM generation failed "
                    f"using model '{config.orchestrator_model}': {type(exc).__name__}: {exc}. "
                    "Set BenchmarkConfig.agent_task_builder='local' only for offline smoke tests, "
                    "or 'auto' if fallback planning is intentionally acceptable."
                ) from exc
            parsed = None
        if isinstance(parsed, dict):
            spec = _parse_dimensions(parsed, goal, scale_budget)
            blueprints: list[AgentTaskBlueprint] = []
            for idx, raw_blueprint in enumerate(parsed.get("agent_task_blueprints", []) or [], 1):
                if not isinstance(raw_blueprint, dict):
                    continue
                blueprints.append(
                    AgentTaskBlueprint(
                        id=str(raw_blueprint.get("id") or f"blueprint_{idx}"),
                        dimension_id=str(raw_blueprint.get("dimension_id") or spec.dimensions[0].id),
                        title=str(raw_blueprint.get("title") or f"Blueprint {idx}"),
                        description=str(raw_blueprint.get("description") or ""),
                        task_family=_safe_task_family(raw_blueprint.get("task_family")),
                        environment_type=_safe_environment_type(raw_blueprint.get("environment_type")),
                        expected_task_count=_safe_optional_int(raw_blueprint.get("expected_task_count")) or 1,
                        resource_queries=[str(q) for q in raw_blueprint.get("resource_queries", []) if q],
                        source_strategy=str(raw_blueprint.get("source_strategy") or ""),
                        tool_requirements=[str(x) for x in raw_blueprint.get("tool_requirements", []) if x],
                        construction_requirements=[str(x) for x in raw_blueprint.get("construction_requirements", []) if x],
                        scoring_strategy=str(raw_blueprint.get("scoring_strategy") or ""),
                    )
                )
            blueprints_by_dimension = {blueprint.dimension_id for blueprint in blueprints}
            for dimension in spec.dimensions:
                if dimension.id not in blueprints_by_dimension:
                    blueprints.append(_default_blueprint_for_dimension(dimension))
            if blueprints:
                return spec, blueprints
        if strict_llm:
            raise RuntimeError(
                "Agent benchmark planner LLM generation failed "
                f"using model '{config.orchestrator_model}': response did not contain a usable "
                "agent benchmark plan. Set BenchmarkConfig.agent_task_builder='local' only for "
                "offline smoke tests, or 'auto' if fallback planning is intentionally acceptable."
            )
    elif strict_llm:
        raise RuntimeError(
            "Agent benchmark planner requires orchestrator_api_key in default 'llm' mode. "
            "Set BenchmarkConfig.agent_task_builder='local' only for offline smoke tests, "
            "or 'auto' if fallback planning is intentionally acceptable."
        )
    spec = EvalSpec(
        id=_slug(goal),
        objective=goal,
        subjects=["user_supplied_targets"],
        task_types=[TaskType.agent_interaction, TaskType.multi_turn],
        dimensions=_fallback_dimensions(goal),
        scale_budget=scale_budget,
        scale=scale_budget_target_workload(scale_budget),
        metrics=[],
        planner_notes="Local fallback agent benchmark planner output.",
    )
    blueprints = [_default_blueprint_for_dimension(dimension) for dimension in spec.dimensions]
    if _goal_mentions_code(goal):
        blueprints = [
            (
                blueprint.model_copy(
                    update={
                        "id": f"{blueprint.dimension_id}_code_blueprint",
                        "title": f"{blueprint.title} code repair",
                        "task_family": AgentTaskFamily.code_repair,
                        "environment_type": AgentEnvironmentType.code_sandbox,
                        "tool_requirements": ["read_file", "write_file", "run_tests"],
                        "construction_requirements": [
                            "Include complete visible source files and hidden tests.",
                            "Require the agent to inspect failures and revise code.",
                        ],
                        "scoring_strategy": "Deterministic hidden tests with partial credit for running tests.",
                    }
                )
                if blueprint.dimension_id == "agent_recovery"
                else blueprint
            )
            for blueprint in blueprints
        ]
    return spec, blueprints
