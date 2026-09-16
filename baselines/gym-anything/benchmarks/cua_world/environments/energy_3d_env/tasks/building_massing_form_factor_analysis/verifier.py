#!/usr/bin/env python3
"""
Verifier for Building Massing Form Factor Energy Analysis task.
Uses a hybrid programmatic (text file parsing) and VLM (trajectory validation) approach.
"""

import json
import os
import re
import tempfile
import logging

# Standard VLM utilities from the framework
try:
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
except ImportError:
    # Fallback/stubs if running outside the framework for local testing
    def sample_trajectory_frames(traj, n=5): return []
    def get_final_screenshot(traj): return ""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying if an agent successfully performed an energy analysis workflow in Energy3D.
Review these frames from the agent's trajectory and determine if the following events occurred.

Look for:
1. location_set_to_chicago: Did the agent set the location/city to "Chicago" (either in a dialog box or visible in a UI bar)?
2. u_value_modified: Did the agent open a properties panel or dialog and set a Wall U-Value to "0.3"?
3. analysis_executed: Is there a graph/chart window shown indicating an "Annual Energy Analysis" or building simulation was run?

Respond ONLY in valid JSON format:
{
    "location_set_to_chicago": true/false,
    "u_value_modified": true/false,
    "analysis_executed": true/false
}
"""

def verify_massing_analysis(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "System error: copy_from_env not available"}

    # ================================================================
    # 1. Read JSON result from the environment
    # ================================================================
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to parse result from environment: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    score = 0
    feedback_parts = []
    
    report_exists = result.get('report_exists', False)
    report_valid_time = result.get('report_created_during_task', False)
    content = result.get('report_content', '').lower()

    # ================================================================
    # 2. Programmatic File Checks (60 pts total)
    # ================================================================
    file_passed = False
    
    if not report_exists:
        feedback_parts.append("Report file not found")
        return {"passed": False, "score": 0, "feedback": "Failed: The report file was not created."}
    
    if not report_valid_time:
        feedback_parts.append("Report existed before task (possible cheating)")
        return {"passed": False, "score": 0, "feedback": "Failed: Report file timestamp predates task."}

    score += 10
    feedback_parts.append("Report file created")

    # Parameter Logging (10 pts)
    has_chicago = 'chicago' in content
    has_u_value = '0.3' in content
    if has_chicago and has_u_value:
        score += 10
        feedback_parts.append("Parameters logged (Chicago, 0.3)")
    else:
        feedback_parts.append(f"Missing parameters in text (Chicago={has_chicago}, U-Value={has_u_value})")

    # Values Reported (20 pts)
    # Looking for at least two numbers greater than 1000 (typical kWh for an entire building)
    numbers = re.findall(r'\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b', content.replace(',', ''))
    large_numbers = [float(n) for n in numbers if float(n) > 500]
    
    if len(large_numbers) >= 2:
        score += 20
        feedback_parts.append("Two numeric kWh values reported")
    elif len(large_numbers) == 1:
        score += 10
        feedback_parts.append("Only one valid numeric value reported")
    else:
        feedback_parts.append("No valid kWh values found in report")

    # Correct Conclusion (20 pts)
    # We look for context clues stating compact is better/more efficient.
    # We accept variations showing 'compact' is 'efficient', 'better', 'lower', 'winner', etc.
    if 'compact' in content and ('efficient' in content or 'lower' in content or 'better' in content or 'less' in content):
        score += 20
        feedback_parts.append("Correct conclusion (Compact is more efficient)")
        file_passed = True
    else:
        feedback_parts.append("Could not find correct logical conclusion linking 'compact' to higher efficiency/lower energy.")

    # ================================================================
    # 3. VLM Trajectory Checks (40 pts total)
    # ================================================================
    vlm_passed = False
    
    if query_vlm:
        frames = sample_trajectory_frames(traj, n=6)
        final = get_final_screenshot(traj)
        images = frames + [final] if final else frames
        
        if not images:
            feedback_parts.append("No images available for VLM verification")
        else:
            vlm_res = query_vlm(prompt=VLM_PROMPT, images=images)
            if vlm_res.get('success'):
                parsed = vlm_res.get('parsed', {})
                
                loc_set = parsed.get('location_set_to_chicago', False)
                u_mod = parsed.get('u_value_modified', False)
                sim_run = parsed.get('analysis_executed', False)
                
                if loc_set:
                    score += 10
                    feedback_parts.append("VLM confirmed location change")
                if u_mod:
                    score += 15
                    feedback_parts.append("VLM confirmed U-value modification")
                if sim_run:
                    score += 15
                    feedback_parts.append("VLM confirmed simulation executed")
                    vlm_passed = True
            else:
                feedback_parts.append("VLM verification failed to process")
    else:
        feedback_parts.append("VLM tool unavailable, skipping visual checks")

    # ================================================================
    # 4. Final Scoring
    # ================================================================
    # To pass, the file MUST draw the correct conclusion AND the VLM MUST confirm the analysis was actually run.
    is_passing = (score >= 70) and file_passed and vlm_passed

    return {
        "passed": is_passing,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }