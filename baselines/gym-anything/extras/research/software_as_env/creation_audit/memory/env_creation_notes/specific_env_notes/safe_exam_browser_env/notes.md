> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Safe Exam Browser Server Environment - Creation Notes

## Key Discovery: No Linux SEB Client
Safe Exam Browser (SEB) has no official Linux client. The desktop clients only exist for Windows and macOS.
The Linux-compatible component is **SEB Server** - a Java Spring Boot web application for exam administration.
SEB Server runs via Docker (MariaDB + Java app) and provides a web UI at port 8080.

## SEB Server Docker Setup

### Image: anhefti/seb-server:v2.2-stable
- Requires MariaDB 10.5 backend
- Demo profile: `spring_profiles_active=bundled,demo`
- Demo includes ETH Zürich institution, Testing/Mock LMS with sample quizzes

### Critical: SPS Environment Variables
SEB Server v2.2-stable requires Screen Proctoring Service (SPS) variables even if SPS is not used:
```yaml
- sps_sebserver_client_secret=sebserver123
- sps_sebserver_password=sebserver123
- sebserver_webservice_autologin_url=http://localhost
- sebserver_feature_exam_seb_screenProctoring_bundled_url=http://localhost:8090
```
Without these, the server fails to start with: `Could not resolve placeholder 'sps.sebserver.client.secret'`

### HTTP Readiness Check
- Root endpoint `/` returns 401 (authentication required)
- Use `/gui` endpoint which returns 200 for readiness polling
- Alternatively accept 401 on root as "server is running"

## Bash Heredoc Issues with Python
Embedding Python code in bash via `python3 << 'PYEOF'` caused issues with SQL queries containing single quotes.
**Solution**: Create a standalone `.py` script file and call it from bash: `python3 /workspace/data/record_baseline.py "$task_name"`

## Docker Permission Fix
The `ga` user needs docker config directory: `mkdir -p /home/ga/.docker && chown -R ga:ga /home/ga/.docker`

## Stale Temp Files
Task setup scripts must clean up `/tmp/` files from previous runs that may have different ownership:
```bash
sudo rm -f /tmp/task_start_time.txt /tmp/seb_task_baseline_*.json /tmp/*_result.json
```

## Timing
- First boot (install + setup): ~280s total
  - pre_start (install Docker, pull images): ~200s
  - post_start (docker compose up, seed data, Firefox setup): ~80s
- Cached boot (loadvm + post_start + pre_task): ~120s
- Task setup (pre_task): ~35s (mostly Firefox login + screenshot)

## Database Schema (Useful Tables)
- `configuration_node` - Exam configurations (type='EXAM_CONFIG')
- `seb_client_configuration` - Connection configurations
- `user` - User accounts
- `user_role` - Role assignments
- `exam_template` - Exam templates
- `exam` - Imported/managed exams
- `indicator` - Monitoring indicators (linked to exam or exam_template)
- `lms_setup` - LMS connections (Testing/Mock LMS in demo)

## Verifier Pattern
Each verifier uses `copy_from_env` to get `/tmp/<task>_result.json` from the VM, then evaluates criteria with weighted scoring. All verifiers correctly return low scores (20-30) for do-nothing tests (only timestamp + Firefox running pass).
