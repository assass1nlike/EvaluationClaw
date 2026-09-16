#!/usr/bin/env python3
"""
Verifier for winter_solstice_tilt_optimization.

Combines programmatic file/content checks with trajectory-based VLM verification
to confirm spatial and UI state changes that cannot easily be parsed from
binary .ng3 files.
"""

import json
import os
import re
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent's completion of a solar energy optimization task in Energy3D.
The goal was to adjust the solar panel array's tilt angle for maximum daily yield on the Winter Solstice (December 21).

Look closely at the sequence of trajectory frames and the final screenshot provided.

Determine the following:
1. DATE_SET: Did the agent change the simulation date to December 21 (or late December)? Look at the date slider or text indicator usually in the top toolbar or UI overlay.
2. ANALYSIS_RUN: Is there evidence that the agent opened an analysis tool or ran an optimization? Look for a 'Daily Yield Analysis' graph window, an optimization dialog, or similar analytic popup during the trajectory frames.
3. PANELS_TILTED: In the final view, are the solar panels visibly, steeply tilted? (Winter optimization in the northern hemisphere requires a steep tilt, typically 55-75 degrees, compared to a flatter summer tilt).

Respond strictly in valid JSON format:
{
    "date_set_to_december": true/false,
    "analysis_was_run": true/false,
    "panels_steeply_tilted": true/false,
    "reasoning": "brief explanation of what you observed"
}
"""

def extract_number(text):
    """Safely extract the first sequence of digits/decimals from a string."""
    if not text:
        return None
    match = re.search(r'\d+\.?\d*', text)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None

def verify_winter_tilt_optimization(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    metadata = task_info.get('metadata', {})
    min_angle = metadata.get('min_winter_angle', 50)
    max_angle = metadata.get('max_winter_angle', 80)

    score = 0
    feedback_parts = []
    
    # 1. Retrieve programmatic results
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read exported result: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    # 2. Check output files existence & timestamps (Anti-gaming)
    ng3_exists = result.get('ng3_exists', False)
    ng3_created = result.get('ng3_created_during_task', False)
    report_exists = result.get('report_exists', False)
    report_created = result.get('report_created_during_task', False)

    file_pts = 0
    if ng3_exists and ng3_created:
        file_pts += 10
        feedback_parts.append("Project saved properly.")
    elif ng3_exists:
        feedback_parts.append("Project saved but timestamp predates task start (invalid).")

    if report_exists and report_created:
        file_pts += 10
        feedback_parts.append("Report created properly.")
    elif report_exists:
        feedback_parts.append("Report created but timestamp predates task start (invalid).")
    
    score += file_pts

    # 3. Parse report content
    if report_exists and report_created:
        angle_val = extract_number(result.get('report_line_1', ''))
        yield_val = extract_number(result.get('report_line_2', ''))
        
        # Check Angle
        if angle_val is not None:
            if min_angle <= angle_val <= max_angle:
                score += 20
                feedback_parts.append(f"Report angle {angle_val} deg is optimal for winter.")
            else:
                score += 5
                feedback_parts.append(f"Report angle {angle_val} deg is not in optimal winter range ({min_angle}-{max_angle}).")
        else:
            feedback_parts.append("Could not parse angle from report line 1.")

        # Check Yield
        if yield_val is not None and yield_val > 0:
            score += 10
            feedback_parts.append(f"Report yield valid (>0).")
        else:
            feedback_parts.append("Could not parse valid positive yield from report line 2.")

    # 4. VLM Verification for UI actions and Visual State
    query_vlm = env_info.get('query_vlm')
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
    
    frames = []
    try:
        frames = sample_trajectory_frames(traj, n=4)
        final = get_final_screenshot(traj)
        if final:
            frames.append(final)
    except Exception as e:
        logger.warning(f"Error sampling frames: {e}")
        
    vlm_success = False
    if query_vlm and frames:
        vlm_result = query_vlm(prompt=VLM_PROMPT, images=frames)
        if vlm_result.get("success"):
            parsed = vlm_result.get("parsed", {})
            vlm_success = True
            
            if parsed.get("date_set_to_december", False):
                score += 15
                feedback_parts.append("VLM confirmed date set to Dec.")
            else:
                feedback_parts.append("VLM: Date not clearly set to Dec.")
                
            if parsed.get("analysis_was_run", False):
                score += 15
                feedback_parts.append("VLM confirmed analysis execution.")
            else:
                feedback_parts.append("VLM: Analysis tool usage not seen.")
                
            if parsed.get("panels_steeply_tilted", False):
                score += 20
                feedback_parts.append("VLM confirmed steep panel tilt.")
            else:
                feedback_parts.append("VLM: Panels do not appear steeply tilted.")
        else:
            feedback_parts.append(f"VLM query failed: {vlm_result.get('error')}")
    else:
        feedback_parts.append("VLM verification skipped (no capability or frames).")

    # Evaluate passing conditions
    # Requires core files created + angle in valid range + at least some VLM visual confirmation
    critical_files = ng3_exists and ng3_created and report_exists and report_created
    passed = score >= 70 and critical_files

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }