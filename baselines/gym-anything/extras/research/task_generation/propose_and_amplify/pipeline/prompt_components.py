"""
Modular Prompt Components for Enhanced Task Generation

This module provides composable prompt sections that can be assembled
into complete prompts for task generation.
"""

import os
import csv
import ast
from collections import Counter
from glob import glob
from typing import List, Optional, Dict

from .verification_templates import (
    get_compact_vlm_summary,
    get_compact_errors_summary,
    get_compact_scoring_summary,
    VLM_PATTERNS_SUMMARY,
    COMMON_ERRORS,
    MULTI_CRITERIA_TEMPLATE,
    ANTI_GAMING_TECHNIQUES,
    TWO_PART_VERIFICATION,
)

from .task_setup_templates import (
    TASK_DESCRIPTION_GUIDELINES,
    INITIAL_STATE_REQUIREMENTS,
    REAL_DATA_REQUIREMENTS_COMPREHENSIVE,
    SETUP_SCRIPT_PATTERNS,
    EVIDENCE_REQUIREMENTS,
    TASK_JSON_REQUIREMENTS,
    get_complete_task_setup_guidelines,
    get_compact_description_guidelines,
    get_compact_initial_state_guidelines,
    get_compact_data_guidelines,
)


# =============================================================================
# TASK GENERATION PROMPT COMPONENTS (Step 1)
# =============================================================================

VERIFICATION_STRATEGY_REQUIREMENTS = """
## VERIFICATION STRATEGY REQUIREMENTS

Every task you create MUST have a clear, robust verification strategy. Consider these approaches:

### 1. Database Verification (for web apps with data persistence)
- Query database tables for created/modified records
- Compare initial vs final record counts
- Verify specific field values match expectations
- Example apps: OpenSIS, OpenEMR, Moodle, Magento

### 2. File-based Verification (for desktop apps that produce outputs)
- Check output file existence, size, and format
- Verify file modification timestamps (detect "do nothing")
- Parse file content for expected values
- Example apps: 3D Slicer, Blender, GIMP, DaVinci Resolve

### 3. VLM Hybrid Verification (for visual/spatial tasks) - RECOMMENDED
- Use trajectory screenshots (NOT just final screenshot!)
- Combine programmatic checks with visual verification
- Verify workflow progression, not just final state
- Example apps: AstroImageJ, Google Earth, Weasis

### 4. API/State Verification (for apps with queryable state)
- Query application internals (e.g., Slicer's mrmlScene)
- Check configuration files, logs, or registry
- Verify application-specific state changes
- Example apps: VSCode, Chrome, IntelliJ IDEA

### KEY PRINCIPLE: Multiple Independent Signals
Your task should be verifiable through AT LEAST 2 independent methods to prevent gaming.
"""


REAL_DATA_REQUIREMENTS = """
## CRITICAL: REAL DATA ONLY

Tasks MUST use real data sources. Synthetic/generated data is NOT acceptable.

### Why Real Data Matters
- Synthetic data doesn't capture real-world complexity
- Verification against synthetic ground truth is meaningless
- Agents need realistic scenarios to be useful

### Data Sources by Domain

| Domain | Real Data Sources |
|--------|-------------------|
| Medical Imaging | BraTS, LIDC-IDRI, TCIA collections, official sample datasets |
| Astronomy | FITS archives, official telescope data releases |
| Documents | Official sample files, public domain documents |
| Databases | Official demo databases, Synthea (healthcare generator) |
| Media | Creative Commons content, codec test suites |
| Geospatial | OpenStreetMap, official GIS datasets |

### Data Preparation Pattern
```bash
# Download real data (not generate synthetic!)
curl -L -o dataset.zip https://official-source.com/dataset.zip
unzip dataset.zip

# Hide ground truth from agent
mv ground_truth.file /var/lib/app/ground_truth/
chmod 700 /var/lib/app/ground_truth/
```
"""


ANTI_GAMING_REQUIREMENTS = """
## ANTI-GAMING REQUIREMENTS

Your task description must enable verification that:

### 1. "Do Nothing" Scores Zero
The verifier must be able to detect if the agent did nothing at all.
Include checks for:
- File creation timestamps (not just existence)
- Database record counts (compare before/after)
- Application state changes

### 2. Partial Work Scores Proportionally
Define clear milestones so partial completion can be scored:
- Step 1 complete: X points
- Step 2 complete: Y points
- All steps complete: 100 points

### 3. Wrong Parameters Fail
Even if the structure is correct, wrong values should fail:
- Specify expected values in task metadata
- Use tolerance ranges where appropriate
- Verify content, not just presence

### 4. Process Matters, Not Just Outcome
For visual tasks, require trajectory verification:
- Agent must show work progression
- Can't just arrange the final screen
"""


# =============================================================================
# OCCUPATION & INDUSTRY DATA LOOKUP
# =============================================================================

def _get_task_creation_notes_dir() -> str:
    """Get the path to the packaged task_creation_notes/ directory.

    Points at extras/research/task_generation/propose_and_amplify/memory/
    task_creation_notes/. Override with GYM_ANYTHING_TASK_NOTES if needed.
    """
    override = os.environ.get("GYM_ANYTHING_TASK_NOTES")
    if override:
        return os.path.abspath(override)
    # prompt_components.py lives in
    # extras/research/task_generation/propose_and_amplify/pipeline/
    module_dir = os.path.dirname(os.path.abspath(__file__))
    method_dir = os.path.dirname(module_dir)
    return os.path.join(method_dir, "memory", "task_creation_notes")


def _find_product_in_csv(software_name: str, csv_path: str, product_col: str = "product", aka_col: str = None) -> Optional[str]:
    """
    Find the matching product name in a CSV file using progressively looser matching.

    Returns the canonical product name from the CSV, or None.
    """
    if not os.path.exists(csv_path):
        return None

    sw_lower = software_name.strip().lower()
    products = []

    with open(csv_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            p = row.get(product_col, "").strip()
            if p and p not in products:
                products.append(p)

    # 1. Exact match
    for p in products:
        if p == software_name.strip():
            return p

    # 2. Case-insensitive match
    for p in products:
        if p.lower() == sw_lower:
            return p

    # 3. Check aka column in master_dataset (if provided)
    if aka_col and os.path.exists(csv_path):
        sw_words_lower = [w.lower() for w in software_name.strip().split()]
        with open(csv_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                aka_str = row.get(aka_col, "")
                if aka_str:
                    aliases = [a.strip().lower() for a in aka_str.split(",")]
                    # Check full name match or any significant word match
                    if sw_lower in aliases:
                        return row.get(product_col, "").strip()
                    for word in sw_words_lower:
                        if len(word) >= 4 and word in aliases:
                            return row.get(product_col, "").strip()

    # 4. Word overlap: pick the product with the most shared words (>= 4 chars each)
    sw_words = {w for w in sw_lower.split() if len(w) >= 4}
    best_match = None
    best_overlap = 0
    for p in products:
        p_words = {w for w in p.lower().split() if len(w) >= 4}
        overlap = len(sw_words & p_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = p
    if best_overlap >= 2 and best_match:
        return best_match

    # 5. Substring match: one name fully contains the other (min 5 chars, >60% length ratio)
    substring_matches = []
    for p in products:
        p_lower = p.lower()
        if len(p_lower) >= 5 and len(sw_lower) >= 5:
            shorter, longer = sorted([p_lower, sw_lower], key=len)
            if shorter in longer and len(shorter) / len(longer) > 0.6:
                substring_matches.append(p)
    if substring_matches:
        return max(substring_matches, key=len)

    return None


def lookup_occupation_data(software_name: str) -> str:
    """
    Look up occupation and industry data for a software product from
    task_creation_notes/selected_products.csv and master_dataset.csv.

    Returns a formatted prompt section string, or empty string if not found.
    """
    notes_dir = _get_task_creation_notes_dir()
    selected_path = os.path.join(notes_dir, "selected_products.csv")
    master_path = os.path.join(notes_dir, "master_dataset.csv")

    # --- Product summary from selected_products.csv ---
    product_summary = None
    canonical_name = None

    if os.path.exists(selected_path):
        canonical_name = _find_product_in_csv(software_name, selected_path)
        if canonical_name:
            with open(selected_path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row.get("product", "").strip() == canonical_name:
                        categories = row.get("category", "")
                        soc_groups = row.get("soc_major_group", "")
                        total_gdp = row.get("product_total_gdp_usd", "")
                        try:
                            categories = ast.literal_eval(categories)
                        except Exception:
                            pass
                        try:
                            soc_groups = ast.literal_eval(soc_groups)
                        except Exception:
                            pass
                        try:
                            total_gdp_fmt = f"${float(total_gdp):,.0f}"
                        except Exception:
                            total_gdp_fmt = total_gdp
                        product_summary = {
                            "categories": categories,
                            "soc_groups": soc_groups,
                            "total_gdp": total_gdp_fmt,
                        }
                        break

    # --- Occupation + industry data from master_dataset.csv ---
    # Try matching in master_dataset (which has the aka column)
    if not canonical_name and os.path.exists(master_path):
        canonical_name = _find_product_in_csv(
            software_name, master_path, aka_col="aka"
        )

    if not canonical_name:
        return ""

    # Read all rows for this product
    rows = []
    if os.path.exists(master_path):
        with open(master_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("product", "").strip() == canonical_name:
                    rows.append(row)

    if not rows:
        return ""

    # Sort by product_gdp_usd descending
    rows.sort(key=lambda r: float(r.get("product_gdp_usd", 0) or 0), reverse=True)

    # --- Aggregate industries (SOC major groups) ---
    industry_counter = Counter()
    for r in rows:
        grp = r.get("soc_major_group", "").strip()
        if grp:
            industry_counter[grp] += 1

    # --- Build the prompt section ---
    lines = []
    lines.append("## WHO USES THIS SOFTWARE — Occupation & Industry Context")
    lines.append("")
    lines.append(f"Data from occupation/industry analysis for **{canonical_name}**.")
    lines.append("")

    # Product summary
    if product_summary:
        lines.append("### Product Summary")
        lines.append(f"- **Categories**: {product_summary['categories']}")
        lines.append(f"- **Total Economic Footprint**: {product_summary['total_gdp']}")
        lines.append("")

    # Industries
    if industry_counter:
        lines.append("### Industries (SOC Major Groups) That Use This Software")
        lines.append("")
        for i, (grp, count) in enumerate(industry_counter.most_common(), 1):
            lines.append(f"{i}. **{grp}** — {count} occupations")
        lines.append("")

    # Top 10 occupations
    top_n = rows[:10]
    if top_n:
        lines.append("### Top 10 Occupations (by economic importance)")
        lines.append("")
        lines.append("| Occupation | Industry (SOC Group) | Importance | GDP ($) | Why They Use It |")
        lines.append("|------------|---------------------|-----------|---------|-----------------|")
        for r in top_n:
            occ = r.get("occupation_title", "")
            soc = r.get("soc_major_group", "")
            imp = r.get("onet_importance", "")
            gdp = r.get("product_gdp_usd", "")
            rationale = r.get("category_rationale", "")
            # Truncate long rationales
            if len(rationale) > 120:
                rationale = rationale[:117] + "..."
            try:
                gdp_fmt = f"{float(gdp):,.0f}"
            except Exception:
                gdp_fmt = gdp
            lines.append(f"| {occ} | {soc} | {imp} | {gdp_fmt} | {rationale} |")
        lines.append("")

    # Usage instructions
    lines.append("### How to Use This Data")
    lines.append("- Each task should target a SPECIFIC occupation from this list (or a related one)")
    lines.append("- Read the \"Why They Use It\" column — design tasks around these REAL workflows")
    lines.append("- Vary BOTH occupations AND industries across tasks for maximum diversity")
    lines.append("- The occupation and industry context should appear in the task's \"Real-world Context\" section")
    lines.append("- Don't cluster all tasks in the top 1-2 industries — spread across the full list")
    lines.append("")

    return "\n".join(lines)


DIVERSITY_STRATEGY = """
## TASK DIVERSITY STRATEGY

Follow this 3-step procedure to maximize task diversity:

### Step 1: Enumerate Human Activities
Before generating any task, brainstorm ALL the different things REAL HUMANS actually do with this software:
- WHO uses this software? (personas)
- WHAT are they trying to accomplish? (goals, not features)
- WHEN and WHY do they use it? (contexts)
- What PROBLEMS do they encounter? (pain points)
- What WORKFLOWS involve this software? (multi-step processes)

List at least 15-20 distinct human activity categories.

### Step 2: TRUE Random Category Selection
From your enumerated list, select ONE category completely at random:
- Do NOT pick the most obvious or common category
- Do NOT pick what seems easiest to verify
- Commit to your random selection even if it seems unusual

State clearly: "Randomly selected category: [X]"

### Step 3: Generate a Scenario-Based Task
Only NOW generate a task for the randomly selected category. Include:
- A realistic scenario/context (WHY is the user doing this?)
- The actual goal the user is trying to achieve
- Any relevant "messiness" from real-world usage
"""


TASK_QUALITY_GUIDELINES = """
## TASK QUALITY GUIDELINES

### 1. Include Human Context
Every task should have an implicit or explicit "why":
- A frustrated user needing help
- An urgent deadline
- A real workflow context

### 2. Embrace Real-World Messiness
Things go wrong in the real world. Include:
- Imperfect starting states
- Partially corrupted or incomplete data
- Settings that need adjustment

### 3. Consider User Personas
Vary between:
- Novice vs expert users
- Casual vs professional use
- One-time vs frequent users

### 4. Think About Workflow Context
Good tasks exist in a workflow:
- What happened before this task?
- What will the user do after?

### 5. Vary the Scope
Mix task sizes:
- Quick single-action tasks (2-3 steps)
- Medium multi-step tasks (5-10 steps)
- Complex workflow tasks (10+ steps)
"""


def get_task_generation_prompt_components(
    software_name: str,
    include_verification_strategy: bool = True,
    include_real_data: bool = True,
    include_anti_gaming: bool = True,
    include_diversity: bool = True,
    include_quality: bool = True,
    include_task_description_guidelines: bool = True,
    include_initial_state: bool = True,
    compact_mode: bool = False,
) -> str:
    """
    Assemble prompt components for task README generation (Step 1).

    Args:
        software_name: Name of the target software
        include_*: Flags to include/exclude specific sections
        compact_mode: If True, use compact summaries to save tokens

    Returns:
        Assembled prompt string
    """
    components = []

    components.append(f"""
# Task Generation for {software_name}

Your goal is to create creative, realistic, and verifiable task specifications.
""")

    # Task Description Quality (CRITICAL - add first)
    if include_task_description_guidelines:
        if compact_mode:
            components.append(get_compact_description_guidelines())
        else:
            components.append(TASK_DESCRIPTION_GUIDELINES)

    # Initial State Requirements
    if include_initial_state:
        if compact_mode:
            components.append(get_compact_initial_state_guidelines())
        else:
            components.append(INITIAL_STATE_REQUIREMENTS)

    # Real Data Requirements (comprehensive version)
    if include_real_data:
        if compact_mode:
            components.append(get_compact_data_guidelines())
        else:
            components.append(REAL_DATA_REQUIREMENTS_COMPREHENSIVE)

    if include_verification_strategy:
        components.append(VERIFICATION_STRATEGY_REQUIREMENTS)

    if include_anti_gaming:
        components.append(ANTI_GAMING_REQUIREMENTS)

    if include_diversity:
        components.append(DIVERSITY_STRATEGY)

    if include_quality:
        components.append(TASK_QUALITY_GUIDELINES)

    return "\n\n".join(components)


# =============================================================================
# FILE GENERATION PROMPT COMPONENTS (Step 2)
# =============================================================================

SCRIPT_GENERATION_INTRO = """
## Implementation File Generation

You will now create the actual implementation files for the task you designed.
Each task requires these files:

1. **task.json** - Task metadata and configuration
2. **README.md** - Full task specification (already designed)
3. **setup_task.sh** - Pre-task setup script (runs before agent starts)
4. **export_result.sh** - Post-task data export (runs after agent finishes)
5. **verifier.py** - Verification logic (runs on host machine)

Follow the patterns and guidelines below carefully.
"""


COPY_FROM_ENV_PATTERN = """
## CRITICAL: Use copy_from_env, NOT exec_in_env

The framework provides `copy_from_env` to read files from the container.
It does NOT provide `exec_in_env` to run commands.

### WRONG Pattern (will crash!)
```python
def verify_task(traj, env_info, task_info):
    exec_in_env = env_info.get('exec_in_env')  # May be None!
    result = exec_in_env("cat /tmp/result.txt")  # CRASH!
```

### CORRECT Pattern
```python
def verify_task(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    try:
        copy_from_env("/tmp/task_result.json", temp_file.name)
        with open(temp_file.name, 'r') as f:
            result = json.load(f)
    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

    # Now evaluate result...
```
"""


TASK_JSON_TEMPLATE = """
## task.json Template

```json
{
  "id": "<task_name>@1",
  "version": "1.0",
  "env_id": "<env_name>@0.1",
  "description": "Detailed description with enough info for agent to complete task...",
  "init": {
    "timeout_sec": 180,
    "max_steps": 30,
    "reward_type": "sparse"
  },
  "hooks": {
    "pre_task": "/workspace/tasks/<task_name>/setup_task.sh",
    "post_task": "/workspace/tasks/<task_name>/export_result.sh"
  },
  "metadata": {
    "expected_value1": "value1",
    "expected_value2": "value2"
  },
  "success": {
    "mode": "program",
    "spec": {
      "program": "verifier.py::verify_<task_name>"
    }
  }
}
```

### CRITICAL: Task Description
The `description` field MUST contain ALL information the agent needs:
- If verifier expects a specific filename → include it in description
- If verifier expects specific values → mention acceptable ranges
- A perfect agent following the description should pass verification
"""


SETUP_TASK_TEMPLATE = """
## setup_task.sh Template

```bash
#!/bin/bash
echo "=== Setting up task ==="

# Record initial state for verification
INITIAL_COUNT=$(some_query_command)
echo "$INITIAL_COUNT" > /tmp/initial_count.txt

# Record task start time (for anti-gaming timestamp checks)
date +%s > /tmp/task_start_time.txt

# Ensure application is in correct starting state
# - Focus correct window
# - Navigate to correct screen
# - Dismiss any dialogs

# For desktop apps: ensure window is maximized
DISPLAY=:1 wmctrl -r "AppName" -b add,maximized_vert,maximized_horz 2>/dev/null || true

echo "=== Task setup complete ==="
```
"""


EXPORT_RESULT_TEMPLATE = """
## export_result.sh Template

```bash
#!/bin/bash
echo "=== Exporting task results ==="

# Record task end time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

# Check if output file was created/modified during task
OUTPUT_PATH="/path/to/expected/output"
if [ -f "$OUTPUT_PATH" ]; then
    OUTPUT_MTIME=$(stat -c %Y "$OUTPUT_PATH" 2>/dev/null || echo "0")
    if [ "$OUTPUT_MTIME" -gt "$TASK_START" ]; then
        FILE_CREATED_DURING_TASK="true"
    else
        FILE_CREATED_DURING_TASK="false"
    fi
    OUTPUT_EXISTS="true"
    OUTPUT_SIZE=$(stat -c %s "$OUTPUT_PATH" 2>/dev/null || echo "0")
else
    OUTPUT_EXISTS="false"
    FILE_CREATED_DURING_TASK="false"
    OUTPUT_SIZE="0"
fi

# Check if application was running
APP_RUNNING=$(pgrep -f "AppName" > /dev/null && echo "true" || echo "false")

# Take final screenshot
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || true

# Create JSON result (use temp file for permission safety)
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "output_exists": $OUTPUT_EXISTS,
    "file_created_during_task": $FILE_CREATED_DURING_TASK,
    "output_size_bytes": $OUTPUT_SIZE,
    "app_was_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move to final location with permission handling
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="
```
"""


def get_file_generation_prompt_components(
    include_vlm_patterns: bool = True,
    include_errors: bool = True,
    include_scoring: bool = True,
    include_copy_pattern: bool = True,
    include_templates: bool = True,
    include_setup_patterns: bool = True,
    include_evidence: bool = True,
    include_task_json_guidelines: bool = True,
    compact_mode: bool = False,
) -> str:
    """
    Assemble prompt components for file generation (Step 2).

    Args:
        include_*: Flags to include/exclude specific sections
        compact_mode: If True, use compact summaries instead of full content

    Returns:
        Assembled prompt string
    """
    components = [SCRIPT_GENERATION_INTRO]

    if include_copy_pattern:
        components.append(COPY_FROM_ENV_PATTERN)

    # Setup Script Patterns (CRITICAL for task setup)
    if include_setup_patterns:
        components.append(SETUP_SCRIPT_PATTERNS)

    # Evidence Requirements (screenshots)
    if include_evidence:
        components.append(EVIDENCE_REQUIREMENTS)

    # task.json detailed requirements
    if include_task_json_guidelines:
        components.append(TASK_JSON_REQUIREMENTS)

    if include_vlm_patterns:
        if compact_mode:
            components.append(get_compact_vlm_summary())
        else:
            components.append("## VLM Verification Patterns\n\n" + VLM_PATTERNS_SUMMARY)

    if include_errors:
        if compact_mode:
            components.append(get_compact_errors_summary())
        else:
            components.append("## Common Errors to Avoid\n\n" + COMMON_ERRORS)

    if include_scoring:
        if compact_mode:
            components.append(get_compact_scoring_summary())
        else:
            components.append("## Multi-Criteria Scoring\n\n" + MULTI_CRITERIA_TEMPLATE)

    if include_templates:
        components.append(TASK_JSON_TEMPLATE)
        components.append(SETUP_TASK_TEMPLATE)
        components.append(EXPORT_RESULT_TEMPLATE)

    return "\n\n".join(components)


# =============================================================================
# ENVIRONMENT SPECIFICATION LOADING
# =============================================================================

def get_env_specification(env_folder: str, max_file_size: int = 10000) -> str:
    """
    Load environment specification files for prompt context.

    Args:
        env_folder: Path to environment folder
        max_file_size: Maximum size per file to include

    Returns:
        Formatted string with environment files
    """
    files_to_include = []

    # Collect relevant files
    patterns = [
        ('utils', '*.py'),
        ('scripts', '*.py'),
        ('scripts', '*.sh'),
        ('config', '*.json'),
        ('', 'README.md'),
        ('', 'env.json'),
    ]

    for subdir, pattern in patterns:
        search_path = os.path.join(env_folder, subdir, pattern) if subdir else os.path.join(env_folder, pattern)
        files_to_include.extend(glob(search_path))

    # Format files
    content = "## Environment Specification\n\n"
    content += f"Environment: {os.path.basename(env_folder)}\n\n"

    for filepath in files_to_include:
        if os.path.isfile(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    file_content = f.read()

                relative_path = filepath.replace(env_folder, '').strip('/')

                if len(file_content) > max_file_size:
                    file_content = file_content[:max_file_size] + "\n... [truncated]"

                content += f"""
<file name="{relative_path}">
{file_content.strip()}
</file>

"""
            except Exception:
                pass

    return content


# =============================================================================
# TASK OUTPUT FORMAT
# =============================================================================

TASK_README_OUTPUT_FORMAT = """
## Expected Output Format for Task README

Your output should be a complete task specification in markdown format:

```markdown
# {Task Title} (`{task_id}@{version}`)

## Overview
[2-3 sentences explaining what the task tests]

## Rationale
**Why this task is valuable:**
- [Skill 1 being tested]
- [Skill 2 being tested]
- [Skill 3 being tested]
- [Real-world relevance]

**Real-world Context:** [1-2 sentences about realistic user motivation]

## Task Description

**Goal:** [One clear sentence stating the objective]

**Starting State:** [What the agent sees when it starts]

**Expected Actions:**
1. [Step 1]
2. [Step 2]
3. [Step 3]
...

**Final State:** [What success looks like]

## Verification Strategy

### Primary Verification: [Method Name]
[Describe how the task will be verified programmatically]

### Secondary Verification: [Method Name]
[Describe backup/supplementary verification]

### Scoring System
| Criterion | Points | Description |
|-----------|--------|-------------|
| [Criterion 1] | X | [What earns these points] |
| [Criterion 2] | Y | [What earns these points] |
| ... | ... | ... |
| **Total** | **100** | |

Pass Threshold: [X] points with [key criteria] met
```
"""


TASK_FILES_OUTPUT_FORMAT = """
## Expected Output Format for Task Files

Output each file enclosed in code blocks with the filename:

```task.json
{
  "id": "task_name@1",
  ...
}
```

```setup_task.sh
#!/bin/bash
...
```

```export_result.sh
#!/bin/bash
...
```

```verifier.py
#!/usr/bin/env python3
...
```

CRITICAL: Ensure all files are complete and functional.
"""


# =============================================================================
# FULL PROMPT ASSEMBLY
# =============================================================================

def assemble_task_generation_prompt(
    software_name: str,
    env_folder: str,
    example_readmes: str,
    previous_tasks: Optional[List[str]] = None,
    compact_mode: bool = False,
) -> str:
    """
    Assemble the complete prompt for task README generation (Step 1).

    Args:
        software_name: Name of the target software
        env_folder: Path to environment folder
        example_readmes: Formatted example task READMEs
        previous_tasks: List of previously generated task names to avoid
        compact_mode: If True, use compact summaries to save tokens

    Returns:
        Complete prompt string
    """
    prompt_parts = []

    # Core guidelines (now includes task description, initial state, real data)
    prompt_parts.append(get_task_generation_prompt_components(
        software_name,
        compact_mode=compact_mode
    ))

    # Occupation & industry context from CSV data
    occupation_context = lookup_occupation_data(software_name)
    if occupation_context:
        prompt_parts.append(occupation_context)

    # Environment specification
    prompt_parts.append(get_env_specification(env_folder))

    # Example tasks
    prompt_parts.append(example_readmes)

    # Output format
    prompt_parts.append(TASK_README_OUTPUT_FORMAT)

    # Previous tasks (avoid duplicates)
    if previous_tasks:
        task_list = "\n".join(f"- {t}" for t in previous_tasks)
        prompt_parts.append(f"""
## Previously Generated Tasks (AVOID DUPLICATES)

The following tasks have already been generated. Do NOT create any task too similar to these:

{task_list}

Generate something meaningfully different from all of these. Do NOT reuse the same base task name with a different version suffix such as @2; a new version number is still a duplicate for this generation run.
""")

    return "\n\n---\n\n".join(prompt_parts)


def assemble_file_generation_prompt(
    example_implementations: str,
    compact_mode: bool = True,
) -> str:
    """
    Assemble the complete prompt for file generation (Step 2).

    Args:
        example_implementations: Formatted example task implementations
        compact_mode: If True, use compact summaries

    Returns:
        Complete prompt string
    """
    prompt_parts = []

    # Guidelines
    prompt_parts.append(get_file_generation_prompt_components(compact_mode=compact_mode))

    # Example implementations
    prompt_parts.append(example_implementations)

    # Output format
    prompt_parts.append(TASK_FILES_OUTPUT_FORMAT)

    return "\n\n---\n\n".join(prompt_parts)


if __name__ == "__main__":
    print("Prompt Components Module")
    print("=" * 50)
    print("\nFor Step 1 (Task README Generation):")
    print("  - get_task_generation_prompt_components(software_name)")
    print("  - assemble_task_generation_prompt(...)")
    print("\nFor Step 2 (File Generation):")
    print("  - get_file_generation_prompt_components()")
    print("  - assemble_file_generation_prompt(...)")
    print("\nUtility:")
    print("  - get_env_specification(env_folder)")
