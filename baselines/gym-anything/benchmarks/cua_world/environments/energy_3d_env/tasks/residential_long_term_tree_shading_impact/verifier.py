#!/usr/bin/env python3
"""
Verifier for Residential Long-Term Tree Shading Impact task.

VERIFICATION STRATEGY:
1. File Checks: Ensure yield_current.csv, yield_year_20.csv, and tree_shading_study.ng3 were created during the task.
2. Data Logic: Parse the CSV files to calculate total solar yield. The yield in year 20 MUST be strictly less than the current yield due to tree shading.
3. VLM Verification: Inspect trajectory frames to confirm physical placement of panels and trees, and that tree height was actively modified between the two simulation runs.
"""

import json
import os
import tempfile
import csv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# VLM Prompt specifically querying for workflow progression and scene content
VLM_PROMPT = """You are verifying an agent's completion of a 3D building energy simulation task in Energy3D.

Look at the provided trajectory frames and the final screenshot and answer the following:
1. Did the agent place solar panels on the roof of the house?
2. Did the agent place multiple trees (like pine trees) near the house?
3. Looking across the sequence of frames, do the trees significantly increase in height at some point (e.g., starting small and becoming very tall)?
4. Did the agent open a window or graph related to "Annual Yield Analysis" or "Daily Yield Analysis"?

Respond strictly in JSON format:
{
    "has_solar_panels": true/false,
    "has_trees": true/false,
    "trees_changed_height": true/false,
    "analysis_run": true/false
}
"""

def sum_csv_numeric_values(filepath):
    """Safely extracts all numeric floating point values from a CSV and returns their sum."""
    total = 0.0
    count = 0
    try:
        with open(filepath, 'r') as f:
            reader = csv.reader(f)
            for row in reader:
                for cell in row:
                    try:
                        val = float(cell)
                        total += val
                        count += 1
                    except ValueError:
                        pass
    except Exception as e:
        logger.warning(f"Failed to read CSV {filepath}: {e}")
    return total, count

def verify_shading_impact(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # 1. Load basic file metadata
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

    csv1_info = result.get("csv1", {})
    csv2_info = result.get("csv2", {})
    ng3_info = result.get("ng3", {})

    files_valid = True
    if csv1_info.get("exists") and csv1_info.get("created_during_task"):
        score += 10
        feedback_parts.append("Current yield CSV saved")
    else:
        files_valid = False
        feedback_parts.append("Current yield CSV missing or not newly created")

    if csv2_info.get("exists") and csv2_info.get("created_during_task"):
        score += 10
        feedback_parts.append("Year 20 yield CSV saved")
    else:
        files_valid = False
        feedback_parts.append("Year 20 yield CSV missing or not newly created")

    if ng3_info.get("exists") and ng3_info.get("created_during_task"):
        score += 10
        feedback_parts.append("Project .ng3 file saved")
    else:
        feedback_parts.append("Project file not saved (missing NG3)")

    # 2. Extract and Validate CSV Data
    yield1_sum = 0
    yield2_sum = 0
    degradation_verified = False

    if files_valid:
        temp_csv1 = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        temp_csv2 = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/yield_current.csv", temp_csv1.name)
            copy_from_env("/home/ga/Documents/Energy3D/yield_year_20.csv", temp_csv2.name)
            
            yield1_sum, count1 = sum_csv_numeric_values(temp_csv1.name)
            yield2_sum, count2 = sum_csv_numeric_values(temp_csv2.name)

            if count1 > 0 and count2 > 0:
                score += 10
                feedback_parts.append("CSV files contain numeric data")
                
                # Check degradation
                if 0 < yield2_sum < yield1_sum:
                    score += 20
                    degradation_verified = True
                    feedback_parts.append(f"Yield degradation verified (Cur: {yield1_sum:.1f}, Yr20: {yield2_sum:.1f})")
                elif yield2_sum >= yield1_sum:
                    feedback_parts.append(f"No shading effect found (Yr20 {yield2_sum:.1f} >= Cur {yield1_sum:.1f})")
                else:
                    feedback_parts.append("Invalid yield values extracted")
            else:
                feedback_parts.append("CSV files do not contain numeric yield data")

        except Exception as e:
            feedback_parts.append(f"Failed to copy/read CSVs: {e}")
        finally:
            if os.path.exists(temp_csv1.name): os.unlink(temp_csv1.name)
            if os.path.exists(temp_csv2.name): os.unlink(temp_csv2.name)

    # 3. VLM Verification on Trajectory
    if query_vlm:
        try:
            # Import dynamically to avoid loading issues in host if not available
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            frames = sample_trajectory_frames(traj, n=4)
            final = get_final_screenshot(traj)
            images = frames + [final] if final else frames
            
            if images:
                vlm_resp = query_vlm(prompt=VLM_PROMPT, images=images)
                if vlm_resp and vlm_resp.get('success'):
                    parsed = vlm_resp.get('parsed', {})
                    if parsed.get("has_solar_panels"):
                        score += 10
                        feedback_parts.append("VLM: Panels detected")
                    if parsed.get("has_trees"):
                        score += 10
                        feedback_parts.append("VLM: Trees detected")
                    if parsed.get("trees_changed_height"):
                        score += 10
                        feedback_parts.append("VLM: Tree growth detected")
                    if parsed.get("analysis_run"):
                        score += 10
                        feedback_parts.append("VLM: Yield analysis detected")
                else:
                    feedback_parts.append("VLM query failed")
            else:
                feedback_parts.append("No frames available for VLM")
        except Exception as e:
            feedback_parts.append(f"VLM process error: {e}")
    else:
        feedback_parts.append("VLM function not available")

    # Pass condition: must have verified data degradation and core file exports
    key_criteria_met = files_valid and degradation_verified
    passed = score >= 70 and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }