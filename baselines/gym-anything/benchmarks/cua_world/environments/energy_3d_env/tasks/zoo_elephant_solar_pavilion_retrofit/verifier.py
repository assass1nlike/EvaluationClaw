#!/usr/bin/env python3
"""
Verifier for Zoo Elephant Solar Pavilion Retrofit task.

Verification Strategy:
1. Programmatically parses the XStream-serialized `.ng3` XML file to check:
    - Location (<city> tag)
    - Base Height (<baseHeight> or <height> tag)
    - Tilt Angle (<tiltAngle> tag)
    - Panel Model (<modelName> tag)
2. Reads the exported CSV file to verify annual simulation data existence & validity.
3. Uses file creation timestamps to detect "do nothing" spoofing.
"""

import json
import tempfile
import os
import re
import csv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_retrofit(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}
    
    score = 0
    feedback_parts = []
    
    # Track the number of geometric/property modifications successfully completed
    modifications_completed = 0
    
    # ---------------------------------------------------------
    # Step 1: Read the task result metadata
    # ---------------------------------------------------------
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result_meta = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result metadata: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)
            
    task_start = result_meta.get("task_start", 0)
    ng3_exists = result_meta.get("ng3_exists", False)
    csv_exists = result_meta.get("csv_exists", False)
    csv_mtime = result_meta.get("csv_mtime", 0)

    # ---------------------------------------------------------
    # Step 2: Validate the NG3 file (XML constraints)
    # ---------------------------------------------------------
    if ng3_exists:
        score += 15
        feedback_parts.append("Project saved correctly")
        
        # Read the ng3 XML contents
        temp_ng3 = tempfile.NamedTemporaryFile(delete=False, suffix='.ng3')
        try:
            copy_from_env("/tmp/phoenix_elephant_pavilion.ng3", temp_ng3.name)
            with open(temp_ng3.name, 'r', encoding='utf-8', errors='ignore') as f:
                ng3_content = f.read()
            
            # Check City/Location (15 pts)
            if re.search(r'<city>\s*Phoenix\s*</city>', ng3_content, re.IGNORECASE):
                score += 15
                modifications_completed += 1
                feedback_parts.append("Location updated to Phoenix")
            else:
                feedback_parts.append("Location not updated to Phoenix")
                
            # Check Base Height (20 pts)
            # Energy3D racks usually use baseHeight, foundations use height
            if re.search(r'<(?:baseHeight|height)>\s*6(?:\.0+)?\s*</(?:baseHeight|height)>', ng3_content):
                score += 20
                modifications_completed += 1
                feedback_parts.append("Canopy clearance set to 6.0m")
            else:
                feedback_parts.append("Canopy clearance incorrect (expected 6.0m)")
                
            # Check Tilt Angle (20 pts)
            if re.search(r'<tiltAngle>\s*10(?:\.0+)?\s*</tiltAngle>', ng3_content):
                score += 20
                modifications_completed += 1
                feedback_parts.append("Tilt angle set to 10 degrees")
            else:
                feedback_parts.append("Tilt angle incorrect (expected 10 degrees)")
                
            # Check Panel Model (15 pts)
            if re.search(r'<modelName>\s*SunPower SPR-X21-345\s*</modelName>', ng3_content, re.IGNORECASE):
                score += 15
                modifications_completed += 1
                feedback_parts.append("Panel model upgraded to SunPower SPR-X21-345")
            else:
                feedback_parts.append("Panel model incorrect")
                
        except Exception as e:
            feedback_parts.append(f"Error parsing .ng3 project file: {e}")
        finally:
            if os.path.exists(temp_ng3.name):
                os.unlink(temp_ng3.name)
    else:
        feedback_parts.append("Modified project (.ng3) NOT saved to correct path")

    # ---------------------------------------------------------
    # Step 3: Validate the CSV Export (Yield Simulation)
    # ---------------------------------------------------------
    csv_valid = False
    if csv_exists:
        if csv_mtime > task_start:
            temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
            try:
                copy_from_env("/tmp/elephant_pavilion_yield.csv", temp_csv.name)
                with open(temp_csv.name, 'r') as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                    
                    # Look for data row structure (usually 1 header row + 12 month rows)
                    if len(rows) >= 12:
                        csv_valid = True
                        score += 15
                        feedback_parts.append("Yield CSV exported successfully")
                    else:
                        feedback_parts.append("Yield CSV has insufficient data rows")
            except Exception as e:
                feedback_parts.append(f"Error reading exported CSV: {e}")
            finally:
                if os.path.exists(temp_csv.name):
                    os.unlink(temp_csv.name)
        else:
            feedback_parts.append("CSV file is stale (timestamp pre-dates task start)")
    else:
        feedback_parts.append("Yield CSV export NOT found")

    # ---------------------------------------------------------
    # Evaluate Pass/Fail Condition
    # ---------------------------------------------------------
    # Requires total points >= 70 AND valid CSV export AND at least 2 geometric/parameter modifications
    passed = (score >= 70) and csv_valid and (modifications_completed >= 2)
    
    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }