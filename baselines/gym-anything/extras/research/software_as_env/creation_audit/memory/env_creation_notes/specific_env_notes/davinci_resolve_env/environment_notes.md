> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# DaVinci Resolve Environment Notes

## Overview

DaVinci Resolve is a professional video editing, color correction, visual effects, and audio post-production application developed by Blackmagic Design. This environment provides a gym_anything wrapper for automated interaction with DaVinci Resolve on Linux.

## Automatic Installation

The installation script automatically downloads DaVinci Resolve using Blackmagic Design's public API:

1. Fetches latest version info from `https://www.blackmagicdesign.com/api/support/latest-stable-version/davinci-resolve/linux`
2. Registers with the download API to get a direct download URL
3. Downloads and extracts the installer
4. Converts to DEB using MakeResolveDeb for Debian/Ubuntu compatibility
5. Installs the package

No manual download or registration is required.

## Linux Distribution Compatibility

DaVinci Resolve is officially supported only on CentOS/RHEL/Rocky Linux. For Debian/Ubuntu:

- **Solution**: Uses MakeResolveDeb script to convert the .run installer to a .deb package
- **Source**: https://www.danieltufvesson.com/makeresolvedeb

## GPU Requirements

- DaVinci Resolve is heavily GPU-dependent
- NVIDIA GPUs with CUDA are recommended
- OpenCL is required for any GPU acceleration
- Software rendering is possible but very slow

### GPU Support in gym_anything QEMU Runner

The QEMU/Apptainer runner now supports GPU acceleration:

1. **VirGL (3D Rendering)**: When `gpu: 1` is set in env.json:
   - QEMU uses `virtio-vga-gl` for 3D acceleration
   - GUI rendering is accelerated through the host GPU
   - Uses `egl-headless` display backend

2. **OpenCL for Video Processing**:
   - Inside the VM, DaVinci Resolve uses OpenCL for GPU compute
   - With VirGL, only software OpenCL (mesa-opencl-icd) is available
   - This is slower than native GPU but functional

3. **For Full GPU Acceleration**:
   - GPU Passthrough (VFIO) - requires IOMMU and specific hardware
   - Or use Docker runner with `--gpus` flag (not QEMU)

### Host Machine Requirements

For GPU support, the host machine needs:
- `/dev/dri` (DRI/Mesa for Intel/AMD)
- `/dev/nvidia*` (NVIDIA GPU with drivers)

The QEMU runner automatically detects available GPUs and:
- Uses `--nv` Apptainer flag for NVIDIA GPUs
- Binds `/dev/dri` and `/dev/nvidia*` devices
- Reports GPU status at startup

## Free Version Limitations on Linux

- **MP4 Import/Export**: Not supported in the free version
- Use MOV or MKV containers instead
- Studio version ($295) removes this limitation

## Resource Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 4 cores | 8+ cores |
| RAM | 8 GB | 16+ GB |
| GPU | OpenCL compatible | NVIDIA with CUDA |
| Disk | 10 GB | 50+ GB for cache |

## Sample Media

The setup script downloads realistic video files from Creative Commons licensed sources:

### Downloaded Videos (CC-BY 3.0 Blender Foundation)
1. **big_buck_bunny.mov**: Full-length Big Buck Bunny (10 min) - high-quality test footage
2. **sintel_trailer.mov**: Sintel movie trailer - dramatic lighting and color
3. **tears_of_steel.mov**: Tears of Steel trailer - VFX-heavy footage

### Generated Videos
1. **color_bars_reference.mov**: SMPTE color bars (10s) - for calibration reference
2. **color_bars.mov**: 30-second clip from Big Buck Bunny - main task video

### Data Sources
- **Google Sample Videos**: `https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/`
- **Blender Foundation**: `https://download.blender.org/`

All videos are converted to MOV format (libx264 + pcm_s16le) for DaVinci Resolve free compatibility on Linux.

## Task Ideas for Future Development

### Basic Tasks
- [ ] Import media to Media Pool
- [ ] Create new timeline
- [ ] Add clips to timeline
- [ ] Export project as H.264

### Color Grading Tasks
- [x] Basic color correction (lift/gamma/gain)
- [ ] Apply LUT
- [ ] Create Power Window
- [ ] Secondary color correction
- [ ] Match shots across clips

### Editing Tasks
- [ ] Trim clips
- [ ] Add transitions
- [ ] Split clips
- [ ] Reorder timeline clips

### Audio Tasks
- [ ] Adjust volume levels
- [ ] Add audio crossfade
- [ ] Apply EQ
- [ ] Mix multiple audio tracks

### Advanced Tasks
- [ ] Motion tracking
- [ ] Fusion VFX
- [ ] Fairlight audio mixing
- [ ] Multi-cam editing

## Verification Strategies

### 1. File-based Verification
- Check for export file existence
- Verify file size is reasonable
- Verify video duration matches expected

### 2. Metadata Verification
- Check codec information
- Verify resolution matches
- Check frame rate

### 3. Visual Verification (Future)
- Compare histograms of input vs output
- Check for color shift magnitude
- Use VLM to verify visual changes

## Known Issues

### 1. First-run Wizard
- DaVinci Resolve shows welcome screens on first launch
- Configuration in `user.conf` attempts to disable these
- May need manual intervention on first run

### 2. Project Database
- DaVinci Resolve uses its own database system
- Projects are not simple files
- Consider using Project Server for automation

### 3. GPU Detection
- May fail to detect GPU in virtualized environments
- Ensure /dev/dri is properly mounted
- Check OpenCL vendors configuration

## Testing the Environment

```python
from gym_anything.api import from_config

# Start without task first
env = from_config("benchmarks/cua_world/environments/davinci_resolve_env")
obs = env.reset(seed=42, use_cache=False)

# Get connection info
print(f"SSH port: {env._runner.ssh_port}")
print(f"VNC port: {env._runner.vnc_port}")

# SSH in and check logs
# ssh -p <ssh_port> ga@localhost
# cat /home/ga/env_setup_pre_start.log
# cat /home/ga/env_setup_post_start.log
```

## References

- [DaVinci Resolve Official](https://www.blackmagicdesign.com/products/davinciresolve)
- [Blackmagic API for Downloads](https://www.blackmagicdesign.com/api/support/latest-stable-version/davinci-resolve/linux)
- [MakeResolveDeb](https://www.danieltufvesson.com/makeresolvedeb)
- [autoresolvedeb](https://github.com/psygreg/autoresolvedeb)
- [Linux Installation Guide](https://www.dedoimedo.com/computers/davinci-resolve-ubuntu-24-04.html)
