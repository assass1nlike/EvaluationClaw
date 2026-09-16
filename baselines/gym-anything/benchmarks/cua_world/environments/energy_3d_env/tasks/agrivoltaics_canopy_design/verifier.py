#!/usr/bin/env python3
"""
Verifier for Agrivoltaics Canopy Design task.
Evaluates if the agent saved the modified project with correct parameters (3.5m pole, 20° tilt) 
and exported the yield analysis CSV. Uses a hybrid approach: inspects saved data files 
programmatically and uses VLM trajectory analysis as a visual fallback and workflow confirmation.
"""

import json
import os
import re
import tempfile
import logging
from typing import Dict, Any

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an AI agent performing an agrivoltaics solar design task in Energy3D.
The agent was asked to:
1. Elevate the solar panel racks to a Pole Height of 3.5m (they should appear very tall, leaving ample space for tractors underneath).
2. Change the Tilt Angle to 20 degrees (the panels should look flatter than a typical steep array).
3. Run a "Daily Yield" analysis via the top menu.

Review the sequence of trajectory frames leading up to the final state.
Respond in JSON format:
{
    "panels_elevated": true/false,
    "tilt_angle_flatter": true/false,
    "yield_analysis_run": true/false,
    "reasoning": "brief explanation of your visual findings"
}"""


def verify_agrivoltaics_design(traj: Dict[str, Any], env_info: Dict[str, Any], task_info: Dict[str, Any]) -> Dict[str, Any]:
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Verifier error: copy_from_env not available."}

    # 1. Fetch JSON result exported by export_result.sh
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read exported results: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    proj_exists = result.get("proj_exists", False)
    proj_new = result.get("proj_new", False)
    proj_size = result.get("proj_size", 0)
    
    csv_exists = result.get("csv_exists", False)
    csv_new = result.get("csv_new", False)
    csv_lines = result.get("csv_lines", 0)

    # 2. Inspect the saved .ng3 project file for expected physical parameters
    # Energy3D .ng3 files are typically JSON-structured
    pole_height_found = False
    tilt_angle_found = False
    
    if proj_exists and proj_size > 500:
        ng3_temp = tempfile.NamedTemporaryFile(delete=False, suffix='.ng3')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/agrivoltaics_array.ng3", ng3_temp.name)
            with open(ng3_temp.name, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                # Use regex to find parameter values flexibly
                if re.search(r'"poleHeight"\s*:\s*3\.5', content) or re.search(r'"Pole Height"\s*:\s*3\.5', content):
                    pole_height_found = True
                if re.search(r'"tiltAngle"\s*:\s*20', content) or re.search(r'"Tilt Angle"\s*:\s*20', content):
                    tilt_angle_found = True
        except Exception as e:
            logger.warning(f"Failed to inspect .ng3 file contents: {e}")
        finally:
            if os.path.exists(ng3_temp.name):
                os.unlink(ng3_temp.name)

    # 3. Hybrid VLM Verification (Fallback for parameters & Confirmation for workflow)
    vlm_panels_elevated = False
    vlm_tilt_angle_flatter = False
    vlm_yield_analysis_run = False
    
    if query_vlm:
        frames = sample_trajectory_frames(traj, n=4)
        final_frame = get_final_screenshot(traj)
        if final_frame:
            frames.append(final_frame)
            
        vlm_res = query_vlm(images=frames, prompt=VLM_PROMPT)
        if vlm_res and vlm_res.get("success"):
            parsed = vlm_res.get("parsed", {})
            vlm_panels_elevated = parsed.get("panels_elevated", False)
            vlm_tilt_angle_flatter = parsed.get("tilt_angle_flatter", False)
            vlm_yield_analysis_run = parsed.get("yield_analysis_run", False)
            logger.info(f"VLM reasoning: {parsed.get('reasoning', '')}")
            
    # 4. Scoring Logic
    score = 0
    feedback = []

    # Criterion A: Modified project file saved (20 pts)
    if proj_exists and proj_new and proj_size > 500:
        score += 20
        feedback.append("✅ Modified project saved successfully.")
    elif proj_exists and not proj_new:
        feedback.append("❌ Project file exists but was not modified during this session.")
    else:
        feedback.append("❌ Project 'agrivoltaics_array.ng3' not saved.")

    # Criterion B: Yield CSV Exported (20 pts)
    if csv_exists and csv_new and csv_lines >= 3:
        score += 20
        feedback.append(f"✅ Yield CSV exported successfully ({csv_lines} rows).")
    elif csv_exists and not csv_new:
        feedback.append("❌ CSV exists but was not exported during this session.")
    elif csv_exists and csv_lines < 3:
        feedback.append("❌ CSV exists but appears to be empty/missing data.")
    else:
        feedback.append("❌ Yield CSV 'agrivoltaics_yield.csv' not exported.")

    # Criterion C: Pole Height Adjusted (25 pts)
    if pole_height_found:
        score += 25
        feedback.append("✅ Pole height of 3.5m confirmed in project file data.")
    elif vlm_panels_elevated:
        score += 25
        feedback.append("✅ VLM visually confirmed panels were elevated.")
    else:
        feedback.append("❌ Pole height adjustment to 3.5m not detected.")

    # Criterion D: Tilt Angle Adjusted (15 pts)
    if tilt_angle_found:
        score += 15
        feedback.append("✅ Tilt angle of 20° confirmed in project file data.")
    elif vlm_tilt_angle_flatter:
        score += 15
        feedback.append("✅ VLM visually confirmed tilt angle adjustment.")
    else:
        feedback.append("❌ Tilt angle adjustment to 20° not detected.")

    # Criterion E: Yield Analysis Run - Workflow confirmation (20 pts)
    if vlm_yield_analysis_run:
        score += 20
        feedback.append("✅ VLM confirmed yield analysis window was opened/run.")
    else:
        # Give partial credit if the CSV exists but VLM failed to catch the fast UI window
        if csv_exists and csv_new and csv_lines >= 3:
            score += 20
            feedback.append("✅ Yield analysis run inferred implicitly via valid CSV export.")
        else:
            feedback.append("❌ Yield analysis execution not detected visually.")

    # Ensure max score caps at 100
    score = min(score, 100)
    
    # Pass threshold: must have adjusted parameters and saved at least one required output
    passed = score >= 70 and (proj_exists or csv_exists)

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback)
    }