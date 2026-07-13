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
like a benchmark author: choose realistic task designs, identify reusable
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
        "challenge_effort": "E3",
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
      "content_summary": "3-8 words naming the concrete task content",
      "description": "...",
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
- If the user specifies an explicit raw task count, distribute that exact count
  across agent_task_blueprints so that the sum of expected_task_count equals
  the requested count.
- Use existing resources when they make the task more realistic: repositories,
  issues, docs, CLI/API manuals, bug reports, datasets, notebooks, webpages, or
  benchmark instances. Do not force external resources when a small synthetic
  fixture is more reliable and sufficient.
- Pick environment_type deliberately:
  - workspace: only the built-in deterministic room/inventory simulation for
    stateful routing, object selection, and memory. It does not execute arbitrary
    custom tools, websites, MCP servers, APIs, or browser actions.
  - code_sandbox: self-contained Python/file repair with hidden tests.
  - docker_workspace: realistic dependencies, shell diagnostics, non-Python
    runtimes, package installation, native builds, OS-sensitive tasks, local
    web applications, API/MCP services, or headless-browser workflows. For web
    tasks, include the complete resettable site/service fixture and a hidden
    state-based evaluator; do not route them to workspace.
  - gui_desktop: GUI/browser/desktop-software tasks executed through a
    bridge that provides screenshot, mouse, keyboard, file, command, and
    evaluation actions. Use this only when real UI operation matters.
  - dialogue: multi-turn user simulation without a file/tool environment.
- Describe each construction plan directly through its capability, description,
  environment, tools, concrete requirements, resources, and scoring strategy.
  Do not reduce the task to a fixed categorical taxonomy.
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
- challenge_effort is the required construction and reasoning effort. It tells task
  builders how much effort to spend making tasks challenging, relative to the
  builder model's own ability:
  - E1: easily generate simple, direct tasks.
  - E2: think and plan moderately; create nontrivial tasks with some edge cases.
  - E3: use high effort and detailed planning; create tasks the builder itself
    considers difficult, with realistic constraints and stronger oracles.
  - E4: use maximum effort, budget, planning depth, and external research/tool
    use when useful; push to the builder's own upper limit for task challenge.
- For expert software-engineering, long-horizon, professional workflow, VM,
  docker_workspace, or GUI task requests, prefer E4 when the user is asking for
  genuinely hard benchmark tasks; use E3 when the scope is intentionally compact.
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
- Treat scale as the planned raw task count: LOW about 100, MID 500, HIGH 1000,
  LARGE 5000, and XLARGE 20000. Do not reduce the count because tasks are agent,
  multi-turn, Docker, VM, GUI, or otherwise complex. Distribute the count across
  agent_task_blueprints so expected_task_count values sum to scale unless the
  user provided a different explicit count.
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
      "prompt": "Instruction shown to the target agent.",
      "system_prompt": "Concise per-task system prompt for the target agent.",
      "resource_ids": ["resource_id"],
      "environment": {
        "type": "code_sandbox",
        "tools": [],
        "visible_files": {"relative/path.py": "complete starting file content"},
        "runtime_files": {"relative/server.py": "complete setup-only runtime content"},
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
        "workdir": "/workspace",
        "workspace": {},
        "browser": {
          "enabled": false,
          "runtime": "playwright_python",
          "start_url": "",
          "allowed_origins": [],
          "executable_path": "",
          "timeout_ms": 15000,
          "startup_timeout": 45,
          "workspace_tools": []
        },
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
        "score_levels": {"0": "fail", "0.5": "partial", "1": "pass"},
        "oracle_notes": "..."
      },
      "challenge_effort": "E3",
      "tags": ["..."],
      "metadata": {
        "challenge_effort_self_assessment": {
          "requested_effort": "E3",
          "meets_requested_effort": true,
          "rationale": "Why this task satisfies the requested construction effort.",
          "effort_actions": ["Concrete choices made to increase or calibrate task challenge."]
        },
        "agent_task_package": {}
      }
    }
  ]
}

Task-construction requirements:
- If the payload contains revision, treat revision.previous_tasks as the tasks
  from the prior builder round and revision.qc_issues as authoritative quality
  feedback. Return complete replacement tasks for this blueprint, preserving
  sound content while fixing every blocking issue. Do not return a patch or
  merely explain the changes.
- The tasks array length must equal task_plan.construction.expected_task_count exactly.
  Generate independent task content for each task; do not duplicate prompts or
  create numbered clones of the same fixture.
- Each task must be independently executable and complete. Do not use ellipses,
  omitted files, preview fields, or references to unavailable context.
- Before returning, audit every task prompt, visible file, hidden file,
  evaluator script, and metadata instruction for completeness. Strings must not
  stop mid-word, mid-sentence, mid-expression, or before closing punctuation,
  braces, quotes, code blocks, or JSON/Python/shell syntax.
- Each task must include content_summary: a short human-readable 3-8 word label
  used in reports between the dimension label and target model name. It should
  summarize the concrete task content, not repeat the dimension, not include
  random IDs, and not include hidden oracle details or answer keys.
- Set task.challenge_effort equal to task_plan.capability.challenge_effort. This field is
  the requested task-builder challenge effort, not a post-hoc absolute item
  challenge-effort estimate.
- Apply the assigned challenge_effort:
  - E1: generate a simple direct task with a clear oracle.
  - E2: spend moderate planning effort; add meaningful edge cases, stronger
    constraints, or a more realistic fixture while keeping the task compact.
  - E3: spend high effort; design a task that is difficult by your own task
    builder standard, with detailed scenario planning, realistic failure modes,
    multiple interacting constraints, and robust hidden evaluation.
  - E4: spend maximum effort; use the highest useful planning depth, resource
    search, external evidence, realistic environment construction, adversarial
    edge cases, and oracle design available to you. Do not perform ceremonial
    tool use if it adds no value, but push the task to your own capability limit.
- Challenge effort measures design depth, realism, and evaluator strength, not
  response length or fixture size. Prefer compact complete fixtures and avoid
  repeating the same long instructions, code, or criteria across overlapping
  fields. Do not spend the output budget on irrelevant application boilerplate.
- Before returning, self-assess whether each task satisfies the requested
  challenge_effort. If not, revise it. Then include
  metadata.challenge_effort_self_assessment with requested_effort,
  meets_requested_effort=true, a concise rationale, and concrete effort_actions.
- Preserve task_plan.capability. If a task mainly evaluates a different agent
  ability, do not include it.
- Use task_plan.construction.environment_type unless the resource makes that impossible.
- The workspace environment is not a generic custom-tool host. It can execute
  only EvaluationClaw's built-in look/move/inspect/take/place/final room-and-
  inventory workflow. For a workspace blueprint, populate environment.workspace
  with start_room, rooms, item_descriptions, and goal.outgoing_bin, and make the
  task use those built-in actions. Do not claim that entries in environment.tools
  implement arbitrary website, browser, MCP, database, or API behavior.
- For browser, website, MCP, or service-state tasks, use a docker_workspace
  blueprint with a compact but complete local application/service fixture,
  pinned runnable dependencies, setup/start commands, canonical browser tools,
  and a deterministic hidden evaluator that checks actual backend/page/artifact
  state. Set environment.browser.enabled=true, runtime=playwright_python,
  start_url to the initial local page, and allowed_origins to the local site
  origins. Use a Python Playwright image such as a pinned
  mcr.microsoft.com/playwright/python image, or build an equivalent image with
  Python Playwright and its browser binaries already installed. For an
  image_build using a system Chromium package, set browser.executable_path to
  its absolute guest path such as /usr/bin/chromium. The local app
  must use preinstalled/standard-library dependencies or an image_build; a
  network=none setup command cannot pip/npm/apt install remote packages. Start
  put server/application code needed by setup in runtime_files, start the app in
  setup_commands with a persistent background command, and make it
  ready before the target's first browser call. EvaluationClaw supplies the
  browser_navigate/browser_snapshot/browser_click/browser_fill/browser_select/
  browser_check/browser_press/browser_get_text tools, so do not invent
  environment.tools entries for them. Use gui_desktop only when visual UI
  operation itself is part of the capability. Do not substitute a prose-only
  website mock.
- Browser tasks expose no shell/file tools by default. If the target must create
  a file artifact, set browser.workspace_tools to the minimal required subset
  of list_files/read_file/write_file/run_command, normally ["write_file"] only.
  File output paths must be relative to environment.workdir or absolute paths
  inside it. Do not use /tmp or another directory that write_file cannot reach.
  Do not expose run_command when it would let the target bypass the intended
  browser workflow by reading application source, databases, or hidden state.
- The canonical completion tool is named final, not final_answer. The runner
  privately writes final's answer argument to /tmp/evalclaw_final_answer.json
  before evaluation.
- Hidden evaluators must inspect the state or artifacts left by the target.
  They must never execute, simulate, or replay the target's required actions to
  create the expected state. For final-answer tasks, the runner stores the
  target's final tool answer in /tmp/evalclaw_final_answer.json before private
  evaluation. Keep every output contract consistent with the target prompt: do
  not require a file or state change that the target was never instructed to
  produce.
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
- Keep scoring scales consistent across scoring, metadata.task_agent, and
  metadata.agent_task_package. If metadata.agent_task_package.evaluation uses
  score_range [0, 1], then use pass=1, partial values between 0 and 1, and
  fail=0 rather than 1-5 levels.
- For numeric outputs, floating-point values, performance timings, or
  platform-sensitive command output, use explicit tolerances or robust
  predicates instead of exact fragile strings.
- For dependency, packaging, service, or configuration tasks, use internally
  consistent real-world failure modes. The visible dependency pins, setup/build
  commands, import/runtime errors, and hidden evaluator must all agree. Do not
  invent conflicts between packages that do not actually interact, and do not
  make success depend on runtime network access unless the environment
  explicitly enables it.
- Hidden evaluator behavior should be summarized concretely in scoring and
  metadata.agent_task_package.evaluation: state what command is run, what app or
  service is started if any, what endpoint/file/output is checked, and what
  exit codes or score values mean. Keep hidden reference contents private, but
  do not leave the execution contract ambiguous.
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
  runtime_files, hidden_files, test_command, timeout, network, and resource_limits. Use it only
  when realistic OS/runtime behavior matters. When the task uses runtime_files
  or hidden_files, do not request run_command: raw
  shell access is withheld so the target cannot bypass protected-file phases.
  Use structured workspace tools and runner-private run_tests instead. If the
  task clearly requires a runtime, choose a common official image such as python:3.11-slim,
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
  Setup-only application/server files belong in runtime_files. Never reference
  hidden_files or /tmp/hidden_files from setup_commands; hidden_files are
  evaluator-only and do not exist until scoring.
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
  score weights. Describe the concrete browser, native application, or general
  desktop workflow directly in the session, environment, tools, requirements,
  and evaluator rather than assigning a fixed category. For Blender tasks, require a
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
"""
