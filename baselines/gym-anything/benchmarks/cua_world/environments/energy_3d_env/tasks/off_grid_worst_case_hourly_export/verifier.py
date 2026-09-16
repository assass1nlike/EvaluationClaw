#!/usr/bin/env python3
import json
import os
import tempfile
import logging
import csv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_off_grid_hourly_export(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    feedback_parts = []
    score = 0

    # 1. READ EXPORTED RESULT JSON
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Failed to read result: {e}"}
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    ng3_exists = result.get('ng3_exists', False)
    csv_exists = result.get('csv_exists', False)

    # 2. EVALUATE PROJECT FILE (Model saved, Anti-gaming timestamp, Content checks)
    if ng3_exists and result.get('ng3_created_during_task', False):
        score += 10
        feedback_parts.append("Model saved correctly")
    elif ng3_exists:
        score += 5
        feedback_parts.append("Model exists but might not be newly created")
    else:
        feedback_parts.append("boston_winter.ng3 not found")

    if ng3_exists:
        temp_ng3 = tempfile.NamedTemporaryFile(delete=False, suffix='.ng3')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/boston_winter.ng3", temp_ng3.name)
            with open(temp_ng3.name, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            if 'Boston' in content:
                score += 15
                feedback_parts.append("Location set to Boston")
            else:
                feedback_parts.append("Location 'Boston' not found in model")

            if '21' in content and ('11' in content or '12' in content or 'Dec' in content):
                score += 15
                feedback_parts.append("Date set to Dec 21")
            else:
                feedback_parts.append("Date Dec 21 not found in model")
        except Exception as e:
            logger.error(f"Error reading NG3: {e}")
        finally:
            if os.path.exists(temp_ng3.name):
                os.unlink(temp_ng3.name)

    # 3. EVALUATE EXPORTED CSV (File checks, Formats, Physical Physics Evaluation)
    csv_valid = False
    if csv_exists and result.get('csv_created_during_task', False):
        score += 15
        feedback_parts.append("CSV exported correctly")

        temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        try:
            copy_from_env("/home/ga/Documents/Energy3D/boston_dec21_hourly.csv", temp_csv.name)
            with open(temp_csv.name, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                rows = list(reader)

            if len(rows) >= 20:  # We expect hourly output rows
                csv_valid = True
                score += 15
                feedback_parts.append("CSV format valid")

                # Parse the solar yields ensuring real output (not just dummy numbers)
                yields = []
                for row in rows[1:]:
                    if len(row) > 1:
                        val_str = ''.join(c for c in row[1] if c.isdigit() or c == '.')
                        if val_str:
                            try:
                                yields.append(float(val_str))
                            except ValueError:
                                pass

                # Ensure it matches a real solar pattern (0 at night, peak midday)
                if len(yields) >= 20:
                    night_sum = sum(yields[:4]) + sum(yields[-4:])
                    mid_sum = sum(yields[10:14])
                    if night_sum < mid_sum * 0.2 and mid_sum > 0.0:
                        score += 10
                        feedback_parts.append("CSV exhibits correct diurnal yield pattern")
                    else:
                        feedback_parts.append("CSV yield pattern lacks expected night/day physical variance")
        except Exception as e:
            logger.error(f"Error reading CSV: {e}")
        finally:
            if os.path.exists(temp_csv.name):
                os.unlink(temp_csv.name)
    elif csv_exists:
        feedback_parts.append("CSV exists but was not created during task")
    else:
        feedback_parts.append("boston_dec21_hourly.csv not found")

    # 4. VLM TRAJECTORY VERIFICATION (Proves UI usage over Python scripting)
    try:
        from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
        frames = sample_trajectory_frames(traj, n=4)
        final = get_final_screenshot(traj)
        images = frames + [final] if final else frames
    except Exception:
        images = []

    query_vlm = env_info.get('query_vlm')
    if query_vlm and images:
        prompt = """You are evaluating an agent that is operating Energy3D.
The task is to run a Daily Solar Radiation analysis, view the yield graph, and export it as a CSV.
Look at these trajectory frames (they are sequential).
Did the agent:
1. Open the 'Daily Solar Radiation' or 'Daily Yield' graph window?
2. Access the export/save dialog to save the data as a CSV file?

Respond with JSON format:
{
    "opened_graph": true/false,
    "exported_csv": true/false
}
"""
        try:
            res = query_vlm(prompt=prompt, images=images)
            if res and res.get('success'):
                parsed = res.get('parsed', {})
                if parsed.get('opened_graph'):
                    score += 10
                    feedback_parts.append("VLM confirmed graph opened")
                if parsed.get('exported_csv'):
                    score += 10
                    feedback_parts.append("VLM confirmed CSV exported via UI")
        except Exception as e:
            logger.error(f"VLM error: {e}")

    # 5. FINAL SCORING
    key_criteria_met = csv_exists and csv_valid
    passed = score >= 70 and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }