> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# blade_runner_look Task Documentation

## Overview

The `blade_runner_look` task tests an agent's ability to perform professional color grading in DaVinci Resolve, recreating the iconic teal/orange aesthetic from "Blade Runner 2049".

## Task Requirements

### Starting State
- DaVinci Resolve is running at the Project Manager
- Professional footage is downloaded to `/home/ga/DaVinciProjects/source/`
- Reference image is available at `/home/ga/DaVinciProjects/reference/`
- Source frame is extracted to `/tmp/source_frame.png` for comparison

### Agent Goals
1. Create or open the "BladeRunnerLook" project
2. Import the source footage
3. Navigate to the Color page
4. Apply Blade Runner 2049 style color grading:
   - Teal/cyan shadows
   - Orange/warm highlights
   - High contrast with lifted blacks
5. Export a still frame as `/home/ga/DaVinciProjects/graded_frame.png`

### Expected Output
- PNG file at `/home/ga/DaVinciProjects/graded_frame.png`
- Minimum file size: 100KB
- Resolution: 1920x1080

## Data Sources

### Source Footage
Professional footage is downloaded from the following sources in order of preference:

1. **Blackmagic BRAW samples** (Tier 1 - Professional)
   - Filmplusgear BRAW test files
   - Format: BRAW (Blackmagic RAW)

2. **Blender Foundation** (Tier 2 - CC-BY Professional)
   - Tears of Steel 4K (~6.7GB)
   - Sintel
   - Source: https://download.blender.org/demo/movies/

3. **Google Sample Videos** (Tier 3 - Backup)
   - Tears of Steel, Sintel
   - Source: https://commondatastorage.googleapis.com/gtv-videos-bucket/

### Reference Image
Reference images showing the Blade Runner 2049 color palette:
- Wikimedia Commons cityscape images
- Target palette: Teal (#004466) to Orange (#FF8844)

## Verification

### Verification Criteria (100 points total)

| Criterion | Weight | Description |
|-----------|--------|-------------|
| Technical Quality | 15% | No banding, proper exposure, no artifacts |
| Grading Applied | 15% | Image was modified from source |
| Teal/Orange Split | 20% | Complementary color relationship detected |
| Tonal Match | 15% | Contrast and lifted shadows |
| Palette Match | 15% | Delta E color comparison |
| VLM Assessment | 20% | AI evaluation of cinematic quality |

### Passing Thresholds
- Minimum score: 60 points
- Maximum palette Delta E: 25
- Minimum histogram correlation: 0.4

### Verification Functions

The verifier (`verifier.py`) includes:

1. **check_technical_quality()** - Detects banding, crushed blacks, blown highlights
2. **check_grading_applied()** - Verifies image was modified from source
3. **check_teal_orange_split()** - Detects complementary color relationship in shadows/highlights
4. **check_tonal_match()** - Analyzes contrast and lifted shadows
5. **check_palette_match()** - CIEDE2000 Delta E color comparison
6. **check_histogram_similarity()** - Channel-by-channel histogram correlation
7. **check_perceptual_similarity()** - SSIM structural similarity
8. **verify_broadcast_legal()** - YCbCr levels check
9. **vlm_verification()** - Optional AI-based cinematic evaluation

## Known Issues

### 1. DaVinci Resolve Scripting Limitations
- The free version has limited scripting capabilities
- Color page parameters cannot be accessed via DaVinci Resolve Script API
- Project creation requires GUI interaction

### 2. First-Run Wizard
- DaVinci Resolve shows welcome dialogs on first launch
- The environment setup attempts to disable these via configuration

### 3. SSL Certificate Issues in Container
- Downloads require `--no-check-certificate` flag for wget
- This is due to certificate verification issues in the Apptainer container

### 4. Project State
- The task starts at Project Manager, not with Color page open
- Agent must navigate through project creation/opening

## Testing

### Quick Test
```python
from gym_anything.api import from_config

env = from_config("benchmarks/cua_world/environments/davinci_resolve_apptainer_env", task_id="blade_runner_look")
obs = env.reset(seed=42, use_cache=False)

# Verify setup
result = env._runner.exec_capture("ls -la /home/ga/DaVinciProjects/source/")
print(result)

# Check DaVinci is running
result = env._runner.exec_capture("pgrep -f resolve")
print(f"DaVinci PID: {result}")

env.close()
```

### Verification Test
```python
# After agent completes task, run verifier
from verifier import verify_blade_runner_look

env_info = {
    'copy_from_env': env.copy_from_env,
    'query_vlm': None  # Optional
}

task_info = {
    'metadata': {
        'expected_output_path': '/home/ga/DaVinciProjects/graded_frame.png',
        'reference_image_path': '/home/ga/DaVinciProjects/reference/blade_runner_reference.jpg',
        'source_frame_path': '/tmp/source_frame.png',
    }
}

result = verify_blade_runner_look(None, env_info, task_info)
print(f"Passed: {result['passed']}, Score: {result['score']}")
```

## Files

| File | Purpose |
|------|---------|
| `task.json` | Task specification and metadata |
| `setup_task.sh` | Downloads footage and reference, extracts source frame |
| `export_result.sh` | Collects color analysis data for verification |
| `verifier.py` | Comprehensive 9-criterion verification |

## Blade Runner 2049 Color Science

The target look has these characteristics:

### Shadow Region (Teal)
- RGB bias: Blue > Red, Green similar to Blue
- Target: #004466 (RGB: 0, 68, 102)
- Lifted blacks (not crushed to pure black)

### Highlight Region (Orange)
- RGB bias: Red > Blue, Green moderate
- Target: #FF8844 (RGB: 255, 136, 68)

### Overall
- High contrast with dramatic falloff
- Slightly desaturated midtones
- Cinematic mood and atmosphere

## References

- [DaVinci Resolve Color Grading Guide](https://documents.blackmagicdesign.com/UserManuals/DaVinci_Resolve_Manual.pdf)
- [Film Grab - Blade Runner 2049](https://film-grab.com/blade-runner-2049/)
- [Tears of Steel - Blender Foundation](https://mango.blender.org/)
