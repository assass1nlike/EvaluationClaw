#!/usr/bin/env python3
"""
Verifier for fire_code_rooftop_solar_setback_compliance.

Verification Strategy:
1. Programmatic Check (40 pts): Verifies that both the project (.ng3) and 
   the analysis CSV were created/modified during the task timeframe.
2. VLM Trajectory & Screenshot Check (60 pts): Evaluates the visual layout 
   to ensure fire code setbacks (margins) were respected, the panel model 
   was changed (seen in properties pane), and the analysis tool was run.
"""

import os
import json
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are evaluating a solar array design completed in Energy3D.
Review these frames representing the agent's workflow and the final state.

Please verify the following elements:
1. "panels_placed": Are there solar panels placed on the roof of the house?
2. "fire_setback_respected": Is there a clear, unpaneled margin (border) left along ALL edges of the roof plane (eaves, ridge, sides)? If the panels cover the roof edge-to-edge with no walkway margin, this is false.
3. "sunpower_selected": Is there evidence in the trajectory (e.g., a properties dialog or right-click menu) that the panel type was changed to a "SunPower" model?
4. "yield_analysis_run": Is there evidence (e.g., a graph window or menu interaction) that the Annual Yield Analysis was executed?

Provide your assessment in the following strict JSON format:
{
    "panels_placed": true/false,
    "fire_setback_respected": true/false,
    "sunpower_selected": true/false,
    "yield_analysis_run": true/false,
    "reasoning": "brief explanation"
}
"""

def verify_solar_setback_compliance(traj, env_info, task_info):
    """Verifies programmatic file exports and VLM-based layout requirements."""
    
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # --- 1. Programmatic Verification (40 Points) ---
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

    # Check NG3 Project Save (20 pts)
    if result.get("ng3_exists") and result.get("ng3_created_during_task"):
        score += 20
        feedback_parts.append("Project saved properly.")
    else:
        feedback_parts.append("Project file not saved or modified.")

    # Check Yield CSV Export (20 pts)
    csv_size = result.get("csv_size_bytes", 0)
    if result.get("csv_exists") and result.get("csv_created_during_task") and csv_size > 50:
        score += 20
        feedback_parts.append("Yield CSV exported successfully.")
    else:
        feedback_parts.append("Yield CSV not found or empty.")

    # --- 2. VLM Trajectory Verification (60 Points) ---
    if not query_vlm:
        feedback_parts.append("VLM query function not available.")
        return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}
    
    try:
        from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
        frames = sample_trajectory_frames(traj, n=4)
        final = get_final_screenshot(traj)
        images_to_analyze = frames + [final] if final else frames
        
        if not images_to_analyze:
            feedback_parts.append("No images available for VLM verification.")
            return {"passed": False, "score": score, "feedback": " | ".join(feedback_parts)}
            
        vlm_result = query_vlm(prompt=VLM_PROMPT, images=images_to_analyze)
        
        if vlm_result.get("success"):
            parsed = vlm_result.get("parsed", {})
            logger.info(f"VLM Response: {parsed}")
            
            panels = parsed.get("panels_placed", False)
            setback = parsed.get("fire_setback_respected", False)
            sunpower = parsed.get("sunpower_selected", False)
            analysis = parsed.get("yield_analysis_run", False)
            
            if panels:
                score += 10
            else:
                feedback_parts.append("No panels visually detected.")
                
            if setback:
                score += 25
                feedback_parts.append("Fire code margins respected.")
            else:
                feedback_parts.append("Fire code margins NOT respected (edge-to-edge).")
                
            if sunpower:
                score += 15
                feedback_parts.append("SunPower model selected.")
            else:
                feedback_parts.append("SunPower selection not clearly verified.")
                
            if analysis:
                score += 10
                feedback_parts.append("Yield analysis execution verified.")
        else:
            feedback_parts.append(f"VLM verification failed: {vlm_result.get('error')}")

    except Exception as e:
        logger.error(f"VLM verification error: {e}")
        feedback_parts.append(f"VLM error: {e}")

    # Determine passing state
    # Must achieve at least 70 points AND have respected the fire setback
    passed = score >= 70 and ("Fire code margins respected." in feedback_parts)
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }