> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Oracle Database Environment - Troubleshooting Guide

## Common Problems and Solutions

### 1. Environment Startup Issues

#### Problem: setup_oracle.sh times out
**Symptoms**:
```
[QemuApptainer] SSH command timed out: sudo -E bash -lc /workspace/scripts/setup_oracle.s...
```

**Cause**: Oracle container startup takes 2-5 minutes on first run.

**Solutions**:
1. Use a checkpoint that already has Oracle running
2. Increase the hook timeout in the runner configuration
3. Pre-pull the Oracle image in pre_start hook

#### Problem: Docker not starting
**Symptoms**:
```
Cannot connect to the Docker daemon
```

**Solution**: Ensure Docker service is started in pre_start hook:
```bash
systemctl enable docker
systemctl start docker
```

### 2. Database Connection Issues

#### Problem: ORA-01017 (invalid username/password)
**Cause**: HR user not created or wrong password.

**Diagnostic**:
```bash
# Test system user first
sudo docker exec oracle-xe sqlplus system/OraclePassword123@localhost:1521/XEPDB1

# Then test HR user
sudo docker exec oracle-xe sqlplus hr/hr123@localhost:1521/XEPDB1
```

**Fix**: Re-run HR user creation:
```sql
CREATE USER hr IDENTIFIED BY hr123
  DEFAULT TABLESPACE users
  TEMPORARY TABLESPACE temp
  QUOTA UNLIMITED ON users;
GRANT CONNECT, RESOURCE, CREATE SESSION, CREATE TABLE TO hr;
```

#### Problem: ORA-12541 (no listener)
**Cause**: Oracle listener not started yet.

**Solution**: Wait for Oracle to fully start:
```bash
# Wait until this returns 1
docker exec oracle-xe bash -c "echo 'SELECT 1 FROM DUAL;' | sqlplus -s system/OraclePassword123@localhost:1521/XE"
```

### 3. GUI Issues

#### Problem: DBeaver not found in app search
**Cause**: DBeaver not installed.

**Solution**:
```bash
sudo snap install dbeaver-ce --classic
```

#### Problem: DBeaver dialogs blocking automation
**Cause**: First-run dialogs (statistics collection, sample database).

**Solution**: Click through programmatically:
```bash
# Click "Continue" or "No" buttons using xdotool
DISPLAY=:1 xdotool mousemove X Y click 1
```

#### Problem: Cannot type in DBeaver fields
**Cause**: Wrong field focused or coordinates off.

**Solution**: Use Tab key navigation instead of mouse clicks:
```bash
DISPLAY=:1 xdotool key Tab
DISPLAY=:1 xdotool type "value"
```

### 4. Script Execution Issues

#### Problem: task_utils.sh functions fail with garbled output
**Symptoms**:
```
SP2-0306: Invalid option
```

**Cause**: Echo piping with special characters fails.

**Solution**: Use here-documents:
```bash
sudo docker exec -i oracle-xe sqlplus -s user/pass@host << EOSQL
SELECT * FROM table;
EOSQL
```

#### Problem: export_result.sh produces invalid JSON
**Cause**: SQL errors or special characters in output.

**Solution**:
1. Validate SQL queries independently first
2. Use proper JSON escaping
3. Add error handling in export script

### 5. Verification Issues

#### Problem: Verifier can't find result file
**Symptoms**:
```
SFTP: source not found: /tmp/add_employee_result.json
```

**Cause**: post_task hook (export_result.sh) failed.

**Solution**:
1. Check post_task hook output for errors
2. Manually run export script and debug
3. Verify file permissions

#### Problem: Verifier reports wrong result
**Cause**: Initial state files contain error messages instead of values.

**Solution**: Ensure pre_task hook runs successfully and writes clean values:
```bash
echo "107" > /tmp/initial_employee_count
echo "206" > /tmp/initial_max_employee_id
```

## Debugging Commands

### Check Oracle Container Status
```bash
sudo docker ps | grep oracle
sudo docker logs oracle-xe --tail 50
```

### Test Database Connectivity
```bash
sudo docker exec oracle-xe healthcheck.sh
```

### Check HR Schema
```bash
sudo docker exec oracle-xe bash -c "echo 'SELECT COUNT(*) FROM employees;' | sqlplus -s hr/hr123@localhost:1521/XEPDB1"
```

### View GUI Windows
```bash
DISPLAY=:1 wmctrl -l
```

### Take Screenshot
```bash
DISPLAY=:1 import -window root /tmp/debug.png
```

### Check Process Status
```bash
DISPLAY=:1 xdotool search --name DBeaver
```
