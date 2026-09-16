#!/usr/bin/env python3
"""
Verifier for the utility_solar_duck_curve_mitigation task.

Verification Strategy:
1. File Verification (10 pts): Check existence and modification timestamps of the three required files.
2. Report Content Parsing (30 pts): Parse `profile_comparison.txt` to find baseline vs new yield at 12:00 and 16:00.
3. Physics Logic Verification (20 pts): Verify `New 16:00 yield > Baseline 16:00 yield` and `New 12:00 yield < Baseline 12:00 yield`.
4. VLM Trajectory/Visual Verification (40 pts): Analyze the trajectory to ensure the user physically altered the array (split/rotated to E/S/W) and evaluate the graph screenshot for a flattened profile.
"""

import json
import os
import re
import tempfile
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_duck_curve_mitigation(traj: Dict[str, Any], env_info: Dict[str, Any], task_info: Dict[str, Any]) -> Dict[str, Any]:
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env or not query_vlm:
        return {"passed": False, "score": 0, "feedback": "Required framework functions (copy_from_env/query_vlm) not available."}

    score = 0
    feedback_parts = []
    
    # 1. Fetch the exported JSON results
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

    # 2. File Verification
    model = result.get('model_file', {})
    screenshot = result.get('screenshot_file', {})
    report = result.get('report_file', {})
    
    files_ok = True
    if model.get('exists') and model.get('created_during_task'):
        feedback_parts.append("✅ Model file saved")
    else:
        files_ok = False
        feedback_parts.append("❌ Model file missing or not modified")
        
    if screenshot.get('exists') and screenshot.get('created_during_task'):
        feedback_parts.append("✅ Screenshot saved")
    else:
        files_ok = False
        feedback_parts.append("❌ Screenshot missing or not modified")
        
    if report.get('exists') and report.get('created_during_task'):
        feedback_parts.append("✅ Report saved")
    else:
        files_ok = False
        feedback_parts.append("❌ Text report missing or not modified")

    if files_ok:
        score += 10

    # 3. Report Content Parsing & Physics Logic Verification
    report_content = result.get('report_content', '').lower()
    
    # We attempt to extract the 4 required numbers using regex
    # Looking for combinations of (baseline|new).*?(12|16).*?([0-9.]+)
    
    baseline_12 = None
    baseline_16 = None
    new_12 = None
    new_16 = None
    
    # Find baseline 12:00
    m_b12 = re.search(r'baseline.*?12.*?([0-9]+\.?[0-9]*)', report_content)
    if m_b12: baseline_12 = float(m_b12.group(1))
    
    # Find baseline 16:00
    m_b16 = re.search(r'baseline.*?16.*?([0-9]+\.?[0-9]*)', report_content)
    if m_b16: baseline_16 = float(m_b16.group(1))
    
    # Find new 12:00
    m_n12 = re.search(r'new.*?12.*?([0-9]+\.?[0-9]*)', report_content)
    if m_n12: new_12 = float(m_n12.group(1))
    
    # Find new 16:00
    m_n16 = re.search(r'new.*?16.*?([0-9]+\.?[0-9]*)', report_content)
    if m_n16: new_16 = float(m_n16.group(1))

    logic_passed = False
    if baseline_12 is not None and baseline_16 is not None and new_12 is not None and new_16 is not None:
        score += 20 # successfully parsed 4 values
        feedback_parts.append(f"✅ Parsed values (B12:{baseline_12}, B16:{baseline_16}, N12:{new_12}, N16:{new_16})")
        
        # Verify Physics logic
        if new_16 > baseline_16 and new_12 < baseline_12:
            score += 30
            logic_passed = True
            feedback_parts.append("✅ Profile flattening logic verified: 12:00 dropped and 16:00 boosted")
        else:
            feedback_parts.append("❌ Physics logic failed: New values don't show flattened duck curve profile")
    else:
        feedback_parts.append("❌ Could not parse all 4 required values from report")

    # 4. VLM Verification (Trajectory + User Screenshot)
    # Get the specific screenshot the agent saved if it exists, otherwise fall back to final
    vlm_images = []
    
    # Extract trajectory frames to see the array manipulation
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
    frames = sample_trajectory_frames(traj, n=4)
    vlm_images.extend(frames)
    
    if screenshot.get('exists'):
        temp_img = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/screenshot_daily_yield.png", temp_img.name)
            vlm_images.append(temp_img.name)
            has_explicit_screenshot = True
        except Exception:
            vlm_images.append(get_final_screenshot(traj))
            has_explicit_screenshot = False
    else:
        vlm_images.append(get_final_screenshot(traj))
        has_explicit_screenshot = False

    vlm_prompt = """You are a technical verifier reviewing a solar engineering task in Energy3D.
Task: The agent had to split a monolithic South-facing solar array into a multi-azimuth array (East, South, West) to flatten the daily yield profile.

Look at the trajectory frames and the Daily Yield graph screenshot. Determine:
1. array_manipulated: Did the agent physically split, duplicate, or rotate sections of the solar racks to face multiple directions (East/South/West) instead of leaving them all parallel?
2. curve_flattened: Does the Daily Yield graph show a widened/flattened curve (e.g., increased morning/evening shoulder hours with a relatively lower noon peak) rather than a single sharp peak?

Respond in JSON format:
{
    "array_manipulated": true/false,
    "curve_flattened": true/false,
    "reasoning": "brief explanation"
}
"""

    vlm_result = query_vlm(prompt=vlm_prompt, images=vlm_images)
    vlm_passed = False

    if vlm_result.get("success"):
        parsed = vlm_result.get("parsed", {})
        array_manipulated = parsed.get("array_manipulated", False)
        curve_flattened = parsed.get("curve_flattened", False)
        
        if array_manipulated:
            score += 20
            feedback_parts.append("✅ VLM: Array manipulation to multi-azimuth detected")
        else:
            feedback_parts.append("❌ VLM: Array remains monolithic/unrotated")
            
        if curve_flattened:
            score += 20
            feedback_parts.append("✅ VLM: Daily Yield graph visually flattened")
        else:
            feedback_parts.append("❌ VLM: Graph not flattened")
            
        vlm_passed = (array_manipulated and curve_flattened)
    else:
        feedback_parts.append(f"❌ VLM query failed: {vlm_result.get('error')}")

    # Cleanup temp image if we created one
    if screenshot.get('exists') and 'has_explicit_screenshot' in locals() and has_explicit_screenshot:
        if os.path.exists(temp_img.name):
            os.unlink(temp_img.name)

    passed = (score >= 70) and files_ok and logic_passed

    return {
        "passed": passed,
        "score": score,
        "feedback": "\n".join(feedback_parts)
    }