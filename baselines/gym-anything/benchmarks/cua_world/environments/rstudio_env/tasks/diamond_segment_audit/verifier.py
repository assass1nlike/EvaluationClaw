#!/usr/bin/env python3
"""Verifier for diamond_segment_audit.

Fully programmatic: the export script reports what is on disk, the ground truth
was computed by the setup script from the same real data, and everything below
is scored against it.

Criteria (100 points, pass at 80):
  A  segment_report.csv present, new, correct columns             5
  B  excluded_records.csv is exactly the ground-truth row set    10
  C  audit_summary.json core counts (total/excluded/valid)        5
  D  reported segment set is exactly the ground-truth set        10
  E  per-segment statistics match, penalised for extra rows      55
  F  audit_summary.json reconciliation fields                     5
  G  price_per_carat_by_segment.png present, new, valid PNG      10

The threshold sits above the 45 points reachable with perfect bookkeeping and
no correct segment statistics, so the analysis itself has to be right.

Gates, in order:
  0  the report is missing/not written during the task -> 0
  1  the report is a wrong-target deliverable (no ground-truth
     segment is reproduced) -> 0
  2  any of the three remaining deliverables is missing, stale or
     invalid -> ceiling of 79, so the whole job has to fit the budget.
"""

import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

PASS_THRESHOLD = 80
DELIVERABLE_CEILING = PASS_THRESHOLD - 1
MIN_PLOT_BYTES = 2000  # below this the write was almost certainly truncated

REPORT_COLUMNS = ["cut", "color", "clarity", "n", "median_price",
                  "median_price_per_carat", "iqr_price_per_carat"]
EXCLUDED_COLUMNS = ["carat", "cut", "color", "clarity", "depth", "table",
                    "price", "x", "y", "z"]
STAT_KEYS = ["n", "median_price", "median_price_per_carat", "iqr_price_per_carat"]


def _read_json(copy_from_env, remote_path):
    local = tempfile.mktemp(suffix=".json")
    try:
        copy_from_env(remote_path, local)
        with open(local, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("could not read %s: %s", remote_path, e)
        return None
    finally:
        try:
            os.unlink(local)
        except Exception:
            pass


def _as_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _segment_key(row):
    """(cut, color, clarity) normalised for comparison."""
    return tuple(str(row.get(k, "")).strip().lower() for k in ("cut", "color", "clarity"))


def _excluded_key(row):
    """A whole excluded record, normalised, so the file can be compared as a set."""
    parts = []
    for col in EXCLUDED_COLUMNS:
        raw = str(row.get(col, "")).strip()
        num = _as_float(raw)
        parts.append("{:.6g}".format(num) if num is not None else raw.lower())
    return tuple(parts)


def _close(a, b, rel=1e-3, abs_tol=0.011):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, abs(b) * rel)


def _parse_embedded_rows(block):
    """The export embeds the parsed CSV as a list of dicts; accept that or a raw string."""
    rows = block.get("rows")
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append({str(k).strip().lower(): v for k, v in r.items()})
    return out


def verify_diamond_segment_audit(traj, env_info, task_info):
    copy_from_env = env_info.get("copy_from_env")
    if copy_from_env is None:
        return {"passed": False, "score": 0,
                "feedback": "Verifier misconfigured: no copy_from_env in env_info"}

    result = _read_json(copy_from_env, "/tmp/diamond_segment_audit_result.json")
    gt = _read_json(copy_from_env, "/tmp/diamond_segment_audit_gt.json")
    if gt is None:
        return {"passed": False, "score": 0,
                "feedback": "Ground truth missing; setup did not complete"}

    if not result:
        return {"passed": False, "score": 0,
                "feedback": "No result file: export did not run"}

    report = result.get("segment_report", {}) or {}
    excluded = result.get("excluded_records", {}) or {}
    summary = result.get("audit_summary", {}) or {}
    plot = result.get("plot", {}) or {}

    # ── Gate 0: no report deliverable ──────────────────────────────────────────
    if not report.get("exists") or not report.get("is_new"):
        return {"passed": False, "score": 0,
                "feedback": "segment_report.csv was not created during the task",
                "subscores": {"report_written": False}}

    rows = _parse_embedded_rows(report)
    cols = [str(c).strip().lower() for c in (report.get("columns") or [])]

    # ── Gate 1: wrong target ───────────────────────────────────────────────────
    gt_segments = {_segment_key(r): r for r in gt["segments"]}
    reported = {}
    for r in rows:
        reported[_segment_key(r)] = r
    matched = [k for k in reported if k in gt_segments]
    if not matched:
        return {"passed": False, "score": 0,
                "feedback": "None of the reported segments exist in the reference audit "
                            "(wrong grouping or wrong dataset)",
                "subscores": {"segments_matched": 0}}

    subscores = {}
    details = []
    score = 0

    # ── A: report structure ────────────────────────────────────────────────────
    missing_cols = [c for c in REPORT_COLUMNS if c not in cols]
    if not missing_cols:
        score += 5
        subscores["report_columns"] = 5
    else:
        subscores["report_columns"] = 0
        details.append("segment_report.csv missing columns: " + ", ".join(missing_cols))

    # ── B: excluded records ────────────────────────────────────────────────────
    excluded_ok = False
    gt_excluded = {_excluded_key(r) for r in gt["excluded"]}
    if excluded.get("exists") and excluded.get("is_new"):
        got_excluded = {_excluded_key(r) for r in _parse_embedded_rows(excluded)}
        if got_excluded == gt_excluded:
            excluded_ok = True
            score += 10
            subscores["excluded_records"] = 10
        else:
            subscores["excluded_records"] = 0
            details.append("excluded_records.csv: expected {} records, matched {}".format(
                len(gt_excluded), len(got_excluded & gt_excluded)))
    else:
        subscores["excluded_records"] = 0
        details.append("excluded_records.csv not created")

    # ── C + F: summary ─────────────────────────────────────────────────────────
    summary_value = summary.get("value") if isinstance(summary.get("value"), dict) else None
    summary_ok = bool(summary.get("exists") and summary.get("is_new") and summary_value)

    if summary_ok:
        core = all(summary_value.get(k) == gt[k]
                   for k in ("total_records", "excluded_records", "valid_records"))
        if core:
            score += 5
            subscores["summary_counts"] = 5
        else:
            subscores["summary_counts"] = 0
            details.append("audit_summary.json counts disagree with the reference audit")

        recon_keys = ("segments_total", "segments_reported", "records_in_reported_segments")
        share = _as_float(summary_value.get("share_in_reported_segments"))
        recon = (all(summary_value.get(k) == gt[k] for k in recon_keys)
                 and _close(share, gt["share_in_reported_segments"], rel=1e-3, abs_tol=1e-4))
        if recon:
            score += 5
            subscores["summary_reconciliation"] = 5
        else:
            subscores["summary_reconciliation"] = 0
            details.append("audit_summary.json reconciliation fields disagree")
    else:
        subscores["summary_counts"] = 0
        subscores["summary_reconciliation"] = 0
        details.append("audit_summary.json not created or not valid JSON")

    # ── D: segment set ─────────────────────────────────────────────────────────
    if set(reported) == set(gt_segments):
        score += 10
        subscores["segment_set"] = 10
    else:
        subscores["segment_set"] = 0
        details.append("segment set differs: {} reported, {} expected, {} spurious".format(
            len(reported), len(gt_segments), len(set(reported) - set(gt_segments))))

    # ── E: segment values (extra segments dilute the score) ────────────────────
    good = 0
    for key, ref in gt_segments.items():
        got = reported.get(key)
        if got is None:
            continue
        if all(_close(_as_float(got.get(s)), _as_float(ref[s])) for s in STAT_KEYS):
            good += 1
    denom = len(gt_segments) + len(set(reported) - set(gt_segments))
    value_pts = int(round(55 * good / denom)) if denom else 0
    score += value_pts
    subscores["segment_values"] = value_pts
    if value_pts < 55:
        details.append("segment statistics: {}/{} correct of {} scored cells".format(
            good, len(gt_segments), denom))

    # ── G: plot ────────────────────────────────────────────────────────────────
    plot_ok = bool(plot.get("exists") and plot.get("is_new") and plot.get("is_valid_png")
                   and plot.get("size_bytes", 0) >= MIN_PLOT_BYTES)
    if plot_ok:
        score += 10
        subscores["plot"] = 10
    else:
        subscores["plot"] = 0
        details.append("price_per_carat_by_segment.png missing, stale, not a PNG, or truncated")

    # ── Gate 2: all four deliverables are mandatory ────────────────────────────
    missing_deliverables = []
    if not excluded_ok:
        missing_deliverables.append("excluded_records.csv")
    if not summary_ok:
        missing_deliverables.append("audit_summary.json")
    if not plot_ok:
        missing_deliverables.append("price_per_carat_by_segment.png")
    if missing_deliverables:
        score = min(score, DELIVERABLE_CEILING)
        details.append("score capped at {}: incomplete or invalid deliverables ({})".format(
            DELIVERABLE_CEILING, ", ".join(missing_deliverables)))

    passed = score >= PASS_THRESHOLD
    feedback = ("PASS" if passed else "FAIL") + ": {}/{} points.".format(score, PASS_THRESHOLD)
    if details:
        feedback += " " + " | ".join(details)

    return {"passed": passed, "score": score, "feedback": feedback, "subscores": subscores}
