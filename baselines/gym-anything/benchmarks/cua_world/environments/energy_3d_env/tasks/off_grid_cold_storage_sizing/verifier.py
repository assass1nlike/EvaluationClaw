#!/usr/bin/env python3
"""
Verifier for the Off-Grid Cold Storage Sizing task.
Uses a hybrid approach:
1. Programmatic file-system checks to prevent "do nothing" runs.
2. VLM review of trajectory frames to confirm thermostat adjustments, solar panel
   placement, and energy analysis actions since the Java (.ng3) file is binary serialized.
"""

import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Safely import VLM trajectory utilities provided by the framework
try:
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
except ImportError:
    logger.warning("gym_anything.vlm not available. Fallback: empty image lists.")
    def sample_trajectory_frames(traj, n): return []
    def get_final_screenshot(traj): return None

VLM_PROMPT = """You are verifying if a user successfully completed an off-grid cold storage design in Energy3D.
Look at the provided trajectory screenshots and the final state.

1. Did the user configure the building's thermostat for cold storage (cooling setpoint lowered significantly, typically visible in the properties window around 5°C to 10°C)?
2. Did they change the project location to Phoenix, AZ (often visible in the toolbar, environment panel, or map)?
3. Did they add a significant solar panel array (panels placed on the roof and/or ground)?
4. Did they run the Annual Energy Analysis tools (evident by bar charts/graphs appearing that show energy use and solar yield)?
5. Based on any visible graphs or reports, does the solar yield appear to equal or offset the energy consumption (off-grid / positive net energy achieved)?

Respond strictly in JSON format:
{
   "thermostat_configured": true/false,
   "location_phoenix": true/false,
   "solar_array_added": true/false,
   "analysis_run": true/false,
   "off_grid_achieved": true/false,
   "confidence": "high/medium/low",
   "reasoning": "brief explanation"
}"""

def verify_off_grid_cold_storage(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []

    # Retrieve programmatic file outputs from the environment
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

    output_exists = result.get('output_exists', False)
    file_created = result.get('file_created_during_task', False)
    output_size = result.get('output_size_bytes', 0)

    # 1. Programmatic verification checking file output constraints
    if output_exists and file_created and output_size > 1000:
        score += 30
        feedback_parts.append("✅ Output project file correctly saved")
    elif output_exists:
        score += 10
        feedback_parts.append("⚠️ Output file exists but timestamp/size anomalous")
    else:
        feedback_parts.append("❌ cold_storage_solar.ng3 was not saved")

    if not query_vlm:
        feedback_parts.append("⚠️ VLM query not available for visual checks")
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}

    # 2. VLM Trajectory Verification
    frames = sample_trajectory_frames(traj, n=5)
    final = get_final_screenshot(traj)
    images = frames + ([final] if final else [])

    if not images:
        feedback_parts.append("❌ No screenshots available for VLM verification")
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}

    vlm_result = query_vlm(prompt=VLM_PROMPT, images=images)
    if not vlm_result or not vlm_result.get("success"):
        feedback_parts.append(f"❌ VLM evaluation failed: {vlm_result.get('error', 'unknown error')}")
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}

    parsed = vlm_result.get("parsed", {})
    
    # 3. Analyze Visual Insights
    thermostat = parsed.get("thermostat_configured", False)
    phoenix = parsed.get("location_phoenix", False)
    solar = parsed.get("solar_array_added", False)
    analysis = parsed.get("analysis_run", False)
    off_grid = parsed.get("off_grid_achieved", False)

    if phoenix:
        score += 10
        feedback_parts.append("✅ Location changed to Phoenix")
    if thermostat:
        score += 20
        feedback_parts.append("✅ Thermostat lowered for cold storage")
    if solar:
        score += 20
        feedback_parts.append("✅ Solar array deployed")
    
    if analysis and off_grid:
        score += 20
        feedback_parts.append("✅ Energy analysis run, and off-grid performance achieved")
    elif analysis:
        score += 10
        feedback_parts.append("⚠️ Energy analysis run, but off-grid achievement unconfirmed")

    # Strict requirement: the agent must have produced output AND correctly configured physical properties.
    key_criteria_met = output_exists and thermostat and solar and file_created
    passed = score >= 70 and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts),
        "details": parsed
    }