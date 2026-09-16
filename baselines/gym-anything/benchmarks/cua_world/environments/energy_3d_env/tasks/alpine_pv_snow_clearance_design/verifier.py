#!/usr/bin/env python3
"""
Verifier for alpine_pv_snow_clearance_design task.

Uses a robust hybrid approach:
1. Programmatic file checks (existence, timestamps for anti-gaming, basic CSV validity).
2. Trajectory VLM verification to confirm visual property changes and workflow progression.
"""

import os
import json
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying if an agent successfully updated a 3D solar array model in Energy3D for alpine snow conditions.

TASK GOALS:
1. Increase ground clearance (Base Height) to 1.5m to prevent snowdrift burial.
2. Steep tilt angle to 45 degrees to shed snow.
3. Change location to Anchorage, AK.
4. Run Annual Solar Analysis.

Look at the provided trajectory frames and the final screenshot. 
Determine the following:
1. Did the agent visually select the solar panels and open their property editor?
2. Does the final visual model show arrays that are noticeably elevated off the ground (higher base height)?
3. Does the final visual model show panels that are steeply tilted?
4. Is there evidence the location was set to Anchorage (e.g. "Anchorage" seen in a city dropdown menu or analysis window)?
5. Is there evidence the Annual Solar Analysis was run (e.g. an analysis graph window or progress bar visible in any frame)?

Respond strictly in JSON format:
{
    "panels_elevated": true/false,
    "panels_steep_tilt": true/false,
    "location_anchorage": true/false,
    "analysis_run": true/false,
    "confidence": "high/medium/low",
    "reasoning": "brief explanation"
}
"""

def verify_alpine_snow_clearance(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to load result JSON: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    score = 0
    feedback_parts = []
    
    # 1. Evaluate NG3 Model Saving (20 points)
    ng3_exists = result.get("ng3_exists", False)
    ng3_created_during_task = result.get("ng3_mtime", 0) > result.get("task_start", 0)
    
    if ng3_exists and ng3_created_during_task:
        score += 20
        feedback_parts.append("✅ alpine_snow_array.ng3 saved correctly")
    elif ng3_exists:
        score += 10
        feedback_parts.append("⚠️ alpine_snow_array.ng3 exists but wasn't modified/created during task")
    else:
        feedback_parts.append("❌ alpine_snow_array.ng3 not found")

    # 2. Evaluate CSV Export (30 points)
    csv_exists = result.get("csv_exists", False)
    csv_created_during_task = result.get("csv_mtime", 0) > result.get("task_start", 0)
    csv_lines = result.get("csv_lines", 0)
    
    if csv_exists and csv_created_during_task and csv_lines >= 12:
        score += 30
        feedback_parts.append("✅ anchorage_yield.csv exported with valid monthly data")
    elif csv_exists and csv_created_during_task:
        score += 15
        feedback_parts.append("⚠️ anchorage_yield.csv created but missing data rows")
    elif csv_exists:
        score += 10
        feedback_parts.append("⚠️ anchorage_yield.csv exists but wasn't created during task")
    else:
        feedback_parts.append("❌ anchorage_yield.csv not found")

    # 3. Trajectory VLM Verification (50 points)
    vlm_score = 0
    query_vlm = env_info.get('query_vlm')
    
    try:
        from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
        frames = sample_trajectory_frames(traj, n=4)
        final = get_final_screenshot(traj)
        
        images = frames
        if final:
            images.append(final)
            
        if query_vlm and images:
            vlm_result = query_vlm(prompt=VLM_PROMPT, images=images)
            
            if vlm_result.get("success"):
                parsed = vlm_result.get("parsed", {})
                
                if parsed.get("panels_elevated"):
                    vlm_score += 15
                    feedback_parts.append("✅ VLM: Panels confirmed visually elevated")
                else:
                    feedback_parts.append("❌ VLM: Panels not visually elevated")
                    
                if parsed.get("panels_steep_tilt"):
                    vlm_score += 15
                    feedback_parts.append("✅ VLM: Panels confirmed steeply tilted")
                else:
                    feedback_parts.append("❌ VLM: Panels not steeply tilted")
                    
                if parsed.get("location_anchorage"):
                    vlm_score += 10
                    feedback_parts.append("✅ VLM: Location confirmed changed to Anchorage")
                    
                if parsed.get("analysis_run"):
                    vlm_score += 10
                    feedback_parts.append("✅ VLM: Analysis confirmed run")
            else:
                feedback_parts.append(f"⚠️ VLM query failed: {vlm_result.get('error')}")
        else:
            feedback_parts.append("⚠️ Could not perform VLM verification (missing function or trajectory images)")
            
    except Exception as e:
        logger.error(f"Error during VLM verification: {e}")
        feedback_parts.append(f"⚠️ VLM verification error: {e}")

    score += vlm_score

    # Passing condition: Must achieve at least 60 points, MUST have successfully exported a CSV during the task, 
    # and MUST have modified the panel geometry (minimum 15 VLM visual points).
    key_criteria_met = (csv_exists and csv_created_during_task) and vlm_score >= 15
    passed = score >= 60 and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }