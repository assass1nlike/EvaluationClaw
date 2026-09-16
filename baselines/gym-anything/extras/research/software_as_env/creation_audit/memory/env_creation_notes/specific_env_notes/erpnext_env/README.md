> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# ERPNext Environment Notes

## Overview

ERPNext is an open-source Enterprise Resource Planning system built on the Frappe Framework. This environment runs ERPNext v15 via Docker Compose with 11 containers inside a QEMU VM.

## Architecture

- **ERPNext Application**: `frappe/erpnext:v15` Docker image (backend, frontend, workers, scheduler, websocket)
- **Database**: MariaDB 10.6 (in separate container)
- **Cache/Queue**: Redis 6.2 Alpine (two containers: cache and queue)
- **Web Interface**: Nginx frontend on port 8080, accessed via Firefox
- **Base Image**: ubuntu-gnome-systemd_highres
- **VM Resources**: 4 CPUs, 8GB RAM

## Credentials

- **ERPNext Admin**: Administrator / admin
- **MariaDB Root**: root / admin
- **Company**: Wind Power LLC (created by `erpnext.setup.utils.before_tests`)

## Key Files

```
benchmarks/cua_world/environments/erpnext_env/
├── env.json                              # Environment configuration
├── config/
│   └── docker-compose.yml                # Docker services (11 containers)
├── scripts/
│   ├── install_erpnext.sh                # pre_start hook - installs Docker, Firefox
│   ├── setup_erpnext.sh                  # post_start hook - starts ERPNext, completes setup
│   └── task_utils.sh                     # Shared utilities for tasks
├── tasks/
│   ├── create_sales_invoice/
│   │   ├── task.json                     # Sales invoice task
│   │   ├── setup_task.sh                 # Creates customer + items via API
│   │   └── verifier.py                   # Stub verifier
│   ├── create_purchase_order/
│   │   ├── task.json                     # Purchase order task
│   │   ├── setup_task.sh                 # Creates supplier + items via API
│   │   └── verifier.py                   # Stub verifier
│   └── add_new_employee/
│       ├── task.json                     # Employee creation task
│       ├── setup_task.sh                 # Creates department + designation via API
│       └── verifier.py                   # Stub verifier
├── data/
│   ├── README.md                         # Data source documentation
│   ├── customers.csv                     # 19 real customers from ERPNext demo
│   ├── suppliers.csv                     # 10 real suppliers from ERPNext demo
│   ├── items.csv                         # 17 real items with prices from ERPNext demo
│   └── employees.csv                     # 15 real employee records from ERPNext demo
├── utils/
│   └── __init__.py                       # Placeholder
└── evidence_docs/
    ├── README.md                         # Verification evidence with 10 screenshots
    └── *.png                             # Screenshots of all task start states
```

## Docker Services (11 containers)

| Container | Image | Purpose |
|-----------|-------|---------|
| frontend | frappe/erpnext:v15 | Nginx reverse proxy, port 8080 |
| backend | frappe/erpnext:v15 | Gunicorn app server |
| db | mariadb:10.6 | MariaDB database |
| redis-cache | redis:6.2-alpine | Caching |
| redis-queue | redis:6.2-alpine | Background job queue |
| websocket | frappe/erpnext:v15 | Socket.IO for real-time |
| scheduler | frappe/erpnext:v15 | Periodic job scheduler |
| queue-long | frappe/erpnext:v15 | Long-running background jobs |
| queue-short | frappe/erpnext:v15 | Short background jobs |
| configurator | frappe/erpnext:v15 | One-shot config (exits after setup) |
| create-site | frappe/erpnext:v15 | One-shot site creation (exits after setup) |

## Database Access

```bash
# Via utility script
erpnext-db-query "SELECT name FROM _1bd2a0294da691c3.tabEmployee LIMIT 5"

# Via Docker directly
cd /home/ga/erpnext
docker-compose exec -T db mysql -u root -padmin -e "SELECT name FROM _1bd2a0294da691c3.tabEmployee LIMIT 5"
```

Note: The database name is a hash (`_1bd2a0294da691c3`) generated during site creation. The site name is "frontend".

## Key Tables (MariaDB)

| Table | Description |
|-------|-------------|
| `tabCustomer` | Customer records |
| `tabSupplier` | Supplier records |
| `tabItem` | Items/Products |
| `tabEmployee` | Employee records |
| `tabSales Invoice` | Sales invoices |
| `tabPurchase Order` | Purchase orders |
| `tabCompany` | Companies |
| `tabDepartment` | Departments |

## Data Source

All task data is sourced from the official ERPNext demo repository:
https://github.com/sahadnk72/erpnext-demo/tree/master/erpnext_demo/demo_docs

Data files stored in `benchmarks/cua_world/environments/erpnext_env/data/`:
- `customers.csv` — 19 real company names (Buttrey Food & Drug, Asian Junction, etc.)
- `suppliers.csv` — 10 real company names (Eagle Hardware, HomeBase, etc.)
- `items.csv` — 17 wind turbine parts with real prices (Upper Bearing Plate $50, Shaft $30, etc.)
- `employees.csv` — 15 diverse international employee records (Gabrielle Loftus, Hatsue Kashiwagi, etc.)

## REST API

ERPNext uses the Frappe REST API. All task setup scripts use this pattern:

```python
import requests

session = requests.Session()
URL = "http://localhost:8080"

# Login
session.post(f"{URL}/api/method/login", data={"usr": "Administrator", "pwd": "admin"})

# Create a document (using real demo data)
session.post(f"{URL}/api/resource/Customer", json={
    "customer_name": "Buttrey Food & Drug",
    "customer_type": "Company",
    "customer_group": "All Customer Groups",
    "territory": "All Territories"
})

# Read documents
response = session.get(f"{URL}/api/resource/Customer?filters=[[\"customer_name\",\"=\",\"Buttrey Food & Drug\"]]")
```

## Installation Quirks

### docker-compose-plugin Not Available
Ubuntu 22.04 default repos do not include `docker-compose-plugin`. The install script uses the standalone `docker-compose` package (v1.29.2) instead. **Critical**: Do not combine `docker.io` and `docker-compose-plugin` in a single `apt-get install` with `set -e`, as the missing package will abort the entire install.

### No `set -e` in Install Script
The install script deliberately avoids `set -e` because some package installs may produce non-zero exit codes (e.g., optional packages). Each critical step is checked individually instead.

### Pre-pulling Docker Images
The pre_start hook pre-pulls `frappe/erpnext:v15`, `mariadb:10.6`, and `redis:6.2-alpine` so that the post_start hook doesn't have to wait for image downloads.

## Service Timing Issues

### ERPNext Startup Takes ~20-60 seconds
After `docker-compose up -d`, the frontend container needs time to become ready. The setup script polls `http://localhost:8080` every 10 seconds for up to 600 seconds.

### Site Creation is Slow
The `create-site` container runs `bench new-site --install-app erpnext` which can take 60-120 seconds. It must complete before the backend serves pages properly.

### Total Setup Time
- pre_start (install + image pull): ~4-5 minutes
- post_start (container start + site creation + setup): ~2-3 minutes
- Total: ~6-8 minutes

## Setup Wizard Completion

ERPNext v15 changed how the setup wizard works. Key findings:

1. **`erpnext.setup.utils.before_tests`**: The recommended way to programmatically complete setup. Creates company "Wind Power LLC" with chart of accounts, fiscal year, warehouses, cost centers, and more.

2. **`frappe.client.set_value`**: After `before_tests`, you must explicitly set `setup_complete=1` in System Settings:
   ```bash
   docker-compose exec -T backend bench --site frontend execute frappe.client.set_value \
     --kwargs '{"doctype":"System Settings","name":"System Settings","fieldname":"setup_complete","value":1}'
   ```

3. **API methods NOT available**: `frappe.desk.page.setup_wizard.setup_wizard.is_setup_complete` and the `setup_complete` method are not whitelisted for external API calls in v15.

4. **Company name is fixed**: `before_tests` always creates "Wind Power LLC" — you cannot choose the company name with this approach.

## Verification Pattern

ERPNext tasks use stub verifiers that return `{"passed": True, "score": 100}`. Actual verification is intended to be done externally (e.g., VLM evaluation). For programmatic verification, query the REST API or MariaDB directly.

## Firefox Configuration

The Firefox profile is pre-configured in `setup_erpnext.sh`:
- Homepage set to `http://localhost:8080`
- First-run dialogs disabled
- Password saving disabled
- Sidebar/extension popups disabled
- Update checks disabled

## ERPNext UI Gotchas

### Department names have company suffix
Departments are stored as "Engineering - WP" (with company abbreviation). When the agent types "Engineering" in the Department field, ERPNext shows "Engineering - WP" in the dropdown. The agent must select this option.

### Company auto-fills on New Employee form
If only one company exists (Wind Power LLC), the Company field auto-fills. This is convenient for agents.

### Date format is US convention
ERPNext with `country: "United States"` uses `mm-dd-yyyy` format. Agents must enter dates correctly.

### "Leave page" browser dialog
When navigating away from an unsaved form, the browser shows a confirmation dialog. Task setup scripts that navigate Firefox to a new form and then the agent needs to navigate elsewhere will encounter this.

## Common Issues

### ERPNext Returns HTTP 000
Docker is not installed or containers failed to start. Check that the pre_start hook completed successfully and Docker images were pulled.

### "Site not found" Errors
The site name must match across `docker-compose.yml` (FRAPPE_SITE_NAME_HEADER), `bench new-site` command, and `bench --site` commands. This environment uses "frontend" as the site name.

### MariaDB Connection Refused
MariaDB may take 30-60 seconds to be ready. The `create-site` container includes `wait-for-it` logic. If MariaDB health check is not passing, increase the health check interval.

### Memory Usage
After full setup with all 11 containers + Firefox: ~1.9GB of 8GB used. Sufficient headroom for task operations.

## Adding New Tasks

1. Create task directory under `tasks/`
2. Add `task.json` with description, metadata, and success spec
3. Create `setup_task.sh` using the REST API pattern from `task_utils.sh`
4. Create `verifier.py` (stub or programmatic verification)
5. Test by running the environment and task hooks
