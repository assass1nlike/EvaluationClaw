"""Shared test helpers for building configured BenchmarkConfig instances."""
from __future__ import annotations

import json
from pathlib import Path

from evalclaw.models.llm import LLMFinalContentMissingError
from evalclaw.types import Message, TargetModelConfig


def save_task_builder_response(payload: dict, response: str) -> str:
    revision = payload.get("revision") if isinstance(payload.get("revision"), dict) else {}
    task_file = payload.get("task_file") if isinstance(payload.get("task_file"), dict) else {}
    document_path = revision.get("path") or task_file.get("path")
    if not document_path:
        return response
    try:
        response_payload = json.loads(response)
    except json.JSONDecodeError:
        response_payload = None
    if not (
        isinstance(response_payload, dict)
        and response_payload.get("status") == "saved"
    ):
        Path(document_path).write_text(response, encoding="utf-8")
    return '{"status":"saved"}'


def patch_task_builder_model(monkeypatch, responder) -> None:
    def run_tools(payload, *, system_prompt, config, **kwargs):
        messages = [
            Message(
                role="user",
                content=json.dumps(payload, ensure_ascii=False, indent=2),
            )
        ]
        response = responder(
            messages,
            system=system_prompt,
            model=config.task_builder_model,
            api_key=config.task_builder_api_key,
            base_url=config.task_builder_base_url,
            provider=config.task_builder_provider,
            backend=config.llm_backend,
            retry_on_truncation=False,
        )
        if not response.strip():
            response = responder(
                messages,
                system=system_prompt,
                model=config.task_builder_model,
                api_key=config.task_builder_api_key,
                base_url=config.task_builder_base_url,
                provider=config.task_builder_provider,
                backend=config.llm_backend,
                reduce_reasoning_effort=True,
                retry_on_truncation=False,
            )
        if not response.strip():
            raise LLMFinalContentMissingError(
                "TaskBuilder returned no final content after one no-thinking recovery attempt."
            )
        return save_task_builder_response(payload, response), []

    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_tools", run_tools)


def dummy_config_kwargs() -> dict:
    """Return dummy keys for roles required by construction tests.

    Tests that previously used ``orchestrator_api_key="dummy"`` to make every
    role configured through the catch-all fallback now spread the same key to
    each role explicitly, matching the no-orchestrator model where roles must
    be configured individually. A single dummy task model is exposed so runner
    scoring and dialogue-simulator paths stay exercised.
    """
    return {
        "planner_api_key": "dummy",
        "task_builder_api_key": "dummy",
        "qc_api_key": "dummy",
        "research_api_key": "dummy",
        "task_models": [
            TargetModelConfig(provider="openai_compatible", model="dummy-task", api_key="dummy")
        ],
    }
