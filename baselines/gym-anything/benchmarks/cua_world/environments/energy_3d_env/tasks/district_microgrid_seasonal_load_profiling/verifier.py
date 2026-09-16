#!/usr/bin/env python3
"""
Verifier for the district microgrid seasonal load profiling task.

This verifier checks:
1. Did the agent save the project file? (10 pts)
2. Does the project file reflect the requested location "Houston, TX"? (10 pts)
3. Did the agent export the August CSV with valid data? (15 pts)
4. Did the agent export the January CSV with valid data? (15 pts)
5. ANTI-GAMING: Are the August and January files numerically different? (25 pts)
6. VLM Trajectory: Did the agent visibly interact with the Energy3D Analysis windows? (25 pts)
"""

import os
import json
import tempfile
import logging
import hashlib
from typing import Dict, Any

from gym_anything.vlm import sample_trajectory_frames, query_vlm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are an AI grader verifying a user's workflow in the Energy3D application.
The user was asked to run a "Daily Energy Analysis" for an urban microgrid block.

Please review these trajectory frames (screenshots taken during their session). 
Look closely for:
1. Is the "Daily Energy Analysis" graph/window visible at any point? (It typically features a line chart or bar chart displaying hourly energy data).
2. Is there evidence they navigated the "Analysis" menu or adjusted calendar dates/locations?

Respond in pure JSON format:
{
    "analysis_graph_visible": true/false,
    "workflow_evidence": true/false,
    "confidence": "low"/"medium"/"high",
    "reasoning": "brief explanation"
}
"""

def verify_district_microgrid_profiling(traj: Dict[str, Any], env_info: Dict[str, Any], task_info: Dict[str, Any]) -> Dict[str, Any]:
    score = 0
    feedback_parts = []
    
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "System error: copy_from_env not available"}

    # ==========================================
    # 1. Read programmatic task results
    # ==========================================
    temp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_json.name)
        with open(temp_json.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read task result: {e}"}
    finally:
        if os.path.exists(temp_json.name):
            os.unlink(temp_json.name)

    project_data = result.get("project_file", {})
    aug_data = result.get("august_csv", {})
    jan_data = result.get("january_csv", {})
    
    project_exists = project_data.get("exists", False)
    location_found = project_data.get("location_houston_found", False)
    
    aug_exists = aug_data.get("exists", False)
    aug_lines = aug_data.get("lines", 0)
    
    jan_exists = jan_data.get("exists", False)
    jan_lines = jan_data.get("lines", 0)

    # Project checks
    if project_exists:
        score += 10
        feedback_parts.append("Project saved")
        if location_found:
            score += 10
            feedback_parts.append("Location correctly set to Houston")
        else:
            feedback_parts.append("Houston location data not found in project file")
    else:
        feedback_parts.append("Target project file not saved")

    # CSV checks
    if aug_exists and aug_lines >= 20:
        score += 15
        feedback_parts.append("August CSV exported")
    elif aug_exists:
        score += 5
        feedback_parts.append("August CSV found but incomplete")
    else:
        feedback_parts.append("August CSV missing")

    if jan_exists and jan_lines >= 20:
        score += 15
        feedback_parts.append("January CSV exported")
    elif jan_exists:
        score += 5
        feedback_parts.append("January CSV found but incomplete")
    else:
        feedback_parts.append("January CSV missing")

    # ==========================================
    # 2. Anti-Gaming: Ensure CSVs differ
    # ==========================================
    if (aug_exists and aug_lines >= 20) and (jan_exists and jan_lines >= 20):
        try:
            # We fetch both CSV files to compare their contents
            temp_aug = tempfile.NamedTemporaryFile(delete=False)
            temp_jan = tempfile.NamedTemporaryFile(delete=False)
            
            copy_from_env("/tmp/houston_microgrid_august.csv", temp_aug.name)
            copy_from_env("/tmp/houston_microgrid_january.csv", temp_jan.name)
            
            with open(temp_aug.name, 'rb') as f1, open(temp_jan.name, 'rb') as f2:
                aug_hash = hashlib.md5(f1.read()).hexdigest()
                jan_hash = hashlib.md5(f2.read()).hexdigest()
                
            if aug_hash != jan_hash:
                score += 25
                feedback_parts.append("Seasonal variation verified (CSVs differ)")
            else:
                feedback_parts.append("ANTI-GAMING FAILED: August and January CSVs are identical")
        except Exception as e:
            logger.error(f"Error checking CSV difference: {e}")
            feedback_parts.append("Error comparing CSV contents")
        finally:
            if os.path.exists(temp_aug.name):
                os.unlink(temp_aug.name)
            if os.path.exists(temp_jan.name):
                os.unlink(temp_jan.name)
    else:
        feedback_parts.append("Skipped seasonal variation check (missing valid CSVs)")

    # ==========================================
    # 3. VLM Trajectory Verification
    # ==========================================
    vlm_points = 0
    try:
        frames = sample_trajectory_frames(traj, n=6)
        if frames:
            vlm_result = query_vlm(images=frames, prompt=VLM_PROMPT)
            if vlm_result and vlm_result.get("success"):
                parsed = vlm_result.get("parsed", {})
                graph_visible = parsed.get("analysis_graph_visible", False)
                workflow = parsed.get("workflow_evidence", False)
                
                if graph_visible:
                    vlm_points += 15
                if workflow:
                    vlm_points += 10
                    
                if vlm_points > 0:
                    feedback_parts.append(f"VLM trajectory verification passed ({vlm_points}/25 pts)")
                else:
                    feedback_parts.append("VLM found no evidence of analysis workflow")
            else:
                feedback_parts.append("VLM query failed")
        else:
            feedback_parts.append("No trajectory frames for VLM")
    except Exception as e:
        logger.error(f"VLM verification error: {e}")
        feedback_parts.append("VLM verification error")

    score += vlm_points

    # ==========================================
    # 4. Finalizing
    # ==========================================
    key_criteria = project_exists and location_found and aug_exists and jan_exists
    passed = score >= 70 and key_criteria

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }