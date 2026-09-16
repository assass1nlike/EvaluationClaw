> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Oracle Database Environment - Development Notes

## Environment Overview

This document captures learnings and best practices from creating the Oracle Database XE environment for gym_anything.

### Key Components
- **Database**: Oracle XE 21c (via gvenzl/oracle-xe:21-slim Docker image)
- **GUI Client**: DBeaver Community Edition (snap package)
- **Schema**: HR (Human Resources) sample database with 107 employees
- **Base Image**: ubuntu-gnome-systemd_highres

## Architecture Decisions

### Docker-in-QEMU Pattern
The Oracle database runs as a Docker container inside the QEMU VM. This provides:
- Isolation from the host system
- Consistent Oracle configuration across runs
- Easy schema reset via container recreation

### Why gvenzl/oracle-xe Image
Chosen over official Oracle images because:
- No Oracle account required
- Smaller image size (~2GB vs ~5GB+)
- Faster startup time
- Pre-configured for development use

## Key Learnings

### 1. Oracle Container Startup Time
**Issue**: Oracle XE container takes 2-3 minutes to fully initialize on first run.

**Solution**:
- Implement `wait_for_oracle()` function with 300s timeout
- Use health check query: `SELECT 1 FROM DUAL;`
- Consider using checkpoints after Oracle is ready

### 2. SQL Execution in Scripts
**Issue**: Using `echo 'SQL' | sqlplus` in bash scripts causes issues with special characters and quoting.

**Solution**: Use here-documents for reliable SQL execution:
```bash
sudo docker exec -i oracle-xe sqlplus -s user/pass@host << EOSQL
SET HEADING OFF FEEDBACK OFF
SELECT * FROM table;
EOSQL
```

### 3. Docker Permissions
**Issue**: The `ga` user cannot run docker commands directly even though added to docker group (group membership not active in current session).

**Solution**: Always use `sudo docker` in scripts:
```bash
sudo docker exec oracle-xe ...
```

### 4. File Permissions in Container
**Issue**: Files copied to Oracle container may not be readable by Oracle user.

**Solution**: Use pipe/stdin instead of file references:
```bash
sudo docker exec -i oracle-xe sqlplus -s ... < /path/to/script.sql
```

### 5. DBeaver Installation
**Issue**: DBeaver requires `--classic` confinement when installed via snap.

**Solution**:
```bash
sudo snap install dbeaver-ce --classic
```

### 6. Oracle JDBC Driver
**Issue**: DBeaver needs Oracle JDBC driver which must be downloaded separately.

**Solution**: DBeaver's built-in driver download works, but takes time. Consider pre-installing the driver in the base image.

## Task Design Guidelines

### For Database Tasks
1. Use pre_task hook to record initial state:
   - Employee count
   - Max IDs for auto-increment tracking
   - Any baseline metrics

2. Store initial state in `/tmp/initial_*` files for verification

3. Export script should:
   - Query database for expected changes
   - Handle case-insensitive matching
   - Provide debug output for troubleshooting

### Verification Patterns
```python
def verify(traj, env_info, task_info):
    # Copy result from VM
    copy_from_env = env_info.get("copy_from_env")
    copy_from_env("/tmp/task_result.json", "/tmp/local_result.json")

    # Parse and verify
    with open("/tmp/local_result.json") as f:
        result = json.load(f)

    return {
        "passed": result.get("employee_found", False),
        "score": 100 if result.get("employee_found") else 0,
        "details": result
    }
```

## Common Issues and Fixes

### Issue: "ORA-01017: invalid username/password"
**Cause**: HR user not created or schema not loaded.
**Fix**: Ensure setup_oracle.sh completes successfully.

### Issue: GUI dialogs blocking automation
**Cause**: DBeaver shows statistics/sample database dialogs on first run.
**Fix**: Use xdotool to dismiss dialogs programmatically.

### Issue: Setup script timeout
**Cause**: Oracle container startup takes longer than default hook timeout.
**Fix**: Increase timeout in env.json or use checkpoints.

## Performance Considerations

### Resource Requirements
- RAM: 8GB minimum (Oracle XE needs ~4GB)
- CPU: 4 cores recommended
- Disk: ~10GB for Oracle data + container

### Checkpoint Strategy
Create checkpoints at these points:
1. `pre_start`: After DBeaver/tools installed, before Oracle container
2. `post_start`: After Oracle container running with HR schema loaded

## Future Improvements

1. **Pre-configured DBeaver**: Create a DBeaver connection profile file to skip manual connection setup
2. **Faster Oracle startup**: Consider using Oracle container snapshots
3. **Multiple schemas**: Add additional sample schemas (SCOTT, OE) for more task variety
4. **Async task support**: Allow tasks that wait for slow Oracle operations
