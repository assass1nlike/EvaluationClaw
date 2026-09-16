#!/usr/bin/env python3
"""
Verifier for residential_window_retrofit_analysis task.

Checks multiple independent signals to verify successful completion:
1. Valid NG3 output model saved during the task timeframe.
2. Parsable textual report showing math: Baseline - Upgraded = Savings.
3. Logical reduction in energy (Upgraded < Baseline).
4. VLM verification of the trajectory ensuring the agent actually modified window properties (U-Value & SHGC).
"""

import json
import os
import re
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_window_retrofit(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # 1. Fetch JSON results
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

    # 2. Check NG3 modification (15 points)
    if result.get("ng3_exists") and result.get("ng3_created_during_task"):
        score += 15
        feedback_parts.append("✅ Modified .ng3 model saved")
    elif result.get("ng3_exists"):
        score += 5
        feedback_parts.append("⚠️ Model saved, but timestamp indicates old file")
    else:
        feedback_parts.append("❌ Target .ng3 model not saved")

    # 3. Check PNG analysis evidence (10 points)
    if result.get("png_exists") and result.get("png_created_during_task"):
        score += 10
        feedback_parts.append("✅ Analysis screenshot saved")
    else:
        feedback_parts.append("❌ Analysis screenshot missing")

    # 4. Check Text Report & Math (35 points)
    math_ok = False
    baseline, upgraded = 0, 0
    
    if result.get("report_exists"):
        content = result.get("report_content", "")
        # Extract numerical values safely
        nums = []
        for line in content.split('\n'):
            matches = re.findall(r'[\d\.]+', line.replace(',', ''))
            if matches:
                try:
                    nums.append(float(matches[-1]))
                except ValueError:
                    pass
        
        if len(nums) >= 3:
            baseline, upgraded, savings = nums[0], nums[1], nums[2]
            
            # Check logic: energy should go down
            if baseline > upgraded and upgraded > 0:
                score += 15
                feedback_parts.append("✅ Report logic correct (Upgraded < Baseline)")
                
                # Check math: baseline - upgraded = savings
                if abs((baseline - upgraded) - savings) < 2.0:
                    score += 20
                    math_ok = True
                    feedback_parts.append("✅ Report math correctly calculated")
                else:
                    feedback_parts.append(f"❌ Report math flawed ({baseline} - {upgraded} != {savings})")
            else:
                feedback_parts.append("❌ Report values invalid (Baseline must be > Upgraded)")
        else:
            feedback_parts.append("❌ Could not parse three distinct values from report")
    else:
        feedback_parts.append("❌ Retrofit report missing")

    # 5. VLM Verification of Trajectory (40 points)
    # Since NG3 is binary, VLM is crucial to ensure properties were genuinely updated
    vlm_score = 0
    query_vlm = env_info.get('query_vlm')
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames
            # Sample trajectory to catch property edits and analysis runs
            frames = sample_trajectory_frames(traj, n=8)
            
            prompt = """You are evaluating an agent using the Energy3D software. 
            Review these sequential screenshots. Did the agent accomplish the following steps?
            1. Select windows on the building and open the property panel on the right.
            2. Edit the physical properties of the windows, specifically typing '1.2' for U-Value and '0.3' for SHGC (Solar Heat Gain Coefficient)?
            3. Open and run the 'Annual Energy Analysis' dialog?
            
            Return JSON only:
            {
                "edited_properties": true/false,
                "ran_analysis": true/false,
                "confidence": "high/medium/low"
            }"""
            
            vlm_resp = query_vlm(prompt=prompt, images=frames)
            
            if vlm_resp.get("success"):
                parsed = vlm_resp.get("parsed", {})
                if parsed.get("edited_properties"):
                    vlm_score += 25
                    feedback_parts.append("✅ VLM confirmed window properties edited")
                else:
                    feedback_parts.append("❌ VLM did not see properties edited")
                
                if parsed.get("ran_analysis"):
                    vlm_score += 15
                    feedback_parts.append("✅ VLM confirmed analysis was run")
                else:
                    feedback_parts.append("❌ VLM did not see analysis executed")
            else:
                feedback_parts.append("⚠️ VLM evaluation failed")
        except Exception as e:
            logger.error(f"VLM verification error: {e}")
            feedback_parts.append("⚠️ VLM verification encountered an error")
    
    score += vlm_score

    # Determine final pass/fail
    key_criteria_met = math_ok and (vlm_score >= 25)
    passed = score >= 70 and key_criteria_met
    
    if passed:
        feedback_parts.insert(0, "🎉 Task completed successfully!")

    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback_parts)
    }