#!/usr/bin/env python3
"""
Verifier for desert_solar_temp_coefficient_upgrade task.

Since Energy3D .ng3 files are binary-serialized objects (or complex XStream XMLs), 
this verifier relies on:
1. File creation checks (was the new project saved? was the text report saved?)
2. Regex parsing of the text report to ensure a valid numeric yield is provided.
3. VLM trajectory verification to confirm the agent actually interacted with the 
   Energy3D UI to change the location, efficiency, temp coeff, and NOCT.
"""

import os
import json
import tempfile
import re
import logging

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent's performance in Energy3D.
The agent was asked to upgrade a solar array for a desert climate.

Review the provided screenshots from the agent's session and determine:
1. Location: Did the agent open the City/Location dialog and set it to Phoenix (or Phoenix, AZ)?
2. Efficiency: Did the agent open the solar panel properties and set the cell efficiency to 22% (or 0.22)?
3. Temp Coeff: Did the agent set the Temperature Coefficient of Pmax to -0.26 %/C?
4. NOCT: Did the agent set the Nominal Operating Cell Temperature (NOCT) to 43 C?
5. Analysis: Did the agent open and run the Annual Yield Analysis (indicated by a graph showing monthly energy generation)?

Respond strictly with a JSON object containing boolean values for these keys:
{
    "location_set_phoenix": true/false,
    "efficiency_set_22": true/false,
    "temp_coeff_set_neg026": true/false,
    "noct_set_43": true/false,
    "ran_annual_yield": true/false,
    "reasoning": "Brief explanation of evidence seen in the screenshots"
}
"""

def verify_solar_upgrade(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available."}
    if not query_vlm:
        return {"passed": False, "score": 0, "feedback": "VLM querying is required for this task's verification."}

    # Extract JSON results from environment
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to load task result JSON: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    score = 0
    max_score = 100
    feedback_parts = []
    
    # 1. Output File check (10 pts)
    ng3_exists = result.get("output_ng3_exists", False)
    ng3_created = result.get("output_ng3_created_during_task", False)
    
    if ng3_exists and ng3_created:
        score += 10
        feedback_parts.append("✅ Project saved successfully")
    elif ng3_exists:
        score += 5
        feedback_parts.append("⚠️ Project exists but timestamps indicate it may be stale")
    else:
        feedback_parts.append("❌ hjt_upgrade_phoenix.ng3 not found")

    # 2. Yield Report check (30 pts)
    report_exists = result.get("report_exists", False)
    report_created = result.get("report_created_during_task", False)
    report_content = result.get("report_content", "")
    
    yield_reported_valid = False
    if report_exists and report_created:
        # Look for numbers in the report content
        numbers = re.findall(r'\d+(?:[.,]\d+)?', report_content)
        if numbers:
            try:
                # Strip commas and check if there's a reasonably large number (kW/kWh output usually > 100)
                vals = [float(n.replace(',', '')) for n in numbers]
                if any(v > 100 for v in vals):
                    yield_reported_valid = True
                    score += 30
                    feedback_parts.append("✅ Yield report contains valid generation data")
                else:
                    score += 15
                    feedback_parts.append("⚠️ Yield report found, but no large numbers (kWh) detected")
            except ValueError:
                score += 10
                feedback_parts.append("⚠️ Yield report found but numbers could not be parsed")
        else:
            score += 10
            feedback_parts.append("⚠️ Yield report found but no numbers detected inside")
    else:
        feedback_parts.append("❌ yield_report.txt not found or stale")

    # 3. VLM Verification of UI actions (60 pts total)
    frames = sample_trajectory_frames(traj, n=5)
    final_frame = get_final_screenshot(traj)
    images_to_check = frames + ([final_frame] if final_frame else [])
    
    vlm_result = query_vlm(prompt=VLM_PROMPT, images=images_to_check)
    
    if vlm_result.get("success"):
        parsed = vlm_result.get("parsed", {})
        
        # Location (15 pts)
        if parsed.get("location_set_phoenix", False):
            score += 15
            feedback_parts.append("✅ Location set to Phoenix")
        else:
            feedback_parts.append("❌ Location change not verified")
            
        # Efficiency (15 pts)
        if parsed.get("efficiency_set_22", False):
            score += 15
            feedback_parts.append("✅ Efficiency set to 22%")
        else:
            feedback_parts.append("❌ Efficiency change not verified")
            
        # Temp Coeff (15 pts)
        if parsed.get("temp_coeff_set_neg026", False):
            score += 15
            feedback_parts.append("✅ Temp coefficient set correctly")
        else:
            feedback_parts.append("❌ Temp coefficient change not verified")
            
        # NOCT (5 pts)
        if parsed.get("noct_set_43", False):
            score += 5
            feedback_parts.append("✅ NOCT set correctly")
        else:
            feedback_parts.append("❌ NOCT change not verified")
            
        # Run Analysis (10 pts)
        if parsed.get("ran_annual_yield", False):
            score += 10
            feedback_parts.append("✅ Annual Yield Analysis confirmed run")
        else:
            feedback_parts.append("❌ Annual Yield Analysis not observed")
    else:
        feedback_parts.append(f"⚠️ VLM query failed: {vlm_result.get('error', 'Unknown error')}")

    # Pass threshold: 70 points AND must have a valid yield reported
    passed = score >= 70 and yield_reported_valid
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }