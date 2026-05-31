"""Runner: execute accepted benchmark items against one or more target models."""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from typing import Any, Callable

from .llm import call_llm, call_target_model, extract_json
from .protocols.multimodal import build_multimodal_user_content, get_multimodal_spec
from .protocols.task_agent import (
    get_task_agent_spec,
    task_agent_available,
    task_agent_initial_content_text,
    task_agent_initial_user_message,
    task_agent_max_turns,
    task_agent_model_settings,
    task_agent_scoring,
    task_agent_scripted_turns,
    task_agent_system_prompt,
    transcript_text,
)
from .runners.agent import parse_agent_action as _parse_agent_action
from .runners.agent import run_agent_interaction as _run_agent_interaction
from .runners.credentials import target_has_credentials as _target_has_credentials
from .runners.pairwise import run_pairwise_preference as _run_pairwise_preference
from .runners.prompts import target_prompt as _target_prompt
from .sandbox import build_code_harness, run_python_sandbox
from .types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    EvalRun,
    EvalSpec,
    ItemResult,
    Message,
    QcReport,
    TargetSummary,
    TaskType,
)


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


def _parse_choice_options(choices: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for index, choice in enumerate(choices):
        fallback_label = chr(ord("A") + index)
        text = str(choice).strip()
        match = re.match(r"^\s*([A-Z])\s*[\).:：]\s*(.+?)\s*$", text, flags=re.IGNORECASE)
        if match:
            parsed[match.group(1).upper()] = match.group(2).strip()
        else:
            parsed[fallback_label] = text
    return parsed


def _boxed_contents(text: str) -> list[str]:
    contents: list[str] = []
    marker = r"\boxed"
    start = 0
    while True:
        marker_index = text.find(marker, start)
        if marker_index < 0:
            break
        brace_index = text.find("{", marker_index + len(marker))
        if brace_index < 0:
            break
        depth = 0
        for index in range(brace_index, len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    contents.append(text[brace_index + 1 : index].strip())
                    start = index + 1
                    break
        else:
            break
    return contents


def _normalize_choice_text(text: str) -> str:
    normalized = text.strip()
    boxed = _boxed_contents(normalized)
    if len(boxed) == 1 and normalized.startswith(r"\boxed"):
        normalized = boxed[0]
    else:
        for content in boxed:
            normalized = normalized.replace(r"\boxed{" + content + "}", f" {content} ")
    normalized = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"\1/\2", normalized)
    normalized = re.sub(r"\\sqrt\s*\[([^]]+)\]\s*\{([^{}]+)\}", r"root\1(\2)", normalized)
    normalized = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"sqrt(\1)", normalized)
    normalized = re.sub(r"\\text\s*\{([^{}]+)\}", r"\1", normalized)
    normalized = re.sub(r"\\left|\\right|\\[()[\\]{}$]", " ", normalized)
    normalized = normalized.replace("√", "sqrt")
    normalized = re.sub(r"\\+", "", normalized)
    normalized = normalized.replace("*", "")
    normalized = normalized.replace(",", "")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.strip(" .,:;，。；：")
    if normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    return normalized.lower()


def _choice_answer_candidates(response: str) -> list[str]:
    candidates: list[str] = []
    boxed = _boxed_contents(response)
    candidates.extend(boxed)
    if len(boxed) > 1:
        candidates.append(" ".join(boxed))
    for pattern in (
        r"(?:final\s+answer|answer|option|choice|答案|选项)\s*(?:is|为|是)?\s*[:=：]?\s*([A-Z]|\$?[-+]?[\d,]+(?:\.\d+)?%?|\\?[A-Za-z0-9_{}^./%+-]+)",
        r"\*\*\s*([A-Z])\s*[\).:：]",
        r"所以\s*(?:答案|结果)?\s*(?:是|为|=|:|：)?\s*([A-Z]|[-+]?\d+(?:\.\d+)?)",
    ):
        candidates.extend(match.group(1) for match in re.finditer(pattern, response, flags=re.IGNORECASE))
    nonempty_lines = [line.strip() for line in response.splitlines() if line.strip()]
    if nonempty_lines:
        candidates.append(nonempty_lines[-1])
    candidates.append(response)
    return candidates


def _choice_answer_letter(answer: str, choices: list[str] | None) -> tuple[str | None, str | None]:
    stripped = (answer or "").strip()
    options = _parse_choice_options(choices or [])
    if not stripped:
        return None, None
    if len(stripped) == 1 and "A" <= stripped.upper() <= "Z":
        letter = stripped.upper()
        return letter, options.get(letter)
    match = re.match(r"^\s*([A-Z])\s*[\).:：]\s*(.+?)\s*$", stripped, flags=re.IGNORECASE)
    if match:
        letter = match.group(1).upper()
        return letter, options.get(letter) or match.group(2).strip()
    normalized_answer = _normalize_choice_text(stripped)
    for letter, text in options.items():
        if normalized_answer == _normalize_choice_text(text) or normalized_answer == _normalize_choice_text(
            f"{letter}. {text}"
        ):
            return letter, text
    return None, None


def _score_choice(response: str, answer: str | None, choices: list[str] | None = None) -> float:
    if not answer:
        return 0.0
    letter, expected_text = _choice_answer_letter(answer, choices)
    if not letter:
        return 0.0

    if not expected_text:
        return 0.0
    expected = _normalize_choice_text(expected_text)
    if not expected:
        return 0.0
    expected_numbers = re.findall(r"[-+]?\d+(?:\.\d+)?", expected)
    for candidate in _choice_answer_candidates(response):
        normalized = _normalize_choice_text(candidate)
        if normalized == letter.lower() or normalized == expected:
            return 1.0
        candidate_numbers = re.findall(r"[-+]?\d+(?:\.\d+)?", normalized)
        if len(expected_numbers) >= 2 and all(number in candidate_numbers for number in expected_numbers):
            return 1.0
    return 0.0


def _is_judge_failure(reasoning: str | None) -> bool:
    if not reasoning:
        return False
    lowered = reasoning.lower()
    return "judge returned invalid json" in lowered or "no orchestrator configured for llm judge" in lowered


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


def _target_user_content(item: BenchmarkItem, target: object) -> str | list[dict[str, Any]] | None:
    if not get_multimodal_spec(item):
        return None
    return build_multimodal_user_content(item, _target_prompt(item), getattr(target, "provider", "openai"))


def _score_from_judge_data(data: dict) -> tuple[float, str]:
    normalized = data.get("score_normalized")
    if normalized is None:
        normalized = float(data.get("score_raw", 0) or 0) / 5.0
    return max(0.0, min(1.0, float(normalized))), str(data.get("reasoning", ""))


def _call_task_agent_json(
    item: BenchmarkItem,
    payload: dict[str, Any],
    config: BenchmarkConfig,
    *,
    system_fallback: str,
    max_tokens: int = 1024,
) -> dict[str, Any] | None:
    if not task_agent_available(config):
        return None
    settings = task_agent_model_settings(config)
    messages = [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))]
    raw = call_llm(
        messages,
        system=task_agent_system_prompt(item, system_fallback),
        model=settings["model"],
        api_key=settings["api_key"],
        base_url=settings["base_url"],
        backend=config.llm_backend,
        max_tokens=max_tokens,
    )
    try:
        parsed = extract_json(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _judge_item(item: BenchmarkItem, response: str, config: BenchmarkConfig) -> tuple[float, str]:
    scoring = task_agent_scoring(item)
    scoring_method = str(scoring.get("method") or "").strip().lower()
    if scoring and scoring_method in {"agent_judge", "task_agent_judge"} and task_agent_available(config):
        payload = {
            "instruction": "Score the target model transcript/response from 1 to 5 using the task scoring guidance. Return JSON only.",
            "item": item.model_dump(mode="json"),
            "model_response": response,
            "task_agent_scoring": scoring,
            "initial_content": task_agent_initial_content_text(item),
            "output_schema": {"score_raw": 3, "score_normalized": 0.6, "reasoning": "..."},
        }
        data = _call_task_agent_json(
            item,
            payload,
            config,
            system_fallback=(
                "You are the task-specific evaluation judge for this item. "
                "Apply only the provided scoring guidance and return JSON only."
            ),
        )
        if data is None:
            return 0.0, "Task agent judge returned invalid JSON."
        score, reason = _score_from_judge_data(data)
        return score, f"task_agent_judge: {reason}"
    if not config.orchestrator_api_key:
        return 0.0, "No orchestrator configured for LLM judge."

    base_prompt = {
        "instruction": "Score the model response from 1 to 5 using the rubric. Return JSON only.",
        "item": item.model_dump(mode="json"),
        "model_response": response,
        "task_agent_scoring": scoring or None,
        "initial_content": task_agent_initial_content_text(item) or None,
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
    scripted = task_agent_scripted_turns(item)
    if scripted:
        return scripted
    if get_task_agent_spec(item):
        return []
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


def _task_agent_next_turn(
    item: BenchmarkItem,
    history: list[Message],
    config: BenchmarkConfig,
    *,
    step_index: int,
) -> tuple[str | None, str | None]:
    if not get_task_agent_spec(item) or not task_agent_available(config):
        return None, "No task_agent metadata or task agent credentials configured."
    payload = {
        "instruction": (
            "Generate the next short user turn for this multi-turn evaluation, or set done=true if the "
            "dialogue should stop. Return JSON only."
        ),
        "item": item.model_dump(mode="json"),
        "step_index": step_index,
        "transcript": transcript_text(history),
        "initial_content": task_agent_initial_content_text(item),
        "output_schema": {"done": False, "turn": "next user message", "reasoning": "brief private rationale"},
    }
    data = _call_task_agent_json(
        item,
        payload,
        config,
        system_fallback=(
            "You are a task-specific user simulator for a multi-turn model evaluation. "
            "Follow the item instructions, keep turns concise, and return JSON only."
        ),
    )
    if not isinstance(data, dict):
        return None, "Task agent returned invalid JSON for next turn."
    if bool(data.get("done")):
        return None, None
    turn = str(data.get("turn") or "").strip()
    if not turn:
        return None, "Task agent did not provide a follow-up turn."
    return turn, None


def _run_multi_turn(item: BenchmarkItem, target: object, config: BenchmarkConfig) -> tuple[str, float, str]:
    history: list[Message] = []
    initial_prompt = task_agent_initial_user_message(item)
    first = call_target_model(initial_prompt, target, history=history, backend=config.llm_backend)
    history.extend([Message(role="user", content=initial_prompt), Message(role="assistant", content=first)])
    scripted = _multi_turn_followups(item, config)
    task_agent_errors: list[str] = []
    for followup in scripted:
        answer = call_target_model(followup, target, history=history, backend=config.llm_backend)
        history.extend([Message(role="user", content=followup), Message(role="assistant", content=answer)])
    if not scripted and get_task_agent_spec(item):
        for step_index in range(task_agent_max_turns(item)):
            followup, error = _task_agent_next_turn(item, history, config, step_index=step_index + 1)
            if error:
                task_agent_errors.append(error)
                break
            if not followup:
                break
            answer = call_target_model(followup, target, history=history, backend=config.llm_backend)
            history.extend([Message(role="user", content=followup), Message(role="assistant", content=answer)])
    transcript = transcript_text(history)
    score, reasoning = _judge_item(item, transcript, config)
    if task_agent_errors:
        reasoning = reasoning + "\n" + "\n".join(f"task_agent_error={error}" for error in task_agent_errors)
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
        if item.task_type == TaskType.multi_turn:
            raw, score, reasoning = _run_multi_turn(item, target, config)
            latency_ms = round((time.monotonic() - start) * 1000)
            return ItemResult(
                item_id=item.id,
                target_id=target.id,
                raw_response=raw,
                score=score,
                judge_reasoning=reasoning,
                error=reasoning if _is_judge_failure(reasoning) else None,
                latency_ms=latency_ms,
            )
        if item.task_type == TaskType.agent_interaction:
            raw, score, reasoning = _run_agent_interaction(item, target, config)
            latency_ms = round((time.monotonic() - start) * 1000)
            return ItemResult(
                item_id=item.id,
                target_id=target.id,
                raw_response=raw,
                score=score,
                judge_reasoning=reasoning,
                latency_ms=latency_ms,
            )
        if item.task_type == TaskType.pairwise_preference:
            raw, score, reasoning, error = _run_pairwise_preference(item, target, config)
            latency_ms = round((time.monotonic() - start) * 1000)
            return ItemResult(
                item_id=item.id,
                target_id=target.id,
                raw_response=raw,
                score=score,
                judge_reasoning=reasoning or error,
                error=error,
                latency_ms=latency_ms,
            )
        prompt_text = _target_prompt(item)
        user_content = _target_user_content(item, target)
        if user_content is None:
            response = call_target_model(prompt_text, target, backend=config.llm_backend)
        else:
            response = call_target_model(
                prompt_text,
                target,
                backend=config.llm_backend,
                user_content=user_content,
            )
        latency_ms = round((time.monotonic() - start) * 1000)
        if item.task_type == TaskType.yes_no:
            score = _score_yes_no(response, item.answer)
            return ItemResult(item_id=item.id, target_id=target.id, raw_response=response, score=score, latency_ms=latency_ms)
        if item.task_type == TaskType.multiple_choice:
            score = _score_choice(response, item.answer, item.choices)
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
        score, reasoning = _judge_item(item, response, config)
        return ItemResult(
            item_id=item.id,
            target_id=target.id,
            raw_response=response,
            score=score,
            judge_reasoning=reasoning,
            error=reasoning if _is_judge_failure(reasoning) else None,
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
        scored_results = [result for result in target_results if not result.error]
        avg = sum(result.score for result in scored_results) / len(scored_results) if scored_results else 0.0
        by_dimension: dict[str, float] = {}
        for dimension in dataset.spec.dimensions:
            dim_results = [
                result
                for result in scored_results
                if item_by_id.get(result.item_id)
                and item_by_id[result.item_id].dimension_id == dimension.id
            ]
            if dim_results:
                by_dimension[dimension.id] = sum(result.score for result in dim_results) / len(dim_results)
        by_type: dict[str, float] = {}
        for task_type in TaskType:
            type_results = [
                result
                for result in scored_results
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
