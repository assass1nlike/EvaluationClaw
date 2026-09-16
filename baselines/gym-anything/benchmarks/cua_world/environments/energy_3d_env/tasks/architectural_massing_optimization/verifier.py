#!/usr/bin/env python3
"""
Verifier for architectural_massing_optimization task.

Verification Strategy:
1. File-based Checks: Verifies the creation of the CSV, TXT, and NG3 files during the task timeframe.
2. VLM Trajectory Checks: 
   - Verifies that the geographic location was adjusted to Anchorage, AK.
   - Evaluates if the agent's text output correctly identifies the most compact building.
   - Verifies that solar panels were added ONLY to the sprawling (least efficient) building.
"""

import json
import os
import re
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_architectural_massing_optimization(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env or not query_vlm:
        return {"passed": False, "score": 0, "feedback": "Missing environment functions (copy_from_env or query_vlm)"}

    # Extract JSON results securely
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read exported results: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    csv_created = result.get("csv_created", False)
    txt_created = result.get("txt_created", False)
    txt_content = result.get("txt_content", "")
    ng3_created = result.get("ng3_created", False)

    score = 0
    feedback_parts = []

    # File based scoring
    if csv_created:
        score += 10
        feedback_parts.append("CSV exported")
    else:
        feedback_parts.append("CSV not exported")

    if txt_created:
        score += 5
        feedback_parts.append("Text file created")
    else:
        feedback_parts.append("Text file missing")

    if ng3_created:
        score += 15
        feedback_parts.append("Optimized NG3 saved")
    else:
        feedback_parts.append("Optimized NG3 not saved")

    # VLM Evaluation
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
    
    # We sample frames to catch location changes and analysis execution
    frames = sample_trajectory_frames(traj, n=5)
    final = get_final_screenshot(traj)
    images = frames + [final] if final else frames
    
    if not images:
        return {
            "passed": False,
            "score": score,
            "feedback": " | ".join(feedback_parts) + " | No visual evidence for VLM verification."
        }

    vlm_prompt = f"""You are an expert evaluating an architectural energy optimization task in Energy3D.

TASK CONTEXT:
1. Change geographic location to Anchorage, AK.
2. Run an energy analysis on the building shapes.
3. Identify the building with the lowest heating load (the most compact/efficient shape, e.g. the cube).
4. Add solar panels ONLY to the building with the highest heating load (the least efficient, most sprawling/complex shape).

AGENT'S TEXT OUTPUT (best_massing.txt):
"{txt_content}"

Look at the trajectory frames and final screenshot provided.

EVALUATE THE FOLLOWING:
1. Did the agent change the location to Anchorage? (Look for location dialogs showing Anchorage, or a winter/snow environment).
2. Based on the agent's text output ("{txt_content}"), did they correctly identify the most compact/efficient building shape in the scene?
3. Did the agent add solar panels?
4. Are the solar panels added ONLY to the most sprawling/least efficient building (e.g. the U-shape or elongated shape), and left off the efficient ones?

Respond strictly in JSON format:
{{
    "location_anchorage": true/false,
    "identified_best_shape": true/false,
    "solar_panels_added": true/false,
    "solar_on_worst_shape_only": true/false,
    "reasoning": "brief explanation"
}}
"""
    
    vlm_response = query_vlm(images=images, prompt=vlm_prompt)
    
    try:
        # Robustly parse JSON from VLM response
        vlm_text = vlm_response if isinstance(vlm_response, str) else vlm_response.get("parsed", vlm_response.get("text", "{}"))
        
        if isinstance(vlm_text, dict):
            vlm_data = vlm_text
        else:
            json_match = re.search(r'\{.*\}', vlm_text, re.DOTALL)
            vlm_data = json.loads(json_match.group()) if json_match else {}
            
        loc_anchorage = vlm_data.get("location_anchorage", False)
        id_best = vlm_data.get("identified_best_shape", False)
        solar_added = vlm_data.get("solar_panels_added", False)
        solar_correct = vlm_data.get("solar_on_worst_shape_only", False)
        
        if loc_anchorage:
            score += 20
            feedback_parts.append("Location Anchorage verified")
        else:
            feedback_parts.append("Location Anchorage NOT verified")
            
        if id_best and txt_created:
            score += 20
            feedback_parts.append("Best shape correctly identified")
        elif not txt_created:
            feedback_parts.append("Skipped shape ID (no text file)")
        else:
            feedback_parts.append("Incorrect best shape identified")
            
        if solar_added and solar_correct:
            score += 30
            feedback_parts.append("Solar panels correctly added to worst shape ONLY")
        elif solar_added:
            score += 10  # Partial credit if added to wrong/all buildings
            feedback_parts.append("Solar panels added, but not strictly to the worst shape")
        else:
            feedback_parts.append("Solar panels not added")
            
    except Exception as e:
        logger.error(f"VLM parse error: {e}")
        feedback_parts.append("VLM evaluation failed to parse")

    # Determine pass/fail
    key_criteria_met = csv_created and ng3_created and score >= 70
    passed = key_criteria_met
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }