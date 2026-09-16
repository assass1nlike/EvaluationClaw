#!/usr/bin/env python3
"""
Verifier for high_wind_landscape_solar_array_redesign task.

Uses MULTIPLE INDEPENDENT SIGNALS for verification:
1. Programmatic state: Evaluates if new project `.ng3` file was saved.
2. Programmatic state: Inspects binary strings inside `.ng3` for Location parameter changes.
3. Output state: Checks for correct CSV export and verifies dimensions (yield entries).
4. VLM Hybrid: Uses trajectory frames to verify panel orientation and tilt were visually adjusted in the UI.
"""

import os
import json
import logging
import tempfile

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent's performance on a 3D solar design task in Energy3D.
The agent was asked to:
1. Change the geographic location to Miami, FL.
2. Select all solar racks and change their panel orientation to 'Landscape'.
3. Change their tilt angle to 15 degrees.
4. Run the Annual Yield Analysis.

Review the provided sequence of screenshots (trajectory + final state).
Determine if the following actions were successfully performed. Answer strictly in JSON.

{
    "location_changed": true/false,
    "orientation_landscape_set": true/false,
    "tilt_15_set": true/false,
    "yield_analysis_graph_visible": true/false,
    "reasoning": "Brief justification for your visual findings"
}
"""

def verify_solar_redesign(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available from env"}

    score = 0
    feedback_parts = []
    
    # 1. Access exported data payload
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to load exported task results: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    task_start = result.get("task_start", 0)
    ng3_exists = result.get("ng3_exists", False)
    ng3_mtime = result.get("ng3_mtime", 0)
    has_miami_string = result.get("has_miami_string", False)
    
    csv_exists = result.get("csv_exists", False)
    csv_mtime = result.get("csv_mtime", 0)
    csv_size = result.get("csv_size", 0)
    csv_lines = int(result.get("csv_lines", 0))

    # Criterion 1: Modified Project Saved
    file_ng3_created = ng3_exists and (ng3_mtime >= task_start)
    if file_ng3_created:
        score += 10
        feedback_parts.append("Saved .ng3 project")
        if has_miami_string:
            score += 10
            feedback_parts.append("Detected Miami configuration natively inside project file")
    else:
        feedback_parts.append("Failed to save .ng3 project file during task timeframe")

    # Criterion 2: CSV Yield Export
    file_csv_created = csv_exists and (csv_mtime >= task_start)
    if file_csv_created:
        if csv_size > 50 and csv_lines >= 12:
            score += 20
            feedback_parts.append("Exported valid yield CSV with data")
        else:
            feedback_parts.append("Exported CSV but it appears empty/invalid")
    else:
        feedback_parts.append("Failed to export yield CSV")

    # 3. VLM Hybrid Trajectory Verification
    vlm_score = 0
    frames = sample_trajectory_frames(traj, n=4)
    final_img = get_final_screenshot(traj)
    images = frames
    if final_img:
        images.append(final_img)
    
    if images and query_vlm:
        try:
            vlm_result = query_vlm(prompt=VLM_PROMPT, images=images)
            if vlm_result.get("success") and "parsed" in vlm_result:
                parsed = vlm_result["parsed"]
                
                if parsed.get("location_changed"):
                    vlm_score += 15
                    feedback_parts.append("VLM confirms location change to Miami")
                    
                if parsed.get("orientation_landscape_set"):
                    vlm_score += 15
                    feedback_parts.append("VLM confirms Landscape orientation set")
                    
                if parsed.get("tilt_15_set"):
                    vlm_score += 15
                    feedback_parts.append("VLM confirms 15 degree tilt set")
                    
                if parsed.get("yield_analysis_graph_visible"):
                    vlm_score += 15
                    feedback_parts.append("VLM confirms yield analysis executed")
            else:
                feedback_parts.append(f"VLM verification response missing/unparsed: {vlm_result.get('error')}")
        except Exception as e:
            feedback_parts.append(f"VLM exception: {str(e)}")
    else:
        feedback_parts.append("VLM verification skipped (VLM unavailable or no images)")

    score += vlm_score

    # Passing determination: Requires saving the files + passing sufficient criteria points
    key_criteria_met = file_csv_created and file_ng3_created
    passed = (score >= 65) and key_criteria_met

    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback_parts)
    }