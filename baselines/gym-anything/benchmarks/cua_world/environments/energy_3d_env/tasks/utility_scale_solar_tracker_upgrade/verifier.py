#!/usr/bin/env python3
"""
Verifier for utility_scale_solar_tracker_upgrade task.

Verification Strategy:
1. File Verification (Programmatic): Ensure 'phoenix_hsat_array.ng3' exists and was modified after task start.
2. Content Verification (Programmatic): Read the .ng3 file (JSON payload) to check if the City is set to Phoenix and if SolarRacks have an active tracker property.
3. Process Verification (VLM): Evaluate trajectory frames to ensure the Annual Yield Analysis was executed via the GUI.
"""

import os
import json
import re
import tempfile
import logging
from typing import Dict, Any

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot, query_vlm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating a solar engineering task performed by a computer agent in the Energy3D application.
The agent was asked to:
1. Change the geographic location to Phoenix, AZ.
2. Upgrade the solar racks to use horizontal single-axis tracking.
3. Run an 'Annual Yield Analysis'.

Look carefully at the provided trajectory frames and the final screenshot:
1. Did the agent open the 'Annual Yield Analysis' window? (Look for a bar chart/graph window titled "Annual Yield Analysis" or similar showing monthly generation).
2. Is there evidence the agent used the Energy3D GUI legitimately to make changes (e.g., clicking menus, adjusting properties in the right-side panel)?

Respond in the following JSON format:
{
    "yield_analysis_executed": true/false,
    "gui_used_legitimately": true/false,
    "reasoning": "Provide a brief explanation of the evidence seen in the frames"
}
"""

def verify_solar_tracker_upgrade(traj: Dict[str, Any], env_info: Dict[str, Any], task_info: Dict[str, Any]) -> Dict[str, Any]:
    copy_from_env = env_info.get('copy_from_env')
    vlm_query_func = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # --- 1. Read exported results ---
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    result_data = {}
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result_data = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result data: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    file_exists = result_data.get("file_exists", False)
    start_time = result_data.get("task_start_time", 0)
    file_mtime = result_data.get("file_mtime", 0)

    # --- 2. Programmatic File checks ---
    if file_exists:
        if file_mtime >= start_time:
            score += 15
            feedback_parts.append("Target file saved successfully")
        else:
            feedback_parts.append("File exists but was not created during this task session")
            
        # Copy the actual .ng3 file to inspect contents
        temp_ng3 = tempfile.NamedTemporaryFile(delete=False, suffix='.ng3')
        file_content = ""
        try:
            copy_from_env("/tmp/agent_output.ng3", temp_ng3.name)
            with open(temp_ng3.name, 'r', encoding='utf-8', errors='ignore') as f:
                file_content = f.read()
        except Exception as e:
            logger.warning(f"Could not read .ng3 file: {e}")
        finally:
            if os.path.exists(temp_ng3.name):
                os.unlink(temp_ng3.name)

        # Parse file contents (Energy3D ng3 is a JSON format)
        city_correct = False
        trackers_correct = False
        
        try:
            data = json.loads(file_content)
            # Check City
            if data.get("City", "").lower() == "phoenix":
                city_correct = True
                
            # Check Trackers on Solar Racks
            components = data.get("components", [])
            racks = [c for c in components if c.get("type") == "Solar Rack"]
            if racks:
                # In Energy3D, tracker 0 = None, 1 = Horizontal Single Axis
                # We check if they have been updated from 0 to > 0 (tracking enabled)
                # Ensure all or the vast majority of racks have tracking enabled
                tracked_racks = [r for r in racks if r.get("Tracker", 0) > 0]
                if len(tracked_racks) >= (len(racks) * 0.8):
                    trackers_correct = True
        except json.JSONDecodeError:
            # Fallback to regex text search if JSON is malformed or slightly custom
            logger.info("Falling back to regex parsing of .ng3 file")
            if re.search(r'"City"\s*:\s*"Phoenix"', file_content, re.IGNORECASE):
                city_correct = True
            
            # Check if tracker property is set to > 0 (1, 2, or 3)
            # Find all tracker assignments
            tracker_matches = re.findall(r'"Tracker"\s*:\s*([0-9]+)', file_content, re.IGNORECASE)
            if tracker_matches:
                tracked = sum(1 for m in tracker_matches if int(m) > 0)
                if tracked >= (len(tracker_matches) * 0.8) and tracked > 0:
                    trackers_correct = True

        if city_correct:
            score += 25
            feedback_parts.append("Location changed to Phoenix")
        else:
            feedback_parts.append("Location not set to Phoenix")
            
        if trackers_correct:
            score += 30
            feedback_parts.append("Solar racks upgraded to use trackers")
        else:
            feedback_parts.append("Solar racks do not have trackers enabled")
    else:
        feedback_parts.append("Target file 'phoenix_hsat_array.ng3' not found")

    # --- 3. VLM Trajectory Verification ---
    vlm_score = 0
    if vlm_query_func and file_exists:
        try:
            frames = sample_trajectory_frames(traj, n=6)
            final_img = get_final_screenshot(traj)
            if final_img:
                frames.append(final_img)
                
            if frames:
                vlm_result = vlm_query_func(prompt=VLM_PROMPT, images=frames)
                if vlm_result and vlm_result.get("success"):
                    parsed = vlm_result.get("parsed", {})
                    
                    if parsed.get("yield_analysis_executed", False):
                        vlm_score += 20
                        feedback_parts.append("Annual Yield Analysis execution confirmed")
                    else:
                        feedback_parts.append("No evidence of Annual Yield Analysis execution")
                        
                    if parsed.get("gui_used_legitimately", False):
                        vlm_score += 10
                        feedback_parts.append("GUI usage verified")
                    else:
                        feedback_parts.append("Legitimate GUI workflow not detected")
                else:
                    feedback_parts.append("VLM evaluation failed")
        except Exception as e:
            logger.error(f"VLM verification error: {e}")
            feedback_parts.append("VLM verification encountered an error")
            
    score += vlm_score

    # Determine final outcome
    # Threshold is 70, must have saved the file AND either changed city or trackers
    key_criteria_met = file_exists and (city_correct or trackers_correct)
    passed = score >= 70 and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }