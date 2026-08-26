"""Controlled environment probing and lightweight runtime decisions."""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..diagnostics import error_record, new_debug_dir, safe_name, write_json
from ..execution.lm_eval import _resolve_lm_eval_executable
from ..types import BenchmarkConfig, BenchmarkItem
from .agent_envs import build_agent_environment
from .desktop_agent_env import desktop_bridge_setup_message, probe_desktop_bridge
from .docker import docker_status
from .docker_images import (
    apply_docker_image_selection,
    docker_image_build_requested,
    inspect_docker_image,
)
from .installers import package_list
from .vm_materializer import (
    VmTaskMaterializationError,
    materialize_vm_task,
    vm_task_requires_vm,
)
from .vm_provider import probe_vm_provider, resolve_vm_image_spec, vm_provider_setup_message


@dataclass
class EnvironmentProbe:
    name: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnvironmentAction:
    action: str
    reason: str
    applied: bool = False
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnvironmentClawReport:
    enabled: bool
    probes: list[EnvironmentProbe] = field(default_factory=list)
    actions: list[EnvironmentAction] = field(default_factory=list)
    blocking_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "probes": [asdict(probe) for probe in self.probes],
            "actions": [asdict(action) for action in self.actions],
            "blocking_errors": list(self.blocking_errors),
        }


def _package_fields(config: dict[str, Any]) -> dict[str, list[str]]:
    aliases = {
        "system_packages": ("system_packages", "apt_packages", "packages"),
        "python_packages": ("python_packages", "pip_packages"),
        "node_packages": ("node_packages", "npm_packages"),
        "cran_packages": ("cran_packages", "r_packages"),
        "bioconductor_packages": ("bioconductor_packages", "bioc_packages"),
        "julia_packages": ("julia_packages",),
        "conda_packages": ("conda_packages",),
        "cargo_packages": ("cargo_packages",),
        "go_packages": ("go_packages",),
        "gem_packages": ("gem_packages", "ruby_gems"),
        "composer_packages": ("composer_packages",),
        "apk_packages": ("apk_packages",),
        "dnf_packages": ("dnf_packages",),
        "yum_packages": ("yum_packages",),
        "pacman_packages": ("pacman_packages",),
    }
    fields: dict[str, list[str]] = {}
    for canonical, keys in aliases.items():
        packages: list[str] = []
        for key in keys:
            packages.extend(package_list(config.get(key)))
        if packages:
            fields[canonical] = list(dict.fromkeys(packages))
    return fields


def _agent_env_type(item: BenchmarkItem) -> str:
    env = item.metadata.get("agent_env")
    if isinstance(env, dict):
        return str(env.get("type") or "").lower()
    return ""


def _has_docker_workspace(items: list[BenchmarkItem]) -> bool:
    return any(_agent_env_type(item) in {"code_sandbox", "docker_workspace"} for item in items)


def _has_gui_desktop(items: list[BenchmarkItem]) -> bool:
    return any(_agent_env_type(item) == "gui_desktop" for item in items)


def _first_gui_bridge_url(items: list[BenchmarkItem]) -> str | None:
    for item in items:
        env = item.metadata.get("agent_env")
        if isinstance(env, dict) and str(env.get("type") or "").lower() == "gui_desktop":
            value = env.get("bridge_url")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _agent_env(item: BenchmarkItem) -> dict[str, Any]:
    env = item.metadata.get("agent_env")
    if isinstance(env, dict):
        return env
    return {}


def _set_agent_env(item: BenchmarkItem, env: dict[str, Any]) -> None:
    item.metadata["agent_env"] = env


def _docker_task_text(item: BenchmarkItem) -> str:
    env = _agent_env(item)
    task_agent = item.metadata.get("task_agent") if isinstance(item.metadata.get("task_agent"), dict) else {}
    parts = [
        item.id,
        item.prompt,
        item.rubric or "",
        " ".join(item.tags),
        str(task_agent.get("system_prompt") or ""),
        str(task_agent.get("initial_content") or ""),
        str(env.get("test_command") or ""),
    ]
    for key in ("visible_files", "files", "hidden_files"):
        files = env.get(key)
        if isinstance(files, dict):
            parts.extend(str(path) for path in files.keys())
    return "\n".join(part for part in parts if part)


def _item_requires_vm(item: BenchmarkItem) -> bool:
    return vm_task_requires_vm(item)


def _has_vm_required(items: list[BenchmarkItem]) -> bool:
    return any(_item_requires_vm(item) for item in items)


def _has_gui_desktop_without_vm(items: list[BenchmarkItem]) -> bool:
    return any(_agent_env_type(item) == "gui_desktop" and not _item_requires_vm(item) for item in items)


def _first_vm_provider_url(items: list[BenchmarkItem]) -> str | None:
    for item in items:
        env = _agent_env(item)
        value = env.get("vm_provider_url")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _probe_docker(report: EnvironmentClawReport, config: BenchmarkConfig) -> None:
    status = docker_status(executable=config.docker_executable, timeout_s=15)
    report.probes.append(
        EnvironmentProbe(
            name="docker",
            ok=status.available,
            detail=status.error or "Docker CLI and daemon are reachable.",
            data={
                "executable": status.executable,
                "client_version": status.client_version,
                "server_version": status.server_version,
            },
        )
    )


def _probe_docker_images(
    report: EnvironmentClawReport,
    items: list[BenchmarkItem],
    config: BenchmarkConfig,
) -> None:
    for item in items:
        env = _agent_env(item)
        if str(env.get("type") or "").lower() != "docker_workspace":
            continue
        selected_env, selection = apply_docker_image_selection(
            env,
            task_text=_docker_task_text(item),
            preserve_explicit=True,
        )
        if selected_env != env:
            _set_agent_env(item, selected_env)
        report.actions.append(
            EnvironmentAction(
                action=f"select docker image {selection.image}",
                reason=selection.reason,
                applied=not selection.explicit,
                data={
                    "item_id": item.id,
                    "image": selection.image,
                    "confidence": selection.confidence,
                    "explicit": selection.explicit,
                    "evidence": selection.evidence,
                },
            )
        )
        if docker_image_build_requested(selected_env):
            build_config = selected_env.get("image_build") if isinstance(selected_env.get("image_build"), dict) else {}
            report.actions.append(
                EnvironmentAction(
                    action=f"build docker image {build_config.get('tag') or 'evalclaw-task:<auto>'}",
                    reason=(
                        "Task requested a custom Docker image build. DockerWorkspaceAgentEnvironment will "
                        "generate or use the configured Dockerfile, build a local image, and run the task with it."
                    ),
                    applied=False,
                    data={
                        "item_id": item.id,
                        "base_image": build_config.get("base_image"),
                        "has_dockerfile": bool(build_config.get("dockerfile")),
                        "system_packages": build_config.get("system_packages") or build_config.get("apt_packages") or [],
                        "python_packages": build_config.get("python_packages") or build_config.get("pip_packages") or [],
                        "package_fields": _package_fields(build_config),
                        "install_step_count": len(build_config.get("install_steps") or []),
                    },
                )
            )
            continue
        probe = inspect_docker_image(
            selection.image,
            docker_executable=config.docker_executable,
            timeout_s=15,
        )
        report.probes.append(
            EnvironmentProbe(
                name="docker_image",
                ok=probe.local,
                detail=probe.detail or ("Image is available locally." if probe.local else "Image is not available locally."),
                data={"item_id": item.id, "image": probe.image, "local": probe.local},
            )
        )
        if not probe.local and bool(selected_env.get("pull_image", True)):
            report.actions.append(
                EnvironmentAction(
                    action=f"pull docker image {selection.image}",
                    reason="Image is not local; DockerWorkspaceAgentEnvironment will pull it when the task starts.",
                    applied=False,
                    data={"item_id": item.id, "image": selection.image},
                )
            )


def _materialize_vm_tasks(report: EnvironmentClawReport, items: list[BenchmarkItem]) -> None:
    for item in items:
        if not _item_requires_vm(item):
            continue
        try:
            result = materialize_vm_task(item)
        except VmTaskMaterializationError as exc:
            report.actions.append(
                EnvironmentAction(
                    action="materialize VM task content",
                    reason=str(exc),
                    applied=False,
                    data={"item_id": item.id},
                )
            )
            report.blocking_errors.append(str(exc))
            continue
        if result.applied:
            command_count = int(result.provisioning.get("command_count") or 0)
            materialization_detail = (
                f"including {command_count} task-specific provisioning command(s)"
                if command_count
                else "containing task files and metadata; initial state comes from the declared "
                "prebuilt VM source and remains guarded by baseline checks"
            )
            report.actions.append(
                EnvironmentAction(
                    action="materialize VM task content",
                    reason=(
                        f"Generated a task-specific NoCloud config-drive ISO using {result.strategy} "
                        f"{materialization_detail}."
                    ),
                    applied=True,
                    data=result.as_dict(),
                )
            )
        elif result.skipped_reason and result.skipped_reason not in {
            "item does not require a VM",
            "no VM guest files to materialize",
        }:
            report.actions.append(
                EnvironmentAction(
                    action="materialize VM task content",
                    reason=result.skipped_reason,
                    applied=False,
                    data=result.as_dict(),
                )
            )


def _resolve_vm_task_images(
    report: EnvironmentClawReport,
    items: list[BenchmarkItem],
    provider_status: object,
) -> None:
    data = getattr(provider_status, "data", {})
    data = data if isinstance(data, dict) else {}
    capabilities = data.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    if not bool(data.get("protocol_v2")):
        return
    for item in items:
        if not _item_requires_vm(item):
            continue
        env = copy.deepcopy(_agent_env(item))
        vm_spec = env.get("vm") if isinstance(env.get("vm"), dict) else {}
        try:
            resolved, selected = resolve_vm_image_spec(
                vm_spec,
                capabilities,
                capabilities_discovered=True,
            )
        except RuntimeError as exc:
            report.blocking_errors.append(f"Task {item.id} VM image resolution failed: {exc}")
            report.actions.append(
                EnvironmentAction(
                    action="resolve VM image",
                    reason=str(exc),
                    applied=False,
                    data={"item_id": item.id},
                )
            )
            continue
        env["vm"] = resolved
        _set_agent_env(item, env)
        if selected is not None:
            report.actions.append(
                EnvironmentAction(
                    action="resolve VM image",
                    reason=(
                        "Selected a provider image matching the task OS and required capabilities."
                    ),
                    applied=True,
                    data={
                        "item_id": item.id,
                        "image": selected,
                    },
                )
            )


def _probe_lm_eval(report: EnvironmentClawReport) -> None:
    executable = _resolve_lm_eval_executable()
    report.probes.append(
        EnvironmentProbe(
            name="lm_eval_executable",
            ok=bool(executable),
            detail=executable or "lm-eval-harness executable was not found.",
            data={"executable": executable},
        )
    )


def _preflight_executable_items(
    report: EnvironmentClawReport,
    items: list[BenchmarkItem],
    config: BenchmarkConfig,
    *,
    trace_dir: Path | None = None,
) -> None:
    for item in items:
        if _agent_env_type(item) not in {"code_sandbox", "docker_workspace"}:
            continue
        environment = None
        try:
            environment = build_agent_environment(item, config)
            preflight = getattr(environment, "preflight", None)
            if not callable(preflight):
                raise RuntimeError("Executable environment does not implement preflight().")
            outcome = preflight()
            report.probes.append(
                EnvironmentProbe(
                    name="task_preflight",
                    ok=True,
                    detail="Container setup and evaluator invocation completed.",
                    data={
                        "item_id": item.id,
                        "environment": _agent_env_type(item),
                        "baseline_score": outcome.score,
                        "evaluator_source": outcome.source,
                        "structured_score": outcome.structured,
                    },
                )
            )
        except Exception as exc:
            detail = f"Task {item.id} failed executable preflight: {exc}"
            report.probes.append(
                EnvironmentProbe(
                    name="task_preflight",
                    ok=False,
                    detail=str(exc),
                    data={"item_id": item.id, "environment": _agent_env_type(item)},
                )
            )
            report.blocking_errors.append(detail)
        finally:
            if trace_dir is not None and environment is not None:
                item_dir = trace_dir / safe_name(item.id)
                try:
                    write_json(item_dir / "state.json", environment.state())
                    export = getattr(environment, "export_artifacts", None)
                    if callable(export):
                        write_json(item_dir / "artifacts.json", export(item_dir))
                except Exception as exc:
                    write_json(item_dir / "artifact-error.json", error_record(exc))
            cleanup = getattr(environment, "cleanup", None)
            if callable(cleanup):
                cleanup()
            if trace_dir is not None:
                write_json(trace_dir / "report.json", report.as_dict())


def run_environment_claw(
    items: list[BenchmarkItem],
    config: BenchmarkConfig,
) -> tuple[BenchmarkConfig, EnvironmentClawReport]:
    """Probe runtime requirements and make safe config decisions before execution."""
    trace_dir = new_debug_dir(config.output_dir, "environment")
    if not config.environment_claw:
        report = EnvironmentClawReport(enabled=False)
        if trace_dir is not None:
            write_json(trace_dir / "report.json", report.as_dict())
        return config, report

    report = EnvironmentClawReport(enabled=True)
    has_docker_workspace = _has_docker_workspace(items)
    has_vm_required = _has_vm_required(items)
    has_gui_desktop_without_vm = _has_gui_desktop_without_vm(items)

    if has_docker_workspace:
        _probe_docker(report, config)
    if has_docker_workspace:
        _probe_docker_images(report, items, config)
    if has_vm_required:
        _materialize_vm_tasks(report, items)

    if has_vm_required:
        provider_url = _first_vm_provider_url(items) or config.vm_provider_url or "local://auto"
        status = probe_vm_provider(
            provider_url,
            api_key=config.vm_provider_api_key,
            timeout=min(config.vm_provider_timeout_s, 30),
        )
        report.probes.append(
            EnvironmentProbe(
                name="vm_provider",
                ok=status.available,
                detail=status.detail or "VM provider is reachable.",
                data={"provider_url": status.provider_url, **status.data},
            )
        )
        if not status.available:
            report.blocking_errors.append(vm_provider_setup_message())
        else:
            _resolve_vm_task_images(report, items, status)

    if has_gui_desktop_without_vm:
        bridge_url = _first_gui_bridge_url(items) or config.gui_bridge_url
        status = probe_desktop_bridge(
            bridge_url,
            api_key=config.gui_bridge_api_key,
            timeout=config.gui_bridge_timeout_s,
        )
        report.probes.append(
            EnvironmentProbe(
                name="gui_desktop_bridge",
                ok=status.available,
                detail=status.detail or "GUI desktop bridge is reachable.",
                data={"bridge_url": status.bridge_url, **status.data},
            )
        )
        if not status.available:
            report.blocking_errors.append(desktop_bridge_setup_message())

    if config.runner in {"lm-eval", "auto"}:
        _probe_lm_eval(report)

    if config.environment_preflight and config.run_targets and has_docker_workspace:
        _preflight_executable_items(report, items, config, trace_dir=trace_dir)

    if trace_dir is not None:
        write_json(trace_dir / "report.json", report.as_dict())
    return config, report


def format_environment_claw_report(report: EnvironmentClawReport) -> list[str]:
    if not report.enabled:
        return ["[Environment Claw] Disabled."]
    lines = ["[Environment Claw] Probing runtime requirements..."]
    if not report.probes and not report.actions:
        lines.append("  No environment-sensitive runner requirements detected.")
    for probe in report.probes:
        status = "ok" if probe.ok else "missing"
        detail = f" - {probe.detail}" if probe.detail else ""
        lines.append(f"  probe {probe.name}: {status}{detail}")
    for action in report.actions:
        status = "applied" if action.applied else "suggested"
        lines.append(f"  action {status}: {action.action} ({action.reason})")
    for error in report.blocking_errors:
        lines.append(f"  blocking: {error}")
    return lines
