"""Runner: execute accepted benchmark items against one or more target models."""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from typing import Callable

from .llm import call_llm, call_target_model, extract_json
from .sandbox import build_code_harness, run_python_sandbox
from .types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    EvalSpec,
    EvalRun,
    ItemResult,
    Message,
    QcReport,
    TargetSummary,
    TaskType,
)


def _target_has_credentials(target_id: str, config: BenchmarkConfig) -> tuple[bool, str | None]:
    target = next(target for target in config.targets if target.id == target_id)
    if target.api_key:
        return True, None
    if target.provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY"
    if target.model.startswith("deepseek-"):
        return bool(os.environ.get("DEEPSEEK_API_KEY")), "DEEPSEEK_API_KEY"
    if target.model.startswith("gemini"):
        return bool(os.environ.get("GEMINI_API_KEY")), "GEMINI_API_KEY"
    if target.provider in {"openai", "openai_compatible"}:
        return bool(os.environ.get("OPENAI_API_KEY")), "OPENAI_API_KEY"
    return True, None


def _score_yes_no(response: str, answer: str | None) -> float:
    expected = (answer or "yes").lower()
    lower = response.lower()
    has_yes = bool(re.search(r"\byes\b|是|正确", lower))
    has_no = bool(re.search(r"\bno\b|否|不正确|错误", lower))
    if has_yes and not has_no:
        return 1.0 if expected == "yes" else 0.0
    if has_no and not has_yes:
        return 1.0 if expected == "no" else 0.0
    return 0.0


def _score_choice(response: str, answer: str | None) -> float:
    if not answer:
        return 0.0
    letter = answer.strip().upper()[0]
    pattern = re.compile(
        rf"\b{letter}\b|\({letter}\)|answer\s*[:：]\s*{letter}|答案\s*[是为：:]\s*{letter}",
        flags=re.IGNORECASE,
    )
    return 1.0 if pattern.search(response) else 0.0


def _score_short_answer(response: str, answer: str | None) -> float:
    if not answer:
        return 0.0
    expected = answer.strip().lower()
    got = response.strip().lower()
    if expected == got:
        return 1.0
    if expected and expected in got:
        return 0.8
    return 0.0


def _call_judge_json(prompt: dict, config: BenchmarkConfig) -> dict | None:
    messages = [Message(role="user", content=json.dumps(prompt, ensure_ascii=False, indent=2))]
    data: dict | None = None
    for _ in range(2):
        raw = call_llm(
            messages,
            model=config.orchestrator_model,
            api_key=config.orchestrator_api_key,
            base_url=config.orchestrator_base_url,
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
                    '{"score_raw":3,"score_normalized":0.6,"reasoning":"brief reason"}'
                ),
            ),
        ]
    return data


def _score_from_judge_data(data: dict) -> tuple[float, str]:
    normalized = data.get("score_normalized")
    if normalized is None:
        normalized = float(data.get("score_raw", 0) or 0) / 5.0
    return max(0.0, min(1.0, float(normalized))), str(data.get("reasoning", ""))


def _judge_item(item: BenchmarkItem, response: str, config: BenchmarkConfig) -> tuple[float, str]:
    if not config.orchestrator_api_key:
        return 0.0, "No orchestrator configured for LLM judge."
    base_prompt = {
        "instruction": "Score the model response from 1 to 5 using the rubric. Return JSON only.",
        "item": item.model_dump(mode="json"),
        "model_response": response,
        "output_schema": {"score_raw": 3, "score_normalized": 0.6, "reasoning": "..."},
    }
    first = _call_judge_json(base_prompt, config)
    if first is None:
        return 0.0, "Judge returned invalid JSON after retry."
    first_score, first_reason = _score_from_judge_data(first)
    if not config.judge_double_pass:
        return first_score, first_reason

    swap_prompt = {
        **base_prompt,
        "instruction": (
            "Second-pass audit: score the same response again, but first look for reasons the "
            "previous answer might deserve a lower or higher score. Return JSON only."
        ),
        "first_pass_score": first_score,
        "first_pass_reasoning": first_reason,
    }
    second = _call_judge_json(swap_prompt, config)
    if second is None:
        return first_score, f"{first_reason}\nJudge second pass failed; using first pass."
    second_score, second_reason = _score_from_judge_data(second)
    final_score = (first_score + second_score) / 2
    disagreement = abs(first_score - second_score)
    reasoning = (
        f"pass1={first_score:.2f}: {first_reason}\n"
        f"pass2={second_score:.2f}: {second_reason}\n"
        f"disagreement={disagreement:.2f}"
    )
    if disagreement >= 0.4:
        reasoning += "\njudge_instability=true"
    return final_score, reasoning


def _run_code(item: BenchmarkItem, response: str) -> tuple[float, str | None]:
    if not item.test_code:
        return 0.0, "Missing test_code."
    code = build_code_harness(item.test_code, response)
    try:
        returncode, stdout, stderr = run_python_sandbox(code, timeout=10)
        if returncode != 0:
            return 0.0, (stderr or stdout)[:800]
        return 1.0, None
    except Exception as exc:
        return 0.0, str(exc)


def _multi_turn_followups(item: BenchmarkItem, config: BenchmarkConfig) -> list[str]:
    turns = item.metadata.get("turns")
    if isinstance(turns, list) and all(isinstance(turn, str) for turn in turns):
        return turns[:5]
    if not config.orchestrator_api_key:
        return []
    prompt = {
        "instruction": "Generate 1-3 short user follow-up turns for this multi-turn evaluation. Return JSON only.",
        "item": item.model_dump(mode="json"),
        "schema": {"turns": ["follow-up 1", "follow-up 2"]},
    }
    raw = call_llm(
        [Message(role="user", content=json.dumps(prompt, ensure_ascii=False, indent=2))],
        model=config.orchestrator_model,
        api_key=config.orchestrator_api_key,
        base_url=config.orchestrator_base_url,
        backend=config.llm_backend,
        max_tokens=1024,
    )
    data = extract_json(raw)
    parsed = data.get("turns", [])
    if isinstance(parsed, list):
        return [str(turn) for turn in parsed[:5]]
    return []


def _run_multi_turn(item: BenchmarkItem, target: object, config: BenchmarkConfig) -> tuple[str, float, str]:
    history: list[Message] = []
    first = call_target_model(item.prompt, target, history=history, backend=config.llm_backend)
    history.extend([Message(role="user", content=item.prompt), Message(role="assistant", content=first)])
    for followup in _multi_turn_followups(item, config):
        answer = call_target_model(followup, target, history=history, backend=config.llm_backend)
        history.extend([Message(role="user", content=followup), Message(role="assistant", content=answer)])
    transcript = "\n\n".join(f"[{message.role.upper()}] {message.content}" for message in history)
    score, reasoning = _judge_item(item, transcript, config)
    return json.dumps([message.model_dump() for message in history], ensure_ascii=False), score, reasoning


def _run_item(item: BenchmarkItem, config: BenchmarkConfig, target_id: str) -> ItemResult:
    target = next(target for target in config.targets if target.id == target_id)
    has_credentials, env_name = _target_has_credentials(target_id, config)
    if not has_credentials:
        return ItemResult(
            item_id=item.id,
            target_id=target.id,
            score=0.0,
            error=f"Missing API key for {target.model}. Set {env_name} or pass --target-api-key.",
        )
    start = time.monotonic()
    try:
        response = call_target_model(item.prompt, target, backend=config.llm_backend)
        latency_ms = round((time.monotonic() - start) * 1000)
        if item.task_type == TaskType.yes_no:
            score = _score_yes_no(response, item.answer)
            return ItemResult(item_id=item.id, target_id=target.id, raw_response=response, score=score, latency_ms=latency_ms)
        if item.task_type == TaskType.multiple_choice:
            score = _score_choice(response, item.answer)
            return ItemResult(item_id=item.id, target_id=target.id, raw_response=response, score=score, latency_ms=latency_ms)
        if item.task_type == TaskType.short_answer and item.answer:
            score = _score_short_answer(response, item.answer)
            return ItemResult(item_id=item.id, target_id=target.id, raw_response=response, score=score, latency_ms=latency_ms)
        if item.task_type == TaskType.code_execution:
            score, error = _run_code(item, response)
            return ItemResult(
                item_id=item.id,
                target_id=target.id,
                raw_response=response,
                score=score,
                judge_reasoning=error,
                latency_ms=latency_ms,
            )
        if item.task_type == TaskType.multi_turn:
            raw, score, reasoning = _run_multi_turn(item, target, config)
            return ItemResult(
                item_id=item.id,
                target_id=target.id,
                raw_response=raw,
                score=score,
                judge_reasoning=reasoning,
                latency_ms=latency_ms,
            )
        score, reasoning = _judge_item(item, response, config)
        return ItemResult(
            item_id=item.id,
            target_id=target.id,
            raw_response=response,
            score=score,
            judge_reasoning=reasoning,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        return ItemResult(item_id=item.id, target_id=target.id, error=str(exc), score=0.0)


def _summarize(
    dataset: BenchmarkDataset,
    results: list[ItemResult],
    config: BenchmarkConfig,
) -> list[TargetSummary]:
    item_by_id = {item.id: item for item in dataset.items}
    results_by_target: dict[str, list[ItemResult]] = defaultdict(list)
    for result in results:
        results_by_target[result.target_id].append(result)

    summaries: list[TargetSummary] = []
    for target in config.targets:
        target_results = results_by_target.get(target.id, [])
        total = len(target_results)
        avg = sum(result.score for result in target_results) / total if total else 0.0
        by_dimension: dict[str, float] = {}
        for dimension in dataset.spec.dimensions:
            dim_results = [
                result
                for result in target_results
                if item_by_id.get(result.item_id)
                and item_by_id[result.item_id].dimension_id == dimension.id
            ]
            if dim_results:
                by_dimension[dimension.id] = sum(result.score for result in dim_results) / len(dim_results)
        by_type: dict[str, float] = {}
        for task_type in TaskType:
            type_results = [
                result
                for result in target_results
                if item_by_id.get(result.item_id)
                and item_by_id[result.item_id].task_type == task_type
            ]
            if type_results:
                by_type[task_type.value] = sum(result.score for result in type_results) / len(type_results)
        summaries.append(
            TargetSummary(
                target_id=target.id,
                model=target.model,
                average_score=avg,
                score_by_dimension=by_dimension,
                score_by_task_type=by_type,
                total_items=total,
                errors=sum(1 for result in target_results if result.error),
            )
        )
    return summaries


def run_eval(
    dataset: BenchmarkDataset,
    qc_report: QcReport,
    config: BenchmarkConfig,
    *,
    on_progress: Callable[[int, int, str, str], None] | None = None,
) -> EvalRun:
    """Run accepted items against all configured target models."""
    accepted = [item for item in dataset.items if item.id in set(qc_report.passed_item_ids)]
    results: list[ItemResult] = []
    if config.run_targets and config.targets:
        total = len(accepted) * len(config.targets)
        done = 0
        for target in config.targets:
            for item in accepted:
                done += 1
                if on_progress:
                    on_progress(done, total, target.id, item.id)
                results.append(_run_item(item, config, target.id))
    summaries = _summarize(dataset, results, config)
    return EvalRun(dataset=dataset, qc_report=qc_report, results=results, summaries=summaries)


# Compatibility wrappers for older imports.
def run_question(item: BenchmarkItem, config: BenchmarkConfig) -> ItemResult:
    if not config.targets:
        raise ValueError("BenchmarkConfig.targets is empty")
    return _run_item(item, config, config.targets[0].id)


def run_benchmark(
    items: list[BenchmarkItem],
    config: BenchmarkConfig,
    on_progress: Callable[[int, int, str, str], None] | None = None,
) -> list[ItemResult]:
    dimension_ids = sorted({item.dimension_id for item in items})
    spec = EvalSpec(
        objective="Compatibility benchmark",
        dimensions=[
            {
                "id": dimension_id,
                "name": dimension_id,
                "description": "",
                "approach": "",
            }
            for dimension_id in dimension_ids
        ],
    )
    dataset = BenchmarkDataset(spec=spec, items=items)
    qc_report = QcReport(passed_item_ids=[item.id for item in items])
    return run_eval(dataset, qc_report, config, on_progress=on_progress).results
