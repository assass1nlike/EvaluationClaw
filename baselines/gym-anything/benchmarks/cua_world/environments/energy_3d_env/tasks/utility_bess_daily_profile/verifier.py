#!/usr/bin/env python3
"""
Verifier for utility_bess_daily_profile task in Energy3D.
Scores based on exported CSV file, text document with peak hour, saved modified project, 
and VLM trajectory analysis to ensure the simulation was successfully executed in the UI.
"""

import json
import tempfile
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VERIFICATION_PROMPT = """You are verifying if a user successfully performed a Daily Energy Analysis in Energy3D.
Task Requirements:
1. Location set to Phoenix, AZ.
2. Date set to June 21 (Summer Solstice).
3. Daily Energy Analysis graph is opened and visible.

Look at the provided trajectory screenshots and final screenshot.
Did the user open the Daily Energy Analysis graph (typically via Analysis > Solar Panels > Daily Yield Analysis)?
Is there any indication that the location was set to Phoenix and the date to June 21 (e.g., UI elements, map backdrop, date slider)?

Respond ONLY with a JSON object format like this:
{
    "daily_analysis_run": true/false,
    "location_set_phoenix": true/false,
    "date_set_june_21": true/false,
    "confidence": "high",
    "reasoning": "string"
}
"""

def verify_utility_bess_daily_profile(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # 1. Access main task findings mapping
    temp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_json.name)
        with open(temp_json.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result: {e}"}
    finally:
        if os.path.exists(temp_json.name):
            os.unlink(temp_json.name)

    ng3_exists = result.get('ng3_exists', False)
    csv_exists = result.get('csv_exists', False)
    txt_exists = result.get('txt_exists', False)

    if ng3_exists:
        score += 10
        feedback_parts.append("Project saved (10/10)")
    else:
        feedback_parts.append("Project NOT saved (0/10)")

    # 2. Check for transcribed/exported profile data
    if csv_exists:
        temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        try:
            copy_from_env("/tmp/solstice_hourly_profile.csv", temp_csv.name)
            with open(temp_csv.name, 'r') as f:
                lines = f.readlines()
                if len(lines) >= 5:
                    score += 20
                    feedback_parts.append("CSV exported with valid data layout (20/20)")
                else:
                    score += 5
                    feedback_parts.append("CSV exported but lacked sufficient data rows (5/20)")
        except Exception:
            feedback_parts.append("Failed to read CSV (0/20)")
        finally:
            if os.path.exists(temp_csv.name):
                os.unlink(temp_csv.name)
    else:
        feedback_parts.append("CSV NOT found (0/20)")

    # 3. Check for specific peak time analysis text
    if txt_exists:
        temp_txt = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        try:
            copy_from_env("/tmp/peak_charge_hour.txt", temp_txt.name)
            with open(temp_txt.name, 'r') as f:
                content = f.read().strip().lower()
                # Peak insolation for Phoenix (S-facing array) typically spans 11:00-14:00
                if any(h in content for h in ["11", "12", "13", "14", "1pm", "2pm", "1 pm", "12pm", "12 pm"]):
                    score += 20
                    feedback_parts.append("Peak hour logically identified (20/20)")
                elif len(content) > 0:
                    score += 10
                    feedback_parts.append(f"Peak hour file created, but value ({content}) may be incorrect (10/20)")
        except Exception:
            feedback_parts.append("Failed to read TXT (0/20)")
        finally:
            if os.path.exists(temp_txt.name):
                os.unlink(temp_txt.name)
    else:
        feedback_parts.append("TXT NOT found (0/20)")

    # 4. VLM Check for Trajectory Actions (Running the Simulation)
    query_vlm = env_info.get('query_vlm')
    vlm_score = 0
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            frames = sample_trajectory_frames(traj, n=4)
            final_shot = get_final_screenshot(traj)
            images = frames
            if final_shot:
                images.append(final_shot)
            
            vlm_res = query_vlm(prompt=VERIFICATION_PROMPT, images=images)
            if vlm_res and vlm_res.get('success'):
                parsed = vlm_res.get('parsed', {})
                daily_run = parsed.get('daily_analysis_run', False)
                loc_phx = parsed.get('location_set_phoenix', False)
                date_june = parsed.get('date_set_june_21', False)
                
                if daily_run:
                    vlm_score += 20
                    feedback_parts.append("VLM confirmed Daily Analysis run (20/20)")
                if loc_phx:
                    vlm_score += 15
                    feedback_parts.append("VLM confirmed Location: Phoenix (15/15)")
                if date_june:
                    vlm_score += 15
                    feedback_parts.append("VLM confirmed Date: June 21 (15/15)")
            else:
                feedback_parts.append("VLM verification failed to parse")
        except ImportError:
            feedback_parts.append("VLM utilities could not be imported")

    score += vlm_score
    
    # Must secure at least 65% and actually have generated the core output
    passed = score >= 65 and csv_exists

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }