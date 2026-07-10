"""GUI desktop fallback agent tasks."""
from __future__ import annotations

import json

from ...types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    AgentScoringSpec,
    AgentTask,
    AgentTaskBlueprint,
    AgentTaskFamily,
    EvalDimension,
)
from ..planning import (
    _contains_any,
    _goal_mentions_blender,
    _goal_mentions_multi_industrial_workflow,
    _mentions_app_state_workflow,
)
from .base import _agent_system_prompt, _task_id, _task_title


def _gui_desktop_task_for_blueprint(
    dimension: EvalDimension,
    blueprint: AgentTaskBlueprint,
    *,
    index: int = 1,
) -> AgentTask:
    blueprint_text = " ".join(
        [dimension.id, dimension.name, dimension.description, dimension.approach, blueprint.title, blueprint.description]
    ).lower()
    route_text = " ".join(
        [
            dimension.id,
            dimension.name,
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
    if blueprint.task_family == AgentTaskFamily.browser_gui:
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
    elif blueprint.task_family == AgentTaskFamily.gui_desktop and _mentions_app_state_workflow(route_text):
        app_state_variants = [
            {
                "application": "browser",
                "image": "evalclaw-browser-gui",
                "required_software": ["chromium", "python3", "evalclaw-desktop-bridge"],
                "prompt": (
                    "Use the desktop browser settings UI to enable the Do Not Track privacy preference and disable "
                    "third-party cookie tracking in the local profile. Export Desktop/browser_state.json with the "
                    "bridge helper and run the bridge evaluation."
                ),
                "visible_files": {
                    "Desktop/browser_state_brief.md": (
                        "Open the browser through the GUI. In the normal settings UI, enable Do Not Track and "
                        "disable third-party cookie tracking for the local profile. Do not edit the profile files directly."
                    ),
                    "Desktop/browser_profile_seed.json": (
                        '{"do_not_track": false, "third_party_cookies": "allow", "profile": "evalclaw-local"}\n'
                    ),
                },
                "expected_artifacts": ["Desktop/browser_state.json"],
                "hidden_script": "hidden/evaluate_app_state.py",
                "hidden_files": {
                    "hidden/evaluate_app_state.py": (
                        "import json, sys\n"
                        "from pathlib import Path\n"
                        "path = Path.home() / 'Desktop' / 'browser_state.json'\n"
                        "data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}\n"
                        "score = 0.0\nissues = []\n"
                        "if path.exists():\n"
                        "    score += 0.2\n"
                        "else:\n"
                        "    issues.append('missing browser_state.json')\n"
                        "if data.get('do_not_track') is True:\n"
                        "    score += 0.4\n"
                        "if str(data.get('third_party_cookies', '')).lower() in {'block', 'blocked', 'disabled'}:\n"
                        "    score += 0.4\n"
                        "print(json.dumps({'score': min(1.0, score), 'issues': issues}, indent=2))\n"
                        "sys.exit(0 if score >= 0.8 else 1)\n"
                    )
                },
                "checks": [
                    {"name": "state_export_exists", "description": "Desktop/browser_state.json exists.", "weight": 0.2},
                    {"name": "do_not_track_enabled", "description": "Do Not Track is enabled in the exported browser state.", "weight": 0.4},
                    {"name": "third_party_tracking_disabled", "description": "Third-party cookie tracking is disabled.", "weight": 0.4},
                ],
            },
            {
                "application": "email_client",
                "image": "evalclaw-thunderbird-gui",
                "required_software": ["thunderbird-or-mail-client", "python3", "evalclaw-desktop-bridge"],
                "prompt": (
                    "Use the desktop email client UI to create a rule for invoices@example.test: messages from this "
                    "sender should be moved into the Accounting/Invoices folder and marked as important. Export "
                    "Desktop/mail_filter_state.json with the bridge helper and run the bridge evaluation."
                ),
                "visible_files": {
                    "Desktop/mail_state_brief.md": (
                        "The local mail profile contains Inbox messages from invoices@example.test and "
                        "alerts@example.test. Create the requested filter through the email client GUI. Do not edit "
                        "the filter JSON directly."
                    ),
                    "Desktop/mail_profile_seed.json": (
                        "{\n"
                        '  "folders": ["Inbox", "Accounting/Invoices"],\n'
                        '  "messages": [\n'
                        '    {"from": "invoices@example.test", "subject": "Invoice 1821"},\n'
                        '    {"from": "alerts@example.test", "subject": "System alert"}\n'
                        "  ],\n"
                        '  "filters": []\n'
                        "}\n"
                    ),
                },
                "expected_artifacts": ["Desktop/mail_filter_state.json"],
                "hidden_script": "hidden/evaluate_app_state.py",
                "hidden_files": {
                    "hidden/evaluate_app_state.py": (
                        "import json, sys\n"
                        "from pathlib import Path\n"
                        "path = Path.home() / 'Desktop' / 'mail_filter_state.json'\n"
                        "data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}\n"
                        "filters = data.get('filters') if isinstance(data.get('filters'), list) else []\n"
                        "match = None\n"
                        "for item in filters:\n"
                        "    if isinstance(item, dict) and item.get('from') == 'invoices@example.test':\n"
                        "        match = item\n"
                        "score = 0.2 if path.exists() else 0.0\n"
                        "issues = [] if path.exists() else ['missing mail_filter_state.json']\n"
                        "if match and match.get('move_to') == 'Accounting/Invoices':\n"
                        "    score += 0.45\n"
                        "if match and match.get('mark_important') is True:\n"
                        "    score += 0.35\n"
                        "print(json.dumps({'score': min(1.0, score), 'issues': issues}, indent=2))\n"
                        "sys.exit(0 if score >= 0.8 else 1)\n"
                    )
                },
                "checks": [
                    {"name": "filter_export_exists", "description": "Desktop/mail_filter_state.json exists.", "weight": 0.2},
                    {"name": "sender_rule_target", "description": "The invoice sender rule moves mail to Accounting/Invoices.", "weight": 0.45},
                    {"name": "importance_action", "description": "The invoice sender rule marks matching mail as important.", "weight": 0.35},
                ],
            },
            {
                "application": "ide",
                "image": "evalclaw-vscode-gui",
                "required_software": ["code-or-compatible-ide", "python3", "evalclaw-desktop-bridge"],
                "prompt": (
                    "Use the desktop IDE UI to install the local extension package Desktop/extensions/evalclaw-linter.vsix, "
                    "enable format-on-save for the workspace, export Desktop/ide_state.json with the bridge helper, "
                    "and run the bridge evaluation."
                ),
                "visible_files": {
                    "Desktop/ide_state_brief.md": (
                        "Open the IDE through the GUI. Install the local extension package and turn on "
                        "editor.formatOnSave for this workspace. Do not edit ide_state.json directly."
                    ),
                    "Desktop/workspace/.vscode/settings.json": "{\n  \"editor.formatOnSave\": false\n}\n",
                    "Desktop/extensions/evalclaw-linter.vsix": "placeholder local extension package for bridge-backed tests\n",
                },
                "expected_artifacts": ["Desktop/ide_state.json"],
                "hidden_script": "hidden/evaluate_app_state.py",
                "hidden_files": {
                    "hidden/evaluate_app_state.py": (
                        "import json, sys\n"
                        "from pathlib import Path\n"
                        "path = Path.home() / 'Desktop' / 'ide_state.json'\n"
                        "data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}\n"
                        "extensions = {str(x).lower() for x in data.get('extensions', []) if x}\n"
                        "settings = data.get('settings') if isinstance(data.get('settings'), dict) else {}\n"
                        "score = 0.2 if path.exists() else 0.0\n"
                        "issues = [] if path.exists() else ['missing ide_state.json']\n"
                        "if 'evalclaw-linter' in extensions or 'publisher.evalclaw-linter' in extensions:\n"
                        "    score += 0.45\n"
                        "if settings.get('editor.formatOnSave') is True or settings.get('editor.format_on_save') is True:\n"
                        "    score += 0.35\n"
                        "print(json.dumps({'score': min(1.0, score), 'issues': issues}, indent=2))\n"
                        "sys.exit(0 if score >= 0.8 else 1)\n"
                    )
                },
                "checks": [
                    {"name": "ide_state_export_exists", "description": "Desktop/ide_state.json exists.", "weight": 0.2},
                    {"name": "local_extension_installed", "description": "The local evalclaw-linter extension is installed.", "weight": 0.45},
                    {"name": "format_on_save_enabled", "description": "Workspace format-on-save is enabled.", "weight": 0.35},
                ],
            },
        ]
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
    elif blueprint.task_family == AgentTaskFamily.desktop_software and _goal_mentions_multi_industrial_workflow(route_text):
        workflow_variants = [
            {
                "title": "controller-board enclosure review",
                "eda_goal": "export the controller PCB outline, mounting holes, and tall-component keepout as a STEP assembly",
                "cad_goal": "design a two-piece electronics enclosure with standoffs, USB clearance, lid screw bosses, and a tolerance report",
                "render_goal": "produce a materials-applied product-review render showing the board seated inside the enclosure",
                "board": {
                    "board_name": "controller_board_rev_a",
                    "units": "mm",
                    "outline": {"width": 72.0, "height": 48.0, "corner_radius": 3.0},
                    "mounting_holes": [
                        {"x": 6.0, "y": 6.0, "diameter": 3.2},
                        {"x": 66.0, "y": 6.0, "diameter": 3.2},
                        {"x": 6.0, "y": 42.0, "diameter": 3.2},
                        {"x": 66.0, "y": 42.0, "diameter": 3.2},
                    ],
                    "components": [
                        {"ref": "U1", "x": 36.0, "y": 24.0, "height": 9.5},
                        {"ref": "J1", "x": 72.0, "y": 24.0, "height": 6.0, "edge_connector": "usb_c"},
                    ],
                },
                "constraints": {
                    "internal_clearance_mm": 2.0,
                    "wall_thickness_mm": 2.4,
                    "standoff_diameter_mm": 6.0,
                    "usb_cutout_extra_clearance_mm": 1.0,
                    "max_enclosure_height_mm": 22.0,
                },
                "visual": {
                    "enclosure_material": "matte dark gray plastic",
                    "pcb_material": "green solder mask",
                    "camera": "three-quarter top view",
                    "required_annotations": ["USB-C opening", "four standoffs", "board seated in lower shell"],
                },
            },
            {
                "title": "sensor-carrier bracket fit check",
                "eda_goal": "export the small sensor PCB with connector envelope and two M2 holes as a STEP assembly",
                "cad_goal": "create a FreeCAD carrier bracket that aligns holes, leaves cable bend clearance, and exports an assembly check",
                "render_goal": "render the bracket and PCB in Blender with transparent cover material and visible connector clearance",
                "board": {
                    "board_name": "sensor_carrier_rev_b",
                    "units": "mm",
                    "outline": {"width": 38.0, "height": 28.0, "corner_radius": 2.0},
                    "mounting_holes": [
                        {"x": 5.0, "y": 5.0, "diameter": 2.2},
                        {"x": 33.0, "y": 23.0, "diameter": 2.2},
                    ],
                    "components": [
                        {"ref": "S1", "x": 19.0, "y": 14.0, "height": 5.0},
                        {"ref": "J2", "x": 38.0, "y": 14.0, "height": 7.5, "edge_connector": "jst"},
                    ],
                },
                "constraints": {
                    "internal_clearance_mm": 1.5,
                    "wall_thickness_mm": 2.0,
                    "standoff_diameter_mm": 4.5,
                    "cable_bend_radius_mm": 8.0,
                    "max_enclosure_height_mm": 18.0,
                },
                "visual": {
                    "enclosure_material": "translucent smoke plastic",
                    "pcb_material": "blue solder mask",
                    "camera": "front-left exploded view",
                    "required_annotations": ["connector clearance", "two aligned standoffs", "transparent cover"],
                },
            },
            {
                "title": "DIN-rail IO module packaging pass",
                "eda_goal": "export the IO PCB, terminal block envelope, and four keepout zones as a STEP assembly",
                "cad_goal": "model a DIN-rail-ready housing with terminal access slots and verify keepout-zone clearances",
                "render_goal": "render a front product shot in Blender with labels, material contrast, and terminal access visible",
                "board": {
                    "board_name": "io_module_rev_c",
                    "units": "mm",
                    "outline": {"width": 94.0, "height": 58.0, "corner_radius": 2.5},
                    "mounting_holes": [
                        {"x": 8.0, "y": 8.0, "diameter": 3.2},
                        {"x": 86.0, "y": 8.0, "diameter": 3.2},
                        {"x": 8.0, "y": 50.0, "diameter": 3.2},
                        {"x": 86.0, "y": 50.0, "diameter": 3.2},
                    ],
                    "components": [
                        {"ref": "TB1", "x": 47.0, "y": 58.0, "height": 12.0, "edge_connector": "terminal_block"},
                        {"ref": "U3", "x": 48.0, "y": 28.0, "height": 8.0},
                    ],
                },
                "constraints": {
                    "internal_clearance_mm": 2.5,
                    "wall_thickness_mm": 2.8,
                    "standoff_diameter_mm": 6.0,
                    "terminal_access_clearance_mm": 3.0,
                    "max_enclosure_height_mm": 32.0,
                },
                "visual": {
                    "enclosure_material": "light gray industrial plastic",
                    "pcb_material": "black solder mask",
                    "camera": "front product shot",
                    "required_annotations": ["terminal access", "DIN rail clip", "four standoffs"],
                },
            },
        ]
        variant = workflow_variants[(index - 1) % len(workflow_variants)]
        expected_artifacts = [
            "Desktop/exports/pcb_assembly.step",
            "Desktop/exports/enclosure.step",
            "Desktop/exports/assembly_clearance_report.json",
            "Desktop/exports/product_render.png",
            "Desktop/exports/workflow_manifest.json",
        ]
        prompt = (
            "Use the VM desktop industrial software stack to complete the "
            f"{variant['title']} workflow. Start in KiCad to {variant['eda_goal']}; then use FreeCAD to "
            f"{variant['cad_goal']}; then use Blender to {variant['render_goal']}. Save the required artifacts "
            "under Desktop/exports, write Desktop/exports/workflow_manifest.json with application provenance and "
            "unit assumptions, and run the bridge evaluation. This task must not be solved as a text-only report "
            "or inside a single application."
        )
        visible_files = {
            "Desktop/industrial_workflow/brief.md": (
                f"# Industrial multi-software workflow\n\nWorkflow: {variant['title']}\n\n"
                "Required application chain:\n"
                "1. KiCad: inspect or create the PCB-side geometry and export the board assembly STEP.\n"
                "2. FreeCAD: import the KiCad STEP, build the mechanical enclosure/bracket, and export a clearance report.\n"
                "3. Blender: import the CAD outputs, apply review materials/camera, and render the product image.\n\n"
                "All outputs must be placed in Desktop/exports. Keep units in millimeters and record every "
                "application handoff in workflow_manifest.json.\n"
            ),
            "Desktop/industrial_workflow/board_requirements.json": json.dumps(variant["board"], ensure_ascii=False, indent=2),
            "Desktop/industrial_workflow/mechanical_constraints.json": json.dumps(
                variant["constraints"],
                ensure_ascii=False,
                indent=2,
            ),
            "Desktop/industrial_workflow/render_requirements.json": json.dumps(variant["visual"], ensure_ascii=False, indent=2),
            "Desktop/industrial_workflow/workflow_manifest_template.json": json.dumps(
                {
                    "units": "mm",
                    "applications_used": [],
                    "handoffs": [],
                    "artifacts": {},
                    "checks_performed": [],
                    "notes": "",
                },
                ensure_ascii=False,
                indent=2,
            ),
        }
        hidden_files = {
            "hidden/evaluate_industrial_workflow.py": (
                "import json\n"
                "import os\n"
                "import sys\n"
                "from pathlib import Path\n\n"
                "desktop = Path(os.environ.get('EVALCLAW_DESKTOP_DIR', str(Path.home() / 'Desktop')))\n"
                "exports = desktop / 'exports'\n"
                "required = [\n"
                "    'pcb_assembly.step',\n"
                "    'enclosure.step',\n"
                "    'assembly_clearance_report.json',\n"
                "    'product_render.png',\n"
                "    'workflow_manifest.json',\n"
                "]\n"
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
                "required_apps = {'kicad', 'freecad', 'blender'}\n"
                "if not required_apps.issubset(apps):\n"
                "    score -= 0.2\n"
                "    issues.append({'missing_applications': sorted(required_apps - apps)})\n"
                "handoffs = manifest.get('handoffs', [])\n"
                "if not isinstance(handoffs, list) or len(handoffs) < 2:\n"
                "    score -= 0.1\n"
                "    issues.append({'handoffs': 'expected at least two artifact handoffs'})\n"
                "try:\n"
                "    report = json.loads((exports / 'assembly_clearance_report.json').read_text(encoding='utf-8'))\n"
                "except Exception as exc:\n"
                "    report = {}\n"
                "    score -= 0.1\n"
                "    issues.append({'clearance_report_error': str(exc)})\n"
                "if report and report.get('units') != 'mm':\n"
                "    score -= 0.05\n"
                "    issues.append({'units': 'expected mm in clearance report'})\n"
                "if report and report.get('min_clearance_mm') is not None and float(report.get('min_clearance_mm', 0)) <= 0:\n"
                "    score -= 0.05\n"
                "    issues.append({'clearance': 'min_clearance_mm must be positive'})\n"
                "score = max(0.0, min(1.0, score))\n"
                "print(json.dumps({'score': score, 'missing': missing, 'issues': issues}, indent=2))\n"
                "sys.exit(0 if score >= 0.8 else 1)\n"
            )
        }
        session = {
            "kind": "desktop_software_multi_app",
            "application": "multi_app_industrial_workflow",
            "applications": ["KiCad", "FreeCAD", "Blender"],
            "launch_sequence": [
                {"application": "KiCad", "command": "kicad", "working_directory": "Desktop/industrial_workflow"},
                {"application": "FreeCAD", "command": "freecad", "working_directory": "Desktop/industrial_workflow"},
                {"application": "Blender", "command": "blender", "working_directory": "Desktop/industrial_workflow"},
            ],
            "workflow_stages": [
                {
                    "id": "eda_board_export",
                    "application": "KiCad",
                    "inputs": ["Desktop/industrial_workflow/board_requirements.json"],
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
            ],
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
            "image": "evalclaw-industrial-cad-eda-gui",
            "display": {"width": 1600, "height": 1000, "scale": 1.0},
            "gpu": "optional",
            "required_software": [
                "kicad>=8",
                "freecad>=0.21",
                "blender>=4.0",
                "python3",
                "evalclaw-desktop-bridge",
            ],
            "software_stack": {
                "eda": "KiCad",
                "mechanical_cad": "FreeCAD",
                "rendering": "Blender",
            },
            "provisioning": {
                "enabled": True,
                "strategy": "cloud_init_apt.v1",
                "base_os": "ubuntu",
                "apt_packages": ["kicad", "freecad", "blender", "python3", "python3-pip", "xvfb", "xdotool"],
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
            "checks": [
                {
                    "name": "eda_step_export",
                    "description": "KiCad-stage Desktop/exports/pcb_assembly.step exists and is referenced in the manifest.",
                    "weight": 0.2,
                },
                {
                    "name": "cad_enclosure_and_clearance",
                    "description": "FreeCAD-stage enclosure STEP and assembly_clearance_report.json satisfy geometry and clearance checks.",
                    "weight": 0.3,
                },
                {
                    "name": "render_review_artifact",
                    "description": "Blender-stage product_render.png exists, is non-empty, and reflects the requested materials/camera.",
                    "weight": 0.2,
                },
                {
                    "name": "workflow_manifest_provenance",
                    "description": "workflow_manifest.json records KiCad, FreeCAD, Blender, units, handoffs, and artifact dependencies.",
                    "weight": 0.2,
                },
                {
                    "name": "multi_app_gui_workflow_used",
                    "description": "The trace shows interaction with multiple industrial applications instead of direct text-only completion.",
                    "weight": 0.1,
                },
            ],
            "pass_criteria": (
                "All required intermediate and final artifacts exist, the manifest records KiCad -> FreeCAD -> "
                "Blender provenance with millimeter units, and bridge checks confirm the multi-application workflow."
            ),
            "partial_criteria": (
                "At least two applications are used and most artifacts are produced, but one handoff, clearance "
                "detail, render requirement, or manifest field is incomplete."
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
            "kicad",
            "freecad",
            "blender",
            "vm",
            "bridge",
        ]
    elif blueprint.task_family == AgentTaskFamily.desktop_software and _goal_mentions_blender(route_text):
        blender_variants = [
            (
                "a blue cube on a gray plane, a red sphere to the cube's right, a warm area light, and a camera "
                "framing both objects",
                [
                    "- Include a blue cube on a gray plane.",
                    "- Include a red sphere to the cube's right.",
                    "- Add a warm area light and a camera that frames both objects.",
                ],
            ),
            (
                "a simple articulated arm with three labeled bones, two colored joint spheres, a neutral material floor, "
                "and a camera framing the rig",
                [
                    "- Include a three-segment articulated arm or armature-like structure.",
                    "- Include two colored joint spheres at different joint positions.",
                    "- Add a floor plane and a camera that frames the whole rig.",
                ],
            ),
            (
                "a small product display with a green cylinder, a gold torus, a labeled base plate, two lights, and a "
                "camera-ready composition",
                [
                    "- Include a green cylinder and a gold torus on a labeled base plate.",
                    "- Add two lights with visibly different positions.",
                    "- Add a camera that frames the product display.",
                ],
            ),
        ]
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
    elif blueprint.task_family == AgentTaskFamily.desktop_software:
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
            artifact_variants = [
                {
                    "application": "blender_or_freecad",
                    "image": "evalclaw-artifact-gui",
                    "required_software": ["blender>=4.0", "freecad", "python3", "evalclaw-desktop-bridge"],
                    "prompt": (
                        "Use the VM desktop modeling tools to reconstruct the visible calibration fixture from "
                        "Desktop/reference/fixture_brief.md and Desktop/reference/measurements.json. Produce "
                        "Desktop/deliverables/final_model.glb, Desktop/deliverables/validation_render.png, and "
                        "Desktop/deliverables/reconstruction_report.md plus Desktop/deliverables/geometry_manifest.json, "
                        "then run the bridge evaluation."
                    ),
                    "visible_files": {
                        "Desktop/reference/fixture_brief.md": (
                            "# Calibration fixture reconstruction\n\n"
                            "Create a compact bracket with a rectangular base, two raised cylindrical bosses, "
                            "a center alignment slot, and a beveled front edge. Keep dimensions in millimeters. "
                            "The model should be usable for visual inspection and downstream CAD import.\n"
                        ),
                        "Desktop/reference/measurements.json": json.dumps(
                            {
                                "units": "mm",
                                "base": {"width": 80, "depth": 45, "height": 6},
                                "bosses": [
                                    {"x": 18, "y": 22.5, "diameter": 10, "height": 12},
                                    {"x": 62, "y": 22.5, "diameter": 10, "height": 12},
                                ],
                                "slot": {"center_x": 40, "center_y": 22.5, "width": 20, "depth": 6},
                                "bevel": {"edge": "front", "size": 2},
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    },
                    "expected_artifacts": [
                        "Desktop/deliverables/final_model.glb",
                        "Desktop/deliverables/validation_render.png",
                        "Desktop/deliverables/reconstruction_report.md",
                        "Desktop/deliverables/geometry_manifest.json",
                    ],
                    "hidden_files": {
                        "hidden/evaluate_artifact.py": (
                            "import json, sys\n"
                            "from pathlib import Path\n"
                            "root = Path.home() / 'Desktop' / 'deliverables'\n"
                            "expected = ['final_model.glb', 'validation_render.png', 'reconstruction_report.md', 'geometry_manifest.json']\n"
                            "score = sum((root / name).is_file() and (root / name).stat().st_size > 0 for name in expected) / 4 * 0.35\n"
                            "report = (root / 'reconstruction_report.md').read_text(encoding='utf-8', errors='ignore').lower() if (root / 'reconstruction_report.md').exists() else ''\n"
                            "for term in ['base', 'boss', 'slot', 'bevel', 'millimeter']:\n"
                            "    score += 0.04 if term in report else 0.0\n"
                            "manifest_path = root / 'geometry_manifest.json'\n"
                            "if manifest_path.exists():\n"
                            "    data = json.loads(manifest_path.read_text(encoding='utf-8'))\n"
                            "    dims = data.get('base', {}) if isinstance(data.get('base'), dict) else {}\n"
                            "    slot = data.get('slot', {}) if isinstance(data.get('slot'), dict) else {}\n"
                            "    bosses = data.get('bosses', []) if isinstance(data.get('bosses'), list) else []\n"
                            "    if abs(float(dims.get('width', 0)) - 80) <= 1 and abs(float(dims.get('depth', 0)) - 45) <= 1:\n"
                            "        score += 0.15\n"
                            "    if len(bosses) == 2 and all(abs(float(b.get('diameter', 0)) - 10) <= 1 for b in bosses if isinstance(b, dict)):\n"
                            "        score += 0.15\n"
                            "    if abs(float(slot.get('width', 0)) - 20) <= 1 and abs(float(slot.get('depth', 0)) - 6) <= 1:\n"
                            "        score += 0.15\n"
                            "print(json.dumps({'score': min(1.0, score), 'expected_artifacts': expected}, indent=2))\n"
                            "sys.exit(0 if score >= 0.8 else 1)\n"
                        )
                    },
                    "checks": [
                        {"name": "deliverables_exist", "description": "GLB, render, report, and geometry manifest are present and non-empty.", "weight": 0.35},
                        {"name": "geometry_features", "description": "Report/model evidence covers base, two bosses, slot, bevel, and units.", "weight": 0.2},
                        {"name": "measurement_tolerances", "description": "The geometry manifest matches hidden measurement tolerances.", "weight": 0.3},
                        {"name": "desktop_modeling_trace", "description": "Trajectory shows GUI modeling or desktop tool use.", "weight": 0.15},
                    ],
                    "software_notes": "Open-source Blender/FreeCAD stack; no proprietary license required.",
                },
                {
                    "application": "scientific_desktop_pipeline",
                    "image": "evalclaw-scivis-gui",
                    "required_software": ["python3", "python3-numpy", "python3-matplotlib", "paraview-or-blender", "evalclaw-desktop-bridge"],
                    "prompt": (
                        "Use the VM desktop scientific visualization workflow to turn Desktop/reference/sensor_grid.csv "
                        "into a reviewed artifact package. Produce Desktop/deliverables/heatmap.png, "
                        "Desktop/deliverables/outlier_table.csv, and Desktop/deliverables/provenance.md, then run "
                        "the bridge evaluation."
                    ),
                    "visible_files": {
                        "Desktop/reference/sensor_grid.csv": (
                            "x,y,temperature_c\n"
                            "0,0,21.0\n1,0,21.3\n2,0,22.0\n"
                            "0,1,21.2\n1,1,29.8\n2,1,22.2\n"
                            "0,2,20.9\n1,2,21.1\n2,2,21.7\n"
                        ),
                        "Desktop/reference/review_brief.md": (
                            "Create a heatmap for the 3x3 sensor grid, identify outliers above 27C, and write "
                            "a short provenance note naming the data file and visualization/export steps."
                        ),
                    },
                    "expected_artifacts": [
                        "Desktop/deliverables/heatmap.png",
                        "Desktop/deliverables/outlier_table.csv",
                        "Desktop/deliverables/provenance.md",
                    ],
                    "hidden_files": {
                        "hidden/evaluate_artifact.py": (
                            "import csv, json, sys\n"
                            "from pathlib import Path\n"
                            "root = Path.home() / 'Desktop' / 'deliverables'\n"
                            "score = 0.0\nissues = []\n"
                            "for name in ['heatmap.png', 'outlier_table.csv', 'provenance.md']:\n"
                            "    if (root / name).is_file() and (root / name).stat().st_size > 0:\n"
                            "        score += 0.2\n"
                            "    else:\n"
                            "        issues.append(f'missing {name}')\n"
                            "if (root / 'outlier_table.csv').exists():\n"
                            "    rows = list(csv.DictReader((root / 'outlier_table.csv').open(newline='', encoding='utf-8-sig')))\n"
                            "    if any(r.get('x') == '1' and r.get('y') == '1' for r in rows):\n"
                            "        score += 0.25\n"
                            "prov = (root / 'provenance.md').read_text(encoding='utf-8', errors='ignore').lower() if (root / 'provenance.md').exists() else ''\n"
                            "if 'sensor_grid.csv' in prov and 'heatmap' in prov:\n"
                            "    score += 0.15\n"
                            "print(json.dumps({'score': min(1.0, score), 'issues': issues}, indent=2))\n"
                            "sys.exit(0 if score >= 0.8 else 1)\n"
                        )
                    },
                    "checks": [
                        {"name": "artifact_package_exists", "description": "Heatmap, outlier table, and provenance are present.", "weight": 0.6},
                        {"name": "outlier_identified", "description": "The table identifies the central high-temperature sensor.", "weight": 0.25},
                        {"name": "provenance_documented", "description": "The provenance note names the input data and export steps.", "weight": 0.15},
                    ],
                    "software_notes": "Open-source Python/scientific desktop stack with optional ParaView or Blender rendering.",
                },
                {
                    "application": "robotics_modeling",
                    "image": "evalclaw-robotics-modeling",
                    "required_software": ["python3", "python3-lxml", "urdfdom-tools", "evalclaw-desktop-bridge"],
                    "prompt": (
                        "Use the staged robotics metadata under Desktop/robot/input to reconstruct a valid robot model. "
                        "Create exactly Desktop/robot/output/submission.urdf and Desktop/robot/output/kinematic_report.json. "
                        "The URDF must preserve all required links, joints, mesh references, joint limits, mimic rules, "
                        "and auxiliary frames from the visible manifests. Run the bridge evaluation when finished."
                    ),
                    "visible_files": {
                        "Desktop/robot/input/task_brief.md": (
                            "# Robotics asset reconstruction\n\n"
                            "Reconstruct a compact six-axis inspection robot as URDF. Use the staged mesh names and "
                            "metadata manifests. Do not invent extra links or write outputs outside Desktop/robot/output."
                        ),
                        "Desktop/robot/input/metadata/link_manifest.json": json.dumps(
                            {
                                "links": [
                                    "base_link",
                                    "shoulder_link",
                                    "upper_arm_link",
                                    "forearm_link",
                                    "wrist_link",
                                    "tool0",
                                    "camera_frame",
                                ],
                                "mesh_links": [
                                    "base_link",
                                    "shoulder_link",
                                    "upper_arm_link",
                                    "forearm_link",
                                    "wrist_link",
                                ],
                            },
                            indent=2,
                        ),
                        "Desktop/robot/input/metadata/joint_manifest.json": json.dumps(
                            {
                                "joints": [
                                    {"name": "joint_1", "type": "revolute", "parent": "base_link", "child": "shoulder_link"},
                                    {"name": "joint_2", "type": "revolute", "parent": "shoulder_link", "child": "upper_arm_link"},
                                    {"name": "joint_3", "type": "revolute", "parent": "upper_arm_link", "child": "forearm_link"},
                                    {"name": "joint_4", "type": "revolute", "parent": "forearm_link", "child": "wrist_link"},
                                    {"name": "tool_mount", "type": "fixed", "parent": "wrist_link", "child": "tool0"},
                                    {"name": "camera_mount", "type": "fixed", "parent": "tool0", "child": "camera_frame"},
                                ]
                            },
                            indent=2,
                        ),
                        "Desktop/robot/input/metadata/joint_limits.csv": (
                            "joint,lower,upper,effort,velocity\n"
                            "joint_1,-3.14,3.14,120,1.5\n"
                            "joint_2,-1.57,1.57,100,1.2\n"
                            "joint_3,-2.10,2.10,80,1.2\n"
                            "joint_4,-3.14,3.14,40,2.0\n"
                        ),
                        "Desktop/robot/input/metadata/mimic_rules.json": json.dumps(
                            {"camera_mount": {"mimics": "tool_mount", "multiplier": 1.0, "offset": 0.0}},
                            indent=2,
                        ),
                        "Desktop/robot/input/meshes/base_link.stl": "solid base_link\nendsolid base_link\n",
                        "Desktop/robot/input/meshes/shoulder_link.stl": "solid shoulder_link\nendsolid shoulder_link\n",
                        "Desktop/robot/input/meshes/upper_arm_link.stl": "solid upper_arm_link\nendsolid upper_arm_link\n",
                        "Desktop/robot/input/meshes/forearm_link.stl": "solid forearm_link\nendsolid forearm_link\n",
                        "Desktop/robot/input/meshes/wrist_link.stl": "solid wrist_link\nendsolid wrist_link\n",
                    },
                    "expected_artifacts": [
                        "Desktop/robot/output/submission.urdf",
                        "Desktop/robot/output/kinematic_report.json",
                    ],
                    "hidden_files": {
                        "hidden/evaluate_artifact.py": (
                            "import json, sys, xml.etree.ElementTree as ET\n"
                            "from pathlib import Path\n"
                            "root = Path.home() / 'Desktop' / 'robot' / 'output'\n"
                            "urdf_path = root / 'submission.urdf'\n"
                            "report_path = root / 'kinematic_report.json'\n"
                            "score = 0.0\nissues = []\n"
                            "required_links = {'base_link','shoulder_link','upper_arm_link','forearm_link','wrist_link','tool0','camera_frame'}\n"
                            "required_joints = {'joint_1','joint_2','joint_3','joint_4','tool_mount','camera_mount'}\n"
                            "if urdf_path.exists() and report_path.exists():\n"
                            "    score += 0.2\n"
                            "else:\n"
                            "    issues.append('missing required output files')\n"
                            "if urdf_path.exists():\n"
                            "    tree = ET.parse(urdf_path)\n"
                            "    root_xml = tree.getroot()\n"
                            "    links = {el.attrib.get('name') for el in root_xml.findall('link')}\n"
                            "    joints = {el.attrib.get('name'): el for el in root_xml.findall('joint')}\n"
                            "    if links == required_links:\n"
                            "        score += 0.25\n"
                            "    if set(joints) == required_joints:\n"
                            "        score += 0.2\n"
                            "    limits_ok = all(joints.get(name) is not None and joints[name].find('limit') is not None for name in ['joint_1','joint_2','joint_3','joint_4'])\n"
                            "    if limits_ok:\n"
                            "        score += 0.15\n"
                            "    mesh_refs = ''.join(ET.tostring(el, encoding='unicode') for el in root_xml.findall('.//mesh'))\n"
                            "    if all(name + '.stl' in mesh_refs for name in ['base_link','shoulder_link','upper_arm_link','forearm_link','wrist_link']):\n"
                            "        score += 0.1\n"
                            "if report_path.exists():\n"
                            "    report = json.loads(report_path.read_text(encoding='utf-8'))\n"
                            "    if report.get('kinematic_tree_checked') is True and report.get('joint_limit_source') == 'joint_limits.csv':\n"
                            "        score += 0.1\n"
                            "print(json.dumps({'score': min(1.0, score), 'issues': issues}, indent=2))\n"
                            "sys.exit(0 if score >= 0.85 else 1)\n"
                        )
                    },
                    "checks": [
                        {"name": "required_outputs", "description": "submission.urdf and kinematic_report.json exist.", "weight": 0.2},
                        {"name": "link_joint_semantics", "description": "URDF preserves exact required link and joint sets.", "weight": 0.45},
                        {"name": "limits_and_meshes", "description": "Joint limits and mesh references match visible metadata.", "weight": 0.25},
                        {"name": "provenance_report", "description": "Report documents kinematic tree and metadata sources.", "weight": 0.1},
                    ],
                    "software_notes": "Open-source URDF/XML tooling; hidden evaluator can run without proprietary robotics software.",
                },
            ]
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
            office_variants = [
                {
                    "application": "spreadsheet",
                    "image": "evalclaw-libreoffice-gui",
                    "required_software": ["libreoffice-calc", "python3", "evalclaw-desktop-bridge"],
                    "prompt": (
                        "Use the desktop spreadsheet application to open Desktop/osworld_orders.csv. Add a Profit "
                        "column, compute revenue minus cost for each order, create a region summary with total profit, "
                        "export Desktop/profit_summary.csv, and run the bridge evaluation."
                    ),
                    "visible_files": {
                        "Desktop/osworld_orders.csv": (
                            "order_id,region,revenue,cost\n"
                            "A-1,north,120,70\n"
                            "A-2,south,90,55\n"
                            "A-3,north,80,60\n"
                            "A-4,west,105,81\n"
                        ),
                        "Desktop/office_task_brief.md": (
                            "Open osworld_orders.csv in the GUI spreadsheet application. The exported summary must "
                            "contain one row per region with total_profit values: north=70, south=35, west=24."
                        ),
                    },
                    "expected_artifacts": ["Desktop/profit_summary.csv"],
                    "checks": [
                        {
                            "name": "summary_export_exists",
                            "description": "Desktop/profit_summary.csv exists and is non-empty.",
                            "weight": 0.25,
                        },
                        {
                            "name": "region_profit_correct",
                            "description": "The exported CSV contains north=70, south=35, and west=24.",
                            "weight": 0.6,
                        },
                        {
                            "name": "spreadsheet_gui_used",
                            "description": "The trajectory shows interaction with the spreadsheet GUI.",
                            "weight": 0.15,
                        },
                    ],
                    "hidden_files": {
                        "hidden/evaluate_office_artifact.py": (
                            "import csv, json, sys\n"
                            "from pathlib import Path\n"
                            "path = Path.home() / 'Desktop' / 'profit_summary.csv'\n"
                            "expected = {'north': 70.0, 'south': 35.0, 'west': 24.0}\n"
                            "score = 0.0\nissues = []\n"
                            "if path.is_file() and path.stat().st_size:\n"
                            "    score += 0.25\n"
                            "    rows = list(csv.DictReader(path.open(newline='', encoding='utf-8-sig')))\n"
                            "    found = {str(r.get('region','')).strip().lower(): float(r.get('total_profit', 'nan')) for r in rows if r.get('region')}\n"
                            "    correct = sum(1 for k, v in expected.items() if abs(found.get(k, -999) - v) < 1e-6)\n"
                            "    score += 0.6 * (correct / len(expected))\n"
                            "else:\n"
                            "    issues.append('missing profit_summary.csv')\n"
                            "score = min(1.0, score)\n"
                            "print(json.dumps({'score': score, 'issues': issues}, indent=2))\n"
                            "sys.exit(0 if score >= 0.8 else 1)\n"
                        )
                    },
                },
                {
                    "application": "word_processor",
                    "image": "evalclaw-libreoffice-gui",
                    "required_software": ["libreoffice-writer", "python3", "evalclaw-desktop-bridge"],
                    "prompt": (
                        "Use the desktop word processor to open Desktop/release_notes.md and Desktop/metrics.csv. "
                        "Insert a two-row metrics table under the 'Main Results' heading, keep the 'Draft Notes' "
                        "section unchanged, export Desktop/release_notes_final.html, and run the bridge evaluation."
                    ),
                    "visible_files": {
                        "Desktop/release_notes.md": (
                            "# Product Release Notes\n\n## Main Results\n\nInsert the approved metrics table here.\n\n"
                            "## Draft Notes\n\nDo not edit this section.\n"
                        ),
                        "Desktop/metrics.csv": "metric,value\nlatency_ms,128\nsuccess_rate,0.94\n",
                    },
                    "expected_artifacts": ["Desktop/release_notes_final.html"],
                    "checks": [
                        {
                            "name": "html_export_exists",
                            "description": "Desktop/release_notes_final.html exists.",
                            "weight": 0.25,
                        },
                        {
                            "name": "metrics_inserted",
                            "description": "The HTML export includes latency_ms=128 and success_rate=0.94 under Main Results.",
                            "weight": 0.55,
                        },
                        {
                            "name": "draft_section_unchanged",
                            "description": "The Draft Notes section remains present and unmodified.",
                            "weight": 0.2,
                        },
                    ],
                    "hidden_files": {
                        "hidden/evaluate_office_artifact.py": (
                            "import json, re, sys\n"
                            "from pathlib import Path\n"
                            "path = Path.home() / 'Desktop' / 'release_notes_final.html'\n"
                            "text = path.read_text(encoding='utf-8', errors='ignore').lower() if path.exists() else ''\n"
                            "score = 0.0\nissues = []\n"
                            "if text:\n"
                            "    score += 0.25\n"
                            "else:\n"
                            "    issues.append('missing html export')\n"
                            "if 'latency_ms' in text and '128' in text and 'success_rate' in text and '0.94' in text:\n"
                            "    score += 0.55\n"
                            "if 'draft notes' in text and 'do not edit this section' in text:\n"
                            "    score += 0.2\n"
                            "print(json.dumps({'score': min(1.0, score), 'issues': issues}, indent=2))\n"
                            "sys.exit(0 if score >= 0.8 else 1)\n"
                        )
                    },
                },
            ]
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
            video_variants = [
                ("green-screen presenter", "replace the green background with the provided city plate"),
                ("product lower-third", "add the provided title and timing notes over the product shot"),
                ("reference color match", "apply the provided color notes and export a matched review clip"),
            ]
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
            cad_variants = [
                ("single-room plan", "extrude walls from the visible 2D room drawing and place a door opening"),
                ("two-level core", "model two stacked floor plates, a stair opening, and four support columns"),
                ("facade bay", "model a facade bay with three windows and a parapet line from the elevation notes"),
            ]
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

    return AgentTask(
        id=_task_id(dimension, blueprint.task_family, index),
        dimension_id=dimension.id,
        title=_task_title(blueprint, index),
        description=(
            "A bridge-backed GUI desktop task. The target agent must inspect screenshots and operate the "
            "desktop/browser/software session through the standardized EvaluationClaw tool protocol."
        ),
        task_family=blueprint.task_family,
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
        scoring=AgentScoringSpec(
            method="deterministic",
            instructions="Score using the GUI desktop bridge evaluation contract in environment.evaluation.",
            pass_criteria=str(evaluation["pass_criteria"]),
            partial_criteria=str(evaluation["partial_criteria"]),
            fail_criteria=str(evaluation["fail_criteria"]),
            score_levels={"5": "all bridge checks pass", "3": "partial artifact or GUI progress", "1": "failed"},
            oracle_notes="The bridge owns the concrete VM/browser/software runtime and artifact inspection.",
        ),
        difficulty=dimension.target_difficulty,
        tags=[dimension.id, blueprint.task_family.value, *tags],
    )
