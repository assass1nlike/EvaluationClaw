#!/usr/bin/env python3
"""
Verifier for parabolic_trough_solar_plant task.

Uses a hybrid approach:
1. Programmatic File Check: Reads the exported JSON to verify the .ng3 file 
   was created during the task, has sufficient size, and contains expected serialized string data.
2. VLM Trajectory Verification: Samples trajectory frames to visually verify 
   the foundation, array configuration, and property panel inputs.
"""

import os
import json
import tempfile
import logging
from typing import Dict, Any

# Framework utilities
from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot, query_vlm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are a solar energy CAD evaluator verifying an Energy3D agent's actions.
Look at this sequence of screenshots (trajectory + final state) showing the user designing a Parabolic Trough solar plant.

Analyze the visual evidence and determine if the user accomplished the following:
1. Added a "Foundation" (a platform area drawn on the ground).
2. Added an array/field of Parabolic Troughs (you should see multiple curved mirror structures).
3. Configured the trough properties. Look closely at any open property dialogs, right-click menus, or side panels. Did the agent set:
   - Width to ~6.0m
   - Reflectance to ~0.95 (or 95%)
   - Absorptance to ~0.92 (or 92%)
4. Checked or set the location to Phoenix, AZ (often visible in a map window, location menu, or top bar).
5. Oriented the troughs North-South (axis running up/down the screen relative to the compass).

Note: The property panel might only be visible in the middle frames of the trajectory sequence.

Return your evaluation in strict JSON format:
{
    "foundation_visible": true/false,
    "multiple_troughs_visible": true/false,
    "properties_configured": true/false,
    "location_is_phoenix": true/false,
    "troughs_north_south": true/false,
    "reasoning": "Brief explanation of the visual evidence found across frames"
}
"""

def verify_parabolic_trough_plant(traj: Dict[str, Any], env_info: Dict[str, Any], task_info: Dict[str, Any]) -> Dict[str, Any]:
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "System error: copy_from_env not available"}

    score = 0
    feedback_parts = []
    
    # ==========================================
    # 1. Programmatic File & Heuristic Checks
    # ==========================================
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read exported results: {str(e)}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    file_exists = result.get('file_exists', False)
    file_created = result.get('file_created_during_task', False)
    file_size = result.get('file_size_bytes', 0)
    has_phoenix = result.get('has_phoenix_string', False)
    has_trough = result.get('has_trough_string', False)
    
    # Evaluate File State (Total 20 points)
    if file_exists and file_created:
        score += 10
        feedback_parts.append("✅ NG3 file created")
        if file_size > 1024:  # At least 1KB
            score += 5
            feedback_parts.append("✅ File size valid")
    else:
        feedback_parts.append("❌ File not created/saved properly")
        
    # Evaluate String Heuristics (Total 10 points)
    if has_phoenix:
        score += 5
        feedback_parts.append("✅ 'Phoenix' found in save data")
    if has_trough:
        score += 5
        feedback_parts.append("✅ 'ParabolicTrough' found in save data")
        
    # ==========================================
    # 2. VLM Trajectory Verification
    # ==========================================
    query_vlm_func = env_info.get('query_vlm', query_vlm)
    
    # Sample 4 frames across the trajectory + 1 final screenshot
    frames = sample_trajectory_frames(traj, n=4)
    final_img = get_final_screenshot(traj)
    
    if final_img:
        frames.append(final_img)
        
    if not frames:
        return {"passed": False, "score": score, "feedback": "❌ No visual evidence to verify workflow."}
        
    try:
        vlm_resp = query_vlm_func(prompt=VLM_PROMPT, images=frames)
        vlm_result = vlm_resp.get("parsed", {})
    except Exception as e:
        logger.error(f"VLM query failed: {e}")
        vlm_result = {}
        
    # Evaluate VLM responses (Total 70 points)
    if vlm_result.get("foundation_visible", False):
        score += 10
        feedback_parts.append("✅ Foundation built")
    else:
        feedback_parts.append("❌ Foundation missing")
        
    if vlm_result.get("multiple_troughs_visible", False):
        score += 20
        feedback_parts.append("✅ Trough array present")
    else:
        feedback_parts.append("❌ Trough array missing")
        
    if vlm_result.get("properties_configured", False):
        score += 20
        feedback_parts.append("✅ Properties configured (Reflectance/Absorptance/Width)")
    else:
        feedback_parts.append("❌ Property configuration not confirmed visually")
        
    if vlm_result.get("location_is_phoenix", False):
        score += 10
        feedback_parts.append("✅ Location set to Phoenix")
        
    if vlm_result.get("troughs_north_south", False):
        score += 10
        feedback_parts.append("✅ Array oriented North-South")
        
    logger.info(f"VLM Reasoning: {vlm_result.get('reasoning', 'None')}")

    # ==========================================
    # Final Scoring
    # ==========================================
    # Critical pass criteria: File must exist, Troughs must exist visually
    key_criteria_met = file_exists and vlm_result.get("multiple_troughs_visible", False)
    passed = (score >= 65) and key_criteria_met
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }