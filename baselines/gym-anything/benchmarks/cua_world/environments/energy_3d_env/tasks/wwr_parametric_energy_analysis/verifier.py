#!/usr/bin/env python3
"""
Verifier for wwr_parametric_energy_analysis.

Evaluates:
1. Save file creation (`chicago_wwr_60.ng3`)
2. Location change applied (string search for 'Chicago' in binary .ng3)
3. CSV file creation and formatting
4. Physics extraction validity (trend E60 > E40 > E20)
5. Trajectory Verification (ensures analysis chart was actually opened)
"""

import os
import json
import csv
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_wwr_analysis(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    score = 0
    feedback_parts = []
    
    # 1. Read task metadata json
    temp_result = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_result.name)
        with open(temp_result.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read exported results: {e}"}
    finally:
        if os.path.exists(temp_result.name):
            os.unlink(temp_result.name)

    task_start = result.get("task_start", 0)

    # 2. Check NG3 Save File (20 points total)
    ng3_exists = result.get("ng3_exists", False)
    ng3_mtime = result.get("ng3_mtime", 0)
    ng3_size = result.get("ng3_size", 0)

    if ng3_exists and ng3_mtime >= task_start and ng3_size > 1000:
        score += 10
        feedback_parts.append("✅ Project saved correctly")
        
        # Check if 'Chicago' is in the saved binary file
        temp_ng3 = tempfile.NamedTemporaryFile(delete=False)
        try:
            copy_from_env("/tmp/chicago_wwr_60.ng3", temp_ng3.name)
            with open(temp_ng3.name, 'rb') as f:
                content = f.read()
                if b'Chicago' in content or b'chicago' in content:
                    score += 10
                    feedback_parts.append("✅ Location updated to Chicago")
                else:
                    feedback_parts.append("❌ Location 'Chicago' not found in project file")
        except Exception:
            feedback_parts.append("⚠️ Failed to parse .ng3 file")
        finally:
            if os.path.exists(temp_ng3.name):
                os.unlink(temp_ng3.name)
    else:
        feedback_parts.append("❌ Saved project 'chicago_wwr_60.ng3' missing or invalid")

    # 3. Check CSV Data (50 points total)
    csv_exists = result.get("csv_exists", False)
    csv_mtime = result.get("csv_mtime", 0)
    
    data_map = {}
    csv_header_valid = False
    
    if csv_exists and csv_mtime >= task_start:
        temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        try:
            copy_from_env("/tmp/wwr_results.csv", temp_csv.name)
            with open(temp_csv.name, 'r') as f:
                reader = csv.reader(f)
                rows = list(reader)
                
                if len(rows) > 0:
                    header = rows[0]
                    if len(header) >= 2 and 'wwr' in header[0].lower() and 'total' in header[1].lower():
                        csv_header_valid = True
                        score += 10
                        feedback_parts.append("✅ CSV header formatted correctly")
                    else:
                        feedback_parts.append("❌ CSV header missing expected format 'WWR,Total_Energy_kWh'")
                
                # Parse rows into map
                for row in rows[1:]:
                    if len(row) >= 2:
                        try:
                            # Handle potential % signs and commas
                            w_str = row[0].replace('%', '').strip()
                            e_str = row[1].replace(',', '').strip()
                            w = float(w_str)
                            e = float(e_str)
                            # Normalize fractional WWR representation (0.2 vs 20)
                            if 0 < w < 1: w = w * 100
                            data_map[w] = e
                        except ValueError:
                            pass
        except Exception as e:
            feedback_parts.append(f"⚠️ Error reading CSV: {e}")
        finally:
            if os.path.exists(temp_csv.name):
                os.unlink(temp_csv.name)
                
        # Evaluate CSV Completeness
        has_20 = 20.0 in data_map
        has_40 = 40.0 in data_map
        has_60 = 60.0 in data_map
        
        if has_20 and has_40 and has_60:
            score += 15
            feedback_parts.append("✅ CSV contains all required WWR values (20, 40, 60)")
            
            # Evaluate Physics/Trend Validity (Chicago cold climate -> windows increase net load)
            e20 = data_map[20.0]
            e40 = data_map[40.0]
            e60 = data_map[60.0]
            
            if e20 > 2000 and e40 > 2000 and e60 > 2000:
                if e60 > e40 and e40 > e20:
                    score += 25
                    feedback_parts.append("✅ Energy data follows expected physical trend (Total load increases with larger WWR in Chicago)")
                else:
                    feedback_parts.append("❌ Energy data does not follow the correct physical trend for this climate")
            else:
                feedback_parts.append("❌ Energy values are too low to be realistic (must be >2000 kWh)")
        else:
            feedback_parts.append("❌ CSV missing one or more required WWR rows")
    else:
        feedback_parts.append("❌ Results CSV file missing or not generated during task")

    # 4. VLM Trajectory Verification (30 points)
    query_vlm = env_info.get('query_vlm')
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames
            # Sample multiple frames across the trajectory to find the analysis chart
            frames = sample_trajectory_frames(traj, n=8)
            
            prompt = """You are evaluating an agent using the Energy3D application.
The agent was asked to run an "Annual Energy Analysis".
Look carefully at these screenshots from the session. 
Do ANY of these images show the "Annual Energy Analysis" window open? This window typically displays a bar chart with monthly energy values.

Respond with JSON format exactly like this:
{
    "chart_visible": true/false,
    "confidence": "high/medium/low"
}"""
            vlm_result = query_vlm(images=frames, prompt=prompt)
            
            if vlm_result.get("success"):
                parsed = vlm_result.get("parsed", {})
                if parsed.get("chart_visible", False):
                    score += 30
                    feedback_parts.append("✅ VLM verified Annual Energy Analysis chart was viewed")
                else:
                    feedback_parts.append("❌ VLM did not detect the Annual Energy Analysis chart in the workflow")
            else:
                feedback_parts.append("⚠️ VLM query failed, skipping trajectory points")
        except Exception as e:
            logger.error(f"VLM verification error: {e}")
            feedback_parts.append("⚠️ VLM verification encountered an error")

    # Determine Pass/Fail (Threshold: 70)
    passed = score >= 70

    return {
        "passed": passed,
        "score": score,
        "feedback": "\n".join(feedback_parts)
    }