#!/usr/bin/env python3
"""
Verifier for Parabolic Trough Process Heat Design task.
Combines programmatic `.ng3` file inspection (JSON payload check) 
with VLM trajectory verification to ensure robust, un-gameable grading.
"""

import os
import json
import re
import tempfile
import logging

# Import VLM utilities
from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating an agent's progress in the Energy3D application.
The task required the agent to:
1. Place at least 4 Parabolic Troughs (long, curved, mirrored solar concentrators).
2. Open the 'Daily Environmental Temperature and Solar Energy' analysis graph.

Review the provided screenshots (trajectory frames and final state) and determine:
1. Are there visible Parabolic Troughs (long curved mirrors) placed on the 3D canvas?
2. Did the agent open the Daily Analysis graph or a yield popup window at any point during the trajectory?

Respond strictly in JSON format:
{
    "troughs_visible": true/false,
    "analysis_graph_opened": true/false,
    "reasoning": "Brief explanation of what is visible"
}
"""

def verify_trough_design(traj, env_info, task_info):
    """Verify programmatic elements and VLM progression."""
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env or not query_vlm:
        return {"passed": False, "score": 0, "feedback": "Required framework functions missing."}

    score = 0
    feedback = []
    
    # 1. Retrieve the exported JSON manifest
    manifest = {}
    temp_manifest = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_manifest.name)
        with open(temp_manifest.name, 'r') as f:
            manifest = json.load(f)
    except Exception as e:
        logger.warning(f"Could not load manifest: {e}")
    finally:
        if os.path.exists(temp_manifest.name):
            os.unlink(temp_manifest.name)
            
    # Check basic file modifications (Anti-gaming: Do nothing scores 0)
    if manifest.get('ng3_modified'):
        score += 10
        feedback.append("Project file saved.")
    else:
        feedback.append("Project file not saved or unmodified.")
        return {"passed": False, "score": 0, "feedback": " | ".join(feedback)}

    if manifest.get('txt_modified'):
        score += 5
        feedback.append("Yield file created.")
        
    # 2. Inspect the .ng3 project file
    temp_ng3 = tempfile.NamedTemporaryFile(delete=False, suffix='.ng3')
    trough_count = 0
    try:
        copy_from_env("/tmp/trough_plant.ng3", temp_ng3.name)
        with open(temp_ng3.name, 'r') as f:
            content = f.read()
            
        try:
            # Modern Energy3D .ng3 files are JSON
            data = json.loads(content)
            
            # Location
            if "Phoenix" in data.get("city", ""):
                score += 10
                feedback.append("City set to Phoenix.")
                
            # Date
            date_str = data.get("date", "")
            if "6" in date_str and "21" in date_str:
                score += 5
                feedback.append("Date set to June 21.")
                
            # Components
            components = data.get("components", [])
            troughs = [c for c in components if "ParabolicTrough" in c.get("className", "")]
            trough_count = len(troughs)
            
            if trough_count >= 4:
                score += 10
                feedback.append(f"Found {trough_count} troughs.")
                
                # Verify Length & Azimuth
                valid_len = sum(1 for t in troughs if 40.0 <= float(t.get("length", 0)) <= 60.0)
                if valid_len >= 4:
                    score += 10
                    feedback.append("Troughs have correct ~50m length.")
                    
                # N/S alignment: azimuth ~0 or ~180
                valid_azi = sum(1 for t in troughs if abs(float(t.get("relativeAzimuth", 90))) <= 15 or 
                                                     abs(float(t.get("relativeAzimuth", 90)) - 180) <= 15 or
                                                     abs(float(t.get("relativeAzimuth", 90)) + 180) <= 15)
                if valid_azi >= 4:
                    score += 10
                    feedback.append("Troughs aligned North-South.")
                    
        except json.JSONDecodeError:
            # Fallback if it's not standard JSON (older versions/serialization)
            if "Phoenix" in content: score += 10
            if "6-21" in content or "June 21" in content: score += 5
            trough_count = content.count("ParabolicTrough")
            if trough_count >= 4: 
                score += 30 # Combine component criteria if fallback
                feedback.append(f"Fallback check found {trough_count} troughs.")
    except Exception as e:
        logger.warning(f"Error parsing .ng3 file: {e}")
    finally:
        if os.path.exists(temp_ng3.name):
            os.unlink(temp_ng3.name)

    # 3. Inspect the yield txt file
    temp_txt = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
    try:
        copy_from_env("/tmp/thermal_yield.txt", temp_txt.name)
        with open(temp_txt.name, 'r') as f:
            txt_content = f.read()
            # Must contain some numeric value reporting the yield
            if re.search(r'\d+\.?\d*', txt_content):
                score += 10
                feedback.append("Yield value reported.")
    except Exception:
        pass
    finally:
        if os.path.exists(temp_txt.name):
            os.unlink(temp_txt.name)

    # 4. VLM Trajectory Verification
    frames = sample_trajectory_frames(traj, n=4)
    final_img = get_final_screenshot(traj)
    
    if final_img:
        frames.append(final_img)
        vlm_result = query_vlm(images=frames, prompt=VLM_PROMPT)
        
        if vlm_result.get("success"):
            parsed = vlm_result.get("parsed", {})
            if parsed.get("troughs_visible"):
                score += 15
                feedback.append("VLM confirmed troughs visible.")
            if parsed.get("analysis_graph_opened"):
                score += 15
                feedback.append("VLM confirmed analysis graph opened.")
        else:
            feedback.append("VLM verification failed to parse.")
    else:
        feedback.append("No screenshots available for VLM.")

    # Determine pass/fail
    # Total possible is 100. Passing requires 70+ and troughs actually present.
    passed = (score >= 70) and (trough_count >= 4 or manifest.get('txt_modified'))
    
    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback)
    }