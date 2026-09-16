> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# MS SQL Server Environment Notes

## Environment Summary

The MS SQL Server environment provides a fully functional SQL Server 2022 instance with Azure Data Studio for GUI-based database management.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    QEMU VM (Ubuntu 22.04)                   │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │           Azure Data Studio (Snap)                   │   │
│  │  - Query editor with syntax highlighting             │   │
│  │  - Results grid with export capabilities             │   │
│  │  - Connection to localhost:1433                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                            │                                │
│                            ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │            Docker Container (mssql-server)           │   │
│  │  - mcr.microsoft.com/mssql/server:2022-latest       │   │
│  │  - AdventureWorks2022 database                       │   │
│  │  - Port 1433 exposed                                 │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Installation Quirks

### Azure Data Studio Installation

**Problem**: Direct download URLs from Microsoft (`go.microsoft.com/fwlink/...`) are unreliable and often redirect to Bing or return HTML instead of the actual .deb file.

**Solution**: Use Snap for installation:
```bash
apt-get install -y snapd
systemctl enable snapd
systemctl start snapd
sleep 2
snap install azuredatastudio
```

### Docker Compose Healthcheck Format

**Problem**: Older docker-compose versions require specific healthcheck format.

**Wrong**:
```yaml
healthcheck:
  test: ["/opt/mssql-tools18/bin/sqlcmd", "-S", "localhost", ...]
```

**Correct**:
```yaml
healthcheck:
  test: ["CMD-SHELL", "/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P 'password' -C -Q 'SELECT 1' || exit 1"]
```

### Microsoft GPG Key Issues

**Problem**: Microsoft's package signing key may fail verification:
```
GPG error: The following signatures couldn't be verified because the public key is not available: NO_PUBKEY EB3E94ADBE1229CF
```

**Solution**: For mssql-tools18, this error can usually be ignored as the tools will still install, or use Docker container's built-in tools instead.

## Service Timing

### SQL Server Startup

SQL Server requires 30-60 seconds after container start to fully initialize. Use polling:

```bash
wait_for_mssql() {
    local timeout=${1:-180}
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if docker exec mssql-server /opt/mssql-tools18/bin/sqlcmd \
            -S localhost -U sa -P "$SA_PASSWORD" -C \
            -Q "SELECT 1" 2>/dev/null | grep -q "1"; then
            echo "SQL Server is ready after ${elapsed}s"
            return 0
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
    return 1
}
```

### Azure Data Studio Window Detection

ADS takes 4-8 seconds to launch and show window. Use wmctrl polling:

```bash
for i in {1..30}; do
    if DISPLAY=:1 wmctrl -l 2>/dev/null | grep -qi "azure\|data studio"; then
        echo "Azure Data Studio window detected after ${i}s"
        break
    fi
    sleep 1
done
```

## Database Schema Notes

### AdventureWorks2022 Key Tables

| Schema | Table | Description | Row Count |
|--------|-------|-------------|-----------|
| Production | Product | All products | 504 |
| Sales | SalesOrderHeader | Order headers | 31,465 |
| Sales | SalesOrderDetail | Order line items | 121,317 |
| Person | Person | People records | 19,972 |

### Common Query Patterns

**Top-selling products by quantity:**
```sql
SELECT TOP 10
    p.Name AS ProductName,
    SUM(sod.OrderQty) AS TotalQuantitySold
FROM Sales.SalesOrderDetail sod
JOIN Production.Product p ON sod.ProductID = p.ProductID
GROUP BY p.Name
ORDER BY TotalQuantitySold DESC
```

**Products by revenue:**
```sql
SELECT TOP 10
    p.Name AS ProductName,
    SUM(sod.LineTotal) AS TotalRevenue
FROM Sales.SalesOrderDetail sod
JOIN Production.Product p ON sod.ProductID = p.ProductID
GROUP BY p.Name
ORDER BY TotalRevenue DESC
```

## Verification Gotchas

### CSV Export Format

Azure Data Studio exports CSV with:
- Header row by default
- Quoted strings for values containing commas
- UTF-8 encoding

Example output:
```csv
ProductName,TotalQuantitySold
AWC Logo Cap,8311
"Sport-100 Helmet, Blue",6743
```

### File Path Considerations

Default export path: `/home/ga/Documents/exports/`

Must create directory before export:
```bash
mkdir -p /home/ga/Documents/exports
chown ga:ga /home/ga/Documents/exports
```

### Result JSON Structure

Export script should produce:
```json
{
    "mssql_running": true,
    "ads_running": true,
    "output_file_exists": true,
    "output_row_count": 10,
    "output_has_headers": true,
    "correct_row_count": true,
    "known_products_found": 5,
    "correct_top_product": true,
    "actual_top_product": "AWC Logo Cap",
    "products_found": "AWC Logo Cap;Water Bottle...",
    "timestamp": "2026-02-02T17:33:35+00:00"
}
```

## Interactive Testing Tips

### Coordinate Scaling

`ask_cua.py` returns coordinates for 1280x720 resolution. Scale for actual resolution:

```python
# 1280x720 → 1920x1080
actual_x = int(cua_x * 1920 / 1280)
actual_y = int(cua_y * 1080 / 720)
```

### Common xdotool Commands

```bash
# Click at coordinates
DISPLAY=:1 xdotool mousemove $x $y click 1

# Double-click
DISPLAY=:1 xdotool mousemove $x $y click --repeat 2 1

# Right-click
DISPLAY=:1 xdotool mousemove $x $y click 3

# Type text
DISPLAY=:1 xdotool type 'SELECT * FROM table'

# Key combinations
DISPLAY=:1 xdotool key ctrl+a
DISPLAY=:1 xdotool key ctrl+s
DISPLAY=:1 xdotool key Return
```

### Azure Data Studio UI Locations

- **Run button**: Top toolbar, green play icon
- **Database dropdown**: Below toolbar, shows current database
- **Results grid**: Bottom pane, shows query results
- **Context menu**: Right-click on results for export options

## Known Issues

1. **First Connection Dialog**: Azure Data Studio shows "Trust server certificate" dialog on first connection - must set to True

2. **Keyring Warning**: May show "OS keyring couldn't be identified" - use "weaker encryption" option

3. **Slow First Query**: First query after restore may be slow (database caching)

## Resources

- [AdventureWorks Schema](https://docs.microsoft.com/en-us/sql/samples/adventureworks-install-configure)
- [Azure Data Studio Docs](https://docs.microsoft.com/en-us/azure-data-studio/)
- [SQL Server Docker Image](https://hub.docker.com/_/microsoft-mssql-server)
