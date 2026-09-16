#!/usr/bin/env python3
"""
Verifier for the southern_hemisphere_mine_solar_orientation task.

Since Energy3D .ng3 files are serialized Java objects, we use a hybrid
approach: checking file system artifacts (to ensure the agent actually
saved the file during the task) combined with VLM trajectory analysis
to verify the procedural requirements (latitude, orientation, tilt, and analysis).
"""

import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent performing a solar engineering QA task in the Energy3D software.

The agent was asked to correct a Northern Hemisphere solar design to suit a Southern Hemisphere location. Look at the sequence of trajectory frames and the final screenshot to verify if the agent accomplished the following:

1. LATITUDE: Did the agent open the Location/Environment dialog and change the latitude to approximately -21 (or 21 South)?
2. ORIENTATION: Did the agent rotate the solar panels/racks so they face North? (Look at the N/S/E/W compass printed on the ground in the 3D view to verify the panels' tilt direction).
3. TILT ANGLE: Did the agent adjust the tilt angle of the panels (often done via right-click properties or a side panel) to approximately 21 degrees?
4. ANALYSIS: Is the 'Annual Energy Analysis' bar chart window visible in any of the frames, indicating the simulation was run?

Respond strictly in JSON format with boolean values and a brief reasoning string:
{
    "latitude_changed": true/false,
    "panels_face_north": true/false,
    "tilt_adjusted": true/false,
    "analysis_run": true/false,
    "reasoning": "Brief explanation of evidence found in the screenshots"
}
"""

def verify_southern_hemisphere_correction(traj, env_info, task_info):
    """
    Verify the completion of the solar array orientation task.
    """
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available in env_info"}
        
    if not query_vlm:
        return {"passed": False, "score": 0, "feedback": "VLM query function not available in env_info"}

    score = 0
    feedback_parts = []
    
    # 1. Check file existence and creation via exported JSON
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    file_exists = False
    created_during_task = False
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
            file_exists = result.get('file_exists', False)
            created_during_task = result.get('created_during_task', False)
    except Exception as e:
        logger.warning(f"Failed to read task_result.json: {e}")
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    if file_exists:
        score += 10
        feedback_parts.append("Corrected file was saved.")
        if created_during_task:
            score += 10
            feedback_parts.append("File creation timestamp is valid.")
        else:
            feedback_parts.append("File timestamp predates task (possible anti-gaming flag).")
    else:
        feedback_parts.append("Corrected file 'mine_site_corrected.ng3' was not found.")

    # 2. Extract trajectory frames for VLM
    try:
        # Import dynamically from gym_anything if needed, or assume it's available via framework context
        from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
        frames = sample_trajectory_frames(traj, n=5)
        final = get_final_screenshot(traj)
        if final and final not in frames:
            frames.append(final)
    except ImportError:
        # Fallback if specific framework import fails but we have traj object
        frames = []
        if 'steps' in traj:
            # Sample up to 5 frames
            step_count = len(traj['steps'])
            indices = [int(i * (step_count - 1) / 4) for i in range(5)] if step_count > 0 else []
            for idx in indices:
                img_path = traj['steps'][idx].get('screenshot_path')
                if img_path and os.path.exists(img_path):
                    frames.append(img_path)
            
            # Add final screenshot
            final_path = traj.get('final_screenshot')
            if final_path and os.path.exists(final_path) and final_path not in frames:
                frames.append(final_path)

    if not frames:
        return {"passed": False, "score": score, "feedback": "No trajectory frames available for VLM verification."}

    # 3. Query VLM
    vlm_result = query_vlm(
        images=frames,
        prompt=VLM_PROMPT
    )

    if not vlm_result.get("success"):
        feedback_parts.append(f"VLM verification failed: {vlm_result.get('error', 'Unknown error')}")
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}

    parsed = vlm_result.get("parsed", {})
    
    latitude_changed = parsed.get("latitude_changed", False)
    panels_face_north = parsed.get("panels_face_north", False)
    tilt_adjusted = parsed.get("tilt_adjusted", False)
    analysis_run = parsed.get("analysis_run", False)
    reasoning = parsed.get("reasoning", "No reasoning provided.")
    
    if latitude_changed:
        score += 25
        feedback_parts.append("Latitude correctly changed to Southern Hemisphere.")
    else:
        feedback_parts.append("Latitude change not detected.")
        
    if panels_face_north:
        score += 25
        feedback_parts.append("Panels successfully rotated to face North.")
    else:
        feedback_parts.append("Panels were not rotated to face North.")
        
    if tilt_adjusted:
        score += 15
        feedback_parts.append("Panel tilt angle adjusted.")
    else:
        feedback_parts.append("Tilt adjustment not detected.")
        
    if analysis_run:
        score += 15
        feedback_parts.append("Annual Energy Analysis graph shown.")
    else:
        feedback_parts.append("Analysis graph not shown.")

    # Passing criteria: Must save the file, must change the latitude, must rotate panels.
    key_criteria_met = file_exists and latitude_changed and panels_face_north
    passed = score >= 70 and key_criteria_met
    
    feedback = " | ".join(feedback_parts) + f" (VLM Reasoning: {reasoning})"
    
    return {
        "passed": passed,
        "score": score,
        "feedback": feedback
    }