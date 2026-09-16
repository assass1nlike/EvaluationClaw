#!/usr/bin/env python3
"""
Verifier for ASHRAE Envelope Compliance Upgrade Task.

Uses a hybrid strategy:
1. File Checks (anti-gaming): Verifies that the required .ng3 and .png files
   were created or modified during the task execution time window.
2. VLM Trajectory Check: Reviews trajectory frames to confirm that the agent
   interacted with the specific U-value and albedo parameters, changed the city
   to Boston, and successfully generated the analysis graph.
"""

import json
import os
import re
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Safely try importing framework VLM utils
try:
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
    HAS_VLM_UTILS = True
except ImportError:
    HAS_VLM_UTILS = False
    logger.warning("gym_anything.vlm utilities not found. Trajectory verification may fail.")

VLM_PROMPT = """You are verifying an agent's completion of an Energy3D CAD/CAE task.
Analyze these trajectory screenshots of the agent's workflow.

Determine if the agent performed the following actions. Look closely at property panels, menus, dialogs, map settings, and final graphs.

1. "city_boston": Did the agent set the city/location to Boston, MA?
2. "wall_u_value_updated": Did the agent set Wall U-value to approximately 0.25?
3. "roof_u_value_updated": Did the agent set Roof U-value to approximately 0.15?
4. "roof_albedo_updated": Did the agent set Roof Albedo (reflectance) to approximately 0.65?
5. "window_u_value_updated": Did the agent set Window U-value to approximately 1.20?
6. "analysis_chart_visible": Is the "Annual Building Energy Analysis" chart/graph visible in any frame?

Respond ONLY with a valid JSON dictionary containing boolean (true/false) values for each of the exact 6 keys above. Do not include markdown formatting or other text."""


def verify_ashrae_compliance(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    # Retrieve file execution metrics
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result JSON: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    score = 0
    feedback_parts = []

    # File Checks
    ng3_exists = result.get('ng3_exists', False)
    ng3_created = result.get('ng3_created_during_task', False)
    png_exists = result.get('png_exists', False)
    png_created = result.get('png_created_during_task', False)

    if ng3_exists and ng3_created:
        score += 15
        feedback_parts.append("✅ Saved modified building .ng3 file")
    elif ng3_exists:
        score += 5
        feedback_parts.append("⚠️ Saved .ng3 file but timestamp predates task")
    else:
        feedback_parts.append("❌ Missing compliant_boston_building.ng3")

    if png_exists and png_created:
        score += 15
        feedback_parts.append("✅ Captured and saved energy_results.png")
    elif png_exists:
        score += 5
        feedback_parts.append("⚠️ Saved .png file but timestamp predates task")
    else:
        feedback_parts.append("❌ Missing energy_results.png")

    # VLM Verification
    if not query_vlm:
        feedback_parts.append("❌ query_vlm missing, skipping visual checks")
        vlm_data = {}
    else:
        images = []
        if HAS_VLM_UTILS:
            frames = sample_trajectory_frames(traj, n=6)
            final = get_final_screenshot(traj)
            if frames:
                images.extend(frames)
            if final and final not in images:
                images.append(final)
        
        if not images:
            feedback_parts.append("❌ No trajectory images available for VLM")
            vlm_data = {}
        else:
            try:
                vlm_result = query_vlm(images=images, prompt=VLM_PROMPT)
                
                # Robust JSON parsing from VLM response
                if isinstance(vlm_result, dict) and "parsed" in vlm_result:
                    vlm_data = vlm_result["parsed"]
                else:
                    text = vlm_result if isinstance(vlm_result, str) else vlm_result.get("response", "")
                    match = re.search(r'\{.*\}', text, re.DOTALL)
                    if match:
                        vlm_data = json.loads(match.group(0))
                    else:
                        vlm_data = {}
            except Exception as e:
                logger.error(f"VLM verification failed: {e}")
                vlm_data = {}

    # Accumulate VLM points
    city_boston = vlm_data.get("city_boston", False)
    if city_boston:
        score += 10
        feedback_parts.append("✅ Location set to Boston")
    else:
        feedback_parts.append("❌ Location not set to Boston")

    wall_u = vlm_data.get("wall_u_value_updated", False)
    if wall_u:
        score += 15
        feedback_parts.append("✅ Wall U-value updated (0.25)")
    else:
        feedback_parts.append("❌ Wall U-value not correctly updated")

    roof_u = vlm_data.get("roof_u_value_updated", False)
    if roof_u:
        score += 10
        feedback_parts.append("✅ Roof U-value updated (0.15)")
    else:
        feedback_parts.append("❌ Roof U-value not correctly updated")

    roof_albedo = vlm_data.get("roof_albedo_updated", False)
    if roof_albedo:
        score += 10
        feedback_parts.append("✅ Roof albedo updated (0.65)")
    else:
        feedback_parts.append("❌ Roof albedo not correctly updated")

    window_u = vlm_data.get("window_u_value_updated", False)
    if window_u:
        score += 10
        feedback_parts.append("✅ Window U-value updated (1.20)")
    else:
        feedback_parts.append("❌ Window U-value not correctly updated")

    chart_visible = vlm_data.get("analysis_chart_visible", False)
    if chart_visible:
        score += 15
        feedback_parts.append("✅ Energy analysis chart shown")
    else:
        feedback_parts.append("❌ Energy analysis chart not found in trajectory")

    # Success conditions
    key_criteria_met = ng3_exists and (png_exists or chart_visible)
    passed = score >= 75 and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }