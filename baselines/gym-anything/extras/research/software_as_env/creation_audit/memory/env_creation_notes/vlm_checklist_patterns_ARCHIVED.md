# VLM Verification Patterns for GUI Agent Trajectories

## Overview

This document catalogs patterns for using Vision-Language Models (VLMs) to verify whether a GUI agent successfully completed a task. The key challenge is that trajectories can be very long (100s of steps), each consisting of a screenshot and agent action. We cannot show all images to the VLM due to context limits and cost, so we need smart verification strategies.

**Core Insight**: Patterns are differentiated by their **input/output structure**, not just question phrasing. The same underlying question ("was the task successful?") can be answered through many structurally different verification approaches.

**CRITICAL**: For a single task, more than one patterns SHOULD be used, and each of these pattern should be given an appropriate score. If total score crosses a predefined threshold (eg, score corresponding to 5-7/8 patterns), then the task is considered successful.

### USE THE FULL TRAJECTORY, NOT JUST THE FINAL SCREENSHOT

**This is the single most important principle for writing robust VLM verifiers.**

The verifier receives `traj` — the complete trajectory of (screenshot, action, output) tuples captured by the framework at every step. VLMs accept multiple images. **You should sample and send multiple trajectory frames**, not just the final screenshot.

Why this matters:
- **A single final screenshot is a snapshot. The trajectory is the story.** Verifying the story (the agent went through the process of loading data → configuring analysis → running it → getting results) is fundamentally more robust than verifying a snapshot (the final screen looks right).
- **Process verification is harder to fake.** An agent might arrange the final screen to look correct, but faking a convincing multi-frame progression through a complex scientific workflow is far more difficult.
- **GUI windows overlap.** In most desktop applications, later windows cover earlier ones. The final screenshot may only show the topmost window (e.g., a results table covering the image, or a plot covering the data). Trajectory frames from earlier steps show what's now hidden — the image with apertures, the configuration dialogs, the intermediate states.
- **Single-image patterns (Category A) are the weakest verification.** They should be combined with trajectory-based patterns (Categories B, C, F) for robust verification.

**Available tools** (from `gym_anything.vlm`):
- `sample_trajectory_frames(traj, n=5)` — sample N frames uniformly across the trajectory
- `get_final_screenshot(traj)` — last frame only (use as ONE input, not the ONLY input)
- `get_first_screenshot(traj)` — first frame (useful for before/after comparison)

**Example — weak vs. robust verification:**

```python
# WEAK: Single final screenshot only
screenshot = get_final_screenshot(traj)
result = query_vlm(image=screenshot, prompt="Does this show a completed analysis?")

# ROBUST: Multiple trajectory frames showing the process
frames = sample_trajectory_frames(traj, n=6)
first = get_first_screenshot(traj)
last = get_final_screenshot(traj)
result = query_vlm(
    images=[first] + frames + [last],
    prompt="""These images show an agent's progression through an analysis task.
    Image 1: Initial state. Images 2-7: Sampled during work. Image 8: Final state.
    Did the agent go through the expected workflow stages?
    1. Data loaded and visible?
    2. Configuration/setup performed?
    3. Analysis executed?
    4. Results visible in final state?"""
)
```

## Index: Pattern Quick Reference

| # | Name | Input | Output | Best For |
|---|------|-------|--------|----------|
| 1 | Final Screenshot Binary | 1 image | bool | Quick pass/fail |
| 2 | Final State Checklist | 1 image + list | checklist | Multi-requirement |
| 3 | Value Extraction | 1 image + expected | value + match | Numeric results |
| 4 | Final State Negative | 1 image + errors | violations | Catching failures |
| 5 | First-Last Transformation | 2 images | transformation | Verifying change |
| 6 | Expected vs Actual | 2 images | similarity | Gold standard comparison |
| 7 | Incremental Progress | N images | per-interval progress | Long tasks |
| 8 | Action-Triggered Pull | text → images | action verification | Specific actions |
| 9 | Error Investigation | text → images | error + recovery | Robustness |
| 10 | Milestone Checkpoint | text → images | milestone status | Multi-step tasks |
| 11 | Claim Grounding | claims + images | evidence check | Hallucination detection |
| 12 | Tool Usage | images | tool audit | Methodology |
| 13 | Parameter Verification | images | setting check | Configuration |
| 14 | Prerequisite Chain | text | order check | Dependencies |
| 15 | Guessing Detection | text + images | guess probability | Catching shortcuts |
| 16 | Loop Detection | image sequence | loop assessment | Stuck detection |
| 17 | Confidence Calibration | text + images | calibration | Overconfidence |
| 18 | Destructive Action | before/after | damage assessment | Mistake detection |
| 19 | Uniform Sampling | N images | overview | General assessment |
| 20 | Keyframe Sampling | change images | transition quality | Key moments |
| 21 | Phase Sampling | phase images | phase completion | Structured tasks |
| 22 | Multi-Region Consistency | region crops | consistency | Complex UIs |
| 23 | Cross-Turn Consistency | same region × time | stability | Setting drift |
| 24 | Instruction Alignment | result + instructions | compliance | Nothing forgotten |
| 25 | Segmentation Quality | overlay image | quality score | Medical imaging |
| 26 | Light Curve Validity | plot image | validity | Astronomy |
| 27 | Network Verification | network image | structure check | Bioinformatics |
| 28 | CAD Verification | model views | completeness | Engineering |
| 29 | Form Verification | document image | completeness | Data entry |
| 30 | Code Output Verification | terminal image | success check | Development |

---

## Trajectory Structure

```
Trajectory = [
    (screenshot_0, action_0, agent_output_0),
    (screenshot_1, action_1, agent_output_1),
    ...
    (screenshot_N, action_N, agent_output_N)
]
```

**Constraints**:
- Text (actions + outputs) can usually be included in full
- Images must be selectively sampled (typically 1-20 images max)
- Selection strategy is pattern-dependent

**Key point**: Every verifier receives the full trajectory. The trajectory screenshots are captured by the **framework** (external to the container), so the agent cannot tamper with them. This makes trajectory-based VLM verification an independent channel from any programmatic checks that rely on data from inside the container (files, API state, window lists).

---

## Pattern Catalog

### Category A: Terminal State Patterns

These patterns focus on the final state, ignoring the journey. **They are the weakest category** — use them as lightweight supplements to trajectory-based patterns (Categories B, C, F), not as the primary verification.

---

#### Pattern 1: Final Screenshot Binary

**Input**: Last screenshot only
**Output**: Binary (yes/no)
**Query**: "Is the task complete based on this final state?"

```yaml
pattern: final_screenshot_binary
input:
  images: [screenshot_N]  # Last image only
  text: null
output:
  type: binary
  format: {"complete": true/false}

example_query: |
  Task: "Segment the brain tumor in 3D Slicer"

  Looking at this screenshot, is there a visible tumor segmentation
  (colored region overlaid on the brain scan)?

  Answer YES or NO.
```

**Best for**: Simple pass/fail verification where final state is sufficient
**Limitations**: Misses methodology errors, may miss subtle failures

---

#### Pattern 2: Final State Checklist

**Input**: Last screenshot + checklist of required elements
**Output**: Structured (which items present/absent)
**Query**: "Which of these elements are visible in the final state?"

```yaml
pattern: final_state_checklist
input:
  images: [screenshot_N]
  text: checklist_items
output:
  type: structured
  format: {"item_1": true/false, "item_2": true/false, ...}

example_query: |
  Task: "Create exoplanet transit analysis in AstroImageJ"

  Check this final screenshot for the following elements:
  1. Light curve plot visible?
  2. Transit dip visible in the curve?
  3. Fitted model overlaid (smooth curve)?
  4. Transit depth value displayed?
  5. Comparison stars marked in aperture window?

  Return JSON: {"light_curve": bool, "transit_dip": bool,
                "fitted_model": bool, "depth_shown": bool,
                "comparisons_marked": bool}
```

**Best for**: Multi-requirement tasks with clear visual indicators
**Limitations**: Doesn't verify correctness, only presence

---

#### Pattern 3: Value Extraction from Final State

**Input**: Last screenshot + location hint + expected value
**Output**: Extracted value + match assessment
**Query**: "What value is displayed at [location]? Does it match [expected]?"

```yaml
pattern: value_extraction_final
input:
  images: [screenshot_N]
  text:
    location: "transit depth field in results panel"
    expected_value: "1.43%"
    tolerance: "0.15%"
output:
  type: structured
  format: {"extracted": string, "matches": bool, "difference": float}

example_query: |
  Look at the results panel in this AstroImageJ screenshot.

  1. What is the displayed transit depth value?
  2. The expected value is 1.43% ± 0.15%
  3. Does the displayed value fall within this range?

  Return: {"extracted": "X.XX%", "matches": true/false, "difference": X.XX}
```

**Best for**: Numeric result verification
**Limitations**: Requires VLM to accurately read numbers (can be error-prone)

---

#### Pattern 4: Final State Negative Check

**Input**: Last screenshot + list of things that should NOT be present
**Output**: List of violations found
**Query**: "Are any of these error conditions visible?"

```yaml
pattern: final_state_negative
input:
  images: [screenshot_N]
  text: error_conditions
output:
  type: list
  format: ["violation_1", "violation_2"] or []

example_query: |
  Check this final screenshot for any of these problems:
  1. Error dialog or warning popup visible
  2. "NaN" or "Infinity" in any numeric fields
  3. Empty plot area (no data displayed)
  4. Red error highlighting in any panel
  5. "Failed" or "Error" text anywhere

  List any violations found, or return empty list if clean.
```

**Best for**: Catching failures the agent didn't report
**Limitations**: May miss subtle errors not in the list

---

### Category B: Before-After Comparison Patterns

These patterns compare initial and final states to verify transformation. **Significantly more robust than Category A** because they prove something changed — an agent that did nothing will fail a before/after comparison even if the final state happens to look plausible.

---

#### Pattern 5: First-Last Transformation Verification

**Input**: First screenshot + last screenshot
**Output**: Transformation description + success rating
**Query**: "Describe what changed and whether it matches the intended task"

```yaml
pattern: first_last_transformation
input:
  images: [screenshot_0, screenshot_N]
  text: task_description
output:
  type: structured
  format: {"transformation": string, "matches_intent": bool, "confidence": 0-10}

example_query: |
  Task: "Segment the liver tumor and create a 3D visualization"

  Image 1: Initial state (before agent started)
  Image 2: Final state (after agent finished)

  1. Describe the transformation that occurred
  2. Does this transformation match the intended task?
  3. Rate your confidence (0-10)
```

**Best for**: Verifying meaningful change occurred
**Limitations**: Doesn't verify intermediate methodology

---

#### Pattern 6: Expected vs Actual Comparison

**Input**: Agent's final screenshot + reference image of correct result
**Output**: Similarity assessment + specific differences
**Query**: "How well does the agent's result match the reference?"

```yaml
pattern: expected_vs_actual
input:
  images: [agent_result, reference_result]
  text: comparison_criteria
output:
  type: structured
  format: {"similarity_score": 0-100, "matches": bool,
           "differences": [string], "critical_differences": [string]}

example_query: |
  Compare the agent's segmentation result (Image 1) with the
  ground truth expert segmentation (Image 2).

  1. Overall similarity score (0-100)
  2. List any differences in boundary placement
  3. Are there any CRITICAL differences (missed regions, wrong structure)?

  A result is acceptable if similarity > 80 and no critical differences.
```

**Best for**: Precise verification against gold standard
**Limitations**: Requires reference image to be available

---

#### Pattern 7: Incremental Progress Verification

**Input**: Consecutive image pairs at key intervals
**Output**: Progress assessment per interval
**Query**: "Did meaningful progress occur between each pair?"

```yaml
pattern: incremental_progress
input:
  images: [img_0, img_25, img_50, img_75, img_100]  # Percentage points
  text: expected_milestones
output:
  type: structured
  format: {"0_to_25": {progress: bool, description: str}, ...}

example_query: |
  These images show the agent's progress at 0%, 25%, 50%, 75%, 100%.

  For each interval, assess:
  1. Did meaningful progress occur?
  2. What specifically changed?
  3. Is the agent on track for the goal?

  Expected milestones:
  - 25%: Data loaded, initial exploration
  - 50%: Analysis started, some results visible
  - 75%: Main analysis complete
  - 100%: Final results with verification
```

**Best for**: Long tasks where incremental progress matters
**Limitations**: Requires good milestone definitions

---

### Category C: Text-Guided Image Selection Patterns

These patterns use text analysis first to identify which images to examine. **These are among the most powerful patterns** because they use the trajectory text to pinpoint exactly which frames to verify, then visually confirm specific actions happened.

---

#### Pattern 8: Action-Triggered Image Pull

**Input**: Full text trajectory → identify key action → pull surrounding images
**Output**: Verification of that action's execution
**Query Two-Stage**:
1. "On which turn did action X occur?"
2. "Looking at that turn's image, was X executed correctly?"

```yaml
pattern: action_triggered_pull
stage_1:
  input:
    text: full_trajectory_text
  query: "On which turn number did the agent perform [action]?"
  output:
    type: numeric
    format: turn_number

stage_2:
  input:
    images: [screenshot_{turn-1}, screenshot_{turn}, screenshot_{turn+1}]
  query: "Was [action] executed correctly? What was the result?"
  output:
    type: structured
    format: {"executed_correctly": bool, "result": string}

example:
  stage_1_query: |
    Read through this trajectory of agent actions.
    On which turn did the agent "run multi-aperture photometry"?
    Return the turn number.

  stage_2_query: |
    These are screenshots before, during, and after the agent
    ran multi-aperture photometry (turn 47).

    1. Was the photometry executed (results visible in after image)?
    2. Were apertures placed on multiple stars?
    3. Did a light curve appear?
```

**Best for**: Verifying specific critical actions
**Limitations**: Requires action to be identifiable in text

---

#### Pattern 9: Error-Triggered Investigation

**Input**: Full text trajectory → find error mentions → pull error images
**Output**: Error analysis and recovery assessment
**Query Two-Stage**:
1. "Were any errors mentioned? Which turns?"
2. "What was the error and did the agent recover?"

```yaml
pattern: error_triggered_investigation
stage_1:
  input:
    text: full_trajectory_text
  query: "Identify any turns where errors, failures, or problems occurred"
  output:
    type: list
    format: [{"turn": N, "error_type": string}]

stage_2:
  input:
    images: [error_screenshot, subsequent_screenshots...]
  query: "Analyze the error and recovery"
  output:
    type: structured
    format: {"error_description": string, "recovered": bool,
             "recovery_method": string}

example:
  stage_1_query: |
    Scan this trajectory for any mentions of:
    - Error messages
    - Failed operations
    - Unexpected results
    - Agent expressing confusion

    Return list of {turn, error_type} for each issue found.

  stage_2_query: |
    Turn 23 shows an error occurred. These images show:
    - Image 1: State when error occurred
    - Image 2-4: Subsequent states

    1. What was the error?
    2. Did the agent successfully recover?
    3. How did they recover (or fail to)?
```

**Best for**: Robustness verification, error handling assessment
**Limitations**: May miss silent failures not mentioned in text

---

#### Pattern 10: Milestone Checkpoint Verification

**Input**: Text trajectory → identify milestone claims → verify each visually
**Output**: Milestone achievement verification
**Query Two-Stage**:
1. "When did the agent claim to complete each milestone?"
2. "Does the image support each milestone claim?"

```yaml
pattern: milestone_checkpoint
stage_1:
  input:
    text: full_trajectory_text
    milestones: ["loaded data", "selected targets", "ran analysis", "exported results"]
  query: "For each milestone, identify the turn where agent claimed completion"
  output:
    type: dict
    format: {"milestone": turn_number}

stage_2:
  input:
    images: [screenshot_at_each_milestone]
    milestone_criteria: {milestone: visual_requirements}
  query: "Verify each milestone was actually achieved"
  output:
    type: dict
    format: {"milestone": {"claimed": turn, "verified": bool}}

example:
  milestones:
    - name: "data_loaded"
      visual_criteria: "Image stack visible in main panel"
    - name: "apertures_placed"
      visual_criteria: "Circular apertures visible on stars"
    - name: "photometry_complete"
      visual_criteria: "Light curve plot displayed"
    - name: "transit_fitted"
      visual_criteria: "Model curve overlaid on data points"
```

**Best for**: Multi-step tasks with clear milestones
**Limitations**: Requires well-defined milestone criteria

---

#### Pattern 11: Claim Grounding Verification

**Input**: Agent's specific claims + corresponding images
**Output**: Whether each claim is supported by visual evidence
**Query**: "Does the image support the agent's claim?"

```yaml
pattern: claim_grounding
input:
  claims: [
    {"turn": 45, "claim": "Transit depth is 1.43%", "image": screenshot_45},
    {"turn": 67, "claim": "Planet radius is 1.8 Jupiter radii", "image": screenshot_67}
  ]
output:
  type: list
  format: [{"claim": string, "supported": bool, "evidence": string}]

example_query: |
  The agent made these claims during the trajectory:

  Claim 1 (Turn 45): "The transit depth is 1.43%"
  [Image 1]

  Claim 2 (Turn 67): "The planet radius is 1.8 Jupiter radii"
  [Image 2]

  For each claim:
  1. Is there visible evidence supporting this claim in the image?
  2. What specific element shows this value?
  3. Or is the agent stating this without visual evidence (possible hallucination)?
```

**Best for**: Detecting hallucinations and unsupported claims
**Limitations**: Requires extracting claims from trajectory

---

### Category D: Methodology Audit Patterns

These patterns verify HOW the agent solved the task, not just the result.

---

#### Pattern 12: Tool Usage Verification

**Input**: Images around tool usage + expected tool workflow
**Output**: Whether correct tools were used correctly
**Query**: "Did the agent use the appropriate tools in the correct way?"

```yaml
pattern: tool_usage_verification
input:
  images: tool_usage_images  # Selected based on text analysis
  expected_tools: ["Segment Editor", "Grow from Seeds", "Threshold"]
  expected_sequence: "Threshold → Grow from Seeds → Manual refinement"
output:
  type: structured
  format: {"tools_used": [string], "sequence_correct": bool,
           "usage_correct": bool, "issues": [string]}

example_query: |
  This task required segmentation using 3D Slicer's Segment Editor.

  Expected workflow:
  1. Use Threshold tool to get initial boundary
  2. Use "Grow from Seeds" to refine
  3. Manual brush cleanup if needed

  Looking at these images of the agent's tool usage:
  1. Which tools were actually used?
  2. Was the sequence appropriate?
  3. Were the tools used correctly?
  4. Any concerning usage patterns?
```

**Best for**: Verifying methodology, not just outcome
**Limitations**: Requires knowledge of correct workflow

---

#### Pattern 13: Parameter/Setting Verification

**Input**: Images showing parameter panels + expected settings
**Output**: Whether parameters are appropriate
**Query**: "Are the configured parameters reasonable for this task?"

```yaml
pattern: parameter_verification
input:
  images: [parameter_panel_screenshots]
  expected_ranges: {
    "aperture_radius": {"min": 8, "max": 20, "unit": "pixels"},
    "inner_annulus": {"min": 20, "max": 40, "unit": "pixels"},
    "outer_annulus": {"min": 30, "max": 60, "unit": "pixels"}
  }
output:
  type: structured
  format: {"parameter": {"value": X, "in_range": bool}}

example_query: |
  For exoplanet photometry, aperture settings should be:
  - Aperture radius: 8-20 pixels (roughly 2-4x FWHM)
  - Inner annulus: 20-40 pixels
  - Outer annulus: 30-60 pixels

  Looking at this aperture settings panel:
  1. What are the actual values set?
  2. Are they within reasonable ranges?
  3. Any red flags (e.g., aperture larger than annulus)?
```

**Best for**: Catching configuration errors
**Limitations**: Requires domain knowledge of appropriate settings

---

#### Pattern 14: Prerequisite Chain Verification

**Input**: Text trajectory + ordered prerequisite list
**Output**: Whether prerequisites were completed in order
**Query**: "Were required steps completed in the correct order?"

```yaml
pattern: prerequisite_chain
input:
  text: full_trajectory_text
  chain: ["load_data", "calibrate", "select_target", "run_analysis", "fit_model"]
  strict_order: true
output:
  type: structured
  format: {"chain_complete": bool, "order_correct": bool,
           "missing_steps": [string], "order_violations": [string]}

example_query: |
  This analysis requires steps in this order:
  1. Load FITS images
  2. Plate solve (get coordinates)
  3. Select target and comparison stars
  4. Run differential photometry
  5. Fit transit model

  Analyze this trajectory:
  - Were all steps completed?
  - Were they in the correct order?
  - Were any steps skipped or done out of order?
```

**Best for**: Complex workflows with dependencies
**Limitations**: May be overly strict if order flexibility is acceptable

---

### Category E: Behavioral Pattern Detection

These patterns detect concerning agent behaviors.

---

#### Pattern 15: Guessing Detection

**Input**: Agent's reasoning text + final answer + supporting images
**Output**: Whether answer appears derived vs guessed
**Query**: "Did the agent derive this answer from evidence, or guess?"

```yaml
pattern: guessing_detection
input:
  text: agent_reasoning_for_answer
  images: [images_around_answer_derivation]
  final_answer: agent_final_answer
output:
  type: structured
  format: {"likely_guessed": bool, "confidence": 0-100, "evidence": string}

indicators_of_guessing:
  - Answer appears suddenly without shown work
  - High confidence without visible verification
  - Answer doesn't match what's visible on screen
  - Agent didn't interact with relevant tools
  - Reasoning contains phrases like "should be about", "typically is"

example_query: |
  The agent's final answer was: "Transit depth is 1.43%"

  Here is their reasoning leading to this answer:
  [Agent's text output]

  Here are screenshots around when they gave this answer:
  [Images]

  Assessment:
  1. Is this value visibly displayed somewhere?
  2. Did the agent perform calculations/measurements to derive it?
  3. Or does this appear to be guessed/assumed?
  4. What's your confidence that this was legitimately derived (0-100)?
```

**Best for**: Catching hallucinations and lazy shortcuts
**Limitations**: Sophisticated guessing may be hard to detect

---

#### Pattern 16: Loop/Thrashing Detection

**Input**: Sequence of images sampled during potential loop
**Output**: Whether agent was stuck in unproductive loop
**Query**: "Is the agent repeating the same actions without progress?"

```yaml
pattern: loop_detection
input:
  images: [img_t, img_t+5, img_t+10, img_t+15, img_t+20]  # Sampled sequence
  text: actions_in_range
output:
  type: structured
  format: {"looping": bool, "loop_type": string, "iterations": int}

loop_types:
  - "retry_same_failed_action": Repeating action that keeps failing
  - "undo_redo_cycle": Making then reverting changes
  - "navigation_loop": Going back and forth in UI
  - "stuck_no_action": Long period with no meaningful action

example_query: |
  These 5 images span turns 40-60 of the trajectory.

  The agent's actions during this period:
  [Action list]

  Assessment:
  1. Are these images essentially the same (no progress)?
  2. Is the agent repeating failed actions?
  3. Is there an undo-redo cycle?
  4. If looping, how many iterations?
```

**Best for**: Catching stuck agents, detecting need for intervention
**Limitations**: Some repetition is normal (legitimate retries)

---

#### Pattern 17: Confidence Calibration Check

**Input**: Agent's stated confidence + final result image
**Output**: Whether confidence matches visible quality
**Query**: "Is the agent's confidence justified by the result?"

```yaml
pattern: confidence_calibration
input:
  agent_confidence: "I am highly confident this segmentation is accurate"
  confidence_score: 95  # If numeric
  images: [final_result_image]
output:
  type: structured
  format: {"confidence_justified": bool, "actual_quality": 0-100,
           "calibration_error": float}

example_query: |
  The agent stated: "I am 95% confident this segmentation is correct"

  [Final segmentation image]

  Assessment:
  1. What is the apparent quality of this result? (0-100)
  2. Is the agent's confidence of 95% justified?
  3. Is the agent overconfident, underconfident, or well-calibrated?
```

**Best for**: Catching overconfident failures
**Limitations**: VLM's quality assessment may itself be miscalibrated

---

#### Pattern 18: Destructive Action Detection

**Input**: Before/after images around potentially destructive actions
**Output**: Whether important work was destroyed
**Query**: "Did the agent accidentally delete or overwrite important work?"

```yaml
pattern: destructive_action_detection
input:
  images: [before_action, after_action]
  action_taken: "Clear all segments"
output:
  type: structured
  format: {"destructive": bool, "what_lost": string, "recoverable": bool}

example_query: |
  The agent performed: "Clear all segments"

  Image 1: Before the action
  Image 2: After the action

  Assessment:
  1. Was important work lost?
  2. What specifically was destroyed?
  3. Was this intentional (starting over) or accidental?
```

**Best for**: Catching mistakes that undo progress
**Limitations**: Intentional resets may be flagged incorrectly

---

### Category F: Sampling Strategy Patterns

These patterns define how to select images from long trajectories. **Use these to feed multiple trajectory frames to the VLM.** They are the practical mechanism for trajectory-based verification — Patterns 19-21 define the sampling strategy, then you pair them with assessment patterns from other categories.

---

#### Pattern 19: Uniform Temporal Sampling

**Input**: N images sampled uniformly across trajectory
**Output**: Overall trajectory assessment
**Query**: "Based on this sample, assess overall task execution"

```yaml
pattern: uniform_sampling
sampling:
  method: uniform
  count: 10
  formula: "indices = [0, N/10, 2N/10, ..., N]"
input:
  images: [10 uniformly sampled images]
  text: trajectory_summary
output:
  type: structured
  format: {"phases_completed": [string], "overall_progress": 0-100,
           "quality_assessment": string}

example_query: |
  These 10 images are sampled uniformly from a 100-step trajectory.

  [Image 1: Step 0] [Image 2: Step 10] ... [Image 10: Step 100]

  Based on this sample:
  1. What phases of work are visible?
  2. Does the trajectory show consistent progress?
  3. Overall assessment of task completion?
```

**Best for**: General trajectory overview
**Limitations**: May miss important events between samples

---

#### Pattern 20: Change-Based Keyframe Sampling

**Input**: Images selected where significant visual changes occurred
**Output**: Assessment of key transitions
**Query**: "Assess each significant change point"

```yaml
pattern: keyframe_sampling
sampling:
  method: visual_difference
  threshold: "significant change detected"
  max_frames: 15
input:
  images: keyframe_images
  change_descriptions: [what_changed_at_each_keyframe]
output:
  type: list
  format: [{"keyframe": N, "change": string, "appropriate": bool}]

example_query: |
  These images represent significant visual changes in the trajectory:

  Keyframe 1 (turn 5): Data loaded
  [Image]

  Keyframe 2 (turn 23): Apertures placed
  [Image]

  Keyframe 3 (turn 45): Light curve appeared
  [Image]

  For each transition, was it a meaningful step toward the goal?
```

**Best for**: Focus on important moments, skip static periods
**Limitations**: Requires change detection preprocessing

---

#### Pattern 21: Phase-Based Sampling

**Input**: One representative image from each task phase
**Output**: Per-phase verification
**Query**: "Verify each phase was completed correctly"

```yaml
pattern: phase_sampling
phases:
  - name: "Setup"
    expected_end_state: "Data loaded, UI configured"
  - name: "Analysis"
    expected_end_state: "Primary analysis complete"
  - name: "Verification"
    expected_end_state: "Results verified and exported"
sampling:
  method: "one image per phase"
  selection: "last image where agent was in each phase"
output:
  type: dict
  format: {"phase_name": {"completed": bool, "quality": 0-10}}
```

**Best for**: Structured tasks with clear phases
**Limitations**: Requires phase definitions and detection

---

### Category G: Comparative and Consistency Patterns

---

#### Pattern 22: Multi-Region Consistency Check

**Input**: Multiple crops/regions from the same final screenshot
**Output**: Whether different parts of the result are consistent
**Query**: "Are all parts of the result internally consistent?"

```yaml
pattern: multi_region_consistency
input:
  regions: [
    {"name": "main_view", "crop": [0, 0, 800, 600]},
    {"name": "results_panel", "crop": [800, 0, 400, 300]},
    {"name": "status_bar", "crop": [0, 580, 1200, 20]}
  ]
output:
  type: structured
  format: {"consistent": bool, "inconsistencies": [string]}

example_query: |
  These are three regions from the final screenshot:

  Region 1: Main visualization (segmentation overlay)
  Region 2: Statistics panel (volume, surface area)
  Region 3: Status bar (current state messages)

  Check for consistency:
  1. Do the statistics match what's visible in the visualization?
  2. Does the status bar indicate successful completion?
  3. Any contradictions between regions?
```

**Best for**: Complex UIs with multiple information sources
**Limitations**: Requires knowing which regions to compare

---

#### Pattern 23: Cross-Turn Consistency

**Input**: Same UI region across multiple turns
**Output**: Whether information remained consistent
**Query**: "Did critical values remain stable across the session?"

```yaml
pattern: cross_turn_consistency
input:
  images: [same_region_at_turn_10, _turn_30, _turn_50, _turn_70]
  tracked_element: "target star coordinates"
output:
  type: structured
  format: {"stable": bool, "changes": [{"turn": N, "from": X, "to": Y}]}

example_query: |
  These images show the target coordinates panel at different turns.
  The coordinates should NOT change during analysis.

  [Turn 10] [Turn 30] [Turn 50] [Turn 70]

  1. Are the coordinates the same in all images?
  2. If they changed, when and how?
  3. Would this change invalidate the analysis?
```

**Best for**: Detecting unintended drift in settings
**Limitations**: Requires knowing what should stay constant

---

#### Pattern 24: Output-Instruction Alignment

**Input**: Original task instructions + final result image(s)
**Output**: Point-by-point instruction compliance
**Query**: "Does the result satisfy each instruction requirement?"

```yaml
pattern: instruction_alignment
input:
  instructions: original_task_text
  images: [final_result_images]
output:
  type: checklist
  format: [{"requirement": string, "satisfied": bool, "evidence": string}]

example_query: |
  Original instructions:
  "Segment the tumor, measure its volume, calculate distance to
   nearest vessel, and export a 3D visualization."

  [Final screenshot(s)]

  Requirement-by-requirement check:
  1. "Segment the tumor" - Is a tumor segmentation visible?
  2. "Measure its volume" - Is a volume measurement displayed?
  3. "Calculate distance to nearest vessel" - Is this measurement shown?
  4. "Export a 3D visualization" - Is a 3D view visible/exported?
```

**Best for**: Ensuring nothing was forgotten
**Limitations**: Requires parseable instructions

---

### Category H: Domain-Specific Patterns

---

#### Pattern 25: Segmentation Quality Assessment

**Domain**: Medical imaging (3D Slicer, ITK-SNAP)
**Input**: Segmentation overlay image + optional reference
**Output**: Quality assessment of segmentation

```yaml
pattern: segmentation_quality
input:
  images: [segmentation_overlay_image]
  reference: optional_ground_truth_overlay
  structure: "liver tumor"
output:
  type: structured
  format: {"quality_score": 0-100, "issues": [string],
           "boundary_quality": string, "coverage": string}

example_query: |
  This shows a tumor segmentation (colored region) overlaid on CT scan.

  Assess the segmentation quality:
  1. Does the boundary follow the actual tumor edge?
  2. Is the entire tumor covered (no missing regions)?
  3. Is there over-segmentation (includes non-tumor)?
  4. Rate overall quality 0-100
  5. List specific issues if any
```

---

#### Pattern 26: Light Curve Validity Assessment

**Domain**: Astronomy (AstroImageJ, EXOTIC)
**Input**: Light curve plot image
**Output**: Assessment of data quality and transit detection

```yaml
pattern: lightcurve_validity
input:
  images: [lightcurve_plot]
  expected: {"transit": true, "depth": "~1.4%", "duration": "~3 hours"}
output:
  type: structured
  format: {"valid_lightcurve": bool, "transit_visible": bool,
           "data_quality": 0-10, "issues": [string]}

example_query: |
  This is a light curve plot from exoplanet transit observations.

  Assess:
  1. Is this a valid light curve (flux vs time, reasonable scatter)?
  2. Is a transit dip visible?
  3. Approximate transit depth (by eye)?
  4. Data quality issues (large scatter, gaps, systematics)?
  5. Does the fitted model (if shown) look reasonable?
```

---

#### Pattern 27: Network Diagram Verification

**Domain**: Bioinformatics (Cytoscape), Systems design
**Input**: Network/graph visualization
**Output**: Structural correctness assessment

```yaml
pattern: network_verification
input:
  images: [network_diagram]
  expected_properties: {
    "node_count_range": [50, 200],
    "should_be_connected": true,
    "hub_nodes_expected": true
  }
output:
  type: structured
  format: {"looks_valid": bool, "node_estimate": int,
           "is_connected": bool, "has_structure": bool}

example_query: |
  This is a protein interaction network from Cytoscape.

  Assess:
  1. Does this appear to be a valid network (not empty/broken)?
  2. Approximate number of nodes?
  3. Does it appear to be connected (one component) or fragmented?
  4. Are there visible hub nodes (highly connected)?
  5. Is appropriate coloring/labeling applied?
```

---

#### Pattern 28: CAD Model Verification

**Domain**: Engineering (SolidWorks, AutoCAD, Fusion360)
**Input**: 3D model view(s)
**Output**: Geometric/design correctness

```yaml
pattern: cad_verification
input:
  images: [model_view_1, model_view_2]  # Different angles
  specifications: {"must_have": ["hole pattern", "chamfered edges"]}
output:
  type: structured
  format: {"complete": bool, "features_present": [string],
           "features_missing": [string], "quality_issues": [string]}

example_query: |
  These two views show a CAD model created by the agent.

  Required features:
  - Rectangular base plate
  - 4x mounting holes in corners
  - Central raised boss
  - Chamfered edges

  Verify:
  1. Are all required features present?
  2. Does the geometry look correct (no obvious errors)?
  3. Are there any quality issues (non-manifold, gaps)?
```

---

#### Pattern 29: Form/Document Verification

**Domain**: Office software, data entry
**Input**: Final form/document screenshot
**Output**: Completeness and correctness check

```yaml
pattern: form_verification
input:
  images: [completed_form]
  required_fields: ["name", "date", "signature", "calculations"]
  expected_values: {"total": "$1,234.56"}
output:
  type: structured
  format: {"complete": bool, "missing_fields": [string],
           "values_correct": bool, "formatting_ok": bool}

example_query: |
  This is a completed expense report form.

  Required fields: Employee name, Date, Line items, Subtotal, Tax, Total
  Expected total: $1,234.56

  Verify:
  1. Are all required fields filled in?
  2. Is the total calculation correct (matches expected)?
  3. Is the formatting professional (aligned, readable)?
  4. Any obvious errors or omissions?
```

---

#### Pattern 30: Code Output Verification

**Domain**: IDEs, terminals, notebooks
**Input**: Code execution output screenshot
**Output**: Success/error assessment

```yaml
pattern: code_output_verification
input:
  images: [terminal_or_notebook_output]
  expected: {"no_errors": true, "expected_output_contains": "Success"}
output:
  type: structured
  format: {"execution_succeeded": bool, "errors_present": bool,
           "error_types": [string], "output_matches_expected": bool}

example_query: |
  This shows the output of running the agent's code.

  Check for:
  1. Did the code execute without errors (no tracebacks)?
  2. Is there any error/warning text?
  3. Does the output contain expected success indicators?
  4. Any unexpected output that suggests problems?
```

---

## Combining Patterns

Most tasks benefit from multiple patterns in combination. **Always include at least one trajectory-based pattern** (Categories B, C, or F) — do not rely solely on terminal state patterns.

### Recommended: Trajectory-Aware Pipeline

```yaml
verification_pipeline:
  # Process verification — USE THE TRAJECTORY (most important VLM check)
  # Proves the agent went through the actual workflow, not just arranged the final screen
  - pattern: incremental_progress  # Pattern 7 — sampled trajectory frames
    weight: 0.3
    required: true
    input: sample_trajectory_frames(traj, n=5)
    query: "Did the agent progress through: data loading → configuration → analysis → results?"

  # Before/after transformation — proves meaningful change occurred
  - pattern: first_last_transformation  # Pattern 5
    weight: 0.2
    input: [get_first_screenshot(traj), get_final_screenshot(traj)]

  # Final state content — verify the end result quality
  - pattern: value_extraction_final  # Pattern 3
    weight: 0.2
    parameters:
      expected_values:
        transit_depth: {value: 1.43, tolerance: 0.15}

  # Negative check — catch errors
  - pattern: final_state_negative  # Pattern 4
    weight: 0.1

  # Red flag detection
  - pattern: guessing_detection  # Pattern 15
    weight: 0.2
    failure_mode: "flag_for_review"

scoring:
  pass_threshold: 0.75
  weights_must_sum_to: 1.0
```

### Anti-Pattern: Final-Screenshot-Only Pipeline (AVOID)

```yaml
# DON'T DO THIS — all checks use only the final screenshot
verification_pipeline:
  - pattern: final_screenshot_binary    # 1 image
    weight: 0.3
  - pattern: final_state_checklist      # 1 image
    weight: 0.4
  - pattern: final_state_negative       # 1 image
    weight: 0.3

# Problems:
# - All patterns see the same single image
# - GUI windows overlap — the final screenshot may only show the topmost window
# - No evidence the agent actually performed the work (could have arranged the screen)
# - Redundant: multiple patterns checking the same image adds little robustness
```

### Why Trajectory Beats Single Image

Consider a task like "perform aperture photometry in AstroImageJ":

- **Final screenshot shows**: Results table ON TOP, covering the FITS image with aperture circles behind it. The VLM can only verify the results table.
- **Trajectory frames show**: (1) FITS image loaded with star field visible, (2) aperture circles being placed on stars, (3) photometry dialog open, (4) Results table appearing with measurements. The VLM can verify the entire workflow happened.

The trajectory captures what the final screenshot hides — because in GUI applications, later windows cover earlier ones, but the trajectory recorded every step before that happened.

---

