#!/usr/bin/env python3
"""
Verifier for cool_roof_albedo_retrofit_analysis task.

Checks:
1. File Creation & Timestamps
2. Location changed to Phoenix
3. Roof Albedo changed to 0.85
4. Mathematical integrity in the reported text file (Baseline - Optimized = Savings)
5. Visual confirmation of UI interactions via VLM
"""

import json
import tempfile
import os
import re
import logging
import math

# Use framework utilities
try:
    from gym_anything.vlm import sample_trajectory_frames, query_vlm, get_final_screenshot
    VLM_AVAILABLE = True
except ImportError:
    VLM_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_cool_roof(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    feedback_parts = []
    score = 0
    max_score = 100

    # 1. Read metadata & task_result
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    temp_ng3 = tempfile.NamedTemporaryFile(delete=False, suffix='.ng3')
    temp_txt = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
    
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result metadata: {e}"}

    ng3_exists = result.get('ng3_exists', False)
    txt_exists = result.get('txt_exists', False)
    start_ts = result.get('start_ts', 0)
    
    # 2. File verification
    if ng3_exists and txt_exists:
        if result.get('ng3_mtime', 0) > start_ts and result.get('txt_mtime', 0) > start_ts:
            score += 10
            feedback_parts.append("✅ Output files created correctly")
        else:
            feedback_parts.append("❌ Files exist but timestamps indicate they are old/stale")
    else:
        feedback_parts.append("❌ Missing required output files (.ng3 or .txt)")
        return {
            "passed": False,
            "score": score,
            "feedback": " | ".join(feedback_parts)
        }

    # 3. Analyze the .ng3 file (Location and Albedo)
    has_phoenix = False
    has_albedo = False
    try:
        copy_from_env("/tmp/cool_roof_optimized.ng3", temp_ng3.name)
        with open(temp_ng3.name, 'r', encoding='utf-8', errors='ignore') as f:
            ng3_content = f.read()
            # XMLEncoder format checks
            if "Phoenix" in ng3_content:
                has_phoenix = True
                score += 15
                feedback_parts.append("✅ Location changed to Phoenix")
            else:
                feedback_parts.append("❌ Location not set to Phoenix in project file")
                
            if "0.85" in ng3_content or ".85" in ng3_content:
                has_albedo = True
                score += 25
                feedback_parts.append("✅ Roof albedo successfully changed to 0.85")
            else:
                feedback_parts.append("❌ Roof albedo 0.85 not found in project file")
    except Exception as e:
        feedback_parts.append(f"❌ Failed to parse .ng3 file: {e}")

    # 4. Analyze the text report (Mathematical Integrity)
    math_correct = False
    try:
        copy_from_env("/tmp/cooling_savings.txt", temp_txt.name)
        with open(temp_txt.name, 'r', encoding='utf-8', errors='ignore') as f:
            txt_content = f.read()
            
        # Extract all floating point/integer numbers from the text
        numbers = [float(x) for x in re.findall(r"[-+]?\d*\.\d+|\d+", txt_content)]
        numbers = [n for n in numbers if n > 0]  # Filter out dates or negatives
        
        # Look for a valid combination where A - B = C
        # We expect Baseline (A), Optimized (B), and Savings (C)
        # where A > B, and A, B, C > 0
        for i, A in enumerate(numbers):
            for j, B in enumerate(numbers):
                if i == j: continue
                for k, C in enumerate(numbers):
                    if k == i or k == j: continue
                    # Accept a small tolerance for rounding discrepancies
                    if A > B and math.isclose(A - B, C, rel_tol=0.02, abs_tol=5.0):
                        math_correct = True
                        break
                if math_correct: break
            if math_correct: break

        if math_correct:
            score += 20  # Report Math Integrity
            score += 15  # Savings Accuracy (values logically correlate)
            feedback_parts.append("✅ Text report math verifies (Baseline - Optimized = Savings)")
        else:
            feedback_parts.append("❌ Could not verify math integrity in text report (Missing/Incorrect values)")
            
    except Exception as e:
        feedback_parts.append(f"❌ Failed to process text report: {e}")

    # 5. VLM Trajectory Verification
    vlm_verified = False
    if VLM_AVAILABLE:
        try:
            frames = sample_trajectory_frames(traj, n=4)
            frames.append(get_final_screenshot(traj))
            
            prompt = """You are verifying an Energy3D building analysis task.
Look at these screens captured during the task.
Determine if the user actively interacted with the 'Annual Energy Analysis' graphing tool.
Look for:
- Bar charts showing months (Jan-Dec) and energy usage (Heating, Cooling, Total)
- Any window titled "Annual Energy Analysis"
- Evidence of active application usage (not just looking at a blank model).

Return JSON format:
{
    "analysis_graph_opened": true/false,
    "reasoning": "brief explanation"
}
"""
            vlm_res = query_vlm(prompt=prompt, images=frames)
            if vlm_res.get('success'):
                parsed = vlm_res.get('parsed', {})
                if parsed.get('analysis_graph_opened', False):
                    score += 15
                    vlm_verified = True
                    feedback_parts.append("✅ VLM verified Annual Energy Analysis was run")
                else:
                    feedback_parts.append("❌ VLM did not detect Annual Energy Analysis execution")
            else:
                feedback_parts.append("⚠️ VLM verification failed to process")
        except Exception as e:
            feedback_parts.append(f"⚠️ VLM error: {e}")

    # Cleanup temp files
    for tmp_file in [temp_result, temp_ng3, temp_txt]:
        if os.path.exists(tmp_file.name):
            os.unlink(tmp_file.name)

    # Criteria Enforcement
    # Must have file changes AND math must be correct to pass
    passed = score >= 70 and has_albedo and math_correct

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }