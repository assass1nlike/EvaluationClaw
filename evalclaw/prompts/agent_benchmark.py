"""Prompt templates for agent benchmark construction."""
from __future__ import annotations

import json

from ..protocols.agent_task_package import (
    AGENT_TASK_PACKAGE_GENERATION_GUIDANCE,
    AGENT_TASK_PACKAGE_SCHEMA,
)
from ..protocols.task_agent import TASK_AGENT_GENERATION_GUIDANCE, TASK_AGENT_SCHEMA

AGENT_BENCHMARK_PLANNER_PROMPT = """\
You are the EvaluationClaw Agent Benchmark Planner.

The user's request should be turned into an executable benchmark for evaluating
AI agents, not primarily a collection of static question-answer items. Think
like a benchmark author: choose realistic task families, identify reusable
resources, define environments/tools, and specify automatic success criteria.

Use English for JSON fields unless the evaluation explicitly tests another
language. Return pure JSON only, with no markdown.

Return this object:
{
  "spec": {
    "id": "snake_case_id",
    "objective": "...",
    "subjects": ["user_supplied_targets"],
    "task_types": ["agent_interaction"],
    "scale_budget": "mid",
    "scale": 500,
    "metrics": ["pass@1", "judge_score"],
    "constraints": ["..."],
    "planner_notes": "...",
    "dimensions": [
      {
        "id": "snake_case",
        "name": "...",
        "description": "...",
        "approach": "...",
        "weight": 1.0,
        "target_difficulty": "L4",
        "needs_research": true,
        "research_queries": ["..."],
        "target_item_count": 3,
        "target_source_backed_count": 2,
        "target_generated_count": 1,
        "task_types": ["agent_interaction"],
        "item_requirements": [
          "What the task builder must construct and what off-target tasks look like."
        ]
      }
    ]
  },
  "agent_task_blueprints": [
    {
      "id": "snake_case",
      "dimension_id": "dimension_id",
      "title": "...",
      "description": "...",
      "task_family": "code_repair",
      "environment_type": "code_sandbox",
      "expected_task_count": 2,
      "resource_queries": ["..."],
      "source_strategy": "Use existing GitHub-style issue/repo materials where possible...",
      "tool_requirements": ["read_file/write_file/run_tests", "..."],
      "construction_requirements": [
        "Build a complete executable task package with visible starting state and hidden oracle."
      ],
      "scoring_strategy": "Deterministic hidden tests plus partial credit for meaningful test runs."
    }
  ],
  "critique": {
    "checklist": {"objective": true, "subjects": true, "format": true, "content": true, "scale": true, "metrics": true},
    "score": 4.5,
    "missing_items": [],
    "notes": "..."
  }
}

Planning requirements:
- Prefer 3-6 independent agent capability dimensions unless the request is
  narrow. Dimensions should reflect agent abilities such as tool selection,
  state tracking, environment exploration, code repair, API use, recovery from
  failed commands/tests, long-horizon planning, and safety-constrained tool use.
- For each dimension, create one or more agent_task_blueprints that say how
  executable tasks should be built from existing resources or compact generated
  fixtures. A blueprint is a task-construction plan, not the final task.
- Use existing resources when they make the task more realistic: repositories,
  issues, docs, CLI/API manuals, bug reports, datasets, notebooks, webpages, or
  benchmark instances. Do not force external resources when a small synthetic
  fixture is more reliable and sufficient.
- Pick environment_type deliberately:
  - workspace: stateful toy tool-use, routing, object selection, memory.
  - code_sandbox: self-contained Python/file repair with hidden tests.
  - docker_workspace: realistic dependencies, shell diagnostics, non-Python
    runtimes, package installation, native builds, or OS-sensitive tasks.
  - gui_desktop: GUI/browser/desktop-software tasks executed through a
    bridge that provides screenshot, mouse, keyboard, file, command, and
    evaluation actions. Use this only when real UI operation matters.
  - dialogue: multi-turn user simulation without a file/tool environment.
- Common task_family values include workspace_navigation, gui_desktop,
  browser_gui, desktop_software, code_repair, repo_issue, shell_debugging,
  api_tool_use, web_research, data_analysis, multi_turn_delegation,
  safety_tool_use, and custom.
- For gui_desktop blueprints, construction_requirements must tell the task
  builder to write standardized metadata.task_agent JSON plus
  metadata.agent_task_package JSON plus environment.session, environment.vm,
  and environment.evaluation. The session
  should describe the app/window, starting state, assets, and expected artifacts.
  The vm object should describe isolation, image/snapshot, display, required
  software, network, and locale requirements when a fresh VM is needed. The
  evaluation should describe artifact/state checks and pass/partial/fail
  criteria. Do not hardcode bridge or VM-provider secrets; bridge_url or
  vm_provider_url can be supplied at run time.
- For multi-industrial-software collaboration requests, do not create a
  single-app CAD, EDA, or rendering task. Plan a VM-backed desktop_software
  workflow with at least two named industrial applications and preferably a
  reproducible open-source stack such as KiCad + FreeCAD + Blender unless the
  user supplied licensed software. The blueprint must define cross-application
  artifact handoffs, expected intermediate/final files, unit/provenance
  tracking, and a deterministic artifact/trace oracle.
- Every executable task must have a clear oracle: deterministic tests, state
  assertions, pass/fail criteria, or a task-specific judge rubric. Prefer
  deterministic scoring when the environment can support it.
- For ALE-like professional workflows, VM-backed tasks, docker_workspace tasks,
  GUI/browser/desktop-software tasks, and long-horizon executable tasks, require
  metadata.agent_task_package. It must separate visible inputs from hidden
  references, define output artifacts/schema, setup/run/evaluate steps,
  artifact/trajectory collection, environment/software requirements, and
  provenance. Do not reduce these tasks to "write a report" unless the requested
  capability is specifically report writing.
- Static question task types may appear only as auxiliary coverage. The primary
  output for agent-capability requests should be agent_interaction or multi_turn.
- Only include multimodal tasks when the user explicitly asks for multimodal
  agent ability.
- Treat scale as simple-equivalent workload: LOW about 100, MID 500, HIGH 1000,
  LARGE 5000, XLARGE 20000. Agent tasks are heavier than static items, so raw
  task counts can be much smaller than the workload number.
- For LARGE/XLARGE, plan resource-backed task pools and stratified sampling.
  Do not plan thousands of near-identical model-generated fixtures.
""" + "\n\nStandardized task-agent guidance:\n" + TASK_AGENT_GENERATION_GUIDANCE + "\n\nExecutable agent task package guidance:\n" + AGENT_TASK_PACKAGE_GENERATION_GUIDANCE + "\n\nCanonical metadata.task_agent schema:\n" + json.dumps(
    TASK_AGENT_SCHEMA,
    ensure_ascii=False,
    indent=2,
) + "\n\nCanonical metadata.agent_task_package schema:\n" + json.dumps(
    AGENT_TASK_PACKAGE_SCHEMA,
    ensure_ascii=False,
    indent=2,
) + "\n"


AGENT_TASK_BUILDER_PROMPT = """\
You are an EvaluationClaw Agent Task Builder.

Construct executable agent benchmark tasks from the provided eval spec,
dimension, blueprint, and resource context. The output is a set of full task
packages that EvaluationClaw can convert into agent_interaction items.

Use English unless the evaluation explicitly tests another language. Return
pure JSON only, with no markdown.

Return this object:
{
  "construction_notes": "...",
  "resources": [
    {
      "id": "resource_id",
      "kind": "github_issue | docs | web | generated_fixture | dataset | repo",
      "uri": "https://...",
      "title": "...",
      "license": "...",
      "content_summary": "...",
      "notes": "..."
    }
  ],
  "tasks": [
    {
      "id": "snake_case_task",
      "dimension_id": "dimension_id",
      "title": "...",
      "description": "...",
      "task_family": "code_repair",
      "prompt": "Instruction shown to the target agent.",
      "system_prompt": "Concise per-task system prompt for the target agent.",
      "resource_ids": ["resource_id"],
      "environment": {
        "type": "code_sandbox",
        "tools": [],
        "visible_files": {"relative/path.py": "complete starting file content"},
        "hidden_files": {"tests.py": "complete hidden test content"},
        "image": "",
        "auto_select_image": true,
        "image_build": {
          "enabled": false,
          "base_image": "",
          "system_packages": [],
          "python_packages": [],
          "node_packages": [],
          "cran_packages": [],
          "bioconductor_packages": [],
          "julia_packages": [],
          "conda_packages": [],
          "cargo_packages": [],
          "go_packages": [],
          "gem_packages": [],
          "composer_packages": [],
          "install_steps": [],
          "commands": [],
          "dockerfile": "",
          "context_files": {}
        },
        "pull_image": true,
        "pull_timeout": 300,
        "setup_commands": [],
        "test_command": "python3 tests.py",
        "max_steps": 8,
        "timeout": 20,
        "network": "none",
        "resource_limits": {},
        "workspace": {},
        "bridge_url": "",
        "bridge_api_key": null,
        "requires_vm": false,
        "vm_provider_url": "",
        "vm_provider_api_key": null,
        "vm": {},
        "vm_provisioning": {
          "enabled": false,
          "strategy": "cloud_init.v1",
          "apt_packages": [],
          "pip_packages": [],
          "snap_packages": [],
          "cran_packages": [],
          "bioconductor_packages": [],
          "julia_packages": [],
          "conda_packages": [],
          "cargo_packages": [],
          "go_packages": [],
          "gem_packages": [],
          "composer_packages": [],
          "install_steps": [],
          "commands": [],
          "desktop_bridge_install_command": "",
          "desktop_bridge_start_command": ""
        },
        "session": {},
        "evaluation": {},
        "notes": "..."
      },
      "interaction": {
        "max_turns": 8,
        "initial_user_message": "",
        "user_turns": [],
        "followup_instruction": "",
        "stop_condition": "..."
      },
      "scoring": {
        "method": "deterministic",
        "instructions": "...",
        "pass_criteria": "...",
        "partial_criteria": "...",
        "fail_criteria": "...",
        "score_levels": {"1": "fail", "3": "partial", "5": "pass"},
        "oracle_notes": "..."
      },
      "difficulty": "L4",
      "tags": ["..."],
      "metadata": {
        "agent_task_package": {}
      }
    }
  ]
}

Task-construction requirements:
- Each task must be independently executable and complete. Do not use ellipses,
  omitted files, preview fields, or references to unavailable context.
- Preserve the assigned dimension. If a task mainly evaluates a different agent
  ability, do not include it.
- Use the blueprint's environment_type unless the resource makes that impossible.
- For ALE-like professional workflows, VM-backed tasks, docker_workspace tasks,
  GUI/browser/desktop-software tasks, and long-horizon executable tasks, include
  metadata.agent_task_package using schema_version
  "evalclaw.agent_task_package.v1". The task package must define capability_target,
  environment_requirements, visible_inputs, hidden_references, output_contract,
  execution, evaluation, artifact_collection, trajectory_requirements, and
  resource_provenance. Keep hidden references out of visible prompts and
  visible_inputs.
- Every evaluation contract must be reproducible. If you mention metrics such as
  pHash, SSIM, perceptual similarity, audio fingerprinting, ffprobe metadata,
  numerical tolerance, schema validation, or log/RCA matching, specify the exact
  algorithm, input paths, threshold/tolerance, and how partial credit is
  computed. Mirror the same concrete values in scoring.pass_criteria,
  scoring.partial_criteria, and metadata.agent_task_package.evaluation.
- Hidden evaluator files, ground-truth JSON, tests, and reference manifests must
  be complete file contents. Never put ellipses, previews, "same as above",
  omitted logic, or placeholder snippets in hidden_files or
  hidden_references.files. The visible evidence must be sufficient and
  internally consistent with the hidden truth set.
- For artifact tasks, visible inputs must include enough concrete files or
  inline asset_files/assets with path/content to start the task. Do not rely on
  unstated human-prepared reference videos, datasets, or project files unless
  they are listed under hidden_references or resource_provenance.
- For code_sandbox, include complete visible_files, hidden_files or a complete
  deterministic test_command, max_steps, and a concise system_prompt that tells
  the target to use one JSON tool action per turn.
  - For docker_workspace, include image, setup_commands, visible_files,
  hidden_files, test_command, timeout, network, and resource_limits. Use it only
  when realistic OS/runtime behavior matters. If the task clearly requires a
  runtime, choose a common official image such as python:3.11-slim,
  node:22-bookworm-slim, rust:1.85-slim, golang:1.23-bookworm,
  maven:3.9-eclipse-temurin-21, gradle:8-jdk21, ruby:3.3-slim,
  php:8.3-cli, gcc:14-bookworm, r-base:4.4.1, or ubuntu:22.04.
  If unsure, leave image empty or set image to "auto"; EvaluationClaw will
  select a runtime image from task files, commands, and prompt evidence before
  execution and the runner will pull it when needed. You may also set
  auto_select_image=true explicitly when you want EvaluationClaw to choose.
  When no common Docker Hub runtime image is sufficient, set image to
  "build://auto" or set image_build.enabled=true. Use image_build.base_image for
  a common base image, system_packages for apt packages, python_packages for pip
  packages, node_packages for global npm packages, cran_packages/r_packages,
  bioconductor_packages, julia_packages, conda_packages with conda_channels,
  cargo_packages, go_packages, gem_packages, composer_packages, apk/dnf/yum/
  pacman package fields, install_steps for manager-specific package installs,
  commands for extra Dockerfile RUN steps, dockerfile for a complete custom
  Dockerfile when needed, and context_files for files required only at
  image-build time. Keep task input files in visible_files/session assets, not
  image_build.context_files, unless the files are genuinely build-time
  dependencies.
- For gui_desktop, include max_steps, timeout, session, evaluation, and usually
  requires_vm=true plus vm for realistic desktop-software or OS-level tasks.
  Leave bridge_url, bridge_api_key, vm_provider_url, and vm_provider_api_key
  empty unless the user explicitly supplied non-secret local service URLs;
  runtime config can inject them. Put guest files that should exist before the
  task starts in metadata.agent_env.visible_files or metadata.task_agent.initial_content.files.
  Put session-specific documents/data in session.asset_files or assets entries
  with path/content objects. EvaluationClaw materializes those files into a
  per-task cloud-init seed ISO before VM startup when no explicit seed ISO is
  supplied. The session object must describe application
  type, launch/start state, assets or input files, expected artifacts, and any
  restrictions such as whether direct file edits are allowed. The vm object
  should describe isolation, image/snapshot, display resolution/scale,
  required software, network policy, locale, and reset behavior. Optional
  vm_materialization may set guest_user, guest_root, enabled=false, or
  overwrite_seed_iso=true for unusual images. The evaluation
  object must define deterministic bridge checks when possible: artifact paths,
  UI/page-state checks, trace constraints, pass/partial/fail criteria, and
  score weights. Use task_family browser_gui for browser UI tasks,
  desktop_software for applications such as spreadsheets or PDF/document
  editors, Blender/3D modeling, image editing, and other native applications,
  and gui_desktop for general desktop operation. For Blender tasks, require a
  VM image with Blender and the desktop bridge, specify .blend plus rendered
  image artifacts, and define a bridge evaluator that inspects objects,
  materials, positions, camera/light, and rendered-image validity. Use requires_vm=false
  only for controlled browser-service tasks or explicitly pre-existing bridge
  sessions where VM isolation is not needed.
- For multi-industrial-software tasks, environment.session must name every
  application, define workflow_stages, handoff_artifacts, and expected_artifacts,
  and require workflow_manifest.json with applications_used, handoffs, artifacts,
  units, checks_performed, and notes. environment.vm.required_software must list
  the full stack, for example kicad, freecad, blender, python3, and the desktop
  bridge. The hidden evaluator or bridge evaluation must check both artifacts
  and provenance; a text-only solution or single-application solution should
  fail.
  If the required software is not assumed to be preinstalled, include
  environment.vm_provisioning.enabled=true with apt_packages/pip_packages/
  snap_packages, cran_packages, bioconductor_packages, julia_packages,
  conda_packages, cargo_packages, go_packages, gem_packages,
  composer_packages, non-Debian package-manager fields, install_steps, and
  commands. EvaluationClaw will add those install/setup commands to the task
  cloud-init seed ISO for cloud-init-capable VM images.
  Use desktop_bridge_install_command or desktop_bridge_start_command only when
  the bridge install/start command is known; otherwise state that the VM provider
  must supply the bridge service.
- For workspace, define a concrete state space in environment.workspace or
  metadata that can be converted into the built-in workspace environment.
- Keep hidden oracle material out of visible task instructions.
- Prefer deterministic scoring. If judge scoring is needed, define score levels
  and pass/partial/fail criteria clearly.
- Diversify tasks within the blueprint by resource, state, failure mode, or tool
  path. Avoid near-duplicates.
""" + "\n\nExecutable agent task package guidance:\n" + AGENT_TASK_PACKAGE_GENERATION_GUIDANCE + "\n\nCanonical metadata.agent_task_package schema:\n" + json.dumps(
    AGENT_TASK_PACKAGE_SCHEMA,
    ensure_ascii=False,
    indent=2,
) + "\n"
