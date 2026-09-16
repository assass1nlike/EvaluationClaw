#!/usr/bin/env python3
"""
Verifier for height_constrained_urban_solar_retrofit.

Verification Strategy:
1. File check: Verifies `low_profile_array.ng3` was saved during the task session.
2. Content check: Verifies `yield_report.txt` exists and contains numeric values.
3. VLM Hybrid check: Since `.ng3` is a Java serialized object that is difficult to parse 
   externally, we query the VLM using the trajectory snapshots to confirm the array's 
   tilt was dramatically lowered (height reduced) and rows were densified.
"""

import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying if an agent successfully completed a solar array redesign task in Energy3D.
The goal was to modify an existing rooftop solar array to make it LOW-PROFILE (height < 0.8m) and DENSIFIED (more rows of panels packed closer together).

Please analyze the sequence of screenshots (trajectory) and the final screenshot.
Determine if:
1. LOW PROFILE: Did the agent reduce the tilt angle of the solar racks significantly so they are nearly flat, or change them to landscape orientation, to reduce their vertical height?
2. DENSIFIED: Did the agent add more rows of panels or reduce row spacing so that more panels fit on the roof compared to the starting state? (There should be visibly more rows packed closely).

Respond ONLY in valid JSON format exactly matching this structure:
{
    "low_profile_achieved": true/false,
    "array_densified": true/false,
    "reasoning": "brief explanation"
}
"""

def verify_height_constrained_urban_solar_retrofit(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}
        
    query_vlm = env_info.get('query_vlm')
    
    # 1. Gather programmatic state payload
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    score = 0
    feedback_parts = []
    
    ng3_exists = result.get('ng3_exists', False)
    ng3_created_after = result.get('ng3_created_after', False)
    report_exists = result.get('report_exists', False)
    report_created_after = result.get('report_created_after', False)
    report_content = result.get('report_content', '')
    
    # Criterion 1: File saved (10 pts)
    if ng3_exists and ng3_created_after:
        score += 10
        feedback_parts.append("Project file 'low_profile_array.ng3' saved.")
    elif ng3_exists:
        score += 3
        feedback_parts.append("Project file exists but was not created/modified during task.")
    else:
        feedback_parts.append("Project file 'low_profile_array.ng3' not found.")
        
    # Criterion 2: Yield Report created and has numeric value (25 pts)
    if report_exists and report_created_after:
        # Check if report contains any numbers (e.g. 5240 kWh)
        if any(char.isdigit() for char in report_content):
            score += 25
            feedback_parts.append("Yield report contains numeric data.")
        else:
            score += 10
            feedback_parts.append("Yield report exists but lacks numeric data.")
    else:
        feedback_parts.append("Yield report not found or not created during task.")

    # 3. VLM Trajectory Verification
    vlm_height = False
    vlm_densify = False
    
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            frames = sample_trajectory_frames(traj, n=4)
            final = get_final_screenshot(traj)
            
            images = frames
            if final:
                images.append(final)
                
            if images:
                vlm_result = query_vlm(images=images, prompt=VLM_PROMPT)
                if vlm_result and vlm_result.get("success"):
                    parsed = vlm_result.get("parsed", {})
                    
                    if parsed.get("low_profile_achieved", False):
                        vlm_height = True
                        score += 35
                        feedback_parts.append("VLM confirmed Low-Profile array.")
                    else:
                        feedback_parts.append("VLM did not detect low-profile adjustment.")
                        
                    if parsed.get("array_densified", False):
                        vlm_densify = True
                        score += 30
                        feedback_parts.append("VLM confirmed Array Densification.")
                    else:
                        feedback_parts.append("VLM did not detect densification.")
                else:
                    feedback_parts.append("VLM query failed or returned invalid response.")
            else:
                feedback_parts.append("No trajectory images available for VLM.")
        except ImportError:
            logger.warning("gym_anything.vlm not found.")
            feedback_parts.append("VLM library missing on host.")
        except Exception as e:
            logger.error(f"VLM verification error: {e}")
            feedback_parts.append(f"VLM verification error: {e}")
    else:
        feedback_parts.append("VLM function not available on host environment.")

    # Pass Threshold: 75 points with both Height Constraint Met and Array Densified criteria achieved
    passed = (score >= 75) and vlm_height and vlm_densify
    
    return {
        "passed": bool(passed),
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }