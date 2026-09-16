#!/usr/bin/env python3
"""
Verifier for Supermarket RTU Shading & Solar Layout task.
Combines programmatic file checks (CSV and NG3 creation) with VLM trajectory 
analysis to confirm 3D spatial modeling steps were performed correctly.
"""

import json
import os
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_supermarket_task(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}
        
    score = 0
    feedback_parts = []
    
    # 1. Read task_result.json
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
            
    # File Checks
    csv_exists = result.get('csv_exists', False)
    csv_created = result.get('csv_created', False)
    csv_size = result.get('csv_size', 0)
    
    ng3_exists = result.get('ng3_exists', False)
    ng3_created = result.get('ng3_created', False)
    ng3_size = result.get('ng3_size', 0)
    
    if ng3_exists and ng3_created and ng3_size > 100:
        score += 15
        feedback_parts.append("Project (.ng3) saved.")
    else:
        feedback_parts.append("Project NOT saved properly.")
        
    if csv_exists and csv_created and csv_size > 50:
        score += 10
        feedback_parts.append("Yield CSV exported.")
        
        # Verify CSV content
        temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        try:
            copy_from_env("/tmp/supermarket_yield.csv", temp_csv.name)
            with open(temp_csv.name, 'r') as f:
                content = f.read()
                lines = content.strip().split('\n')
                # A daily or monthly yield export from Energy3D should have at least 12 lines
                if len(lines) >= 12:
                    score += 10
                    feedback_parts.append("CSV has valid yield rows.")
                else:
                    feedback_parts.append("CSV exported but lacks sufficient rows.")
        except Exception:
            pass
        finally:
            if os.path.exists(temp_csv.name):
                os.unlink(temp_csv.name)
    else:
        feedback_parts.append("Yield CSV NOT exported.")

    # 2. VLM Trajectory Verification
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            # Sample throughout to catch the transient heat map
            frames = sample_trajectory_frames(traj, n=5)
            final = get_final_screenshot(traj)
            images = frames + [final] if final else frames
            
            if images:
                prompt = """You are evaluating an architectural solar design in Energy3D.
Review these trajectory screenshots and the final result. Did the user accomplish the following?

1. Modeled a large, flat-roof building (resembling a commercial supermarket).
2. Placed multiple solid block structures (HVAC/RTUs) on top of the roof.
3. Activated the Solar Heat Map tool (indicated by a color gradient/thermal overlay appearing on the roof and highlighting shadows).
4. Placed a large array of solar panel racks on the roof.
5. Placed the panels intelligently to avoid the dark shadow zones cast by the RTU blocks.

Respond in strict JSON format:
{
    "building_modeled": true/false,
    "rtus_placed": true/false,
    "heat_map_used": true/false,
    "solar_panels_placed": true/false,
    "shadows_avoided": true/false
}"""
                vlm_result = query_vlm(images=images, prompt=prompt)
                
                if vlm_result and vlm_result.get("success"):
                    parsed = vlm_result.get("parsed", {})
                    
                    if parsed.get("building_modeled"):
                        score += 10
                        feedback_parts.append("Building visually confirmed.")
                    if parsed.get("rtus_placed"):
                        score += 15
                        feedback_parts.append("RTUs visually confirmed.")
                    if parsed.get("heat_map_used"):
                        score += 10
                        feedback_parts.append("Heat map usage confirmed.")
                    if parsed.get("solar_panels_placed"):
                        score += 15
                        feedback_parts.append("Solar panels visually confirmed.")
                    if parsed.get("shadows_avoided"):
                        score += 15
                        feedback_parts.append("Shadow avoidance logic confirmed.")
                else:
                    feedback_parts.append("VLM query failed to parse.")
        except Exception as e:
            feedback_parts.append(f"VLM verification error: {str(e)}")

    # Key criteria requirement for passing
    key_criteria_met = csv_exists and ng3_exists and score >= 60
    passed = key_criteria_met
    
    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback_parts)
    }