#!/usr/bin/env python3
"""
Verifier for historic_preservation_solar_retrofit@1 task.

Strategy:
1. Programmatic File Check: Ensure output .ng3 and .csv files exist, are of reasonable size, and were created during the task.
2. VLM Trajectory/Visual Verification: Confirm visual layout parameters (Hip roof, panel placement respects North facet constraint, yield graph executed).
"""

import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent's performance in a 3D energy modeling software (Energy3D).
Please analyze the provided screenshots from the agent's workflow and final state.

Look carefully for the following criteria:
1. Did the agent change the building's roof to a "Hip" roof (sloped on all 4 sides instead of a flat box)?
2. Did the agent place solar panels on the roof?
3. CRITICAL PRESERVATION RULE: Is the North-facing roof facet (typically facing the top/back in the default view) completely empty of solar panels?
4. Are there solar panels placed on multiple other facets (South, East, West)?
5. Did the agent open the "Daily Solar Yield" (or "Yield Today") graph window at some point?
6. Are there indicators in the UI that the location was set to "Boston, MA" and the date to "Jun 21" (Summer Solstice)?

Respond strictly in valid JSON format matching this schema:
{
    "has_hip_roof": boolean,
    "has_solar_panels": boolean,
    "north_facet_is_empty": boolean,
    "panels_on_multiple_facets": boolean,
    "yield_graph_shown": boolean,
    "location_date_indicators_visible": boolean,
    "confidence": "low|medium|high",
    "reasoning": "Brief explanation of what you observed."
}
"""

def verify_historic_retrofit(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Verifier error: copy_from_env not available."}

    # 1. Read exported programmatic results
    temp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_json.name)
        with open(temp_json.name, 'r') as f:
            results = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to load programmatic results: {e}"}
    finally:
        if os.path.exists(temp_json.name):
            os.unlink(temp_json.name)

    score = 0
    feedback_parts = []
    max_score = 100

    # 2. Evaluate Programmatic Checks (40 points total)
    ng3_ok = results.get("ng3_exists", False) and results.get("ng3_created_during_task", False) and results.get("ng3_size_bytes", 0) > 1000
    csv_ok = results.get("csv_exists", False) and results.get("csv_created_during_task", False) and results.get("csv_line_count", 0) >= 5

    if ng3_ok:
        score += 20
        feedback_parts.append("Project file successfully saved.")
    else:
        feedback_parts.append("Project file missing, invalid, or untouched.")

    if csv_ok:
        score += 20
        feedback_parts.append("CSV yield data successfully exported.")
    else:
        feedback_parts.append("CSV export missing or empty.")

    # 3. Evaluate VLM Visual Constraints (60 points total)
    query_vlm = env_info.get('query_vlm')
    if not query_vlm:
        feedback_parts.append("VLM query function not available. Cannot verify visual constraints.")
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}

    # Get trajectory frames and final screenshot
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
    frames = sample_trajectory_frames(traj, n=4)
    final_img = get_final_screenshot(traj)
    images_to_check = frames + ([final_img] if final_img else [])

    if not images_to_check:
        feedback_parts.append("No screenshots available for visual verification.")
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}

    try:
        vlm_response = query_vlm(prompt=VLM_PROMPT, images=images_to_check)
        parsed = vlm_response.get("parsed", {})
    except Exception as e:
        feedback_parts.append(f"VLM verification failed: {e}")
        parsed = {}

    has_hip_roof = parsed.get("has_hip_roof", False)
    has_solar_panels = parsed.get("has_solar_panels", False)
    north_empty = parsed.get("north_facet_is_empty", False)
    multiple_facets = parsed.get("panels_on_multiple_facets", False)
    yield_graph = parsed.get("yield_graph_shown", False)
    loc_date = parsed.get("location_date_indicators_visible", False)

    if has_hip_roof:
        score += 10
        feedback_parts.append("Hip roof confirmed.")
    else:
        feedback_parts.append("Hip roof not detected.")

    if yield_graph:
        score += 10
        feedback_parts.append("Yield graph workflow verified.")

    if loc_date:
        score += 10
        feedback_parts.append("Location/Date settings observed.")

    # Critical Panel Constraints
    if has_solar_panels and multiple_facets:
        if north_empty:
            score += 30
            feedback_parts.append("Panel placement strictly followed preservation constraints (North empty).")
        else:
            feedback_parts.append("FAILED CONSTRAINT: Panels found on restricted North facet (0/30 points).")
    else:
        feedback_parts.append("Solar panels not sufficiently placed on permitted facets.")

    # 4. Final Verification Logic
    # Agent must score at least 70 and MUST NOT have violated the panel constraint (if panels were placed).
    passed = (score >= 70) and (not (has_solar_panels and not north_empty)) and csv_ok

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }