#!/usr/bin/env python3
"""
Verifier for passive_solar_overhang_optimization task.

Verification Strategy:
1. Programmatic: Check if the required file was saved and created during the task.
2. Programmatic String Search: Energy3D .ng3 files are serialized objects (often containing XML/JSON text). 
   We scan the raw binary content for "Phoenix" and "1.5" (overhang depth) to verify settings.
3. VLM Trajectory: Uses multiple frames to verify the Daily Energy graph was opened.
4. VLM Trajectory: Verifies window overhangs are visibly present on the building.
"""

import json
import tempfile
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_passive_solar_overhang(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # 1. Read JSON result
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result JSON: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    # 2. Check File Existence and Timestamps
    output_exists = result.get('output_exists', False)
    file_created = result.get('file_created_during_task', False)
    file_size = result.get('output_size_bytes', 0)
    output_path = result.get('output_path', '/home/ga/Documents/Energy3D/phoenix_passive.ng3')

    if output_exists and file_created and file_size > 100:
        score += 15
        feedback_parts.append("✅ File 'phoenix_passive.ng3' saved successfully.")
    elif output_exists:
        feedback_parts.append("❌ File exists but was not created during this task (stale data).")
    else:
        feedback_parts.append("❌ Target file 'phoenix_passive.ng3' was not saved.")

    # 3. Text search within the saved .ng3 file (robust fallback for serialized properties)
    location_found = False
    overhang_found = False
    
    if output_exists and file_created:
        temp_ng3 = tempfile.NamedTemporaryFile(delete=False, suffix='.ng3')
        try:
            copy_from_env(output_path, temp_ng3.name)
            # Read as binary and decode ignoring errors to safely scan strings
            with open(temp_ng3.name, 'rb') as f:
                content = f.read().decode('utf-8', errors='ignore')
            
            # Look for the city assignment
            if 'Phoenix' in content:
                location_found = True
                score += 20
                feedback_parts.append("✅ Location set to Phoenix confirmed in save file.")
            else:
                feedback_parts.append("❌ Location not set to Phoenix.")
                
            # Look for overhang dimensions
            if '1.5' in content and ('overhang' in content.lower() or 'Overhang' in content):
                overhang_found = True
                score += 20
                feedback_parts.append("✅ 1.5m Overhang configuration found in save file.")
            else:
                feedback_parts.append("❌ 1.5m Overhang configuration not found in save file.")
                
        except Exception as e:
            logger.error(f"Failed to copy or read .ng3 file: {e}")
        finally:
            if os.path.exists(temp_ng3.name):
                os.unlink(temp_ng3.name)

    # 4. VLM Verification using Trajectory Frames
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
    
    query_vlm = env_info.get('query_vlm')
    if query_vlm:
        try:
            # Sample multiple frames so we can catch the analysis graph if it was opened and closed
            frames = sample_trajectory_frames(traj, n=6)
            final = get_final_screenshot(traj)
            if final and final not in frames:
                frames.append(final)
                
            prompt = """You are verifying a CAD engineering task in Energy3D.
Review these screenshots spanning the user's trajectory.

1. Overhangs Visible: Are there physical window overhangs (roof-like shades extending outward horizontally from the top of the windows) visible on the building in the 3D view? 
2. Daily Energy Graph: Did the user open and display the "Daily Building Energy" analysis graph (a line/bar chart displaying daily heat, solar, and net energy) at any point in these frames?

Respond ONLY in valid JSON format:
{
  "overhangs_visible": true/false,
  "daily_energy_graph_displayed": true/false,
  "reasoning": "Brief explanation"
}"""

            vlm_response = query_vlm(prompt=prompt, images=frames)
            vlm_parsed = vlm_response.get('parsed', {})
            
            if vlm_parsed.get('overhangs_visible', False):
                score += 25
                feedback_parts.append("✅ VLM confirmed window overhangs are visibly present.")
            else:
                feedback_parts.append("❌ VLM did not see window overhangs on the building.")
                
            if vlm_parsed.get('daily_energy_graph_displayed', False):
                score += 20
                feedback_parts.append("✅ VLM confirmed Daily Building Energy graph was displayed.")
            else:
                feedback_parts.append("❌ VLM did not see the Daily Building Energy graph.")
                
        except Exception as e:
            logger.error(f"VLM verification error: {e}")
            feedback_parts.append(f"⚠️ VLM verification encountered an error: {e}")
    else:
        feedback_parts.append("⚠️ VLM endpoint unavailable.")

    # Evaluate passing condition
    # Required: File created AND Overhangs added (either via file strings or VLM)
    key_criteria_met = output_exists and file_created and (overhang_found or getattr(vlm_parsed, 'overhangs_visible', False))
    passed = score >= 70 and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": "\n".join(feedback_parts)
    }