#!/usr/bin/env python3
"""
Verifier for the Solar Array Row Spacing Optimization task.
Requires the agent to save an optimized .ng3 scene and export a CSV for Dec 21.

Verification relies on multiple independent signals:
1. File verification (existence, timestamps, size) to ensure outputs were generated.
2. Content verification of the exported CSV to ensure it looks like a valid Energy3D yield file.
3. VLM trajectory verification to confirm visual UI actions (spacing changes, Dec 21 selection).
"""

import os
import json
import base64
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Note: Energy3D .ng3 files are Java-serialized objects, so we don't parse them directly here.
# We rely on VLM visual confirmation of the row spacing combined with file timestamp validation.

VLM_PROMPT = """You are evaluating an agent's completion of a Solar Engineering task in Energy3D.
The agent was asked to:
1. Increase the "Row Spacing" of the solar array to at least 6.0 meters to prevent winter shading.
2. Run a "Daily Yield Analysis" specifically for the Winter Solstice (December 21).

Look closely at the provided trajectory frames (which show the progression) and the final screenshot.
Please determine:
1. Did the agent physically increase the distance/spacing between the rows of solar panels? (Look for changes in the 3D view where the rows spread further apart).
2. Did the agent open the Daily Environmental Temperature / Solar Yield analysis graph?
3. Was the analysis date explicitly set to December 21 (or 12/21) on the graph or in the UI?

Respond EXACTLY in this JSON format:
{
    "row_spacing_visibly_increased": true/false,
    "daily_analysis_graph_opened": true/false,
    "december_21_selected": true/false,
    "reasoning": "brief explanation of what you see in the images"
}
"""

def verify_solar_row_spacing(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Verifier error: copy_from_env not available."}
        
    score = 0
    feedback_parts = []
    
    # ---------------------------------------------------------
    # 1. Retrieve and parse exported result JSON
    # ---------------------------------------------------------
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    result_data = {}
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result_data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read exported results: {e}")
        return {"passed": False, "score": 0, "feedback": "Failed to read exported result state."}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)
            
    # ---------------------------------------------------------
    # 2. Programmatic Verification (Files & Timestamps) [50 pts]
    # ---------------------------------------------------------
    ng3 = result_data.get('ng3_file', {})
    csv = result_data.get('csv_file', {})
    
    # NG3 File Check (20 pts)
    if ng3.get('exists') and ng3.get('created_during_task') and ng3.get('size_bytes', 0) > 1000:
        score += 20
        feedback_parts.append("✅ Optimized project saved (.ng3)")
    elif ng3.get('exists'):
        score += 5
        feedback_parts.append("❌ Project saved but seems invalid or not modified during task")
    else:
        feedback_parts.append("❌ Missing optimized_array.ng3 file")

    # CSV File Check (15 pts)
    if csv.get('exists') and csv.get('created_during_task') and csv.get('size_bytes', 0) > 50:
        score += 15
        feedback_parts.append("✅ Yield analysis exported (.csv)")
    elif csv.get('exists'):
        score += 5
        feedback_parts.append("❌ CSV exported but seems invalid or not modified during task")
    else:
        feedback_parts.append("❌ Missing winter_yield_optimized.csv file")
        
    # CSV Content Check (15 pts)
    csv_b64 = csv.get('content_base64', '')
    if csv_b64:
        try:
            csv_text = base64.b64decode(csv_b64).decode('utf-8', errors='ignore').lower()
            # Valid Energy3D daily yield CSVs typically contain terms related to time, solar, yield, etc.
            if "time" in csv_text or "solar" in csv_text or "yield" in csv_text or "panel" in csv_text:
                score += 15
                feedback_parts.append("✅ CSV contains valid yield data headers")
            else:
                feedback_parts.append("❌ CSV content does not appear to be Energy3D yield data")
        except:
            feedback_parts.append("❌ Could not parse CSV content")
            
    # ---------------------------------------------------------
    # 3. VLM Verification (Trajectory/UI state) [50 pts]
    # ---------------------------------------------------------
    if not query_vlm:
        feedback_parts.append("⚠️ VLM verification unavailable")
    else:
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            
            # Sample trajectory frames to capture intermediate steps (like entering spacing parameters)
            frames = sample_trajectory_frames(traj, n=4)
            final_img = get_final_screenshot(traj)
            if final_img:
                frames.append(final_img)
                
            vlm_resp = query_vlm(images=frames, prompt=VLM_PROMPT)
            if vlm_resp and vlm_resp.get("success"):
                vlm_parsed = vlm_resp.get("parsed", {})
                
                if vlm_parsed.get("row_spacing_visibly_increased", False):
                    score += 20
                    feedback_parts.append("✅ VLM verified row spacing increased")
                else:
                    feedback_parts.append("❌ VLM did not observe row spacing increase")
                    
                if vlm_parsed.get("daily_analysis_graph_opened", False):
                    score += 15
                    feedback_parts.append("✅ VLM verified daily analysis opened")
                else:
                    feedback_parts.append("❌ VLM did not observe daily analysis graph")
                    
                if vlm_parsed.get("december_21_selected", False):
                    score += 15
                    feedback_parts.append("✅ VLM verified Dec 21 date selected")
                else:
                    feedback_parts.append("❌ VLM did not observe Dec 21 date selection")
            else:
                feedback_parts.append(f"⚠️ VLM query failed or returned invalid response")
        except Exception as e:
            logger.error(f"VLM verification exception: {e}")
            feedback_parts.append("⚠️ VLM verification encountered an error")

    # ---------------------------------------------------------
    # 4. Final Evaluation
    # ---------------------------------------------------------
    # To pass, the agent must have successfully saved the CSV/NG3 and passed at least part of the VLM check.
    files_created = (ng3.get('created_during_task') and csv.get('created_during_task'))
    passed = (score >= 70) and files_created

    return {
        "passed": passed,
        "score": score,
        "feedback": "\n".join(feedback_parts)
    }