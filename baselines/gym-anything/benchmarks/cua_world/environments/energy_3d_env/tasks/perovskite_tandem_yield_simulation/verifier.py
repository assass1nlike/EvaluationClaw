#!/usr/bin/env python3
"""
Verifier for perovskite_tandem_yield_simulation task.
Uses a hybrid programmatic (file checks) and VLM (trajectory validation) approach.
"""

import json
import os
import re
import tempfile
import logging
from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an AI agent's performance in Energy3D.
The agent was asked to modify a solar array's properties to simulate a high-efficiency tandem cell and run an annual yield analysis.

Please review these trajectory frames and the final screenshot and determine if the following actions occurred:
1. Did the agent open the properties/specifications for the solar panel array and set the 'Cell Efficiency' to 29% (or 0.29)?
2. Did the agent set the 'Temperature Coefficient of Pmax' to -0.20?
3. Did the agent set the 'Nominal Operating Cell Temp (NOCT)' to 40?
4. Did the agent run an 'Annual Yield' (or Daily Yield) Analysis, producing a visible simulation graph?

Respond in the following JSON format:
{
    "efficiency_set": true/false,
    "temp_coeff_set": true/false,
    "noct_set": true/false,
    "analysis_run": true/false,
    "reasoning": "brief explanation"
}
"""

def verify_perovskite_tandem_yield_simulation(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # 1. Read Programmatic Artifacts
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read task result: {str(e)}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    # 2. Score File Outputs (40 points max)
    if result.get("project_exists") and result.get("project_modified_during_task"):
        score += 20
        feedback_parts.append("Project file saved correctly")
    elif result.get("project_exists"):
        score += 10
        feedback_parts.append("Project file exists but may not have been modified")
    else:
        feedback_parts.append("Project file not saved")

    if result.get("graph_exists"):
        score += 10
        feedback_parts.append("Graph screenshot saved")
    else:
        feedback_parts.append("Graph screenshot missing")

    if result.get("report_exists"):
        content = result.get("report_content", "")
        # Extract any numbers from the report string
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", content)
        if numbers:
            # Just check if *some* valid numerical yield was extracted
            val = float(numbers[0])
            if val > 0:
                score += 10
                feedback_parts.append(f"Yield report contains value ({val})")
            else:
                feedback_parts.append("Yield report numeric value invalid/zero")
        else:
            feedback_parts.append("Yield report created but no numeric value found")
    else:
        feedback_parts.append("Yield report missing")

    # 3. Score VLM Trajectory (60 points max)
    vlm_passed_critical = False
    if query_vlm:
        frames = sample_trajectory_frames(traj, n=8)
        final_img = get_final_screenshot(traj)
        images = frames + [final_img] if final_img else frames

        if images:
            vlm_result = query_vlm(prompt=VLM_PROMPT, images=images)
            
            if vlm_result and vlm_result.get("success"):
                parsed = vlm_result.get("parsed", {})
                
                if parsed.get("efficiency_set"):
                    score += 20
                    feedback_parts.append("VLM: Efficiency updated to 29%")
                    vlm_passed_critical = True
                else:
                    feedback_parts.append("VLM: Efficiency change not detected")

                if parsed.get("temp_coeff_set"):
                    score += 10
                    feedback_parts.append("VLM: Temp Coeff updated to -0.20")
                else:
                    feedback_parts.append("VLM: Temp Coeff change not detected")

                if parsed.get("noct_set"):
                    score += 10
                    feedback_parts.append("VLM: NOCT updated to 40")
                else:
                    feedback_parts.append("VLM: NOCT change not detected")

                if parsed.get("analysis_run"):
                    score += 20
                    feedback_parts.append("VLM: Yield analysis was run")
                else:
                    feedback_parts.append("VLM: Yield analysis not detected")
            else:
                feedback_parts.append("VLM query failed or returned invalid response")
        else:
            feedback_parts.append("No trajectory images available for VLM")
    else:
        feedback_parts.append("VLM not configured in environment")

    # Pass threshold: 70 points AND must have successfully set the efficiency
    passed = score >= 70 and vlm_passed_critical and result.get("project_exists")

    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback_parts)
    }