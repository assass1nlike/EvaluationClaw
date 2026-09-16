> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Odoo Environment Notes

## Overview

Odoo is an open-source Enterprise Resource Planning (ERP) system that includes modules for CRM, sales, inventory, accounting, HR, and more. This environment runs Odoo 17 via Docker containers.

## Architecture

- **Odoo Application**: Official Odoo 17 Docker image
- **Database**: PostgreSQL 15 (in separate container)
- **Web Interface**: Accessed via Firefox on port 8069
- **Base Image**: ubuntu-gnome-systemd_highres

## Credentials

- **Odoo Admin**: admin@example.com / admin
- **Database Name**: odoo_demo
- **PostgreSQL**: odoo / odoo

## Key Files

```
benchmarks/cua_world/environments/odoo_env/
├── env.json                        # Environment configuration
├── config/
│   └── docker-compose.yml          # Docker services configuration
├── scripts/
│   ├── install_odoo.sh             # pre_start hook - installs Docker
│   ├── setup_odoo.sh               # post_start hook - starts Odoo
│   └── task_utils.sh               # Shared utilities for tasks
└── tasks/
    └── create_customer/
        ├── task.json               # Task definition
        ├── setup_task.sh           # pre_task hook
        ├── export_result.sh        # post_task hook
        └── verifier.py             # Verification logic
```

## Database Access

Query Odoo's PostgreSQL database:

```bash
# Via utility script
odoo-db-query "SELECT * FROM res_partner LIMIT 5"

# Via Docker directly
docker exec odoo-postgres psql -U odoo -d odoo_demo -c "SELECT * FROM res_partner"
```

## Key Tables

| Table | Description |
|-------|-------------|
| `res_partner` | Contacts/Customers/Vendors |
| `res_users` | User accounts |
| `sale_order` | Sales orders |
| `product_product` | Products |
| `account_move` | Invoices/Bills |

## Odoo Navigation

1. **Main Apps Menu**: Click the grid icon (top-left)
2. **Contacts App**: Customer/Vendor management
3. **Sales App**: Quotations, Sales Orders
4. **Inventory App**: Stock management
5. **Accounting App**: Invoices, Bills, Payments

## Common Issues

### Database Creation Timeout
The first run may take longer as Odoo creates the database with demo data. The setup script waits up to 5 minutes.

### Demo Data Loading
To create a database with demo data via the web API, use:
```bash
curl -X POST 'http://localhost:8069/web/database/create' \
  -d 'master_pwd=admin&name=odoo_demo&login=admin@example.com&password=admin&phone=&lang=en_US&country_code=us&demo=1'
```
**Important**: The `phone` field is required (can be empty) and `demo=1` enables demo data.

### Firefox First-Run Dialogs
The Firefox profile is pre-configured to skip first-run dialogs and set Odoo as the homepage.

### PostgreSQL Connection
Ensure the postgres container is healthy before Odoo starts. The docker-compose.yml includes health checks.

### Column Differences in Odoo 17
Odoo 17 does not have a `customer_rank` column in `res_partner`. Use `is_company` to identify companies instead.

## Verification Pattern

1. `setup_task.sh`: Records initial state (e.g., partner count)
2. Agent performs task
3. `export_result.sh`: Queries database, exports JSON to /tmp/
4. `verifier.py`: Uses `copy_from_env` to read JSON and verify

## Adding New Tasks

1. Create task directory under `tasks/`
2. Add task.json with expected values in metadata
3. Create setup_task.sh to record initial state
4. Create export_result.sh to query database and export JSON
5. Create verifier.py using the copy_from_env pattern

## Resources

- [Odoo Documentation](https://www.odoo.com/documentation/17.0/)
- [Odoo Docker Hub](https://hub.docker.com/_/odoo/)
- [PostgreSQL 15 Documentation](https://www.postgresql.org/docs/15/)
