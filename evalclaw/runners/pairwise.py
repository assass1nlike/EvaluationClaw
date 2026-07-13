"""Pairwise target-vs-reference execution for runner items."""
from __future__ import annotations

import json

from ..models.llm import call_llm, call_target_model, extract_json
from ..protocols.multimodal import build_multimodal_user_content, get_multimodal_spec
from ..types import BenchmarkConfig, BenchmarkItem, Message, TargetModelConfig
from .credentials import target_config_has_credentials
from .prompts import target_prompt


def _is_pairwise_judge_failure(reasoning: str | None) -> bool:
    if not reasoning:
        return False
    lowered = reasoning.lower()
    return (
        "pairwise judge returned invalid json" in lowered
        or "no orchestrator configured for pairwise judge" in lowered
    )


def _call_pairwise_judge_json(prompt: dict, config: BenchmarkConfig) -> dict | None:
    messages = [Message(role="user", content=json.dumps(prompt, ensure_ascii=False, indent=2))]
    data: dict | None = None
    for _ in range(2):
        raw = call_llm(
            messages,
            model=config.orchestrator_model,
            api_key=config.orchestrator_api_key,
            base_url=config.orchestrator_base_url,
            provider=config.orchestrator_provider,
            backend=config.llm_backend,
            max_tokens=1024,
        )
        try:
            parsed = extract_json(raw)
            if isinstance(parsed, dict):
                data = parsed
                break
        except Exception:
            pass
        messages = [
            *messages,
            Message(role="assistant", content=raw or ""),
            Message(
                role="user",
                content=(
                    "Your previous judge response was missing or invalid JSON. "
                    "Return only this compact JSON object now, with no markdown: "
                    '{"winner":"target","score_normalized":1.0,"reasoning":"brief reason"}'
                ),
            ),
        ]
    return data


def judge_pairwise_preference(
    item: BenchmarkItem,
    target_response: str,
    reference_response: str,
    config: BenchmarkConfig,
) -> tuple[float, str, str]:
    if not config.orchestrator_api_key:
        return 0.0, "reference", "No orchestrator configured for pairwise judge."
    prompt = {
        "instruction": (
            "Judge a pairwise model comparison for one EvaluationClaw item. "
            "Decide whether the target response is better than, tied with, or worse than the reference response. "
            "Use only the item prompt and rubric. Return JSON only."
        ),
        "item": item.model_dump(mode="json"),
        "target_response": target_response,
        "reference_response": reference_response,
        "reference_model": config.reference_model.model_dump(mode="json") if config.reference_model else None,
        "output_schema": {
            "winner": "target | reference | tie",
            "score_normalized": 1.0,
            "reasoning": "brief reason",
        },
    }
    data = _call_pairwise_judge_json(prompt, config)
    if data is None:
        return 0.0, "reference", "Pairwise judge returned invalid JSON after retry."
    winner = str(data.get("winner") or "").strip().lower()
    if winner in {"target", "target_model", "a", "response_a"}:
        score = 1.0
        normalized_winner = "target"
    elif winner in {"tie", "draw", "equal"}:
        score = 0.5
        normalized_winner = "tie"
    elif winner in {"reference", "reference_model", "baseline", "b", "response_b"}:
        score = 0.0
        normalized_winner = "reference"
    else:
        try:
            score = max(0.0, min(1.0, float(data.get("score_normalized"))))
        except (TypeError, ValueError):
            score = 0.0
        normalized_winner = "target" if score > 0.5 else "tie" if score == 0.5 else "reference"
    reasoning = str(data.get("reasoning") or "")
    return score, normalized_winner, reasoning


def run_pairwise_preference(
    item: BenchmarkItem,
    target: TargetModelConfig,
    config: BenchmarkConfig,
) -> tuple[str, float, str, str | None]:
    reference = config.reference_model
    if reference is None:
        return "", 0.0, "", "No reference model configured for pairwise_preference item."
    has_reference_credentials, reference_env_name = target_config_has_credentials(reference)
    if not has_reference_credentials:
        return (
            "",
            0.0,
            "",
            f"Missing API key for reference model {reference.model}. Set {reference_env_name} or pass --reference-api-key.",
        )

    prompt = target_prompt(item)
    user_content_target = (
        build_multimodal_user_content(item, prompt, target.provider)
        if get_multimodal_spec(item)
        else None
    )
    user_content_reference = (
        build_multimodal_user_content(item, prompt, reference.provider)
        if get_multimodal_spec(item)
        else None
    )
    if user_content_target is None:
        target_response = call_target_model(prompt, target, backend=config.llm_backend)
    else:
        target_response = call_target_model(
            prompt,
            target,
            backend=config.llm_backend,
            user_content=user_content_target,
        )
    if user_content_reference is None:
        reference_response = call_target_model(prompt, reference, backend=config.llm_backend)
    else:
        reference_response = call_target_model(
            prompt,
            reference,
            backend=config.llm_backend,
            user_content=user_content_reference,
        )
    score, winner, reasoning = judge_pairwise_preference(item, target_response, reference_response, config)
    raw = {
        "prompt": prompt,
        "target_response": target_response,
        "reference_response": reference_response,
        "reference_model": reference.model,
        "winner": winner,
        "score_mapping": {"target": 1.0, "tie": 0.5, "reference": 0.0},
    }
    error = reasoning if _is_pairwise_judge_failure(reasoning) else None
    return json.dumps(raw, ensure_ascii=False), score, f"winner={winner}; {reasoning}", error
