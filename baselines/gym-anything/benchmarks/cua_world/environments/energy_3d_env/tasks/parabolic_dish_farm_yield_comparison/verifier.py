#!/usr/bin/env python3
import os
import json
import re
import tempfile
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying if an agent successfully designed a parabolic dish solar farm in Energy3D.

Look at the provided trajectory frames and the final screenshot.
Please answer the following questions:
1. Did the agent place Parabolic Dishes (large satellite-dish-like structures) on the foundation?
2. Did the agent open the Location menu/settings and select Seattle, WA at any point?
3. Did the agent run an Annual Energy Analysis (or Yield Analysis) window that shows a bar chart of monthly energy output?

Respond in JSON format:
{
    "placed_parabolic_dishes": true/false,
    "changed_location_seattle": true/false,
    "ran_yield_analysis": true/false,
    "reasoning": "Brief explanation"
}
"""

def verify_dish_farm(traj: Dict[str, Any], env_info: Dict[str, Any], task_info: Dict[str, Any]) -> Dict[str, Any]:
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    metadata = task_info.get('metadata', {})
    min_dishes = metadata.get('min_dish_count', 25)
    max_dishes = metadata.get('max_dish_count', 45)
    yield_ratio_min = metadata.get('yield_ratio_min', 1.3)

    score = 0
    feedback_parts = []
    
    # 1. Read JSON result from container
    temp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    result = {}
    try:
        copy_from_env("/tmp/task_result.json", temp_json.name)
        with open(temp_json.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load task result JSON: {e}")
    finally:
        if os.path.exists(temp_json.name):
            os.unlink(temp_json.name)

    # Base file scores
    ng3_valid = False
    txt_valid = False

    if result.get("ng3_exists") and result.get("ng3_created_during_task"):
        score += 15
        ng3_valid = True
        feedback_parts.append("✅ dish_farm_final.ng3 created")
    elif result.get("ng3_exists"):
        score += 5
        feedback_parts.append("⚠️ dish_farm_final.ng3 exists but was not created during task")
    else:
        feedback_parts.append("❌ dish_farm_final.ng3 missing")

    if result.get("txt_exists") and result.get("txt_created_during_task"):
        score += 15
        txt_valid = True
        feedback_parts.append("✅ yield_comparison.txt created")
    elif result.get("txt_exists"):
        score += 5
        feedback_parts.append("⚠️ yield_comparison.txt exists but was not created during task")
    else:
        feedback_parts.append("❌ yield_comparison.txt missing")

    # 2. Parse the text file
    txt_score = 0
    if result.get("txt_exists"):
        temp_txt = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/yield_comparison.txt", temp_txt.name)
            with open(temp_txt.name, 'r') as f:
                content = f.read()
            
            # Clean commas and extract numbers to be robust against formatting variations
            text_clean = re.sub(r',', '', content)
            numbers = [float(n) for n in re.findall(r'\b\d+\.?\d*\b', text_clean)]
            
            # Extract dish count heuristically
            possible_dishes = [n for n in numbers if 10 <= n <= 100]
            if possible_dishes:
                dish_count = possible_dishes[0]
                if min_dishes <= dish_count <= max_dishes:
                    txt_score += 10
                    score += 10
                    feedback_parts.append(f"✅ Valid dish count reported ({dish_count})")
                else:
                    feedback_parts.append(f"❌ Reported dish count ({dish_count}) out of expected range ({min_dishes}-{max_dishes})")
            else:
                feedback_parts.append("❌ Could not parse valid dish count from text file")

            # Extract yields heuristically
            possible_yields = [n for n in numbers if n > 1000]
            if len(possible_yields) >= 2:
                possible_yields.sort()
                seattle_yield = possible_yields[-2]
                phoenix_yield = possible_yields[-1]
                
                # Check CSP Logic: Desert sunlight > Cloud cover
                if phoenix_yield > seattle_yield * yield_ratio_min:
                    txt_score += 20
                    score += 20
                    feedback_parts.append("✅ Yield logic correct (Phoenix CSP > Seattle CSP)")
                else:
                    feedback_parts.append(f"❌ Yield logic failed (Phoenix: {phoenix_yield}, Seattle: {seattle_yield})")
            else:
                feedback_parts.append("❌ Could not parse two distinct yield values > 1000")

        except Exception as e:
            logger.error(f"Failed to parse text file: {e}")
            feedback_parts.append("❌ Error reading yield_comparison.txt")
        finally:
            if os.path.exists(temp_txt.name):
                os.unlink(temp_txt.name)

    # 3. VLM Verification using Trajectory Frames
    if query_vlm:
        try:
            # Dynamically import framework VLM utilities to capture the workflow
            try:
                from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
                frames = sample_trajectory_frames(traj, n=4)
                final = get_final_screenshot(traj)
                images = frames + [final] if final else frames
            except ImportError:
                # Fallback if specific imports fail
                images = []
                if "final_screenshot" in traj:
                    images.append(traj["final_screenshot"])
                
            if images:
                vlm_res = query_vlm(images=images, prompt=VLM_PROMPT)
                if vlm_res.get("success"):
                    parsed = vlm_res.get("parsed", {})
                    if parsed.get("placed_parabolic_dishes"):
                        score += 15
                        feedback_parts.append("✅ VLM: Parabolic dishes placed")
                    else:
                        feedback_parts.append("❌ VLM: Parabolic dishes NOT placed")
                        
                    if parsed.get("changed_location_seattle"):
                        score += 10
                        feedback_parts.append("✅ VLM: Location change detected")
                    else:
                        feedback_parts.append("❌ VLM: Location change NOT detected")
                        
                    if parsed.get("ran_yield_analysis"):
                        score += 15
                        feedback_parts.append("✅ VLM: Yield analysis run")
                    else:
                        feedback_parts.append("❌ VLM: Yield analysis NOT run")
                else:
                    feedback_parts.append(f"⚠️ VLM query failed: {vlm_res.get('error')}")
            else:
                feedback_parts.append("⚠️ No images available for VLM verification")
        except Exception as e:
            logger.error(f"VLM verification error: {e}")
            feedback_parts.append("⚠️ VLM verification encountered an error")

    # Pass criteria: Score must be solid, file outputs valid, and analysis text parsed
    key_criteria_met = ng3_valid and txt_score > 0
    passed = score >= 70 and key_criteria_met

    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback_parts)
    }