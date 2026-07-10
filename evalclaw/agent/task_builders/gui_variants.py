"""Template variants for GUI desktop fallback task builders."""
from __future__ import annotations

import json
from typing import Any


def get_app_state_variants() -> list[Any]:
    return [
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

def get_industrial_workflow_variants() -> list[Any]:
    return [
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

def get_blender_variants() -> list[Any]:
    return [
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

def get_artifact_variants() -> list[Any]:
    return [
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

def get_office_variants() -> list[Any]:
    return [
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

def get_video_variants() -> list[Any]:
    return [
                    ("green-screen presenter", "replace the green background with the provided city plate"),
                    ("product lower-third", "add the provided title and timing notes over the product shot"),
                    ("reference color match", "apply the provided color notes and export a matched review clip"),
                ]

def get_cad_variants() -> list[Any]:
    return [
                    ("single-room plan", "extrude walls from the visible 2D room drawing and place a door opening"),
                    ("two-level core", "model two stacked floor plates, a stair opening, and four support columns"),
                    ("facade bay", "model a facade bay with three windows and a parapet line from the elevation notes"),
                ]

