> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# uniCenta oPOS Environment Notes

## Critical Lessons Learned

### 1. JDBC URL Format
**The `db.URL` property must NOT include the database name.** uniCenta appends the database name and additional parameters (like `?zeroDateTimeBehavior=convertToNull`) automatically. If you include the database name in `db.URL`, it gets doubled:
```
# WRONG: db.URL=jdbc:mysql://localhost:3306/unicentaopos
# Result: connects to "unicentaoposunicentaopos" (doubled!)
# 
# CORRECT: db.URL=jdbc:mysql://localhost:3306/
```

### 2. The `db.driver` Property
The properties file MUST include `db.driver=com.mysql.jdbc.Driver`. The app reads this property to load the JDBC driver class. This is separate from `db.engine=MySQL` which is used for SQL dialect selection.

### 3. MySQL Connector Version
MySQL Connector/J 5.1.x has timezone and classloader issues with MySQL 8.0 + Java 11. Use **Connector 8.0.33** instead:
```
wget -O lib/mysql-connector-j-8.0.33.jar \
    "https://repo1.maven.org/maven2/com/mysql/mysql-connector-j/8.0.33/mysql-connector-j-8.0.33.jar"
```
Note: The connector MUST be on the `-cp` classpath for `DriverManager` to find it. While the app uses `DriverWrapper` to handle classloader isolation, having the driver on the classpath ensures compatibility.

### 4. Schema Creation: `$FILE{}` Placeholders
The schema SQL (`MySQL-create.sql`) uses `$FILE{/com/openbravo/pos/templates/...}` placeholders for:
- Role permissions XML
- Template resources (menus, tickets, receipts)
- Image resources

These only work inside the Java app. When loading via `mysql` CLI:
1. Use `-f` (force) flag to skip `$FILE{}` INSERT errors
2. Extract template files from the JAR: `jar xf unicentaopos.jar com/openbravo/pos/templates/`
3. Insert them via Python/pymysql using parameterized queries

### 5. ROW_FORMAT for MySQL 8.0
The schema SQL uses `ROW_FORMAT = Compact` which fails with MySQL 8.0 due to row size limits. Fix:
```bash
sed -i 's/ROW_FORMAT = Compact/ROW_FORMAT = DYNAMIC/g' MySQL-create.sql
```
Also set `SET GLOBAL innodb_default_row_format=DYNAMIC;` before loading.

### 6. Launcher Script: `-cp` vs `-jar`
The official `start.sh` uses `-cp` (classpath) NOT `-jar`. The MANIFEST Class-Path lists lib JARs, but the app loads them dynamically via `dirname.path`. The launcher must set `-Ddirname.path=/opt/unicentaopos/` for dynamic class loading to work.

### 7. Default Users
Default users with NULL passwords (no PIN required):
- Administrator (role 0) - full access
- Manager (role 1)
- Employee (role 2)  
- Guest (role 3)

### 8. SourceForge Download
- v4.6.4 installer: `unicentaopos-4.6.4-linux-x64-installer.run` (~148 MB)
- BitRock installer supports `--mode unattended --prefix /path`
- The installer may report "Java JRE not found" but still installs files

## File Locations
| File | Path |
|------|------|
| Main JAR | `/opt/unicentaopos/unicentaopos.jar` |
| Lib JARs | `/opt/unicentaopos/lib/` |
| Locales | `/opt/unicentaopos/locales/` |
| Reports | `/opt/unicentaopos/reports/` |
| User config | `/home/ga/unicentaopos.properties` |
| App log | `/home/ga/.unicenta/unicenta-YYYY-MM-DD.log` |
| DB backup | `/opt/unicentaopos/unicentaopos_backup.sql` |
| Schema SQL | `/opt/unicentaopos/sql/MySQL-create-fixed.sql` |
| Templates | `/tmp/unicenta_resources/com/openbravo/pos/templates/` |

## Database Schema
- 52 tables total
- Key tables: products, categories, taxcategories, taxes, customers, tickets, ticketlines, payments, people, roles, resources, applications
- Uses lowercase table names on MySQL
