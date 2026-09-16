# Task Difficulty Adaptation Guide

This guide documents the process for adapting task difficulty in either direction:
- **Hard to Easy**: Simplifying tasks when model performance is too low
- **Easy to Hard**: Adding complexity when tasks are too simple

## When to Adapt Difficulty

### Indicators for Hard → Easy
- Model success rate < 5% on existing tasks
- Consistent failure patterns across multiple runs
- Model gets stuck in loops (scrolling, clicking same element repeatedly)
- Tasks require domain knowledge the model lacks
- Multi-step tasks where model fails at a specific step

### Indicators for Easy → Hard
- Model success rate > 80% consistently
- Model completes tasks with many unused steps
- Tasks don't differentiate between model capabilities
- Need to test more advanced reasoning/planning

---

## Hard to Easy: Simplification Process

### Step 1: Trajectory Analysis

Before simplifying tasks, analyze existing model trajectories to understand WHY tasks fail.

**Required files to examine:**
```
results/{env_name}/{task_name}/
├── parsed_responses.json    # Step-by-step model actions
├── info.json               # Final scores and metrics
├── screenshot_*.png        # Visual state at each step
└── trajectory.json         # Full action/observation history
```

**Analysis checklist:**
1. At which step does the model typically fail?
2. What action does the model repeat unnecessarily?
3. Does the model understand the goal but fail execution?
4. Does the model misinterpret what it sees?
5. Is the model stuck searching for something?

**Document findings** in a trajectory analysis file (see `slicer3d_trajectory_analysis.md` for example).

### Step 2: Identify Failure Patterns


### Step 3: Design Simplified Tasks

**Core principles for easier tasks:**

1. **Pre-position everything possible**
   - Load data before task starts
   - Navigate to correct view/slice/page
   - Open required panels/modules
   - Set correct zoom/window levels

2. **Reduce navigation requirements**
   - Minimize scrolling needed
   - Avoid file browser navigation
   - Pre-open relevant menus
   - Pre-select correct tools

3. **Make targets visually obvious**
   - Use high-contrast displays
   - Center targets in view
   - Use large, visible elements
   - Consider adding visual guides in setup

4. **Remove domain knowledge requirements**
   - Don't require anatomical level identification
   - Don't require clinical interpretation
   - Use descriptive visual criteria ("bright circular region")
   - Avoid jargon unless testing domain knowledge specifically

5. **Allow generous tolerances**
   - Accept measurements within ±20-30% of ground truth
   - Accept approximate placements
   - Give partial credit for reasonable attempts

### Step 4: Create Tiered Task Suite

Organize tasks into difficulty tiers:

| Tier | Target Success | Characteristics |
|------|---------------|-----------------|
| **Tier 1** | >70% | UI operations only (click, type, navigate menus) |
| **Tier 2** | >40% | Pre-positioned actions (measure visible target) |
| **Tier 3** | >20% | Guided actions (some interpretation needed) |
| **Tier 4** | >10% | Minimal navigation (1-2 steps of searching) |
| **Tier 5** | <5% | Full complexity (original hard tasks) |

### Step 5: Implementation

**Task structure:**
```
tasks/{task_name}/
├── task.json          # Task configuration
├── setup_task.sh      # Pre-positioning script
├── export_result.sh   # Result extraction
└── verifier.py        # Success evaluation
```

**task.json guidelines:**
- Keep description concise (1-2 sentences)
- State the goal and output location only
- Do NOT include step-by-step instructions
- Do NOT explain how to use the software
- Assume agent has software knowledge

**Good description:**
```
"Measure the maximum diameter of the visible glioma tumor on this brain FLAIR MRI. Save to ~/Documents/SlicerData/BraTS/tumor_diameter.mrk.json"
```

**Bad description (too verbose):**
```
"A brain MRI is displayed showing a glioma tumor. The tumor appears as a bright region. Use the Markups > Line tool to measure it. Click one point at one edge, then click at the opposite edge. The measurement will appear. Then save using File > Save Data..."
```

**setup_task.sh guidelines:**
- Do all pre-positioning programmatically
- Load data to correct state
- Navigate to correct module/view
- Only output: `echo "=== Setup Complete ==="`
- Do NOT echo task instructions

**verifier.py guidelines:**
- Score multiple criteria independently
- Use generous tolerances for measurements
- Include VLM-based visual verification
- Give partial credit for attempts

---


## Specific Guidelines Learned

### From Slicer3D Experience

1. **Scrolling is the enemy of success**
   - Models cannot reliably find "optimal" anatomical levels
   - Pre-position to correct slice whenever possible
   - If scrolling required, limit to 1-2 slices maximum

2. **Visual obviousness matters**
   - Bright lesions on FLAIR work well
   - High-contrast structures are easier
   - Centered targets are easier than edge targets

3. **File saving is achievable**
   - Models can navigate save dialogs
   - Provide specific save paths
   - File verification is reliable

4. **Module switching works**
   - Models reliably switch between modules
   - Pre-switch to reduce steps needed

5. **Markup placement succeeds when decisive**
   - If model knows WHERE to click, it can place markups
   - Failure is in FINDING where, not in clicking

### General Best Practices

1. **Test before deploying**
   - Run environment manually first
   - Use screenshot-based UI grounding for interactive testing (Claude: `visual_grounding` MCP tool; Codex: native screenshot understanding or `ask_cua.py`)
   - Verify setup script achieves intended state

2. **Check screenshot output**
   - Verify target is visible after setup
   - Verify UI is in correct state
   - Verify no dialogs block view

3. **Verifier should be robust**
   - Handle missing files gracefully
   - Use VLM for visual verification
   - Return partial scores, not just pass/fail

4. **Document your changes**
   - Record why task was simplified/hardened
   - Note expected success rates
   - Track actual vs expected performance

---


---

## Example: Slicer3D Simplification

**Original hard task**: `aorta_measurement`
- Required finding L2 vertebral level
- Required scrolling through volume
- Required precise measurement
- Result: 0% success (scrolling loop)

**Simplified task**: `scroll_one_slice_measure_aorta`
- Pre-positioned 1-2 slices from optimal
- Minimal scrolling required
- Generous tolerance (±20mm)
- Target: 10% success rate

**Even simpler task**: `measure_visible_tumor_diameter`
- Pre-positioned to correct slice
- No scrolling required
- Obvious visual target (bright tumor)
- Target: 20% success rate

---

## Appendix: Template Files

### Minimal task.json
```json
{
  "id": "task_name@1",
  "version": "1.0",
  "env_id": "env_name@0.1",
  "description": "Single sentence describing goal and output location.",
  "difficulty": "easy",
  "init": {
    "timeout_sec": 300,
    "max_steps": 40
  },
  "hooks": {
    "pre_task": "/workspace/tasks/task_name/setup_task.sh",
    "post_task": "/workspace/tasks/task_name/export_result.sh"
  },
  "success": {
    "mode": "program",
    "spec": {
      "program": "verifier.py::verify_task_name"
    }
  }
}
```

### Minimal setup_task.sh ending
```bash
# ... all setup code ...

echo "=== Setup Complete ==="
```

---

## Questions to Ask Before Starting

1. What is the current success rate on this task?
2. What is the target success rate?
3. What is the primary failure pattern?
4. Can the failure be eliminated by pre-positioning?
5. What is the minimum complexity needed to test the target skill?
6. How will success be measured?
