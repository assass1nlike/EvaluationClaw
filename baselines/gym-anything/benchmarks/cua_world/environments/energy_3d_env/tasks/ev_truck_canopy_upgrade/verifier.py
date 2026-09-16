#!/usr/bin/env python3
"""
Verifier for ev_truck_canopy_upgrade task.

Verification Strategy:
1. Programmatic State Check (Primary): Parses the saved .ng3 file (which uses XMLEncoder) 
   to verify structural modifications (poleHeight, nx, ny, tiltAngle).
2. Data Extraction Check: Verifies the presence of a text file with a valid, realistic yield number.
3. VLM Trajectory Verification: Checks trajectory frames to ensure the Annual Yield Analysis graph was 
   actually opened and the agent didn't just hallucinate a file.
"""

import json
import os
import re
import tempfile
import logging

try:
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
except ImportError:
    # Fallback if gym_anything is not directly available in standard path
    sample_trajectory_frames = lambda traj, n: []
    get_final_screenshot = lambda traj: None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_ev_truck_canopy_upgrade(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm_func = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    metadata = task_info.get('metadata', {})
    min_yield = metadata.get('min_yield_kwh', 5000)
    
    score = 0
    feedback_parts = []
    
    # 1. Retrieve the task result JSON
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)
            
    task_start = result.get('task_start', 0)
    ng3_exists = result.get('ng3_exists', False)
    ng3_mtime = result.get('ng3_mtime', 0)
    txt_exists = result.get('txt_exists', False)
    txt_content = result.get('txt_content', "")

    # Anti-gaming: Ensure NG3 was created/modified during the task
    file_modified_during_task = False
    if ng3_exists:
        if ng3_mtime >= task_start:
            file_modified_during_task = True
            score += 10
            feedback_parts.append("File ev_canopy_expanded.ng3 successfully saved.")
        else:
            feedback_parts.append("File ev_canopy_expanded.ng3 exists but is stale (was not modified during task).")
    else:
        feedback_parts.append("ev_canopy_expanded.ng3 not found.")

    # 2. Inspect NG3 File for Structural Properties
    modifications = 0
    if ng3_exists and file_modified_during_task:
        temp_ng3 = tempfile.NamedTemporaryFile(delete=False, suffix='.ng3')
        try:
            copy_from_env("/tmp/ev_canopy_expanded.ng3", temp_ng3.name)
            # Energy3D uses Java's XMLEncoder, which produces text files
            with open(temp_ng3.name, 'r', errors='ignore') as f:
                content = f.read()
                
            # Check pole height = 4.5
            if re.search(r'property="poleHeight".*?>\s*4\.5\s*<', content, re.DOTALL) or '4.5' in content:
                score += 20
                modifications += 1
                feedback_parts.append("Pole height configured correctly (4.5m).")
            else:
                feedback_parts.append("Pole height not set to 4.5m.")
                
            # Check grid nx=12, ny=5
            grid_nx = bool(re.search(r'property="nx".*?>\s*12\s*<', content, re.DOTALL))
            grid_ny = bool(re.search(r'property="ny".*?>\s*5\s*<', content, re.DOTALL))
            
            # Fallback if binary encoded or XMLEncoder format changed
            if not (grid_nx and grid_ny):
                if '12' in content and '5' in content:
                    grid_nx = grid_ny = True
                    
            if grid_nx and grid_ny:
                score += 20
                modifications += 1
                feedback_parts.append("Array grid expanded correctly (12x5).")
            else:
                feedback_parts.append("Array grid not correctly set to 12x5.")
                
            # Check tilt angle = 15.0
            if re.search(r'property="tiltAngle".*?>\s*15\.0?\s*<', content, re.DOTALL) or '15.0' in content or '15 ' in content:
                score += 15
                modifications += 1
                feedback_parts.append("Tilt angle optimized correctly (15 degrees).")
            else:
                feedback_parts.append("Tilt angle not set to 15 degrees.")
                
        except Exception as e:
            logger.error(f"Error reading NG3 file: {e}")
            feedback_parts.append("Failed to verify NG3 internals.")
        finally:
            if os.path.exists(temp_ng3.name):
                os.unlink(temp_ng3.name)

    # 3. Verify Yield Summary Text File
    if txt_exists:
        # Extract any numeric sequence from the text, removing commas (e.g. "12,345.6" -> 12345.6)
        number_strs = re.findall(r'\b\d+(?:,\d+)*(?:\.\d+)?\b', txt_content)
        valid_yield_found = False
        
        for num_str in number_strs:
            try:
                val = float(num_str.replace(',', ''))
                if val >= min_yield:
                    valid_yield_found = True
                    break
            except ValueError:
                continue
                
        if valid_yield_found:
            score += 15
            feedback_parts.append(f"Yield summary contains a valid, realistic numeric value (>{min_yield} kWh).")
        else:
            feedback_parts.append(f"Yield summary does not contain a realistic annual yield value.")
    else:
        feedback_parts.append("yield_summary.txt not found.")

    # 4. VLM Verification (Trajectory checking)
    if query_vlm_func:
        # Sample frames from the trajectory to ensure they actually ran the simulation
        frames = sample_trajectory_frames(traj, n=4)
        final = get_final_screenshot(traj)
        
        images_to_check = frames
        if final:
            images_to_check.append(final)
            
        if images_to_check:
            vlm_prompt = """You are verifying the execution of a 3D simulation task in Energy3D.
TASK: Modify a solar canopy and run an "Annual Yield Analysis".

Look at these trajectory frames and determine:
1. Did the agent open the "Annual Yield Analysis" window or graph at any point? Look for a pop-up window displaying a bar chart or line graph of monthly energy generation.
2. Is the 3D solar canopy structure visibly selected and modified (e.g., taller or more panels than a standard starter setup)?

Respond in JSON format:
{
    "analysis_graph_opened": true/false,
    "canopy_modified": true/false,
    "confidence": "high/medium/low"
}
"""
            # Add VLM query support (pass as list if framework supports it, otherwise use fallback)
            try:
                vlm_res = query_vlm_func(prompt=vlm_prompt, images=images_to_check)
            except TypeError:
                # Fallback if query_vlm_func only accepts a single 'image' parameter
                vlm_res = query_vlm_func(prompt=vlm_prompt, image=final)
                
            if vlm_res and vlm_res.get("success"):
                parsed = vlm_res.get("parsed", {})
                
                if parsed.get("analysis_graph_opened", False):
                    score += 20
                    feedback_parts.append("VLM confirms Annual Yield Analysis was executed.")
                else:
                    feedback_parts.append("VLM could not confirm Annual Yield Analysis was executed.")
                    
            else:
                logger.warning("VLM query failed.")
                feedback_parts.append("VLM verification failed to run.")

    # Evaluate Passing Conditions
    # Max Score = 10 (File) + 20 (Height) + 20 (Grid) + 15 (Tilt) + 15 (Txt) + 20 (VLM) = 100
    # Must achieve at least 2 structural modifications and have successfully saved the file.
    key_criteria_met = file_modified_during_task and (modifications >= 2)
    passed = (score >= 70) and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }