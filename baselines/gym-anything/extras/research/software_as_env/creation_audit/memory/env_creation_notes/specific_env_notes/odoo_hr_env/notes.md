> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Odoo HR Environment Notes

## Status: FULLY VERIFIED 2026-02-23, UPDATED 2026-03-15

## Fixes Applied (2026-03-15)
- **ImageMagick PDF policy**: Ubuntu default policy blocks `convert` from generating PDFs. Fixed in `install_odoo.sh` by updating `/etc/ImageMagick-6/policy.xml`.
- **Missing seed task**: `approve_leave_request` listed in `seed_tasks.json` but directory doesn't exist. Replaced with `adjust_approve_allocation`.
- **Duplicate comment**: Removed duplicate Docker Hub auth comment in `install_odoo.sh`.

## Stack
- Docker Compose: `postgres:15` + `odoo:17` (CE)
- Modules: `hr,hr_holidays,hr_expense,hr_recruitment`
- DB name: `odoo_hr`; admin creds: `admin`/`admin`
- Web port: 8069

## CRITICAL: Use Odoo Official Demo Data (NOT synthetic data)
- Remove `--without-demo all` from the Odoo init command to use bundled demo data
- Odoo 17 CE ships `hr/data/hr_demo.xml` and `hr_holidays/data/hr_holidays_demo.xml`
- This provides **20 real demo employees**, 7 departments, 7 job positions, 4 employee tags,
  5 leave types, and leave allocations — all official Odoo sample data

**Init command (correct)**:
```bash
docker compose run --rm --no-deps odoo odoo \
    -d odoo_hr \