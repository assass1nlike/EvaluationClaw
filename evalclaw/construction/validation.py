"""Structural validation for tasks built by the general constructor."""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from ..protocols.agent_task_package import AGENT_TASK_PACKAGE_METADATA_KEY
from ..protocols.assets import asset_label, environment_asset_guest_path, is_image_asset_path
from ..types import (
    AgentEnvironmentType,
    EvalDimension,
    TaskBlueprint,
    TaskDefinition,
    TaskDesign,
    TaskType,
)

TASK_STRUCTURE_VALIDATION_VERSION = "evalclaw.task_structure.v1"
_COMPLETE_PROMPT_ENDINGS = (".", "!", "?", ")", "]", "}", '"', "'")
_DANGLING_PROMPT_ENDINGS = (
    " and",
    " or",
    " to",
    " with",
    " through",
    " across",
    " by",
    " for",
    " from",
    " into",
    " must",
    " must be",
    " must be carried",
    " should",
    " should be",
    " will",
    " will be",
)


def _has_text(value: object) -> bool:
    return bool(str(value or "").strip())


def _has_any_text(*values: object) -> bool:
    return any(_has_text(value) for value in values)


def _has_scoring_guidance(task: TaskDefinition) -> bool:
    return bool(
        _has_any_text(
            task.rubric,
            task.scoring.instructions,
            task.scoring.pass_criteria,
            task.scoring.partial_criteria,
            task.scoring.fail_criteria,
            task.scoring.instructions,
        )
        or task.scoring.score_levels
    )


def _has_environment_evaluator(task: TaskDefinition) -> bool:
    env = task.environment
    if env is None:
        return False
    if env.type == AgentEnvironmentType.docker_workspace:
        return _has_text(env.test_command)
    if env.type == AgentEnvironmentType.gui:
        evaluation = env.evaluation
        return bool(
            isinstance(evaluation.get("checks"), list)
            and evaluation["checks"]
        ) or _has_any_text(
            evaluation.get("method"),
            evaluation.get("evaluator"),
            evaluation.get("command"),
            evaluation.get("pass_criteria"),
            evaluation.get("fail_criteria"),
        )
    return False


def _environment_has_visible_file_input(task: TaskDefinition) -> bool:
    env = task.environment
    if env is None:
        return False
    if env.visible_files or (
        task.assets
        and env.type == AgentEnvironmentType.docker_workspace
    ):
        return True
    for key in ("files", "input_files", "asset_files", "assets"):
        value = env.session.get(key)
        if isinstance(value, (dict, list)) and bool(value):
            return True
    return False


def resolve_builder_asset_path(path: str | Path, builder_work_dir: Path | None = None) -> Path:
    """Resolve an asset path against the current Builder job when it is relative."""
    candidate = Path(str(path).strip()).expanduser()
    if builder_work_dir is None or candidate.is_absolute():
        return candidate.resolve()
    root = builder_work_dir.expanduser().resolve()
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(
            f"relative asset path must remain inside the Builder job directory: {path!r}"
        )
    return resolved


def _builder_host_path_issues(task: TaskDefinition, work_dir: Path) -> list[str]:
    resolved = work_dir.expanduser().resolve()
    spellings = tuple(
        dict.fromkeys(
            spelling.casefold()
            for spelling in (
                str(resolved),
                str(resolved).replace("\\", "\\\\"),
                resolved.as_posix(),
            )
            if spelling
        )
    )
    target_visible: dict[str, object] = {
        "prompt": task.prompt,
        "system_prompt": task.system_prompt,
        "interaction": task.interaction,
        "metadata": task.metadata,
    }
    if task.environment is not None and task.environment.type == AgentEnvironmentType.docker_workspace:
        target_visible.update(
            {
                "environment": task.environment.model_dump(mode="json"),
                "output_contract": task.output_contract,
                "scoring": task.scoring.model_dump(mode="json"),
                "rubric": task.rubric or "",
            }
        )
    serialized = json.dumps(target_visible, ensure_ascii=False, default=str).casefold()
    if not any(spelling in serialized for spelling in spellings):
        return []
    return [
        "Builder-host paths must not appear in environment-backed task fields. "
        "Environment visible_files, runtime_files, and hidden_files map guest-relative "
        "paths to literal file contents, not host paths or filenames. Read a construction "
        "file and place its contents in the appropriate map, or keep its host path only in "
        "top-level assets when it should be copied as task input; in either case, expose "
        "only the guest path in prompt or choices."
    ]


def _prompt_looks_truncated(prompt: str) -> bool:
    stripped = prompt.strip()
    if len(stripped) < 120 or stripped.endswith(_COMPLETE_PROMPT_ENDINGS):
        return False
    lower = stripped.lower()
    return lower.endswith(_DANGLING_PROMPT_ENDINGS)


def _declared_vm_guest_os(env: object) -> str:
    vm = getattr(env, "vm", {})
    materialization = getattr(env, "vm_materialization", {})
    candidates = []
    if isinstance(materialization, dict):
        candidates.extend((materialization.get("guest_os"), materialization.get("os")))
    if isinstance(vm, dict):
        candidates.extend((vm.get("guest_os"), vm.get("os"), vm.get("os_type"), vm.get("platform")))
    raw = next((str(value).strip().lower() for value in candidates if _has_text(value)), "")
    normalized = raw.replace("_", "-")
    if normalized == "win" or normalized.startswith("windows"):
        return "windows"
    if normalized.startswith("linux") or normalized in {
        "ubuntu",
        "debian",
        "fedora",
        "rhel",
        "centos",
        "alpine",
        "arch",
    }:
        return "linux"
    return raw


def _vm_provisioning_platform_issues(env: object) -> list[str]:
    provisioning = getattr(env, "vm_provisioning", {})
    if not isinstance(provisioning, dict) or not provisioning:
        return []
    guest_os = _declared_vm_guest_os(env)
    windows_fields = {
        "winget_packages",
        "choco_packages",
        "chocolatey_packages",
        "windows_features",
        "powershell_commands",
        "powershell_script",
        "interactive_powershell_commands",
        "restart_after_provisioning",
    }
    linux_fields = {
        "apt_packages",
        "apk_packages",
        "dnf_packages",
        "yum_packages",
        "pacman_packages",
        "snap_packages",
        "cran_packages",
        "r_packages",
        "bioconductor_packages",
        "bioc_packages",
        "julia_packages",
        "conda_packages",
        "cargo_packages",
        "go_packages",
        "gem_packages",
        "ruby_gems",
        "composer_packages",
    }
    used_windows = sorted(key for key in windows_fields if provisioning.get(key))
    used_linux = sorted(key for key in linux_fields if provisioning.get(key))
    raw_steps = (
        provisioning.get("install_steps")
        or provisioning.get("package_manager_steps")
        or provisioning.get("software_install_steps")
    )
    steps = [raw_steps] if isinstance(raw_steps, dict) else raw_steps
    step_managers = {
        str(step.get("manager") or step.get("type") or "").strip().lower().replace("_", "-")
        for step in steps or []
        if isinstance(step, dict)
    }
    linux_step_managers = step_managers & {
        "apt",
        "apt-get",
        "apk",
        "dnf",
        "yum",
        "pacman",
        "snap",
        "cran",
        "bioconductor",
        "julia",
        "conda",
        "cargo",
        "go",
        "gem",
        "composer",
    }
    windows_step_managers = step_managers & {
        "winget",
        "choco",
        "chocolatey",
        "windows-feature",
        "windows-features",
    }
    if guest_os and guest_os not in {"linux", "windows"}:
        return ["VM guest_os must be linux or windows for built-in task materialization."]
    if used_windows and not guest_os:
        return ["Windows VM provisioning fields require vm.guest_os=windows."]
    if guest_os == "windows" and used_linux:
        return [
            "Windows VM provisioning cannot use Linux-only package fields: "
            + ", ".join(used_linux)
            + ". Use winget/choco, Windows features, pip/npm, or PowerShell commands."
        ]
    if guest_os == "windows" and linux_step_managers:
        return [
            "Windows VM provisioning cannot use Linux-only install-step managers: "
            + ", ".join(sorted(linux_step_managers))
            + "."
        ]
    if guest_os == "linux" and used_windows:
        return [
            "Linux VM provisioning cannot use Windows-only fields: " + ", ".join(used_windows) + "."
        ]
    if guest_os == "linux" and windows_step_managers:
        return [
            "Linux VM provisioning cannot use Windows-only install-step managers: "
            + ", ".join(sorted(windows_step_managers))
            + "."
        ]
    return []


def _parse_powershell_syntax_errors(command: str) -> list[str]:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if not executable:
        return []
    encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
    parser_script = (
        f"$source=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}'));"
        "$tokens=$null;$errors=$null;"
        "[void][System.Management.Automation.Language.Parser]::ParseInput("
        "$source,[ref]$tokens,[ref]$errors);"
        "if($errors){$errors|ForEach-Object{$_.Message};exit 1}"
    )
    try:
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", "-"],
            input=parser_script,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 1:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _vm_powershell_syntax_issues(env: object) -> list[str]:
    if _declared_vm_guest_os(env) != "windows":
        return []
    provisioning = getattr(env, "vm_provisioning", {})
    if not isinstance(provisioning, dict):
        return []
    raw_commands = provisioning.get("powershell_commands")
    commands = list(raw_commands) if isinstance(raw_commands, list) else [raw_commands]
    script = provisioning.get("powershell_script")
    if _has_text(script):
        commands.append(script)
    interactive_commands = provisioning.get("interactive_powershell_commands")
    if isinstance(interactive_commands, list):
        commands.extend(interactive_commands)
    elif _has_text(interactive_commands):
        commands.append(interactive_commands)
    issues: list[str] = []
    for index, command in enumerate(commands, 1):
        if not _has_text(command):
            continue
        errors = _parse_powershell_syntax_errors(str(command))
        if errors:
            issues.append(
                f"environment.vm_provisioning PowerShell command {index} has invalid syntax: "
                + "; ".join(errors[:3])
            )
    return issues


def _vm_interactive_provisioning_issues(env: object) -> list[str]:
    if _declared_vm_guest_os(env) != "windows":
        return []
    provisioning = getattr(env, "vm_provisioning", {})
    if not isinstance(provisioning, dict):
        return []
    issues: list[str] = []
    interactive_raw = provisioning.get("interactive_powershell_commands")
    if interactive_raw and not provisioning.get("restart_after_provisioning"):
        issues.append(
            "environment.vm_provisioning.interactive_powershell_commands requires "
            "restart_after_provisioning=true so the commands run in the intended signed-in user session."
        )
    interactive = interactive_raw if isinstance(interactive_raw, list) else [interactive_raw]
    system_raw = provisioning.get("powershell_commands")
    system = system_raw if isinstance(system_raw, list) else [system_raw]
    if _has_text(provisioning.get("powershell_script")):
        system.append(provisioning.get("powershell_script"))
    duplicates = {
        str(command).strip()
        for command in interactive
        if _has_text(command)
    } & {
        str(command).strip()
        for command in system
        if _has_text(command)
    }
    if duplicates:
        issues.append(
            "The same PowerShell command cannot appear in both system powershell_commands/"
            "powershell_script and interactive_powershell_commands; assign it to exactly one "
            "execution identity."
        )
    return issues


def _powershell_command_tokens(command: str) -> tuple[set[str], set[str]]:
    """Return lowercase invoked command names and their argument tokens.

    Parsing the script means a name that only appears in a comment or in an
    unrelated string is not mistaken for an actual invocation.
    """
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if executable:
        encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
        parser_script = (
            f"$source=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}'));"
            "$tokens=$null;$errors=$null;"
            "$ast=[System.Management.Automation.Language.Parser]::ParseInput("
            "$source,[ref]$tokens,[ref]$errors);"
            "$nodes=$ast.FindAll({param($node)"
            "$node -is [System.Management.Automation.Language.CommandAst]},$true);"
            "foreach($node in $nodes){"
            "$name=$node.GetCommandName();"
            "if($name){Write-Output (\"CMD`t\"+$name.ToLowerInvariant())}"
            "foreach($element in $node.CommandElements){"
            "Write-Output (\"ARG`t\"+$element.Extent.Text.Trim(\"'\",'\"').ToLowerInvariant())}}"
        )
        try:
            result = subprocess.run(
                [executable, "-NoProfile", "-NonInteractive", "-Command", "-"],
                input=parser_script,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0:
            names: set[str] = set()
            arguments: set[str] = set()
            for line in result.stdout.splitlines():
                kind, _, value = line.strip().partition("\t")
                if value:
                    (names if kind == "CMD" else arguments).add(value.removesuffix(".exe"))
            return names, arguments
    text = re.sub(r"<#.*?#>", " ", command, flags=re.DOTALL)
    text = re.sub(r"#[^\n]*", " ", text)
    names = {
        match.group(1).lower().removesuffix(".exe")
        for match in re.finditer(r"(?:^|[;|&(){}\n])\s*([A-Za-z][A-Za-z0-9_.-]*)", text)
    }
    arguments = {
        next(group for group in match.groups() if group is not None).lower()
        for match in re.finditer(r"'([^']*)'|\"([^\"]*)\"|([A-Za-z][A-Za-z0-9_.-]*)", text)
    }
    return names, arguments


def _vm_windows_session_identity_issues(env: object) -> list[str]:
    if _declared_vm_guest_os(env) != "windows":
        return []
    vm = getattr(env, "vm", {})
    session = getattr(env, "session", {})
    provisioning = getattr(env, "vm_provisioning", {})
    if not all(isinstance(value, dict) for value in (vm, session, provisioning)):
        return []
    source_fields = (
        "template",
        "template_name",
        "image",
        "disk_image",
        "disk_path",
        "template_path",
    )
    if _has_any_text(*(vm.get(field) for field in source_fields)):
        return []
    checks = session.get("baseline_checks")
    if not isinstance(checks, list):
        return []
    asserted_users: set[str] = set()
    for check in checks:
        if not isinstance(check, dict):
            continue
        command = str(check.get("command") or "")
        asserted_users.update(
            match.group(1)
            for match in re.finditer(
                r"(?i)\$env:USERNAME\s+-i?(?:eq|ne)\s+['\"]([^'\"]+)['\"]",
                command,
            )
        )
        asserted_users.update(
            match.group(1)
            for match in re.finditer(
                r"(?i)-(?:not)?match\s+['\"][^'\"]*\\+([A-Za-z0-9_.-]+)\$['\"]",
                command,
            )
        )
    if not asserted_users:
        return []
    commands = "\n".join(
        str(command)
        for field in ("powershell_commands", "powershell_script")
        for command in (
            provisioning.get(field)
            if isinstance(provisioning.get(field), list)
            else [provisioning.get(field)]
        )
        if _has_text(command)
    )
    command_names, command_arguments = _powershell_command_tokens(commands)
    creates_local_user = "new-localuser" in command_names or (
        "net" in command_names and "user" in command_arguments
    )
    issues: list[str] = []
    names = ", ".join(sorted(asserted_users))
    if not creates_local_user:
        issues.append(
            "Windows capability-resolved VM baseline requires the signed-in user "
            f"{names}, but provisioning does not create a local user. Create the account "
            "explicitly; Scheduled Task principals and ACL entries do not create users."
        )
    has_logon_configuration = {"autoadminlogon", "defaultusername"} <= command_arguments
    if not provisioning.get("restart_after_provisioning") or not has_logon_configuration:
        issues.append(
            "Windows capability-resolved VM baseline asserts a named signed-in user, but "
            "provisioning must configure a concrete logon mechanism and set "
            "restart_after_provisioning=true before the bridge exposes that session."
        )
    return issues


def _vm_protected_evaluator_reference_issues(env: object) -> list[str]:
    if _declared_vm_guest_os(env) != "windows":
        return []
    provisioning = getattr(env, "vm_provisioning", {})
    evaluation = getattr(env, "evaluation", {})
    if not isinstance(provisioning, dict) or not isinstance(evaluation, dict):
        return []
    raw_commands = provisioning.get("powershell_commands")
    commands = list(raw_commands) if isinstance(raw_commands, list) else [raw_commands]
    script = provisioning.get("powershell_script")
    if _has_text(script):
        commands.append(script)
    provisioning_text = "\n".join(str(command) for command in commands if _has_text(command))
    assignments = {
        match.group(1).lower(): match.group(2)
        for match in re.finditer(
            r"(?im)^\s*\$([A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"]([A-Za-z]:\\[^'\"]+)['\"]",
            provisioning_text,
        )
    }
    protected_roots: set[str] = set()
    lines = provisioning_text.splitlines()
    for line in lines:
        if "icacls" not in line.lower() or "/inheritance:r" not in line.lower():
            continue
        variables = re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", line)
        roots = [assignments[name.lower()] for name in variables if name.lower() in assignments]
        roots.extend(re.findall(r"['\"]([A-Za-z]:\\[^'\"]+)['\"]", line))
        for root in roots:
            related = "\n".join(
                candidate
                for candidate in lines
                if root.lower() in candidate.lower()
                or any(f"${name}".lower() in candidate.lower() for name, value in assignments.items() if value == root)
            ).lower()
            target_can_read = any(
                marker in related
                for marker in ("everyone:", "authenticated users:", "users:", "*s-1-5-32-545")
            )
            if not target_can_read:
                protected_roots.add(root)
    if not protected_roots:
        return []
    checks = evaluation.get("checks")
    if not isinstance(checks, list):
        return []
    evaluation_text = "\n".join(
        str(check.get("command") or "")
        for check in checks
        if isinstance(check, dict)
    )
    inaccessible = sorted(root for root in protected_roots if root.lower() in evaluation_text.lower())
    if not inaccessible:
        return []
    return [
        "Windows gui evaluation runs as the signed-in target user and cannot read "
        "provisioning paths whose ACL grants only SYSTEM/Administrators: "
        + ", ".join(inaccessible)
        + ". Embed expected values or hashes in the evaluator command instead of reading a "
        "target-inaccessible oracle at runtime."
    ]


def _vm_powershell_check_issues(env: object) -> list[str]:
    if _declared_vm_guest_os(env) != "windows":
        return []
    groups = (
        ("environment.session.baseline_checks", getattr(env, "session", {}).get("baseline_checks")),
        ("environment.evaluation.checks", getattr(env, "evaluation", {}).get("checks")),
    )
    issues: list[str] = []
    for field_name, checks in groups:
        if not isinstance(checks, list):
            continue
        for index, check in enumerate(checks, 1):
            if not isinstance(check, dict) or str(check.get("method") or "").lower() != "command":
                continue
            command = str(check.get("command") or "").strip()
            if not command:
                continue
            if re.match(r"(?i)^\s*(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)\b.*\s-(?:command|c)\b", command):
                issues.append(
                    f"{field_name}[{index}].command must be the raw PowerShell script body; "
                    "do not wrap it in powershell.exe/pwsh -Command."
                )
                continue
            errors = _parse_powershell_syntax_errors(command)
            if errors:
                issues.append(
                    f"{field_name}[{index}].command has invalid PowerShell syntax: "
                    + "; ".join(errors[:3])
                )
    return issues


def _scheduled_task_parameter_sets(command: str) -> list[set[str]]:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if not executable:
        statements = re.split(r"[;\r\n]+", command)
        return [
            {name.lower() for name in re.findall(r"(?<!\w)-([A-Za-z][A-Za-z0-9]*)\b", statement)}
            for statement in statements
            if re.search(r"(?i)\bRegister-ScheduledTask\b", statement)
        ]
    encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
    parser_script = (
        f"$source=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}'));"
        "$tokens=$null;$errors=$null;"
        "$ast=[System.Management.Automation.Language.Parser]::ParseInput("
        "$source,[ref]$tokens,[ref]$errors);"
        "$nodes=$ast.FindAll({param($node)"
        "$node -is [System.Management.Automation.Language.CommandAst] -and "
        "$node.GetCommandName() -eq 'Register-ScheduledTask'},$true);"
        "foreach($node in $nodes){"
        "$parameters=@($node.CommandElements|Where-Object{"
        "$_ -is [System.Management.Automation.Language.CommandParameterAst]}|"
        "ForEach-Object{$_.ParameterName.ToLowerInvariant()});"
        "Write-Output ($parameters -join ',')}"
    )
    try:
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", "-"],
            input=parser_script,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [
        {name for name in line.strip().split(",") if name}
        for line in result.stdout.splitlines()
    ]


def _vm_powershell_contract_issues(env: object) -> list[str]:
    if _declared_vm_guest_os(env) != "windows":
        return []
    provisioning = getattr(env, "vm_provisioning", {})
    if not isinstance(provisioning, dict):
        return []
    raw_commands = provisioning.get("powershell_commands")
    commands = list(raw_commands) if isinstance(raw_commands, list) else [raw_commands]
    script = provisioning.get("powershell_script")
    if _has_text(script):
        commands.append(script)
    issues: list[str] = []
    for index, command in enumerate(commands, 1):
        text = str(command or "")
        if any(
            {"principal", "password"}.issubset(parameters)
            for parameters in _scheduled_task_parameter_sets(text)
        ):
            issues.append(
                f"environment.vm_provisioning PowerShell command {index} combines "
                "Register-ScheduledTask -Principal with -Password, which are different "
                "parameter sets. Use -User/-Password/-RunLevel or -Principal without -Password."
            )
    return issues


def _vm_source_looks_descriptive_or_placeholder(value: object) -> bool:
    text = str(value or "").strip()
    lowered = text.lower()
    if not text:
        return False
    if any(
        marker in lowered
        for marker in (
            "<",
            ">",
            "runner-resolvable",
            "placeholder",
            "replace me",
            "template identifier",
            "snapshot identifier",
            "disk identifier",
        )
    ):
        return True
    return len(text) > 120 and text.endswith((".", "!", "?"))


def _desktop_check_issues(checks: object, *, field_name: str) -> list[str]:
    if not isinstance(checks, list):
        return []
    issues: list[str] = []
    for index, check in enumerate(checks, 1):
        if not isinstance(check, dict):
            issues.append(f"{field_name}[{index}] must be an object.")
            continue
        method = str(check.get("method") or "").strip().lower()
        if method == "command":
            command = str(check.get("command") or "").strip()
            if not command:
                issues.append(
                    f"{field_name}[{index}] uses method=command but has no executable guest command."
                )
            elif re.fullmatch(r"[A-Z][A-Z0-9_]{2,}:[A-Za-z0-9_.:/-]+", command):
                issues.append(
                    f"{field_name}[{index}].command must contain the complete executable guest "
                    "command; opaque runner-private command identifiers are not part of the "
                    "gui bridge contract."
                )
            elif field_name == "environment.evaluation.checks" and _command_is_probe_only(
                command,
                check,
            ):
                issues.append(
                    f"{field_name}[{index}].command only collects output and succeeds "
                    "unconditionally. A command check must directly return success or failure for "
                    "the state being scored; ordinary task metadata cannot supply a separate "
                    "runtime evaluator."
                )
        elif method == "file_exists" and not _has_text(check.get("path")):
            issues.append(f"{field_name}[{index}] uses {method} but has no path.")
        elif method not in {"command", "file_exists"}:
            issues.append(
                f"{field_name}[{index}] uses unsupported method {method or '<empty>'}; "
                "the gui bridge supports command and file_exists."
            )
    return issues


def _command_is_probe_only(command: str, check: dict[str, object]) -> bool:
    comparison_fields = {
        "expected_output",
        "expected_stdout",
        "stdout_contains",
        "output_regex",
        "expected_value",
        "json_path",
    }
    if any(_has_text(check.get(field)) for field in comparison_fields):
        return False
    normalized = re.sub(r"\s+", " ", command.strip().lower())
    unconditional_success = bool(
        re.search(r"(?:^|[;}&|]\s*)exit\s+(?:0|'0'|\"0\")\s*[\"']?\s*$", normalized)
    )
    explicit_failure = bool(
        re.search(r"\bexit\s+(?!0(?:\D|$))\d+\b", normalized)
        or re.search(r"\b(?:throw|assert)\b", normalized)
    )
    return unconditional_success and not explicit_failure


def _metadata_runtime_evaluator_issues(metadata: dict[str, object]) -> list[str]:
    issues: list[str] = []
    executable_markers = re.compile(
        r"runner[-_ ]private|host[-_ ]side|private evaluator|runner_private://|"
        r"\bentrypoint\b|\bexecutable\b",
        re.IGNORECASE,
    )
    for key, value in metadata.items():
        normalized_key = str(key).strip().lower().replace("-", "_")
        if not any(term in normalized_key for term in ("evaluator", "evaluation", "validation")):
            continue
        if executable_markers.search(f"{key} {value}"):
            issues.append(
                f"Task metadata.{key} declares a runtime evaluator, but ordinary task metadata "
                "is not executable. Put the complete evaluator in the canonical environment "
                "evaluation fields supported by the selected runtime."
            )
    return issues


def task_structure_issues(
    task: TaskDefinition,
    *,
    dimension: EvalDimension | None = None,
    blueprint: TaskBlueprint | None = None,
    task_design: TaskDesign | None = None,
    require_challenge_effort_self_assessment: bool = False,
    builder_work_dir: Path | None = None,
) -> list[str]:
    """Return blocking structural issues that should be fixed before global QC.

    This is intentionally narrower than content QC. It checks whether the task
    has the fields needed for its task type and optional execution capabilities.
    """
    issues: list[str] = []
    if not _has_text(task.id):
        issues.append("Task id is empty.")
    issues.extend(_metadata_runtime_evaluator_issues(task.metadata))
    if not _has_text(task.title):
        issues.append("Task title is empty.")
    if not _has_text(task.prompt):
        issues.append("Task prompt is empty.")
    elif _prompt_looks_truncated(task.prompt):
        issues.append("Task prompt appears truncated or ends with an incomplete instruction.")
    if dimension is not None and task.dimension_id != dimension.id:
        issues.append(f"Task dimension_id must be {dimension.id}.")
    if task_design is not None:
        modalities = task_design.input_requirements.get("modalities")
        asset_requirements = task_design.input_requirements.get("asset_requirements")
        requires_assets = bool(asset_requirements) or (
            isinstance(modalities, list)
            and any(str(modality).strip().lower() != "text" for modality in modalities)
        )
        if requires_assets:
            if task.environment is not None:
                if not _environment_has_visible_file_input(task):
                    issues.append(
                        "TaskDesign requires file inputs, so the environment must provide "
                        "target-visible guest files."
                    )
            elif not task.assets:
                issues.append("TaskDesign requires file inputs, so the task must provide assets.")
    if task.task_type != TaskType.agent:
        non_image_assets = [
            asset.path
            for asset in task.assets
            if asset.path.strip() and not is_image_asset_path(asset.path)
        ]
        if non_image_assets:
            issues.append(
                "Non-agent tasks may use only image assets; convey other task information "
                "in text or use task_type='agent' for a required non-image file: "
                + ", ".join(non_image_assets)
            )
    for index, asset in enumerate(task.assets, 1):
        path = asset.path.strip()
        if not path:
            issues.append(f"Asset #{index} path is empty.")
            continue
        prompt_reference = (
            environment_asset_guest_path(asset)
            if task.task_type == TaskType.agent
            else asset_label(index)
        )
        if prompt_reference not in task.prompt and not any(
            prompt_reference in choice.text for choice in task.choices
        ):
            issues.append(
                f"Task prompt or choices must reference asset {prompt_reference!r}."
            )
        try:
            resolved_path = resolve_builder_asset_path(path, builder_work_dir)
        except ValueError as exc:
            issues.append(f"Invalid asset path {path!r}: {exc}")
            continue
        if not resolved_path.is_file():
            issues.append(f"Asset path does not exist or is not a file: {path!r}.")
    if (
        task.environment is not None
        and task.assets
        and task.environment.type != AgentEnvironmentType.docker_workspace
    ):
        issues.append(
            "This environment does not map top-level assets; put input files in its "
            "target-visible environment fields."
        )
    if task.environment is not None and task.environment.type == AgentEnvironmentType.docker_workspace:
        guest_names = [environment_asset_guest_path(asset) for asset in task.assets]
        duplicate_guest_names = sorted(
            name for name in set(guest_names) if guest_names.count(name) > 1
        )
        if duplicate_guest_names:
            issues.append(
                "Environment asset filenames must be unique: "
                + ", ".join(duplicate_guest_names)
            )
    if builder_work_dir is not None and task.environment is not None:
        issues.extend(_builder_host_path_issues(task, builder_work_dir))
    expected_effort = (
        task_design.challenge_effort
        if task_design is not None
        else (dimension.challenge_effort if dimension is not None else None)
    )
    if expected_effort is not None and task.challenge_effort != expected_effort:
        issues.append(
            f"Task challenge_effort must be {expected_effort.value}; "
            f"got {task.challenge_effort.value}."
        )
    if require_challenge_effort_self_assessment:
        assessment = task.metadata.get("challenge_effort_self_assessment")
        if not isinstance(assessment, dict):
            issues.append(
                "Task metadata.challenge_effort_self_assessment is required for LLM-built tasks."
            )
        else:
            requested = str(assessment.get("requested_effort") or "").strip()
            if expected_effort is not None and requested and requested != expected_effort.value:
                issues.append(
                    "Task metadata.challenge_effort_self_assessment.requested_effort must match "
                    f"{expected_effort.value}."
                )
            if assessment.get("meets_requested_effort") is not True:
                issues.append(
                    "Task metadata.challenge_effort_self_assessment.meets_requested_effort must be true; "
                    "revise the task until the builder judges it satisfies the requested challenge effort."
                )
            if not _has_text(assessment.get("rationale")):
                issues.append("Task metadata.challenge_effort_self_assessment.rationale must explain the self-check.")

    if task.task_type == TaskType.choice:
        if len(task.choices) < 2:
            issues.append("choice tasks must provide at least two choices.")
        choice_ids = [choice.id for choice in task.choices]
        if len(set(choice_ids)) != len(choice_ids) or any(not _has_text(value) for value in choice_ids):
            issues.append("choice option ids must be non-empty and unique.")
        if not task.correct_choice_ids:
            issues.append("choice tasks must provide at least one correct_choice_id.")
        elif any(value not in set(choice_ids) for value in task.correct_choice_ids):
            issues.append("correct_choice_ids must refer to provided choice ids.")
    elif task.task_type == TaskType.fill_blank:
        if task.expected_text is None or not _has_text(task.expected_text):
            issues.append("fill_blank tasks must provide one non-empty expected_text.")
    if task.task_type in {TaskType.generation, TaskType.multi_turn} and not _has_scoring_guidance(task):
        issues.append("generation and multi_turn tasks must provide a judge rubric or scoring guidance.")

    registered_judge_tools = {"python_tests"}
    for judge_tool in task.judge_tools:
        if judge_tool.tool not in registered_judge_tools:
            issues.append(f"Unsupported judge tool: {judge_tool.tool!r}.")
            continue
        if task.task_type not in {TaskType.generation, TaskType.multi_turn, TaskType.agent}:
            issues.append("judge_tools are only valid for generation, multi_turn, and agent tasks.")
        if judge_tool.tool == "python_tests":
            test_code = str(judge_tool.config.get("test_code") or "")
            if not test_code.strip():
                issues.append("python_tests requires config.test_code.")
            elif "{model_output}" not in test_code:
                issues.append("python_tests config.test_code must consume {model_output}.")
    if task.task_type == TaskType.agent and task.environment is None:
        issues.append("agent tasks must provide an executable environment.")

    if task.task_type == TaskType.multi_turn:
        interaction = task.interaction
        try:
            max_turns = int(interaction.get("max_turns", 0))
        except (TypeError, ValueError):
            max_turns = 0
        if not 1 <= max_turns <= 5:
            issues.append("multi_turn tasks must define interaction.max_turns between 1 and 5.")
        scripted_turns = interaction.get("user_turns")
        followup_instruction = interaction.get("followup_instruction")
        scripted_turns_valid = bool(
            isinstance(scripted_turns, list)
            and 1 <= len(scripted_turns) <= 5
            and all(isinstance(turn, str) and turn.strip() for turn in scripted_turns)
        )
        if scripted_turns is not None and not scripted_turns_valid:
            issues.append("interaction.user_turns must contain 1 to 5 non-empty strings.")
        if not scripted_turns_valid and not _has_text(followup_instruction):
            issues.append(
                "multi_turn tasks must provide either interaction.user_turns or "
                "interaction.followup_instruction."
            )
        if scripted_turns_valid and _has_text(followup_instruction):
            issues.append(
                "multi_turn tasks must set exactly one of interaction.user_turns and "
                "interaction.followup_instruction."
            )
        followup_mode = (
            str(task_design.interaction_requirements.get("followup_mode") or "").strip().lower()
            if task_design is not None
            else ""
        )
        if followup_mode == "adaptive":
            if scripted_turns is not None:
                issues.append("Adaptive multi_turn tasks must omit interaction.user_turns.")
            if not _has_text(followup_instruction):
                issues.append(
                    "Adaptive multi_turn tasks must provide interaction.followup_instruction."
                )
            if not _has_text(task.system_prompt):
                issues.append("Adaptive multi_turn tasks must provide a simulator system_prompt.")
        elif followup_mode == "scripted":
            if not scripted_turns_valid:
                issues.append("Scripted multi_turn tasks must provide interaction.user_turns.")
            if _has_text(followup_instruction):
                issues.append("Scripted multi_turn tasks must omit interaction.followup_instruction.")

    expected_environment = blueprint.environment_type if blueprint is not None else None
    if blueprint is not None:
        if expected_environment is None:
            if task.environment is not None:
                issues.append("Task must omit environment because the TaskDesign does not request one.")
            return issues
        if task.environment is None:
            issues.append(
                f"Task must provide environment because the TaskDesign requests {expected_environment.value}."
            )
            return issues
    elif task.environment is None:
        return issues
    else:
        expected_environment = task.environment.type

    env = task.environment
    if env.type != expected_environment:
        issues.append(
            f"Task environment.type must match the TaskDesign requirement {expected_environment.value}."
        )
    artifact_requirement = str(
        env.evaluation.get("artifact_requirement")
        or env.session.get("artifact_requirement")
        or "all"
    ).strip().lower()
    if artifact_requirement not in {"all", "any", "exactly_one"}:
        issues.append(
            "environment artifact_requirement must be all, any, or exactly_one."
        )
    if task.task_type != TaskType.agent:
        issues.append(
            f"{env.type.value} environments are executable only for agent tasks."
        )
    if env.max_steps < 1:
        issues.append("Executable environments must set max_steps to a positive bound.")
    if env.timeout < 1:
        issues.append("Executable environments must set timeout to a positive bound.")
    if env.tools:
        issues.append(
            "environment.tools does not define executable custom behavior; use only tools exposed by "
            "the selected runtime and its structured configuration."
        )
    image_build = env.image_build if isinstance(env.image_build, dict) else {}
    context_dir = str(image_build.get("context_dir") or "").strip()
    if context_dir:
        context_parts = PurePosixPath(context_dir.replace("\\", "/")).parts
        if Path(context_dir).is_absolute() or ".." in context_parts:
            issues.append(
                "image_build.context_dir must be a relative path inside the Builder job directory."
            )

    visible_paths = set(env.visible_files)
    runtime_paths = set(env.runtime_files)
    hidden_paths = set(env.hidden_files)
    collisions = (visible_paths & runtime_paths) | (visible_paths & hidden_paths) | (runtime_paths & hidden_paths)
    if collisions:
        issues.append(
            "Environment files must belong to exactly one lifecycle phase; duplicate paths: "
            + ", ".join(sorted(collisions))
        )
    setup_text = "\n".join(env.setup_commands)
    referenced_hidden = [
        path
        for path in hidden_paths
        if path in setup_text or PurePosixPath(path).name in setup_text
    ]
    if referenced_hidden:
        issues.append(
            "setup_commands reference evaluator-only hidden_files. Move setup assets to runtime_files: "
            + ", ".join(sorted(referenced_hidden))
        )

    if env.type == AgentEnvironmentType.docker_workspace:
        if not _has_text(env.test_command):
            issues.append("docker_workspace tasks must include a deterministic test_command.")
        task_text = f"{task.prompt} {' '.join(task.tags)}".lower()
        browser_enabled = bool(env.browser.get("enabled"))
        planned_designs = (
            [task_design]
            if task_design is not None
            else (blueprint.task_designs if blueprint is not None else [])
        )
        requested_capabilities = [
            str(capability).strip().lower()
            for design in planned_designs
            for capability in (
                list(design.interaction_requirements.get("allowed_action_or_tool_categories", []))
                + list(design.environment_requirements.get("required_capabilities", []))
            )
            if str(capability).strip()
        ]
        browser_required = any("browser" in capability for capability in requested_capabilities)
        if browser_required and not browser_enabled:
            issues.append(
                "TaskDesign requires browser actions, so environment.browser.enabled=true and an "
                "executable browser runtime are required."
            )
        if browser_enabled:
            if str(env.browser.get("runtime") or "") != "playwright_python":
                issues.append("Docker browser runtime must set browser.runtime=playwright_python.")
            if not _has_text(env.browser.get("start_url")):
                issues.append("Docker browser runtime must define browser.start_url.")
            if not isinstance(env.browser.get("allowed_origins"), list) or not env.browser.get("allowed_origins"):
                issues.append("Docker browser runtime must define at least one browser.allowed_origins entry.")
            executable_path = str(env.browser.get("executable_path") or "")
            if any(marker in executable_path for marker in ("*", "?", "[", "]")):
                issues.append("browser.executable_path must be an exact guest path, not a wildcard pattern.")
            if "final_answer tool" in task_text or "final_answer_tool" in task_text:
                issues.append("The canonical completion tool is final; prompts must not name a final_answer tool.")

            package = task.metadata.get(AGENT_TASK_PACKAGE_METADATA_KEY)
            output_contract = package.get("output_contract") if isinstance(package, dict) else None
            expected_artifacts = (
                output_contract.get("expected_artifacts")
                if isinstance(output_contract, dict)
                and isinstance(output_contract.get("expected_artifacts"), list)
                else []
            )
            file_artifacts: list[str] = []
            for artifact in expected_artifacts:
                value = str(artifact or "").strip()
                if not value:
                    continue
                path = PurePosixPath(value)
                if path.is_absolute() or (" " not in value and bool(path.suffix)):
                    file_artifacts.append(value)
            configured_workspace_tools = env.browser.get("workspace_tools")
            workspace_tools = (
                {str(name) for name in configured_workspace_tools}
                if isinstance(configured_workspace_tools, list)
                else set()
            )
            if bool(env.browser.get("allow_workspace_tools")):
                workspace_tools.update({"list_files", "read_file", "write_file", "run_command"})
            if file_artifacts and "write_file" not in workspace_tools:
                issues.append(
                    "Browser tasks with file artifacts must expose write_file through "
                    "browser.workspace_tools."
                )
            workdir = PurePosixPath(env.workdir or "/workspace")
            for artifact in file_artifacts:
                artifact_path = PurePosixPath(artifact)
                if not artifact_path.is_absolute():
                    continue
                try:
                    artifact_path.relative_to(workdir)
                except ValueError:
                    issues.append(
                        f"Browser file artifact {artifact} must be inside environment.workdir={workdir}."
                    )

    elif env.type == AgentEnvironmentType.gui:
        if not env.session:
            issues.append(
                "gui tasks must include environment.session with application, launch/start state, "
                "input assets, expected artifacts, or task restrictions."
            )
        else:
            has_application = _has_any_text(
                env.session.get("application"),
                env.session.get("kind"),
            ) or bool(env.session.get("applications"))
            has_start_state = _has_any_text(
                env.session.get("launch_state"),
                env.session.get("start_state"),
                env.session.get("start_url"),
                env.session.get("entrypoint"),
            )
            if not has_application:
                issues.append(
                    "gui tasks must set environment.session.application, kind, or applications; "
                    "session.surface is not consumed by the runtime."
                )
            if not has_start_state:
                issues.append(
                    "gui tasks must set environment.session.launch_state, start_state, "
                    "start_url, or entrypoint."
                )
        if not _has_environment_evaluator(task):
            issues.append(
                "gui tasks must put an executable method or checks in environment.evaluation; "
                "session.evaluation_checks is not consumed by the runtime."
            )
        issues.extend(
            _desktop_check_issues(
                env.session.get("baseline_checks"),
                field_name="environment.session.baseline_checks",
            )
        )
        issues.extend(
            _desktop_check_issues(
                env.evaluation.get("checks"),
                field_name="environment.evaluation.checks",
            )
        )
        requires_vm = bool(env.requires_vm or env.vm)
        if requires_vm:
            if not env.vm:
                issues.append("gui tasks with requires_vm=true must include environment.vm.")
            else:
                source_fields = (
                    "template",
                    "template_name",
                    "image",
                    "disk_image",
                    "disk_path",
                    "template_path",
                )
                source_values = [env.vm.get(field) for field in source_fields]
                requirements = env.vm.get("requirements")
                requirements = requirements if isinstance(requirements, dict) else {}
                required_capabilities = (
                    requirements.get("capabilities")
                    or requirements.get("required_capabilities")
                    or env.vm.get("required_capabilities")
                )
                has_runtime_requirements = bool(
                    _declared_vm_guest_os(env)
                    and isinstance(required_capabilities, list)
                    and required_capabilities
                )
                if not _has_any_text(*source_values) and not has_runtime_requirements:
                    issues.append(
                        "VM-backed gui tasks must provide a runner-resolvable template, "
                        "image, or disk identifier, or guest OS plus required_capabilities for "
                        "runtime provider resolution."
                    )
                for field in (*source_fields, "snapshot"):
                    value = env.vm.get(field)
                    if _vm_source_looks_descriptive_or_placeholder(value):
                        issues.append(
                            f"environment.vm.{field} must be a concrete runner-resolvable identifier, "
                            "not a placeholder or prose description."
                        )
            issues.extend(_vm_provisioning_platform_issues(env))
            issues.extend(_vm_powershell_syntax_issues(env))
            issues.extend(_vm_interactive_provisioning_issues(env))
            issues.extend(_vm_windows_session_identity_issues(env))
            issues.extend(_vm_protected_evaluator_reference_issues(env))
            issues.extend(_vm_powershell_check_issues(env))
            issues.extend(_vm_powershell_contract_issues(env))
            if not (
                isinstance(env.session.get("baseline_checks"), list)
                and env.session["baseline_checks"]
            ):
                issues.append(
                    "Every VM-backed gui task must define executable "
                    "environment.session.baseline_checks for the bridge to verify before the target starts."
                )

    return issues


def task_structure_validation_metadata(issues: list[str]) -> dict[str, object]:
    return {
        "schema_version": TASK_STRUCTURE_VALIDATION_VERSION,
        "status": "passed" if not issues else "failed",
        "issues": issues,
    }
