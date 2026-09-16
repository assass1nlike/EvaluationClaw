> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# MySQL Workbench Environment - Implementation Notes

## Overview

This document contains learnings and notes from implementing the MySQL Workbench environment for gym_anything.

## Installation Method

MySQL Workbench was installed via **snap** package manager:
```bash
snap install mysql-workbench-community
```

This is the most reliable method for Ubuntu 22.04+ as:
- APT repository method requires specific MySQL APT config
- Direct DEB download may have dependency issues
- Snap provides automatic updates and sandboxed installation

### Snap Permissions

Required snap connections for full functionality:
```bash
snap connect mysql-workbench-community:password-manager-service :password-manager-service
snap connect mysql-workbench-community:ssh-keys :ssh-keys
```

**Note**: Even with these connections, the snap version may show dbus-launch errors.

## Configuration File Locations

### Snap Installation Paths

MySQL Workbench snap stores data in:
```
/home/ga/snap/mysql-workbench-community/<version>/
├── .mysql/
│   └── workbench/
│       ├── server_instances.xml  # Stores connection data!
│       ├── wb_options.xml
│       ├── log/
│       ├── modules/
│       └── scripts/
├── .local/
│   └── share/
└── .config/
```

**CRITICAL**: The snap version stores connection data in `server_instances.xml`, NOT in `connections.xml`. The export scripts must check this file for verifying connections.

### Standard Installation Paths (if not using snap)

```
/home/ga/.mysql/workbench/
├── connections.xml
├── server_instances.xml
└── wb_options.xml
```

## Database Setup

### Official Sample Databases

Using official MySQL sample databases from https://downloads.mysql.com/docs/:

1. **Sakila Database** (`sakila-db.zip`)
   - DVD rental store data
   - ~16 tables + views
   - Download and load:
     ```bash
     wget https://downloads.mysql.com/docs/sakila-db.zip
     unzip sakila-db.zip
     mysql -u root -p < sakila-db/sakila-schema.sql
     mysql -u root -p < sakila-db/sakila-data.sql
     ```

2. **World Database** (`world-db.zip`)
   - Countries, cities, languages
   - 3 tables
   - Download and load:
     ```bash
     wget https://downloads.mysql.com/docs/world-db.zip
     unzip world-db.zip
     mysql -u root -p < world-db/world.sql
     ```

## MySQL Server Setup

### Non-Interactive Installation

To avoid prompts during installation:
```bash
export DEBIAN_FRONTEND=noninteractive
debconf-set-selections <<< "mysql-server mysql-server/root_password password GymAnything#2024"
debconf-set-selections <<< "mysql-server mysql-server/root_password_again password GymAnything#2024"
apt-get install -y mysql-server
```

### User Configuration

Create a non-root user for agent interaction:
```sql
CREATE USER 'ga'@'localhost' IDENTIFIED BY 'password123';
GRANT ALL PRIVILEGES ON *.* TO 'ga'@'localhost' WITH GRANT OPTION;
FLUSH PRIVILEGES;
```

### Authentication Method

For MySQL 8.0+, ensure native password authentication:
```sql
ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'GymAnything#2024';
```

## GUI Interaction Notes

### Window Detection

MySQL Workbench window titles include "MySQL Workbench" or "Workbench":
```bash
DISPLAY=:1 wmctrl -l | grep -i "workbench\|mysql"
```

### Common UI Elements

| Element | CUA Coords (1280x720) | Actual (1920x1080) |
|---------|----------------------|-------------------|
| File menu | (31, 38) | (47, 57) |
| Database menu | (79, 38) | (119, 57) |
| + button (add connection) | (277, 323) | (415, 484) |
| MySQL Connections header | (97, 162) | (145, 243) |

### Connection Dialog Fields

When "Setup New Connection" dialog is open:
- Connection Name: CUA (645, 229) -> Actual (968, 343)
- Username: CUA (593, 347) -> Actual (890, 520)
- OK button: CUA (903, 557) -> Actual (1354, 835)

### Coordinate Scaling

CUA returns coordinates normalized to 1280x720. Scale to actual resolution:
```python
actual_x = int(cua_x * 1920 / 1280)
actual_y = int(cua_y * 1080 / 720)
```

## Verification Challenges

### Finding Connections

The export script must search multiple locations for connection data:
```bash
# Search for server_instances.xml (snap version)
find /home/ga/snap/mysql-workbench-community -name "server_instances.xml" 2>/dev/null

# Search for connections.xml (standard version)
find /home/ga -name "connections.xml" 2>/dev/null
```

### Parsing Connection Data

The snap version stores connections in XML format within `server_instances.xml`:
```xml
<value type="object" struct-name="db.mgmt.ServerInstance">
  <value type="string" key="name">SakilaDB</value>
  <link type="object" struct-name="db.mgmt.Connection" key="connection">...</link>
</value>
```

### Visual Verification

Since connection config files may not be immediately written, VLM/CUA verification of screenshots is valuable for confirming task completion.

## Known Issues

### 1. dbus-launch Error

**Problem**: Snap version shows "Failed to execute child process 'dbus-launch'" when connecting.

**Cause**: Snap sandboxing restricts D-Bus access.

**Impact**: Password storage fails, but connections still work without saving password.

**Workaround**: Accept the error and proceed. Connection data is still saved.

### 2. Root Connection Failure

**Problem**: Connecting as 'root' via GUI fails with authentication error.

**Cause**: MySQL 8.0 uses `caching_sha2_password` by default.

**Solution**: Use the 'ga' user instead, or change root to use `mysql_native_password`.

### 3. Connection File Location

**Problem**: Export scripts couldn't find `connections.xml`.

**Cause**: Snap version uses `server_instances.xml` instead.

**Solution**: Updated export scripts to check both files.

## Task Design Considerations

### Task 1: connect_to_database

- Difficulty: Easy
- Timeout: 180s
- Key steps:
  1. Click + to add connection
  2. Fill Connection Name field ("SakilaDB")
  3. Change Username to "ga"
  4. Click OK
- Verification: Check server_instances.xml for connection name

### Task 2: run_sql_query

- Difficulty: Medium
- Timeout: 240s
- Query: `SELECT title, rental_rate FROM sakila.film WHERE rental_rate > 2.99`
- Expected: 336 films
- Output: /home/ga/Documents/exports/expensive_films.csv

### Task 3: export_data

- Difficulty: Medium
- Timeout: 240s
- Query: `SELECT * FROM world.city WHERE CountryCode = 'JPN'`
- Expected: 248 cities
- Output: /home/ga/Documents/exports/japan_cities.csv

## Performance Notes

- Environment setup: ~95-130 seconds total
- MySQL service start: ~5-10 seconds
- Workbench launch: ~10-15 seconds
- Database loading: ~10-20 seconds

## Best Practices

1. **Always use snap version** - Most reliable for Ubuntu 22.04+
2. **Check server_instances.xml** - Not connections.xml for snap
3. **Use 'ga' user** - More reliable than root for GUI connections
4. **Scale CUA coordinates** - Remember 1280x720 -> 1920x1080
5. **Handle dbus errors gracefully** - Connection still works despite error

## Resources

- [MySQL Workbench Manual](https://dev.mysql.com/doc/workbench/en/)
- [Sakila Sample Database](https://dev.mysql.com/doc/sakila/en/)
- [World Sample Database](https://dev.mysql.com/doc/world-setup/en/)
- [MySQL APT Repository Guide](https://dev.mysql.com/doc/mysql-apt-repo-quick-guide/en/)
