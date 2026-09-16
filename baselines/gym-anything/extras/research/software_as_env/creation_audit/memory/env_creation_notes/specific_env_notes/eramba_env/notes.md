> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Eramba GRC Environment Notes

## Overview
Eramba Community Edition - open-source GRC (Governance, Risk & Compliance) platform built on CakePHP + MySQL + Redis.
Docker-based environment on Ubuntu GNOME VM.

## Key Configuration

- **URL**: `http://localhost:8080` (HTTP) — use this for all task navigation
- **HTTPS also available**: `https://localhost:8443` (self-signed cert)
- **Admin credentials**: login=`admin`, password=`Admin2024!`, email=`admin@eramba.local`
- **Docker services**: `eramba-app` (port 8080/8443), `eramba-db` (MySQL 8.4), `eramba-cache` (Redis 7), `eramba-cron`

## Critical Bugs Found and Fixed

### 1. Wrong DB Environment Variable Names
The docker-compose originally used `DB_USER`/`DB_NAME` but Eramba's `app_local.php` reads `DB_USERNAME`/`DB_DATABASE`.
**Fix**: Use `DB_USERNAME` and `DB_DATABASE` in docker-compose.yml.

### 2. Docker Compose Plugin Not Found
Ubuntu's docker.io package v28 does NOT automatically find compose plugin at `/usr/local/lib/docker/cli-plugins/`.
**Fix**: Symlink to `/usr/lib/docker/cli-plugins/docker-compose` in install_eramba.sh.

### 3. First-Run Welcome Screen
Eramba shows a "Welcome to Eramba Community - Unlock power of GRC" screen at `/welcome` on first run. This must be dismissed before agents can use the application. The setup script handles this with Firefox + xdotool.

### 4. Long Startup Time
Eramba containers take 10-12 minutes to fully initialize (DB migrations + Apache). Poll HTTP:8080 (NOT HTTPS:8443) for readiness — HTTPS often times out.

## Database Schema Key Tables

### users
- `login` (not `username`) — for login field
- `email`, `name`, `surname`, `password` (bcrypt)
- `default_password=0, account_ready=1` means setup complete

### risks
- `title` (not `name`)
- `threats`, `vulnerabilities`, `description`
- `risk_score_formula`, `residual_risk_formula` — text fields, can be strings
- `risk_mitigation_strategy_id`: 1=Accept, 2=Avoid, 3=Mitigate, 4=Transfer
- `review` (date, NOT NULL)

### security_policies
- `index` (not `name`!) — policy name/title field
- `short_description` — brief description
- `description` — full text

### third_parties
- `name`, `description` — standard

### projects
- `title` (not `name`), `goal`, `start`, `deadline` (all NOT NULL)

### security_incidents
- `title`, `description`, `reporter`, `victim`, `open_date` (all NOT NULL)
- `type` varchar(255) NOT NULL

### policy_exceptions
- `title`, `description`
- `expiration` date NOT NULL

### security_services (= Internal Controls)
- `name`, `objective` — main fields
- Used for "internal controls" concept in Eramba

## URL Routes (CakePHP DashedRoute)

| Module | URL |
|--------|-----|
| Login | `/login` |
| Welcome (first-run) | `/welcome` |
| Security Policies | `/security-policies/index` |
| Risks | `/risks/index` |
| Security Services (Internal Controls) | `/security-services/index` |
| Policy Exceptions | `/policy-exceptions/index` |
| Compliance Exceptions | `/compliance-exceptions/index` |
| Third Parties | `/third-parties/index` |
| Third Party Risks | `/third-party-risks/index` |
| Projects | `/projects/index` |
| Security Incidents | `/security-incidents/index` |
| Users | `/users/index` |
| Compliance Managements | `/compliance-managements/index` |

## Enterprise-Only Features (NOT in Community)
- **Awareness Programs** — tables exist (`awareness_programs`) but NO web controller. URL `/awareness-programs` returns 404.
- Use **Security Incidents** or other Community features instead.

## Tasks

| Task | Table | Key Field |
|------|-------|-----------|
| create_security_policy | security_policies | `index` (policy name) |
| add_risk | risks | `title` |
| create_internal_control | security_services | `name` |
| add_compliance_exception | policy_exceptions | `title` |
| add_third_party | third_parties | `name` |
| create_project | projects | `title` |
| add_user | users | `login`, `name` |
| update_risk_treatment | risks | `risk_mitigation_strategy_id` (3=Mitigate) |
| create_security_incident (dir: create_awareness_program) | security_incidents | `title` |
| create_security_questionnaire | — | VLM only |

## Data Seeding
The `setup_eramba.sh` seeds "Phishing Attacks on Employees" risk for the `update_risk_treatment` task.
Direct DB INSERT is used since API requires CSRF authentication.

## Firefox Setup
- Snap Firefox profile at `/home/ga/snap/firefox/common/.mozilla/firefox/`
- Need certutil injection for HTTPS cert acceptance
- Use `security.enterprise_roots.enabled=true` in user.js
- First-run welcome screen at `/welcome` must be clicked through via xdotool in setup

## eramba-cron Container Restarting
The `eramba-cron` container repeatedly exits (code 0) and restarts — this is NORMAL behavior. It runs migrations then exits, Docker restarts it with `restart: unless-stopped`. The main `eramba-app` is unaffected.
