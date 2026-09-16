#!/usr/bin/env python3
"""
Verifier for equatorial_microgrid_solar_redesign task.

Uses multi-criteria verification, including programmatic physics analysis.
"""

import json
import tempfile
import os
import logging
import csv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_equatorial_microgrid_solar_redesign(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # Get JSON result
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
            
    csv_exists = result.get("csv_exists", False)
    ng3_exists = result.get("ng3_exists", False)
    csv_created_during_task = result.get("csv_created_during_task", False)
    
    if ng3_exists:
        score += 20
        feedback_parts.append("Modified project file saved (+20)")
    else:
        feedback_parts.append("Modified project file NOT found")
        
    if csv_exists:
        score += 20
        feedback_parts.append("Yield CSV exported (+20)")
        if csv_created_during_task:
            score += 10
            feedback_parts.append("CSV created during task (+10)")
        else:
            feedback_parts.append("CSV not created during task")
    else:
        feedback_parts.append("Yield CSV NOT found")
        
    # Analyze the CSV if it exists (proves geographic location & tilt parameters)
    csv_variance_ok = False
    if csv_exists:
        temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/nairobi_yield.csv", temp_csv.name)
            yields = []
            with open(temp_csv.name, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 2:
                        try:
                            # Safely extract values from typical Energy3D export column structure
                            val = float(row[-1].strip())
                            yields.append(val)
                        except ValueError:
                            pass
            
            yields.sort()
            
            # Remove sum/total row if present (usually ~12x average, safely checked at 0.95x remaining sum)
            if len(yields) >= 13:
                if yields[-1] >= sum(yields[:-1]) * 0.95:
                    yields.pop()
                    
            if len(yields) >= 12:
                # Take top 12 (covers 12 months)
                top_12 = yields[-12:]
                y_max = max(top_12)
                y_min = min(top_12)
                y_avg = sum(top_12) / len(top_12)
                
                if y_avg > 0:
                    variance = (y_max - y_min) / y_avg
                    logger.info(f"Calculated variance: {variance:.3f} (max={y_max}, min={y_min}, avg={y_avg})")
                    
                    if variance < 0.25:
                        score += 30
                        csv_variance_ok = True
                        feedback_parts.append(f"CSV data profile is flat (variance={variance:.2f} < 0.25), confirming equatorial physics and 5 deg tilt (+30)")
                    else:
                        feedback_parts.append(f"CSV data profile variance is too high (variance={variance:.2f}). Required < 0.25. Location or tilt is likely incorrect.")
                else:
                    feedback_parts.append("Average yield is zero in CSV")
            else:
                feedback_parts.append(f"Could not find 12 valid yield values in CSV (found {len(yields)})")
                
        except Exception as e:
            logger.error(f"Error parsing CSV: {e}")
            feedback_parts.append("Error parsing CSV")
        finally:
            if os.path.exists(temp_csv.name):
                os.unlink(temp_csv.name)
                
    # VLM Trajectory Verification
    vlm_score = 0
    query_vlm = env_info.get('query_vlm')
    if query_vlm:
        try:
            import random
            
            screenshots = []
            for step in traj.get('steps', []):
                if 'screenshot' in step:
                    screenshots.append(step['screenshot'])
                elif 'observation' in step and 'image' in step['observation']:
                    screenshots.append(step['observation']['image'])
                    
            images = []
            if screenshots:
                if len(screenshots) > 4:
                    images = random.sample(screenshots[:-1], min(3, len(screenshots)-1))
                images.append(screenshots[-1])
            
            if images:
                prompt = (
                    "You are evaluating an agent using Energy3D. "
                    "The task was to change geographic location to Nairobi (equator), "
                    "change solar panel tilt to 5 degrees, and run an annual yield analysis. "
                    "Look at these trajectory screenshots. "
                    "Respond in JSON format: "
                    "{\"interacted_with_energy3d\": true/false, \"evidence_of_analysis\": true/false}"
                )
                
                vlm_result = query_vlm(images=images, prompt=prompt)
                if vlm_result.get("success"):
                    parsed = vlm_result.get("parsed", {})
                    if parsed.get("interacted_with_energy3d", False):
                        vlm_score += 10
                    if parsed.get("evidence_of_analysis", False):
                        vlm_score += 10
                        
            score += vlm_score
            feedback_parts.append(f"VLM score: {vlm_score}/20")
        except Exception as e:
            logger.error(f"VLM verification error: {e}")
            feedback_parts.append(f"VLM verification error: {str(e)}")
            
    # Key Success Criteria
    passed = (score >= 60) and csv_variance_ok
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }