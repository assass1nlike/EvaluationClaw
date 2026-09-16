#!/usr/bin/env python3
"""
Verifier for the Solar Array Regional Optimization task in Energy3D.

Uses a hybrid verification strategy:
1. Programmatic Check: Parses the exported JSON to ensure the target `.ng3` file 
   was created during the session, and that the binary contains the updated location 
   and hardware strings.
2. Trajectory VLM Check: Queries a VLM using sampled trajectory frames to confirm 
   the agent interacted with spatial parameter inputs (Tilt and Azimuth).
"""

import os
import json
import logging
import tempfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent interacting with the Energy3D engineering software.
The agent was instructed to modify a solar array design.

Please analyze these trajectory screenshots and determine if the agent successfully changed the spatial orientation parameters. 
Look carefully at the properties panels, context menus, or popup dialogs.

Answer the following questions:
1. Is there visual evidence that the agent changed or attempted to change the Tilt angle to 33 degrees?
2. Is there visual evidence that the agent changed or attempted to change the Azimuth angle to 180 degrees?

Provide your response strictly in the following JSON format:
{
    "changed_tilt": true/false,
    "changed_azimuth": true/false,
    "reasoning": "brief explanation of what you see in the UI"
}
"""

def verify_solar_array_optimization(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "System error: copy_from_env not available."}

    # Extract task result JSON from container
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result_data = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to parse task results: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    score = 0
    feedback_parts = []
    
    # 1. Check file existence and timestamp (Anti-Gaming)
    file_exists = result_data.get("file_exists", False)
    created_during_task = result_data.get("created_during_task", False)
    
    if not file_exists:
        return {"passed": False, "score": 0, "feedback": "Failed: 'phoenix-solar-array.ng3' was not created."}
    
    if not created_during_task:
        return {"passed": False, "score": 0, "feedback": "Failed: File exists but was not modified/created during this session."}
    
    score += 20
    feedback_parts.append("File created correctly")

    # 2. Check extracted binary strings for City and Hardware modifications
    has_phoenix = result_data.get("has_phoenix_string", False)
    has_panel = result_data.get("has_panel_string", False)
    
    if has_phoenix:
        score += 20
        feedback_parts.append("Location updated to Phoenix")
    else:
        feedback_parts.append("Location not updated to Phoenix")
        
    if has_panel:
        score += 20
        feedback_parts.append("Panel hardware updated to SunPower SPR-X21")
    else:
        feedback_parts.append("Panel hardware not updated")

    # 3. VLM Trajectory Verification for numeric parameters (Tilt and Azimuth)
    if not query_vlm:
        feedback_parts.append("System error: VLM verification unavailable")
    else:
        try:
            # Sample multiple frames across the trajectory to catch UI property changes
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            frames = sample_trajectory_frames(traj, n=8)
            final_frame = get_final_screenshot(traj)
            if final_frame:
                frames.append(final_frame)
                
            vlm_response = query_vlm(images=frames, prompt=VLM_PROMPT)
            vlm_parsed = vlm_response.get("parsed", {})
            
            changed_tilt = vlm_parsed.get("changed_tilt", False)
            changed_azimuth = vlm_parsed.get("changed_azimuth", False)
            
            if changed_tilt:
                score += 20
                feedback_parts.append("Tilt angle updated to 33°")
            else:
                feedback_parts.append("Tilt angle update not verified")
                
            if changed_azimuth:
                score += 20
                feedback_parts.append("Azimuth angle updated to 180°")
            else:
                feedback_parts.append("Azimuth angle update not verified")
                
            logger.info(f"VLM Reasoning: {vlm_parsed.get('reasoning', 'None provided')}")
            
        except Exception as e:
            logger.error(f"VLM error: {e}")
            feedback_parts.append(f"VLM verification failed")

    # Determine passing criteria
    # Must have created the file AND achieved at least 2 of the 4 required edits.
    passed = (score >= 60)
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }