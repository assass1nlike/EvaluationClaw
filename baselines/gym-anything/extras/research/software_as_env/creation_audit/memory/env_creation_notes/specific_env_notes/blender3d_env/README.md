> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Blender 3D Environment Notes

## Overview

The Blender 3D environment provides a complete Blender installation with virtio GPU support for 3D modeling, animation, rendering, and video editing tasks.

## Key Features

- **Blender 4.2 LTS** - Latest stable long-term support version
- **GPU Support** - Uses virtio-GPU in QEMU for hardware-accelerated rendering
- **Pre-configured** - Splash screen disabled, Python tooltips enabled
- **Official Demo Files** - Uses real Blender demo scenes (BMW benchmark, classroom)

## Data Sources (REALISTIC DATA)

The environment downloads **official Blender demo files** instead of using procedurally generated toy scenes:

| File | Source | Description |
|------|--------|-------------|
| BMW27.blend | https://download.blender.org/demo/test/BMW27.blend.zip | Official benchmark scene (3MB) |
| classroom.blend | https://download.blender.org/demo/test/classroom.zip | Classic demo scene (70MB) |
| blender-4.0-splash.blend | https://download.blender.org/demo/splash/ | Official splash artwork (33MB) |

These are production-quality scenes with proper materials, lighting, and geometry.

## GPU Configuration

The environment is configured for GPU rendering:

1. **Host Device Passthrough**: `/dev/dri` is mounted for DRI access
2. **Render Group**: User `ga` is added to `render` group
3. **Auto-detection**: Blender will auto-detect CUDA (NVIDIA), OpenCL, HIP, or fallback to CPU

### GPU in QEMU

When running with the QEMU runner, the VM uses `virtio-vga` which provides:
- Software OpenGL rendering via Mesa/LLVMpipe
- Basic 3D acceleration for GUI
- For heavy renders, use Cycles CPU mode

## Installation Details

### Dependencies Installed

- OpenGL/Mesa libraries (libgl1-mesa-glx, libegl1-mesa, etc.)
- Vulkan support (mesa-vulkan-drivers, libvulkan1)
- OpenCL support (ocl-icd-opencl-dev, clinfo)
- Image processing (ffmpeg, imagemagick)
- GUI automation (scrot, wmctrl, xdotool)

### Blender Location

- Binary: `/opt/blender/blender`
- Symlink: `/usr/local/bin/blender`
- User config: `/home/ga/.config/blender/4.2/`

## Sample Files

Located in `/home/ga/BlenderDemos/`:
- `BMW27.blend` - Official benchmark car scene
- `classroom/classroom.blend` - Classic classroom demo
- `blender-4.0-splash.blend` - Official splash artwork

Located in `/home/ga/BlenderProjects/`:
- `render_scene.blend` - Copy of BMW27 for rendering tasks
- `baseline_scene.blend` - Simple scene for object manipulation tasks

## Tasks

### render_basic_scene
- **Difficulty**: Easy
- **Goal**: Render the official demo scene and save as PNG
- **Verification**: ROBUST MULTI-SIGNAL VERIFICATION
  - File existence and format (15 pts)
  - File created/modified during task (15 pts)
  - File size reasonable for render (10 pts)
  - Image dimensions correct (10 pts)
  - Blender was running (10 pts)
  - Render actually performed (15 pts)
  - VLM: 3D content verified (15 pts)
  - VLM: Not just UI screenshot (10 pts)
- **Pass criteria**: 60% score AND key criteria (new file + render + visual check)

### add_sphere_to_scene
- **Difficulty**: Easy
- **Goal**: Add a UV sphere to the scene and save
- **Verification**: Checks for new sphere object in blend file

## Verification Patterns

### ROBUST Multi-Signal Verification

The render task uses multiple independent signals to prevent gaming:

1. **File-based checks**: Existence, modification time, size, dimensions
2. **Application state**: Blender running, window title, render time
3. **VLM visual verification**: Confirm 3D content in rendered output
4. **"Do nothing" detection**: Caps score if no work performed

### Blender Python API for Scene Queries

```bash
# Query scene state
/usr/local/bin/blender-query-scene /path/to/file.blend

# Returns JSON with object counts, types, locations
```

### Verifier Test Cases

The verifier includes explicit test cases for:
- "Do nothing" scenario (must FAIL)
- Suspiciously small file (must FAIL)
- Pre-existing file not modified (must FAIL)
- Successful render (must PASS)

## Common Issues

### 1. Render Too Slow
- Use CPU rendering with lower samples
- Reduce resolution for testing (set to 50% in baseline scene)

### 2. GPU Not Detected
- Expected in QEMU - uses software rendering
- Pass-through GPU on supported hosts

### 3. Blender Won't Start
- Check DISPLAY=:1 is set
- Verify desktop environment is running

### 4. Demo Files Not Downloaded
- Check network connectivity (net: true in env.json)
- Check /home/ga/BlenderDemos/ for downloaded files

## Useful Commands

```bash
# Check Blender version
blender --version

# Query scene state (custom utility)
blender-query-scene /path/to/scene.blend

# Run Blender script headlessly
blender --background scene.blend --python script.py

# Render from command line
blender --background scene.blend --render-output //output_ --render-frame 1

# Get GPU info
blender-info  # Custom script installed by setup
```

## Lessons Learned During Development

This section documents mistakes made during environment creation and how they were fixed.

### Mistake 1: Procedural Data Instead of Real Demo Files

**Initial approach (WRONG):**
```python
# Generated simple scenes with Python
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
bpy.ops.mesh.primitive_sphere_add(radius=1, location=(-3, 0, 1))
```

**Problem:** This creates "toy data" - not realistic 3D scenes. The prompt explicitly warns against this.

**Fixed approach:**
```bash
# Download official Blender demo files
wget https://download.blender.org/demo/test/BMW27.blend.zip
wget https://download.blender.org/demo/test/classroom.zip
```

### Mistake 2: Simple Verification (Easily Gameable)

**Initial verifier (WRONG):**
```python
# Only 4 criteria, no VLM, no "do nothing" detection
if file_exists and file_size > 50KB and dimensions == 1920x1080:
    return passed=True
```

**Problem:** Agent could do nothing and pass if file pre-existed.

**Fixed verifier:** 8 criteria including:
- File CREATED during task (not pre-existing)
- Render time > 0 (actual work done)
- VLM visual verification
- "Do nothing" detection that caps score

### Mistake 3: Forgetting VLM in Second Task

**Problem:** Updated `render_basic_scene` with VLM but forgot `add_sphere_to_scene`.

**Fix:** Both tasks now have consistent multi-signal verification with VLM.

### Mistake 4: GPU Rendering Confusion

**Initial assumption:** Virtio GPU would provide GPU rendering for Cycles.

**Reality:**
- Virtio GPU provides **display acceleration** (OpenGL for UI) ✅
- Cycles rendering uses **CPU** (no CUDA/HIP in QEMU) ✅
- This is expected and correct behavior

**Verified output:**
```
compute_device_type: "NONE"  # Expected - no GPU compute
GPU Hardware: Red Hat, Inc. Virtio GPU  # Display works
direct rendering: Yes  # OpenGL works
```

## Resources

- Blender Manual: https://docs.blender.org/manual/
- Python API: https://docs.blender.org/api/current/
- Demo Files: https://download.blender.org/demo/
- BMW Benchmark: https://download.blender.org/demo/test/BMW27.blend.zip
