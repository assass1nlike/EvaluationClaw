#!/usr/bin/env python3
"""
Verifier for parabolic_dish_repowering_upgrade.

Verifies:
1. Programmatic: The output file was saved, exists, and was created during the task.
2. Visual (VLM via Trajectory): Old panels were deleted, new dishes placed, parameters configured, and analysis run.
"""

import os
import json
import tempfile
import logging
from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent's performance in Energy3D on a "Repowering" task.
The agent was asked to:
1. Delete the old flat solar panels/racks from the foundation.
2. Place a new array of Parabolic Dishes (bowl/dish shaped solar collectors) on the foundation (at least 6).
3. Set the Parabolic Dish parameters: Diameter to 10.0, Reflectance to 0.94 (or 94%).
4. Run the "Annual Energy Analysis" (a graph/chart window will appear calculating the annual yield).

Look at these sequential screenshots from the agent's workflow. Determine if the agent completed the steps.

Respond ONLY with a valid JSON object matching this schema:
{
    "old_panels_deleted": true/false,
    "parabolic_dishes_added": true/false,
    "parameters_edited_10_and_94": true/false,
    "annual_analysis_run": true/false,
    "reasoning": "Brief explanation of evidence seen in the frames"
}
"""

def verify_repowering(traj, env_info, task_info):
    """Hybrid verification combining programmatic file checks and VLM trajectory analysis."""
    
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env or not query_vlm:
        return {"passed": False, "score": 0, "feedback": "Required framework functions missing."}

    score = 0
    feedback_parts = []
    
    # 1. Programmatic File Check
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result file: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    output_exists = result.get("output_exists", False)
    file_created = result.get("file_created_during_task", False)
    size_bytes = result.get("output_size_bytes", 0)
    
    if output_exists and size_bytes > 1000:
        score += 15
        feedback_parts.append("File saved successfully.")
        if file_created:
            score += 15
            feedback_parts.append("File was created during task.")
        else:
            feedback_parts.append("Warning: File may have been pre-existing.")
    else:
        feedback_parts.append("Output file not found or invalid size.")
        return {"passed": False, "score": 0, "feedback": " | ".join(feedback_parts)}
        
    # Programmatic hint (not strict pass/fail, but helpful logic guard)
    hints = result.get("programmatic_hints", {})
    if hints.get("dish_string_count", 0) > 0:
        feedback_parts.append("Found ParabolicDish traces in binary.")

    # 2. VLM Trajectory Check
    frames = sample_trajectory_frames(traj, n=5)
    final_frame = get_final_screenshot(traj)
    if final_frame:
        frames.append(final_frame)
        
    if not frames:
        return {"passed": False, "score": score, "feedback": "No frames available for VLM."}

    vlm_result = query_vlm(prompt=VLM_PROMPT, images=frames)
    
    if not vlm_result.get("success"):
        feedback_parts.append(f"VLM Error: {vlm_result.get('error')}")
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}
        
    parsed = vlm_result.get("parsed", {})
    
    if parsed.get("old_panels_deleted"):
        score += 15
        feedback_parts.append("Old panels deleted.")
    if parsed.get("parabolic_dishes_added"):
        score += 25
        feedback_parts.append("Parabolic dishes placed.")
    if parsed.get("parameters_edited_10_and_94"):
        score += 15
        feedback_parts.append("Parameters (10.0, 94%) configured.")
    if parsed.get("annual_analysis_run"):
        score += 15
        feedback_parts.append("Annual analysis was run.")

    # Pass condition: File saved during task AND dishes added AND panels deleted
    passed = (
        output_exists and 
        file_created and 
        parsed.get("old_panels_deleted", False) and 
        parsed.get("parabolic_dishes_added", False) and
        score >= 70
    )
    
    feedback_parts.append(f"Reasoning: {parsed.get('reasoning', 'None')}")

    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback_parts)
    }