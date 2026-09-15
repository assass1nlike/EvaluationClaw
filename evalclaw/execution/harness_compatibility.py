"""Static compatibility checks for shell-based external agent harnesses."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def external_harness_issues(
    environment: Mapping[str, Any],
    harnesses: Iterable[str],
    *,
    has_workflow: bool = False,
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
    if has_workflow:
        issues.append("External shell harnesses do not implement multi-stage task workflows.")
    if environment.get("actors"):
        unsupported = [name for name in selected if name != "openclaw"]
        if unsupported:
            issues.append(
                "Environment actors require the OpenClaw harness; incompatible selected "
                "harnesses: " + ", ".join(unsupported) + "."
            )
    return issues
