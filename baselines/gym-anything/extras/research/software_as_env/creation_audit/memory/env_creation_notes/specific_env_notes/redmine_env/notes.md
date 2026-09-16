> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Redmine Env Notes

## Architecture
- Docker-in-QEMU: `redmine:6.0-bookworm` + `postgres:16`, port 3000
- Docker Compose v2 (`docker-compose-v2` package, NOT `docker-compose-plugin`)
- Admin: `admin` / `Admin1234!`
- 5 tasks: create_bug_issue, update_issue_status, add_issue_comment, close_issue, log_time_on_issue

## Installation
- `docker-compose-v2` (not plugin) on Ubuntu 22.04 Jammy
- `SECRET_KEY_BASE` must be passed explicitly to `docker exec` for Rails rake tasks
- Seed via Ruby: `docker exec -i redmine-redmine-1 bundle exec rails runner -`

## Seeding
- `seed_redmine.rb` seeds via Redmine Ruby models (not REST API)
- Creates: 7 users, 3 projects, versions, categories, 23 issues, journals, time entries
- **CRITICAL**: Versions must be created 'open', then closed AFTER all issues are assigned to them
  - Redmine validation: cannot assign issues to closed versions
  - Fix: Section 9 in seed_redmine.rb closes versions at the end
- Seed result JSON saved to `/tmp/redmine_seed_result.json` and `/home/ga/redmine_seed_result.json`
- `jq` used in task_utils.sh to look up issue IDs by subject fragment

## Firefox Launch (CRITICAL)
- Firefox is a SNAP package; requires explicit env vars to launch:
  ```bash
  DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority XDG_RUNTIME_DIR=/run/user/1000 \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus firefox URL
  ```
- Use `su - ga -c "...firefox..."` from root hook context (loads login shell environment)
- Post_start warm-up: Firefox launched during setup_redmine.sh to initialize snap profile
- Snap profile dir: `/home/ga/snap/firefox/common/.mozilla/firefox/default.profile/`
- Clear locks from BOTH regular and snap paths in `clear_firefox_profile_locks()`

## Login Mechanism
- `ensure_redmine_logged_in(target_url)` in `task_utils.sh`:
  1. Stops Firefox, clears locks
  2. Launches Firefox at login URL via `su - ga -c "...firefox..."`
  3. Waits for Firefox window
  4. Uses xdotool (from root context with XAUTHORITY) to fill login form
     - Username field: (996, 398) in 1920x1080
     - Password field: (996, 467) in 1920x1080
     - Press Return to submit
  5. Waits 6s for login redirect
  6. Navigates to target URL via Ctrl+L address bar
- **Key finding**: xdotool works from root (`sudo bash -c`) when XAUTHORITY=/home/ga/.Xauthority is set
- **Cookie injection does NOT work**: `_redmine_session` is a Rails session cookie (stored in memory by browser, NOT persisted to cookies.sqlite)

## Session Cookie (Why Injection Fails)
- Redmine's `_redmine_session` is a non-persistent session cookie
- Firefox keeps it in memory only, not in cookies.sqlite
- Injecting into cookies.sqlite with expiry doesn't work because Rails session verification fails
- Solution: Use xdotool GUI login instead

## Task Execution Times (from post_start cache)
- VM boot + file copies: ~28s
- pre_task hook (Firefox + login + navigate): ~29s
- Total: ~57s per task reset

## Data
- 3 projects: phoenix-ecommerce, mobile-app-v2, infra-devops
- 7 non-admin users: alice.chen, bob.walker, carol.santos, david.kim, eve.martinez, frank.nguyen, grace.lee
- 23 issues across all projects
- Key issues for tasks:
  - #11: Biometric authentication (Status=New) → update_issue_status
  - #13: Offline mode (Status=New) → log_time_on_issue
  - #18: CI/CD migration (Status=In Progress) → add_issue_comment
  - #22: SSL certificate (Status=Resolved) → close_issue
