"""Code and repository fallback agent tasks."""
from __future__ import annotations

from ...types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    EvalDimension,
    TaskBlueprint,
    TaskDefinition,
    TaskScoringSpec,
    TaskType,
)
from .base import _agent_system_prompt, _task_id, _task_title


def _code_repair_task_for_blueprint(
    dimension: EvalDimension,
    blueprint: TaskBlueprint,
    *,
    index: int = 1,
) -> TaskDefinition:
    variants = [
        {
            "prompt": (
                "Fix the bug in solution.py. The function normalize_scores(scores) should return values scaled "
                "to the range [0, 1], preserve input order, handle equal values by returning zeros, and run tests "
                "until the hidden tests pass."
            ),
            "visible": {
                "solution.py": (
                    "def normalize_scores(scores):\n"
                    "    low = min(scores)\n"
                    "    high = max(scores)\n"
                    "    return [(score - low) / high for score in scores]\n"
                )
            },
            "hidden": {
                "tests.py": (
                    "from solution import normalize_scores\n\n"
                    "assert normalize_scores([10, 20, 30]) == [0.0, 0.5, 1.0]\n"
                    "assert normalize_scores([5, 5, 5]) == [0.0, 0.0, 0.0]\n"
                    "assert normalize_scores([-2, 0, 2]) == [0.0, 0.5, 1.0]\n"
                )
            },
        },
        {
            "prompt": (
                "Fix the bug in solution.py. The function merge_counts(left, right) should return a new dict "
                "whose counts are the sum of both inputs without mutating either input. Run tests until they pass."
            ),
            "visible": {
                "solution.py": (
                    "def merge_counts(left, right):\n"
                    "    for key, value in right.items():\n"
                    "        left[key] = value\n"
                    "    return left\n"
                )
            },
            "hidden": {
                "tests.py": (
                    "from solution import merge_counts\n\n"
                    "left = {'a': 2, 'b': 1}\n"
                    "right = {'a': 3, 'c': 4}\n"
                    "result = merge_counts(left, right)\n"
                    "assert result == {'a': 5, 'b': 1, 'c': 4}\n"
                    "assert left == {'a': 2, 'b': 1}\n"
                    "assert right == {'a': 3, 'c': 4}\n"
                )
            },
        },
        {
            "prompt": (
                "Fix the bug in solution.py. The function first_unique(values) should return the first value "
                "that appears exactly once, or None if no value is unique. Run tests until hidden tests pass."
            ),
            "visible": {
                "solution.py": (
                    "def first_unique(values):\n"
                    "    seen = set()\n"
                    "    for value in values:\n"
                    "        if value not in seen:\n"
                    "            return value\n"
                    "        seen.add(value)\n"
                    "    return None\n"
                )
            },
            "hidden": {
                "tests.py": (
                    "from solution import first_unique\n\n"
                    "assert first_unique(['a', 'b', 'a', 'c']) == 'b'\n"
                    "assert first_unique([1, 1, 2, 2]) is None\n"
                    "assert first_unique([]) is None\n"
                )
            },
        },
    ]
    variant = variants[(index - 1) % len(variants)]
    return TaskDefinition(
        id=_task_id(dimension, blueprint, index),
        dimension_id=dimension.id,
        task_type=TaskType.agent_interaction,
        title=_task_title(blueprint, index),
        description="A compact repository repair task with hidden deterministic tests.",
        prompt=str(variant["prompt"]),
        system_prompt=_agent_system_prompt("code_sandbox"),
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.code_sandbox,
            visible_files=variant["visible"],
            hidden_files=variant["hidden"],
            test_command="python3 tests.py",
            max_steps=8,
            timeout=10,
        ),
        interaction={
            "max_turns": 8,
            "stop_condition": "Stop when hidden tests pass or the code_sandbox step limit is reached.",
        },
        scoring=TaskScoringSpec(
            method="deterministic",
            instructions=(
                "Use deterministic hidden-test scoring: full credit when hidden tests pass, partial credit "
                "after a meaningful failing test run, and no credit if the agent never runs tests."
            ),
            pass_criteria="The hidden tests pass after the agent edits the visible source.",
            partial_criteria="The agent inspects files and runs tests but the final implementation still fails.",
            fail_criteria="The agent does not make meaningful code changes or never runs tests.",
        ),
        challenge_effort=dimension.challenge_effort,
        tags=[dimension.id, "code_sandbox", "hidden_tests"],
    )


def _repo_issue_task_for_blueprint(
    dimension: EvalDimension,
    blueprint: TaskBlueprint,
    *,
    index: int = 1,
) -> TaskDefinition:
    visible = {
        "README.md": (
            "# Ticket Parser\n\n"
            "The library parses compact support tickets of the form `KEY=value;KEY=value`.\n"
            "Whitespace around keys and values should be ignored. Empty segments should be ignored.\n"
        ),
        "issue.md": (
            "Users report that tickets copied from spreadsheets fail when spaces appear around separators. "
            "Example: `id = 42; priority = high ; owner = Mei` should parse into clean keys and values."
        ),
        "ticket_parser.py": (
            "def parse_ticket(text):\n"
            "    fields = {}\n"
            "    for segment in text.split(';'):\n"
            "        key, value = segment.split('=')\n"
            "        fields[key] = value\n"
            "    return fields\n"
        ),
    }
    hidden = {
        "tests.py": (
            "from ticket_parser import parse_ticket\n\n"
            "assert parse_ticket('id = 42; priority = high ; owner = Mei') == {\n"
            "    'id': '42', 'priority': 'high', 'owner': 'Mei'\n"
            "}\n"
            "assert parse_ticket('id=7;;owner=Kai') == {'id': '7', 'owner': 'Kai'}\n"
            "assert parse_ticket('bad-segment; id=9') == {'id': '9'}\n"
        )
    }
    return TaskDefinition(
        id=_task_id(dimension, blueprint, index),
        dimension_id=dimension.id,
        task_type=TaskType.agent_interaction,
        title=_task_title(blueprint, index),
        description=(
            "A GitHub-style issue resolution task. The target must read issue context, inspect the small "
            "repository, implement the fix, and validate it with hidden tests."
        ),
        prompt=(
            "Resolve the bug described in issue.md. Inspect README.md and ticket_parser.py, update the "
            "implementation without changing hidden tests, and run tests until they pass."
        ),
        system_prompt=_agent_system_prompt("code_sandbox"),
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.code_sandbox,
            visible_files=visible,
            hidden_files=hidden,
            test_command="python3 tests.py",
            max_steps=9,
            timeout=10,
        ),
        interaction={
            "max_turns": 9,
            "stop_condition": "Stop when the issue is resolved and hidden tests pass.",
        },
        scoring=TaskScoringSpec(
            method="deterministic",
            instructions="Score by hidden tests that encode the issue's acceptance criteria.",
            pass_criteria="The parser handles whitespace, empty segments, and malformed segments as specified.",
            partial_criteria="The agent makes a plausible fix but misses one edge case.",
            fail_criteria="The repository remains broken or the agent does not run tests.",
        ),
        challenge_effort=dimension.challenge_effort,
        tags=[dimension.id, "repo_issue", "code_sandbox"],
    )
