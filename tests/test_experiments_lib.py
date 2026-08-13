"""Tests for the pure metric/report helpers in experiments/_lib.py.

No network, no LLM calls — mocks only, in the style of tests/test_core_smoke.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

import _lib

from evalclaw.types import BenchmarkItem, EvalDimension, EvalSpec, TargetSummary, TaskType


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def test_load_config_merges_defaults(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"scale_budget": "mid", "embedding_model": None}), encoding="utf-8")
    config = _lib.load_config(path)
    assert config["scale_budget"] == "mid"  # overridden
    assert config["goals"] == _lib.DEFAULT_CONFIG["goals"]  # default kept
    assert config["embedding_model"] is None  # null does not override to garbage
    assert _lib.load_config(None) == _lib.DEFAULT_CONFIG


def test_slugify() -> None:
    assert _lib.slugify("Evaluate models' tax law reasoning ability!") == "evaluate_models_tax_law_reasoning_abilit"
    assert _lib.slugify("///") == "experiment"


def test_tee_output_duplicates_stdout(tmp_path) -> None:
    log = tmp_path / "run.log"
    with _lib.tee_output(log):
        print("hello tee")
    content = log.read_text(encoding="utf-8")
    assert "hello tee" in content
    assert "run started" in content
    # stdout/stderr restored after the block
    assert not isinstance(sys.stdout, _lib._Tee)
    assert not isinstance(sys.stderr, _lib._Tee)


# ---------------------------------------------------------------------------
# Diversity metrics
# ---------------------------------------------------------------------------
def test_jaccard_distance_bounds() -> None:
    assert _lib.jaccard_distance("tax law reasoning", "tax law reasoning") == 0.0
    assert _lib.jaccard_distance("alpha beta", "gamma delta") == 1.0
    assert _lib.jaccard_distance("", "") == 0.0


def test_cosine_distance() -> None:
    assert abs(_lib.cosine_distance([1.0, 0.0], [0.0, 1.0]) - 1.0) < 1e-9
    assert abs(_lib.cosine_distance([2.0, 0.0], [4.0, 0.0])) < 1e-9
    assert _lib.cosine_distance([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_semantic_diversity_uses_embeddings_when_available() -> None:
    def embed(texts):
        # Orthogonal unit vectors -> all pairwise cosine distances are 1.0.
        return [[1.0 if i == j else 0.0 for j in range(len(texts))] for i in range(len(texts))]

    result = _lib.semantic_diversity(["a", "b", "c"], embed_fn=embed)
    assert result["method"] == "embedding"
    assert result["mean_pairwise_distance"] == 1.0
    assert result["texts"] == 3


def test_semantic_diversity_falls_back_when_embedding_fails() -> None:
    def broken_embed(texts):
        raise RuntimeError("no deployment")

    result = _lib.semantic_diversity(["tax law", "lab safety"], embed_fn=broken_embed)
    assert result["method"] == "jaccard"
    assert result["mean_pairwise_distance"] == 1.0  # disjoint token sets
    assert "failed" in result["note"]


def test_semantic_diversity_falls_back_on_wrong_shape() -> None:
    result = _lib.semantic_diversity(["a b", "a c"], embed_fn=lambda texts: [[1.0]])
    assert result["method"] == "jaccard"
    assert "wrong shape" in result["note"]


def test_semantic_diversity_without_embed_fn_and_few_texts() -> None:
    assert _lib.semantic_diversity(["a b c", "a d e"])["method"] == "jaccard"
    none_result = _lib.semantic_diversity(["only one"])
    assert none_result["method"] == "none"
    assert none_result["mean_pairwise_distance"] is None


# ---------------------------------------------------------------------------
# Discriminative power
# ---------------------------------------------------------------------------
def _summary(target_id: str, avg: float, by_dim: dict | None = None) -> TargetSummary:
    return TargetSummary(
        target_id=target_id,
        model=target_id,
        average_score=avg,
        score_by_dimension=by_dim or {},
        total_items=4,
    )


def test_discriminative_power_correct_order() -> None:
    result = _lib.discriminative_power(
        [_summary("strong", 0.8), _summary("weak", 0.55)], "strong", "weak"
    )
    assert result["order_correct"] is True
    assert abs(result["gap"] - 0.25) < 1e-9


def test_discriminative_power_inverted_order_and_dicts() -> None:
    summaries = [
        {"target_id": "strong", "average_score": 0.4},
        {"target_id": "weak", "average_score": 0.6},
    ]
    result = _lib.discriminative_power(summaries, "strong", "weak")
    assert result["order_correct"] is False
    assert result["gap"] == -0.2


def test_discriminative_power_missing_target_skipped() -> None:
    result = _lib.discriminative_power([_summary("strong", 0.8)], "strong", "weak")
    assert "skipped" in result


def test_per_dimension_gaps() -> None:
    gaps = _lib.per_dimension_gaps(
        [
            _summary("strong", 0.8, {"d1": 0.9, "d2": 0.7}),
            _summary("weak", 0.5, {"d1": 0.5, "d2": 0.8, "d3": 0.1}),
        ],
        "strong",
        "weak",
    )
    assert gaps == {"d1": 0.4, "d2": -0.1}  # only shared dimensions
    assert _lib.per_dimension_gaps([], "strong", "weak") == {}


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
def _item(item_id: str, dim: str) -> BenchmarkItem:
    return BenchmarkItem(
        id=item_id, dimension_id=dim, task_type=TaskType.fill_blank, prompt=f"p {item_id}"
    )


def test_stratified_sample_per_dimension_and_cap() -> None:
    items = [_item(f"a{i}", "dim_a") for i in range(5)] + [_item(f"b{i}", "dim_b") for i in range(5)]
    sample = _lib.stratified_sample(items, per_dimension=2, cap=10)
    assert [item.id for item in sample] == ["a0", "a1", "b0", "b1"]
    capped = _lib.stratified_sample(items, per_dimension=5, cap=3)
    assert len(capped) == 3


# ---------------------------------------------------------------------------
# LLM audits (mocked)
# ---------------------------------------------------------------------------
def _spec() -> EvalSpec:
    return EvalSpec(
        objective="Evaluate tax law reasoning",
        dimensions=[
            EvalDimension(id="statutes", name="Statutes", description="d", approach="a"),
            EvalDimension(id="deductions", name="Deductions", description="d", approach="a"),
        ],
    )


def test_coverage_audit_skipped_without_key() -> None:
    result = _lib.audit_dimension_coverage("goal", _spec(), {"api_key": None})
    assert result == {"skipped": "no role API key"}


def test_coverage_audit_parses_scores() -> None:
    def fake_call(messages, **kwargs):
        payload = json.loads(messages[0].content)
        assert payload["dimensions"][0]["id"] == "statutes"
        return json.dumps(
            {"coverage_score": 4, "relevance_score": 5, "missing_aspects": ["state taxes"], "notes": "ok"}
        )

    result = _lib.audit_dimension_coverage(
        "goal", _spec(), {"api_key": "k", "model": "m"}, call=fake_call
    )
    assert result["coverage_score"] == 4.0
    assert result["relevance_score"] == 5.0
    assert result["missing_aspects"] == ["state taxes"]


def test_coverage_audit_error_captured() -> None:
    def broken_call(messages, **kwargs):
        raise RuntimeError("boom")

    result = _lib.audit_dimension_coverage("goal", _spec(), {"api_key": "k"}, call=broken_call)
    assert "error" in result


def test_item_validity_audit() -> None:
    items = [_item("i1", "d"), _item("i2", "d")]

    def fake_call(messages, **kwargs):
        payload = json.loads(messages[0].content)
        assert [entry["id"] for entry in payload["items"]] == ["i1", "i2"]
        return json.dumps(
            {"items": [
                {"id": "i1", "valid": True, "reason": "fine"},
                {"id": "i2", "valid": False, "reason": "ambiguous"},
            ]}
        )

    result = _lib.audit_item_validity("goal", items, {"api_key": "k"}, call=fake_call)
    assert result["valid_rate"] == 0.5
    assert result["judged"] == 2
    assert _lib.audit_item_validity("goal", [], {"api_key": "k"})["skipped"] == "no items to audit"
    assert "skipped" in _lib.audit_item_validity("goal", items, {"api_key": None})


# ---------------------------------------------------------------------------
# Cost accounting
# ---------------------------------------------------------------------------
def test_count_llm_calls_wraps_and_restores(monkeypatch) -> None:
    import evalclaw.models.llm as llm_module

    monkeypatch.setattr(llm_module, "_call_litellm", lambda **kwargs: "ok")
    monkeypatch.setattr(llm_module, "_post_with_retry", lambda *args, **kwargs: {"ok": True})
    patched_litellm = llm_module._call_litellm

    with _lib.count_llm_calls() as counter:
        llm_module._call_litellm(model="m", messages=[], max_tokens=1)
        llm_module._call_litellm(model="m", messages=[], max_tokens=1)
        llm_module._post_with_retry("u", {}, {})
    assert counter == {"litellm": 2, "http": 1}
    assert llm_module._call_litellm is patched_litellm  # restored


def test_stage_timer_records_durations() -> None:
    timer = _lib.StageTimer()
    with timer.stage("fast"):
        pass
    assert "fast" in timer.as_dict()
    assert timer.as_dict()["fast"] >= 0.0


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------
def test_render_exp1_report_with_skipped_metrics() -> None:
    metrics = {
        "generated_at": "2026-07-03T00:00:00Z",
        "experiment_config": {"role_model": "azure/gpt-4o"},
        "variants": {
            "baseline": {
                "wall_time_s": 2.5,
                "llm_calls": {"litellm": 0, "http": 0},
                "dimensions": 3,
                "items": 12,
                "qc_quality": 1.0,
                "coverage_audit": {"skipped": "no role API key"},
                "item_validity": {"skipped": "no role API key"},
                "diversity": {"method": "jaccard", "mean_pairwise_distance": 0.8},
                "discriminative": {"skipped": "runner produced no results"},
            },
            "deep_research": {"error": "boom"},
        },
    }
    report = _lib.render_exp1_report("tax law", metrics)
    assert "# Experiment 1: Deep Research A/B — tax law" in report
    assert "skipped (no role API key)" in report
    assert "Pipeline failed: boom" in report
    assert "| Diversity (mean pairwise) | 0.8 |" in report
    assert "## Caveats" in report


def test_render_exp1_report_with_full_metrics() -> None:
    metrics = {
        "variants": {
            "baseline": {
                "coverage_audit": {"coverage_score": 3.0, "missing_aspects": ["x"]},
                "item_validity": {
                    "valid_rate": 0.5,
                    "judged": 2,
                    "verdicts": [
                        {"id": "i1", "valid": True, "reason": ""},
                        {"id": "i2", "valid": False, "reason": "ambiguous"},
                    ],
                },
                "diversity": {"method": "embedding", "mean_pairwise_distance": 0.4},
                "discriminative": {"gap": 0.2, "order_correct": True},
            },
            "deep_research": {},
        }
    }
    report = _lib.render_exp1_report("goal", metrics)
    assert "Missing aspects flagged" in report
    assert "i2: ambiguous" in report
    assert "| Order correct | True | - |" in report


def test_render_exp2_report_verdicts() -> None:
    passed = _lib.render_exp2_report(
        "goal",
        "azure/gpt-4o",
        "azure/gpt-4o-mini",
        {"order_correct": True, "strong_id": "s", "weak_id": "w",
         "strong_avg": 0.8, "weak_avg": 0.6, "gap": 0.2},
        {"dim_a": 0.3},
    )
    assert "PASS" in passed
    assert "| dim_a | 0.3 |" in passed

    failed = _lib.render_exp2_report(
        "goal", "s", "w",
        {"order_correct": False, "strong_id": "s", "weak_id": "w",
         "strong_avg": 0.5, "weak_avg": 0.6, "gap": -0.1},
    )
    assert "FAIL" in failed

    skipped = _lib.render_exp2_report("goal", "s", "w", {"skipped": "no creds"})
    assert "Skipped: no creds" in skipped
