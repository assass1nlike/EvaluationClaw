"""
Verification Templates and Patterns for Enhanced Task Generation

This module provides structured templates for verification strategies,
common errors to avoid, and anti-gaming techniques.
"""

# =============================================================================
# VLM VERIFICATION PATTERNS SUMMARY
# =============================================================================

VLM_PATTERNS_SUMMARY = """
## VLM Verification Patterns - CRITICAL GUIDELINES

### MOST IMPORTANT PRINCIPLE: Use Full Trajectory, NOT Just Final Screenshot

The verifier receives `traj` — the complete trajectory of (screenshot, action, output) tuples.
VLMs accept multiple images. **You MUST sample and send multiple trajectory frames.**

Why this matters:
- A single final screenshot is a snapshot. The trajectory is the story.
- Process verification is harder to fake.
- GUI windows overlap - later windows cover earlier ones.
- Single-image patterns are the WEAKEST verification.

### Available Tools (from gym_anything.vlm):
```python
from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot, get_first_screenshot

# Sample N frames uniformly across trajectory
frames = sample_trajectory_frames(traj, n=5)

# Get first and last frames for comparison
first = get_first_screenshot(traj)
last = get_final_screenshot(traj)
```

### Recommended Pattern: Trajectory-Aware Pipeline

```python
# ROBUST: Multiple trajectory frames showing the process
frames = sample_trajectory_frames(traj, n=6)
first = get_first_screenshot(traj)
last = get_final_screenshot(traj)

result = query_vlm(
    images=[first] + frames + [last],
    prompt=\"\"\"These images show an agent's progression through a task.
    Image 1: Initial state. Images 2-7: Sampled during work. Image 8: Final state.
    Did the agent go through the expected workflow stages?
    1. Data loaded and visible?
    2. Configuration/setup performed?
    3. Analysis executed?
    4. Results visible in final state?\"\"\"
)
```

### Pattern Categories

**Category A: Terminal State (WEAKEST - use sparingly)**
- Pattern 1: Final Screenshot Binary - single image, yes/no
- Pattern 2: Final State Checklist - single image, checklist
- Pattern 3: Value Extraction - single image, extract value
- Pattern 4: Negative Check - single image, find errors

**Category B: Before-After Comparison (BETTER)**
- Pattern 5: First-Last Transformation - proves change occurred
- Pattern 6: Expected vs Actual - compare to reference
- Pattern 7: Incremental Progress - sample at 0%, 25%, 50%, 75%, 100%

**Category C: Text-Guided Selection (POWERFUL)**
- Pattern 8: Action-Triggered Pull - find action in text, pull surrounding images
- Pattern 9: Error Investigation - find errors in text, examine those frames
- Pattern 10: Milestone Checkpoint - verify each milestone visually

**Category F: Sampling Strategies**
- Pattern 19: Uniform Temporal Sampling - N images across trajectory
- Pattern 20: Change-Based Keyframe - images where significant changes occurred
- Pattern 21: Phase-Based Sampling - one image per task phase

### Anti-Pattern to AVOID

```python
# WEAK - Don't do this!
screenshot = get_final_screenshot(traj)
result = query_vlm(image=screenshot, prompt="Was the task completed?")
# This is easily spoofed - use trajectory verification instead!
```
"""


# =============================================================================
# COMMON ERRORS TO AVOID
# =============================================================================

COMMON_ERRORS = """
## Common Verifier Errors - AVOID THESE

### ERROR 1: Using exec_in_env (NOT AVAILABLE!)

```python
# WRONG - exec_in_env is not provided by the framework!
def verify_task(traj, env_info, task_info):
    exec_in_env = env_info.get('exec_in_env')  # This may be None!
    result = exec_in_env("cat /tmp/result.txt")  # CRASH!

# CORRECT - use copy_from_env
def verify_task(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    copy_from_env("/tmp/task_result.json", temp_file.name)
    with open(temp_file.name, 'r') as f:
        result = json.load(f)
```

### ERROR 2: Hardcoded Expected Values

```python
# WRONG - hardcoded values break reusability
def verify_task(traj, env_info, task_info):
    expected_name = "John"  # Hardcoded!
    expected_count = 5      # Hardcoded!

# CORRECT - use task metadata
def verify_task(traj, env_info, task_info):
    metadata = task_info.get('metadata', {})
    expected_name = metadata.get('expected_name', 'John')
    expected_count = metadata.get('expected_count', 5)
```

### ERROR 3: Single Screenshot Verification (Weak)

```python
# WEAK - can be spoofed by arranging the final screen
screenshot = get_final_screenshot(traj)
result = query_vlm(image=screenshot, prompt="Is task complete?")

# STRONG - use trajectory verification
frames = sample_trajectory_frames(traj, n=5)
result = query_vlm(
    images=frames,
    prompt="Did the agent progress through: setup → work → completion?"
)
```

### ERROR 4: Screenshot Size Heuristics

```python
# TERRIBLE - passes even when agent does nothing!
if screenshot_size_kb > 100:
    data_loaded = True  # WRONG! Welcome screen is also >100KB

# CORRECT - query application state
result = copy_from_env("/tmp/app_state.json", temp_file.name)
if result.get('data_loaded') and result.get('node_count') > 0:
    data_loaded = True
```

### ERROR 5: No "Do Nothing" Detection

```python
# BAD - no do-nothing detection
if output_file_exists:
    return {"passed": True}  # Passes if file pre-existed!

# GOOD - track file creation/modification
if result.get('file_created_during_task'):
    score += 20  # File was actually created
elif result.get('file_modified_during_task'):
    score += 15  # File was modified
else:
    score = max(score, 20)  # Cap score - file pre-existed!
```

### ERROR 6: Synthetic/Generated Data

```python
# WRONG - synthetic data gives meaningless verification
# Task setup generates: {"name": "Test", "value": 123}
# Verification checks: name == "Test" and value == 123
# This proves nothing about actual task completion!

# CORRECT - use real data from official sources
# Task setup downloads actual dataset (BraTS, LIDC, official samples)
# Verification checks against real ground truth
```

### ERROR 7: Missing Temp File Cleanup

```python
# BAD - temp file leak
temp_file = tempfile.NamedTemporaryFile(delete=False)
copy_from_env("/tmp/result.json", temp_file.name)
result = json.load(open(temp_file.name))
# temp_file never deleted!

# GOOD - proper cleanup with try/finally
temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
try:
    copy_from_env("/tmp/result.json", temp_file.name)
    with open(temp_file.name, 'r') as f:
        result = json.load(f)
finally:
    if os.path.exists(temp_file.name):
        os.unlink(temp_file.name)
```

### ERROR 8: No VLM Fallback Strategy

```python
# FRAGILE - fails if VLM unavailable
vlm_result = query_vlm(image=screenshot, prompt="Is complete?")
return {"passed": vlm_result['complete']}  # No fallback!

# ROBUST - VLM is supplementary, not primary
score = 0
# Primary verification (programmatic)
if result.get('data_exists'):
    score += 40
if result.get('output_correct'):
    score += 30

# VLM verification (supplementary)
query_vlm = env_info.get('query_vlm')
if query_vlm:
    vlm_result = query_vlm(...)
    if vlm_result.get('visual_confirmation'):
        score += 30
else:
    # No VLM available - still return reasonable result
    pass

return {"passed": score >= 60, "score": score}
```
"""


# =============================================================================
# MULTI-CRITERIA SCORING TEMPLATE
# =============================================================================

MULTI_CRITERIA_TEMPLATE = """
## Multi-Criteria Scoring Template

Every verifier should check multiple independent signals. Here's the recommended pattern:

```python
def verify_task(traj, env_info, task_info):
    \"\"\"Multi-criteria verification with weighted scoring.\"\"\"

    # Setup
    copy_from_env = env_info.get('copy_from_env')
    query_vlm = env_info.get('query_vlm')
    metadata = task_info.get('metadata', {})

    score = 0
    feedback_parts = []

    # =========================================================================
    # CRITERION 1: Data/Output Exists (15 points)
    # =========================================================================
    output_exists = result.get('output_exists', False)
    if output_exists:
        score += 15
        feedback_parts.append("Output exists")
    else:
        feedback_parts.append("Output NOT found")

    # =========================================================================
    # CRITERION 2: Data Created/Modified DURING Task (15 points)
    # Critical for anti-gaming - detects "do nothing"
    # =========================================================================
    file_created = result.get('file_created_during_task', False)
    file_modified = result.get('file_modified_during_task', False)

    if file_created:
        score += 15
        feedback_parts.append("Output created during task")
    elif file_modified:
        score += 12
        feedback_parts.append("Output modified during task")
    else:
        feedback_parts.append("WARN: Output may have pre-existed")

    # =========================================================================
    # CRITERION 3: Content Correctness (20 points)
    # =========================================================================
    expected_value = metadata.get('expected_value')
    actual_value = result.get('actual_value')

    if expected_value and actual_value:
        if actual_value == expected_value:
            score += 20
            feedback_parts.append(f"Value correct: {actual_value}")
        else:
            feedback_parts.append(f"Value wrong: expected {expected_value}, got {actual_value}")

    # =========================================================================
    # CRITERION 4: VLM Visual Verification (25 points)
    # Use trajectory frames, not just final screenshot
    # =========================================================================
    if query_vlm:
        try:
            from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot

            frames = sample_trajectory_frames(traj, n=5)
            final = get_final_screenshot(traj)

            vlm_result = query_vlm(
                images=frames + [final],
                prompt=\"\"\"These images show task progression.
                Did the agent:
                1. Start correctly?
                2. Make meaningful progress?
                3. Complete the task successfully?
                Return JSON: {"started": bool, "progress": bool, "completed": bool}\"\"\"
            )

            if vlm_result.get('completed'):
                score += 25
                feedback_parts.append("VLM: Task completed")
            elif vlm_result.get('progress'):
                score += 15
                feedback_parts.append("VLM: Partial progress")
            else:
                feedback_parts.append("VLM: No progress detected")

        except Exception as e:
            feedback_parts.append(f"VLM unavailable: {e}")

    # =========================================================================
    # CRITERION 5: No Errors Present (10 points)
    # =========================================================================
    errors_found = result.get('errors', [])
    if not errors_found:
        score += 10
        feedback_parts.append("No errors")
    else:
        feedback_parts.append(f"Errors: {errors_found[:2]}")

    # =========================================================================
    # CRITERION 6: Application Was Running (15 points)
    # =========================================================================
    app_running = result.get('app_was_running', False)
    if app_running:
        score += 15
        feedback_parts.append("App confirmed running")

    # =========================================================================
    # KEY CRITERIA ENFORCEMENT
    # Some criteria are mandatory for passing, regardless of score
    # =========================================================================
    key_criteria_met = (
        (file_created or file_modified) and  # Something was actually done
        output_exists and                     # Output was produced
        app_running                           # App was involved
    )

    # =========================================================================
    # FINAL RESULT
    # =========================================================================
    passed = score >= 60 and key_criteria_met

    return {
        "passed": passed,
        "score": score,
        "feedback": " | ".join(feedback_parts),
        "details": {
            "key_criteria_met": key_criteria_met,
            "output_exists": output_exists,
            "file_created": file_created,
            "app_running": app_running,
        }
    }
```
"""


# =============================================================================
# ANTI-GAMING TECHNIQUES
# =============================================================================

ANTI_GAMING_TECHNIQUES = """
## Anti-Gaming Techniques

### 1. Track File Creation/Modification Time

```bash
# In export_result.sh - record timestamps
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
OUTPUT_MTIME=$(stat -c %Y /path/to/output 2>/dev/null || echo "0")

if [ "$OUTPUT_MTIME" -gt "$TASK_START" ]; then
    FILE_CREATED_DURING_TASK="true"
else
    FILE_CREATED_DURING_TASK="false"
fi
```

### 2. Require Multiple Independent Signals

```python
# Don't pass on just one signal
key_criteria_met = (
    programmatic_check_passed and  # Can't be faked
    vlm_trajectory_passed and      # Visual confirmation
    timestamp_check_passed         # File was actually created
)
passed = score >= threshold and key_criteria_met
```

### 3. Use Trajectory Verification (Not Just Final Screenshot)

```python
# The trajectory is captured by the FRAMEWORK, not the agent
# This makes it tamper-proof
frames = sample_trajectory_frames(traj, n=5)  # Framework-captured
vlm_result = query_vlm(images=frames, prompt="Did agent progress?")
```

### 4. Compare Initial vs Final State

```bash
# In setup_task.sh
INITIAL_COUNT=$(mysql -e "SELECT COUNT(*) FROM table")
echo "$INITIAL_COUNT" > /tmp/initial_count.txt

# In export_result.sh
FINAL_COUNT=$(mysql -e "SELECT COUNT(*) FROM table")
INITIAL_COUNT=$(cat /tmp/initial_count.txt)
NEW_RECORDS=$((FINAL_COUNT - INITIAL_COUNT))
```

### 5. Verify Application Was Actually Used

```python
# Check that the application was running
if not result.get('app_was_running'):
    score = max(score, 20)  # Cap score if app wasn't even used
    feedback_parts.append("WARN: Application may not have been used")
```

### 6. VLM Cross-Validation

```python
# Use VLM to validate programmatic results
if programmatic_score > 80:
    vlm_result = query_vlm(image=screenshot,
                          prompt="Does this show successful completion?")
    if not vlm_result.get('success'):
        # Suspicious - high programmatic score but VLM disagrees
        score -= 20
        feedback_parts.append("WARN: VLM disagrees with programmatic check")
```

### 7. Test "Do Nothing" Explicitly

Every verifier should be tested with these scenarios:
1. Agent does nothing → Should score ~0
2. Agent only loads data → Should score <30%
3. Agent does partial work → Should score proportionally
4. Agent completes task → Should pass

### 8. Require Specific Output Content

```python
# Don't just check file exists - check content
if output_content.strip():  # Non-empty
    if expected_pattern in output_content:
        score += points
    else:
        feedback_parts.append("Output exists but content incorrect")
else:
    feedback_parts.append("Output file is empty")
```
"""


# =============================================================================
# TWO-PART VERIFICATION PATTERN
# =============================================================================

TWO_PART_VERIFICATION = """
## Two-Part Verification Pattern (MANDATORY)

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                      CONTAINER (VM/Docker)                          │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ export_result.sh (post_task hook)                              │ │
│  │ - Query databases                                              │ │
│  │ - Check files                                                  │ │
│  │ - Gather all verification data                                 │ │
│  │ - Save to /tmp/task_result.json                                │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ copy_from_env()
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         HOST MACHINE                                │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ verifier.py                                                    │ │
│  │ - Copy /tmp/task_result.json from container                   │ │
│  │ - Parse JSON                                                   │ │
│  │ - Evaluate results                                             │ │
│  │ - Return {passed, score, feedback}                             │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### Part 1: export_result.sh (Runs IN Container)

```bash
#!/bin/bash
echo "=== Exporting Task Results ==="

# Record task end time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

# Query database/files
DATA=$(some_query_command)
COUNT=$(another_check)

# Check application state
APP_RUNNING=$(pgrep -f "MyApp" > /dev/null && echo "true" || echo "false")

# Take final screenshot
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || true

# Create JSON result using temp file (permission-safe)
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "data_found": "$DATA",
    "record_count": $COUNT,
    "app_was_running": $APP_RUNNING,
    "screenshot_exists": true
}
EOF

# Move to final location with permission handling
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
```

### Part 2: verifier.py (Runs on HOST)

```python
#!/usr/bin/env python3
import json
import tempfile
import os

def verify_task(traj, env_info, task_info):
    # Get copy function
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    # Get metadata
    metadata = task_info.get('metadata', {})

    # Copy result from container
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

    # Evaluate using multi-criteria approach
    score = 0
    feedback_parts = []

    # ... (apply multi-criteria scoring template)

    return {"passed": score >= 60, "score": score, "feedback": " | ".join(feedback_parts)}
```
"""


# =============================================================================
# VERIFIER OUTPUT FORMAT
# =============================================================================

VERIFIER_OUTPUT_FORMAT = """
## Verifier Output Format

All verifiers MUST return this exact structure:

```python
return {
    "passed": bool,           # True if task completed successfully
    "score": int,             # 0-100, percentage of criteria met
    "feedback": str,          # Human-readable summary
    "details": dict           # Optional: detailed breakdown
}
```

### Examples

**Successful completion:**
```python
return {
    "passed": True,
    "score": 95,
    "feedback": "Data created | Content correct | VLM confirmed | App was running",
    "details": {
        "criteria_met": 8,
        "criteria_total": 8,
        "vlm_confidence": 0.92
    }
}
```

**Partial completion:**
```python
return {
    "passed": False,
    "score": 45,
    "feedback": "Data exists | Content WRONG: expected 'John', got 'Jane' | VLM: partial progress",
    "details": {
        "expected": "John",
        "actual": "Jane",
        "vlm_progress": True
    }
}
```

**Complete failure:**
```python
return {
    "passed": False,
    "score": 0,
    "feedback": "Output not found | App was not running | VLM: no progress detected",
    "details": {
        "output_exists": False,
        "app_running": False
    }
}
```
"""


# =============================================================================
# COMPLETE VERIFICATION GUIDELINES
# =============================================================================

def get_complete_verification_guidelines() -> str:
    """Get all verification guidelines combined."""
    return f"""
# Verification Guidelines for Task Generation

{VLM_PATTERNS_SUMMARY}

{COMMON_ERRORS}

{MULTI_CRITERIA_TEMPLATE}

{ANTI_GAMING_TECHNIQUES}

{TWO_PART_VERIFICATION}

{VERIFIER_OUTPUT_FORMAT}
"""


# =============================================================================
# COMPACT SUMMARIES (for prompt length management)
# =============================================================================

def get_compact_vlm_summary() -> str:
    """Get a compact summary of VLM patterns for prompts."""
    return """
## VLM Verification (CRITICAL)

USE TRAJECTORY FRAMES, NOT JUST FINAL SCREENSHOT:
```python
from gym_anything.vlm import sample_trajectory_frames, get_final_screenshot
frames = sample_trajectory_frames(traj, n=5)  # Sample across trajectory
final = get_final_screenshot(traj)
result = query_vlm(images=frames + [final], prompt="Did agent complete workflow?")
```

WHY: Final screenshot can be spoofed. Trajectory proves actual work was done.
"""


def get_compact_errors_summary() -> str:
    """Get a compact summary of common errors for prompts."""
    return """
## Common Errors to AVOID

1. USE `copy_from_env`, NOT `exec_in_env` (exec_in_env is not provided!)
2. Get expected values from `task_info.get('metadata', {})`, NOT hardcoded
3. Use trajectory frames for VLM, NOT just final screenshot
4. Detect "do nothing" via file timestamps, NOT just file existence
5. Use real data, NOT synthetic/generated data
6. Clean up temp files with try/finally
"""


def get_compact_scoring_summary() -> str:
    """Get a compact summary of multi-criteria scoring for prompts."""
    return """
## Multi-Criteria Scoring Pattern

```python
score = 0
# Criterion 1: Output exists (15 pts)
# Criterion 2: Created DURING task (15 pts) - anti-gaming!
# Criterion 3: Content correct (20 pts)
# Criterion 4: VLM trajectory verification (25 pts)
# Criterion 5: No errors (10 pts)
# Criterion 6: App was running (15 pts)

key_criteria_met = (file_created or file_modified) and output_exists and app_running
passed = score >= 60 and key_criteria_met
```
"""


if __name__ == "__main__":
    print("Verification Templates Module")
    print("=" * 50)
    print("\nAvailable functions:")
    print("  - get_complete_verification_guidelines()")
    print("  - get_compact_vlm_summary()")
    print("  - get_compact_errors_summary()")
    print("  - get_compact_scoring_summary()")
    print("\nAvailable constants:")
    print("  - VLM_PATTERNS_SUMMARY")
    print("  - COMMON_ERRORS")
    print("  - MULTI_CRITERIA_TEMPLATE")
    print("  - ANTI_GAMING_TECHNIQUES")
    print("  - TWO_PART_VERIFICATION")
    print("  - VERIFIER_OUTPUT_FORMAT")
