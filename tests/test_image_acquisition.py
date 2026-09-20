from __future__ import annotations

import io
import json
import subprocess
import tarfile
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from evalclaw.execution import image_acquisition as acquisition


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setenv(
        acquisition.MIRRORS_ENV, "https://first.example/,second.example,third.example"
    )
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setattr(acquisition, "resolve_docker_executable", lambda _: "/docker")
    monkeypatch.setattr(acquisition.shutil, "which", lambda _: "/crane")
    images, calls, failures = set(), [], []

    def run(args, *, timeout, env):
        calls.append(args)
        code, output = 0, ""
        if args[1:3] == ["image", "inspect"]:
            code = 0 if args[3] in images else 1
            if "--format" in args and code == 0:
                output = "linux/amd64"
        elif args[1] == "info":
            output = json.dumps({"OSType": "linux", "Architecture": "x86_64"})
        elif args[0] == "/crane":
            assert env["HTTPS_PROXY"] == "http://127.0.0.1:7890"
            if failures:
                failure = failures.pop(0)
                if failure == "timeout":
                    raise subprocess.TimeoutExpired(args, timeout)
                code = 1
            else:
                config = b'{"architecture":"amd64","os":"linux"}'
                manifest = json.dumps(
                    [{"Config": "config.json", "RepoTags": [], "Layers": []}]
                ).encode()
                with tarfile.open(args[-1], "w") as tar:
                    for name, data in [("manifest.json", manifest), ("config.json", config)]:
                        member = tarfile.TarInfo(name)
                        member.size = len(data)
                        tar.addfile(member, io.BytesIO(data))
        elif args[1] == "load":
            with tarfile.open(args[-1]) as tar:
                manifest = json.load(tar.extractfile("manifest.json"))
                images.update(manifest[0]["RepoTags"])
                assert (
                    tar.extractfile("config.json").read()
                    == b'{"architecture":"amd64","os":"linux"}'
                )
        else:
            pytest.fail(f"Unexpected Docker operation: {args}")
        return subprocess.CompletedProcess(
            args, code, output, "registry unavailable" if code else ""
        )

    monkeypatch.setattr(acquisition, "run_bounded", run)
    return images, calls, failures


@pytest.mark.parametrize(
    ("reference", "repository"),
    [
        ("node:20", "library/node:20"),
        ("docker.io/node:20", "library/node:20"),
        ("index.docker.io/library/node:20", "library/node:20"),
        ("org/project:1", "org/project:1"),
        ("node@sha256:abc", "library/node@sha256:abc"),
    ],
)
def test_hub_reference_mapping(reference, repository):
    assert acquisition.mirror_sources(reference, ["https://mirror.example/"]) == [
        "mirror.example/" + repository
    ]


def test_other_registries_are_not_rewritten():
    for image in ["ghcr.io/org/image:1", "localhost:5000/image:1"]:
        assert acquisition.mirror_sources(image, ["mirror.example"]) == [image]


@pytest.mark.parametrize("reference", [
    "node:20", "docker.io/library/node:20", "second.example/library/node:20",
])
def test_configured_mirror_references_keep_the_full_fallback_chain(reference):
    assert acquisition.mirror_sources(reference, ["https://first.example/", "second.example"]) == [
        "first.example/library/node:20", "second.example/library/node:20",
    ]


def test_mirror_alias_keeps_digest():
    digest = "sha256:" + "a" * 64
    assert acquisition.mirror_sources("second.example/team/image@" + digest, ["first.example", "second.example"]) == [
        "first.example/team/image@" + digest, "second.example/team/image@" + digest,
    ]


def test_explicit_route_does_not_change_other_requests():
    env = {
        "HTTPS_PROXY": "http://proxy:123", "http_proxy": "http://proxy:123", "ALL_PROXY": "socks5://proxy:456",
        "NO_PROXY": "localhost", "PATH": "/bin",
        acquisition.ROUTES_ENV: '{"mainland.example":"direct"}',
    }
    direct = acquisition.image_source_env("mainland.example/library/node:20", env)
    assert not any(key.lower().endswith('_proxy') for key in direct)
    assert direct["PATH"] == "/bin"
    assert acquisition.image_source_env("other.example/node:20", env) == env
    assert env["HTTPS_PROXY"] == "http://proxy:123"


def test_mirror_alias_reuses_downloaded_image(registry):
    _, calls, _ = registry
    acquisition.acquire_image("second.example/library/node:20")
    acquisition.acquire_image("node:20")
    assert len([c for c in calls if c[0] == "/crane"]) == 1


def test_import_and_registry_transfer_have_independent_timeouts(registry, monkeypatch):
    run = acquisition.run_bounded
    timeouts = {}

    def capture(args, *, timeout, env):
        timeouts[args[1]] = timeout
        return run(args, timeout=timeout, env=env)

    monkeypatch.setattr(acquisition, "run_bounded", capture)
    acquisition.acquire_image("node:20", timeout_s=31, import_timeout_s=1800)
    assert timeouts["pull"] == 31
    assert timeouts["load"] == 1800


def test_platform_scoped_acquisition_and_digest_alias_cache(registry):
    _, calls, _ = registry
    digest = "sha256:" + "b" * 64
    first = acquisition.acquire_image("second.example/library/node@" + digest, platform="linux/x86_64")
    second = acquisition.acquire_image("node@" + digest, platform="linux/amd64")
    assert first == second
    pulls = [c for c in calls if c[0] == "/crane"]
    assert len(pulls) == 1
    assert pulls[0][2:4] == ["--platform", "linux/amd64"]
    assert acquisition.normalize_platform("linux/arm64/v8") == "linux/arm64"


def test_mirrors_retry_in_order_without_direct_fallback(registry):
    images, calls, failures = registry
    failures.extend(["timeout", "unavailable"])
    assert acquisition.acquire_image("node:20") == "node:20"
    assert [c[-2] for c in calls if c[0] == "/crane"] == [
        "first.example/library/node:20",
        "second.example/library/node:20",
        "third.example/library/node:20",
    ]
    assert "node:20" in images
    assert acquisition.image_pull_options() == ["--pull", "never"]


def test_unavailable_sources_raise_infrastructure_error(registry):
    _, calls, failures = registry
    failures.extend(["unavailable"] * 3)
    with pytest.raises(acquisition.ImageAcquisitionError):
        acquisition.acquire_image("node:20")
    assert len([c for c in calls if c[0] == "/crane"]) == 3
    assert all(c[1] != "pull" for c in calls if c[0] == "/docker")


def test_existing_local_image_and_pull_disabled(registry):
    images, calls, _ = registry
    images.add("task:built")
    assert acquisition.acquire_image("task:built", allow_pull=False) == "task:built"
    with pytest.raises(acquisition.ImageAcquisitionError):
        acquisition.acquire_image("task:missing", allow_pull=False)
    assert all(c[0] == "/docker" for c in calls)


def test_pinned_digest_is_preserved_and_cached(registry):
    _, calls, _ = registry
    reference = "node@sha256:" + "a" * 64
    local = acquisition.acquire_image(reference)
    assert local == acquisition.acquire_image(reference)
    pulls = [c for c in calls if c[0] == "/crane"]
    assert len(pulls) == 1
    assert pulls[0][-2] == "first.example/library/" + reference


def test_concurrent_requests_share_one_download(registry):
    _, calls, _ = registry
    ready = threading.Barrier(2)

    def acquire():
        ready.wait(timeout=5)
        return acquisition.acquire_image("node:20")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(acquire) for _ in range(2)]
        assert [future.result(timeout=5) for future in futures] == ["node:20"] * 2
    assert len([c for c in calls if c[0] == "/crane"]) == 1


def test_preflight_propagates_acquisition_failure_without_task_repair(monkeypatch, tmp_path):
    from evalclaw.construction.suite import _preflight_builder_environments
    from evalclaw.types import (
        AgentEnvironmentSpec,
        BenchmarkConfig,
        EvalDimension,
        TaskDefinition,
        TaskType,
    )
    from tests.blueprint_factory import make_blueprint

    task = TaskDefinition(
        id="t",
        dimension_id="d",
        task_type="agent",
        title="Test",
        prompt="Work.",
        environment=AgentEnvironmentSpec(type="docker_workspace", test_command="true"),
    )
    dimension = EvalDimension(id="d", name="d", description="d", approach="d")

    def unavailable(*args, **kwargs):
        raise acquisition.ImageAcquisitionError("All registries unavailable")

    monkeypatch.setattr("evalclaw.runners.harness.preflight_harness_environments", unavailable)
    with pytest.raises(acquisition.ImageAcquisitionError):
        _preflight_builder_environments(
            [task],
            dimension=dimension,
            blueprint=make_blueprint("b", "d", "Test", task_type=TaskType.agent),
            resources=[],
            config=BenchmarkConfig(),
            trace_dir=tmp_path,
        )
    failure = json.loads((tmp_path / "t/failure.json").read_text())
    assert failure["status"] == "evaluation_blocked"
    assert failure["error_type"] == "ImageAcquisitionError"


def test_builder_tool_does_not_turn_registry_failure_into_task_feedback(monkeypatch):
    from evalclaw.construction.research import _execute_task_builder_tool
    from evalclaw.protocols.tool import ToolCall
    from evalclaw.types import BenchmarkConfig

    def unavailable(*args, **kwargs):
        raise acquisition.ImageAcquisitionError("All registries unavailable")

    monkeypatch.setattr("evalclaw.construction.research.run_docker_image_check", unavailable)
    with pytest.raises(acquisition.ImageAcquisitionError):
        _execute_task_builder_tool(
            ToolCall(id="image-check", name="run_image_check", arguments={"image": "node:20", "command": "true"}),
            BenchmarkConfig(), max_chars=1000,
        )
