#!/usr/bin/env python3
"""
Verifier for Urban Solar Heat Map Analysis task.

Strategy:
1. Programmatic file checks (existence + size + modification time to prevent gaming).
2. VLM trajectory verification to confirm the Heat Map feature was genuinely used and 
   the date/location parameters match the specification.
"""

import os
import json
import tempfile
import logging
import sys

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent performing an urban solar heat map analysis in Energy3D.
Please look at the provided screenshot(s) of the application and determine the following:

1. Heat Map Visible: Are the buildings in the 3D viewport rendered with a colorful thermal/radiation overlay (Solar Radiation Heat Map) instead of standard flat colors or textures?
2. Location Boston: Is the location dropdown/UI element clearly set to "Boston, MA"?
3. Date June 21: Is the date in the UI clearly set to June 21 (or the month slider is at June and day slider at 21)?

Respond in JSON format:
{
    "heat_map_visible": true/false,
    "location_boston": true/false,
    "date_june_21": true/false,
    "reasoning": "Brief explanation of what you observed in the UI"
}
"""

def verify_heat_map_analysis(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}
    if not query_vlm:
        return {"passed": False, "score": 0, "feedback": "VLM query function not available"}

    # 1. Extract and read the exported results safely
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

    score = 0
    feedback_parts = []

    # 2. Check Project File (20 Points)
    proj_exists = result.get('proj_exists', False)
    proj_created = result.get('proj_created_during_task', False)
    proj_size = result.get('proj_size', 0)
    
    if proj_exists and proj_created and proj_size > 1000:
        score += 20
        feedback_parts.append("✅ Project file saved correctly")
    elif proj_exists:
        feedback_parts.append("❌ Project file exists but wasn't created during task/invalid")
    else:
        feedback_parts.append("❌ Project file not found")

    # 3. Check Screenshot File (20 Points)
    img_exists = result.get('img_exists', False)
    img_created = result.get('img_created_during_task', False)
    img_size = result.get('img_size', 0)
    
    if img_exists and img_created and img_size > 1000:
        score += 20
        feedback_parts.append("✅ Screenshot saved correctly")
    elif img_exists:
        feedback_parts.append("❌ Screenshot exists but wasn't created during task/invalid")
    else:
        feedback_parts.append("❌ Screenshot not found")

    # 4. VLM Verification (60 Points)
    # Combine final frame + 3 samples across the trajectory
    frames = sample_trajectory_frames(traj, n=3)
    final_frame = get_final_screenshot(traj)
    
    images_to_check = frames
    if final_frame:
        images_to_check.append(final_frame)
        
    if not images_to_check:
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts) + " | No images to verify via VLM"}

    vlm_result = query_vlm(prompt=VLM_PROMPT, images=images_to_check)
    
    if vlm_result.get("success"):
        parsed = vlm_result.get("parsed", {})
        
        # Heat Map Visual Check (30 points)
        if parsed.get("heat_map_visible", False):
            score += 30
            feedback_parts.append("✅ VLM: Heat map overlay visible")
        else:
            feedback_parts.append("❌ VLM: Heat map overlay NOT visible")
            
        # Config Check (30 points total)
        config_score = 0
        if parsed.get("location_boston", False):
            config_score += 15
        if parsed.get("date_june_21", False):
            config_score += 15
        
        if config_score > 0:
            score += config_score
            feedback_parts.append(f"✅ VLM: Config check passed ({config_score}/30)")
        else:
            feedback_parts.append("❌ VLM: Location/Date configuration incorrect")
    else:
        feedback_parts.append(f"⚠️ VLM query failed: {vlm_result.get('error')}")

    # Pass condition: File must exist, heat map must be visually verified.
    passed = score >= 70

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }