#!/usr/bin/env python3
"""
Verifier for Time-of-Use Solar Azimuth Optimization task.
Checks output file creation, parses the generated Daily Yield CSV to ensure
peak generation occurs in the afternoon (verifying a West-facing array),
and uses VLM trajectory sampling to ensure UI steps were genuinely taken.
"""

import json
import os
import csv
import tempfile
import logging
import traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fallback imports for VLM
try:
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot, query_vlm
    VLM_AVAILABLE = True
except ImportError:
    VLM_AVAILABLE = False
    logger.warning("VLM utilities not available.")

VLM_PROMPT = """You are verifying an agent's completion of a 3D Energy Simulation task in Energy3D.
The goal was to modify a solar panel array to face West (270 degrees azimuth), set the date to June 21, run the Daily Yield Analysis graph, and export the data.

Examine the provided trajectory frames (chronological order) and determine:
1. Did the agent select the solar array and interact with its properties (like changing Azimuth to 270)?
2. Did the agent open the Daily Yield Analysis graph?
3. Did the agent trigger an export or save dialog for the CSV data?
4. Did the agent save the project file?

Return a JSON with the following boolean keys:
{
    "changed_properties": true/false,
    "opened_analysis_graph": true/false,
    "exported_data": true/false,
    "saved_project": true/false
}
"""

def parse_csv_peak_hour(csv_path: str) -> int:
    """
    Parses the Energy3D exported Daily Yield CSV to find the hour of maximum generation.
    Expected format: Time is in column 0, yield values in subsequent columns.
    Returns the hour (integer) of peak generation, or -1 if unparseable.
    """
    peak_hour = -1
    max_yield = -1.0
    
    if not os.path.exists(csv_path):
        return -1
        
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 2:
                    continue
                
                # Attempt to parse time from first column (e.g., "14", "14:00", "14:00:00")
                time_str = row[0].strip()
                try:
                    if ':' in time_str:
                        hour = int(time_str.split(':')[0])
                    else:
                        hour = int(time_str)
                except ValueError:
                    continue # Likely a header row
                
                # Sum the generation values for this row
                total_yield = 0.0
                for val_str in row[1:]:
                    try:
                        total_yield += float(val_str)
                    except ValueError:
                        pass
                
                if total_yield > max_yield:
                    max_yield = total_yield
                    peak_hour = hour
                    
    except Exception as e:
        logger.error(f"Error parsing CSV: {e}")
        
    return peak_hour

def verify_tou_optimization(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available in environment."}

    metadata = task_info.get('metadata', {})
    min_peak_hour = metadata.get('min_peak_hour', 14)
    
    score = 0
    feedback_parts = []
    
    # 1. Fetch the main task result JSON
    result_json_path = tempfile.NamedTemporaryFile(delete=False, suffix='.json').name
    try:
        copy_from_env("/tmp/task_result.json", result_json_path)
        with open(result_json_path, 'r') as f:
            results = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read export results: {e}"}
    finally:
        if os.path.exists(result_json_path):
            os.unlink(result_json_path)

    # 2. Programmatic Checks based on Results
    csv_exists = results.get('csv_exists', False)
    csv_created = results.get('csv_created_during_task', False)
    ng3_exists = results.get('ng3_exists', False)
    ng3_created = results.get('ng3_created_during_task', False)
    
    if ng3_exists and ng3_created:
        score += 20
        feedback_parts.append("✅ Project successfully saved (tou_optimized.ng3).")
    elif ng3_exists:
        score += 10
        feedback_parts.append("⚠️ Project saved, but timestamp indicates it wasn't newly created.")
    else:
        feedback_parts.append("❌ Target project file (tou_optimized.ng3) was not saved.")
        
    if csv_exists and csv_created:
        score += 20
        feedback_parts.append("✅ Yield CSV exported successfully.")
    elif csv_exists:
        score += 10
        feedback_parts.append("⚠️ CSV exported, but timestamp indicates it wasn't newly created.")
    else:
        feedback_parts.append("❌ Yield CSV (west_facing_yield.csv) was not exported.")

    # 3. Peak Generation Analysis (The core physics check)
    peak_hour = -1
    if csv_exists:
        csv_local_path = tempfile.NamedTemporaryFile(delete=False, suffix='.csv').name
        try:
            copy_from_env("/tmp/west_facing_yield.csv", csv_local_path)
            peak_hour = parse_csv_peak_hour(csv_local_path)
        except Exception as e:
            logger.error(f"Failed to copy/parse CSV: {traceback.format_exc()}")
        finally:
            if os.path.exists(csv_local_path):
                os.unlink(csv_local_path)
                
        if peak_hour >= min_peak_hour:
            score += 35
            feedback_parts.append(f"✅ Yield profile is correct for West-facing array (Peak hour: {peak_hour}:00).")
        elif peak_hour != -1:
            feedback_parts.append(f"❌ Yield profile incorrect for West-facing (Peak hour: {peak_hour}:00, expected >= {min_peak_hour}:00). Array might still be South-facing.")
        else:
            feedback_parts.append("❌ Could not determine peak generation hour from CSV.")

    # 4. VLM Trajectory Verification
    vlm_score = 0
    if VLM_AVAILABLE and 'query_vlm' in env_info:
        try:
            # Sample trajectory frames
            frames = sample_trajectory_frames(traj, n=4)
            final_frame = get_final_screenshot(traj)
            if final_frame:
                frames.append(final_frame)
            
            if frames:
                vlm_result = env_info['query_vlm'](
                    prompt=VLM_PROMPT,
                    image=frames
                )
                
                if vlm_result.get("success") and "parsed" in vlm_result:
                    parsed = vlm_result["parsed"]
                    if parsed.get("changed_properties"): vlm_score += 10
                    if parsed.get("opened_analysis_graph"): vlm_score += 10
                    if parsed.get("exported_data"): vlm_score += 5
                    
                    if vlm_score == 25:
                        feedback_parts.append("✅ VLM confirmed correct UI trajectory steps.")
                    else:
                        feedback_parts.append("⚠️ VLM detected incomplete UI trajectory steps.")
                    
                    score += vlm_score
                else:
                    feedback_parts.append("⚠️ VLM verification failed to parse.")
        except Exception as e:
            logger.error(f"VLM verification exception: {e}")
            feedback_parts.append("⚠️ VLM verification encountered an error.")
            # Gracefully provide partial points if VLM errors out but physics match
            if peak_hour >= min_peak_hour:
                score += 25
    else:
        # Fallback if VLM not supported
        if peak_hour >= min_peak_hour:
            score += 25
            feedback_parts.append("⚠️ VLM unavailable; assumed UI steps correct based on CSV output.")

    # Determine passing state
    # Must have saved the project, exported the CSV, and physically produced a West-facing yield profile
    physics_passed = (peak_hour >= min_peak_hour)
    files_created = (csv_exists and ng3_exists and csv_created and ng3_created)
    
    passed = score >= 70 and physics_passed and files_created

    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback_parts)
    }