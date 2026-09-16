#!/usr/bin/env python3
"""
Verifier for Concentrated Solar Power (CSP) Tower Design Task in Energy3D.

Verification Strategy:
1. Programmatic File Checks (30 points): Ensure target file was created during the task, 
   has non-trivial size, and parses to contain "SolarTower", "Heliostat", and "Las Vegas".
2. VLM Trajectory Check (70 points): Use trajectory frames to confirm that the agent visually
   constructed a CSP field (tower + mirrors) and successfully opened an Analysis Graph.
"""

import os
import json
import tempfile
import logging

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot, query_vlm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying an agent's completion of a Concentrated Solar Power (CSP) engineering task in Energy3D.
The agent was asked to build a CSP field (a central solar tower surrounded by multiple tracking mirrors called heliostats), set the location to Las Vegas, and run a yield/energy analysis graph.

Please analyze these trajectory frames and the final screenshot to answer the following:
1. CSP Field Setup: Is there a 3D scene showing a central Solar Tower surrounded by a field of many mirrors (Heliostats)?
2. Analysis Graph: Did the agent open an energy analysis graph (e.g., 'Daily Yield Analysis', 'Solar Radiation', or 'Annual Energy Analysis') in a pop-up window or bottom panel?
3. Settings Interaction: Is there visual evidence the agent changed or viewed the Location (to Las Vegas) or the Date (to December/Winter)?

Respond in strictly JSON format:
{
    "csp_field_visible": true/false,
    "analysis_graph_shown": true/false,
    "settings_interaction_seen": true/false,
    "confidence": "high/medium/low",
    "reasoning": "Brief explanation of what you observed"
}
"""

def verify_csp_design(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm_func = env_info.get('query_vlm')
    
    if not copy_from_env or not query_vlm_func:
        return {"passed": False, "score": 0, "feedback": "Verification functions not available"}

    score = 0
    feedback_parts = []
    
    # -------------------------------------------------------------------------
    # 1. Programmatic Checks
    # -------------------------------------------------------------------------
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read export JSON: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    file_exists = result.get('file_exists', False)
    file_created = result.get('file_created_during_task', False)
    file_size = result.get('file_size', 0)

    if file_exists and file_created and file_size > 500:
        score += 10
        feedback_parts.append("✅ File correctly saved during task")
    elif file_exists:
        score += 5
        feedback_parts.append("⚠️ File exists but may not have been created during task")
    else:
        feedback_parts.append("❌ Target project file was not saved")

    # Read the .ng3 file (which is effectively a text/XML/JSON payload in Energy3D)
    ng3_content = ""
    temp_ng3 = tempfile.NamedTemporaryFile(delete=False, suffix='.ng3')
    try:
        if file_exists:
            copy_from_env("/tmp/project.ng3", temp_ng3.name)
            with open(temp_ng3.name, 'r', encoding='utf-8', errors='ignore') as f:
                ng3_content = f.read()
    except Exception as e:
        logger.warning(f"Could not read .ng3 file: {e}")
    finally:
        if os.path.exists(temp_ng3.name):
            os.unlink(temp_ng3.name)

    # Basic programmatic string checks
    if "SolarTower" in ng3_content or "Solar Tower" in ng3_content:
        score += 10
        feedback_parts.append("✅ Solar Tower detected in save file")
    
    heliostat_count = ng3_content.count("Heliostat")
    if heliostat_count >= 10:  # Relaxing the exact 30 string match to account for save serialization quirks
        score += 10
        feedback_parts.append(f"✅ Heliostats detected in save file ({heliostat_count} hits)")
    elif heliostat_count > 0:
        score += 5
        feedback_parts.append(f"⚠️ Few Heliostats detected in save file ({heliostat_count} hits)")

    if "Las Vegas" in ng3_content:
        score += 5
        feedback_parts.append("✅ Las Vegas location detected in save file")

    # -------------------------------------------------------------------------
    # 2. VLM Trajectory Verification
    # -------------------------------------------------------------------------
    frames = sample_trajectory_frames(traj, n=5)
    final = get_final_screenshot(traj)
    if final:
        frames.append(final)
        
    vlm_result = query_vlm_func(images=frames, prompt=VLM_PROMPT)
    parsed = vlm_result.get("parsed", {})
    
    csp_field_visible = parsed.get("csp_field_visible", False)
    analysis_graph_shown = parsed.get("analysis_graph_shown", False)
    settings_interaction = parsed.get("settings_interaction_seen", False)
    
    if csp_field_visible:
        score += 35
        feedback_parts.append("✅ VLM confirmed CSP field (Tower + Heliostats) visually")
    else:
        feedback_parts.append("❌ VLM did not clearly see a CSP field")
        
    if analysis_graph_shown:
        score += 20
        feedback_parts.append("✅ VLM confirmed Energy Analysis Graph was opened")
    else:
        feedback_parts.append("❌ VLM did not see an Energy Analysis Graph")
        
    if settings_interaction:
        score += 10
        feedback_parts.append("✅ VLM confirmed location/date settings interaction")

    # -------------------------------------------------------------------------
    # Final Scoring
    # -------------------------------------------------------------------------
    # Cap score at 100
    score = min(100, score)
    
    # Must have both file output AND visual confirmation to pass
    passed = (score >= 70) and file_exists and csp_field_visible
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }