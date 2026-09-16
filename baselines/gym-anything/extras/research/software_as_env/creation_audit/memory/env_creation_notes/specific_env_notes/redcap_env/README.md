> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# LimeSurvey Environment Notes

## Overview

This environment was originally planned for REDCap, but was pivoted to **LimeSurvey** because REDCap requires a proprietary license from Vanderbilt University. LimeSurvey is a free and open-source survey tool that provides similar functionality.

LimeSurvey is the most popular free open-source survey tool on the web, used for creating online surveys and collecting research data.

## Architecture

- **Base**: `ubuntu-gnome-systemd_highres` (QEMU VM)
- **Survey Platform**: LimeSurvey 6 with Apache (Docker container)
- **Database**: MySQL 8.0 (Docker container)

## Default Credentials

- **LimeSurvey Admin**: `admin` / `Admin123!`
- **MySQL**: `limesurvey` / `limesurvey_pass`
- **MySQL Root**: `root` / `limesurvey_root_pw`

## Services and Ports

| Service | Port | Description |
|---------|------|-------------|
| LimeSurvey Web | 80 | Main LimeSurvey application |
| MySQL | 3306 | Database server (internal) |

## Database Schema

Key tables used for verification:

```sql
-- Surveys
SELECT sid FROM lime_surveys;

-- Survey titles/settings
SELECT sid, surveyls_title FROM lime_surveys_languagesettings;

-- Questions
SELECT qid, title FROM lime_questions WHERE sid = X;

-- Responses (table created per survey)
SELECT * FROM lime_survey_XXXX;
```

## Utility Scripts

The `task_utils.sh` provides helper functions:

```bash
# Query database
limesurvey_query "SELECT * FROM lime_surveys"

# Get survey count
get_survey_count

# Get question count for a survey
get_question_count $SURVEY_ID

# Check if survey exists
survey_exists "Customer Satisfaction"

# Get survey ID by title
get_survey_id "Customer Satisfaction"
```

## Interactive Testing Notes (2026-02-03)

### SSH Connection
- **Password**: `password123` (from env.json user_accounts)
- **Port**: Dynamically assigned, check runner output

### Firefox Issues
If Firefox shows "already running" error:
```bash
pkill -9 firefox
rm -f /home/ga/.mozilla/firefox/default.profile/.parentlock
rm -f /home/ga/.mozilla/firefox/default.profile/lock
DISPLAY=:1 firefox --new-instance "http://localhost/index.php/admin" &
```

### Screenshot Commands
```bash
# ImageMagick import works better than scrot
DISPLAY=:1 import -window root /tmp/screen.png
```

### ask_cua.py Coordinate Scaling
CUA returns coordinates normalized to 1280x720. Scale to actual resolution:
```python
# Scale from 1280x720 to 1920x1080
actual_x = int(cua_x * 1920 / 1280)
actual_y = int(cua_y * 1080 / 720)
```

### xdotool Actions
```bash
# Click at scaled coordinates
DISPLAY=:1 xdotool mousemove $X $Y click 1

# Type text
DISPLAY=:1 xdotool type "text"

# Press keys
DISPLAY=:1 xdotool key Return
DISPLAY=:1 xdotool key Tab
DISPLAY=:1 xdotool key ctrl+s
```

### LimeSurvey UI Flow
1. Login page at `http://localhost/index.php/admin`
2. After login, "Welcome" dialog appears with "Create a new survey" button
3. Survey creation form has "Survey title" field at top
4. "Create survey" button at bottom saves the survey
5. Success message appears with auto-created question group

### Database Table Names
LimeSurvey uses `lime_` prefix for all tables:
- `lime_surveys` - Survey metadata
- `lime_surveys_languagesettings` - Survey titles in different languages
- `lime_questions` - Survey questions
- `lime_survey_XXXX` - Response data (one table per survey)

### Known Issues
1. Firefox may need `--new-instance` flag to start properly
2. Database column names differ from documentation (check actual schema)
3. LimeSurvey auto-appends date to survey titles

## Task: create_survey

Creates a new survey titled "Customer Satisfaction Survey".

### Verification
The verifier checks:
1. Survey count increased
2. Survey with title containing "customer satisfaction" exists in database
3. Survey ID is valid

### Expected Result
```json
{
    "survey_found": true,
    "survey": {
        "survey_id": "332139",
        "title": "Customer Satisfaction Survey",
        "question_count": 1
    }
}
```

## References

- [LimeSurvey Official Site](https://www.limesurvey.org/)
- [LimeSurvey Manual](https://manual.limesurvey.org/)
- [Docker Image: martialblog/limesurvey](https://hub.docker.com/r/martialblog/limesurvey)
