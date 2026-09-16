#!/usr/bin/env python3
"""
Verifier for the utility_interconnection_peak_vs_energy task.
Reads the parsed JSON result and evaluates accuracy of the reported text file,
while using VLM trajectory analysis to verify the software was genuinely used.
"""

import os
import json
import re
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# VLM prompt to check the trajectory for the actual UI workflow
VLM_PROMPT = """You are verifying an agent's completion of a solar analysis workflow in Energy3D.

The agent was instructed to:
1. Change the site location to Phoenix, AZ and the date to June 21.
2. Run a "Daily Yield Analysis" (resulting in a graph popup) for the original Fixed-Tilt array.
3. Change the Tracker property of the solar racks to "Dual Axis".
4. Run the "Daily Yield Analysis" again.

Examine the provided sequence of screenshots from the agent's session.
Did the agent perform these physical steps in the software?

Look for:
- The Location/Date settings being adjusted (City: Phoenix, AZ; Date: 6/21).
- The "Daily Yield" graph window appearing at least once.
- The solar panels changing physical orientation or the Properties panel showing "Dual Axis".

Provide your assessment in the following JSON format:
{
    "location_date_set": true/false,
    "yield_analysis_run": true/false,
    "tracker_changed": true/false,
    "confidence": "high/medium/low",
    "reasoning": "brief explanation of evidence found in screenshots"
}
"""

def verify_interconnection_study(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Verifier error: copy_from_env missing."}

    # Extract ground truth and tolerances
    metadata = task_info.get('metadata', {})
    tol_pct = metadata.get('tolerance_pct', 20.0) / 100.0
    gt = metadata.get('ground_truth', {
        "fixed_peak_kw": 16.5,
        "fixed_total_kwh": 135.0,
        "dual_peak_kw": 16.5,
        "dual_total_kwh": 195.0
    })

    score = 0
    feedback = []
    
    # 1. Retrieve the exported JSON result
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to retrieve result: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    # 2. Check File Existence & Anti-Gaming
    output_exists = result.get('output_exists', False)
    file_created_during_task = result.get('file_created_during_task', False)
    content = result.get('content', '')

    if not output_exists:
        return {"passed": False, "score": 0, "feedback": "Failure: interconnection_report.txt was not found."}
    
    if not file_created_during_task:
        feedback.append("Penalty: File appears to have been created before task start.")
    else:
        score += 10
        feedback.append("Report file created successfully.")

    # 3. Parse Document Content
    # Use regex to extract the values flexibly
    patterns = {
        "fixed_peak": r"Fixed Peak Power:\s*([\d.]+)\s*kW",
        "fixed_energy": r"Fixed Total Energy:\s*([\d.]+)\s*kWh",
        "dual_peak": r"Dual-Axis Peak Power:\s*([\d.]+)\s*kW",
        "dual_energy": r"Dual-Axis Total Energy:\s*([\d.]+)\s*kWh"
    }
    
    extracted = {}
    missing_keys = []
    for key, pattern in patterns.items():
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            try:
                extracted[key] = float(match.group(1))
            except ValueError:
                missing_keys.append(key)
        else:
            missing_keys.append(key)

    if missing_keys:
        feedback.append(f"Missing or malformed values for: {', '.join(missing_keys)}")
    else:
        # All keys parsed!
        # Check Logical Consistency (Dual Energy > Fixed Energy)
        if extracted["dual_energy"] > extracted["fixed_energy"] * 1.1:
            score += 10
            feedback.append("Logical constraint met: Dual-Axis Energy > Fixed Energy.")
        else:
            feedback.append("Logical failure: Dual-Axis energy should be significantly higher than Fixed-Tilt energy in summer.")

        # Check Accuracy against Ground Truth (with tolerance)
        metrics_checks = [
            ("fixed_peak", extracted["fixed_peak"], gt["fixed_peak_kw"], 10),
            ("fixed_energy", extracted["fixed_energy"], gt["fixed_total_kwh"], 10),
            ("dual_peak", extracted["dual_peak"], gt["dual_peak_kw"], 15),
            ("dual_energy", extracted["dual_energy"], gt["dual_total_kwh"], 15)
        ]

        for name, val, target, pts in metrics_checks:
            lower_bound = target * (1.0 - tol_pct)
            upper_bound = target * (1.0 + tol_pct)
            if lower_bound <= val <= upper_bound:
                score += pts
                feedback.append(f"Metric '{name}' within expected range ({val}).")
            else:
                feedback.append(f"Metric '{name}' outside tolerance (Got {val}, Target ~{target}).")

    # 4. VLM Trajectory Verification
    vlm_score = 0
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
            frames = sample_trajectory_frames(traj, n=5)
            final = get_final_screenshot(traj)
            
            # Remove None frames safely
            images = [f for f in frames + [final] if f is not None]
            
            if images:
                vlm_resp = query_vlm(prompt=VLM_PROMPT, images=images)
                
                if vlm_resp and vlm_resp.get("success"):
                    parsed = vlm_resp.get("parsed", {})
                    loc_set = parsed.get("location_date_set", False)
                    analysis_run = parsed.get("yield_analysis_run", False)
                    tracker_chg = parsed.get("tracker_changed", False)
                    
                    if loc_set:
                        vlm_score += 10
                    if analysis_run:
                        vlm_score += 10
                    if tracker_chg:
                        vlm_score += 10
                        
                    feedback.append(f"VLM verified trajectory: Location={loc_set}, Analysis={analysis_run}, Tracker={tracker_chg}.")
                else:
                    feedback.append("VLM verification failed to parse or return successfully.")
            else:
                feedback.append("No valid screenshots available for VLM verification.")
        except Exception as e:
            feedback.append(f"Error during VLM evaluation: {e}")
    else:
        feedback.append("VLM query function unavailable; skipping trajectory visual verification.")

    score += vlm_score

    # Evaluate Pass/Fail
    passed = (score >= 70) and ("Missing or malformed" not in "".join(feedback)) and output_exists

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback),
        "details": {
            "extracted_values": extracted,
            "vlm_score": vlm_score
        }
    }