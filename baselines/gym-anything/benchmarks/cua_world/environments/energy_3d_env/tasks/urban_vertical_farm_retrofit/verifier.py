#!/usr/bin/env python3
"""
Verifier for urban_vertical_farm_retrofit task.
"""

import os
import json
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent's performance in Energy3D.
The agent was asked to design an urban vertical farm retrofit with the following features:
1. A multi-story rectangular building (warehouse).
2. Large windows added to the walls (high window-to-wall ratio).
3. A solar panel array installed on the roof.
4. An "Annual Energy Analysis" run (which generates a bar chart window showing monthly energy).

Review the provided sequence of screenshots (trajectory) and the final screenshot.
Determine if the agent successfully completed these requirements.

Respond with a JSON object strictly matching this format:
{
  "building_created": true/false,
  "windows_added": true/false,
  "solar_panels_present": true/false,
  "analysis_run": true/false,
  "reasoning": "brief explanation"
}
"""

def verify_urban_vertical_farm_retrofit(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    # Get results from container
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

    score = 0
    feedback_parts = []

    # Criterion 1: File saved properly (20 points)
    output_exists = result.get('output_exists', False)
    file_created = result.get('file_created_during_task', False)
    
    if output_exists and file_created:
        score += 20
        feedback_parts.append("Project file saved correctly")
    elif output_exists:
        score += 10
        feedback_parts.append("Project file exists but timestamp is from before task")
    else:
        feedback_parts.append("Project file not saved")

    # VLM Verification for visual elements
    query_vlm = env_info.get('query_vlm')
    if not query_vlm:
        feedback_parts.append("VLM query function not available")
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}
        
    try:
        from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
        frames = sample_trajectory_frames(traj, n=5)
        final = get_final_screenshot(traj)
        
        images_to_analyze = frames
        if final:
            images_to_analyze.append(final)
            
        if not images_to_analyze:
            feedback_parts.append("No screenshots available for VLM verification")
            return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}
            
        vlm_result = query_vlm(images=images_to_analyze, prompt=VLM_PROMPT)
        
        parsed = {}
        if isinstance(vlm_result, dict):
            if vlm_result.get("success"):
                parsed = vlm_result.get("parsed", {})
            else:
                parsed = vlm_result
        else:
            parsed = vlm_result

        building_created = parsed.get("building_created", False)
        windows_added = parsed.get("windows_added", False)
        solar_panels_present = parsed.get("solar_panels_present", False)
        analysis_run = parsed.get("analysis_run", False)
            
        # Criterion 2: Building Created (20 pts)
        if building_created:
            score += 20
            feedback_parts.append("Building visually confirmed")
        else:
            feedback_parts.append("Building not found")
            
        # Criterion 3: Windows Added (20 pts)
        if windows_added:
            score += 20
            feedback_parts.append("Windows visually confirmed")
        else:
            feedback_parts.append("Large windows not found")
            
        # Criterion 4: Solar Panels Present (20 pts)
        if solar_panels_present:
            score += 20
            feedback_parts.append("Solar panels visually confirmed")
        else:
            feedback_parts.append("Solar panels not found")
            
        # Criterion 5: Analysis Run (20 pts)
        if analysis_run:
            score += 20
            feedback_parts.append("Analysis chart visually confirmed")
        else:
            feedback_parts.append("Analysis chart not found")
            
        logger.info(f"VLM reasoning: {parsed.get('reasoning', 'None provided')}")
                
    except Exception as e:
        logger.error(f"Error during VLM verification: {e}")
        feedback_parts.append(f"VLM verification error: {str(e)}")

    # To pass, the agent must have at least drawn the building AND saved the file
    building_created = locals().get('building_created', False)
    passed = (score >= 60) and output_exists and building_created

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }