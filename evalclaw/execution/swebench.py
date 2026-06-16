"""SWE-bench Docker harness integration.

This module intentionally delegates repository image construction and test
execution to the official SWE-bench harness. EvaluationClaw owns validation,
prediction-file handling, and command orchestration.
"""
from __future__ import annotations

import ast
import json
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..types import BenchmarkConfig, BenchmarkItem
from .docker import DockerStatus, docker_status, docker_subprocess_env, resolve_docker_executable


@dataclass(frozen=True)
class SweBenchPrediction:
    instance_id: str
    model_name_or_path: str
    model_patch: str

    def as_json(self) -> dict[str, str]:
        return {
            "instance_id": self.instance_id,
            "model_name_or_path": self.model_name_or_path,
            "model_patch": self.model_patch,
        }


@dataclass(frozen=True)
class SweBenchHarnessConfig:
    predictions_path: str | Path
    output_dir: str | Path = "benchmark-output/swebench"
    dataset_name: str = "princeton-nlp/SWE-bench_Lite"
    split: str = "test"
    max_workers: int = 1
    run_id: str = "evalclaw_swebench"
    instance_ids: list[str] = field(default_factory=list)
    cache_level: str | None = "env"
    clean: bool | None = None
    force_rebuild: bool | None = None
    timeout: int | None = None
    namespace: str | None = None
    instance_image_tag: str | None = None
    env_image_tag: str | None = None
    python_executable: str = sys.executable
    docker_executable: str = "docker"
    use_wsl: bool = False
    wsl_distro: str | None = None
    wsl_docker_host: str = "unix:///mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.proxy.sock"
    wsl_docker_cli_dir: str = "/mnt/wsl/docker-desktop/cli-tools/usr/bin"
    wsl_http_proxy: str | None = None
    extra_args: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SweBenchHarnessResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    output_dir: Path
    docker: DockerStatus | None = None


@dataclass(frozen=True)
class SweBenchProxyBaseResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    base_image: str
    proxy_url: str


SWE_BENCH_METADATA_KEY = "swebench"


def normalize_json_list(value: Any) -> list[str]:
    """Normalize SWE-bench list fields that may arrive as JSON strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = ast.literal_eval(text)
        if not isinstance(parsed, list):
            raise ValueError(f"Expected list-like SWE-bench field, got {type(parsed).__name__}")
        return [str(item) for item in parsed]
    raise TypeError(f"Expected list or string SWE-bench field, got {type(value).__name__}")


def normalize_swebench_instance(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw Hugging Face SWE-bench row for local execution code."""
    normalized = dict(row)
    normalized["FAIL_TO_PASS"] = normalize_json_list(row.get("FAIL_TO_PASS"))
    normalized["PASS_TO_PASS"] = normalize_json_list(row.get("PASS_TO_PASS"))
    return normalized


def write_predictions_jsonl(
    predictions: list[SweBenchPrediction | dict[str, Any]],
    path: str | Path,
) -> Path:
    """Write official SWE-bench prediction JSONL."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for prediction in predictions:
            payload = prediction.as_json() if isinstance(prediction, SweBenchPrediction) else prediction
            for key in ("instance_id", "model_name_or_path", "model_patch"):
                if key not in payload:
                    raise ValueError(f"SWE-bench prediction is missing required key: {key}")
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return output


def swebench_item_metadata(item: BenchmarkItem) -> dict[str, Any] | None:
    """Return normalized SWE-bench metadata when an item should use the harness."""
    metadata = item.metadata or {}
    raw = metadata.get(SWE_BENCH_METADATA_KEY)
    if isinstance(raw, dict):
        return dict(raw)
    if raw is True:
        return {}

    markers = {
        str(metadata.get("benchmark", "")).lower(),
        str(metadata.get("external_benchmark", "")).lower(),
        str(metadata.get("runner", "")).lower(),
    }
    tags = {tag.lower() for tag in item.tags}
    source_uri = (item.source.uri or "").lower() if item.source else ""
    if "swebench" in markers or "swe-bench" in markers:
        return {}
    if "swebench" in tags or "swe-bench" in tags:
        return {}
    if source_uri.startswith(("swebench:", "swe-bench:")):
        return {}
    return None


def is_swebench_item(item: BenchmarkItem) -> bool:
    return swebench_item_metadata(item) is not None


def swebench_items(items: list[BenchmarkItem]) -> list[BenchmarkItem]:
    return [item for item in items if is_swebench_item(item)]


def _first_swebench_metadata(items: list[BenchmarkItem]) -> dict[str, Any]:
    for item in items:
        metadata = swebench_item_metadata(item)
        if metadata is not None:
            return metadata
    return {}


def _metadata_value(metadata: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in metadata and metadata[name] is not None:
            return metadata[name]
    return None


def _bool_metadata(metadata: dict[str, Any], name: str, default: bool) -> bool:
    value = metadata.get(name)
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _swebench_instance_ids(items: list[BenchmarkItem]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for item in items:
        metadata = swebench_item_metadata(item) or {}
        raw_ids = _metadata_value(metadata, "instance_ids", "instance_id")
        values = raw_ids if isinstance(raw_ids, list) else [raw_ids] if raw_ids else []
        for raw_id in values:
            instance_id = str(raw_id).strip()
            if instance_id and instance_id not in seen:
                ids.append(instance_id)
                seen.add(instance_id)
    return ids


def swebench_harness_config_from_items(
    items: list[BenchmarkItem],
    config: BenchmarkConfig,
) -> SweBenchHarnessConfig:
    """Build a harness config for preflight from item metadata and global config."""
    metadata = _first_swebench_metadata(items)
    output_dir = _metadata_value(metadata, "output_dir") or str(Path(config.output_dir) / "swebench")
    use_wsl = _bool_metadata(metadata, "use_wsl", config.swebench_use_wsl)
    python_executable = (
        _metadata_value(metadata, "python_executable")
        or (config.swebench_wsl_python_executable if use_wsl else config.swebench_python_executable)
    )
    return SweBenchHarnessConfig(
        predictions_path=_metadata_value(metadata, "predictions_path") or config.swebench_predictions_path,
        output_dir=output_dir,
        dataset_name=_metadata_value(metadata, "dataset_name", "dataset") or config.swebench_dataset_name,
        split=_metadata_value(metadata, "split") or config.swebench_split,
        max_workers=int(_metadata_value(metadata, "max_workers") or 1),
        run_id=_metadata_value(metadata, "run_id") or "evalclaw_swebench",
        instance_ids=_swebench_instance_ids(items),
        cache_level=_metadata_value(metadata, "cache_level") or "env",
        force_rebuild=_metadata_value(metadata, "force_rebuild"),
        timeout=_metadata_value(metadata, "timeout"),
        namespace=_metadata_value(metadata, "namespace"),
        instance_image_tag=_metadata_value(metadata, "instance_image_tag"),
        env_image_tag=_metadata_value(metadata, "env_image_tag"),
        python_executable=str(python_executable),
        docker_executable=str(_metadata_value(metadata, "docker_executable") or config.swebench_docker_executable),
        use_wsl=use_wsl,
        wsl_distro=_metadata_value(metadata, "wsl_distro") or config.swebench_wsl_distro,
        wsl_docker_host=_metadata_value(metadata, "wsl_docker_host") or config.swebench_wsl_docker_host,
        wsl_docker_cli_dir=_metadata_value(metadata, "wsl_docker_cli_dir") or config.swebench_wsl_docker_cli_dir,
        wsl_http_proxy=_metadata_value(metadata, "wsl_http_proxy") or config.swebench_wsl_http_proxy,
    )


def _format_swebench_item_list(items: list[BenchmarkItem]) -> str:
    item_ids = ", ".join(item.id for item in items[:5])
    if len(items) > 5:
        item_ids += f", ... (+{len(items) - 5} more)"
    return item_ids or "(none)"


def _format_swebench_setup_commands(config: SweBenchHarnessConfig) -> str:
    pip_index = "https://pypi.tuna.tsinghua.edu.cn/simple"
    if config.use_wsl:
        distro = f"-d {config.wsl_distro} " if config.wsl_distro else ""
        lines = [
            "1. Install and start Docker Desktop, then enable the WSL 2 backend.",
            "2. Create the SWE-bench harness environment inside WSL:",
            f"   wsl.exe {distro}-- bash -lc \"cd /mnt/d/localwork/EvaluationClaw && "
            "python3 -m venv .venv-swebench-wsl && "
            ". .venv-swebench-wsl/bin/activate && "
            f"python -m pip install swebench datasets -i {pip_index}\"",
            "3. If WSL needs the Windows proxy, expose it and set swebench_wsl_http_proxy:",
            "   python scripts/tcp_forward.py --listen-host 0.0.0.0 --listen-port 7891 "
            "--target-host 127.0.0.1 --target-port 7890",
            "   Then rerun with swebench_wsl_http_proxy=http://<WSL_GATEWAY>:7891.",
        ]
    else:
        lines = [
            "1. Install and start Docker Desktop:",
            "   winget install -e --id Docker.DockerDesktop",
            "2. Install the optional SWE-bench harness dependencies in this Python environment:",
            f"   python -m pip install swebench datasets -i {pip_index}",
        ]
    return "\n".join(lines)


def validate_swebench_environment_for_items(
    items: list[BenchmarkItem],
    config: BenchmarkConfig,
) -> None:
    """Preflight the SWE-bench runtime only when accepted items require it."""
    selected = swebench_items(items)
    if not selected or not config.run_targets or not config.targets:
        return

    harness_config = swebench_harness_config_from_items(selected, config)
    missing: list[str] = []

    docker = docker_status_wsl(harness_config) if harness_config.use_wsl else docker_status(
        executable=harness_config.docker_executable
    )
    if not docker.available:
        missing.append(f"Docker is not reachable: {docker.error}")

    try:
        if harness_config.use_wsl:
            ensure_swebench_harness_available_wsl(harness_config)
        else:
            ensure_swebench_harness_available(harness_config.python_executable)
    except RuntimeError as exc:
        missing.append(str(exc))

    if not missing:
        return

    details = "\n".join(f"- {line}" for line in missing)
    raise RuntimeError(
        "This benchmark contains SWE-bench item(s), but the SWE-bench runtime is not ready.\n\n"
        f"Detected item(s): {_format_swebench_item_list(selected)}\n\n"
        f"Missing:\n{details}\n\n"
        "Setup/configuration commands:\n"
        f"{_format_swebench_setup_commands(harness_config)}\n\n"
        "After configuring the environment, rerun the benchmark. EvaluationClaw does not install "
        "Docker, WSL components, or SWE-bench dependencies automatically during planning."
    )


def prepare_proxy_base_image(
    *,
    proxy_url: str,
    base_image: str = "sweb.base.py.x86_64:latest",
    docker_executable: str = "docker",
) -> SweBenchProxyBaseResult:
    """Inject proxy environment and conda proxy config into an existing SWE-bench base image."""
    if "\n" in proxy_url or "\r" in proxy_url:
        raise ValueError("proxy_url cannot contain newlines")
    if "\n" in base_image or "\r" in base_image:
        raise ValueError("base_image cannot contain newlines")
    resolved = resolve_docker_executable(docker_executable)
    if not resolved:
        raise RuntimeError(f"Docker executable '{docker_executable}' was not found.")
    env = docker_subprocess_env(docker_executable)
    inspect = subprocess.run(
        [resolved, "image", "inspect", base_image],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=60,
    )
    if inspect.returncode != 0:
        detail = (inspect.stderr or inspect.stdout).strip()
        raise RuntimeError(
            f"Base image {base_image!r} is not available. Build it with SWE-bench first. {detail}"
        )
    with tempfile.TemporaryDirectory(prefix="evalclaw_swebench_proxy_base_") as tmp:
        dockerfile = Path(tmp) / "Dockerfile"
        dockerfile.write_text(
            "\n".join(
                [
                    f"FROM {base_image}",
                    f"ENV HTTP_PROXY={proxy_url}",
                    f"ENV HTTPS_PROXY={proxy_url}",
                    f"ENV http_proxy={proxy_url}",
                    f"ENV https_proxy={proxy_url}",
                    "RUN printf 'proxy_servers:\\n"
                    f"  http: {proxy_url}\\n"
                    f"  https: {proxy_url}\\n' > /root/.condarc",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        command = [resolved, "build", "-t", base_image, tmp]
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
    return SweBenchProxyBaseResult(
        command=command,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        base_image=base_image,
        proxy_url=proxy_url,
    )


def build_run_evaluation_command(config: SweBenchHarnessConfig) -> list[str]:
    predictions_path = str(config.predictions_path)
    command = [
        config.python_executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        config.dataset_name,
        "--split",
        config.split,
        "--predictions_path",
        predictions_path,
        "--max_workers",
        str(config.max_workers),
        "--run_id",
        config.run_id,
    ]
    if config.instance_ids:
        command.extend(["--instance_ids", *config.instance_ids])
    if config.cache_level:
        command.extend(["--cache_level", config.cache_level])
    if config.clean is not None:
        command.extend(["--clean", str(config.clean)])
    if config.force_rebuild is not None:
        command.extend(["--force_rebuild", str(config.force_rebuild)])
    if config.timeout is not None:
        command.extend(["--timeout", str(config.timeout)])
    if config.namespace:
        command.extend(["--namespace", config.namespace])
    if config.instance_image_tag:
        command.extend(["--instance_image_tag", config.instance_image_tag])
    if config.env_image_tag:
        command.extend(["--env_image_tag", config.env_image_tag])
    command.extend(config.extra_args)
    return command


def _windows_path_to_wsl(path: str | Path) -> str:
    absolute = str(Path(path).resolve())
    if len(absolute) >= 3 and absolute[1] == ":" and absolute[2] in {"\\", "/"}:
        drive = absolute[0].lower()
        rest = absolute[2:].replace("\\", "/").lstrip("/")
        return f"/mnt/{drive}/{rest}"
    return absolute.replace("\\", "/")


def _wsl_base_command(config: SweBenchHarnessConfig) -> list[str]:
    command = ["wsl.exe"]
    if config.wsl_distro:
        command.extend(["-d", config.wsl_distro])
    command.extend(["--", "bash", "-lc"])
    return command


def _wsl_env_prefix(config: SweBenchHarnessConfig) -> str:
    exports = [
        f'export PATH={shlex.quote(config.wsl_docker_cli_dir)}:"$PATH"',
        f"export DOCKER_HOST={shlex.quote(config.wsl_docker_host)}",
    ]
    if config.wsl_http_proxy:
        proxy = shlex.quote(config.wsl_http_proxy)
        exports.extend(
            [
                f"export HTTP_PROXY={proxy}",
                f"export HTTPS_PROXY={proxy}",
                f"export http_proxy={proxy}",
                f"export https_proxy={proxy}",
            ]
        )
    return "\n".join(exports)


def _wsl_python_executable(config: SweBenchHarnessConfig) -> str:
    python_executable = config.python_executable
    if ("/" in python_executable or "\\" in python_executable) and not python_executable.startswith("/"):
        return _windows_path_to_wsl(python_executable)
    return python_executable


def _run_wsl_shell(config: SweBenchHarnessConfig, script: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    command = [*_wsl_base_command(config), script]
    return subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _wsl_inner_config(config: SweBenchHarnessConfig, output_dir: Path) -> SweBenchHarnessConfig:
    predictions_path = str(config.predictions_path)
    if predictions_path != "gold":
        predictions_path = _windows_path_to_wsl(predictions_path)
    python_executable = _wsl_python_executable(config)
    return SweBenchHarnessConfig(
        predictions_path=predictions_path,
        output_dir=_windows_path_to_wsl(output_dir),
        dataset_name=config.dataset_name,
        split=config.split,
        max_workers=config.max_workers,
        run_id=config.run_id,
        instance_ids=config.instance_ids,
        cache_level=config.cache_level,
        clean=config.clean,
        force_rebuild=config.force_rebuild,
        timeout=config.timeout,
        namespace=config.namespace,
        instance_image_tag=config.instance_image_tag,
        env_image_tag=config.env_image_tag,
        python_executable=python_executable,
        docker_executable="docker",
        use_wsl=False,
        wsl_http_proxy=config.wsl_http_proxy,
        extra_args=config.extra_args,
    )


def ensure_swebench_harness_available(python_executable: str = sys.executable) -> None:
    probe = subprocess.run(
        [
            python_executable,
            "-c",
            "import swebench.harness.run_evaluation",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip()
        raise RuntimeError(
            "The official SWE-bench harness is not available in this Python environment. "
            "Install the optional SWE-bench dependencies first, for example: "
            "python -m pip install 'evaluationclaw[swebench]' "
            "or python -m pip install swebench datasets. "
            f"Import error: {detail}"
        )


def ensure_swebench_harness_available_wsl(config: SweBenchHarnessConfig) -> None:
    script = "\n".join(
        [
            "set -e",
            _wsl_env_prefix(config),
            f"{shlex.quote(_wsl_python_executable(config))} -c 'import swebench.harness.run_evaluation'",
        ]
    )
    probe = _run_wsl_shell(config, script, timeout=120)
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip()
        raise RuntimeError(
            "The official SWE-bench harness is not available in the configured WSL "
            "Python environment. Install it inside WSL first, for example: "
            "python3 -m venv .venv-swebench-wsl && "
            ". .venv-swebench-wsl/bin/activate && "
            "python -m pip install swebench datasets. "
            f"Import error: {detail}"
        )


def docker_status_wsl(config: SweBenchHarnessConfig) -> DockerStatus:
    script = "\n".join(
        [
            "set -e",
            _wsl_env_prefix(config),
            "docker version --format 'client={{.Client.Version}} server={{.Server.Version}}'",
        ]
    )
    probe = _run_wsl_shell(config, script, timeout=60)
    stdout = probe.stdout.strip()
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "Docker daemon is not reachable from WSL.").strip()
        return DockerStatus(
            available=False,
            executable="wsl:docker",
            error=detail,
        )
    client_version = ""
    server_version = ""
    for part in stdout.split():
        if part.startswith("client="):
            client_version = part.removeprefix("client=")
        elif part.startswith("server="):
            server_version = part.removeprefix("server=")
    return DockerStatus(
        available=bool(server_version),
        executable="wsl:docker",
        client_version=client_version,
        server_version=server_version,
        error="" if server_version else stdout,
    )


def run_swebench_harness_wsl(
    config: SweBenchHarnessConfig,
    output_dir: Path,
) -> SweBenchHarnessResult:
    inner_config = _wsl_inner_config(config, output_dir)
    inner_command = build_run_evaluation_command(inner_config)
    wsl_output_dir = str(inner_config.output_dir)
    script = "\n".join(
        [
            "set -e",
            _wsl_env_prefix(config),
            f"mkdir -p {shlex.quote(wsl_output_dir)}",
            f"cd {shlex.quote(wsl_output_dir)}",
            f"exec {shlex.join(inner_command)}",
        ]
    )
    command = [*_wsl_base_command(config), script]
    proc = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return SweBenchHarnessResult(
        command=command,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        output_dir=output_dir,
        docker=None,
    )


def run_swebench_harness(
    config: SweBenchHarnessConfig,
    *,
    check_docker: bool = True,
    check_harness: bool = True,
) -> SweBenchHarnessResult:
    """Run the official SWE-bench harness with Docker-first validation."""
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    docker: DockerStatus | None = None
    if check_docker:
        docker = docker_status_wsl(config) if config.use_wsl else docker_status(executable=config.docker_executable)
        if not docker.available:
            raise RuntimeError(
                "SWE-bench execution requires Docker for reliable full benchmark runs. "
                f"{docker.error}"
            )
    if check_harness:
        if config.use_wsl:
            ensure_swebench_harness_available_wsl(config)
        else:
            ensure_swebench_harness_available(config.python_executable)

    if config.use_wsl:
        result = run_swebench_harness_wsl(config, output_dir)
        return SweBenchHarnessResult(
            command=result.command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            output_dir=result.output_dir,
            docker=docker,
        )

    command = build_run_evaluation_command(config)
    proc = subprocess.run(
        command,
        cwd=output_dir,
        text=True,
        capture_output=True,
        check=False,
        env=docker_subprocess_env(config.docker_executable),
    )
    return SweBenchHarnessResult(
        command=command,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        output_dir=output_dir,
        docker=docker,
    )
