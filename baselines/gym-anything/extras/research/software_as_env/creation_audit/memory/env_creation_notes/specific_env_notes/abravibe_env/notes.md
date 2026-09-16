> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# ABRAVIBE Environment Notes

## Application Details
- **ABRAVIBE**: MATLAB/Octave toolbox for noise and vibration analysis
- **Author**: Anders Brandt (University of Southern Denmark)
- **License**: GNU Public License
- **Official site**: abravibe.com
- **MATLAB File Exchange**: ID 68508
- **Python port**: github.com/adessein/pyabravibe

## Installation Approach
- ABRAVIBE is distributed as .m files on MATLAB File Exchange (requires auth to download)
- We bundle the core ABRAVIBE functions (13 .m files) directly in the environment's `data/abravibe_toolbox/` directory
- Functions are standard signal processing algorithms, reimplemented based on the pyabravibe Python port and textbook definitions
- Installed to `/usr/share/octave/site/m/abravibe/` in the VM

## ABRAVIBE Functions Included
| Function | Description |
|----------|-------------|
| `ahann` | Hanning window |
| `aflattop` | Flat-top window (ISO 18431-2) |
| `makexaxis` | Create time/frequency axis |
| `alinspec` | Linear RMS spectrum (Welch's method) |
| `alinspecp` | Linear spectrum with phase |
| `apsd` | Power spectral density |
| `acsd` | Cross spectral density |
| `afrf` | FRF estimation (H1/H2 estimator) |
| `mck2frf` | FRF from mass/damping/stiffness matrices |
| `mck2modal` | Modal analysis from M,C,K matrices |
| `amac` | Modal Assurance Criterion |
| `amif` | Mode Indicator Function |
| `timeint` | Time domain integration with HP filter |

## Data: CWRU Bearing Dataset
- Source: Case Western Reserve University Bearing Data Center
- Downloaded from GitHub mirror: `github.com/s-whynot/CWRU-dataset`
- Format: MATLAB .mat files with accelerometer time series
- Sampling rate: 12,000 Hz
- Variables: `X{NNN}_DE_time` (drive end), `X{NNN}_FE_time` (fan end), `X{NNN}_BA_time` (base), `X{NNN}RPM`

### Files Used
| File | Condition | Fault Size | Samples |
|------|-----------|-----------|---------|
| `normal_97.mat` | Normal baseline, 0 HP | N/A | 243,938 |
| `ir007_105.mat` | Inner race fault, 0 HP | 0.007" | 121,265 |
| `ball007_118.mat` | Ball fault, 0 HP | 0.007" | 122,571 |
| `or007_130.mat` | Outer race fault (@6 o'clock), 0 HP | 0.007" | 121,991 |
| `ir021_209.mat` | Inner race fault, 0 HP | 0.021" | 131,072 |

## Octave Quirks
- **First-run wizard**: Suppressed via `.octaverc` + warm-up launch in post_start
- **Graphics toolkit**: Must use `gnuplot` (not `qt`) for off-screen/headless rendering
- **Config paths**: Qt settings at `~/.config/octave/qt-settings/octave-gui.conf`
- **setsid required**: Launch with `setsid` to prevent SIGHUP killing Octave when hook exits
- **Window detection**: Use `xdotool search --name "Octave"` (Octave GUI window has "Octave" in title)

## Timing
- Installation (pre_start): ~75 seconds
- Setup (post_start): ~20 seconds (includes warm-up launch)
- Task setup (pre_task): ~19 seconds
- Total boot-to-ready: ~115 seconds

## Proportional Damping Notes
For the 2-DOF FRF task, proportional damping `C = alpha*M + beta*K` gives modal damping:
```
zeta_i = alpha/(2*omega_i) + beta*omega_i/2
```
With alpha=2, beta=0.0002: both modes get ~2.1% damping (physically realistic for lightly damped metal structures).

Using alpha=0.0001, beta=0.01 gives overdamped behavior (~35-70% damping) - avoid for demonstration purposes.
