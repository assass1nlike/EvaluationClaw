> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# wger_env Notes

**Application**: wger Workout Manager (Django fitness tracker)
**Docker image**: wger/server:latest (pinned to 2.5-dev in practice)
**URL**: http://localhost
**Admin creds**: admin / adminadmin

---

## Architecture

- **4-service Docker Compose** stack: wger-web (gunicorn on :8000), wger-nginx (reverse proxy on :80), wger-db (PostgreSQL 15-alpine), wger-cache (Redis-alpine)
- **No celery** containers — must set `USE_CELERY=False` in prod.env or web container fails to start
- Config files mounted at `/workspace/config/`: docker-compose.yml, prod.env, nginx.conf
- **Startup time**: ~418s total (Docker pull ~3min + DB migrations ~1min + exercise sync ~30s)

---

## Critical Configuration Fixes

### 1. Redis Cache TypeError (wger + redis-py 6.4.0)

**Problem**: wger's `settings/main.py` always injects `OPTIONS: {'CLIENT_CLASS': env.str('DJANGO_CACHE_CLIENT_CLASS', '')}` when `DJANGO_CACHE_BACKEND` is set. The built-in `django.core.cache.backends.redis.RedisCache` passes `CLIENT_CLASS` directly to redis-py 6.x's `ConnectionPool`, which rejects it: `TypeError: AbstractConnection.__init__() got an unexpected keyword argument 'CLIENT_CLASS'`.

**Fix**: Use `django-redis` backend (already installed in wger image) which handles `CLIENT_CLASS` at the client level, not the connection pool level:
```
DJANGO_CACHE_BACKEND=django_redis.cache.RedisCache
DJANGO_CACHE_LOCATION=redis://cache:6379/1
DJANGO_CACHE_CLIENT_CLASS=django_redis.client.DefaultClient
```

### 2. Celery Must Be Disabled
```
USE_CELERY=False
SYNC_EXERCISES_CELERY=False
SYNC_INGREDIENTS_CELERY=False
SYNC_EXERCISE_IMAGES_CELERY=False
SYNC_EXERCISE_VIDEOS_CELERY=False
```
Without `USE_CELERY=False`, wger-web connects to celery broker on startup and crashes since there's no celery container.

### 3. DJANGO_DEBUG=False Required for collectstatic (React SPA)

**Problem**: wger's entrypoint only runs `collectstatic` when `DJANGO_DEBUG == "False"` (string comparison). Without `DJANGO_DEBUG=False` in prod.env, `/home/wger/static` volume stays empty. The React bundle at `/static/node/@wger-project/react-components/build/main.js` returns 404, causing ALL React-rendered pages (weight chart, nutrition plans, etc.) to show blank content.

**Fix**: Add `DJANGO_DEBUG=False` to `config/prod.env`. Also add explicit collectstatic call in `setup_wger.sh` as safety net:
```bash
docker exec wger-web python3 manage.py collectstatic --noinput
```
- `STATICFILES_DIRS = [('node', '/home/wger/src/node_modules')]` — React bundle source inside container
- After collectstatic: 11,450 files copied; React bundle is 2.57MB at HTTP 200

---

## Python Module Structure (CRITICAL)

wger changed significantly from the older version used in training data. All module references MUST use the new paths:

| What | Old (WRONG) | Correct |
|------|------------|---------|
| Routine model | `wger.training.models` | `wger.manager.models` |
| Day model | `wger.training.models` | `wger.manager.models` |
| WorkoutSession | `wger.workoutsession.models` | `wger.manager.models` |
| Measurement category | `wger.measurement.models.MeasurementCategory` | `wger.measurements.models.Category` |
| Measurement entry | `wger.measurement.models.Measurement` | `wger.measurements.models.Measurement` |

Other modules (verified correct):
- `wger.weight.models.WeightEntry` ✓
- `wger.nutrition.models.NutritionPlan` ✓
- `wger.nutrition.models.Meal` ✓
- `wger.core.models.UserProfile` ✓

---

## Routine Model Required Fields

The `Routine` model has two required `DateField`s:
- `start` (date the routine starts)
- `end` (date the routine ends)

These are NOT optional. Any API POST to `/api/v2/routine/` without them returns:
```json
{"start": ["This field is required."], "end": ["This field is required."]}
```

In task_utils.sh `create_routine()`:
```bash
local today end_date result
today=$(date +%Y-%m-%d)
end_date=$(date -d "+6 months" +%Y-%m-%d 2>/dev/null || echo "${today}")
result=$(wger_api POST /api/v2/routine/ \
    "{\"name\": \"${name}\", \"description\": \"${description}\", \"start\": \"${today}\", \"end\": \"${end_date}\"}")
```

---

## WorkoutSession Model Fields

```python
# WorkoutSession is in wger.manager.models (NOT wger.workoutsession)
from wger.manager.models import WorkoutSession

# Fields:
# - user: FK to User
# - routine: FK to Routine (NOT "workout")
# - day: FK to Day (optional)
# - date: DateField
# - notes: TextField
# - impression: CharField ('1'=general, '2'=good, '3'=excellent, '4'=bad)
# - time_start, time_end: TimeField (optional)
```

**Important**: The field linking to a Routine is called `routine` (NOT `workout`). Django filter:
```python
WorkoutSession.objects.filter(user=u, routine=routine, date=today)
```

---

## Measurement Model

```python
from wger.measurements.models import Category, Measurement
# Category has: name, unit, user
# Measurement has: category, date, value
```
Note: NO `notes` field on Measurement, unlike some other versions.

---

## JWT Authentication

- Token endpoint: `POST /api/v2/token` (NO trailing slash — `/api/v2/token/` returns 404)
- Request body: `{"username": "admin", "password": "adminadmin"}`
- Returns: `{"access": "...", "refresh": "..."}`
- Use in headers: `Authorization: Bearer <access_token>`
- Token lifetime: short (15 min), but sufficient for task setup scripts

---

## Exercise Sync

`sync-exercises` management command syncs from wger.de:
```bash
docker exec wger-web python3 manage.py sync-exercises
```
This downloads ~414 exercises with categories, muscles, equipment. Requires `net: true` in env.json.

---

## URL Reference

Frontend URLs (accessible after login):
- `/en/dashboard` — Main dashboard
- `/en/routine/overview` — List all routines
- `/en/routine/add` — Create new routine
- `/en/routine/<id>/view` — View/edit specific routine (add training days here)
- `/en/routine/calendar` — Workout calendar (log workout sessions here)
- `/en/routine/<id>/logs` — Workout logs for a routine
- `/en/weight/overview` — Body weight history chart + entry form
- `/en/measurement/` — Measurement categories list
- `/en/measurement/category/<id>` — Specific measurement category with entries
- `/en/nutrition/overview/` — Nutrition plans list
- `/en/nutrition/<id>/view/` — View/edit specific nutrition plan (add meals here)
- `/en/user/preferences` — User preferences (weight unit, etc.)
- `/en/gym/1/add-member` — Add user to gym (admin creates new accounts; has Name/Username/Email/Role fields, NO password)
- `/en/user/registration` — Public registration (but redirects to dashboard if already logged in; NOT useful for admin task setup)

**404 URLs** (don't exist in wger 2.5-dev):
- `/en/user/add` — does not exist
- `/en/user/1/config` — does not exist
- `/en/workoutsession/add/` — does not exist (sessions via calendar UI)

---

## Screenshot Capture

`xwd | convert` pipe breaks in SSH context (pipe disconnects). Use temp file approach:
```bash
xwd -root -silent -out /tmp/raw.xwd 2>/dev/null \
    && convert /tmp/raw.xwd /tmp/screenshot.png 2>/dev/null \
    && rm -f /tmp/raw.xwd \
    || echo "Warning: screenshot failed"
```

This is implemented in `task_utils.sh`'s `take_screenshot()` function.

---

## Seed Data

The `setup_wger.sh` post_start script creates:
- **30 body weight entries**: 87.0kg → 82.65kg over 30 days (WeightEntry)
- **3 workout routines**: Push-Pull-Legs, 5x5 Beginner, Upper-Lower Split (Routine with start/end)
- **2 nutrition plans**: Maintenance Diet, Lean Bulk Plan (NutritionPlan)
- **3 measurement categories**: Body Fat (%), Chest (cm), Waist (cm) with 5 weekly entries each (Category + Measurement)

---

## Firebase/Firefox Notes

- Firefox snap profile: `/home/ga/snap/firefox/common/.mozilla/firefox/wger.profile`
- Firefox has a "Privacy Notice" tab that opens on first run — ignore it (user.js suppresses most first-run dialogs)
- Login is automated during post_start: navigates to `/en/user/login`, types admin/adminadmin

---

## Docker Compose Notes

- `docker exec wger-web python3 manage.py shell -c "..."` — always shows 6 HistoricalExercise model import warnings and "76 objects imported automatically" — these are normal/harmless
- `docker compose pull` downloads ~2GB of images (wger/server:latest ≈ 1.3GB + postgres + redis)
- From `ga` SSH user: use `sudo docker exec` / `sudo docker compose` (docker group permissions depend on config)
- From root (hooks): use `docker exec` / `docker compose` directly

---

## 10 Tasks

1. **create_workout_routine** — Create routine named '5x5 Strength Program'; starts at `/en/routine/overview`
2. **log_body_weight** — Log weight entry of 82.5 kg for today; starts at `/en/weight/overview/`
3. **create_nutrition_plan** — Create plan named 'High Protein Diet'; starts at `/en/nutrition/overview/`
4. **add_measurement_category** — Create 'Neck' category (cm) + 38.5 entry; starts at `/en/measurement/`
5. **add_training_day** — Add 'Chest and Triceps' day to 'Power Training' routine; starts at `/en/routine/<id>/view`
6. **log_workout_session** — Log session with 'Full Body Workout', impression=General, notes='Felt strong today'; starts at `/en/routine/calendar`
7. **add_meal_to_plan** — Add 'Breakfast' meal to 'Muscle Building' plan; starts at `/en/nutrition/<id>/view/`
8. **register_new_user** — Add user 'john_trainee' (john.smith@fitnessgym.com) to Default Gym; starts at `/en/gym/1/add-member` (has First/Last name, Username, Email, Role fields — no password)
9. **change_weight_unit** — Change weight unit from kg to lbs; starts at `/en/user/preferences`
10. **set_nutrition_goal** — Set energy goal 2500 kcal on 'Athlete Diet' plan; starts at `/en/nutrition/<id>/view/`

---

## Known Issues / Limitations

- **Exercise images**: Not synced (sync disabled in prod.env to avoid bandwidth) — exercises have no images
- **Guest users disabled**: `ALLOW_GUEST_USERS=False` — simplifies benchmark (only admin user)
- **Brute force protection disabled**: `AXES_ENABLED=False` — simplifies test login automation
- **Historical models**: wger has simple_history for exercises but can't auto-import 6 historical models — harmless warnings in django shell
