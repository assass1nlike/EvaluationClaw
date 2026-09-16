#!/usr/bin/env python3
"""
Verifier for datacenter_rooftop_solar_thermal_offset task.

Uses MULTIPLE INDEPENDENT SIGNALS for verification:
1. File check: `datacenter_shaded.ng3` created after task start.
2. File check: `thermal_offset_results.csv` created after task start.
3. Content check: Parsed CSV actually contains proper thermal/solar output logs.
4. Trajectory VLM: Verified location set to Phoenix.
5. Trajectory VLM: Verified flat-roof target was chosen and populated with panels.
6. Trajectory VLM: Verified Annual Analysis window was accessed.
"""

import json
import os
import tempfile
import logging

try:
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
except ImportError:
    # Fallback if imports vary slightly
    def sample_trajectory_frames(*args, **kwargs): return []
    def get_final_screenshot(*args, **kwargs): return None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


VLM_PROMPT = """You are verifying an agent's workflow trajectory in the Energy3D engineering application.

TASK:
1. Locate the flat-roof building (ignore the pitched/slanted roof buildings in the scene).
2. Change the city/location to Phoenix, AZ.
3. Install a dense array of solar panels on the flat roof.
4. Run the "Annual Building Energy Analysis".

Carefully examine the provided trajectory frames and final screenshot, then answer:
1. Did the agent open the location/city settings and select Phoenix (or is Phoenix visible in the environment status)?
2. Did the agent place a significant number of solar panels specifically on a flat-roofed building?
3. Did the agent open an "Annual Energy Analysis" or "Annual Building Energy Analysis" graph/dialog window at some point?

Respond strictly with JSON ONLY:
{
    "city_set_to_phoenix": true/false,
    "panels_on_flat_roof": true/false,
    "analysis_graph_visible": true/false,
    "confidence": "high/medium/low",
    "reasoning": "brief explanation"
}
"""

def verify_datacenter_rooftop_solar(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')

    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Execution error: copy_from_env not available"}
    
    score = 0
    feedback_parts = []
    
    # 1. READ EXPORTED JSON METADATA
    temp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_json.name)
        with open(temp_json.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read exported results: {e}"}
    finally:
        if os.path.exists(temp_json.name):
            os.unlink(temp_json.name)

    # 2. CHECK .NG3 FILE
    ng3_created = result.get('ng3_created_during_task', False)
    if ng3_created and result.get('ng3_size_bytes', 0) > 1000:
        score += 15
        feedback_parts.append("✅ New project (.ng3) saved")
    else:
        feedback_parts.append("❌ Target .ng3 not properly saved")

    # 3. CHECK CSV FILE
    csv_created = result.get('csv_created_during_task', False)
    if csv_created and result.get('csv_size_bytes', 0) > 50:
        score += 15
        feedback_parts.append("✅ CSV export file created")
    else:
        feedback_parts.append("❌ Target CSV not exported")

    # 4. CONTENT CHECK OF CSV (Must contain actual energy data logs)
    csv_valid = False
    if csv_created:
        temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        try:
            # Pull the actual CSV from the VM
            copy_from_env("/home/ga/Documents/Energy3D/thermal_offset_results.csv", temp_csv.name)
            with open(temp_csv.name, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read().lower()
                if "cooling" in content and "solar" in content:
                    csv_valid = True
                    score += 20
                    feedback_parts.append("✅ CSV correctly contains multi-variable (Cooling + Solar) data")
                else:
                    feedback_parts.append("❌ CSV exists but is missing expected analysis metrics (Cooling/Solar)")
        except Exception as e:
            logger.warning(f"Failed to copy/read CSV content: {e}")
            feedback_parts.append("❌ Could not read CSV contents")
        finally:
            if os.path.exists(temp_csv.name):
                os.unlink(temp_csv.name)

    # 5. VLM TRAJECTORY VERIFICATION
    if query_vlm:
        frames = sample_trajectory_frames(traj, n=4)
        final = get_final_screenshot(traj)
        
        images = []
        if frames: images.extend(frames)
        if final: images.append(final)
        
        if images:
            vlm_response = query_vlm(images=images, prompt=VLM_PROMPT)
            parsed = vlm_response.get("parsed", {})
            
            # City Setting
            if parsed.get("city_set_to_phoenix", False):
                score += 15
                feedback_parts.append("✅ City successfully updated to Phoenix")
            else:
                feedback_parts.append("❌ City not updated to Phoenix")
                
            # Geometry & Placement
            panels_on_roof = parsed.get("panels_on_flat_roof", False)
            if panels_on_roof:
                score += 20
                feedback_parts.append("✅ Dense solar array placed on flat-roof building")
            else:
                feedback_parts.append("❌ No proper panel placement detected on target flat roof")
                
            # Annual Analysis Tool
            if parsed.get("analysis_graph_visible", False):
                score += 15
                feedback_parts.append("✅ Annual Energy Analysis workflow verified")
            else:
                feedback_parts.append("❌ Annual Energy Analysis dialog not detected in trajectory")
        else:
            feedback_parts.append("❌ No trajectory images available for VLM verification")
    else:
        feedback_parts.append("❌ VLM endpoint unavailable")

    # Final scoring calculation
    # Agent must successfully place panels and export a valid CSV to be considered passing
    key_criteria_met = csv_valid and panels_on_roof
    passed = (score >= 70) and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": "\n".join(feedback_parts)
    }