import subprocess
import sys
from pathlib import Path

import pytest

from evalclaw.construction.validation import task_structure_issues
from evalclaw.execution.docker_agent_env import DockerWorkspaceAgentEnvironment
from evalclaw.execution.docker_browser import DOCKER_BROWSER_RUNTIME_SCRIPT
from evalclaw.execution.docker_images import _render_dockerfile, build_docker_image_if_requested
from evalclaw.execution.vm_materializer import VmTaskMaterializationError, materialize_vm_task
from evalclaw.execution.vm_materializer import _run_command as _run_vm_materializer_command
from evalclaw.types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    BenchmarkItem,
    TaskDefinition,
    TaskScoringSpec,
    TaskType,
)
from tests.blueprint_factory import make_blueprint


def test_docker_browser_runtime_script_compiles() -> None:
    compile(DOCKER_BROWSER_RUNTIME_SCRIPT, "browser_runtime.py", "exec")


def test_docker_browser_environment_exposes_browser_tools_and_private_evaluator() -> None:
    env = DockerWorkspaceAgentEnvironment(
        image="mcr.microsoft.com/playwright/python:v1.52.0-noble",
        visible_files={},
        hidden_files={},
        browser={
            "enabled": True,
            "runtime": "playwright_python",
            "start_url": "http://localhost:8000",
            "allowed_origins": ["http://localhost:8000"],
        },
        expose_test_tool=False,
        auto_evaluate_on_final=True,
    )

    names = [tool.name for tool in env.tool_specs()]

    assert "browser_navigate" in names
    assert "browser_snapshot" in names
    assert "browser_fill" in names
    assert "final" in names
    assert "run_command" not in names
    assert "run_tests" not in names


def test_docker_browser_environment_can_expose_only_write_file() -> None:
    env = DockerWorkspaceAgentEnvironment(
        image="mcr.microsoft.com/playwright/python:v1.52.0-noble",
        visible_files={},
        hidden_files={},
        browser={
            "enabled": True,
            "start_url": "http://localhost:8000",
            "workspace_tools": ["write_file"],
        },
        expose_test_tool=False,
    )

    names = [tool.name for tool in env.tool_specs()]

    assert "write_file" in names
    assert "read_file" not in names
    assert "run_command" not in names
    assert env._clean_path("/workspace/result.csv") == "result.csv"
    assert env._clean_path("/tmp/result.csv") is None


def test_docker_browser_final_runs_private_evaluator(monkeypatch) -> None:
    env = DockerWorkspaceAgentEnvironment(
        image="mcr.microsoft.com/playwright/python:v1.52.0-noble",
        visible_files={},
        hidden_files={"evaluate.py": "raise SystemExit(0)"},
        browser={"enabled": True, "start_url": "http://localhost:8000"},
        expose_test_tool=False,
        auto_evaluate_on_final=True,
    )
    written: list[str] = []

    monkeypatch.setattr(env, "_write_final_answer", lambda answer: written.append(answer))

    def fake_tests() -> str:
        env.test_runs += 1
        env.last_test = {
            "passed": True,
            "score": 1.0,
            "returncode": 0,
            "stdout": "PASS",
            "stderr": "",
        }
        return "Evaluator passed with score=1.0."

    monkeypatch.setattr(env, "_run_configured_tests", fake_tests)

    outcome = env.step({"tool": "final", "args": {"answer": "42"}})

    assert outcome.done is True
    assert env.score() == 1.0
    assert env.final_answer == "42"
    assert written == ["42"]
    assert env.test_runs == 1


def test_browser_blueprint_requires_executable_docker_browser_runtime() -> None:
    task = TaskDefinition(
        id="browser_task",
        dimension_id="web",
        task_type=TaskType.agent,
        title="Browser task",
        prompt="Use the browser tools to update the local website.",
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.docker_workspace,
            image="python:3.11-slim",
            visible_files={"app.py": "print('app')"},
            hidden_files={"test.py": "raise SystemExit(0)"},
            test_command="python3 test.py",
        ),
        scoring=TaskScoringSpec(pass_criteria="The website is updated."),
    )
    blueprint = make_blueprint(
        "browser_blueprint",
        "web",
        "Browser workflow",
        task_type=TaskType.agent,
        content="One browser workflow.",
        environment_type=AgentEnvironmentType.docker_workspace,
        allowed_tools=["browser"],
    )

    issues = task_structure_issues(task, blueprint=blueprint)

    assert any("environment.browser.enabled=true" in issue for issue in issues)


def test_setup_cannot_reference_evaluator_only_hidden_files() -> None:
    task = TaskDefinition(
        id="invalid_lifecycle",
        dimension_id="code",
        task_type=TaskType.agent,
        title="Invalid lifecycle",
        prompt="Configure the application and complete the requested code change.",
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.docker_workspace,
            image="python:3.11-slim",
            visible_files={"solution.py": "pass\n"},
            hidden_files={"private/evaluate.py": "raise SystemExit(0)\n"},
            setup_commands=["python3 private/evaluate.py --serve"],
            test_command="python3 private/evaluate.py",
        ),
        scoring=TaskScoringSpec(pass_criteria="The evaluator accepts the solution."),
    )

    issues = task_structure_issues(task)

    assert any("reference evaluator-only hidden_files" in issue for issue in issues)


def test_browser_file_artifact_requires_write_tool_and_workdir_path() -> None:
    task = TaskDefinition(
        id="browser_artifact_task",
        dimension_id="web",
        task_type=TaskType.agent,
        title="Browser artifact task",
        prompt="Use browser tools and save the extracted data.",
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.docker_workspace,
            image="mcr.microsoft.com/playwright/python:v1.52.0-noble",
            workdir="/workspace",
            visible_files={"app.py": "print('app')"},
            hidden_files={"test.py": "raise SystemExit(0)"},
            test_command="python3 test.py",
            browser={
                "enabled": True,
                "runtime": "playwright_python",
                "start_url": "http://localhost:8000",
                "allowed_origins": ["http://localhost:8000"],
                "workspace_tools": [],
            },
        ),
        scoring=TaskScoringSpec(pass_criteria="The CSV matches expected rows."),
        metadata={
            "agent_task_package": {"output_contract": {"expected_artifacts": ["/tmp/result.csv"]}}
        },
    )

    issues = task_structure_issues(task)

    assert any("must expose write_file" in issue for issue in issues)
    assert any("must be inside environment.workdir=/workspace" in issue for issue in issues)


def test_vm_materializer_command_replaces_invalid_output_bytes() -> None:
    success, output = _run_vm_materializer_command(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xffseed-ok')"]
    )

    assert success is True
    assert "seed-ok" in output


def test_docker_image_build_renders_cross_domain_installers(monkeypatch) -> None:
    build_commands: list[list[str]] = []
    dockerfile_text = ""
    monkeypatch.setattr(
        "evalclaw.execution.docker_images.resolve_docker_executable", lambda executable: "docker"
    )
    monkeypatch.setattr(
        "evalclaw.execution.docker_images.docker_subprocess_env", lambda executable: {}
    )

    def fake_run(command, **kwargs):
        nonlocal dockerfile_text
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="not found")
        if command[1] == "build":
            build_commands.append(command)
            dockerfile_text = Path(command[-1], "Dockerfile").read_text(encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="built\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("evalclaw.execution.docker_images.subprocess.run", fake_run)

    env, result = build_docker_image_if_requested(
        {
            "type": "docker_workspace",
            "image": "build://auto",
            "id": "cross-domain",
            "image_build": {
                "enabled": True,
                "base_image": "ubuntu:24.04",
                "tag": "evalclaw-cross-domain:test",
                "apt_packages": [
                    "gdal-bin",
                    "samtools",
                    "texlive-latex-base",
                    "tshark",
                    "r-base",
                    "julia",
                    "cargo",
                    "golang-go",
                    "ruby",
                    "composer",
                ],
                "pip_packages": ["geopandas", "biopython", "rdkit-pypi"],
                "npm_packages": ["typescript"],
                "cran_packages": ["tidyverse"],
                "bioconductor_packages": ["DESeq2"],
                "julia_packages": ["DifferentialEquations"],
                "conda_packages": ["pytorch", "torchvision"],
                "conda_channels": ["conda-forge", "pytorch"],
                "cargo_packages": ["ripgrep"],
                "go_packages": ["github.com/projectdiscovery/httpx/cmd/httpx@latest"],
                "gem_packages": ["bundler"],
                "composer_packages": ["phpunit/phpunit"],
                "install_steps": [
                    {"manager": "shell", "command": "echo domain-ready >/opt/evalclaw-domain.txt"},
                ],
            },
        },
        docker_executable="docker",
    )

    assert result is not None
    assert result.built is True
    assert env["image"] == "evalclaw-cross-domain:test"
    assert build_commands
    assert "FROM ubuntu:24.04" in dockerfile_text
    assert "apt-get update && apt-get install -y --no-install-recommends" in dockerfile_text
    for package in ("gdal-bin", "samtools", "texlive-latex-base", "tshark"):
        assert package in dockerfile_text
    assert "pip install --no-cache-dir geopandas biopython rdkit-pypi" in dockerfile_text
    assert "npm install -g typescript" in dockerfile_text
    assert "Rscript -e" in dockerfile_text
    assert "tidyverse" in dockerfile_text
    assert "BiocManager::install" in dockerfile_text
    assert "DESeq2" in dockerfile_text
    assert "julia -e" in dockerfile_text
    assert "DifferentialEquations" in dockerfile_text
    assert (
        "micromamba install -y -n base -c conda-forge -c pytorch pytorch torchvision"
        in dockerfile_text
    )
    assert "cargo install ripgrep" in dockerfile_text
    assert "go install github.com/projectdiscovery/httpx/cmd/httpx@latest" in dockerfile_text
    assert "gem install bundler" in dockerfile_text
    assert "composer global require phpunit/phpunit" in dockerfile_text
    assert "echo domain-ready >/opt/evalclaw-domain.txt" in dockerfile_text


def test_docker_image_build_passes_proxy_and_custom_build_args(monkeypatch) -> None:
    build_commands: list[list[str]] = []
    monkeypatch.setattr(
        "evalclaw.execution.docker_images.resolve_docker_executable", lambda executable: "docker"
    )
    monkeypatch.setattr(
        "evalclaw.execution.docker_images.docker_subprocess_env", lambda executable: {}
    )
    monkeypatch.setenv("EVALCLAW_DOCKER_HTTP_PROXY", "http://host.docker.internal:7890")
    monkeypatch.setenv("EVALCLAW_DOCKER_HTTPS_PROXY", "http://host.docker.internal:7890")

    def fake_run(command, **kwargs):
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="not found")
        if command[1] == "build":
            build_commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="built\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("evalclaw.execution.docker_images.subprocess.run", fake_run)

    build_docker_image_if_requested(
        {
            "type": "docker_workspace",
            "image": "build://auto",
            "id": "proxy-build",
            "image_build": {
                "enabled": True,
                "base_image": "ubuntu:22.04",
                "tag": "evalclaw-proxy-build:test",
                "build_args": {"APT_MIRROR": "archive.ubuntu.com"},
            },
        },
        docker_executable="docker",
    )

    command = build_commands[0]
    joined = " ".join(command)
    assert "--build-arg APT_MIRROR=archive.ubuntu.com" in joined
    assert "--build-arg HTTP_PROXY=http://host.docker.internal:7890" in joined
    assert "--build-arg http_proxy=http://host.docker.internal:7890" in joined
    assert "--build-arg HTTPS_PROXY=http://host.docker.internal:7890" in joined


def test_docker_image_build_supports_non_debian_package_managers() -> None:
    dockerfile = _render_dockerfile(
        {
            "type": "docker_workspace",
            "image": "build://auto",
            "image_build": {
                "enabled": True,
                "base_image": "alpine:3.20",
                "apk_packages": ["git", "openjdk17"],
                "install_steps": [
                    {"manager": "dnf", "packages": ["qgis"]},
                    {"manager": "yum", "packages": ["nmap"]},
                    {"manager": "pacman", "packages": ["openscad"]},
                    {"manager": "shell", "commands": ["echo custom"]},
                ],
                "tag": "evalclaw-nondebian:test",
            },
        }
    )

    assert "FROM alpine:3.20" in dockerfile
    assert "apk add --no-cache git openjdk17" in dockerfile
    assert "dnf install -y qgis" in dockerfile
    assert "yum install -y nmap" in dockerfile
    assert "pacman -Sy --noconfirm openscad" in dockerfile
    assert "RUN echo custom" in dockerfile


def test_vm_provisioning_renders_cross_domain_cloud_init(monkeypatch, tmp_path) -> None:
    def fake_build_seed_iso(seed_dir: Path, iso_path: Path, *, timeout: int = 60) -> None:
        iso_path.write_bytes(b"fake iso")

    monkeypatch.setattr("evalclaw.execution.vm_materializer._build_seed_iso", fake_build_seed_iso)
    item = BenchmarkItem(
        id="vm_cross_domain_provisioning",
        dimension_id="env",
        task_type=TaskType.agent,
        prompt="Run a cross-domain VM task.",
        metadata={
            "agent_env": {
                "type": "gui_desktop",
                "requires_vm": True,
                "vm": {"image": "ubuntu-base"},
                "session": {
                    "baseline_checks": [
                        {"method": "command", "command": "test -d /", "expected_exit_code": 0}
                    ]
                },
                "vm_provisioning": {
                    "enabled": True,
                    "apt_packages": ["qgis", "openbabel", "ffmpeg", "latexmk"],
                    "pip_packages": ["pandas", "scikit-learn"],
                    "snap_packages": ["hello-world"],
                    "cran_packages": ["ggplot2"],
                    "julia_packages": ["JuMP"],
                    "conda_packages": ["numpy"],
                    "conda_channels": ["conda-forge"],
                    "desktop_bridge_install_command": "python3 -m pip install evalclaw-desktop-bridge",
                    "desktop_bridge_start_command": "systemctl enable --now evalclaw-desktop-bridge || true",
                },
            }
        },
    )

    result = materialize_vm_task(item, work_dir=tmp_path)
    user_data = Path(result.work_dir, "seed", "user-data").read_text(encoding="utf-8")

    assert result.applied is True
    assert result.provisioning["apt_packages"] == ["qgis", "openbabel", "ffmpeg", "latexmk"]
    assert result.provisioning["pip_packages"] == ["pandas", "scikit-learn"]
    assert result.provisioning["snap_packages"] == ["hello-world"]
    assert "package_update: true" in user_data
    for package in ("qgis", "openbabel", "ffmpeg", "latexmk"):
        assert f'- "{package}"' in user_data
    assert "pip install --no-cache-dir pandas scikit-learn" in user_data
    assert "snap install hello-world" in user_data
    assert "Rscript -e" in user_data
    assert "ggplot2" in user_data
    assert "julia -e" in user_data
    assert "JuMP" in user_data
    assert "micromamba install -y -n base -c conda-forge numpy" in user_data
    assert "python3 -m pip install evalclaw-desktop-bridge" in user_data
    assert "systemctl enable --now evalclaw-desktop-bridge || true" in user_data


def test_vm_provisioning_triggers_from_non_apt_package_fields(monkeypatch, tmp_path) -> None:
    def fake_build_seed_iso(seed_dir: Path, iso_path: Path, *, timeout: int = 60) -> None:
        iso_path.write_bytes(b"fake iso")

    monkeypatch.setattr("evalclaw.execution.vm_materializer._build_seed_iso", fake_build_seed_iso)
    item = BenchmarkItem(
        id="vm_non_apt_provisioning",
        dimension_id="env",
        task_type=TaskType.agent,
        prompt="Run a VM task that only needs domain language packages.",
        metadata={
            "agent_env": {
                "type": "gui_desktop",
                "requires_vm": True,
                "vm": {"image": "ubuntu-base"},
                "session": {
                    "baseline_checks": [
                        {"method": "command", "command": "test -d /", "expected_exit_code": 0}
                    ]
                },
                "vm_provisioning": {
                    "cran_packages": ["forecast"],
                    "bioconductor_packages": ["edgeR"],
                    "julia_packages": ["DataFrames"],
                    "conda_packages": ["scanpy"],
                    "cargo_packages": ["fd-find"],
                    "go_packages": ["golang.org/x/tools/cmd/stringer@latest"],
                    "gem_packages": ["rake"],
                    "composer_packages": ["phpunit/phpunit"],
                    "install_steps": [{"manager": "shell", "command": "echo non-apt-ready"}],
                },
            }
        },
    )

    result = materialize_vm_task(item, work_dir=tmp_path)
    user_data = Path(result.work_dir, "seed", "user-data").read_text(encoding="utf-8")

    assert result.applied is True
    assert result.provisioning["cran_packages"] == ["forecast"]
    assert result.provisioning["bioconductor_packages"] == ["edgeR"]
    assert result.provisioning["julia_packages"] == ["DataFrames"]
    assert result.provisioning["conda_packages"] == ["scanpy"]
    assert result.provisioning["cargo_packages"] == ["fd-find"]
    assert result.provisioning["go_packages"] == ["golang.org/x/tools/cmd/stringer@latest"]
    assert result.provisioning["gem_packages"] == ["rake"]
    assert result.provisioning["composer_packages"] == ["phpunit/phpunit"]
    assert "package_update: true" not in user_data
    assert "forecast" in user_data
    assert "edgeR" in user_data
    assert "DataFrames" in user_data
    assert "scanpy" in user_data
    assert "cargo install fd-find" in user_data
    assert "go install golang.org/x/tools/cmd/stringer@latest" in user_data
    assert "gem install rake" in user_data
    assert "composer global require phpunit/phpunit" in user_data
    assert "echo non-apt-ready" in user_data


def test_vm_materialization_fails_closed_without_initial_state_checks(tmp_path) -> None:
    item = BenchmarkItem(
        id="unchecked_vm",
        dimension_id="env",
        task_type=TaskType.agent,
        prompt="Operate an unchecked VM.",
        metadata={
            "agent_env": {
                "type": "gui_desktop",
                "requires_vm": True,
                "vm": {"image": "windows-11-cloudbase", "guest_os": "windows"},
            }
        },
    )

    with pytest.raises(VmTaskMaterializationError, match="baseline_checks"):
        materialize_vm_task(item, work_dir=tmp_path)
