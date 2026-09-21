"""Acquire container images through explicitly configured registry mirrors.

Downloads run on the host through crane so HTTP(S)_PROXY applies without
changing the system Docker daemon. Container startup never fetches implicitly
when this policy is enabled.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .docker import docker_subprocess_env, resolve_docker_executable
from .errors import EvaluationExecutionError
from .process import run_bounded
from .registry_errors import inspect_registry_failure

MIRRORS_ENV = "EVALCLAW_DOCKER_MIRRORS"
ROUTES_ENV = "EVALCLAW_IMAGE_ROUTES"


class ImageAcquisitionError(EvaluationExecutionError):
    """Image acquisition failed; preserve the per-source diagnostic evidence."""

    def __init__(self, message: str, *, image: str = "", failures: list[dict] | None = None):
        super().__init__(message)
        self.image = image
        self.failures = failures or []


class ImageReferenceError(ImageAcquisitionError):
    """A registry reports an unusable reference; repair only during authoring."""


def mirror_hosts(mirrors: list[str]) -> list[str]:
    hosts = []
    for mirror in mirrors:
        parsed = urlsplit(mirror if "://" in mirror else "https://" + mirror)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ImageAcquisitionError(
                "Docker mirrors must be HTTPS registry hosts, without paths or credentials."
            )
        hosts.append(parsed.netloc.lower())
    return list(dict.fromkeys(hosts))


def configured_mirrors() -> list[str]:
    return mirror_hosts([part.strip() for part in os.environ.get(MIRRORS_ENV, "").split(",") if part.strip()])


def canonical_image(image: str, mirrors: list[str] | None = None) -> str:
    """Normalize registry aliases explicitly declared as Docker Hub mirrors."""
    hosts = configured_mirrors() if mirrors is None else mirror_hosts(mirrors)
    first, separator, rest = image.strip().partition("/")
    if separator and ("." in first or ":" in first or first == "localhost"):
        host, repository = first, rest
    else:
        host, repository = "docker.io", image.strip()
    if host in {"index.docker.io", "registry-1.docker.io", *hosts}:
        host = "docker.io"
    if host == "docker.io" and "/" not in repository:
        repository = "library/" + repository
    if ":" not in repository.rsplit("/", 1)[-1] and "@" not in repository:
        repository += ":latest"
    return host + "/" + repository


def mirror_sources(image: str, mirrors: list[str]) -> list[str]:
    hosts = mirror_hosts(mirrors)
    reference = canonical_image(image, hosts)
    host, repository = reference.split("/", 1)
    if host != "docker.io":
        return [image]
    return [host + "/" + repository for host in hosts]


def image_source_env(source: str, env: dict[str, str]) -> dict[str, str]:
    """Apply an explicit route to one registry operation, including its redirects."""
    try:
        routes = json.loads(env.get(ROUTES_ENV, "{}"))
        if not isinstance(routes, dict) or any(v not in {"direct", "environment"} for v in routes.values()):
            raise ValueError("expected registry hosts mapped to direct or environment")
        for host in routes:
            if mirror_hosts([host]) != [host]:
                raise ValueError("route keys must be registry host names")
    except (ValueError, TypeError) as exc:
        raise ImageAcquisitionError(f"Invalid {ROUTES_ENV}: {exc}") from exc
    if routes.get(source.split("/", 1)[0]) == "direct":
        return {k: v for k, v in env.items() if k.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}}
    return dict(env)


def image_pull_options() -> list[str]:
    return ["--pull", "never"] if os.environ.get(MIRRORS_ENV, "").strip() else []


def normalize_platform(platform: str) -> str:
    parts = platform.lower().split("/")
    if len(parts) not in {2, 3} or not all(parts):
        raise ValueError(f"Expected os/architecture[/variant], got {platform!r}")
    parts[1] = {"x86_64": "amd64", "aarch64": "arm64"}.get(parts[1], parts[1])
    if parts[1:] == ["arm64", "v8"]:
        parts.pop()
    return "/".join(parts)


def acquire_image(
    image: str, *, docker_executable: str = "docker", timeout_s: int = 300, allow_pull: bool = True,
    platform: str | None = None, import_timeout_s: int = 1800,
) -> str:
    """Return a local image reference; preserve legacy behavior without a policy.

    Pinned digests are downloaded unchanged and cached under a deterministic local
    tag because docker load does not preserve registry RepoDigests.
    timeout_s applies to registry operations; import_timeout_s allows local
    unpacking to wait for storage independently of network transfer.
    """
    mirrors = configured_mirrors()
    if not mirrors:
        return image
    if platform:
        platform = normalize_platform(platform)
    docker = resolve_docker_executable(docker_executable)
    if not docker:
        raise ImageAcquisitionError("Docker executable is unavailable for image acquisition.")
    env = docker_subprocess_env(docker_executable)

    def local(reference):
        command = [docker, "image", "inspect", reference]
        if platform:
            command.extend(["--format", "{{.Os}}/{{.Architecture}}{{if .Variant}}/{{.Variant}}{{end}}"])
        result = run_bounded(command, timeout=30, env=env)
        return result.returncode == 0 and (not platform or normalize_platform(result.stdout.strip()) == platform)

    def checked(args, *, timeout=timeout_s):
        result = run_bounded(args, timeout=timeout, env=env)
        if result.returncode:
            raise ImageAcquisitionError(
                f"Image acquisition failed: {result.stderr or result.stdout}"
            )
        return result

    import fcntl

    canonical = canonical_image(image, mirrors)
    key = hashlib.sha256((canonical + ("\0" + platform if platform else "")).encode()).hexdigest()
    state = Path("/tmp") / f"evalclaw-image-locks-{os.getuid()}"
    state.mkdir(mode=0o700, exist_ok=True)
    with (state / key).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if local(image):
                return image
            if canonical != image and local(canonical):
                return canonical
            cached = f"evalclaw-pinned:{key}" if "@" in image or platform else image
            if cached != image and local(cached):
                return cached
            if not allow_pull:
                raise ImageAcquisitionError(
                    f"Image {image!r} is missing locally and pull_image=false."
                )
            crane = shutil.which(os.environ.get("EVALCLAW_CRANE_EXECUTABLE", "crane"))
            if not crane:
                raise ImageAcquisitionError(
                    "Configured Docker mirrors require crane; set EVALCLAW_CRANE_EXECUTABLE."
                )
            # A missing local image and an unavailable daemon both make inspect
            # fail. Confirm Docker health before diagnosing registry references.
            info = json.loads(checked([docker, "info", "--format", "{{json .}}"]).stdout)
            pull_platform = platform
            if not pull_platform:
                architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(info["Architecture"], info["Architecture"])
                pull_platform = f"{info['OSType']}/{architecture}"
            failures = []
            with tempfile.TemporaryDirectory(prefix="evalclaw-image-") as directory:
                archive = Path(directory) / "image.tar"
                for source in mirror_sources(image, mirrors):
                    source_env = image_source_env(source, env)
                    print(f"[docker image] Fetching {source} ({pull_platform}).", flush=True)
                    try:
                        result = run_bounded(
                            [crane, "pull", "--platform", pull_platform, source, str(archive)],
                            timeout=timeout_s,
                            env=source_env,
                        )
                    except subprocess.TimeoutExpired:
                        failures.append({"source": source, "kind": "timeout", "status": None,
                                         "codes": [], "detail": f"timed out after {timeout_s}s"})
                        continue
                    if result.returncode:
                        failures.append({"source": source, "kind": "unknown", "status": None,
                                         "codes": [], "exit_code": result.returncode,
                                         "detail": (result.stderr or result.stdout)[-1500:]})
                        continue
                    # Assign the local name in the archive itself. Docker's
                    # containerd image store uses manifest IDs, whereas the
                    # classic store uses config IDs; neither needs guessing.
                    imported = Path(directory) / "import.tar"
                    with tarfile.open(archive) as tar:
                        manifest = json.load(tar.extractfile("manifest.json"))
                        if len(manifest) != 1:
                            raise ImageAcquisitionError(
                                "Expected one platform image in the downloaded archive."
                            )
                        manifest[0]["RepoTags"] = list(dict.fromkeys(
                            [cached] if "@" in image or platform else [image, canonical]
                        ))
                        content = json.dumps(manifest).encode()
                        with tarfile.open(imported, "w") as output:
                            for member in tar:
                                if member.name == "manifest.json":
                                    member.size = len(content)
                                    output.addfile(member, io.BytesIO(content))
                                else:
                                    output.addfile(
                                        member, tar.extractfile(member) if member.isfile() else None
                                    )
                    # Local unpacking competes for disk I/O independently of registry transfer.
                    checked([docker, "load", "-i", str(imported)], timeout=import_timeout_s)
                    if not local(cached):
                        raise ImageAcquisitionError(f"Image import did not materialize {cached!r}.")
                    print(
                        f"[docker image] Acquired {image} from {source}; local reference {cached}.",
                        flush=True,
                    )
                    return cached
            # Only diagnose once every transfer failed; a working fallback does
            # not need additional network calls. A killed downloader is not a
            # registry reference error.
            for failure in failures:
                if failure.get("exit_code", 0) > 0:
                    failure.update(inspect_registry_failure(
                        failure["source"], image_source_env(failure["source"], env), timeout_s,
                    ))
            # Missing references mixed with mirror permission failures can be
            # returned to the author without claiming global nonexistence. An
            # unknown/transport/service failure is not evidence to rewrite a task.
            repairable = any(f["kind"] == "reference" for f in failures) and all(
                f["kind"] in {"reference", "permission"} for f in failures
            )
            error = ImageReferenceError if repairable else ImageAcquisitionError
            raise error(
                f"All attempted image sources failed for {image!r}; no direct Docker Hub fallback.\n"
                + json.dumps(failures, ensure_ascii=False), image=image, failures=failures,
            )
        except (OSError, subprocess.SubprocessError, ValueError, tarfile.TarError) as exc:
            raise ImageAcquisitionError(f"Could not acquire image {image!r}: {exc}") from exc
