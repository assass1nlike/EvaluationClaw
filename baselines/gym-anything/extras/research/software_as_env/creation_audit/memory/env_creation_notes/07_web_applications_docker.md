# Web Applications & Docker-Based Environments

## Overview

Web applications present unique challenges for gym_anything environments compared to desktop applications. This document covers patterns and best practices learned from implementing the OpenEMR environment.

## When to Use Docker

### Use Docker When:

1. **Application has complex dependencies** - Multiple services (database, web server, cache, queue)
2. **Official Docker images exist** - Pre-configured, tested, and maintained
3. **Manual setup is error-prone** - Web installers, database migrations, config wizards
4. **Version-specific configuration** - Schema changes between versions break scripts

### Docker Inside QEMU Works

The gym_anything QEMU VM supports running Docker:

```bash
# In pre_start hook
apt-get install -y docker.io docker-compose
systemctl enable docker
systemctl start docker
usermod -aG docker ga
```

**Performance**: With KVM acceleration, nested containerization has minimal overhead.

## Docker Hub Rate Limits (IMPORTANT)

Anonymous Docker image pulls are rate-limited by Docker Hub (~100 pulls/6hr per IP). On shared compute infrastructure this limit is hit frequently, causing `docker compose pull` to fail with `429 Too Many Requests`.

**Always authenticate with Docker Hub credentials before pulling images:**

```bash
# In post_start hook, before docker compose pull:
if [ -f /workspace/config/.dockerhub_credentials ]; then
    source /workspace/config/.dockerhub_credentials
    echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin 2>/dev/null || true
fi
docker compose pull
```

**Copy the credentials file from the reference environment** — do not create a new one:
```bash
cp benchmarks/cua_world/environments/idempiere_env/config/.dockerhub_credentials benchmarks/cua_world/environments/<your_env>/config/.dockerhub_credentials
```

The file contains (already gitignored):
```bash
DOCKERHUB_USERNAME="hackear2041"
DOCKERHUB_TOKEN="dckr_pat_YISK01jQAaGVVmzkVoZnkOH3Q3g"
```

This pattern is used in `benchmarks/cua_world/environments/idempiere_env/` and must be used in **all new Docker-based environments**.

## Docker Compose Pattern

### Basic Structure

```yaml
version: '3.8'
services:
  database:
    image: mariadb:10.11  # or postgres, mysql
    container_name: app-db
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: appdb
      MYSQL_USER: appuser
      MYSQL_PASSWORD: apppass
    volumes:
      - db_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5

  webapp:
    image: vendor/app:version
    container_name: app-web
    ports:
      - "80:80"
    environment:
      DB_HOST: database
      DB_USER: appuser
      DB_PASS: apppass
    depends_on:
      database:
        condition: service_healthy

volumes:
  db_data:
```

### Key Patterns

1. **Use healthchecks** - Ensure database is ready before app starts
2. **Named containers** - Makes `docker exec` commands predictable
3. **Volumes for persistence** - Data survives container restarts
4. **Environment variables** - Configure without modifying images

## Waiting for Services

### HTTP Polling Pattern

```bash
wait_for_webapp() {
    local url="$1"
    local timeout=${2:-180}
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null)
        if [ "$HTTP_CODE" = "200" ]; then
            echo "Service ready after ${elapsed}s"
            return 0
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
    return 1
}

wait_for_webapp "http://localhost/login" 180
```

### Database Polling Pattern

```bash
wait_for_database() {
    local container="$1"
    local timeout=${2:-60}
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        if docker exec "$container" mysqladmin ping -h localhost --silent 2>/dev/null; then
            echo "Database ready after ${elapsed}s"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    return 1
}
```

## Database Verification

### Querying via Docker

```bash
# Direct query
docker exec app-db mysql -u appuser -papppass appdb -N -e "SELECT COUNT(*) FROM users"

# Create utility script
cat > /usr/local/bin/app-db-query << 'EOF'
#!/bin/bash
docker exec app-db mysql -u appuser -papppass appdb -e "$1"
EOF
chmod +x /usr/local/bin/app-db-query
```

### Python Verification Pattern

```python
def verify_task(traj, env_info, task_info):
    exec_in_env = env_info.get('exec_in_env')

    # Query database via Docker
    result = exec_in_env(
        'docker exec app-db mysql -u appuser -papppass appdb -N -e '
        '"SELECT COUNT(*) FROM records WHERE field=\'expected_value\'"'
    )

    count = int(result.strip()) if result.strip().isdigit() else 0
    passed = count > 0

    return {
        "passed": passed,
        "score": 100 if passed else 0,
        "message": f"Found {count} matching records"
    }
```

## Loading Data

### Schema Compatibility

**Always check the target schema first:**

```bash
docker exec app-db mysql -u user -ppass dbname -e "DESCRIBE table_name"
```

Common differences between versions:
- Column types (integer vs string)
- Required vs nullable fields
- Auto-increment behavior
- Default values

### SQL Import Pattern

```bash
# Copy SQL file to container
docker cp /path/to/data.sql app-db:/tmp/data.sql

# Import data
docker exec app-db mysql -u user -ppass dbname -e "source /tmp/data.sql"

# Clean up
docker exec app-db rm /tmp/data.sql
```

### Handling Import Errors

```bash
# Suppress specific warnings (e.g., duplicate key)
docker exec app-db mysql -u user -ppass dbname -e "source /tmp/data.sql" 2>&1 | grep -v "Duplicate entry"
```

## Browser Configuration

### Firefox Profile for Web Apps

```bash
FIREFOX_PROFILE_DIR="/home/ga/.mozilla/firefox"
mkdir -p "$FIREFOX_PROFILE_DIR/default-release"

# profiles.ini
cat > "$FIREFOX_PROFILE_DIR/profiles.ini" << 'EOF'
[Install4F96D1932A9F858E]
Default=default-release
Locked=1

[Profile0]
Name=default-release
IsRelative=1
Path=default-release
Default=1

[General]
StartWithLastProfile=1
Version=2
EOF

# user.js - essential preferences
cat > "$FIREFOX_PROFILE_DIR/default-release/user.js" << 'EOF'
// Disable first-run dialogs
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.rights.3.shown", true);
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);

// Set homepage to app
user_pref("browser.startup.homepage", "http://localhost/");
user_pref("browser.startup.page", 1);

// Disable password prompts
user_pref("signon.rememberSignons", false);
user_pref("signon.autofillForms", false);

// Disable sidebar and popups
user_pref("sidebar.revamp", false);
user_pref("sidebar.verticalTabs", false);
user_pref("browser.vpn_promo.enabled", false);

// Disable updates
user_pref("app.update.enabled", false);
EOF

chown -R ga:ga "$FIREFOX_PROFILE_DIR"
```

## Debugging

### Common Commands

```bash
# Container status
docker-compose ps

# View logs
docker logs app-web
docker logs app-db

# Follow logs
docker-compose logs -f

# Shell into container
docker exec -it app-web /bin/bash

# Check network
docker network ls
docker network inspect app_default
```

### Common Issues

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| Container exits immediately | Missing dependency | Check `docker logs` |
| 500 error on web app | Database not ready | Use healthchecks |
| Data import fails | Schema mismatch | Check `DESCRIBE table` |
| Connection refused | Wrong port mapping | Verify `docker-compose.yml` |

## File Structure Pattern

```
benchmarks/cua_world/environments/webapp_env/
├── env.json
├── scripts/
│   ├── install_webapp.sh      # pre_start: Docker + Firefox
│   └── setup_webapp.sh        # post_start: docker-compose + data
├── config/
│   ├── docker-compose.yml     # Container orchestration
│   └── sample_data.sql        # Initial data
├── tasks/
│   └── task_name/
│       ├── task.json
│       ├── verifier.py
│       └── setup_task.sh
└── utils/
    └── verification_utils.py
```

## env.json Configuration

```json
{
  "name": "webapp_env",
  "description": "Web application environment using Docker",
  "base_image": "ubuntu-gnome-systemd_highres",
  "resources": {
    "cpus": 4,
    "memory": "8192m"
  },
  "security": {
    "privileged": true,
    "use_systemd": true
  },
  "net": true,
  "user": "ga",
  "scripts": {
    "pre_start": "scripts/install_webapp.sh",
    "post_start": "scripts/setup_webapp.sh"
  },
  "mounts": [
    {"host": "scripts", "guest": "/workspace/scripts"},
    {"host": "config", "guest": "/workspace/config"}
  ]
}
```

## Key Lessons

1. **Docker simplifies complex setups** - Let official images handle dependencies
2. **Use Docker Compose v2, not v1** - v1 (`docker-compose`) has known bugs (e.g., `KeyError: 'ContainerConfig'`). Always use v2 (`docker compose` subcommand). See `10_cross_cutting_patterns.md` pattern #8
3. **Healthchecks prevent race conditions** - Services start in correct order
4. **Service readiness polling is essential** - Containers report "running" before the app inside is ready. Always poll with retries and timeouts. See `10_cross_cutting_patterns.md` pattern #1
5. **Schema matters for data loading** - Always verify column types and names
6. **Browser config is critical** - First-run dialogs break automation. Use two-layer suppression. See `10_cross_cutting_patterns.md` pattern #2
7. **Database verification >> screenshot verification** - Query state changes, not UI elements. See `10_cross_cutting_patterns.md` pattern #5
8. **Named containers are predictable** - Easier to script `docker exec` commands
9. **Fix file permissions after `docker cp`** - Match container's runtime UID/GID. See `10_cross_cutting_patterns.md` pattern #9
10. **Use here-documents for SQL with special characters** - Avoids shell escaping nightmares. See `10_cross_cutting_patterns.md` pattern #11
