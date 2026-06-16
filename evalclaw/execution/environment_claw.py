"""Controlled environment probing and lightweight runtime decisions."""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

from ..execution.lm_eval import _resolve_lm_eval_executable
from ..types import BenchmarkConfig, BenchmarkItem
from .docker import docker_status
from .swebench import is_swebench_item


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


def _agent_env_type(item: BenchmarkItem) -> str:
    env = item.metadata.get("agent_env")
    if isinstance(env, dict):
        return str(env.get("type") or "").lower()
    task_agent = item.metadata.get("task_agent")
    if isinstance(task_agent, dict):
        execution = task_agent.get("execution")
        if isinstance(execution, dict):
            task_env = execution.get("agent_env")
            if isinstance(task_env, dict):
                return str(task_env.get("type") or execution.get("environment_type") or "").lower()
            return str(execution.get("environment_type") or "").lower()
    return ""


def _has_docker_workspace(items: list[BenchmarkItem]) -> bool:
    return any(_agent_env_type(item) == "docker_workspace" for item in items)


def _has_swebench(items: list[BenchmarkItem]) -> bool:
    return any(is_swebench_item(item) for item in items)


def _python_module_available(python_executable: str, module: str, timeout_s: int = 20) -> tuple[bool, str]:
    command = [python_executable, "-c", f"import {module}"]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s, check=False)
    except Exception as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()


def _wsl_available(timeout_s: int = 20) -> tuple[bool, str]:
    exe = shutil.which("wsl.exe") or shutil.which("wsl")
    if not exe:
        return False, "wsl.exe was not found."
    try:
        proc = subprocess.run([exe, "--status"], capture_output=True, text=True, timeout=timeout_s, check=False)
    except Exception as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, (proc.stdout or "").strip()
    detail = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
    return False, detail


def _wsl_python_module_available(
    python_executable: str,
    module: str,
    *,
    distro: str | None = None,
    timeout_s: int = 30,
) -> tuple[bool, str]:
    exe = shutil.which("wsl.exe") or shutil.which("wsl")
    if not exe:
        return False, "wsl.exe was not found."
    command = [exe]
    if distro:
        command.extend(["-d", distro])
    command.extend(["--", "bash", "-lc", f"{python_executable} -c 'import {module}'"])
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s, check=False)
    except Exception as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()


def _probe_docker(report: EnvironmentClawReport, config: BenchmarkConfig) -> None:
    status = docker_status(executable=config.swebench_docker_executable, timeout_s=15)
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


def run_environment_claw(
    items: list[BenchmarkItem],
    config: BenchmarkConfig,
) -> tuple[BenchmarkConfig, EnvironmentClawReport]:
    """Probe runtime requirements and make safe config decisions before execution."""
    if not config.environment_claw:
        return config, EnvironmentClawReport(enabled=False)

    report = EnvironmentClawReport(enabled=True)
    updated = config
    has_swebench = _has_swebench(items)
    has_docker_workspace = _has_docker_workspace(items)

    if has_swebench or has_docker_workspace:
        _probe_docker(report, config)

    if config.runner in {"lm-eval", "auto"}:
        _probe_lm_eval(report)

    if has_swebench:
        if config.swebench_use_wsl:
            ok, detail = _wsl_python_module_available(
                config.swebench_wsl_python_executable,
                "swebench.harness.run_evaluation",
                distro=config.swebench_wsl_distro,
            )
            report.probes.append(
                EnvironmentProbe(
                    name="swebench_wsl_harness",
                    ok=ok,
                    detail=detail or "SWE-bench harness import succeeded inside WSL.",
                    data={"python_executable": config.swebench_wsl_python_executable},
                )
            )
        else:
            ok, detail = _python_module_available(
                config.swebench_python_executable,
                "swebench.harness.run_evaluation",
            )
            report.probes.append(
                EnvironmentProbe(
                    name="swebench_native_harness",
                    ok=ok,
                    detail=detail or "SWE-bench harness import succeeded.",
                    data={"python_executable": config.swebench_python_executable},
                )
            )
            if not ok and platform.system().lower().startswith("win"):
                wsl_ok, wsl_detail = _wsl_available()
                report.probes.append(
                    EnvironmentProbe(
                        name="wsl",
                        ok=wsl_ok,
                        detail=wsl_detail or "WSL is available.",
                    )
                )
                if wsl_ok and config.environment_claw_auto_configure:
                    updated = updated.model_copy(update={"swebench_use_wsl": True})
                    report.actions.append(
                        EnvironmentAction(
                            action="set swebench_use_wsl=True",
                            reason=(
                                "Native SWE-bench harness is unavailable on Windows and WSL is available; "
                                "use the WSL preflight path before runner execution."
                            ),
                            applied=True,
                        )
                    )
                elif wsl_ok:
                    report.actions.append(
                        EnvironmentAction(
                            action="recommend swebench_use_wsl=True",
                            reason="Native SWE-bench harness is unavailable on Windows, but WSL is available.",
                            applied=False,
                        )
                    )

    return updated, report


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
