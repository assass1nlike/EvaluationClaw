> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Canvas LMS Environment Creation Notes

## Overview

Canvas LMS is an open-source Learning Management System. This environment uses the `lbjay/canvas-docker` fat container which includes all services (PostgreSQL, Redis, Rails, Apache) pre-configured.

## Configuration

### Docker Container
- **Image**: `lbjay/canvas-docker`
- **Container Name**: `canvas-lms`
- **Database**: `canvas_development` (PostgreSQL)
- **Admin Credentials**: `canvas@example.edu` / `canvas-docker`

### Port Mapping
```yaml
ports:
  - "80:80"       # Web interface (Apache)
  - "443:443"     # HTTPS
  - "3000:3000"   # Rails direct access
```

## Audit Fixes Applied (2026-02-01)

### Audit Summary
An independent audit identified the following critical issues:
1. **CRITICAL**: Credentials in setup scripts didn't match task descriptions
2. **CRITICAL**: No final state screenshots showing task completion
3. **MINOR**: Due date not validated in create_assignment verifier
4. **MINOR**: Inconsistent user role for assignment creation

## Fixes Applied (2026-02-01)

### 1. Credential Mismatch Fix
**Issue**: Task descriptions referenced `admin@example.com / Admin1234!` but the fat container uses different credentials.

**Fix**: Updated all task descriptions to use correct credentials:
- Email: `canvas@example.edu`
- Password: `canvas-docker`

**Files Modified**:
- `tasks/create_course/task.json`
- `tasks/create_assignment/task.json`
- `tasks/enroll_student/task.json`

### 2. Database Configuration Fix
**Issue**: Scripts referenced `canvas_production` database but fat container uses `canvas_development`.

**Fix**: Updated all scripts to use correct database:
- Container name: `canvas-lms` (not `canvas-postgres`)
- Database name: `canvas_development` (not `canvas_production`)

**Files Modified**:
- `scripts/task_utils.sh`
- `scripts/setup_canvas.sh`
- `tasks/create_course/export_result.sh`
- `tasks/create_assignment/export_result.sh`
- `tasks/enroll_student/export_result.sh`

### 3. Enrollment Verifier Enhancement
**Issue**: Verifier didn't check if enrollment was specifically a student enrollment.

**Fix**: Added enrollment type verification:
```python
enrollment_type = enrollment.get('type', '')
is_student_enrollment = enrollment_type.lower() == 'studentenrollment'
```

**File Modified**: `tasks/enroll_student/verifier.py`

### 4. Due Date Validation Added (Audit Fix)
**Issue**: The `create_assignment` verifier didn't validate that a due date was set.

**Fix**: Added 5th criterion to verify due date is set:
```python
# Criterion 4: Due date is set (any valid date)
due_at = assignment.get('due_at', '')
due_date_set = bool(due_at and due_at.strip() and due_at.strip().lower() != 'null')
if due_date_set:
    criteria_passed += 1
    feedback_parts.append(f"Due date set: {due_at}")
else:
    feedback_parts.append("Due date NOT set (required)")
```

**File Modified**: `tasks/create_assignment/verifier.py`
- Changed from 4 criteria to 5 criteria (100% pass required)
- Added `due_date_set` subscore

### 5. Setup Script Credential Fixes (Audit Fix)
**Issue**: Setup scripts displayed wrong credentials to agents.

**Files Modified**:
- `tasks/create_course/setup_task.sh` - Changed from `admin@example.com/Admin1234!` to `canvas@example.edu/canvas-docker`
- `tasks/enroll_student/setup_task.sh` - Changed from `admin@example.com/Admin1234!` to `canvas@example.edu/canvas-docker`
- `tasks/create_assignment/setup_task.sh` - Changed from `teacher1/Teacher1234!` to `canvas@example.edu/canvas-docker`

### 6. Strengthened Due Date Validation (Audit Fix #2)
**Issue**: Due date validation only checked if value was non-empty, allowing invalid dates.

**Fix**: Added comprehensive due date validation:
```python
def parse_due_date(due_at_str):
    """Parse Canvas due date string and return datetime object."""
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(due_at_str.strip(), fmt)
        except ValueError:
            continue
    return None

# Validation checks:
# 1. Due date must be parseable
# 2. Due date must be at least 1 hour in the future
```

**File Modified**: `tasks/create_assignment/verifier.py`

### 7. Added Workflow State Verification (Audit Fix #2)
**Issue**: Assignment verifier didn't check if assignment was published.

**Fix**: Added 6th criterion to verify workflow_state='published':
```python
# Criterion 5: Assignment is published (workflow_state = 'published')
workflow_state = assignment.get('workflow_state', '')
is_published = workflow_state.lower() == 'published'
```

**Files Modified**:
- `tasks/create_assignment/verifier.py` - Added is_published criterion (now 6 total criteria)
- `tasks/create_assignment/export_result.sh` - Added workflow_state to SQL query and JSON output

### 8. Screenshot Persistence (Audit Fix #2)
**Issue**: Screenshots were saved to /tmp and lost when container stopped.

**Fix**: Export scripts now copy screenshots to /workspace/evidence/:
```bash
mkdir -p /workspace/evidence 2>/dev/null || true
cp /tmp/task_end_screenshot.png /workspace/evidence/<task>_final.png
cp /tmp/task_start_screenshot.png /workspace/evidence/<task>_initial.png
```

**Files Modified**:
- `tasks/create_course/export_result.sh`
- `tasks/create_assignment/export_result.sh`
- `tasks/enroll_student/export_result.sh`

### 4. Setup Script Update
**Issue**: Setup script was designed for multi-container setup, not fat container.

**Fix**: Simplified setup script for fat container:
- Removed references to separate `canvas-web`, `canvas-postgres`, `canvas-redis` containers
- Updated database queries to use `canvas-lms` container
- Corrected credentials in setup documentation

**File Modified**: `scripts/setup_canvas.sh`

## Known Issues

### Container Startup Time (CRITICAL)
The Canvas fat container requires significant time to start:
1. PostgreSQL initialization: ~30 seconds
2. Rails boot: ~60-90 seconds
3. Apache proxy setup: ~10 seconds
4. **Total initialization: 2-3 minutes**

**Problem Identified in Audit #4**: 67% of test episodes (4/6) started with Canvas inaccessible, showing:
- "The connection was reset" errors
- "Unable to connect" errors
- Pages loading indefinitely

**Solution Implemented**: Pre-task health checks in all setup_task.sh scripts:
```bash
# In task_utils.sh
ensure_canvas_ready_for_task()  # Waits up to 120s for Canvas, refreshes Firefox
```

### Memory Requirements
Canvas requires substantial memory:
- Minimum: 8GB RAM
- Recommended: 10GB RAM

The `env.json` is configured with `"mem_gb": 10`.

### First-Time Container Pull
The `lbjay/canvas-docker` image is ~2GB. First pull may take significant time depending on network speed.

### 9. Canvas Health Check Implementation (Audit Fix #4)
**Issue**: 67% of test episodes showed Canvas was inaccessible at task start (connection errors, pages not loading).

**Fix**: Added comprehensive pre-task health check to `task_utils.sh`:
```bash
wait_for_canvas_ready() {
    # Polls Canvas HTTP endpoint until 200/302/303 response
    # Timeout: 120 seconds
}

ensure_canvas_ready_for_task() {
    # 1. Wait for Canvas server to respond
    # 2. Ensure Firefox is running
    # 3. Focus and maximize Firefox window
    # 4. Refresh page to clear any connection errors
    # 5. Take screenshot only after Canvas is confirmed ready
}
```

**All setup_task.sh scripts now call** `ensure_canvas_ready_for_task` before recording initial state.

**Task descriptions updated** to include: "Note: If Canvas shows a connection error or is loading slowly, wait a few seconds and refresh the page - the server may still be initializing."

**Files Modified**:
- `scripts/task_utils.sh` - Added health check functions
- `tasks/create_course/setup_task.sh` - Added health check call
- `tasks/create_assignment/setup_task.sh` - Added health check call
- `tasks/enroll_student/setup_task.sh` - Added health check call
- `tasks/*/task.json` - Updated descriptions with loading delay note
- `evidence_docs/README.md` - Updated to accurately reflect reliability issues

### 10. Task/Verifier Mismatch Fix (Audit Fix #5)
**Issue**: create_assignment task said "any date is acceptable" but verifier required future date (>1 hour).

**Fix**: Updated task description to match verifier requirements:
- Changed "Due Date: Next week (any date is acceptable)"
- To: "Due Date: Set to a date at least one week in the future"

**File Modified**: `tasks/create_assignment/task.json`

### 11. Workflow State Verification for create_course (Audit Fix #5)
**Issue**: create_course verifier didn't check if course was in 'available' state.

**Fix**: Added 5th criterion to verify workflow_state='available':
```python
# Criterion 4: Course is in 'available' state (workflow_state)
workflow_state = course.get('workflow_state', '')
is_available = workflow_state.lower() == 'available'
```

**Files Modified**:
- `tasks/create_course/verifier.py` - Added is_available criterion (now 5 total criteria)
- `tasks/create_course/export_result.sh` - Added workflow_state to SQL query and JSON output

### 12. Evidence Documentation Accuracy Fix (Audit Fix #5)
**Issue**: README claimed tasks PASSED with 100% scores and referenced "final state" screenshots, but the screenshots only showed the login page twice.

**Fix**: Updated evidence_docs/README.md to:
- Clearly note that 01_login_page.png and 03_final_state.png both show the login page (NOT a final state)
- Remove claims of verified task completion
- Document what visual evidence SHOULD be captured
- Mark visual evidence as "NOT CAPTURED"

**File Modified**: `evidence_docs/README.md`

## Task Descriptions

### create_course
Create a new course (e.g., "Introduction to Python Programming" with code "CS101").

### create_assignment
Create an assignment "Lab Report 1" with 100 points in the BIO101 course.

### enroll_student
Enroll a student (e.g., `jsmith`) in a course (e.g., BIO101) as a student.

## Verification Strategy

All tasks use the two-part verification pattern:
1. **Export Script** (runs in VM): Queries database, takes screenshots, saves JSON to `/tmp/`
2. **Verifier** (runs on host): Uses `copy_from_env` to retrieve JSON and validate criteria

### Database Query Example
```bash
docker exec canvas-lms psql -U canvas -d canvas_development -t -A -c "SELECT * FROM courses WHERE workflow_state='available'"
```

## References

- [Canvas LMS Documentation](https://canvas.instructure.com/doc/api/)
- [lbjay/canvas-docker on Docker Hub](https://hub.docker.com/r/lbjay/canvas-docker)
- [Canvas GitHub Repository](https://github.com/instructure/canvas-lms)
