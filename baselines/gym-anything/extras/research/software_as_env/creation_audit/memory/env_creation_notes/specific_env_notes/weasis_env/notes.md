> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Weasis DICOM Viewer Environment Notes

## Overview

Weasis is a free, open-source DICOM viewer for medical images. It's used by healthcare professionals to view X-rays, CT scans, MRIs, and other medical imaging formats.

## Installation

### Primary Method: Snap
```bash
sudo snap install weasis
```

### Alternative: Native DEB Package
```bash
WEASIS_VERSION="4.5.1"
wget "https://github.com/nroduit/Weasis/releases/download/v${WEASIS_VERSION}/weasis_${WEASIS_VERSION}-1_amd64.deb"
dpkg -i weasis_${WEASIS_VERSION}-1_amd64.deb
```

## Key Learnings

### 1. DICOM File Generation
- If sample DICOM files are unavailable, synthetic files can be generated using `pydicom`
- Important DICOM attributes: PatientName, PatientID, Modality, StudyDescription, WindowCenter, WindowWidth
- Window Center/Width values control contrast display (CT typically: WC=40, WW=400)

### 2. Snap vs Native Installation
- Snap uses sandboxed environment: `~/snap/weasis/current/.weasis` for config
- Native installation uses: `~/.weasis` for config
- Scripts should check for both locations

### 3. Verification Challenges
- Weasis doesn't have a simple CLI for querying state
- Verification relies on:
  - Window title changes (shows patient info when DICOM loaded)
  - Screenshot comparison (visual changes)
  - Log file analysis
  - File access timestamps

### 4. Sample DICOM Data Sources
- Rubo Medical: https://www.rubomedical.com/dicom_files/
- OsiriX Image Library: https://www.osirix-viewer.com/resources/dicom-image-library/
- Synthetic generation via pydicom (when network unavailable)

## Tasks

| Task | Description | Verification Method |
|------|-------------|-------------------|
| open_dicom | Open a DICOM file | Window title change, file access |
| adjust_window_level | Adjust contrast/brightness | Screenshot diff |
| zoom_image | Magnify the image | Screenshot diff |
| take_snapshot | Export image as PNG/JPG | Check exports directory |
| view_metadata | View DICOM tags | Window detection |

## Resource Requirements

- CPU: 4 cores
- Memory: 8 GB (medical images can be large)
- GPU: Not required (but helps with volume rendering)
- Network: Required for downloading sample DICOM files

## Common Issues

### Issue: Weasis won't start
**Solution**: Check if snap is properly initialized:
```bash
systemctl enable snapd.socket
systemctl start snapd.socket
sleep 5
snap install weasis
```

### Issue: No DICOM samples available
**Solution**: Generate synthetic DICOM files using pydicom (see setup_weasis.sh)

### Issue: Verification fails for window/level changes
**Solution**: Use screenshot comparison - visual changes are the most reliable indicator

## File Structure

```
benchmarks/cua_world/environments/weasis_env/
├── env.json                 # Environment configuration
├── scripts/
│   ├── install_weasis.sh    # Pre-start hook (installation)
│   ├── setup_weasis.sh      # Post-start hook (configuration)
│   └── task_utils.sh        # Shared shell utilities
├── config/                   # Configuration files
├── tasks/
│   ├── open_dicom/          # Open DICOM file task
│   ├── adjust_window_level/ # Adjust contrast task
│   ├── zoom_image/          # Zoom task
│   ├── take_snapshot/       # Export image task
│   └── view_metadata/       # View DICOM tags task
├── utils/
│   ├── __init__.py
│   └── weasis_verification_utils.py
└── assets/                   # Runtime assets
```

## Future Improvements

1. Add PACS connectivity tasks (connect to DICOM server)
2. Add measurement/annotation tasks
3. Add multi-frame/series navigation tasks
4. Add window preset tasks (lung, bone, brain presets)
5. Add image comparison tasks (side-by-side viewing)
