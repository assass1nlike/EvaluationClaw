"""
Task Setup Templates and Guidelines for Enhanced Task Generation

This module provides comprehensive guidance on task setup, including:
- Task description quality
- Initial state requirements
- Real data sourcing
- Setup script patterns
- Evidence and screenshot requirements
"""

# =============================================================================
# TASK DESCRIPTION QUALITY GUIDELINES
# =============================================================================

TASK_DESCRIPTION_GUIDELINES = """
## Task Description Quality Requirements

The task description in task.json is THE PRIMARY INPUT the agent receives.
A good description is the difference between a fair task and an impossible one.

### Principle 1: Sufficient Detail for Completion

The description MUST contain ALL information needed to complete the task correctly:

**GOOD:**
```json
"description": "Create a new patient record in OpenEMR with the following details:
- First Name: John
- Last Name: TestPatient
- Date of Birth: 1985-03-15
- Sex: Male
- Address: 123 Main Street, Boston, MA 02101

Navigate to Patient > New Patient, fill in the form, and save."
```

**BAD:**
```json
"description": "Add a new patient to the system."
// Missing: What fields? What values? Where to navigate?
```

### Principle 2: Not Over-Detailed (Agent Should Know Features)

Don't explain HOW to use software features - the agent should know that.
Focus on WHAT to accomplish.

**GOOD:**
```json
"description": "Apply a sepia tone color grade to the video clip on track 1."
```

**BAD:**
```json
"description": "Apply a sepia tone color grade to the video clip on track 1.
To do this, click on the Color page, then select the clip, then open
the Curves panel, then adjust the RGB curves to create a sepia effect
by reducing blue channel..."
// TOO MUCH - agent should know DaVinci Resolve!
```

### Principle 3: Avoid Ambiguity (Multiple Valid Approaches)

If multiple approaches are valid, either:
- Accept all valid approaches in verification, OR
- Specify which approach to use

**PROBLEMATIC:**
```json
"description": "Export the image in a web-friendly format."
// Ambiguous: PNG? JPEG? WebP? At what quality?
```

**FIXED (Option A - Specific):**
```json
"description": "Export the image as a JPEG file at 80% quality to ~/output.jpg"
```

**FIXED (Option B - Flexible Verifier):**
```json
"description": "Export the image in a web-friendly format (PNG, JPEG, or WebP)."
// Verifier accepts any of these formats
```

### Principle 4: Expected Output Must Be Clear

If the verifier checks for specific outputs, the description MUST mention them:

**CRITICAL:**
- If verifier checks for a file → describe the expected filename
- If verifier checks for specific values → mention acceptable ranges
- If verifier checks for screenshot evidence → mention what should be visible

**BAD:**
```json
"description": "Render the scene."
// Verifier expects output at ~/renders/output.png - but agent doesn't know!
```

**GOOD:**
```json
"description": "Render the scene and save the output to ~/renders/output.png at 1920x1080 resolution."
```

### Principle 5: Align Description with Verification

The golden rule: **A perfect agent following the description should pass verification.**

Before finalizing, verify:
1. Every verifier criterion is achievable from description alone
2. No hidden requirements not mentioned in description
3. Expected outputs (files, values, states) are clearly specified
"""


# =============================================================================
# INITIAL STATE REQUIREMENTS
# =============================================================================

INITIAL_STATE_REQUIREMENTS = """
## Initial State Requirements (Task Setup)

The task must start from a WELL-DEFINED initial state. The agent should not
have to guess what state the application is in.

### What setup_task.sh Must Establish

1. **Correct Software Open**
   - The target application MUST be running
   - The correct window must be focused
   - The application should be maximized (not hidden behind other windows)

2. **Correct Screen/View**
   - If task requires specific view → navigate to that view
   - If task requires specific panel open → open that panel
   - If task starts from a menu → open that menu

3. **Data Pre-loaded (If Required)**
   - If description says "Given a loaded image..." → image must be loaded
   - If description says "With the project open..." → project must be open
   - If description says "Starting from the database..." → database must be connected

4. **Clean State (No Stale Data)**
   - Remove previous task artifacts
   - Reset to known good state
   - Clear any popup dialogs

### setup_task.sh Template

```bash
#!/bin/bash
set -e
echo "=== Setting up task ==="

# Record task start time (for anti-gaming verification)
date +%s > /tmp/task_start_time.txt

# Record initial state for comparison
INITIAL_COUNT=$(some_query_command 2>/dev/null || echo "0")
echo "$INITIAL_COUNT" > /tmp/initial_count.txt

# Ensure application is running
if ! pgrep -f "MyApp" > /dev/null; then
    echo "Starting MyApp..."
    su - ga -c "DISPLAY=:1 /usr/bin/myapp &"
    sleep 5
fi

# Wait for window to appear
for i in {1..30}; do
    if DISPLAY=:1 wmctrl -l | grep -i "MyApp"; then
        break
    fi
    sleep 1
done

# Maximize window (CRITICAL for agent visibility)
DISPLAY=:1 wmctrl -r "MyApp" -b add,maximized_vert,maximized_horz 2>/dev/null || true

# Focus the window
DISPLAY=:1 wmctrl -a "MyApp" 2>/dev/null || true

# Navigate to correct initial state
# (Example: open a specific screen or load required data)
if [ -n "$DATA_FILE" ]; then
    # Load required data file
    DISPLAY=:1 xdotool key ctrl+o
    sleep 1
    DISPLAY=:1 xdotool type "$DATA_FILE"
    DISPLAY=:1 xdotool key Return
    sleep 3
fi

# Dismiss any startup dialogs
DISPLAY=:1 xdotool key Escape 2>/dev/null || true

# Take screenshot of initial state (for evidence)
DISPLAY=:1 scrot /tmp/task_initial_state.png 2>/dev/null || true

echo "=== Task setup complete ==="
```

### Initial State Verification Checklist

Before the task is considered ready:

- [ ] Application is visible in initial screenshot
- [ ] Application is in the state described in task description
- [ ] If data should be loaded, it is visible
- [ ] No blocking dialogs or popups
- [ ] Window is maximized and focused
- [ ] Initial state screenshot is saved for evidence
"""


# =============================================================================
# REAL DATA REQUIREMENTS (COMPREHENSIVE)
# =============================================================================

REAL_DATA_REQUIREMENTS_COMPREHENSIVE = """
## Real Data Requirements (CRITICAL)

**RULE: Synthetic/fake data is NEVER acceptable.**

### Why Real Data Matters

1. **Authenticity**: Fake data doesn't represent real-world complexity
2. **Verification Validity**: Checking fake data against fake ground truth is meaningless
3. **Agent Training**: Agents need realistic scenarios to be useful
4. **Credibility**: Tasks with obvious fake data are not taken seriously

### What Counts as "Fake" Data

**NOT ACCEPTABLE:**
- Handwritten SQL inserts: `INSERT INTO patients VALUES (1, 'John', 'Doe')`
- Generated placeholder text: "Lorem ipsum dolor sit amet"
- Trivial examples: 3 rows in an Excel sheet
- Obviously synthetic: Perfect sine waves, uniform distributions
- Placeholder images: Solid color rectangles, text placeholders

**ACCEPTABLE:**
- Official sample datasets from software vendors
- Public domain datasets (Kaggle, government portals)
- Domain-specific generators (Synthea for healthcare - it generates realistic patterns)
- Real media files (Creative Commons, codec test suites)
- Actual screenshots/documents (anonymized if needed)

### Data Sourcing by Domain

| Domain | GOOD Sources | BAD Approaches |
|--------|--------------|----------------|
| **Medical Imaging** | BraTS, LIDC-IDRI, TCIA, official DICOM samples | Hand-drawn shapes, random noise |
| **Healthcare/EHR** | Synthea generator, MIMIC demo | Handwritten patient records |
| **Astronomy** | FITS archives, official telescope data | Synthetic star patterns |
| **Documents** | Official templates, public domain PDFs | "Lorem ipsum" placeholder text |
| **Databases** | Official demo DBs (Sakila, Northwind, Chinook) | 3-row handwritten tables |
| **Video/Audio** | Codec test suites, Creative Commons media | Solid color frames, silence |
| **Spreadsheets** | Government open data, Kaggle datasets | Trivial 3x3 example data |
| **GIS/Maps** | OpenStreetMap, official GIS datasets | Hand-drawn geometries |

### Data Complexity Requirements

Data should be **challenging enough** to be meaningful:

**TOO SIMPLE (Not Acceptable):**
```
| Name  | Age |
|-------|-----|
| John  | 30  |
| Jane  | 25  |
```

**APPROPRIATE:**
```
- Database with 100+ records
- Spreadsheet with multiple sheets and formulas
- Medical scan with actual anatomy
- Video with real footage (not test patterns)
- Document with realistic content and formatting
```

### Data Preparation Pattern

```bash
#!/bin/bash
# prepare_data.sh

DATA_DIR="/home/ga/Documents/TaskData"
GROUND_TRUTH_DIR="/var/lib/app/ground_truth"  # Hidden from agent

# Download real dataset
if [ ! -d "$DATA_DIR/dataset" ]; then
    echo "Downloading real dataset..."

    # Option 1: Direct download
    curl -L -o "$DATA_DIR/dataset.zip" "https://official-source.com/dataset.zip"
    unzip -q "$DATA_DIR/dataset.zip" -d "$DATA_DIR/"

    # Option 2: Kaggle (for public datasets)
    curl -L -o "$DATA_DIR/dataset.zip" \\
        "https://www.kaggle.com/api/v1/datasets/download/user/dataset-name"

    # Option 3: Official sample data
    wget -O "$DATA_DIR/sample.db" "https://github.com/org/repo/raw/main/sample.db"
fi

# Separate ground truth (keep hidden from agent)
if [ -f "$DATA_DIR/ground_truth.nii.gz" ]; then
    mkdir -p "$GROUND_TRUTH_DIR"
    mv "$DATA_DIR/ground_truth.nii.gz" "$GROUND_TRUTH_DIR/"
    chmod 700 "$GROUND_TRUTH_DIR"
fi

# Set proper permissions
chown -R ga:ga "$DATA_DIR"
```

### Data Validation Checklist

Before task is ready, verify:

- [ ] Data is from a legitimate real source (not handwritten)
- [ ] Data matches task description (right format, content)
- [ ] Data is sufficiently complex (not trivial examples)
- [ ] Ground truth is hidden from agent (if applicable)
- [ ] Data can be downloaded/prepared reliably
- [ ] Data license permits use
"""


# =============================================================================
# SETUP SCRIPT PATTERNS
# =============================================================================

SETUP_SCRIPT_PATTERNS = """
## Setup Script Patterns

### Desktop Application Setup

```bash
#!/bin/bash
echo "=== Setting up desktop app task ==="

# Timestamp for anti-gaming
date +%s > /tmp/task_start_time.txt

# Start application if not running
if ! pgrep -f "MyApp" > /dev/null; then
    su - ga -c "DISPLAY=:1 /usr/bin/myapp &"

    # Wait for window
    for i in {1..60}; do
        if DISPLAY=:1 wmctrl -l | grep -qi "myapp"; then
            echo "Application window detected"
            break
        fi
        sleep 1
    done
fi

# Maximize and focus
DISPLAY=:1 wmctrl -r "MyApp" -b add,maximized_vert,maximized_horz 2>/dev/null || true
DISPLAY=:1 wmctrl -a "MyApp" 2>/dev/null || true

# Load required data (if any)
if [ -f "/home/ga/Documents/data.file" ]; then
    # Use application-specific method to open file
    DISPLAY=:1 xdotool key ctrl+o
    sleep 1
    DISPLAY=:1 xdotool type "/home/ga/Documents/data.file"
    DISPLAY=:1 xdotool key Return
    sleep 3
fi

# Take initial screenshot
DISPLAY=:1 scrot /tmp/task_initial.png 2>/dev/null || true

echo "=== Setup complete ==="
```

### Web Application Setup

```bash
#!/bin/bash
echo "=== Setting up web app task ==="

# Timestamp
date +%s > /tmp/task_start_time.txt

# Record initial database state
INITIAL_COUNT=$(docker exec db mysql -N -e "SELECT COUNT(*) FROM records" 2>/dev/null || echo "0")
echo "$INITIAL_COUNT" > /tmp/initial_count.txt

# Ensure services are running
docker-compose -f /app/docker-compose.yml up -d

# Wait for web interface
for i in {1..60}; do
    if curl -s http://localhost/ > /dev/null 2>&1; then
        echo "Web interface ready"
        break
    fi
    sleep 2
done

# Start Firefox to correct page
if ! pgrep -f firefox > /dev/null; then
    su - ga -c "DISPLAY=:1 firefox http://localhost/target-page &"
    sleep 5
fi

# Maximize browser
DISPLAY=:1 wmctrl -r "Firefox" -b add,maximized_vert,maximized_horz 2>/dev/null || true

# Login if needed
# ... login automation ...

# Take screenshot
DISPLAY=:1 scrot /tmp/task_initial.png 2>/dev/null || true

echo "=== Setup complete ==="
```

### Scientific Application Setup (With Data Pre-Loading)

```bash
#!/bin/bash
echo "=== Setting up scientific task ==="

# Timestamp and initial state
date +%s > /tmp/task_start_time.txt

# Ensure data is prepared
/workspace/scripts/prepare_data.sh

# Get sample ID from data preparation
SAMPLE_ID=$(cat /tmp/sample_id.txt 2>/dev/null || echo "default")
echo "$SAMPLE_ID" > /tmp/task_sample_id.txt

# Start application with data
if ! pgrep -f "Slicer" > /dev/null; then
    # Start Slicer with data file as argument
    su - ga -c "DISPLAY=:1 /opt/Slicer/Slicer --no-splash \\
        /home/ga/Documents/Data/${SAMPLE_ID}_flair.nii.gz &"
    sleep 10
fi

# Wait for data to load (check via API or window title)
for i in {1..30}; do
    # Check if data is loaded via application API
    LOADED=$(/opt/Slicer/bin/PythonSlicer -c "
import slicer
nodes = slicer.mrmlScene.GetNodesByClass('vtkMRMLScalarVolumeNode')
print(nodes.GetNumberOfItems())
" 2>/dev/null || echo "0")

    if [ "$LOADED" -gt "0" ]; then
        echo "Data loaded: $LOADED volumes"
        break
    fi
    sleep 2
done

# Maximize
DISPLAY=:1 wmctrl -r "Slicer" -b add,maximized_vert,maximized_horz 2>/dev/null || true

# Screenshot of initial state showing loaded data
DISPLAY=:1 scrot /tmp/task_initial.png 2>/dev/null || true

echo "=== Setup complete ==="
```
"""


# =============================================================================
# EVIDENCE AND SCREENSHOT REQUIREMENTS
# =============================================================================

EVIDENCE_REQUIREMENTS = """
## Evidence and Screenshot Requirements

Screenshots are CRITICAL evidence that tasks are set up and verified correctly.

### Required Screenshots

1. **Initial State Screenshot** (`/tmp/task_initial.png`)
   - Captured at END of setup_task.sh
   - Must show: Application open, correct state, data loaded (if applicable)
   - Purpose: Proves agent starts from expected state

2. **Final State Screenshot** (`/tmp/task_final.png`)
   - Captured at START of export_result.sh
   - Must show: Final application state
   - Purpose: Evidence of task completion

3. **Agent Screenshots** (during trajectory)
   - Captured by framework at each step
   - Used for trajectory-based VLM verification
   - Purpose: Prove work was actually done

### Screenshot Capture Pattern

```bash
# In setup_task.sh (end):
echo "Capturing initial state..."
sleep 1  # Allow UI to stabilize
DISPLAY=:1 scrot /tmp/task_initial.png 2>/dev/null || \\
    DISPLAY=:1 import -window root /tmp/task_initial.png 2>/dev/null || true

# Verify screenshot was captured
if [ -f /tmp/task_initial.png ]; then
    SIZE=$(stat -c %s /tmp/task_initial.png 2>/dev/null || echo "0")
    echo "Initial screenshot captured: ${SIZE} bytes"
else
    echo "WARNING: Could not capture initial screenshot"
fi
```

```bash
# In export_result.sh (start):
echo "Capturing final state..."
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || \\
    DISPLAY=:1 import -window root /tmp/task_final.png 2>/dev/null || true

# Include screenshot info in export JSON
SCREENSHOT_EXISTS="false"
if [ -f /tmp/task_final.png ]; then
    SCREENSHOT_EXISTS="true"
fi
```

### Evidence Validation Checklist

For auditing, verify screenshots show:

- [ ] **Initial Screenshot**:
  - Correct software is open
  - Window is maximized and focused
  - Data is loaded (if task requires)
  - No blocking dialogs
  - State matches task description

- [ ] **Final Screenshot**:
  - Task output is visible (if visual)
  - Expected state achieved
  - No error dialogs

- [ ] **File Timestamps**:
  - Initial screenshot taken before agent starts
  - Final screenshot taken after agent finishes

### What Screenshots Should NOT Show

- Empty desktop (application not started)
- Application startup/splash screen
- Error dialogs
- Wrong application
- State that doesn't match description
"""


# =============================================================================
# TASK.JSON REQUIREMENTS
# =============================================================================

TASK_JSON_REQUIREMENTS = """
## task.json Requirements

### Complete Template

```json
{
  "id": "<task_name>@1",
  "version": "1.0",
  "env_id": "<env_name>@0.1",
  "description": "Detailed description with ALL required information...",
  "difficulty": "medium",
  "init": {
    "timeout_sec": 300,
    "max_steps": 50,
    "reward_type": "sparse"
  },
  "hooks": {
    "pre_task": "/workspace/tasks/<task_name>/setup_task.sh",
    "post_task": "/workspace/tasks/<task_name>/export_result.sh",
    "pre_task_timeout": 600
  },
  "metadata": {
    "expected_output_file": "/home/ga/output.png",
    "expected_value": "100",
    "tolerance": "10",
    "data_source": "BraTS 2021 dataset",
    "ground_truth_location": "/var/lib/app/ground_truth/"
  },
  "success": {
    "mode": "program",
    "spec": {
      "program": "verifier.py::verify_<task_name>"
    }
  }
}
```

### Field Requirements

| Field | Required | Notes |
|-------|----------|-------|
| `id` | Yes | Format: `task_name@version` |
| `description` | Yes | MUST be complete and unambiguous |
| `difficulty` | Recommended | easy/medium/hard |
| `init.timeout_sec` | Yes | Based on task complexity |
| `init.max_steps` | Yes | Reasonable for task |
| `hooks.pre_task` | Yes | Setup script path |
| `hooks.post_task` | Yes | Export script path |
| `hooks.pre_task_timeout` | If needed | For long data downloads |
| `metadata` | Recommended | Expected values, data sources |
| `success.spec.program` | Yes | Verifier function path |

### Description Quality Checks

Before finalizing task.json:

1. **Information Completeness**:
   - [ ] All required values/filenames mentioned
   - [ ] Clear success criteria stated
   - [ ] Starting state described

2. **Ambiguity Check**:
   - [ ] Only one valid interpretation
   - [ ] No "use any approach" without flexible verifier

3. **Alignment Check**:
   - [ ] Every verifier criterion is achievable from description
   - [ ] No hidden requirements

### Metadata Best Practices

Use metadata to store expected values (not hardcoded in verifier):

```json
"metadata": {
  // Expected outputs
  "expected_output_path": "/home/ga/output.png",
  "expected_filename": "report.pdf",

  // Expected values
  "expected_count": 5,
  "expected_value": "100",
  "tolerance": "10%",

  // Data information
  "data_source": "https://example.com/dataset.zip",
  "sample_id": "BraTS2021_00495",
  "ground_truth_dir": "/var/lib/app/ground_truth/",

  // Scoring weights (if needed)
  "score_output_exists": 20,
  "score_content_correct": 40,
  "score_vlm_verification": 40
}
```
"""


# =============================================================================
# COMPLETE TASK SETUP GUIDELINES
# =============================================================================

def get_complete_task_setup_guidelines() -> str:
    """Get all task setup guidelines combined."""
    return f"""
# Task Setup Guidelines for Task Generation

{TASK_DESCRIPTION_GUIDELINES}

{INITIAL_STATE_REQUIREMENTS}

{REAL_DATA_REQUIREMENTS_COMPREHENSIVE}

{SETUP_SCRIPT_PATTERNS}

{EVIDENCE_REQUIREMENTS}

{TASK_JSON_REQUIREMENTS}
"""


# =============================================================================
# COMPACT SUMMARIES
# =============================================================================

def get_compact_description_guidelines() -> str:
    """Get compact task description guidelines."""
    return """
## Task Description Guidelines (CRITICAL)

1. **Sufficient Detail**: Include ALL info agent needs (filenames, values, locations)
2. **Not Over-Detailed**: Don't explain HOW to use features - agent should know that
3. **Avoid Ambiguity**: If multiple approaches valid, accept all OR specify which one
4. **Output Clarity**: If verifier checks for file/value, mention it in description
5. **Alignment**: A perfect agent following description should pass verification

**BAD:** "Add a patient to the system."
**GOOD:** "Create a patient record: John TestPatient, DOB 1985-03-15, Male, 123 Main St Boston MA"
"""


def get_compact_initial_state_guidelines() -> str:
    """Get compact initial state guidelines."""
    return """
## Initial State Requirements

setup_task.sh MUST ensure:
1. Correct software is running and maximized
2. Correct screen/view is shown
3. Required data is loaded (if description says "Given...")
4. No blocking dialogs
5. Initial screenshot captured

```bash
# Essential pattern:
date +%s > /tmp/task_start_time.txt  # Anti-gaming timestamp
# ... start app, maximize, load data ...
DISPLAY=:1 scrot /tmp/task_initial.png  # Evidence
```
"""


def get_compact_data_guidelines() -> str:
    """Get compact data guidelines."""
    return """
## Real Data Requirements (NON-NEGOTIABLE)

**NOT ACCEPTABLE:**
- Handwritten SQL: `INSERT INTO t VALUES (1, 'John')`
- Trivial examples: 3-row spreadsheet
- Placeholder text: "Lorem ipsum"
- Synthetic patterns: Perfect sine waves

**ACCEPTABLE:**
- Official sample datasets
- Kaggle/government open data
- Domain generators (Synthea for healthcare)
- Real media (Creative Commons)

Data must be:
- [ ] From legitimate source (not handwritten)
- [ ] Sufficiently complex (not trivial)
- [ ] Matching task description
- [ ] Ground truth hidden from agent
"""


if __name__ == "__main__":
    print("Task Setup Templates Module")
    print("=" * 50)
    print("\nAvailable functions:")
    print("  - get_complete_task_setup_guidelines()")
    print("  - get_compact_description_guidelines()")
    print("  - get_compact_initial_state_guidelines()")
    print("  - get_compact_data_guidelines()")
    print("\nAvailable constants:")
    print("  - TASK_DESCRIPTION_GUIDELINES")
    print("  - INITIAL_STATE_REQUIREMENTS")
    print("  - REAL_DATA_REQUIREMENTS_COMPREHENSIVE")
    print("  - SETUP_SCRIPT_PATTERNS")
    print("  - EVIDENCE_REQUIREMENTS")
    print("  - TASK_JSON_REQUIREMENTS")
