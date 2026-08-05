"""Shared helpers for EvalClaw experiments: config, metrics, LLM audits, reports.

Plain-script utilities used by run_ab_deep_research.py and run_ranking_check.py.
Every metric degrades gracefully: LLM audits return {"skipped": ...} without a
key, and semantic diversity falls back to token-Jaccard when no embedding model
is configured or the embedding call fails.
"""
from __future__ import annotations

import contextlib
import json
import math
import re
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

from evalclaw.models.json_utils import extract_json
from evalclaw.models.llm import call_llm
from evalclaw.types import Message

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG: dict = {
    "goals": [
        "Evaluate models' tax law reasoning ability",
        "Evaluate models' understanding of materials science laboratory safety",
        "Evaluate an agent's ability to understand and modify a legacy codebase",
    ],
    "orchestrator_model": "azure/gpt-4o",
    "strong_target": "azure/gpt-4o",
    "weak_target": "azure/gpt-4o-mini",
    "embedding_model": None,  # e.g. "azure/text-embedding-3-small"
    "scale_budget": "low",
    "search_backend": "auto",
    "questions_per_dimension": 3,
    "max_research_iterations": 3,
    "item_audit_sample_per_dimension": 3,
    "item_audit_sample_cap": 12,
    "llm_backend": "auto",
    "output_root": "experiments/results",
}


def load_config(path: str | Path | None) -> dict:
    """Load an experiment config JSON, merged over DEFAULT_CONFIG."""
    config = dict(DEFAULT_CONFIG)
    if path:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        config.update({key: value for key, value in payload.items() if value is not None})
    return config


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug[:limit] or "experiment"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class _Tee:
    """File-like object duplicating writes to a stream and a log file."""

    def __init__(self, stream, log_file) -> None:
        self._stream = stream
        self._log = log_file

    def write(self, data: str) -> int:
        n = self._stream.write(data)
        self._log.write(data)
        self._log.flush()
        return n

    def flush(self) -> None:
        self._stream.flush()
        self._log.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


@contextlib.contextmanager
def tee_output(log_path: Path):
    """Duplicate stdout/stderr to ``log_path`` for the duration of the block."""
    import sys

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"\n===== run started {time.strftime('%Y-%m-%dT%H:%M:%S%z')} =====\n")
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = _Tee(old_out, log_file)
        sys.stderr = _Tee(old_err, log_file)
        try:
            yield
        finally:
            sys.stdout, sys.stderr = old_out, old_err


# ---------------------------------------------------------------------------
# Metrics: semantic diversity
# ---------------------------------------------------------------------------
def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{2,}", text.lower()))


def jaccard_distance(a: str, b: str) -> float:
    """1 - Jaccard similarity over word tokens. 0.0 identical, 1.0 disjoint."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 0.0
    union = ta | tb
    if not union:
        return 0.0
    return 1.0 - len(ta & tb) / len(union)


def cosine_distance(u: Sequence[float], v: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(u, v))
    nu = math.sqrt(sum(x * x for x in u))
    nv = math.sqrt(sum(y * y for y in v))
    if nu == 0.0 or nv == 0.0:
        return 0.0
    return 1.0 - dot / (nu * nv)


def _mean_pairwise(items: list, distance: Callable) -> float:
    total, count = 0.0, 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            total += distance(items[i], items[j])
            count += 1
    return total / count if count else 0.0


def semantic_diversity(
    texts: Sequence[str],
    *,
    embed_fn: Optional[Callable[[list[str]], list[Sequence[float]]]] = None,
    max_texts: int = 100,
) -> dict:
    """Mean pairwise distance of texts.

    Uses embeddings (cosine distance) when embed_fn is provided and succeeds;
    otherwise falls back to token-Jaccard distance so the metric never
    hard-fails.
    """
    texts = [t for t in texts if t and t.strip()][:max_texts]
    if len(texts) < 2:
        return {"method": "none", "mean_pairwise_distance": None, "texts": len(texts),
                "note": "fewer than 2 texts"}
    note = ""
    if embed_fn is not None:
        try:
            vectors = embed_fn(list(texts))
            if vectors and len(vectors) == len(texts):
                return {
                    "method": "embedding",
                    "mean_pairwise_distance": round(_mean_pairwise(list(vectors), cosine_distance), 4),
                    "texts": len(texts),
                }
            note = "embedding returned wrong shape; fell back to jaccard"
        except Exception as exc:
            note = f"embedding failed ({exc}); fell back to jaccard"
    result = {
        "method": "jaccard",
        "mean_pairwise_distance": round(_mean_pairwise(list(texts), jaccard_distance), 4),
        "texts": len(texts),
    }
    if note:
        result["note"] = note
    return result


def make_litellm_embed_fn(model: str, api_key: str | None = None) -> Callable:
    """Build an embed_fn backed by litellm.embedding (supports azure/<deployment>)."""

    def embed(texts: list[str]) -> list[Sequence[float]]:
        import litellm

        kwargs = {"model": model, "input": texts, "timeout": 120}
        if api_key:
            kwargs["api_key"] = api_key
        response = litellm.embedding(**kwargs)
        data = response["data"] if isinstance(response, dict) else response.data
        return [
            entry["embedding"] if isinstance(entry, dict) else entry.embedding
            for entry in data
        ]

    return embed


# ---------------------------------------------------------------------------
# Metrics: discriminative power
# ---------------------------------------------------------------------------
def _summary_field(summary, field: str):
    if isinstance(summary, dict):
        return summary.get(field)
    return getattr(summary, field, None)


def discriminative_power(summaries: Sequence, strong_id: str, weak_id: str) -> dict:
    """Strong-vs-weak average score gap from EvalRun target summaries."""
    by_id = {_summary_field(s, "target_id"): s for s in summaries}
    strong = by_id.get(strong_id)
    weak = by_id.get(weak_id)
    if strong is None or weak is None:
        return {
            "skipped": (
                f"missing target summaries (have: {sorted(k for k in by_id if k)}; "
                f"need: {strong_id}, {weak_id})"
            )
        }
    strong_avg = float(_summary_field(strong, "average_score") or 0.0)
    weak_avg = float(_summary_field(weak, "average_score") or 0.0)
    gap = strong_avg - weak_avg
    return {
        "strong_id": strong_id,
        "weak_id": weak_id,
        "strong_avg": round(strong_avg, 4),
        "weak_avg": round(weak_avg, 4),
        "gap": round(gap, 4),
        "order_correct": gap > 0,
    }


def per_dimension_gaps(summaries: Sequence, strong_id: str, weak_id: str) -> dict[str, float]:
    by_id = {_summary_field(s, "target_id"): s for s in summaries}
    strong = by_id.get(strong_id)
    weak = by_id.get(weak_id)
    if strong is None or weak is None:
        return {}
    strong_scores = _summary_field(strong, "score_by_dimension") or {}
    weak_scores = _summary_field(weak, "score_by_dimension") or {}
    return {
        dim: round(float(strong_scores[dim]) - float(weak_scores[dim]), 4)
        for dim in sorted(set(strong_scores) & set(weak_scores))
    }


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
def stratified_sample(items: Sequence, per_dimension: int = 3, cap: int = 12) -> list:
    """Take up to per_dimension items from each dimension, capped overall.

    Deterministic (keeps original order) so runs are reproducible.
    """
    taken_by_dim: dict[str, int] = {}
    sample: list = []
    for item in items:
        dim = getattr(item, "dimension_id", None) or (
            item.get("dimension_id") if isinstance(item, dict) else "unknown"
        )
        if taken_by_dim.get(dim, 0) >= per_dimension:
            continue
        taken_by_dim[dim] = taken_by_dim.get(dim, 0) + 1
        sample.append(item)
        if len(sample) >= cap:
            break
    return sample


# ---------------------------------------------------------------------------
# LLM audits (skipped gracefully without a key)
# ---------------------------------------------------------------------------
COVERAGE_AUDIT_SYSTEM_PROMPT = """\
You audit an automatically generated evaluation spec against the user's goal.
Input JSON: {"goal": "...", "dimensions": [{"id", "name", "description"}]}
Return pure JSON only:
{"coverage_score": 1-5, "relevance_score": 1-5, "missing_aspects": ["..."], "notes": "..."}
- coverage_score: how completely the dimensions cover the capability implied by the goal.
- relevance_score: how well each dimension stays on-target (no drift/filler).
Be strict: generic dimensions that could apply to any goal deserve low relevance.
"""

ITEM_VALIDITY_SYSTEM_PROMPT = """\
You audit benchmark items for validity.
Input JSON: {"goal": "...", "items": [{"id", "prompt", "choices", "correct_choice_ids", "expected_text", "rubric", "task_type"}]}
Return pure JSON only:
{"items": [{"id": "...", "valid": true|false, "reason": "..."}]}
An item is valid when it: tests the goal capability (not trivia or filler), is
answerable/scoreable as specified (answer or rubric is consistent with the
prompt), and is self-contained. Judge each item independently.
"""


def _call_orchestrator_json(orch: dict, system: str, payload: dict, call: Callable | None = None) -> dict:
    caller = call or call_llm
    raw = caller(
        [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))],
        system=system,
        model=orch.get("model"),
        api_key=orch.get("api_key"),
        base_url=orch.get("base_url"),
        backend=orch.get("backend", "auto"),
        max_tokens=4096,
    )
    data = extract_json(raw)
    return data if isinstance(data, dict) else {}


def audit_dimension_coverage(goal: str, spec, orch: dict, *, call: Callable | None = None) -> dict:
    """LLM-as-judge audit of spec dimension coverage/relevance (1-5)."""
    if not orch.get("api_key"):
        return {"skipped": "no orchestrator API key"}
    dimensions = [
        {"id": d.id, "name": d.name, "description": d.description}
        for d in getattr(spec, "dimensions", [])
    ]
    try:
        data = _call_orchestrator_json(
            orch, COVERAGE_AUDIT_SYSTEM_PROMPT, {"goal": goal, "dimensions": dimensions}, call
        )
        return {
            "coverage_score": float(data.get("coverage_score", 0) or 0),
            "relevance_score": float(data.get("relevance_score", 0) or 0),
            "missing_aspects": [str(x) for x in data.get("missing_aspects", [])],
            "notes": str(data.get("notes", "")),
        }
    except Exception as exc:
        return {"error": f"coverage audit failed: {exc}"}


def audit_item_validity(goal: str, items: Sequence, orch: dict, *, call: Callable | None = None) -> dict:
    """LLM audit of a sample of items: valid/invalid + reason -> validity rate."""
    if not orch.get("api_key"):
        return {"skipped": "no orchestrator API key"}
    if not items:
        return {"skipped": "no items to audit"}
    payload_items = [
        {
            "id": item.id,
            "prompt": item.prompt[:1500],
            "choices": [choice.model_dump(mode="json") for choice in item.choices],
            "correct_choice_ids": item.correct_choice_ids,
            "expected_text": (item.expected_text or "")[:400],
            "rubric": (item.rubric or "")[:600],
            "task_type": item.task_type.value,
        }
        for item in items
    ]
    try:
        data = _call_orchestrator_json(
            orch, ITEM_VALIDITY_SYSTEM_PROMPT, {"goal": goal, "items": payload_items}, call
        )
        verdicts = [
            {
                "id": str(entry.get("id", "")),
                "valid": bool(entry.get("valid", False)),
                "reason": str(entry.get("reason", "")),
            }
            for entry in data.get("items", [])
            if isinstance(entry, dict)
        ]
        if not verdicts:
            return {"error": "item validity audit returned no verdicts"}
        valid_count = sum(1 for v in verdicts if v["valid"])
        return {
            "sampled": len(payload_items),
            "judged": len(verdicts),
            "valid_rate": round(valid_count / len(verdicts), 4),
            "verdicts": verdicts,
        }
    except Exception as exc:
        return {"error": f"item validity audit failed: {exc}"}


# ---------------------------------------------------------------------------
# Cost accounting: wall time + LLM call counts
# ---------------------------------------------------------------------------
class StageTimer:
    """Record wall-time per named stage."""

    def __init__(self) -> None:
        self.durations: dict[str, float] = {}

    @contextlib.contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.durations[name] = round(time.perf_counter() - start, 2)

    def as_dict(self) -> dict[str, float]:
        return dict(self.durations)


@contextlib.contextmanager
def count_llm_calls():
    """Count LiteLLM/httpx-level LLM calls made through evalclaw.models.llm.

    Wraps evalclaw.models.llm internals for the duration of the context. Calls routed
    through the native Anthropic SDK path are not counted (noted in reports).
    """
    import evalclaw.models.llm as llm_module

    counter = {"litellm": 0, "http": 0}
    original_litellm = llm_module._call_litellm
    original_post = llm_module._post_with_retry

    def counted_litellm(*args, **kwargs):
        counter["litellm"] += 1
        return original_litellm(*args, **kwargs)

    def counted_post(*args, **kwargs):
        counter["http"] += 1
        return original_post(*args, **kwargs)

    llm_module._call_litellm = counted_litellm
    llm_module._post_with_retry = counted_post
    try:
        yield counter
    finally:
        llm_module._call_litellm = original_litellm
        llm_module._post_with_retry = original_post


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------
def _fmt_metric(value: object) -> str:
    if isinstance(value, dict):
        if "skipped" in value:
            return f"skipped ({value['skipped']})"
        if "error" in value:
            return f"error ({value['error']})"
    if value is None:
        return "-"
    return str(value)


def _variant_metric_rows(metrics_by_variant: dict) -> list[str]:
    def cell(variant: str, path: list[str]) -> str:
        node = metrics_by_variant.get(variant, {})
        for key in path:
            if not isinstance(node, dict):
                return "-"
            if "skipped" in node or "error" in node:
                return _fmt_metric(node)
            node = node.get(key)
        return _fmt_metric(node)

    rows_spec = [
        ("Wall time (s)", ["wall_time_s"]),
        ("LLM calls (litellm)", ["llm_calls", "litellm"]),
        ("LLM calls (http)", ["llm_calls", "http"]),
        ("Dimensions", ["dimensions"]),
        ("Items", ["items"]),
        ("QC quality", ["qc_quality"]),
        ("Coverage score (1-5)", ["coverage_audit", "coverage_score"]),
        ("Relevance score (1-5)", ["coverage_audit", "relevance_score"]),
        ("Item validity rate", ["item_validity", "valid_rate"]),
        ("Diversity (mean pairwise)", ["diversity", "mean_pairwise_distance"]),
        ("Diversity method", ["diversity", "method"]),
        ("Strong-weak gap", ["discriminative", "gap"]),
        ("Order correct", ["discriminative", "order_correct"]),
    ]
    lines = ["| Metric | baseline | deep_research |", "| --- | --- | --- |"]
    for label, path in rows_spec:
        lines.append(f"| {label} | {cell('baseline', path)} | {cell('deep_research', path)} |")
    return lines


def render_exp1_report(goal: str, metrics: dict) -> str:
    """Render the A/B (baseline vs deep research) report for one goal."""
    lines = [
        f"# Experiment 1: Deep Research A/B — {goal}",
        "",
        f"- Generated at: {metrics.get('generated_at', '-')}",
        f"- Config: {json.dumps(metrics.get('experiment_config', {}), ensure_ascii=False)}",
        "",
        "## Metric Comparison",
        "",
        *_variant_metric_rows(metrics.get("variants", {})),
        "",
    ]
    for variant in ("baseline", "deep_research"):
        payload = metrics.get("variants", {}).get(variant, {})
        lines.extend([f"## Variant: {variant}", ""])
        if "error" in payload:
            lines.extend([f"- Pipeline failed: {payload['error']}", ""])
            continue
        coverage = payload.get("coverage_audit", {})
        if isinstance(coverage, dict) and coverage.get("missing_aspects"):
            lines.append("- Missing aspects flagged by coverage audit:")
            lines.extend(f"  - {aspect}" for aspect in coverage["missing_aspects"])
        validity = payload.get("item_validity", {})
        if isinstance(validity, dict) and validity.get("verdicts"):
            invalid = [v for v in validity["verdicts"] if not v["valid"]]
            lines.append(f"- Invalid items in audit sample: {len(invalid)}/{validity['judged']}")
            lines.extend(f"  - {v['id']}: {v['reason']}" for v in invalid[:6])
        if payload.get("notes"):
            lines.append(f"- Notes: {payload['notes']}")
        lines.append("")
    lines.extend(
        [
            "## Caveats",
            "",
            "- LLM call counts cover the LiteLLM/httpx paths only (native Anthropic SDK calls are not counted).",
            "- Token/cost accounting is not captured by the direct runner; wall time is the cost proxy.",
            "- LLM audits are themselves model judgments; spot-check a sample by hand.",
            "",
        ]
    )
    return "\n".join(lines)


def render_exp2_report(
    goal: str,
    strong_model: str,
    weak_model: str,
    result: dict,
    dimension_gaps: dict[str, float] | None = None,
) -> str:
    """Render the ranking sanity-check report."""
    lines = [
        f"# Experiment 2: Ranking Sanity Check — {goal}",
        "",
        f"- Expected order: `{strong_model}` > `{weak_model}`",
        "",
        "## Result",
        "",
    ]
    if "skipped" in result:
        lines.extend([f"- Skipped: {result['skipped']}", ""])
        return "\n".join(lines)
    verdict = "PASS (expected order preserved)" if result.get("order_correct") else "FAIL (order inverted or tied)"
    lines.extend(
        [
            f"- Verdict: **{verdict}**",
            f"- Strong ({result.get('strong_id')}): {result.get('strong_avg')}",
            f"- Weak ({result.get('weak_id')}): {result.get('weak_avg')}",
            f"- Gap: {result.get('gap')}",
            "",
        ]
    )
    if dimension_gaps:
        lines.extend(["## Per-Dimension Gaps (strong - weak)", "", "| Dimension | Gap |", "| --- | --- |"])
        lines.extend(f"| {dim} | {gap} |" for dim, gap in dimension_gaps.items())
        lines.append("")
    lines.extend(
        [
            "## Interpretation",
            "",
            "- A positive gap with the expected order suggests the generated benchmark discriminates",
            "  real capability differences. A tiny or negative gap on a known-ordered pair is a red flag",
            "  for benchmark validity (noise, mis-scored items, or saturated challenge).",
            "",
        ]
    )
    return "\n".join(lines)
