from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..vlm import DEFAULT_LOCAL_URL, DEFAULT_MODELS, parse_vlm_json, query_vlm


_VERIFIER_MODE_ENV = "GYM_ANYTHING_VERIFIER_MODE"
_CHECKLIST_ENV_PREFIX = "GYM_ANYTHING_VLM_CHECKLIST_"


@dataclass
class VLMChecklistConfig:
    checklist: str = "vlm_checklist.json"
    backend: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    max_retries: Optional[int] = None
    temperature: float = 0.1
    top_p: float = 0.95
    max_tokens: int = 8192
    max_frames: int = -1
    frame_strategy: str = "legacy_every_third"
    completion_threshold: float = 100.0
    integrity_threshold: float = 1.0
    timeout: Optional[int] = None

    @classmethod
    def from_spec(
        cls,
        spec: Any,
        verifier_env: Optional[Dict[str, str]] = None,
    ) -> "VLMChecklistConfig":
        raw = _extract_vlm_spec(spec)
        explicit_backend = _env("BACKEND", verifier_env) or raw.get("backend")
        backend = str(explicit_backend or _base_env("VLM_BACKEND", verifier_env, "local")).lower()
        explicit_model = _env("MODEL", verifier_env) or raw.get("model")
        if explicit_model is not None:
            model = str(explicit_model)
        elif explicit_backend is not None:
            model = DEFAULT_MODELS.get(backend, DEFAULT_MODELS["local"])
        else:
            model = _base_env(
                "VLM_MODEL",
                verifier_env,
                DEFAULT_MODELS.get(backend, DEFAULT_MODELS["local"]),
            )
        checklist = (
            _env("CHECKLIST", verifier_env)
            or _env("CHECKLIST_PATH", verifier_env)
            or raw.get("checklist")
            or raw.get("checklist_path")
            or cls.checklist
        )
        return cls(
            checklist=str(checklist),
            backend=backend,
            model=str(model),
            base_url=_get_str(
                raw,
                "base_url",
                "BASE_URL",
                _base_env("VLM_BASE_URL", verifier_env, DEFAULT_LOCAL_URL),
                verifier_env,
            ),
            api_key=_get_str(raw, "api_key", "API_KEY", _provider_api_key(backend, verifier_env), verifier_env),
            max_retries=_get_int(
                raw,
                "max_retries",
                "MAX_RETRIES",
                _env_int("VLM_MAX_RETRIES", 3, verifier_env),
                verifier_env,
            ),
            temperature=_get_float(raw, "temperature", "TEMPERATURE", cls.temperature, verifier_env),
            top_p=_get_float(raw, "top_p", "TOP_P", cls.top_p, verifier_env),
            max_tokens=_get_int(raw, "max_tokens", "MAX_TOKENS", cls.max_tokens, verifier_env),
            max_frames=_get_int(raw, "max_frames", "MAX_FRAMES", cls.max_frames, verifier_env),
            frame_strategy=_get_str(raw, "frame_strategy", "FRAME_STRATEGY", cls.frame_strategy, verifier_env)
            or cls.frame_strategy,
            completion_threshold=_get_float(
                raw,
                "completion_threshold",
                "COMPLETION_THRESHOLD",
                cls.completion_threshold,
                verifier_env,
            ),
            integrity_threshold=_get_float(
                raw,
                "integrity_threshold",
                "INTEGRITY_THRESHOLD",
                cls.integrity_threshold,
                verifier_env,
            ),
            timeout=_env_int_optional("VLM_TIMEOUT", verifier_env),
        )

    def public_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("api_key", None)
        return data

    def to_vlm_config(self) -> Dict[str, Any]:
        backend = (self.backend or "local").lower()
        config: Dict[str, Any] = {
            "backend": backend,
            "model": self.model or DEFAULT_MODELS.get(backend, DEFAULT_MODELS["local"]),
            "max_retries": self.max_retries if self.max_retries is not None else 3,
        }
        if self.base_url:
            config["base_url"] = self.base_url
        if self.api_key is not None:
            config["api_key"] = self.api_key
        elif backend == "local":
            config["api_key"] = "EMPTY"
        else:
            config["api_key"] = ""
        if self.timeout is not None:
            config["timeout"] = self.timeout
        return config


def normalize_verifier_mode(mode: Optional[str]) -> Optional[str]:
    if mode is None:
        return None
    normalized = mode.strip().lower().replace("-", "_")
    if normalized in {"", "auto", "default", "task", "task_json"}:
        return None
    return normalized


def get_verifier_mode_override(verifier_env: Optional[Dict[str, str]] = None) -> Optional[str]:
    if verifier_env is not None and _VERIFIER_MODE_ENV in verifier_env:
        return normalize_verifier_mode(verifier_env.get(_VERIFIER_MODE_ENV))
    return normalize_verifier_mode(os.environ.get(_VERIFIER_MODE_ENV))


def evaluate_vlm_checklist(
    *,
    spec: Any,
    traj: Dict[str, Any],
    task_info: Dict[str, Any],
    task_root: Optional[Path],
    env_root: Optional[Path],
    verifier_env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    config = VLMChecklistConfig.from_spec(spec, verifier_env=verifier_env)
    checklist_path = _resolve_checklist_path(config.checklist, task_root, env_root)
    if checklist_path is None:
        return _failure(
            "task_root is required to resolve a relative VLM checklist path",
            config=config,
        )
    if not checklist_path.exists():
        return _failure(f"VLM checklist not found: {checklist_path}", config=config)

    try:
        checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _failure(f"failed to load VLM checklist {checklist_path}: {exc}", config=config)

    images = _select_images(traj, max_frames=config.max_frames, strategy=config.frame_strategy)
    if not images:
        return _failure("no trajectory screenshots available for VLM checklist verifier", config=config)

    prompt = build_verification_prompt(
        checklist=checklist,
        task_description=_task_description(task_info),
        image_count=len(images),
    )
    response = query_vlm(
        prompt=prompt,
        images=images,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        top_p=config.top_p,
        config=config.to_vlm_config(),
    )

    if not response.get("success"):
        return _failure(
            f"VLM query failed: {response.get('error', 'unknown error')}",
            config=config,
            images=images,
            raw_response=response.get("response", ""),
        )

    verdicts = _extract_verdicts(response)
    scores = compute_scores(
        verdicts,
        checklist,
        completion_threshold=config.completion_threshold,
        integrity_threshold=config.integrity_threshold,
    )
    feedback = scores.get("overall_reasoning") or _default_feedback(scores)
    return {
        "decided": True,
        "passed": scores["passed"],
        "score": scores["final_score"],
        "feedback": feedback,
        "config": config.public_dict(),
        "checklist_path": str(checklist_path),
        "image_count": len(images),
        "scores": scores,
        "verdicts": verdicts,
        "raw_response": response.get("response", ""),
    }


def build_verification_prompt(
    *,
    checklist: Dict[str, Any],
    task_description: str,
    image_count: int,
) -> str:
    completion_items = []
    for item in checklist.get("task_completion", []):
        completion_items.append(
            {
                "id": item.get("id"),
                "points": item.get("points"),
                "description": item.get("description"),
                "visual_evidence": item.get("visual_evidence"),
            }
        )
    integrity_items = []
    for item in checklist.get("integrity", []):
        integrity_items.append(
            {
                "id": item.get("id"),
                "description": item.get("description"),
                "visual_evidence": item.get("visual_evidence"),
            }
        )

    privileged_info = checklist.get(
        "privileged_info_for_vlm",
        "No privileged information available.",
    )
    return f"""You are an expert evaluator scoring an AI agent trajectory on a computer-use benchmark task.
You will inspect {image_count} screenshots, provided separately in chronological order.

Task description:
{task_description}

Privileged information verified for the evaluator:
{privileged_info}

Task completion checklist:
{json.dumps(completion_items, indent=2)}

Integrity checklist:
{json.dumps(integrity_items, indent=2)}

Scoring rules:
- For each task_completion item, use verdict "pass", "partial", or "fail".
- Give "pass" only when screenshots provide clear visual evidence, unless the item is clearly non-essential based on the task description and the rest of the task is complete.
- Use "partial" only for meaningful progress that does not fully satisfy the item.
- Integrity checks are only for cheating or shortcuts. Genuine failed attempts, empty outputs, or wrong outputs should usually pass integrity and fail task_completion instead.
- Mark integrity "fail" only for clear evidence of hardcoding, fabricated results, copy-pasting expected answers, or bypassing the required application workflow.

Respond with only a JSON object in this exact shape:
{{
  "task_completion": [
    {{"id": "item_id", "verdict": "pass|partial|fail", "confidence": 0.0, "evidence": "what you see"}}
  ],
  "integrity": [
    {{"id": "item_id", "verdict": "pass|fail", "confidence": 0.0, "evidence": "what you see"}}
  ],
  "overall_reasoning": "1-3 sentence summary of what the agent did and how well it performed"
}}"""


def compute_scores(
    verdicts: Dict[str, Any],
    checklist: Dict[str, Any],
    *,
    completion_threshold: float,
    integrity_threshold: float,
) -> Dict[str, Any]:
    completion_items = checklist.get("task_completion", []) or []
    completion_verdicts = _verdict_map(verdicts.get("task_completion", []))
    default_points = 100.0 / len(completion_items) if completion_items else 0.0

    raw_earned = 0.0
    raw_possible = 0.0
    completion_details = []
    for index, item in enumerate(completion_items):
        item_id = _item_id(item, index)
        points = _coerce_float(item.get("points"), default_points)
        verdict_record = completion_verdicts.get(item_id, {})
        verdict = _normalize_completion_verdict(verdict_record.get("verdict"))
        if verdict == "pass":
            earned = points
        elif verdict == "partial":
            earned = points * 0.5
        else:
            earned = 0.0
        raw_earned += earned
        raw_possible += points
        completion_details.append(
            {
                "id": item_id,
                "max_points": points,
                "earned": round(earned, 2),
                "verdict": verdict,
                "confidence": _coerce_float(verdict_record.get("confidence"), 0.0),
                "evidence": verdict_record.get("evidence", ""),
            }
        )

    completion_score = (raw_earned / raw_possible * 100.0) if raw_possible > 0 else 0.0

    integrity_items = checklist.get("integrity", []) or []
    integrity_verdicts = _verdict_map(verdicts.get("integrity", []))
    integrity_passes = 0
    integrity_details = []
    for index, item in enumerate(integrity_items):
        item_id = _item_id(item, index)
        verdict_record = integrity_verdicts.get(item_id, {})
        verdict = _normalize_integrity_verdict(verdict_record.get("verdict"))
        if verdict == "pass":
            integrity_passes += 1
        integrity_details.append(
            {
                "id": item_id,
                "verdict": verdict,
                "confidence": _coerce_float(verdict_record.get("confidence"), 0.0),
                "evidence": verdict_record.get("evidence", ""),
            }
        )

    integrity_total = len(integrity_items)
    integrity_rate = (integrity_passes / integrity_total) if integrity_total else 1.0
    integrity_passed = integrity_rate >= integrity_threshold
    final_score = completion_score if integrity_passed else 0.0
    passed = final_score >= completion_threshold and integrity_passed
    return {
        "passed": passed,
        "score_a": round(completion_score, 1),
        "score_b": integrity_passed,
        "integrity_pass_rate": f"{integrity_passes}/{integrity_total}",
        "integrity_rate": round(integrity_rate, 3),
        "final_score": round(final_score, 1),
        "completion_threshold": completion_threshold,
        "integrity_threshold": integrity_threshold,
        "completion_details": completion_details,
        "integrity_details": integrity_details,
        "overall_reasoning": verdicts.get("overall_reasoning", ""),
    }


def _failure(
    message: str,
    *,
    config: VLMChecklistConfig,
    images: Optional[Sequence[str]] = None,
    raw_response: str = "",
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "decided": True,
        "passed": False,
        "score": 0,
        "error": message,
        "feedback": message,
        "config": config.public_dict(),
    }
    if images is not None:
        result["image_count"] = len(images)
    if raw_response:
        result["raw_response"] = raw_response
    return result


def _extract_vlm_spec(spec: Any) -> Dict[str, Any]:
    if isinstance(spec, str):
        return {"checklist": spec}
    if not isinstance(spec, dict):
        return {}
    nested = spec.get("vlm_checklist")
    if isinstance(nested, dict):
        merged = {k: v for k, v in spec.items() if k != "vlm_checklist"}
        merged.update(nested)
        return merged
    if isinstance(nested, str):
        merged = {k: v for k, v in spec.items() if k != "vlm_checklist"}
        merged["checklist"] = nested
        return merged
    return spec


def _resolve_checklist_path(
    checklist: str,
    task_root: Optional[Path],
    env_root: Optional[Path],
) -> Optional[Path]:
    path = Path(checklist)
    if path.is_absolute():
        return path
    if task_root is not None:
        return task_root / path
    if env_root is not None:
        return env_root / path
    return None


def _select_images(traj: Dict[str, Any], *, max_frames: int, strategy: str) -> List[str]:
    candidates: List[str] = []
    for path in traj.get("frames", []) or []:
        if path and Path(path).exists():
            candidates.append(path)
    for key in ("final_screenshot", "post_verification_screenshot"):
        path = traj.get(key)
        if path and Path(path).exists() and path not in candidates:
            candidates.append(path)

    if not candidates:
        return []
    if max_frames <= 0:
        max_frames = len(candidates)

    strategy = (strategy or "legacy_every_third").strip().lower()
    if strategy == "all":
        selected = candidates
    elif strategy in {"legacy", "legacy_every_third", "first3_every3_last3"}:
        selected = candidates[:3] + candidates[3:-3:3] + candidates[-3:]
    else:
        selected = _uniform_sample(candidates, max_frames)

    deduped = list(dict.fromkeys(selected))
    if len(deduped) > max_frames:
        deduped = _uniform_sample(deduped, max_frames)
    return deduped


def _uniform_sample(items: Sequence[str], count: int) -> List[str]:
    if count <= 0 or len(items) <= count:
        return list(items)
    if count == 1:
        return [items[-1]]
    indices = {round(i * (len(items) - 1) / (count - 1)) for i in range(count)}
    return [items[i] for i in sorted(indices)]


def _extract_verdicts(response: Dict[str, Any]) -> Dict[str, Any]:
    parsed = response.get("parsed")
    if isinstance(parsed, dict) and (
        "task_completion" in parsed or "integrity" in parsed or "overall_reasoning" in parsed
    ):
        return parsed
    parsed_text = parse_vlm_json(response.get("response", ""))
    return parsed_text if isinstance(parsed_text, dict) else {}


def _verdict_map(records: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(records, list):
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        item_id = str(record.get("id", "")).strip()
        if item_id:
            result[item_id] = record
    return result


def _item_id(item: Dict[str, Any], index: int) -> str:
    return str(item.get("id") or f"item_{index + 1}")


def _normalize_completion_verdict(value: Any) -> str:
    text = str(value or "fail").strip().lower()
    if text in {"pass", "passed", "yes", "true", "complete", "completed"}:
        return "pass"
    if text in {"partial", "partially", "partially_passed", "incomplete"}:
        return "partial"
    return "fail"


def _normalize_integrity_verdict(value: Any) -> str:
    text = str(value or "fail").strip().lower()
    return "pass" if text in {"pass", "passed", "yes", "true"} else "fail"


def _task_description(task_info: Dict[str, Any]) -> str:
    task_spec = task_info.get("task_spec") or {}
    if isinstance(task_spec, dict) and task_spec.get("description"):
        return str(task_spec["description"])
    if task_info.get("description"):
        return str(task_info["description"])
    return ""


def _default_feedback(scores: Dict[str, Any]) -> str:
    score = scores.get("final_score", 0)
    integrity = "passed" if scores.get("score_b") else "failed"
    return f"VLM checklist score {score}; integrity {integrity}."


def _base_env(
    name: str,
    verifier_env: Optional[Dict[str, str]] = None,
    default: Optional[str] = None,
) -> Optional[str]:
    if verifier_env is not None and name in verifier_env:
        value = verifier_env.get(name)
        return default if value in (None, "") else str(value)
    return os.environ.get(name, default)


def _env(name: str, verifier_env: Optional[Dict[str, str]] = None) -> Optional[str]:
    key = _CHECKLIST_ENV_PREFIX + name
    if verifier_env is not None and key in verifier_env:
        value = verifier_env.get(key)
        return None if value in (None, "") else str(value)
    value = os.environ.get(key)
    if value is None or value == "":
        return None
    return value


def _env_int(name: str, default: int, verifier_env: Optional[Dict[str, str]] = None) -> int:
    try:
        return int(_base_env(name, verifier_env, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int_optional(name: str, verifier_env: Optional[Dict[str, str]] = None) -> Optional[int]:
    value = _base_env(name, verifier_env, None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _provider_api_key(backend: str, verifier_env: Optional[Dict[str, str]] = None) -> Optional[str]:
    if backend == "openai":
        return _base_env("OPENAI_API_KEY", verifier_env, "")
    if backend == "anthropic":
        return _base_env("ANTHROPIC_API_KEY", verifier_env, "")
    if backend == "gemini":
        return _base_env("GEMINI_API_KEY", verifier_env, "")
    return _base_env("VLM_API_KEY", verifier_env, "EMPTY")


def _get_str(
    raw: Dict[str, Any],
    key: str,
    env_suffix: str,
    default: Optional[str],
    verifier_env: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    env_value = _env(env_suffix, verifier_env)
    if env_value is not None:
        return env_value
    value = raw.get(key)
    if value is None:
        return default
    return str(value)


def _get_int(
    raw: Dict[str, Any],
    key: str,
    env_suffix: str,
    default: Optional[int],
    verifier_env: Optional[Dict[str, str]] = None,
) -> Optional[int]:
    value = _env(env_suffix, verifier_env)
    if value is None:
        value = raw.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_float(
    raw: Dict[str, Any],
    key: str,
    env_suffix: str,
    default: float,
    verifier_env: Optional[Dict[str, str]] = None,
) -> float:
    value = _env(env_suffix, verifier_env)
    if value is None:
        value = raw.get(key)
    return _coerce_float(value, default)


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "VLMChecklistConfig",
    "build_verification_prompt",
    "compute_scores",
    "evaluate_vlm_checklist",
    "get_verifier_mode_override",
    "normalize_verifier_mode",
]
