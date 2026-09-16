#!/usr/bin/env python3
"""
Verifier for building_facade_irradiance_sensor_study task.

Verification Strategy:
1. File Analysis: Checks for the existence and creation-timestamps of the output `.ng3` and `.png` files.
2. Content Analysis: Sniffs the saved `.ng3` file for sensor string signatures to ensure they were added.
3. VLM Trajectory & Content Analysis: Inspects the trajectory frames AND the generated graph image 
   to confirm the simulation was executed and multiple diurnal curves are visible.
"""

import os
import json
import logging
import tempfile

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """
You are verifying an Energy3D engineering task.
The user was asked to:
1. Place multiple light sensors on a 3D building model.
2. Run a Daily Environmental Simulation.
3. View and capture the resulting 'Sensor Data' graph showing diurnal (daily) irradiance curves.

Review these images (which include agent trajectory frames and the exported sensor graph).
Determine if the workflow was completed successfully.

Look for:
- A graph/plot window titled "Sensor Data" or similar.
- The graph should display multiple distinct lines/curves, indicating data from multiple sensors placed on different faces.
- The shape of the curves should represent daylight (rising and falling, a diurnal arc), NOT empty/flat lines.

Respond ONLY with a JSON object in this exact format:
{
    "simulation_run": true/false,
    "graph_visible": true/false,
    "multiple_curves_present": true/false,
    "diurnal_shape_present": true/false,
    "reasoning": "Brief explanation of what you see"
}
"""

def verify_building_facade_irradiance_sensor_study(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env or not query_vlm:
        return {"passed": False, "score": 0, "feedback": "Required framework functions (copy/VLM) missing."}

    score = 0
    feedback = []

    # 1. Retrieve the exported JSON result
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result file: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    # 2. Check Model File (.ng3)
    if result.get("model_exists") and result.get("model_created_during_task"):
        score += 15
        feedback.append("✅ Model file saved during task.")
        
        # Check if sensors were actually added (sniffing string signatures)
        if result.get("sensor_strings_found", 0) > 0:
            score += 15
            feedback.append(f"✅ Sensors detected in model file.")
        else:
            feedback.append("❌ No sensor signatures found in saved model.")
    else:
        feedback.append("❌ Target model file (facade_sensors.ng3) not saved or missing.")

    # 3. Check Graph Screenshot (.png)
    graph_image = None
    if result.get("graph_exists") and result.get("graph_created_during_task"):
        score += 20
        feedback.append("✅ Graph screenshot saved during task.")
        
        # Try to extract the user's saved graph for VLM inspection
        temp_graph = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/sensor_graph.png", temp_graph.name)
            if os.path.getsize(temp_graph.name) > 0:
                graph_image = temp_graph.name
        except Exception:
            pass
    else:
        feedback.append("❌ Target graph screenshot (sensor_graph.png) not saved or missing.")

    # 4. VLM Verification
    frames = sample_trajectory_frames(traj, n=3)
    final_ui = get_final_screenshot(traj)
    images_to_analyze = [f for f in frames + [final_ui] if f is not None]
    
    if graph_image and os.path.exists(graph_image):
        images_to_analyze.append(graph_image)

    vlm_result = query_vlm(prompt=VLM_PROMPT, images=images_to_analyze)
    
    vlm_success = False
    if vlm_result.get("success"):
        try:
            parsed = vlm_result.get("parsed", {})
            if parsed.get("graph_visible"):
                score += 15
                feedback.append("✅ VLM confirmed graph visibility.")
            if parsed.get("simulation_run") and parsed.get("diurnal_shape_present"):
                score += 15
                feedback.append("✅ VLM confirmed simulation data presence.")
            if parsed.get("multiple_curves_present"):
                score += 20
                feedback.append("✅ VLM confirmed multiple distinct curves.")
                vlm_success = True
            
            feedback.append(f"VLM Note: {parsed.get('reasoning', '')}")
        except Exception as e:
            feedback.append(f"⚠️ VLM parsing error: {e}")
    else:
        feedback.append("⚠️ VLM evaluation failed.")

    # Check key criteria to pass
    file_saved = result.get("model_exists") and result.get("model_created_during_task")
    graph_saved = result.get("graph_exists") and result.get("graph_created_during_task")
    
    passed = score >= 70 and file_saved and graph_saved and vlm_success

    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback)
    }