#!/usr/bin/env python3
"""
Verifier for urban_canyon_heliostat_daylighting task.

Combines programmatic file checks with VLM verification of the optical setup.
Energy3D .ng3 files are Java-serialized, so we cannot safely parse the DOM in Python.
Instead, we rely on the creation of the required files + VLM inspection of the 
trajectory/UI state showing the Sun Rays, Mirror, and Date settings.
"""

import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are an expert evaluating a computer agent's work in a 3D CAD/CAE application called Energy3D.
The task was to install a tracking Mirror (heliostat) on a tall building, target it to a shaded area, enable "Sun Rays" to visualize the light bouncing down, and set the date to December 21.

Analyze these screenshots of the agent's workflow and final state. Evaluate the following criteria:

1. MIRROR PLACED: Is there a reflective Mirror object placed on top of one of the buildings (specifically the tallest skyscraper)?
2. SUN RAYS ENABLED: Are there visible bright yellow/white lines representing Sun Rays striking the 3D scene?
3. RAYS REFLECTING (TARGET BINDING): Are the Sun Rays visibly hitting the mirror and reflecting/bouncing downwards into the city block or onto a lower building? (This proves the mirror has a target).
4. WINTER SOLSTICE: Does the date in the top UI bar or side panel indicate December 21 (e.g., 12/21)?

Respond in JSON format:
{
    "mirror_placed": true/false,
    "sun_rays_enabled": true/false,
    "rays_reflecting_downwards": true/false,
    "date_is_december": true/false,
    "reasoning": "Brief explanation of what is visible in the UI and scene"
}
"""

def verify_urban_canyon_heliostat_daylighting(traj, env_info, task_info):
    """Verifies the heliostat task using file checks and VLM trajectory analysis."""
    
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env or not query_vlm:
        return {"passed": False, "score": 0, "feedback": "Required verification functions missing."}

    # 1. Programmatic Check (File Exports)
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load programmatic result: {e}")
        result = {}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    score = 0
    feedback_parts = []
    
    ng3_exists = result.get('ng3_exists', False)
    ng3_new = result.get('ng3_created_during_task', False)
    png_exists = result.get('png_exists', False)

    if ng3_exists and ng3_new:
        score += 15
        feedback_parts.append("Project saved properly")
    elif ng3_exists:
        score += 5
        feedback_parts.append("Project saved but timestamp is old")
    else:
        feedback_parts.append("Modified .ng3 project not saved")

    if png_exists:
        score += 15
        feedback_parts.append("Agent screenshot saved")
    else:
        feedback_parts.append("Agent screenshot not saved")

    # 2. VLM Check on Trajectory + Final Frame
    # We sample the trajectory because the agent might have rotated the camera just right
    # earlier in the process before saving.
    try:
        from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
        frames = sample_trajectory_frames(traj, n=4)
        final = get_final_screenshot(traj)
        if final:
            frames.append(final)
            
        vlm_result = query_vlm(images=frames, prompt=VLM_PROMPT)
        
        if vlm_result and vlm_result.get("success"):
            parsed = vlm_result.get("parsed", {})
            
            if parsed.get("mirror_placed"):
                score += 20
                feedback_parts.append("Mirror placed")
            
            if parsed.get("sun_rays_enabled"):
                score += 15
                feedback_parts.append("Sun rays enabled")
                
            if parsed.get("rays_reflecting_downwards"):
                score += 20
                feedback_parts.append("Rays reflecting downwards (Target active)")
                
            if parsed.get("date_is_december"):
                score += 15
                feedback_parts.append("Date set to Dec 21")
        else:
            feedback_parts.append("VLM evaluation failed to parse")
            
    except Exception as e:
        logger.error(f"VLM verification error: {e}")
        feedback_parts.append(f"VLM exception: {str(e)}")

    # Passing threshold is 70. They must have demonstrated at least the reflection mechanic.
    passed = score >= 70

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }