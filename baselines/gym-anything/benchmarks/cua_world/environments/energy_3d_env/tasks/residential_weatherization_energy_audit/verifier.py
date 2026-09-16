#!/usr/bin/env python3
"""
Verifier for residential_weatherization_energy_audit task.

Since Energy3D uses a Java-serialized binary format (.ng3) that cannot be 
easily parsed with Python without relying on external JVM processes, this 
verifier uses a robust hybrid approach:
1. Programmatic check: Ensure the requested output file was created/saved *during* the task.
2. VLM Trajectory Verification: Examines screenshots over time to prove the 
   agent actively altered the exact thermal properties and ran the analysis.
"""

import json
import os
import tempfile
import logging

# Assume framework utilities are available
try:
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
except ImportError:
    # Fallback/stubs if running outside the formal execution environment
    def sample_trajectory_frames(traj, n=5): return []
    def get_final_screenshot(traj): return None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying an Energy3D energy auditor task.
The agent was asked to weatherize a house in the software by doing the following:
1. Change the Roof U-value to 0.15
2. Change ALL Walls U-value to 0.30
3. Change ALL Windows U-value to 1.50
4. Change the Air Infiltration Rate to 0.4
5. Run the Annual Building Energy Analysis (a bar graph popup usually appears)
6. Save the file.

Review the sequence of trajectory screenshots (from start to finish). Determine if the agent showed evidence of performing these actions. You should look for properties dialogs, context menus, right-hand panel adjustments, and the analysis graph popup.

Respond with a JSON object strictly following this structure:
{
    "roof_u_value_edited": true/false,
    "walls_u_value_edited": true/false,
    "windows_u_value_edited": true/false,
    "air_infiltration_edited": true/false,
    "analysis_graph_run": true/false,
    "confidence": "low/medium/high",
    "reasoning": "brief explanation of what UI elements confirm the actions"
}
"""

def verify_weatherization(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available in environment."}

    # ==========================================
    # 1. Programmatic Checks (File Timestamps)
    # ==========================================
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read exported result: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    score = 0
    feedback_parts = []
    
    file_exists = result.get('output_exists', False)
    file_created_during_task = result.get('file_created_during_task', False)
    output_size = result.get('output_size_bytes', 0)

    if file_exists and file_created_during_task and output_size > 1000:
        score += 20
        feedback_parts.append("✅ weatherized_home.ng3 saved correctly.")
    elif file_exists:
        feedback_parts.append("❌ File exists but timestamp/size check failed (Possible anti-gaming trigger).")
    else:
        feedback_parts.append("❌ Target file weatherized_home.ng3 not saved.")

    # ==========================================
    # 2. VLM Trajectory Verification
    # ==========================================
    if not query_vlm:
        return {"passed": False, "score": score, "feedback": "VLM query not available. " + " | ".join(feedback_parts)}

    # Extract 6 frames from trajectory to capture property changing popups and workflows
    frames = sample_trajectory_frames(traj, n=6)
    final_frame = get_final_screenshot(traj)
    if final_frame and final_frame not in frames:
        frames.append(final_frame)

    if not frames:
        return {"passed": False, "score": score, "feedback": "No trajectory frames available for VLM."}

    vlm_result = query_vlm(images=frames, prompt=VLM_PROMPT)

    if not vlm_result.get("success"):
        feedback_parts.append(f"❌ VLM query failed: {vlm_result.get('error', 'unknown error')}")
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}

    parsed = vlm_result.get("parsed", {})
    logger.info(f"VLM Parsed Result: {parsed}")

    # Assess VLM results
    if parsed.get("roof_u_value_edited", False):
        score += 15
        feedback_parts.append("✅ Roof U-value updated")
    else:
        feedback_parts.append("❌ Roof U-value update not seen")

    if parsed.get("walls_u_value_edited", False):
        score += 15
        feedback_parts.append("✅ Walls U-value updated")
    else:
        feedback_parts.append("❌ Walls U-value update not seen")

    if parsed.get("windows_u_value_edited", False):
        score += 15
        feedback_parts.append("✅ Windows U-value updated")
    else:
        feedback_parts.append("❌ Windows U-value update not seen")

    if parsed.get("air_infiltration_edited", False):
        score += 15
        feedback_parts.append("✅ Air Infiltration updated")
    else:
        feedback_parts.append("❌ Air Infiltration update not seen")

    if parsed.get("analysis_graph_run", False):
        score += 20
        feedback_parts.append("✅ Annual Energy Analysis run")
    else:
        feedback_parts.append("❌ Annual Energy Analysis graph not seen")

    # ==========================================
    # 3. Final Evaluation
    # ==========================================
    # Agent must save the file properly and complete at least most of the retrofit items
    passed = score >= 75 and file_created_during_task

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts),
        "details": parsed
    }