"""Prepare Dockerfile image dependencies through the host's image acquisition policy."""
from __future__ import annotations

import csv
import json
import re
import subprocess
from pathlib import Path

import dockerfile

from .image_acquisition import (
    ImageAcquisitionError,
    acquire_image,
    canonical_image,
    normalize_platform,
)
from .process import run_bounded


def _expand(word: str, variables: dict[str, str]) -> str:
    """Docker's basic ARG substitutions; never execute shell expressions."""
    result = []
    quote = ""
    i = 0
    while i < len(word):
        char = word[i]
        if char in {"'", '"'} and (not quote or quote == char):
            quote = "" if quote else char
            i += 1
            continue
        if char == "\\" and quote != "'" and i + 1 < len(word):
            result.append(word[i + 1])
            i += 2
            continue
        if char != "$" or quote == "'":
            result.append(char)
            i += 1
            continue
        if word[i:i + 2] == "${":
            end, depth = i + 2, 1
            while end < len(word) and depth:
                if word[end:end + 2] == "${":
                    depth += 1
                    end += 2
                    continue
                if word[end] == "}":
                    depth -= 1
                end += 1
            if depth:
                raise ValueError(f"Unclosed build ARG expression: {word!r}")
            expression = word[i + 2:end - 1]
            match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?:(:?[+-])(.*))?", expression, re.S)
            if not match:
                raise ValueError(f"Unsupported image ARG expression ${{{expression}}}; supply an explicit image reference.")
            name, operator, alternate = match.groups()
            value = variables.get(name, "")
            present = name in variables and (bool(value) if operator and operator.startswith(":") else True)
            if operator:
                if operator.endswith("+"):
                    value = _expand(alternate, variables) if present else ""
                elif not present:
                    value = _expand(alternate, variables)
            result.append(value)
            i = end
        else:
            match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", word[i + 1:])
            if not match:
                result.append("$")
                i += 1
                continue
            result.append(variables.get(match[0], ""))
            i += 1 + len(match[0])
    if quote:
        raise ValueError(f"Unclosed quote in image ARG: {word!r}")
    return "".join(result)


def image_dependencies(text: str, build_args: dict[str, str], platform: str) -> list[tuple[str, str]]:
    """Read FROM, external COPY/RUN mounts and frontend references using Docker's parser."""
    try:
        commands = dockerfile.parse_string(text)
    except Exception as exc:
        raise ValueError(f"Invalid Dockerfile: {exc}") from exc
    os_name, architecture, *variant = platform.split("/")
    variables = {}
    for prefix in ("BUILD", "TARGET"):
        variables.update({prefix + "PLATFORM": platform, prefix + "OS": os_name,
                          prefix + "ARCH": architecture, prefix + "VARIANT": "/".join(variant)})
    variables.update({key: value for key, value in build_args.items() if key in variables})
    from_commands = [c for c in commands if c.cmd == "FROM"]
    aliases = {c.value[2].lower(): i for i, c in enumerate(from_commands)
               if len(c.value) == 3 and c.value[1].upper() == "AS"}
    frontend = []
    stages: list[list[tuple[str, str]]] = []
    edges: list[set[int]] = []
    current_platform = platform
    in_stage = False

    def add(reference, image_platform, *, base=False):
        if not reference or "$" in reference or any(c.isspace() for c in reference):
            raise ValueError(f"Unresolved Docker image reference: {reference!r}")
        if reference == "scratch":
            return
        index = aliases.get(reference.lower())
        if not base and reference.isdigit():
            index = int(reference)
            if index >= len(from_commands):
                raise ValueError(f"Unknown Dockerfile stage index: {index}")
        if index is not None and (not base or index < len(stages) - 1):
            edges[-1].add(index)
        else:
            stages[-1].append((reference, image_platform))

    # Parser directives are valid only before the first blank, ordinary comment, or instruction.
    for line in text.lstrip("\ufeff").splitlines():
        match = re.fullmatch(r"\s*#\s*(syntax|escape|check)\s*=\s*(.*?)\s*", line, re.I)
        if not match:
            break
        if match[1].lower() == "syntax":
            frontend.append((match[2], platform))
    if build_args.get("BUILDKIT_SYNTAX"):
        frontend = [(build_args["BUILDKIT_SYNTAX"], platform)]
    for command in commands:
        if command.cmd == "ARG" and not in_stage:
            for declaration in command.value:
                name, equals, default = declaration.partition("=")
                if name in build_args:
                    variables[name] = build_args[name]
                elif equals:
                    variables[name] = _expand(default, variables)
            continue
        if command.cmd == "FROM":
            if len(command.value) not in {1, 3} or (len(command.value) == 3 and command.value[1].upper() != "AS"):
                raise ValueError(f"Invalid FROM instruction: {command.original}")
            current_platform = platform
            stages.append([])
            edges.append(set())
            for flag in command.flags:
                key, _, value = flag.partition("=")
                if key == "--platform":
                    current_platform = _expand(value, variables)
            add(_expand(command.value[0], variables), current_platform, base=True)
            in_stage = True
        elif command.cmd in {"COPY", "RUN"}:
            for flag in command.flags:
                key, _, value = flag.partition("=")
                if key == "--from":
                    add(value, current_platform)
                elif key == "--mount":
                    options = dict(field.split("=", 1) for field in next(csv.reader([value])) if "=" in field)
                    if "from" in options:
                        add(options["from"], current_platform)
    references = list(frontend)
    visited, visiting = set(), set()

    def visit(index):
        if index in visiting:
            raise ValueError("Dockerfile has a circular stage dependency.")
        if index in visited:
            return
        visiting.add(index)
        for dependency in sorted(edges[index]):
            visit(dependency)
        references.extend(stages[index])
        visiting.remove(index)
        visited.add(index)

    if stages:
        visit(len(stages) - 1)
    return list(dict.fromkeys(references))


def prepare_build_sources(
    dockerfile_path: Path, build_args: dict[str, str], *, docker: str,
    docker_executable: str, env: dict[str, str], log_dir: Path,
    unavailable_images: set[str] | None = None,
) -> Path:
    """Pin prepared local dependencies with BuildKit's source-conversion interface."""
    def checked(command):
        try:
            result = run_bounded(command, timeout=300, env=env)
            result.check_returncode()
            return result.stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise ImageAcquisitionError(f"Build dependency preparation failed: {exc}") from exc

    info = json.loads(checked([docker, "info", "--format", "{{json .}}"]))
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(info["Architecture"], info["Architecture"])
    platform = f"{info['OSType']}/{arch}"
    dependencies = image_dependencies(dockerfile_path.read_text(encoding="utf-8"), build_args, platform)
    rules, prepared = [], {}
    for reference, source_platform in dependencies:
        source_platform = normalize_platform(source_platform)
        identity = canonical_image(reference)
        if identity in (unavailable_images or set()):
            raise ValueError(f"Local build dependency {reference!r} has not built successfully; repair it before building dependent images.")
        original = canonical_image(reference, [])
        if original in prepared:
            if prepared[original]["platform"] != source_platform:
                raise ValueError(f"Image {reference!r} is requested for multiple platforms in one build; use distinct image references for each platform.")
            continue
        acquired = acquire_image(reference, docker_executable=docker_executable, platform=source_platform)
        image_id = checked([docker, "image", "inspect", acquired, "--format", "{{.Id}}"]).strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise ImageAcquisitionError(f"Invalid local image ID for {reference!r}: {image_id!r}")
        local = "evalclaw-build-source:" + image_id.split(":")[1]
        checked([docker, "tag", image_id, local])
        prepared[original] = {"platform": source_platform, "image_id": image_id, "local": local}
        rules.append({"action": "CONVERT", "selector": {"identifier": "docker-image://" + original},
                      "updates": {"identifier": "docker-image://" + canonical_image(local, []),
                                  "attrs": {"image.resolvemode": "local"}}})
    path = log_dir / "source-policy.json"
    path.write_text(json.dumps({"rules": rules}, indent=2), encoding="utf-8")
    (log_dir / "image-sources.json").write_text(json.dumps(prepared, indent=2), encoding="utf-8")
    return path
