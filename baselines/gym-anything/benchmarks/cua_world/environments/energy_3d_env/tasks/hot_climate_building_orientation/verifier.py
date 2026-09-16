#!/usr/bin/env python3
"""
Verifier for hot_climate_building_orientation task.

Energy3D .ng3 files are Java-serialized binary files, making programmatic XML/JSON parsing unfeasible.
Therefore, this task uses a robust hybrid verification strategy:
1. Programmatic Check: Output file exists, meets minimum size, and was created AFTER the task started.
2. VLM Trajectory Check: Verifies the location change, building rotation, and energy analysis graph.
"""

import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent's performance in modifying a 3D building design in Energy3D.
Look at this sequence of screenshots taken during the agent's session.

TASK REQUIREMENTS:
1. Change Location: Did the agent open the location/city settings and change the location to Phoenix, AZ?
2. Rotate Building: Did the agent select the building and rotate its foundation by approximately 90 degrees compared to the initial frame? (Look for a shift from a North-South alignment to an East-West alignment, or vice versa).
3. Run Energy Analysis: Did the agent run an "Annual Energy Analysis"? You should see a bar chart dialog appearing with monthly heating, cooling, and total energy data.

Respond strictly in JSON format:
{
    "location_changed_to_phoenix": true/false,
    "building_rotated_90_deg": true/false,
    "energy_analysis_graph_shown": true/false,
    "confidence": "low/medium/high",
    "reasoning": "Brief explanation of what visual evidence supports your conclusions."
}
"""

def verify_hot_climate_building_orientation(traj, env_info, task_info):
    """
    Verify the building orientation task using a mix of programmatic file checks and VLM trajectory analysis.
    """
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "System error: copy_from_env not available."}
        
    if not query_vlm:
        return {"passed": False, "score": 0, "feedback": "System error: query_vlm not available."}

    metadata = task_info.get('metadata', {})
    min_size = metadata.get('min_file_size_bytes', 1024)
    
    score = 0
    feedback_parts = []
    
    # ---------------------------------------------------------
    # 1. Programmatic File Verification
    # ---------------------------------------------------------
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result data: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    output_exists = result.get('output_exists', False)
    file_created = result.get('file_created_during_task', False)
    file_size = result.get('output_size_bytes', 0)

    if output_exists and file_created and file_size >= min_size:
        score += 25
        feedback_parts.append("File correctly saved (phoenix_rotated.ng3).")
    elif output_exists:
        feedback_parts.append("File exists but was not created during task or is too small.")
    else:
        feedback_parts.append("Modified project file was not saved.")

    # ---------------------------------------------------------
    # 2. VLM Trajectory Verification
    # ---------------------------------------------------------
    # Extract frames from trajectory (we need the progression to see the actions)
    try:
        from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
        frames = sample_trajectory_frames(traj, n=5)
        final_img = get_final_screenshot(traj)
        if final_img not in frames:
            frames.append(final_img)
    except Exception as e:
        logger.warning(f"Error sampling frames, falling back to final screenshot: {e}")
        frames = [traj.get("final_screenshot")] if traj.get("final_screenshot") else []

    if not frames or not frames[0]:
        return {
            "passed": False, 
            "score": score, 
            "feedback": " | ".join(feedback_parts) + " | No screenshots available for VLM verification."
        }

    vlm_result = query_vlm(images=frames, prompt=VLM_PROMPT)
    
    if not vlm_result.get("success"):
        return {
            "passed": False, 
            "score": score, 
            "feedback": " | ".join(feedback_parts) + f" | VLM query failed: {vlm_result.get('error')}"
        }

    parsed = vlm_result.get("parsed", {})
    loc_changed = parsed.get("location_changed_to_phoenix", False)
    rotated = parsed.get("building_rotated_90_deg", False)
    analysis_run = parsed.get("energy_analysis_graph_shown", False)
    
    vlm_score = 0
    if loc_changed:
        vlm_score += 25
        feedback_parts.append("Location changed to Phoenix.")
    else:
        feedback_parts.append("Location not changed to Phoenix.")
        
    if rotated:
        vlm_score += 25
        feedback_parts.append("Building rotated correctly.")
    else:
        feedback_parts.append("Building rotation not detected.")
        
    if analysis_run:
        vlm_score += 25
        feedback_parts.append("Annual Energy Analysis graph shown.")
    else:
        feedback_parts.append("Energy analysis graph not detected.")

    # Apply confidence penalty if VLM was unsure
    confidence = parsed.get("confidence", "low").lower()
    if confidence == "medium":
        vlm_score = int(vlm_score * 0.9)
    elif confidence == "low":
        vlm_score = int(vlm_score * 0.7)
        
    score += vlm_score
    
    # Requirement for passing: Must save the file correctly AND accomplish at least 2 of the 3 VLM subtasks
    vlm_tasks_met = sum([loc_changed, rotated, analysis_run])
    passed = (score >= 70) and output_exists and (vlm_tasks_met >= 2)

    return {
        "passed": passed,
        "score": min(100, score),
        "feedback": " | ".join(feedback_parts),
        "details": {
            "vlm_reasoning": parsed.get("reasoning", ""),
            "file_exists": output_exists,
            "vlm_tasks_met": vlm_tasks_met
        }
    }