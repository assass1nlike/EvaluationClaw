# Verification Patterns for gym_anything

## Overview

This document covers best practices for writing verifiers in the gym_anything framework. Verifiers determine whether a task was completed successfully.

Also SEE: `vlm_checklist_patterns.md` and `verifiers/VLM_EVALUATOR_DESIGN_GUIDE.md` for more details.

## Key Principle: Use `copy_from_env`, NOT `exec_in_env`

**CRITICAL**: The framework provides `copy_from_env` to read files from the container, NOT `exec_in_env` to run commands.

```python
# WRONG - exec_in_env may not be available
def verify_task(traj, env_info, task_info):
    exec_in_env = env_info.get('exec_in_env')
    if not exec_in_env:
        return {"passed": False, "score": 0, "feedback": "Exec function not available"}
    # This will fail!

# CORRECT - use copy_from_env
def verify_task(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}
    # This works!
```

## Two-Part Verification Pattern

### Part 1: Export Script (runs in container)

The `export_result.sh` hook runs **inside the container** AFTER the task completes. It should:
1. Query databases, check files, gather all verification data
2. Save results to a JSON file in `/tmp/`

```bash
#!/bin/bash
# export_result.sh - runs in container

# Query database
RESULT=$(mysql -u user -ppass db -N -e "SELECT * FROM table WHERE ...")

# Save to JSON
cat > /tmp/task_result.json << EOF
{
    "found": true,
    "data": "$RESULT",
    "timestamp": "$(date -Iseconds)"
}
EOF
```

### Part 2: Verifier Script (runs on host)

The `verifier.py` runs **on the host machine**. It should:
1. Use `copy_from_env` to copy the JSON file from container to host
2. Parse the JSON and evaluate the results
3. Return the verification result

```python
#!/usr/bin/env python3
# verifier.py - runs on host

import json
import tempfile
import os

def verify_task(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    # Copy result from container
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    finally:
        os.unlink(temp_file.name)

    # Evaluate and return
    if result.get('found'):
        return {"passed": True, "score": 100, "feedback": "Task completed"}
    else:
        return {"passed": False, "score": 0, "feedback": "Expected data not found"}
```

## Avoid Hardcoded Values

### Problem: Hardcoded Expected Values

```python
# BAD - hardcoded values
def verify_task(traj, env_info, task_info):
    expected_count = 3  # Hardcoded!
    expected_name = "John"  # Hardcoded!
```

### Solution: Use task_info Metadata

```python
# GOOD - values from task metadata
def verify_task(traj, env_info, task_info):
    metadata = task_info.get('metadata', {})
    expected_name = metadata.get('expected_name', 'John')  # Default fallback
    expected_count = metadata.get('expected_count', 0)
```

And in `task.json`:
```json
{
  "id": "my_task@1",
  "metadata": {
    "expected_name": "John",
    "expected_count": 5
  },
  "success": {
    "mode": "program",
    "spec": {
      "program": "verifier.py::verify_task"
    }
  }
}
```

## Verifier Output Format

Always return this structure:

```python
return {
    "passed": bool,           # True if task was completed successfully
    "score": int,             # 0-100, percentage of criteria met
    "feedback": str,          # Human-readable feedback
    "subscores": dict         # Optional: detailed breakdown
}
```

## Multi-Criteria Verification

For complex tasks, check multiple criteria:

```python
def verify_task(traj, env_info, task_info):
    criteria_met = 0
    total_criteria = 4
    feedback_parts = []

    # Criterion 1: Data exists
    if result.get('data_exists'):
        criteria_met += 1
        feedback_parts.append("Data found")
    else:
        feedback_parts.append("Data NOT found")

    # Criterion 2: Value correct
    if result.get('value') == expected_value:
        criteria_met += 1
        feedback_parts.append(f"Value correct: {expected_value}")
    else:
        feedback_parts.append(f"Value wrong: expected {expected_value}, got {result.get('value')}")

    # ... more criteria ...

    # Calculate score
    score = int((criteria_met / total_criteria) * 100)
    passed = score >= 75  # Pass if 75%+ criteria met

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts)
    }
```

## Database Verification Pattern

For web applications with databases (OpenEMR, etc.):

### Export Script Pattern

```bash
#!/bin/bash
# Query database and save to JSON

# Get counts
INITIAL=$(cat /tmp/initial_count)
CURRENT=$(docker exec db mysql -N -e "SELECT COUNT(*) FROM table")

# Find specific record
RECORD=$(docker exec db mysql -N -e "SELECT * FROM table WHERE name='John'")

# Parse and save
if [ -n "$RECORD" ]; then
    FOUND="true"
    # Parse tab-separated fields
    FIELD1=$(echo "$RECORD" | cut -f1)
    FIELD2=$(echo "$RECORD" | cut -f2)
else
    FOUND="false"
fi

cat > /tmp/result.json << EOF
{
    "initial_count": $INITIAL,
    "current_count": $CURRENT,
    "record_found": $FOUND,
    "record": {
        "field1": "$FIELD1",
        "field2": "$FIELD2"
    }
}
EOF
```

### Verifier Pattern

```python
def verify_task(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    metadata = task_info.get('metadata', {})
    expected_name = metadata.get('expected_name', 'John')

    # Copy and parse result
    temp = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/result.json", temp.name)
        with open(temp.name, 'r') as f:
            result = json.load(f)
    finally:
        os.unlink(temp.name)

    # Verify
    if result.get('record_found'):
        record = result.get('record', {})
        if record.get('name') == expected_name:
            return {"passed": True, "score": 100, "feedback": f"Record '{expected_name}' found"}

    return {"passed": False, "score": 0, "feedback": f"Record '{expected_name}' not found"}
```

## Common Errors

### Error: "Exec function not available"

**Cause**: Verifier uses `exec_in_env` which isn't provided.

**Fix**: Use `copy_from_env` and export data to files first.

### Error: Database query finds nothing, but data is visible in UI

**Cause**: SQL query uses exact string matching, but data may have:
- Different case ("john" vs "John")
- Extra whitespace
- Different encoding

**Fix**: Use case-insensitive matching with fallbacks:

```bash
# Step 1: Try case-insensitive exact match
PATIENT_DATA=$(openemr_query "SELECT * FROM patient_data
    WHERE LOWER(TRIM(fname))='john' AND LOWER(TRIM(lname))='testpatient'")

# Step 2: If not found, try partial match with LIKE
if [ -z "$PATIENT_DATA" ]; then
    PATIENT_DATA=$(openemr_query "SELECT * FROM patient_data
        WHERE LOWER(fname) LIKE '%john%' AND LOWER(lname) LIKE '%testpatient%'")
fi

# Step 3: If still not found, find any new patient added
if [ -z "$PATIENT_DATA" ]; then
    PATIENT_DATA=$(openemr_query "SELECT * FROM patient_data
        WHERE pid > $INITIAL_COUNT ORDER BY pid DESC LIMIT 1")
fi
```

### Error: "Copy function not available"

**Cause**: `env_info` doesn't contain `copy_from_env`.

**Fix**: Check framework version and verify env_info structure.

### Error: "Result file not found"

**Cause**: `export_result.sh` didn't run or failed.

**Fix**: Check that `hooks.post_task` is configured in task.json.

### Error: "Permission denied" when writing result file

**Cause**: Export script runs as different user than previous run, can't overwrite file owned by another user.

**Fix**: Use temp file approach with sudo fallback:

```bash
# Create JSON in temp file first
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{"data": "value"}
EOF

# Remove old file and copy new one (with sudo fallback)
rm -f /tmp/result.json 2>/dev/null || sudo rm -f /tmp/result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/result.json
chmod 666 /tmp/result.json 2>/dev/null || sudo chmod 666 /tmp/result.json 2>/dev/null || true
rm -f "$TEMP_JSON"
```

### Error: JSON parsing fails

**Cause**: Export script generated invalid JSON (unescaped quotes, etc).

**Fix**: Use proper escaping in bash:
```bash
# Escape special characters
VALUE=$(echo "$RAW" | sed 's/"/\\"/g')
```

## File Structure

```
tasks/my_task/
├── task.json           # Task config with metadata
├── setup_task.sh       # pre_task hook (optional)
├── export_result.sh    # post_task hook (REQUIRED for verification)
└── verifier.py         # Verification logic
```

## Testing Verifiers

To confirm your verifier works:

1. Start the environment with the task
2. Complete the task interactively using `ask_cua.py` and xdotool
3. Run verification through the framework

```python
# Run verification
result = env.verify()
print(f"Passed: {result['passed']}, Score: {result['score']}")
print(f"Feedback: {result['feedback']}")
```

See `03_interactive_testing.md` for the interactive testing workflow.

## CRITICAL: Avoid Hackable Verification

### The Problem: Screenshot Size Heuristics

**NEVER** use screenshot file size as the sole indicator of task completion:

```python
# BAD - Extremely hackable!
if screenshot_size_kb > 100:
    data_loaded = True  # WRONG! Welcome screen is also >100KB
```

This passes even when the agent does nothing - the desktop/welcome screen produces large screenshots.

### Solution: Query Application State

For desktop applications, use the application's API or internal state:

```bash
# 3D Slicer example - query loaded volumes via Python API
if [ -x "/opt/Slicer/bin/PythonSlicer" ]; then
    QUERY_RESULT=$(/opt/Slicer/bin/PythonSlicer -c "
import json, slicer
nodes = slicer.mrmlScene.GetNodesByClass('vtkMRMLScalarVolumeNode')
nodes.InitTraversal()
count = 0
n = nodes.GetNextItemAsObject()
while n:
    count += 1
    n = nodes.GetNextItemAsObject()
print(json.dumps({'volume_count': count}))
" 2>/dev/null)
fi
```

### Hybrid Verification with VLM

For visual applications, combine programmatic checks with VLM verification:

```python
# GOOD - Hybrid verification
score = 0
programmatic_pass = False
vlm_pass = False

# Programmatic: Check API state (30 points)
if result.get('mrhead_loaded'):
    score += 30
    programmatic_pass = True

# VLM: Visual verification (40 points)
vlm_result = query_vlm(
    image=screenshot_path,
    prompt="Is brain scan data visible in the slice views?"
)
if vlm_result.get('brain_scan_visible'):
    score += 40
    vlm_pass = True

# Pass requires BOTH checks
passed = programmatic_pass and vlm_pass
```

See `extras/research/software_as_env/creation_audit/memory/env_creation_notes/verifiers/VLM_EVALUATOR_DESIGN_GUIDE_ARCHIVED.md` for comprehensive VLM verification patterns.

## Desktop Application Verification Checklist

For desktop applications like 3D Slicer, GIMP, Google Earth:

- [ ] **Maximize window** in task setup for better agent interaction
- [ ] **Dismiss startup dialogs** before agent starts
- [ ] **Query application API** in export script (not just screenshots)
- [ ] **Use VLM visual verification** for data visibility
- [ ] **Test that verification FAILS** when agent does nothing
- [ ] **Multiple independent signals** required (harder to game)

## CRITICAL: Always Use Real Data

**NEVER use synthetic/generated data for tasks.** Tasks must use real-world datasets:

### Why Real Data is Non-Negotiable

1. **Realism**: Synthetic data doesn't capture the complexity of real-world scenarios
2. **Validity**: Verification against synthetic ground truth is meaningless
3. **Agent Learning**: Agents need to interact with authentic data to be useful

### How to Download Real Data

Many public datasets can be downloaded directly without authentication:

```bash
# Kaggle datasets (many are publicly accessible)
curl -L -o dataset.zip \
  https://www.kaggle.com/api/v1/datasets/download/username/dataset-name

# Direct URLs from research repositories
wget -O data.tar.gz https://example.com/dataset.tar.gz

# Using aria2 for faster parallel downloads of large files
aria2c -x 4 -s 4 -k 1M -o output.zip "https://download.url/large_file.zip"
```

### Data Preparation Pattern

```bash
#!/bin/bash
# prepare_data.sh

DATA_DIR="/home/ga/Documents/TaskData"
GROUND_TRUTH_DIR="/var/lib/app/ground_truth"  # Hidden from agent

# Download if not exists
if [ ! -f "$DATA_DIR/data.zip" ]; then
    curl -L -o "$DATA_DIR/data.zip" "https://download.url/dataset.zip"
    unzip -q "$DATA_DIR/data.zip" -d "$DATA_DIR"
fi

# Move ground truth to hidden location
mv "$DATA_DIR/ground_truth.nii.gz" "$GROUND_TRUTH_DIR/"
chmod 700 "$GROUND_TRUTH_DIR"  # Prevent agent access
```

### Ground Truth Handling

- Store ground truth in a **hidden directory** (e.g., `/var/lib/slicer/ground_truth/`)
- Set **restrictive permissions** (`chmod 700`) so agents cannot peek
- Calculate and save **statistics** (e.g., expected volume, counts) for verification

## Window Title Parsing as Fallback

When macro queries fail (due to xdotool unreliability), parse window titles as a backup:

### Example: Detecting Virtual Stack in AstroImageJ

```bash
# Window title format: "WASP-12b (V) (18.4%)"
# (V) = virtual stack, percentage = memory usage

WINDOWS_LIST=$(DISPLAY=:1 wmctrl -l 2>/dev/null)
IMAGE_WINDOW=$(echo "$WINDOWS_LIST" | grep -iE "wasp|\.fits|stack" | head -1)

if [ -n "$IMAGE_WINDOW" ]; then
    echo "Detected image window: $IMAGE_WINDOW"

    # Check for virtual stack indicator
    if echo "$IMAGE_WINDOW" | grep -q "(V)"; then
        # Count actual FITS files as proxy for slices
        FITS_COUNT=$(ls -1 /path/to/data/*.fits 2>/dev/null | wc -l)
        NUM_SLICES=$FITS_COUNT
        NUM_IMAGES=1  # Single stack window
    fi
fi
```

### Window Indicators to Look For

| Application | Window Pattern | Meaning |
|-------------|----------------|---------|
| AstroImageJ | `filename (V)` | Virtual stack loaded |
| AstroImageJ | `Multi-plot` | Light curve window |
| AstroImageJ | `Multi-Aperture` | Photometry in progress |
| 3D Slicer | `MRHead` | Sample data loaded |
| GIMP | `.xcf` in title | Project file open |

## Scientific Application Verification Pattern

For astronomy, medical imaging, and other scientific applications:

### Multi-Signal Verification

Require MULTIPLE independent signals to prevent gaming:

```python
def verify_scientific_task(traj, env_info, task_info):
    score = 0
    feedback_parts = []

    # Signal 1: Data loaded (from window titles or API)
    data_loaded = result.get('num_slices', 0) >= 100
    if data_loaded:
        score += 15
        feedback_parts.append(f"Data loaded ({result['num_slices']} frames)")

    # Signal 2: Analysis performed (measurements exist)
    analysis_done = result.get('num_measurements', 0) >= 50
    if analysis_done:
        score += 20
        feedback_parts.append(f"Analysis complete ({result['num_measurements']} points)")

    # Signal 3: Parameters within tolerance
    expected = metadata.get('expected_value', 1.4)
    tolerance = metadata.get('tolerance', 0.3)
    measured = float(result.get('measured_value', 0))

    if abs(measured - expected) <= tolerance:
        score += 25
        feedback_parts.append(f"Value correct: {measured:.2f}")

    # Signal 4: VLM visual verification
    if query_vlm:
        vlm_result = query_vlm(image=screenshot, prompt="Is the expected visualization visible?")
        if 'yes' in vlm_result.lower():
            score += 15
            feedback_parts.append("VLM: Visualization confirmed")

    # KEY CRITERIA: Must have multiple signals, not just one
    key_criteria_met = data_loaded and analysis_done and (measured > 0)

    # Pass threshold with key criteria
    passed = score >= 60 and key_criteria_met

    return {"passed": passed, "score": score, "feedback": " | ".join(feedback_parts)}
```

### Anti-Gaming Checklist

- [ ] **"Do nothing" scores 0** - verify this explicitly
- [ ] **"Load data only" scores <30%** - not enough to pass
- [ ] **Wrong parameters fail** - even with all other criteria met
- [ ] **Multiple independent signals required** - can't game with one trick
- [ ] **Window title parsing** - fallback when API queries fail
- [ ] **Real data with known parameters** - can verify correctness

## Case Study: Blender 3D Environment Verification Evolution

This case study documents the iterative improvement of verification for a 3D rendering task.

### Initial (Flawed) Approach

```python
# BAD - First attempt at verification
def verify_render(traj, env_info, task_info):
    if result.get('output_exists'):
        if result.get('file_size_kb') > 50:
            if result.get('image_width') == 1920:
                return {"passed": True, "score": 100}
    return {"passed": False, "score": 0}
```

**Problems identified:**
1. Passes if file pre-existed (agent did nothing)
2. No check that file was actually created during task
3. No render time verification
4. No VLM visual verification
5. No "do nothing" detection

### Improved (Robust) Approach

```python
# GOOD - Multi-signal verification with 8 criteria
def verify_render_basic_scene(traj, env_info, task_info):
    score = 0
    feedback_parts = []

    # Criterion 1: Output file exists and is valid (15 pts)
    if output_exists and image_format in ['PNG', 'JPEG']:
        score += 15

    # Criterion 2: File was CREATED/MODIFIED during task (15 pts)
    if file_created:
        score += 15
    elif file_modified:
        score += 12
    # If neither, file pre-existed - NO points

    # Criterion 3: File size reasonable (10 pts)
    if file_size_kb >= 500:
        score += 10
    elif file_size_kb >= 50:
        score += 7

    # Criterion 4: Image dimensions (10 pts)
    # ... check width/height

    # Criterion 5: Blender was running (10 pts)
    if blender_was_running:
        score += 10

    # Criterion 6: Render actually performed (15 pts)
    if render_time_sec > 5:
        score += 15
    elif render_time_sec > 0:
        score += 10

    # Criterion 7: VLM - 3D content verified (15 pts)
    if query_vlm:
        vlm_result = query_vlm(image=render_path,
            prompt="Does this show a 3D rendered scene with objects, lighting, shadows?")
        if has_3d_content:
            score += 15
            vlm_3d_verified = True

    # Criterion 8: VLM - Not just UI screenshot (10 pts)
    # ... verify actual render output

    # NEGATIVE CHECK: "Do nothing" detection
    if not file_created and not file_modified:
        feedback_parts.append("FAIL: No new render output created")
        score = min(score, 20)  # Cap score!

    # KEY CRITERIA: Multiple signals required
    key_criteria_met = (
        (file_created or file_modified) and
        (render_time_sec > 0 or file_size_kb > 100) and
        (vlm_3d_verified or dimensions_ok)
    )

    passed = score >= 60 and key_criteria_met
```

### Test Cases That Must Be Included

```python
# Test 1: Agent did nothing - MUST FAIL
mock_data = {"output_exists": False, "file_created": False}
assert not verify_render(...)['passed']

# Test 2: File exists but too small - MUST FAIL
mock_data = {"output_exists": True, "file_size_bytes": 1000, "file_created": True}
assert not verify_render(...)['passed']

# Test 3: Pre-existing file not modified - MUST FAIL
mock_data = {"output_exists": True, "file_created": False, "file_modified": False}
assert not verify_render(...)['passed']

# Test 4: Successful render - MUST PASS
mock_data = {"output_exists": True, "file_created": True, "render_time_seconds": 35}
assert verify_render(...)['passed']
```

### Key Lessons

1. **Always track file modification time** - Compare initial vs final state
2. **Query application state** - Was the app running? Did it perform the operation?
3. **VLM is essential for visual tasks** - Confirms actual content, not just file existence
4. **"Do nothing" should score near 0** - Verifier should not give credit for no work
5. **Multiple signals prevent gaming** - Can't pass by gaming just one criterion

---

## Summary

1. **Use `copy_from_env`**, not `exec_in_env`
2. **Export data to JSON** in `export_result.sh`
3. **Read JSON in verifier** using `copy_from_env`
4. **Use task metadata** for expected values, not hardcoded constants
5. **Return proper format**: `{passed, score, feedback}`
6. **NEVER rely on screenshot size alone** - query application state
7. **Use hybrid verification** with VLM for visual applications
8. **ALWAYS use real data** - never synthetic/generated data
9. **Hide ground truth** from agents using restricted directories
10. **Parse window titles** as fallback when API queries fail
11. **Require multiple signals** for scientific applications
12. **Track file modification times** - detect pre-existing vs newly created
