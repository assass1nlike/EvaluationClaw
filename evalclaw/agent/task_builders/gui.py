"""GUI desktop fallback agent tasks."""
from __future__ import annotations

import json

from ...types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    EvalDimension,
    TaskBlueprint,
    TaskDefinition,
    TaskScoringSpec,
    TaskType,
)
from ..goal_detection import (
    _contains_any,
    _goal_mentions_blender,
    _goal_mentions_browser_gui,
    _goal_mentions_desktop_software,
    _goal_mentions_multi_industrial_workflow,
    _mentions_app_state_workflow,
)
from .base import _agent_system_prompt, _task_id, _task_title
from .gui_variants import (
    get_app_state_variants,
    get_artifact_variants,
    get_blender_variants,
    get_cad_variants,
    get_industrial_workflow_variants,
    get_office_variants,
    get_video_variants,
)


def _minimal_kicad_pcb_fixture(board: dict[str, object]) -> str:
    outline = board.get("outline") if isinstance(board.get("outline"), dict) else {}
    holes = board.get("mounting_holes") if isinstance(board.get("mounting_holes"), list) else []
    components = board.get("components") if isinstance(board.get("components"), list) else []
    board_name = str(board.get("board_name") or "evalclaw_board")
    width = float(outline.get("width", 60.0)) if isinstance(outline, dict) else 60.0
    height = float(outline.get("height", 40.0)) if isinstance(outline, dict) else 40.0
    fixture = [
        "(kicad_pcb (version 20240108) (generator evalclaw)",
        '  (general (thickness 1.6))',
        '  (paper "A4")',
        '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (32 "B.Adhes" user) (44 "Edge.Cuts" user))',
        f'  (title_block (title "{board_name}") (company "EvaluationClaw"))',
        f'  (gr_line (start 0 0) (end {width:.2f} 0) (layer "Edge.Cuts") (width 0.1))',
        f'  (gr_line (start {width:.2f} 0) (end {width:.2f} {height:.2f}) (layer "Edge.Cuts") (width 0.1))',
        f'  (gr_line (start {width:.2f} {height:.2f}) (end 0 {height:.2f}) (layer "Edge.Cuts") (width 0.1))',
        f'  (gr_line (start 0 {height:.2f}) (end 0 0) (layer "Edge.Cuts") (width 0.1))',
    ]
    for idx, hole in enumerate(holes, start=1):
        if not isinstance(hole, dict):
            continue
        x = float(hole.get("x", 5.0))
        y = float(hole.get("y", 5.0))
        diameter = float(hole.get("diameter", 3.0))
        fixture.append(
            f'  (footprint "MountingHole:MountingHole_{diameter:.1f}mm" (layer "F.Cu") '
            f'(at {x:.2f} {y:.2f}) (property "Reference" "H{idx}"))'
        )
    for idx, component in enumerate(components, start=1):
        if not isinstance(component, dict):
            continue
        ref = str(component.get("ref") or f"U{idx}")
        x = float(component.get("x", width / 2.0))
        y = float(component.get("y", height / 2.0))
        fixture.append(
            f'  (footprint "EvalClaw:ComponentEnvelope" (layer "F.Cu") (at {x:.2f} {y:.2f}) '
            f'(property "Reference" "{ref}"))'
        )
    fixture.append(")\n")
    return "\n".join(fixture)


def _placeholder_step_fixture(title: str, variant: dict[str, object]) -> str:
    return (
        "ISO-10303-21;\n"
        "HEADER;\n"
        f"FILE_DESCRIPTION(('EvaluationClaw placeholder fixture: {title}'),'2;1');\n"
        "FILE_NAME('evalclaw_fixture.step','2026-07-10T00:00:00',('EvaluationClaw'),('EvaluationClaw'),'','','');\n"
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN_CC2'));\n"
        "ENDSEC;\n"
        "DATA;\n"
        f"/* Source workflow: {variant.get('title', 'industrial workflow')} */\n"
        "ENDSEC;\n"
        "END-ISO-10303-21;\n"
    )


def _industrial_hidden_evaluator(
    *,
    required_artifacts: list[str],
    required_apps: list[str],
    min_handoffs: int,
    report_file: str | None = "assembly_clearance_report.json",
) -> str:
    required_names = [artifact.removeprefix("Desktop/exports/") for artifact in required_artifacts]
    return (
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        "desktop = Path(os.environ.get('EVALCLAW_DESKTOP_DIR', str(Path.home() / 'Desktop')))\n"
        "exports = desktop / 'exports'\n"
        f"required = {json.dumps(required_names, ensure_ascii=False)}\n"
        f"required_apps = {json.dumps([app.lower() for app in required_apps], ensure_ascii=False)}\n"
        f"min_handoffs = {min_handoffs}\n"
        f"report_file = {json.dumps(report_file, ensure_ascii=False)}\n"
        "missing = [name for name in required if not (exports / name).is_file() or (exports / name).stat().st_size == 0]\n"
        "issues = []\n"
        "score = 1.0\n"
        "if missing:\n"
        "    score -= 0.45\n"
        "    issues.append({'missing_artifacts': missing})\n"
        "try:\n"
        "    manifest = json.loads((exports / 'workflow_manifest.json').read_text(encoding='utf-8'))\n"
        "except Exception as exc:\n"
        "    manifest = {}\n"
        "    score -= 0.2\n"
        "    issues.append({'manifest_error': str(exc)})\n"
        "apps = {str(app).lower() for app in manifest.get('applications_used', [])}\n"
        "missing_apps = set(required_apps) - apps\n"
        "if missing_apps:\n"
        "    score -= 0.2\n"
        "    issues.append({'missing_applications': sorted(missing_apps)})\n"
        "handoffs = manifest.get('handoffs', [])\n"
        "if not isinstance(handoffs, list) or len(handoffs) < min_handoffs:\n"
        "    score -= 0.1\n"
        "    issues.append({'handoffs': f'expected at least {min_handoffs} artifact handoffs'})\n"
        "if report_file:\n"
        "    try:\n"
        "        report = json.loads((exports / report_file).read_text(encoding='utf-8'))\n"
        "    except Exception as exc:\n"
        "        report = {}\n"
        "        score -= 0.1\n"
        "        issues.append({'report_error': str(exc), 'report_file': report_file})\n"
        "    if report and report.get('units') != 'mm':\n"
        "        score -= 0.05\n"
        "        issues.append({'units': 'expected mm in report'})\n"
        "    if report and report.get('min_clearance_mm') is not None and float(report.get('min_clearance_mm', 0)) <= 0:\n"
        "        score -= 0.05\n"
        "        issues.append({'clearance': 'min_clearance_mm must be positive'})\n"
        "score = max(0.0, min(1.0, score))\n"
        "print(json.dumps({'score': score, 'missing': missing, 'issues': issues}, indent=2))\n"
        "sys.exit(0 if score >= 0.8 else 1)\n"
    )


def _gui_desktop_task_for_blueprint(
    dimension: EvalDimension,
    blueprint: TaskBlueprint,
    *,
    index: int = 1,
) -> TaskDefinition:
    blueprint_text = " ".join(
        [dimension.id, dimension.name, dimension.description, dimension.approach, blueprint.title, blueprint.description]
    ).lower()
    route_text = " ".join(
        [
            dimension.id,
            dimension.name,
            dimension.description,
            dimension.approach,
            " ".join(dimension.item_requirements),
            blueprint.id,
            blueprint.title,
            blueprint.description,
            blueprint.source_strategy,
            " ".join(blueprint.construction_requirements),
        ]
    ).lower()
    vm_spec = {
        "isolation": "fresh_snapshot",
        "image": "evalclaw-gui-ubuntu-22.04",
        "snapshot": "clean",
        "display": {"width": 1280, "height": 900, "scale": 1.0},
        "network": "restricted",
        "locale": "en-US",
        "bridge": {"required": True, "protocol": "evalclaw.gui_bridge.v1"},
    }
    hidden_files: dict[str, str] = {}
    if _goal_mentions_browser_gui(route_text):
        prompt = (
            "Use the GUI browser session to review the local customer portal, update the priority field for "
            "ticket EC-104 to high, save the change, and run the bridge evaluation when finished."
        )
        visible_files = {
            "portal_fixture/tickets.json": (
                "[\n"
                '  {"id": "EC-103", "priority": "normal", "owner": "Nora"},\n'
                '  {"id": "EC-104", "priority": "normal", "owner": "Kai"}\n'
                "]\n"
            ),
            "portal_fixture/README.md": (
                "The bridge should launch a browser with a local ticket portal backed by tickets.json. "
                "The target agent must use GUI actions to modify ticket EC-104 rather than editing the file directly."
            ),
        }
        session = {
            "kind": "browser_gui",
            "application": "browser",
            "entrypoint": "local_web_app",
            "start_url": "http://evalclaw.local/tickets",
            "instruction": prompt,
            "assets": ["portal_fixture/tickets.json", "portal_fixture/README.md"],
            "expected_artifacts": ["bridge_state:ticket_priority"],
            "allowed_direct_file_edits": False,
        }
        vm_spec = {
            **vm_spec,
            "image": "evalclaw-browser-gui",
            "required_software": ["chromium", "evalclaw-desktop-bridge"],
        }
        evaluation = {
            "method": "bridge_state_check",
            "checks": [
                {
                    "name": "ticket_priority_updated",
                    "description": "Ticket EC-104 has priority high in the browser-backed application state.",
                    "weight": 0.8,
                },
                {
                    "name": "gui_path_used",
                    "description": "The trace shows screenshot/mouse/keyboard interactions rather than direct data-file edits.",
                    "weight": 0.2,
                },
            ],
            "pass_criteria": "EC-104 is saved with priority high and no unrelated ticket is modified.",
            "partial_criteria": "The agent reaches the correct page or selects EC-104 but does not complete the saved change.",
            "fail_criteria": "The agent does not use the GUI state or changes the wrong ticket.",
        }
        tags = ["gui_desktop", "browser_gui", "bridge"]
    elif _mentions_app_state_workflow(route_text):
        app_state_variants = get_app_state_variants()
        variant = app_state_variants[(index - 1) % len(app_state_variants)]
        prompt = variant["prompt"]
        visible_files = variant["visible_files"]
        hidden_files = variant["hidden_files"]
        session = {
            "kind": "application_state",
            "application": variant["application"],
            "launch": {"application": variant["application"]},
            "instruction": prompt,
            "assets": list(visible_files.keys()),
            "expected_artifacts": variant["expected_artifacts"],
            "preferred_tools": ["screenshot", "click", "scroll", "key", "type", "run_command", "evaluate"],
            "allowed_direct_file_edits": False,
        }
        vm_spec = {
            **vm_spec,
            "image": variant["image"],
            "required_software": variant["required_software"],
            "artifacts_dir": "Desktop",
        }
        evaluation = {
            "method": "app_state_check",
            "expected_artifacts": variant["expected_artifacts"],
            "checks": variant["checks"],
            "pass_criteria": "The requested application state is saved exactly and the trace shows GUI interaction.",
            "partial_criteria": "The agent reaches the correct application/settings area but misses one state requirement.",
            "fail_criteria": "The target application state is not changed or the task is bypassed through direct file edits.",
            "bridge_evaluator": {
                "type": "hidden_script",
                "hidden_script": variant["hidden_script"],
                "requires_trace_tools": ["screenshot", "click", "key", "evaluate"],
            },
        }
        tags = ["gui_desktop", "application_state", variant["application"], "bridge"]
    elif _goal_mentions_multi_industrial_workflow(route_text):
        workflow_variants = get_industrial_workflow_variants()
        variant = workflow_variants[(index - 1) % len(workflow_variants)]
        dimension_focus = f"Dimension focus: {dimension.name}. {dimension.description}".strip()
        focus_lower = " ".join([dimension.id, dimension.name, dimension.description]).lower()
        if _contains_any(focus_lower, ("change", "propagation", "parametric", "revision")):
            focus_instruction = (
                "Emphasize design-change propagation: a changed board/mechanical constraint must be carried "
                "through EDA, CAD, and rendering artifacts with the before/after change recorded in the manifest."
            )
        elif _contains_any(focus_lower, ("eda", "pcb", "mechanical handoff", "fit verification")):
            focus_instruction = (
                "Emphasize the KiCad-to-FreeCAD handoff: exported PCB geometry, mounting holes, component "
                "keepouts, enclosure fit, and clearance verification must be explicitly recorded."
            )
        elif _contains_any(focus_lower, ("render", "photorealistic", "visual")):
            focus_instruction = (
                "Emphasize the FreeCAD-to-Blender handoff: imported mechanical geometry, material assignment, "
                "camera/light setup, and final render review must be explicitly recorded."
            )
        else:
            focus_instruction = (
                "Emphasize cross-application artifact integrity: each application must consume an artifact from "
                "the previous stage and produce a checkable artifact for the next stage."
            )
        cad_render_focus = _contains_any(
            focus_lower,
            ("cad-to-render", "cad to render", "freecad-to-blender", "freecad to blender", "render", "photorealistic", "visual"),
        )
        normalized_focus = focus_lower.replace("_", " ").replace("-", " ")
        ecad_focus = f" ecad " in f" {normalized_focus} " or _contains_any(
            focus_lower,
            ("eda", "pcb", "kicad", "enclosure", "mechanical handoff", "fit verification"),
        )
        full_chain_focus = _contains_any(
            focus_lower,
            (
                "cross-application",
                "cross_application",
                "end-to-end",
                "end_to_end",
                "multi-software",
                "multi software",
                "multi-app",
                "multi_app",
                "manufacturing",
            ),
        )
        if _contains_any(focus_lower, ("change", "propagation", "parametric", "revision")) or full_chain_focus:
            workflow_kind = "eda_cad_render"
        elif ecad_focus:
            workflow_kind = "eda_cad"
        elif cad_render_focus:
            workflow_kind = "cad_render"
        else:
            workflow_kind = "eda_cad_render"

        manifest_template = {
            "units": "mm",
            "applications_used": [],
            "handoffs": [],
            "artifacts": {},
            "checks_performed": [],
            "dimension_focus": dimension.name,
            "notes": "",
        }
        visible_files = {
            "Desktop/industrial_workflow/brief.md": (
                f"# Industrial multi-software workflow\n\nWorkflow: {variant['title']}\n\n"
                f"{dimension_focus}\n\n{focus_instruction}\n\n"
                "All outputs must be placed in Desktop/exports. Keep units in millimeters and record every "
                "application handoff in workflow_manifest.json.\n"
            ),
            "Desktop/industrial_workflow/workflow_manifest_template.json": json.dumps(
                manifest_template,
                ensure_ascii=False,
                indent=2,
            ),
        }
        workflow_stages: list[dict[str, object]]
        checks: list[dict[str, object]]
        report_file: str | None = "assembly_clearance_report.json"
        if workflow_kind == "cad_render":
            applications = ["FreeCAD", "Blender"]
            expected_artifacts = [
                "Desktop/exports/refined_model.step",
                "Desktop/exports/render_review_report.json",
                "Desktop/exports/product_render.png",
                "Desktop/exports/workflow_manifest.json",
            ]
            visible_files.update(
                {
                    "Desktop/industrial_workflow/base_model.step": _placeholder_step_fixture(
                        "starting mechanical model",
                        variant,
                    ),
                    "Desktop/industrial_workflow/mechanical_constraints.json": json.dumps(
                        variant["constraints"],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "Desktop/industrial_workflow/render_requirements.json": json.dumps(
                        variant["visual"],
                        ensure_ascii=False,
                        indent=2,
                    ),
                }
            )
            workflow_stages = [
                {
                    "id": "mechanical_model_refinement",
                    "application": "FreeCAD",
                    "inputs": [
                        "Desktop/industrial_workflow/base_model.step",
                        "Desktop/industrial_workflow/mechanical_constraints.json",
                    ],
                    "outputs": ["Desktop/exports/refined_model.step", "Desktop/exports/render_review_report.json"],
                    "goal": variant["cad_goal"],
                },
                {
                    "id": "visual_review_render",
                    "application": "Blender",
                    "inputs": [
                        "Desktop/exports/refined_model.step",
                        "Desktop/industrial_workflow/render_requirements.json",
                    ],
                    "outputs": ["Desktop/exports/product_render.png"],
                    "goal": variant["render_goal"],
                },
            ]
            prompt = (
                "Use the VM desktop industrial software stack to complete a CAD-to-render review workflow. "
                f"Start in FreeCAD to {variant['cad_goal']}; then use Blender to {variant['render_goal']}. "
                "Save the required artifacts under Desktop/exports, write workflow_manifest.json with application "
                "provenance and unit assumptions, and run the bridge evaluation. This task must not be solved as a "
                f"text-only report or inside a single application. {focus_instruction}"
            )
            checks = [
                {
                    "name": "cad_model_refinement",
                    "description": "FreeCAD-stage refined_model.step and render_review_report.json exist and reflect constraints.",
                    "weight": 0.35,
                },
                {
                    "name": "render_review_artifact",
                    "description": "Blender-stage product_render.png exists, is non-empty, and reflects requested materials/camera.",
                    "weight": 0.25,
                },
                {
                    "name": "workflow_manifest_provenance",
                    "description": "workflow_manifest.json records FreeCAD, Blender, units, handoffs, and artifact dependencies.",
                    "weight": 0.25,
                },
                {
                    "name": "multi_app_gui_workflow_used",
                    "description": "The trace shows interaction with both industrial applications.",
                    "weight": 0.15,
                },
            ]
            report_file = "render_review_report.json"
            image_name = "evalclaw-industrial-cad-render-gui"
        elif workflow_kind == "eda_cad":
            applications = ["KiCad", "FreeCAD"]
            expected_artifacts = [
                "Desktop/exports/pcb_assembly.step",
                "Desktop/exports/enclosure.step",
                "Desktop/exports/assembly_clearance_report.json",
                "Desktop/exports/workflow_manifest.json",
            ]
            visible_files.update(
                {
                    "Desktop/industrial_workflow/source_project.kicad_pcb": _minimal_kicad_pcb_fixture(variant["board"]),
                    "Desktop/industrial_workflow/board_requirements.json": json.dumps(
                        variant["board"],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "Desktop/industrial_workflow/mechanical_constraints.json": json.dumps(
                        variant["constraints"],
                        ensure_ascii=False,
                        indent=2,
                    ),
                }
            )
            workflow_stages = [
                {
                    "id": "eda_board_export",
                    "application": "KiCad",
                    "inputs": [
                        "Desktop/industrial_workflow/source_project.kicad_pcb",
                        "Desktop/industrial_workflow/board_requirements.json",
                    ],
                    "outputs": ["Desktop/exports/pcb_assembly.step"],
                    "goal": variant["eda_goal"],
                },
                {
                    "id": "mechanical_enclosure_fit",
                    "application": "FreeCAD",
                    "inputs": [
                        "Desktop/exports/pcb_assembly.step",
                        "Desktop/industrial_workflow/mechanical_constraints.json",
                    ],
                    "outputs": ["Desktop/exports/enclosure.step", "Desktop/exports/assembly_clearance_report.json"],
                    "goal": variant["cad_goal"],
                },
            ]
            prompt = (
                "Use the VM desktop industrial software stack to complete an ECAD-to-mechanical enclosure workflow. "
                f"Start in KiCad to {variant['eda_goal']}; then use FreeCAD to {variant['cad_goal']}. Save the "
                "required artifacts under Desktop/exports, write workflow_manifest.json with application provenance "
                "and unit assumptions, and run the bridge evaluation. This task must not be solved as a text-only "
                f"report or inside a single application. {focus_instruction}"
            )
            checks = [
                {
                    "name": "eda_step_export",
                    "description": "KiCad-stage pcb_assembly.step exists and is referenced in the manifest.",
                    "weight": 0.3,
                },
                {
                    "name": "cad_enclosure_and_clearance",
                    "description": "FreeCAD-stage enclosure.step and assembly_clearance_report.json satisfy fit checks.",
                    "weight": 0.35,
                },
                {
                    "name": "workflow_manifest_provenance",
                    "description": "workflow_manifest.json records KiCad, FreeCAD, units, handoffs, and artifact dependencies.",
                    "weight": 0.25,
                },
                {
                    "name": "multi_app_gui_workflow_used",
                    "description": "The trace shows interaction with both industrial applications.",
                    "weight": 0.1,
                },
            ]
            image_name = "evalclaw-industrial-eda-cad-gui"
        else:
            applications = ["KiCad", "FreeCAD", "Blender"]
            expected_artifacts = [
                "Desktop/exports/pcb_assembly.step",
                "Desktop/exports/enclosure.step",
                "Desktop/exports/assembly_clearance_report.json",
                "Desktop/exports/product_render.png",
                "Desktop/exports/workflow_manifest.json",
            ]
            visible_files.update(
                {
                    "Desktop/industrial_workflow/source_project.kicad_pcb": _minimal_kicad_pcb_fixture(variant["board"]),
                    "Desktop/industrial_workflow/board_requirements.json": json.dumps(
                        variant["board"],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "Desktop/industrial_workflow/mechanical_constraints.json": json.dumps(
                        variant["constraints"],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "Desktop/industrial_workflow/render_requirements.json": json.dumps(
                        variant["visual"],
                        ensure_ascii=False,
                        indent=2,
                    ),
                }
            )
            workflow_stages = [
                {
                    "id": "eda_board_export",
                    "application": "KiCad",
                    "inputs": [
                        "Desktop/industrial_workflow/source_project.kicad_pcb",
                        "Desktop/industrial_workflow/board_requirements.json",
                    ],
                    "outputs": ["Desktop/exports/pcb_assembly.step"],
                    "goal": variant["eda_goal"],
                },
                {
                    "id": "mechanical_enclosure_fit",
                    "application": "FreeCAD",
                    "inputs": [
                        "Desktop/exports/pcb_assembly.step",
                        "Desktop/industrial_workflow/mechanical_constraints.json",
                    ],
                    "outputs": ["Desktop/exports/enclosure.step", "Desktop/exports/assembly_clearance_report.json"],
                    "goal": variant["cad_goal"],
                },
                {
                    "id": "visual_review_render",
                    "application": "Blender",
                    "inputs": [
                        "Desktop/exports/pcb_assembly.step",
                        "Desktop/exports/enclosure.step",
                        "Desktop/industrial_workflow/render_requirements.json",
                    ],
                    "outputs": ["Desktop/exports/product_render.png"],
                    "goal": variant["render_goal"],
                },
            ]
            prompt = (
                "Use the VM desktop industrial software stack to complete the "
                f"{variant['title']} workflow. Start in KiCad to {variant['eda_goal']}; then use FreeCAD to "
                f"{variant['cad_goal']}; then use Blender to {variant['render_goal']}. Save the required artifacts "
                "under Desktop/exports, write workflow_manifest.json with application provenance and unit assumptions, "
                "and run the bridge evaluation. This task must not be solved as a text-only report or inside a single "
                f"application. {focus_instruction}"
            )
            checks = [
                {
                    "name": "eda_step_export",
                    "description": "KiCad-stage pcb_assembly.step exists and is referenced in the manifest.",
                    "weight": 0.2,
                },
                {
                    "name": "cad_enclosure_and_clearance",
                    "description": "FreeCAD-stage enclosure.step and assembly_clearance_report.json satisfy geometry checks.",
                    "weight": 0.3,
                },
                {
                    "name": "render_review_artifact",
                    "description": "Blender-stage product_render.png exists, is non-empty, and reflects requested materials/camera.",
                    "weight": 0.2,
                },
                {
                    "name": "workflow_manifest_provenance",
                    "description": "workflow_manifest.json records KiCad, FreeCAD, Blender, units, and handoffs.",
                    "weight": 0.2,
                },
                {
                    "name": "multi_app_gui_workflow_used",
                    "description": "The trace shows interaction with multiple industrial applications.",
                    "weight": 0.1,
                },
            ]
            image_name = "evalclaw-industrial-cad-eda-gui"

        app_commands = {"KiCad": "kicad", "FreeCAD": "freecad", "Blender": "blender"}
        software_versions = {
            "KiCad": "kicad>=8",
            "FreeCAD": "freecad>=0.21",
            "Blender": "blender>=4.0",
        }
        apt_packages = [app_commands[application] for application in applications]
        hidden_files = {
            "hidden/evaluate_industrial_workflow.py": _industrial_hidden_evaluator(
                required_artifacts=expected_artifacts,
                required_apps=applications,
                min_handoffs=max(1, len(applications) - 1),
                report_file=report_file,
            )
        }
        visible_files["Desktop/industrial_workflow/brief.md"] += "\nRequired application chain:\n" + "\n".join(
            f"{idx}. {stage['application']}: {stage['goal']}" for idx, stage in enumerate(workflow_stages, start=1)
        )
        visible_files["Desktop/industrial_workflow/brief.md"] += (
            "\n\nAll required initial assets are in Desktop/industrial_workflow. "
            "Do not replace the task with a text-only report.\n"
        )
        session = {
            "kind": "desktop_software_multi_app",
            "application": "multi_app_industrial_workflow",
            "applications": applications,
            "launch_sequence": [
                {
                    "application": application,
                    "command": app_commands[application],
                    "working_directory": "Desktop/industrial_workflow",
                }
                for application in applications
            ],
            "workflow_stages": workflow_stages,
            "handoff_artifacts": expected_artifacts[:-1],
            "instruction": prompt,
            "assets": list(visible_files.keys()),
            "expected_artifacts": expected_artifacts,
            "preferred_tools": [
                "screenshot",
                "click",
                "drag",
                "scroll",
                "key",
                "type",
                "run_command",
                "read_file",
                "write_file",
                "evaluate",
            ],
            "allowed_direct_file_edits": False,
            "allowed_automation": (
                "Application macros/scripts are allowed only when launched through the corresponding industrial "
                "application and recorded in workflow_manifest.json."
            ),
        }
        vm_spec = {
            **vm_spec,
            "image": image_name,
            "display": {"width": 1600, "height": 1000, "scale": 1.0},
            "gpu": "optional",
            "required_software": [software_versions[application] for application in applications]
            + ["python3", "evalclaw-desktop-bridge"],
            "software_stack": {
                "eda": "KiCad" if "KiCad" in applications else None,
                "mechanical_cad": "FreeCAD" if "FreeCAD" in applications else None,
                "rendering": "Blender" if "Blender" in applications else None,
            },
            "provisioning": {
                "enabled": True,
                "strategy": "cloud_init_apt.v1",
                "base_os": "ubuntu",
                "apt_packages": [*apt_packages, "python3", "python3-pip", "xvfb", "xdotool"],
                "commands": [
                    "mkdir -p /opt/evalclaw/bridge",
                    "if command -v evalclaw-desktop-bridge >/dev/null 2>&1; then "
                    "echo bridge-ready >/opt/evalclaw/bridge/status.txt; "
                    "else echo 'evalclaw-desktop-bridge install command not configured; base image or VM provider must supply the bridge service' "
                    ">/opt/evalclaw/bridge/status.txt; fi",
                ],
            },
            "artifacts_dir": "Desktop/exports",
        }
        evaluation = {
            "method": "industrial_multi_app_artifact_check",
            "expected_artifacts": expected_artifacts,
            "checks": checks,
            "pass_criteria": (
                "All required intermediate and final artifacts exist, the manifest records the required application "
                "chain with millimeter units, and bridge checks confirm the multi-application workflow."
            ),
            "partial_criteria": (
                "At least two applications are used and most artifacts are produced, but one handoff, report detail, "
                "render requirement, or manifest field is incomplete."
            ),
            "fail_criteria": (
                "The task is completed inside a single application, produces only a text report, omits core "
                "intermediate artifacts, or lacks a usable workflow manifest."
            ),
            "bridge_evaluator": {
                "type": "industrial_workflow_artifact_check",
                "hidden_script": "hidden/evaluate_industrial_workflow.py",
                "requires_trace_tools": ["screenshot", "click", "key", "run_command", "evaluate"],
            },
        }
        tags = [
            "gui_desktop",
            "desktop_software",
            "industrial_workflow",
            "multi_app",
            "artifact_handoff",
            *(application.lower() for application in applications),
            "vm",
            "bridge",
        ]
    elif _goal_mentions_blender(route_text):
        blender_variants = get_blender_variants()
        scene_summary, requirement_lines = blender_variants[(index - 1) % len(blender_variants)]
        prompt = (
            "Use the Blender desktop application inside the VM to create a low-poly evaluation scene: "
            f"{scene_summary}. Save the project as Desktop/evalclaw_scene.blend, render a PNG to "
            "Desktop/evalclaw_render.png, and run the bridge evaluation."
        )
        visible_files = {
            "Desktop/scene_requirements.md": (
                "# Blender scene requirements\n\n"
                "- Create or edit the scene in Blender through the GUI.\n"
                + "\n".join(requirement_lines)
                + "\n"
                "- Save Desktop/evalclaw_scene.blend and render Desktop/evalclaw_render.png.\n"
            ),
            "Desktop/starter_scene.py": (
                "import bpy\n\n"
                "bpy.ops.object.select_all(action='SELECT')\n"
                "bpy.ops.object.delete()\n"
                "bpy.ops.mesh.primitive_plane_add(size=6, location=(0, 0, 0))\n"
                "plane = bpy.context.object\n"
                "plane.name = 'gray_ground_plane'\n"
                "mat = bpy.data.materials.new('neutral_gray')\n"
                "mat.diffuse_color = (0.45, 0.45, 0.45, 1)\n"
                "plane.data.materials.append(mat)\n"
            ),
        }
        session = {
            "kind": "desktop_software",
            "application": "blender",
            "launch": {
                "command": "blender --factory-startup --python Desktop/starter_scene.py",
                "working_directory": "Desktop",
            },
            "instruction": prompt,
            "assets": ["Desktop/scene_requirements.md", "Desktop/starter_scene.py"],
            "expected_artifacts": ["Desktop/evalclaw_scene.blend", "Desktop/evalclaw_render.png"],
            "preferred_tools": [
                "screenshot",
                "click",
                "drag",
                "scroll",
                "key",
                "type",
                "run_command",
                "read_file",
                "evaluate",
            ],
            "allowed_direct_file_edits": False,
            "notes": "The bridge may expose Blender console/menu automation, but the target should still operate the desktop session.",
        }
        vm_spec = {
            **vm_spec,
            "image": "evalclaw-blender-gui",
            "display": {"width": 1440, "height": 1000, "scale": 1.0},
            "gpu": "optional",
            "required_software": ["blender>=4.0", "python3", "evalclaw-desktop-bridge"],
            "artifacts_dir": "Desktop",
        }
        evaluation = {
            "method": "blender_artifact_check",
            "expected_artifacts": ["Desktop/evalclaw_scene.blend", "Desktop/evalclaw_render.png"],
            "checks": [
                {
                    "name": "blend_file_exists",
                    "description": "Desktop/evalclaw_scene.blend exists and can be opened by Blender.",
                    "weight": 0.2,
                },
                {
                    "name": "required_objects",
                    "description": "The .blend file contains a cube, sphere, plane, camera, and area light.",
                    "weight": 0.25,
                },
                {
                    "name": "materials_and_positions",
                    "description": "The cube is blue, the sphere is red, the plane is gray, and the sphere is to the cube's right.",
                    "weight": 0.25,
                },
                {
                    "name": "render_file_exists",
                    "description": "Desktop/evalclaw_render.png exists and is a non-empty image rendered from the scene.",
                    "weight": 0.2,
                },
                {
                    "name": "gui_workflow_used",
                    "description": "The trace shows interaction with the Blender desktop session rather than only writing final artifacts directly.",
                    "weight": 0.1,
                },
            ],
            "pass_criteria": "The saved Blender scene and rendered PNG satisfy all object, material, lighting, and camera requirements.",
            "partial_criteria": "The agent creates a usable Blender scene with at least two required elements but misses some material, render, or framing requirements.",
            "fail_criteria": "No valid Blender scene artifact is produced or the task is completed outside the desktop/VM workflow.",
            "bridge_evaluator": {
                "type": "blender_python",
                "script": "Open the .blend file, inspect objects/materials/positions/camera/light, and verify the PNG dimensions and non-empty pixels.",
            },
        }
        tags = ["gui_desktop", "desktop_software", "blender", "3d_modeling", "vm", "bridge"]
    elif _goal_mentions_desktop_software(route_text):
        if _contains_any(
            route_text,
            (
                "professional artifact",
                "artifact reconstruction",
                "hidden reference",
                "hidden grading",
                "visual media",
                "professional workflow",
            ),
        ):
            artifact_variants = get_artifact_variants()
            if _contains_any(
                blueprint_text,
                (
                    "robot",
                    "robotics",
                    "urdf",
                    "kinematic",
                    "joint limits",
                    "engineering assets",
                    "structured metadata",
                    "relationships and constraints",
                    "executable artifact",
                ),
            ):
                variant = artifact_variants[2]
            else:
                variant = artifact_variants[(index - 1) % 2]
            prompt = variant["prompt"]
            visible_files = variant["visible_files"]
            hidden_files = variant["hidden_files"]
            session = {
                "kind": "professional_artifact_workflow",
                "application": variant["application"],
                "launch": {"path": "Desktop/reference"},
                "instruction": prompt,
                "assets": list(visible_files.keys()),
                "expected_artifacts": variant["expected_artifacts"],
                "preferred_tools": ["screenshot", "click", "drag", "key", "type", "read_file", "write_file", "run_command", "evaluate"],
                "allowed_direct_file_edits": True,
            }
            vm_spec = {
                **vm_spec,
                "image": variant["image"],
                "required_software": variant["required_software"],
                "artifacts_dir": "Desktop/deliverables",
            }
            evaluation = {
                "method": "professional_artifact_check",
                "expected_artifacts": variant["expected_artifacts"],
                "checks": variant["checks"],
                "pass_criteria": "All required deliverables exist, match the visible professional brief, and pass hidden artifact checks.",
                "partial_criteria": "A usable subset of deliverables exists but one feature, export, or provenance requirement is incomplete.",
                "fail_criteria": "The agent produces only a text answer or no checkable professional artifact package.",
                "bridge_evaluator": {
                    "type": "hidden_script",
                    "hidden_script": "hidden/evaluate_artifact.py",
                    "requires_trace_tools": ["screenshot", "run_command", "evaluate"],
                },
                "software_notes": variant["software_notes"],
            }
            tags = ["gui_desktop", "desktop_software", "professional_artifact", "ale_style", "bridge"]
        elif _contains_any(route_text, ("office", "spreadsheet", "document", "presentation", "libreoffice")):
            office_variants = get_office_variants()
            variant = office_variants[(index - 1) % len(office_variants)]
            prompt = variant["prompt"]
            visible_files = variant["visible_files"]
            hidden_files = variant["hidden_files"]
            session = {
                "kind": "desktop_software",
                "application": variant["application"],
                "launch": {"file": next(iter(visible_files))},
                "instruction": prompt,
                "assets": list(visible_files.keys()),
                "expected_artifacts": variant["expected_artifacts"],
                "preferred_tools": ["screenshot", "click", "drag", "key", "type", "read_file", "run_command", "evaluate"],
                "allowed_direct_file_edits": False,
            }
            vm_spec = {
                **vm_spec,
                "image": variant["image"],
                "required_software": variant["required_software"],
                "artifacts_dir": "Desktop",
            }
            evaluation = {
                "method": "office_artifact_check",
                "expected_artifacts": variant["expected_artifacts"],
                "checks": variant["checks"],
                "pass_criteria": "The exported office artifact exists, contains the exact requested values/content, and the GUI workflow is evidenced in the trace.",
                "partial_criteria": "The agent opens the correct application and produces a partially correct artifact.",
                "fail_criteria": "No usable office artifact is produced or the task is completed outside the intended GUI workflow.",
                "bridge_evaluator": {
                    "type": "hidden_script",
                    "hidden_script": "hidden/evaluate_office_artifact.py",
                    "requires_trace_tools": ["screenshot", "click", "key", "evaluate"],
                },
            }
            tags = ["gui_desktop", "desktop_software", "office", variant["application"], "bridge"]
        elif _contains_any(route_text, ("image", "photo", "gimp", "creative")):
            prompt = (
                "Use the desktop image editor to open Desktop/source.ppm. Create a derived image where the red "
                "marker pixels are converted to blue while the gray background stays unchanged, export "
                "Desktop/edited_marker.ppm, and run the bridge evaluation."
            )
            visible_files = {
                "Desktop/source.ppm": (
                    "P3\n4 4\n255\n"
                    "200 200 200 200 200 200 255 0 0 255 0 0\n"
                    "200 200 200 255 0 0 255 0 0 200 200 200\n"
                    "200 200 200 255 0 0 255 0 0 200 200 200\n"
                    "200 200 200 200 200 200 200 200 200 200 200 200\n"
                ),
                "Desktop/image_edit_brief.md": (
                    "Open source.ppm in the GUI image editor. Convert every red marker pixel (255,0,0) to blue "
                    "(0,0,255), keep gray background pixels unchanged, and export edited_marker.ppm."
                ),
            }
            hidden_files = {
                "hidden/evaluate_image_artifact.py": (
                    "import json, re, sys\n"
                    "from pathlib import Path\n"
                    "path = Path.home() / 'Desktop' / 'edited_marker.ppm'\n"
                    "score = 0.0\nissues = []\n"
                    "if not path.is_file() or path.stat().st_size == 0:\n"
                    "    issues.append('missing edited_marker.ppm')\n"
                    "else:\n"
                    "    tokens = [t for t in re.split(r'\\s+', path.read_text(encoding='utf-8', errors='ignore').strip()) if t and not t.startswith('#')]\n"
                    "    if tokens[:4] == ['P3', '4', '4', '255']:\n"
                    "        vals = list(map(int, tokens[4:]))\n"
                    "        pixels = list(zip(vals[0::3], vals[1::3], vals[2::3]))\n"
                    "        blue = sum(1 for p in pixels if p == (0,0,255))\n"
                    "        gray = sum(1 for p in pixels if p == (200,200,200))\n"
                    "        red = sum(1 for p in pixels if p == (255,0,0))\n"
                    "        score = 0.25 + 0.55 * min(1.0, blue / 6) + (0.2 if gray >= 10 and red == 0 else 0)\n"
                    "    else:\n"
                    "        issues.append('not a 4x4 P3 PPM export')\n"
                    "print(json.dumps({'score': min(1.0, score), 'issues': issues}, indent=2))\n"
                    "sys.exit(0 if score >= 0.8 else 1)\n"
                )
            }
            session = {
                "kind": "desktop_software",
                "application": "image_editor",
                "launch": {"file": "Desktop/source.ppm"},
                "instruction": prompt,
                "assets": list(visible_files.keys()),
                "expected_artifacts": ["Desktop/edited_marker.ppm"],
                "preferred_tools": ["screenshot", "click", "drag", "key", "type", "run_command", "evaluate"],
                "allowed_direct_file_edits": False,
            }
            vm_spec = {
                **vm_spec,
                "image": "evalclaw-gimp-gui",
                "required_software": ["gimp-or-image-editor", "python3", "evalclaw-desktop-bridge"],
                "artifacts_dir": "Desktop",
            }
            evaluation = {
                "method": "image_artifact_check",
                "expected_artifacts": ["Desktop/edited_marker.ppm"],
                "checks": [
                    {"name": "export_exists", "description": "Desktop/edited_marker.ppm exists and is parseable.", "weight": 0.25},
                    {"name": "marker_recolored", "description": "All six red marker pixels are converted to blue.", "weight": 0.55},
                    {"name": "background_preserved", "description": "The gray background remains unchanged and no red pixels remain.", "weight": 0.2},
                ],
                "pass_criteria": "The exported image recolors the marker exactly while preserving the background.",
                "partial_criteria": "A parseable edited image exists but some pixels or export requirements are wrong.",
                "fail_criteria": "No usable edited image artifact is produced.",
                "bridge_evaluator": {
                    "type": "hidden_script",
                    "hidden_script": "hidden/evaluate_image_artifact.py",
                    "requires_trace_tools": ["screenshot", "click", "drag", "evaluate"],
                },
            }
            tags = ["gui_desktop", "desktop_software", "image_editor", "gimp_like", "bridge"]
        elif _contains_any(route_text, ("media", "vlc")):
            prompt = (
                "Use the desktop media player preferences to disable the startup splash/cone artwork, save the "
                "preference, export Desktop/media_player_prefs.json through the bridge helper, and run the bridge evaluation."
            )
            visible_files = {
                "Desktop/media_pref_brief.md": (
                    "Open the media player through the GUI. Disable the startup splash/cone artwork preference, "
                    "then use the bridge helper to export media_player_prefs.json."
                )
            }
            hidden_files = {
                "hidden/evaluate_media_prefs.py": (
                    "import json, sys\n"
                    "from pathlib import Path\n"
                    "path = Path.home() / 'Desktop' / 'media_player_prefs.json'\n"
                    "data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}\n"
                    "ok = data.get('show_startup_artwork') is False or data.get('qt_bgcone') == 0\n"
                    "print(json.dumps({'score': 1.0 if ok else 0.0, 'prefs': data}, indent=2))\n"
                    "sys.exit(0 if ok else 1)\n"
                )
            }
            session = {
                "kind": "desktop_software",
                "application": "media_player",
                "launch": {"application": "VLC-compatible media player"},
                "instruction": prompt,
                "assets": list(visible_files.keys()),
                "expected_artifacts": ["Desktop/media_player_prefs.json"],
                "preferred_tools": ["screenshot", "click", "scroll", "key", "type", "evaluate"],
            }
            vm_spec = {
                **vm_spec,
                "image": "evalclaw-media-gui",
                "required_software": ["vlc-or-media-player", "python3", "evalclaw-desktop-bridge"],
            }
            evaluation = {
                "method": "app_preference_check",
                "expected_artifacts": ["Desktop/media_player_prefs.json"],
                "checks": [
                    {"name": "preference_export_exists", "description": "Preference export exists.", "weight": 0.3},
                    {"name": "startup_artwork_disabled", "description": "Startup artwork/cone preference is disabled.", "weight": 0.7},
                ],
                "pass_criteria": "The media-player preference is saved as disabled.",
                "partial_criteria": "The agent reaches the preference panel but does not save/export the final state.",
                "fail_criteria": "The relevant preference remains enabled or no state artifact is exported.",
                "bridge_evaluator": {"type": "hidden_script", "hidden_script": "hidden/evaluate_media_prefs.py"},
            }
            tags = ["gui_desktop", "desktop_software", "media_player", "settings", "bridge"]
        elif _contains_any(route_text, ("video", "compositing", "chroma", "davinci", "after effects")):
            video_variants = get_video_variants()
            shot, edit_goal = video_variants[(index - 1) % len(video_variants)]
            prompt = (
                f"Use the desktop video editor to open the {shot} project brief, {edit_goal}, export "
                "Desktop/final_composite.mp4, save Desktop/project_state.json with the edit decisions, and run the bridge evaluation."
            )
            visible_files = {
                "Desktop/video_brief.md": (
                    f"# Video compositing brief\n\nSource shot: {shot}\nTask: {edit_goal}.\n"
                    "Use the GUI editor timeline. Do not create only a text report.\n"
                ),
                "Desktop/project_state.json": "{\"layers\": [], \"exported\": false}\n",
            }
            session = {
                "kind": "desktop_software",
                "application": "video_editor",
                "launch": {"file": "Desktop/video_brief.md"},
                "instruction": prompt,
                "assets": ["Desktop/video_brief.md", "Desktop/project_state.json"],
                "expected_artifacts": ["Desktop/final_composite.mp4", "Desktop/project_state.json"],
                "preferred_tools": ["screenshot", "click", "drag", "key", "type", "read_file", "evaluate"],
            }
            vm_spec = {
                **vm_spec,
                "image": "evalclaw-video-gui",
                "required_software": ["kdenlive-or-openshot", "ffmpeg", "evalclaw-desktop-bridge"],
            }
            evaluation = {
                "method": "video_artifact_check",
                "expected_artifacts": ["Desktop/final_composite.mp4", "Desktop/project_state.json"],
                "checks": [
                    {"name": "video_export_exists", "description": "Desktop/final_composite.mp4 exists and is non-empty.", "weight": 0.35},
                    {"name": "edit_decisions_match", "description": "project_state.json records the requested compositing decisions.", "weight": 0.45},
                    {"name": "gui_workflow_used", "description": "The trace shows timeline/editor GUI interaction.", "weight": 0.2},
                ],
                "pass_criteria": "The exported video artifact and project state match the visible brief and hidden reference checks.",
                "partial_criteria": "The project is opened and partially edited but export or one edit criterion is missing.",
                "fail_criteria": "No usable video project/export artifact is produced.",
            }
            tags = ["gui_desktop", "desktop_software", "video_compositing", "bridge"]
        elif _contains_any(route_text, ("cad", "bim", "cae", "cam", "rhino", "drawing", "architectural")):
            cad_variants = get_cad_variants()
            drawing, model_goal = cad_variants[(index - 1) % len(cad_variants)]
            prompt = (
                f"Use the desktop CAD/BIM application in the VM to read the {drawing} brief, {model_goal}. "
                "Save Desktop/model_project.step, export Desktop/model_preview.png, and run the bridge evaluation."
            )
            visible_files = {
                "Desktop/drawing_brief.md": (
                    f"# CAD/BIM drawing brief\n\nDrawing: {drawing}\nRequired model: {model_goal}.\n"
                    "Use the CAD/BIM GUI and create geometric artifacts, not a text-only explanation.\n"
                )
            }
            session = {
                "kind": "desktop_software",
                "application": "cad_bim",
                "launch": {"file": "Desktop/drawing_brief.md"},
                "instruction": prompt,
                "assets": ["Desktop/drawing_brief.md"],
                "expected_artifacts": ["Desktop/model_project.step", "Desktop/model_preview.png"],
                "preferred_tools": ["screenshot", "click", "drag", "key", "type", "run_command", "evaluate"],
            }
            vm_spec = {
                **vm_spec,
                "image": "evalclaw-cad-gui",
                "required_software": ["freecad-or-rhino-compatible-cad", "python3", "evalclaw-desktop-bridge"],
            }
            evaluation = {
                "method": "cad_artifact_check",
                "expected_artifacts": ["Desktop/model_project.step", "Desktop/model_preview.png"],
                "checks": [
                    {"name": "model_file_exists", "description": "Desktop/model_project.step exists and can be parsed.", "weight": 0.3},
                    {"name": "geometry_requirements", "description": "The model contains required walls/columns/openings/features.", "weight": 0.5},
                    {"name": "preview_exists", "description": "Desktop/model_preview.png exists and is non-empty.", "weight": 0.2},
                ],
                "pass_criteria": "The CAD model and preview satisfy the hidden geometry and artifact checks.",
                "partial_criteria": "A parseable model exists but misses one required geometry feature or preview.",
                "fail_criteria": "No usable CAD/BIM artifact is produced.",
            }
            tags = ["gui_desktop", "desktop_software", "cad_bim", "bridge"]
        else:
            prompt = (
                "Use the desktop spreadsheet application to open Desktop/orders.csv, compute profit for each row, "
                "create a summary sheet with total profit by region, export Desktop/profit_summary.csv, and run "
                "the bridge evaluation."
            )
            visible_files = {
                "Desktop/orders.csv": (
                    "order_id,region,revenue,cost\n"
                    "A-1,north,120,70\n"
                    "A-2,south,90,55\n"
                    "A-3,north,80,60\n"
                )
            }
            session = {
                "kind": "desktop_software",
                "application": "spreadsheet",
                "launch": {"file": "Desktop/orders.csv"},
                "instruction": prompt,
                "assets": ["Desktop/orders.csv"],
                "expected_artifacts": ["Desktop/profit_summary.csv"],
                "preferred_tools": ["screenshot", "click", "type", "key", "read_file", "evaluate"],
            }
            vm_spec = {
                **vm_spec,
                "image": "evalclaw-libreoffice-gui",
                "required_software": ["libreoffice-calc", "evalclaw-desktop-bridge"],
            }
            evaluation = {
                "method": "artifact_check",
                "expected_artifacts": ["Desktop/profit_summary.csv"],
                "checks": [
                    {
                        "name": "artifact_exists",
                        "description": "Desktop/profit_summary.csv was exported by the desktop application.",
                        "weight": 0.25,
                    },
                    {
                        "name": "region_profit_correct",
                        "description": "The artifact contains north=70 and south=35 total profit.",
                        "weight": 0.6,
                    },
                    {
                        "name": "spreadsheet_workflow_used",
                        "description": "The trace indicates GUI interaction with the spreadsheet application.",
                        "weight": 0.15,
                    },
                ],
                "pass_criteria": "The exported CSV exists and contains correct profit totals for all regions.",
                "partial_criteria": "The agent opens the spreadsheet and computes at least one region correctly.",
                "fail_criteria": "No useful spreadsheet artifact is produced.",
            }
            tags = ["gui_desktop", "desktop_software", "spreadsheet", "bridge"]
    else:
        prompt = (
            "Use the GUI desktop session to organize the provided task files: move the approved brief into "
            "the Ready folder, leave the draft brief untouched, create Desktop/summary.txt with the approved "
            "brief title, and run the bridge evaluation."
        )
        visible_files = {
            "Desktop/Inbox/approved_brief.txt": "Title: Launch Readiness\nStatus: approved\n",
            "Desktop/Inbox/draft_brief.txt": "Title: Legacy Proposal\nStatus: draft\n",
            "Desktop/Ready/.keep": "",
        }
        session = {
            "kind": "gui_desktop",
            "application": "file_manager_and_text_editor",
            "launch": {"path": "Desktop/Inbox"},
            "instruction": prompt,
            "assets": [
                "Desktop/Inbox/approved_brief.txt",
                "Desktop/Inbox/draft_brief.txt",
                "Desktop/Ready/.keep",
            ],
            "expected_artifacts": ["Desktop/Ready/approved_brief.txt", "Desktop/summary.txt"],
        }
        vm_spec = {
            **vm_spec,
            "required_software": ["file-manager", "text-editor", "evalclaw-desktop-bridge"],
        }
        evaluation = {
            "method": "artifact_and_file_state_check",
            "expected_artifacts": ["Desktop/Ready/approved_brief.txt", "Desktop/summary.txt"],
            "checks": [
                {
                    "name": "approved_file_moved",
                    "description": "approved_brief.txt is in Desktop/Ready.",
                    "weight": 0.4,
                },
                {
                    "name": "draft_file_untouched",
                    "description": "draft_brief.txt remains outside Desktop/Ready.",
                    "weight": 0.25,
                },
                {
                    "name": "summary_created",
                    "description": "Desktop/summary.txt contains Launch Readiness.",
                    "weight": 0.35,
                },
            ],
            "pass_criteria": "The final file state and summary match all requested conditions.",
            "partial_criteria": "At least one required artifact is correct and no critical wrong move is made.",
            "fail_criteria": "The desktop state does not show meaningful progress toward the requested file organization.",
        }
        tags = ["gui_desktop", "file_manager", "bridge"]

    return TaskDefinition(
        id=_task_id(dimension, blueprint, index),
        dimension_id=dimension.id,
        task_type=TaskType.agent_interaction,
        title=_task_title(blueprint, index),
        description=(
            "A bridge-backed GUI desktop task. The target agent must inspect screenshots and operate the "
            "desktop/browser/software session through the standardized EvaluationClaw tool protocol."
        ),
        prompt=prompt,
        system_prompt=_agent_system_prompt("gui_desktop"),
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.gui_desktop,
            visible_files=visible_files,
            hidden_files=hidden_files,
            max_steps=24,
            timeout=30,
            requires_vm=True,
            vm=vm_spec,
            vm_provisioning=vm_spec.get("provisioning", {}) if isinstance(vm_spec.get("provisioning"), dict) else {},
            session=session,
            evaluation=evaluation,
            notes=(
                "Requires an external VM provider or pre-existing GUI desktop bridge. When requires_vm is true, "
                "the VM provider should create/reset an isolated desktop VM and return a bridge_url."
            ),
        ),
        interaction={
            "max_turns": 24,
            "stop_condition": "Stop when the bridge evaluation reports completion or the step limit is reached.",
        },
        scoring=TaskScoringSpec(
            method="deterministic",
            instructions="Score using the GUI desktop bridge evaluation contract in environment.evaluation.",
            pass_criteria=str(evaluation["pass_criteria"]),
            partial_criteria=str(evaluation["partial_criteria"]),
            fail_criteria=str(evaluation["fail_criteria"]),
            score_levels={"1": "all bridge checks pass", "0.5": "partial artifact or GUI progress", "0": "failed"},
            oracle_notes="The bridge owns the concrete VM/browser/software runtime and artifact inspection.",
        ),
        challenge_effort=dimension.challenge_effort,
        tags=[dimension.id, *tags],
    )
