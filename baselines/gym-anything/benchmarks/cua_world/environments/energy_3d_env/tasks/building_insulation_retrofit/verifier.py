#!/usr/bin/env python3
"""
Verifier for building_insulation_retrofit.

Verification Strategy:
1. File Checks: Verifies that the `.ng3` project and `.png` graph files were created 
   and modified *after* the task start (Anti-gaming).
2. Trajectory VLM: Uses the trajectory frames to verify that the agent actively 
   opened the properties panel, navigated the 3D scene, and set the U-values for 
   Roof (0.11) and Walls (0.24). (Needed because Energy3D `.ng3` files are 
   Java-serialized binaries that are difficult to parse perfectly in pure Python).
3. Screenshot VLM: Checks that the exported `retrofit_analysis.png` actually contains
   the Daily Energy Analysis graph.
"""

import json
import os
import tempfile
import logging

# Import VLM utilities
try:
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
except ImportError:
    # Fallback/stub for local testing if gym_anything is unavailable
    def sample_trajectory_frames(traj, n=5): return []
    def get_final_screenshot(traj): return None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_GRAPH_PROMPT = """
You are an expert verifier checking a screenshot output from an Energy3D analysis task.
The user was asked to run a "Daily Energy Analysis" and save the screenshot.

Please analyze this image and reply in JSON format:
{
    "is_analysis_graph": true/false,
    "reasoning": "Explain if this looks like a graph/chart showing energy analysis (heating/cooling/net) vs time."
}
"""

VLM_TRAJECTORY_PROMPT = """
You are verifying an agent's workflow in Energy3D.
The agent's task was to:
1. Select the Roof and change its U-value to 0.11
2. Select the Walls and change their U-values to 0.24

Look through these trajectory frames of the agent's screen.
Reply in JSON format:
{
    "roof_u_value_changed": true/false,
    "wall_u_value_changed": true/false,
    "reasoning": "Did you observe the agent selecting a roof and wall? Did you see '0.11' and '0.24' being entered into property panels for U-value?"
}
"""

def verify_building_insulation_retrofit(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "System error: copy_from_env function not available"}

    # ==========================================
    # 1. READ RESULT DATA
    # ==========================================
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    result = {}
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read task results: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    score = 0
    feedback_parts = []
    
    # 1a. Verify NG3 Project File
    if result.get("ng3_exists") and result.get("ng3_created_after_start"):
        if result.get("ng3_size_bytes", 0) > 1000:
            score += 10
            feedback_parts.append("Project file saved correctly.")
        else:
            feedback_parts.append("Project file exists but is suspiciously small (corrupted).")
    else:
        feedback_parts.append("Project file not saved or was not created during the task.")

    # 1b. Verify PNG Screenshot File
    png_file_valid = False
    if result.get("png_exists") and result.get("png_created_after_start"):
        if result.get("png_size_bytes", 0) > 5000:
            score += 10
            feedback_parts.append("Analysis screenshot saved.")
            png_file_valid = True
        else:
            feedback_parts.append("Analysis screenshot exists but is suspiciously small.")
    else:
        feedback_parts.append("Analysis screenshot not saved.")

    # ==========================================
    # 2. VLM VERIFICATION - GRAPH SCREENSHOT
    # ==========================================
    graph_is_valid = False
    if png_file_valid and query_vlm:
        temp_png = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/retrofit_analysis.png", temp_png.name)
            
            vlm_graph_res = query_vlm(
                prompt=VLM_GRAPH_PROMPT,
                images=[temp_png.name]
            )
            
            if vlm_graph_res.get("success"):
                parsed = vlm_graph_res.get("parsed", {})
                if parsed.get("is_analysis_graph", False):
                    score += 30
                    graph_is_valid = True
                    feedback_parts.append("VLM confirmed Daily Energy Analysis graph is valid.")
                else:
                    feedback_parts.append(f"VLM rejected graph screenshot: {parsed.get('reasoning', '')}")
            else:
                feedback_parts.append("VLM query for graph evaluation failed.")
        except Exception as e:
            logger.error(f"Error querying VLM for graph: {e}")
        finally:
            if os.path.exists(temp_png.name):
                os.unlink(temp_png.name)

    # ==========================================
    # 3. VLM VERIFICATION - TRAJECTORY (U-VALUES)
    # ==========================================
    roof_changed = False
    wall_changed = False
    
    if query_vlm:
        frames = sample_trajectory_frames(traj, n=10)
        final_frame = get_final_screenshot(traj)
        if final_frame:
            frames.append(final_frame)
            
        if frames:
            vlm_traj_res = query_vlm(
                prompt=VLM_TRAJECTORY_PROMPT,
                images=frames
            )
            
            if vlm_traj_res.get("success"):
                parsed = vlm_traj_res.get("parsed", {})
                roof_changed = parsed.get("roof_u_value_changed", False)
                wall_changed = parsed.get("wall_u_value_changed", False)
                
                if roof_changed:
                    score += 25
                    feedback_parts.append("VLM confirmed Roof U-value updated to 0.11.")
                else:
                    feedback_parts.append("VLM did not observe Roof U-value updated to 0.11.")
                    
                if wall_changed:
                    score += 25
                    feedback_parts.append("VLM confirmed Wall U-value updated to 0.24.")
                else:
                    feedback_parts.append("VLM did not observe Wall U-values updated to 0.24.")
            else:
                feedback_parts.append("VLM query for trajectory evaluation failed.")

    # Determine pass/fail
    # Must achieve at least 70 points AND both key property changes must be detected
    passed = (score >= 70) and roof_changed and wall_changed

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }