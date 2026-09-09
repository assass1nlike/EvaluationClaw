"""TaskBuilder prompts scoped to one Planner-authored TaskDesign."""
from __future__ import annotations

import copy
import json

from ..types import TaskType

_COMMON_FIELDS = {
    "task_type": "",
    "title": "",
    "content_summary": "",
    "description": "",
    "prompt": "",
    "assets": [],
    "challenge_effort": "E3",
    "tags": [],
    "metadata": {
        "challenge_effort_self_assessment": {
            "requested_effort": "E3",
            "meets_requested_effort": True,
            "rationale": "",
        }
    },
}

_TYPE_FIELDS = {
    TaskType.choice: {"choices": [{"text": ""}, {"text": ""}], "correct_choice_indices": [0]},
    TaskType.fill_blank: {"expected_text": ""},
    TaskType.generation: {"rubric": "", "judge_tools": [], "output_contract": {}, "scoring": {}},
    TaskType.multi_turn: {
        "system_prompt": "",
        "interaction": {"max_turns": 3, "user_turns": [""]},
        "rubric": "",
        "judge_tools": [],
        "scoring": {},
    },
    TaskType.agent: {
        "system_prompt": "",
        "interaction": {},
        "environment": {},
        "workflow": None,
        "output_contract": {},
        "rubric": "",
        "judge_tools": [],
        "scoring": {},
    },
}

_TYPE_RULES = {
    TaskType.choice: (
        "Provide at least two choices and a non-empty zero-based correct_choice_indices list. "
        "The framework assigns choice ids. Put all options in choices and do not repeat them in prompt."
    ),
    TaskType.fill_blank: (
        "Provide exactly one expected_text string and state the response format in prompt. "
        "Scoring is exact apart from surrounding whitespace."
    ),
    TaskType.generation: (
        "Provide concrete scoring guidance. Use judge_tools or output_contract only when required by "
        "the TaskDesign, and do not repeat the same scoring rule in multiple fields."
    ),
    TaskType.multi_turn: (
        "Provide interaction.max_turns from 1 to 5 and exactly one of interaction.user_turns or "
        "interaction.followup_instruction. prompt is the first content sent to the target; "
        "system_prompt is only the adaptive dialogue simulator prompt. Provide transcript scoring."
    ),
    TaskType.agent: (
        "Provide an executable environment, output contract, and deterministic checks or task-specific "
        "scoring. Use workflow only for ordered multi-stage tasks."
    ),
}


def task_builder_fields(task_type: TaskType, *, source_backed: bool = False) -> frozenset[str]:
    """Return fields that one concrete Builder task may contain."""
    fields = {*_COMMON_FIELDS, *_TYPE_FIELDS[TaskType(task_type)]}
    if source_backed:
        fields.add("resource_ids")
    return frozenset(fields)


def task_builder_document_template(
    task_type: TaskType,
    *,
    task_count: int,
    challenge_effort: str,
    source_backed: bool,
) -> dict[str, object]:
    """Create the working JSON document edited during one Builder job."""
    task_type = TaskType(task_type)
    task = copy.deepcopy({**_COMMON_FIELDS, **_TYPE_FIELDS[task_type]})
    task["task_type"] = task_type.value
    task["challenge_effort"] = challenge_effort
    task["metadata"]["challenge_effort_self_assessment"][
        "requested_effort"
    ] = challenge_effort
    if source_backed:
        task["resource_ids"] = []
    return {
        "construction_notes": "",
        "resources": [],
        "tasks": [copy.deepcopy(task) for _ in range(task_count)],
    }


def project_task_builder_task(
    task: dict[str, object],
    task_type: TaskType,
    *,
    source_backed: bool,
    preserve_identity: bool = False,
) -> dict[str, object]:
    """Project a task document onto the fields visible to its Builder job."""
    task_type = TaskType(task_type)
    allowed = task_builder_fields(task_type, source_backed=source_backed)
    projected = {key: value for key, value in task.items() if key in allowed}
    metadata = task.get("metadata")
    if isinstance(metadata, dict):
        projected["metadata"] = {
            key: metadata[key]
            for key in ("challenge_effort_self_assessment", "task_model_id")
            if key in metadata
        }
    if task_type == TaskType.choice and isinstance(task.get("choices"), list):
        choices = [choice for choice in task["choices"] if isinstance(choice, dict)]
        correct_ids = {
            str(value) for value in task.get("correct_choice_ids", [])
        } if isinstance(task.get("correct_choice_ids"), list) else set()
        projected["choices"] = [
            {"text": str(choice.get("text") or "")} for choice in choices
        ]
        if correct_ids:
            projected["correct_choice_indices"] = [
                index
                for index, choice in enumerate(choices)
                if str(choice.get("id") or "") in correct_ids
            ]
    if preserve_identity:
        for key in ("id", "dimension_id"):
            if key in task:
                projected[key] = task[key]
    return projected


def project_task_builder_document(
    document: dict[str, object],
    task_type: TaskType,
    *,
    source_backed: bool,
    preserve_identity: bool = False,
) -> dict[str, object]:
    """Project every task in a Builder or repair document onto its task schema."""
    tasks = document.get("tasks")
    if not isinstance(tasks, list):
        return document
    return {
        **document,
        "tasks": [
            project_task_builder_task(
                task,
                task_type,
                source_backed=source_backed,
                preserve_identity=preserve_identity,
            )
            for task in tasks
            if isinstance(task, dict)
        ],
    }


def build_task_builder_prompt(
    task_type: TaskType,
    *,
    source_strategy: str = "generated",
    requires_environment: bool = False,
) -> str:
    """Build a system prompt containing only fields relevant to one task type."""
    task_type = TaskType(task_type)
    source_backed = source_strategy in {"adapted", "reused", "imported_dataset"}
    example = json.dumps(
        task_builder_document_template(
            task_type,
            task_count=1,
            challenge_effort="E3",
            source_backed=source_backed,
        ),
        ensure_ascii=False,
        indent=2,
    )
    source_rule = {
        "generated": "Construct from the TaskDesign, return an empty resources array, and omit resource_ids.",
        "adapted": (
            "Inspect supplied sources, make content-level changes, and bind every task with the exact "
            "resource_ids it uses. Use ids from resources.available or resource_1, resource_2, and so on."
        ),
        "reused": (
            "Inspect and reuse supplied material without content-level changes, and bind every task with "
            "the exact resource_ids it uses. Use ids from resources.available or resource_1, resource_2, and so on."
        ),
        "imported_dataset": (
            "Use supplied dataset items without content-level changes, and bind every task with the exact "
            "resource_ids it uses. Use ids from resources.available or resource_1, resource_2, and so on."
        ),
    }.get(source_strategy, "Follow task_plan.task_design.source_plan exactly.")
    asset_rule = (
        "\nEach assets entry has exactly one path field naming a real file in the Builder directory. "
        "For non-agent tasks, use assets only for images and refer to them as Image 1, Image 2, and "
        "so on. For agent tasks, refer to an asset by the filename visible in its runtime. Never put "
        "a host path in target-visible text."
    )
    scoring_rule = (
        "\nscoring, when present, is an object with method, instructions, pass_criteria, "
        "partial_criteria, fail_criteria, allows_partial_credit, and score_levels."
        if "scoring" in task_builder_fields(task_type)
        else ""
    )
    environment_rule = ""
    if requires_environment:
        environment_rule = (
            "\nEnvironment file maps contain literal contents under guest-relative paths. Keep "
            "target-visible files, runtime support, and evaluator-only material separate. For a "
            "docker workspace, use an absolute POSIX workdir such as /workspace. Preserve verified "
            "image-build or VM-image results in the corresponding environment fields. For agent tasks, "
            "put public initial scenario or state in the target-visible environment fields; keep setup "
            "and evaluator material private."
        )
    scoring_guidance = (
        "\nWhen scoring is present, set allows_partial_credit only for a real middle band and describe "
        "that band in partial_criteria. If score_levels is empty while partial credit is enabled, the "
        "framework supplies fail/partial/pass levels."
        if "scoring" in task_builder_fields(task_type)
        else ""
    )
    model_guidance = (
        "\nIf available_models.models is non-empty and this task uses an LLM judge or adaptive dialogue, "
        "select exactly one listed model and record its id in metadata.task_model_id."
    )
    count_guidance = (
        "\nReturn exactly the task count and type counts required by task_builder_contract. A design with "
        "task_count greater than one requires distinct concrete tasks. The framework injects task and "
        "design ids after parsing."
    )
    provenance_guidance = (
        "\nFor source-grounded tasks, a title or URL is only a lead: inspect the supplied material or use "
        "the available source tools before claiming that a task is grounded in it. If the material cannot "
        "be verified, state that limitation in construction_notes."
        if source_backed
        else ""
    )
    return f"""You are the EvaluationClaw Task Builder.

Implement the single Planner-authored TaskDesign in task_plan. Treat the TaskDesign, resources, and
task_builder_contract as authoritative. Materialize every input, asset, runtime dependency, and
piece of scoring evidence needed by the target and evaluator; do not merely describe a dependency.

During initial construction, task_file.path points to a JSON working document with this task shape:
{example}

Use read_candidate and update_candidate to inspect and edit that file throughout construction. As soon
as a part of a task is settled, merge its fields into the file instead of retaining the result only
in reasoning or waiting to reproduce the whole task in the final message. Keep the document valid
JSON after each merge when practical. Complete every required task before finishing, omit optional
empty fields, and do not add fields from another task type or invent aliases.

The framework owns task, dimension, TaskDesign, resource, and choice-option ids; do not emit them.
Put all target-visible instructions in prompt. description is reporting metadata, while
content_summary is a short report label. Store only required construction metadata such as the effort
self-assessment and selected task model. Use English unless the evaluation explicitly tests another
language.{count_guidance}

{source_rule}
{_TYPE_RULES[task_type]}{asset_rule}{scoring_rule}{scoring_guidance}{model_guidance}{environment_rule}
{provenance_guidance}

For repair requests with revision.path, use the same file-editing process on that document. Repair
only the listed tasks, preserve their order and ids, and fix every listed issue. For both initial
construction and repair, return only a compact confirmation after the file is complete."""


# Compatibility value for callers that imported the former module-level prompt.
# Construction uses the scoped builder above for every real job.
TASK_BUILDER_PROMPT = build_task_builder_prompt(TaskType.generation)


def build_task_builder_tool_prompt(
    task_type: TaskType,
    *,
    source_backed: bool,
    include_image_tools: bool = False,
    include_vm_image_tools: bool = False,
) -> str:
    """Build tool guidance without mentioning unrelated task protocols."""
    task_type = TaskType(task_type)
    parts = [
        "Use supplied tools only when they materially improve construction. run_python operates in "
        "the fixed Builder directory; save files needed by the task there.",
    ]
    if task_type == TaskType.agent:
        parts.append(
            "Put existing host input files in assets; the runner copies them into the environment. "
            "Refer only to runtime-visible filenames. File-map values are literal contents, not paths."
        )
    else:
        parts.append(
            "Non-agent assets may contain images only. Refer to them as Image 1, Image 2, and so on; "
            "never expose host paths."
        )
        parts.append(
            "Use view_image to inspect a generated or downloaded image before using it as a task asset. "
            "When generate_image is available, save the PNG inside the Builder directory and verify its "
            "visible content."
        )
    if source_backed:
        parts.append(
            "Use read_research_source, search_web, fetch_url, or download_files to inspect source "
            "material. Do not claim source grounding from a title or URL alone."
        )
    if include_image_tools:
        parts.append(
            "For a custom Docker environment, create or edit its Dockerfile and context with run_python, "
            "build the declared image, run a short image check, and preserve the returned relative context "
            "directory and image tag in environment.image_build."
        )
    if include_vm_image_tools:
        parts.append(
            "Use build_vm_image when required GUI software or state is absent from the base image, "
            "then preserve the returned image id in environment.vm.image."
        )
    parts.append(
        "When task_file.path or revision.path is supplied, progressively merge your finished parts into "
        "that JSON file with read_candidate / update_candidate and return only a compact confirmation after it is complete. "
        "Otherwise return the complete task-builder JSON after tool use."
    )
    return "\n\n".join(parts)


TASK_BUILDER_TRUNCATION_SUMMARY_PROMPT = """\
Compress interrupted TaskBuilder output into a continuation summary. Preserve task-design decisions,
completed work and artifact paths, unresolved problems, and next actions. Use only supplied content.
Do not continue the task or emit final task JSON; return only the summary text.
"""


__all__ = [
    "TASK_BUILDER_PROMPT",
    "TASK_BUILDER_TRUNCATION_SUMMARY_PROMPT",
    "build_task_builder_prompt",
    "build_task_builder_tool_prompt",
    "project_task_builder_document",
    "project_task_builder_task",
    "task_builder_fields",
    "task_builder_document_template",
]
