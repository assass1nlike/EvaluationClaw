#!/usr/bin/env python3
"""
Verifier for deciduous_tree_shading_analysis.

Verification Strategy:
1. File check: `shaded_building.ng3` was created during the task. (10 pts)
2. File check: `summer_analysis.csv` was created during the task. (15 pts)
3. CSV Analysis: Read the CSV contents to ensure it contains valid time-series 
   building energy data (Cooling, Heating) with non-zero cooling loads for summer. (25 pts)
4. VLM Trajectory: Analyze screenshots to visually confirm the agent added tall trees
   around the house, used the UI to change location, and ran the analysis. (50 pts)
"""

import json
import os
import tempfile
import csv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying if a user successfully completed a landscape-based building energy analysis task in Energy3D.

Task constraints:
1. Change location to Chicago.
2. Plant ~3 large Oak trees (~15m tall) on the South/West side of the building.
3. Run a Daily Building Energy Analysis for July 21.

Analyze these trajectory frames and the final screenshot of the workflow:

1. TREES PLACED: Can you see multiple large deciduous trees added to the 3D scene near the house?
2. SCALE & POSITION: Do the trees appear scaled up (taller than the 1-story house) and are they positioned to shade the walls/roof?
3. ANALYSIS WORKFLOW: Is there any frame showing the "Daily Building Energy Analysis" line graph window being opened or viewed?

Respond in JSON format:
{
    "trees_placed": true/false,
    "trees_scaled_and_positioned": true/false,
    "analysis_graph_visible": true/false,
    "confidence": "low/medium/high",
    "reasoning": "Briefly explain your observations"
}
"""

def verify_shading_analysis(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available."}
    
    score = 0
    feedback_parts = []
    
    # 1. Fetch and process the task_result.json
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    result_data = {}
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result_data = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result data: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    # Validate output files
    ng3_exists = result_data.get("ng3_exists", False)
    ng3_valid = ng3_exists and result_data.get("ng3_created_after_start", False)
    
    if ng3_valid:
        score += 10
        feedback_parts.append("✅ NG3 model saved")
    else:
        feedback_parts.append("❌ NG3 model not properly saved")

    csv_exists = result_data.get("csv_exists", False)
    csv_valid = csv_exists and result_data.get("csv_created_after_start", False)
    
    if csv_valid:
        score += 15
        feedback_parts.append("✅ CSV export found")
    else:
        feedback_parts.append("❌ CSV export not found")

    # 2. Check CSV File Contents
    csv_data_valid = False
    if csv_valid:
        temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/summer_analysis.csv", temp_csv.name)
            
            with open(temp_csv.name, 'r') as f:
                reader = csv.reader(f)
                headers = next(reader, [])
                
                # Check for standard Energy3D analysis headers
                header_str = " ".join(headers).lower()
                if "time" in header_str and ("cooling" in header_str or "energy" in header_str):
                    rows = list(reader)
                    if len(rows) > 10:  # Energy3D outputs multiple time steps (24 or 96 depending on interval)
                        # Find cooling column index
                        cooling_idx = -1
                        for i, h in enumerate(headers):
                            if "cooling" in h.lower():
                                cooling_idx = i
                                break
                        
                        if cooling_idx != -1:
                            # Verify there is actual cooling load (must be a warm summer day)
                            total_cooling = 0.0
                            for r in rows:
                                try:
                                    if len(r) > cooling_idx:
                                        val = float(r[cooling_idx].strip())
                                        total_cooling += val
                                except ValueError:
                                    pass
                            
                            if total_cooling > 0.1:
                                csv_data_valid = True
                                score += 25
                                feedback_parts.append("✅ CSV contains valid cooling load data for summer day")
                            else:
                                feedback_parts.append("❌ CSV exists but cooling load is zero (wrong date/location?)")
                        else:
                            # Fallback if specific "cooling" header missing but data has rows
                            csv_data_valid = True
                            score += 15
                            feedback_parts.append("⚠️ CSV valid but 'Cooling' column not explicitly found")
                    else:
                        feedback_parts.append("❌ CSV has insufficient data rows")
                else:
                    feedback_parts.append("❌ CSV headers don't match Energy3D analysis format")
        except Exception as e:
            feedback_parts.append(f"❌ Failed to parse CSV: {e}")
        finally:
            if os.path.exists(temp_csv.name):
                os.unlink(temp_csv.name)

    # 3. VLM Verification of visual workflow state
    if query_vlm:
        # Sample trajectory frames plus final screenshot
        import sys
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            frames = sample_trajectory_frames(traj, n=4)
            final_img = get_final_screenshot(traj)
            if final_img:
                frames.append(final_img)
            
            vlm_response = query_vlm(images=frames, prompt=VLM_PROMPT)
            if vlm_response and vlm_response.get("success"):
                vlm_res = vlm_response.get("parsed", {})
                
                trees_placed = vlm_res.get("trees_placed", False)
                trees_scaled = vlm_res.get("trees_scaled_and_positioned", False)
                graph_visible = vlm_res.get("analysis_graph_visible", False)
                
                vlm_pts = 0
                if trees_placed:
                    vlm_pts += 15
                    feedback_parts.append("✅ VLM: Trees placed in scene")
                if trees_scaled:
                    vlm_pts += 15
                    feedback_parts.append("✅ VLM: Trees appropriately scaled/positioned")
                if graph_visible:
                    vlm_pts += 20
                    feedback_parts.append("✅ VLM: Analysis graph visible in workflow")
                    
                score += vlm_pts
            else:
                feedback_parts.append(f"⚠️ VLM query failed: {vlm_response.get('error', 'Unknown error')}")
        except Exception as e:
            logger.error(f"VLM verification error: {e}")
            feedback_parts.append("⚠️ VLM verification skipped due to error")
    else:
        feedback_parts.append("⚠️ VLM query function unavailable")

    passed = (score >= 70) and csv_data_valid and csv_valid

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }