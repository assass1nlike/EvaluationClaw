#!/usr/bin/env python3
"""
Verifier for urban_rooftop_solar_assessment.

Uses a hybrid approach:
1. Programmatic file verification (checking if .ng3 and .csv were created and contain expected footprints).
2. Trajectory VLM verification to confirm qualitative spatial reasoning tasks:
   - Selecting the tallest building.
   - Using automated array design (landscape, tilted panels).
   - Actually viewing the yield analysis graph.
"""

import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are an expert verifier for an Energy3D software task.
Review these trajectory frames from the user's session and answer the following questions.

TASK REQUIREMENTS:
1. Identify the tallest building in the city block.
2. Place a solar panel array covering the flat roof of that tallest building.
3. Panels should be in Landscape orientation and visibly tilted (not perfectly flat against the roof).
4. Run an Annual Yield Analysis (look for a bar chart/line graph pop-up analyzing energy yield across months).

Based on the images, provide a JSON response:
{
    "tallest_building_targeted": true/false,
    "panels_placed_on_tallest_roof": true/false,
    "panels_in_landscape_orientation": true/false,
    "panels_are_tilted": true/false,
    "annual_yield_graph_visible": true/false,
    "reasoning": "Brief explanation of what you observed to justify the boolean values."
}
"""

def verify_rooftop_assessment(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    feedback_parts = []
    score = 0
    
    # --- 1. PROGRAMMATIC VERIFICATION ---
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

    # Check NG3 Project
    if result.get("ng3_exists") and result.get("ng3_created_during_task"):
        score += 10
        feedback_parts.append("Project correctly saved as city_block_upgraded.ng3")
    else:
        feedback_parts.append("Modified project NOT saved correctly")

    # Check Location Change
    if result.get("has_chicago_string"):
        score += 10
        feedback_parts.append("Location updated to Chicago")
    else:
        feedback_parts.append("Location string 'Chicago' not found in project file")

    # Check CSV Export
    csv_exists = result.get("csv_exists") and result.get("csv_created_during_task")
    if csv_exists:
        score += 10
        feedback_parts.append("Yield CSV exported")
        
        # Verify CSV Content
        if result.get("csv_lines", 0) >= 12:
            score += 15
            feedback_parts.append("CSV contains full annual data (>12 lines)")
        else:
            feedback_parts.append(f"CSV data incomplete (found {result.get('csv_lines', 0)} lines)")
    else:
        feedback_parts.append("Yield CSV NOT exported")

    # --- 2. VLM TRAJECTORY VERIFICATION ---
    if not query_vlm:
        feedback_parts.append("VLM query function not available")
        return {
            "passed": False,
            "score": score,
            "feedback": " | ".join(feedback_parts)
        }

    try:
        # Import framework VLM utilities
        from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
        frames = sample_trajectory_frames(traj, n=5)
        final_frame = get_final_screenshot(traj)
        
        images_to_analyze = frames
        if final_frame:
            images_to_analyze.append(final_frame)

        vlm_resp = query_vlm(prompt=VLM_PROMPT, images=images_to_analyze)
        
        if vlm_resp.get("success") and "parsed" in vlm_resp:
            parsed = vlm_resp["parsed"]
            
            # Target Selection & Array Generation
            if parsed.get("tallest_building_targeted") and parsed.get("panels_placed_on_tallest_roof"):
                score += 25
                feedback_parts.append("Solar array successfully placed on tallest building")
            else:
                feedback_parts.append("Array NOT placed on tallest building")
                
            # Orientation and Tilt Parameters
            if parsed.get("panels_in_landscape_orientation") and parsed.get("panels_are_tilted"):
                score += 15
                feedback_parts.append("Panels are properly tilted and in landscape orientation")
            else:
                feedback_parts.append("Panel configuration (tilt/orientation) missing or incorrect")
                
            # Yield Graph Verified
            if parsed.get("annual_yield_graph_visible"):
                score += 15
                feedback_parts.append("Annual Yield Analysis successfully simulated")
            else:
                feedback_parts.append("No evidence of Annual Yield Analysis being run")
                
        else:
            feedback_parts.append("VLM analysis failed to return parsed JSON")

    except Exception as e:
        feedback_parts.append(f"Error during VLM verification: {e}")

    # --- 3. FINAL EVALUATION ---
    # To pass, the agent must have scored >= 70 AND exported the CSV AND placed panels on the tallest roof
    tallest_targeted = (score >= 25 and "successfully placed on tallest building" in " | ".join(feedback_parts))
    passed = score >= 70 and csv_exists and tallest_targeted

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }