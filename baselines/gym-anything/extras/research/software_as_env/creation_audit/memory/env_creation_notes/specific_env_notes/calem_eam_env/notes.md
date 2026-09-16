> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# CalemEAM Environment Notes

## Architecture
- **Hybrid pattern**: PHP 7.4/Apache native + MySQL 5.7 in Docker
- **Base image**: ubuntu-gnome-systemd_highres (1920x1080)
- **Browser**: Firefox ESR (from mozillateam PPA, not snap)

## Critical Fixes (7 total)

### PHP 7.4 Compatibility (Fixes 1-4, in install script)
1. **CalemPDOStatement::bindValue** - NULL `$data_type` causes queries to silently return 0 rows
2. **CalemPDOStatement::fetch** - NULL cursor params cause fetch to return false
3. **CalemPdo::rollback** - Must check `inTransaction()` before calling `rollback()`
4. **db_stmt_driver_options** - Change from numeric `array(3, 0)` to associative `array(3 => 0)`

### PHP 7.4 Warnings (Fixes 5-7, in install script)
5. **JsPkg.php line 33** - `!js` should be `!$js` (missing dollar sign)
6. **JsPkgCustom.php line 73** - `$parentGroups` can be null, add `is_array()` check
7. **log4php.properties** - Must copy from `log4php.sample.properties`

### ACL Group Cache (in setup script)
- **ROOT CAUSE of blank post-login page**: DirectLoad.php bypasses CalemEAM's ORM, so the ACL group cache is never built
- `CalemCachedGroups` constructor reads `CalemData['acl_group']` from the JS custom package
- If cache is empty, `JsPkgCustom.php` returns `CalemData['acl_group']=false`
- This causes `this._parentMap` to be undefined -> JS crash in `CalemDesktop.launch()`
- **Fix**: Run `build_cache.php` after data loading to populate the ACL group cache

## CalemEAM Login Form JS Behavior
- Enter key on username field moves focus to password field
- Enter key on password field submits the form
- Login button is `type="button"` with `onclick` handler
- Form POSTs to `/CalemEAM/index.php` with `calemAction=LoginAction`

## Database Setup Approach
1. Schema created via `CreateSchemaCmd.php` (CLI, runs from `server/setup/` directory)
2. Data loaded via custom `DirectLoad.php` (uses plain PDO, bypasses broken CalemEAM ORM)
3. ACL group cache built via `build_cache.php`

## Known Issues
- Firefox ESR still shows "Privacy Notice" tab on first launch (suppressed via user.js prefs but some versions ignore them)
- CalemEAM has `SyntaxError: invalid escape sequence` warnings from legacy JS code (non-fatal, doesn't affect rendering)
