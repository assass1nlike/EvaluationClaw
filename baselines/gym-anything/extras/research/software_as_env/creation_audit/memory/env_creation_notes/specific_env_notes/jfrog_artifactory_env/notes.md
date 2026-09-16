> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# JFrog Artifactory Environment Notes

**Status**: Complete and tested
**Date**: 2026-02-21
**Version**: jfrog_artifactory_env@0.1

## Architecture

- **Base image**: `ubuntu-gnome-systemd_highres`
- **Docker Compose**: Artifactory OSS 7.77.3 + PostgreSQL 13
- **UI**: Firefox at `http://localhost:8082`
- **Resources**: 4 CPUs, 10 GB RAM (minimum for Artifactory to run stably)

## Critical Limitation: OSS 7.x REST API

**Artifactory OSS 7.x ONLY allows GET operations via REST API for management resources.**

The following REST API endpoints return HTTP 400 with "This REST API is available only in Artifactory Pro":
- `PUT /artifactory/api/repositories/{key}` — create repository
- `PUT /artifactory/api/security/users/{username}` — create user
- `PUT /artifactory/api/security/groups/{groupname}` — create group
- `PUT /artifactory/api/security/permissions/{name}` — create permission target

**What DOES work:**
- `GET /artifactory/api/repositories` — list repos
- `GET /artifactory/api/repositories/{key}` — get repo info
- `GET /artifactory/api/security/users/{username}` — check if user exists
- `GET /artifactory/api/security/groups/{groupname}` — check if group exists
- `GET /artifactory/api/security/permissions/{name}` — check if permission exists
- `PUT /artifactory/{repokey}/{path}` — deploy/upload artifact to existing repo
- `GET /artifactory/api/search/quick` — search for artifacts
- `GET /access/api/v1/tokens` — list access tokens
- `POST /artifactory/api/security/users/authorization/changePassword` — change password

**Implication**: All management operations (create repos, users, groups) MUST be done via the Firefox UI. The verifiers use GET endpoints which work fine.

## Setup Script Design

### install_artifactory.sh (pre_start)
1. Adds Docker's official apt repository (docker-ce, docker-ce-cli, containerd.io, docker-compose-plugin)
2. Installs supporting tools: wmctrl, xdotool, jq, wget, python3-pip, scrot
3. Sets up Firefox profile directory
4. Does NOT start Artifactory (that's post_start)

**Key gotcha**: Ubuntu 22.04's default apt repos do NOT include `docker-compose-plugin`. Must add Docker's official GPG key and apt repo first.

### setup_artifactory.sh (post_start)
1. Copies docker-compose.yml to `/home/ga/artifactory/`
2. Docker Hub login (to avoid rate limiting)
3. `docker compose up -d`
4. Waits for PostgreSQL health check
5. Waits for Artifactory ping endpoint (up to 600s — takes 5-8 min on first start)
6. Calls changePassword API to mark password as initialized (reduces wizard prompts)
7. Downloads real artifact JARs from Maven Central to `/home/ga/artifacts/`
8. Sets up Firefox profile (user.js preferences to suppress first-run dialogs)
9. Launches Firefox at Artifactory URL

**Artifactory startup time**: First boot takes 5-8 minutes due to Hibernate initialization and database schema creation.

## Task Design Notes

### Default State After post_start
- Only `example-repo-local` (Generic type) exists by default
- Only `admin` user exists
- No groups, no permission targets

### Task Design Philosophy
- All tasks are **UI-based**: agents interact with Firefox to perform management operations
- Setup scripts navigate Firefox to the relevant admin section
- Verifiers use **REST API GET calls** to verify the desired state was achieved

### Task-Specific Notes

#### create_local_maven_repo
- Creates `team-releases` (Maven local)
- Verifier: GET /api/repositories/team-releases → rclass=local, packageType=maven

#### create_local_npm_repo
- Creates `npm-local` (npm local)
- Verifier: GET /api/repositories/npm-local → rclass=local, packageType=npm

#### create_local_pypi_repo
- Creates `pypi-local` (PyPI local)
- Verifier: GET /api/repositories/pypi-local → rclass=local, packageType=pypi

#### create_remote_repo
- Creates `maven-central-proxy` (Maven remote, proxying Maven Central)
- Verifier: GET /api/repositories/maven-central-proxy → rclass=remote

#### create_virtual_repo
- Creates `generic-virtual` (Generic virtual, includes example-repo-local)
- **NOTE**: Changed from original Maven design (libs-release-local, central) because those repos don't exist by default in OSS 7.x
- Verifier: GET /api/repositories/generic-virtual → rclass=virtual

#### upload_artifact
- Uploads `commons-io-2.15.1.jar` to `example-repo-local`
- **NOTE**: Changed target from `libs-snapshot-local` to `example-repo-local` (the only default repo in OSS 7.x)
- Artifact file pre-downloaded to `/home/ga/artifacts/commons-io/commons-io-2.15.1.jar` and Desktop
- Verifier: Quick search for commons-io-2.15.1.jar in example-repo-local

#### add_user
- Creates user `john_doe` via UI (Security > Users)
- Verifier: GET /api/security/users/john_doe → 200

#### create_group
- Creates group `developers` via UI (Security > Groups)
- **NOTE**: Removed `devuser` member requirement (devuser doesn't exist in fresh env and can't be created via REST API)
- Verifier: GET /api/security/groups/developers → 200

#### set_permission_target
- Creates `dev-permissions` permission target for `example-repo-local`, granting `admin` read/deploy
- **NOTE**: Changed from `libs-release-local`+`devuser` to `example-repo-local`+`admin` (OSS 7.x defaults)
- Verifier: GET /api/security/permissions/dev-permissions → 200

#### create_access_token
- Generates admin access token with description "CI/CD pipeline token"
- Verifier: GET /access/api/v1/tokens → checks for user-created tokens

## Onboarding Wizard Behavior

On first login after env reset, Artifactory shows:
1. Firefox "Save Password?" dialog → agent should click "Not now"
2. Red banner: "Change default admin password" warning → can be ignored
3. "Welcome To JFrog Platform" onboarding wizard → agent should click "Skip"

After skipping, the main Administration panel is accessible. The wizard may reappear each time the environment is reset (this is expected Artifactory OSS behavior for fresh installs).

## VNC / Screenshot Method

`scrot` was not found in the test environment. Use `xwd -root -silent | convert - output.png` instead:
```bash
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xwd -root -silent | convert - /tmp/screenshot.png
```

Note: The task_utils.sh `take_screenshot()` function already handles this fallback.

## Resource Requirements

- **RAM**: 10 GB minimum (Artifactory requires ~4-6 GB, PostgreSQL ~512 MB, OS ~1 GB)
- **CPU**: 4 cores (Artifactory is multithreaded)
- **Disk**: ~3 GB for Docker images, ~1 GB for Artifactory data volume
- **Startup time**: 5-8 minutes (first boot), ~2-3 minutes (subsequent boots from saved state)

## Docker Images

- `releases-docker.jfrog.io/jfrog/artifactory-oss:7.77.3` — NOT rate-limited (JFrog's own registry)
- `postgres:13-alpine` — from Docker Hub, needs auth to avoid rate limits

The dockerhub_credentials file covers `postgres:13-alpine`. The Artifactory image is pulled from JFrog's registry which doesn't rate-limit.
