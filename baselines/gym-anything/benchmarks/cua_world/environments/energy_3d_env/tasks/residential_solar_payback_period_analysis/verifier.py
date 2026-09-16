#!/usr/bin/env python3
"""
Verifier for residential_solar_payback_period_analysis.

Strategy:
1. Verify required files were created during the task.
2. Read the exported text report and use Regex to extract the Agent's reported Yield, Cost, Savings, and Payback.
3. Perform a mathematical consistency check (Savings = Yield * 0.30, Payback = Cost / Savings) to ensure no hallucination.
4. Query VLM on trajectory screenshots to ensure the agent physically built the house, placed panels, and ran the analysis in Energy3D.
"""

import json
import tempfile
import os
import re
import logging
import math

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import VLM utilities
try:
    from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
    VLM_AVAILABLE = True
except ImportError:
    logger.warning("VLM utilities not available. VLM checks will be skipped.")
    VLM_AVAILABLE = False


def extract_value(text, keywords):
    """Attempt to extract a numeric value from lines containing specific keywords."""
    lines = text.split('\n')
    for line in lines:
        if any(kw.lower() in line.lower() for kw in keywords):
            # Extract numbers that might contain commas or decimals
            matches = re.findall(r'-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?', line)
            if matches:
                try:
                    return float(matches[0].replace(',', ''))
                except ValueError:
                    continue
    return None


def verify_payback_analysis(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # 1. Read JSON metadata
    temp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_json.name)
        with open(temp_json.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result metadata: {e}"}
    finally:
        if os.path.exists(temp_json.name):
            os.unlink(temp_json.name)

    task_start = result.get("task_start_time", 0)
    report_exists = result.get("report_exists", False)
    report_mtime = result.get("report_mtime", 0)
    ng3_exists = result.get("ng3_exists", False)

    # 2. Check File Exists & Created During Task (Anti-Gaming)
    if ng3_exists:
        score += 10
        feedback_parts.append("Project .ng3 file saved.")
    else:
        feedback_parts.append("Project .ng3 file missing.")

    report_valid = False
    if report_exists and report_mtime > task_start:
        score += 15
        feedback_parts.append("Report file created.")
        report_valid = True
    elif report_exists:
        feedback_parts.append("Report file exists but is stale (was not created during this session).")
    else:
        feedback_parts.append("Report file missing.")

    # 3. Read and verify the mathematical content of the report
    math_valid = False
    if report_valid:
        temp_report = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        try:
            copy_from_env("/tmp/payback_report_result.txt", temp_report.name)
            with open(temp_report.name, 'r', encoding='utf-8') as f:
                report_content = f.read()
            
            yield_val = extract_value(report_content, ['yield', 'generation', 'produced', 'kwh'])
            cost_val = extract_value(report_content, ['cost', 'price', '$'])
            savings_val = extract_value(report_content, ['saving', 'financial'])
            payback_val = extract_value(report_content, ['payback', 'years', 'period'])
            
            # Check extraction success
            if all(v is not None for v in [yield_val, cost_val, savings_val, payback_val]):
                score += 15
                feedback_parts.append("All metrics successfully extracted from report.")
                
                # Verify Math Logic (Tolerance handles rounding differences by the agent)
                electricity_rate = task_info.get("metadata", {}).get("electricity_rate_usd", 0.30)
                
                expected_savings = yield_val * electricity_rate
                expected_payback = cost_val / savings_val if savings_val > 0 else 0
                
                savings_ok = math.isclose(savings_val, expected_savings, rel_tol=0.05) or abs(savings_val - expected_savings) <= 2.0
                payback_ok = math.isclose(payback_val, expected_payback, rel_tol=0.05) or abs(payback_val - expected_payback) <= 0.5
                
                if savings_ok and payback_ok:
                    score += 20
                    math_valid = True
                    feedback_parts.append("Mathematical calculations are correct.")
                else:
                    feedback_parts.append(f"Math errors detected. Expected Savings: ~${expected_savings:.2f}, got ${savings_val}. Expected Payback: ~{expected_payback:.2f} yrs, got {payback_val} yrs.")
            else:
                feedback_parts.append("Could not extract all required numeric metrics (Cost, Yield, Savings, Payback) from the report.")
        except Exception as e:
            feedback_parts.append(f"Error reading report content: {e}")
        finally:
            if os.path.exists(temp_report.name):
                os.unlink(temp_report.name)

    # 4. VLM Verification (Trajectory checking)
    vlm_passed = False
    if VLM_AVAILABLE and query_vlm:
        frames = sample_trajectory_frames(traj, n=4)
        final = get_final_screenshot(traj)
        
        prompt = """You are evaluating an agent's trajectory in the 3D physics software Energy3D.
Look closely at these sequential screenshots of the agent's workflow.
1. Did the agent model a house (foundation, walls, roof) in the 3D view?
2. Did the agent place solar panels on the roof of the house?
3. Did the agent open or view an Analysis graph window (like 'Annual Yield Analysis' or 'Project Cost') during the process?

Respond in JSON format:
{
    "house_modeled": true/false,
    "panels_placed": true/false,
    "analysis_run": true/false,
    "reasoning": "brief explanation"
}
"""
        try:
            vlm_response = query_vlm(prompt=prompt, images=frames + [final])
            if vlm_response and vlm_response.get("success"):
                parsed = vlm_response.get("parsed", {})
                house_modeled = parsed.get("house_modeled", False)
                panels_placed = parsed.get("panels_placed", False)
                analysis_run = parsed.get("analysis_run", False)
                
                if house_modeled and panels_placed:
                    score += 20
                    feedback_parts.append("VLM verified 3D house and panel modeling.")
                    
                if analysis_run:
                    score += 20
                    feedback_parts.append("VLM verified Analysis chart execution.")
                    
                if house_modeled and panels_placed and analysis_run:
                    vlm_passed = True
            else:
                feedback_parts.append("VLM evaluation failed to return a valid response.")
        except Exception as e:
            feedback_parts.append(f"VLM error: {str(e)}")

    # Check total criteria
    passed = (score >= 80) and report_valid and math_valid and vlm_passed

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }