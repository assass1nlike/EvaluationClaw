#!/usr/bin/env python3
"""
Verifier for Agricultural Solar Seasonal Optimization.

Combines programmatic checks (file timestamps, report parsing, binary string extraction)
with VLM trajectory verification to ensure robust, anti-gaming evaluation.
"""

import os
import json
import re
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating a user's workflow in the Energy3D application.
Please review these screenshots representing the user's progress and final state.

Analyze the sequence and determine:
1. Did the user open and view a "Monthly Yield" or "Annual Yield" graph during the process? (Look for a bar chart showing energy production over 12 months).
2. Does the scene show a large ground-mounted solar panel array (looks like a foundation with many solar panels arranged in rows/columns)?

Respond strictly in JSON format with boolean values and a brief reasoning:
{
    "viewed_yield_graph": true/false,
    "array_visible": true/false,
    "reasoning": "Brief explanation of what is visible in the frames"
}
"""

def verify_solar_optimization(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env or not query_vlm:
        return {"passed": False, "score": 0, "feedback": "Required framework functions not available."}

    metadata = task_info.get('metadata', {})
    opt_min = metadata.get('optimal_tilt_min', 5.0)
    opt_max = metadata.get('optimal_tilt_max', 20.0)
    annual_min = metadata.get('annual_default_tilt_min', 25.0)
    annual_max = metadata.get('annual_default_tilt_max', 45.0)

    score = 0
    feedback_parts = []
    
    # --- 1. Programmatic Data Extraction ---
    temp_dir = tempfile.mkdtemp()
    result_json = os.path.join(temp_dir, 'result.json')
    report_txt = os.path.join(temp_dir, 'report.txt')
    strings_txt = os.path.join(temp_dir, 'strings.txt')
    
    try:
        copy_from_env("/tmp/task_result.json", result_json)
        with open(result_json, 'r') as f:
            result = json.load(f)
            
        copy_from_env("/tmp/agent_report.txt", report_txt)
        with open(report_txt, 'r') as f:
            report_content = f.read().strip()
            
        copy_from_env("/tmp/ng3_strings.txt", strings_txt)
        with open(strings_txt, 'r') as f:
            ng3_strings = f.read()
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to extract files from container: {e}"}
        
    # --- 2. Evaluate File Creation & String Evidence ---
    if result.get('ng3_created_during_task', False):
        score += 15
        feedback_parts.append("Project file created during task (+15)")
    else:
        feedback_parts.append("Project file NOT saved or pre-dates task start")
        
    # Check if Sacramento is in the binary strings (confirms location configuration)
    if "Sacramento" in ng3_strings or "CA" in ng3_strings:
        score += 10
        feedback_parts.append("Location set to Sacramento (+10)")
    else:
        feedback_parts.append("Sacramento location not found in save file")

    # --- 3. Parse Optimization Report ---
    if result.get('report_exists', False) and report_content:
        score += 10
        feedback_parts.append("Report created (+10)")
        
        # Extract all numbers from the report
        numbers = re.findall(r'\b\d+(?:\.\d+)?\b', report_content)
        floats = [float(n) for n in numbers]
        
        # Check if the chosen tilt angle falls into our ranges
        optimized = False
        defaulted = False
        
        for val in floats:
            if opt_min <= val <= opt_max:
                optimized = True
            if annual_min <= val <= annual_max:
                defaulted = True
                
        if optimized:
            score += 35
            feedback_parts.append("Summer seasonal optimization angle found (5-20 deg) (+35)")
        elif defaulted:
            # Penalize: Agent fell back to latitude tilt / annual optimum instead of reading the prompt
            feedback_parts.append("Found annual optimum angle (~30-40 deg). Agent failed to optimize for summer season.")
        else:
            feedback_parts.append(f"No valid optimal angle found in report. Numbers found: {floats}")
    else:
        feedback_parts.append("Optimization report missing or empty")

    # --- 4. VLM Trajectory Verification ---
    # Sample trajectory frames + final screenshot to check workflow
    try:
        from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
        frames = sample_trajectory_frames(traj, n=4)
        final_img = get_final_screenshot(traj)
        if final_img:
            frames.append(final_img)
            
        if frames:
            vlm_response = query_vlm(prompt=VLM_PROMPT, images=frames)
            if vlm_response.get("success"):
                vlm_data = vlm_response.get("parsed", {})
                
                if vlm_data.get("array_visible"):
                    score += 10
                    feedback_parts.append("VLM: Large array visually confirmed (+10)")
                else:
                    feedback_parts.append("VLM: Solar array not visible")
                    
                if vlm_data.get("viewed_yield_graph"):
                    score += 20
                    feedback_parts.append("VLM: Yield graph analysis workflow confirmed (+20)")
                else:
                    feedback_parts.append("VLM: Yield graph analysis not observed")
            else:
                feedback_parts.append("VLM query failed")
    except Exception as e:
        logger.error(f"VLM verification error: {e}")
        feedback_parts.append("VLM verification encountered an error")

    # --- 5. Final Evaluation ---
    # To pass, they must score >= 70 AND have created the file AND found the summer optimum
    key_criteria_met = result.get('ng3_created_during_task', False) and optimized
    passed = (score >= 70) and key_criteria_met

    if not passed and score >= 70:
        feedback_parts.append("FAILED: Key criteria missing (must save file AND report a summer-optimized angle 5-20 deg).")

    return {
        "passed": bool(passed),
        "score": min(score, 100),
        "feedback": " | ".join(feedback_parts)
    }