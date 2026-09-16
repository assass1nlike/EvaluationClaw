> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Vtiger CRM Environment - Creation Notes

## Overview
- **Application**: Vtiger CRM 8.3.0 (open source)
- **Architecture**: Docker-in-QEMU (MariaDB 10.11 + PHP 8.1/Apache)
- **Base VM**: ubuntu-gnome-systemd_highres (4 CPU, 8GB RAM)
- **Port**: 8000 (HTTP), mapped from container port 80
- **Credentials**: admin / password

## Key Implementation Decisions

### Docker Image
- Base: `php:8.1-apache-bookworm` (NOT default which uses Trixie)
  - Trixie lacks `libc-client-dev`, needed for IMAP extension
  - Also need `libonig-dev` for mbstring extension
- PHP extensions: gd, imap, mysqli, pdo_mysql, xml, zip, intl, curl, mbstring
- Vtiger 8.3.0 downloaded from SourceForge

### Installation Method
- **Web wizard does NOT work via curl/requests** - CSRF tokens and session state make it unreliable
- **PHP CLI installer works**: Bootstrap Vtiger framework, call `Install_InitSchema_Model::initialize()`, `Install_Utils_Model::installModules()`, `Install_InitSchema_Model::upgrade()`
- Must include `vendor/autoload.php` before any Vtiger includes (Monolog dependency)
- Config created from `config.template.php` via sed substitution

### Password Hashing (CRITICAL)
- Vtiger's `crypt_type: SHA256` does NOT use sha256() hash
- It uses PHP's `crypt($password, $salt)` where `$salt = substr(username, 0, 2)`
- For admin user: `crypt('password', 'ad')` = `advwtv/9yU5yQ`
- The `{SHA256}` prefix format is NOT correct for Vtiger authentication

### Data Seeding
- Uses Vtiger Webservice API (challenge + login + create)
- Access key from `vtiger_users.accesskey` column
- Calendar events require `duration_hours` and `duration_minutes` fields (mandatory)
- Successfully seeds: 15 orgs, 20 contacts, 10 products, 12 deals, 8 tickets, 5 events

### Firefox Setup
- Snap Firefox on Ubuntu: warm-up headless launch to create default profile
- user.js injection for homepage, telemetry suppression, etc.
- Login coordinates at 1920x1080 (calibrated via visual_grounding MCP tool):
  - Username field: (464, 404) — from (309, 269) in 1280x720
  - Password field: use Tab from username (more reliable than coordinate click)
  - Sign In: use Enter key (more reliable than coordinate click)
- Firefox needs 12+ seconds after launch to fully render the JS-heavy login page
- After first login, Vtiger redirects to SystemSetup page (dismissed by navigating to index.php)

### Vtiger Permissions (CRITICAL)
- After schema installation, must chmod 777 these directories for Apache (www-data) access:
  - `test/templates_c/` — Smarty template cache (causes 500 without write permission)
  - `cache/` and `cache/logs/` — application cache
  - `storage/` — file storage
  - `logs/` — application logs
- Without this fix, Vtiger returns HTTP 500 with no error message (Smarty write failure)

## Timing
- pre_start (install Docker, Firefox, tools): ~67s (cached as checkpoint)
- post_start (build image, install schema, seed data, setup Firefox): ~204s
- pre_task (login + navigate to module + screenshot): ~25s
- Total from pre_start cache: ~229s

## File Structure
```
benchmarks/cua_world/environments/vtiger_crm_env/
  env.json                          # Main config
  config/
    Dockerfile                      # PHP 8.1 + Vtiger 8.3.0
    docker-compose.yml              # MariaDB + Vtiger app
    entrypoint.sh                   # Wait for DB, start Apache
  scripts/
    install_vtiger.sh               # pre_start: install Docker, Firefox
    setup_vtiger.sh                 # post_start: build, install, seed, login
    task_utils.sh                   # Shared: DB queries, Firefox helpers
  utils/
    seed_data.php                   # Webservice API data seeder
  data/
    seed_vtiger_data.sql            # Placeholder (seeding via PHP)
  tasks/
    create_contact/                 # Create Nathan Blackwood
    create_organization/            # Create Redwood Consulting Partners
    create_deal/                    # Create DataForge Enterprise deal
    create_ticket/                  # Create API gateway ticket
    schedule_calendar_event/        # Schedule GreenLeaf kickoff meeting
```

## Bugs Encountered & Fixes
1. `libc-client-dev` not found on Trixie -> use `php:8.1-apache-bookworm` + `libc-client2007e-dev`
2. `libonig-dev` missing for mbstring -> add to Dockerfile apt-get
3. Curl-based installer fails (CSRF tokens) -> PHP CLI installer
4. Monolog not found -> include vendor/autoload.php first
5. Password hash mismatch -> use crypt() not sha256()
6. Calendar events missing duration_hours -> add mandatory fields
7. /tmp permission denied in setup_task.sh -> rm -f before write + chmod 666 after
8. Smarty template write failure (HTTP 500) -> chmod 777 test/templates_c, cache, storage dirs
9. Firefox caching 500 error page -> needs restart after permissions fix
10. Login coordinates off -> calibrated via visual_grounding MCP tool; use Tab/Enter for reliability
11. Post-start auto-login unreliable -> added `ensure_vtiger_logged_in()` to task_utils.sh; pre_task hooks always perform fresh login before navigating to target module
