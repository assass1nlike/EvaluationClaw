> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# InVesalius 3 Environment Notes

## Installation
- Prefer distro package (`invesalius` or `invesalius3`) when available. If apt packages are missing, fall back to Flatpak (`br.gov.cti.invesalius`) from Flathub.
- The CLI supports importing a DICOM folder via `-i <folder>` (see the `invesalius3` man page). The task setup uses this to pre-load data before the agent starts.

## Sample Data
- Official DICOM test datasets are available from the InVesalius download page (CT Cranium, CT Fox, CT Clavicle, CT Feet, CT Chest, MRI T1).
- This environment downloads the CT Cranium dataset to `/opt/invesalius/sample_data/ct_cranium` and exposes it at `/home/ga/DICOM/ct_cranium`.
- As of Feb 2026, the download page links CT Cranium to the GitHub release asset `v3.0/0051.zip`.

## Notes
- Use `wmctrl` to detect the main window title (`InVesalius`) for readiness checks.
- Flatpak first-run can show a blocking `Language selection` dialog before the main window appears.
  - Dismissing by keyboard tab order was flaky; window-relative `xdotool` clicking the OK button was reliable.
- The sample DICOM series is exposed via a symlink (`/home/ga/DICOM/ct_cranium -> /opt/invesalius/sample_data/ct_cranium`).
  - `find` does not traverse symlinked directories by default; use `find -L` (or a trailing slash) when checking for DICOM files.
- If other startup dialogs appear, send `Escape`/`Return` to dismiss.
