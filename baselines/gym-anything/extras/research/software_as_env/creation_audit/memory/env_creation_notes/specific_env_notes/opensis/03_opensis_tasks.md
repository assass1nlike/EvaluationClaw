> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenSIS Task Design Patterns

## Overview

This document describes how to design and implement tasks for the OpenSIS gym_anything environment.

## Task Structure

Each task should have:
```
tasks/<task_name>/
├── task.json           # Task configuration
├── setup_task.sh       # Task-specific setup
└── verify_task.py      # Task verification script
```

## UI Navigation

### Important: OpenSIS Uses Iframes

The main OpenSIS interface uses iframes for content loading:
- Main page (`index.php`) contains a container iframe
- Content is loaded via `Modules.php?modname=<module_path>`

### Navigation Pattern

**Via JavaScript (recommended for automation):**
```javascript
// Change iframe content
var iframe = document.querySelector('iframe');
iframe.src = 'Modules.php?modname=students/Student.php';
```

**Via Menu Clicks:**
1. Expand module menu (e.g., "Students")
2. Click submenu item (e.g., "Add a Student")

### Module URLs

| Task | Module URL |
|------|------------|
| Student Search | `Modules.php?modname=students/Student.php` |
| Add Student | `Modules.php?modname=students/Student.php&include=GeneralInfoInc&student_id=new` |
| Attendance | `Modules.php?modname=attendance/TakeAttendance.php` |
| Grades | `Modules.php?modname=grades/Grades.php` |
| Courses | `Modules.php?modname=scheduling/Courses.php` |

## Task Examples

### 1. add_student Task

**Objective**: Add a new student record

**Setup (setup_task.sh)**:
```bash
# Ensure services running
# Open Chrome to login page
# Optionally pre-fill some data
```

**Verification (verify_task.py)**:
```python
def verify_student_added(traj, env_info, task_info):
    """Verify student was added via database query."""
    query = """
    SELECT student_id, first_name, last_name 
    FROM students 
    WHERE first_name='Emily' AND last_name='Johnson'
    """
    result = run_db_query(env_info, query)
    
    if result and len(result) > 0:
        return {
            "passed": True,
            "score": 100,
            "feedback": "Student record found in database"
        }
    
    # Fallback to VLM if database check fails
    return verify_via_vlm(traj, "success message for student creation")
```

### 2. search_student Task

**Objective**: Find an existing student

**Setup**:
- Pre-insert a "Sample Student" record
- Open Chrome to Students page

**Verification**:
- VLM check for student info displayed
- Or check session/request logs for search execution

### 3. record_attendance Task

**Objective**: Mark attendance for a student

**Setup**:
- Ensure student exists
- Ensure enrollment record exists
- Open Chrome to attendance page

**Verification**:
```python
def verify_attendance_recorded(traj, env_info, task_info):
    query = """
    SELECT * FROM attendance_day 
    WHERE student_id = (
        SELECT student_id FROM students 
        WHERE first_name='Sample' AND last_name='Student'
    ) 
    AND school_date = CURDATE()
    """
    result = run_db_query(env_info, query)
    return {"passed": len(result) > 0, "score": 100 if len(result) > 0 else 0}
```

### 4. create_course Task

**Objective**: Create a new course

**Verification**:
```python
def verify_course_created(traj, env_info, task_info):
    query = "SELECT * FROM courses WHERE course_title='Advanced Chemistry'"
    result = run_db_query(env_info, query)
    return {"passed": len(result) > 0}
```

### 5. add_grade Task

**Objective**: Enter a grade for a student

**Setup**:
- Ensure student exists
- Ensure course exists
- Ensure student enrolled in course

**Verification**:
```python
def verify_grade_added(traj, env_info, task_info):
    query = """
    SELECT * FROM gradebook_grades 
    WHERE student_id = (SELECT student_id FROM students WHERE first_name='Sample')
    """
    result = run_db_query(env_info, query)
    return {"passed": len(result) > 0}
```

## Verification Best Practices

### 1. Database First
Always prefer database queries for verification - they provide definitive answers.

### 2. VLM Fallback
Use VLM verification when:
- Task involves viewing information (not modifying)
- Database state is ambiguous
- UI confirmation is the primary indicator

### 3. Hybrid Approach
```python
def verify_task(traj, env_info, task_info):
    # Try database first
    db_result = check_database(env_info)
    if db_result["definitive"]:
        return db_result
    
    # Fall back to VLM
    vlm_result = check_screenshot(traj)
    
    # Combine scores
    return {
        "passed": db_result["partial"] or vlm_result["passed"],
        "score": max(db_result["score"], vlm_result["score"])
    }
```

## Form Field Mapping

Common form fields in OpenSIS (discovered via testing):

| Field Label | Input Name Pattern | Type | Notes |
|-------------|-------------------|------|-------|
| First Name | `students[FIRST_NAME]` or `*FIRST_NAME*` | text | |
| Last Name | `students[LAST_NAME]` or `*LAST_NAME*` | text | |
| Gender | `students[GENDER]` or `*GENDER*` | select | Options: Male, Female |
| Birth Date | `students[BIRTHDATE]` or `*BIRTHDATE*` | text | Format: MM/DD/YYYY |
| Grade Level | `students[GRADE_ID]` or `*GRADE*` | select | Grade 9, Grade 10, etc. |
| Email | `students[EMAIL]` or `*EMAIL*` | email | |

**Note:** Use CSS selector `input[name*="FIRST_NAME"]` to match any variation.

### Accessing Form Fields via JavaScript

Since Selenium's `switch_to.frame()` often fails with OpenSIS, use JavaScript:

```python
# Fill form via JavaScript (works reliably)
driver.execute_script("""
    var iframe = document.querySelector('iframe');
    if (iframe && iframe.contentDocument) {
        var doc = iframe.contentDocument;

        // First name
        var fn = doc.querySelector('input[name*="FIRST_NAME"]');
        if (fn) fn.value = 'Emily';

        // Last name
        var ln = doc.querySelector('input[name*="LAST_NAME"]');
        if (ln) ln.value = 'Johnson';

        // Gender (select)
        var gender = doc.querySelector('select[name*="GENDER"]');
        if (gender) {
            for (var i = 0; i < gender.options.length; i++) {
                if (gender.options[i].text === 'Female') {
                    gender.selectedIndex = i;
                    break;
                }
            }
        }

        // Birth date
        var dob = doc.querySelector('input[name*="BIRTHDATE"]');
        if (dob) dob.value = '03/15/2008';
    }
""")
```

## Testing Tasks Locally

```bash
# Start environment
python -c "
from gym_anything.runtime.runners.qemu_apptainer import QemuApptainerRunner
# ... setup code
runner.start()
print(f'SSH: {runner.ssh_port}')
"

# SSH into VM
ssh -p <port> ga@localhost

# Run setup script
sudo /workspace/tasks/<task_name>/setup_task.sh

# Test verification manually
python /workspace/tasks/<task_name>/verify_task.py
```
