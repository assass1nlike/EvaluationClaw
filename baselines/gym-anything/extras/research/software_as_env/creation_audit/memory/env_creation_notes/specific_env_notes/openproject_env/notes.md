> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenProject Environment Notes

**Verified**: 2026-02-22
**Status**: COMPLETE — 10 tasks created and validated

## Stack
- Docker Compose: `openproject/openproject:15` all-in-one container
  - Bundles PostgreSQL, memcached, Rails, Nginx
  - Internal port 80, mapped to host port 8080
- Ubuntu GNOME VM, snap Firefox

## Admin Credentials
- login: `admin`, password: `Admin1234!`
- Key env var: `OPENPROJECT_SEED_ADMIN_USER_PASSWORD_RESET=false` prevents forced change

## User Credentials
- alice.johnson / User1234!@ (bob.smith, carol.williams same password)
- **NOTE**: OpenProject requires minimum 10 character passwords!

## CRITICAL: API Authentication in OpenProject 15
OpenProject 15.x does NOT support username:password basic auth for APIv3.
Only `apikey:<token>` (personal API token) works via UserBasicAuth warden strategy.

**Create token** (setup_openproject.sh):
```ruby
token = Token::API.new(user: u)
token.save!
puts token.plain_value  # Use this! token.value is SHA256 hash — NOT usable directly
```

**Use in curl**:
```bash
curl -u "apikey:<plain_token>" http://localhost:8080/api/v3/users/me
```

Token stored in `/home/ga/openproject_api_token.txt`.

## CRITICAL: Member Creation
Roles must be assigned BEFORE saving:
```ruby
m = Member.new(project: project, principal: user)
m.member_roles.build(role: developer_role)
m.save!  # Correct!
# WRONG: save then MemberRole.create → "Validation failed: Roles need to be assigned"
```

## CRITICAL: WorkPackage requires priority
```ruby
wp.priority = IssuePriority.find_by(name: 'Normal')  # REQUIRED
```

## Status Names (actual values)
- "New", "In progress" (lowercase 'p'), "Closed" (not "Resolved")
- Full list: check `Status.all.map(&:name)` in container

## Browser Login Coordinates (1920×1080)
- Username center: (1076, 386)
- Password center: (1076, 434)
- Handle '!' with `xdotool key exclam` separately

## Task Start State
Task setups kill Firefox with pkill -9 (no graceful cookie save). Login page with
`back_url` pointing to target is the correct start state — agents log in then get redirected.

## 10 Tasks
1. create_project → /projects/new
2. create_work_package → ecommerce-platform work_packages list
3. add_project_member → devops-automation /members (NOTE: /settings/members returns 404 in OP15 — use /members directly)
4. create_version → mobile-banking-app settings/versions
5. update_work_package_status → WP#48 Kubernetes bug (In progress → Resolved)
6. log_time → WP#42 biometric login (log 3.5h)
7. create_wiki_page → ecommerce-platform wiki
8. add_work_package_comment → WP#38 mobile Safari bug
9. assign_work_package → WP#44 push notification (assign to carol)
10. set_work_package_dates → WP#49 blue-green deployment
