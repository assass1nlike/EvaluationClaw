> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# SciNote Environment Notes

## Application Overview
- **SciNote**: Open-source Electronic Lab Notebook (ELN)
- **Tech Stack**: Ruby on Rails, Vue.js, PostgreSQL 15
- **Port**: 3000 (Rails server)
- **Repository**: https://github.com/scinote-eln/scinote-web (develop branch)
- **Default Admin**: admin@scinote.net / inHisHouseAtRlyehDeadCthulhuWaitsDreaming

## Architecture
- Docker Compose with 3 services: db (postgres:15), web (Rails), jobs (background worker)
- Dockerfile.production uses BuildKit `--mount=type=cache` syntax
- Requires Docker official repo (docker-ce + docker-buildx-plugin + docker-compose-plugin)
- `docker.io` package does NOT include buildx, so the build will fail

## Data Model
- **Teams** → **Projects** → **Experiments** → **Tasks (my_modules)**
- **Protocols**: types 0-1 are task-level, types 2-7 are repository-level
  - 0=unlinked, 1=linked, 2=private, 3=public, 4=archived, 5=published_original, 6=draft, 7=published_version
- **Repositories** (Inventories) → **Repository Rows** (items)
- Seed data creates: 1 project ("SciNote Examples"), 9 experiments, 56 tasks, 56 protocols (all type 0)

## Key Learnings

### Docker Setup
- Must use Docker official repo (not docker.io) for BuildKit support
- SECRET_KEY_BASE and PAPERCLIP_HASH_SECRET must be alphanumeric-only (no $, {, } characters)
- Dollar signs in docker-compose env vars cause variable interpolation errors

### Firefox Profile
- Use `default-release` profile name with `[Install4F96D1932A9F858E]` section (matches other envs)
- Launch Firefox WITHOUT `-profile` flag: `su - ga -c "DISPLAY=:1 firefox 'URL' > /tmp/firefox.log 2>&1 &"`
- The `-profile` flag causes "Profile Missing" dialog when profile was created by root

### SQL vs Rails Runner
- `scinote_rails_query` (Rails runner via docker exec) has severe quoting issues with single quotes
- Use SQL INSERT/SELECT via `scinote_db_query` instead for setup scripts
- Required NOT NULL columns per table:
  - **projects**: name, visibility, team_id, created_at, updated_at, archived, demo, due_date_notification_sent
  - **experiments**: name, project_id, created_by_id, last_modified_by_id, archived, due_date_notification_sent, created_at, updated_at
  - **my_modules**: name, x, y, experiment_id, created_at, updated_at, archived, workflow_order
  - **protocols**: team_id, protocol_type, created_at, updated_at, archived
  - **repositories**: created_by_id, permission_level, archived, repository_rows_count

## Tasks Created

| Task | Difficulty | Expected Objects | Verifier Criteria |
|------|-----------|-----------------|-------------------|
| create_project | easy | "Protein Crystallization Study" project | name match, count increase, valid ID |
| create_experiment | easy | "HPLC Analysis Run 3" in "Drug Discovery Pipeline" | name match, correct project, count increase, valid ID |
| add_task_to_experiment | medium | "Run Mass Spec Calibration" in "LC-MS Compound Screening" | name match, correct experiment, count increase, correct project |
| create_protocol | medium | "Western Blot Analysis v2" in protocol repository | name match, count increase, valid ID |
| create_inventory_item | medium | "Lab Reagents" inventory + "Tris-HCl Buffer pH 7.4" item | inventory name, count increase, item name, row count increase |

## Verification Results

All 5 tasks verified:
- Baseline (no action): score = 0
- After simulated completion: score = 100

## Build Time
- Docker image build: ~5-6 minutes
- Total setup (install + build + DB seed + Firefox): ~90 seconds (with pre-built image)
- First-time install + build: ~10-15 minutes
- Clean env.reset() time (no cache): ~641 seconds (pre_start + post_start hooks)
- Task-specific hook time: ~4 seconds

## End-to-End Test Results
- Clean `env.reset(seed=42, use_cache=False)` + `env.step([], mark_done=True)` tested successfully
- SciNote HTTP 200, all 3 Docker containers running, Firefox shows login page
- Baseline verification: score=0 (correct)
- Evidence screenshots and logs saved in `evidence_docs/`
