> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# 3D Slicer Environment Notes

## Overview

3D Slicer is a free, open-source medical image visualization and analysis platform. This environment provides 3D Slicer with sample medical imaging data for agents to interact with.

## Installation Quirks

### Download Timeout
- **Issue**: The 3D Slicer package is ~400-500MB and can take longer than the default SSH timeout (300 seconds)
- **Solution**:
  - Use `aria2c` for parallel downloads when available
  - Split installation: `install_slicer.sh` tries to download, `setup_slicer.sh` completes if interrupted
  - Use `curl` with shorter timeouts and retry logic

### Download URLs
- **Primary**: `https://download.slicer.org/download?os=linux&stability=release`
- **Fallback**: `https://slicer-packages.kitware.com/api/v1/item/<item_id>/download`
- Note: URLs may change between versions; check download.slicer.org for latest

### Dependencies (CRITICAL)
Ubuntu 22.04 requires these Qt/XCB libraries - **missing any will cause "cannot open shared object" errors**:
```bash
apt-get install -y \
    libglu1-mesa \
    libpulse-mainloop-glib0 \
    libnss3 \
    libasound2 \
    libxcb-xinerama0 \
    libsm6 \
    libpcre2-16-0 \
    libxkbcommon0 \
    libdbus-1-3 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-keysyms1 \
    libxcb-shape0 \
    libxcb-render-util0 \
    libxcb-image0

# Run ldconfig after installation
ldconfig
```

**Common errors if libraries are missing:**
- `libpcre2-16.so.0: cannot open shared object file` → Install `libpcre2-16-0`
- `libxcb-xinerama.so.0: cannot open shared object file` → Install `libxcb-xinerama0`

## Sample Data

### MRHead.nrrd
- **Source**: Slicer Testing Data repository
- **URL**: `https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/<hash>`
- **Fallback**: Script generates synthetic NRRD if download fails
- **Size**: ~4MB original, ~500KB synthetic

### CTChest.nrrd
- **Source**: Slicer Testing Data repository
- **Size**: ~42MB
- **Use**: For tasks requiring larger/more complex data

### Synthetic Data Generation
If MRHead download fails, a synthetic volume is generated:
- 64x64x64 voxels
- Spherical structure simulating brain tissue
- Written directly as NRRD format

## Configuration

### Slicer Settings (Slicer.ini)
Located at `~/.config/NA-MIC/Slicer.ini`:
- Disables update checks and telemetry
- Sets screenshot output directory
- Configures home module as "Welcome"
- Disables exit confirmation

### Key Directories
- Config: `~/.config/NA-MIC/`
- Data: `~/Documents/SlicerData/`
- Screenshots: `~/Documents/SlicerData/Screenshots/`
- Sample data: `~/Documents/SlicerData/SampleData/`

## Verification Strategy

### IMPORTANT: Avoid Hackable Verification

**NEVER rely on screenshot size alone** - this is easily gamed:
```bash
# BAD - Welcome screen is also >100KB!
if [ "$SCREENSHOT_SIZE_KB" -gt 100 ]; then
    DATA_LOADED="true"  # WRONG!
fi
```

### Proper Verification: Hybrid Approach

1. **Programmatic (60%)**: Query Slicer's Python API for loaded volumes
2. **VLM Visual (40%)**: Check if brain scan is visible in slice views

### Export Script Pattern
The export script should query Slicer's internal state:
```bash
# Use PythonSlicer to query scene
QUERY_RESULT=$(/opt/Slicer/bin/PythonSlicer -c "
import json, slicer
nodes = slicer.mrmlScene.GetNodesByClass('vtkMRMLScalarVolumeNode')
nodes.InitTraversal()
count = 0
names = []
n = nodes.GetNextItemAsObject()
while n:
    count += 1
    names.append(n.GetName())
    n = nodes.GetNextItemAsObject()
print(json.dumps({'count': count, 'names': names}))
")
```

### Key Verification Metrics
- `volume_loaded`: Was a volume actually loaded? (API check)
- `mrhead_loaded`: Was MRHead specifically loaded? (name check)
- `volume_count`: How many volumes in scene?
- `brain_scan_visible`: VLM check for data in slice views
- `slicer_functional`: VLM check for no error dialogs

### Window Setup for Agent Interaction
Task setup MUST:
1. **Maximize window**: `wmctrl -i -r "$WID" -b add,maximized_vert,maximized_horz`
2. **Dismiss dialogs**: Press Escape/Enter to close popups
3. **Wait for full load**: Not just window detection, but module loading complete

## Tasks

### load_sample_data
- **Difficulty**: Easy
- **Goal**: Load MRHead.nrrd and verify it's visible
- **Timeout**: 120 seconds
- **Max steps**: 30

### capture_3d_view
- **Difficulty**: Medium
- **Goal**: Load data, enable volume rendering, save screenshot
- **Timeout**: 180 seconds
- **Max steps**: 50

### brats_tumor_segmentation
- **Difficulty**: Hard
- **Goal**: Segment brain tumor from real BraTS 2021 MRI data
- **Timeout**: 600 seconds
- **Max steps**: 100
- **Data**: Real BraTS 2021 dataset downloaded from Kaggle (~5GB)
- **Verification**: Dice coefficient, Hausdorff distance, volume accuracy, report check

**Requirements for task completion:**
1. Create segmentation of tumor regions (enhancing, necrotic, edema)
2. Create 3D visualization of the tumor
3. Report tumor volume in milliliters (mL) to a text file

**Data Download:**
```bash
curl -L -o brats-2021-task1.zip \
  https://www.kaggle.com/api/v1/datasets/download/dschettler8845/brats-2021-task1
```

**Scoring (100 points):**
- Dice Whole Tumor: 25 points (threshold: 0.5)
- Dice Tumor Core: 15 points (threshold: 0.3)
- Dice Enhancing: 15 points (threshold: 0.3)
- Hausdorff Distance 95%: 10 points (threshold: 30mm)
- Volume Accuracy: 15 points (within 50%)
- Volume Report: 10 points (within 30% of ground truth)
- 3D Visualization: 10 points (screenshots created)

## Timing

Typical environment startup times (observed in testing):
- Pre-start hook (install): 80-130 seconds (depends on network speed for ~400MB download)
- Post-start hook (setup): 20-40 seconds
- Pre-task hook (launch Slicer): 25-40 seconds (when dependencies are correctly installed)
- Total: ~130-200 seconds

**Note**: If pre-task hook takes 90-100 seconds, Slicer likely failed to launch due to missing libraries.

## Known Issues

1. **MRHead download may fail**: GitHub rate limits can cause download failures; synthetic data is generated as fallback
2. **First-run dialogs**: Slicer.ini configuration attempts to suppress these, but some may still appear
3. **GPU requirements**: Volume rendering requires OpenGL 3.2+; software rendering fallback may be slow

## Resources

- 3D Slicer Documentation: https://slicer.readthedocs.io/
- Download Page: https://download.slicer.org/
- Sample Data Wiki: https://www.slicer.org/wiki/SampleData
- Slicer Testing Data: https://github.com/Slicer/SlicerTestingData
