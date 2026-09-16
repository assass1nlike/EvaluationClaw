#!/usr/bin/env python3
"""
Verifier for flat_roof_flush_vs_tilted_solar_optimization.

Verification relies on MULTIPLE INDEPENDENT SIGNALS:
1. File Checks (20 pts): All 5 required files must exist and be created DURING the task.
2. Content Checks (20 pts): Output text files must contain reasonable structures (numbers for yield, text for recommendation).
3. Visual Trajectory Checks (60 pts): Uses VLM to verify actual workflow progression inside the Energy3D GUI.

Pass threshold is 70 points, ensuring the agent cannot pass by merely generating text files without interacting with the CAD environment, nor can it pass by clicking around the GUI without successfully extracting and recording the engineering conclusions.
"""

import json
import tempfile
import os
import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_flat_roof_optimization(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}
        
    # Safely copy results from the container
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
    
    # -------------------------------------------------------------------------
    # 1. FILE CHECKS (20 pts - 4 per file)
    # -------------------------------------------------------------------------
    files_to_check = ['flush_array', 'tilted_array', 'flush_yield', 'tilted_yield', 'recommendation']
    all_files_exist = True
    
    for f in files_to_check:
        f_info = result.get(f, {})
        # File must exist, be > 0 bytes, and have been created/modified after the task started
        if f_info.get('exists') and f_info.get('created_during_task') and f_info.get('size') > 0:
            score += 4
        else:
            all_files_exist = False
            feedback_parts.append(f"File '{f}' missing, empty, or not created during task")
            
    if all_files_exist:
        feedback_parts.append("All required files created successfully")
        
    # -------------------------------------------------------------------------
    # 2. CONTENT CHECKS (20 pts)
    # -------------------------------------------------------------------------
    flush_content = result.get('flush_yield_content', '')
    tilted_content = result.get('tilted_yield_content', '')
    rec_content = result.get('recommendation_content', '')
    
    # Yield files should record the kWh (must contain digits)
    has_flush_num = bool(re.search(r'\d+', flush_content))
    has_tilted_num = bool(re.search(r'\d+', tilted_content))
    
    if has_flush_num and has_tilted_num:
        score += 10
        feedback_parts.append("Yield files contain expected numeric data")
    else:
        feedback_parts.append("Yield files missing numeric data")
        
    # Recommendation should be an actual sentence/statement
    if len(rec_content.strip()) > 10:
        score += 10
        feedback_parts.append("Recommendation file contains text")
    else:
        feedback_parts.append("Recommendation file empty or too short")

    # -------------------------------------------------------------------------
    # 3. VLM TRAJECTORY VERIFICATION (60 pts)
    # -------------------------------------------------------------------------
    query_vlm = env_info.get('query_vlm')
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            frames = sample_trajectory_frames(traj, n=6)
            final = get_final_screenshot(traj)
            
            # Filter out Nones
            images = [img for img in frames + [final] if img]
            
            prompt = """You are verifying an Energy3D task where the agent designs a solar array on a 50x50m flat roof in Seattle, comparing a 0-degree flush mount vs a 15-degree tilted mount with row spacing, and running an annual yield analysis for both.

Review the trajectory frames and final screenshot.
Please answer the following boolean questions:
1. Is there evidence the agent set the location to Seattle (or Washington state)?
2. Did the agent create a flat roof, platform, or foundation structure?
3. Is there evidence of a 0-degree flush mount array (panels laid flat, densely packed)?
4. Is there evidence of a 15-degree tilted array with visible spacing/gaps between rows?
5. Did the agent open the 'Annual Yield Analysis' graph/chart UI window at any point?

Return ONLY a JSON object with these exact boolean keys:
{
    "location_seattle": true/false,
    "foundation_created": true/false,
    "flush_array_seen": true/false,
    "tilted_array_seen": true/false,
    "analysis_run": true/false
}"""
            
            if images:
                vlm_res = query_vlm(images=images, prompt=prompt)
                
                vlm_parsed = {}
                if vlm_res and vlm_res.get('success'):
                    vlm_parsed = vlm_res.get('parsed', {})
                    
                if vlm_parsed.get('location_seattle'):
                    score += 10
                else:
                    feedback_parts.append("VLM: Seattle location not confirmed")
                    
                if vlm_parsed.get('foundation_created'):
                    score += 10
                else:
                    feedback_parts.append("VLM: Roof/foundation not confirmed")
                    
                if vlm_parsed.get('flush_array_seen'):
                    score += 10
                else:
                    feedback_parts.append("VLM: Flush array state not confirmed")
                    
                if vlm_parsed.get('tilted_array_seen'):
                    score += 15
                else:
                    feedback_parts.append("VLM: Tilted array with spacing not confirmed")
                    
                if vlm_parsed.get('analysis_run'):
                    score += 15
                else:
                    feedback_parts.append("VLM: Yield analysis graph not observed")
            else:
                feedback_parts.append("No images available for VLM verification")
                
        except Exception as e:
            logger.error(f"VLM Verification failed: {e}")
            feedback_parts.append("VLM verification encountered an error")
    else:
        feedback_parts.append("VLM verification skipped (query_vlm not available)")
        
    passed = score >= 70
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }