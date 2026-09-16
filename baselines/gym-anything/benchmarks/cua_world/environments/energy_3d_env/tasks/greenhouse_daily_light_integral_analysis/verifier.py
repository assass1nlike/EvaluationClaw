#!/usr/bin/env python3
"""
Verifier for Commercial Greenhouse Winter Light Analysis.

Verification Strategy (Hybrid File + VLM):
1. Verifies the new .ng3 design file exists and was created during the task.
2. Verifies the user-directed screenshot exists.
3. Uses string parsing on the binary output as a heuristic for location ("Denver").
4. Uses VLM Trajectory checking to confirm Date manipulation, Window-to-Wall ratio manipulation,
   and visual verification of the Daily Solar Radiation heat map logic.
"""

import os
import json
import tempfile
import logging

try:
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
except ImportError:
    # Fallbacks in case framework injection is done differently
    sample_trajectory_frames = lambda traj, n=5: traj.get('frames', [])[-n:] if traj.get('frames') else []
    get_final_screenshot = lambda traj: traj.get('frames', [])[-1] if traj.get('frames') else None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating a user's workflow in the application Energy3D.
Review the provided progression frames and the final screenshot of the application.
Determine if the user successfully completed the following actions:

1. Did the user change the location setting to "Denver, CO"? (Look for the city selection dialog or Denver on the UI map ribbon).
2. Did the user change the simulation date to December 21? (Look for the date slider at the top or a time control showing 12/21).
3. Did the user make the building highly transparent like a greenhouse? (Look for the building model walls being converted to glass/windows, e.g., using a high Window-to-Wall Ratio).
4. Did the user generate a Daily Solar Radiation map? (A successful execution displays a colorful, color-coded heat map painted directly over the 3D building).

Respond strictly in JSON format:
{
    "location_denver": true/false,
    "date_dec_21": true/false,
    "walls_transparent": true/false,
    "solar_radiation_map_visible": true/false,
    "reasoning": "Brief explanation of evidence seen for each item"
}
"""

def verify_greenhouse_analysis(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    # 1. Retrieve programmatic results from the export script
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read exported results: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    score = 0
    feedback_parts = []

    design_exists = result.get('design_exists', False)
    design_created = result.get('design_created_during_task', False)
    screenshot_exists = result.get('screenshot_exists', False)
    has_denver_string = result.get('has_denver_string', False)

    # Base programmatic scoring (20 points max)
    if design_exists and design_created:
        score += 10
        feedback_parts.append("✅ Design file saved correctly.")
    else:
        feedback_parts.append("❌ Design file missing or unmodified.")

    if screenshot_exists:
        score += 10
        feedback_parts.append("✅ Viewport screenshot saved.")
    else:
        feedback_parts.append("❌ Viewport screenshot missing.")

    # 2. VLM Trajectory Verification
    vlm_parsed = {}
    if query_vlm:
        frames = sample_trajectory_frames(traj, n=4)
        final = get_final_screenshot(traj)
        images = [img for img in frames + [final] if img is not None]
        
        if images:
            vlm_response = query_vlm(prompt=VLM_PROMPT, images=images)
            if vlm_response.get('success'):
                vlm_parsed = vlm_response.get('parsed', {})
            else:
                feedback_parts.append("⚠️ VLM verification failed to process.")

    # 3. Apply VLM and heuristic points
    
    # Check Location (15 points) - Accepts either string heuristic OR visual evidence
    location_denver = vlm_parsed.get('location_denver', False) or has_denver_string
    if location_denver:
        score += 15
        feedback_parts.append("✅ Location set to Denver.")
    else:
        feedback_parts.append("❌ Location Denver not detected.")

    # Check Date (15 points)
    if vlm_parsed.get('date_dec_21', False):
        score += 15
        feedback_parts.append("✅ Date set to Dec 21.")
    else:
        feedback_parts.append("❌ Date Dec 21 not detected.")

    # Check Windows/Walls (20 points)
    walls_transparent = vlm_parsed.get('walls_transparent', False)
    if walls_transparent:
        score += 20
        feedback_parts.append("✅ Building converted to greenhouse (transparent).")
    else:
        feedback_parts.append("❌ Highly transparent walls not detected.")

    # Check Radiation Heat Map (30 points)
    solar_map = vlm_parsed.get('solar_radiation_map_visible', False)
    if solar_map:
        score += 30
        feedback_parts.append("✅ Solar Radiation map applied to building.")
    else:
        feedback_parts.append("❌ Solar Radiation map not visible.")

    # Key criteria: Must have achieved the solar map OR transparent walls to be considered "passing" overall
    key_criteria_met = solar_map and walls_transparent and design_exists
    passed = score >= 70 and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }