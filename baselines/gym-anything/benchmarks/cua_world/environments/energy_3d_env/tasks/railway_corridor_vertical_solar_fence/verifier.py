#!/usr/bin/env python3
"""
Verifier for railway_corridor_vertical_solar_fence task.
Energy3D .ng3 files are Java-serialized binaries, so we rely on:
1. File timestamp analysis (anti-gaming, ensures save actions happened).
2. Data extraction (parsing the user's manual yield logging).
3. Vision-Language Model evaluation via trajectory (verifying the UI changes).
"""

import json
import os
import tempfile
import logging

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_vertical_solar_fence(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env or not query_vlm:
        return {"passed": False, "score": 0, "feedback": "Required framework functions missing"}
        
    # Extract programmatic signals from the exported container state
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result metadata: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)
            
    score = 0
    feedback = []
    
    # 1. Project Creation Check (20 pts)
    ng3_created = result.get('ng3_exists', False) and result.get('ng3_created_during_task', False)
    if ng3_created:
        score += 20
        feedback.append("NG3 project properly saved.")
    else:
        feedback.append("NG3 project not found or not modified during task.")
        
    # 2. Text File Content Analysis (20 pts)
    txt_exists = result.get('txt_exists', False)
    try:
        yield_val = float(result.get('yield_value', 0.0))
        # Expected Yield should be a non-trivial positive number for a multi-rack array 
        if txt_exists and yield_val > 1000:
            score += 20
            feedback.append(f"Recorded valid yield value: {yield_val} kWh.")
        elif txt_exists:
            score += 5
            feedback.append(f"Recorded yield value ({yield_val}) seems trivially low or invalid.")
        else:
            feedback.append("Yield text file not found.")
    except ValueError:
        feedback.append("Could not parse a valid number from yield text file.")

    # 3. VLM Trajectory Verification (60 pts)
    frames = sample_trajectory_frames(traj, n=4)
    final_img = get_final_screenshot(traj)
    images = frames + [final_img] if final_img else frames
    
    prompt = """You are evaluating an agent's architectural design work in Energy3D.
Task Context: The agent was instructed to convert standard solar racks into a vertical East-West solar fence, run Annual Yield Analysis, and record the result.
Carefully review the trajectory frames and final screenshot to verify:
1. Are the solar panels oriented vertically (90 degree tilt)? (They should resemble upright vertical fences/walls, NOT slanted roofs).
2. Are they oriented East-West? (Rotated 90 degrees horizontally from their original default South-facing position).
3. Is there evidence that the 'Bifacial' setting was enabled or visible in the properties UI panel?
4. Is there evidence that the Annual Yield Analysis tool was executed? (Look for a bar chart popup showing monthly energy generation).

Provide a JSON response representing the booleans exactly as specified:
{
  "vertical_tilt_visible": true/false,
  "east_west_azimuth_visible": true/false,
  "bifacial_enabled_or_visible": true/false,
  "yield_analysis_run": true/false,
  "reasoning": "brief explanation"
}"""

    vlm_res = query_vlm(images=images, prompt=prompt)
    if vlm_res and vlm_res.get("success") and isinstance(vlm_res.get("parsed"), dict):
        parsed = vlm_res.get("parsed", {})
        
        if parsed.get("vertical_tilt_visible", False):
            score += 20
            feedback.append("Vertical 90-degree tilt visually verified.")
        else:
            feedback.append("Failed to visually verify vertical tilt.")
            
        if parsed.get("east_west_azimuth_visible", False):
            score += 15
            feedback.append("East-West horizontal orientation visually verified.")
            
        if parsed.get("bifacial_enabled_or_visible", False):
            score += 10
            feedback.append("Bifacial parameter interaction visually verified.")
            
        if parsed.get("yield_analysis_run", False):
            score += 15
            feedback.append("Annual yield analysis popup visually verified.")
    else:
        feedback.append(f"VLM evaluation failed or returned invalid format: {vlm_res.get('error', 'Unknown Error')}")

    # Determine passing state
    # Must save the file, extract a plausible number, and get at least partial UI verification.
    passed = score >= 75 and ng3_created
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback)
    }