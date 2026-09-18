#!/usr/bin/env python3
"""Verifier for airport_weather_monthly_report.

Fully programmatic: the export script reports what is on disk, the ground truth
was computed by the setup script from the same real NOAA data, and everything
below is scored against it.

Criteria (100 points, pass at 80):
  A  monthly_station_stats.csv present, new, correct columns      5
  B  all 36 station-months present                                10
  C  per-station-month statistics, proportional, all-or-nothing
     per row                                                      45
  D  adverse_hours.csv covers exactly the reference adverse set   15
  E  report_summary.json fields                                   5
  F  figures/, scored on how many of the 36 expected files are
     present, new, valid PNGs of a plausible size                 20

Gates, in order:
  0  monthly_station_stats.csv missing or not written during the
     task -> 0
  1  no reference station-month reproduced -> 0
  2  any deliverable missing or invalid, fewer than 30 valid
     figures, or fewer than 90% of the station-month rows correct
     -> ceiling of 79, so bookkeeping alone cannot pass and the
     whole job has to fit the budget.
"""

import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

PASS_THRESHOLD = 80
DELIVERABLE_CEILING = PASS_THRESHOLD - 1
MIN_FIGURES_FOR_FULL_CREDIT = 30
MIN_ROW_FRACTION = 0.90
MIN_FIGURE_BYTES = 2000  # below this the write was almost certainly truncated

STAT_COLUMNS = ["origin", "month", "n_hours", "mean_temp_f",
                "mean_wind_speed_mph", "total_precip_in", "n_adverse_hours"]
STAT_VALUE_KEYS = ["n_hours", "mean_temp_f", "mean_wind_speed_mph",
                   "total_precip_in", "n_adverse_hours"]
ADVERSE_KEY_COLUMNS = ["origin", "month", "day", "hour"]
SUMMARY_KEYS = ["total_hours", "adverse_hours_total", "n_station_months", "mean_temp_f_all"]


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


def _close(a, b, rel=1e-3, abs_tol=0.011):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, abs(b) * rel)


def _rows(block):
    rows = block.get("rows")
    if not isinstance(rows, list):
        return []
    return [{str(k).strip().lower(): v for k, v in r.items()} for r in rows if isinstance(r, dict)]


def _station_month(row):
    origin = str(row.get("origin", "")).strip().upper()
    month = _as_float(row.get("month"))
    return (origin, int(month)) if month is not None else None


def _adverse_key(row):
    origin = str(row.get("origin", "")).strip().upper()
    parts = [_as_float(row.get(c)) for c in ("month", "day", "hour")]
    if any(p is None for p in parts):
        return None
    return (origin, int(parts[0]), int(parts[1]), int(parts[2]))


def verify_airport_weather_monthly_report(traj, env_info, task_info):
    copy_from_env = env_info.get("copy_from_env")
    if copy_from_env is None:
        return {"passed": False, "score": 0,
                "feedback": "Verifier misconfigured: no copy_from_env in env_info"}

    result = _read_json(copy_from_env, "/tmp/airport_weather_monthly_report_result.json")
    gt = _read_json(copy_from_env, "/tmp/airport_weather_monthly_report_gt.json")
    if gt is None:
        return {"passed": False, "score": 0,
                "feedback": "Ground truth missing; setup did not complete"}
    if not result:
        return {"passed": False, "score": 0,
                "feedback": "No result file: export did not run"}

    stats_block = result.get("monthly_station_stats", {}) or {}
    adverse_block = result.get("adverse_hours", {}) or {}
    summary_block = result.get("report_summary", {}) or {}
    figures = result.get("figures", {}) or {}

    # ── Gate 0 ─────────────────────────────────────────────────────────────────
    if not stats_block.get("exists") or not stats_block.get("is_new"):
        return {"passed": False, "score": 0,
                "feedback": "monthly_station_stats.csv was not created during the task",
                "subscores": {"stats_written": False}}

    rows = _rows(stats_block)
    cols = [str(c).strip().lower() for c in (stats_block.get("columns") or [])]

    gt_stats = {(r["origin"], r["month"]): r for r in gt["stats"]}
    reported = {}
    for r in rows:
        key = _station_month(r)
        if key:
            reported[key] = r

    # ── Gate 1: wrong target ───────────────────────────────────────────────────
    if not any(k in gt_stats for k in reported):
        return {"passed": False, "score": 0,
                "feedback": "No reference station-month reproduced (wrong data or wrong grouping)",
                "subscores": {"station_months_matched": 0}}

    subscores = {}
    details = []
    score = 0

    # ── A: structure ───────────────────────────────────────────────────────────
    missing_cols = [c for c in STAT_COLUMNS if c not in cols]
    if missing_cols:
        subscores["stats_columns"] = 0
        details.append("monthly_station_stats.csv missing columns: " + ", ".join(missing_cols))
    else:
        score += 5
        subscores["stats_columns"] = 5

    # ── B: all station-months present ──────────────────────────────────────────
    if set(reported) == set(gt_stats):
        score += 10
        subscores["station_months"] = 10
    else:
        missing = len(set(gt_stats) - set(reported))
        subscores["station_months"] = 0
        details.append("station-month rows: {} present, {} missing, {} unexpected".format(
            len(set(reported) & set(gt_stats)), missing, len(set(reported) - set(gt_stats))))

    # ── C: values ──────────────────────────────────────────────────────────────
    good_rows = 0
    for key, ref in gt_stats.items():
        got = reported.get(key)
        if got is None:
            continue
        if all(_close(_as_float(got.get(k)), ref[k]) for k in STAT_VALUE_KEYS):
            good_rows += 1
    denom = len(gt_stats) + len(set(reported) - set(gt_stats))
    value_pts = int(round(45 * good_rows / denom)) if denom else 0
    score += value_pts
    subscores["station_month_values"] = value_pts
    row_fraction = good_rows / len(gt_stats)
    if value_pts < 45:
        details.append("station-month statistics: {}/{} rows correct".format(
            good_rows, len(gt_stats)))

    # ── D: adverse hours ───────────────────────────────────────────────────────
    gt_adverse = {tuple(k) for k in gt["adverse_keys"]}
    adverse_ok = False
    if adverse_block.get("exists") and adverse_block.get("is_new"):
        got_adverse = {k for k in (_adverse_key(r) for r in _rows(adverse_block)) if k}
        matched = len(got_adverse & gt_adverse)
        if got_adverse == gt_adverse:
            adverse_ok = True
            score += 15
            subscores["adverse_hours"] = 15
        else:
            subscores["adverse_hours"] = 0
            details.append("adverse_hours.csv: {} of {} reference hours present, "
                           "{} unexpected".format(matched, len(gt_adverse),
                                                  len(got_adverse - gt_adverse)))
    else:
        subscores["adverse_hours"] = 0
        details.append("adverse_hours.csv not created")

    # ── E: summary ─────────────────────────────────────────────────────────────
    summary_ok = False
    summary_value = summary_block.get("value")
    if summary_block.get("exists") and summary_block.get("is_new") \
            and isinstance(summary_value, dict):
        summary_ok = all(_close(_as_float(summary_value.get(k)), gt[k])
                         for k in SUMMARY_KEYS)
        if summary_ok:
            score += 5
            subscores["summary"] = 5
        else:
            subscores["summary"] = 0
            details.append("report_summary.json fields disagree with the reference report")
    else:
        subscores["summary"] = 0
        details.append("report_summary.json not created or not valid JSON")

    # ── F: figures ─────────────────────────────────────────────────────────────
    valid_figures = sum(
        1 for info in figures.values()
        if info.get("exists") and info.get("is_new") and info.get("is_valid_png")
        and info.get("size_bytes", 0) >= MIN_FIGURE_BYTES
    )
    expected_count = len(figures) if figures else 36
    figure_pts = int(round(20 * valid_figures / expected_count)) if expected_count else 0
    score += figure_pts
    subscores["figures"] = figure_pts
    if valid_figures < expected_count:
        details.append("figures/: {}/{} valid".format(valid_figures, expected_count))

    # ── Gate 2 ─────────────────────────────────────────────────────────────────
    blockers = []
    if not adverse_ok:
        blockers.append("adverse_hours.csv")
    if not summary_ok:
        blockers.append("report_summary.json")
    if valid_figures < MIN_FIGURES_FOR_FULL_CREDIT:
        blockers.append("figures/ ({}/{} valid)".format(valid_figures, expected_count))
    if row_fraction < MIN_ROW_FRACTION:
        blockers.append("{:.0%} of station-month rows correct".format(row_fraction))
    if blockers:
        score = min(score, DELIVERABLE_CEILING)
        details.append("score capped at {}: {}".format(DELIVERABLE_CEILING, "; ".join(blockers)))

    passed = score >= PASS_THRESHOLD
    feedback = ("PASS" if passed else "FAIL") + ": {}/{} points.".format(score, PASS_THRESHOLD)
    if details:
        feedback += " " + " | ".join(details)

    return {"passed": passed, "score": score, "feedback": feedback, "subscores": subscores}
