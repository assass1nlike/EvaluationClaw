#!/usr/bin/env python3
"""
Verifier for HVAC Thermostat Setback Savings task.

Multi-Criteria Verification:
1. File Checks (25 pts): Ensure both the new `.ng3` model and `.txt` report were created during the task timeframe.
2. Math Validation (25 pts): Programmatically parse the agent's text report to verify calculations (Baseline - Eco = Savings, and correct percentage).
3. Trajectory VLM (50 pts): Verify visual progression (Setting Boston location, adjusting Thermostat to 18/26, running Annual Energy Analysis).
"""

import json
import tempfile
import os
import re
import logging

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent's performance on an Energy3D building simulation task.
TASK: The agent must set the location to 'Boston, MA', adjust the thermostat (Heating to 18°C, Cooling to 26°C), and run the Annual Building Energy Analysis.

Analyze these trajectory frames (and the final screenshot) to verify the workflow.

Look closely for:
1. Did the agent open the Location/City dialog and set it to 'Boston, MA'?
2. Did the agent open the Thermostat settings and adjust the Heating setpoint to 18 and Cooling setpoint to 26?
3. Did the agent run the "Annual Building Energy Analysis" at least once? (Evidence: a graph window with monthly heating/cooling/net energy use).

Provide your response in JSON format:
{
    "set_boston": true/false,
    "set_thermostat": true/false,
    "ran_analysis": true/false,
    "reasoning": "brief step-by-step reasoning"
}
"""

def verify_hvac_thermostat_setback_savings(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available."}

    score = 0
    feedback_parts = []
    
    # 1. Retrieve the exported JSON result
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

    task_start = result.get('task_start', 0)
    
    # 2. Evaluate File Creation & Timestamps (25 pts)
    ng3_created = result.get('ng3_exists') and result.get('ng3_mtime', 0) >= task_start
    report_created = result.get('report_exists') and result.get('report_mtime', 0) >= task_start

    if ng3_created:
        score += 15
        feedback_parts.append("eco_building.ng3 saved.")
    else:
        feedback_parts.append("eco_building.ng3 not found or not modified.")

    if report_created:
        score += 10
        feedback_parts.append("thermostat_savings_report.txt saved.")
    else:
        feedback_parts.append("thermostat_savings_report.txt not found or not modified.")

    # 3. Math Validation (25 pts)
    # Extracts numbers and strictly verifies mathematical logic without enforcing strict text formats
    math_valid = False
    found_b, found_e, found_s, found_p = 0, 0, 0, 0
    report_content = result.get('report_content', '')

    if result.get('report_exists') and len(report_content) > 0:
        # Strip commas to safely parse thousands (e.g. 15,000 -> 15000)
        text_clean = report_content.replace(',', '')
        numbers = [float(x) for x in re.findall(r"[-+]?\d*\.\d+|\d+", text_clean)]
        
        # Greedy search for a valid mathematical relationship representing the energy analysis
        if len(numbers) >= 4:
            for b in numbers:
                for e in numbers:
                    if b <= e or b == 0: continue
                    for s in numbers:
                        if abs((b - e) - s) < 5.0:  # Allow minor rounding in manual transcription
                            for p in numbers:
                                if abs((s / b * 100) - p) < 2.0:
                                    math_valid = True
                                    found_b, found_e, found_s, found_p = b, e, s, p
                                    break
                            if math_valid: break
                    if math_valid: break
                if math_valid: break

        if math_valid:
            score += 25
            feedback_parts.append(f"Report math valid (Base: {found_b}, Eco: {found_e}, Sav: {found_s}).")
        else:
            feedback_parts.append("Report math invalid or missing expected calculations.")

    # 4. VLM Trajectory Verification (50 pts)
    if query_vlm:
        frames = sample_trajectory_frames(traj, n=6)
        final_img = get_final_screenshot(traj)
        images = frames + [final_img] if final_img else frames
        
        vlm_res = query_vlm(prompt=VLM_PROMPT, images=images)
        
        if vlm_res and vlm_res.get('success'):
            parsed = vlm_res.get('parsed', {})
            
            if parsed.get('set_boston'):
                score += 10
                feedback_parts.append("VLM confirmed location set to Boston.")
            else:
                feedback_parts.append("VLM did not observe Location change.")
                
            if parsed.get('set_thermostat'):
                score += 20
                feedback_parts.append("VLM confirmed thermostat adjusted.")
            else:
                feedback_parts.append("VLM did not observe Thermostat adjustment.")
                
            if parsed.get('ran_analysis'):
                score += 20
                feedback_parts.append("VLM confirmed Annual Analysis execution.")
            else:
                feedback_parts.append("VLM did not observe Energy Analysis execution.")
        else:
            feedback_parts.append("VLM query failed.")
    else:
        feedback_parts.append("VLM verification skipped (not available).")

    # Final Evaluation
    # Must achieve at least 70 points AND have valid math AND have created the output files
    passed = score >= 70 and ng3_created and math_valid

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts),
        "details": {
            "math_valid": math_valid,
            "ng3_created": ng3_created,
            "report_created": report_created
        }
    }