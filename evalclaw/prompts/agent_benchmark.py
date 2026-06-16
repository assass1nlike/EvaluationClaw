"""Prompt templates for agent benchmark construction."""
from __future__ import annotations

import json

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
  - dialogue: multi-turn user simulation without a file/tool environment.
- Common task_family values include workspace_navigation, code_repair,
  repo_issue, shell_debugging, api_tool_use, web_research, data_analysis,
  multi_turn_delegation, safety_tool_use, and custom.
- Every executable task must have a clear oracle: deterministic tests, state
  assertions, pass/fail criteria, or a task-specific judge rubric. Prefer
  deterministic scoring when the environment can support it.
- Static question task types may appear only as auxiliary coverage. The primary
  output for agent-capability requests should be agent_interaction or multi_turn.
- Only include multimodal tasks when the user explicitly asks for multimodal
  agent ability.
- Treat scale as simple-equivalent workload: LOW about 100, MID 500, HIGH 1000,
  LARGE 5000, XLARGE 20000. Agent tasks are heavier than static items, so raw
  task counts can be much smaller than the workload number.
- For LARGE/XLARGE, plan resource-backed task pools and stratified sampling.
  Do not plan thousands of near-identical model-generated fixtures.
""" + "\n\nStandardized task-agent guidance:\n" + TASK_AGENT_GENERATION_GUIDANCE + "\n\nCanonical metadata.task_agent schema:\n" + json.dumps(
    TASK_AGENT_SCHEMA,
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
        "setup_commands": [],
        "test_command": "python3 tests.py",
        "max_steps": 8,
        "timeout": 20,
        "network": "none",
        "resource_limits": {},
        "workspace": {},
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
      "metadata": {}
    }
  ]
}

Task-construction requirements:
- Each task must be independently executable and complete. Do not use ellipses,
  omitted files, preview fields, or references to unavailable context.
- Preserve the assigned dimension. If a task mainly evaluates a different agent
  ability, do not include it.
- Use the blueprint's environment_type unless the resource makes that impossible.
- For code_sandbox, include complete visible_files, hidden_files or a complete
  deterministic test_command, max_steps, and a concise system_prompt that tells
  the target to use one JSON tool action per turn.
- For docker_workspace, include image, setup_commands, visible_files,
  hidden_files, test_command, timeout, network, and resource_limits. Use it only
  when realistic OS/runtime behavior matters.
- For workspace, define a concrete state space in environment.workspace or
  metadata that can be converted into the built-in workspace environment.
- Keep hidden oracle material out of visible task instructions.
- Prefer deterministic scoring. If judge scoring is needed, define score levels
  and pass/partial/fail criteria clearly.
- Diversify tasks within the blueprint by resource, state, failure mode, or tool
  path. Avoid near-duplicates.
"""
