#!/usr/bin/env python3
"""
Verifier for remote_clinic_netzero_design task.

Uses a robust multi-signal strategy:
1. Validates that the expected .ng3 project file was saved during the task.
2. Validates that the Annual Energy Analysis .csv was exported during the task.
3. Parses the copied .csv to ensure actual solar generation data exists.
4. Uses VLM on trajectory frames to verify 3D scene modifications (building isolation, solar array presence, UI interactions).
"""

import json
import os
import tempfile
import logging
import csv

try:
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
except ImportError:
    # Fallback if running outside full framework context
    def sample_trajectory_frames(traj, n=5): return []
    def get_final_screenshot(traj): return None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VERIFICATION_PROMPT = """You are evaluating an Energy3D net-zero building design task. 
Please review the provided sequence of screenshots (trajectory frames) and the final screenshot.

Determine if the agent successfully completed these workflow requirements:
1. Building Isolation: Is ONLY the flat-roof building remaining in the 3D scene? (The other 3 shapes from the starting model must be deleted).
2. Solar Array: Are there solar panels (a dense array, ~40 panels) placed on the flat roof?
3. Location Setting: Is there evidence in the UI (menus, dialogs, or panels) that the location was changed to Phoenix, AZ?
4. Thermal Properties: Is there evidence in the UI that the user adjusted wall U-values (to 0.2) or window SHGC (to 0.25)?

Respond strictly in JSON format:
{
    "only_flat_roof_building_remains": true/false,
    "solar_panels_present_on_roof": true/false,
    "location_changed_to_phoenix": true/false,
    "thermal_properties_adjusted": true/false,
    "reasoning": "Brief explanation of what visual evidence supports these flags"
}
"""

def verify_remote_clinic_design(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    feedback = []
    score = 0
    
    # -------------------------------------------------------------------------
    # 1. Fetch & Check JSON Stats
    # -------------------------------------------------------------------------
    stats_temp = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", stats_temp.name)
        with open(stats_temp.name, 'r') as f:
            result_stats = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result stats: {e}"}
    finally:
        if os.path.exists(stats_temp.name):
            os.unlink(stats_temp.name)

    ng3_file = result_stats.get('ng3_file', {})
    csv_file = result_stats.get('csv_file', {})

    if ng3_file.get('exists') and ng3_file.get('created_during_task'):
        score += 15
        feedback.append("✅ Project saved as phoenix_clinic.ng3")
    else:
        feedback.append("❌ phoenix_clinic.ng3 missing or not created during task")

    if csv_file.get('exists') and csv_file.get('created_during_task'):
        score += 15
        feedback.append("✅ Energy simulation exported as phoenix_clinic_energy.csv")
    else:
        feedback.append("❌ phoenix_clinic_energy.csv missing or not created during task")

    # -------------------------------------------------------------------------
    # 2. Programmatic CSV Content Verification
    # -------------------------------------------------------------------------
    csv_temp = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
    csv_has_solar_data = False
    
    if csv_file.get('exists'):
        try:
            copy_from_env("/home/ga/Documents/Energy3D/phoenix_clinic_energy.csv", csv_temp.name)
            with open(csv_temp.name, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader, [])
                
                # Find column containing "Solar" or "Photovoltaic"
                solar_col_idx = -1
                for i, col in enumerate(header):
                    if 'solar' in col.lower() or 'photovoltaic' in col.lower() or 'pv' in col.lower():
                        solar_col_idx = i
                        break
                
                if solar_col_idx != -1:
                    # Check if there's non-zero generation in any month
                    for row in reader:
                        if len(row) > solar_col_idx:
                            try:
                                val = float(row[solar_col_idx])
                                if val > 0.0:
                                    csv_has_solar_data = True
                                    break
                            except ValueError:
                                pass
        except Exception as e:
            logger.warning(f"Error parsing CSV: {e}")
        finally:
            if os.path.exists(csv_temp.name):
                os.unlink(csv_temp.name)

    if csv_has_solar_data:
        score += 10
        feedback.append("✅ CSV contains valid positive solar generation data")
    elif csv_file.get('exists'):
        feedback.append("❌ CSV found but contains no valid solar generation data (panels missing or simulation failed)")

    # -------------------------------------------------------------------------
    # 3. VLM Trajectory Verification
    # -------------------------------------------------------------------------
    vlm_success = False
    if query_vlm:
        frames = sample_trajectory_frames(traj, n=4)
        final_img = get_final_screenshot(traj)
        images = frames + [final_img] if final_img else frames

        if images:
            vlm_response = query_vlm(images=images, prompt=VERIFICATION_PROMPT)
            parsed = vlm_response.get("parsed", {})
            
            b_isolated = parsed.get("only_flat_roof_building_remains", False)
            solar_present = parsed.get("solar_panels_present_on_roof", False)
            loc_changed = parsed.get("location_changed_to_phoenix", False)
            therm_adj = parsed.get("thermal_properties_adjusted", False)
            
            if b_isolated:
                score += 15
                feedback.append("✅ VLM verified: Building isolated")
            else:
                feedback.append("❌ VLM verified: Extra buildings not deleted")
                
            if solar_present:
                score += 15
                feedback.append("✅ VLM verified: Solar array present on roof")
            else:
                feedback.append("❌ VLM verified: Solar array missing")
                
            if loc_changed:
                score += 15
                feedback.append("✅ VLM verified: Location set to Phoenix")
            else:
                feedback.append("⚠️ VLM did not clearly see location change to Phoenix")
                
            if therm_adj:
                score += 15
                feedback.append("✅ VLM verified: Thermal properties adjusted")
            else:
                feedback.append("⚠️ VLM did not clearly see thermal property adjustments")
                
            if b_isolated and solar_present:
                vlm_success = True
        else:
            feedback.append("❌ No images available for VLM verification")
    else:
        feedback.append("⚠️ query_vlm not available, skipping visual checks")

    # -------------------------------------------------------------------------
    # 4. Final Scoring
    # -------------------------------------------------------------------------
    # Key requirements: Project saved, simulation exported with solar data, and VLM confirmed solar array.
    key_criteria_met = (
        ng3_file.get('created_during_task', False) and 
        csv_file.get('created_during_task', False) and 
        csv_has_solar_data and 
        vlm_success
    )
    
    passed = score >= 70 and key_criteria_met

    return {
        "passed": passed,
        "score": min(score, 100),
        "feedback": " | ".join(feedback)
    }