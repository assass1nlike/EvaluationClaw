from __future__ import annotations

import json
import subprocess

import pytest

from evalclaw.execution import build_sources as sources
from evalclaw.execution import docker_images as images
from evalclaw.execution.image_acquisition import ImageAcquisitionError


def test_real_dockerfile_syntax_and_reachable_stage_dependencies():
    text = '''# syntax=docker/dockerfile:1
ARG VERSION="3.11"
ARG BASE=python:${VERSION}-slim
FROM inaccessible.invalid/unused AS unused
FROM --platform=$BUILDPLATFORM ${BASE} AS build
RUN <<EOF
FROM this-is-script-text
EOF
FROM scratch
COPY --from=build /app /app
COPY --from=alpine:3.20 ["/etc/alpine-release", "/release"]
RUN --mount=type=bind,from=busybox:1,target=/tools true
'''
    assert sources.image_dependencies(text, {"VERSION": "3.12"}, "linux/amd64") == [
        ("docker/dockerfile:1", "linux/amd64"), ("python:3.12-slim", "linux/amd64"),
        ("alpine:3.20", "linux/amd64"), ("busybox:1", "linux/amd64"),
    ]


@pytest.mark.parametrize("text,expected", [
    ("FROM node:20 AS node\nFROM node", [("node:20", "linux/amd64")]),
    ("FROM scratch AS empty\nFROM python:3.11 AS worker\nCOPY --from=0 /f /f", [("python:3.11", "linux/amd64")]),
    ("FROM scratch\nCOPY --from=later /f /f\nFROM alpine:3.20 AS later", [("alpine:3.20", "linux/amd64")]),
    ("ARG BASE\nFROM ${BASE:-python:3.11-slim}", [("python:3.11-slim", "linux/amd64")]),
    ("FROM --platform=linux/arm64 alpine:3.20", [("alpine:3.20", "linux/arm64")]),
    ("FROM scratch\nRUN <<EOF\nCOPY --from=fake /f /f\nEOF", []),
])
def test_dependency_resolution(text, expected):
    assert sources.image_dependencies(text, {}, "linux/amd64") == expected


def test_unresolved_reference_is_not_downloaded():
    with pytest.raises(ValueError):
        sources.image_dependencies("ARG BASE\nFROM $BASE", {}, "linux/amd64")


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("ARG BASE=second.example/library/python:3.11\nFROM ${BASE}\n")
    log = tmp_path / "logs"
    log.mkdir()
    calls, pulls = [], []
    digest = "sha256:" + "a" * 64

    def run(command, **kwargs):
        calls.append(command)
        if command[1] == "info":
            value = json.dumps({"OSType": "linux", "Architecture": "x86_64"})
        elif command[1:3] == ["image", "inspect"]:
            value = digest
        else:
            assert command[1] == "tag"
            value = ""
        return subprocess.CompletedProcess(command, 0, value, "")

    def acquire(image, **kwargs):
        pulls.append((image, kwargs))
        return "local:loaded"

    monkeypatch.setenv("EVALCLAW_DOCKER_MIRRORS", "first.example,second.example")
    monkeypatch.setattr(sources, "run_bounded", run)
    monkeypatch.setattr(sources, "acquire_image", acquire)
    kwargs = dict(docker="docker", docker_executable="docker", env={}, log_dir=log)
    return dockerfile, log, kwargs, calls, pulls


def test_source_policy_preserves_dockerfile_and_pins_local_content(prepared):
    dockerfile, log, kwargs, calls, pulls = prepared
    before = dockerfile.read_bytes()
    path = sources.prepare_build_sources(dockerfile, {}, **kwargs)
    assert dockerfile.read_bytes() == before
    policy = json.loads(path.read_text())
    rule, = policy["rules"]
    assert rule["selector"]["identifier"] == "docker-image://second.example/library/python:3.11"
    assert rule["updates"]["identifier"] == "docker-image://docker.io/library/evalclaw-build-source:" + "a" * 64
    assert rule["updates"]["attrs"] == {"image.resolvemode": "local"}
    assert calls[-1] == ["docker", "tag", "sha256:" + "a" * 64, "evalclaw-build-source:" + "a" * 64]
    assert pulls == [("second.example/library/python:3.11", {"docker_executable": "docker", "platform": "linux/amd64"})]
    assert (log / "image-sources.json").is_file()


def test_failed_local_dependency_cannot_be_pulled(prepared):
    dockerfile, _, kwargs, _, pulls = prepared
    with pytest.raises(ValueError):
        sources.prepare_build_sources(dockerfile, {}, unavailable_images={"docker.io/library/python:3.11"}, **kwargs)
    assert pulls == []


@pytest.mark.parametrize("entrypoint", ["builder", "environment"])
def test_build_stops_before_docker_when_sources_are_unavailable(monkeypatch, prepared, entrypoint):
    dockerfile, _, _, _, _ = prepared
    monkeypatch.setenv(images.DOCKER_BUILD_DIR_ENV_VAR, str(dockerfile.parent / "builds"))
    monkeypatch.setattr(images, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(images, "docker_subprocess_env", lambda _: {})
    monkeypatch.setattr(images.subprocess, "run", lambda *a, **kw: pytest.fail("build started without sources"))

    def fail(*a, **kw):
        raise ImageAcquisitionError("image sources unreachable")

    monkeypatch.setattr(images, "prepare_build_sources", fail)
    with pytest.raises(ImageAcquisitionError):
        if entrypoint == "builder":
            images.build_docker_image_from_context(dockerfile.parent)
        else:
            images.build_docker_image_if_requested({"image_build": {
                "enabled": True, "rebuild": True, "context_dir": str(dockerfile.parent),
            }})
    failures = list((dockerfile.parent / "builds/logs").glob("*/dependency-failure.json"))
    assert len(failures) == 1


def test_build_command_receives_policy_with_custom_dockerfile(monkeypatch, prepared):
    dockerfile, log, _, _, _ = prepared
    custom = dockerfile.with_name("Customfile")
    dockerfile.rename(custom)
    policy = log / "source-policy.json"
    policy.write_text('{"rules":[]}')
    monkeypatch.setenv(images.DOCKER_BUILD_DIR_ENV_VAR, str(log))
    monkeypatch.setattr(images, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(images, "docker_subprocess_env", lambda _: {})

    def prepare(path, args, **kw):
        assert path == custom
        return policy

    def run(command, **kwargs):
        assert command[command.index("-f") + 1] == str(custom)
        assert kwargs["env"]["EXPERIMENTAL_BUILDKIT_SOURCE_POLICY"] == str(policy)
        return subprocess.CompletedProcess(command, 0, "built", "")

    monkeypatch.setattr(images, "prepare_build_sources", prepare)
    monkeypatch.setattr(images.subprocess, "run", run)
    _, result = images.build_docker_image_if_requested({"image_build": {
        "enabled": True, "rebuild": True, "context_dir": str(custom.parent), "dockerfile_name": "Customfile",
    }})
    assert result.built
