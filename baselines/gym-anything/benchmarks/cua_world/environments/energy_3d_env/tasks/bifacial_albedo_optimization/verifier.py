#!/usr/bin/env python3
import os
import json
import tempfile
import logging
import csv

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_bifacial_optimization(traj, env_info, task_info):
    """
    Verifies bifacial solar array optimization in Energy3D using multiple independent checks.
    Combines timestamp anti-gaming, CSV parsing, .ng3 inspection, and VLM trajectory logic.
    """
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # 1. Check exported metadata JSON
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

    task_start = result.get("task_start", 0)
    ng3_exists = result.get("ng3_exists", False)
    ng3_mtime = result.get("ng3_mtime", 0)
    csv_exists = result.get("csv_exists", False)
    csv_mtime = result.get("csv_mtime", 0)
    
    # 2. Score file outputs
    if ng3_exists and ng3_mtime > task_start:
        score += 20
        feedback_parts.append("Saved .ng3 project file")
    elif ng3_exists:
        feedback_parts.append("Found .ng3 but not modified during task (Stale Data)")
        
    if csv_exists and csv_mtime > task_start:
        score += 15
        feedback_parts.append("Exported yield CSV")
    elif csv_exists:
        feedback_parts.append("Found CSV but not modified during task (Stale Data)")

    # 3. Check exported CSV structure/contents
    if csv_exists and csv_mtime > task_start:
        temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/bifacial_yield.csv", temp_csv.name)
            with open(temp_csv.name, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                rows = list(reader)
                if len(rows) >= 10:  # Allow header rows + 12 months data
                    score += 15
                    feedback_parts.append("Valid CSV data structure")
                else:
                    feedback_parts.append("CSV lacks sufficient data rows")
        except Exception as e:
            feedback_parts.append("Failed to parse CSV")
        finally:
            if os.path.exists(temp_csv.name):
                os.unlink(temp_csv.name)
                
    # 4. Keyword search in Java-serialized NG3
    if result.get("ng3_has_bifacial", False):
        score += 5
        feedback_parts.append("Bifacial property localized in NG3")
    if result.get("ng3_has_albedo", False):
        score += 5
        feedback_parts.append("Albedo property localized in NG3")

    # 5. Visual/Process Trajectory Verification (VLM)
    query_vlm = env_info.get('query_vlm')
    
    if query_vlm:
        frames = sample_trajectory_frames(traj, n=6)
        final = get_final_screenshot(traj)
        images = frames + [final] if final else frames
        
        if images:
            vlm_prompt = """You are verifying an Energy3D solar design workflow.
TASK: Upgrade solar array to Bifacial panels, change rack height to 2.5m, change foundation Albedo to 0.65, and run annual yield analysis.

Review these trajectory frames from the session and determine:
1. Did the user select the solar panels and open the property window/menu to change them to 'Bifacial'?
2. Did the user change the rack height or pole height (e.g. to 2.5m)?
3. Did the user select the foundation and change its Albedo (to 0.65)?
4. Did the user run an Annual Yield Analysis (indicated by a progress bar or a yield graph popup)?

Respond strictly in JSON format:
{
    "changed_bifacial": true/false,
    "changed_height": true/false,
    "changed_albedo": true/false,
    "ran_yield_analysis": true/false
}"""
            vlm_res = query_vlm(prompt=vlm_prompt, images=images)
            if vlm_res.get("success"):
                parsed = vlm_res.get("parsed", {})
                if parsed.get("changed_bifacial", False):
                    score += 10
                    feedback_parts.append("VLM: Bifacial property modified")
                if parsed.get("changed_height", False):
                    score += 10
                    feedback_parts.append("VLM: Rack height modified")
                if parsed.get("changed_albedo", False):
                    score += 10
                    feedback_parts.append("VLM: Albedo modified")
                if parsed.get("ran_yield_analysis", False):
                    score += 10
                    feedback_parts.append("VLM: Analysis executed")
            else:
                feedback_parts.append(f"VLM verification failed: {vlm_res.get('error', 'unknown')}")
        else:
            feedback_parts.append("No screenshots available for VLM verification")
    else:
        feedback_parts.append("VLM query function unavailable in environment")
            
    passed = score >= 75
    return {"passed": passed, "score": score, "feedback": ", ".join(feedback_parts)}