#!/usr/bin/env python3
"""
Verifier for aviation_hangar_solar_yield_pruning task.

Verification Strategy:
1. File Verification (30 pts): Ensures `hangar_optimized.ng3` and `optimized_yield.csv` were saved after the task started.
2. Data Verification (10 pts): Parses the exported CSV to confirm it has valid tabular data (headers + rows) indicating solar panels remain.
3. Visual/Trajectory Verification (60 pts): Uses VLM to inspect trajectory frames and confirm the solar heatmap was run, the location dialog was opened, and the array was selectively pruned.
"""

import json
import tempfile
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_hangar_pruning(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # ====================================================================
    # 1. Fetch File Verification Results
    # ====================================================================
    temp_res = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_res.name)
        with open(temp_res.name, 'r') as f:
            res = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to load result payload: {e}"}
    finally:
        if os.path.exists(temp_res.name): 
            os.unlink(temp_res.name)
            
    start_time = res.get('start_time', 0)
    
    # Verify NG3 File
    if res.get('ng3_exists'):
        if res.get('ng3_mtime', 0) > start_time:
            score += 15
            feedback_parts.append("✅ hangar_optimized.ng3 saved")
        else:
            feedback_parts.append("❌ hangar_optimized.ng3 has old timestamp (not updated)")
    else:
        feedback_parts.append("❌ hangar_optimized.ng3 missing")
        
    # Verify CSV File and Data
    csv_valid = False
    if res.get('csv_exists'):
        if res.get('csv_mtime', 0) > start_time:
            score += 15
            feedback_parts.append("✅ optimized_yield.csv exported")
            
            # Fetch and parse CSV directly
            temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
            try:
                copy_from_env("/tmp/optimized_yield.csv", temp_csv.name)
                with open(temp_csv.name, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read().strip().split('\n')
                    if len(content) > 1:
                        panel_count = len(content) - 1  # Excluding header row
                        csv_valid = True
                        score += 10
                        feedback_parts.append(f"✅ CSV validates ({panel_count} active panels left)")
                    else:
                        feedback_parts.append("❌ CSV exists but is empty/missing panel rows")
            except Exception as e:
                feedback_parts.append(f"❌ Failed to parse CSV: {e}")
            finally:
                if os.path.exists(temp_csv.name): 
                    os.unlink(temp_csv.name)
        else:
            feedback_parts.append("❌ optimized_yield.csv has old timestamp")
    else:
        feedback_parts.append("❌ optimized_yield.csv missing")

    # ====================================================================
    # 2. VLM Trajectory Verification
    # ====================================================================
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            
            frames = sample_trajectory_frames(traj, n=5)
            final = get_final_screenshot(traj)
            if final: 
                frames.append(final)
            
            prompt = """You are verifying an Energy3D task where an agent must analyze and prune underperforming solar panels from a building structure.
Please examine these trajectory frames and determine:
1. Did the agent open the Location/City dialog (to set the location to Seattle)?
2. Did the agent run a Solar Radiation / Annual Yield Analysis (indicated by a color heat map appearing on the solar panels)?
3. Did the agent selectively delete/prune some solar panels while leaving others intact?
4. Does the final state show a partially pruned array (not fully covered like the start, but not fully empty either)?

Respond in pure JSON format with exactly these boolean keys:
{
    "location_dialog_opened": true/false,
    "solar_heatmap_run": true/false,
    "panels_selectively_pruned": true/false,
    "final_array_partially_pruned": true/false
}"""
            
            vlm_res = query_vlm(images=frames, prompt=prompt)
            if vlm_res and vlm_res.get('success'):
                parsed = vlm_res.get('parsed', {})
                
                if parsed.get('location_dialog_opened'):
                    score += 10
                    feedback_parts.append("✅ VLM: Location adjusted")
                
                if parsed.get('solar_heatmap_run'):
                    score += 20
                    feedback_parts.append("✅ VLM: Solar heat map activated")
                    
                if parsed.get('panels_selectively_pruned') or parsed.get('final_array_partially_pruned'):
                    score += 30
                    feedback_parts.append("✅ VLM: Panels correctly pruned")
            else:
                feedback_parts.append(f"⚠️ VLM check failed: {vlm_res.get('error', 'Unknown Error')}")
                
        except ImportError:
            feedback_parts.append("⚠️ VLM utilities unavailable")

    # Final threshold check
    passed = score >= 70 and csv_valid
    
    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback_parts)
    }