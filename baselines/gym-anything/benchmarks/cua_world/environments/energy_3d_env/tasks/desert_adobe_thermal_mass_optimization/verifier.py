#!/usr/bin/env python3
"""
Verifier for the desert_adobe_thermal_mass_optimization task.

Uses a hybrid verification approach:
1. Programmatic Check: Reads exported JSON to verify the CSV outputs and modified model 
   were saved during the session and contain valid headers.
2. VLM Trajectory Check: Analyzes screenshots to verify properties (U-Value, Heat Capacity, 
   Date, Location) were correctly set in the Energy3D UI.
"""

import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying an Energy3D architectural physics simulation task.
Review these screenshots from the agent's trajectory.

Did the agent successfully configure the following parameters in the Energy3D UI:
1. Is the location set to Albuquerque, NM (or latitude ~35°)?
2. Is the simulation date set to January 21 (or late January)?
3. Is the building's Wall U-value modified to exactly 0.4 (or 0.40)?
4. Is the building's Wall Volumetric Heat Capacity modified to exactly 0.5?
5. Did the agent open the "Daily Building Energy Analysis" graph window at least once?

Reply ONLY with a JSON object using these exact keys:
{
    "location_set": true/false,
    "date_set": true/false,
    "u_value_set": true/false,
    "heat_capacity_set": true/false,
    "analysis_run": true/false
}
"""

def verify_thermal_mass_optimization(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env or not query_vlm:
        return {"passed": False, "score": 0, "feedback": "Required environment functions not available"}

    # --- 1. Programmatic File Checks ---
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    task_start = result.get('task_start', 0)
    baseline_csv = result.get('baseline_csv', {})
    adobe_csv = result.get('adobe_csv', {})
    ng3_exists = result.get('ng3_exists', False)
    ng3_mtime = result.get('ng3_mtime', 0)

    score = 0
    feedback_parts = []
    
    # Check baseline export
    if baseline_csv.get('exists'):
        if baseline_csv.get('mtime', 0) >= task_start:
            if baseline_csv.get('valid_header'):
                score += 15
                feedback_parts.append("Baseline CSV exported correctly.")
            else:
                score += 5
                feedback_parts.append("Baseline CSV exists but headers are invalid.")
        else:
            feedback_parts.append("Baseline CSV is stale (created before task).")
    else:
        feedback_parts.append("Baseline CSV missing.")

    # Check adobe export
    if adobe_csv.get('exists'):
        if adobe_csv.get('mtime', 0) >= task_start:
            if adobe_csv.get('valid_header'):
                score += 15
                feedback_parts.append("Adobe CSV exported correctly.")
            else:
                score += 5
                feedback_parts.append("Adobe CSV exists but headers are invalid.")
        else:
            feedback_parts.append("Adobe CSV is stale.")
    else:
        feedback_parts.append("Adobe CSV missing.")

    # Check NG3 save
    if ng3_exists and ng3_mtime >= task_start:
        score += 10
        feedback_parts.append("Modified .ng3 model saved.")
    else:
        feedback_parts.append("Modified .ng3 model not saved properly.")

    # --- 2. VLM Trajectory Checks ---
    try:
        from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
        frames = sample_trajectory_frames(traj, n=5)
        final_frame = get_final_screenshot(traj)
        if final_frame:
            frames.append(final_frame)
            
        vlm_result = query_vlm(prompt=VLM_PROMPT, images=frames)
        parsed = vlm_result.get("parsed", {})
        
        if parsed.get("location_set"):
            score += 10
            feedback_parts.append("Location correctly set.")
        if parsed.get("date_set"):
            score += 10
            feedback_parts.append("Simulation date correctly set.")
        if parsed.get("u_value_set"):
            score += 15
            feedback_parts.append("U-Value modified to 0.4.")
        if parsed.get("heat_capacity_set"):
            score += 15
            feedback_parts.append("Volumetric Heat Capacity modified to 0.5.")
        if parsed.get("analysis_run"):
            score += 10
            feedback_parts.append("Analysis graph opened.")
            
    except Exception as e:
        logger.error(f"VLM verification failed: {e}")
        feedback_parts.append("VLM verification failed to run.")

    # Must have completed some structural modification and exported at least one file
    key_criteria_met = (baseline_csv.get('exists') or adobe_csv.get('exists')) and \
                       (parsed.get('u_value_set', False) or parsed.get('heat_capacity_set', False))
                       
    passed = score >= 60 and key_criteria_met

    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback_parts)
    }