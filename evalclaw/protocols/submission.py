"""A single public artifact contract shared by prompts and evaluator evidence."""
from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Literal

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SubmissionArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    format: Literal["file", "directory", "text", "json", "csv"] = "file"
    required: bool = True
    json_schema: dict | None = Field(default=None, alias="schema")

    @model_validator(mode="after")
    def validate_artifact(self):
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or str(path) == ".":
            raise ValueError("Submission paths must be relative to the task workspace")
        self.path = str(path)
        if self.json_schema is not None:
            if self.format != "json":
                raise ValueError("An artifact schema requires format=json")
            jsonschema.Draft202012Validator.check_schema(self.json_schema)
        return self


class SubmissionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evalclaw.output.v1"]
    artifacts: list[SubmissionArtifact] = Field(default_factory=list)
    response_schema: dict | None = None

    @model_validator(mode="after")
    def validate_contract(self):
        for name in ("id", "path"):
            values = [getattr(a, name) for a in self.artifacts]
            if len(values) != len(set(values)):
                raise ValueError(f"Submission artifact {name}s must be unique")
        if self.response_schema is not None:
            jsonschema.Draft202012Validator.check_schema(self.response_schema)
        return self


def validate_output_contract(value: dict) -> SubmissionContract | None:
    # Existing free-form contracts retain their semantics. The version explicitly
    # opts into rendering and the evaluator's artifact-ID interface.
    if not str(value.get("schema_version", "")).startswith("evalclaw.output."):
        return None
    try:
        return SubmissionContract.model_validate(value)
    except jsonschema.SchemaError as exc:
        raise ValueError(f"Invalid submission JSON schema: {exc.message}") from exc


def submission_contract(item) -> dict:
    raw = item.content.output_contract if item.content is not None else item.output_contract
    contract = validate_output_contract(raw)
    if contract is None:
        return {}
    public = contract.model_dump(mode="json", by_alias=True, exclude_none=True)
    if not contract.artifacts:
        return public
    env = item.environment
    root = getattr(env, "workdir", None) or item.metadata.get("agent_env", {}).get("workdir") or "/workspace"
    return {
        **public,
        "workspace_root": root,
        "artifact_paths": {a.id: str(PurePosixPath(root) / a.path) for a in contract.artifacts},
    }


def submission_instructions(item) -> str:
    contract = submission_contract(item)
    if not contract:
        return ""
    return "\n\nSubmission requirements:\n" + json.dumps(contract, ensure_ascii=False, indent=2)
