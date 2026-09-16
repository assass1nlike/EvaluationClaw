#!/usr/bin/env python3
"""
Verifier for floatovoltaics_yield_simulation task in Energy3D.
"""

import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent performing a solar engineering task in Energy3D.
The task involves designing a floating solar array (floatovoltaics) by configuring a solar panel rack with specific properties and running an Annual Yield Analysis.

Please review these screenshots from the agent's workflow and determine the following:
1. Did the agent open the Location or City dialog and select "Los Angeles"?
2. Did the agent select a solar panel rack and modify its 'Temperature Coefficient of Pmax' property to -0.2 (or a similar value for cooling effect)?
3. Did the agent modify the solar rack's 'Tilt angle' to approximately 10 degrees?
4. Did the agent modify the solar rack's 'Base height' to approximately 0.5m?
5. Did the agent run an Annual Yield Analysis (indicated by an analysis graph window showing monthly yield data)?

Respond ONLY with a valid JSON object matching this structure exactly:
{
    "location_la_set": true/false,
    "temp_coeff_adjusted": true/false,
    "tilt_angle_adjusted": true/false,
    "base_height_adjusted": true/false,
    "annual_yield_run": true/false,
    "confidence": "high/medium/low",
    "reasoning": "brief explanation"
}
"""

def get_trajectory_frames(traj, max_frames=8):
    """Safely extract frames from trajectory without external dependencies."""
    frames = []
    if not traj or 'steps' not in traj:
        return frames
        
    steps = traj['steps']
    if not steps:
        return frames
        
    # Determine indices for even sampling across the workflow
    step_indices = []
    if len(steps) <= max_frames:
        step_indices = list(range(len(steps)))
    else:
        interval = len(steps) / max_frames
        step_indices = [int(i * interval) for i in range(max_frames)]
        if len(steps) - 1 not in step_indices:
            step_indices[-1] = len(steps) - 1
            
    for idx in step_indices:
        step = steps[idx]
        if 'observation' in step and 'image' in step['observation']:
            frames.append(step['observation']['image'])
            
    return frames

def verify_floatovoltaics_yield_simulation(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env or not query_vlm:
        return {"passed": False, "score": 0, "feedback": "Required framework functions missing"}
    
    score = 0
    feedback_parts = []
    
    # 1. Read exported result data
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)
            
    # 2. Check Programmatic Output (Yield CSV)
    csv_exists = result.get('csv_exists', False)
    csv_created = result.get('csv_created_during_task', False)
    csv_lines = result.get('csv_lines', 0)
    
    if csv_exists and csv_created:
        if csv_lines >= 10:  # Typically 12 months + header rows
            score += 25
            feedback_parts.append("CSV exported successfully with valid rows")
        else:
            score += 10
            feedback_parts.append(f"CSV exported but has unexpectedly few rows ({csv_lines})")
    else:
        feedback_parts.append("Yield CSV not properly exported")
        
    # 3. Check Programmatic Artifact (Modified Design save file)
    ng3_exists = result.get('ng3_exists', False)
    ng3_created = result.get('ng3_created_during_task', False)
    
    if ng3_exists and ng3_created:
        score += 10
        feedback_parts.append("Project saved successfully")
    else:
        feedback_parts.append("Project not saved properly")
        
    # 4. Trajectory VLM Verification (for properties locked in binary state)
    frames = get_trajectory_frames(traj, max_frames=8)
    
    if not frames:
        return {"passed": False, "score": score, "feedback": "No screenshots available for VLM"}
        
    vlm_result = query_vlm(images=frames, prompt=VLM_PROMPT)
    
    if not vlm_result or not vlm_result.get("success"):
        feedback_parts.append("VLM verification failed")
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}
        
    parsed = vlm_result.get("parsed", {})
    
    # Evaluate VLM visual markers against scoring criteria
    if parsed.get("location_la_set", False):
        score += 10
        feedback_parts.append("Location set to LA")
    else:
        feedback_parts.append("Location LA not set")
        
    if parsed.get("temp_coeff_adjusted", False):
        score += 20
        feedback_parts.append("Temperature coefficient adjusted")
    else:
        feedback_parts.append("Temperature coefficient not adjusted")
        
    tilt = parsed.get("tilt_angle_adjusted", False)
    height = parsed.get("base_height_adjusted", False)
    
    if tilt and height:
        score += 15
        feedback_parts.append("Geometry (tilt & height) adjusted")
    elif tilt or height:
        score += 7
        feedback_parts.append("Geometry partially adjusted")
    else:
        feedback_parts.append("Geometry not adjusted")
        
    if parsed.get("annual_yield_run", False):
        score += 20
        feedback_parts.append("Array placed and yield analysis run")
    else:
        feedback_parts.append("Annual yield analysis not visually run")
        
    # Core requirements to pass the task block "do nothing" failures
    passed = (score >= 70) and csv_exists and csv_created
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }