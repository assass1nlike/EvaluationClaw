#!/usr/bin/env python3
"""
Verifier for urban_architectural_obj_export task.

Verification Strategy:
1. Programmatic Check (File Validation):
   - Confirms `proposed_city_block.obj` exists and was created during the task.
   - Checks if the OBJ file contains valid 3D geometry (vertices, faces).
   - Confirms `proposed_city_block.ng3` was saved.
2. VLM Verification (Trajectory Analysis):
   - Uses `sample_trajectory_frames` to analyze agent's workflow.
   - Checks if a new building was drawn in the center.
   - Checks if trees were hidden or removed before exporting.
"""

import os
import json
import logging
import tempfile

# Framework utilities
from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot, query_vlm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are an architectural visualizer evaluating a user's work in a 3D planning tool (Energy3D).
The user was asked to:
1. Draw a new, tall building (50m) in the central open area of the city block.
2. Hide or remove all green trees from the scene.
3. Export the 3D geometry.

You are provided with a sequence of chronological screenshots capturing their workflow.
Review these frames and determine:

1. Did the user draw a NEW building in the central open plaza area of the block? (Should appear as a tall structure where there used to be empty space).
2. Are the green trees, which are visible scattered across the block initially, completely hidden or removed in the final frames?

Respond ONLY in the following JSON format:
{
    "new_building_added": true/false,
    "trees_hidden_or_removed": true/false,
    "reasoning": "Brief explanation of what is observed in the frames."
}
"""

def verify_urban_architectural_obj_export(traj, env_info, task_info):
    """Verifies the urban model preparation and export task."""
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Verifier Error: copy_from_env not available"}

    # Fetch result JSON from the container
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to parse task_result.json: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    score = 0
    feedback_parts = []
    
    # -------------------------------------------------------------------------
    # 1. Programmatic File Checks
    # -------------------------------------------------------------------------
    
    # NG3 Check (15 pts)
    ng3_exists = result.get("ng3_exists", False)
    ng3_created = result.get("ng3_created_during_task", False)
    if ng3_exists and ng3_created:
        score += 15
        feedback_parts.append("Project saved successfully (.ng3).")
    elif ng3_exists:
        score += 5
        feedback_parts.append("Project exists but wasn't created/modified during task (.ng3).")
    else:
        feedback_parts.append("Updated project (.ng3) not saved.")

    # OBJ Export Check (20 pts)
    obj_exists = result.get("obj_exists", False)
    obj_created = result.get("obj_created_during_task", False)
    if obj_exists and obj_created:
        score += 20
        feedback_parts.append("OBJ exported successfully.")
    else:
        feedback_parts.append("OBJ export not found or not generated during task.")
        
    # OBJ Content Validity (15 pts)
    obj_vertices = int(result.get("obj_vertices", 0))
    if obj_exists and obj_vertices > 50:
        score += 15
        feedback_parts.append(f"OBJ contains valid geometry ({obj_vertices} vertices).")
    elif obj_exists:
        feedback_parts.append(f"OBJ generated but seems empty or invalid ({obj_vertices} vertices).")
        
    # Early stop if no files generated to avoid unnecessary VLM calls
    if not obj_exists:
        return {
            "passed": False,
            "score": score,
            "feedback": " | ".join(feedback_parts) + " -> Critical failure: No OBJ output found."
        }

    # -------------------------------------------------------------------------
    # 2. VLM Trajectory Verification
    # -------------------------------------------------------------------------
    frames = sample_trajectory_frames(traj, n=4)
    final_frame = get_final_screenshot(traj)
    
    if final_frame:
        frames.append(final_frame)
    else:
        logger.warning("No final screenshot found in trajectory.")

    if not frames:
        return {
            "passed": False,
            "score": score,
            "feedback": " | ".join(feedback_parts) + " -> VLM Error: No trajectory frames available."
        }
        
    vlm_result = query_vlm(prompt=VLM_PROMPT, images=frames)
    
    if not vlm_result.get("success", False):
        feedback_parts.append(f"VLM analysis failed: {vlm_result.get('error', 'unknown error')}")
    else:
        parsed = vlm_result.get("parsed", {})
        
        # New Building (25 pts)
        building_added = parsed.get("new_building_added", False)
        if building_added:
            score += 25
            feedback_parts.append("VLM confirmed new building added.")
        else:
            feedback_parts.append("VLM did not detect a new building.")
            
        # Trees Hidden/Removed (25 pts)
        trees_removed = parsed.get("trees_hidden_or_removed", False)
        if trees_removed:
            score += 25
            feedback_parts.append("VLM confirmed trees were hidden/removed.")
        else:
            feedback_parts.append("VLM detected trees are still visible.")
            
        feedback_parts.append(f"VLM Notes: {parsed.get('reasoning', '')}")

    # -------------------------------------------------------------------------
    # 3. Final Scoring
    # -------------------------------------------------------------------------
    passed = score >= 75 and obj_exists and obj_created and (vlm_result.get("parsed", {}).get("new_building_added", False))
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }