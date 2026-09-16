> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# DBeaver Environment Notes

## Overview

DBeaver is a free, open-source, universal database management tool that supports many database types including SQLite, PostgreSQL, MySQL, Oracle, and many more. This environment provides a setup for testing database management tasks using DBeaver Community Edition.

## Installation

DBeaver is installed from the official DBeaver repository:
- Repository: https://dbeaver.io/debs/dbeaver-ce
- Java: Default JDK (required by DBeaver)
- SQLite: Installed for sample database operations

## Sample Database

The environment uses the **Chinook** database - a well-known sample database representing a digital media store:

- **Source**: [SQLite Tutorial](https://www.sqlitetutorial.net/sqlite-sample-database/)
- **Location**: `/home/ga/Documents/databases/chinook.db`
- **Tables**: 11 tables including:
  - `artists` (275 records) - Musical artists
  - `albums` - Albums linked to artists
  - `tracks` (3503 records) - Individual songs/tracks
  - `customers` (59 records) - Customer information
  - `invoices` - Customer purchases
  - `employees` - Store employees
  - `genres`, `media_types`, `playlists`, etc.

This provides realistic, production-like data for testing database operations.

## Tasks

### 1. connect_to_database
**Difficulty**: Easy
**Goal**: Create a new SQLite database connection in DBeaver

The agent must:
1. Open the "New Database Connection" dialog
2. Select SQLite as the database type
3. Navigate to `/home/ga/Documents/databases/chinook.db`
4. Name the connection "Chinook"
5. Test and save the connection

### 2. run_sql_query
**Difficulty**: Medium
**Goal**: Execute a SQL query to find tracks by a specific artist

The agent must:
1. Connect to the Chinook database
2. Open a new SQL editor
3. Write a JOIN query across tracks, albums, and artists tables
4. Execute the query
5. View the results (18 AC/DC tracks expected)

### 3. export_data
**Difficulty**: Medium
**Goal**: Export table data to a CSV file

The agent must:
1. Connect to the Chinook database
2. Navigate to the customers table
3. Use DBeaver's export functionality
4. Export all 59 customers to `/home/ga/Documents/exports/customers_export.csv`

## Verification Strategy

Each task uses a two-part verification pattern:

1. **Export Script** (`export_result.sh`): Runs inside the VM to:
   - Check DBeaver configuration files for connections
   - Verify exported files exist and have correct content
   - Capture window states and titles
   - Save results to JSON

2. **Verifier** (`verifier.py`): Runs on host to:
   - Read exported JSON via `copy_from_env`
   - Evaluate multiple criteria
   - Optionally use VLM for visual verification
   - Return pass/fail with score

## Key Configuration Files

DBeaver stores connections in:
- `/home/ga/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json`

This is checked by the verifier to confirm database connections were created.

## Known Issues and Workarounds

### First-run wizard
DBeaver may show a first-run wizard or welcome screen. The setup script attempts to dismiss this by:
- Creating marker files
- Sending Escape key presses

### File permissions
Export scripts use the temp file pattern with sudo fallbacks to avoid permission issues when writing result files.

### DBeaver startup time
DBeaver can take 10-15 seconds to fully start. The setup script waits for the window to appear and then maximizes it.

## Testing

Use the test script:
```bash
python benchmarks/cua_world/environments/test_dbeaver_env.py                    # Environment only
python benchmarks/cua_world/environments/test_dbeaver_env.py connect_to_database  # With task
```

Or manually:
```python
from gym_anything.api import from_config

env = from_config("benchmarks/cua_world/environments/dbeaver_env", task_id="connect_to_database")
obs = env.reset(seed=42, use_cache=False)

# SSH connection info
print(f"SSH: ssh -p {env._runner.ssh_port} ga@localhost")
print(f"VNC: {env._runner.vnc_port}")

# Debug commands
env._runner.exec_capture('cat /home/ga/env_setup_pre_start.log | tail -20')
env._runner.exec_capture('cat /home/ga/env_setup_post_start.log | tail -20')
```

## Resources

- [DBeaver Official Documentation](https://dbeaver.com/docs/dbeaver/)
- [Chinook Database](https://github.com/lerocha/chinook-database)
- [SQLite Tutorial - Chinook](https://www.sqlitetutorial.net/sqlite-sample-database/)
