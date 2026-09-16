#!/usr/bin/env python3
"""
Verifier for HOA Compliant Energy Retrofit task.

Evaluates:
1. File saved & created during task
2. Wall U-values selectively upgraded (via XML parsing & VLM fallback)
3. Window U-values selectively upgraded (via XML parsing & VLM fallback)
4. Solar panels added (via XML parsing & VLM fallback)
5. Strict constraint: NO panels on the South-facing roof (VLM visual confirmation)
"""

import json
import tempfile
import os
import re
import logging
import zipfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_hoa_compliant_retrofit(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    temp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    temp_ng3 = tempfile.NamedTemporaryFile(delete=False, suffix='.ng3')
    
    try:
        # Retrieve JSON state
        copy_from_env("/tmp/task_result.json", temp_json.name)
        with open(temp_json.name, 'r') as f:
            result = json.load(f)
            
        # Retrieve the project file if it exists
        if result.get('file_exists'):
            copy_from_env("/tmp/result.ng3", temp_ng3.name)
            
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to retrieve files: {e}"}
    finally:
        if os.path.exists(temp_json.name):
            os.unlink(temp_json.name)

    # 1. Check File Creation (10 pts)
    file_saved = result.get('file_created', False)
    if file_saved:
        score += 10
        feedback_parts.append("File successfully created/modified")
        if "hoa_compliant_retrofit" not in result.get('used_path', ''):
            feedback_parts.append("(Note: Saved over starter file instead of expected name)")
    else:
        feedback_parts.append("Project file not saved or modified")
        return {"passed": False, "score": 0, "feedback": " | ".join(feedback_parts)}

    # Parse .ng3 file programmatically
    # Energy3D .ng3 files can be plain XML or zipped XML depending on version/settings
    content = ""
    if os.path.exists(temp_ng3.name):
        try:
            if zipfile.is_zipfile(temp_ng3.name):
                with zipfile.ZipFile(temp_ng3.name, 'r') as z:
                    content = z.read(z.namelist()[0]).decode('utf-8', errors='ignore')
            else:
                with open(temp_ng3.name, 'rb') as f:
                    content = f.read().decode('utf-8', errors='ignore')
        except Exception as e:
            logger.warning(f"Could not parse ng3 file programmatically: {e}")

    # XML Programmatic Checks
    xml_walls_upgraded = False
    xml_wall_compliance = False
    xml_windows_upgraded = False
    xml_window_compliance = False
    xml_solar_added = False
    
    if content:
        # Check solar panel element count
        solar_count = len(re.findall(r'SolarPanel', content, re.IGNORECASE))
        if solar_count >= 6:
            xml_solar_added = True
            logger.info(f"XML Check: Found {solar_count} solar panels.")

        # Check U-values
        # Look for numbers near 'uValue' (accounting for XML tags in between)
        u_values = [float(x) for x in re.findall(r'uValue.{0,40}?([0-9]*\.[0-9]+)', content, re.IGNORECASE)]
        
        if u_values:
            logger.info(f"XML Check: Found U-values: {u_values}")
            # Did they upgrade some? (U-value <= 0.5)
            if any(u <= 0.5 for u in u_values):
                xml_walls_upgraded = True
            # Did they leave some compliant? (U-value > 1.0, typically original is ~0.8-2.0, so checking >1.0 ensures south wall unedited)
            if any(u > 0.6 for u in u_values):
                xml_wall_compliance = True
                
            # Same logic applied to windows (target <= 1.5, original > 1.5)
            if any(u <= 1.5 for u in u_values):
                xml_windows_upgraded = True
            if any(u > 1.5 for u in u_values):
                xml_window_compliance = True
                
    # VLM Fallback and Roof Constraint Check
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
    frames = sample_trajectory_frames(traj, n=4)
    final = get_final_screenshot(traj)
    images_to_analyze = frames + [final] if final else frames
    
    vlm_prompt = """You are verifying an agent's compliance with strict HOA guidelines in Energy3D.
    The building has a South-facing side, easily identified as the side with the large main windows and front door.
    
    Analyze the trajectory frames and determine:
    1. Are there solar panels added to the roof?
    2. Are there ZERO solar panels on the South-facing roof facet (the roof facet directly above the large main windows)?
    3. Are there solar panels safely on the OTHER roof facets (North, East, or West)?
    4. Does the trajectory show the agent editing properties (like U-Value) in the side panels?
    
    Respond in strict JSON:
    {
      "solar_panels_added": true/false,
      "south_roof_is_clear": true/false,
      "panels_on_other_roofs": true/false,
      "edited_properties": true/false
    }
    """
    
    vlm_solar_added = False
    vlm_south_roof_clear = False
    vlm_panels_other_roofs = False
    vlm_edited_properties = False
    
    if query_vlm and images_to_analyze:
        vlm_resp = query_vlm(images=images_to_analyze, prompt=vlm_prompt)
        if vlm_resp and vlm_resp.get("success"):
            parsed = vlm_resp.get("parsed", {})
            vlm_solar_added = parsed.get("solar_panels_added", False)
            vlm_south_roof_clear = parsed.get("south_roof_is_clear", False)
            vlm_panels_other_roofs = parsed.get("panels_on_other_roofs", False)
            vlm_edited_properties = parsed.get("edited_properties", False)

    # Clean up NG3
    if os.path.exists(temp_ng3.name):
        os.unlink(temp_ng3.name)

    # 2. Walls Upgraded (20 pts)
    if xml_walls_upgraded or vlm_edited_properties:
        score += 20
        feedback_parts.append("Wall U-values upgraded")
        
    # 3. Wall Compliance (15 pts) - Ensures they didn't bulk-upgrade everything
    if xml_wall_compliance or (vlm_edited_properties and vlm_south_roof_clear):
        score += 15
        feedback_parts.append("Wall constraints respected")
        
    # 4. Windows Upgraded (15 pts)
    if xml_windows_upgraded or vlm_edited_properties:
        score += 15
        feedback_parts.append("Window U-values upgraded")
        
    # 5. Window Compliance (10 pts)
    if xml_window_compliance or (vlm_edited_properties and vlm_south_roof_clear):
        score += 10
        feedback_parts.append("Window constraints respected")
        
    # 6. Solar Added (10 pts)
    if xml_solar_added or vlm_solar_added or vlm_panels_other_roofs:
        score += 10
        feedback_parts.append("Solar panels added")
        
    # 7. Roof Compliance (20 pts) - The most critical visual constraint
    if vlm_south_roof_clear and (vlm_panels_other_roofs or xml_solar_added):
        score += 20
        feedback_parts.append("HOA Roof constraint respected (no panels on South)")
    elif not vlm_south_roof_clear and (xml_solar_added or vlm_solar_added):
        feedback_parts.append("FAILED HOA constraint: Panels placed on South roof")

    # Pass condition: Must have minimum score and specifically meet the negative roof constraint
    key_constraints_met = vlm_south_roof_clear and (xml_solar_added or vlm_solar_added or vlm_panels_other_roofs)
    passed = score >= 70 and key_constraints_met

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }