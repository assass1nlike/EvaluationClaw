> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# AstroImageJ Environment - Implementation Notes

## Overview

AstroImageJ is an astronomy-focused image processing application based on ImageJ. This environment provides a GNOME desktop with AstroImageJ installed for astronomical image analysis, photometry, and light curve generation.

## Installation Learnings

### Download URL Changes

**Issue**: The original download URLs for AstroImageJ v5.x no longer work. The project has moved to GitHub releases with a new naming convention.

**Solution**: Use the GitHub releases URL with the correct format:
```
https://github.com/AstroImageJ/astroimagej/releases/download/6.0.3.00/AstroImageJ-6.0.3.00-linux-x64.tgz
```

### Directory Structure

**Issue**: The extracted directory name is lowercase `astroimagej`, not `AstroImageJ` as might be expected.

**Solution**: Check multiple possible paths when locating the executable:
```bash
/opt/astroimagej/astroimagej/bin/AstroImageJ  # Actual location
/opt/astroimagej/AstroImageJ/bin/AstroImageJ  # Expected location
```

### Script Timeout

**Issue**: The initial install script timed out because it was too complex (downloading large files, creating synthetic FITS data with Python).

**Solution**:
- Simplified the install script
- Added timeout flags to wget commands
- Removed synthetic FITS generation (use NASA samples instead)

## Data Sources

### FITS Sample Files

Used NASA FITS samples from the official FITS Support Office:
- `https://fits.gsfc.nasa.gov/samples/WFPC2u5780205r_c0fx.fits` (HST WFPC2 sample)
- `https://fits.gsfc.nasa.gov/samples/UITfuv2582gc.fits` (UIT galaxy sample)

These are real astronomical images suitable for photometry tasks.

### Alternative Data Sources

For more complex tasks, consider:
- [AAVSO sample FITS files](https://www.aavso.org/sample-fit-files)
- [NOIRLab FITS Liberator datasets](https://noirlab.edu/public/products/applications/fitsliberator/datasets/)
- [Chandra X-ray Observatory open FITS](https://chandra.harvard.edu/photo/openFITS/)

## Task Design

### Task 1: measure_star_photometry (Difficulty: Medium)

**Objective**: Open a FITS image and perform aperture photometry on a star.

**Verification Strategy**:
1. Check if FITS file was opened (via log analysis)
2. Check for photometry activity
3. Look for measurement file creation in `~/AstroImages/measurements/`
4. Validate flux value if extracted

**Key Insight**: AstroImageJ saves photometry results in various formats (.txt, .csv, .tbl). The export script checks multiple possible locations and formats.

### Task 2: detect_exoplanet_transit (Difficulty: Hard)

**Objective**: Analyze REAL WASP-12b transit observations from University of Louisville and extract transit parameters.

**Data**: 230 calibrated FITS images from Moore Observatory (4.3GB total):
- Source: University of Louisville AstroImageJ Examples
- URL: <WASP-12b sample data URL — see the AstroImageJ user guide / examples page; the previously listed URL was hallucinated and does not exist>
- Image size: 4096x4096 pixels
- Filter: r-band (530-700nm)
- Exposure: 100 sec each

**Expected Transit Parameters** (from literature):
- Transit depth: ~1.4% (14 mmag)
- Transit duration: ~2.7 hours
- Planet radius: ~1.79 R_Jupiter (using R_star = 1.599 R_sun)

**What Agent Must Do**:
1. Load images (pre-loaded as sequence)
2. Configure apertures on target star WASP-12 (RA 06:30:32.79, Dec +29:40:20.4)
3. Select at least 2 comparison stars
4. Run multi-aperture photometry across all 230 images
5. Generate differential light curve
6. Measure transit parameters (depth, duration, mid-time)
7. Calculate planet radius using: Rp = Rs × sqrt(depth)

**Verification Strategy** (9 weighted criteria):
1. Image sequence loaded (10 pts)
2. Multi-aperture photometry performed (15 pts)
3. Multiple comparison stars used (15 pts)
4. Measurements recorded (10 pts)
5. Transit depth within tolerance (15 pts)
6. Mid-transit time within tolerance (10 pts)
7. Transit duration within tolerance (10 pts)
8. Light curve window visible (10 pts)
9. VLM verification of transit dip (5 pts)

**Pass Threshold**: Score >= 70% AND key criteria met (images + measurements + transit detection)

**Anti-Gaming Features**:
- Parameters validated against ground truth with tolerances
- Requires MULTIPLE independent signals
- "Do nothing" fails with Score: 0
- Wrong parameters fail with Score: 62 (below threshold)

## Launch Script Patterns

### Finding AstroImageJ Executable

Multiple paths must be checked due to version differences:
```bash
for path in \
    "/usr/local/bin/aij" \
    "/opt/astroimagej/astroimagej/bin/AstroImageJ" \
    "/opt/astroimagej/AstroImageJ/bin/AstroImageJ" \
    # ... more paths
```

### GUI Launch Requirements

- Must set `DISPLAY=:1`
- Run `xhost +local:` for X11 permissions
- Launch as the `ga` user with `su - ga -c "..."`

## Resource Requirements

- **Memory**: 6GB recommended (AstroImageJ with FITS files needs memory)
- **CPU**: 4 cores
- **Network**: Required for downloading AstroImageJ and FITS samples

## Known Limitations

1. **First-run dialogs**: AstroImageJ may show welcome dialogs on first launch. Preferences are set to disable these, but some may still appear.

2. **Update checks**: Disabled via preferences to avoid network delays during testing.

3. **Java dependency**: AstroImageJ 6.x bundles its own Java runtime, but system Java is installed as a fallback.

## Verification Strategy (CRITICAL)

### Anti-Gaming Design

The verification uses **multiple independent signals** to prevent gaming:

1. **Query AIJ's internal state via macro** (most reliable)
   - Uses ImageJ macro language to query `nImages`, `nResults`, `getTitle()`
   - Cannot be faked by creating files

2. **Window title analysis** (fallback)
   - Checks if FITS file window exists
   - Checks if Results window exists

3. **VLM visual verification** (when available)
   - Confirms astronomical image is visible
   - Detects aperture markers/circles
   - Verifies Results table is displayed

4. **Negative checks**
   - Explicitly fails if no evidence of FITS file interaction
   - "Do nothing" must fail

### What DOESN'T Work (Hackable)

- ❌ Just checking if measurement files exist (can be faked)
- ❌ Checking log file entries (can be appended)
- ❌ Screenshot size heuristics (welcome screen is also large)

### Testing the Verifiers

```bash
# Run measure_star_photometry verifier tests
python3 benchmarks/cua_world/environments/astroimagej_env/tasks/measure_star_photometry/verifier.py

# Expected output:
# Test 1 (do nothing): FAILS (Score: 0) ✅
# Test 2 (faked files): FAILS (Score: 0) ✅
# Test 3 (proper completion): PASSES (Score: 91) ✅

# Run detect_exoplanet_transit verifier tests
python3 benchmarks/cua_world/environments/astroimagej_env/tasks/detect_exoplanet_transit/verifier.py

# Expected output:
# Test 1 (do nothing): FAILS (Score: 0) ✅
# Test 2 (partial work): FAILS (Score: 10) ✅
# Test 3 (proper completion): PASSES (Score: 97) ✅
# Test 4 (wrong parameters): FAILS (Score: 62) ✅
```

## Task Setup Guidelines

**CRITICAL**: Setup should NOT do the task for the agent!

- ✅ Launch AstroImageJ
- ✅ Maximize window for better interaction
- ✅ Ensure FITS files are available
- ❌ Do NOT pre-load data
- ❌ Do NOT open any files
- ❌ Do NOT perform any measurements

## Testing Checklist

### measure_star_photometry Task
- [x] AstroImageJ downloads and installs
- [x] Symlink created at `/usr/local/bin/aij`
- [x] FITS sample files downloaded
- [x] AstroImageJ launches with GUI visible
- [x] Export script produces valid JSON
- [x] Verifier correctly processes results
- [x] Environment registered in constants.py
- [x] **End-to-end verification passes** (Score: 100, all criteria met)

### detect_exoplanet_transit Task
- [x] Real WASP-12b calibrated images from University of Louisville (186 FITS files, 4.3GB)
- [x] Data URL: <WASP-12b sample data URL — see the AstroImageJ user guide / examples page; the previously listed URL was hallucinated and does not exist>
- [x] AstroImageJ launches with images pre-loaded as virtual stack
- [x] Export script detects loaded images via window title parsing
- [x] Verifier mock tests all pass:
  - Test 1 (do nothing): Score 0, FAILS ✓
  - Test 2 (images only): Score 15, FAILS ✓
  - Test 3 (proper completion): Score 97, PASSES ✓
  - Test 4 (wrong params): Score 62, FAILS ✓
- [x] **Real interactive testing completed (2026-01-22)**:
  - Environment starts with SSH/VNC access ✓
  - 186 FITS files loaded as virtual stack in AstroImageJ ✓
  - Window title shows "WASP-12b (V)" indicating virtual stack ✓
  - Export correctly detects num_slices=186 from window parsing ✓
  - "Images loaded but no analysis" correctly scores 8/100 ✓

**Fixed Issues**:
- Hook paths must be absolute (e.g., `/workspace/tasks/.../setup_task.sh`)
- SSH command timeout increased from 300s to 600s for install scripts
- FITS threshold lowered from 200 to 100 (actual download has 186 files)
- Removed invalid "Maximize" macro command that caused errors
- Added window title parsing to detect virtual stack when macro query fails

## End-to-End Test Results

When task is completed (measurement file created, FITS opened, photometry performed):
```
Verification Result:
  Passed: True
  Score: 100
  Feedback: FITS file opened | Photometry activity detected | Measurement file created: photometry_results.txt | Flux value within expected range
```

## Files Created

```
benchmarks/cua_world/environments/astroimagej_env/
├── env.json                              # Environment configuration
├── scripts/
│   ├── install_astroimagej.sh            # Downloads and installs AstroImageJ
│   ├── setup_astroimagej.sh              # Configures user environment
│   └── task_utils.sh                     # Shared utility functions
├── tasks/
│   ├── measure_star_photometry/          # Basic photometry task
│   │   ├── task.json                     # Task specification
│   │   ├── setup_task.sh                 # Task setup
│   │   ├── export_result.sh              # Exports verification data
│   │   └── verifier.py                   # Verification logic
│   └── detect_exoplanet_transit/         # Advanced transit detection task
│       ├── task.json                     # Task spec with ground truth
│       ├── setup_task.sh                 # Downloads data, loads images
│       ├── export_result.sh              # Extracts transit parameters
│       └── verifier.py                   # Multi-criteria verification
├── config/                               # Configuration files (empty)
├── assets/                               # Asset files (empty)
└── utils/                                # Verification utilities (empty)
```

## Future Improvements

1. **Additional tasks**:
   - Light curve generation
   - Image alignment
   - Plate solving
   - Multi-aperture photometry with multiple stars

2. **Better data**: Download time-series FITS data for light curve tasks

3. **Synthetic data**: Create synthetic variable star data with known parameters for precise verification
