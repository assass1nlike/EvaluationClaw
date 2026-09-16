#!/usr/bin/env python3
"""
Verifier for urban_microgrid_shading_analysis task.

Strategy:
1. Copy the exported .ng3 file and task_result.json from the environment.
2. Programmatically verify:
   - File exists and was modified after task start.
   - City is set to Chicago (text search in .ng3 serialization).
   - Panels are added (counting 'SolarPanel'/'Rack' instances).
   - Tilt angle is 20 degrees.
3. VLM Verification:
   - Check trajectory frames and final screenshot.
   - Verify panels are ON the central building.
   - Verify skyscrapers are EMPTY of panels.
"""

import json
import os
import re
import tempfile
import logging

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an urban microgrid shading analysis task in a 3D CAD tool (Energy3D).
The agent was asked to:
1. Identify the central, low-rise building (surrounded by four tall skyscrapers).
2. Install many solar panels (at least 50) exclusively on the flat roof of this central building.
3. Ensure the surrounding tall skyscrapers have NO solar panels on them.
4. Adjust the panels to a 20-degree tilt.

Analyze these trajectory frames and the final screenshot:
1. Are there solar panels placed ON TOP OF the central, low-rise building?
2. Are the four surrounding tall skyscrapers completely empty of solar panels?
3. Did the agent successfully complete the task without placing panels on the ground or wrong buildings?

Return your analysis in this JSON format:
{
    "panels_on_central_building": true/false,
    "skyscrapers_are_empty": true/false,
    "workflow_completed": true/false,
    "reasoning": "brief explanation"
}
"""

def verify_urban_microgrid(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available."}
    
    score = 0
    feedback_parts = []
    
    # 1. Read task_result.json
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to load task result: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    # Validate file presence and timestamp
    file_exists = result.get('file_exists', False)
    task_start = result.get('task_start', 0)
    file_mtime = result.get('file_mtime', 0)

    if not file_exists:
        return {"passed": False, "score": 0, "feedback": "Target file chicago_microgrid.ng3 was not saved."}
    
    if file_mtime < task_start:
        return {"passed": False, "score": 0, "feedback": "File exists but was not modified during the task (stale file)."}
    
    score += 10
    feedback_parts.append("File Saved (10/10)")

    # 2. Parse the .ng3 file
    temp_ng3 = tempfile.NamedTemporaryFile(delete=False, suffix='.ng3')
    ng3_content = ""
    try:
        copy_from_env("/tmp/exported_microgrid.ng3", temp_ng3.name)
        with open(temp_ng3.name, 'r', errors='ignore') as f:
            ng3_content = f.read()
    except Exception as e:
        logger.warning(f"Could not read .ng3 file content: {e}")
    finally:
        if os.path.exists(temp_ng3.name):
            os.unlink(temp_ng3.name)

    # City Check (Chicago)
    # Energy3D JSON often stores this as "City": "Chicago" or similar
    if "Chicago" in ng3_content:
        score += 20
        feedback_parts.append("City set to Chicago (20/20)")
    else:
        feedback_parts.append("City not set to Chicago (0/20)")

    # Panels Check
    # Counting occurrences of SolarPanel or Rack
    panel_count = ng3_content.count('SolarPanel') + ng3_content.count('Rack')
    if panel_count >= 50:
        score += 20
        feedback_parts.append(f"Solar Panels Added: {panel_count} (20/20)")
    elif panel_count >= 20:
        score += 10
        feedback_parts.append(f"Partial Solar Panels Added: {panel_count} (10/20)")
    else:
        feedback_parts.append(f"Insufficient Solar Panels Added: {panel_count} (0/20)")

    # Tilt Angle Check
    # We look for "20.0" or variants near tilt properties. 
    # Just checking if '20.0' or '20' appears significantly more times than in a blank file.
    if ng3_content.count('20.0') >= 5 or ng3_content.count('tiltAngle": 20') > 0 or ng3_content.count('tilt": 20') > 0:
        score += 20
        feedback_parts.append("Tilt Angle set to 20 (20/20)")
    else:
        feedback_parts.append("Tilt Angle not adjusted to 20 (0/20)")

    # 3. VLM Verification
    if query_vlm:
        frames = sample_trajectory_frames(traj, n=4)
        final_frame = get_final_screenshot(traj)
        
        if final_frame:
            images = frames + [final_frame]
            vlm_res = query_vlm(images=images, prompt=VLM_PROMPT)
            
            if vlm_res.get('success'):
                parsed = vlm_res.get('parsed', {})
                vlm_score = 0
                
                if parsed.get('panels_on_central_building', False):
                    vlm_score += 15
                if parsed.get('skyscrapers_are_empty', False):
                    vlm_score += 10
                if parsed.get('workflow_completed', False):
                    vlm_score += 5
                    
                score += vlm_score
                feedback_parts.append(f"VLM Spatial Verification ({vlm_score}/30)")
            else:
                feedback_parts.append("VLM query failed (0/30)")
        else:
            feedback_parts.append("No screenshots available for VLM (0/30)")
    else:
        feedback_parts.append("VLM not available (0/30)")

    # Final Evaluation
    key_criteria_met = file_exists and (panel_count >= 20) and ("Chicago" in ng3_content)
    passed = (score >= 70) and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }