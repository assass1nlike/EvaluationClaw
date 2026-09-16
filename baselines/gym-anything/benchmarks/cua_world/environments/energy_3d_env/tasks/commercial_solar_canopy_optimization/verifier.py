#!/usr/bin/env python3
"""
Verifier for Commercial Solar Canopy Optimization task.
Checks programmatic file states and leverages VLM trajectory analysis to evaluate GUI interactions.
"""

import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an AI agent's performance on a 3D CAD analysis task in Energy3D.
The agent was instructed to:
1. Change the geographic city location to 'Phoenix'.
2. Select the existing solar canopy and change the solar panel tilt angle to 15 degrees.
3. Run a Solar Radiation or Daily/Annual Yield analysis to display a performance graph popup.

Analyze the trajectory frames and final screenshot provided.
Respond ONLY with a valid JSON object evaluating these criteria:
{
  "location_menu_used": true/false,
  "tilt_visually_adjusted": true/false,
  "analysis_graph_visible_at_end": true/false,
  "reasoning": "Briefly explain the visual evidence you found for each step."
}"""

def verify_canopy_optimization(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Container file access (copy_from_env) is not available."}
        
    score = 0
    feedback_parts = []
    
    # 1. Read JSON file containing programmatic checks
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to load result JSON: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    # 2. Evaluate Programmatic Criteria
    output_exists = result.get('output_exists', False)
    created_during_task = result.get('created_during_task', False)
    has_phoenix_string = result.get('has_phoenix_string', False)
    
    if output_exists and created_during_task:
        score += 20
        feedback_parts.append("✅ Correct file 'phoenix_canopy.ng3' saved")
    elif output_exists:
        feedback_parts.append("❌ File exists but timestamp shows it was not created during this task")
    else:
        feedback_parts.append("❌ Target output file was not saved")
        
    if has_phoenix_string:
        score += 20
        feedback_parts.append("✅ Location 'Phoenix' found in project configuration")
    else:
        feedback_parts.append("❌ Location 'Phoenix' not detected in saved file data")
        
    # 3. VLM Visual Verification
    if not query_vlm:
        feedback_parts.append("⚠️ VLM unavailable for visual trajectory checking")
    else:
        try:
            # We import here to allow fallback gracefully if framework components are missing
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            
            frames = sample_trajectory_frames(traj, n=4)
            final_img = get_final_screenshot(traj)
            
            images_to_evaluate = frames
            if final_img:
                images_to_evaluate.append(final_img)
                
            if images_to_evaluate:
                vlm_resp = query_vlm(
                    prompt=VLM_PROMPT,
                    images=images_to_evaluate
                )
                
                if vlm_resp.get("success"):
                    parsed = vlm_resp.get("parsed", {})
                    
                    if parsed.get("location_menu_used", False):
                        score += 15
                        feedback_parts.append("✅ VLM confirmed location properties accessed")
                        
                    if parsed.get("tilt_visually_adjusted", False):
                        score += 20
                        feedback_parts.append("✅ VLM confirmed canopy tilt angle was adjusted")
                        
                    if parsed.get("analysis_graph_visible_at_end", False):
                        score += 25
                        feedback_parts.append("✅ VLM confirmed performance graph generated and visible")
                    else:
                        feedback_parts.append("❌ Target graph popup not visible at task end")
                else:
                    feedback_parts.append(f"⚠️ VLM parsing failed: {vlm_resp.get('error')}")
        except Exception as e:
            feedback_parts.append(f"⚠️ Trajectory VLM error: {e}")

    # 4. Final Evaluation Logic
    # Must have the target file saved properly + reasonable score threshold
    key_criteria_met = output_exists and created_during_task and has_phoenix_string
    passed = score >= 60 and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": "\n".join(feedback_parts)
    }