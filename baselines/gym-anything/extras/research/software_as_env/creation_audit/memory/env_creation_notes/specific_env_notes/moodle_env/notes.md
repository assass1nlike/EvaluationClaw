> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Moodle LMS Environment Notes

## Overview

Moodle (Modular Object-Oriented Dynamic Learning Environment) is an open-source Learning Management System. This environment runs Moodle natively via Apache+PHP on a QEMU VM, with MariaDB in Docker, and Firefox for GUI interaction.

## Architecture

- **Base Image**: `ubuntu-gnome-systemd_highres`
- **Moodle**: Native installation via git clone (MOODLE_405_STABLE branch)
- **Web Server**: Apache 2.4 with mod_php (PHP 8.1)
- **Database**: MariaDB 10.11 Docker container
- **Browser**: Firefox with pre-configured profile
- **Resources**: 4 CPU, 8GB RAM, network enabled

## Installation Approach

The environment uses a native LAMP installation (not Docker for Moodle itself):

1. **pre_start (install_moodle.sh)**: Installs Docker (for MariaDB), Apache, PHP with all Moodle-required extensions, downloads Moodle source via `git clone`
2. **post_start (setup_moodle.sh)**: Starts MariaDB Docker container, runs Moodle CLI installer, generates test data, launches Firefox

### Why Native Instead of Docker for Moodle?

The Bitnami Moodle Docker image (`bitnami/moodle`) was originally planned but was found to be unavailable (0 tags on Docker Hub). The native LAMP approach is more reliable and gives direct access to Moodle CLI tools.

### Key Paths

- Moodle source: `/var/www/html/moodle`
- Moodle data: `/var/moodledata`
- Apache config: `/etc/apache2/sites-available/moodle.conf`
- Docker compose: `/home/ga/moodle/docker-compose.yml`

### Database Credentials

- Host: `127.0.0.1:3306` (MariaDB Docker exposed on host)
- Database: `moodle`
- User: `moodleuser`
- Password: `moodlepass`
- Root password: `rootpass`
- Docker container: `moodle-mariadb`

## Pre-loaded Data

The setup script creates realistic test data using Moodle PHP CLI:

### Course Categories
- Science (SCI)
- Humanities (HUM)
- Engineering (ENG)

### Sample Courses
- Introduction to Biology (BIO101) - Science category
- World History (HIST201) - Humanities category
- Computer Science Fundamentals (CS110) - Engineering category

### Test Users
| Username | Name | Role | Password |
|----------|------|------|----------|
| admin | Admin User | Admin | Admin1234! |
| teacher1 | Professor Anderson | Teacher | Teacher1234! |
| teacher2 | Dr. Martinez | Teacher | Teacher1234! |
| jsmith | Jane Smith | Student | Student1234! |
| mjones | Michael Jones | Student | Student1234! |
| awilson | Alice Wilson | Student | Student1234! |
| bbrown | Bob Brown | Student | Student1234! |
| cgarcia | Carlos Garcia | Student | Student1234! |
| dlee | Diana Lee | Student | Student1234! |
| epatel | Emily Patel | Student | Student1234! |
| fkim | Frank Kim | Student | Student1234! |

### Pre-enrolled Students
- BIO101: jsmith, mjones, awilson (teacher1 as instructor)
- HIST201: bbrown, cgarcia, dlee (teacher2 as instructor)

## Database Access

### From Inside the VM
```bash
# Query utility
moodle-db-query "SELECT COUNT(*) FROM mdl_course"

# Direct Docker exec
docker exec moodle-mariadb mysql -u moodleuser -pmoodlepass moodle -e "SELECT * FROM mdl_course"

# Via task_utils.sh functions
source /workspace/scripts/task_utils.sh
moodle_query "SELECT COUNT(*) FROM mdl_course"
get_course_by_shortname "BIO101"
```

### Key Moodle Tables
| Table | Purpose |
|-------|---------|
| `mdl_course` | Courses (id=1 is the site course) |
| `mdl_course_categories` | Course categories |
| `mdl_user` | User accounts |
| `mdl_user_enrolments` | Enrollment records |
| `mdl_enrol` | Enrollment methods |
| `mdl_role_assignments` | Role assignments (student=5, teacher=3) |
| `mdl_assign` | Assignment activities |
| `mdl_assign_submission` | Assignment submissions |
| `mdl_assign_plugin_config` | Assignment plugin configs (submission types) |

## Tasks

### create_course
- Creates a new course "Data Science 101" (DS101) in Science category
- Verifies via database query for the course record
- Checks: course exists, fullname matches, shortname matches, category matches
- Pass threshold: 75% (3 of 4 criteria)

### enroll_student
- Enrolls Emily Patel (epatel) in Introduction to Biology (BIO101)
- Verifies via enrollment table query
- Checks: user is enrolled, correct role (student), newly enrolled (not pre-existing)
- Pass threshold: 66% (2 of 3 criteria)

### create_assignment
- Creates assignment "Lab Report: Cell Biology" in BIO101 with online text submission
- Verifies via assignment table query and plugin config
- Checks: assignment exists, name matches, has description, newly created
- Pass threshold: 75% (3 of 4 criteria)

## Service Timing

- MariaDB Docker: Ready in ~20-30s
- Moodle CLI installer: ~60s (database schema + plugin setup)
- Test data generation: ~10s
- Total env setup: ~100-150s
- Firefox startup: ~5s after setup

## Verification Strategy

All tasks use the two-part verification pattern:
1. `export_result.sh` queries the Moodle database via Docker and saves JSON to `/tmp/`
2. `verifier.py` uses `copy_from_env` to read the JSON and evaluate criteria

### Case-Insensitive Matching
All database queries use `LOWER(TRIM(...))` for case-insensitive matching with fallback to partial matches using `LIKE`.

### Anti-gaming
- Initial state is recorded before the task (counts, enrollment status)
- Verification checks for "newly created" records, not just existence
- Multiple criteria must be met (course name + shortname + category, not just one)

## PHP Configuration Notes

- `max_input_vars = 5000` is required by Moodle (set in both CLI and Apache php.ini)
- `memory_limit = 256M` for the Moodle installer
- Both `/etc/php/8.1/cli/php.ini` and `/etc/php/8.1/apache2/php.ini` are configured
- The Moodle CLI installer must be run from the Moodle directory (to avoid chdir permission errors)

## Known Issues

- Email notification errors during enrollment are benign (noreply@localhost is not a valid mail host)
- The Moodle installer may show warnings about `chdir` if not run from the Moodle directory (fixed in current setup)
