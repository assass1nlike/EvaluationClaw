#!/usr/bin/env python3
"""
Verifier for industrial_fresnel_process_heat task.

Employs a robust, multi-signal verification approach:
1. Programmatic File Check: Verifies the `.ng3` CAD project file was saved.
2. Programmatic Data Check: Verifies the `.csv` yield data was successfully exported and contains actual data values.
3. Trajectory VLM Verification: Uses trajectory frames to visually verify that the physical objects (Absorber Pipe & Fresnel Reflectors) were constructed and targeted correctly, and that the simulation was executed.
"""

import json
import tempfile
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying if an AI agent successfully designed a Concentrated Solar Power (CSP) system in the Energy3D software.

TASK: Design a Linear Fresnel Reflector array targeting an Absorber Pipe, set location to Fresno CA, date to June 21, and run the Daily CSP analysis.

Carefully examine these trajectory frames and the final screenshot to determine:
1. Is Energy3D the application being used?
2. Is there an Absorber Pipe visible in the scene (a long, elevated tube/pipe structure)?
3. Are there multiple Linear Fresnel Reflectors (long flat/curved mirrors arranged on the ground) visible?
4. Is there evidence of the Daily Analysis being run (e.g., a graph window appearing showing daily yield, or the analysis menu open for CSP Yield)?

Respond strictly in JSON format:
{
    "is_energy3d": true/false,
    "has_absorber_pipe": true/false,
    "has_fresnel_reflectors": true/false,
    "analysis_run": true/false,
    "confidence": "low/medium/high",
    "reasoning": "Brief explanation"
}
"""

def verify_fresnel_process_heat(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    # 1. Retrieve the exported result JSON
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    result = {}
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        if os.path.exists(temp_file.name) and os.path.getsize(temp_file.name) > 0:
            with open(temp_file.name, 'r') as f:
                result = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read task result: {e}")
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    score = 0
    feedback_parts = []
    
    # 2. Check the NG3 Project File (15 pts)
    if result.get("ng3_exists", False) and result.get("ng3_size_bytes", 0) > 100:
        score += 15
        feedback_parts.append("✅ Project NG3 file saved")
    else:
        feedback_parts.append("❌ Project NG3 file missing or empty")
        
    # 3. Check the CSV Export File (35 pts)
    csv_exists = result.get("csv_exists", False)
    csv_has_data = result.get("csv_has_data", False)
    csv_lines = result.get("csv_lines", 0)
    
    if csv_exists:
        if csv_has_data and csv_lines > 2:
            score += 35
            feedback_parts.append("✅ CSP yield data successfully exported to CSV")
        else:
            score += 15
            feedback_parts.append("⚠️ CSV exported but appears empty or lacks yield numbers (check targeting)")
    else:
        feedback_parts.append("❌ CSV export missing")

    # 4. VLM Verification (50 pts total)
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            # Sample trajectory frames to catch intermittent states (like menus or graphs popping up)
            frames = sample_trajectory_frames(traj, n=3)
            final_img = get_final_screenshot(traj)
            if final_img:
                frames.append(final_img)
                
            vlm_result = query_vlm(images=frames, prompt=VLM_PROMPT)
            
            if vlm_result.get("success"):
                parsed = vlm_result.get("parsed", {})
                
                if parsed.get("is_energy3d", False):
                    if parsed.get("has_absorber_pipe", False):
                        score += 15
                        feedback_parts.append("✅ VLM verified Absorber Pipe")
                    else:
                        feedback_parts.append("❌ VLM could not verify Absorber Pipe")
                        
                    if parsed.get("has_fresnel_reflectors", False):
                        score += 20
                        feedback_parts.append("✅ VLM verified Fresnel Reflectors")
                    else:
                        feedback_parts.append("❌ VLM could not verify Fresnel Reflectors")
                        
                    if parsed.get("analysis_run", False):
                        score += 15
                        feedback_parts.append("✅ VLM verified Analysis execution")
                    else:
                        feedback_parts.append("❌ VLM could not verify Analysis execution")
                else:
                    feedback_parts.append("❌ VLM did not recognize Energy3D interface")
            else:
                feedback_parts.append(f"⚠️ VLM query failed: {vlm_result.get('error')}")
        except ImportError:
            feedback_parts.append("⚠️ VLM frame extraction functions not found")
        except Exception as e:
            feedback_parts.append(f"⚠️ VLM verification error: {e}")
    else:
        feedback_parts.append("⚠️ VLM service not available")

    # The agent must successfully export the simulation CSV and achieve a baseline visual setup to pass
    key_criteria_met = csv_exists and score >= 60
    passed = key_criteria_met and score >= 70

    return {
        "passed": bool(passed),
        "score": min(int(score), 100),
        "feedback": " | ".join(feedback_parts)
    }