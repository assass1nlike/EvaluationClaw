#!/usr/bin/env python3
"""
Verifier for polar_station_midnight_sun_array task.
Combines programmatic CSV verification with VLM trajectory verification.
"""

import json
import os
import tempfile
import logging
import csv
from typing import Dict, Any

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying if an agent successfully designed a polar solar array in Energy3D.
Task requirements:
1. Geographic location (latitude) must be set to 78° N (near the North Pole). Look for the map or properties showing 78 degrees.
2. The date must be set to June 21 (Summer Solstice). Look for the date slider/calendar.
3. A solar array (solar panels or racks) must be added to the scene.
4. Constraint: No panels may be flat. Panels must be tilted (e.g. >= 30 degrees) OR use active solar tracking to shed snow.

Review these screenshots from the agent's workflow.
Respond in JSON format:
{
  "latitude_set_to_polar": true/false,
  "date_set_to_june_21": true/false,
  "solar_array_added": true/false,
  "panels_tilted_or_tracking": true/false,
  "confidence": "low" | "medium" | "high",
  "reasoning": "explain what you see in the UI"
}
"""

def verify_polar_station_array(traj: Dict[str, Any], env_info: Dict[str, Any], task_info: Dict[str, Any]) -> Dict[str, Any]:
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # 1. READ TASK JSON RESULT
    temp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/polar_task_result.json", temp_json.name)
        with open(temp_json.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result metadata: {e}"}
    finally:
        if os.path.exists(temp_json.name):
            os.unlink(temp_json.name)

    project_exists = result.get('project_exists', False)
    project_modified = result.get('project_modified', False)
    csv_exists = result.get('csv_exists', False)
    csv_modified = result.get('csv_modified', False)

    # Grading project save
    if project_exists and project_modified:
        score += 10
        feedback_parts.append("Project saved successfully")
    elif project_exists:
        feedback_parts.append("Project exists but was not modified")
    else:
        feedback_parts.append("Project not saved")

    # Grading CSV Export
    if csv_exists and csv_modified:
        score += 15
        feedback_parts.append("CSV exported successfully")
    elif csv_exists:
        feedback_parts.append("CSV exists but was not newly exported")
    else:
        feedback_parts.append("CSV not exported")

    # 2. CHECK CSV CONTENTS PROGRAMMATICALLY (24-hour yield check)
    csv_score = 0
    if csv_exists:
        temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/midnight_sun_yield.csv", temp_csv.name)
            with open(temp_csv.name, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                headers = next(reader, [])
                
                # Determine which column holds the solar yield
                yield_col = 1
                for i, h in enumerate(headers):
                    if any(kw in h.lower() for kw in ['yield', 'panel', 'system', 'output']):
                        yield_col = i
                        break
                
                rows = list(reader)
                if len(rows) >= 10:
                    non_zero_count = 0
                    total_count = 0
                    for row in rows:
                        try:
                            if len(row) > yield_col:
                                val = float(row[yield_col])
                                total_count += 1
                                if val > 0.001:  # Threshold for active generation
                                    non_zero_count += 1
                        except ValueError:
                            pass
                    
                    if total_count > 0:
                        ratio = non_zero_count / total_count
                        # Expecting near 100% since it's 24 hours of sunlight
                        if ratio >= 0.90:
                            csv_score = 40
                            feedback_parts.append(f"Continuous midnight sun generation verified ({non_zero_count}/{total_count} hours active)")
                        elif ratio >= 0.50:
                            csv_score = 20
                            feedback_parts.append(f"Partial generation, array missing sun at some hours ({non_zero_count}/{total_count} hours active)")
                        else:
                            csv_score = 0
                            feedback_parts.append(f"Standard generation profile detected, failed 360-degree capture ({non_zero_count}/{total_count} hours active)")
                    else:
                        feedback_parts.append("Could not parse numeric yield values from CSV")
                else:
                    feedback_parts.append("CSV has too few rows to evaluate daily profile")
        except Exception as e:
            feedback_parts.append(f"Error analyzing CSV data: {e}")
        finally:
            if os.path.exists(temp_csv.name):
                os.unlink(temp_csv.name)
                
    score += csv_score

    # 3. VLM TRAJECTORY VERIFICATION
    vlm_score = 0
    query_vlm_func = env_info.get('query_vlm')
    if query_vlm_func:
        # Provide multiple frames across trajectory to prove settings and state
        frames = sample_trajectory_frames(traj, n=4)
        final = get_final_screenshot(traj)
        if final:
            frames.append(final)
        
        if frames:
            vlm_res = query_vlm_func(prompt=VLM_PROMPT, images=frames)
            if vlm_res.get('success'):
                parsed = vlm_res.get('parsed', {})
                if parsed.get('latitude_set_to_polar'):
                    vlm_score += 10
                    feedback_parts.append("VLM: Latitude ~78N confirmed")
                if parsed.get('date_set_to_june_21'):
                    vlm_score += 10
                    feedback_parts.append("VLM: Date June 21 confirmed")
                if parsed.get('solar_array_added') and parsed.get('panels_tilted_or_tracking'):
                    vlm_score += 15
                    feedback_parts.append("VLM: Valid steep-tilt/tracking array confirmed")
                elif parsed.get('solar_array_added'):
                    vlm_score += 5
                    feedback_parts.append("VLM: Array added but snow-shedding tilt constraint failed")
            else:
                feedback_parts.append("VLM query error")
        else:
            feedback_parts.append("No screenshots available for VLM verification")
    else:
        feedback_parts.append("VLM function not available in environment")
        
    score += vlm_score

    # Passing requires basic project/CSV generation, generation metrics passed, and minimum visual layout
    passed = score >= 70 and csv_score >= 20
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }