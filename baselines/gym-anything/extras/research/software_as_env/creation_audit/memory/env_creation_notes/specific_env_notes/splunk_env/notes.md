> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Splunk Enterprise Environment Notes

## Installation Quirks

### Splunk Download
- Splunk Enterprise requires a ~920 MB .deb download from `download.splunk.com`
- The download URL includes a build hash that changes per version: `splunk-9.4.0-6b4ebe426ca6-linux-amd64.deb`
- No authentication is needed for the direct download URL if you have the full URL with hash
- The URL can be found in public GitHub repositories and Dockerfiles

### First Start
- First start must use `--accept-license --answer-yes --no-prompt --seed-passwd` flags
- Alternatively, pre-seed credentials via `/opt/splunk/etc/system/local/user-seed.conf`
- Splunk auto-deletes `user-seed.conf` after first start
- First start generates SSL certificates and takes about 30-60 seconds

### Pre-seeding Credentials
```
[user_info]
USERNAME = admin
PASSWORD = SplunkAdmin1!
```

## Service Timing Issues

### REST API vs Web UI
- The web UI (port 8000) becomes available before the REST API (port 8089)
- The REST API uses self-signed SSL, requiring `curl -sk` (skip cert verification)
- Wait for web UI first (HTTP 200/302/303), then wait for REST API
- Do NOT use `set -e` in setup scripts - curl with `-k` flag can return non-zero even on success

### Data Ingestion Timing
- `splunk add oneshot` is asynchronous - the command returns before indexing completes
- Wait at least 15 seconds after all oneshot commands before verifying event counts
- Large files (>50 MB) may take longer to index

## Data Download Reliability
- Some public data sources may return 403 or be temporarily unavailable
- Always use `set +e` during download section and validate file sizes
- Implement fallback: use the VM's own system logs if external downloads fail
- The Zenodo/Loghub datasets are the most reliable download sources

## Verification Strategy

### REST API Verification
- All verification uses the REST API on port 8089
- Always use `output_mode=json` parameter
- Use temp files for curl output, not pipe + heredoc (incompatible)
- Pattern: `curl > tempfile; python3 - tempfile << 'EOF' ... EOF`

### Search Job Detection
- Search jobs are accessible via `/services/search/jobs`
- Jobs expire after a configurable TTL (default ~10 minutes for ad-hoc searches)
- Compare job counts before/after to detect agent activity
- Match search queries by content (index name, keywords) not exact string

### Saved Search/Alert Detection
- Saved searches/alerts listed via `/servicesNS/-/-/saved/searches`
- Detect new alerts by comparing names before/after task
- Check `is_scheduled`, `cron_schedule`, `alert_type` fields for alert properties
- The pre-created `Failed_SSH_Logins` saved search exists as a demo

### Monitor Input Detection
- File monitors listed via `/services/data/inputs/monitor`
- Also check `inputs.conf` files as fallback
- Monitor names include the full path (e.g., `/var/log/kern.log`)

## Common Gotchas

1. **JSON parsing in bash**: Never use `echo "$VAR" | python3 << 'HEREDOC'` - heredoc and pipe are incompatible for stdin. Use temp files instead.
2. **set -e with curl**: `curl -sk` may return non-zero exit codes with self-signed certs. Avoid `set -e` or use `|| true`.
3. **Splunk CLI auth**: Most CLI commands need `-auth admin:password` flag.
4. **Index creation**: `splunk add index` is idempotent - safe to run multiple times.
5. **Firefox profile**: Must create `profiles.ini` and `user.js` before first Firefox launch to prevent first-run dialogs.

## Audit Fixes (2024)

### Task Start State
- **Issue**: Task start screenshot showed desktop without Firefox/Splunk visible
- **Fix**: Added `ensure_firefox_with_splunk()` function in task_utils.sh that:
  - Checks if Firefox is running, launches if not
  - Waits for Firefox window to appear with Splunk in title
  - Focuses and maximizes Firefox window
  - Refreshes page if Splunk not detected
  - Called in all setup_task.sh scripts before taking screenshot

### Verifier Strictness
- **Issue**: Verifiers were too lenient and could be gamed with minimal valid work
- **Fixes**:
  - search_security_events: Now requires ALL of: security_logs index, Failed keyword, meaningful results, completed status
  - create_alert: Now requires exact name "Brute_Force_Detection", exact cron "*/5 * * * *"
  - add_data_source: Now requires exact path "/var/log/kern.log", exact index "system_logs" (not "main")
  - All verifiers changed from "3 of 4 criteria" to "ALL criteria required"
