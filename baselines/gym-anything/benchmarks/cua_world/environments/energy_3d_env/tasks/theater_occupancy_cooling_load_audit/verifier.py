#!/usr/bin/env python3
"""
Verifier for Theater Occupancy Cooling Load Audit task.
"""

import os
import json
import re
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fallback import for VLM testing
try:
    from gym_anything.vlm import sample_trajectory_frames, query_vlm
    VLM_AVAILABLE = True
except ImportError:
    VLM_AVAILABLE = False
    logger.warning("VLM utilities not available.")

VLM_PROMPT = """You are verifying if an agent successfully analyzed a building's energy footprint in Energy3D.

Look closely at these screenshots captured during the agent's session.
Determine if the following actions occurred:
1. Did the agent open the "Daily Building Energy Analysis" graph window at any point? (Look for a line or bar chart plotting energy over 24 hours).
2. Is there evidence that the agent accessed the building properties to edit occupancy? (Look for property panels or dialogs on the right side or floating).
3. Did the agent change the location/city to Miami?

Respond strictly in this JSON format:
{
    "daily_analysis_graph_visible": true/false,
    "building_properties_accessed": true/false,
    "confidence": "high/medium/low",
    "reasoning": "Brief explanation"
}
"""

def extract_numbers_from_text(text):
    """Extracts all floating point and integer numbers from a string."""
    # Matches numbers like 400, 1500.5, 1,200.45
    matches = re.findall(r'-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?', text)
    numbers = []
    for m in matches:
        try:
            numbers.append(float(m.replace(',', '')))
        except ValueError:
            pass
    return numbers

def verify_theater_occupancy_audit(traj, env_info, task_info):
    """
    Verifies the Energy3D cooling audit task.
    """
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available."}

    score = 0
    feedback_parts = []
    
    # 1. Retrieve the exported JSON result
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r', encoding='utf-8') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    # 2. NG3 File Checks (20 points)
    if result.get("ng3_exists"):
        if result.get("ng3_created_during_task"):
            score += 15
            feedback_parts.append("✅ Modified project file saved during task.")
            if result.get("ng3_has_miami_string"):
                score += 5
                feedback_parts.append("✅ 'Miami' location found in project file.")
        else:
            feedback_parts.append("❌ Project file exists but was NOT created/modified during task.")
    else:
        feedback_parts.append("❌ Project file 'occupied_theater.ng3' not found.")

    # 3. Report File Checks & Logical Math Check (40 points)
    math_valid = False
    if result.get("report_exists"):
        if result.get("report_created_during_task"):
            score += 10
            feedback_parts.append("✅ Report text file created.")
            
            # Math check
            report_content = result.get("report_content", "")
            numbers = extract_numbers_from_text(report_content)
            
            if len(numbers) >= 3:
                # We need to find if there's a relationship: Baseline + Delta = Occupied (approximate tolerance)
                # Or just verify they recorded three distinct valid loads. 
                # Cooling loads for this building in Miami usually run in the thousands of kWh.
                
                # Check all combinations of 3 numbers to see if A + B ≈ C
                found_relation = False
                for i in range(len(numbers)):
                    for j in range(len(numbers)):
                        for k in range(len(numbers)):
                            if i != j and i != k and j != k:
                                A, B, C = numbers[i], numbers[j], numbers[k]
                                if A > 0 and B > 0 and C > 0:
                                    if abs((A + B) - C) <= 5.0: # 5 kWh tolerance
                                        found_relation = True
                                        math_valid = True
                                        break
                        if found_relation: break
                    if found_relation: break
                
                if math_valid:
                    score += 30
                    feedback_parts.append("✅ Report contains logically valid data (Baseline + Increase = Occupied Load).")
                else:
                    score += 10 # Partial credit for extracting numbers
                    feedback_parts.append("⚠️ Report has numbers, but mathematically A + B = C relationship was not found.")
            else:
                feedback_parts.append(f"❌ Report does not contain enough numerical data (found {len(numbers)} numbers).")
        else:
            feedback_parts.append("❌ Report file exists but was NOT created/modified during task.")
    else:
        feedback_parts.append("❌ Report file 'cooling_audit.txt' not found.")

    # 4. VLM Verification of Trajectory (40 points)
    vlm_success = False
    if VLM_AVAILABLE and env_info.get("query_vlm"):
        try:
            frames = sample_trajectory_frames(traj, n=6)
            vlm_result = env_info["query_vlm"](images=frames, prompt=VLM_PROMPT)
            
            if vlm_result and vlm_result.get("success"):
                parsed = vlm_result.get("parsed", {})
                graph_seen = parsed.get("daily_analysis_graph_visible", False)
                props_seen = parsed.get("building_properties_accessed", False)
                
                if graph_seen:
                    score += 25
                    feedback_parts.append("✅ VLM confirmed Daily Analysis graph was used.")
                else:
                    feedback_parts.append("❌ VLM did not see Daily Analysis graph used.")
                    
                if props_seen:
                    score += 15
                    feedback_parts.append("✅ VLM confirmed building properties were accessed.")
                else:
                    feedback_parts.append("❌ VLM did not see properties being modified.")
                
                vlm_success = graph_seen
            else:
                feedback_parts.append("⚠️ VLM verification query failed.")
        except Exception as e:
            logger.error(f"VLM Exception: {e}")
            feedback_parts.append("⚠️ VLM evaluation error.")
    else:
        feedback_parts.append("⚠️ VLM not available. Skipping visual trajectory check.")

    # Determine Pass/Fail Status
    # Must have saved files, recorded valid numbers, AND used the graph according to VLM.
    key_criteria = result.get("ng3_exists") and result.get("report_exists") and math_valid and vlm_success
    passed = (score >= 70) and key_criteria

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }