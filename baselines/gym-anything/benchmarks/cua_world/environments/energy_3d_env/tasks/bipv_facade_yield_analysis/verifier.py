#!/usr/bin/env python3
"""
Verifier for bipv_facade_yield_analysis task.

This verifier uses a hybrid approach:
1. Programmatic File Check: Confirms that the target NG3 project and CSV yield data
   were created *during* the task execution window (preventing "do nothing" gaming).
   It also validates that the CSV has content.
2. VLM Trajectory Verification: Energy3D projects are serialized binary/XML. We use
   the agent's trajectory screenshots to visually confirm the two core visual actions:
   placing panels on a vertical surface, and displaying the analysis plot.
"""

import os
import json
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are an expert verifier assessing a task in the software Energy3D.
The agent was asked to design a Building-Integrated Photovoltaics (BIPV) system.
Review these sequential screenshots capturing the agent's workflow and final state.

Check for two specific criteria:
1. "vertical_facade_panels": Did the agent successfully place a significant number of solar panels (arrays) on a VERTICAL wall (facade) of a high-rise building? This should be clearly visible as panels hugging the sides of a structure, not just the flat roof or ground.
2. "analysis_yield_visible": Did the agent run an Annual Yield Analysis? Evidence includes a pop-up chart/graph window showing monthly energy yield bars/lines, or the analysis progress bar.

Respond ONLY in valid JSON format:
{
  "vertical_facade_panels": true/false,
  "analysis_yield_visible": true/false,
  "reasoning": "Brief explanation of evidence found in the screenshots."
}
"""

def verify_bipv_yield_analysis(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Verifier setup error: copy_from_env missing"}

    # 1. Programmatic Verification
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read exported results: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    score = 0
    feedback_parts = []
    
    # NG3 file validation
    if result.get("ng3_exists") and result.get("ng3_created_during_task"):
        score += 20
        feedback_parts.append("Project correctly saved as city_block_bipv.ng3")
    elif result.get("ng3_exists"):
        feedback_parts.append("Project exists but was not modified during task (Stale)")
    else:
        feedback_parts.append("Project not saved to expected NG3 file")

    # CSV file validation
    if result.get("csv_exists") and result.get("csv_created_during_task"):
        if result.get("csv_lines", 0) > 2:
            score += 30
            feedback_parts.append("Yield CSV exported successfully with data")
        else:
            score += 10
            feedback_parts.append("Yield CSV created but appears empty/missing data rows")
    elif result.get("csv_exists"):
        feedback_parts.append("Yield CSV exists but was not modified during task (Stale)")
    else:
        feedback_parts.append("Yield CSV not exported")

    # 2. VLM Verification
    if not query_vlm:
        feedback_parts.append("VLM query function missing, unable to verify visual components")
        vlm_success = False
    else:
        try:
            # We must import from framework inside the script runtime context
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            
            # Extract progression frames plus final result to confirm workflow
            frames = sample_trajectory_frames(traj, n=4)
            final = get_final_screenshot(traj)
            images_to_evaluate = frames + [final] if final else frames
            
            if not images_to_evaluate:
                vlm_success = False
                feedback_parts.append("No screenshots available for VLM verification")
            else:
                vlm_resp = query_vlm(prompt=VLM_PROMPT, images=images_to_evaluate)
                if vlm_resp and vlm_resp.get('success'):
                    parsed = vlm_resp.get('parsed', {})
                    
                    panels_vertical = parsed.get("vertical_facade_panels", False)
                    analysis_visible = parsed.get("analysis_yield_visible", False)
                    
                    if panels_vertical:
                        score += 30
                        feedback_parts.append("VLM confirmed vertical facade BIPV panels")
                    else:
                        feedback_parts.append("VLM did not detect solar panels on vertical walls")
                        
                    if analysis_visible:
                        score += 20
                        feedback_parts.append("VLM confirmed yield analysis graph/execution")
                    else:
                        feedback_parts.append("VLM did not detect yield analysis window")
                else:
                    vlm_error = vlm_resp.get('error', 'Unknown') if vlm_resp else 'No response'
                    feedback_parts.append(f"VLM parsing/query failed: {vlm_error}")
                    
        except Exception as e:
            logger.error(f"VLM Verification error: {e}")
            feedback_parts.append("VLM verification exception occurred")

    # Final determination
    # Must have both programmatic proof (at least partial) and visual proof
    key_criteria_met = (result.get("ng3_exists") and result.get("csv_exists") and score >= 60)
    passed = bool(key_criteria_met and score >= 70)

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }