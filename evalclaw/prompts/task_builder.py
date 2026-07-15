"""Prompt for the single general task-construction route."""

TASK_BUILDER_PROMPT = """\
You are the EvaluationClaw Task Builder.

Construct exactly one benchmark task for the supplied blueprint slot. Treat the
task type, capability, requirements, resources, scoring strategy, and response
schema in the payload as authoritative. Return only the fields required for
this task; do not invent optional sections that the blueprint does not request.

Use English unless the evaluation explicitly tests another language. Return
pure JSON only, with no markdown. The top-level object must contain:
{
  "construction_notes": "...",
  "resources": [],
  "tasks": [
    {
      "id": "...",
      "dimension_id": "...",
      "task_type": "...",
      "title": "...",
      "content_summary": "...",
      "description": "...",
      "prompt": "...",
      "choices": [],
      "answer": null,
      "rubric": null,
      "test_code": null,
      "scoring": {
        "method": "...",
        "instructions": "...",
        "pass_criteria": "...",
        "partial_criteria": "...",
        "fail_criteria": "...",
        "score_levels": {},
        "oracle_notes": "..."
      },
      "challenge_effort": "E3",
      "tags": [],
      "metadata": {
        "challenge_effort_self_assessment": {
          "requested_effort": "E3",
          "meets_requested_effort": true,
          "rationale": "..."
        }
      }
    }
  ]
}

The tasks array must contain exactly one complete task. Choices, answer,
rubric, test_code, system_prompt, resource_ids, interaction, and other optional
fields should be populated only when required by the requested task type or
the payload. Provide a usable scoring oracle for every task. During repair,
fix every listed issue while preserving content that QC did not identify as
problematic.
"""

EXECUTION_CAPABILITY_PROMPT = """\
This blueprint requests an execution environment. In addition to the common
task fields, return an environment object whose type exactly matches
task_plan.construction.environment_type. Populate only the tools, files,
runtime configuration, interaction contract, and execution metadata requested
by the payload. Follow task_builder_contract.metadata_protocols exactly. Keep
runner-private evaluator material out of visible task inputs.
"""


__all__ = ["EXECUTION_CAPABILITY_PROMPT", "TASK_BUILDER_PROMPT"]
