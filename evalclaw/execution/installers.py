"""Shared package-manager rendering helpers for task environments."""
from __future__ import annotations

import json
import re
import shlex
from typing import Any


def string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def package_list(value: Any) -> list[str]:
    packages: list[str] = []
    for package in string_list(value):
        packages.extend(part for part in re.split(r"\s+", package) if part)
    return list(dict.fromkeys(packages))


def _install_steps(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw = config.get("install_steps") or config.get("package_manager_steps") or config.get("software_install_steps")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [step for step in raw if isinstance(step, dict)]


def _manager(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "apt-get": "apt",
        "system": "apt",
        "system-packages": "apt",
        "apk-packages": "apk",
        "dnf-packages": "dnf",
        "yum-packages": "yum",
        "pacman-packages": "pacman",
        "python": "pip",
        "pip3": "pip",
        "node": "npm",
        "nodejs": "npm",
        "r": "cran",
        "r-cran": "cran",
        "bioc": "bioconductor",
        "bioconductor-packages": "bioconductor",
        "mamba": "conda",
        "micromamba": "conda",
        "ruby": "gem",
        "php-composer": "composer",
        "shell": "command",
        "sh": "command",
        "bash": "command",
        "powershell": "powershell",
        "pwsh": "powershell",
        "ps1": "powershell",
        "chocolatey": "choco",
        "windows-feature": "windows_feature",
        "windows-features": "windows_feature",
    }
    return aliases.get(raw, raw)


def _step_packages(step: dict[str, Any]) -> list[str]:
    return package_list(step.get("packages") or step.get("package") or step.get("package_specs"))


def _step_commands(step: dict[str, Any]) -> list[str]:
    commands = string_list(step.get("command"))
    commands.extend(string_list(step.get("commands")))
    commands.extend(string_list(step.get("run")))
    return commands


def packages_for_manager(config: dict[str, Any], manager: str, *keys: str) -> list[str]:
    canonical = _manager(manager)
    packages: list[str] = []
    for key in keys:
        packages.extend(package_list(config.get(key)))
    for step in _install_steps(config):
        if _manager(step.get("manager") or step.get("type")) == canonical:
            packages.extend(_step_packages(step))
    return list(dict.fromkeys(packages))


def apt_packages(config: dict[str, Any]) -> list[str]:
    return packages_for_manager(config, "apt", "apt_packages", "system_packages", "packages")


def _quoted_packages(packages: list[str]) -> str:
    return " ".join(shlex.quote(package) for package in packages)


def _r_vector(packages: list[str]) -> str:
    return "c(" + ", ".join(json.dumps(package) for package in packages) + ")"


def _render_conda_install(packages: list[str], channels: list[str]) -> str:
    package_args = _quoted_packages(packages)
    channel_args = " ".join(f"-c {shlex.quote(channel)}" for channel in channels)
    args = " ".join(part for part in (channel_args, package_args) if part)
    return (
        "if command -v micromamba >/dev/null 2>&1; then "
        f"micromamba install -y -n base {args} && micromamba clean -a -y; "
        "elif command -v mamba >/dev/null 2>&1; then "
        f"mamba install -y {args} && mamba clean -a -y; "
        "elif command -v conda >/dev/null 2>&1; then "
        f"conda install -y {args} && conda clean -a -y; "
        "else echo 'conda, mamba, or micromamba is required for conda_packages' >&2; exit 127; fi"
    )


def _install_step_channels(config: dict[str, Any], step: dict[str, Any]) -> list[str]:
    channels = package_list(step.get("channels") or step.get("channel"))
    if not channels:
        channels = package_list(config.get("conda_channels") or config.get("channels"))
    return channels


def render_install_commands(config: dict[str, Any]) -> list[str]:
    """Render non-apt package manager steps as shell commands.

    Apt packages are intentionally excluded so Docker can put them in a single
    apt-get layer and VM cloud-init can use its native packages section.
    """
    commands: list[str] = []
    manager_specs: list[tuple[str, list[str], list[str]]] = [
        ("apk", ["apk_packages"], []),
        ("dnf", ["dnf_packages"], []),
        ("yum", ["yum_packages"], []),
        ("pacman", ["pacman_packages"], []),
        ("snap", ["snap_packages"], []),
        ("pip", ["pip_packages", "python_packages"], []),
        ("npm", ["npm_packages", "node_packages"], []),
        ("cran", ["cran_packages", "r_packages"], []),
        ("bioconductor", ["bioconductor_packages", "bioc_packages"], []),
        ("julia", ["julia_packages"], []),
        ("conda", ["conda_packages"], []),
        ("cargo", ["cargo_packages"], []),
        ("go", ["go_packages"], []),
        ("gem", ["gem_packages", "ruby_gems"], []),
        ("composer", ["composer_packages"], []),
    ]
    rendered_managers: set[str] = set()
    for manager, keys, _ in manager_specs:
        packages = packages_for_manager(config, manager, *keys)
        if not packages:
            continue
        rendered_managers.add(manager)
        if manager == "apk":
            commands.append(f"apk add --no-cache {_quoted_packages(packages)}")
        elif manager == "dnf":
            commands.append(f"dnf install -y {_quoted_packages(packages)}")
        elif manager == "yum":
            commands.append(f"yum install -y {_quoted_packages(packages)}")
        elif manager == "pacman":
            commands.append(f"pacman -Sy --noconfirm {_quoted_packages(packages)}")
        elif manager == "snap":
            commands.extend(f"snap install {shlex.quote(package)}" for package in packages)
        elif manager == "pip":
            package_args = _quoted_packages(packages)
            commands.append(
                f"python3 -m pip install --no-cache-dir {package_args} || "
                f"python -m pip install --no-cache-dir {package_args} || "
                f"python3 -m pip install --break-system-packages --no-cache-dir {package_args}"
            )
        elif manager == "npm":
            commands.append(f"npm install -g {_quoted_packages(packages)}")
        elif manager == "cran":
            commands.append(
                "Rscript -e "
                + shlex.quote(
                    "install.packages("
                    + _r_vector(packages)
                    + ", repos='https://cloud.r-project.org')"
                )
            )
        elif manager == "bioconductor":
            commands.append(
                "Rscript -e "
                + shlex.quote(
                    "if (!requireNamespace('BiocManager', quietly=TRUE)) "
                    "install.packages('BiocManager', repos='https://cloud.r-project.org'); "
                    "BiocManager::install("
                    + _r_vector(packages)
                    + ", ask=FALSE, update=FALSE)"
                )
            )
        elif manager == "julia":
            commands.append(
                "julia -e "
                + shlex.quote(
                    "using Pkg; Pkg.add("
                    + json.dumps(packages)
                    + "); Pkg.precompile()"
                )
            )
        elif manager == "conda":
            commands.append(_render_conda_install(packages, package_list(config.get("conda_channels") or config.get("channels"))))
        elif manager == "cargo":
            commands.append(f"cargo install {_quoted_packages(packages)}")
        elif manager == "go":
            commands.extend(f"go install {shlex.quote(package)}" for package in packages)
        elif manager == "gem":
            commands.append(f"gem install {_quoted_packages(packages)}")
        elif manager == "composer":
            commands.append(f"composer global require {_quoted_packages(packages)}")

    for step in _install_steps(config):
        manager = _manager(step.get("manager") or step.get("type"))
        if manager == "apt":
            continue
        if manager == "command":
            commands.extend(_step_commands(step))
            continue
        packages = _step_packages(step)
        if not packages or manager in rendered_managers:
            continue
        if manager == "apk":
            commands.append(f"apk add --no-cache {_quoted_packages(packages)}")
        elif manager == "dnf":
            commands.append(f"dnf install -y {_quoted_packages(packages)}")
        elif manager == "yum":
            commands.append(f"yum install -y {_quoted_packages(packages)}")
        elif manager == "pacman":
            commands.append(f"pacman -Sy --noconfirm {_quoted_packages(packages)}")
        elif manager == "snap":
            commands.extend(f"snap install {shlex.quote(package)}" for package in packages)
        elif manager == "conda":
            commands.append(_render_conda_install(packages, _install_step_channels(config, step)))
        elif manager == "pip":
            package_args = _quoted_packages(packages)
            commands.append(
                f"python3 -m pip install --no-cache-dir {package_args} || "
                f"python -m pip install --no-cache-dir {package_args} || "
                f"python3 -m pip install --break-system-packages --no-cache-dir {package_args}"
            )
        elif manager == "npm":
            commands.append(f"npm install -g {_quoted_packages(packages)}")
        elif manager == "cran":
            commands.append(
                "Rscript -e "
                + shlex.quote(
                    "install.packages("
                    + _r_vector(packages)
                    + ", repos='https://cloud.r-project.org')"
                )
            )
        elif manager == "bioconductor":
            commands.append(
                "Rscript -e "
                + shlex.quote(
                    "if (!requireNamespace('BiocManager', quietly=TRUE)) "
                    "install.packages('BiocManager', repos='https://cloud.r-project.org'); "
                    "BiocManager::install("
                    + _r_vector(packages)
                    + ", ask=FALSE, update=FALSE)"
                )
            )
        elif manager == "julia":
            commands.append(
                "julia -e "
                + shlex.quote(
                    "using Pkg; Pkg.add("
                    + json.dumps(packages)
                    + "); Pkg.precompile()"
                )
            )
        elif manager == "cargo":
            commands.append(f"cargo install {_quoted_packages(packages)}")
        elif manager == "go":
            commands.extend(f"go install {shlex.quote(package)}" for package in packages)
        elif manager == "gem":
            commands.append(f"gem install {_quoted_packages(packages)}")
        elif manager == "composer":
            commands.append(f"composer global require {_quoted_packages(packages)}")

    commands.extend(string_list(config.get("desktop_bridge_install_command") or config.get("bridge_install_command")))
    commands.extend(string_list(config.get("commands") or config.get("run_commands")))
    commands.extend(string_list(config.get("bootstrap_commands") or config.get("runcmd")))
    commands.extend(string_list(config.get("desktop_bridge_start_command") or config.get("bridge_start_command")))
    return list(dict.fromkeys(commands))


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_windows_install_commands(config: dict[str, Any]) -> list[str]:
    """Render Windows VM provisioning as PowerShell commands."""
    commands: list[str] = []
    winget_packages = packages_for_manager(config, "winget", "winget_packages")
    choco_packages = packages_for_manager(
        config,
        "choco",
        "choco_packages",
        "chocolatey_packages",
    )
    windows_features = packages_for_manager(config, "windows_feature", "windows_features")
    pip_packages = packages_for_manager(config, "pip", "pip_packages", "python_packages")
    npm_packages = packages_for_manager(config, "npm", "npm_packages", "node_packages")

    for package in winget_packages:
        quoted = _powershell_quote(package)
        commands.append(
            f"winget install --id {quoted} --exact --silent "
            "--accept-package-agreements --accept-source-agreements"
        )
    if choco_packages:
        commands.append("choco install -y " + " ".join(_powershell_quote(p) for p in choco_packages))
    for feature in windows_features:
        commands.append(
            "Enable-WindowsOptionalFeature -Online -All -NoRestart -FeatureName "
            + _powershell_quote(feature)
        )
    if pip_packages:
        args = " ".join(_powershell_quote(package) for package in pip_packages)
        commands.append(
            "if (Get-Command py -ErrorAction SilentlyContinue) { "
            f"& py -3 -m pip install {args} "
            "} elseif (Get-Command python -ErrorAction SilentlyContinue) { "
            f"& python -m pip install {args} "
            "} else { throw 'Python is required for pip_packages' }"
        )
    if npm_packages:
        commands.append("npm install -g " + " ".join(_powershell_quote(p) for p in npm_packages))

    rendered_managers = {
        manager
        for manager, packages in (
            ("winget", winget_packages),
            ("choco", choco_packages),
            ("windows_feature", windows_features),
            ("pip", pip_packages),
            ("npm", npm_packages),
        )
        if packages
    }
    for step in _install_steps(config):
        manager = _manager(step.get("manager") or step.get("type"))
        if manager in {"command", "powershell"}:
            commands.extend(_step_commands(step))
            continue
        packages = _step_packages(step)
        if not packages or manager in rendered_managers:
            continue
        if manager == "winget":
            for package in packages:
                commands.append(
                    f"winget install --id {_powershell_quote(package)} --exact --silent "
                    "--accept-package-agreements --accept-source-agreements"
                )
        elif manager == "choco":
            commands.append("choco install -y " + " ".join(_powershell_quote(p) for p in packages))
        elif manager == "windows_feature":
            commands.extend(
                "Enable-WindowsOptionalFeature -Online -All -NoRestart -FeatureName "
                + _powershell_quote(package)
                for package in packages
            )

    commands.extend(string_list(config.get("desktop_bridge_install_command") or config.get("bridge_install_command")))
    commands.extend(string_list(config.get("powershell_commands") or config.get("powershell_script")))
    commands.extend(string_list(config.get("commands") or config.get("run_commands")))
    commands.extend(string_list(config.get("bootstrap_commands") or config.get("runcmd")))
    commands.extend(string_list(config.get("desktop_bridge_start_command") or config.get("bridge_start_command")))
    return list(dict.fromkeys(commands))
