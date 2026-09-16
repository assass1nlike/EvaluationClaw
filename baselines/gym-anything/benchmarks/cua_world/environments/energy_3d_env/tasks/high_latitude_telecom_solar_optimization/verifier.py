#!/usr/bin/env python3
"""
Verifier for high_latitude_telecom_solar_optimization

Verification Strategy:
1. Programmatic File Check: NG3 project file and CSV yield data exist and were created during the task.
2. Programmatic Physics Check: The CSV is parsed. A winter solstice day (Dec 21) in Anchorage (Lat 61.2) 
   has roughly 5.5 hours of daylight. We verify that the yield curve reflects this physical reality 
   (only ~5-7 rows with positive yield), which proves the agent correctly set BOTH the location and the date.
3. VLM Verification: Uses trajectory frames to verify the visual UI components (Tilt angle set to ~75, 
   row spacing physically widened in the 3D viewer).
"""

import os
import json
import csv
import logging
import tempfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating a user's performance in the Energy3D application for a solar array optimization task.

TASK REQUIREMENTS:
1. Location set to Anchorage, AK.
2. Date set to December 21 (Winter Solstice).
3. Solar racks tilted steeply (to approximately 75 degrees).
4. Distance between solar rack rows increased to prevent long shadows.
5. Daily Yield Analysis graph generated.

Examine these trajectory screenshots. Based on the sequence of actions and the final state, evaluate:
1. Did the user tilt the solar racks very steeply? (Look at the 3D model or the properties window).
2. Did the user increase the spacing between the rows of solar racks compared to their original tight packing? (Look at the gaps between the rows in the 3D viewer).
3. Did the user run a simulation resulting in a graph window appearing?

Respond strictly in the following JSON format:
{
    "steep_tilt_applied": true/false,
    "row_spacing_increased": true/false,
    "analysis_graph_visible": true/false,
    "confidence": "high/medium/low",
    "reasoning": "brief explanation"
}
"""

def extract_trajectory_frames(traj, max_frames=5):
    """Safely extract a subset of frames from the trajectory."""
    frames = traj.get('frames', [])
    if not frames:
        return []
    step = max(1, len(frames) // max_frames)
    return [f for i, f in enumerate(frames) if i % step == 0][:max_frames]

def get_final_screenshot(traj):
    """Safely extract the final screenshot from the trajectory."""
    frames = traj.get('frames', [])
    return frames[-1] if frames else None

def parse_yield_csv(csv_path):
    """
    Parses the Energy3D CSV export.
    Returns (total_rows, non_zero_yield_rows).
    A non-zero yield row is one where any of the panel values is > 0.
    """
    total_rows = 0
    non_zero_rows = 0
    
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            
            for row in reader:
                if not row or len(row) < 2:
                    continue
                total_rows += 1
                
                # Check columns after the Time column (index 0)
                is_producing = False
                for val in row[1:]:
                    try:
                        if float(val.strip()) > 0.05: # Threshold to ignore nighttime noise
                            is_producing = True
                            break
                    except ValueError:
                        pass
                
                if is_producing:
                    non_zero_rows += 1
                    
    except Exception as e:
        logger.error(f"Failed to parse CSV: {e}")
        
    return total_rows, non_zero_rows

def verify_telecom_solar_optimization(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # 1. READ EXPORTED RESULT JSON
    temp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    result = {}
    try:
        copy_from_env("/tmp/task_result.json", temp_json.name)
        with open(temp_json.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        logger.error(f"Error reading task result: {e}")
    finally:
        if os.path.exists(temp_json.name):
            os.unlink(temp_json.name)

    # 2. FILE CHECKS (20 points)
    ng3_exists = result.get('ng3_exists', False)
    csv_exists = result.get('csv_exists', False)
    
    if ng3_exists and result.get('ng3_created_during_task', False):
        score += 10
        feedback_parts.append("Project saved")
    else:
        feedback_parts.append("Project file not saved or unmodified")
        
    if csv_exists and result.get('csv_created_during_task', False):
        score += 10
        feedback_parts.append("CSV exported")
    else:
        feedback_parts.append("Yield CSV not exported")
        
    # Early exit if CSV is missing since physical logic checks depend on it
    if not csv_exists:
        return {
            "passed": False,
            "score": score,
            "feedback": ", ".join(feedback_parts) + " - Task requires CSV export to evaluate physics."
        }

    # 3. CSV PHYSICS CHECK (40 points)
    # Copy the CSV file to analyze
    temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
    try:
        copy_from_env("/tmp/yield_export.csv", temp_csv.name)
        total_rows, sunny_rows = parse_yield_csv(temp_csv.name)
        
        # Anchorage on Dec 21 gets ~5.5 hours of sunlight. 
        # Energy3D usually samples hourly or half-hourly.
        # If sunny_rows is between 3 and 8 (assuming hourly/half-hourly sampling), 
        # it strongly proves they successfully set both Location and Date.
        # If they left it on summer, it would be 15-20 hours.
        if total_rows > 0:
            logger.info(f"CSV Analysis: {sunny_rows} producing hours out of {total_rows} total rows.")
            if 1 <= sunny_rows <= 10:
                score += 40
                feedback_parts.append(f"Physics check passed: CSV shows short daylight hours ({sunny_rows} rows), confirming Anchorage Winter Solstice.")
            elif sunny_rows > 10:
                feedback_parts.append(f"Physics check failed: CSV shows long daylight hours ({sunny_rows} rows). Date or Location was not correctly set to Anchorage winter.")
            else:
                feedback_parts.append("Physics check failed: No positive yield found. Racks might be fully shaded or broken.")
    except Exception as e:
        logger.error(f"CSV copy/parse error: {e}")
    finally:
        if os.path.exists(temp_csv.name):
            os.unlink(temp_csv.name)

    # 4. VLM VISUAL CHECK (40 points)
    if query_vlm:
        frames = extract_trajectory_frames(traj, max_frames=4)
        final = get_final_screenshot(traj)
        images = frames + [final] if final else frames
        
        if images:
            vlm_resp = query_vlm(prompt=VLM_PROMPT, images=images)
            if vlm_resp.get("success"):
                parsed = vlm_resp.get("parsed", {})
                
                if parsed.get("steep_tilt_applied"):
                    score += 15
                    feedback_parts.append("VLM: Racks tilted steeply")
                else:
                    feedback_parts.append("VLM: Racks not tilted appropriately")
                    
                if parsed.get("row_spacing_increased"):
                    score += 15
                    feedback_parts.append("VLM: Row spacing increased")
                else:
                    feedback_parts.append("VLM: Row spacing not widened")
                    
                if parsed.get("analysis_graph_visible"):
                    score += 10
                    feedback_parts.append("VLM: Analysis graph detected")
            else:
                feedback_parts.append("VLM Error")
                logger.error(f"VLM verification failed: {vlm_resp.get('error')}")

    # Pass threshold: 70
    passed = score >= 70
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }