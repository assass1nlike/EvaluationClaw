"""Docker image selection and lightweight image preflight helpers."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .docker import docker_subprocess_env, resolve_docker_executable
from .installers import apt_packages, render_install_commands

DEFAULT_DOCKER_IMAGE = "python:3.11-slim"
DOCKER_IMAGE_SELECTION_STRATEGY = "evalclaw_builtin_rules.v1"
DOCKER_IMAGE_BUILD_STRATEGY = "evalclaw_dockerfile_build.v1"
DOCKER_BUILD_AUTO_IMAGES = {"build://auto", "auto://build", "evalclaw:build"}
DOCKER_BUILD_DIR_ENV_VAR = "EVALCLAW_DOCKER_BUILD_DIR"
DOCKER_HTTP_PROXY_ENV_VAR = "EVALCLAW_DOCKER_HTTP_PROXY"
DOCKER_HTTPS_PROXY_ENV_VAR = "EVALCLAW_DOCKER_HTTPS_PROXY"
DOCKER_NO_PROXY_ENV_VAR = "EVALCLAW_DOCKER_NO_PROXY"


@dataclass(frozen=True)
class DockerImageSelection:
    image: str
    reason: str
    confidence: float = 0.0
    explicit: bool = False
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DockerImageProbe:
    image: str
    local: bool
    detail: str = ""


@dataclass(frozen=True)
class DockerImageBuildResult:
    image: str
    built: bool
    dockerfile: str
    context_dir: str = ""
    detail: str = ""
    commands: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _ImageRule:
    image: str
    reason: str
    patterns: tuple[str, ...]
    confidence: float


_IMAGE_RULES: tuple[_ImageRule, ...] = (
    _ImageRule(
        image="node:22-bookworm-slim",
        reason="JavaScript/TypeScript or npm-style project.",
        patterns=(
            r"\bpackage\.json\b",
            r"\bpackage-lock\.json\b",
            r"\byarn\.lock\b",
            r"\bpnpm-lock\.yaml\b",
            r"\btsconfig\.json\b",
            r"\b(vite|webpack|eslint|jest|vitest|npm|pnpm|yarn|node)\b",
            r"\.(mjs|cjs|jsx|tsx|ts|js)\b",
        ),
        confidence=0.92,
    ),
    _ImageRule(
        image="rust:1.85-slim",
        reason="Rust/Cargo project.",
        patterns=(r"\bCargo\.toml\b", r"\bCargo\.lock\b", r"\bcargo\s+(test|build|run)\b", r"\.rs\b"),
        confidence=0.9,
    ),
    _ImageRule(
        image="golang:1.23-bookworm",
        reason="Go module or go test task.",
        patterns=(r"\bgo\.mod\b", r"\bgo\.sum\b", r"\bgo\s+test\b", r"\.go\b"),
        confidence=0.9,
    ),
    _ImageRule(
        image="maven:3.9-eclipse-temurin-21",
        reason="Maven/Java project.",
        patterns=(r"\bpom\.xml\b", r"\bmvn\s+test\b", r"\bsrc/main/java\b", r"\.java\b"),
        confidence=0.88,
    ),
    _ImageRule(
        image="gradle:8-jdk21",
        reason="Gradle/Java or Kotlin project.",
        patterns=(r"\bbuild\.gradle\b", r"\bsettings\.gradle\b", r"\bgradle(w)?\b", r"\.kt\b"),
        confidence=0.86,
    ),
    _ImageRule(
        image="ruby:3.3-slim",
        reason="Ruby/Bundler project.",
        patterns=(r"\bGemfile\b", r"\bgemspec\b", r"\bbundle\s+exec\b", r"\bruby\b", r"\.rb\b"),
        confidence=0.84,
    ),
    _ImageRule(
        image="php:8.3-cli",
        reason="PHP CLI or Composer project.",
        patterns=(r"\bcomposer\.json\b", r"\bcomposer\.lock\b", r"\bphpunit\b", r"\.php\b"),
        confidence=0.84,
    ),
    _ImageRule(
        image="gcc:14-bookworm",
        reason="C/C++ build task.",
        patterns=(r"\bCMakeLists\.txt\b", r"\bMakefile\b", r"\b(gcc|g\+\+|cmake|make)\b", r"\.(c|cc|cpp|h|hpp)\b"),
        confidence=0.82,
    ),
    _ImageRule(
        image="r-base:4.4.1",
        reason="R/Rscript task.",
        patterns=(r"\bRscript\b", r"\bDESCRIPTION\b", r"\brenv\.lock\b", r"\.R\b"),
        confidence=0.82,
    ),
    _ImageRule(
        image="python:3.11-slim",
        reason="Python source, pytest, pip, or pyproject task.",
        patterns=(
            r"\b(pytest|python3?|pip|requirements\.txt|pyproject\.toml|setup\.py|tox\.ini)\b",
            r"\.py\b",
        ),
        confidence=0.8,
    ),
    _ImageRule(
        image="ubuntu:22.04",
        reason="General Linux shell task that benefits from Ubuntu userland.",
        patterns=(r"\b(apt-get|apt|bash|shell|linux|ubuntu|dpkg)\b", r"\.sh\b"),
        confidence=0.62,
    ),
)


def _compact_text(value: Any, *, limit: int = 1200) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit]


def docker_image_selection_context(env_config: dict[str, Any], *, task_text: str = "") -> str:
    """Build a compact text context for deterministic image selection."""
    parts: list[str] = [_compact_text(task_text, limit=2000)]
    for key in ("test_command", "setup_commands", "notes", "image_requirements"):
        value = env_config.get(key)
        if isinstance(value, list):
            parts.extend(_compact_text(item) for item in value)
        elif value:
            parts.append(_compact_text(value))
    for key in ("visible_files", "files", "hidden_files"):
        files = env_config.get(key)
        if not isinstance(files, dict):
            continue
        for path, content in list(files.items())[:40]:
            parts.append(str(path))
            parts.append(_compact_text(content, limit=700))
    return "\n".join(part for part in parts if part)


def select_docker_image(
    env_config: dict[str, Any] | None = None,
    *,
    task_text: str = "",
    preserve_explicit: bool = True,
) -> DockerImageSelection:
    """Select a Docker Hub/runtime image from task evidence.

    Explicit non-auto image names are preserved by default. Use
    ``auto_select_image=true`` with image omitted, empty, or ``"auto"`` to let
    EvaluationClaw choose from the built-in official-runtime catalog.
    """
    env = env_config or {}
    image = str(env.get("image") or "").strip()
    auto_requested = bool(env.get("auto_select_image", True))
    explicit_auto = image.lower() in {"", "auto", "auto://dockerhub", "evalclaw:auto"}
    if image and not explicit_auto and preserve_explicit:
        return DockerImageSelection(
            image=image,
            reason="Task supplied an explicit Docker image.",
            confidence=1.0,
            explicit=True,
            evidence=["explicit image"],
        )
    if not auto_requested:
        return DockerImageSelection(
            image=image or DEFAULT_DOCKER_IMAGE,
            reason="Docker image auto-selection is disabled for this task.",
            confidence=1.0,
            explicit=True,
            evidence=["auto_select_image=false"],
        )

    context = docker_image_selection_context(env, task_text=task_text)
    best: tuple[float, _ImageRule, list[str]] | None = None
    for rule in _IMAGE_RULES:
        evidence = []
        score = 0.0
        for pattern in rule.patterns:
            if re.search(pattern, context, flags=re.IGNORECASE):
                evidence.append(pattern)
                score += 1.0
        if not evidence:
            continue
        weighted_score = score * rule.confidence
        if best is None or weighted_score > best[0]:
            best = (weighted_score, rule, evidence[:6])

    if best is None:
        return DockerImageSelection(
            image=DEFAULT_DOCKER_IMAGE,
            reason="No stronger runtime evidence found; using the Python default image.",
            confidence=0.45,
            evidence=[],
        )
    _, rule, evidence = best
    return DockerImageSelection(
        image=rule.image,
        reason=rule.reason,
        confidence=rule.confidence,
        evidence=evidence,
    )


def apply_docker_image_selection(
    env_config: dict[str, Any],
    *,
    task_text: str = "",
    preserve_explicit: bool = True,
) -> tuple[dict[str, Any], DockerImageSelection]:
    """Return a docker_workspace env config with image selection metadata."""
    env = dict(env_config)
    selection = select_docker_image(env, task_text=task_text, preserve_explicit=preserve_explicit)
    env["image"] = selection.image
    image_build = env.get("image_build")
    if _image_build_requested(env_config):
        build_config = image_build if isinstance(image_build, dict) else {}
        if not str(build_config.get("base_image") or "").strip():
            build_base = select_docker_image({**env, "image": ""}, task_text=task_text, preserve_explicit=False)
            build_config = {**build_config, "base_image": build_base.image}
        env["image"] = str(env_config.get("image") or "").strip() or "build://auto"
        env["image_build"] = {**build_config, "enabled": True}
    env.setdefault("pull_image", True)
    env.setdefault("pull_timeout", 300)
    env["image_selection"] = {
        "strategy": DOCKER_IMAGE_SELECTION_STRATEGY,
        "image": selection.image,
        "reason": selection.reason,
        "confidence": selection.confidence,
        "explicit": selection.explicit,
        "evidence": selection.evidence,
    }
    return env, selection


def _image_build_requested(env_config: dict[str, Any] | None) -> bool:
    env = env_config or {}
    image = str(env.get("image") or "").strip().lower()
    build_config = env.get("image_build")
    return image in DOCKER_BUILD_AUTO_IMAGES or (isinstance(build_config, dict) and bool(build_config.get("enabled")))


def docker_image_build_requested(env_config: dict[str, Any] | None) -> bool:
    return _image_build_requested(env_config)


def _docker_tag_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_.-]+", "-", value.lower()).strip("-._")
    return slug[:40] or "task"


def _safe_context_path(raw_path: str) -> str:
    path = raw_path.strip().replace("\\", "/")
    if not path or "\x00" in path:
        raise ValueError("Docker build context path is empty or invalid.")
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"Unsafe Docker build context path: {raw_path}")
    return str(pure)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _package_list(value: Any) -> list[str]:
    packages = []
    for package in _string_list(value):
        packages.extend(part for part in re.split(r"\s+", package) if part)
    return packages


def _default_base_image(env_config: dict[str, Any], *, task_text: str = "") -> str:
    build_config = env_config.get("image_build") if isinstance(env_config.get("image_build"), dict) else {}
    base = str(build_config.get("base_image") or "").strip()
    if base:
        return base
    image = str(env_config.get("image") or "").strip()
    if image and image.lower() not in DOCKER_BUILD_AUTO_IMAGES:
        return image
    return select_docker_image({**env_config, "image": ""}, task_text=task_text, preserve_explicit=False).image


def _render_dockerfile(env_config: dict[str, Any], *, task_text: str = "") -> str:
    build_config = env_config.get("image_build") if isinstance(env_config.get("image_build"), dict) else {}
    explicit = str(build_config.get("dockerfile") or "").strip()
    if explicit:
        return explicit + ("\n" if not explicit.endswith("\n") else "")

    base_image = _default_base_image(env_config, task_text=task_text)
    system_packages = apt_packages(build_config)
    commands = render_install_commands(build_config)
    lines = [
        f"FROM {base_image}",
        "WORKDIR /workspace",
        "ENV PYTHONDONTWRITEBYTECODE=1",
    ]
    if system_packages:
        packages = " ".join(shlex.quote(package) for package in system_packages)
        lines.append(
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            f"{packages} && rm -rf /var/lib/apt/lists/*"
        )
    for command in commands:
        lines.append(f"RUN {command}")
    return "\n".join(lines) + "\n"


def _build_context_root() -> Path:
    configured = str(os.environ.get(DOCKER_BUILD_DIR_ENV_VAR) or "").strip()
    if configured:
        root = Path(configured).expanduser()
    elif os.name == "nt" and Path(r"D:\localwork").exists():
        root = Path(r"D:\localwork\docker_builds")
    else:
        root = Path(tempfile.gettempdir()) / "evalclaw-docker-builds"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_context_files(context_dir: Path, files: Any) -> None:
    if not isinstance(files, dict):
        return
    for raw_path, content in files.items():
        if not isinstance(raw_path, str):
            continue
        clean = _safe_context_path(raw_path)
        target = context_dir / clean
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(str(content), encoding="utf-8")


def _docker_build_args(build_config: dict[str, Any]) -> dict[str, str]:
    """Return explicit docker build args, including proxy args when configured."""
    args: dict[str, str] = {}
    configured = build_config.get("build_args") or build_config.get("args")
    if isinstance(configured, dict):
        args.update({str(key): str(value) for key, value in configured.items() if str(value).strip()})

    proxy_values = {
        "HTTP_PROXY": os.environ.get(DOCKER_HTTP_PROXY_ENV_VAR) or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"),
        "HTTPS_PROXY": os.environ.get(DOCKER_HTTPS_PROXY_ENV_VAR) or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"),
        "NO_PROXY": os.environ.get(DOCKER_NO_PROXY_ENV_VAR) or os.environ.get("NO_PROXY") or os.environ.get("no_proxy"),
    }
    for key, value in proxy_values.items():
        if not value:
            continue
        args.setdefault(key, value)
        args.setdefault(key.lower(), value)
    return args


def _build_tag(env_config: dict[str, Any], dockerfile: str, *, task_text: str = "") -> str:
    build_config = env_config.get("image_build") if isinstance(env_config.get("image_build"), dict) else {}
    explicit_tag = str(build_config.get("tag") or build_config.get("image") or "").strip()
    if explicit_tag:
        return explicit_tag
    digest_payload = {
        "dockerfile": dockerfile,
        "context_files": build_config.get("context_files") or build_config.get("build_context_files") or {},
        "task_text": task_text[:2000],
    }
    digest = hashlib.sha256(json.dumps(digest_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
    slug = _docker_tag_slug(str(build_config.get("name") or env_config.get("id") or "agent-task"))
    return f"evalclaw-{slug}:{digest}"


def build_docker_image_if_requested(
    env_config: dict[str, Any],
    *,
    task_text: str = "",
    docker_executable: str = "docker",
    timeout_s: int = 600,
) -> tuple[dict[str, Any], DockerImageBuildResult | None]:
    """Build a task-specific Docker image when image_build is requested."""
    if not _image_build_requested(env_config):
        return env_config, None
    env = dict(env_config)
    build_config = env.get("image_build") if isinstance(env.get("image_build"), dict) else {}
    dockerfile = _render_dockerfile(env, task_text=task_text)
    tag = _build_tag(env, dockerfile, task_text=task_text)
    resolved = resolve_docker_executable(docker_executable)
    if not resolved:
        raise RuntimeError(f"Docker executable {docker_executable!r} not found; cannot build task image {tag}.")

    rebuild = bool(build_config.get("rebuild"))
    if not rebuild:
        probe = inspect_docker_image(tag, docker_executable=docker_executable, timeout_s=15)
        if probe.local:
            env["image"] = tag
            env["pull_image"] = False
            env["image_build"] = {
                **build_config,
                "enabled": True,
                "strategy": DOCKER_IMAGE_BUILD_STRATEGY,
                "base_image": _default_base_image(env, task_text=task_text),
                "tag": tag,
                "dockerfile": dockerfile,
                "built": False,
                "detail": "Image already exists locally.",
            }
            return env, DockerImageBuildResult(image=tag, built=False, dockerfile=dockerfile, detail="Image already exists locally.")

    context_root = _build_context_root()
    context_dir = context_root / _docker_tag_slug(tag.replace(":", "-"))
    context_dir.mkdir(parents=True, exist_ok=True)
    dockerfile_path = context_dir / "Dockerfile"
    dockerfile_path.write_text(dockerfile, encoding="utf-8")
    _write_context_files(
        context_dir,
        build_config.get("context_files") or build_config.get("build_context_files"),
    )
    command = [resolved, "build"]
    for key, value in _docker_build_args(build_config).items():
        command.extend(["--build-arg", f"{key}={value}"])
    command.extend(["-t", tag, str(context_dir)])
    proc = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=max(1, timeout_s),
        env=docker_subprocess_env(docker_executable),
    )
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"Docker build failed for {tag}: {output}")
    env["image"] = tag
    env["pull_image"] = False
    env["image_build"] = {
        **build_config,
        "enabled": True,
        "strategy": DOCKER_IMAGE_BUILD_STRATEGY,
        "base_image": _default_base_image(env, task_text=task_text),
        "tag": tag,
        "dockerfile": dockerfile,
        "context_dir": str(context_dir),
        "built": True,
        "detail": output[-1000:],
    }
    return env, DockerImageBuildResult(
        image=tag,
        built=True,
        dockerfile=dockerfile,
        context_dir=str(context_dir),
        detail=output[-1000:],
        commands=[" ".join(command)],
    )


def inspect_docker_image(
    image: str,
    *,
    docker_executable: str = "docker",
    timeout_s: int = 15,
) -> DockerImageProbe:
    """Check whether an image is already present locally."""
    resolved = resolve_docker_executable(docker_executable)
    if not resolved:
        return DockerImageProbe(image=image, local=False, detail=f"Docker executable {docker_executable!r} not found.")
    try:
        proc = subprocess.run(
            [resolved, "image", "inspect", image],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=max(1, timeout_s),
            env=docker_subprocess_env(docker_executable),
        )
    except Exception as exc:
        return DockerImageProbe(image=image, local=False, detail=str(exc))
    if proc.returncode == 0:
        return DockerImageProbe(image=image, local=True, detail="Image is available locally.")
    detail = (proc.stderr or proc.stdout or "Image is not available locally.").strip()
    return DockerImageProbe(image=image, local=False, detail=detail)
