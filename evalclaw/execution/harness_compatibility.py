"""Static compatibility checks for shell-based external agent harnesses."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def external_harness_issues(
    environment: Mapping[str, Any],
    harnesses: Iterable[str],
    *,
    has_workflow: bool = False,
    workflow: Any = None,
) -> list[str]:
    selected = sorted({str(name).strip() for name in harnesses if str(name).strip()})
    if not selected:
        return []

    issues: list[str] = []
    # A python-mode dump of the environment model yields the enum member rather than
    # its value, and str() of a str-mixin enum member is "Class.member" on Python 3.11+.
    # Normalize enum-like values so the type check compares the canonical string.
    raw_type = environment.get("type")
    env_type = raw_type.value if hasattr(raw_type, "value") else raw_type
    if str(env_type or "") != "docker_workspace":
        issues.append("External shell harnesses currently require a docker_workspace environment.")
    browser = environment.get("browser")
    browser = browser if isinstance(browser, Mapping) else {}
    if (
        environment.get("workspace_tools")
        or browser.get("workspace_tools")
        or browser.get("allow_workspace_tools")
        or browser.get("enabled")
    ):
        issues.append(
            "External shell harnesses cannot enforce workspace_tools or the native browser "
            "tool contract."
        )
    if environment.get("runtime_files"):
        issues.append(
            "External shell harnesses cannot safely hide runtime_files from the target. Put "
            "setup-only support in image_build, target-visible state in visible_files, or use "
            "only native targets."
        )
    if str(environment.get("workdir") or "/workspace") != "/workspace":
        issues.append("External shell harnesses require environment.workdir=/workspace.")
    if workflow is not None:
        issues.extend(external_workflow_issues(workflow, selected))
    elif has_workflow:
        issues.append("External shell harnesses do not implement multi-stage task workflows.")
    return issues


def external_workflow_issues(workflow: Any, harnesses: Iterable[str]) -> list[str]:
    from ..runners.harness import get_harness

    issues = []
    stages = workflow.stages
    if workflow.metrics:
        issues.append("External workflows currently expose only the final score; derived workflow metrics are unsupported.")
    if any(s.kind == "agent" and (s.test_command or s.evaluation) for s in stages):
        issues.append("External workflow evaluator overrides belong only on the final evaluate stage.")
    if stages[-1].inputs or stages[-1].prompt or stages[-1].system_prompt:
        issues.append("The final external evaluate stage uses execution evidence and the scorer, not prompts or stage inputs.")
    if any(ref.field != "output" for stage in stages for ref in stage.inputs):
        issues.append("External workflow inputs currently support preceding stage output only.")
    if any(s.kind == "text" or s.files or s.output_files or s.environment_spec or s.resume_commands
           or s.allow_evaluation_feedback for s in stages):
        issues.append("External workflows support agent stages in one persistent environment and a final evaluation; text stages, file transfers, environment overrides and intermediate evaluator feedback are unsupported.")
    if stages[0].kind != "agent" or stages[0].environment != "fresh":
        issues.append("External workflow must begin with an agent stage in a fresh environment.")
    if any(s.environment != "reuse" for s in stages[1:]):
        issues.append("External workflow stages after the first must reuse the environment; context=fresh resets only conversation history.")
    if stages[-1].kind != "evaluate" or any(s.kind == "evaluate" for s in stages[:-1]):
        issues.append("External workflow must have exactly one final evaluate stage.")
    for name in harnesses:
        runner = get_harness(name)
        manifest = getattr(runner, "_manifest", None)
        template = (getattr(manifest, "session_run", "") or getattr(manifest, "run", ""))
        templates = " ".join([template, *getattr(manifest, "config_args", ())])
        for field, default in (("max_steps", 40), ("max_tokens", 32768)):
            if any(s.kind == "agent" and getattr(s, field) != default for s in stages) and "{" + field + "}" not in templates:
                issues.append(f"Harness {name} cannot enforce stage {field}; its command has no corresponding parameter.")
        if any(s.context == "continue" for s in stages if s.kind == "agent"):
            if not getattr(manifest, "session_run", ""):
                issues.append(f"Harness {name} has no configured persistent-session command; it cannot continue conversation history.")
    return issues
