#!/usr/bin/env python3
"""
Verifier for Multi-City ESG Carbon Offset Comparison task.

Verifies:
1. Agent created the CSV file during the task.
2. CSV format is correct (headers: City,Yield_kWh,CO2_Offset_kg).
3. Logic check: Phoenix solar yield should be higher than Seattle solar yield.
4. Math check: CO2 Offset = Yield * respective grid intensity factor.
5. VLM check: Trajectory shows use of Location dialog and Annual Solar Radiation graph.
"""

import os
import csv
import json
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_carbon_offset_comparison(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    metadata = task_info.get('metadata', {})
    seattle_factor = metadata.get('seattle_factor', 0.15)
    phoenix_factor = metadata.get('phoenix_factor', 0.45)

    score = 0
    feedback_parts = []
    
    # 1. Fetch JSON result
    temp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_json.name)
        with open(temp_json.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result JSON: {e}"}
    finally:
        if os.path.exists(temp_json.name):
            os.unlink(temp_json.name)

    file_exists = result.get('file_exists', False)
    file_created = result.get('file_created_during_task', False)
    
    if not file_exists:
        return {"passed": False, "score": 0, "feedback": "CSV report was not found."}
    
    if not file_created:
        feedback_parts.append("Warning: CSV file timestamp implies it wasn't created during task.")
    else:
        feedback_parts.append("CSV file created successfully.")
        
    # 2. Fetch and parse CSV report
    temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
    try:
        copy_from_env("/tmp/esg_location_report.csv", temp_csv.name)
        
        parsed_data = {}
        with open(temp_csv.name, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            headers = next(reader, [])
            headers = [h.strip() for h in headers]
            
            # Check headers
            expected_headers = ["City", "Yield_kWh", "CO2_Offset_kg"]
            if headers[:3] != expected_headers:
                feedback_parts.append(f"Header mismatch. Expected {expected_headers}, got {headers}")
            else:
                score += 15
                feedback_parts.append("CSV headers correct.")
                
            for row in reader:
                if len(row) >= 3:
                    city = row[0].strip().lower()
                    try:
                        yield_val = float(row[1].strip().replace(',', ''))
                        offset_val = float(row[2].strip().replace(',', ''))
                        if 'seattle' in city:
                            parsed_data['seattle'] = {'yield': yield_val, 'offset': offset_val}
                        elif 'phoenix' in city:
                            parsed_data['phoenix'] = {'yield': yield_val, 'offset': offset_val}
                    except ValueError:
                        continue
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to parse CSV: {e}"}
    finally:
        if os.path.exists(temp_csv.name):
            os.unlink(temp_csv.name)
            
    # 3. Logic and Math Validation
    if 'seattle' not in parsed_data or 'phoenix' not in parsed_data:
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts) + " | Missing data for Seattle or Phoenix."}

    syield = parsed_data['seattle']['yield']
    soffset = parsed_data['seattle']['offset']
    pyield = parsed_data['phoenix']['yield']
    poffset = parsed_data['phoenix']['offset']
    
    # Phoenix gets more sun than Seattle for an identical array
    logic_passed = pyield > syield > 0
    if logic_passed:
        score += 25
        feedback_parts.append("Simulation logic correct (Phoenix yield > Seattle yield > 0).")
    else:
        feedback_parts.append(f"Simulation logic failed. Seattle yield: {syield}, Phoenix yield: {pyield}.")

    # Offset math verification (+/- 2 kg tolerance for rounding)
    expected_soffset = syield * seattle_factor
    expected_poffset = pyield * phoenix_factor
    
    seattle_math_ok = abs(soffset - expected_soffset) <= 2.0
    phoenix_math_ok = abs(poffset - expected_poffset) <= 2.0
    
    if seattle_math_ok:
        score += 20
        feedback_parts.append("Seattle offset math correct.")
    else:
        feedback_parts.append(f"Seattle offset math incorrect. Expected ~{expected_soffset:.0f}, got {soffset}.")
        
    if phoenix_math_ok:
        score += 20
        feedback_parts.append("Phoenix offset math correct.")
    else:
        feedback_parts.append(f"Phoenix offset math incorrect. Expected ~{expected_poffset:.0f}, got {poffset}.")

    # 4. VLM Verification (Trajectory frames)
    if query_vlm:
        from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
        frames = sample_trajectory_frames(traj, n=4)
        final = get_final_screenshot(traj)
        all_frames = frames + [final] if final else frames
        
        prompt = """You are evaluating an agent's trajectory in the application Energy3D.
Look at the sequence of screenshots. Answer the following questions:
1. Did the agent open a map, location settings, or city selection dialog?
2. Did the agent run an "Annual Solar Radiation" or "Annual Yield" analysis (this usually results in a bar graph or chart appearing)?

Respond ONLY in valid JSON format:
{
    "opened_location_dialog": true/false,
    "ran_solar_analysis": true/false
}"""
        try:
            vlm_response = query_vlm(images=all_frames, prompt=prompt)
            if vlm_response and vlm_response.get("success"):
                parsed = vlm_response.get("parsed", {})
                if parsed.get("opened_location_dialog") and parsed.get("ran_solar_analysis"):
                    score += 20
                    feedback_parts.append("VLM visual verification passed.")
                else:
                    feedback_parts.append("VLM visual verification failed (did not detect location changes and solar analysis).")
            else:
                feedback_parts.append("VLM query returned unsuccessful.")
        except Exception as e:
            logger.error(f"VLM verification error: {e}")
            feedback_parts.append("VLM verification encountered an error.")
    else:
        feedback_parts.append("VLM query function not provided.")

    # Final evaluation
    # Pass requires correct headers, logic, and correct math for at least one city
    key_criteria_met = (score >= 60) and file_created and file_exists
    passed = key_criteria_met and (score >= 75)

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }