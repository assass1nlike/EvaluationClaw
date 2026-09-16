> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenLCA Environment Creation Notes

## Application Overview
- **OpenLCA** is a free, open-source Life Cycle Assessment (LCA) desktop application
- Built on Eclipse RCP (Java), requires JRE/JDK (bundles its own JRE in 2.x)
- Uses Apache Derby embedded database for storing LCA data
- Workspace directory: `~/openLCA-data-1.4/databases/`
- License: MPL-2.0

## Download Sources
- **Primary**: GreenDelta Nextcloud share at `share.greendelta.com`
  - URL pattern: `https://share.greendelta.com/index.php/s/D1xa3haTiHJdhqt/download?path=%2F{VERSION}&files=openLCA_mkl_Linux_x64_{VERSION}_{DATE}.tar.gz`
  - Filenames include build dates, so exact URLs must be known
  - Binary size: ~553MB (includes bundled JRE and Intel MKL libraries)
- **SourceForge**: Only has versions up to 1.9.0 (do NOT use for 2.x)
- **GitHub (GreenDelta/olca-app)**: Source code only, no release binaries

## USLCI Database
- Real U.S. Life Cycle Inventory data from NREL
- Available from GitHub: `https://github.com/FLCAC-admin/uslci-content`
- JSON-LD format for import into OpenLCA
- File size: ~9MB (zip)

## Key Learnings
1. **SourceForge redirects don't work with simple wget** - SourceForge does JavaScript-based redirects that wget can't follow. Use `curl -L` or GreenDelta Nextcloud instead.
2. **LCIA methods from Figshare** - agdatacommons.nal.usda.gov is behind AWS WAF (blocks wget/curl). Use `ndownloader.figshare.com/files/46211520` for TRACI v2.1, which redirects to presigned S3 URLs. `curl -L` handles this correctly.
3. **OpenLCA 2.x bundles its own JRE** - No need to install Java separately, but having system JDK helps with debugging tools.
4. **Derby databases are directories** - Each database in OpenLCA is a directory under `~/openLCA-data-1.4/databases/`. Verification can check for directory existence and size.
5. **Java GUI startup is slow** - OpenLCA takes 30-60 seconds to fully launch. Task scripts need generous timeouts.

## Tasks Created
1. **import_uslci_database** (easy): Create database, import USLCI data from JSON-LD zip
2. **create_product_system** (medium): Create product system from electricity process
3. **calculate_carbon_footprint** (hard): Run LCIA calculation and export results

## Verification Strategy
- Hybrid approach: programmatic checks (file/DB state) + VLM checks (trajectory + final screenshot)
- export_result.sh gathers state into /tmp/task_result.json
- verifier.py uses copy_from_env to read results on host
- Partial credit via fractional criteria_met scores (0.5 for partial completion)

## Interactive Testing Results (2026-02-12)
- **VM boot**: ~114 seconds (including 553MB download from GreenDelta Nextcloud)
- **OpenLCA 2.6.0**: Successfully installed at `/opt/openlca/openLCA/`
- **USLCI database**: Successfully downloaded (9.1MB) and placed in user's LCA_Imports
- **Desktop**: GNOME desktop working, OpenLCA shortcut visible
- **Key issue found**: `runner.exec()` returns `int` (not tuple). Use `runner.exec_capture()` for output.
- **Key issue found**: `env.reset()` returns `dict` (not `(obs, info)` tuple).
- Evidence docs directory was removed (contained misleading auto-generated screenshots).

## Framework API Notes
- `from_config("benchmarks/cua_world/environments/openlca_env")` - loads env config
- `env.reset()` - returns `dict` with key `screen`
- `env._runner.exec(cmd)` - returns `int` (return code only)
- `env._runner.exec_capture(cmd)` - returns `str` (stdout)
- `env._runner.copy_from(src, dst)` - copies file from VM to host
- Hooks are executed via: `sudo -E bash -lc {hook_cmd} > /home/ga/env_setup_*.log 2>&1`
