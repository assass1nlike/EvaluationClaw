> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# SuiteCRM Environment Notes

## Application Details
- **Version**: SuiteCRM 7.14.6 (NOT 8.x - 8.x has Docker deployment bugs)
- **Architecture**: Docker-in-QEMU with php:8.1-apache-bookworm + mariadb:10.11
- **Port**: 8000 (mapped to container port 80)
- **Admin credentials**: admin / Admin1234!

## Installation Quirks

### Pre-built Release ZIP vs Source Archive
**CRITICAL**: GitHub source archives (`/archive/refs/tags/`) do NOT include the `vendor/` directory. This causes "Composer autoloader not found" errors.

**Solution**: Use the pre-built release ZIP from GitHub Releases:
```
https://github.com/salesagility/SuiteCRM/releases/download/v7.14.6/SuiteCRM-7.14.6.zip
```
This ZIP includes the full `vendor/` directory with all Composer dependencies pre-installed.

### Silent Install
- PHP CLI install (`php -r '...; require_once "install.php";'`) fails with "Bad data passed in"
- **Working approach**: curl fallback — `curl http://localhost:8000/install.php?goto=SilentInstall&cli=true`
- Requires `config_si.php` placed in webroot before calling
- Wait 30 seconds after curl for install to complete
- Always verify `config.php` was created after install

### Permissions
After install, must fix permissions:
```bash
chmod -R 775 cache/ custom/ modules/ upload/
chmod 775 config.php config_override.php .htaccess
chown -R www-data:www-data /var/www/html
```

## Service Timing
- MariaDB: Ready almost instantly from cache (healthcheck: `mysqladmin ping`)
- SuiteCRM web: Takes ~20s to respond after Docker Compose starts
- Firefox: Takes 12+ seconds to fully render SuiteCRM login page (JS-heavy)

## Data Seeding
- Uses SugarBean API via PHP script (`BeanFactory::newBean()` + `$bean->save()`)
- Must `include 'include/entryPoint.php'` to bootstrap SuiteCRM framework
- Total: 82 records (20 accounts, 20 contacts, 14 opportunities, 12 cases, 7 meetings, 8 calls)
- All accounts are real Fortune 500 companies with real phone numbers and addresses

## Login Coordinates (1920x1080)
Calibrated via visual_grounding MCP tool:
- Username field: (995, 480)
- Password field: (995, 539) — or just Tab from username
- LOG IN button: (995, 597)
- With "session expired" banner: fields shift ~30px down

## GUI Automation Gotchas

### xdotool must run as `ga` user
When setup_task.sh runs via `sudo bash` (root), xdotool commands using `DISPLAY=:1` can't reliably interact with Firefox windows owned by `ga` user.

**Solution**: Use `run_as_ga()` helper that wraps commands in `su - ga -c "export DISPLAY=:1; ..."`:
```bash
run_as_ga() {
    if [ "$(whoami)" = "ga" ]; then
        eval "$@"
    else
        su - ga -c "export DISPLAY=:1; $*"
    fi
}
```

### xdotool commands must be in single shell session
Separate `ssh.exec_command()` calls for sequential xdotool operations lose display focus between commands. The navigation URL bar interaction (Ctrl+L, Ctrl+A, type URL, Enter) must all run in ONE shell session.

### --clearmodifiers flag
Always use `xdotool type --clearmodifiers` to avoid stuck modifier keys affecting typed text.

### Page load times
SuiteCRM pages are JS-heavy. After `xdotool key Return` for URL navigation, wait at least 8-10 seconds for the page to fully render.

## Firefox (snap) Notes
- Snap Firefox does NOT support `-profile` flag
- Warm-up launch (`firefox --headless`) creates default profile
- Inject `user.js` into the profile directory at `~/snap/firefox/common/.mozilla/firefox/*.default*/`
- Key user.js preferences: disable first-run, set homepage to localhost:8000, disable telemetry

## Docker Compose
- Must use Docker Compose v2 plugin (`docker compose`), NOT v1 (`docker-compose`)
- v1 causes `KeyError: 'ContainerConfig'` errors
- Install v2 plugin: download binary to `/usr/local/lib/docker/cli-plugins/docker-compose`

## Task Structure
Each task's `setup_task.sh`:
1. Sources `task_utils.sh` for shared functions
2. Records initial count of target entity type
3. Soft-deletes any pre-existing target record (idempotent)
4. Calls `ensure_suitecrm_logged_in()` with target module URL
5. Takes initial screenshot

## API Notes
- `from_config()` task_id is the directory name (e.g., `create_account`), NOT the task.json `id` field
- Runner attribute: `env._runner.ssh_port` (no underscore prefix)
- Boot pattern: `use_cache=True, cache_level='pre_start', use_savevm=True`
