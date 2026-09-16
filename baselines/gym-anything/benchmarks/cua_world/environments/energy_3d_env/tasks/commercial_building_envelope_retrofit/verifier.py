#!/usr/bin/env python3
"""
Verifier for commercial_building_envelope_retrofit task.

VERIFICATION METRICS:
1. File operations: Upgraded NG3 file saved and text file created (10 points)
2. NG3 XML parsing: Roof U-value updated to 0.15 (25 points)
3. NG3 XML parsing: Window U-values to 1.4 and SHGC to 0.25 (35 points proportional)
4. Trajectory VLM: Verified viewing of "Daily Energy Analysis" (15 points)
5. Analysis Result: Numerical cooling value recorded in text file (15 points)
"""

import json
import os
import re
import tempfile
import logging
import xml.etree.ElementTree as ET

# Attempt to load VLM utils, robust to environment unavailability during test parsing
try:
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
except ImportError:
    sample_trajectory_frames = None
    get_final_screenshot = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """You are verifying an Energy3D task execution.
The user was asked to run a "Daily Energy Analysis" for a commercial building on July 15.
Review these screenshots from their session trajectory.
Did the user successfully open and view the Daily Energy Analysis graph window at any point?
(Look for a popup window containing a bar chart with "Heating", "Cooling", and "Solar" data).

Respond in JSON format:
{
    "analysis_graph_visible": true/false,
    "confidence": "low/medium/high",
    "reasoning": "brief explanation"
}"""

def check_ng3_modifications(filepath):
    """
    Parses Energy3D's Java XMLEncoder output to verify object properties.
    Returns: (roof_count, roof_correct, window_count, window_correct)
    """
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        
        # Verify roofs
        roofs = root.findall(".//object[@class='org.concord.energy3d.model.Roof']")
        roof_count = len(roofs)
        roof_correct = 0
        
        for r in roofs:
            for v in r.findall("void"):
                if v.get("property") == "uValue":
                    d = v.find("double")
                    if d is not None and "0.15" in d.text:
                        roof_correct += 1
                        break
                        
        # Verify windows
        windows = root.findall(".//object[@class='org.concord.energy3d.model.Window']")
        window_count = len(windows)
        window_correct = 0
        
        for w in windows:
            u_ok = False
            shgc_ok = False
            for v in w.findall("void"):
                if v.get("property") == "uValue":
                    d = v.find("double")
                    if d is not None and "1.4" in d.text:
                        u_ok = True
                if v.get("property") == "shgc":
                    d = v.find("double")
                    if d is not None and "0.25" in d.text:
                        shgc_ok = True
            if u_ok and shgc_ok:
                window_correct += 1
                
        return roof_count, roof_correct, window_count, window_correct
    except Exception as e:
        logger.error(f"Error parsing NG3 file: {e}")
        return -1, -1, -1, -1

def verify_retrofit_task(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "System error: copy_from_env missing"}
        
    score = 0
    feedback_parts = []
    
    # 1. Read task_result.json
    temp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_json.name)
        with open(temp_json.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to load result JSON: {e}"}
    finally:
        os.unlink(temp_json.name)
        
    # File Checks
    upgraded_exists = result.get('upgraded_file_exists', False)
    upgraded_modified = result.get('upgraded_file_modified_during_task', False)
    results_exists = result.get('results_file_exists', False)
    
    if upgraded_exists and upgraded_modified:
        score += 10
        feedback_parts.append("NG3 file successfully saved")
    elif upgraded_exists:
        feedback_parts.append("NG3 file exists but timestamp indicates it wasn't modified during task")
    else:
        feedback_parts.append("NG3 file not saved")
        
    # 2 & 3. NG3 Content Analysis
    roof_count = 0
    window_count = 0
    
    if upgraded_exists and upgraded_modified:
        temp_ng3 = tempfile.NamedTemporaryFile(delete=False, suffix='.ng3')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/office_upgraded.ng3", temp_ng3.name)
            r_cnt, r_cor, w_cnt, w_cor = check_ng3_modifications(temp_ng3.name)
            
            if r_cnt > 0:
                roof_count = r_cnt
                roof_score = 25 * (r_cor / r_cnt)
                score += roof_score
                if r_cor == r_cnt:
                    feedback_parts.append("Roof U-value upgraded to 0.15")
                else:
                    feedback_parts.append(f"Roof upgraded partially ({r_cor}/{r_cnt})")
            else:
                feedback_parts.append("Failed to find roof objects in NG3")
                
            if w_cnt > 0:
                window_count = w_cnt
                window_score = 35 * (w_cor / w_cnt)
                score += window_score
                if w_cor == w_cnt:
                    feedback_parts.append("All windows upgraded to U=1.4, SHGC=0.25")
                elif w_cor > 0:
                    feedback_parts.append(f"Windows partially upgraded ({w_cor}/{w_cnt})")
                else:
                    feedback_parts.append("No windows upgraded correctly")
            else:
                feedback_parts.append("Failed to find window objects in NG3")
                
        except Exception as e:
            feedback_parts.append(f"Error reading NG3: {e}")
        finally:
            os.unlink(temp_ng3.name)
            
    # 4. Results Text File Check
    if results_exists:
        temp_txt = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/cooling_results.txt", temp_txt.name)
            with open(temp_txt.name, 'r') as f:
                content = f.read()
                
            # Check for any numerical value (int or float) representing the load
            if re.search(r'\d+\.?\d*', content):
                score += 15
                feedback_parts.append("Cooling load numerical result recorded")
            else:
                feedback_parts.append("Results file found but contained no numerical cooling value")
        except Exception as e:
            feedback_parts.append(f"Error reading cooling results: {e}")
        finally:
            os.unlink(temp_txt.name)
    else:
        feedback_parts.append("Cooling results file not found")
        
    # 5. VLM Trajectory Verification
    if query_vlm and sample_trajectory_frames and get_final_screenshot:
        try:
            frames = sample_trajectory_frames(traj, n=6)
            final = get_final_screenshot(traj)
            images = frames + [final] if final else frames
            
            vlm_response = query_vlm(images=images, prompt=VLM_PROMPT)
            parsed = vlm_response.get("parsed", {})
            
            if parsed.get("analysis_graph_visible", False):
                score += 15
                feedback_parts.append("VLM confirmed Daily Energy Analysis was run")
            else:
                feedback_parts.append("VLM did not detect the Daily Energy Analysis graph")
        except Exception as e:
            logger.error(f"VLM check failed: {e}")
            feedback_parts.append("VLM verification failed")

    # Round score safely
    score = int(min(100, max(0, score)))
    
    # Passing requires saving the file and successfully modifying at least some structure
    passed = score >= 70
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }