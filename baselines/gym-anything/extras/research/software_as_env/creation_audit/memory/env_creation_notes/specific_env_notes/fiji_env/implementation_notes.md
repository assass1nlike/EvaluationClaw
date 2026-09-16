> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Fiji Environment Implementation Notes

## Overview

The Fiji environment provides Fiji (Fiji Is Just ImageJ), a comprehensive scientific image analysis platform. This environment was created to support microscopy and biological image processing tasks.

## Key Implementation Decisions

### 1. Fiji vs ImageJ

- **Decision**: Create a separate Fiji environment even though `imagej_env` already exists
- **Rationale**:
  - Fiji is ImageJ with "batteries included" - has many additional plugins
  - Different tasks focusing on Fiji-specific capabilities
  - Allows for different sample datasets
  - Educational clarity - users can understand Fiji as distinct from basic ImageJ

### 2. Installation Method

- **Approach**: Download pre-built Fiji distribution with bundled JDK
- **URL**: `https://downloads.imagej.net/fiji/latest/fiji-latest-linux64-jdk.zip`
- **Fallbacks**: UK mirror, stable version
- **Rationale**:
  - Fiji provides pre-built binaries (no compilation needed)
  - JDK-bundled version ensures Java compatibility
  - Official distribution includes all plugins

### 3. Java Version

- **Choice**: OpenJDK 17
- **Rationale**:
  - Modern Java version
  - Good compatibility with Fiji
  - LTS (Long Term Support) version

### 4. Sample Data Strategy

Following the prompt's critical requirement for **real data**, not synthetic:

#### Sources Used:

1. **Broad Bioimage Benchmark Collection (BBBC005)**
   - **Type**: Synthetic cells with ground truth
   - **URL**: https://data.broadinstitute.org/bbbc/BBBC005/
   - **Size**: ~1MB
   - **Purpose**: Cell counting and segmentation validation
   - **Why chosen**: Widely used benchmark, has ground truth for verification

2. **Cell Image Library**
   - **Type**: Real biological cell images
   - **URL**: http://www.cellimagelibrary.org/
   - **Purpose**: Real microscopy examples
   - **Why chosen**: Authentic biological data

3. **Fiji Built-in Samples**
   - **Type**: Various (CT scans, fluorescence, etc.)
   - **Access**: File > Open Samples menu
   - **Purpose**: Standard test images
   - **Examples**: Blobs, T1 Head, HeLa Cells
   - **Why chosen**: Pre-vetted by Fiji team, diverse image types

#### Why NOT synthetic/handwritten data:

- Prompt explicitly forbids: "Do NOT handwrite small sample data files"
- Real data reveals actual application behavior
- Edge cases and realistic scenarios
- Professional-grade verification possible

### 5. Task Selection

Created two tasks that showcase Fiji-specific capabilities:

#### Task 1: Z-Stack Projection (Easy)
- **Image**: T1 Head CT scan (Fiji built-in)
- **Skills**: 3D imaging, projection, contrast adjustment
- **Output**: Maximum intensity projection + statistics
- **Difficulty**: Easy - straightforward workflow

#### Task 2: Color Deconvolution (Medium)
- **Image**: HeLa Cells (Fiji built-in)
- **Skills**: Color separation, histology analysis, multi-channel saving
- **Output**: Separated channels + statistics
- **Difficulty**: Medium - requires understanding staining concepts

**Rationale for task choices**:
- **Diverse**: One 3D/grayscale, one 2D/color
- **Fiji-specific**: Color deconvolution is a key Fiji capability
- **Real workflow**: Both are common in scientific imaging
- **Progressive difficulty**: Easy to medium

### 6. Directory Structure

```
fiji_env/
├── env.json              # Environment configuration
├── scripts/
│   ├── install_fiji.sh   # Pre-start: Install Fiji, Java, samples
│   └── setup_fiji.sh     # Post-start: Configure user, create shortcuts
├── tasks/
│   ├── z_stack_projection/
│   │   ├── task.json
│   │   ├── setup_task.sh      # Launch Fiji, prepare environment
│   │   ├── export_result.sh   # Copy results to /tmp
│   │   └── verifier.py        # Stub verifier (VLM evaluation is external)
│   └── color_deconvolution/
│       ├── task.json
│       ├── setup_task.sh
│       ├── export_result.sh
│       └── verifier.py
├── assets/              # (Created for future data needs)
├── config/              # (Created for future config needs)
├── utils/               # (Created for future utilities)
├── evidence_docs/       # Testing evidence and screenshots
└── README.md            # Comprehensive documentation
```

### 7. User Setup

- **User**: `ga` (guest agent)
- **Password**: `password123`
- **Permissions**: sudo with nopasswd
- **Display**: `:1` (set via env var)
- **Data directory**: `~/Fiji_Data/` with subdirectories:
  - `raw/` - Input images
  - `processed/` - Intermediate results
  - `results/` - Final outputs
  - `measurements/` - Analysis data

### 8. Preferences Configuration

Created `IJ_Prefs.txt` to disable first-run dialogs:

```
.imagej.prefs.firstRun=false
.imagej.prefs.updateCheckOnStartup=false
.fiji.prefs.updateCheckOnStartup=false
```

**Location**: Both `~/.fiji/IJ_Prefs.txt` and in Fiji installation directory

**Why needed**: Prevents interactive dialogs that would block automated agents

### 9. Launcher Wrapper

Created `/usr/local/bin/fiji` wrapper script:

**Purpose**:
- Changes to correct working directory
- Handles both fiji-linux-x64 binary and fiji shell script
- Works from any directory
- Symlinked to `/usr/local/bin/imagej` for compatibility

**Why needed**: Fiji uses relative paths, fails if not run from its directory

### 10. Resource Allocation

- **CPU**: 4 cores (image processing is CPU-intensive)
- **RAM**: 6GB (large stacks need memory)
  - Java heap set to 4GB via `_JAVA_OPTIONS="-Xmx4g"`
- **GPU**: 0 (Fiji doesn't use GPU)
- **Network**: true (for downloading samples, updates)

## Common Issues and Solutions

### Issue 1: Fiji Executable Not Found

**Problem**: Fiji directory structure varies between versions

**Solution**:
- Search multiple possible paths
- Support both `fiji-linux-x64` and `ImageJ-linux64`
- Create compatibility symlink `Fiji.app` → `Fiji/`

### Issue 2: Java Memory

**Problem**: Large images cause out-of-memory errors

**Solution**: Set `_JAVA_OPTIONS="-Xmx4g"` in launch script

### Issue 3: First-Run Dialogs

**Problem**: Interactive dialogs block automation

**Solution**: Pre-create `IJ_Prefs.txt` with `firstRun=false`

### Issue 4: Window Management

**Problem**: Fiji window may not maximize properly

**Solution**: Use `wmctrl` with fallbacks for different window titles:
```bash
DISPLAY=:1 wmctrl -r "fiji" -b add,maximized_vert,maximized_horz
DISPLAY=:1 wmctrl -r "ImageJ" -b add,maximized_vert,maximized_horz
```

## Testing Approach

### Manual Testing Steps

1. **Start environment**: `env.reset(seed=42, use_cache=False)`
2. **Connect SSH**: Port from `env._runner.ssh_port`
3. **Take screenshot**: Verify Fiji window visible
4. **Check processes**: `ps aux | grep fiji`
5. **Check windows**: `wmctrl -l`
6. **Verify installation**: Check `/opt/fiji/` structure
7. **Test sample access**: Verify `~/Fiji_Data/raw/` has samples
8. **Interactive test**: Use screenshot grounding to verify task state (Claude: `visual_grounding`; Codex: native/`ask_cua.py`)

### Verification Checklist

- [ ] Fiji launches successfully
- [ ] Window visible and maximized
- [ ] Sample images accessible
- [ ] Tasks can be completed interactively
- [ ] Results saved to correct locations
- [ ] Installation logs clean (no critical errors)
- [ ] User directories created with correct permissions

## Data Sources Documentation

All sample data comes from **publicly available, real sources**:

1. **BBBC005**: Broad Institute's Bioimage Benchmark Collection
   - License: Public domain
   - Purpose: Cell segmentation benchmarks
   - Citation: https://bbbc.broadinstitute.org/BBBC005

2. **Fiji Samples**: Official ImageJ/Fiji sample images
   - License: Public domain
   - Purpose: Testing and demonstration
   - Source: Bundled with Fiji distribution

3. **Cell Image Library**: National resource for microscopy images
   - License: Varies (mostly CC BY)
   - Purpose: Real biological imaging
   - Citation: Required per image

## Lessons Learned

1. **Real data matters**: Using real microscopy images makes tasks more authentic and challenging

2. **Fiji's diversity**: Many ways to accomplish the same task - need clear instructions

3. **Window title variations**: Fiji window might be titled "Fiji", "ImageJ", or image name - need fallbacks

4. **Memory is critical**: Scientific imaging needs generous RAM allocation

5. **Directory structure changes**: Fiji packaging has changed over time - need flexible path detection

6. **Plugin availability**: Some plugins might need manual installation - verify in testing

## Future Improvements

Potential enhancements for future iterations:

1. **More tasks**:
   - Macro scripting task
   - 3D volume rendering
   - Object tracking in time-lapse
   - Machine learning segmentation (Weka)

2. **Additional data**:
   - Time-lapse sequences
   - Multi-channel fluorescence
   - Large tile scans

3. **Plugin configuration**:
   - Pre-install additional plugins
   - Custom plugin development task

4. **Batch processing**:
   - Process multiple images
   - Create analysis pipelines

## References

- Fiji documentation: https://imagej.net/software/fiji/
- ImageJ user guide: https://imagej.net/learn/
- Fiji scripting: https://imagej.net/scripting/
- BBBC collection: https://bbbc.broadinstitute.org/
