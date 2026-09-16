#!/usr/bin/env python3
"""
Verifier for Building Passive Solar Heating Optimization task.

Verification Strategy:
1. Programmatic Check: Ensure the modified .ng3 file was saved.
2. Programmatic Check: Ensure the daily energy load .csv file was exported and contains data.
3. VLM Check: Use trajectory frames to verify that windows were modified on the building, 
   the date was set to January 15, and the Daily Energy Analysis tool was run.
"""

import os
import json
import logging
import tempfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent's performance in Energy3D on a passive solar heating design task.
I am providing several frames from the agent's screen recording trajectory.

Please review the trajectory frames and determine the following:
1. WINDOW MODIFICATION: Did the agent add a new window, or resize/enlarge an existing window on the South-facing wall of the building?
2. DATE SETTING: Did the agent adjust the date control in the top toolbar to January 15?
3. ANALYSIS EXECUTION: Did the agent run a Daily Energy Analysis? Look for a graph window titled "Daily Energy Analysis" appearing on screen.

Return a JSON object strictly following this format:
{
    "window_modified": true/false,
    "date_set_jan15": true/false,
    "analysis_run": true/false,
    "reasoning": "brief explanation of what you observed in the frames"
}
"""

def verify_passive_heating(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    # 1. Read exported programmatic data
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read task result: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    ng3_info = result.get("ng3_file", {})
    csv_info = result.get("csv_file", {})
    original_ng3_size = result.get("original_ng3_size", 0)
    
    score = 0
    feedback_parts = []
    
    # 2. Check Modified Project File (20 points)
    # Note: Because .ng3 files in Energy3D are Java-serialized binary, size difference is our programmatic heuristic.
    ng3_exists = ng3_info.get("exists", False)
    ng3_created = ng3_info.get("created_during_task", False)
    ng3_size = ng3_info.get("size_bytes", 0)
    
    if ng3_exists and ng3_created:
        score += 10
        feedback_parts.append("Modified .ng3 saved correctly")
        
        # Check if size changed (indicating a modification was actually made)
        if abs(ng3_size - original_ng3_size) > 10: 
            score += 10
            feedback_parts.append("Project file size differs from original, confirming changes")
        else:
            feedback_parts.append("Project file saved, but size is identical to starter file (no changes detected programmatically)")
    else:
        feedback_parts.append("Modified project file not found or not created during task")

    # 3. Check CSV Export (25 points)
    csv_exists = csv_info.get("exists", False)
    csv_created = csv_info.get("created_during_task", False)
    csv_size = csv_info.get("size_bytes", 0)
    
    if csv_exists and csv_created:
        score += 15
        feedback_parts.append("CSV file exported successfully")
        
        # Check if CSV has actual data (not empty, a typical export should be a few hundred bytes)
        if csv_size > 50:
            score += 10
            feedback_parts.append(f"CSV contains valid data ({csv_size} bytes)")
        else:
            feedback_parts.append(f"CSV file is too small to contain valid analysis data ({csv_size} bytes)")
    else:
        feedback_parts.append("CSV file not found or not created during task")

    # 4. VLM Verification (55 points)
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            
            # Sample frames from trajectory to see the workflow
            frames = sample_trajectory_frames(traj, n=5)
            final_frame = get_final_screenshot(traj)
            
            if final_frame:
                frames.append(final_frame)
                
            vlm_response = query_vlm(images=frames, prompt=VLM_PROMPT)
            parsed_vlm = vlm_response.get("parsed", {})
            
            window_modified = parsed_vlm.get("window_modified", False)
            date_set_jan15 = parsed_vlm.get("date_set_jan15", False)
            analysis_run = parsed_vlm.get("analysis_run", False)
            
            if window_modified:
                score += 25
                feedback_parts.append("VLM confirmed window modification")
            else:
                feedback_parts.append("VLM did not detect window modification")
                
            if date_set_jan15:
                score += 10
                feedback_parts.append("VLM confirmed date set to Jan 15")
            else:
                feedback_parts.append("VLM did not detect date change")
                
            if analysis_run:
                score += 20
                feedback_parts.append("VLM confirmed Daily Analysis graph visible")
            else:
                feedback_parts.append("VLM did not detect Daily Analysis execution")
                
        except Exception as e:
            feedback_parts.append(f"VLM verification failed with exception: {e}")
    else:
        feedback_parts.append("VLM function not available, skipping visual validation")

    # Determine Pass/Fail (Threshold: 80 points)
    # A perfect agent must export valid files AND modify the geometry in the VLM.
    passed = score >= 80
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }