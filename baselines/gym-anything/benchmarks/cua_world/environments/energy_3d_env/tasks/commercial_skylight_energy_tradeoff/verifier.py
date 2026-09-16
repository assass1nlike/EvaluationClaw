#!/usr/bin/env python3
"""
Verifier for commercial_skylight_energy_tradeoff task.
"""

import json
import tempfile
import os
import re
import logging
from typing import Dict, Any

from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VLM_PROMPT = """
You are verifying if a user successfully performed a building energy analysis task in Energy3D.
Review the provided sequence of screenshots from their session.

Did the user do the following:
1. "skylights_added": Did the user place windows/skylights on the ROOF of the building? (True/False)
2. "analysis_run": Is there evidence that the user ran the Annual Building Energy Analysis? Look for a pop-up window or bottom panel containing a bar graph showing monthly heating/cooling loads. (True/False)

Answer strictly in JSON format:
{
    "skylights_added": true/false,
    "analysis_run": true/false,
    "reasoning": "Brief explanation of what was observed in the frames."
}
"""

def parse_report_content(content: str) -> Dict[str, Any]:
    """Parse the specific report format requested in the task."""
    result = {
        "valid_format": False,
        "baseline_total": None,
        "skylight_total": None,
        "conclusion": None,
        "logic_correct": False
    }
    
    # Extract values using regex
    baseline_match = re.search(r"Baseline Total:\s*([\d\.,]+)", content, re.IGNORECASE)
    skylight_match = re.search(r"Skylight Total:\s*([\d\.,]+)", content, re.IGNORECASE)
    conclusion_match = re.search(r"Conclusion:\s*(.*)", content, re.IGNORECASE)
    
    # Require all 7 lines to be somewhat present
    lines = [line.strip() for line in content.split('\n') if line.strip()]
    if len(lines) >= 7 and baseline_match and skylight_match and conclusion_match:
        result["valid_format"] = True
        
        try:
            b_total = float(baseline_match.group(1).replace(',', ''))
            s_total = float(skylight_match.group(1).replace(',', ''))
            result["baseline_total"] = b_total
            result["skylight_total"] = s_total
            
            conc = conclusion_match.group(1).lower()
            result["conclusion"] = conc
            
            # Logic check
            if s_total > b_total and "increase" in conc and "decrease" not in conc:
                result["logic_correct"] = True
            elif s_total < b_total and "decrease" in conc:
                result["logic_correct"] = True
            elif s_total == b_total:
                result["logic_correct"] = True  # Edge case
                
        except ValueError:
            pass # Failed to parse floats
            
    return result

def verify_skylight_tradeoff(traj: Dict[str, Any], env_info: Dict[str, Any], task_info: Dict[str, Any]) -> Dict[str, Any]:
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # 1. Read export JSON
    temp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_json.name)
        with open(temp_json.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result JSON: {e}"}
    finally:
        if os.path.exists(temp_json.name):
            os.unlink(temp_json.name)
            
    # File existence checks (20 pts)
    report_ok = result.get("report_exists", False) and result.get("report_created_during_task", False)
    project_ok = result.get("project_exists", False) and result.get("project_created_during_task", False)
    
    if report_ok:
        score += 10
        feedback_parts.append("Report file created")
    else:
        feedback_parts.append("Report file missing or not newly created")
        
    if project_ok:
        score += 10
        feedback_parts.append("Project file saved")
    else:
        feedback_parts.append("Project file missing or not newly created")

    # 2. Read Report Content
    temp_report = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
    report_content = ""
    try:
        copy_from_env("/home/ga/Documents/Energy3D/skylight_tradeoff_report.txt", temp_report.name)
        with open(temp_report.name, 'r', encoding='utf-8') as f:
            report_content = f.read()
    except Exception:
        pass
    finally:
        if os.path.exists(temp_report.name):
            os.unlink(temp_report.name)

    # Content parsing (20 pts)
    if report_content:
        parsed_report = parse_report_content(report_content)
        if parsed_report["valid_format"]:
            score += 10
            feedback_parts.append("Report format valid")
            if parsed_report["logic_correct"]:
                score += 10
                feedback_parts.append("Tradeoff logic mathematically correct")
            else:
                feedback_parts.append("Tradeoff conclusion does not match values")
        else:
            feedback_parts.append("Report missing required formatting or values")
    else:
        feedback_parts.append("Could not read report content")

    # 3. VLM Trajectory Verification (60 pts)
    if query_vlm:
        frames = sample_trajectory_frames(traj, n=4)
        final_frame = get_final_screenshot(traj)
        if final_frame:
            frames.append(final_frame)
            
        if frames:
            vlm_result = query_vlm(prompt=VLM_PROMPT, images=frames)
            if vlm_result.get("success"):
                vlm_parsed = vlm_result.get("parsed", {})
                
                if vlm_parsed.get("skylights_added", False):
                    score += 30
                    feedback_parts.append("VLM: Skylights observed on roof")
                else:
                    feedback_parts.append("VLM: No skylights observed on roof")
                    
                if vlm_parsed.get("analysis_run", False):
                    score += 30
                    feedback_parts.append("VLM: Energy analysis graph observed")
                else:
                    feedback_parts.append("VLM: Energy analysis not observed")
            else:
                feedback_parts.append("VLM query failed")
        else:
            feedback_parts.append("No screenshots available for VLM")
    else:
        feedback_parts.append("VLM not configured")

    # Final pass conditions
    # Requires saving project, saving report, adding skylights, running analysis, and logic
    passed = (score >= 75)
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }