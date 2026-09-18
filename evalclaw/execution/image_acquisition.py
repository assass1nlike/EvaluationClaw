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

MIRRORS_ENV = "EVALCLAW_DOCKER_MIRRORS"


class ImageAcquisitionError(EvaluationExecutionError):
    """Image infrastructure is unavailable; do not rewrite the task to repair it."""


def mirror_sources(image: str, mirrors: list[str]) -> list[str]:
    repository = image
    first, separator, rest = image.partition("/")
    if first in {"docker.io", "index.docker.io", "registry-1.docker.io"}:
        repository = rest
    elif separator and ("." in first or ":" in first or first == "localhost"):
        return [image]
    if "/" not in repository:
        repository = "library/" + repository
    sources = []
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
        sources.append(parsed.netloc + "/" + repository)
    return sources


def image_pull_options() -> list[str]:
    return ["--pull", "never"] if os.environ.get(MIRRORS_ENV, "").strip() else []


def acquire_image(
    image: str, *, docker_executable: str = "docker", timeout_s: int = 300, allow_pull: bool = True
) -> str:
    """Return a local image reference; preserve legacy behavior without a policy.

    Pinned digests are downloaded unchanged and cached under a deterministic local
    tag because docker load does not preserve registry RepoDigests.
    """
    mirrors = [part.strip() for part in os.environ.get(MIRRORS_ENV, "").split(",") if part.strip()]
    if not mirrors:
        return image
    docker = resolve_docker_executable(docker_executable)
    if not docker:
        raise ImageAcquisitionError("Docker executable is unavailable for image acquisition.")
    env = docker_subprocess_env(docker_executable)

    def local(reference):
        result = run_bounded([docker, "image", "inspect", reference], timeout=30, env=env)
        return result.returncode == 0

    def checked(args):
        result = run_bounded(args, timeout=timeout_s, env=env)
        if result.returncode:
            raise ImageAcquisitionError(
                f"Image acquisition failed: {result.stderr or result.stdout}"
            )
        return result

    import fcntl

    key = hashlib.sha256(image.encode()).hexdigest()
    state = Path("/tmp") / f"evalclaw-image-locks-{os.getuid()}"
    state.mkdir(mode=0o700, exist_ok=True)
    with (state / key).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if local(image):
                return image
            cached = f"evalclaw-pinned:{key}" if "@" in image else image
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
            info = json.loads(checked([docker, "info", "--format", "{{json .}}"]).stdout)
            architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(
                info["Architecture"], info["Architecture"]
            )
            platform = f"{info['OSType']}/{architecture}"
            failures = []
            with tempfile.TemporaryDirectory(prefix="evalclaw-image-") as directory:
                archive = Path(directory) / "image.tar"
                for source in mirror_sources(image, mirrors):
                    print(f"[docker image] Fetching {source} ({platform}).", flush=True)
                    try:
                        result = run_bounded(
                            [crane, "pull", "--platform", platform, source, str(archive)],
                            timeout=timeout_s,
                            env=env,
                        )
                    except subprocess.TimeoutExpired:
                        failures.append(f"{source}: timed out after {timeout_s}s")
                        continue
                    if result.returncode:
                        failures.append(f"{source}: {(result.stderr or result.stdout)[-1500:]}")
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
                        manifest[0]["RepoTags"] = [cached]
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
                    checked([docker, "load", "-i", str(imported)])
                    if not local(cached):
                        raise ImageAcquisitionError(f"Image import did not materialize {cached!r}.")
                    print(
                        f"[docker image] Acquired {image} from {source}; local reference {cached}.",
                        flush=True,
                    )
                    return cached
            raise ImageAcquisitionError(
                "All configured image sources failed; Docker Hub direct fallback is disabled.\n"
                + "\n".join(failures)
            )
        except (OSError, subprocess.SubprocessError, ValueError, tarfile.TarError) as exc:
            raise ImageAcquisitionError(f"Could not acquire image {image!r}: {exc}") from exc
