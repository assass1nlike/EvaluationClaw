import subprocess
from pathlib import Path

from evalclaw.execution.docker_images import _render_dockerfile, build_docker_image_if_requested
from evalclaw.execution.vm_materializer import materialize_vm_task
from evalclaw.types import BenchmarkItem, TaskType


def test_docker_image_build_renders_cross_domain_installers(monkeypatch) -> None:
    build_commands: list[list[str]] = []
    dockerfile_text = ""
    monkeypatch.setattr("evalclaw.execution.docker_images.resolve_docker_executable", lambda executable: "docker")
    monkeypatch.setattr("evalclaw.execution.docker_images.docker_subprocess_env", lambda executable: {})

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
    assert "micromamba install -y -n base -c conda-forge -c pytorch pytorch torchvision" in dockerfile_text
    assert "cargo install ripgrep" in dockerfile_text
    assert "go install github.com/projectdiscovery/httpx/cmd/httpx@latest" in dockerfile_text
    assert "gem install bundler" in dockerfile_text
    assert "composer global require phpunit/phpunit" in dockerfile_text
    assert "echo domain-ready >/opt/evalclaw-domain.txt" in dockerfile_text


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
        task_type=TaskType.agent_interaction,
        prompt="Run a cross-domain VM task.",
        metadata={
            "agent_env": {
                "type": "gui_desktop",
                "requires_vm": True,
                "vm": {"image": "ubuntu-base"},
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
        task_type=TaskType.agent_interaction,
        prompt="Run a VM task that only needs domain language packages.",
        metadata={
            "agent_env": {
                "type": "gui_desktop",
                "requires_vm": True,
                "vm": {"image": "ubuntu-base"},
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
