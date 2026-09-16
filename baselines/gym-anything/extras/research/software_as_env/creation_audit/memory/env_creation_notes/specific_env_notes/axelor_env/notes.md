> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Axelor Environment - Learnings & Notes

## Docker Image

- **Image**: `axelor/aio-erp:latest` (all-in-one: PostgreSQL + Tomcat + nginx)
- **Size**: 838MB compressed
- **First startup**: 10-30 minutes for database initialization
- **Subsequent starts**: ~20 seconds
- **Internal ports**: 80 (nginx), 8080 (Tomcat), 5432 (PostgreSQL)

## Critical: VM Memory Requirements

Axelor is a Java/Tomcat application that requires significantly more memory than Python-based ERPs (Odoo, ERPNext):

- **8GB RAM: FAILS** - Tomcat Java heap + PostgreSQL + Firefox + OS exceeds 8GB, causing OOM kills that crash the QEMU VM
- **16GB RAM: WORKS** - Sufficient for all services
- At runtime, ~3GB used, ~12GB available

## Critical: Docker and QEMU SSH Port Forwarding

Docker's default iptables rules break QEMU's NAT-based SSH port forwarding. Two approaches:

### Approach 1 (NOT recommended): daemon.json with iptables=false
Writing `/etc/docker/daemon.json` with `"iptables": false` prevents Docker from modifying iptables. However, this requires `network_mode: host` in docker-compose.yml.

### Approach 2 (RECOMMENDED): Follow SuiteCRM/Canvas pattern
1. Install `docker.io` from apt (NOT Docker CE from upstream)
2. Do NOT write daemon.json (let Docker use default iptables)
3. Use `systemctl start docker` (NOT `restart`)
4. Use `network_mode: host` in docker-compose.yml anyway

The key insight: `apt-get install docker.io` auto-starts Docker. Writing daemon.json BEFORE install changes Docker's startup behavior in ways that can crash the VM. Writing it AFTER install and NOT restarting Docker leaves the default iptables intact.

## Critical: Snap Firefox

Ubuntu 22.04 installs Firefox as a snap package. Key differences from apt-installed Firefox:

1. **NO `--profile` flag** - Snap Firefox ignores the `--profile` argument. Don't use it.
2. **Profile path**: `/home/ga/snap/firefox/common/.mozilla/firefox/<profile>/`
3. **`su - ga` doesn't work from root** - Use `sudo -u ga DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority firefox` instead
4. **First launch is slow** - Allow 10+ seconds for the snap sandbox to initialize
5. **user.js injection**: Write to the snap profile directory after a warm-up launch creates it

## Database Access

The PostgreSQL database is inside the `axelor-app` container (bundled in the aio-erp image):

```bash
# Peer auth doesn't work, must use -h localhost and PGPASSWORD
docker exec -e PGPASSWORD=axelor axelor-app psql -U axelor -d axelor -h localhost -c "SELECT ..."
```

### Key Tables
- `base_partner` - Partners (customers, suppliers, contacts)
- `sale_sale_order` - Sales orders/quotations
- `purchase_purchase_order` - Purchase orders
- `base_product` - Products
- `account_invoice` - Invoices

### Table naming convention
Java entity `com.axelor.apps.<module>.db.<Entity>` maps to table `<module>_<entity_snake_case>`.

## Axelor URL Structure

- Login page: `http://localhost/login.jsp`
- After login: `http://localhost/` (redirects to main app)
- REST API: `http://localhost/ws/rest/<model>`
- Login API: `POST http://localhost/callback` with JSON `{"username":"admin","password":"admin"}`

## Module Installation via API

The correct action name for installing a module is `action-app-method-install-app` (NOT `action-app-method-install`). Found by querying the view metadata:
```python
# Fetch toolbar actions from cards view
req_data = json.dumps({"model": "com.axelor.apps.base.db.App", "data": {"name": "all.app.management", "type": "cards"}})
# Look for: action-app-method-install-app, action-app-open-bulk-install-selector
```

**Critical**: Install modules sequentially with 20-second pauses. Installing multiple modules simultaneously causes OOM crashes in the QEMU VM. The Tomcat JPA/Hibernate migrations are extremely memory-intensive.

The install action returns `{"status": 0, "data": [{"signal-data": true, "signal": "refresh-app"}]}` on success.

## REST API Notes

- Session-based authentication (cookie-based, NOT token/JWT)
- Login: `POST /login.jsp` with form data `username=admin&password=admin` (NOT `/callback` with JSON)
- Create: `PUT /ws/rest/<model>` with `{"data": {...}}`
- Search: `POST /ws/rest/<model>/search` with domain filter
- Update requires `version` field (optimistic locking)
- Action execution: `POST /ws/action/` with `{"action": "<name>", "data": {"context": {...}}}`

## Docker Compose Notes

- Use `docker compose` (v2) not `docker-compose` (v1) for the compose commands
- The docker-compose.yml uses `version: '3.8'` for compatibility with both
- `network_mode: host` is required

## Timing

| Phase | Duration |
|-------|----------|
| pre_start (Docker + tools install) | 60-90 seconds |
| post_start (image pull + container start + Firefox) | 180-220 seconds |
| pre_task (data seed + Firefox navigation) | 30-75 seconds |
| **Total** | **~5-6 minutes** |
