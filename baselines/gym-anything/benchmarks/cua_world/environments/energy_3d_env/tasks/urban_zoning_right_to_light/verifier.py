#!/usr/bin/env python3
"""
Verifier for urban_zoning_right_to_light task.

Combines programmatic checks (file validation, string parsing) 
with VLM verification (visual structure and trajectory validation).
"""

import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are an expert Urban Planning software evaluator. 
Review the provided trajectory screenshots and the final screenshot of the Energy3D interface.

Task Requirements:
1. Reduce the height of the absolute tallest building in the scene to ~40m (it should no longer be a towering skyscraper).
2. Add a solar panel array (multiple panels) to the roof of the shortest building in the scene.
3. Set the date to December 21 (Winter Solstice).

Analyze the images and respond with a JSON object exactly matching this format:
{
    "tallest_building_height_reduced": true/false,
    "solar_panels_on_shortest_building": true/false,
    "date_set_to_dec_21": true/false,
    "confidence": "low/medium/high",
    "reasoning": "Brief explanation of your observations"
}"""

def verify_urban_zoning(traj, env_info, task_info):
    """
    Verify the right-to-light zoning task.
    """
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env or not query_vlm:
        return {"passed": False, "score": 0, "feedback": "Required verification functions not available."}

    # Extract task result JSON
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to load task result: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    score = 0
    feedback_parts = []
    
    # 1. Programmatic File Checks
    file_exists = result.get("file_exists", False)
    file_created = result.get("file_created_during_task", False)
    file_size = result.get("file_size_bytes", 0)
    has_chicago = result.get("has_chicago_string", False)

    if not file_exists:
        return {
            "passed": False, 
            "score": 0, 
            "feedback": "Target file chicago_zoning.ng3 was not saved."
        }
        
    if not file_created:
        feedback_parts.append("Warning: File does not appear to be created during task timeframe.")
    elif file_size > 1000:
        score += 20
        feedback_parts.append("Target file successfully saved.")
    else:
        feedback_parts.append("Target file saved but is abnormally small.")

    if has_chicago:
        score += 15
        feedback_parts.append("Location successfully set to Chicago (verified via file contents).")
    else:
        feedback_parts.append("Location 'Chicago' not found in project file.")

    # 2. VLM Trajectory Checks
    try:
        from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
        frames = sample_trajectory_frames(traj, n=4)
        final_img = get_final_screenshot(traj)
        
        vlm_images = frames + [final_img] if final_img else frames
        
        if not vlm_images:
            return {"passed": False, "score": score, "feedback": "No images available for VLM verification."}
            
        vlm_response = query_vlm(images=vlm_images, prompt=VLM_PROMPT)
        
        if vlm_response.get("success"):
            vlm_parsed = vlm_response.get("parsed", {})
            
            building_reduced = vlm_parsed.get("tallest_building_height_reduced", False)
            panels_added = vlm_parsed.get("solar_panels_on_shortest_building", False)
            date_set = vlm_parsed.get("date_set_to_dec_21", False)
            
            if building_reduced:
                score += 25
                feedback_parts.append("Tallest building height reduction verified visually.")
            else:
                feedback_parts.append("Tallest building does not appear reduced in height.")
                
            if panels_added:
                score += 25
                feedback_parts.append("Solar panels on shortest building verified visually.")
            else:
                feedback_parts.append("Solar panels on shortest building not detected.")
                
            if date_set:
                score += 15
                feedback_parts.append("Date change to Dec 21 verified visually.")
            else:
                feedback_parts.append("Date change not visible in UI.")
                
        else:
            feedback_parts.append("VLM query failed, visual criteria could not be scored.")
            
    except Exception as e:
        feedback_parts.append(f"Error during VLM processing: {e}")

    # 3. Final Evaluation
    # Pass threshold is 75 points. The agent must have the file + building reduced + panels added.
    key_criteria_met = file_exists and file_size > 1000 and (score >= 70)
    passed = key_criteria_met and score >= 75
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }