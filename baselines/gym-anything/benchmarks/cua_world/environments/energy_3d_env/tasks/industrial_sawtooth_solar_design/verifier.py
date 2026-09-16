#!/usr/bin/env python3
import os
import json
import tempfile
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are an architectural evaluator grading a user's task in Energy3D. 
The task is to convert a building roof into a 'Sawtooth' shape and populate its south-facing slopes with solar panels.

Examine these trajectory frames and the final screenshot:
1. Did the user successfully change the building's roof geometry to a distinct "Sawtooth" shape?
2. Are there visible Solar Panels added to the building's roof?
3. Are the solar panels intelligently placed ONLY on the angled slopes of the sawtooth roof (rather than floating in midair or randomly placed on flat sections)?
4. Is Energy3D the application being used?

Respond with a JSON object:
{
    "sawtooth_roof_present": true/false,
    "panels_present": true/false,
    "panels_on_slopes": true/false,
    "is_energy3d": true/false,
    "reasoning": "Brief explanation of what is visually confirmed."
}
"""

def verify_sawtooth_solar_design(traj, env_info: Dict[str, Any], task_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verifies the industrial sawtooth solar design task via file analysis and VLM trajectory grading.
    """
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Evaluation environment error: copy_from_env missing."}

    # 1. Read JSON results from the container
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            results = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to load task result JSON: {str(e)}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    score = 0
    max_score = 100
    feedback_parts = []
    
    # 2. Check NG3 Project File (15 pts)
    ng3_exists = results.get("ng3_exists", False)
    ng3_created = results.get("ng3_created_during_task", False)
    
    if ng3_exists and ng3_created:
        score += 15
        feedback_parts.append("✅ Project saved successfully")
    elif ng3_exists:
        score += 5
        feedback_parts.append("⚠️ Project exists but wasn't modified during task")
    else:
        feedback_parts.append("❌ Project file not saved")

    # 3. Check CSV Export (15 pts)
    csv_exists = results.get("csv_exists", False)
    csv_created = results.get("csv_created_during_task", False)
    
    if csv_exists and csv_created:
        score += 15
        feedback_parts.append("✅ CSV analysis exported successfully")
    elif csv_exists:
        score += 5
        feedback_parts.append("⚠️ CSV exists but wasn't created during task")
    else:
        feedback_parts.append("❌ CSV analysis not exported")

    # 4. Validate CSV Simulation Data (20 pts)
    csv_rows = results.get("csv_rows", 0)
    csv_solar = results.get("csv_solar_sum", 0.0)
    
    if csv_exists:
        if csv_rows >= 12 and csv_solar > 0:
            score += 20
            feedback_parts.append(f"✅ Simulation valid (12 months of data, PV Yield: {csv_solar:.2f} kWh)")
        elif csv_rows >= 12:
            score += 10
            feedback_parts.append("⚠️ Simulation ran, but PV yield was zero (panels not wired/placed properly)")
        else:
            feedback_parts.append("❌ Exported CSV lacks 12 months of simulation data")

    # 5. Check Environment Metadata: Detroit Location (10 pts)
    detroit_found = results.get("detroit_in_ng3", False)
    if detroit_found:
        score += 10
        feedback_parts.append("✅ Location metadata correctly set to Detroit")
    else:
        feedback_parts.append("❌ Detroit location not found in metadata")

    # 6. VLM Trajectory Verification (40 pts)
    vlm_score = 0
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            frames = sample_trajectory_frames(traj, n=4)
            final_img = get_final_screenshot(traj)
            if final_img:
                frames.append(final_img)
            
            vlm_resp = query_vlm(images=frames, prompt=VLM_PROMPT)
            if vlm_resp and vlm_resp.get("success"):
                vlm_data = vlm_resp.get("parsed", {})
                
                is_energy3d = vlm_data.get("is_energy3d", False)
                sawtooth = vlm_data.get("sawtooth_roof_present", False)
                panels = vlm_data.get("panels_present", False)
                slopes = vlm_data.get("panels_on_slopes", False)
                
                if is_energy3d:
                    if sawtooth:
                        vlm_score += 20
                        feedback_parts.append("✅ VLM verified Sawtooth roof geometry")
                    else:
                        feedback_parts.append("❌ VLM did not detect Sawtooth roof geometry")
                        
                    if panels and slopes:
                        vlm_score += 20
                        feedback_parts.append("✅ VLM verified optimal panel placement on slopes")
                    elif panels:
                        vlm_score += 10
                        feedback_parts.append("⚠️ VLM detected panels, but poor placement")
                    else:
                        feedback_parts.append("❌ VLM detected no solar panels")
            else:
                feedback_parts.append("⚠️ VLM evaluation query failed")
        except Exception as e:
            logger.error(f"VLM verification error: {str(e)}")
            feedback_parts.append("⚠️ VLM internal error")
    
    score += vlm_score

    # Passing conditions
    # Requires saving the core files, running the sim, and visually satisfying the geometry requirements.
    passed = score >= 70 and csv_exists and csv_solar > 0

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }