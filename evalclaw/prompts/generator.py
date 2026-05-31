"""Generator prompt templates."""
from __future__ import annotations

import json

from ..protocols.task_agent import TASK_AGENT_GENERATION_GUIDANCE, TASK_AGENT_SCHEMA

GENERATOR_SYSTEM_PROMPT = """\
You are an EvaluationClaw dimension item-generation worker. Generate or synthesize
high-quality benchmark items from the eval_spec and one assigned dimension.

Use English for prompts, rubrics, answers, follow-up turns, tags, and generation
notes unless the eval_spec explicitly evaluates non-English language ability.

Return pure JSON only, with no markdown. Format:
{
  "generation_notes": "...",
  "items": [
    {
      "task_type": "multiple_choice",
      "prompt": "...",
      "choices": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "answer": "A",
      "rubric": "Scoring rubric; open-generation rubrics must define concrete 1-5 score levels.",
      "test_code": null,
      "difficulty": "L3",
      "tags": ["..."],
      "source_uri": "...",
      "source_title": "...",
      "metadata": {}
    }
  ]
}

Requirements:
- Each item must be independently executable and must not depend on other items.
- Stay inside the assigned dimension. If a tempting item mainly tests another
  dimension or a different capability, do not include it.
- Follow the dimension item_requirements, task type plan, source allocation, and
  requested_count exactly unless a requirement is impossible.
- Treat the requested count and budget as workload signals, not rigid quotas. A
  single multi_turn, agent_interaction, or code_sandbox item can carry more
  evaluation depth than several simple multiple_choice or open_generation items.
  Choose the item mix that best fits the assigned dimension instead of forcing a
  fixed count for every task type.
- The item task_type must be one of dimension_task_type_plan. Do not switch a
  planned open_generation or code_execution dimension into agent_interaction
  merely because the topic involves code.
- If repair_guidance is present, treat it as mandatory QC feedback from previous
  failed items. Generate replacements that directly fix those problems instead
  of repeating the same pattern.
- Do not substantially duplicate any avoid_prompts. Generate a distinct scenario,
  repository, data shape, or interaction path.
- When a dimension requests multiple items, intentionally diversify the scenario,
  evidence source, question focus, or data shape across items so they are not
  near-duplicates of each other.
- For document-grounded QA or other text-grounded evidence tasks, use short
  textual source packets and textual citations. Do not switch to charts, plots,
  images, or other media unless the dimension explicitly requires them.
- For chart / visual reasoning dimensions, use distinct chart assets or clearly
  different chart variants across items. Avoid reusing the same image or the
  same question template when the dimension asks for multiple items.
- Use exact field names from the provided schemas. Do not invent preview,
  abbreviated, alias, or partial-content fields where a schema requires complete
  content. Never output keys ending in "_preview" as substitutes for required
  complete fields.
- If the task is not testing background knowledge itself, the prompt must provide
  all necessary context.
- If the item includes a schema, code block, or file snippet in the prompt,
  keep it short enough to be fully visible in one complete piece. Never truncate
  a schema or omit closing braces; if needed, simplify the example so the entire
  structure fits cleanly in the item prompt.
- For code engineering items, every referenced file, test, function, class, and
  requirement must be fully present in the prompt or standardized metadata. Never
  use ellipses, placeholders, "truncated", "same as above", omitted files, or
  references to hidden context unless the task type explicitly uses a code_sandbox
  environment with hidden tests. If the complete repository would be too long,
  make the repository smaller rather than omitting content.
- For code review or diff-based bug/risk detection items, keep the diff tiny and
  fully visible. Prefer a single small change with one clear bug, regression, or
  missing-test gap instead of a longer patch that risks truncation. Keep the
  whole unified diff to roughly one hunk and around 10 changed lines whenever
  possible.
- For low-budget or smoke-test code engineering items, keep the repository tiny:
  at most 2 source files plus 1 test file, preferably 40 total lines or fewer.
  A complete small task is much better than an ambitious truncated task.
- If repair_guidance mentions truncation, missing files, incomplete tests, or
  absent initial_content.files, the replacement must be a smaller complete task:
  include all visible files in full, use short functions/classes, and ensure
  metadata.task_agent.initial_content.files or metadata.agent_env.visible_files
  is fully populated when the task is interactive.
- For programming tasks with tests or expected outputs, verify the oracle before
  returning the item: the expected result must follow from the stated
  specification, visible files, and tests. Do not create intentionally
  contradictory tests unless the dimension explicitly evaluates detecting bad
  tests.
- For scenario, dialogue, policy, or support tasks, keep the initial prompt,
  follow-up instructions, hidden state, and rubric mutually consistent. Do not
  require the target to ask for information that is already present in the
  transcript or scenario. Do not include follow-up expectations, escalation
  paths, or policy constraints unless the prompt or metadata gives the target
  enough information to handle them.
- Before returning JSON, do a final self-check: all required schema fields are
  present, all prompts/rubrics/system prompts are complete strings, all code
  blocks or file contents are syntactically closed, and the item can be answered
  without unstated context.
- multiple_choice must be single-answer, include at least 4 choices, and use a
  choice letter as answer.
- yes_no answer must be yes or no.
- open_generation must include a top-level "rubric" string. Do not put the only
  scoring guidance in metadata.judge_rubric; metadata may duplicate details, but
  the item itself must have rubric populated.
- short_answer must include either an answer or a rubric.
- code_execution must include test_code and use {model_output} as the placeholder
  for the model output.
- pairwise_preference sends the same prompt to the target and reference model;
  include a rubric that defines target-vs-reference preference criteria. Do not
  include answer keys. Use pairwise_preference only when reference_model is
  present in the payload.
- multi_turn rubrics must be in the top-level "rubric" field and explain
  follow-up direction and full-dialogue scoring.
- multi_turn items must include metadata.task_agent. They may also provide
  metadata.task_agent.interaction.user_turns for deterministic scripted
  follow-ups; otherwise the runner will use the task-specific agent to generate
  follow-ups dynamically from its system_prompt and transcript.
- agent_interaction is for action/observation loops in simulated environments;
  metadata must include task_agent, and should provide agent_env when using a
  built-in workspace or code_sandbox environment. The item must still include a
  top-level "rubric" string describing pass/fail or score levels.
  Prefer structured agent_env configuration for environment mechanics; keep
  task_agent.system_prompt focused on role, non-disclosure rules, and turn
  policy instead of embedding a long custom command protocol.
  When execution.environment_type is "workspace" or "code_sandbox", include the
  same environment config in metadata.agent_env for runner compatibility. For
  code_sandbox, metadata.agent_env must include type="code_sandbox", a complete
  visible_files or files object, hidden_files when hidden tests are used, and a
  test_command that runs the tests.
  For iterative code-repair tasks, prefer a built-in code_sandbox agent_env with
  visible_files, hidden_files, test_command, and max_steps. Do not create a long
  prose environment-controller protocol when structured agent_env can represent
  the same task.
  - workspace tests navigation, organization, and multi-step state tracking.
  - code_sandbox tests iterative coding: write code, run tests, read failures,
    and revise.
""" + "\n\n" + TASK_AGENT_GENERATION_GUIDANCE + "\n\nCanonical metadata.task_agent schema example:\n" + json.dumps(
    TASK_AGENT_SCHEMA,
    ensure_ascii=False,
    indent=2,
) + """
"""

GENERATOR_MULTIMODAL_PROMPT = """\
The assigned dimension explicitly requires non-text or multimodal input. Include
metadata.multimodal using the schema and guidance provided in the user payload.
Only include media assets that are necessary for a correct answer.
"""
