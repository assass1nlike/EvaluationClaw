# Task Description Rewrite Guide

## Purpose

This document guides the systematic audit and rewriting of task descriptions in gym_anything environments. Task descriptions should be to-the-point statements that tell the agent WHAT to accomplish—not HOW to do it.

---

## Your Assignment

You are given a path to an environment (e.g., `benchmarks/cua_world/environments/google_earth_env`). Your job is to:

1. **Find all tasks** in `<env_path>/tasks/*/task.json`
2. **Audit each task description** against the criteria below
3. **Rewrite non-compliant descriptions** to follow the principles
4. **Update the task.json files** with the improved descriptions

---

## Evaluation Criteria

Rate each task description on these 4 criteria using: ✅ PASS, ⚠️ PARTIAL, ❌ FAIL

### 1. No Step-by-Step Instructions

**PASS**: No numbered steps, no procedural instructions
**PARTIAL**: Has some procedural hints but not explicit steps
**FAIL**: Contains numbered steps, explicit UI instructions, or procedural sequences

```
❌ FAIL (explicit steps):
"INSTRUCTIONS:
1. Navigate to the Mara River...
2. Locate the main crossing point...
3. Use the ruler/measure tool (Tools > Ruler)...
4. Create a placemark at the crossing location..."

❌ FAIL (procedural sequence):
"First, search for the location. Then, enable 3D buildings. Next, tilt the view.
After that, open the ruler tool..."

✅ PASS (goal only):
"Document the Mara River wildebeest crossing point with a placemark showing
the river width measurement."
```

### 2. Assumes Software Knowledge (No UI tutorials)

**PASS**: No menu paths, no keyboard shortcuts, no UI element references
**FAIL**: Explains menu navigation, keyboard shortcuts, mentions specific tool/button names, or how to use UI elements

```
❌ FAIL (UI tutorial):
"Use the ruler/measure tool (Tools > Ruler or Ctrl+Shift+R)"
"Add a new placemark (Add > Placemark or Ctrl+Shift+P)"
"Right-click the placemark in My Places and select 'Save Place As...'"
"use middle mouse button or tilt slider"
"Open Tools → Options and go to the '3D View' tab"

✅ PASS (assumes knowledge):
"Measure the building height using the 3D ruler"
"Create a placemark at the location"
"Export the placemark as KML"
```

### 3. Includes Output Path (When applicable)

**PASS**: Clear file path for any required outputs
**PARTIAL**: Mentions saving but path is vague
**FAIL**: No output path when task produces files

```
❌ FAIL (no path):
"Save the placemark to My Places"

⚠️ PARTIAL (vague):
"Export the results to a file on the Desktop"

✅ PASS (clear path):
"Export to /home/ga/Documents/measurement.kml"
"Save screenshot to ~/Documents/view.png"
```

### 4. No Expected Answers or Ground Truth (Critical!)

**PASS**: Description does NOT reveal expected measurements, values, or answers
**PARTIAL**: Minor hints that don't directly give away the answer
**FAIL**: Tells the agent what answer to expect (biases the measurement)

```
❌ FAIL (gives away the answer):
"Expected height: 320-480 meters"
"The river is typically 30-60 meters wide"
"The area should be approximately 116,000 square meters"
"actual height is 381m to roof, 443m to antenna tip"

❌ FAIL (biases the agent):
"Measure the building height (expected range: 380-450m)"

✅ PASS (no answer given):
"Measure the building height and record it in the description"
"Measure the river width at the crossing point"
"Measure the area of the building footprint"
```

**Why this matters:**
- If you tell the agent "expected: 320-480m", they can guess 400m without measuring
- A 160m tolerance range isn't testing measurement—it's testing "can you guess"
- The agent likely already knows famous building heights; don't confirm their prior knowledge
- Expected values belong ONLY in `metadata` for the verifier, NEVER in the description
- The agent should discover the answer by performing the task

**What IS okay to include:**
- **Location coordinates** (helps find the target): "Navigate to 40.7484°N, 73.9857°W"
- **Required names** (verified by system): "Name the placemark 'Empire State Building Height'"
- **Output paths** (verified by system): "Export to ~/Documents/result.kml"
- **Format requirements**: "Record in meters" or "Use decimal degrees"

---

## Rewriting Process

### Step 1: Read and Analyze

For each task.json:
1. Read the current `description` field
2. Score each of the 4 criteria
3. Identify specific violations

### Step 2: Create Analysis Grid

```
Task: <task_name>
Current description: "<full text>"

| Criterion | Rating | Issue |
|-----------|--------|-------|
| No steps | ❌/⚠️/✅ | <specific issue> |
| Assumes knowledge | ❌/⚠️/✅ | <specific issue> |
| Output path | ❌/⚠️/✅ | <specific issue> |
| No expected answers | ❌/⚠️/✅ | <specific issue> |

Verdict: PASS / NEEDS WORK / MAJOR REWRITE
```

### Step 3: Apply Rewrite Rules

**If PASS (all ✅):** No changes needed

**If NEEDS WORK (1-2 issues):** Minor edits to fix specific issues

**If MAJOR REWRITE (3+ issues):** Complete rewrite. You can use this template as a starting point:

```
[Action verb] [specific target/object] [at location with coordinates].
[Required output format/content]. [Save/Export to <exact path>].
```

### Step 4: Preserve Essential Information

When rewriting, KEEP:
- **Backstory and context** (personas, scenarios, domain context — these give the agent useful framing)
- Exact placemark/path names (these are verified)
- Location coordinates (to help find the target)
- Output file paths
- Required description text content
- Format requirements (e.g., "in meters", "decimal degrees")
- Credentials and login info

When rewriting, REMOVE:
- Numbered instruction lists
- Menu paths and keyboard shortcuts
- UI element explanations
- Procedural sequences ("First... Then... After that...")
- **Expected values, ranges, or ground truth** (e.g., "expected: 320-480m")
- Hints about what the answer should be (e.g., "typically 30-60 meters")

---

## Rewrite Templates

### Navigation Task
```
Navigate to [location] ([coordinates]). [Additional requirement if any].
```

### Measurement Task
```
Measure [what] at [location] ([coordinates]). Create a placemark named
'[exact name]' with the measurement in [units] in the description.
[Export to path if required].
```
**Note:** Do NOT include expected ranges or ground truth values!

### Placemark Creation Task
```
Create a placemark named '[exact name]' at [location] ([coordinates]).
[Icon/style requirements if any]. Description: '[required text]'.
Export to [path].
```

### Path/Route Task
```
Create a path named '[exact name]' from [start] ([coords]) to [end] ([coords]).
Description: '[required text]'. Export to [path].
```

### Import + Visualization Task
```
Import [file path], adjust view to show [what], and export image
(minimum [dimensions]) to [output path].
```

### Coordinate Documentation Task
```
Navigate to [location] ([coordinates]) and record coordinates in
[format(s)] to [output path].
```

---

## Examples: Before and After

### Example 1: Wildlife Corridor Crossing

**BEFORE (❌ Major violations):**
```
"You are a wildlife conservation biologist updating a database of critical
migration chokepoints in the Serengeti-Mara ecosystem. Document the main
wildebeest crossing point on the Mara River.

INSTRUCTIONS:
1. Navigate to the Mara River wildebeest crossing area in Kenya/Tanzania
   (approximate location: 1°29'S, 35°01'E)
2. Locate the main crossing point - look for where wildlife trails converge
   at the riverbanks
3. Use the ruler/measure tool (Tools > Ruler or Ctrl+Shift+R) to measure
   the river width at the crossing point in meters
4. Create a placemark at the crossing location:
   - Name: 'Mara River Crossing Point'
   - In the Description field, include the measured river width
5. Save the placemark to My Places
6. Right-click the placemark in My Places and select 'Save Place As...'
   to export as KML to: /home/ga/Documents/mara_crossing.kml
7. Save a screenshot to: /home/ga/Documents/mara_crossing_view.png

NOTE: The Mara River is typically 30-60 meters wide at crossing points."
```

**AFTER (✅ Compliant):**
```
"You are a wildlife conservation biologist updating a database of critical
migration chokepoints in the Serengeti-Mara ecosystem. Document the main
wildebeest crossing point on the Mara River (~1.48°S, 35.02°E). Measure
the river width at the crossing point and create a placemark named
'Mara River Crossing Point' with the width in meters in the description.
Export KML to /home/ga/Documents/mara_crossing.kml and screenshot to
/home/ga/Documents/mara_crossing_view.png"
```

### Example 2: Skyscraper Height Measurement

**BEFORE (❌ Major violations):**
```
"An architecture firm needs to verify building heights for a site analysis
project in Manhattan. Navigate to the Empire State Building in New York City
(search 'Empire State Building' or use coordinates 40.7484°N, 73.9857°W).
Enable the 3D Buildings layer in the Layers panel if not already enabled.
Tilt the view to see the building in 3D perspective (use middle mouse button
or tilt slider). Open the Ruler tool (Tools menu > Ruler, or press
Ctrl+Shift+R). Use the ruler in 3D/Line mode to measure from ground level
at the base to the top of the building. Create a placemark at the Empire
State Building location (Add > Placemark or Ctrl+Shift+P). Name the placemark
'Empire State Building Height' and in the description field, document the
measured height in meters. Expected height: 320-480 meters."
```

**AFTER (✅ Compliant):**
```
"An architecture firm needs to verify building heights for a site analysis
project in Manhattan. Measure the Empire State Building height (40.7484°N,
73.9857°W) from ground to top. Create a placemark named 'Empire State
Building Height' with the measured height in meters in the description."
```

### Example 3: Coordinate Format Documentation

**BEFORE (❌ Major violations):**
```
"Navigate to the summit of Mont Blanc (approximately 45.83°N, 6.87°E) and
document its precise coordinates in three different formats.

Your task:
1. Navigate to Mont Blanc summit using Search (Ctrl+F)
2. Position your view precisely on the summit peak
3. Open Tools → Options and go to the '3D View' tab
4. For each coordinate format, change the 'Show Lat/Long' dropdown and
   record the coordinates:
   - Decimal Degrees (e.g., 45.8326, 6.8652)
   - Degrees, Minutes, Seconds (e.g., 45°49'57\"N, 6°51'55\"E)
   - Universal Transverse Mercator (e.g., 32T 343500E 5078100N)
5. Create a text file at ~/Documents/mont_blanc_coordinates.txt containing
   all three coordinate representations"
```

**AFTER (✅ Compliant):**
```
"Navigate to Mont Blanc summit (45.83°N, 6.87°E) and document its coordinates
in three formats: Decimal Degrees, Degrees/Minutes/Seconds, and UTM. Save
all three with labels to ~/Documents/mont_blanc_coordinates.txt"
```

---

## Workflow Summary

```
For each task in <env_path>/tasks/*/task.json:
    1. Read task.json
    2. Extract description field
    3. Analyze against 4 criteria
    4. Create analysis grid
    5. Determine verdict: PASS / NEEDS WORK / MAJOR REWRITE
    6. If not PASS:
        a. Apply appropriate rewrite template
        b. Preserve required names, coordinates, paths
        c. Remove steps, UI instructions, expected answers
    7. Update task.json with new description
    8. Log the change (before/after)
```

---

## Important Notes

1. **Don't change metadata** - The `metadata` section contains expected values for verification. Only change the `description` field.

2. **Preserve exact names** - If a task requires a placemark named "Cambridge MA Research Point", keep that exact name in the rewrite.

3. **Keep coordinate tolerances** - If the original mentions "within 500 meters", preserve that tolerance.

4. **Output paths are sacred** - Never change output file paths; verifiers depend on them.

5. **Test the rewrite mentally** - Ask: "Could an agent who knows the software accomplish this task from just this description?" If yes, it's good.

6. **Keep it to the point** - The description can be as long as needed, but every sentence should serve a purpose. No length restriction, but no fluff either.

---

## Checklist Before Finishing

For each rewritten description, verify:

- [ ] No numbered steps or procedural sequences
- [ ] No menu paths or keyboard shortcuts
- [ ] No expected values, ranges, or ground truth revealed
- [ ] Clear output path(s) if task produces files
- [ ] Required names preserved from original
- [ ] Credentials and login info preserved (if present in original)
- [ ] Location coordinates included (to help find target)
- [ ] Description is to the point
