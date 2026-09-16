#!/usr/bin/env python3
import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying if an AI agent successfully completed an architectural task in the Energy3D application.

TASK REQUIREMENTS:
1. Draw a new U-shaped school building using the Foundation tool (must look like a "U" or have a distinct courtyard).
2. Add a Flat Roof to the new building.
3. Add Windows to the new building.
4. Add Trees inside or immediately adjacent to the courtyard of the new U-shaped building.
5. Do not delete the existing city context buildings.

Please review the provided trajectory frames (which show the workflow progression) and the final screenshot. 
Determine if the agent successfully completed the visual aspects of the task.

Respond EXACTLY with this JSON format:
{
    "drew_u_shaped_building": true/false,
    "added_flat_roof": true/false,
    "added_windows": true/false,
    "added_trees_in_courtyard": true/false,
    "reasoning": "brief explanation of what is visible"
}
"""

def verify_urban_school(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    # Extract JSON results
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to load export data: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    score = 0
    feedback_parts = []
    
    # 1. Check file existence & anti-gaming (20 points)
    output_exists = result.get('output_exists', False)
    file_created = result.get('file_created_during_task', False)
    output_size = result.get('output_size_bytes', 0)
    
    if output_exists and file_created and output_size > 1000:
        score += 20
        feedback_parts.append("File city_school_addition.ng3 saved successfully")
    elif output_exists:
        score += 10
        feedback_parts.append("File exists but was not verified as newly created (partial credit)")
    else:
        feedback_parts.append("File city_school_addition.ng3 was NOT saved")

    # 2. VLM Verification
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            frames = sample_trajectory_frames(traj, n=4)
            final = get_final_screenshot(traj)
            images = frames + [final] if final else frames
        except ImportError:
            # Fallback if specific gym_anything utils are absent
            images = []
            
        if not images:
            feedback_parts.append("VLM verification failed (no images)")
            return {
                "passed": False, 
                "score": score, 
                "feedback": " | ".join(feedback_parts)
            }
            
        vlm_res = query_vlm(prompt=VLM_PROMPT, images=images)
        if not vlm_res.get("success"):
            feedback_parts.append(f"VLM error: {vlm_res.get('error', 'unknown')}")
        else:
            parsed = vlm_res.get("parsed", {})
            
            # Evaluate visual criteria
            u_shape = parsed.get("drew_u_shaped_building", False)
            roof = parsed.get("added_flat_roof", False)
            windows = parsed.get("added_windows", False)
            trees = parsed.get("added_trees_in_courtyard", False)
            
            if u_shape:
                score += 30
                feedback_parts.append("U-shaped building verified")
            else:
                feedback_parts.append("No U-shaped building detected")
                
            if roof:
                score += 15
                feedback_parts.append("Flat roof verified")
                
            if windows:
                score += 15
                feedback_parts.append("Windows verified")
                
            if trees:
                score += 20
                feedback_parts.append("Courtyard trees verified")
                
    else:
        feedback_parts.append("VLM query function not available")

    # Final pass logic: Must score at least 70 and MUST have saved the file and drawn the building
    key_criteria_met = output_exists and (score >= 50) 
    passed = score >= 70 and key_criteria_met
    
    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback_parts)
    }