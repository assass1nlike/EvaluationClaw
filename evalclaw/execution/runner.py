"""Runner: execute accepted benchmark items against one or more target models."""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from ..diagnostics import _io_path, new_debug_dir, safe_name, write_json
from ..models.llm import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    call_llm,
    call_target_model,
    extract_json,
)
from ..models.roles import resolve_task_model
from ..protocols.assets import (
    build_asset_user_content,
    replace_non_agent_asset_references,
)
from ..protocols.task_agent import (
    get_task_agent_spec,
    task_agent_available,
    task_agent_initial_content_text,
    task_agent_initial_user_message,
    task_agent_max_turns,
    task_agent_scoring,
    task_agent_scripted_turns,
    task_agent_system_prompt,
    transcript_text,
)
from ..runners.agent import parse_agent_action as _parse_agent_action
from ..runners.agent import run_agent_interaction as _run_agent_interaction
from ..runners.credentials import target_has_credentials as _target_has_credentials
from ..runners.prompts import target_prompt as _target_prompt
from ..types import (
    BenchmarkConfig,
    BenchmarkItem,
    EvalRun,
    EvalSpec,
    ItemResult,
    Message,
    QcReport,
    TargetSummary,
    TaskSuite,
    TaskType,
)
from .plan import build_execution_plan
from .sandbox import build_code_harness, run_python_sandbox


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
    normalized = normalized.replace("\u221a", "sqrt")
    normalized = re.sub(r"\\+", "", normalized)
    normalized = normalized.replace("*", "")
    normalized = normalized.replace(",", "")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.strip(" .,:;\uff0c\u3002\uff1b\uff1a")
    if normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    return normalized.lower()


def _selected_choice_ids(response: str, item: BenchmarkItem) -> set[str] | None:
    by_lower = {choice.id.lower(): choice.id for choice in item.choices}
    text_by_lower = {_normalize_choice_text(choice.text): choice.id for choice in item.choices}
    stripped = response.strip()
    try:
        parsed = json.loads(stripped)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        parsed = parsed.get("choice_ids")
    if isinstance(parsed, list):
        values = [str(value).strip().lower() for value in parsed]
    else:
        answer_text = re.sub(
            r"^\s*(?:final\s+answer|answer|choices?|options?|\u7b54\u6848|\u9009\u9879)\s*[:=\uff1a]\s*",
            "",
            stripped,
            flags=re.IGNORECASE,
        )
        exact_text_id = text_by_lower.get(_normalize_choice_text(answer_text))
        if exact_text_id:
            return {exact_text_id}
        values = [value.lower() for value in re.split(r"[\s,;]+", answer_text) if value]
    if not values or any(value not in by_lower for value in values):
        return None
    return {by_lower[value] for value in values}


def _score_choice(response: str, item: BenchmarkItem) -> float:
    selected = _selected_choice_ids(response, item)
    return 1.0 if selected is not None and selected == set(item.correct_choice_ids) else 0.0


def _is_judge_failure(reasoning: str | None) -> bool:
    if not reasoning:
        return False
    lowered = reasoning.lower()
    return "judge returned invalid json" in lowered or "no judge model configured" in lowered


def _score_fill_blank(response: str, expected_texts: list[str]) -> float:
    normalized = response.strip()
    return 1.0 if any(normalized == expected.strip() for expected in expected_texts) else 0.0


def _call_judge_json(
    prompt: dict,
    config: BenchmarkConfig,
    judge_config,
    *,
    trace_dir: Path | None = None,
    trace_name: str = "judge",
) -> dict | None:
    messages = [Message(role="user", content=json.dumps(prompt, ensure_ascii=False, indent=2))]
    data: dict | None = None
    for attempt in range(1, 3):
        raw = call_llm(
            messages,
            model=judge_config.model,
            provider=judge_config.provider,
            api_key=judge_config.api_key,
            base_url=judge_config.base_url,
            backend=config.llm_backend,
            max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            trace_dir=trace_dir,
            trace_name=f"{trace_name}-{attempt:02d}",
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
    if not item.assets:
        return None
    return build_asset_user_content(item, _target_prompt(item), getattr(target, "provider", "openai"))


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
    trace_dir: Path | None = None,
    trace_name: str = "task-agent",
) -> dict[str, Any] | None:
    model_config = resolve_task_model(config, item)
    if model_config is None:
        return None
    messages = [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))]
    raw = call_llm(
        messages,
        system=task_agent_system_prompt(item, system_fallback),
        model=model_config.model,
        api_key=model_config.api_key,
        base_url=model_config.base_url,
        provider=model_config.provider,
        backend=config.llm_backend,
        max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        trace_dir=trace_dir,
        trace_name=trace_name,
    )
    try:
        parsed = extract_json(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _judge_item(
    item: BenchmarkItem,
    response: str,
    config: BenchmarkConfig,
    *,
    external_evidence: list[dict[str, object]] | None = None,
    trace_dir: Path | None = None,
) -> tuple[float, str]:
    scoring = task_agent_scoring(item)
    scoring_method = str(scoring.get("method") or "").strip().lower()
    if scoring and scoring_method in {"agent_judge", "task_agent_judge"} and task_agent_available(config):
        payload = {
            "instruction": "Score the target model transcript/response from 1 to 5 using the task scoring guidance. Return JSON only.",
            "item": item.model_dump(mode="json"),
            "model_response": response,
            "task_agent_scoring": scoring,
            "initial_content": task_agent_initial_content_text(item),
            "external_evidence": external_evidence or [],
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
            trace_dir=trace_dir,
            trace_name="task-agent-judge",
        )
        if data is None:
            return 0.0, "Task agent judge returned invalid JSON."
        score, reason = _score_from_judge_data(data)
        return score, f"task_agent_judge: {reason}"
    judge_config = resolve_task_model(config, item)
    if judge_config is None:
        raise RuntimeError(
            "Item requires an LLM judge but no task model is configured; "
            "pass --task-model to score generation/multi_turn items."
        )

    base_prompt = {
        "instruction": "Score the model response from 1 to 5 using the rubric. Return JSON only.",
        "item": item.model_dump(mode="json"),
        "model_response": response,
        "task_agent_scoring": scoring or None,
        "initial_content": task_agent_initial_content_text(item) or None,
        "external_evidence": external_evidence or [],
        "output_schema": {"score_raw": 3, "score_normalized": 0.6, "reasoning": "..."},
    }
    first = _call_judge_json(
        base_prompt,
        config,
        judge_config,
        trace_dir=trace_dir,
        trace_name="judge-first-pass",
    )
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
    second = _call_judge_json(
        swap_prompt,
        config,
        judge_config,
        trace_dir=trace_dir,
        trace_name="judge-second-pass",
    )
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


def _python_test_evidence(
    item: BenchmarkItem,
    response: str,
    config: BenchmarkConfig,
) -> dict[str, object]:
    tool = next((tool for tool in item.judge_tools if tool.tool == "python_tests"), None)
    test_code = str(tool.config.get("test_code") or "") if tool else ""
    if not test_code:
        return {"tool": "python_tests", "passed": False, "error": "Missing test_code in tool config."}
    code = build_code_harness(test_code, response)
    try:
        returncode, stdout, stderr = run_python_sandbox(
            code,
            timeout=10,
            image=config.container_sandbox_image,
            docker_executable=config.docker_executable,
        )
        return {
            "tool": "python_tests",
            "passed": returncode == 0,
            "returncode": returncode,
            "stdout": stdout[:800],
            "stderr": stderr[:800],
        }
    except Exception as exc:
        return {"tool": "python_tests", "passed": False, "error": str(exc)}


def _judge_tool_evidence(
    item: BenchmarkItem,
    response: str,
    config: BenchmarkConfig,
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    for tool in item.judge_tools:
        if tool.tool == "python_tests":
            evidence.append(_python_test_evidence(item, response, config))
    return evidence


def _multi_turn_followups(
    item: BenchmarkItem,
    config: BenchmarkConfig,
    *,
    trace_dir: Path | None = None,
) -> list[str]:
    scripted = task_agent_scripted_turns(item)
    if scripted:
        return scripted
    if get_task_agent_spec(item):
        return []
    judge_config = resolve_task_model(config, item)
    if judge_config is None:
        return []
    prompt = {
        "instruction": "Generate 1-3 short user follow-up turns for this multi-turn evaluation. Return JSON only.",
        "item": item.model_dump(mode="json"),
        "schema": {"turns": ["follow-up 1", "follow-up 2"]},
    }
    raw = call_llm(
        [Message(role="user", content=json.dumps(prompt, ensure_ascii=False, indent=2))],
        model=judge_config.model,
        provider=judge_config.provider,
        api_key=judge_config.api_key,
        base_url=judge_config.base_url,
        backend=config.llm_backend,
        max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        trace_dir=trace_dir,
        trace_name="multi-turn-plan",
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
    trace_dir: Path | None = None,
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
        trace_dir=trace_dir,
        trace_name=f"task-agent-turn-{step_index:02d}",
    )
    if not isinstance(data, dict):
        return None, "Task agent returned invalid JSON for next turn."
    if bool(data.get("done")):
        return None, None
    turn = str(data.get("turn") or "").strip()
    if not turn:
        return None, "Task agent did not provide a follow-up turn."
    return turn, None


def _run_multi_turn(
    item: BenchmarkItem,
    target: object,
    config: BenchmarkConfig,
    *,
    trace_dir: Path | None = None,
) -> tuple[str, float, str]:
    history: list[Message] = []
    initial_prompt = task_agent_initial_user_message(item)
    initial_content = (
        build_asset_user_content(item, initial_prompt, getattr(target, "provider", "openai"))
        if item.assets
        else None
    )
    visible_initial_prompt = (
        replace_non_agent_asset_references(initial_prompt, item.assets)
        if item.assets
        else initial_prompt
    )
    first = call_target_model(
        initial_prompt,
        target,
        history=history,
        backend=config.llm_backend,
        user_content=initial_content,
        trace_dir=trace_dir,
        trace_name="target-turn-01",
    )
    history.extend([Message(role="user", content=visible_initial_prompt), Message(role="assistant", content=first)])
    scripted = _multi_turn_followups(item, config, trace_dir=trace_dir)
    task_agent_errors: list[str] = []
    for turn_index, followup in enumerate(scripted, 2):
        answer = call_target_model(
            followup,
            target,
            history=history,
            backend=config.llm_backend,
            trace_dir=trace_dir,
            trace_name=f"target-turn-{turn_index:02d}",
        )
        history.extend([Message(role="user", content=followup), Message(role="assistant", content=answer)])
    if not scripted and get_task_agent_spec(item):
        for step_index in range(task_agent_max_turns(item)):
            followup, error = _task_agent_next_turn(
                item,
                history,
                config,
                step_index=step_index + 1,
                trace_dir=trace_dir,
            )
            if error:
                task_agent_errors.append(error)
                break
            if not followup:
                break
            answer = call_target_model(
                followup,
                target,
                history=history,
                backend=config.llm_backend,
                trace_dir=trace_dir,
                trace_name=f"target-turn-{len(history) // 2 + 1:02d}",
            )
            history.extend([Message(role="user", content=followup), Message(role="assistant", content=answer)])
    transcript = transcript_text(history)
    score, reasoning = _judge_item(item, transcript, config, trace_dir=trace_dir)
    if task_agent_errors:
        reasoning = reasoning + "\n" + "\n".join(f"task_agent_error={error}" for error in task_agent_errors)
    return json.dumps([message.model_dump() for message in history], ensure_ascii=False), score, reasoning


def _run_item(
    item: BenchmarkItem,
    config: BenchmarkConfig,
    target_id: str,
    *,
    trace_dir: Path | None = None,
) -> ItemResult:
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
            raw, score, reasoning = _run_multi_turn(
                item,
                target,
                config,
                trace_dir=trace_dir,
            )
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
        if item.task_type == TaskType.agent:
            raw, score, reasoning = _run_agent_interaction(
                item,
                target,
                config,
                artifact_dir=trace_dir,
            )
            latency_ms = round((time.monotonic() - start) * 1000)
            return ItemResult(
                item_id=item.id,
                target_id=target.id,
                raw_response=raw,
                score=score,
                judge_reasoning=reasoning,
                latency_ms=latency_ms,
            )
        prompt_text = _target_prompt(item)
        user_content = _target_user_content(item, target)
        if user_content is None:
            response = call_target_model(
                prompt_text,
                target,
                backend=config.llm_backend,
                trace_dir=trace_dir,
                trace_name="target",
            )
        else:
            response = call_target_model(
                prompt_text,
                target,
                backend=config.llm_backend,
                user_content=user_content,
                trace_dir=trace_dir,
                trace_name="target",
            )
        latency_ms = round((time.monotonic() - start) * 1000)
        if item.task_type == TaskType.choice:
            score = _score_choice(response, item)
            return ItemResult(item_id=item.id, target_id=target.id, raw_response=response, score=score, latency_ms=latency_ms)
        if item.task_type == TaskType.fill_blank:
            score = _score_fill_blank(response, item.expected_texts)
            return ItemResult(item_id=item.id, target_id=target.id, raw_response=response, score=score, latency_ms=latency_ms)
        if item.task_type == TaskType.generation:
            evidence = _judge_tool_evidence(item, response, config)
            score, reasoning = _judge_item(
                item,
                response,
                config,
                external_evidence=evidence,
                trace_dir=trace_dir,
            )
            return ItemResult(
                item_id=item.id,
                target_id=target.id,
                raw_response=response,
                score=score,
                judge_reasoning=reasoning,
                error=reasoning if _is_judge_failure(reasoning) else None,
                latency_ms=latency_ms,
            )
        score, reasoning = _judge_item(item, response, config, trace_dir=trace_dir)
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
    suite: TaskSuite,
    results: list[ItemResult],
    config: BenchmarkConfig,
) -> list[TargetSummary]:
    item_by_id = {item.id: item for item in suite.tasks}
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
        for dimension in suite.spec.dimensions:
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
    suite: TaskSuite,
    qc_report: QcReport,
    config: BenchmarkConfig,
    *,
    on_progress: Callable[[int, int, str, str], None] | None = None,
    trace_dir: Path | None = None,
) -> EvalRun:
    """Run accepted items against all configured target models."""
    debug_dir = Path(trace_dir) if trace_dir is not None else new_debug_dir(config.output_dir, "runner")
    execution_plan = build_execution_plan(suite, qc_report)
    accepted = execution_plan.suite.tasks
    if debug_dir is not None:
        write_json(
            debug_dir / "input.json",
            {
                "accepted_item_ids": [item.id for item in accepted],
                "targets": [target.model_dump(mode="json") for target in config.targets],
                "run_targets": config.run_targets,
            },
            redact=True,
        )
    results: list[ItemResult] = []
    if config.run_targets and config.targets:
        total = len(accepted) * len(config.targets)
        jobs = [(target.id, item) for target in config.targets for item in accepted]

        def execute(target_id: str, item: BenchmarkItem) -> ItemResult:
            item_dir = (
                debug_dir / safe_name(target_id) / safe_name(item.id)
                if debug_dir is not None
                else None
            )
            if item_dir is not None:
                write_json(item_dir / "item.json", item.model_dump(mode="json"))
            cached_result = None
            if item_dir is not None and _io_path(item_dir / "result.json").is_file():
                try:
                    result_path = _io_path(item_dir / "result.json")
                    cached_result = ItemResult.model_validate(
                        json.loads(result_path.read_text(encoding="utf-8"))
                    )
                except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
                    cached_result = None
            if (
                cached_result is not None
                and cached_result.target_id == target_id
                and cached_result.item_id == item.id
                and not cached_result.error
            ):
                return cached_result
            result = _run_item(item, config, target_id, trace_dir=item_dir)
            if item_dir is not None:
                write_json(item_dir / "result.json", result.model_dump(mode="json"))
            return result

        max_workers = max(1, int(getattr(config, "runner_max_workers", 4) or 1))
        if max_workers == 1 or len(jobs) <= 1:
            completed = 0
            for target_id, item in jobs:
                result = execute(target_id, item)
                results.append(result)
                completed += 1
                if on_progress:
                    on_progress(completed, total, target_id, item.id)
        else:
            completed = 0
            with ThreadPoolExecutor(max_workers=min(max_workers, len(jobs))) as executor:
                futures: dict[Future[ItemResult], tuple[str, BenchmarkItem]] = {
                    executor.submit(execute, target_id, item): (target_id, item)
                    for target_id, item in jobs
                }
                for future in as_completed(futures):
                    target_id, item = futures[future]
                    result = future.result()
                    results.append(result)
                    completed += 1
                    if on_progress:
                        on_progress(completed, total, target_id, item.id)
    summaries = _summarize(suite, results, config)
    run = EvalRun(
        suite=suite,
        qc_report=qc_report,
        results=results,
        summaries=summaries,
        runner_artifacts={
            "judge": {"double_pass_enabled": bool(config.judge_double_pass)},
            "debug_dir": str(debug_dir) if debug_dir is not None else None,
            "execution_plan": {
                "accepted_item_ids": list(execution_plan.accepted_item_ids),
                "rejected_item_ids": list(execution_plan.rejected_item_ids),
            },
        },
    )
    if debug_dir is not None:
        write_json(debug_dir / "run.json", run.model_dump(mode="json"))
    return run


def run_item(item: BenchmarkItem, config: BenchmarkConfig) -> ItemResult:
    if not config.targets:
        raise ValueError("BenchmarkConfig.targets is empty")
    return _run_item(item, config, config.targets[0].id)
