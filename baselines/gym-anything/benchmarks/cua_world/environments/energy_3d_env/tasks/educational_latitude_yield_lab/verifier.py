#!/usr/bin/env python3
"""
Verifier for Educational Latitude Yield Lab task.

Multi-Criteria Verification:
1. CSV File Creation: Exists and was created during the task (Anti-gaming).
2. CSV Formatting: Contains the exact required headers.
3. CSV Content: Contains rows for Boston, Miami, and Seattle.
4. Data Validity: The extracted values are numeric, > 0, and logically valid (Annual > December).
5. VLM Trajectory: Verifies the agent actually interacted with the location menu and yield analysis graph.
"""

import json
import os
import csv
import tempfile
import logging
from typing import Dict, Any

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot, query_vlm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying an agent's completion of a simulation task in the Energy3D software.
The agent was asked to change the geographical location of a solar array to multiple different cities and run an "Annual Yield Analysis" for each.

Look at these screenshots sampled from the agent's session trajectory. 
Determine if the agent performed the required actions:
1. Did the agent open a location/city selection menu or dialog at any point?
2. Did the agent successfully generate an "Annual Yield Analysis" graph/chart (typically a bar chart showing monthly energy yields)?

Respond in JSON format:
{
    "location_menu_opened": true/false,
    "yield_analysis_run": true/false,
    "confidence": "low"/"medium"/"high",
    "reasoning": "Brief explanation of what evidence you see in the frames."
}
"""

def verify_latitude_yield_lab(traj: Dict[str, Any], env_info: Dict[str, Any], task_info: Dict[str, Any]) -> Dict[str, Any]:
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    feedback_parts = []
    score = 0
    max_score = 100

    # 1. Retrieve the metadata JSON
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

    csv_exists = result.get('csv_exists', False)
    csv_created_during_task = result.get('csv_created_during_task', False)

    # Scoring Criteria 1 & 2: File exists and created during task (15 points)
    if not csv_exists:
        return {
            "passed": False,
            "score": 0,
            "feedback": "❌ Required CSV file 'latitude_lab_results.csv' was not found."
        }
    
    if csv_created_during_task:
        score += 15
        feedback_parts.append("✅ CSV created during session")
    else:
        feedback_parts.append("❌ CSV file existed before task (possible cheating)")
        return {"passed": False, "score": 0, "feedback": " | ".join(feedback_parts)}

    # 2. Retrieve and parse the CSV
    temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
    csv_valid = False
    try:
        copy_from_env("/tmp/latitude_lab_results.csv", temp_csv.name)
        with open(temp_csv.name, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            rows = [row for row in reader if any(cell.strip() for cell in row)]  # filter empty rows
            
            if len(rows) > 0:
                headers = [h.strip() for h in rows[0]]
                data_rows = rows[1:]
                
                # Scoring Criteria 3: Check Headers (15 points)
                expected_headers = task_info.get('metadata', {}).get('expected_headers', ["City", "Annual_Yield_kWh", "December_Yield_kWh"])
                if headers == expected_headers:
                    score += 15
                    feedback_parts.append("✅ Correct CSV headers")
                else:
                    feedback_parts.append(f"❌ Incorrect headers. Expected: {expected_headers}, Got: {headers}")

                # Scoring Criteria 4: Content and Values (35 points)
                found_cities = []
                valid_data = True
                
                for row in data_rows:
                    if len(row) >= 3:
                        city = row[0].strip().lower()
                        # Extract raw strings, clean them, convert to float
                        try:
                            annual_val = float(row[1].replace(',', '').strip())
                            december_val = float(row[2].replace(',', '').strip())
                            
                            # Logically, annual must be > december and > 0
                            if annual_val > 0 and december_val > 0 and annual_val > december_val:
                                # Identify city
                                if 'boston' in city: found_cities.append('boston')
                                elif 'miami' in city: found_cities.append('miami')
                                elif 'seattle' in city: found_cities.append('seattle')
                            else:
                                valid_data = False
                        except ValueError:
                            valid_data = False

                expected_cities = set(task_info.get('metadata', {}).get('expected_cities', ["boston", "miami", "seattle"]))
                missing_cities = expected_cities - set(found_cities)
                
                if len(missing_cities) == 0:
                    score += 20
                    feedback_parts.append("✅ Found data for all required cities")
                else:
                    feedback_parts.append(f"❌ Missing or invalid data for cities: {missing_cities}")
                
                if valid_data and len(data_rows) >= 3:
                    score += 15
                    feedback_parts.append("✅ Yield data is numeric and logically valid")
                else:
                    feedback_parts.append("❌ Yield data contained invalid formats or impossible values")
                    
            else:
                feedback_parts.append("❌ CSV file is empty")
                
    except Exception as e:
        feedback_parts.append(f"❌ Failed to parse CSV: {e}")
    finally:
        if os.path.exists(temp_csv.name):
            os.unlink(temp_csv.name)

    # 3. VLM Trajectory Verification (35 points)
    # Check if the agent actually navigated the software
    try:
        frames = sample_trajectory_frames(traj, n=6)
        final_frame = get_final_screenshot(traj)
        if final_frame:
            frames.append(final_frame)
            
        vlm_response = query_vlm(images=frames, prompt=VLM_PROMPT)
        
        if vlm_response.get("success"):
            parsed = vlm_response.get("parsed", {})
            location_opened = parsed.get("location_menu_opened", False)
            yield_run = parsed.get("yield_analysis_run", False)
            
            if location_opened:
                score += 15
                feedback_parts.append("✅ VLM verified location menu interaction")
            else:
                feedback_parts.append("❌ VLM did not detect location changes")
                
            if yield_run:
                score += 20
                feedback_parts.append("✅ VLM verified yield analysis execution")
            else:
                feedback_parts.append("❌ VLM did not detect yield analysis execution")
        else:
            feedback_parts.append("⚠️ VLM verification failed to process")
    except Exception as e:
        logger.error(f"VLM check failed: {e}")
        feedback_parts.append("⚠️ VLM trajectory verification encountered an error")

    # Final pass/fail determination
    # Must have the CSV file correctly formatted, data for the cities, and at least some VLM evidence
    passed = score >= 75

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }